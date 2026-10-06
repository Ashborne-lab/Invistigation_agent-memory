"""In-memory end-to-end pipeline (TEST ONLY): the completed components wired together, with no new semantics.

    Evidence -> Policy Registry -> Claim Gate -> Commit / Journal -> Current State -> Typed Retrieval -> Context

No Firestore, PostgreSQL, Redis, network, LLM or embeddings. Every component is the real one; this module only
holds the in-memory stores and passes values between them.

**Durable facts.** A rebuild may use only these:
- the policy history;
- the evidence store;
- the journal, plus the commit ledger;
- per-subject keys (custody is open: C-1);
- episodes and commitment events.

Everything else is derived. ``rebuild()`` re-derives from those facts alone and never re-runs the gate.
"""
import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .. import commitments as CM
from ..claimgate import GateOutcome, Proposal, decide, is_observation
from ..commit import (CommitResult, CommitStore, RetractionRecord, SyncRecord, commit, last_sync_from, lifecycle,
                      rebuild_claims, record_policy, record_sync, retract, supersede_by_policy)
from ..config import AMENDED, Decisions
from ..context import CompiledContext, TaskProfile, compile_context
from ..fence import Context
from ..model import Episode, Evidence, SlotResult
from ..registry import Caller, PolicyRegistry, PredicatePolicy, PublishReport, Resolved, resolve_slot
from ..retrieval import (MemorySource, RetrievalResult, get_commitments, get_current_state, search_history,
                         search_memory)
from ..state import CurrentState, _replay, _subject_claims, operational, project_subject


def empty_fence() -> Context:
    return Context(epoch_log={}, merged_into={}, merges_undone=set(), subject_erased_at={}, org_erased_at={},
                   org_of={}, known_subjects=set())


