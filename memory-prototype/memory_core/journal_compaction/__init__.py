"""Durable Journal compaction and checkpoints, v1 (``investigation/durable-journal-compaction-contract-v1.md``).
TEST/PROTOTYPE ONLY.

A checkpoint is an ACCELERATION STRUCTURE, never a second source of truth:
- it holds the exact state of ONE partition's rebuild fold after every evaluation point at or before a closed
  position ``c``: claims, carried retractions (LA-9), pending validity boundaries, versions and last signatures, the
  version in force per predicate, the version trace, max sync per predicate, the claims version, commitment events,
  the latest episode generations, and the erased flag;
- it is never a journal entry (no commit time, no idem), and ``reconstruct`` never reads it;
- its payload is sealed under the subject key, the same crypto-shred domain as the facts it was derived from;
- it is used only after validation. Any failure falls back to a full replay and marks the checkpoint unusable.

``rebuild(facts, subject, r, checkpoints)`` = checkpoint(c) + the durable suffix (c, r]. It equals a full replay at r.
v1 deletes NO fact: "compaction" only retires superseded checkpoints. Truncating the prefix would make a checkpoint
the only record of it (a new authority) and needs owner decisions (contract §7).

The fold mirrors ``durable_journal.reconstruct`` -> ``state.project_subject`` -> ``state.slot_versions`` on the
REBUILD path (``incremental=False``: every slot at every point). The conformance suite proves the equivalence.
"""
import copy
import hashlib
import heapq
import pickle
import secrets
from dataclasses import dataclass, field, fields, replace
from typing import Dict, List, Optional, Tuple

from ..commit import SUPERSEDED_BY_POLICY, JournalEntry, rebuild_claims
from ..config import AMENDED, Decisions
from ..durable_journal import (PROJECTED_KINDS, AppendRejected, DurableFacts, Publication, Reconstructed, _unseal,
                               reconstruct)
from ..episode_commitment import COMMITMENT_EVENT, EPISODE_SUMMARY, commitment_events_at, generations_at
from ..model import Claim, ClaimState
from ..registry import requires_revalidation
from ..state import (CurrentState, _replay, _resolve, _signature, _slot, _subject_claims, base_predicate,
                     operational)
from ..temporal import status_at

CONTRACT = "journal-compaction-v1"
NEG = float("-inf")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ============================================================================================ the rebuild fold
@dataclass
class Fold:
    subject: str
    at: float = NEG                                   # covered position c
    position: int = 0                                 # partition entries consumed (all kinds): a prefix
    claims: Dict = field(default_factory=dict)
    retractions: List = field(default_factory=list)   # LA-9: they also end claims committed later
    versions: Dict[str, int] = field(default_factory=dict)
    last: Dict[str, tuple] = field(default_factory=dict)
    in_force: Dict[str, int] = field(default_factory=dict)
    pending: List[tuple] = field(default_factory=list)   # heap of future validity boundaries (instant, tie, pred)
    tie: int = 0
    trace: Dict[str, List[tuple]] = field(default_factory=dict)
    sync: Dict[str, float] = field(default_factory=dict)  # predicate -> max synced_at (this subject)
    cv: int = 0                                       # claims_version
    erased: bool = False
    unsafe: Optional[str] = None                      # the fold consulted read-time policy content
    events: List = field(default_factory=list)        # commitment events (the projection is a set function)
    generations: Dict = field(default_factory=dict)   # latest episode generation per episode id
    predicates: Tuple[str, ...] = ()                  # v1.2: entry predicates (metadata) of every covered entry,
    #                                                   sorted (canonical, so equal folds serialize identically)
    # Pruning v1: where each payload-carrying object came from in the durable facts (vault key id, ref). Lets the
    # compact encoding store a reference to the sealed fact instead of a copy of it.
    claim_refs: Dict = field(default_factory=dict)    # claim id -> (key id, ref) of its claim entry
    retraction_refs: List = field(default_factory=list)   # parallel to ``retractions``
    event_refs: List = field(default_factory=list)        # parallel to ``events``
    generation_refs: Dict = field(default_factory=dict)   # episode id -> (key id, ref) of its latest generation


