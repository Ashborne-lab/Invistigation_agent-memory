"""Evidence -> Claim gate. Every policy here is TEST_ONLY_*: its governance values (retention, ownership, authority
ranks, staleness budgets) are placeholders that exist only to exercise the gate, never production policy."""
import inspect

import pytest

from memory_core.claimgate import (ACCEPT, CONFLICT, REJECT, REQUIRES_ESTABLISHMENT, REPLACEMENT, RESOLUTION,
                                   SHADOWED, Proposal, decide)
from memory_core.config import AMENDED
from memory_core.model import ACCESS_DENIED, CONFLICT as S_CONFLICT, EXPLICIT_NONE, UNKNOWN, VALUE, Claim, \
    ClaimContent, ClaimState, Evidence
from memory_core.registry import (Caller, ConflictPolicy, FreshnessContract, PolicyError, PolicyRegistry,
                                  PredicatePolicy, authorize, resolve_slot)

NOW = 100.0
R = "TEST_ONLY_RETENTION"
OPS = {VALUE: frozenset({"SET"}), EXPLICIT_NONE: frozenset({"SET"}), UNKNOWN: frozenset({"SET", "ESTABLISH"}),
       S_CONFLICT: frozenset({"RESOLVE_CONFLICT"})}

CITY = PredicatePolicy(
    "TEST_ONLY_residence_city", 2, "SINGLE", frozenset({"llm_extractor", "operator"}),
    frozenset({"USER", "OPERATOR"}), OPS, "TEST_ONLY_DOMAIN", {"USER": 1, "OPERATOR": 1}, retention_class=R,
    llm_write_mode="PROPOSE_VIA_GATE")
ROLE = PredicatePolicy(
    "TEST_ONLY_account_role", 1, "SINGLE", frozenset({"system_sync"}), frozenset({"IDENTITY_SYSTEM"}), OPS,
    "IDENTITY_SECURITY", {"IDENTITY_SYSTEM": 9}, security_class="identity_security", retention_class=R,
    conflict_policy=ConflictPolicy(resolvers=frozenset({"system_sync"})))
BILL = PredicatePolicy(
    "TEST_ONLY_billing_address", 1, "SINGLE", frozenset({"system_sync"}), frozenset({"BILLING_SYSTEM"}), OPS,
    "BILLING_SYSTEM", {"BILLING_SYSTEM": 5}, retention_class=R,
    conflict_policy=ConflictPolicy(resolvers=frozenset({"system_sync"})),
    freshness=FreshnessContract(max_staleness=0.01, stale_read_policy="DISPLAY_ONLY",
                                stale_write_policy="WRITE_FORBIDDEN", freshness_source="external_sync"))
ORDER = PredicatePolicy(
    "TEST_ONLY_order_status", 1, "STATE_MACHINE", frozenset({"system_sync"}), frozenset({"ORDER_SYSTEM"}),
    {VALUE: frozenset({"TRANSITION"}), EXPLICIT_NONE: frozenset({"ESTABLISH"}), UNKNOWN: frozenset({"ESTABLISH"}),
     S_CONFLICT: frozenset({"RESOLVE_CONFLICT"})},
    "ORDER_SYSTEM", {"ORDER_SYSTEM": 5}, retention_class=R, conflict_policy=ConflictPolicy(resolvers=frozenset({"system_sync"})),
    transitions={"placed": frozenset({"paid"}), "paid": frozenset({"shipped"}), "shipped": frozenset()},
    initial_states=frozenset({"placed"}))
PREFS = PredicatePolicy(
    "TEST_ONLY_notification_prefs", 1, "MAP", frozenset({"llm_extractor"}), frozenset({"USER"}),
    {VALUE: frozenset({"PUT_KEY"}), EXPLICIT_NONE: frozenset({"PUT_KEY"}), UNKNOWN: frozenset({"PUT_KEY"}),
     S_CONFLICT: frozenset({"RESOLVE_CONFLICT"})},
    "TEST_ONLY_DOMAIN", {"USER": 1}, retention_class=R, llm_write_mode="PROPOSE_VIA_GATE",
    conflict_policy=ConflictPolicy(resolvers=frozenset({"llm_extractor"})), map_keys=frozenset({"email", "sms"}))


@pytest.fixture
def reg():
    r = PolicyRegistry(allow_test_only=True)
    r.publish(PredicatePolicy(**{**CITY.__dict__, "policy_version_id": 1}))     # an older version exists
    for p in (CITY, ROLE, BILL, ORDER, PREFS):
        r.publish(p)
    return r


def ev(eid, text, role="user", source_system=None, member="m_user", observed=NOW - 1, subj="subj_1", org="org_A",
       **kw):
    return Evidence(evidence_id=eid, org_id=org, subject_id=subj, source_member_id=member, agent_id="agent_A1",
                    session_id="s1", author_role=role, text=text, observed_at=observed, epochs={}, source_system=source_system,
                    **kw)


