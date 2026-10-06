"""Agent execution memory, visibility v1: the owner decision is CUSTOMER_SHARED for execution episodes AND commitments.
TEST_ONLY.

Contract: ``investigation/agent-execution-memory-foundation-v1.md``. Execution memory uses existing objects only:
member Evidence (ids), one ``episode_summary`` generation (journal A1) by a declared execution generator, Claims only
through the deterministic gate, commitments as ``commitment_event``. Visibility: any principal holding
("CUSTOMER", X) reads X's execution episodes and commitments, whatever agent created them. Access comes only from
the authenticated Caller (built from the signed handle); an ``agent_id`` on a record is attribution, never authority.
No agent-level grant exists, and AGENT_PRIVATE (rejected) is not implemented. Both reference stores."""
import dataclasses
import inspect

import pytest

from memory_core import commitments as CM
from memory_core import episode_commitment as EC
from memory_core import handle as H
from memory_core import journal_compaction as JC
from memory_core import retrieval as RT
from memory_core.context import compile_context
from memory_core.durable_journal import PROJECTED_KINDS, reconstruct
from memory_core.registry import Caller
from memory_core.retrieval import (ACCESS_DENIED, CURRENT_STATE, HISTORICAL, NARRATIVE, OK, MemorySource,
                                   get_commitments, get_current_state, search_memory)
from test_durable_storage_boundary import make
from test_integration import CHAT, CITY
from test_journal_compaction import KEY, erase, ev
from test_x1_commit_time import put

KINDS = ["explicit", "implied"]
EXEC_GEN = "TEST_ONLY_exec_generator/1"          # a declared execution generator family (foundation §B)
X, Y = "s1", "s2"                                # customers of tenant t1


def caller(agent, *subjects):
    """What the Gateway builds from a verified handle: principal = the handle's agent; scopes = its subject."""
    return Caller(agent, frozenset({("CUSTOMER", s) for s in subjects}))


A, B, C = caller("a1", X), caller("a2", X), caller("a3")          # C holds no grant at all


def exec_gen(epid, agent, members, summary, subj=X, usable=None):
    return EC.EpisodeGeneration(epid, subj, agent, "t1", tuple(members), tuple(members if usable is None else usable),
                                1.0, 2.0, summary, EXEC_GEN)


def setup(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    return wr, j


def r_of(j, subj, clock):
    return j.read(subj, clock).r


def source(j, subj, r, dead=frozenset(), undone=frozenset(), status=None):
    f = j.store.facts()
    rb = reconstruct(f, subj, r)
    return MemorySource(rb.journal, rb.policies, EC.episodes_at(f, subj, r, status or {}, undone),
                        EC.commitment_events_at(f, subj, r), dead, policy_history=f.policy_history)


def texts(res):
    return [it.value[1] for it in res.items]


# ============================================================================================ creation
@pytest.mark.parametrize("kind", KINDS)
def test_ec1_one_execution_episode_one_generation_in_the_customer_partition(kind):
    wr, j = setup(kind)
    g = exec_gen("ex1", "a1", ["tc1", "tr1", "dc1", "oc1"], "called crm lookup, it returned 404, retried, succeeded")
    assert EC.record_episode_generation(j, KEY, g, 2.0)[0] == "APPENDED"
    mine = [s for s in j.store.entries(X) if s.entry.kind == EC.EPISODE_SUMMARY]
    assert len(mine) == 1 and not [s for s in j.store.entries(Y) if s.entry.kind == EC.EPISODE_SUMMARY]
    assert EC.generations_at(j.store.facts(), X, r_of(j, X, 3.0))["ex1"].evidence_ids == ("tc1", "tr1", "dc1", "oc1")


@pytest.mark.parametrize("kind", KINDS)
def test_ec2_same_inputs_return_the_recorded_generation(kind):
    wr, j = setup(kind)
    assert EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "first text"), 2.0)[0] == "APPENDED"
    assert EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "other text"), 2.5)[0] == "DUPLICATE"
    assert EC.generations_at(j.store.facts(), X, r_of(j, X, 3.0))["ex1"].summary == "first text"


@pytest.mark.parametrize("kind", KINDS)
def test_ec3_a_changed_usable_set_is_a_new_generation_and_the_latest_wins(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1", "e2"], "two steps"), 2.0)
    assert EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1", "e2"], "one step", usable=["e1"]),
                                        2.5)[0] == "APPENDED"
    assert EC.generations_at(j.store.facts(), X, r_of(j, X, 3.0))["ex1"].summary == "one step"