def _current(facts: DurableFacts, r: float) -> Dict:
    """The policies visible at r (as ``reconstruct`` computes them)."""
    pubs = [p for p in facts.publications if p.at <= r]
    out = {}
    for pred, versions in facts.policy_history.items():
        vis = [p.version for p in pubs if p.predicate == pred]
        if vis:
            out[pred] = versions[max(vis)]
    return out


def _points(facts: DurableFacts, subject: str, lo: float, hi: float, start: int) -> List[tuple]:
    """Evaluation points in (lo, hi]: claim-projected partition entries from position ``start`` (the suffix only),
    plus publications, ordered exactly as ``durable_journal.evaluation_order``."""
    items = [(s.entry.at, 0, s.pos, s.entry) for s in facts.partitions.get(subject, ())[start:]
             if s.entry.at <= hi and s.entry.kind in PROJECTED_KINDS]
    pubs = [p for p in facts.publications if p.at <= hi]
    items += [(p.at, 1, i, p) for i, p in enumerate(pubs) if p.at > lo]
    items.sort(key=lambda x: (x[0], x[1], x[2]))
    return items


def _evaluate(f: Fold, t: float, policies, history, d: Decisions):
    preds = {base_predicate(c.content.key) for c in f.claims.values()}
    mine = _subject_claims(f.claims, f.subject)
    for pred in sorted(preds & set(policies)):
        p = policies[pred]
        if history and pred in f.in_force:
            p = history[pred][f.in_force[pred]]
        elif f.unsafe is None:
            f.unsafe = "read_time_policy:" + pred
        if not p.current_state_eligible:
            continue
        empty = _signature(p, [], t, d)
        for slot_key, sig in _signature(p, operational(mine, p, t), t, d).items():
            if slot_key not in f.last and sig == empty[slot_key]:
                continue
            if f.last.get(slot_key) != sig:
                f.last[slot_key] = sig
                f.versions[slot_key] = f.versions.get(slot_key, 0) + 1
                f.trace.setdefault(slot_key, []).append((f.versions[slot_key], sig))


def _drain(f: Fold, upto: float, policies, history, d):
    while f.pending and f.pending[0][0] <= upto:
        b = f.pending[0][0]
        while f.pending and f.pending[0][0] == b:
            heapq.heappop(f.pending)
        _evaluate(f, b, policies, history, d)


def _step(f: Fold, facts: DurableFacts, item: tuple, policies, history, d):
    at, _, _, x = item
    if isinstance(x, Publication):
        e = JournalEntry(0, "policy", at, (x.predicate, x.version))
    else:
        payload = _unseal(facts, x.payload)
        if payload is None:
            return                                   # unreadable (crypto-shredded): contributes nothing
        if x.kind == "lifecycle" and payload[0] not in f.claims:
            return
        e = JournalEntry(0, x.kind, x.at, payload)
    _drain(f, e.at, policies, history, d)            # boundaries at or before this point come first
    _replay([e], f.claims, f.retractions)
    if e.kind == "claim":
        f.claim_refs[e.payload.claim_content.claim_id] = (x.payload.key_id, x.payload.ref)
    elif e.kind == "retraction":
        f.retraction_refs.append((x.payload.key_id, x.payload.ref))
    if e.kind == "policy":
        f.in_force[e.payload[0]] = e.payload[1]
    elif e.kind == "claim":
        c = e.payload.claim_content
        for b in (c.valid_from, c.valid_until):
            if b is not None and b > e.at:
                f.tie += 1
                heapq.heappush(f.pending, (b, f.tie, base_predicate(c.key)))
        if c.subject_id == f.subject:
            f.cv += 1
    elif e.kind == "sync" and e.payload.subject_id == f.subject:
        f.sync[e.payload.predicate] = max(f.sync.get(e.payload.predicate, NEG), e.payload.synced_at)
    _evaluate(f, e.at, policies, history, d)