EVID = {
    "e1": ev("e1", "I live in Pune now"),
    "e2": ev("e2", "Please note I moved to Delhi last week", observed=NOW - 0.5),
    "e_agent": ev("e_agent", "So you live in Mumbai?", role="agent"),
    "e_op": ev("e_op", "Customer confirmed address Delhi", role="operator", member="m_op"),
    "e_role": ev("e_role", "role=admin", role="tool", source_system="IDENTITY_SYSTEM"),
    "e_bill": ev("e_bill", "billing address: Gurgaon", role="tool", source_system="BILLING_SYSTEM"),
    "e_order": ev("e_order", "order status shipped", role="tool", source_system="ORDER_SYSTEM"),
    "e_order_paid": ev("e_order_paid", "order status paid", role="tool", source_system="ORDER_SYSTEM"),
    "e_sms": ev("e_sms", "text me by sms on please"),
    "e_unsealed": ev("e_unsealed", "I live in Pune", seal_state="unsealed"),
    "e_other": ev("e_other", "I live in Pune", subj="subj_2"),
    "e_future": ev("e_future", "I live in Pune", observed=NOW + 5),
}

_k = [0]


def prop(pol, op="SET", value=("text", "pune"), anchor=(("e1", "I live in Pune"),), writer="llm_extractor",
         source="USER", version=None, pid=None, **kw):
    _k[0] += 1
    return Proposal(pid or f"p{_k[0]}", "subj_1", "org_A", pol.predicate,
                    pol.policy_version_id if version is None else version, op, writer, source, value, tuple(anchor),
                    **kw)


def claim(pol, value, source, observed, member, key=None, kind="text"):
    _k[0] += 1
    c = ClaimContent(f"c{_k[0]}", "subj_1", member, "org_A", "agent_A1", key or pol.predicate, (kind, value), source,
                     "stated", "verified", None, (), None, None, None, observed, observed, "t", pol.policy_version_id,
                     written_via="command")
    return Claim(c, ClaimState())


def cur(pol, claims=(), last_sync=NOW):
    return resolve_slot(pol, list(claims), NOW, NOW, AMENDED, NOW, last_sync)


def run(reg, pr, current, ledger=None):
    return decide(pr, reg, EVID, current, NOW, ledger)


# ----------------------------------------------------------------------------------------------- required cases
def test_valid_grounded_assertion_accepted(reg):
    o = run(reg, prop(CITY), cur(CITY))
    assert o.decision == ACCEPT and o.draft.value == ("text", "pune") and o.draft.written_via == "llm"
    assert o.draft.source_member_id == "m_user" and o.draft.observed_at == NOW - 1


@pytest.mark.parametrize("anchor, reason", [
    ((("e1", "I live in Mumbai"),), "unsupported:quote_not_in_evidence"),
    ((("e_agent", "you live in Mumbai"),), "unsupported:agent_or_system_text"),
    ((("e_unsealed", "I live in Pune"),), "unsupported:evidence_unsealed"),
    ((("e_missing", "I live in Pune"),), "evidence_not_found"),
    ((), "no_supporting_evidence"),
])
def test_unsupported_assertion_rejected(reg, anchor, reason):
    value = ("text", "mumbai") if "Mumbai" in str(anchor) else ("text", "pune")
    o = run(reg, prop(CITY, value=value, anchor=anchor), cur(CITY))
    assert (o.decision, o.reason) == (REJECT, reason)


def test_value_must_be_carried_by_the_quote(reg):
    o = run(reg, prop(CITY, value=("text", "delhi")), cur(CITY))
    assert (o.decision, o.reason) == (REJECT, "unsupported:value_not_in_quote")


def test_wrong_source_rejected(reg):
    assert run(reg, prop(CITY, source="BILLING_SYSTEM"), cur(CITY)).reason == "source_not_allowed"
    # an allowed source the evidence does not come from: user text cannot be passed off as OPERATOR
    o = run(reg, prop(CITY, source="OPERATOR"), cur(CITY))
    assert (o.decision, o.reason) == (REJECT, "evidence_source_mismatch")


def test_forbidden_llm_writer_rejected(reg):
    o = run(reg, prop(BILL, value=("text", "gurgaon"), anchor=(("e_bill", "billing address: Gurgaon"),),
                      source="BILLING_SYSTEM"), cur(BILL))
    assert (o.decision, o.reason) == (REJECT, "writer_not_allowed")


