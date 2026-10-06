"""Amendment A1: commitment events and episode generations as durable-journal facts. TEST_ONLY.

Every store-dependent test runs unchanged against both storage-boundary reference implementations (explicit and
implied frontiers), through the unchanged ``TimedJournal`` (journal-assigned commit time, duplicate before time).
Decision record: ``investigation/durable-home-episodes-commitments-decision-v1.md``."""
import dataclasses
import random

import pytest

from conftest import P, World
from memory_core import commitments as CM
from memory_core import episode_commitment as EC
from memory_core.commit_time import JOURNAL, TimedJournal
from memory_core.durable_journal import KINDS, PROJECTED_KINDS, DurableFacts, Entry, Sealed, reconstruct
from memory_core.registry import Caller
from memory_core.retrieval import MemorySource, get_commitments, search_memory
from memory_core.storage_boundary import ExplicitFrontierStore, ImpliedFrontierStore
from test_durable_storage_boundary import make as make_with_claims
from test_integration import CITY
from test_x1_commit_time import put

STORES = {"explicit": ExplicitFrontierStore, "implied": ImpliedFrontierStore}
STORE_KINDS = list(STORES)
KEYS = {"s1": b"k" * 32, "s2": b"q" * 32}
CALLER = Caller("TEST_ONLY_agent", frozenset({("CUSTOMER", "s1"), ("CUSTOMER", "s2")}))


def journal(kind):
    return TimedJournal({}, JOURNAL, storage=STORES[kind]({}))


def ev(eid, key, kind, at, actor, subj="s1", evidence="e1", due=None, agent="a1", tenant="t1", ext=None):
    return CM.Event(eid, key, kind, at, actor, evidence, due, ext, subj, agent, tenant)


def rec(j, e, clock, **kw):
    return EC.record_commitment_event(j, KEYS[e.subject_id], e, clock, **kw)


def gen(epid, members, summary, subj="s1", version="TEST_ONLY_gen_v1", active=None, merges=(), start=1.0):
    return EC.EpisodeGeneration(epid, subj, "a1", "t1", tuple(members),
                                tuple(members if active is None else active), start, start + len(members), summary,
                                version, tuple(merges))


def recg(j, g, clock):
    return EC.record_episode_generation(j, KEYS[g.subject_id], g, clock)


def served(j, subj, clock):
    return j.read(subj, clock).r


# ============================================================================== registration and identity
def test_kinds_are_added_without_changing_existing_kinds_and_are_never_claim_projected():
    assert KINDS[:7] == ("claim", "retraction", "lifecycle", "sync", "erasure", "commit_intent", "commit_outcome")
    assert {EC.COMMITMENT_EVENT, EC.EPISODE_SUMMARY} <= set(KINDS)
    assert not {EC.COMMITMENT_EVENT, EC.EPISODE_SUMMARY} & set(PROJECTED_KINDS)


def test_identity_is_deterministic_keyed_and_generation_identity_ignores_output_text():
    e = ev("x1", "k1", "create", 1.0, "agent")
    assert EC.event_ref(KEYS["s1"], e) == EC.event_ref(KEYS["s1"], dataclasses.replace(e))
    assert EC.event_ref(KEYS["s1"], e) != EC.event_ref(KEYS["s2"], e)          # keyed: unlinkable without the key
    assert EC.event_ref(KEYS["s1"], e) != EC.event_ref(KEYS["s1"], dataclasses.replace(e, kind="cancel"))
    g = gen("ep1", ["e1", "e2"], "first text")
    assert EC.generation_idem(KEYS["s1"], g) == EC.generation_idem(KEYS["s1"], dataclasses.replace(g, summary="x"))
    assert EC.generation_idem(KEYS["s1"], g) == EC.generation_idem(KEYS["s1"], gen("ep1", ["e2", "e1"], "y"))
    assert EC.generation_idem(KEYS["s1"], g) != EC.generation_idem(KEYS["s1"], gen("ep1", ["e1"], "first text"))
    assert EC.generation_idem(KEYS["s1"], g) != EC.generation_idem(
        KEYS["s1"], dataclasses.replace(g, generator_version="TEST_ONLY_gen_v2"))
    assert EC.generation_idem(KEYS["s1"], g) != EC.generation_idem(KEYS["s2"], g)
    assert EC.generation_idem(KEYS["s1"], g) != EC.generation_idem(       # forget_fact changed the usable inputs
        KEYS["s1"], gen("ep1", ["e1", "e2"], "first text", active=["e2"]))


