"""Evidence -> Claim acceptance gate over the Predicate Policy Registry. Pure and deterministic.

The LLM (or a typed command) PROPOSES; this code DECIDES. The gate takes:
- evidence metadata;
- one proposal;
- the registry;
- the slot's current resolved result (from ``registry.resolve_slot``).

It returns ACCEPT, REJECT, CONFLICT or REQUIRES_ESTABLISHMENT, plus the claim draft to commit.

It never resolves state, and never takes a caller: authorization stays a separate read-time step
(``registry.authorize``, contract §6 step 9). Grounding reuses the Lane A helpers (``memory_core.gate``).
Commit, fencing and sealing stay where they already live.
"""
import hashlib
import hmac
import os
from dataclasses import dataclass, replace
from typing import Dict, Mapping, Optional, Tuple

from ..gate import _grounded, _source_of, _value_in
from ..model import CONFLICT as S_CONFLICT, UNKNOWN as S_UNKNOWN, VALUE as S_VALUE, Evidence
from ..registry import (OPERATIONS, PolicyRegistry, PredicatePolicy, Resolved, UnknownPredicate, WriteCommand,
                        check_write, map_claim_key)

ACCEPT, REJECT, CONFLICT, REQUIRES_ESTABLISHMENT = "ACCEPT", "REJECT", "CONFLICT", "REQUIRES_ESTABLISHMENT"
# Effect of an accepted proposal on the slot (informational: resolution, not the gate, decides the value)
NEW_VALUE, REPLACEMENT, SAME_VALUE, SHADOWED, RESOLUTION, TRANSITION, ESTABLISH, ELEMENT = (
    "NEW_VALUE", "REPLACEMENT", "SAME_VALUE", "SHADOWED", "RESOLUTION", "TRANSITION", "ESTABLISH", "ELEMENT")
VALUE_KINDS = frozenset({"text", "enum", "none", "number", "bool"})


@dataclass(frozen=True)
class Proposal:
    proposal_id: str                          # idempotency key, chosen by the proposer
    subject_id: str
    org_id: str
    predicate: str
    policy_version_id: int
    op: str                                   # an operation from the registry vocabulary
    writer: str
    source: str
    value: Optional[Tuple[str, str]]          # (kind, canonical value); None only for REMOVE/CLEAR/REMOVE_KEY
    anchor: Tuple[Tuple[str, str], ...]       # ((evidence_id, quote), ...): the support, required
    map_key: Optional[str] = None
    valid_from: Optional[float] = None
    valid_until: Optional[float] = None


@dataclass(frozen=True)
class ClaimDraft:
    """Everything needed to commit an immutable ClaimContent; ids and commit time are assigned at commit."""
    subject_id: str
    org_id: str
    key: str                                  # predicate, or predicate[map_key]
    value: Optional[Tuple[str, str]]
    source: str
    source_member_id: str
    written_via: str                          # llm | command
    anchor: Tuple[Tuple[str, str], ...]
    valid_from: Optional[float]
    valid_until: Optional[float]
    observed_at: float
    policy_version: int
    op: str


@dataclass(frozen=True)
class GateOutcome:
    decision: str
    reason: str
    proposal_id: str
    fingerprint: str
    step: int                                 # the gate step that decided (see GATE_ORDER)
    effect: Optional[str] = None
    draft: Optional[ClaimDraft] = None
    duplicate: bool = False
    attestation: str = ""                     # set by the gate; commit refuses an outcome the gate did not issue


GATE_ORDER = (
    "0 idempotency", "1 predicate in registry", "2 policy version current", "3 proposal schema",
    "4 writer / source / LLM mode / security class", "5 evidence support", "6 subject and org binding",
    "7 temporal validity", "8 status gate, MAP keys, state machine, freshness", "9 effect / conflict classification")


# Per-process attestation key: an outcome built by hand (not by ``decide``) cannot be committed. Custody of any
# production equivalent is an open Security decision (C-1); this is in-process integrity, not a credential.
_GATE_KEY = os.urandom(32)


def _attestation_body(o: "GateOutcome") -> bytes:
    return repr((o.decision, o.reason, o.proposal_id, o.fingerprint, o.step, o.effect, o.draft,
                 o.duplicate)).encode("utf-8")


