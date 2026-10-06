"""Claim Commit Protocol: records an already-approved gate decision safely. Pure in-memory model.

Responsibilities, unchanged:
- registry: what is allowed;
- claimgate: is this proposal admissible;
- **commit: record the approved decision**;
- resolver: what is current;
- authorize: who may see it.

This layer never resolves a value and never sees a caller.

Reused from Lane A rather than redesigned:
- keyed deterministic ids (``memory_core.ids``), including the F-3 derivation tag;
- the E3 evidence fence (``memory_core.fence``);
- the LA-9 recorded-retraction rule;
- the LA-1 rule that replay applies the RECORDED outcome.

Concurrency follows contract §7 and the spec (§10.4, §13). A typed state command carries ``expected_version``
for its slot, and a mismatch is a typed ``STATE_CONFLICT`` that is never retried. ``claims_version`` advances on
every commit and is never used as an expected version. A slot's ``state_version`` is the projection's, because only
resolution knows whether the result changed (``Projection`` below).
"""
import copy
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..claimgate import ACCEPT, CONFLICT, ClaimDraft, GateOutcome, Proposal, fingerprint, verify_attestation
from ..fence import COMMIT as F_COMMIT, DEFER as F_DEFER, QUARANTINE as F_QUARANTINE, Context, Stamp, fence
from ..ids import claim_id as _lane_a_claim_id
from ..model import (ACTIVE, INVALIDATED, NEVER_TRUE, NO_LONGER_TRUE, PENDING_ERASURE, QUARANTINED, RETRACTED,
                     SUPERSEDED, Claim, ClaimContent, ClaimState, Evidence, Transition)

SUPERSEDED_BY_POLICY = "superseded_by_policy"     # contract §10: terminal for resolution; history/provenance only
LIFECYCLE_STATUSES = frozenset({ACTIVE, RETRACTED, INVALIDATED, QUARANTINED, PENDING_ERASURE, SUPERSEDED})
RETRACT_CAUSES = frozenset({NO_LONGER_TRUE, NEVER_TRUE})
# commit result statuses
COMMITTED, EXISTING_CLAIM, NOT_COMMITTED, FENCED, DEFERRED, STATE_CONFLICT, REJECTED = (
    "COMMITTED", "EXISTING_CLAIM", "NOT_COMMITTED", "FENCED", "DEFERRED", "STATE_CONFLICT", "REJECTED")
_ASSERTION_MODE = {"llm_extractor": "stated", "user_command": "stated", "operator": "operator",
                   "import": "imported", "system_sync": "imported"}


class CrashBeforeWrite(RuntimeError):
    """Injected failure: nothing was written."""


class CrashAfterWrite(RuntimeError):
    """Injected failure: the commit is durable, but the caller never received the acknowledgement."""


# --------------------------------------------------------------------------- identity (one swappable function)
def claim_identity(subject_key: bytes, draft: ClaimDraft, derivation: str) -> str:
    """The ONLY place a claim id is built.

    Lane A keyed formula (HMAC under the subject key) with the F-3 derivation tag, so a recovery re-derivation
    never collides with the original. The inputs are extended with source member and asserted interval, so
    claims differing only in those never collide either. The production construction and key custody remain
    OPEN; swap this function.
    """
    evid = ",".join(sorted(e for e, _ in draft.anchor))
    value = "%s:%s" % draft.value
    tag = "%s|%s|%r|%r" % (derivation, draft.source_member_id, draft.valid_from, draft.valid_until)
    return _lane_a_claim_id(subject_key, evid, draft.key, value + "|" + tag, derivation, include_derivation=True)


# --------------------------------------------------------------------------- records
@dataclass(frozen=True)
class StateConflict:
    """Contract §7 typed failure. Returned to the caller; never retried by infrastructure."""
    predicate: str
    scope: Tuple[str, str]
    expected_version: int
    actual_version: int
    expected_status: Optional[str] = None
    actual_status: Optional[str] = None


