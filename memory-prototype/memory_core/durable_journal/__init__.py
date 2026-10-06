"""Technology-neutral Durable Journal and Rebuild Contract (executable form). TEST/PROTOTYPE ONLY.

The contract is stated in ``investigation/durable-journal-rebuild-contract-v1.md``. This module provides:
- ``DurableJournal``: the abstract interface with the contract's append rules, shared by every implementation;
- ``GlobalJournal``: implementation A, the prototype's single in-memory journal (one global order);
- ``PartitionedJournal``: implementation B, a simulator that challenges the contract. It has independent
  per-subject partitions, a separate policy log, no global sequence, out-of-order cross-partition delivery,
  duplicate delivery, crash/restart, sealed content and key destruction. It also has switches that deliberately
  WEAKEN single rules, for the break tests;
- ``reconstruct``: rebuild from durable facts only. It never calls the gate, never reads a live store, and
  evaluates each point under the policy in force at that point.

**The ordering model** (the minimum proven sufficient; see the contract §B):
- O1: each partition (subject) has a total order of its own entries, with non-decreasing commit times;
- O2: policy publications form an ordered log per predicate (versions), each with a commit time T;
- O3 (causality): every entry carries the version of its predicate in force at its commit time, where "in
  force at t" means the latest publication with T < t. At equal time, entries precede publications;
- O4 (visibility): a publication with time T is visible to every append and every read with time > T.

No order between different subjects' entries is required.
"""
import copy
from dataclasses import dataclass, field, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..commit import JournalEntry
from ..config import AMENDED, Decisions
from ..registry import PredicatePolicy
from ..state import CurrentState, project_subject

KINDS = ("claim", "retraction", "lifecycle", "sync", "erasure", "commit_intent", "commit_outcome",
         "commitment_event", "episode_summary")                  # Amendment A1: additive, not claim-projected
SEALED_KINDS = ("claim", "retraction", "commit_intent", "commitment_event", "episode_summary")
PROJECTED_KINDS = ("claim", "retraction", "lifecycle", "sync")   # what the projection consumes


class AppendRejected(Exception):
    pass


class Crash(Exception):
    """Injected process crash."""


@dataclass(frozen=True)
class Sealed:
    """A reference to content readable only while the key ``key_id`` exists (crypto-shred). The mechanism is
    custody-neutral (C-1 open): the contract only requires that destroying the key makes the content
    unrecoverable."""
    key_id: str
    ref: str


@dataclass(frozen=True)
class Entry:
    partition: str                 # owning subject
    kind: str
    idem: str                      # idempotency identity, unique within the partition
    at: float                      # commit (knowledge) time
    predicate: Optional[str]       # the slot predicate the entry concerns (None for erasure and ledger kinds)
    policy_version: Optional[int]  # O3 stamp: version of ``predicate`` in force at ``at``
    payload: object                # Sealed for SEALED_KINDS


@dataclass(frozen=True)
class Stored:
    entry: Entry
    pos: int                       # position within its partition (partitions) or global (implementation A)


@dataclass(frozen=True)
class Publication:
    predicate: str
    version: int
    at: float


@dataclass(frozen=True)
class DurableFacts:
    """Everything a rebuild may consume. Nothing else."""
    partitions: Mapping[str, Tuple[Stored, ...]]
    publications: Tuple[Publication, ...]
    vault: Mapping[Tuple[str, str], object]        # sealed content still readable (destroyed keys removed)
    policy_history: Mapping[str, Mapping[int, PredicatePolicy]]


def in_force(pubs: Sequence[Publication], predicate: str, t: float) -> Optional[int]:
    """O3: the latest version of ``predicate`` published strictly before ``t``."""
    vs = [p.version for p in pubs if p.predicate == predicate and p.at < t]
    return max(vs) if vs else None