# ============================================================================== commitment events: writes
@pytest.mark.parametrize("kind", STORE_KINDS)
def test_an_event_is_a_sealed_fact_in_its_subject_partition_at_journal_time(kind):
    j = journal(kind)
    e = ev("x1", "k1", "create", 0.5, "agent", due=50.0)
    status, at = rec(j, e, 5.0)
    assert status == "APPENDED" and at >= 5.0
    f = j.store.facts()
    assert list(f.partitions) == ["s1"]
    (s,) = f.partitions["s1"]
    assert (s.entry.kind, s.entry.idem, s.entry.at) == (EC.COMMITMENT_EVENT, "cevent:x1", at)
    assert isinstance(s.entry.payload, Sealed) and s.entry.payload.key_id == "key:s1"
    assert f.vault[(s.entry.payload.key_id, s.entry.payload.ref)] == e          # business `at` kept as recorded
    assert "x1" not in s.entry.payload.ref


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_same_event_id_same_content_is_duplicate_with_original_time_different_content_is_refused(kind):
    j = journal(kind)
    e = ev("x1", "k1", "create", 1.0, "agent")
    _, at = rec(j, e, 5.0)
    assert rec(j, e, 9.0) == ("DUPLICATE", at)
    for other in (dataclasses.replace(e, kind="cancel", actor="user"), dataclasses.replace(e, at=2.0),
                  dataclasses.replace(e, evidence_id="e2"), dataclasses.replace(e, due_until=3.0),
                  dataclasses.replace(e, agent_id="a2")):
        assert rec(j, other, 9.0) == ("EVENT_ID_REUSED", None)
    assert len(j.store.entries("s1")) == 1
    assert EC.commitment_events_at(j.store.facts(), "s1", 1e9) == (e,)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_a_racing_reuse_with_different_content_cannot_overwrite_the_original_fact(kind):
    j = journal(kind)
    a = ev("x1", "k1", "create", 1.0, "agent")
    b = dataclasses.replace(a, kind="cancel", actor="user")

    def build(x):
        return lambda at: [(Entry("s1", EC.COMMITMENT_EVENT, "cevent:x1", at, None, None, None),
                            ("s1", EC.event_ref(KEYS["s1"], x), x))]
    pa = j.prepare("s1", "cevent:x1", None, None, 5.0, build(a))[1]
    pb = j.prepare("s1", "cevent:x1", None, None, 5.0, build(b))[1]          # both passed the pre-check
    results = [j.finish(pb), j.finish(pa)]                                   # the later-timed one lands first
    assert [x[0] for x in results].count("APPENDED") == 1
    loser = results[1]
    assert loser in (("REJECTED", "idem_reused_with_different_content"), ("READ_CLOSED", pa.at))
    assert EC.commitment_events_at(j.store.facts(), "s1", 1e9) == (b,)       # the winner, intact
    assert rec(j, a, 9.0) == ("EVENT_ID_REUSED", None)                       # the loser's retry is refused


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_identity_less_events_and_events_without_live_evidence_are_refused_before_time(kind):
    j = journal(kind)
    assert rec(j, ev("x1", "k1", "create", 1.0, "agent", subj="s1"), 1.0,
               evidence_live=lambda eid: eid != "e1") == ("REJECTED", "evidence_not_live")
    assert EC.record_commitment_event(j, KEYS["s1"], ev("x2", "k1", "create", 1.0, "agent", subj=""), 1.0) == \
        ("REJECTED", "identity_required")
    assert EC.record_episode_generation(j, KEYS["s1"], gen("ep1", ["e1"], "t", subj=""), 1.0) == \
        ("REJECTED", "identity_required")
    assert j.store.facts().partitions == {}


# ============================================================================== commitment events: rebuild
def random_events(rng, n, subj, tag):
    kinds = list(CM._T)
    out = []
    for i in range(n):
        k = rng.choice(kinds)
        actor = rng.choice(sorted(CM._AUTH[k])) if rng.random() < 0.85 else "clock"
        out.append(ev("%s%d" % (tag, i), "%s-k%d" % (tag, rng.randrange(3)), k if i else "create",
                      round(rng.uniform(0, 20), 1), actor, subj, "e%d" % rng.randrange(5),
                      rng.choice([None, 8.0, 15.0]), ext=rng.choice([None, "ext-1"])))
    return out