@dataclass(frozen=True)
class RetractionRecord:
    """LA-9: a recorded retraction. It ends every matching claim of its source group observed at or before it,
    including claims committed later."""
    retraction_id: str                       # idempotency key
    subject_id: str
    key: str
    value: Tuple[str, str]
    source: str
    source_member_id: str
    cause: str                               # no_longer_true | never_true
    observed_at: float
    observed_seq: int
    evidence_id: str
    merge_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SyncRecord:
    """C-C: a recorded external-sync success, the only basis of external freshness (contract §3).
    Recorded like any other journal fact, so a rebuild reproduces freshness."""
    sync_id: str                             # idempotency key
    subject_id: str
    predicate: str
    sync_source: str                         # identity of the sync process whose success counts (B-2)
    synced_at: float


@dataclass(frozen=True)
class CommitRecord:
    """Proposal + recorded gate decision + what was committed. Replay applies THIS, never today's policy."""
    seq: int
    proposal: Proposal
    proposal_fingerprint: str
    decision: GateOutcome
    status: str
    claim_id: Optional[str] = None
    claim_content: Optional[ClaimContent] = None
    initial_status: str = ACTIVE
    attributed: bool = True
    merge_ids: Tuple[str, ...] = ()
    reason: str = ""
    state_conflict: Optional[StateConflict] = None
    committed_at: float = 0.0


@dataclass(frozen=True)
class CommitResult:
    status: str
    record: Optional[CommitRecord]
    duplicate: bool = False
    reason: str = ""


@dataclass(frozen=True)
class JournalEntry:
    seq: int
    kind: str                                # claim | lifecycle | retraction
    at: float
    payload: object


@dataclass
class CommitStore:
    """Durable state of the prototype. ``journal`` is the single source of truth for rebuild."""
    journal: List[JournalEntry] = field(default_factory=list)
    claims: Dict[str, Claim] = field(default_factory=dict)
    records: Dict[str, CommitRecord] = field(default_factory=dict)          # proposal_id -> record
    retractions: Dict[str, RetractionRecord] = field(default_factory=dict)  # retraction_id -> record
    provenance: Dict[str, List[int]] = field(default_factory=dict)          # claim_id -> commit record seqs
    claims_version: Dict[str, int] = field(default_factory=dict)            # subject -> n (never an expected_version)
    _seq: int = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


def _stamp(ev: Evidence) -> Stamp:
    return Stamp(ev.evidence_id, True, ev.status, dict(ev.epochs),
                 {"org": "org:" + ev.org_id, "subject": "subject:" + ev.subject_id, "session": "session:" + ev.session_id},
                 tuple(ev.merge_ids_at_ingestion), ev.subject_id, ev.observed_at)


def _missing(eid: str) -> Stamp:
    return Stamp(eid, False, "missing", {}, {}, (), "", 0.0)


def _apply_atomically(store: CommitStore, mutate: Callable[[], None], crash: Optional[str]):
    """All-or-nothing: either every mutation of one commit lands, or none does."""
    if crash == "before_write":
        raise CrashBeforeWrite()
    snapshot = copy.deepcopy(store.__dict__)
    try:
        mutate()
    except Exception:
        store.__dict__.update(snapshot)
        raise
    if crash == "after_write":
        raise CrashAfterWrite()


