"""The current-state and historical resolver (implementation spec §8). Pure.

``resolve(policy, claims, as_of, cutoff)`` returns a contract §11 result.
The LLM never takes part in resolution.

Supersession, read-time mode (the spec default):
- A claim is superseded at valid time t by a later-observed claim from the
  same source group, when t lies in that later claim's supersession interval.
- Which interval counts is set by ``Decisions.supersession_interval``
  (finding F-2): "asserted" uses the later claim's own asserted interval;
  "effective_overlap" is the literal E7 wording.

Independent source groups (distinct source class or member) never supersede
one another. At equal authority rank, incompatible values give CONFLICT
(contract Ex.7; identity rule R2).
"""
from typing import Dict, List, Optional, Sequence

from ..config import Decisions
from ..model import CONFLICT, EXPLICIT_NONE, SUPERSEDED, UNKNOWN, VALUE, Claim, SlotResult
from ..policy import PredicatePolicy
from ..temporal import asserted_interval, covers, effective_interval, eligible_at, ended_by_retraction, freshness, status_at


def _group(c: Claim):
    return (c.content.source, c.content.source_member_id)


def admissible(p: PredicatePolicy, c: Claim, d: Decisions) -> bool:
    """Red-team M-8 / R-16: a claim must satisfy the CURRENT policy's admission rules to take part."""
    if not d.policy_admission_filter:
        return True
    if c.content.source not in p.allowed_sources:
        return False
    if c.content.written_via == "llm" and p.llm_write_mode != "PROPOSE_VIA_GATE":
        return False
    return True


def _order(c: Claim):
    return (c.content.observed_at, c.content.observed_seq)


def _successor_vf(c: Claim, by_id: Dict[str, Claim], d: Decisions) -> Optional[float]:
    if c.state.superseded_by and c.state.superseded_by in by_id:
        return asserted_interval(by_id[c.state.superseded_by], d)[0]
    return None


def resolve(p: PredicatePolicy, claims: Sequence[Claim], as_of: float, cutoff: float, d: Decisions,
            now: Optional[float] = None, key: Optional[str] = None) -> SlotResult:
    key = key or p.key
    now = cutoff if now is None else now
    mine = [c for c in claims if c.content.key == key and admissible(p, c, d)]
    by_id = {c.id: c for c in mine}
    elig = [c for c in mine if eligible_at(c, cutoff, d.supersession_storage_mode)]
    base = dict(key=key, authority_domain=p.authority_domain, policy_version=p.version)
    if p.cardinality == "SET":
        return _resolve_set(p, elig, as_of, cutoff, d, now, base, by_id)
    cands = [c for c in elig if covers(effective_interval(c, cutoff, d, _successor_vf(c, by_id, d)), as_of)]
    if d.supersession_storage_mode == "persisted":
        winners = [c for c in cands if status_at(c, cutoff)[0] != SUPERSEDED]
    else:
        winners = [c for c in cands if not _superseded_read_time(c, elig, as_of, cutoff, d)]
    # a claim whose source the policy does not accept never resolves the slot
    winners = [c for c in winners if c.content.source in p.allowed_sources]
    if winners:
        top = max(p.authority_rank.get(c.content.source, 0) for c in winners)
        winners = [c for c in winners if p.authority_rank.get(c.content.source, 0) == top]
    values = sorted({c.content.value for c in winners})
    if len(values) > 1:
        return SlotResult(status=CONFLICT, conflict_claim_ids=tuple(sorted(c.id for c in winners)),
                          note="incompatible values from independent sources/members", **base)
    if len(values) == 1:
        ws = sorted(winners, key=lambda c: c.id)
        if p.requires_verified_for_slot and p.current_state_eligible and all(
                c.content.value_check != "verified" for c in ws):
            return SlotResult(status=UNKNOWN, note="winning claim unverified (M9): " + ",".join(c.id for c in ws),
                              **base)
        v = values[0]
        last = max((e.observed_at for c in ws for e in c.state.support.values()), default=None)
        vf, vu = effective_interval(ws[0], cutoff, d, _successor_vf(ws[0], by_id, d))
        return SlotResult(status=EXPLICIT_NONE if v[0] == "none" else VALUE, value=None if v[0] == "none" else v,
                          winning_claim_ids=tuple(c.id for c in ws), valid_from=vf, valid_until=vu,
                          source=ws[0].content.source, freshness_status=freshness(last, now, p.freshness_days),
                          **base)
    # no survivor
    for c in elig:
        vf, _ = asserted_interval(c, d)
        if vf <= as_of and ended_by_retraction(c, cutoff) and not covers(effective_interval(c, cutoff, d), as_of):
            return SlotResult(status=p.clear_outcome, note="value ended by retraction (policy clear_outcome)",
                              **base)
    return SlotResult(status=UNKNOWN, **base)


def _superseded_read_time(c: Claim, elig: List[Claim], t: float, cutoff: float, d: Decisions) -> bool:
    for o in elig:
        if o is c or _group(o) != _group(c):
            continue
        if _order(o) < _order(c):
            continue
        if _order(o) == _order(c):
            # LA-20: one message stating a current and a future value is a planned transition: the claim with the
            # later asserted start supersedes the other over its own interval (otherwise: false CONFLICT)
            if not (asserted_interval(o, d)[0] > asserted_interval(c, d)[0]):
                continue
        iv = asserted_interval(o, d) if d.supersession_interval == "asserted" else effective_interval(o, cutoff, d)
        if covers(iv, t):
            return True
    return False


def _resolve_set(p, elig, t, cutoff, d, now, base, by_id) -> SlotResult:
    elems = {}
    for c in elig:
        v = c.content.value
        live = covers(effective_interval(c, cutoff, d), t)
        st = "ACTIVE" if live else ("RETRACTED" if ended_by_retraction(c, cutoff) else "ENDED")
        prev = elems.get(v)
        rank = {"ACTIVE": 3, "RETRACTED": 2, "ENDED": 1}      # deterministic: independent of claim order
        if prev is None or rank[st] > rank[prev[0]]:
            elems[v] = (st, [c.id])
        elif st == prev[0]:
            prev[1].append(c.id)
    elements = tuple(sorted((v[1], st, tuple(sorted(ids))) for v, (st, ids) in elems.items()))
    act = [e for e in elements if e[1] == "ACTIVE"]
    return SlotResult(status=VALUE if act else UNKNOWN, elements=elements,
                      winning_claim_ids=tuple(i for e in act for i in e[2]), **base)
