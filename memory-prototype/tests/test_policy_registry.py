"""Predicate Policy Registry: validation, versioning, cardinality, authority, freshness, status gating and
the authorization boundary (contract §3, §5, §6, §10, §11). Synthetic data only."""
import inspect

import pytest

from memory_core.config import AMENDED
from memory_core.model import ACCESS_DENIED, CONFLICT, EXPLICIT_NONE, UNAVAILABLE, UNKNOWN, VALUE, Claim, \
    ClaimContent, ClaimState
from memory_core.registry import (DISPLAY_ONLY, OPERATIONAL, REFRESH_REQUIRED, Caller, ConflictPolicy,
                                  FreshnessContract, PolicyError, PolicyRegistry, PredicatePolicy, UnknownPredicate,
                                  WriteCommand, authorize, check_write, map_claim_key, resolve_slot, validate_policy)

D = AMENDED
NOW = 100.0
SUBJ = ("CUSTOMER", "subj_1")
STD_OPS = {VALUE: frozenset({"SET"}), EXPLICIT_NONE: frozenset({"SET"}),
           UNKNOWN: frozenset({"SET", "ESTABLISH"}), CONFLICT: frozenset({"RESOLVE_CONFLICT"})}


def pol(**kw) -> PredicatePolicy:
    base = dict(predicate="residence.city", policy_version_id=1, cardinality="SINGLE",
                allowed_writers=frozenset({"user_command", "operator"}), allowed_sources=frozenset({"USER", "OPERATOR"}),
                allowed_operations_by_status=STD_OPS, authority_domain="CUSTOMER_PREFERENCE",
                authority_rank={"USER": 1, "OPERATOR": 1}, retention_class="TEST_ONLY_RETENTION")
    base.update(kw)
    return PredicatePolicy(**base)


_n = [0]


def claim(key, value, source, observed, kind="text", member=None, vf=None):
    _n[0] += 1
    c = ClaimContent(claim_id=f"c{_n[0]:03d}", subject_id="subj_1", source_member_id=member or source,
                     org_id="org_A", learned_by_agent_id="agent_A1", key=key, value=(kind, value), source=source,
                     assertion_mode="stated", value_check="verified", normaliser_id=None, anchor=(), prompt_ref=None,
                     valid_from=vf, valid_until=None, observed_at=observed, committed_at=observed,
                     extractor_version="t", policy_version=1, written_via="command")
    return Claim(c, ClaimState())


def res(p, claims, last_sync=None, now=NOW):
    return resolve_slot(p, claims, as_of=now, cutoff=now, d=D, now=now, last_sync=last_sync)


# ----------------------------------------------------------------- policies used across tests (contract examples)
BILLING_ADDR = pol(predicate="billing_address", authority_domain="BILLING_SYSTEM",
                   allowed_writers=frozenset({"system_sync", "operator"}),
                   allowed_sources=frozenset({"BILLING_SYSTEM", "CRM_SYSTEM"}),
                   authority_rank={"BILLING_SYSTEM": 5, "CRM_SYSTEM": 5},
                   freshness=FreshnessContract(max_staleness=15 / 1440, stale_read_policy="DISPLAY_ONLY",
                                               stale_write_policy="WRITE_FORBIDDEN", freshness_source="external_sync"))
ACCOUNT_ROLE = pol(predicate="account_role", authority_domain="IDENTITY_SECURITY", security_class="identity_security",
                   allowed_writers=frozenset({"system_sync"}), allowed_sources=frozenset({"IDENTITY_SYSTEM"}),
                   authority_rank={"IDENTITY_SYSTEM": 9}, conflict_policy=ConflictPolicy(resolvers=frozenset({"system_sync"})))
LANGS = pol(predicate="preferred_languages", cardinality="SET",
            allowed_operations_by_status={VALUE: frozenset({"ADD", "REMOVE"}), UNKNOWN: frozenset({"ADD"})})