@dataclass
class Pipeline:
    registry: PolicyRegistry = field(default_factory=lambda: PolicyRegistry(allow_test_only=True))
    store: CommitStore = field(default_factory=CommitStore)
    evidence: Dict[str, Evidence] = field(default_factory=dict)      # append-only evidence store
    gate_ledger: Dict = field(default_factory=dict)
    fence_ctx: Context = field(default_factory=empty_fence)
    keys: Dict[str, bytes] = field(default_factory=dict)
    episodes: List[Episode] = field(default_factory=list)
    commitment_events: List[CM.Event] = field(default_factory=list)
    dead_evidence: frozenset = frozenset()
    d: Decisions = AMENDED

    # ------------------------------------------------------------------ policy and evidence
    def publish(self, p: PredicatePolicy, now: float = 0.0) -> PublishReport:
        """Publish, and journal the publication as an evaluation point (state_version stays monotonic)."""
        rep = self.registry.publish(p)
        record_policy(self.store, p.predicate, p.policy_version_id, now)
        return rep

    def policies(self) -> Dict[str, PredicatePolicy]:
        return {pred: self.registry.get(pred) for pred in self.registry._v}

    def ingest(self, ev: Evidence) -> None:
        """Evidence is recorded on its own, before and independently of any proposal derived from it."""
        prior = self.evidence.get(ev.evidence_id)
        if prior is not None and prior != ev:
            raise ValueError("evidence_id reused with different content")
        self.evidence[ev.evidence_id] = ev
        self.fence_ctx.known_subjects.add(ev.subject_id)
        self.fence_ctx.org_of.setdefault(ev.subject_id, ev.org_id)

    def _key(self, subject: str) -> bytes:
        return self.keys.setdefault(subject, (subject * 32).encode()[:32])   # TEST_ONLY key provider (C-1 open)

    # ------------------------------------------------------------------ the write path
    def current_for(self, subject: str, predicate: str, now: float) -> Resolved:
        """The slot's current resolved state as the gate needs it, derived from the journal alone."""
        p = self.registry.get(predicate)
        claims: Dict = {}
        _replay(sorted(self.store.journal, key=lambda e: e.seq), claims, [])
        mine = operational(_subject_claims(claims, subject), p, now)
        return resolve_slot(p, mine, now, now, self.d, now, last_sync_from(self.store.journal, subject, predicate, now))

    def propose(self, pr: Proposal, now: float, expected_version: Optional[int] = None
                ) -> Tuple[GateOutcome, CommitResult]:
        """LLM observation or typed command -> gate (deterministic) -> commit of the attested decision only."""
        current = self.current_for(pr.subject_id, pr.predicate, now) if pr.predicate in self.registry._v else \
            None
        if current is None:                   # unknown predicate: the gate refuses (no fallback); nothing resolves
            current = Resolved(SlotResult(key=pr.predicate, status="UNKNOWN"))
        out = decide(pr, self.registry, self.evidence, current, now, self.gate_ledger)
        actual = self.project(pr.subject_id, now).slot_version(pr.predicate)
        res = commit(self.store, pr, out, self.evidence, self.fence_ctx, self._key, now,
                     expected_version=None if is_observation(pr) else expected_version, actual_version=actual)
        return out, res

    def retract(self, r: RetractionRecord, now: float) -> CommitResult:
        return retract(self.store, r, now)

    def lifecycle(self, claim_id: str, to: str, cause: str, now: float) -> CommitResult:
        return lifecycle(self.store, claim_id, to, cause, now)

    def supersede_by_policy(self, old_id: str, new_id: str, now: float) -> CommitResult:
        return supersede_by_policy(self.store, old_id, new_id, now)

    def sync(self, r: SyncRecord, now: float) -> CommitResult:
        return record_sync(self.store, r, now)

    # ------------------------------------------------------------------ the read path
    def project(self, subject: str, now: float, as_of: Optional[float] = None, incremental: bool = True
                ) -> "Projected":
        j = self.store.journal
        cs = project_subject([e for e in j if e.kind == "claim"], [e for e in j if e.kind != "claim"],
                             self.policies(), now if as_of is None else as_of, now, subject=subject, d=self.d,
                             incremental=incremental, policy_history=self.registry._v)
        return Projected(cs)

    def source(self) -> MemorySource:
        return MemorySource(tuple(self.store.journal), self.policies(), tuple(self.episodes),
                            tuple(self.commitment_events), self.dead_evidence, self.d, self.registry._v)

    def retrieve(self, subject: str, now: float, caller: Caller, query: str = "") -> List[RetrievalResult]:
        s = self.source()
        return [get_current_state(s, subject, None, now, now, caller), get_commitments(s, subject, now, caller),
                search_history(s, subject, None, now, caller), search_memory(s, subject, query, caller)]

    def context(self, subject: str, now: float, caller: Caller, profile: TaskProfile, budget: int,
                query: str = "", info: Optional[dict] = None) -> CompiledContext:
        return compile_context(self.retrieve(subject, now, caller, query), profile, budget, caller.principal,
                               info or {"request_id": "TEST_ONLY"})

    # ------------------------------------------------------------------ rebuild
    def rebuild(self) -> "Pipeline":
        """A fresh pipeline from durable facts only. Claims are re-derived from the journal; the gate is NOT
        re-run (recorded outcomes are applied as recorded)."""
        reg = PolicyRegistry(allow_test_only=self.registry.allow_test_only)
        reg._v = {k: dict(v) for k, v in self.registry._v.items()}   # published versions are immutable
        p = Pipeline(registry=reg, evidence=copy.deepcopy(self.evidence),
                     fence_ctx=copy.deepcopy(self.fence_ctx), keys=dict(self.keys),
                     episodes=list(self.episodes), commitment_events=list(self.commitment_events),
                     dead_evidence=self.dead_evidence, d=self.d)
        p.store.journal = copy.deepcopy(self.store.journal)
        p.store.records = copy.deepcopy(self.store.records)
        p.store.claims = rebuild_claims(p.store.journal)
        return p


@dataclass(frozen=True)
class Projected:
    state: CurrentState

    def slot_version(self, predicate: str) -> int:
        slots = dict(self.state.slots)
        return slots[predicate].state_version if predicate in slots else 0
