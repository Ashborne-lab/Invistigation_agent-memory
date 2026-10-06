"""Checkpoint-aware ProjectionView: what consumers read instead of a journal view. TEST/PROTOTYPE ONLY.

Contract: ``investigation/checkpoint-consumer-interface-v1.md``.

    journal facts -> (authoritative replay) -> validated checkpoint + suffix -> ProjectionView -> Gateway / Retrieval

A ProjectionView is a read representation of ONE partition at ONE served position r. It is derived, never stored,
and never a fact. ``open_view`` returns one only when a checkpoint passed every validation check and was advanced
through the durable suffix (c, r]. Otherwise it returns None, and the consumer MUST use its existing authoritative
journal path unchanged. An erased partition never gets a view.

What it carries is exactly what the proven consumers need (contract §2): the current state, the version trace, the
policies visible at r and the policy history, the partition's claim map (lifecycle included), the max sync time per
predicate, commitment events, and episode generations. It carries no journal entries, no idempotency outcomes and
no history before r.
"""
import copy
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple

from ..commit import CommitStore
from ..config import AMENDED, Decisions
from ..journal_compaction import CheckpointStore, _finalize, checkpoint_fold
from ..retrieval import MemorySource
from ..state import CurrentState


@dataclass(frozen=True)
class ProjectionView:
    subject: str                       # partition identity
    r: float                           # the served position this view answers for
    covered_at: float                  # c of the validated checkpoint it was built from (diagnostic)
    policies: Mapping                  # policy context: the versions visible at r
    policy_history: Mapping
    state: CurrentState                # current state at as_of = now = r
    trace: Mapping                     # version trace (history stability)
    claims: Mapping                    # the partition's claim map at r (provenance, lifecycle)
    sync: Mapping[str, float]          # freshness: max synced_at per predicate for this subject at r
    commitment_events: Tuple
    generations: Mapping

    def last_sync(self, predicate: str) -> Optional[float]:
        return self.sync.get(predicate)


def open_view(facts, subject: str, r: float, cps: Optional[CheckpointStore],
              d: Decisions = AMENDED, op=None) -> Optional[ProjectionView]:
    """A ProjectionView of ``subject`` at r from a validated checkpoint plus the suffix, or None (fall back to the
    authoritative journal path). ``op``: the calling operation's checkpoint validations."""
    hit = checkpoint_fold(facts, subject, r, cps, d, op=op)
    if hit is None:
        return None
    cp, f = hit
    if f.erased:
        return None                                    # erasure: the journal path answers
    rb = _finalize(f, facts, r, d)
    return ProjectionView(subject, r, cp.covered_at, rb.policies, facts.policy_history, rb.state, rb.trace,
                          f.claims, dict(f.sync), tuple(f.events), dict(f.generations))


class _NoJournal(tuple):
    """The journal of a view-backed source: any access is a defect (a consumer that still needs the journal must
    not be routed through a view)."""

    def __iter__(self):
        raise AssertionError("a view-backed MemorySource has no journal")

    def __getitem__(self, i):
        raise AssertionError("a view-backed MemorySource has no journal")


def memory_source(v: ProjectionView) -> MemorySource:
    """The retrieval source for a view. It answers current state and history at r only (``retrieval`` raises on any
    other position)."""
    return MemorySource(_NoJournal(), v.policies, policy_history=v.policy_history, view=v)


def scratch(v: ProjectionView) -> Tuple[CommitStore, Callable[[str], Optional[float]]]:
    """A throwaway commit store for the gate and ``commit()`` at r, plus the freshness input. The claims are
    deep-copied every time because ``commit`` mutates its store. No journal entry is synthesized."""
    return CommitStore(journal=[], claims=copy.deepcopy(dict(v.claims))), v.last_sync