# --------------------------------------------------------------------------- the interface + shared append rules
class DurableJournal:
    """Contract rules every implementation enforces (G1, G3, G4, O1, O3, erasure seal)."""

    def __init__(self, policy_history: Mapping[str, Mapping[int, PredicatePolicy]], *, stamp_check: bool = True,
                 idempotent: bool = True, atomic: bool = True, seal_after_erasure: bool = True,
                 monotone_time: bool = True):
        self.policy_history = policy_history
        self.stamp_check, self.idempotent, self.atomic = stamp_check, idempotent, atomic
        self.seal_after_erasure = seal_after_erasure
        self.monotone_time = monotone_time
        self.vault: Dict[Tuple[str, str], object] = {}
        self.destroyed: set = set()

    # implementation hooks -----------------------------------------------------
    def _durable(self, partition: str) -> List[Stored]: raise NotImplementedError
    def _publications(self) -> List[Publication]: raise NotImplementedError
    def _write(self, partition: str, entries: Sequence[Entry], crash_after: Optional[int]) -> None: raise NotImplementedError
    def _write_publication(self, pub: Publication) -> None: raise NotImplementedError
    def partitions(self) -> List[str]: raise NotImplementedError
    def crash(self) -> None: raise NotImplementedError

    # contract operations ------------------------------------------------------
    def seal(self, key_id: str, ref: str, content: object) -> Sealed:
        if key_id in self.destroyed:
            raise AppendRejected("key_destroyed")
        self.vault[(key_id, ref)] = content
        return Sealed(key_id, ref)

    def destroy_key(self, key_id: str) -> None:
        """Crypto-shred: every sealed payload under this key becomes unrecoverable, everywhere."""
        self.destroyed.add(key_id)
        for k in [k for k in self.vault if k[0] == key_id]:
            del self.vault[k]

    def publish(self, pub: Publication) -> str:
        pubs = self._publications()
        if any(p.predicate == pub.predicate and p.version == pub.version for p in pubs):
            return "DUPLICATE"
        mine = [p for p in pubs if p.predicate == pub.predicate]
        if mine and (pub.version <= max(p.version for p in mine) or pub.at < max(p.at for p in mine)):
            raise AppendRejected("publication_out_of_order")
        self._write_publication(pub)
        return "APPENDED"

    def append(self, entries: Sequence[Entry], crash_after: Optional[int] = None) -> str:
        """Append a group of entries to ONE partition, all or nothing (G4). Idempotent per entry ``idem``."""
        if not entries or len({e.partition for e in entries}) != 1:
            raise AppendRejected("group_must_target_one_partition")
        part = entries[0].partition
        stored = self._durable(part)
        have = {s.entry.idem: s.entry for s in stored}
        fresh = []
        for e in entries:
            if e.kind not in KINDS:
                raise AppendRejected("unknown_kind")
            if self.idempotent and e.idem in have:
                if have[e.idem] != e:
                    raise AppendRejected("idem_reused_with_different_content")
                continue
            fresh.append(e)
        if not fresh:
            return "DUPLICATE"
        if self.seal_after_erasure and any(s.entry.kind == "erasure" for s in stored):
            raise AppendRejected("partition_erased")                 # fence: an erased subject is sealed
        last_at = stored[-1].entry.at if stored else float("-inf")
        pubs = self._publications()
        for e in fresh:
            if self.monotone_time and e.at < last_at:
                raise AppendRejected("commit_time_regressed")        # O1
            last_at = e.at
            if self.stamp_check and e.predicate is not None and e.policy_version != in_force(pubs, e.predicate,
                                                                                               e.at):
                raise AppendRejected("stale_policy_stamp")           # O3
        self._write(part, fresh, crash_after)
        return "APPENDED"

    def facts(self) -> DurableFacts:
        return DurableFacts({p: tuple(self._durable(p)) for p in self.partitions()}, tuple(self._publications()),
                            dict(self.vault), self.policy_history)


