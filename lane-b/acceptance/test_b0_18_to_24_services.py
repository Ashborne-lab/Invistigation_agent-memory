"""B0-18 admin · B0-19 send-directive · B0-20 MCP · B0-21 Lumen · B0-22 activities · B0-23 share tokens ·
B0-24 engine permission helper. Invariants INV-S7, S9, S10, S11, S12."""
import asyncio

import pytest
from fastapi import HTTPException

from world import ALICE, BOB, Denied, Principal

STAFF_UNVERIFIED = Principal("firebase", uid="uid_fake", email="intern@olbrain.com", email_verified=False,
                             provider="password")
STAFF_VERIFIED = Principal("firebase", uid="uid_staff", email="staff@olbrain.com", email_verified=True,
                           provider="google.com", hd="olbrain.com")
STAFF_PASSWORD_VERIFIED = Principal("firebase", uid="uid_pw", email="pw@olbrain.com", email_verified=True,
                                    provider="password")
CLAIM_ADMIN = Principal("firebase", uid="uid_claim", email="ops@contractor.example", email_verified=True,
                        admin_claim=True)


# ------------------------------------------------------------------ B0-18
def test_B0_18_unverified_olbrain_address_gets_no_admin(impl):
    assert impl.is_platform_admin(STAFF_UNVERIFIED) is False


def test_B0_18_verified_google_hosted_domain_admin_allowed(impl):
    assert impl.is_platform_admin(STAFF_VERIFIED) is True


def test_B0_18_password_account_with_olbrain_address_is_not_admin(impl):
    assert impl.is_platform_admin(STAFF_PASSWORD_VERIFIED) is False


def test_B0_18_explicit_backend_admin_claim_allowed(impl):
    assert impl.is_platform_admin(CLAIM_ADMIN) is True


def test_B0_18_ordinary_external_account_denied(impl):
    assert impl.is_platform_admin(ALICE) is False


@pytest.mark.skipif(__import__("os").environ.get("B0_TARGET", "reference") != "current",
                    reason="documents the other two CURRENT gates (engine, research) with REAL code")
def test_B0_18_current_engine_and_research_gates_also_accept_unverified(impl):
    assert impl.engine_admin(STAFF_UNVERIFIED) is False, "engine require_olbrain_user accepts unverified"
    assert impl.research_internal(STAFF_UNVERIFIED) is False, "research is_internal_user accepts unverified"


# ------------------------------------------------------------------ B0-19
DIRECTIVES_SA = Principal("service", service_email="directives-sa@synthetic")


def test_B0_19_unauthenticated_caller_denied(impl, w):
    with pytest.raises(Denied):
        impl.send_directive(w, None, "agent_A1", "eu_A1", "promo")
    assert w.sent == []


def test_B0_19_invalid_service_credential_denied(impl, w):
    with pytest.raises(Denied):
        impl.send_directive(w, Principal("service", service_email="random@evil"), "agent_A1", "eu_A1", "promo")


def test_B0_19_valid_internal_caller_allowed(impl, w):
    assert impl.send_directive(w, DIRECTIVES_SA, "agent_A1", "eu_A1", "reminder") == "sent"


def test_B0_19_caller_cannot_target_arbitrary_victim_identity(impl, w):
    with pytest.raises(Denied):                       # an end user of ANOTHER agent/org
        impl.send_directive(w, DIRECTIVES_SA, "agent_A1", "eu_B1", "promo")
    with pytest.raises(Denied):                       # an identity that is not an end user at all
        impl.send_directive(w, DIRECTIVES_SA, "agent_A1", "+919999999999", "promo")


# ------------------------------------------------------------------ B0-20
RUNTIME_SA = Principal("service", service_email="runtime-sa@synthetic")


def test_B0_20_default_configuration_fails_closed(impl, w):
    with pytest.raises(Denied):                       # MCP_REQUIRE_AUTH unset, no caller identity
        impl.mcp_tools_call(w, {}, None, "shopify", body_agent="agent_A1")