@pytest.mark.parametrize("kind", STORE_KINDS)
@pytest.mark.parametrize("seed", range(15))
def test_rebuilt_commitments_equal_the_lane_a_projection_and_unchanged_retrieval(kind, seed):
    rng = random.Random(seed)
    j = journal(kind)
    evs = random_events(rng, 12, "s1", "a") + random_events(rng, 8, "s2", "b")
    rng.shuffle(evs)
    for i, e in enumerate(evs):
        assert rec(j, e, float(i))[0] == "APPENDED"
        if rng.random() < 0.3:
            assert rec(j, e, float(i))[0] == "DUPLICATE"                    # redelivery changes nothing
    dead = frozenset({"e4"})
    f = j.store.facts()
    for subj in ("s1", "s2"):
        r = served(j, subj, 30.0)
        mine = [e for e in evs if e.subject_id == subj]
        assert EC.commitments_at(f, subj, r, dead) == {
            k: h for k, h in CM.project(evs, r, dead).items() if h.subject_id == subj}
        live = MemorySource((), {}, commitment_events=tuple(evs), dead_evidence=dead)
        durable = MemorySource((), {}, commitment_events=EC.commitment_events_at(j.store.facts(), subj, r),
                               dead_evidence=dead)
        assert get_commitments(durable, subj, r, CALLER) == get_commitments(live, subj, r, CALLER)
        assert len(EC.commitment_events_at(j.store.facts(), subj, r)) == len(mine)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_a_duplicate_assent_with_a_fresh_event_id_yields_one_commitment(kind):
    j = journal(kind)
    rec(j, ev("x1", "book", "create", 1.0, "agent"), 1.0)
    rec(j, ev("x2", "book", "create", 1.1, "agent"), 2.0)                   # the "yes" delivered twice
    rec(j, ev("x3", "book", "confirm_assent", 1.2, "user"), 3.0)
    heads = EC.commitments_at(j.store.facts(), "s1", served(j, "s1", 4.0))
    assert list(heads) == ["book"] and heads["book"].state == CM.CONFIRMED


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_expiry_is_evaluated_at_the_served_position(kind):
    j = journal(kind)
    rec(j, ev("x1", "k1", "create", 1.0, "agent", due=10.0), 1.0)
    r1, r2 = served(j, "s1", 5.0), served(j, "s1", 12.0)
    f = j.store.facts()
    assert EC.commitments_at(f, "s1", r1)["k1"].state == CM.PROPOSED
    assert EC.commitments_at(f, "s1", r2)["k1"].state == CM.EXPIRED


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_commit_time_governs_visibility_and_business_time_governs_order(kind):
    j = journal(kind)
    rec(j, ev("x2", "k1", "confirm_assent", 2.0, "user"), 1.0)              # committed first, happened later
    r1 = served(j, "s1", 3.0)
    rec(j, ev("x1", "k1", "create", 1.0, "agent"), 4.0)                     # committed later, happened first
    r2 = served(j, "s1", 6.0)
    f = j.store.facts()
    assert EC.commitments_at(f, "s1", r1) == {}                              # only the orphan confirm is visible
    assert EC.commitments_at(f, "s1", r2)["k1"].state == CM.CONFIRMED       # ordered by business time


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_served_positions_stay_immutable_for_both_kinds(kind):
    j = journal(kind)
    rec(j, ev("x1", "k1", "create", 1.0, "agent"), 1.0)
    recg(j, gen("ep1", ["e1"], "talked about tea"), 2.0)
    r = served(j, "s1", 3.0)
    before = (EC.commitments_at(j.store.facts(), "s1", r), EC.generations_at(j.store.facts(), "s1", r))
    rec(j, ev("x2", "k1", "cancel", 0.5, "user"), 1.0)                      # a lagging writer clock
    recg(j, gen("ep1", ["e1", "e2"], "tea and coffee"), 1.0)
    assert all(s.entry.at > r for s in j.store.entries("s1")[2:])
    assert (EC.commitments_at(j.store.facts(), "s1", r), EC.generations_at(j.store.facts(), "s1", r)) == before


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_no_cross_subject_contamination_even_with_a_colliding_commitment_key(kind):
    j = journal(kind)
    a = [ev("a1", "same", "create", 1.0, "agent", subj="s1"), ev("a2", "same", "cancel", 2.0, "user", subj="s1")]
    b = [ev("b1", "same", "create", 1.5, "agent", subj="s2"), ev("b2", "same", "confirm_assent", 3.0, "user",
                                                               subj="s2")]
    for i, e in enumerate(a + b):
        rec(j, e, float(i))
    f = j.store.facts()
    r1, r2 = served(j, "s1", 10.0), served(j, "s2", 10.0)
    assert EC.commitments_at(f, "s1", r1)["same"].state == CM.CANCELLED
    assert EC.commitments_at(f, "s2", r2)["same"].state == CM.CONFIRMED
    assert {s.entry.partition for s in j.store.entries("s1")} == {"s1"}
    # Lane A's single global log (recorded, not fixed): s1's create shadows s2's commitment entirely
    assert {h.subject_id for h in CM.project(a + b, 10.0).values()} == {"s1"}


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_a_foreign_identity_event_in_a_partition_is_never_served_as_that_subjects_commitment(kind):
    j = journal(kind)
    stray = ev("z1", "k9", "create", 1.0, "agent", subj="s2")               # bypasses the API: defence in depth
    j.commit("s1", "cevent:z1", None, None, 1.0,
             lambda at: [(Entry("s1", EC.COMMITMENT_EVENT, "cevent:z1", at, None, None, None),
                          ("s1", EC.event_ref(KEYS["s1"], stray), stray))])
    assert EC.commitments_at(j.store.facts(), "s1", served(j, "s1", 2.0)) == {}


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_both_kinds_leave_claim_state_unchanged(kind):
    wr, j = make_with_claims(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    rec(j, ev("x1", "k1", "create", 1.0, "agent"), 2.0)
    recg(j, gen("ep1", ["e1"], "pune talk"), 3.0)
    put(j, wr, "c2", CITY, "goa", 4.0)
    rec(j, ev("x2", "k1", "fulfil", 2.0, "tool"), 5.0)
    r = served(j, "s1", 9.0)
    f = j.store.facts()
    stripped = DurableFacts({p: tuple(s for s in xs if s.entry.kind not in (EC.COMMITMENT_EVENT, EC.EPISODE_SUMMARY))
                             for p, xs in f.partitions.items()}, f.publications, f.vault, f.policy_history)
    full, bare = reconstruct(f, "s1", r), reconstruct(stripped, "s1", r)
    assert full.state == bare.state and full.trace == bare.trace


# ============================================================================== episode generations
@pytest.mark.parametrize("kind", STORE_KINDS)
def test_a_retried_summarisation_returns_the_recorded_generation_never_a_new_one(kind):
    j = journal(kind)
    g = gen("ep1", ["e1", "e2"], "recorded text")
    _, at = recg(j, g, 1.0)
    assert recg(j, dataclasses.replace(g, summary="different nondeterministic text"), 5.0) == ("DUPLICATE", at)
    assert recg(j, g, 6.0) == ("DUPLICATE", at)
    assert len(j.store.entries("s1")) == 1
    assert EC.generations_at(j.store.facts(), "s1", 1e9)["ep1"].summary == "recorded text"


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_the_latest_generation_is_served_and_earlier_generations_remain_history(kind):
    j = journal(kind)
    recg(j, gen("ep1", ["e1"], "v1 text"), 1.0)
    r1 = served(j, "s1", 2.0)
    recg(j, gen("ep1", ["e1", "e2"], "v2 text"), 3.0)
    recg(j, gen("ep2", ["e3"], "other"), 4.0)
    r2 = served(j, "s1", 5.0)
    f = j.store.facts()
    assert {k: g.summary for k, g in EC.generations_at(f, "s1", r1).items()} == {"ep1": "v1 text"}
    assert {k: g.summary for k, g in EC.generations_at(f, "s1", r2).items()} == {"ep1": "v2 text", "ep2": "other"}
    assert len(j.store.entries("s1")) == 3


def runtime_generation(m, ep, version="TEST_ONLY_gen_v1"):
    """What a writer records after Lane A's ``assign_episodes``: membership, the members active NOW, the output."""
    return EC.EpisodeGeneration(ep.episode_id, ep.subject_id, ep.agent_id, "t1", tuple(ep.evidence_ids),
                                tuple(e for e in ep.evidence_ids if m.evidence[e].status == "active"),
                                ep.started_at, ep.ended_at, ep.summary, version, tuple(ep.merge_ids))


def status_now(m, j, subj, clock):
    r = served(j, subj, clock)
    st = {e: v.status for e, v in m.evidence.items()}
    return {e.episode_id: e.summary_status for e in EC.episodes_at(j.store.facts(), subj, r, st,
                                                                   frozenset(m.merges_undone))}


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_derived_episode_status_matches_lane_a_through_forget_fact_and_regeneration(kind):
    w, j = World(), journal(kind)
    e1 = w.say("u1", "I have a dog", 1)
    w.say("u1", "I like tea", 1.1)
    s = e1.subject_id
    KEYS[s] = b"r" * 32
    w.extract(s, [P("note.pet", "dog", e1, quote="I have a dog")], 1)
    w.m.assign_episodes(s)
    ep = next(iter(w.m.episodes.values()))
    recg(j, runtime_generation(w.m, ep), 1.0)
    assert status_now(w.m, j, s, 1.5) == {ep.episode_id: "ok"}
    w.m.forget_fact(s, "note.pet", "dog", 2)
    assert ep.summary_status == "regenerate_pending"
    assert status_now(w.m, j, s, 2.5) == {ep.episode_id: "regenerate_pending"}
    w.m.assign_episodes(s)
    assert ep.summary_status == "ok" and "dog" not in ep.summary
    recg(j, runtime_generation(w.m, ep), 3.0)
    assert status_now(w.m, j, s, 3.5) == {ep.episode_id: "ok"}
    assert "dog" not in EC.generations_at(j.store.facts(), s, 1e9)[ep.episode_id].summary


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_derived_episode_status_matches_lane_a_quarantine_on_merge_undo(kind):
    w, j = World(), journal(kind)
    ea, eb0 = w.say("alice", "hi", 1), w.say("bob", "hi", 1)
    a, b = ea.subject_id, eb0.subject_id
    KEYS[b] = b"m" * 32
    mid = w.m.merge(b, a, 2)
    w.say("bob", "I have a dog", 5)
    w.m.assign_episodes(b)
    eps = [e for e in w.m.episodes.values() if mid in e.merge_ids]
    assert eps
    for i, ep in enumerate(eps):
        recg(j, runtime_generation(w.m, ep), 5.0 + i)
    w.m.undo_merge(mid, 6)
    assert all(e.summary_status == "quarantined" for e in eps)
    got = status_now(w.m, j, b, 7.0)
    assert all(got[e.episode_id] == "quarantined" for e in eps)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_search_memory_over_durable_episodes_equals_the_in_memory_episodes(kind):
    j = journal(kind)
    gs = [gen("ep1", ["e1"], "tea and biscuits", start=1.0), gen("ep2", ["e2", "e3"], "booking a table", start=2.0),
          gen("ep3", ["e4"], None, start=3.0), gen("ep4", ["e5"], "tea again", start=4.0, active=["e5"])]
    for i, g in enumerate(gs):
        recg(j, g, float(i))
    status = {"e5": "context_suppressed"}
    r = served(j, "s1", 10.0)
    durable = EC.episodes_at(j.store.facts(), "s1", r, status)
    expected = tuple(EC.Episode(g.episode_id, g.subject_id, g.agent_id, list(g.evidence_ids), g.started_at,
                                g.ended_at, g.summary, EC.derive_status(g, status), list(g.merge_ids)) for g in gs)
    assert durable == expected
    for q in ("tea", "booking", ""):
        a = search_memory(MemorySource((), {}, episodes=durable), "s1", q, CALLER)
        b = search_memory(MemorySource((), {}, episodes=expected), "s1", q, CALLER)
        assert a == b
    assert [i.value[1] for i in search_memory(MemorySource((), {}, episodes=durable), "s1", "tea", CALLER).items] \
        == ["tea and biscuits"]                                              # the suppressed generation is withheld


# ============================================================================== erasure
def erase(j, subj, clock, destroy=True):
    e = Entry(subj, "erasure", "erasure:" + subj, 0.0, None, None, ("cluster", (subj,)))
    assert j.commit(subj, "erasure:" + subj, None, None, clock,
                    lambda at: [(dataclasses.replace(e, at=at), None)])[0] == "APPENDED"
    if destroy:
        j.store.destroy_key("key:" + subj)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_erasure_leaves_neither_kind_recoverable_and_seals_the_partition(kind):
    j = journal(kind)
    rec(j, ev("x1", "zanzibar-booking", "create", 1.0, "agent", ext="zanzibar-ref"), 1.0)
    recg(j, gen("ep1", ["e1"], "zanzibar canary secret"), 2.0)
    rec(j, ev("y1", "k2", "create", 1.0, "agent", subj="s2"), 2.5)
    erase(j, "s1", 3.0)
    f = j.store.facts()
    assert "zanzibar" not in repr(f.partitions) + repr(f.vault)
    assert EC.commitments_at(f, "s1", 1e9) == {} and EC.generations_at(f, "s1", 1e9) == {}
    assert reconstruct(f, "s1", 1e9).erased
    assert rec(j, ev("x2", "k3", "create", 4.0, "agent"), 4.0)[0] == "REJECTED"   # no sealing under a shredded key
    assert recg(j, gen("ep2", ["e9"], "late"), 4.0)[0] == "REJECTED"
    assert len(j.store.entries("s1")) == 3
    assert list(EC.commitments_at(f, "s2", 1e9)) == ["k2"]                  # the other subject is untouched


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_an_erasure_entry_alone_already_hides_both_kinds_before_key_destruction(kind):
    j = journal(kind)
    rec(j, ev("x1", "k1", "create", 1.0, "agent"), 1.0)
    recg(j, gen("ep1", ["e1"], "text"), 2.0)
    r = served(j, "s1", 2.5)
    erase(j, "s1", 3.0, destroy=False)                                       # erasure in progress
    f = j.store.facts()
    assert EC.commitments_at(f, "s1", 1e9) == {} and EC.generations_at(f, "s1", 1e9) == {}
    assert EC.commitments_at(f, "s1", r) != {}                               # the served past is unchanged
    assert rec(j, ev("x2", "k3", "create", 4.0, "agent"), 4.0) == ("REJECTED", "partition_erased")


# ============================================================================== restart, decomposition, growth
@pytest.mark.parametrize("kind", STORE_KINDS)
def test_a_restarted_journal_over_the_same_store_serves_the_same_and_retries_are_duplicates(kind):
    j = journal(kind)
    e, g = ev("x1", "k1", "create", 1.0, "agent"), gen("ep1", ["e1"], "text")
    _, at_e = rec(j, e, 1.0)
    _, at_g = recg(j, g, 2.0)
    r = served(j, "s1", 3.0)
    before = (EC.commitments_at(j.store.facts(), "s1", r), EC.generations_at(j.store.facts(), "s1", r))
    j.crash()
    j2 = TimedJournal({}, JOURNAL, storage=j.store)                          # the journal itself holds nothing
    assert (EC.commitments_at(j2.store.facts(), "s1", r), EC.generations_at(j2.store.facts(), "s1", r)) == before
    assert rec(j2, e, 9.0) == ("DUPLICATE", at_e)
    assert recg(j2, dataclasses.replace(g, summary="regenerated"), 9.0) == ("DUPLICATE", at_g)


@pytest.mark.parametrize("kind", STORE_KINDS)
@pytest.mark.parametrize("seed", range(5))
def test_projections_decompose_per_key_and_a_checkpoint_plus_suffix_equals_the_full_rebuild(kind, seed):
    rng = random.Random(100 + seed)
    j = journal(kind)
    evs = random_events(rng, 20, "s1", "a")
    for i, e in enumerate(evs):
        rec(j, e, float(i))
        if i % 3 == 0:
            members = ["e%d" % k for k in range(rng.randrange(1, 4))]
            recg(j, gen("ep%d" % rng.randrange(3), members, "text %d" % i), float(i))
    r1 = served(j, "s1", 10.0)
    for i in range(5):
        recg(j, gen("ep%d" % rng.randrange(3), ["e%d" % k for k in range(i + 4)], "later %d" % i), 20.0 + i)
    r2 = served(j, "s1", 40.0)
    f = j.store.facts()
    full = EC.commitments_at(f, "s1", r2)
    for k, h in full.items():                                                # per commitment key
        assert CM.project([e for e in evs if e.commitment_key == k], r2)[k] == h
    checkpoint = dict(EC.generations_at(f, "s1", r1))
    for s in f.partitions["s1"]:                                             # fold only the suffix (r1, r2]
        if s.entry.kind == EC.EPISODE_SUMMARY and r1 < s.entry.at <= r2:
            g = f.vault[(s.entry.payload.key_id, s.entry.payload.ref)]
            checkpoint[g.episode_id] = g
    assert checkpoint == EC.generations_at(f, "s1", r2)


@pytest.mark.parametrize("kind", STORE_KINDS)
def test_history_grows_only_with_new_inputs_not_with_retries(kind):
    j = journal(kind)
    for n in range(1, 21):
        g = gen("ep1", ["e%d" % k for k in range(n)], "summary %d" % n)
        for attempt in range(3):                                             # every generation retried
            recg(j, dataclasses.replace(g, summary="%s/attempt %d" % (g.summary, attempt)), float(n))
    assert len(j.store.entries("s1")) == 20
    assert EC.generations_at(j.store.facts(), "s1", 1e9)["ep1"].summary == "summary 20/attempt 0"
