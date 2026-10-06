"""Predicate Policy Registry: contract §3 data model, validation, write gating, resolution and step-9 authorization.

Pure. It supersedes ``memory_core.policy`` as the contract-shaped registry. The old module is kept unchanged
because the Lane A suites depend on it. Resolution of SINGLE/SET reuses the Lane A bitemporal resolver
(``memory_core.resolve``) through ``_legacy``; this module adds what that resolver lacks:
- MAP;
- STATE_MACHINE;
- the freshness contract;
- operations gated by status;
- versioned publication;
- authorization as a separate final step.

Contract references:
- §3: policy structure, freshness contract, status gating, cardinality;
- §5: authority is predicate-specific;
- §6: authorization is not part of state resolution;
- §10: policy migration;
- §11: result granularity.
"""
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from ..config import Decisions
from ..model import ACCESS_DENIED, CONFLICT, EXPLICIT_NONE, UNAVAILABLE, UNKNOWN, VALUE, Claim, SlotResult
from ..policy import PredicatePolicy as _LegacyPolicy
from ..resolve import resolve as _legacy_resolve

# --------------------------------------------------------------------------- vocabularies (closed)
CARDINALITIES = frozenset({"SINGLE", "SET", "ORDERED_SET", "MAP", "STATE_MACHINE", "COUNTER"})
IMPLEMENTED = frozenset({"SINGLE", "SET", "MAP", "STATE_MACHINE"})   # ORDERED_SET / COUNTER: no domain needs them yet
SINGLE_STATUSES = frozenset({VALUE, EXPLICIT_NONE, UNKNOWN, CONFLICT})
SET_STATUSES = frozenset({VALUE, UNKNOWN})                          # collection-level gate for SET
OPERATIONS = frozenset({"SET", "ESTABLISH", "TRANSITION", "RESOLVE_CONFLICT", "CLEAR", "ADD", "REMOVE",
                        "PUT_KEY", "REMOVE_KEY"})
BLIND_WRITES = frozenset({"SET", "ESTABLISH", "TRANSITION", "PUT_KEY", "ADD"})   # forbidden under CONFLICT (§3)
WRITERS = frozenset({"llm_extractor", "user_command", "operator", "system_sync", "import"})
LLM_WRITE_MODES = frozenset({"FORBIDDEN", "PROPOSE_VIA_GATE", "TYPED_COMMAND"})
SECURITY_CLASSES = frozenset({"standard", "sensitive", "identity_security"})
TEMPORAL_MODELS = frozenset({"stable", "volatile", "expiring"})
STALE_READ = frozenset({"READ_ALLOWED", "DISPLAY_ONLY", "REQUIRES_REFRESH", "UNAVAILABLE"})
STALE_WRITE = frozenset({"WRITE_ALLOWED", "WRITE_FORBIDDEN", "REQUIRES_REFRESH"})
FRESHNESS_SOURCES = frozenset({"observed_at", "external_sync"})
# Usage label attached to a resolved result after the freshness contract is applied.
OPERATIONAL, DISPLAY_ONLY, REFRESH_REQUIRED, NO_USE = "OPERATIONAL", "DISPLAY_ONLY", "REFRESH_REQUIRED", "NONE"


class PolicyError(ValueError):
    """A policy failed validation. ``errors`` lists every violated rule."""

    def __init__(self, predicate: str, errors: List[str]):
        super().__init__(f"{predicate}: " + "; ".join(errors))
        self.errors = errors


class UnknownPredicate(KeyError):
    """No published policy. There is no fallback policy (contract §3: the registry is mandatory)."""


# --------------------------------------------------------------------------- data model
@dataclass(frozen=True)
class FreshnessContract:
    max_staleness: Optional[float] = None             # days; None = no staleness budget
    stale_read_policy: str = "READ_ALLOWED"
    stale_write_policy: str = "WRITE_ALLOWED"
    freshness_source: str = "observed_at"             # external_sync: measured from the last successful sync