def _advance(f: Fold, facts: DurableFacts, hi: float, d: Decisions) -> Fold:
    """Fold the durable suffix (f.at, hi] into ``f`` (in place) and return it."""
    part = facts.partitions.get(f.subject, ())
    suffix = [s for s in part[f.position:] if s.entry.at <= hi]
    preds = tuple(sorted(set(f.predicates) | {s.entry.predicate for s in suffix if s.entry.predicate}))
    if f.erased or any(s.entry.kind == "erasure" for s in suffix):
        return Fold(f.subject, hi, f.position + len(suffix), erased=True, predicates=preds)
    policies, history = _current(facts, hi), facts.policy_history
    for item in _points(facts, f.subject, f.at, hi, f.position):
        _step(f, facts, item, policies, history, d)
    _drain(f, hi, policies, history, d)
    for s in suffix:
        x = _unseal(facts, s.entry.payload) if s.entry.kind in (COMMITMENT_EVENT, EPISODE_SUMMARY) else None
        if x is not None and s.entry.kind == COMMITMENT_EVENT:
            f.events.append(x)
            f.event_refs.append((s.entry.payload.key_id, s.entry.payload.ref))
        elif x is not None:
            f.generations[x.episode_id] = x
            f.generation_refs[x.episode_id] = (s.entry.payload.key_id, s.entry.payload.ref)
    f.at, f.position, f.predicates = hi, f.position + len(suffix), preds
    return f


def _finalize(f: Fold, facts: DurableFacts, r: float, d: Decisions) -> Reconstructed:
    """``project_subject``'s final resolution at as_of = now = r, from the folded state."""
    if f.erased:
        return Reconstructed(f.subject, True, None)
    policies = _current(facts, r)
    mine = _subject_claims(f.claims, f.subject)
    slots, unprojected, reval = [], [], []
    for pred in sorted({base_predicate(c.content.key) for c in mine}):
        p = policies.get(pred)
        if p is None:
            unprojected.append(pred)
            continue
        reval.extend(c.id for c in mine if base_predicate(c.content.key) == pred
                     and requires_revalidation(p, c.content.policy_version)
                     and status_at(c, r)[0] != SUPERSEDED_BY_POLICY)
        if not p.current_state_eligible:
            continue
        res = _resolve(p, operational(mine, p, r), r, r, d, f.sync.get(pred))
        slots.append((pred, _slot(f.subject, pred, p, res, f.versions)))
    st = CurrentState(f.subject, r, r, f.cv, tuple(slots), tuple(unprojected), tuple(sorted(reval)))
    return Reconstructed(f.subject, False, st, {k: tuple(v) for k, v in f.trace.items()}, (), policies)


# ============================================================================================ results
@dataclass(frozen=True)
class Rebuilt:
    """What a rebuild at r yields for current-state purposes. The journal VIEW (history) is not part of it: history
    reads always replay the retained facts (contract §7)."""
    subject: str
    r: float
    erased: bool
    state: Optional[CurrentState]
    trace: Dict
    policies: Dict
    claims: Dict
    commitment_events: Tuple
    generations: Dict
    source: str = "full"                              # "full" | "checkpoint" (diagnostic only)

    def view(self):
        return (self.subject, self.r, self.erased, self.state, self.trace, self.policies, self.claims,
                self.commitment_events, self.generations)


def full_replay(facts: DurableFacts, subject: str, r: float, d: Decisions = AMENDED) -> Rebuilt:
    """The reference: the unchanged ``reconstruct`` plus the unchanged A1 reads."""
    rb = reconstruct(facts, subject, r, d)
    if rb.erased:
        return Rebuilt(subject, r, True, None, {}, {}, {}, (), {})
    return Rebuilt(subject, r, False, rb.state, dict(rb.trace), dict(rb.policies), rebuild_claims(rb.journal),
                   commitment_events_at(facts, subject, r), generations_at(facts, subject, r))


def _result(f: Fold, facts: DurableFacts, r: float, d: Decisions, source: str) -> Rebuilt:
    rb = _finalize(f, facts, r, d)
    if rb.erased:
        return Rebuilt(f.subject, r, True, None, {}, {}, {}, (), {}, source)
    return Rebuilt(f.subject, r, False, rb.state, dict(rb.trace), dict(rb.policies), f.claims, tuple(f.events),
                   dict(f.generations), source)


# ============================================================================================ checkpoints
@dataclass(frozen=True)
class Checkpoint:
    partition: str
    covered_at: float                     # c: a closed position; the fold covers every point at or before it
    covered_count: int                    # n: the partition entries (all kinds) with at <= c, a prefix
    tail: Optional[Tuple[str, float]]     # (idem, at) of entry n-1: anchors the covered prefix
    policy_position: Tuple[int, str]      # publications with T <= c: count and digest (the policy context)
    contract: str                         # schema / contract version
    state_signature: str                  # canonical digest of the derived state (identity)
    blob_digest: str                      # integrity of the sealed payload
    created_at: float                     # creation metadata (the creator's reading)
    ref: str                              # sealed payload reference (key: the partition's subject key)
    encoding: str = "full"                # payload encoding: "full" (a copy of the fold) or "ref" (pruning v1)