@pytest.mark.parametrize("kind", KINDS)
def test_ec4_an_identity_less_generation_is_refused_and_nothing_is_durable(kind):
    wr, j = setup(kind)
    n = len(j.store.entries(X))
    assert EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "x", subj=""), 2.0) == \
        ("REJECTED", "identity_required")
    assert len(j.store.entries(X)) == n


# ============================================================================================ provenance / attribution
@pytest.mark.parametrize("kind", KINDS)
def test_pv1_retrieved_items_carry_member_evidence_as_provenance_and_the_generation_its_agent(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["tc1", "tr1"], "called crm tool"), 2.0)
    r = r_of(j, X, 3.0)
    res = search_memory(source(j, X, r), X, "crm", A)
    assert res.status == OK and res.items[0].provenance == ("tc1", "tr1")
    assert EC.generations_at(j.store.facts(), X, r)["ex1"].agent_id == "a1"            # attribution, not authority


@pytest.mark.parametrize("kind", KINDS)
def test_pv2_rebuild_from_facts_serves_the_same_items(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["tc1"], "called crm tool"), 2.0)
    r = r_of(j, X, 3.0)
    assert search_memory(source(j, X, r), X, "crm", A) == search_memory(source(j, X, r), X, "crm", A)
    assert EC.episodes_at(j.store.facts(), X, r, {}) == EC.episodes_at(j.store.facts(), X, r, {})


def test_at1_retrieval_takes_no_caller_supplied_agent_identity():
    """Access is decided from the Caller (the verified handle) only. No retrieval operation accepts an agent id, so a
    request cannot assert one."""
    for fn in (search_memory, get_commitments, get_current_state, RT.search_history):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"agent_id", "agent", "requesting_agent", "on_behalf_of"}, fn.__name__


def test_at2_a_forged_handle_agent_never_verifies():
    """The only source of the authenticated agent is the signed handle; altering it breaks the signature."""
    secret = b"TEST_ONLY_secret_for_handles_____"
    tok = H.issue(secret, H.Handle("o1", "a2", "sess", X, "anonymous", (), 0, 100.0))
    body, sig = tok.rsplit(".", 1)
    import base64
    import json
    forged = json.loads(base64.urlsafe_b64decode(body))
    forged["agent"] = "a1"
    forged_tok = base64.urlsafe_b64encode(json.dumps(forged, sort_keys=True).encode()).decode() + "." + sig
    assert H.verify(secret, tok, 1.0).agent == "a2"
    with pytest.raises(H.HandleError):
        H.verify(secret, forged_tok, 1.0)


# ============================================================================================ partitioning
@pytest.mark.parametrize("kind", KINDS)
def test_pt1_an_agent_serving_two_customers_writes_each_episode_to_its_own_partition(kind):
    wr, j = setup(kind)
    put(j, wr, "d1", CITY, "goa", 1.5, subj=Y)
    EC.record_episode_generation(j, KEY, exec_gen("exX", "a1", ["e1"], "crm call for X"), 2.0)
    EC.record_episode_generation(j, KEY, exec_gen("exY", "a1", ["e2"], "crm call for Y", subj=Y), 2.0)
    rx, ry = r_of(j, X, 3.0), r_of(j, Y, 3.0)
    assert texts(search_memory(source(j, X, rx), X, "crm", caller("a1", X, Y))) == ["crm call for X"]
    assert texts(search_memory(source(j, Y, ry), Y, "crm", caller("a1", X, Y))) == ["crm call for Y"]


