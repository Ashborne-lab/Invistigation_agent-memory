"""B0-15 share/API-key route scope · B0-16 caller-controlled user_id · B0-17 email webhook. Invariants INV-S7, S8, S9."""
import pytest

from world import KEY_A, SHARE_A1, Denied


# ------------------------------------------------------------------ B0-15
@pytest.mark.parametrize("route", ["leads.list", "leads.export", "leads.import", "leads.erase"])
def test_B0_15_share_key_cannot_touch_org_wide_leads(impl, w, route):
    with pytest.raises(Denied):
        impl.runtime_call(w, SHARE_A1, route, org="org_A")


@pytest.mark.parametrize("route", ["memory.read", "memory.delete"])
def test_B0_15_share_key_cannot_read_or_delete_end_user_memory(impl, w, route):
    with pytest.raises(Denied):
        impl.runtime_call(w, SHARE_A1, route, path_agent="agent_A1", header_agent="agent_A1")


def test_B0_15_share_key_still_reaches_its_agent_webhook(impl, w):
    assert impl.runtime_call(w, SHARE_A1, "webhook", path_agent="agent_A1", header_agent="agent_A1") == "ok"


def test_B0_15_scope_is_enforced_by_server_not_inferred_from_caller(impl, w):
    # a key WITHOUT leads scope (an ordinary key with only agents:invoke) is refused even inside its own org
    from world import Principal
    k = Principal("api_key", uid="uid_alice", org="org_A", key_id="key_invoke", perms=("agents:invoke",))
    with pytest.raises(Denied):
        impl.runtime_call(w, k, "leads.export", org="org_A")


def test_B0_15_memory_route_path_agent_must_match_header_agent(impl, w):
    w.agents["agent_A2"] = {"org": "org_A", "owner": "uid_alice", "project": "proj_A"}
    with pytest.raises(Denied):
        impl.runtime_call(w, KEY_A, "memory.read", path_agent="agent_A2", header_agent="agent_A1")


def test_B0_15_full_key_keeps_legitimate_lead_access_in_own_org(impl, w):
    assert impl.runtime_call(w, KEY_A, "leads.list", org="org_A") == [{"id": "lead_a1"}]
    with pytest.raises(Denied):
        impl.runtime_call(w, KEY_A, "leads.list", org="org_B")


# ------------------------------------------------------------------ B0-16
VICTIM_PHONE = "+919800000001"


def test_B0_16_caller_cannot_select_another_customers_memory_by_asserting_their_id(impl, w):
    impl.store_verified_memory(w, "agent_A1", "whatsapp", VICTIM_PHONE, "SECRET victim memory")
    for caller in (KEY_A, SHARE_A1):
        assert impl.webhook_memory_lookup(w, caller, "agent_A1", VICTIM_PHONE) is None


def test_B0_16_channel_and_assurance_are_part_of_the_lookup(impl, w):
    assert impl.memory_key("agent_A1", "whatsapp", "channel_verified", VICTIM_PHONE) != \
        impl.memory_key("agent_A1", "api:key_A", "asserted", VICTIM_PHONE)
    assert impl.memory_key("agent_A1", "whatsapp", "channel_verified", VICTIM_PHONE) != \
        impl.memory_key("agent_A1", "email", "channel_verified", VICTIM_PHONE)


def test_B0_16_asserted_identity_cannot_read_verified_memory_even_with_identical_id(impl, w):
    impl.store_verified_memory(w, "agent_A1", "email", "victim@x.example", "SECRET")
    assert impl.webhook_memory_lookup(w, KEY_A, "agent_A1", "victim@x.example") is None


def test_B0_16_legitimate_channel_verified_lookup_still_works(impl, w):
    impl.store_verified_memory(w, "agent_A1", "whatsapp", VICTIM_PHONE, "her own memory")
    assert impl.channel_memory_lookup(w, "agent_A1", "whatsapp", VICTIM_PHONE) == "her own memory"


# ------------------------------------------------------------------ B0-17
def _form(**kw):
    f = {"from": "victim@x.example", "to": "agent-a1@inbound.synthetic", "cc": ["attacker@evil.example"],
         "SPF": "pass", "dkim": "{@x.example : pass}", "text": "hi"}
    f.update(kw)
    return f


def test_B0_17_missing_authentication_is_denied(impl, w):
    with pytest.raises(Denied):
        impl.email_webhook(w, _form(), None)


def test_B0_17_invalid_authentication_is_denied(impl, w):
    with pytest.raises(Denied):
        impl.email_webhook(w, _form(), "wrong-secret")


def test_B0_17_spf_or_dkim_failure_takes_the_unverified_path(impl, w):
    r = impl.email_webhook(w, _form(SPF="fail"), w.email_parse_secret)
    assert r["verified"] is False and r["subject_key"] is None
    r = impl.email_webhook(w, _form(dkim="{@x.example : fail}"), w.email_parse_secret)
    assert r["verified"] is False and r["subject_key"] is None


def test_B0_17_spoofed_sender_with_attacker_cc_receives_no_victim_memory(impl, w):
    impl.store_verified_memory(w, "agent_A1", "email", "victim@x.example", "SECRET victim memory")
    r = impl.email_webhook(w, _form(SPF="fail", dkim="none"), w.email_parse_secret)
    assert r["memory"] is None and r["memory_in_reply"] is False


def test_B0_17_legitimate_authenticated_mail_still_processes(impl, w):
    impl.store_verified_memory(w, "agent_A1", "email", "victim@x.example", "her own memory")
    r = impl.email_webhook(w, _form(cc=[]), w.email_parse_secret)
    assert r["accepted"] and r["verified"] and r["memory"] == "her own memory" and r["reply_to"] == ["victim@x.example"]