NOTIFY = pol(predicate="notification_preferences", cardinality="MAP", map_keys=frozenset({"email", "sms", "push"}),
             allowed_operations_by_status={VALUE: frozenset({"PUT_KEY", "REMOVE_KEY"}),
                                           EXPLICIT_NONE: frozenset({"PUT_KEY"}),
                                           UNKNOWN: frozenset({"PUT_KEY"}), CONFLICT: frozenset({"RESOLVE_CONFLICT"})})
ORDER = pol(predicate="order_status", cardinality="STATE_MACHINE", authority_domain="ORDER_SYSTEM",
            allowed_writers=frozenset({"system_sync", "operator"}), allowed_sources=frozenset({"ORDER_SYSTEM"}),
            authority_rank={"ORDER_SYSTEM": 5},
            allowed_operations_by_status={VALUE: frozenset({"TRANSITION", "SET"}), EXPLICIT_NONE: frozenset({"SET"}),
                                          UNKNOWN: frozenset({"SET", "ESTABLISH"}),
                                          CONFLICT: frozenset({"RESOLVE_CONFLICT"})},
            transitions={"placed": frozenset({"paid", "cancelled"}), "paid": frozenset({"shipped", "refunded"}),
                         "shipped": frozenset({"delivered"}), "delivered": frozenset(), "cancelled": frozenset(),
                         "refunded": frozenset()},
            initial_states=frozenset({"placed"}))
HEALTH = pol(predicate="health.condition", security_class="sensitive", allowed_writers=frozenset({"user_command"}),
             allowed_sources=frozenset({"USER"}), authority_rank={"USER": 1},
             conflict_policy=ConflictPolicy(resolvers=frozenset({"user_command"})))


def cmd(p, op, writer, source, value=None, map_key=None, version=None):
    return WriteCommand(p.predicate, p.policy_version_id if version is None else version, op, writer, source, value,
                        map_key)


# ================================================================= 1. validation
def test_every_example_policy_is_valid():
    for p in (pol(), BILLING_ADDR, ACCOUNT_ROLE, LANGS, NOTIFY, ORDER, HEALTH):
        assert validate_policy(p) == [], p.predicate


@pytest.mark.parametrize("bad, rule", [
    (dict(allowed_operations_by_status={**STD_OPS, CONFLICT: frozenset({"RESOLVE_CONFLICT", "SET"})}), "blind writes"),
    (dict(allowed_operations_by_status={**STD_OPS, CONFLICT: frozenset()}), "resolve operation"),
    (dict(allowed_operations_by_status={VALUE: frozenset({"SET"})}), "missing"),
    (dict(authority_rank={"USER": 1}), "authority_rank"),
    (dict(cardinality="ORDERED_SET"), "not implemented"),
    (dict(cardinality="LIST"), "unknown cardinality"),
    (dict(cardinality="MAP"), "map_keys"),
    (dict(cardinality="STATE_MACHINE"), "transitions"),
    (dict(retention_class=""), "retention_class"),
    (dict(freshness=FreshnessContract(freshness_source="external_sync")), "max_staleness"),
    (dict(allowed_writers=frozenset({"llm_extractor", "user_command"})), "PROPOSE_VIA_GATE"),
    (dict(security_class="identity_security"), "identity_security"),
])
def test_invalid_policy_rejected(bad, rule):
    errs = validate_policy(pol(**bad))
    assert any(rule in e for e in errs), errs
    with pytest.raises(PolicyError):
        PolicyRegistry(allow_test_only=True).publish(pol(**bad))


def test_state_machine_target_must_be_declared():
    bad = pol(cardinality="STATE_MACHINE", transitions={"a": frozenset({"ghost"})}, initial_states=frozenset({"a"}))
    assert any("not a declared state" in e for e in validate_policy(bad))


# ================================================================= 2. registry: no fallback, versioned, immutable
def test_unknown_predicate_has_no_fallback():
    r = PolicyRegistry(allow_test_only=True)
    r.publish(pol())
    with pytest.raises(UnknownPredicate):
        r.get("residence.country")
    with pytest.raises(UnknownPredicate):
        r.get("residence.city", version=7)