def test_identity_security_writer_rejected(reg):
    for writer in ("llm_extractor", "user_command", "operator"):
        o = run(reg, prop(ROLE, value=("text", "admin"), anchor=(("e_role", "role=admin"),), writer=writer,
                          source="IDENTITY_SYSTEM"), cur(ROLE))
        assert (o.decision, o.reason) == (REJECT, "writer_not_allowed"), writer
    ok = run(reg, prop(ROLE, value=("text", "admin"), anchor=(("e_role", "role=admin"),), writer="system_sync",
                       source="IDENTITY_SYSTEM"), cur(ROLE))
    assert ok.decision == ACCEPT
    # and a policy that tried to allow it could never be published
    with pytest.raises(PolicyError):
        PolicyRegistry(allow_test_only=True).publish(PredicatePolicy(**{
            **ROLE.__dict__, "allowed_writers": frozenset({"system_sync", "llm_extractor"}),
            "llm_write_mode": "PROPOSE_VIA_GATE"}))


def _conflicted():
    return cur(CITY, [claim(CITY, "pune", "USER", 1, "m_user"), claim(CITY, "delhi", "OPERATOR", 2, "m_op")])


def test_conflicted_slot_blind_set_rejected(reg):
    # A blind SET is a typed state COMMAND: refused under CONFLICT (§3). (C-D / G-1: an extracted LLM
    # OBSERVATION is not a command; it is recorded as evidence and resolution decides; see the next assertion.)
    c = _conflicted()
    assert c.slot.status == S_CONFLICT
    o = run(reg, prop(CITY, value=("text", "delhi"), anchor=(("e_op", "address Delhi"),), writer="operator",
                      source="OPERATOR"), c)
    assert (o.decision, o.reason) == (REJECT, "op_SET_not_allowed_in_CONFLICT")
    obs = run(reg, prop(CITY), c)                          # the user's statement during the conflict
    assert obs.decision in (ACCEPT, CONFLICT) and obs.draft is not None


def test_conflicted_slot_declared_resolver_accepted(reg):
    o = run(reg, prop(CITY, op="RESOLVE_CONFLICT", value=("text", "delhi"),
                      anchor=(("e_op", "address Delhi"),), writer="operator", source="OPERATOR"), _conflicted())
    assert (o.decision, o.effect) == (ACCEPT, RESOLUTION)
    # a writer that is not a declared resolver cannot resolve
    o2 = run(reg, prop(CITY, op="RESOLVE_CONFLICT"), _conflicted())   # an observation cannot issue commands
    assert (o2.decision, o2.reason) == (REJECT, "observation_cannot_issue_command_op")


def test_stale_value_forbidden_stale_write_rejected(reg):
    stale = cur(BILL, [claim(BILL, "gurgaon", "BILLING_SYSTEM", 1, "billing")], last_sync=NOW - 1)
    assert stale.slot.freshness_status == "STALE"
    pr = prop(BILL, value=("text", "gurgaon"), anchor=(("e_bill", "billing address: Gurgaon"),),
              writer="system_sync", source="BILLING_SYSTEM")
    assert run(reg, pr, stale).reason == "stale_write_forbidden"
    fresh = cur(BILL, [claim(BILL, "gurgaon", "BILLING_SYSTEM", 1, "billing")], last_sync=NOW)
    assert run(reg, prop(BILL, value=("text", "gurgaon"), anchor=(("e_bill", "billing address: Gurgaon"),),
                         writer="system_sync", source="BILLING_SYSTEM"), fresh).decision == ACCEPT


def test_invalid_state_transition_rejected(reg):
    placed = cur(ORDER, [claim(ORDER, "placed", "ORDER_SYSTEM", 1, "orders", kind="enum")])
    o = run(reg, prop(ORDER, op="TRANSITION", value=("enum", "shipped"), anchor=(("e_order", "status shipped"),),
                      writer="system_sync", source="ORDER_SYSTEM"), placed)
    assert (o.decision, o.reason) == (REJECT, "illegal_transition")
    ok = run(reg, prop(ORDER, op="TRANSITION", value=("enum", "paid"), anchor=(("e_order_paid", "status paid"),),
                       writer="system_sync", source="ORDER_SYSTEM"), placed)
    assert ok.decision == ACCEPT


def test_transition_on_unknown_requires_establishment(reg):
    o = run(reg, prop(ORDER, op="TRANSITION", value=("enum", "paid"), anchor=(("e_order_paid", "status paid"),),
                      writer="system_sync", source="ORDER_SYSTEM"), cur(ORDER))
    assert (o.decision, o.reason) == (REQUIRES_ESTABLISHMENT, "slot_unknown_establish_first")


def test_undeclared_map_key_rejected(reg):
    o = run(reg, prop(PREFS, op="PUT_KEY", value=("text", "on"), anchor=(("e_sms", "sms on"),), map_key="fax"),
            cur(PREFS))
    assert (o.decision, o.reason) == (REJECT, "map_key_not_declared")
    ok = run(reg, prop(PREFS, op="PUT_KEY", value=("text", "on"), anchor=(("e_sms", "sms on"),), map_key="sms"),
             cur(PREFS))
    assert ok.decision == ACCEPT and ok.draft.key == "TEST_ONLY_notification_prefs[sms]"


