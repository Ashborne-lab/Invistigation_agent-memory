"""B0-12 require_org_access · B0-13 studio-backend create/fork · B0-14 agent-design. Invariants INV-S1, S2, S7."""
import pytest

from world import ALICE, BOB, KEY_A, VIEWER_A, Denied, Principal


# ------------------------------------------------------------------ B0-12
def test_B0_12_firebase_user_from_A_cannot_access_org_B(impl, w):
    with pytest.raises(Denied):
        impl.require_org_access(w, ALICE, "org_B")


def test_B0_12_firebase_member_of_A_can_access_org_A(impl, w):
    impl.require_org_access(w, ALICE, "org_A")


def test_B0_12_api_key_for_A_cannot_access_org_B(impl, w):
    with pytest.raises(Denied):
        impl.require_org_access(w, KEY_A, "org_B")


def test_B0_12_api_key_for_A_can_access_org_A(impl, w):
    impl.require_org_access(w, KEY_A, "org_A")


def test_B0_12_caller_supplied_org_never_overrides_server_derived_org(impl, w):
    # Alice names her own org in the body while targeting org B's agent: the server must use the agent's org.
    with pytest.raises(Denied):
        impl.access_org_resource(w, ALICE, "agent", "agent_B1", body_org="org_A")


def test_B0_12_unauthenticated_or_unknown_principal_is_denied(impl, w):
    with pytest.raises(Denied):
        impl.require_org_access(w, Principal("anonymous"), "org_A")


# ------------------------------------------------------------------ B0-13
def test_B0_13_cannot_create_agent_in_another_orgs_project(impl, w):
    with pytest.raises(Denied):
        impl.create_agent(w, ALICE, "proj_B")
    assert not [a for a, d in w.agents.items() if d["org"] == "org_B" and d["owner"] == "uid_alice"]


def test_B0_13_cannot_create_agent_by_naming_own_org_in_body(impl, w):
    with pytest.raises(Denied):
        impl.create_agent(w, ALICE, "proj_B", body_org="org_A")


def test_B0_13_cannot_fork_another_orgs_agent(impl, w):
    with pytest.raises(Denied):
        impl.fork_agent(w, ALICE, "agent_B1")


def test_B0_13_cannot_fork_into_victim_org_and_inherit_knowledge(impl, w):
    try:
        impl.fork_agent(w, ALICE, "agent_B1", target_project="proj_B")
    except Denied:
        pass
    assert w.knowledge["kb_B"] == {"agent_B1"}          # no attacker-owned agent gained knowledge access
    assert not [a for a, d in w.agents.items() if d.get("owner") == "uid_alice" and d["org"] == "org_B"]


def test_B0_13_cannot_list_forks_or_preflight_another_orgs_agent(impl, w):
    with pytest.raises(Denied):
        impl.list_forks(w, ALICE, "agent_B1")
    with pytest.raises(Denied):
        impl.fork_preflight(w, ALICE, "agent_B1")


def test_B0_13_legitimate_same_org_create_and_fork_still_work(impl, w):
    aid = impl.create_agent(w, ALICE, "proj_A")
    fid = impl.fork_agent(w, ALICE, "agent_A1")
    assert w.agents[aid]["org"] == "org_A" and w.agents[fid]["org"] == "org_A"
    assert impl.list_forks(w, ALICE, "agent_A1") == [fid]


# ------------------------------------------------------------------ B0-14
def test_B0_14_get_agent_cross_org_denied_for_user_and_key(impl, w):
    for p in (ALICE, KEY_A):
        with pytest.raises(Denied):
            impl.get_agent(w, p, "agent_B1")


def test_B0_14_list_by_project_cannot_cross_org(impl, w):
    for p in (ALICE, KEY_A):
        with pytest.raises(Denied):
            impl.list_agents(w, p, project_id="proj_B")


def test_B0_14_active_agents_requires_membership(impl, w):
    with pytest.raises(Denied):
        impl.active_agents(w, ALICE, "org_B")
    assert impl.active_agents(w, ALICE, "org_A") == ["agent_A1"]


def test_B0_14_agent_users_read_write_delete_enforce_agent_and_org(impl, w):
    with pytest.raises(Denied):
        impl.agent_user_read(w, ALICE, "agent_B1", "eu_B1")
    with pytest.raises(Denied):
        impl.agent_user_write(w, ALICE, "agent_B1", "eu_B1", {"opted_out": False})   # would re-enable outreach
    with pytest.raises(Denied):
        impl.agent_user_delete(w, ALICE, "agent_B1", "eu_B1")
    with pytest.raises(Denied):                                                       # row of another agent
        impl.agent_user_read(w, ALICE, "agent_A1", "eu_B1")
    assert w.agent_users["eu_B1"]["opted_out"] is True


def test_B0_14_agent_users_viewer_can_read_not_write(impl, w):
    assert impl.agent_user_read(w, VIEWER_A, "agent_A1", "eu_A1")["agent"] == "agent_A1"
    with pytest.raises(Denied):
        impl.agent_user_write(w, VIEWER_A, "agent_A1", "eu_A1", {"notes": "x"})


def test_B0_14_blueprint_install_cannot_target_unauthorized_project(impl, w):
    with pytest.raises(Denied):
        impl.install_blueprint(w, ALICE, "proj_B")
    assert impl.install_blueprint(w, ALICE, "proj_A") == "installed:proj_A"


def test_B0_14_store_admin_approval_requires_verified_admin(impl, w):
    with pytest.raises(Denied):
        impl.store_admin_approve(w, ALICE, "sub_1")
    assert w.submissions["sub_1"] == "pending"
    admin = Principal("firebase", uid="uid_staff", email="staff@olbrain.com", email_verified=True,
                      provider="google.com", hd="olbrain.com")
    impl.store_admin_approve(w, admin, "sub_1")
    assert w.submissions["sub_1"] == "approved"


def test_B0_14_legitimate_same_org_reads_still_work(impl, w):
    assert impl.get_agent(w, ALICE, "agent_A1")["org"] == "org_A"
    assert impl.list_agents(w, KEY_A, project_id="proj_A") == ["agent_A1"]
