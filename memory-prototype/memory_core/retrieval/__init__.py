"""Typed retrieval over Claims, Current State, narrative episodes and commitments (contract §8). Pure.

How the future Memory Gateway obtains memory without touching the store:
- each operation is a declared intent (§8: the tool schema is the intent classifier);
- results use one stable, typed structure;
- raw storage objects are never returned.

**Order of every operation:** build the result from the system's resolved data, independent of the caller. Then
apply the single read-authorization rule (``registry.may_read``, §6 step 9). A caller can change only WHETHER it
sees a result, never WHICH value is true.

There is no LLM, no embeddings, no external services and no mutation. Ranking is deterministic.

Supported:
- ``get_current_state`` (projection);
- ``search_history`` (immutable claims with temporal labels, §8);
- ``search_memory`` (narrative Episode summaries);
- ``get_commitments`` (the commitment event-log projection).

Explicitly unsupported (no model in the architecture prototype):
- ``get_relationships``;
- ``get_tenant_knowledge``: TENANT scope is unmodelled (S-3). Agent Knowledge exists, but its read scope is
  undefined.

Scope vocabulary is the contract's (§2): GLOBAL, TENANT, WORKSPACE, CUSTOMER, SESSION, AGENT, RESOURCE.
- CUSTOMER is the only projected scope;
- every other contract scope returns UNSUPPORTED_SCOPE;
- a name outside the contract (for example "ORG") returns INVALID_SCOPE.
"""
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .. import commitments as CM
from ..commit import SUPERSEDED_BY_POLICY, JournalEntry, _insert, _transition, apply_retraction, last_sync_from
from ..config import AMENDED, Decisions
from ..model import NEVER_TRUE, RETRACTED, Claim, Episode
from ..normalise import tokens
from ..registry import Caller, PredicatePolicy, may_read, requires_revalidation
from ..resolve import _superseded_read_time
from ..state import CurrentState, StateSlot, base_predicate, project_subject
from ..temporal import EXCLUDED, asserted_interval, effective_interval, status_at

# retrieval types (§8)
CURRENT_STATE, HISTORY, NARRATIVE, COMMITMENT, RELATIONSHIP, TENANT_KNOWLEDGE = (
    "CURRENT_STATE", "HISTORY", "NARRATIVE", "COMMITMENT", "RELATIONSHIP", "TENANT_KNOWLEDGE")
# result statuses
OK, ACCESS_DENIED, UNKNOWN_PREDICATE, UNSUPPORTED_SCOPE, UNSUPPORTED_CAPABILITY, INVALID_SCOPE = (
    "OK", "ACCESS_DENIED", "UNKNOWN_PREDICATE", "UNSUPPORTED_SCOPE", "UNSUPPORTED_CAPABILITY", "INVALID_SCOPE")
CONTRACT_SCOPES = frozenset({"GLOBAL", "TENANT", "WORKSPACE", "CUSTOMER", "SESSION", "AGENT", "RESOURCE"})
# history labels
H_CURRENT, H_IN_CONFLICT, H_SUPERSEDED, H_ENDED, H_NOT_SELECTED = (
    "CURRENT", "IN_CONFLICT", "SUPERSEDED", "ENDED", "NOT_SELECTED")
H_REVALIDATION_REQUIRED, H_SUPERSEDED_BY_POLICY = "REVALIDATION_REQUIRED", "SUPERSEDED_BY_POLICY"   # §10
HISTORICAL = "HISTORICAL"          # usage label: history is never operational truth
SUPPORTED_SCOPE = "CUSTOMER"


@dataclass(frozen=True)
class MemoryItem:
    retrieval_type: str
    subject_id: str
    scope: Tuple[str, str]
    predicate: Optional[str]
    value: Optional[Tuple[str, str]]
    status: str                     # slot status, history label, or commitment state
    valid_from: Optional[float]
    valid_until: Optional[float]
    freshness_status: str
    usage: str
    provenance: Tuple[str, ...]     # claim ids / evidence ids / event ids (references only)
    policy_version: Optional[int]
    source: Optional[str]
    authority_domain: Optional[str]
    observed_at: Optional[float] = None
    state_version: Optional[int] = None