def test_old_policy_version_rejected(reg):
    o = run(reg, prop(CITY, version=1), cur(CITY))
    assert (o.decision, o.reason) == (REJECT, "stale_policy_version")


def test_unknown_predicate_rejected(reg):
    p = prop(CITY)
    o = decide(Proposal(**{**p.__dict__, "predicate": "TEST_ONLY_not_registered"}), reg, EVID, cur(CITY), NOW)
    assert (o.decision, o.reason) == (REJECT, "unknown_predicate")


def test_duplicate_and_idempotent_proposal(reg):
    ledger = {}
    first = run(reg, prop(CITY, pid="same"), cur(CITY), ledger)
    again = run(reg, prop(CITY, pid="same"), cur(CITY), ledger)
    assert first.decision == again.decision == ACCEPT
    assert again.duplicate and again.draft is None                    # no second claim
    reused = run(reg, prop(CITY, pid="same", value=("text", "pune"), anchor=(("e1", "live in Pune"),)),
                 cur(CITY), ledger)
    assert (reused.decision, reused.reason) == (REJECT, "proposal_id_reused_with_different_content")
    content_dup = run(reg, prop(CITY, pid="other"), cur(CITY), ledger)
    assert content_dup.duplicate and content_dup.draft is None and content_dup.reason == "duplicate_of_same"


def test_valid_temporal_replacement(reg):
    current = cur(CITY, [claim(CITY, "pune", "USER", 1, "m_user")])
    o = run(reg, prop(CITY, value=("text", "delhi"), anchor=(("e2", "I moved to Delhi"),), valid_from=NOW - 7),
            current)
    assert (o.decision, o.effect) == (ACCEPT, REPLACEMENT)              # same source group supersedes
    assert o.draft.valid_from == NOW - 7


def test_empty_validity_interval_and_future_evidence_rejected(reg):
    assert run(reg, prop(CITY, valid_from=5, valid_until=5), cur(CITY)).reason == "empty_validity_interval"
    assert run(reg, prop(CITY, anchor=(("e_future", "I live in Pune"),)), cur(CITY)).reason \
        == "evidence_from_the_future"


def test_authorization_after_resolution_exposes_nothing(reg):
    o = run(reg, prop(CITY), cur(CITY))
    d = o.draft
    committed = Claim(ClaimContent("c_new", d.subject_id, d.source_member_id, d.org_id, "agent_A1", d.key, d.value,
                                   d.source, "stated", "verified", None, d.anchor, None, d.valid_from, d.valid_until,
                                   d.observed_at, NOW, "t", d.policy_version, written_via=d.written_via),
                      ClaimState())
    resolved = cur(CITY, [committed])
    assert resolved.slot.value == ("text", "pune")
    denied = authorize(resolved, ("CUSTOMER", "subj_1"), Caller("stranger", frozenset()))
    assert denied.slot.status == ACCESS_DENIED and denied.slot.value is None
    assert denied.slot.winning_claim_ids == () and denied.slot.source is None


# ----------------------------------------------------------------------------------------------- invariants
def test_equal_authority_independent_disagreement_flags_conflict(reg):
    current = cur(CITY, [claim(CITY, "delhi", "OPERATOR", 1, "m_op")])
    o = run(reg, prop(CITY), current)
    assert o.decision == CONFLICT and o.draft is not None              # kept as evidence; flagged


def test_lower_authority_claim_is_shadowed_not_rejected(reg):
    p = PredicatePolicy(**{**CITY.__dict__, "predicate": "TEST_ONLY_city_ranked",
                           "authority_rank": {"USER": 1, "OPERATOR": 2}})
    reg.publish(p)
    current = cur(p, [claim(p, "delhi", "OPERATOR", 1, "m_op")])
    o = run(reg, prop(p), current)
    assert (o.decision, o.effect) == (ACCEPT, SHADOWED)


def test_subject_or_org_mismatch_rejected(reg):
    o = run(reg, prop(CITY, anchor=(("e_other", "I live in Pune"),)), cur(CITY))
    assert (o.decision, o.reason) == (REJECT, "evidence_subject_or_org_mismatch")


def test_gate_is_deterministic_and_takes_no_caller(reg):
    params = set(inspect.signature(decide).parameters)
    assert not params & {"caller", "principal", "authorized_scopes"}
    pr, c = prop(CITY, pid="fixed"), cur(CITY)
    assert run(reg, pr, c) == run(reg, pr, c)


def test_test_only_policies_cannot_enter_a_production_registry():
    with pytest.raises(PolicyError, match="TEST_ONLY"):
        PolicyRegistry().publish(CITY)