# --------------------------------------------------------------------------- implementation A: one global journal
class GlobalJournal(DurableJournal):
    """Today's prototype layout: a single list with one global sequence."""

    def __init__(self, policy_history, **kw):
        super().__init__(policy_history, **kw)
        self.log: List[object] = []           # Stored entries and Publications in one global order

    def _durable(self, partition):
        return [x for x in self.log if isinstance(x, Stored) and x.entry.partition == partition]

    def _publications(self):
        return [x for x in self.log if isinstance(x, Publication)]

    def partitions(self):
        return sorted({x.entry.partition for x in self.log if isinstance(x, Stored)})

    def _write(self, partition, entries, crash_after):
        staged = [Stored(e, len(self.log) + i) for i, e in enumerate(entries)]
        if crash_after is not None and not self.atomic:
            self.log.extend(staged[:crash_after])
            raise Crash()
        if crash_after is not None:
            raise Crash()                                              # atomic: nothing becomes durable
        self.log.extend(staged)

    def _write_publication(self, pub):
        self.log.append(pub)

    def crash(self):
        pass                                                           # everything written is durable


# --------------------------------------------------------------------------- implementation B: partitioned simulator
class PartitionedJournal(DurableJournal):
    """Independent partitions (no global sequence) and a separate policy log. Writes go through a non-durable
    staging area that a crash discards. Cross-partition delivery order is chosen by the test driver."""

    def __init__(self, policy_history, **kw):
        super().__init__(policy_history, **kw)
        self.parts: Dict[str, List[Stored]] = {}
        self.pubs: List[Publication] = []
        self.staging: List[Tuple[str, Entry]] = []                     # written but not yet durable

    def _durable(self, partition):
        return list(self.parts.get(partition, []))

    def _publications(self):
        return list(self.pubs)

    def partitions(self):
        return sorted(self.parts)

    def _write(self, partition, entries, crash_after):
        self.staging = [(partition, e) for e in entries]
        if crash_after is not None:
            if not self.atomic:                                        # weakened: a prefix leaks into durability
                self._flush(self.staging[:crash_after])
            self.staging = []
            raise Crash()
        self._flush(self.staging)
        self.staging = []

    def _flush(self, staged):
        for part, e in staged:
            lst = self.parts.setdefault(part, [])
            lst.append(Stored(e, len(lst)))

    def _write_publication(self, pub):
        self.pubs.append(pub)

    def crash(self):
        self.staging = []


# --------------------------------------------------------------------------- rebuild from durable facts only
@dataclass(frozen=True)
class Reconstructed:
    subject: str
    erased: bool
    state: Optional[CurrentState]
    trace: Mapping[str, Tuple[tuple, ...]] = field(default_factory=dict)
    journal: Tuple[JournalEntry, ...] = ()           # the rebuilt journal view (for retrieval over the rebuild)
    policies: Mapping[str, PredicatePolicy] = field(default_factory=dict)


def _unseal(facts: DurableFacts, x):
    if isinstance(x, Sealed):
        return facts.vault.get((x.key_id, x.ref))                     # None: destroyed (crypto-shredded)
    return x


def reconstruct(facts: DurableFacts, subject: str, r: float, d: Decisions = AMENDED, *,
                placement: str = "time", historical_policy: bool = True) -> Reconstructed:
    """Rebuild one subject's state at read time ``r`` from durable facts only.

    ``placement`` / ``historical_policy`` exist only so the break tests can weaken a rule. The contract values
    are "time" and True."""
    stored = [s for s in facts.partitions.get(subject, ()) if s.entry.at <= r]
    if any(s.entry.kind == "erasure" for s in stored):
        return Reconstructed(subject, True, None)
    pubs = [p for p in facts.publications if p.at <= r]      # a read at r sees publications at r (after entries)
    items = evaluation_order(facts, subject, r, placement)
    return _rebuild(facts, subject, r, d, items, pubs, historical_policy)


