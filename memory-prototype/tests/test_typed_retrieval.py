"""Typed retrieval. Policies are TEST_ONLY_* (placeholder governance values; never production policy)."""
import copy
import inspect

import pytest

from memory_core import commitments as CM
from memory_core.model import (ACTIVE, CONFLICT, NEVER_TRUE, NO_LONGER_TRUE, PENDING_ERASURE, QUARANTINED, UNKNOWN,
                               VALUE, Episode)
from memory_core.registry import Caller
from memory_core.retrieval import (INVALID_SCOPE, ACCESS_DENIED, COMMITMENT, CURRENT_STATE, H_CURRENT, H_ENDED, H_IN_CONFLICT,
                                   H_NOT_SELECTED, H_SUPERSEDED, HISTORICAL, HISTORY, NARRATIVE, OK,
                                   UNKNOWN_PREDICATE, UNSUPPORTED_CAPABILITY, UNSUPPORTED_SCOPE, MemorySource,
                                   get_commitments, get_current_state, get_relationships, get_tenant_knowledge,
                                   search_history, search_memory)
from test_current_state import BILL, CITY, EMPLOYER, P, POLICIES, W

HEALTH = P("health", security_class="sensitive", ranks={"USER": 1})
POL = {**POLICIES, HEALTH.predicate: HEALTH}
SCOPE = ("CUSTOMER", "s1")
ALICE = Caller("alice", frozenset({SCOPE}))
BOB = Caller("bob", frozenset({SCOPE}))
STRANGER = Caller("mallory", frozenset({("CUSTOMER", "s9")}))
CLEARED = Caller("doc", frozenset({SCOPE}), frozenset({"standard", "sensitive"}))


def src(w, episodes=(), events=(), dead=frozenset()):
    return MemorySource(tuple(w.store.journal), POL, tuple(episodes), tuple(events), dead)


def world():
    w = W()
    w.put(CITY, "pune", observed=10)
    w.put(CITY, "delhi", observed=20, valid_from=20)          # same source group supersedes pune from t=20
    w.put(EMPLOYER, "acme", observed=21)
    w.put(EMPLOYER, "globex", source="HR_SYSTEM", observed=22)  # outranks acme
    w.put(HEALTH, "asthma", observed=23)
    w.t = 30
    return w


# ------------------------------------------------------------------------------------------------- current state
def test_current_state_returns_projection_with_metadata():
    w = world()
    r = get_current_state(src(w), "s1", CITY.predicate, w.t, w.t, ALICE)
    (it,) = r.items
    assert (r.status, it.retrieval_type, it.value, it.status, it.policy_version, it.state_version) == (
        OK, CURRENT_STATE, ("text", "delhi"), VALUE, 7, 2)
    assert it.provenance and it.usage == "OPERATIONAL" and it.scope == SCOPE and it.authority_domain


def test_current_state_listing_omits_uncleared_sensitive_predicates():
    w = world()
    preds = {i.predicate for i in get_current_state(src(w), "s1", None, w.t, w.t, ALICE).items}
    assert HEALTH.predicate not in preds and CITY.predicate in preds
    assert HEALTH.predicate in {i.predicate for i in get_current_state(src(w), "s1", None, w.t, w.t, CLEARED).items}


def test_sensitive_predicate_without_clearance_denied_without_leak():
    w = world()
    r = get_current_state(src(w), "s1", HEALTH.predicate, w.t, w.t, ALICE)
    assert (r.status, r.items) == (ACCESS_DENIED, ())
    ok = get_current_state(src(w), "s1", HEALTH.predicate, w.t, w.t, CLEARED)
    assert ok.items[0].value == ("text", "asthma")


