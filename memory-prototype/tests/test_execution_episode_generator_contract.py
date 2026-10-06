"""Execution-episode generator contract v1: the DURABLE-SURFACE guarantees a future generator relies on. TEST_ONLY.

Contract: ``investigation/execution-episode-generator-contract-v1.md``. No generator exists in the prototype and none
is built here; these tests pin what the existing surface (``episode_commitment``) already guarantees: generation
identity depends only on inputs (never on text or attribution), separate episodes stay separate, regeneration over a
changed usable set is a new generation, and the recorded outcome survives process loss and a fresh journal. Both
reference stores. The generator-side rules (grouping refusals, trusted-context attribution, non-procedural rendering)
are requirements, not tests (contract §J REQ-ONLY)."""
import dataclasses

import pytest

from memory_core import episode_commitment as EC
from memory_core.commit_time import JOURNAL, TimedJournal
from memory_core.retrieval import search_memory
from test_execution_memory_visibility import A, B, EXEC_GEN, X, exec_gen, r_of, setup, source, texts
from test_journal_compaction import KEY

KINDS = ["explicit", "implied"]


def test_gen2_generation_identity_depends_only_on_inputs():
    """Same inputs give the same key whatever the summary text or the agent; every input changes it."""
    g = exec_gen("ex1", "a1", ["e1", "e2"], "called crm")
    k = EC.generation_idem(KEY, g)
    assert EC.generation_idem(KEY, dataclasses.replace(g, summary="other words")) == k
    assert EC.generation_idem(KEY, dataclasses.replace(g, agent_id="a2")) == k        # attribution is not identity
    assert EC.generation_idem(KEY, dataclasses.replace(g, evidence_ids=("e2", "e1"))) == k   # member order-insensitive
    for changed in (dataclasses.replace(g, evidence_ids=("e1",)), dataclasses.replace(g, active_at_generation=("e1",)),
                    dataclasses.replace(g, generator_version=EXEC_GEN + ".2"),
                    dataclasses.replace(g, episode_id="ex2")):
        assert EC.generation_idem(KEY, changed) != k
    assert EC.generation_idem(b"another-subject-key-" * 2, g) != k                    # keyed per subject


@pytest.mark.parametrize("kind", KINDS)
def test_gen3_gen10_a_retry_with_other_text_or_another_agent_keeps_the_recorded_generation(kind):
    wr, j = setup(kind)
    assert EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1"], "crm call ok"), 2.0)[0] == "APPENDED"
    forged = exec_gen("ex1", "a2", ["e1"], "crm is always unreliable")               # other agent, other text
    assert EC.record_episode_generation(j, KEY, forged, 2.5)[0] == "DUPLICATE"
    g = EC.generations_at(j.store.facts(), X, r_of(j, X, 3.0))["ex1"]
    assert (g.agent_id, g.summary) == ("a1", "crm call ok")
    assert sum(s.entry.kind == EC.EPISODE_SUMMARY for s in j.store.entries(X)) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_gen4_distinct_episode_ids_are_served_as_separate_episodes(kind):
    """Two correlation ids (two episode ids) of the same agent and customer never merge."""
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex_corr1", "a1", ["e1"], "crm lookup one"), 2.0)
    EC.record_episode_generation(j, KEY, exec_gen("ex_corr2", "a1", ["e2"], "crm lookup two"), 2.0)
    r = r_of(j, X, 3.0)
    assert sorted(EC.generations_at(j.store.facts(), X, r)) == ["ex_corr1", "ex_corr2"]
    assert sorted(texts(search_memory(source(j, X, r), X, "crm", B))) == ["crm lookup one", "crm lookup two"]


@pytest.mark.parametrize("kind", KINDS)
def test_gen8_regeneration_over_surviving_members_is_a_new_generation(kind):
    """A member becomes unusable: the served episode is excluded until a regeneration over the surviving members,
    which is a NEW generation (the usable set is part of the key) and is then served."""
    wr, j = setup(kind)
    EC.record_episode_generation(j, KEY, exec_gen("ex1", "a1", ["e1", "e2"], "crm two steps"), 2.0)
    r = r_of(j, X, 3.0)
    assert texts(search_memory(source(j, X, r, status={"e2": EC.SUPPRESSED}), X, "crm", A)) == []
    regen = exec_gen("ex1", "a1", ["e1", "e2"], "crm one step", usable=["e1"])
    assert EC.record_episode_generation(j, KEY, regen, 3.5)[0] == "APPENDED"
    r = r_of(j, X, 4.0)
    assert texts(search_memory(source(j, X, r, status={"e2": EC.SUPPRESSED}), X, "crm", A)) == ["crm one step"]


@pytest.mark.parametrize("kind", KINDS)
def test_gen13_recorded_output_survives_process_loss_and_a_fresh_journal(kind):
    wr, j = setup(kind)
    g = exec_gen("ex1", "a1", ["e1"], "crm call ok")
    EC.record_episode_generation(j, KEY, g, 2.0)
    j.store.crash()                                                                   # process state lost
    fresh = TimedJournal(j.store.policy_history, JOURNAL, storage=j.store)            # a new process, same storage
    assert EC.record_episode_generation(fresh, KEY, dataclasses.replace(g, summary="regenerated words"),
                                        2.5)[0] == "DUPLICATE"
    assert EC.generations_at(fresh.store.facts(), X, r_of(fresh, X, 3.0))["ex1"].summary == "crm call ok"