# --------------------------------------------------------------------------- commit
def commit(store: CommitStore, proposal: Proposal, decision: GateOutcome, evidence: Mapping[str, Evidence],
           fence_ctx: Context, subject_key: Callable[[str], bytes], now: float, *, extractor_version: str = "x",
           expected_version: Optional[int] = None, actual_version: int = 0,
           expected_status: Optional[str] = None, actual_status: Optional[str] = None,
           derivation: str = "orig", crash: Optional[str] = None) -> CommitResult:
    """Record one approved decision. Exactly one logical commit per ``proposal_id``, whatever the retries."""
    fp = fingerprint(proposal)
    # 1. idempotency on the proposal (distinct from claim identity)
    prior = store.records.get(proposal.proposal_id)
    if prior is not None:
        if prior.proposal_fingerprint != fp:
            return CommitResult(REJECTED, None, reason="proposal_id_reused_with_different_content")
        return CommitResult(prior.status, prior, duplicate=True, reason=prior.reason)
    # 2. the decision must have been ISSUED by the gate (not built by hand) and be for THIS proposal
    if not verify_attestation(decision):
        return CommitResult(REJECTED, None, reason="decision_not_attested_by_gate")
    if decision.proposal_id != proposal.proposal_id or decision.fingerprint != fp:
        return CommitResult(REJECTED, None, reason="decision_does_not_match_proposal")
    if decision.decision not in (ACCEPT, CONFLICT) or decision.draft is None:
        return _record_only(store, proposal, fp, decision, NOT_COMMITTED, "gate_" + decision.decision.lower(),
                            now, crash)
    draft = decision.draft
    if draft.value is None:
        return CommitResult(REJECTED, None, reason="valueless_op_is_a_lifecycle_command")
    # 3. optimistic concurrency for typed state commands (LLM assertions are evidence, not state commands)
    typed = proposal.writer != "llm_extractor"
    if typed and expected_version is None:
        return CommitResult(REJECTED, None, reason="expected_version_required_for_state_command")
    if typed and expected_version != actual_version:
        sc = StateConflict(proposal.predicate, ("CUSTOMER", proposal.subject_id), expected_version, actual_version,
                           expected_status, actual_status)
        return _record_only(store, proposal, fp, decision, STATE_CONFLICT, "state_conflict", now, crash, sc)
    # 4. evidence fence (Lane A E3)
    evs = [evidence.get(e) for e, _ in draft.anchor]
    fr = fence([_stamp(e) if e else _missing(eid) for e, (eid, _) in zip(evs, draft.anchor)], fence_ctx)
    if fr.action == F_DEFER:
        return CommitResult(DEFERRED, None, reason=fr.reason)                     # not recorded: retry allowed
    if fr.action not in (F_COMMIT, F_QUARANTINE):
        return _record_only(store, proposal, fp, decision, FENCED, fr.reason, now, crash)
    target = fr.target_subject
    status0 = QUARANTINED if fr.action == F_QUARANTINE else ACTIVE
    # 5. claim identity (content-level dedup; distinct from proposal idempotency)
    cid = claim_identity(subject_key(target), replace(draft, subject_id=target), derivation)
    ev0 = evs[0]
    content = ClaimContent(
        claim_id=cid, subject_id=target, source_member_id=draft.source_member_id, org_id=draft.org_id,
        learned_by_agent_id=ev0.agent_id, key=draft.key, value=draft.value, source=draft.source,
        assertion_mode=_ASSERTION_MODE[proposal.writer], value_check="verified", normaliser_id=None,
        anchor=tuple(draft.anchor), prompt_ref=None, valid_from=draft.valid_from, valid_until=draft.valid_until,
        observed_at=draft.observed_at, committed_at=now, extractor_version=extractor_version,
        policy_version=draft.policy_version, derivation=derivation,
        observed_seq=max(e.receipt_seq for e in evs), written_via=draft.written_via)
    existing = cid in store.claims
    status = EXISTING_CLAIM if existing else COMMITTED

    def mutate():
        seq = store.next_seq()
        rec = CommitRecord(seq, proposal, fp, decision, status, cid, content, status0, fr.attributed,
                           tuple(fr.merges_recorded), fr.reason, committed_at=now)
        store.records[proposal.proposal_id] = rec
        store.provenance.setdefault(cid, []).append(seq)
        if not existing:
            store.journal.append(JournalEntry(seq, "claim", now, rec))
            _insert(store.claims, rec, store.retractions.values(), now)
            store.claims_version[target] = store.claims_version.get(target, 0) + 1

    _apply_atomically(store, mutate, crash)
    return CommitResult(status, store.records[proposal.proposal_id], reason=fr.reason)


def _record_only(store, proposal, fp, decision, status, reason, now, crash, sc=None) -> CommitResult:
    def mutate():
        store.records[proposal.proposal_id] = CommitRecord(store.next_seq(), proposal, fp, decision, status,
                                                           reason=reason, state_conflict=sc, committed_at=now)
    _apply_atomically(store, mutate, crash)
    return CommitResult(status, store.records[proposal.proposal_id], reason=reason)