@pytest.mark.parametrize("fn", ["state", "history", "memory", "commitments"])
def test_unauthorized_caller_gets_access_denied_and_nothing_else(fn):
    w = world()
    s = src(w, episodes=[Episode("ep1", "s1", "a1", ["e1"], 1, 2, "moved to delhi", "ok")])
    r = {"state": lambda: get_current_state(s, "s1", CITY.predicate, w.t, w.t, STRANGER),
         "history": lambda: search_history(s, "s1", CITY.predicate, w.t, STRANGER),
         "memory": lambda: search_memory(s, "s1", "delhi", STRANGER),
         "commitments": lambda: get_commitments(s, "s1", w.t, STRANGER)}[fn]()
    assert r.status == ACCESS_DENIED and r.items == () and r.reason == ""


def test_same_request_same_result_for_every_authorized_caller():
    w = world()
    s = src(w)
    for q in (lambda c: get_current_state(s, "s1", None, w.t, w.t, c),
              lambda c: search_history(s, "s1", None, w.t, c)):
        assert q(ALICE) == q(BOB)                 # caller changes whether, never which


def test_stale_current_value_labelled_not_promoted():
    w = W()
    w.put(BILL, "gurgaon", source="OPERATOR", observed=5)
    w.sync(BILL, 2)                                                 # C-C: a recorded sync, not a parameter
    w.t = 10
    r = get_current_state(src(w), "s1", BILL.predicate, 10, 10, ALICE).items[0]
    assert (r.value, r.freshness_status, r.usage) == (("text", "gurgaon"), "STALE", "DISPLAY_ONLY")


# ------------------------------------------------------------------------------------------------- history
def _by_value(r):
    return {i.value[1]: i for i in r.items}


def test_history_labels_and_never_promotes():
    w = world()
    h = _by_value(search_history(src(w), "s1", None, w.t, ALICE))
    assert h["delhi"].status == H_CURRENT and h["pune"].status == H_SUPERSEDED
    assert h["pune"].valid_until == 20                       # temporal label on the superseded value
    assert h["globex"].status == H_CURRENT and h["acme"].status == H_NOT_SELECTED
    assert all(i.usage == HISTORICAL for i in h.values())    # history is never operational truth
    assert "asthma" not in h                                 # sensitive, uncleared: omitted


def test_history_preserves_provenance():
    w = world()
    it = _by_value(search_history(src(w), "s1", CITY.predicate, w.t, ALICE))["pune"]
    assert it.provenance[0].startswith("clm_") and it.provenance[1:] and it.source == "USER"
    assert (it.policy_version, it.observed_at, it.retrieval_type) == (7, 10, HISTORY)


def test_history_for_a_past_window():
    w = world()
    r = search_history(src(w), "s1", CITY.predicate, w.t, ALICE, valid_window=(11, 15))
    assert [i.value[1] for i in r.items] == ["pune"]


def test_retracted_claims_follow_lifecycle_semantics():
    w = W()
    w.put(CITY, "pune", observed=10)
    w.put(CITY, "delhi", observed=11, member="m2")
    w.retract(CITY, "pune", cause=NO_LONGER_TRUE)
    w.retract(CITY, "delhi", member="m2", cause=NEVER_TRUE)
    h = _by_value(search_history(src(w), "s1", CITY.predicate, w.t, ALICE))
    assert h["pune"].status == H_ENDED and h["pune"].valid_until is not None
    assert "delhi" not in h                                   # never true: not history of truth


@pytest.mark.parametrize("to", [QUARANTINED, PENDING_ERASURE])
def test_quarantined_and_pending_erasure_excluded_everywhere(to):
    w = W()
    cid = w.put(CITY, "pune", observed=10)
    w.life(cid, to)
    s = src(w)
    assert search_history(s, "s1", CITY.predicate, w.t, ALICE).items == ()
    cur = get_current_state(s, "s1", CITY.predicate, w.t, w.t, ALICE).items[0]
    assert cur.status == UNKNOWN and cur.value is None
    w.life(cid, ACTIVE)
    assert search_history(src(w), "s1", CITY.predicate, w.t, ALICE).items[0].status == H_CURRENT