# ============================================================================================ payload encodings
ENCODINGS = ("full", "ref")


def load(cp, facts: DurableFacts):
    """Decode a validated checkpoint's payload by its own encoding: (fold, None) or (None, reason)."""
    try:
        return decode(facts.vault[("key:" + cp.partition, cp.ref)], cp.encoding, facts), None
    except Unreadable:
        return None, "unreadable_reference"


class Unreadable(Exception):
    """A compact payload refers to a sealed fact that cannot be read: the checkpoint is unusable."""


def _deref(facts: DurableFacts, ref):
    x = facts.vault.get(tuple(ref))
    if x is None:
        raise Unreadable(ref)                        # never skipped: a partial fold would silently diverge
    return x


_STATE = fields(ClaimState)


def encode(f: Fold, encoding: str) -> bytes:
    """``full``: the fold itself. ``ref`` (pruning v1, lossless): every object that is a copy of a sealed journal
    fact (claim content, retraction records, commitment events, episode generations) is replaced by its vault
    reference; ``versions`` and ``last`` are dropped because they are derivable from the trace."""
    if encoding == "full":
        return pickle.dumps(f)
    ok = (list(f.versions) == list(f.last) == list(f.trace)          # the derivation invariant, per slot
          and all(v == len(f.trace[k]) and f.last[k] == f.trace[k][-1][1] for k, v in f.versions.items())
          and len(f.retraction_refs) == len(f.retractions) and len(f.event_refs) == len(f.events)
          and set(f.claim_refs) >= set(f.claims) and set(f.generation_refs) >= set(f.generations))
    if not ok:
        raise ValueError("compact_encoding_invariant")   # refuse rather than derive wrongly
    core = replace(f, claims={}, retractions=[], events=[], generations={}, versions={}, last={}, claim_refs={},
                   retraction_refs=[], event_refs=[], generation_refs={})
    keys: List[str] = []

    def short(ref):                                  # (key id, ref) -> (index into a shared key-id table, ref)
        if ref[0] not in keys:
            keys.append(ref[0])
        return keys.index(ref[0]), ref[1]
    return pickle.dumps({"fold": core,
                         # the claim id is not stored: it is the referenced content's claim_id (the map key)
                         "claims": [(short(f.claim_refs[cid]), tuple(getattr(c.state, x.name) for x in _STATE))
                                    for cid, c in f.claims.items()],
                         "retractions": [short(r) for r in f.retraction_refs],
                         "events": [short(r) for r in f.event_refs],
                         "generations": [short(f.generation_refs[k]) for k in f.generations],
                         "keys": keys})


def decode(blob: bytes, encoding: str, facts: DurableFacts) -> Fold:
    if encoding == "full":
        return pickle.loads(blob)
    d = pickle.loads(blob)
    f = d["fold"]

    def full(r):
        return d["keys"][r[0]], r[1]
    f.claims, f.claim_refs = {}, {}
    for r, state in d["claims"]:
        content = _deref(facts, full(r)).claim_content
        f.claims[content.claim_id] = Claim(content, ClaimState(*state))
        f.claim_refs[content.claim_id] = full(r)
    f.retraction_refs = [full(r) for r in d["retractions"]]
    f.retractions = [_deref(facts, r) for r in f.retraction_refs]
    f.event_refs = [full(r) for r in d["events"]]
    f.events = [_deref(facts, r) for r in f.event_refs]
    f.generations, f.generation_refs = {}, {}
    for r in d["generations"]:
        g = _deref(facts, full(r))
        f.generations[g.episode_id], f.generation_refs[g.episode_id] = g, full(r)
    f.versions = {k: len(v) for k, v in f.trace.items()}
    f.last = {k: v[-1][1] for k, v in f.trace.items()}
    return f


def policy_position(facts: DurableFacts, c: float) -> Tuple[int, str]:
    pubs = sorted((p.predicate, p.version, p.at) for p in facts.publications if p.at <= c)
    return len(pubs), _sha(repr(pubs).encode())