def test_B0_20_missing_agent_is_rejected_and_never_uses_default_credentials(impl, w):
    try:
        r = impl.mcp_tools_call(w, {"MCP_REQUIRE_AUTH": "true"}, RUNTIME_SA, "shopify")
    except Denied:
        return
    assert r["credential"] != "cred-DEFAULT", "empty agent_id fell through to default credentials"
    pytest.fail("missing agent binding was accepted")


def test_B0_20_body_or_query_agent_does_not_establish_authority(impl, w):
    with pytest.raises(Denied):
        impl.mcp_tools_call(w, {"MCP_REQUIRE_AUTH": "true"}, RUNTIME_SA, "shopify", body_agent="agent_B1")
    with pytest.raises(Denied):
        impl.mcp_tools_call(w, {"MCP_REQUIRE_AUTH": "true"}, RUNTIME_SA, "shopify", query_agent="agent_B1")


def test_B0_20_spoofed_agent_with_valid_binding_for_another_agent_rejected(impl, w):
    b = impl.mint_binding(w, "agent_A1", "shopify")
    with pytest.raises(Denied):
        impl.mcp_tools_call(w, {"MCP_REQUIRE_AUTH": "true"}, RUNTIME_SA, "shopify", body_agent="agent_B1", binding=b)


def test_B0_20_wrong_tenant_expired_or_forged_binding_rejected(impl, w):
    env = {"MCP_REQUIRE_AUTH": "true"}
    for bad in (impl.mint_binding(w, "agent_A1", "shopify", org="org_B"),
                impl.mint_binding(w, "agent_A1", "shopify", exp_delta=-1),
                impl.mint_binding(w, "agent_A1", "notion"),
                "forged.0000"):
        with pytest.raises(Denied):
            impl.mcp_tools_call(w, env, RUNTIME_SA, "shopify", binding=bad)


def test_B0_20_valid_binding_allowed_and_resolves_only_its_own_credentials(impl, w):
    r = impl.mcp_tools_call(w, {"MCP_REQUIRE_AUTH": "true"}, RUNTIME_SA, "shopify",
                            binding=impl.mint_binding(w, "agent_A1", "shopify"))
    assert r == {"agent": "agent_A1", "credential": "cred-A1"}


def test_B0_20_agent_without_tenant_credentials_never_falls_back_to_default(impl, w):
    w.agents["agent_A3"] = {"org": "org_A", "owner": "uid_alice", "project": "proj_A"}
    try:
        r = impl.mcp_tools_call(w, {"MCP_REQUIRE_AUTH": "true"}, RUNTIME_SA, "shopify", body_agent="agent_A3",
                                binding=impl.mint_binding(w, "agent_A3", "shopify"))
    except Denied:
        return
    assert r["credential"] != "cred-DEFAULT"


def test_B0_20_credential_management_requires_studio_backend_and_user_edit_right(impl, w):
    with pytest.raises(Denied):
        impl.mcp_credentials_route(w, RUNTIME_SA, ALICE, "set", "agent_A1")
    sb = Principal("service", service_email="studio-backend-sa@synthetic")
    with pytest.raises(Denied):
        impl.mcp_credentials_route(w, sb, ALICE, "delete", "agent_B1")
    assert impl.mcp_credentials_route(w, sb, ALICE, "set", "agent_A1") == "set:agent_A1"


# ------------------------------------------------------------------ B0-21
ROWS = [("mine", "my log"), ("victim", "victim phone +910000000009"), ("victim", "victim email v@x.example")]
ATTACKS = {
    "or": "SELECT msg FROM service_logs WHERE agent_id = 'mine' OR agent_id = 'victim'",
    "union": "SELECT msg FROM service_logs WHERE agent_id = 'mine' UNION SELECT msg FROM service_logs",
    "comment": "SELECT msg FROM service_logs /* agent_id = 'mine' */",
    "string": "SELECT msg FROM service_logs WHERE msg <> \"agent_id = 'mine'\"",
    "subquery": "SELECT msg FROM service_logs WHERE agent_id = 'mine' OR agent_id IN (SELECT agent_id FROM service_logs)",
}