def test_versions_are_append_only_and_pinned():
    r = PolicyRegistry(allow_test_only=True)
    r.publish(pol())
    rep = r.publish(pol(policy_version_id=2, cardinality="SET",
                        allowed_operations_by_status={VALUE: frozenset({"ADD"}), UNKNOWN: frozenset({"ADD"})}))
    assert rep.cardinality_changed is True                      # §10: migration applies
    assert r.get("residence.city").cardinality == "SET"
    assert r.get("residence.city", 1).cardinality == "SINGLE"   # old version still readable, unchanged
    with pytest.raises(PolicyError):
        r.publish(pol(policy_version_id=2))                     # no rewrite of a published version
    with pytest.raises(TypeError):
        r.get("residence.city", 1).allowed_operations_by_status[VALUE] = frozenset()   # frozen mapping


# ================================================================= 3. cardinality
def test_cardinality_comes_from_policy_not_data():
    cs = [claim("langs", "hi", "USER", 1), claim("langs", "en", "USER", 2, member="USER2")]
    single = res(pol(predicate="langs"), cs).slot
    as_set = res(pol(predicate="langs", cardinality="SET",
                     allowed_operations_by_status={VALUE: frozenset({"ADD"}), UNKNOWN: frozenset({"ADD"})}), cs).slot
    assert single.status == CONFLICT
    assert as_set.status == VALUE and {e[0] for e in as_set.elements if e[1] == "ACTIVE"} == {"hi", "en"}


def test_single_equal_authority_disagreement_is_conflict_never_recency():
    cs = [claim("billing_address", "Gurgaon", "CRM_SYSTEM", 1), claim("billing_address", "Delhi", "BILLING_SYSTEM", 2)]
    r = res(BILLING_ADDR, cs, last_sync=NOW)
    assert r.slot.status == CONFLICT and r.slot.value is None


def test_map_keys_resolve_independently():
    k = lambda key: map_claim_key("notification_preferences", key)
    cs = [claim(k("email"), "on", "USER", 1), claim(k("sms"), "on", "USER", 1),
          claim(k("sms"), "off", "OPERATOR", 2)]
    r = res(NOTIFY, cs)
    assert r.keys["email"].slot.status == VALUE
    assert r.keys["sms"].slot.status == CONFLICT          # equal-rank independent sources
    assert r.keys["push"].slot.status == UNKNOWN
    assert r.slot.status == VALUE


def test_state_machine_transitions_gated_by_graph():
    cur = res(ORDER, [claim("order_status", "paid", "ORDER_SYSTEM", 1, kind="enum")])
    assert cur.slot.value == ("enum", "paid")
    assert check_write(ORDER, cmd(ORDER, "TRANSITION", "system_sync", "ORDER_SYSTEM", "shipped"), cur).allowed
    assert check_write(ORDER, cmd(ORDER, "TRANSITION", "system_sync", "ORDER_SYSTEM", "delivered"), cur).reason \
        == "illegal_transition"
    unk = res(ORDER, [])
    assert check_write(ORDER, cmd(ORDER, "ESTABLISH", "system_sync", "ORDER_SYSTEM", "paid"), unk).reason \
        == "not_an_initial_state"
    assert check_write(ORDER, cmd(ORDER, "ESTABLISH", "system_sync", "ORDER_SYSTEM", "placed"), unk).allowed


def test_state_machine_undeclared_resolved_state_is_not_operational():
    r = res(ORDER, [claim("order_status", "teleported", "ORDER_SYSTEM", 1, kind="enum")])
    assert r.slot.status == UNKNOWN and r.slot.value is None


# ================================================================= 4. authority (predicate-specific, §5)
def test_user_statement_cannot_override_billing_system():
    cs = [claim("billing_address", "Delhi", "BILLING_SYSTEM", 1), claim("billing_address", "Pune", "USER", 5)]
    assert res(BILLING_ADDR, cs, last_sync=NOW).slot.value == ("text", "Delhi")   # USER is not an allowed source
    assert check_write(BILLING_ADDR, cmd(BILLING_ADDR, "SET", "user_command", "USER", "Pune"),
                       res(BILLING_ADDR, cs, last_sync=NOW)).reason == "writer_not_allowed"