def state_signature(f: Fold) -> str:
    """Canonical (not pickle-dependent): the same facts and c give the same signature."""
    canon = (f.subject, f.at, f.position, f.erased, f.cv, sorted(f.versions.items()), sorted(f.last.items()),
             sorted(f.in_force.items()), sorted(f.pending), sorted(f.sync.items()),
             sorted((k, tuple(v)) for k, v in f.trace.items()), sorted((k, repr(c)) for k, c in f.claims.items()),
             repr(f.retractions), repr(f.events), sorted((k, repr(g)) for k, g in f.generations.items()),
             sorted(f.predicates))
    return _sha(repr(canon).encode())


class CheckpointStore:
    """Derived acceleration state. Losing any or all of it changes no result. Payloads are sealed under the subject
    key (so crypto-shred covers them); this index holds no personal content."""

    def __init__(self, storage, encoding: str = "full"):
        self.storage = storage
        self.encoding = encoding                     # payload encoding of the checkpoints it CREATES
        self.index: Dict[str, List[Checkpoint]] = {}
        self.unusable: set = set()
        self.rejections: List[Tuple[str, str]] = []

    # Publication protocol (maintenance v1): stage -> verify -> publish. Only ``publish`` (one index append, the
    # atomic publication step) makes a checkpoint selectable; a staged payload is invisible until then.
    def stage(self, cp: Checkpoint, blob: bytes):
        self.storage.seal("key:" + cp.partition, cp.ref, blob)

    def verify(self, cp: Checkpoint) -> Optional[str]:
        """Re-read the STAGED payload from storage and run every validation a reader would."""
        facts = self.storage.facts()
        reason = validate(cp, facts)
        if reason is None:
            f, reason = load(cp, facts)
            if reason is None and state_signature(f) != cp.state_signature:
                reason = "state_signature"
        return reason

    def drop_staged(self, cp: Checkpoint):
        self.storage.drop_derived("key:" + cp.partition, cp.ref)        # through the storage boundary

    def publish(self, cp: Checkpoint):
        self.index.setdefault(cp.partition, []).append(cp)

    def add(self, cp: Checkpoint, blob: bytes):
        self.stage(cp, blob)
        self.publish(cp)

    def candidates(self, subject: str, r: float) -> List[Checkpoint]:
        return sorted((cp for cp in self.index.get(subject, ()) if cp.covered_at <= r and cp.ref not in self.unusable),
                      key=lambda cp: cp.covered_at, reverse=True)

    def discard(self, cp: Checkpoint, reason: str = "retired"):
        self.unusable.add(cp.ref)
        self.rejections.append((cp.ref, reason))
        self.storage.drop_derived("key:" + cp.partition, cp.ref)        # physical cleanup, after logical retirement

    def compact(self, subject: str) -> int:
        """v1 compaction: retire every checkpoint of ``subject`` except the newest usable one. Deletes no fact."""
        live = self.candidates(subject, float("inf"))
        for cp in live[1:]:
            self.discard(cp, "superseded")
        return len(live[1:])


def build_fold(facts: DurableFacts, subject: str, c: float, d: Decisions = AMENDED) -> Fold:
    return _advance(Fold(subject), facts, c, d)