def _attest(o: "GateOutcome") -> "GateOutcome":
    return replace(o, attestation=hmac.new(_GATE_KEY, _attestation_body(o), hashlib.sha256).hexdigest())


def verify_attestation(o: "GateOutcome") -> bool:
    good = hmac.new(_GATE_KEY, _attestation_body(o), hashlib.sha256).hexdigest()
    return bool(o.attestation) and hmac.compare_digest(o.attestation, good)


def is_observation(pr: "Proposal") -> bool:
    """An LLM-extracted proposal is an OBSERVATION (evidence -> claim), never a state command."""
    return pr.writer == "llm_extractor"


def fingerprint(pr: Proposal) -> str:
    """Content identity of a proposal (independent of proposal_id)."""
    parts = (pr.subject_id, pr.org_id, pr.predicate, str(pr.policy_version_id), pr.op, pr.writer, pr.source,
             repr(pr.value), repr(sorted(pr.anchor)), str(pr.map_key), repr(pr.valid_from), repr(pr.valid_until))
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def _out(pr, fp, decision, reason, step, effect=None, draft=None, duplicate=False):
    return GateOutcome(decision, reason, pr.proposal_id, fp, step, effect, draft, duplicate)


def decide(pr: Proposal, registry: PolicyRegistry, evidence: Mapping[str, Evidence], current: Resolved, now: float,
           ledger: Optional[Dict[str, GateOutcome]] = None) -> GateOutcome:
    """Decide one proposal. ``ledger`` maps proposal_id / fingerprint -> earlier outcome (idempotency, step 0).
    Every returned outcome is attested by the gate."""
    return _attest(_decide_idem(pr, registry, evidence, current, now, ledger))


def _decide_idem(pr, registry, evidence, current, now, ledger) -> GateOutcome:
    fp = fingerprint(pr)
    ledger = {} if ledger is None else ledger

    # 0. idempotency: the same proposal again yields the same decision and no second claim
    prior = ledger.get("id:" + pr.proposal_id)
    if prior is not None:
        if prior.fingerprint != fp:
            return _out(pr, fp, REJECT, "proposal_id_reused_with_different_content", 0)
        return GateOutcome(**{**prior.__dict__, "duplicate": True, "draft": None})
    same = ledger.get("fp:" + fp)
    if same is not None and same.decision == ACCEPT:
        return _out(pr, fp, ACCEPT, "duplicate_of_" + same.proposal_id, 0, same.effect, None, True)

    out = _decide(pr, fp, registry, evidence, current, now)
    ledger["id:" + pr.proposal_id] = out
    if out.decision == ACCEPT:
        ledger.setdefault("fp:" + fp, out)
    return out