def test_account_role_unreachable_by_llm_or_user_under_any_framing():
    cur = res(ACCOUNT_ROLE, [])
    for writer, source in (("llm_extractor", "IDENTITY_SYSTEM"), ("user_command", "IDENTITY_SYSTEM"),
                           ("system_sync", "USER")):
        assert not check_write(ACCOUNT_ROLE, cmd(ACCOUNT_ROLE, "SET", writer, source, "admin"), cur).allowed
    assert check_write(ACCOUNT_ROLE, cmd(ACCOUNT_ROLE, "SET", "system_sync", "IDENTITY_SYSTEM", "admin"), cur).allowed


def test_repetition_does_not_outrank_authority():
    p = pol(predicate="work.employer", allowed_sources=frozenset({"USER", "HR_SYSTEM"}),
            allowed_writers=frozenset({"user_command", "system_sync", "operator"}),
            authority_rank={"USER": 1, "HR_SYSTEM": 5})
    cs = [claim("work.employer", "Acme", "USER", t) for t in range(1, 40)] + [
        claim("work.employer", "Globex", "HR_SYSTEM", 0.5)]
    assert res(p, cs).slot.value == ("text", "Globex")


# ================================================================= 5. freshness contract (§3)
def test_external_value_synced_6h_ago_with_15m_budget_is_stale_display_only():
    cs = [claim("billing_address", "Gurgaon", "BILLING_SYSTEM", NOW - 0.001)]   # observed just now ...
    r = res(BILLING_ADDR, cs, last_sync=NOW - 0.25)                              # ... but synced 6 h ago
    assert r.slot.value == ("text", "Gurgaon")
    assert r.slot.freshness_status == "STALE" and r.usage == DISPLAY_ONLY      # never unqualified operational truth


def test_fresh_sync_is_operational():
    r = res(BILLING_ADDR, [claim("billing_address", "Gurgaon", "BILLING_SYSTEM", 1)], last_sync=NOW - 0.001)
    assert r.slot.freshness_status == "FRESH" and r.usage == OPERATIONAL


def test_stale_read_policies():
    stale = lambda rp: pol(freshness=FreshnessContract(max_staleness=1, stale_read_policy=rp))
    cs = [claim("residence.city", "Pune", "USER", NOW - 10)]
    assert res(stale("UNAVAILABLE"), cs).slot.status == UNAVAILABLE
    assert res(stale("UNAVAILABLE"), cs).slot.value is None
    assert res(stale("REQUIRES_REFRESH"), cs).usage == REFRESH_REQUIRED
    assert res(stale("READ_ALLOWED"), cs).usage == OPERATIONAL
    assert res(stale("READ_ALLOWED"), cs).slot.freshness_status == "STALE"


def test_stale_write_forbidden():
    cs = [claim("billing_address", "Gurgaon", "BILLING_SYSTEM", 1)]
    stale = res(BILLING_ADDR, cs, last_sync=NOW - 1)
    assert check_write(BILLING_ADDR, cmd(BILLING_ADDR, "SET", "system_sync", "BILLING_SYSTEM", "Delhi"), stale).reason \
        == "stale_write_forbidden"
    fresh = res(BILLING_ADDR, cs, last_sync=NOW)
    assert check_write(BILLING_ADDR, cmd(BILLING_ADDR, "SET", "system_sync", "BILLING_SYSTEM", "Delhi"), fresh).allowed


def test_freshness_independent_of_authority_and_support():
    cs = [claim("billing_address", "Gurgaon", "BILLING_SYSTEM", t) for t in (99.0, 99.5, 99.9)]
    r = res(BILLING_ADDR, cs, last_sync=None)                  # no successful sync recorded
    assert r.slot.status == VALUE and r.slot.freshness_status == "STALE"