def _insert(claims: Dict[str, Claim], rec: CommitRecord, retractions, at: float):
    st = ClaimState(status=ACTIVE, attributed=rec.attributed, merge_ids=list(rec.merge_ids))
    c = Claim(rec.claim_content, st)
    if rec.initial_status != ACTIVE:
        st.transitions.append(Transition(at, ACTIVE, rec.initial_status, "commit_fence_" + rec.initial_status))
        st.status = rec.initial_status
    claims[c.id] = c
    for r in retractions:                       # a recorded retraction also ends claims committed after it (LA-9)
        apply_retraction(r, c, at)


# --------------------------------------------------------------------------- retraction and lifecycle
def apply_retraction(r: RetractionRecord, c: Claim, at: float) -> bool:
    """LA-9, pure. Returns True if it transitioned the claim. Converges whatever the commit order."""
    s = c.state
    if s.status not in (ACTIVE, RETRACTED) or c.content.key != r.key or c.content.value != r.value:
        return False
    if c.content.subject_id != r.subject_id:
        return False
    if (c.content.source, c.content.source_member_id) != (r.source, r.source_member_id):
        return False
    if (c.content.observed_at, c.content.observed_seq) > (r.observed_at, r.observed_seq):
        return False
    if s.status == RETRACTED:
        cur_eff = next((x.effective_at for x in reversed(s.transitions) if x.to == RETRACTED), None)
        if s.retract_cause == NEVER_TRUE:
            return False
        if r.cause != NEVER_TRUE and cur_eff is not None and cur_eff <= r.observed_at:
            return False
    s.transitions.append(Transition(at, s.status, RETRACTED, r.cause, r.evidence_id, effective_at=r.observed_at,
                                    merge_ids=tuple(r.merge_ids)))
    s.status, s.retract_cause = RETRACTED, r.cause
    return True


def retract(store: CommitStore, r: RetractionRecord, now: float, crash: Optional[str] = None) -> CommitResult:
    """Record a retraction command once (idempotent on ``retraction_id``) and apply it."""
    if r.cause not in RETRACT_CAUSES:
        return CommitResult(REJECTED, None, reason="unknown_retraction_cause")
    prior = store.retractions.get(r.retraction_id)
    if prior is not None:
        return CommitResult(COMMITTED if prior == r else REJECTED, None, duplicate=prior == r,
                            reason="" if prior == r else "retraction_id_reused_with_different_content")

    def mutate():
        store.journal.append(JournalEntry(store.next_seq(), "retraction", now, r))
        store.retractions[r.retraction_id] = r
        for c in store.claims.values():
            apply_retraction(r, c, now)
    _apply_atomically(store, mutate, crash)
    return CommitResult(COMMITTED, None)


def lifecycle(store: CommitStore, claim_id: str, to: str, cause: str, now: float) -> CommitResult:
    """A recorded lifecycle transition. Content is never touched; only the state history grows."""
    if to not in LIFECYCLE_STATUSES or to == RETRACTED:
        return CommitResult(REJECTED, None, reason="use_retract_for_retraction" if to == RETRACTED
                            else "unknown_lifecycle_status")
    c = store.claims.get(claim_id)
    if c is None:
        return CommitResult(REJECTED, None, reason="unknown_claim")
    t = Transition(now, c.state.status, to, cause)

    def mutate():
        store.journal.append(JournalEntry(store.next_seq(), "lifecycle", now, (claim_id, t)))
        _transition(c, t)
    _apply_atomically(store, mutate, None)
    return CommitResult(COMMITTED, None)