def test_conflict_is_reported_in_history_and_not_resolved():
    w = W()
    w.put(CITY, "pune", source="USER", observed=10)
    w.put(CITY, "delhi", source="OPERATOR", observed=11)
    cur = get_current_state(src(w), "s1", CITY.predicate, w.t, w.t, ALICE).items[0]
    assert cur.status == CONFLICT and cur.value is None and len(cur.provenance) == 2
    assert {i.status for i in search_history(src(w), "s1", CITY.predicate, w.t, ALICE).items} == {H_IN_CONFLICT}


def test_stale_history_is_labelled():
    w = W()
    w.put(BILL, "gurgaon", source="OPERATOR", observed=5)
    w.sync(BILL, 2)
    it = search_history(src(w), "s1", BILL.predicate, 10, ALICE).items[0]
    assert (it.freshness_status, it.usage) == ("STALE", HISTORICAL)


# ------------------------------------------------------------------------------------------------- narrative
def test_narrative_search_is_deterministic_and_lifecycle_aware():
    w = world()
    eps = [Episode("ep1", "s1", "a1", ["e1"], 1, 2, "customer moved to delhi for work", "ok"),
           Episode("ep2", "s1", "a1", ["e2"], 5, 6, "talked about delhi weather", "ok"),
           Episode("ep3", "s1", "a1", ["e3"], 7, 8, "delhi delhi secret", "quarantined"),
           Episode("ep4", "s1", "a1", ["e4"], 9, 9.5, "delhi plans", "ok"),
           Episode("ep5", "s2", "a1", ["e5"], 9, 9.5, "delhi other person", "ok")]
    s = src(w, episodes=eps, dead=frozenset({"e4"}))
    r = search_memory(s, "s1", "moved delhi", ALICE)
    assert [i.provenance for i in r.items] == [("e1",), ("e2",)]       # overlap, then recency
    assert all(i.retrieval_type == NARRATIVE and i.usage == HISTORICAL for i in r.items)
    assert r == search_memory(s, "s1", "moved delhi", ALICE)


# ------------------------------------------------------------------------------------------------- commitments
def test_commitments_use_the_existing_event_projection():
    w = world()
    idn = dict(subject_id="s1", agent_id="a1", tenant_id="o1")
    ev = [CM.Event("c1", "k1", "create", 1, "agent", "e1", due_until=50, **idn),
          CM.Event("c2", "k1", "confirm_assent", 2, "user", "e2", **idn),
          CM.Event("c3", "k2", "create", 3, "agent", "e3", due_until=20, **idn),
          CM.Event("c4", "k3", "create", 4, "agent", "e_dead", **idn),
          CM.Event("c5", "k4", "create", 5, "agent", "e5", subject_id="s2", agent_id="a1", tenant_id="o1"),
          CM.Event("c6", "k5", "create", 6, "agent", "e6"),                       # identity-less: never served
          CM.Event("c7", "k1", "cancel", 7, "user", "e7", subject_id="s9", agent_id="a1", tenant_id="o1")]
    r = get_commitments(src(w, events=ev, dead=frozenset({"e_dead"})), "s1", 30, ALICE)
    states = {i.provenance[0]: i.status for i in r.items}
    assert states == {"c1": CM.CONFIRMED, "c3": CM.EXPIRED}               # read-time expiry; erased evidence gone
    assert all(i.retrieval_type == COMMITMENT for i in r.items)


# ------------------------------------------------------------------------------------------------- unsupported / unknown
def test_unknown_predicate():
    w = world()
    assert get_current_state(src(w), "s1", "TEST_ONLY_nope", w.t, w.t, ALICE).status == UNKNOWN_PREDICATE
    assert search_history(src(w), "s1", "TEST_ONLY_nope", w.t, ALICE).status == UNKNOWN_PREDICATE


