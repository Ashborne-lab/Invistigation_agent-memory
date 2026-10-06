"""Context Compiler: authorized typed-retrieval results -> one labelled context package plus a manifest. Pure.

retrieval -> relevance selection (task profile) -> priority -> budget -> labelled text + manifest

The compiler:
- consumes ``RetrievalResult`` objects only. It never reads the journal or store, never resolves truth and never
  re-authorizes: an ACCESS_DENIED result contributes nothing;
- never calls an LLM and never mutates its inputs. It is deterministic.

Memory text is DATA. It is:
- sanitised with the Lane A ``sanitise_value``;
- bracket-escaped, so it cannot imitate the compiler's own labels;
- wrapped in the Lane A "not instructions" header.
"""
import hashlib
import json
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from ..model import CONFLICT, UNAVAILABLE, UNKNOWN
from ..normalise import sanitise_value
from ..render import FOOTER, HEADER
from ..retrieval import (ACCESS_DENIED, COMMITMENT, CURRENT_STATE, HISTORICAL, HISTORY, NARRATIVE, OK, MemoryItem,
                         RetrievalResult)

COMPILER_VERSION = "ctx-proto-1"
LABEL = {CURRENT_STATE: "CURRENT_STATE", HISTORY: "HISTORICAL", COMMITMENT: "COMMITMENT", NARRATIVE: "NARRATIVE"}
SECTION = {CURRENT_STATE: "## Current state (operational)",
           COMMITMENT: "## Commitments",
           HISTORY: "## History (past information; NOT current truth)",
           NARRATIVE: "## Narrative context (background only; not authoritative)"}
# compile status
COMPILED, NO_CONTEXT, BUDGET_INSUFFICIENT, MISSING_MANDATORY = (
    "COMPILED", "NO_CONTEXT", "BUDGET_INSUFFICIENT", "MISSING_MANDATORY")


@dataclass(frozen=True)
class TaskProfile:
    """A task's compilation policy. Every profile here is TEST_ONLY: production task policies are undecided."""
    name: str
    categories: Tuple[str, ...]                     # included retrieval types, in priority order
    predicates: Optional[FrozenSet[str]] = None     # relevant predicates (None = all); applies to state and history
    mandatory_predicates: FrozenSet[str] = frozenset()   # current-state items that must be present or nothing ships
    max_items: Mapping[str, int] = None             # per-category caps
    value_cap: int = 80                             # max characters of any memory value

    def __post_init__(self):
        if not self.name.startswith("TEST_ONLY_"):
            raise ValueError("task profiles are TEST_ONLY until production task policy is decided")


@dataclass(frozen=True)
class ManifestEntry:
    category: str
    label: str
    predicate: Optional[str]
    status: str
    freshness_status: str
    usage: str
    provenance: Tuple[str, ...]
    policy_version: Optional[int]
    chars: int = 0
    reason: str = ""                                # exclusion reason (excluded entries only)


@dataclass(frozen=True)
class CompiledContext:
    status: str
    text: str
    manifest: Mapping


# --------------------------------------------------------------------------- rendering (data, never instructions)
def _neutral(v: str, cap: int) -> str:
    return sanitise_value(v, cap).replace("[", "(").replace("]", ")")


def _t(x) -> str:
    return "open" if x is None else "d%g" % x


def _line(it: MemoryItem, cap: int) -> str:
    val = None if it.value is None else _neutral(it.value[1], cap)
    tags = [LABEL[it.retrieval_type]]
    if it.freshness_status == "STALE":
        tags.append("STALE")
    if it.retrieval_type == CURRENT_STATE:
        if it.status == CONFLICT:
            return "[%s][CONFLICT] %s: unresolved; sources disagree. Do not state a value; ask or escalate." % (
                tags[0], it.predicate)
        if it.status in (UNKNOWN, UNAVAILABLE):
            return "[%s] %s: %s" % (tags[0], it.predicate, it.status.lower())
        use = "" if it.usage == "OPERATIONAL" else "; use=" + it.usage
        return "[%s] %s = \"%s\" (since %s; source %s%s)" % (
            "][".join(tags), it.predicate, val, _t(it.valid_from), it.source, use)
    if it.retrieval_type == HISTORY:
        return "[%s][%s] %s was \"%s\" (valid %s..%s; source %s)" % (
            "][".join(tags), it.status, it.predicate, val, _t(it.valid_from), _t(it.valid_until), it.source)
    if it.retrieval_type == COMMITMENT:
        return "[%s] state=%s due=%s" % (tags[0], it.status, _t(it.valid_until))
    return "[%s] \"%s\" (%s..%s)" % ("][".join(tags), val, _t(it.valid_from), _t(it.valid_until))


def _entry(it: MemoryItem, chars: int = 0, reason: str = "") -> ManifestEntry:
    return ManifestEntry(it.retrieval_type, LABEL.get(it.retrieval_type, "?"), it.predicate, it.status,
                         it.freshness_status, it.usage, it.provenance, it.policy_version, chars, reason)