# ============================================================================================ retrieval
@pytest.mark.parametrize("kind", KINDS)
def test_rt1_execution_memory_is_narrative_historical_and_never_current_state(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm said city goa"), 2.0)
    src = source(j, X, r_of(j, X, 3.0))
    it = search_memory(src, X, "crm", A).items[0]
    assert (it.retrieval_type, it.status, it.usage) == (NARRATIVE, "NARRATIVE", HISTORICAL)
    cs = get_current_state(src, X, None, 3.0, 3.0, A)
    assert all(i.retrieval_type == CURRENT_STATE for i in cs.items)
    assert [i.value for i in cs.items] == [("text", "pune")]                     # the summary changed nothing


@pytest.mark.parametrize("kind", KINDS)
def test_rt2_rt3_dead_member_evidence_and_quarantined_or_pending_episodes_are_excluded(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, dataclasses.replace(exec_gen("ex1", "a1", ["e1"], "crm one"),
                                                             merge_ids=("m1",)), 2.0)
    EC.record_episode_generation(j, KEY, exec_gen("ex2", "a1", ["e2"], "crm two"), 2.0)
    r = r_of(j, X, 3.0)
    assert sorted(texts(search_memory(source(j, X, r), X, "crm", A))) == ["crm one", "crm two"]
    assert texts(search_memory(source(j, X, r, dead=frozenset({"e2"})), X, "crm", A)) == ["crm one"]   # RT-2
    assert texts(search_memory(source(j, X, r, undone=frozenset({"m1"})), X, "crm", A)) == ["crm two"]  # RT-3
    assert texts(search_memory(source(j, X, r, status={"e1": EC.SUPPRESSED}), X, "crm", A)) == ["crm two"]


# ============================================================================================ context compilation
def _compile(results, budget=4000):
    cc = compile_context(results, CHAT, budget, "a2", {"request_id": "TEST_ONLY"})
    return cc


@pytest.mark.parametrize("kind", KINDS)
def test_cx1_execution_episodes_compile_only_into_the_non_authoritative_narrative_section(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm lookup returned order shipped"), 2.0)
    src = source(j, X, r_of(j, X, 3.0))
    cc = _compile([get_current_state(src, X, None, 3.0, 3.0, B), search_memory(src, X, "crm", B)])
    narrative = cc.text.split("## Narrative context (background only; not authoritative)", 1)
    assert len(narrative) == 2 and "crm lookup" in narrative[1] and "crm lookup" not in narrative[0]


def test_cx2_a_narrative_item_claiming_authority_is_rejected_by_the_compiler():
    forged = RT.MemoryItem(NARRATIVE, X, ("CUSTOMER", X), None, ("text", "order shipped"), "NARRATIVE", 1.0, 2.0,
                           "FRESH", "OPERATIONAL", ("e1",), None, None, None)
    cc = _compile([RT.RetrievalResult(NARRATIVE, OK, (forged,))])
    assert "order shipped" not in cc.text
    assert "narrative_claims_authority" in repr(cc.manifest)


@pytest.mark.parametrize("kind", KINDS)
def test_cx3_optional_narrative_is_dropped_by_budget_without_failing(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm " + "x" * 300), 2.0)
    src = source(j, X, r_of(j, X, 3.0))
    full = _compile([get_current_state(src, X, None, 3.0, 3.0, B), search_memory(src, X, "crm", B)])
    small = _compile([get_current_state(src, X, None, 3.0, 3.0, B), search_memory(src, X, "crm", B)],
                     budget=len(full.text) - 50)
    assert small.status == "COMPILED" and "xxxxx" not in small.text and "pune" in small.text


# ============================================================================================ Claim-Gate boundary
@pytest.mark.parametrize("kind", KINDS)
def test_cg1_an_execution_summary_stating_a_world_fact_changes_no_state(kind):
    wr, j = setup(kind)
    before = reconstruct(j.store.facts(), X, r_of(j, X, 3.0))
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm says city is goa; order 123 SHIPPED"),
                                 3.5)
    after = reconstruct(j.store.facts(), X, r_of(j, X, 4.0))
    assert after.state.slots == before.state.slots and after.trace == before.trace
    assert after.state.claims_version == before.state.claims_version


@pytest.mark.parametrize("kind", KINDS)
def test_cg2_a_trusted_observation_becomes_a_claim_only_through_the_gate_with_evidence_provenance(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["ev_tool"], "crm says city is goa"), 2.0)
    assert put(j, wr, "c2", CITY, "goa", 3.0)[0] == "APPENDED"                    # the gate + commit path
    src = source(j, X, r_of(j, X, 4.0))
    it = get_current_state(src, X, None, 4.0, 4.0, A).items[0]
    assert it.value == ("text", "goa")
    assert "ex1" not in it.provenance and "ev_tool" not in it.provenance         # never the episode


def test_cg3_neither_a1_kind_is_consumed_by_the_claim_projection():
    assert EC.EPISODE_SUMMARY not in PROJECTED_KINDS and EC.COMMITMENT_EVENT not in PROJECTED_KINDS


# ============================================================================================ commitment boundary
def cev(eid, kind, at, actor, agent="a1", subj=X):
    return dataclasses.replace(ev(eid, "k1", kind, at, actor, subj=subj), agent_id=agent)


@pytest.mark.parametrize("kind", KINDS)
def test_cm1_cm2_cm3_commitments_are_separate_from_execution_episodes(kind):
    wr, j = setup(kind)
    assert EC.record_commitment_event(j, KEY, cev("x1", "create", 1.0, "agent"), 2.0)[0] == "APPENDED"
    EC.record_commitment_event(j, KEY, cev("x2", "confirm_tool_success", 1.5, "tool"), 2.2)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "promised a callback; it is fulfilled"), 2.5)
    head = EC.commitments_at(j.store.facts(), X, r_of(j, X, 3.0))["k1"]
    assert head.state == CM.CONFIRMED and head.events == ("x1", "x2")              # CM-2: the summary changed nothing
    EC.record_commitment_event(j, KEY, cev("x3", "fulfil", 3.2, "tool"), 3.5)       # CM-3: a real fulfil event
    assert EC.commitments_at(j.store.facts(), X, r_of(j, X, 4.0))["k1"].state == CM.FULFILLED
    assert EC.generations_at(j.store.facts(), X, r_of(j, X, 4.0))["ex1"].summary == \
        "promised a callback; it is fulfilled"                                      # the episode is unchanged