def checkpoint_at(facts: DurableFacts, cps: CheckpointStore, subject: str, c: float, created_at: float = 0.0,
                  d: Decisions = AMENDED, crash: Optional[str] = None, incremental: bool = True,
                  op: Optional["OperationValidation"] = None):
    """Create a checkpoint covering every point of ``subject`` at or before ``c``. The caller guarantees that c is
    closed (``create`` does it with a current read); validation re-checks the prefix on every use.

    Maintenance v1, incremental: the newest VALID checkpoint at or before c (every reader validation), decoded into
    a fresh object from its sealed payload (the published one is never mutated) and advanced through the durable
    suffix only. Otherwise (none, or any validation failure) a full build. Either way the fold is the same."""
    if crash == "build":
        raise Crash()                                # nothing staged, nothing published
    base = checkpoint_fold(facts, subject, c, cps, d, op=op) if incremental else None
    f = base[1] if base is not None else build_fold(facts, subject, c, d)
    if f.unsafe is None and any(base_predicate(x.content.key) not in f.in_force for x in f.claims.values()):
        f.unsafe = "claim_without_publication_in_force"
    if f.unsafe is not None:
        return ("UNSUPPORTED", f.unsafe)            # fail-safe: such a fold could differ at a later read
    part = facts.partitions.get(subject, ())
    tail = (part[f.position - 1].entry.idem, part[f.position - 1].entry.at) if f.position else None
    sig = state_signature(f)
    try:
        blob = encode(f, cps.encoding)
    except ValueError as e:
        return ("UNSUPPORTED", str(e))
    if crash == "digest":
        raise Crash()
    cp = Checkpoint(subject, c, f.position, tail, policy_position(facts, c), CONTRACT, sig, _sha(blob), created_at,
                    "ckpt:%s:%r:%s:%s" % (subject, c, sig[:16], secrets.token_hex(8)), cps.encoding)
    if crash == "before_seal":
        raise Crash()
    if crash == "torn":                              # a partial payload became durable with its index entry
        cps.add(cp, blob[: len(blob) // 2])
        raise Crash()
    try:
        cps.stage(cp, blob)
    except AppendRejected as e:
        return ("REJECTED", str(e))                  # e.g. the subject key is destroyed: nothing may be sealed
    if crash == "after_seal":                        # payload durable, index entry never written: invisible
        raise Crash()
    reason = cps.verify(cp)
    if reason is not None:                           # the staged payload is not what was built: never published
        cps.drop_staged(cp)
        return ("REJECTED", "verify:" + reason)
    cps.publish(cp)                                  # the one atomic publication step
    if crash == "after_publish":
        raise Crash()
    return ("CREATED", cp)


def create(j, cps: CheckpointStore, subject: str, clock: float, served=None, d: Decisions = AMENDED,
           crash: Optional[str] = None, incremental: bool = True, op: Optional["OperationValidation"] = None):
    """Create a checkpoint at a CLOSED position: the served position of a current read (partition and its
    predicates closed through r, K5-K7), so no later append can land at or before it."""
    sv = served if served is not None else j.read(subject, clock, op=op)
    return checkpoint_at(j.store.facts(), cps, subject, sv.r, clock, d, crash, incremental, op)


class Crash(Exception):
    """Injected process crash during checkpoint creation."""


def uncovered(j, cps: CheckpointStore, subject: str) -> int:
    """Partition entries not covered by the newest published checkpoint (positional; no replay)."""
    live = cps.candidates(subject, float("inf"))
    return len(j.store.entries(subject)) - (live[0].covered_count if live else 0)


def maintain(j, cps: CheckpointStore, subject: str, clock: float, threshold: int, d: Decisions = AMENDED,
             crash: Optional[str] = None):
    """Maintenance v1. When ``uncovered >= threshold`` (checkpoint cadence = an operational parameter; no production
    value), create a checkpoint incrementally at a closed position; only once it is PUBLISHED, retire the older
    checkpoints of the partition (derived payloads; no fact is touched). Correctness never depends on it."""
    n = uncovered(j, cps, subject)
    if n < threshold:
        return ("SKIPPED", n)
    with OperationValidation(subject) as op:          # the closing read and the base share one validation;
        #                                               the staged checkpoint is still verified independently
        res = create(j, cps, subject, clock, d=d, crash=None if crash == "during_retire" else crash, op=op)
    if res[0] != "CREATED":
        return res
    new = res[1]
    olds = [cp for cp in cps.index.get(subject, ()) if cp.ref != new.ref and cp.ref not in cps.unusable]
    for i, old in enumerate(olds):
        if crash == "during_retire" and i == len(olds) - 1:
            raise Crash()                            # some retired, some not: every remaining one is still valid
        cps.discard(old, "superseded")
    return res


def validate(cp: Checkpoint, facts: DurableFacts) -> Optional[str]:
    """None if the checkpoint may be used against ``facts``; otherwise the reason it must not be."""
    if cp.contract != CONTRACT:
        return "contract_version"
    if cp.encoding not in ENCODINGS:
        return "encoding"
    blob = facts.vault.get(("key:" + cp.partition, cp.ref))
    if blob is None:
        return "unreadable"                          # key destroyed (crypto-shred), or never written
    if _sha(blob) != cp.blob_digest:
        return "integrity"
    part = facts.partitions.get(cp.partition, ())
    n = cp.covered_count
    if len(part) < n:
        return "prefix_missing"
    if n and (part[n - 1].entry.idem, part[n - 1].entry.at) != cp.tail:
        return "prefix_mismatch"
    if len(part) > n and part[n].entry.at <= cp.covered_at:
        return "suffix_not_after_c"
    if policy_position(facts, cp.covered_at) != cp.policy_position:
        return "policy_log_changed"
    return None


class OperationValidation:
    """Per-operation validation reuse v1 (``investigation/per-operation-checkpoint-validation-v1.md``).

    The checkpoints that passed FULL validation (validate + load + canonical signature) inside ONE logical operation
    on ONE subject. A later use in the same operation still runs ``validate`` against its own facts; it skips only
    load + signature, and only while the payload and every sealed fact the decode read are the very same objects
    (the signature is a pure function of them). Otherwise the full path runs again. Created as a local by each
    operation entry point and closed when it ends: never stored, never shared, never trusted after close."""

    def __init__(self, subject: str):
        self.subject = subject
        self._seen: Dict = {}                        # Checkpoint value -> (witness, pristine decoded fold)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def bind(self, subject: str):
        if self.closed:
            raise ValueError("operation_validation_closed")      # a finished operation authorizes nothing
        if subject != self.subject:
            raise ValueError("operation_validation_subject")

    @staticmethod
    def _keys(cp: Checkpoint, f: Fold) -> List[tuple]:
        """Every vault entry ``load`` read: the payload, plus (compact encoding) each referenced sealed fact."""
        keys = [("key:" + cp.partition, cp.ref)]
        if cp.encoding != "full":
            keys += [tuple(r) for r in f.claim_refs.values()] + [tuple(r) for r in f.retraction_refs]
            keys += [tuple(r) for r in f.event_refs] + [tuple(r) for r in f.generation_refs.values()]
        return keys

    def remember(self, cp: Checkpoint, facts: DurableFacts, f: Fold):
        self._seen[cp] = (tuple((k, facts.vault.get(k)) for k in self._keys(cp, f)), copy.deepcopy(f))

    def reuse(self, cp: Checkpoint, facts: DurableFacts) -> Optional[Fold]:
        hit = self._seen.get(cp)
        if hit is None or any(facts.vault.get(k) is not v for k, v in hit[0]):
            return None
        return copy.deepcopy(hit[1])                 # the pristine fold is never handed out


def checkpoint_fold(facts: DurableFacts, subject: str, r: float, cps: Optional[CheckpointStore],
                    d: Decisions = AMENDED, advance: bool = True, op: Optional[OperationValidation] = None
                    ) -> Optional[Tuple[Checkpoint, Fold]]:
    """The newest VALID checkpoint of ``subject`` at or before r, advanced through the durable suffix (c, r].
    None when there is none: the caller must then use the authoritative journal replay. Every rejected checkpoint
    is marked unusable and never trusted. ``op``: this operation's validations (load + signature reused, every
    other check re-run against ``facts``)."""
    if op is not None:
        op.bind(subject)
    for cp in (cps.candidates(subject, r) if cps is not None else ()):
        reason = "wrong_partition" if cp.partition != subject else validate(cp, facts)
        if reason is None:
            f = op.reuse(cp, facts) if op is not None else None
            if f is None:
                f, reason = load(cp, facts)
                if reason is None and state_signature(f) != cp.state_signature:
                    reason = "state_signature"
                elif reason is None and op is not None:
                    op.remember(cp, facts, f)
            if reason is None:
                return cp, (_advance(f, facts, r, d) if advance else f)
        cps.discard(cp, reason)                      # fail-safe: never trusted, rebuilt from the facts instead
    return None


def rebuild(facts: DurableFacts, subject: str, r: float, cps: Optional[CheckpointStore] = None,
            d: Decisions = AMENDED) -> Rebuilt:
    """checkpoint(c) + durable suffix (c, r], or a full replay when no valid checkpoint exists."""
    hit = checkpoint_fold(facts, subject, r, cps, d)
    if hit is None:
        return full_replay(facts, subject, r, d)
    return _result(hit[1], facts, r, d, "checkpoint")