def supersede_by_policy(store: CommitStore, old_id: str, new_id: str, now: float) -> CommitResult:
    """Contract §10: once a replacement claim under the newer policy is committed, the old claim becomes
    SUPERSEDED_BY_POLICY (terminal for resolution, kept for history). Recorded; never inferred. No revalidation
    workflow is defined here: the replacement claim arrives through the normal gate and commit."""
    old, new = store.claims.get(old_id), store.claims.get(new_id)
    if old is None or new is None:
        return CommitResult(REJECTED, None, reason="unknown_claim")
    if (old.content.subject_id, old.content.key) != (new.content.subject_id, new.content.key):
        return CommitResult(REJECTED, None, reason="replacement_for_a_different_slot")
    if new.content.policy_version <= old.content.policy_version:
        return CommitResult(REJECTED, None, reason="replacement_not_under_a_newer_policy")
    if old.state.status in (INVALIDATED, SUPERSEDED_BY_POLICY):
        return CommitResult(REJECTED, None, reason="old_claim_terminal")
    t = Transition(now, old.state.status, SUPERSEDED_BY_POLICY, "superseded_by_policy", new_id)

    def mutate():
        store.journal.append(JournalEntry(store.next_seq(), "lifecycle", now, (old_id, t)))
        _transition(old, t)
    _apply_atomically(store, mutate, None)
    return CommitResult(COMMITTED, None)


def record_sync(store: CommitStore, r: SyncRecord, now: float) -> CommitResult:
    """C-C: journal an external-sync success. Idempotent on ``sync_id``."""
    if any(e.kind == "sync" and e.payload.sync_id == r.sync_id for e in store.journal):
        prior = next(e.payload for e in store.journal if e.kind == "sync" and e.payload.sync_id == r.sync_id)
        return CommitResult(COMMITTED if prior == r else REJECTED, None, duplicate=prior == r,
                            reason="" if prior == r else "sync_id_reused_with_different_content")
    if r.synced_at > now:
        return CommitResult(REJECTED, None, reason="sync_from_the_future")
    _apply_atomically(store, lambda: store.journal.append(JournalEntry(store.next_seq(), "sync", now, r)), None)
    return CommitResult(COMMITTED, None)


def record_policy(store: CommitStore, predicate: str, version: int, now: float) -> CommitResult:
    """Journal a policy publication as an evaluation point, so state_version history is evaluated under the policy
    IN FORCE at each point and never rewritten retroactively (monotonic). Idempotent on (predicate, version)."""
    if any(e.kind == "policy" and e.payload == (predicate, version) for e in store.journal):
        return CommitResult(COMMITTED, None, duplicate=True)
    _apply_atomically(store, lambda: store.journal.append(
        JournalEntry(store.next_seq(), "policy", now, (predicate, version))), None)
    return CommitResult(COMMITTED, None)


def last_sync_from(journal: Sequence[JournalEntry], subject: str, predicate: str, cutoff: float) -> Optional[float]:
    """The freshness input, derived only from recorded sync events known at ``cutoff``."""
    times = [e.payload.synced_at for e in journal if e.kind == "sync" and e.at <= cutoff
             and e.payload.subject_id == subject and e.payload.predicate == predicate]
    return max(times) if times else None


def _transition(c: Claim, t: Transition):
    c.state.transitions.append(t)
    c.state.status = t.to


# --------------------------------------------------------------------------- replay and rebuild
def rebuild_claims(journal: Sequence[JournalEntry]) -> Dict[str, Claim]:
    """Rebuild every claim and its lifecycle from the journal alone, applying RECORDED outcomes in order."""
    claims: Dict[str, Claim] = {}
    retractions: List[RetractionRecord] = []
    for e in sorted(journal, key=lambda x: x.seq):
        if e.kind == "claim":
            _insert(claims, e.payload, retractions, e.at)
        elif e.kind == "retraction":
            retractions.append(e.payload)
            for c in claims.values():
                apply_retraction(e.payload, c, e.at)
        elif e.kind == "lifecycle":
            cid, t = e.payload
            _transition(claims[cid], t)
    return claims


@dataclass
class Projection:
    """A rebuildable Current State view: slot -> (state_version, signature). Never independent truth.

    ``state_version`` advances only when the resolved signature changes (spec §13), so it is computed here from
    resolution, not at commit."""
    versions: Dict[str, Tuple[int, tuple]] = field(default_factory=dict)

    def observe(self, slot_key: str, signature: tuple) -> int:
        v, sig = self.versions.get(slot_key, (0, None))
        if sig != signature:
            v += 1
            self.versions[slot_key] = (v, signature)
        return v