@dataclass(frozen=True)
class RetrievalResult:
    retrieval_type: str
    status: str
    items: Tuple[MemoryItem, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class MemorySource:
    """What the gateway would read. Immutable inputs; the retrieval layer never writes."""
    journal: Tuple[JournalEntry, ...]
    policies: Mapping[str, PredicatePolicy]
    episodes: Tuple[Episode, ...] = ()
    commitment_events: Tuple[CM.Event, ...] = ()
    dead_evidence: frozenset = frozenset()
    d: Decisions = AMENDED
    # N-5: state_version must be evaluated under the policy IN FORCE at each point, here as in the projection.
    policy_history: Optional[Mapping[str, Mapping[int, PredicatePolicy]]] = None
    # Checkpoint consumer v1: a validated ProjectionView of ONE subject at ONE served position r. When set, current
    # state, the claim map and freshness come from it, and the journal is never read. Any other read raises.
    view: Optional[object] = None


def _denied(rtype: str) -> RetrievalResult:
    return RetrievalResult(rtype, ACCESS_DENIED)          # no items: no value, no provenance, no metadata


def _scope_check(rtype: str, scope: Tuple[str, str]) -> Optional[RetrievalResult]:
    if scope[0] not in CONTRACT_SCOPES:
        return RetrievalResult(rtype, INVALID_SCOPE, reason=f"{scope[0]} is not a contract scope (§2)")
    if scope[0] != SUPPORTED_SCOPE:
        return RetrievalResult(rtype, UNSUPPORTED_SCOPE, reason=f"{scope[0]} scope not modelled (S-3)")
    return None


def _view_for(src: MemorySource, subject: str, as_of: float, now: float):
    v = src.view
    if (v.subject, v.r, v.r) != (subject, as_of, now):
        raise ValueError("the ProjectionView does not cover this read")
    return v


def _projection(src: MemorySource, subject: str, as_of: float, now: float) -> CurrentState:
    if src.view is not None:
        return _view_for(src, subject, as_of, now).state
    j = src.journal
    return project_subject([e for e in j if e.kind == "claim"], [e for e in j if e.kind != "claim"], src.policies,
                           as_of, now, subject=subject, d=src.d, policy_history=src.policy_history)


def _claims(src: MemorySource, subject: str, now: Optional[float] = None) -> Dict[str, Claim]:
    if src.view is not None:
        v = _view_for(src, subject, now, now)
        return {k: c for k, c in v.claims.items() if c.content.subject_id == subject}
    claims: Dict[str, Claim] = {}
    retr = []
    for e in sorted(src.journal, key=lambda x: x.seq):      # the commit layer's recorded-outcome replay
        if e.kind == "claim":
            _insert(claims, e.payload, retr, e.at)
        elif e.kind == "retraction":
            retr.append(e.payload)
            for c in claims.values():
                apply_retraction(e.payload, c, e.at)
        elif e.kind == "lifecycle":
            cid, t = e.payload
            _transition(claims[cid], t)
    return {k: c for k, c in claims.items() if c.content.subject_id == subject}


# --------------------------------------------------------------------------- get_current_state
def get_current_state(src: MemorySource, subject: str, predicate: Optional[str], as_of: float, now: float,
                      caller: Caller, scope_type: str = SUPPORTED_SCOPE) -> RetrievalResult:
    scope = (scope_type, subject)
    if (r := _scope_check(CURRENT_STATE, scope)) is not None:
        return r
    if predicate is not None and predicate not in src.policies:
        return RetrievalResult(CURRENT_STATE, UNKNOWN_PREDICATE)
    if scope not in caller.authorized_scopes:
        return _denied(CURRENT_STATE)
    cs = _projection(src, subject, as_of, now)
    slots = dict(cs.slots)
    wanted = [predicate] if predicate is not None else sorted(slots)
    items = []
    for pred in wanted:
        p = src.policies[pred]
        if not may_read(caller, scope, p.security_class):
            if predicate is not None:
                return _denied(CURRENT_STATE)                 # an explicit request for an uncleared predicate
            continue                                          # a listing omits it entirely (no existence leak)
        s = slots.get(pred)
        if s is None:
            items.append(MemoryItem(CURRENT_STATE, subject, scope, pred, None, "UNKNOWN", None, None, "FRESH",
                                    "OPERATIONAL", (), p.policy_version_id, None, p.authority_domain))
            continue
        items.append(_slot_item(s, subject, scope))
    return RetrievalResult(CURRENT_STATE, OK, tuple(items))


def _slot_item(s: StateSlot, subject: str, scope) -> MemoryItem:
    return MemoryItem(CURRENT_STATE, subject, scope, s.predicate, s.value, s.status, s.valid_from, s.valid_until,
                      s.freshness_status, s.usage, s.winning_claim_ids + s.conflict_claim_ids, s.policy_version,
                      s.source, s.authority_domain, state_version=s.state_version)


# --------------------------------------------------------------------------- search_history
def search_history(src: MemorySource, subject: str, predicate: Optional[str], now: float, caller: Caller,
                   valid_window: Optional[Tuple[float, float]] = None, limit: int = 50,
                   scope_type: str = SUPPORTED_SCOPE) -> RetrievalResult:
    """Immutable claims with temporal labels (§8). Never operational truth: usage is always HISTORICAL.

    Lifecycle handling:
    - quarantined, pending_erasure and invalidated claims are excluded;
    - never_true retractions are excluded (the claim was never true);
    - no_longer_true retractions appear as ENDED with their effective end."""
    scope = (scope_type, subject)
    if (r := _scope_check(HISTORY, scope)) is not None:
        return r
    if predicate is not None and predicate not in src.policies:
        return RetrievalResult(HISTORY, UNKNOWN_PREDICATE)
    if scope not in caller.authorized_scopes:
        return _denied(HISTORY)
    claims = _claims(src, subject, now)
    cs = _projection(src, subject, now, now)
    slots = dict(cs.slots)
    items = []
    for c in claims.values():
        pred = base_predicate(c.content.key)
        if predicate is not None and pred != predicate:
            continue
        p = src.policies.get(pred)
        if p is None or not may_read(caller, scope, p.security_class):
            continue
        st, cause, _ = status_at(c, now)
        if st in EXCLUDED or st == "not_yet" or (st == RETRACTED and cause == NEVER_TRUE):
            continue
        vf, vu = effective_interval(c, now, src.d)
        if valid_window is not None and not (vf < valid_window[1] and valid_window[0] < vu):
            continue
        if st == SUPERSEDED_BY_POLICY:
            label = H_SUPERSEDED_BY_POLICY
        elif requires_revalidation(p, c.content.policy_version):
            label = H_REVALIDATION_REQUIRED          # §10: kept for history and provenance, never operational
        else:
            label = _label(c, st, slots.get(pred), list(claims.values()), now, src.d, vu)
        if label == H_SUPERSEDED:
            vu = _superseded_end(c, list(claims.values()), vf, src.d)   # §8: a superseded value carries its end
        items.append(MemoryItem(HISTORY, subject, scope, c.content.key, c.content.value, label,
                                None if vf == float("-inf") else vf, None if vu == float("inf") else vu,
                                _freshness(p, c, now, _last_sync(src, subject, pred, now)),
                                HISTORICAL,
                                (c.id,) + tuple(e for e, _ in c.content.anchor), c.content.policy_version,
                                c.content.source, p.authority_domain, observed_at=c.content.observed_at))
    items.sort(key=lambda i: (-(i.observed_at or 0), i.provenance[0]))
    return RetrievalResult(HISTORY, OK, tuple(items[:limit]))


def _last_sync(src: MemorySource, subject: str, pred: str, now: float) -> Optional[float]:
    if src.view is not None:
        return _view_for(src, subject, now, now).last_sync(pred)
    return last_sync_from(src.journal, subject, pred, now)


def _label(c: Claim, st: str, slot: Optional[StateSlot], claims, now: float, d: Decisions, vu: float) -> str:
    if slot is not None and c.id in slot.winning_claim_ids:
        return H_CURRENT
    if slot is not None and c.id in slot.conflict_claim_ids:
        return H_IN_CONFLICT
    if st == RETRACTED or vu <= now:
        return H_ENDED
    same_key = [o for o in claims if o.content.key == c.content.key]
    if _superseded_read_time(c, same_key, now, now, d):
        return H_SUPERSEDED
    return H_NOT_SELECTED                                    # e.g. outranked by a higher-authority source


def _superseded_end(c: Claim, claims, vf: float, d: Decisions) -> float:
    """Read-time supersession: the value ends where the earliest later claim of the same source group starts."""
    grp = (c.content.source, c.content.source_member_id)
    order = (c.content.observed_at, c.content.observed_seq)
    starts = [asserted_interval(o, d)[0] for o in claims
              if o is not c and o.content.key == c.content.key
              and (o.content.source, o.content.source_member_id) == grp
              and (o.content.observed_at, o.content.observed_seq) >= order and asserted_interval(o, d)[0] > vf]
    return min(starts) if starts else float("inf")


def _freshness(p: PredicatePolicy, c: Claim, now: float, last_sync: Optional[float]) -> str:
    f = p.freshness
    if f.max_staleness is None:
        return "FRESH"
    ref = last_sync if f.freshness_source == "external_sync" else c.content.observed_at
    return "STALE" if ref is None or now - ref > f.max_staleness else "FRESH"


# --------------------------------------------------------------------------- search_memory (narrative)
def search_memory(src: MemorySource, subject: str, query: str, caller: Caller, limit: int = 10,
                  scope_type: str = SUPPORTED_SCOPE) -> RetrievalResult:
    """Deterministic structured search over narrative Episode summaries. Only summaries in state ``ok`` are
    eligible (quarantined, pending-erasure and regenerating summaries never surface). Ranking: query-token
    overlap, then recency, then episode id. No vectors."""
    scope = (scope_type, subject)
    if (r := _scope_check(NARRATIVE, scope)) is not None:
        return r
    if not may_read(caller, scope, "standard"):
        return _denied(NARRATIVE)
    q = set(tokens(query))
    scored = []
    for ep in src.episodes:
        if ep.subject_id != subject or ep.summary_status != "ok" or not ep.summary:
            continue
        if any(e in src.dead_evidence for e in ep.evidence_ids):
            continue
        overlap = len(q & set(tokens(ep.summary)))
        if q and overlap == 0:
            continue
        scored.append((-overlap, -ep.started_at, ep.episode_id, ep))
    scored.sort(key=lambda x: x[:3])
    items = tuple(MemoryItem(NARRATIVE, subject, scope, None, ("text", ep.summary), "NARRATIVE", ep.started_at,
                             ep.ended_at, "FRESH", HISTORICAL, tuple(ep.evidence_ids), None, None, None,
                             observed_at=ep.started_at) for *_, ep in scored[:limit])
    return RetrievalResult(NARRATIVE, OK, items)


# --------------------------------------------------------------------------- get_commitments
def get_commitments(src: MemorySource, subject: str, now: float, caller: Caller,
                    scope_type: str = SUPPORTED_SCOPE) -> RetrievalResult:
    """The existing evidence-backed commitment projection (R-10), with read-time expiry; erased evidence is
    rejected by the projection itself. C-E: only commitments whose recorded identity names this subject are
    served. Unscoped (identity-less) commitments are never served (fail closed). Commitments are presented under
    the subject's CUSTOMER scope; whether they are CUSTOMER- or relationship-scoped (agent × subject) remains an
    open Product/Security decision, and ``agent_id`` / ``tenant_id`` are carried so either can be enforced."""
    scope = (scope_type, subject)
    if (r := _scope_check(COMMITMENT, scope)) is not None:
        return r
    if not may_read(caller, scope, "standard"):
        return _denied(COMMITMENT)
    heads = CM.project(src.commitment_events, now, src.dead_evidence)
    items = tuple(MemoryItem(COMMITMENT, subject, scope, "commitment", None, h.state, None, h.due_until,
                             "FRESH", "OPERATIONAL", h.events, None, h.agent_id, h.tenant_id)
                  for k, h in sorted(heads.items()) if h.subject_id == subject)
    return RetrievalResult(COMMITMENT, OK, items)


# --------------------------------------------------------------------------- not modelled
def get_relationships(*_a, **_k) -> RetrievalResult:
    return RetrievalResult(RELATIONSHIP, UNSUPPORTED_CAPABILITY, reason="no relationship model in the prototype")


def get_tenant_knowledge(*_a, **_k) -> RetrievalResult:
    return RetrievalResult(TENANT_KNOWLEDGE, UNSUPPORTED_SCOPE,
                           reason="TENANT scope not modelled (S-3); Agent Knowledge read scope undefined (T-5)")