@dataclass(frozen=True)
class ConflictPolicy:
    resolve_operation: str = "RESOLVE_CONFLICT"
    resolvers: FrozenSet[str] = frozenset({"operator"})   # writers allowed to perform the resolve operation


@dataclass(frozen=True)
class PredicatePolicy:
    predicate: str
    policy_version_id: int
    cardinality: str
    allowed_writers: FrozenSet[str]
    allowed_sources: FrozenSet[str]
    allowed_operations_by_status: Mapping[str, FrozenSet[str]]
    authority_domain: str
    authority_rank: Mapping[str, int]                  # contract `resolution_policy`: per-source rank in this domain
    temporal_model: str = "stable"
    conflict_policy: ConflictPolicy = ConflictPolicy()
    security_class: str = "standard"
    retention_class: str = ""                          # required; values are governance (G5), not engineering
    current_state_eligible: bool = True
    llm_write_mode: str = "FORBIDDEN"
    freshness: FreshnessContract = FreshnessContract()
    map_keys: FrozenSet[str] = frozenset()             # MAP: the bounded key set
    transitions: Mapping[str, FrozenSet[str]] = field(default_factory=dict)   # STATE_MACHINE: state -> next states
    initial_states: FrozenSet[str] = frozenset()       # STATE_MACHINE: states ESTABLISH may enter
    # §10 policy migration. ``breaking`` is declared by the policy author; a cardinality change is always breaking.
    # Claims bound to a version below ``revalidate_before`` are REVALIDATION_REQUIRED (excluded from operational
    # truth) unless this version explicitly grandfathers prior claims. ``revalidate_before`` is set by publish().
    breaking: bool = False
    grandfather_prior_claims: bool = False
    revalidate_before: int = 0

    def __post_init__(self):                           # freeze the mappings so a published policy cannot change
        for name in ("allowed_operations_by_status", "authority_rank", "transitions"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def validate_policy(p: PredicatePolicy) -> List[str]:
    """Every rule a policy must satisfy before publication. Returns all violations (empty = valid)."""
    e = []
    if p.cardinality not in CARDINALITIES:
        e.append(f"unknown cardinality {p.cardinality}")
    elif p.cardinality not in IMPLEMENTED:
        e.append(f"cardinality {p.cardinality} declared by the contract but not implemented in this registry")
    if not p.allowed_writers or not p.allowed_writers <= WRITERS:
        e.append("allowed_writers empty or outside the writer vocabulary")
    if not p.allowed_sources:
        e.append("allowed_sources empty")
    if set(p.authority_rank) != set(p.allowed_sources):
        e.append("authority_rank must rank exactly the allowed_sources")
    if p.llm_write_mode not in LLM_WRITE_MODES:
        e.append("bad llm_write_mode")
    if ("llm_extractor" in p.allowed_writers) != (p.llm_write_mode == "PROPOSE_VIA_GATE"):
        e.append("llm_extractor is an allowed writer iff llm_write_mode == PROPOSE_VIA_GATE")
    if p.security_class not in SECURITY_CLASSES:
        e.append("bad security_class")
    if p.security_class == "identity_security" and (p.llm_write_mode != "FORBIDDEN"
                                                    or {"llm_extractor", "user_command"} & p.allowed_writers):
        e.append("identity_security predicates: no LLM or user writes under any framing (§5 account_role)")
    if p.temporal_model not in TEMPORAL_MODELS:
        e.append("bad temporal_model")
    if not p.retention_class:
        e.append("retention_class must be declared")
    f = p.freshness
    if f.stale_read_policy not in STALE_READ or f.stale_write_policy not in STALE_WRITE \
            or f.freshness_source not in FRESHNESS_SOURCES:
        e.append("bad freshness contract vocabulary")
    if f.freshness_source == "external_sync" and f.max_staleness is None:
        e.append("external_sync freshness requires max_staleness")
    # status gating
    ops = p.allowed_operations_by_status
    needed = SET_STATUSES if p.cardinality == "SET" else SINGLE_STATUSES
    if missing := needed - set(ops):
        e.append(f"allowed_operations_by_status missing {sorted(missing)}")
    for st, allowed in ops.items():
        if not allowed <= OPERATIONS:
            e.append(f"unknown operation under {st}")
    if CONFLICT in ops:
        if p.conflict_policy.resolve_operation not in ops[CONFLICT]:
            e.append("CONFLICT must allow the policy's resolve operation")
        if ops[CONFLICT] & BLIND_WRITES:
            e.append("CONFLICT must not allow blind writes (§3)")
        if not p.conflict_policy.resolvers or not p.conflict_policy.resolvers <= p.allowed_writers:
            e.append("conflict resolvers must be allowed writers")
    if p.cardinality == "MAP" and not p.map_keys:
        e.append("MAP requires a bounded map_keys set")
    if p.cardinality == "STATE_MACHINE":
        states = set(p.transitions)
        if not states:
            e.append("STATE_MACHINE requires transitions")
        if any(not t <= states for t in p.transitions.values()):
            e.append("transition target is not a declared state")
        if not p.initial_states or not p.initial_states <= states:
            e.append("initial_states must be non-empty declared states")
    return e


# --------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class PublishReport:
    predicate: str
    policy_version_id: int
    cardinality_changed: bool       # true -> §10 policy migration applies; old claims keep their pinned version


TEST_ONLY = "TEST_ONLY_"


def is_test_only(p: PredicatePolicy) -> bool:
    """Policies whose governance values are placeholders. Never production policy."""
    return p.predicate.startswith(TEST_ONLY) or p.retention_class.startswith(TEST_ONLY)


class PolicyRegistry:
    """Append-only, versioned. A published version never changes; reads pin a version.

    ``allow_test_only`` must be set explicitly to accept TEST_ONLY_* policies (placeholder governance values),
    so they can never enter a registry that is not a test registry."""

    def __init__(self, allow_test_only: bool = False):
        self._v: Dict[str, Dict[int, PredicatePolicy]] = {}
        self.allow_test_only = allow_test_only

    def publish(self, p: PredicatePolicy) -> PublishReport:
        if errs := validate_policy(p):
            raise PolicyError(p.predicate, errs)
        if is_test_only(p) and not self.allow_test_only:
            raise PolicyError(p.predicate, ["TEST_ONLY policy refused by a non-test registry"])
        hist = self._v.setdefault(p.predicate, {})
        if hist and p.policy_version_id <= max(hist):
            raise PolicyError(p.predicate, [f"version {p.policy_version_id} not above current {max(hist)}"])
        prev = hist[max(hist)] if hist else None
        card_changed = prev is not None and prev.cardinality != p.cardinality
        breaking = prev is not None and (p.breaking or card_changed)
        if breaking and not p.grandfather_prior_claims:
            rb = p.policy_version_id
        else:
            rb = prev.revalidate_before if prev else 0
        p = replace(p, breaking=breaking, revalidate_before=rb)
        hist[p.policy_version_id] = p
        return PublishReport(p.predicate, p.policy_version_id, card_changed)

    def get(self, predicate: str, version: Optional[int] = None) -> PredicatePolicy:
        hist = self._v.get(predicate)
        if not hist:
            raise UnknownPredicate(predicate)
        if version is None:
            return hist[max(hist)]
        if version not in hist:
            raise UnknownPredicate(f"{predicate}@{version}")
        return hist[version]

    def versions(self, predicate: str) -> Tuple[int, ...]:
        return tuple(sorted(self._v.get(predicate, {})))


def requires_revalidation(p: PredicatePolicy, claim_policy_version: int) -> bool:
    """§10: a claim bound to an older version than a breaking change is never silently reinterpreted."""
    return claim_policy_version < p.revalidate_before


# --------------------------------------------------------------------------- resolution (steps 1-8, no caller)
@dataclass(frozen=True)
class Resolved:
    """A resolved slot plus what the freshness contract permits it to be used for."""
    slot: SlotResult
    usage: str = OPERATIONAL
    keys: Mapping[str, "Resolved"] = field(default_factory=dict)   # MAP only: per-key results
    security_class: str = "standard"


def map_claim_key(predicate: str, map_key: str) -> str:
    return f"{predicate}[{map_key}]"


def _legacy(p: PredicatePolicy) -> _LegacyPolicy:
    return _LegacyPolicy(key=p.predicate, version=p.policy_version_id,
                         cardinality="SET" if p.cardinality == "SET" else "SINGLE",
                         allowed_sources=p.allowed_sources, authority_rank=dict(p.authority_rank),
                         llm_write_mode=p.llm_write_mode, current_state_eligible=p.current_state_eligible,
                         authority_domain=p.authority_domain, security_class=p.security_class)


def _freshness(p: PredicatePolicy, slot: SlotResult, claims: Sequence[Claim], now: float,
               last_sync: Optional[float]) -> str:
    f = p.freshness
    if f.max_staleness is None or slot.status not in (VALUE, EXPLICIT_NONE):
        return "FRESH"
    if f.freshness_source == "external_sync":
        # §3: observed_at does not prove freshness for an externally owned value; only the sync time does.
        return "STALE" if last_sync is None or now - last_sync > f.max_staleness else "FRESH"
    won = [c.content.observed_at for c in claims if c.id in slot.winning_claim_ids]
    return "STALE" if not won or now - max(won) > f.max_staleness else "FRESH"


def _apply_freshness(p: PredicatePolicy, slot: SlotResult, fresh: str) -> Resolved:
    slot = replace(slot, freshness_status=fresh)
    if fresh != "STALE":
        return Resolved(slot, OPERATIONAL, security_class=p.security_class)
    rp = p.freshness.stale_read_policy
    if rp == "UNAVAILABLE":
        return Resolved(replace(slot, status=UNAVAILABLE, value=None, note="stale beyond max_staleness"), NO_USE,
                        security_class=p.security_class)
    usage = {"READ_ALLOWED": OPERATIONAL, "DISPLAY_ONLY": DISPLAY_ONLY, "REQUIRES_REFRESH": REFRESH_REQUIRED}[rp]
    return Resolved(slot, usage, security_class=p.security_class)


def resolve_slot(p: PredicatePolicy, claims: Sequence[Claim], as_of: float, cutoff: float, d: Decisions,
                 now: float, last_sync: Optional[float] = None) -> Resolved:
    """Contract §6 steps 1-8 under the system's authoritative policy. Deliberately takes no caller."""
    if p.cardinality not in IMPLEMENTED:
        raise PolicyError(p.predicate, [f"cardinality {p.cardinality} not implemented"])
    lp = _legacy(p)
    if p.cardinality == "MAP":
        per = {}
        for k in sorted(p.map_keys):
            ck = map_claim_key(p.predicate, k)
            mine = [c for c in claims if c.content.key == ck]
            s = _legacy_resolve(lp, mine, as_of, cutoff, d, now=now, key=ck)
            per[k] = _apply_freshness(p, s, _freshness(p, s, mine, now, last_sync))
        top = SlotResult(key=p.predicate, status=VALUE if any(r.slot.status == VALUE for r in per.values())
                         else UNKNOWN, authority_domain=p.authority_domain, policy_version=p.policy_version_id)
        return Resolved(top, OPERATIONAL, MappingProxyType(per), p.security_class)
    mine = [c for c in claims if c.content.key == p.predicate]
    s = _legacy_resolve(lp, mine, as_of, cutoff, d, now=now)
    if p.cardinality == "STATE_MACHINE" and s.status == VALUE and s.value[1] not in p.transitions:
        s = replace(s, status=UNKNOWN, value=None, note=f"value {s.value[1]!r} is not a declared state")
    return _apply_freshness(p, s, _freshness(p, s, mine, now, last_sync))


# --------------------------------------------------------------------------- write gating
@dataclass(frozen=True)
class WriteCommand:
    predicate: str
    policy_version_id: int
    op: str
    writer: str
    source: str
    value: Optional[str] = None
    map_key: Optional[str] = None


@dataclass(frozen=True)
class WriteDecision:
    allowed: bool
    reason: str = "ok"


ASSERTION_OPS = frozenset({"SET", "ADD", "PUT_KEY"})   # what an extracted observation may propose


def check_write(p: PredicatePolicy, cmd: WriteCommand, current: Resolved, assertion: bool = False) -> WriteDecision:
    """Validate a write against the policy and the slot's CURRENT resolved status (§3, §7).

    ``assertion=True`` marks an extracted OBSERVATION (evidence that becomes a claim; resolution decides), not a
    state COMMAND. Observations are not status-gated, carry no resolver / transition / stale-write semantics, and
    may only use ``ASSERTION_OPS``. Structural rules (declared map keys, declared states) still apply."""
    def no(r):
        return WriteDecision(False, r)

    if cmd.predicate != p.predicate:
        return no("predicate_mismatch")
    if cmd.policy_version_id != p.policy_version_id:
        return no("stale_policy_version")
    if cmd.writer not in p.allowed_writers:
        return no("writer_not_allowed")
    if cmd.source not in p.allowed_sources:
        return no("source_not_allowed")
    if cmd.writer == "llm_extractor" and p.llm_write_mode != "PROPOSE_VIA_GATE":
        return no("llm_write_forbidden")
    target = current
    if p.cardinality == "MAP":
        if cmd.map_key not in p.map_keys:
            return no("map_key_not_declared")
        target = current.keys[cmd.map_key]
    status = target.slot.status
    if status == ACCESS_DENIED:
        return no("slot_access_denied")
    if assertion:
        if cmd.op not in ASSERTION_OPS:
            return no("observation_cannot_issue_command_op")
        if p.cardinality == "STATE_MACHINE" and cmd.value not in p.transitions:
            return no("undeclared_state")
        return WriteDecision(True)
    if status == UNAVAILABLE:
        return no("slot_unavailable")
    if cmd.op not in p.allowed_operations_by_status.get(status, frozenset()):
        return no(f"op_{cmd.op}_not_allowed_in_{status}")
    if cmd.op == p.conflict_policy.resolve_operation and cmd.writer not in p.conflict_policy.resolvers:
        return no("not_a_conflict_resolver")
    if p.cardinality == "STATE_MACHINE":
        if cmd.value not in p.transitions:
            return no("undeclared_state")
        if cmd.op == "ESTABLISH" and cmd.value not in p.initial_states:
            return no("not_an_initial_state")
        if cmd.op == "TRANSITION" and cmd.value not in p.transitions.get(target.slot.value[1], frozenset()):
            return no("illegal_transition")
    if target.slot.freshness_status == "STALE" and p.freshness.stale_write_policy != "WRITE_ALLOWED":
        return no(f"stale_{p.freshness.stale_write_policy.lower()}")
    return WriteDecision(True)


# --------------------------------------------------------------------------- step 9: authorization
@dataclass(frozen=True)
class Caller:
    principal: str
    authorized_scopes: FrozenSet[Tuple[str, str]]          # e.g. {("CUSTOMER", "subj_1")}
    cleared_classes: FrozenSet[str] = frozenset({"standard"})


def may_read(caller: Caller, scope: Tuple[str, str], security_class: str) -> bool:
    """The single read-authorization rule (§6 step 9), shared by every retrieval path."""
    return scope in caller.authorized_scopes and security_class in caller.cleared_classes


def authorize(resolved: Resolved, slot_scope: Tuple[str, str], caller: Caller) -> Resolved:
    """§6 step 9. Decides who may READ the already-resolved result; never what the result is."""
    if may_read(caller, slot_scope, resolved.security_class):
        return resolved
    s = resolved.slot
    denied = SlotResult(key=s.key, status=ACCESS_DENIED, authority_domain=s.authority_domain,
                        policy_version=s.policy_version)                     # no value, no provenance
    return Resolved(denied, NO_USE, security_class=resolved.security_class)
