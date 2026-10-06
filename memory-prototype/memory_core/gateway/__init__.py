"""Memory Gateway v0 (CUSTOMER scope): the caller-facing boundary over the proven core. TEST/PROTOTYPE ONLY.

Contract: ``investigation/memory-gateway-contract-v0.md``. A reference composition of EXISTING components only:
- caller binding: Lane A conversation handles (``memory_core.handle``: issue / verify / authorize, scope "person"),
  then the single read rule ``may_read`` through a ``Caller`` scoped to ("CUSTOMER", subject);
- write admission: the real Claim Gate (``decide``), and the real ``commit()`` used as a record factory on a
  throwaway store rebuilt from durable facts at the journal-assigned time (the bridge proven in
  next-architecture-work-decision-v1 §5), inside ``TimedJournal`` over any ``StorageBoundary``;
- reads: ``TimedJournal`` current reads (served position r, causal token), then typed retrieval over a source
  reconstructed from durable facts at r;
- context: the real Context Compiler; its output is returned as a separate data channel.

Nothing here changes the gate, the commit layer, the Pipeline harness or the storage boundary. Excluded from v0:
non-CUSTOMER scopes, erasure, identity events, Agent Knowledge, ``explain``, operator (non-handle) reads."""
import base64
import hashlib
import hmac
import json
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Sequence, Tuple

from .. import handle as H
from ..claimgate import Proposal, decide, fingerprint, is_observation
from ..commit import COMMITTED, CommitStore, commit, last_sync_from, rebuild_claims
from ..commit_time import JOURNAL, TimedJournal
from ..config import AMENDED
from ..context import CompiledContext, TaskProfile, compile_context
from ..durable_journal import Entry, reconstruct
from ..integration import empty_fence
from ..journal_compaction import OperationValidation
from ..model import Evidence
from ..projection_view import memory_source as view_source, open_view, scratch as view_scratch
from ..registry import Caller, PolicyRegistry, PredicatePolicy, resolve_slot
from ..retrieval import CONTRACT_SCOPES, SUPPORTED_SCOPE, MemorySource, RetrievalResult, get_current_state, \
    search_history
from ..state import _subject_claims, operational

# ----------------------------------------------------------------------------- typed results (contract §12)
HANDLE_REQUIRED, ACCESS_DENIED, INVALID_SCOPE, UNSUPPORTED_SCOPE = (
    "HANDLE_REQUIRED", "ACCESS_DENIED", "INVALID_SCOPE", "UNSUPPORTED_SCOPE")
APPENDED, DUPLICATE, STATE_CONFLICT, STALE_POLICY_STAMP, READ_CLOSED = (
    "APPENDED", "DUPLICATE", "STATE_CONFLICT", "STALE_POLICY_STAMP", "READ_CLOSED")
NOT_AN_OBSERVATION, NOT_A_COMMAND, GATE_REFUSED, EVIDENCE_ID_REUSED = (
    "NOT_AN_OBSERVATION", "NOT_A_COMMAND", "GATE_REFUSED", "EVIDENCE_ID_REUSED")
INVALID_CAUSAL_TOKEN, COMMAND_ID_REUSED = "INVALID_CAUSAL_TOKEN", "COMMAND_ID_REUSED"     # v0.1 (GW-1, GW-2)
TRANSIENT = ("READ_CLOSED", "COMMIT_TIME_REGRESSED")
MAX_TRANSIENT_RETRIES = 3                       # TEST_ONLY retry budget (the real budget is [OWNER] Infrastructure)

# The evidence store's storage guarantees are NOT specified by any contract (journal S1-S5 do not cover it).
# The Gateway states that explicitly instead of assuming durability, ordering, closure or transactions.
EVIDENCE_STORE_GUARANTEES = {
    "durability": "CONTRACT_GAP", "ordering": "CONTRACT_GAP", "closure": "CONTRACT_GAP",
    "transactions": "CONTRACT_GAP", "consistency": "CONTRACT_GAP",
    "established_semantics": "id reuse with different content is refused (existing ingest rule)",
}


@dataclass(frozen=True)
class WriteResult:
    status: str
    at: Optional[float] = None                  # journal-assigned commit time (APPENDED / DUPLICATE)
    reason: str = ""
    actual_version: Optional[int] = None        # STATE_CONFLICT only
    original: Optional[Tuple] = None            # DUPLICATE: the recorded original outcome
    attempts: int = 0                           # journal attempts made by this call (transient retries)
    token: Optional[str] = None                 # v0.1: signed causal token for `at` (APPENDED / DUPLICATE)


