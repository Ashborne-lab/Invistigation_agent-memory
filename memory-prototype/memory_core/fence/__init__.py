"""The E3 commit fence (RECON §7.1 E3; implementation spec §10.2 step 5). Pure.

It is evaluated once per derived write, over every input evidence item.
A write that fails the fence is rejected whole; it is never committed
with an input left out.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

COMMIT, REJECT, QUARANTINE, DEFER = "commit", "reject", "quarantine", "defer"
DEAD = {"erased", "pending_erasure", "invalidated", "context_suppressed"}


@dataclass(frozen=True)
class Stamp:
    evidence_id: str
    exists: bool
    status: str
    epochs: Dict[str, int]                 # {"org": n, "subject": n, "session": n}
    scope_ids: Dict[str, str]              # {"org": "org:o1", "subject": "subject:s1", ...}
    merge_ids_at_ingestion: Tuple[str, ...]
    source_subject_id: str
    observed_at: float
    transient_unavailable: bool = False


@dataclass
class Context:
    epoch_log: Dict[str, List[Tuple[int, str, float]]]   # scope id -> [(epoch, cause, at)]
    merged_into: Dict[str, Tuple[str, str]]               # subject -> (survivor, merge_id)
    merges_undone: Set[str]
    subject_erased_at: Dict[str, float]
    org_erased_at: Dict[str, float]
    org_of: Dict[str, str]
    known_subjects: Set[str]
    q17_recovery: bool = False


@dataclass
class Result:
    action: str
    reason: str = ""
    target_subject: Optional[str] = None
    merges_recorded: Tuple[str, ...] = ()
    attributed: bool = True


def fence(inputs: Sequence[Stamp], ctx: Context, max_hops: int = 8) -> Result:
    if not inputs:
        return Result(REJECT, "no_inputs")
    # (a) input evidence must exist and be alive
    for s in inputs:
        if s.transient_unavailable:
            return Result(DEFER, "transient:" + s.evidence_id)
        if not s.exists or s.status in DEAD:
            return Result(REJECT, "a:evidence_%s:%s" % ("missing" if not s.exists else s.status, s.evidence_id))
    # (b) any generation advance not caused by a merge since ingestion
    for s in inputs:
        for kind, n in s.epochs.items():
            for (epoch, cause, _at) in ctx.epoch_log.get(s.scope_ids[kind], []):
                if epoch > n and cause != "merge":
                    return Result(REJECT, "b:%s_advanced_by_%s" % (kind, cause))
    # (c) follow merged_into; any erased subject on the path, or an erased org, rejects
    earliest = min(s.observed_at for s in inputs)
    src = inputs[0].source_subject_id
    path, seen, traversed = [src], {src}, []
    cur = src
    while cur in ctx.merged_into:
        nxt, mid = ctx.merged_into[cur]
        if nxt in seen or len(path) > max_hops:
            return Result(REJECT, "c:merge_loop")
        if nxt not in ctx.known_subjects:
            return Result(REJECT, "c:unresolvable_link")
        traversed.append(mid)
        path.append(nxt)
        seen.add(nxt)
        cur = nxt
    for subj in path:
        at = ctx.subject_erased_at.get(subj)
        if at is not None and at >= earliest:
            return Result(REJECT, "c:subject_on_path_erased:" + subj)
        org = ctx.org_of.get(subj)
        oat = ctx.org_erased_at.get(org) if org else None
        if oat is not None and oat >= earliest:
            return Result(REJECT, "c:org_erased")
    recorded = tuple(sorted(set(m for s in inputs for m in s.merge_ids_at_ingestion) | set(traversed)))
    undone = [m for m in recorded if m in ctx.merges_undone]
    if undone:
        if ctx.q17_recovery:
            # recovery derives NEW claims from the member's own evidence (Q17); not merge-epoch content
            return Result(COMMIT, "q17_recovery", target_subject=src, merges_recorded=())
        return Result(QUARANTINE, "recorded_merge_undone:" + ",".join(undone), target_subject=src,
                      merges_recorded=recorded, attributed=False)
    return Result(COMMIT, "", target_subject=path[-1], merges_recorded=recorded)
