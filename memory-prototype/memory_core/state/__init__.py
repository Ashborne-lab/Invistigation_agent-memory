"""Current State projection (Subject Head). Pure; a projection of the commit journal, never a second truth.

Responsibilities, unchanged:
- claims and lifecycle come from the commit journal;
- the Lane A resolver (through ``registry.resolve_slot``) decides values;
- this module only materialises slots and versions them.

There is no caller, no authorization (contract §6 step 9 stays in ``registry.authorize``), no LLM, and no hidden
state. Every input is an argument.

``state_version`` is a deterministic function of the journal. For each slot, it is the number of journal
prefixes at which the slot's SEMANTIC signature changed, each prefix evaluated at its own entry time. Rebuilding
from the journal therefore reproduces the live versions exactly.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..commit import SUPERSEDED_BY_POLICY, JournalEntry, _insert, _transition, apply_retraction, last_sync_from
from ..config import AMENDED, Decisions
from ..model import Claim, SlotResult
from ..registry import PredicatePolicy, Resolved, requires_revalidation, resolve_slot
from ..temporal import status_at

SCOPE_TYPE = "CUSTOMER"


@dataclass(frozen=True)
class StateSlot:
    subject_id: str
    predicate: str                     # predicate, or predicate[map_key] for a MAP key slot
    scope: Tuple[str, str]             # (scope type, scope id)
    policy_version: int                # the version actually used to resolve (explicit)
    status: str
    value: Optional[Tuple[str, str]]
    elements: Tuple                    # SET: (value, element_status, claim_ids)
    keys: Tuple[Tuple[str, "StateSlot"], ...]   # MAP: per-key slots
    winning_claim_ids: Tuple[str, ...]  # provenance references
    conflict_claim_ids: Tuple[str, ...]
    valid_from: Optional[float]
    valid_until: Optional[float]
    freshness_status: str              # separate from validity (§3)
    usage: str                         # OPERATIONAL | DISPLAY_ONLY | REFRESH_REQUIRED | NONE
    authority_domain: str
    source: Optional[str]
    state_version: int


@dataclass(frozen=True)
class CurrentState:
    subject_id: str
    as_of: float
    now: float
    claims_version: int                # claims committed for this subject; never an expected_version
    slots: Tuple[Tuple[str, StateSlot], ...]
    unprojected_keys: Tuple[str, ...]  # claim keys with no policy (no fallback; reported, never guessed)
    revalidation_required: Tuple[str, ...] = ()   # claim ids bound to a pre-breaking policy (§10): not operational

    def slot(self, predicate: str) -> StateSlot:
        return dict(self.slots)[predicate]


# --------------------------------------------------------------------------- helpers
def base_predicate(key: str) -> str:
    return key.split("[", 1)[0]


def semantic_signature(slot: SlotResult, value_of: Mapping[str, Tuple[str, str]]) -> tuple:
    """What counts as a CHANGE for state_version: status, value, the SET elements' values and statuses, and the
    set of conflicting VALUES. Claim ids are deliberately excluded, so a new supporting claim for the same value
    does not advance the version."""
    return (slot.status, slot.value, tuple((v, st) for v, st, _ in slot.elements),
            tuple(sorted({value_of[i] for i in slot.conflict_claim_ids})))


def _replay(entries: Iterable[JournalEntry], claims: Dict[str, Claim], retractions: List) -> None:
    """Apply journal entries to a claim map (the commit layer's own recorded-outcome rules)."""
    for e in entries:
        if e.kind == "claim":
            _insert(claims, e.payload, retractions, e.at)
        elif e.kind == "retraction":
            retractions.append(e.payload)
            for c in claims.values():
                apply_retraction(e.payload, c, e.at)
        elif e.kind == "lifecycle":
            cid, t = e.payload
            _transition(claims[cid], t)


def operational(claims: Sequence[Claim], p: PredicatePolicy, cutoff: float) -> List[Claim]:
    """Claims allowed to construct operational truth under policy ``p`` (contract §10): never one superseded by
    policy, and never one bound to a version older than a breaking change (REVALIDATION_REQUIRED)."""
    return [c for c in claims if status_at(c, cutoff)[0] != SUPERSEDED_BY_POLICY
            and not requires_revalidation(p, c.content.policy_version)]


def _subject_claims(claims: Mapping[str, Claim], subject: str) -> List[Claim]:
    return [c for c in claims.values() if c.content.subject_id == subject]


def _resolve(p: PredicatePolicy, claims: Sequence[Claim], as_of: float, now: float, d: Decisions,
             last_sync: Optional[float]) -> Resolved:
    return resolve_slot(p, list(claims), as_of, now, d, now, last_sync)


def _signature(p: PredicatePolicy, claims: Sequence[Claim], t: float, d: Decisions) -> Dict[str, tuple]:
    """Semantic signatures of every slot of one predicate at time t (as_of = cutoff = t). For a MAP, one per key
    plus the map itself."""
    r = _resolve(p, claims, t, t, d, t)            # freshness is not part of the signature; last_sync irrelevant
    vo = {c.id: c.content.value for c in claims}
    out = {p.predicate: semantic_signature(r.slot, vo)}
    if p.cardinality == "MAP":
        per = {k: semantic_signature(rk.slot, vo) for k, rk in r.keys.items()}
        out[p.predicate] = tuple(sorted(per.items()))
        out.update({f"{p.predicate}[{k}]": s for k, s in per.items()})
    return out


# --------------------------------------------------------------------------- state_version over the journal
def slot_versions(journal: Sequence[JournalEntry], policies: Mapping[str, PredicatePolicy], subject: str,
                  d: Decisions = AMENDED, incremental: bool = True, now: Optional[float] = None,
                  policy_history: Optional[Mapping[str, Mapping[int, PredicatePolicy]]] = None,
                  trace: Optional[Dict[str, List[tuple]]] = None) -> Dict[str, int]:
    """state_version per slot over explicit EVALUATION POINTS (contract G6 / decision S-2):
    - every journal entry, at its commit time;
    - every validity-boundary instant (valid_from / valid_until) of a claim already known, as its OWN point at
      that exact instant, ordered before entries with the same time;
    - policy publications (journal entries of kind "policy"), evaluated under the policy in force at each point.

    Reads create no points: ``now`` only bounds which boundaries have occurred. The version history is therefore
    a function of the facts alone, and a later read's history extends an earlier read's (history stability).

    ``incremental`` (the live path) evaluates only the slots a point touches; ``incremental=False`` (the rebuild
    path) evaluates every slot at every point. The two must agree."""
    import heapq
    claims: Dict[str, Claim] = {}
    retractions: List = []
    versions: Dict[str, int] = {}
    last: Dict[str, tuple] = {}
    in_force: Dict[str, int] = {}                 # journaled policy publications
    pending: List[Tuple[float, int, str]] = []    # (boundary instant, tie, predicate) of known claims
    tie = [0]

    def evaluate(t: float, touched: set):
        preds = touched if incremental else {base_predicate(c.content.key) for c in claims.values()}
        mine = _subject_claims(claims, subject)
        for pred in sorted(preds & set(policies)):
            p = policies[pred]
            if policy_history and pred in in_force:       # the version in force at THIS point
                p = policy_history[pred][in_force[pred]]
            if not p.current_state_eligible:
                continue
            empty = _signature(p, [], t, d)
            for slot_key, sig in _signature(p, operational(mine, p, t), t, d).items():
                if slot_key not in last and sig == empty[slot_key]:
                    continue                      # never-populated slot: no version yet
                if last.get(slot_key) != sig:
                    last[slot_key] = sig
                    versions[slot_key] = versions.get(slot_key, 0) + 1
                    if trace is not None:              # version -> the state it denotes (history stability)
                        trace.setdefault(slot_key, []).append((versions[slot_key], sig))

    def drain(upto: float):
        while pending and pending[0][0] <= upto:
            b = pending[0][0]
            group = set()
            while pending and pending[0][0] == b:
                group.add(heapq.heappop(pending)[2])
            evaluate(b, group)

    for e in sorted(journal, key=lambda x: x.seq):
        drain(e.at)                                   # boundaries at or before this entry come first
        _replay([e], claims, retractions)
        if e.kind == "policy":
            in_force[e.payload[0]] = e.payload[1]
        if e.kind == "claim":
            c = e.payload.claim_content
            for b in (c.valid_from, c.valid_until):
                if b is not None and b > e.at:
                    tie[0] += 1
                    heapq.heappush(pending, (b, tie[0], base_predicate(c.key)))
        evaluate(e.at, _touched(e, claims))
    if now is not None:
        drain(now)
    return versions


def _touched(e: JournalEntry, claims: Mapping[str, Claim]) -> set:
    if e.kind == "policy":
        return {e.payload[0]}                 # a publication may change resolution (contract 2: MAY advance)
    if e.kind == "sync":
        return set()                         # freshness is not part of the version signature
    if e.kind == "claim":
        return {base_predicate(e.payload.claim_content.key)}
    if e.kind == "retraction":
        return {base_predicate(e.payload.key)}
    cid, _ = e.payload
    return {base_predicate(claims[cid].content.key)}


# --------------------------------------------------------------------------- the projection
def project_subject(claims: Sequence[JournalEntry], lifecycle_events: Sequence[JournalEntry],
                    policies: Mapping[str, PredicatePolicy], as_of: float, now: float, *, subject: str,
                    d: Decisions = AMENDED, incremental: bool = False,
                    policy_history: Optional[Mapping[str, Mapping[int, PredicatePolicy]]] = None,
                    trace: Optional[Dict[str, List[tuple]]] = None) -> CurrentState:
    """Project one subject's Current State from committed claim entries plus recorded lifecycle, retraction and
    external-sync entries. Fully rebuildable: the result depends only on the arguments. Freshness comes ONLY from
    recorded sync entries (C-C), never from a caller-supplied value."""
    journal = sorted(list(claims) + list(lifecycle_events), key=lambda x: x.seq)
    state: Dict[str, Claim] = {}
    _replay(journal, state, [])
    mine = _subject_claims(state, subject)
    versions = slot_versions(journal, policies, subject, d, incremental=incremental, now=now,
                             policy_history=policy_history, trace=trace)
    keys = {base_predicate(c.content.key) for c in mine}
    slots, unprojected, reval = [], [], []
    for pred in sorted(keys):
        p = policies.get(pred)
        if p is None:
            unprojected.append(pred)
            continue
        reval.extend(c.id for c in mine if base_predicate(c.content.key) == pred
                     and requires_revalidation(p, c.content.policy_version)
                     and status_at(c, now)[0] != SUPERSEDED_BY_POLICY)
        if not p.current_state_eligible:
            continue
        r = _resolve(p, operational(mine, p, now), as_of, now, d, last_sync_from(journal, subject, pred, now))
        slots.append((pred, _slot(subject, pred, p, r, versions)))
    cv = sum(1 for e in journal if e.kind == "claim" and e.payload.claim_content.subject_id == subject)
    return CurrentState(subject, as_of, now, cv, tuple(slots), tuple(unprojected), tuple(sorted(reval)))


def _slot(subject: str, key: str, p: PredicatePolicy, r: Resolved, versions: Mapping[str, int]) -> StateSlot:
    s = r.slot
    children = tuple((k, _slot(subject, f"{key}[{k}]", p, rk, versions)) for k, rk in sorted(r.keys.items()))
    return StateSlot(subject, key, (SCOPE_TYPE, subject), p.policy_version_id, s.status, s.value, s.elements,
                     children, s.winning_claim_ids, s.conflict_claim_ids, s.valid_from, s.valid_until,
                     s.freshness_status, r.usage, s.authority_domain, s.source, versions.get(key, 0))