# ============================================================================================ replay / rebuild
@pytest.mark.parametrize("kind", KINDS)
def test_rp1_checkpoint_plus_suffix_serves_the_same_generations_and_commitments_as_a_full_replay(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm one"), 2.0)
    cps = JC.CheckpointStore(j.store)
    assert JC.create(j, cps, X, 2.5)[0] == "CREATED"
    EC.record_episode_generation(j, KEY, exec_gen("ex2", "a2", ["e2"], "crm two"), 3.0)
    EC.record_commitment_event(j, KEY, cev("x1", "create", 3.1, "agent", agent="a2"), 3.2)
    f, r = j.store.facts(), r_of(j, X, 4.0)
    a, b = JC.rebuild(f, X, r, cps), JC.full_replay(f, X, r)
    assert a.source == "checkpoint" and a.generations == b.generations and a.commitment_events == b.commitment_events


@pytest.mark.parametrize("kind", KINDS)
def test_rp2_a_retried_write_after_a_lost_acknowledgement_is_one_entry(kind):
    wr, j = setup(kind)
    g = exec_gen("ex1", "a1", ["e1"], "crm one")
    EC.record_episode_generation(j, KEY, g, 2.0)
    assert EC.record_episode_generation(j, KEY, g, 2.0)[0] == "DUPLICATE"
    assert sum(s.entry.kind == EC.EPISODE_SUMMARY for s in j.store.entries(X)) == 1


# ============================================================================================ erasure
@pytest.mark.parametrize("kind", KINDS)
def test_er1_customer_erasure_removes_execution_memory_and_commitments_for_every_agent(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm one"), 2.0)
    EC.record_commitment_event(j, KEY, cev("x1", "create", 2.1, "agent"), 2.2)
    erase(j, X, 3.0, destroy=True)
    f, r = j.store.facts(), r_of(j, X, 4.0)
    assert EC.generations_at(f, X, r) == {} and EC.commitment_events_at(f, X, r) == ()
    for who in (A, B):
        assert search_memory(source(j, X, r), X, "crm", who).items == ()
        assert get_commitments(source(j, X, r), X, 4.0, who).items == ()
    assert EC.record_episode_generation(j, KEY, exec_gen("ex2", "a2", ["e2"], "late"), 5.0)[0] == "REJECTED"


@pytest.mark.parametrize("kind", KINDS)
def test_er2_er3_session_fence_and_merge_undo_hide_the_episode_from_every_agent(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, dataclasses.replace(exec_gen("ex1", "a1", ["e1"], "crm one"),
                                                             merge_ids=("m1",)), 2.0)
    r = r_of(j, X, 3.0)
    for who in (A, B):
        assert search_memory(source(j, X, r, dead=frozenset({"e1"})), X, "crm", who).items == ()
        assert search_memory(source(j, X, r, undone=frozenset({"m1"})), X, "crm", who).items == ()


# ============================================================================================ visibility (owner decision)
@pytest.mark.parametrize("kind", KINDS)
def test_oa1_the_originating_agent_reads_its_execution_episode(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm one"), 2.0)
    assert texts(search_memory(source(j, X, r_of(j, X, 3.0)), X, "crm", A)) == ["crm one"]


@pytest.mark.parametrize("kind", KINDS)
def test_xa1_customer_shared_another_authorized_agent_reads_it(kind):
    """OWNER DECISION 1 = CUSTOMER_SHARED: B holds (CUSTOMER, X) and reads A's execution episode."""
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm one"), 2.0)
    res = search_memory(source(j, X, r_of(j, X, 3.0)), X, "crm", B)
    assert res.status == OK and texts(res) == ["crm one"]


@pytest.mark.parametrize("kind", KINDS)
def test_xa2_customer_shared_another_agents_context_includes_it(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm lookup succeeded"), 2.0)
    src = source(j, X, r_of(j, X, 3.0))
    assert "crm lookup succeeded" in _compile([search_memory(src, X, "crm", B)]).text


@pytest.mark.parametrize("kind", KINDS)
def test_cm4_customer_shared_another_authorized_agent_reads_the_commitment(kind):
    """OWNER DECISION 2 = YES: commitments follow the same customer-shared rule."""
    wr, j = setup(kind)
    EC.record_commitment_event(j, KEY, cev("x1", "create", 1.0, "agent", agent="a1"), 2.0)
    res = get_commitments(source(j, X, r_of(j, X, 3.0)), X, 3.0, B)
    assert res.status == OK and len(res.items) == 1 and res.items[0].provenance == ("x1",)


@pytest.mark.parametrize("kind", KINDS)
def test_ua1_an_agent_without_the_customer_grant_gets_nothing(kind):
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm one"), 2.0)
    EC.record_commitment_event(j, KEY, cev("x1", "create", 1.0, "agent"), 2.1)
    src = source(j, X, r_of(j, X, 3.0))
    for res in (search_memory(src, X, "crm", C), get_commitments(src, X, 3.0, C)):
        assert res.status == ACCESS_DENIED and res.items == ()                    # no content, no provenance


@pytest.mark.parametrize("kind", KINDS)
def test_ua2_a_subject_reference_is_not_authorization(kind):
    """An agent holding another customer's grant (or another tenant's) names X: denied."""
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm one"), 2.0)
    src = source(j, X, r_of(j, X, 3.0))
    for who in (caller("a1", Y), caller("t2_agent", "z1")):
        assert search_memory(src, X, "crm", who).status == ACCESS_DENIED
        assert get_commitments(src, X, 3.0, who).status == ACCESS_DENIED


@pytest.mark.parametrize("kind", KINDS)
def test_ua3_attribution_confers_no_access(kind):
    """C's principal equals the episode's agent_id but C holds no (CUSTOMER, X) grant: denied. The agent_id on a
    record is attribution only; it can neither grant nor (CUSTOMER_SHARED) restrict access."""
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a3", ["e1"], "crm one"), 2.0)
    assert search_memory(source(j, X, r_of(j, X, 3.0)), X, "crm", caller("a3")).status == ACCESS_DENIED


def test_rj1_the_rejected_agent_private_policy_and_any_agent_grant_are_absent():
    """The rejected AGENT_PRIVATE policy is not active and no agent-level grant mechanism exists."""
    for fn in (search_memory, get_commitments):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"policy", "visibility", "grants", "agent_grants"}, fn.__name__
    assert set(f.name for f in dataclasses.fields(Caller)) == {"principal", "authorized_scopes", "cleared_classes"}
    assert not [n for n in dir(RT) if "agent_private" in n.lower() or "agent_grant" in n.lower()]


# ============================================================================================ determinism
@pytest.mark.parametrize("kind", KINDS)
def test_dt1_the_same_facts_query_and_caller_give_byte_identical_results(kind):
    def run():
        wr, j = setup(kind)
        EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm one"), 2.0)
        EC.record_episode_generation(j, KEY, exec_gen("ex2", "a2", ["e2"], "crm two"), 2.0)
        EC.record_commitment_event(j, KEY, cev("x1", "create", 1.0, "agent"), 2.1)
        src = source(j, X, r_of(j, X, 3.0))
        res = [search_memory(src, X, "crm", B), get_commitments(src, X, 3.0, B)]
        cc = _compile(res)
        return repr(res), cc.text, repr(cc.manifest)
    assert run() == run()