@pytest.mark.parametrize("name", sorted(ATTACKS))
def test_B0_21_adversarial_sql_cannot_widen_tenant_scope(impl, w, name):
    try:
        out = impl.lumen_query(w, "mine", ATTACKS[name], ROWS)
    except Denied:
        return
    assert not any("victim" in r for r in out), "tenant scope widened by " + name


def test_B0_21_authorized_query_returns_only_own_rows(impl, w):
    assert impl.lumen_query(w, "mine", "SELECT msg FROM service_logs WHERE agent_id = 'mine'", ROWS) == ["my log"]


# ------------------------------------------------------------------ B0-22
def test_B0_22_caller_cannot_log_activity_into_another_org(impl, w):
    with pytest.raises(Denied):
        impl.activity_log(w, ALICE, "org_B")
    assert not [a for a in w.activities if a["org"] == "org_B"]


def test_B0_22_firebase_supplied_actor_id_is_ignored(impl, w):
    impl.activity_log(w, ALICE, "org_A", actor_id="uid_bob")
    assert w.activities[-1]["actor"] == "uid_alice"


def test_B0_22_cross_org_list_denied_and_same_org_works(impl, w):
    impl.activity_log(w, BOB, "org_B")
    with pytest.raises(Denied):
        impl.activity_list(w, ALICE, "org_B")
    impl.activity_log(w, ALICE, "org_A")
    assert len(impl.activity_list(w, ALICE, "org_A")) == 1


# ------------------------------------------------------------------ B0-23
def test_B0_23_validation_never_returns_the_stored_live_key(impl, w):
    r = impl.share_validate(w, "tok_A1", "sess_1")
    assert r["credential"] != w.share_tokens["tok_A1"]["stored_api_key"]


def test_B0_23_exchanged_credential_is_short_lived(impl, w):
    r = impl.share_validate(w, "tok_A1", "sess_1")
    assert r["expires_at"] is not None and r["expires_at"] - w.now <= 3600


def test_B0_23_credential_bound_to_agent_and_session(impl, w):
    c = impl.share_validate(w, "tok_A1", "sess_1")["credential"]
    w.agents["agent_A2"] = {"org": "org_A", "owner": "uid_alice", "project": "proj_A"}
    with pytest.raises(Denied):
        impl.share_use(w, c, "agent_A2", "sess_1", "webhook")        # another agent of the same org
    with pytest.raises(Denied):
        impl.share_use(w, c, "agent_A1", "sess_OTHER", "webhook")    # replay in another session
    assert impl.share_use(w, c, "agent_A1", "sess_1", "webhook") == "ok"


def test_B0_23_expired_credential_rejected(impl, w):
    c = impl.share_validate(w, "tok_A1", "sess_1")["credential"]
    w.now += 10 ** 6
    with pytest.raises(Denied):
        impl.share_use(w, c, "agent_A1", "sess_1", "webhook")


def test_B0_23_credential_cannot_be_replayed_outside_its_route_scope(impl, w):
    c = impl.share_validate(w, "tok_A1", "sess_1")["credential"]
    with pytest.raises(Denied):
        impl.share_use(w, c, "agent_A1", "sess_1", "leads.export")


# ------------------------------------------------------------------ B0-24
def _run(coro):
    return asyncio.run(coro)


def test_B0_24_valid_permission_passes(impl, w):
    _run(impl.engine_require_permission(w, "uid_alice", "org_A", "agents:write"))


def test_B0_24_unauthorized_access_denied_explicitly_not_by_accident(impl, w):
    try:
        _run(impl.engine_require_permission(w, "uid_alice", "org_B", "agents:read"))
    except HTTPException as e:
        assert e.status_code == 403
        return
    except TypeError as e:
        pytest.fail("denial was an accidental TypeError, not an authorization decision: %s" % e)
    pytest.fail("cross-org permission was granted")


def test_B0_24_viewer_cannot_write(impl, w):
    with pytest.raises(HTTPException) as e:
        _run(impl.engine_require_permission(w, "uid_viewer_A", "org_A", "agents:write"))
    assert e.value.status_code == 403
