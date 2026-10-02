"""The acceptance gate (implementation spec §6). Pure.

The model proposes and this code decides. Proposals are checked
independently: one rejected proposal never blocks the others in its batch.
Fencing (E3) is not done here. It runs at commit (``memory_core.fence``).
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple

from ..config import Decisions
from ..model import AGENT, IMPORT_ROLE, OPERATOR_ROLE, SYSTEM_ROLE, TOOL, USER, Claim, Evidence
from ..normalise import (NORMALISERS, PLACEHOLDER, fold, future_marker, is_assent, is_interrogative,
                         resolve_time_expression, script_of, security_hit, tokens)
from ..policy import PredicatePolicy, lookup

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]{1,40})*$")
VALUE_KINDS = {"text", "enum", "none", "number", "bool"}

# Rejection codes (spec §6.1)
SCHEMA, UNKNOWN_KEY, SECURITY_KEY, GROUNDING, MODE, AUTHORITY, SENSITIVE, SUPPRESSED, RETRACT_TARGET = (
    "schema", "unknown_key", "security_key", "grounding", "mode", "authority", "sensitive", "suppressed",
    "retract_target")


@dataclass
class Rejection:
    code: str
    index: int
    key: str = ""
    evidence_id: str = ""
    detail: str = ""


@dataclass
class Accepted:
    kind: str                      # new_claim | support | retract
    index: int
    key: str
    value: Tuple[str, str]
    mode: str
    value_check: str
    normaliser_id: Optional[str]
    source: str
    source_member_id: str
    anchor: Tuple[Tuple[str, str], ...]
    prompt_ref: Optional[Tuple[str, str]]
    valid_from: Optional[float]
    valid_until: Optional[float]
    observed_at: float
    policy: PredicatePolicy
    target_claim_id: Optional[str] = None
    cause: Optional[str] = None
    input_evidence_ids: Tuple[str, ...] = ()


@dataclass
class GateResult:
    accepted: List[Accepted] = field(default_factory=list)
    rejections: List[Rejection] = field(default_factory=list)
    anomalies: List[Rejection] = field(default_factory=list)


def canonical(value: dict) -> Optional[Tuple[str, str]]:
    if not isinstance(value, dict) or value.get("kind") not in VALUE_KINDS:
        return None
    k = value["kind"]
    if k == "none":
        return ("none", "")
    v = value.get("v")
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if k == "bool":
        return ("bool", "true" if v in (True, "true", "True") else "false")
    return (k, fold(str(v)))


def _source_of(ev: Evidence) -> Optional[str]:
    return {USER: "USER", OPERATOR_ROLE: "OPERATOR", IMPORT_ROLE: "IMPORT"}.get(ev.author_role) or (
        ev.source_system if ev.author_role == TOOL else None)


def _grounded(quote: str, ev: Evidence, require_seal: bool = False) -> Tuple[bool, str]:
    if ev.author_role in (AGENT, SYSTEM_ROLE):
        return False, "agent_or_system_text"
    if ev.status != "active":
        return False, "evidence_" + ev.status
    if require_seal and ev.seal_state != "sealed":
        return False, "evidence_" + ev.seal_state            # red-team C-2: unsealed/tampered/withdrawn
    if PLACEHOLDER.match(ev.text or ""):
        return False, "placeholder"
    q = fold(quote)
    if not q or q not in fold(ev.text):
        return False, "quote_not_in_evidence"
    if ev.author_role == TOOL and ev.tool_args and q in fold(ev.tool_args):
        return False, "echo_of_agent_arguments"            # E1
    return True, ""


# LA-20 (held-out real-model run): "I work at TCS but I'm joining Infosys next month" — the sentence-level clause
# rejected the PRESENT fact. Clauses also split at commas and coordinating conjunctions (en/hi/te/Hinglish).
_CLAUSE = re.compile(r"[.!?\n।;,]+|\b(?:but|and|while|whereas|though|lekin|magar|par|aur|kintu)\b|लेकिन|मगर|और|కానీ|మరియు",
                     re.IGNORECASE)


def _clause(text: str, quote: str) -> str:
    """The sentence of ``text`` that contains ``quote`` (falls back to the whole text)."""
    q = fold(quote)
    for part in _CLAUSE.split(text or ""):
        if q and q in fold(part):
            return part
    return text or ""


def _value_in(quote: str, value: Tuple[str, str]) -> bool:
    kind, v = value
    if kind == "none":
        return True
    vt = tokens(v)
    qt = set(tokens(quote))
    return bool(vt) and all(t in qt for t in vt)


def _check_value(p: PredicatePolicy, mode: str, quote: str, value: Tuple[str, str], d: Decisions
                 ) -> Tuple[Optional[str], Optional[str], str]:
    """Returns (value_check or None to reject, normaliser_id, detail)."""
    if mode == "normalized":
        # "normalized" asserts that a registered normaliser produced the value, so it must have.
        if p.normaliser and fold(NORMALISERS[p.normaliser](quote) or "") == value[1]:
            return "verified", p.normaliser, ""
        if d.normalized_fallback_unverified and script_of(quote) != script_of(value[1]):
            return "unverified", None, "normaliser_coverage_gap"     # LA-14: keep, never as current state
        return None, None, "no_normaliser_maps_quote_to_value"
    if _value_in(quote, value):
        return "verified", None, ""
    if p.normaliser:
        out = NORMALISERS[p.normaliser](quote)
        if out is not None and fold(out) == value[1]:
            return "verified", p.normaliser, ""
    if mode == "confirmed":
        return None, None, "value_not_in_proposition"     # a confirmed value must come from the agent's proposition
    if d.unverified_scope == "cross_script_only" and script_of(quote) == script_of(value[1]):
        return None, None, "same_script_value_not_in_quote"      # finding F-1 amendment
    return "unverified", None, "value_not_deterministically_verifiable"


def gate(proposals: Sequence[dict], batch: Dict[str, Evidence], order: Sequence[str], candidates: Sequence[Claim],
         reg: Dict[str, PredicatePolicy], d: Decisions,
         is_suppressed: Callable[[str, str, float], bool] = lambda k, v, t: False,
         agent_purpose: FrozenSet[str] = frozenset(), via: str = "llm",
         pending: Optional[FrozenSet[str]] = None) -> GateResult:
    out = GateResult()
    active = [c for c in candidates if c.state.status == "active"]
    for i, pr in enumerate(proposals):
        r = _one(i, pr, batch, order, active, reg, d, is_suppressed, agent_purpose, via, out, pending)
        if isinstance(r, Rejection):
            out.rejections.append(r)
        elif r is not None:
            out.accepted.append(r)
    if d.drop_replacement_retractions:
        # LA-16: a retraction of a SINGLE-key value in the same evidence that asserts a different value for the
        # key is redundant with read-time supersession and harmful if the new value is later declared never_true.
        asserts = {(a.key, a.anchor[0][0]) for a in out.accepted if a.kind in ("new_claim", "support")
                   and a.policy.cardinality == "SINGLE"}
        keep = []
        for a in out.accepted:
            if a.kind in ("retract", "retract_record") and a.cause == "no_longer_true" and                     a.policy.cardinality == "SINGLE" and (a.key, a.anchor[0][0]) in asserts:
                out.rejections.append(Rejection(RETRACT_TARGET, a.index, a.key, a.anchor[0][0],
                                                "redundant_replacement_retraction"))
            else:
                keep.append(a)
        out.accepted = keep
    return out


def _one(i, pr, batch, order, active, reg, d, is_suppressed, purpose, via, out, pending=None):
    # 1 schema
    if not isinstance(pr, dict) or pr.get("op") not in ("assert", "retract"):
        return Rejection(SCHEMA, i, detail="op")
    key = pr.get("key", "")
    if not isinstance(key, str) or not KEY_RE.match(key):
        return Rejection(SCHEMA, i, key=str(key), detail="key_syntax")
    mode = pr.get("mode")
    if mode not in ("stated", "normalized", "confirmed", "inferred"):
        return Rejection(SCHEMA, i, key, detail="mode")
    anchors = pr.get("anchor")
    if not isinstance(anchors, list) or not anchors or not all(
            isinstance(a, dict) and a.get("evidence_id") and isinstance(a.get("quote"), str) for a in anchors):
        return Rejection(SCHEMA, i, key, detail="anchor")
    op = pr["op"]
    value = canonical(pr.get("value")) if op == "assert" or pr.get("value") else None
    if d.canonicalise_values and value is not None and value[0] == "text":
        p0 = lookup(reg, key)
        if p0 is not None and p0.normaliser:                  # LA-18: one canonical form per value
            c0 = NORMALISERS[p0.normaliser](pr["value"].get("v", ""))
            if c0:
                value = ("text", fold(c0))
    if op == "assert" and value is None:
        return Rejection(SCHEMA, i, key, detail="value")
    if op == "retract" and pr.get("cause") not in ("no_longer_true", "never_true"):
        return Rejection(SCHEMA, i, key, detail="retract_cause")
    # 2 key policy
    p = lookup(reg, key)
    if p is None:
        return Rejection(UNKNOWN_KEY, i, key)
    # 3 security lexicon (open namespaces)
    if p.is_namespace and p.security_class == "standard":
        leaf = key.split(".", 1)[1]
        if security_hit(leaf, value[1] if value else ""):
            rj = Rejection(SECURITY_KEY, i, key, detail="security_lexicon")
            out.anomalies.append(rj)
            return rj
    # 4 grounding
    srcs = set()
    for a in anchors:
        ev = batch.get(a["evidence_id"])
        if ev is None:
            return Rejection(GROUNDING, i, key, a["evidence_id"], "evidence_not_in_batch")
        if d.anchor_pending_only and pending is not None and a["evidence_id"] not in pending:
            return Rejection(GROUNDING, i, key, a["evidence_id"], "anchor_not_in_pending_turn")    # LA-13
        ok, why = _grounded(a["quote"], ev, d.require_seal)
        if not ok:
            return Rejection(GROUNDING, i, key, ev.evidence_id, why)
        srcs.add(_source_of(ev))
    if len(srcs) != 1 or None in srcs:
        return Rejection(SCHEMA, i, key, detail="mixed_or_unknown_source")
    source = srcs.pop()
    ev0 = batch[anchors[0]["evidence_id"]]
    quote = " ".join(a["quote"] for a in anchors)
    # 5 mode + 6 value check
    if mode not in p.modes:
        return Rejection(MODE, i, key, detail="mode_not_allowed_for_key")
    prompt_ref = None
    normaliser_id = None
    value_check = "verified"
    if op == "assert":
        if mode == "confirmed":
            pref = pr.get("prompt_ref")
            if not isinstance(pref, dict) or pref.get("evidence_id") not in batch:
                return Rejection(MODE, i, key, detail="confirmed_without_prompt_ref")
            aev = batch[pref["evidence_id"]]
            if aev.author_role != AGENT:
                return Rejection(MODE, i, key, detail="prompt_ref_not_agent")
            try:
                ai, ui = order.index(aev.evidence_id), order.index(ev0.evidence_id)
            except ValueError:
                return Rejection(MODE, i, key, detail="order")
            if ui != ai + 1:
                return Rejection(MODE, i, key, detail="prompt_ref_not_immediately_preceding")
            if fold(pref.get("quote", "")) not in fold(aev.text) or not pref.get("quote"):
                return Rejection(MODE, i, key, detail="prompt_ref_quote_not_in_agent_text")
            if not is_interrogative(aev.text):
                return Rejection(MODE, i, key, detail="agent_turn_not_a_proposal")
            ok, why = is_assent(quote)
            if not ok:
                return Rejection(MODE, i, key, detail="not_assent:" + why)
            vc, nid, det = _check_value(p, "confirmed", pref["quote"], value, d)
            if vc is None:
                return Rejection(MODE, i, key, detail="value_not_in_proposition")
            value_check, normaliser_id = vc, nid
            prompt_ref = (aev.evidence_id, pref["quote"])
            source = "USER"
        elif mode == "inferred":
            if d.r_m1_inference != "store_labelled":
                return Rejection(MODE, i, key, detail="inference_not_persisted_r_m1")
            value_check = "unverified"
        else:
            vc, nid, det = _check_value(p, mode, quote, value, d)
            if vc is None:
                return Rejection(MODE, i, key, detail=det)
            value_check, normaliser_id = vc, nid
    # 7 authority
    if via == "llm" and p.llm_write_mode != "PROPOSE_VIA_GATE":
        rj = Rejection(AUTHORITY, i, key, detail="llm_write_" + p.llm_write_mode.lower())
        if p.security_class == "identity_security":
            out.anomalies.append(rj)
        return rj
    if source not in p.allowed_sources:
        return Rejection(AUTHORITY, i, key, detail="source_not_allowed:" + source)
    # 8 sensitivity
    if p.security_class == "sensitive" and p.key not in purpose:
        return Rejection(SENSITIVE, i, key, detail="purpose_not_declared")
    vf, vu, _prec = resolve_time_expression((pr.get("valid_time") or {}).get("expression"), ev0.observed_at)
    # red-team M-7: a current-state assertion carrying a future/intent marker must assert future validity
    # Lane A finding LA-2: checking only the quote is bypassed by minimal quotes ("Pune" out of "I'm moving
    # to Pune next month"); the rule inspects the clause of the evidence that contains each quote.
    if (d.future_marker_rule and op == "assert" and p.current_state_eligible
            and any(future_marker(_clause(batch[a["evidence_id"]].text, a["quote"])) for a in anchors)
            and (vf is None or vf <= ev0.observed_at)):
        return Rejection(MODE, i, key, ev0.evidence_id, "future_without_validity")
    ids = tuple(a["evidence_id"] for a in anchors) + ((prompt_ref[0],) if prompt_ref else ())
    common = dict(index=i, key=key, mode=mode, value_check=value_check, normaliser_id=normaliser_id,
                  source=source, source_member_id=ev0.source_member_id,
                  anchor=tuple((a["evidence_id"], a["quote"]) for a in anchors), prompt_ref=prompt_ref,
                  valid_from=vf, valid_until=vu, observed_at=ev0.observed_at, policy=p, input_evidence_ids=ids)
    if op == "retract":
        tgt = None
        for c in active:
            if c.content.key != key:
                continue
            if d.retract_observed_before and c.content.observed_at > ev0.observed_at:
                continue            # finding F-7: a retraction never reaches a claim observed after it
            if d.retract_same_group and (c.content.source, c.content.source_member_id) != (source, ev0.source_member_id):
                continue            # finding F-8: one member's words never retract another member's claim (R2)
            if pr.get("target") and c.id == pr["target"]:
                tgt = c
            elif value is not None and c.content.value == value:
                tgt = c
        if tgt is None:
            if d.retraction_records and value is not None:
                # LA-9: record the retraction even with no target yet; it applies to matching claims committed
                # later from evidence observed before it (out-of-order extraction must not escape it)
                return Accepted(kind="retract_record", value=value, target_claim_id=None, cause=pr["cause"],
                                **common)
            return Rejection(RETRACT_TARGET, i, key, detail="no_active_target")
        return Accepted(kind="retract", value=tgt.content.value, target_claim_id=tgt.id, cause=pr["cause"],
                        **common)
    # 9 suppression
    if is_suppressed(key, value[1], ev0.observed_at):
        return Rejection(SUPPRESSED, i, key, ev0.evidence_id)
    # 10 dedup / support: only within the same source group (finding F-6: dedup across sources would fold
    # e.g. an HR_SYSTEM confirmation into a USER claim and lose its authority)
    if d.dedup_mode == "per_evidence":
        return Accepted(kind="new_claim", value=value, **common)    # LA-11: dedup happens at read time
    for c in active:
        same_group = c.content.source == source and c.content.source_member_id == ev0.source_member_id
        if c.content.key == key and c.content.value == value and (d.dedup_scope == "any" or same_group):
            return Accepted(kind="support", value=value, target_claim_id=c.id, **common)
    return Accepted(kind="new_claim", value=value, **common)