# --------------------------------------------------------------------------- compile
def compile_context(results: Sequence[RetrievalResult], profile: TaskProfile, budget: int, caller_principal: str,
                    manifest_info: Mapping[str, str]) -> CompiledContext:
    """Deterministic. ``budget`` is in characters of the final text (a TEST_ONLY size unit). ``caller_principal``
    is recorded only: authorization already happened in retrieval."""
    if any(not isinstance(r, RetrievalResult) for r in results):
        raise TypeError("compile_context accepts typed RetrievalResult objects only")
    auth = tuple(sorted((r.retrieval_type, r.status) for r in results))
    included: List[Tuple[MemoryItem, str]] = []
    excluded: List[ManifestEntry] = []
    seen_lines = set()
    caps = dict(profile.max_items or {})
    # 1. relevance selection + defensive checks, in profile priority order
    for rank, cat in enumerate(profile.categories):
        n = 0
        for r in results:
            if r.retrieval_type != cat or r.status != OK:
                continue                                    # denied / unsupported results contribute nothing
            for it in r.items:
                why = _reject(it, profile)
                line = None if why else _line(it, profile.value_cap)
                # narrative repeats are the same text at different times; history keeps distinct periods
                key = (NARRATIVE, it.value) if cat == NARRATIVE else line
                if not why and key in seen_lines:
                    why = "duplicate"
                if not why and cat in caps and n >= caps[cat]:
                    why = "category_cap"
                if why:
                    excluded.append(_entry(it, reason=why))
                    continue
                seen_lines.add(key)
                included.append((it, line))
                n += 1
    for r in results:                                      # categories this task does not use
        if r.status == OK and r.retrieval_type not in profile.categories:
            excluded.extend(_entry(it, reason="category_not_in_task_profile") for it in r.items)
    # 2. mandatory items must be present
    have = {it.predicate for it, _ in included if it.retrieval_type == CURRENT_STATE}
    missing = sorted(profile.mandatory_predicates - have)
    # 3. budget: mandatory first, then priority order; drop the lowest priority deterministically
    mand = [(it, ln) for it, ln in included if it.retrieval_type == CURRENT_STATE
            and it.predicate in profile.mandatory_predicates]
    rest = [(it, ln) for it, ln in included if (it, ln) not in mand]
    kept, dropped = _fit(mand, rest, budget)
    status = COMPILED if kept else NO_CONTEXT
    drop_reason = "budget"
    if missing:                                              # fail closed: a mandatory item is absent
        status, kept, dropped, drop_reason = MISSING_MANDATORY, [], included, "missing_mandatory"
    elif any(m not in kept for m in mand):                   # fail closed: mandatory items exceed the budget
        status, kept, dropped, drop_reason = BUDGET_INSUFFICIENT, [], included, "mandatory_exceeds_budget"
    text = _assemble(kept, profile.categories)
    excluded.extend(_entry(it, reason=drop_reason) for it, _ in dropped)
    manifest = {
        "compiler_version": COMPILER_VERSION,
        "request": dict(manifest_info),
        "task_profile": profile.name,
        "caller": caller_principal,
        "subject_scope": sorted({it.scope for r in results if r.status == OK for it in r.items}),
        "authorization": [list(a) for a in auth],
        "retrieval_types_used": sorted({it.retrieval_type for it, _ in kept}),
        "policy_versions": sorted({it.policy_version for it, _ in kept if it.policy_version is not None}),
        "included": [_entry(it, len(ln)).__dict__ for it, ln in kept],
        "excluded": [e.__dict__ for e in excluded],
        "missing_mandatory": missing,
        "truncation": {"budget": budget, "used": len(text), "dropped": sum(1 for e in excluded if e.reason == "budget")},
        "freshness": sorted({(it.predicate or it.retrieval_type, it.freshness_status) for it, _ in kept}),
        "status": status,
        "block_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    return CompiledContext(status, text, json.loads(json.dumps(manifest, default=list)))


def _reject(it: MemoryItem, p: TaskProfile) -> str:
    """Defense in depth on what retrieval already guarantees; never a substitute for it."""
    if it.retrieval_type in (CURRENT_STATE, HISTORY) and p.predicates is not None \
            and (it.predicate or "").split("[", 1)[0] not in p.predicates:
        return "not_relevant_to_task"
    if it.retrieval_type == HISTORY and it.usage != HISTORICAL:
        return "history_without_historical_usage"          # history can never be emitted as current truth
    if it.retrieval_type == NARRATIVE and it.usage != HISTORICAL:
        return "narrative_claims_authority"
    if it.retrieval_type == CURRENT_STATE and it.usage == HISTORICAL:
        return "historical_item_in_current_state"
    if it.retrieval_type == CURRENT_STATE and it.status == CONFLICT and it.value is not None:
        return "conflict_with_value"                        # a conflict never becomes a factual statement
    return ""


def _fit(mand, rest, budget):
    """Mandatory first, then strict priority order: the first item that does not fit ends inclusion, so only
    lower-priority material is ever dropped. Section order does not change the size."""
    kept = []
    order = mand + rest
    for i, x in enumerate(order):
        if len(_assemble(kept + [x], (CURRENT_STATE, COMMITMENT, HISTORY, NARRATIVE))) > budget:
            return kept, order[i:]
        kept.append(x)
    return kept, []


def _assemble(kept, order) -> str:
    if not kept:
        return ""
    parts = [HEADER]
    for cat in order:
        lines = [ln for it, ln in kept if it.retrieval_type == cat]
        if lines:
            parts.append(SECTION[cat])
            parts.extend(lines)
    parts.append(FOOTER)
    return "\n".join(parts)