@pytest.mark.parametrize("scope", ["TENANT", "WORKSPACE", "AGENT", "SESSION", "RESOURCE", "GLOBAL"])
def test_unsupported_scopes_are_explicit(scope):
    w = world()
    s = src(w)
    for r in (get_current_state(s, "s1", CITY.predicate, w.t, w.t, ALICE, scope_type=scope),
              search_history(s, "s1", None, w.t, ALICE, scope_type=scope),
              search_memory(s, "s1", "x", ALICE, scope_type=scope),
              get_commitments(s, "s1", w.t, ALICE, scope_type=scope)):
        assert r.status == UNSUPPORTED_SCOPE and r.items == ()


def test_unmodelled_capabilities_are_explicit():
    assert get_relationships().status == UNSUPPORTED_CAPABILITY
    assert get_tenant_knowledge().status == UNSUPPORTED_SCOPE


# ------------------------------------------------------------------------------------------------- architecture
def test_retrieval_does_not_mutate_or_create_memory_or_depend_on_caller():
    w = world()
    w.retract(CITY, "pune")
    eps = (Episode("ep1", "s1", "a1", ["e1"], 1, 2, "moved to delhi", "ok"),)
    s = src(w, episodes=eps)
    journal_before = copy.deepcopy(w.store.journal)
    claims_before = copy.deepcopy(w.store.claims)
    state_before = w.project()
    for caller in (ALICE, BOB, STRANGER, CLEARED):
        get_current_state(s, "s1", None, w.t, w.t, caller)
        search_history(s, "s1", None, w.t, caller)
        search_memory(s, "s1", "delhi", caller)
        get_commitments(s, "s1", w.t, caller)
    assert w.store.journal == journal_before and w.store.claims == claims_before   # no mutation, no new memory
    assert w.project() == state_before                                            # Current State unchanged
    assert get_current_state(s, "s1", None, w.t, w.t, ALICE) == get_current_state(s, "s1", None, w.t, w.t, BOB)
    for fn in (get_current_state, search_history, search_memory, get_commitments):
        assert "llm" not in inspect.signature(fn).parameters


def test_access_denied_carries_no_provenance_anywhere():
    w = world()
    for r in (get_current_state(src(w), "s1", CITY.predicate, w.t, w.t, STRANGER),
              get_current_state(src(w), "s1", HEALTH.predicate, w.t, w.t, ALICE),
              search_history(src(w), "s1", None, w.t, STRANGER)):
        assert r.status == ACCESS_DENIED and r.items == () and r.reason == ""


def test_unauthorized_listing_is_denied_not_an_empty_ok():
    w = world()
    for r in (get_current_state(src(w), "s1", None, w.t, w.t, STRANGER), search_history(src(w), "s1", None, w.t, STRANGER)):
        assert (r.status, r.items) == (ACCESS_DENIED, ())


def test_non_contract_scope_names_are_invalid_not_unsupported():
    w = world()
    for name in ("ORG", "PERSON", "RELATIONSHIP", "EPISODE"):
        r = get_current_state(src(w), "s1", CITY.predicate, w.t, w.t, ALICE, scope_type=name)
        assert (r.status, r.items) == (INVALID_SCOPE, ())


def test_commitments_carry_identity_and_mismatched_events_are_refused():
    w = world()
    idn = dict(subject_id="s1", agent_id="a1", tenant_id="o1")
    ev = [CM.Event("c1", "k1", "create", 1, "agent", "e1", due_until=50, **idn),
          CM.Event("c2", "k1", "cancel", 2, "user", "e2", subject_id="s9", agent_id="a1", tenant_id="o1")]
    (it,) = get_commitments(src(w, events=ev), "s1", 10, ALICE).items
    assert (it.status, it.source, it.authority_domain) == (CM.PROPOSED, "a1", "o1")   # foreign cancel refused
    assert CM.project(ev, 10)["k1"].rejected == (("c2", "identity_mismatch"),)