def evaluation_order(facts: DurableFacts, subject: str, r: float, placement: str = "time") -> List[tuple]:
    """The evaluation points of one subject at read time ``r``: its own entries, plus every visible publication,
    ordered by (time, entries-before-publications, position). No other subject's entries take part."""
    stored = [s for s in facts.partitions.get(subject, ()) if s.entry.at <= r]
    pubs = [p for p in facts.publications if p.at <= r]
    items = []
    for s in stored:
        if s.entry.kind in PROJECTED_KINDS:
            items.append((s.entry.at, 0, s.pos, s.entry))             # O3: entries precede publications at equal t
    if placement == "time":
        items += [(p.at, 1, i, p) for i, p in enumerate(pubs)]
    else:                                                              # WEAKENED: adopt at the next own entry
        for i, p in enumerate(pubs):
            nxt = [s for s in stored if s.entry.predicate == p.predicate and (s.entry.policy_version or 0) >= p.version]
            at = nxt[0].entry.at if nxt else r
            items.append((at, -1, i, p))
    items.sort(key=lambda x: (x[0], x[1], x[2]))
    return items


def _rebuild(facts, subject, r, d, items, pubs, historical_policy) -> "Reconstructed":
    claims_j, rest_j, live_claims = [], [], set()
    for idx, (placed_at, _, _, x) in enumerate(items):
        if isinstance(x, Publication):           # evaluated where it is PLACED (== its own time under the contract)
            rest_j.append(JournalEntry(idx, "policy", placed_at, (x.predicate, x.version)))
            continue
        payload = _unseal(facts, x.payload)
        if payload is None:
            continue                                                   # unreadable: contributes nothing
        if x.kind == "claim":
            live_claims.add(payload.claim_id)
            claims_j.append(JournalEntry(idx, "claim", x.at, payload))
        elif x.kind == "lifecycle":
            if payload[0] in live_claims:
                rest_j.append(JournalEntry(idx, "lifecycle", x.at, payload))
        else:
            rest_j.append(JournalEntry(idx, x.kind, x.at, payload))
    history = facts.policy_history
    current = {}
    for pred, versions in history.items():
        vis = [p.version for p in pubs if p.predicate == pred]
        if vis:
            current[pred] = versions[max(vis)]
    trace: Dict[str, List[tuple]] = {}
    st = project_subject(claims_j, rest_j, current, r, r, subject=subject, d=d, incremental=False,
                         policy_history=history if historical_policy else None, trace=trace)
    return Reconstructed(subject, False, st, {k: tuple(v) for k, v in trace.items()},
                         tuple(sorted(claims_j + rest_j, key=lambda x: x.seq)), current)


# --------------------------------------------------------------------------- exporting a pipeline's history
def export_pipeline(p) -> Tuple[List[Entry], List[Publication]]:
    """Turn an integration Pipeline's recorded history into contract entries (partition, stamp, sealing).
    Claim/retraction/ledger content is sealed under the owning subject's key id. Returns per-partition-ordered
    entries in the pipeline's own order, plus the publication log."""
    j = p.store.journal
    pubs = [Publication(e.payload[0], e.payload[1], e.at) for e in j if e.kind == "policy"]
    owner = {}
    out: List[Tuple[Entry, Optional[Tuple[str, str, object]]]] = []
    for e in sorted(j, key=lambda x: x.seq):
        if e.kind == "policy":
            continue
        if e.kind == "claim":
            rec = e.payload
            subj, pred = rec.claim_content.subject_id, rec.claim_content.key.split("[", 1)[0]
            owner[rec.claim_id] = (subj, pred)
            out.append((Entry(subj, "claim", "claim:" + rec.claim_id, e.at, pred, rec.claim_content.policy_version,
                              None), (subj, "c:" + rec.claim_id, rec)))
        elif e.kind == "retraction":
            r = e.payload
            pred = r.key.split("[", 1)[0]
            out.append((Entry(r.subject_id, "retraction", "retraction:" + r.retraction_id, e.at, pred,
                              in_force(pubs, pred, e.at), None), (r.subject_id, "r:" + r.retraction_id, r)))
        elif e.kind == "lifecycle":
            cid, t = e.payload
            subj, pred = owner[cid]
            out.append((Entry(subj, "lifecycle", f"lifecycle:{cid}:{t.at}:{t.to}", e.at, pred,
                              in_force(pubs, pred, e.at), (cid, t)), None))
        elif e.kind == "sync":
            s = e.payload
            out.append((Entry(s.subject_id, "sync", "sync:" + s.sync_id, e.at, s.predicate,
                              in_force(pubs, s.predicate, e.at), s), None))
    return out, pubs