def _decide(pr, fp, registry, evidence, current, now) -> GateOutcome:
    # 1. predicate must exist (no fallback policy)
    try:
        p: PredicatePolicy = registry.get(pr.predicate)
    except UnknownPredicate:
        return _out(pr, fp, REJECT, "unknown_predicate", 1)
    # 2. the proposal must name the current version
    if pr.policy_version_id != p.policy_version_id:
        return _out(pr, fp, REJECT, "stale_policy_version", 2)
    # 3. schema
    if pr.op not in OPERATIONS:
        return _out(pr, fp, REJECT, "unknown_operation", 3)
    needs_value = pr.op not in ("REMOVE", "CLEAR", "REMOVE_KEY")
    if needs_value and (pr.value is None or pr.value[0] not in VALUE_KINDS):
        return _out(pr, fp, REJECT, "bad_value", 3)
    if p.cardinality == "MAP" and pr.map_key is None:
        return _out(pr, fp, REJECT, "map_key_required", 3)
    # 4. writer / source / LLM mode / security class (static policy)
    if pr.writer not in p.allowed_writers:
        return _out(pr, fp, REJECT, "writer_not_allowed", 4)
    if pr.source not in p.allowed_sources:
        return _out(pr, fp, REJECT, "source_not_allowed", 4)
    if pr.writer == "llm_extractor" and p.llm_write_mode != "PROPOSE_VIA_GATE":
        return _out(pr, fp, REJECT, "llm_write_forbidden", 4)
    # 5. evidence must support the assertion: every anchor is real, active, sealed, from a permitted author, and
    #    contains the quote; the quote must carry the value; the evidence's own source must be the claimed source
    if not pr.anchor:
        return _out(pr, fp, REJECT, "no_supporting_evidence", 5)
    evs = []
    for eid, quote in pr.anchor:
        ev = evidence.get(eid)
        if ev is None:
            return _out(pr, fp, REJECT, "evidence_not_found", 5)
        ok, why = _grounded(quote, ev, require_seal=True)
        if not ok:
            return _out(pr, fp, REJECT, "unsupported:" + why, 5)
        if _source_of(ev) != pr.source:
            return _out(pr, fp, REJECT, "evidence_source_mismatch", 5)       # e.g. user text claimed as BILLING
        if needs_value and not _value_in(quote, pr.value):
            return _out(pr, fp, REJECT, "unsupported:value_not_in_quote", 5)
        evs.append(ev)
    # 6. subject / org binding (not authorization: the gate never sees a caller)
    if any(ev.subject_id != pr.subject_id or ev.org_id != pr.org_id for ev in evs):
        return _out(pr, fp, REJECT, "evidence_subject_or_org_mismatch", 6)
    # 7. temporal validity
    observed = max(ev.observed_at for ev in evs)
    if observed > now:
        return _out(pr, fp, REJECT, "evidence_from_the_future", 7)
    if pr.valid_from is not None and pr.valid_until is not None and pr.valid_until <= pr.valid_from:
        return _out(pr, fp, REJECT, "empty_validity_interval", 7)
    # 8. dynamic rules: status gate, MAP keys, state machine, stale writes (one implementation: the registry's)
    wd = check_write(p, WriteCommand(pr.predicate, pr.policy_version_id, pr.op, pr.writer, pr.source,
                                     None if pr.value is None else pr.value[1], pr.map_key), current,
                     assertion=is_observation(pr))
    target = current.keys[pr.map_key] if p.cardinality == "MAP" and pr.map_key in current.keys else current
    if not wd.allowed:
        if wd.reason.endswith(f"not_allowed_in_{S_UNKNOWN}") \
                and "ESTABLISH" in p.allowed_operations_by_status.get(S_UNKNOWN, frozenset()):
            return _out(pr, fp, REQUIRES_ESTABLISHMENT, "slot_unknown_establish_first", 8)
        return _out(pr, fp, REJECT, wd.reason, 8)
    # 9. classify the effect (informational) and flag a proposal that will put the slot in CONFLICT
    member = evs[0].source_member_id or pr.source
    key = map_claim_key(pr.predicate, pr.map_key) if p.cardinality == "MAP" else pr.predicate
    draft = ClaimDraft(pr.subject_id, pr.org_id, key, pr.value, pr.source, member,
                       "llm" if pr.writer == "llm_extractor" else "command", tuple(pr.anchor), pr.valid_from,
                       pr.valid_until, observed, p.policy_version_id, pr.op)
    effect, conflict = _effect(p, pr, target, member)
    if conflict:
        # The claim is evidence and is kept, but its acceptance creates a CONFLICT the policy must resolve.
        return _out(pr, fp, CONFLICT, "equal_authority_independent_source_disagrees", 9, effect, draft)
    return _out(pr, fp, ACCEPT, "ok", 9, effect, draft)


def _effect(p: PredicatePolicy, pr: Proposal, target: Resolved, member: str) -> Tuple[str, bool]:
    s = target.slot
    if pr.op == p.conflict_policy.resolve_operation:
        return RESOLUTION, False
    if pr.op == "TRANSITION":
        return TRANSITION, False
    if pr.op == "ESTABLISH":
        return ESTABLISH, False
    if p.cardinality == "SET":
        return ELEMENT, False
    if s.status != S_VALUE or pr.value is None:
        return NEW_VALUE, False
    if s.value == pr.value:
        return SAME_VALUE, False
    cur_rank = p.authority_rank.get(s.source, 0)
    my_rank = p.authority_rank.get(pr.source, 0)
    if my_rank < cur_rank:
        return SHADOWED, False                                # kept as evidence; cannot win this slot
    if my_rank > cur_rank or s.source == pr.source:
        return REPLACEMENT, False                             # same source group supersedes (temporal replacement)
    return NEW_VALUE, True                                    # equal rank, different source, different value