@dataclass(frozen=True)
class ReadResult:
    status: str                                 # "OK" or a typed refusal
    r: Optional[float] = None                   # served position (also the causal token for the next read)
    result: Optional[RetrievalResult] = None
    reason: str = ""
    token: Optional[str] = None                 # v0.1: signed causal token for `r`


@dataclass(frozen=True)
class ContextPackage:
    """The ONLY shape compile_context returns. Memory is a data channel: there is no instruction field, and the
    Gateway accepts no instruction text to merge it into."""
    status: str
    r: Optional[float]
    channel: str                                 # always "memory_data"
    memory_data: str                             # the compiler's framed, sanitised block
    manifest: Dict = field(default_factory=dict)


class Gateway:
    def __init__(self, policies: Sequence[PredicatePolicy], storage_factory: Callable, *, clock0: float = 0.0,
                 handle_secret: bytes = b"TEST_ONLY_gateway_handle_secret_"):
        self.registry = PolicyRegistry(allow_test_only=True)
        self.evidence: Dict[str, Evidence] = {}          # evidence store (guarantees: CONTRACT_GAP, see above)
        self.fence = empty_fence()
        self._gate_ledger: Dict = {}                     # v0.1: kept EMPTY. The gate gets a fresh ledger per call;
        #                                                  no in-process ledger ever decides an outcome (GW-3)
        self._pending: Dict = {}                         # (subject, command id) -> attested decision, until terminal
        self._secret = handle_secret
        # causal-token key: same custody class as the handle secret (C-1), domain-separated from the handle MAC
        self._token_key = hmac.new(handle_secret, b"olbrain-gateway-causal-token-v1", hashlib.sha256).digest()
        for p in policies:
            self.registry.publish(p)
        self.journal = TimedJournal(self.registry._v, JOURNAL, storage=storage_factory(self.registry._v))
        self.last_read_source: Optional[str] = None      # diagnostic only: "checkpoint" | "journal"
        for p in policies:
            self.journal.publish(p.predicate, p.policy_version_id, clock0)

    # Checkpoint consumer v1 / journal fast path v1.2: ONE optional journal_compaction.CheckpointStore, held by the
    # journal (derived acceleration, never truth). None = the v0.1 paths, unchanged. With it, a VALIDATED checkpoint
    # + suffix feeds reads, the write-path scratch store, and the journal's own trace/version lookups; any rejection
    # falls back to the authoritative replay.
    @property
    def checkpoints(self):
        return self.journal.checkpoints

    @checkpoints.setter
    def checkpoints(self, cps):
        self.journal.checkpoints = cps

    # ------------------------------------------------------------------ administration (not a v0 caller operation)
    def publish_policy(self, policy: PredicatePolicy, clock: float) -> float:
        self.registry.publish(policy)
        return self.journal.publish(policy.predicate, policy.policy_version_id, clock)

    @staticmethod
    def _key(subject: str) -> bytes:
        return (subject * 32).encode()[:32]             # TEST_ONLY key provider (custody C-1 is [OWNER])

    # ------------------------------------------------------------------ evidence and handles
    def ingest_evidence(self, ev: Evidence, clock: float, ttl: float = 1.0) -> Tuple[str, Optional[str]]:
        """Record evidence (no claim is created here) and issue the conversation-bound handle for its turn."""
        prior = self.evidence.get(ev.evidence_id)
        if prior is not None and prior != ev:
            return EVIDENCE_ID_REUSED, None
        self.evidence[ev.evidence_id] = ev
        self.fence.known_subjects.add(ev.subject_id)
        self.fence.org_of.setdefault(ev.subject_id, ev.org_id)
        return ev.evidence_id, self.issue_handle(ev.evidence_id, clock, ttl)

    def issue_handle(self, evidence_id: str, clock: float, ttl: float = 1.0) -> str:
        """Lane A issuance: org, agent and session of the evidence's conversation; subject = its root (no merges
        in v0, so the subject itself, member-set version 0); default assurance."""
        ev = self.evidence[evidence_id]
        return H.issue(self._secret, H.Handle(ev.org_id, ev.agent_id, ev.session_id, ev.subject_id, "anonymous",
                                              (), 0, clock + ttl))

    def _bind(self, token: Optional[str], subject: str, clock: float) -> Tuple[Optional[str], Optional[H.Handle]]:
        """C-4: a subject reference alone is never authority. Returns (refusal, handle)."""
        if not token:
            return HANDLE_REQUIRED, None
        try:
            h = H.verify(self._secret, token, clock)
            org = self.fence.org_of.get(subject)
            if org is None:
                return ACCESS_DENIED + ":unknown_subject", None
            H.authorize(h, subject_root=subject, subject_org=org, current_msv=0, scope="person")
        except H.HandleError as e:
            return ACCESS_DENIED + ":" + e.code, None
        return None, h

    # ------------------------------------------------------------------ causal tokens (GW-G3)
    def _sign_position(self, org: str, subject: str, position: float) -> str:
        body = json.dumps({"org": org, "subject": subject, "pos": position}, sort_keys=True).encode()
        mac = hmac.new(self._token_key, body, hashlib.sha256).hexdigest()
        return "ct." + base64.urlsafe_b64encode(body).decode() + "." + mac

    def _token_position(self, token: str, org: str, subject: str) -> Optional[float]:
        try:
            tag, b64, mac = token.split(".")
            body = base64.urlsafe_b64decode(b64.encode())
        except Exception:
            return None
        if tag != "ct" or not hmac.compare_digest(hmac.new(self._token_key, body, hashlib.sha256).hexdigest(), mac):
            return None
        try:
            d = json.loads(body)
            pos = float(d["pos"])
        except Exception:
            return None
        if d.get("org") != org or d.get("subject") != subject or not math.isfinite(pos):
            return None
        return pos

    def _causal_position(self, after, org: str, subject: str, clock: float) -> Tuple[bool, Optional[float]]:
        """GW-G3 hybrid: a finite number <= max(gateway clock, the subject's latest durable commit time), OR a valid
        Gateway-signed token for the same (org, subject). Decided BEFORE any closure; a read of durable facts only."""
        if after is None:
            return True, None
        if isinstance(after, str):
            pos = self._token_position(after, org, subject)
            return (pos is not None), pos
        if isinstance(after, bool) or not isinstance(after, (int, float)) or not math.isfinite(after):
            return False, None
        entries = self.journal.store.entries(subject)
        bound = max(clock, entries[-1].entry.at if entries else -math.inf)
        return (after <= bound), float(after)

    @staticmethod
    def _scope(scope: str) -> Optional[str]:
        if scope not in CONTRACT_SCOPES:
            return INVALID_SCOPE
        if scope != SUPPORTED_SCOPE:
            return UNSUPPORTED_SCOPE
        return None

    # ------------------------------------------------------------------ writes
    def propose_observation(self, token: Optional[str], pr: Proposal, clock: float) -> WriteResult:
        if not is_observation(pr):
            return WriteResult(NOT_AN_OBSERVATION, reason="typed writers use command()")
        return self._admit(token, pr, clock, None)

    def command(self, token: Optional[str], pr: Proposal, expected_version: Optional[int], clock: float
                ) -> WriteResult:
        if is_observation(pr):
            return WriteResult(NOT_A_COMMAND, reason="observations use propose_observation()")
        return self._admit(token, pr, clock, expected_version)

    def _outcome_of(self, subject: str, pid: str):
        for x in self.journal.store.entries(subject):
            if x.entry.idem == "outcome:" + pid:
                return x.entry.payload
        return None

    def _record(self, subject: str, pid: str, outcome: Tuple, clock: float) -> None:
        e = Entry(subject, "commit_outcome", "outcome:" + pid, 0.0, None, None, outcome)
        for _ in range(MAX_TRANSIENT_RETRIES + 1):
            st, _x = self.journal.commit(subject, "outcome:" + pid, None, None, clock,
                                         lambda at: [(Entry(e.partition, e.kind, e.idem, at, None, None, outcome),
                                                      None)])
            if st not in TRANSIENT:
                return

    def _view(self, facts, subject: str, r: float, op=None):
        return open_view(facts, subject, r, self.checkpoints, op=op) if self.checkpoints is not None else None

    def _scratch(self, subject: str, at: float, op=None):
        """A throwaway commit store at ``at`` plus its freshness input (predicate -> last sync time)."""
        facts = self.journal.store.facts()
        v = self._view(facts, subject, at, op)
        if v is not None:
            return view_scratch(v)                                     # validated checkpoint + suffix
        rb = reconstruct(facts, subject, at)                           # durable facts only
        js = list(rb.journal)
        return CommitStore(journal=js, claims=rebuild_claims(js)), (lambda pred: last_sync_from(js, subject, pred, at))

    def _admit(self, token, pr: Proposal, clock: float, expected_version: Optional[int]) -> WriteResult:
        # Per-operation validation reuse v1: ONE command = one operation. The gate scratch, the build scratch and
        # the build's version lookup share its checkpoint validation; the journal's in-write K9 check does not.
        with OperationValidation(pr.subject_id) as op:
            return self._admit_op(op, token, pr, clock, expected_version)

    def _admit_op(self, op, token, pr: Proposal, clock: float, expected_version: Optional[int]) -> WriteResult:
        refusal, _h = self._bind(token, pr.subject_id, clock)
        if refusal:
            return WriteResult(refusal)
        # K8: the duplicate is decided on the command id BEFORE any time is assigned. Namespace (GW-G1):
        # (org, subject, command id); the bound subject's partition is the only authority (GW-3).
        fp = fingerprint(pr)
        prior = self._outcome_of(pr.subject_id, pr.proposal_id)
        if prior is not None:
            if prior[-1] != fp:                          # GW-2: same id, different content: refused, not recorded
                return WriteResult(COMMAND_ID_REUSED, reason="command_id_reused_with_different_content")
            return WriteResult(DUPLICATE, at=prior[1], original=tuple(prior),
                               token=None if prior[1] is None else self._sign_position(pr.org_id, pr.subject_id,
                                                                                       prior[1]))
        # the gate (not a consumer: the commit step re-validates the stamp and OCC)
        p = self.registry.get(pr.predicate) if pr.predicate in self.registry._v else None
        if p is None:
            return self._terminal(pr, (GATE_REFUSED, None, "unknown_predicate"), clock)
        sc, sync = self._scratch(pr.subject_id, clock, op)
        current = resolve_slot(p, operational(_subject_claims(sc.claims, pr.subject_id), p, clock), clock, clock,
                               AMENDED, clock, sync(pr.predicate))
        out = self._pending.get((pr.subject_id, pr.proposal_id))   # optimisation for an unresolved transient only
        if out is None or out.fingerprint != fp:
            out = decide(pr, self.registry, self.evidence, current, clock, {})   # fresh ledger: no process state
        if out.draft is None:
            status = STALE_POLICY_STAMP if out.reason == "stale_policy_version" else GATE_REFUSED
            return self._terminal(pr, (status, None, out.reason), clock)
        built = {}

        def build(at):
            res = commit(self._scratch(pr.subject_id, at, op)[0], pr, out, self.evidence, self.fence, self._key, at,
                         expected_version=expected_version,
                         actual_version=self.journal._version(pr.subject_id, pr.predicate, at, op))
            built["res"] = res
            if res.status != COMMITTED:
                return []
            c = res.record.claim_content
            return [(Entry(c.subject_id, "claim", "claim:" + c.claim_id, at, pr.predicate, c.policy_version, None),
                     (c.subject_id, "c:" + c.claim_id, res.record))]

        attempts = 0
        while True:
            attempts += 1
            built.clear()
            st, x = self.journal.prepare(pr.subject_id, pr.proposal_id, pr.predicate, out.draft.policy_version,
                                         clock, build, expected_version)
            if st == "PREPARED":
                if not x.entries:                        # the commit layer refused (e.g. STATE_CONFLICT, fence)
                    res = built["res"]
                    sc_ = res.record.state_conflict if res.record is not None else None
                    status = STATE_CONFLICT if res.status == "STATE_CONFLICT" else GATE_REFUSED
                    return self._terminal(pr, (status, None, res.reason,
                                               sc_.actual_version if sc_ else None), clock, attempts)
                st, x = self.journal.finish(x)
            if st in TRANSIENT and attempts <= MAX_TRANSIENT_RETRIES:
                continue                                 # transient closure: a new time, every check again
            if st in TRANSIENT:
                self._pending[(pr.subject_id, pr.proposal_id)] = out   # not recorded: retry re-enters with it
                return WriteResult(READ_CLOSED, reason=st, attempts=attempts)
            if st == "DUPLICATE":                        # durable claim from an unacknowledged earlier attempt
                st = APPENDED
            if st == STATE_CONFLICT:                     # typed and terminal: NEVER retried by the Gateway
                return self._terminal(pr, (STATE_CONFLICT, None, "state_conflict", x), clock, attempts)
            if st == "STALE_POLICY_STAMP":
                return self._terminal(pr, (STALE_POLICY_STAMP, None, "stale_policy_stamp"), clock, attempts)
            if st == APPENDED:
                return self._terminal(pr, (APPENDED, x, ""), clock, attempts)
            return self._terminal(pr, (GATE_REFUSED, None, str(x)), clock, attempts)

    def _terminal(self, pr: Proposal, outcome: Tuple, clock: float, attempts: int = 0) -> WriteResult:
        self._pending.pop((pr.subject_id, pr.proposal_id), None)
        status, at, reason = outcome[0], outcome[1], outcome[2]
        actual = outcome[3] if len(outcome) > 3 else None
        self._record(pr.subject_id, pr.proposal_id, (status, at, reason, actual, fingerprint(pr)), clock)
        return WriteResult(status, at=at, reason=reason, actual_version=actual, attempts=attempts,
                           token=None if at is None else self._sign_position(pr.org_id, pr.subject_id, at))

    # ------------------------------------------------------------------ reads
    def _read(self, token, subject: str, clock: float, after: Optional[float], scope: str):
        if (bad := self._scope(scope)) is not None:
            return bad, None, None, None
        refusal, h = self._bind(token, subject, clock)
        if refusal:
            return refusal, None, None, None
        ok, pos = self._causal_position(after, h.org, subject, clock)   # GW-1: validated BEFORE any closure
        if not ok:
            return INVALID_CAUSAL_TOKEN, None, None, None
        with OperationValidation(subject) as op:                     # one read = one checkpoint validation
            sv = self.journal.read(subject, clock, after=pos, op=op)  # a current read: closed before it reads
            facts = self.journal.store.facts()
            v = self._view(facts, subject, sv.r, op)
        if v is not None:
            src = view_source(v)                                     # validated checkpoint + suffix (c, r]
        else:
            rb = reconstruct(facts, subject, sv.r)
            src = MemorySource(rb.journal, rb.policies, policy_history=facts.policy_history)
        self.last_read_source = "journal" if v is None else "checkpoint"
        self._last_org = h.org
        return None, sv.r, src, Caller(h.agent, frozenset({(SUPPORTED_SCOPE, h.subject)}))

    def get_current_state(self, token: Optional[str], subject: str, clock: float, *, predicate: Optional[str] = None,
                          after: Optional[float] = None, scope: str = SUPPORTED_SCOPE) -> ReadResult:
        refusal, r, src, caller = self._read(token, subject, clock, after, scope)
        if refusal:
            return ReadResult(refusal)
        return ReadResult("OK", r, get_current_state(src, subject, predicate, r, r, caller),
                          token=self._sign_position(self._last_org, subject, r))

    def search_history(self, token: Optional[str], subject: str, clock: float, *, predicate: Optional[str] = None,
                       after: Optional[float] = None, scope: str = SUPPORTED_SCOPE) -> ReadResult:
        refusal, r, src, caller = self._read(token, subject, clock, after, scope)
        if refusal:
            return ReadResult(refusal)
        return ReadResult("OK", r, search_history(src, subject, predicate, r, caller),
                          token=self._sign_position(self._last_org, subject, r))

    def compile_context(self, token: Optional[str], subject: str, profile: TaskProfile, budget: int, clock: float,
                        *, after: Optional[float] = None, request: Optional[Dict[str, str]] = None
                        ) -> ContextPackage:
        refusal, r, src, caller = self._read(token, subject, clock, after, SUPPORTED_SCOPE)
        if refusal:
            return ContextPackage(refusal, None, "memory_data", "", {})
        results = [get_current_state(src, subject, None, r, r, caller), search_history(src, subject, None, r, caller)]
        cc: CompiledContext = compile_context(results, profile, budget, caller.principal, dict(request or {}))
        return ContextPackage(cc.status, r, "memory_data", cc.text, dict(cc.manifest))