def load(journal: DurableJournal, exported, pubs: Sequence[Publication], order: Optional[Sequence[int]] = None):
    """Deliver an exported history into a journal. ``order`` may interleave PARTITIONS arbitrarily (the contract
    permits any cross-partition order). Each partition's own order is preserved, and every publication is made
    visible before any entry whose commit time is later than it (O4)."""
    for pub in sorted(pubs, key=lambda x: x.at):
        journal.publish(pub)
    idx = list(range(len(exported))) if order is None else list(order)
    for i in idx:
        e, seal = exported[i]
        if seal is not None:
            subj, ref, content = seal
            e = replace(e, payload=journal.seal("key:" + subj, ref, content))
        journal.append([e])


def interleave(exported, rng) -> List[int]:
    """A random cross-partition delivery order that keeps each partition's own order (no global order)."""
    queues: Dict[str, List[int]] = {}
    for i, (e, _) in enumerate(exported):
        queues.setdefault(e.partition, []).append(i)
    order = []
    while any(queues.values()):
        part = rng.choice(sorted(k for k, v in queues.items() if v))
        order.append(queues[part].pop(0))
    return order


def erase_person(journal: DurableJournal, cluster: Sequence[str], at: float, crash_after_partitions: int = None):
    """Erase a person: an erasure entry in EVERY partition of the merge cluster, then destroy each key. Complete
    only when every partition is done (completion barrier); a crash leaves it in progress and a retry finishes it.
    No cross-partition atomicity is required."""
    for i, subj in enumerate(sorted(cluster)):
        if crash_after_partitions is not None and i == crash_after_partitions:
            raise Crash()
        journal.append([Entry(subj, "erasure", "erasure:" + ",".join(sorted(cluster)), at, None, None,
                              ("cluster", tuple(sorted(cluster))))])
        journal.destroy_key("key:" + subj)
    return "COMPLETE"


# --------------------------------------------------------------------------- G3: cross-partition commit protocol
def protocol_commit(journal: DurableJournal, *, proposal_subject: str, proposal_id: str, target: str,
                    claim_id: str, record, at: float, predicate: str, stamp: int, use_intent: bool = True,
                    crash_after_step: Optional[int] = None) -> str:
    """Exactly one logical commit per proposal, without cross-partition atomicity.

    1. INTENT (proposal_id -> target, claim_id) in the PROPOSAL subject's partition (where idempotency lives);
    2. the CLAIM in the TARGET partition (idempotent on the deterministic claim id);
    3. the OUTCOME in the proposal subject's partition.

    A retry re-reads the intent, so a later change of merge target cannot produce a second claim.
    ``use_intent=False`` deliberately weakens step 1 (break test)."""
    intent_idem = "intent:" + proposal_id
    if use_intent:
        prior = next((s.entry for s in journal.facts().partitions.get(proposal_subject, ())
                      if s.entry.idem == intent_idem), None)
        if prior is not None:
            target, claim_id = _unseal(journal.facts(), prior.payload)
        else:
            journal.append([Entry(proposal_subject, "commit_intent", intent_idem, at, None, None,
                                  journal.seal("key:" + proposal_subject, intent_idem, (target, claim_id)))])
    if crash_after_step == 1:
        raise Crash()
    journal.append([Entry(target, "claim", "claim:" + claim_id, at, predicate, stamp,
                          journal.seal("key:" + target, "c:" + claim_id, record))])
    if crash_after_step == 2:
        raise Crash()
    journal.append([Entry(proposal_subject, "commit_outcome", "outcome:" + proposal_id, at, None, None,
                          ("COMMITTED", claim_id))])
    return "COMMITTED"