# ================================================================= 6. operations gated by status (§3)
def test_conflict_permits_only_the_declared_resolution():
    cs = [claim("residence.city", "Pune", "USER", 1), claim("residence.city", "Delhi", "OPERATOR", 2)]
    cur = res(pol(), cs)
    assert cur.slot.status == CONFLICT
    assert check_write(pol(), cmd(pol(), "SET", "operator", "OPERATOR", "Delhi"), cur).reason \
        == "op_SET_not_allowed_in_CONFLICT"
    assert check_write(pol(), cmd(pol(), "RESOLVE_CONFLICT", "user_command", "USER", "Pune"), cur).reason \
        == "not_a_conflict_resolver"
    assert check_write(pol(), cmd(pol(), "RESOLVE_CONFLICT", "operator", "OPERATOR", "Delhi"), cur).allowed


def test_unknown_and_explicit_none_gates():
    p = pol(allowed_writers=frozenset({"user_command", "operator"}))
    unk = res(p, [])
    assert check_write(p, cmd(p, "ESTABLISH", "user_command", "USER", "Pune"), unk).allowed
    assert not check_write(p, cmd(p, "TRANSITION", "user_command", "USER", "Pune"), unk).allowed
    none = res(p, [claim("residence.city", "", "USER", 1, kind="none")])
    assert none.slot.status == EXPLICIT_NONE
    assert check_write(p, cmd(p, "SET", "user_command", "USER", "Pune"), none).allowed


def test_map_gating_is_per_key():
    k = lambda key: map_claim_key("notification_preferences", key)
    cur = res(NOTIFY, [claim(k("sms"), "on", "USER", 1), claim(k("sms"), "off", "OPERATOR", 2)])
    assert not check_write(NOTIFY, cmd(NOTIFY, "PUT_KEY", "operator", "OPERATOR", "on", "sms"), cur).allowed
    assert check_write(NOTIFY, cmd(NOTIFY, "PUT_KEY", "operator", "OPERATOR", "on", "push"), cur).allowed
    assert check_write(NOTIFY, cmd(NOTIFY, "PUT_KEY", "operator", "OPERATOR", "on", "fax"), cur).reason \
        == "map_key_not_declared"


def test_command_must_name_current_policy_version():
    assert check_write(pol(), cmd(pol(), "SET", "operator", "OPERATOR", "Pune", version=0), res(pol(), [])).reason \
        == "stale_policy_version"


# ================================================================= 7. authorization interaction (§6)
def test_resolver_takes_no_caller():
    params = set(inspect.signature(resolve_slot).parameters)
    assert not params & {"caller", "principal", "authorized_scopes", "requester"}


def test_authorization_never_changes_the_value():
    cs = [claim("residence.city", "Pune", "USER", 1, member="member_hidden_from_B")]
    r = res(pol(), cs)
    a = authorize(r, SUBJ, Caller("A", frozenset({SUBJ})))
    b = authorize(r, SUBJ, Caller("B", frozenset({SUBJ})))
    assert a.slot == b.slot == r.slot                              # one slot -> one system-authoritative result
    denied = authorize(r, SUBJ, Caller("C", frozenset({("CUSTOMER", "other")})))
    assert denied.slot.status == ACCESS_DENIED
    assert denied.slot.value is None and denied.slot.winning_claim_ids == ()   # no value, no provenance


def test_sensitive_class_needs_clearance():
    r = res(HEALTH, [claim("health.condition", "asthma", "USER", 1)])
    assert authorize(r, SUBJ, Caller("A", frozenset({SUBJ}))).slot.status == ACCESS_DENIED
    ok = authorize(r, SUBJ, Caller("A", frozenset({SUBJ}), frozenset({"standard", "sensitive"})))
    assert ok.slot.value == ("text", "asthma")


def test_denied_caller_cannot_write_through_a_denied_result():
    r = authorize(res(pol(), []), SUBJ, Caller("C", frozenset()))
    assert check_write(pol(), cmd(pol(), "ESTABLISH", "operator", "OPERATOR", "Pune"), r).reason \
        == "slot_access_denied"


def test_test_only_policies_refused_by_a_non_test_registry():
    with pytest.raises(PolicyError, match="TEST_ONLY"):
        PolicyRegistry().publish(pol())
