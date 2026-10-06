"""X-1 decision: the journal owns commit time; closed frontiers enforce O4 and R-READ. TEST_ONLY_* policies only.

Every case runs against the chosen model (``journal``). The break tests run the REJECTED interpretations and show
that an invariant check fails. Records are produced by the real gate and commit, built INSIDE the commit step from
the journal-assigned time (so the record's committed_at equals the entry's commit time)."""
import dataclasses
import random

import pytest

from memory_core.commit_time import (JOURNAL, STORE_LOCAL, WRITER, WRITER_READ_WATERMARK, Crash, TimedJournal, View,
                                     acknowledged_stamps_hold, served_prefixes_are_immutable)
from memory_core.durable_journal import export_pipeline, reconstruct
from test_integration import ALL, CITY, NOTE, World

VALUES = ("pune", "delhi", "goa")


class Writer:
    """The writer side: real gate + commit. ``claim`` returns the build callback the commit step calls with ``at``."""

    def __init__(self):
        self.w = World()
        self.seen = {e.idem for e, _ in export_pipeline(self.w.p)[0]}

    def stamp(self, policy):
        return self.w.p.registry.get(policy.predicate).policy_version_id

    def claim(self, policy, value, subj="s1", valid_from=None, **kw):
        def build(at):
            self.w.say(policy, value, subj=subj, observed=at, valid_from=valid_from, text=f"{subj} {value}", **kw)
            new = [(e, s) for e, s in export_pipeline(self.w.p)[0] if e.idem not in self.seen]
            self.seen |= {e.idem for e, _ in new}
            return [(e, s) for e, s in new if e.partition == subj]
        return build

    def publish(self, j, policy, clock, breaking=False):
        cur = self.w.p.registry.get(policy.predicate)
        new = dataclasses.replace(cur, policy_version_id=cur.policy_version_id + 1, breaking=breaking)
        T = j.publish(policy.predicate, new.policy_version_id, clock)     # the journal decides T
        self.w.p.publish(new, T)
        return T


def setup(mode=JOURNAL, **kw):
    wr = Writer()
    j = TimedJournal(wr.w.p.registry._v, mode, **kw)
    for p in ALL:
        j.publish(p.predicate, 1, 0.0)
    return wr, j


def put(j, wr, cmd, policy, value, clock, subj="s1", valid_from=None, stamp=None, **kw):
    return j.commit(subj, cmd, policy.predicate, wr.stamp(policy) if stamp is None else stamp, clock,
                    wr.claim(policy, value, subj, valid_from, **kw.pop("say", {})), **kw)


def values(sv, pred=None):
    return [sig[1] for _, sig in sv.trace.get(pred or CITY.predicate, ())]


def violated(j):
    try:
        served_prefixes_are_immutable(j)
        acknowledged_stamps_hold(j)
    except AssertionError:
        return True
    return False


# ============================================================================== Case 1: back-dated publication
def test_case1_publication_is_never_placed_before_an_acknowledged_entry():
    wr, j = setup()
    assert put(j, wr, "c1", CITY, "pune", 6.0) == ("APPENDED", 6.0)
    T = wr.publish(j, CITY, 5.0, breaking=True)                       # the publisher's clock is behind
    assert T > 6.0
    acknowledged_stamps_hold(j)


@pytest.mark.parametrize("mode", [WRITER, WRITER_READ_WATERMARK])
def test_break_case1_writer_assigned_publication_time_invalidates_an_acknowledged_entry(mode):
    wr, j = setup(mode)
    put(j, wr, "c1", CITY, "pune", 6.0)
    assert wr.publish(j, CITY, 5.0, breaking=True) == 5.0
    with pytest.raises(AssertionError):
        acknowledged_stamps_hold(j)


# ============================================================================== Case 2: late back-dated entry
def test_case2_late_entry_cannot_enter_a_served_read():
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 5.0)
    sv = j.read("s1", 10.0)
    status, at = put(j, wr, "c2", CITY, "goa", 8.0)                  # the writer's clock is behind
    assert status == "APPENDED" and at > sv.r
    served_prefixes_are_immutable(j)


def test_break_case2_writer_assigned_entry_time_rewrites_a_served_read():
    wr, j = setup(WRITER)
    put(j, wr, "c1", CITY, "pune", 5.0)
    j.read("s1", 10.0)
    assert put(j, wr, "c2", CITY, "goa", 8.0) == ("APPENDED", 8.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


def test_read_watermark_alone_fixes_case2_only():
    wr, j = setup(WRITER_READ_WATERMARK)
    put(j, wr, "c1", CITY, "pune", 5.0)
    j.read("s1", 10.0)
    assert put(j, wr, "c2", CITY, "goa", 8.0)[0] == "READ_CLOSED"      # R-READ holds; O4 does not (case 1 break)
    served_prefixes_are_immutable(j)


# ============================================================================== Case 3: equal time
def test_case3_equal_clock_readings_never_produce_cross_source_ties():
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 10.0)
    T = wr.publish(j, CITY, 10.0)                                     # same clock reading as the entry
    sv = j.read("s1", T)
    status, at = put(j, wr, "c2", CITY, "goa", T)
    assert T > 10.0 and status == "APPENDED" and at > T >= sv.r
    times = [x.entry.at for x in j.store.facts().partitions["s1"]] + \
            [p.at for p in j.store._publications() if p.predicate == CITY.predicate]
    assert len(times) == len(set(times))
    served_prefixes_are_immutable(j)
    acknowledged_stamps_hold(j)


def test_break_case3_equal_time_entry_after_a_served_read_lands_inside_it():
    wr, j = setup(WRITER)
    put(j, wr, "c1", CITY, "pune", 10.0)
    wr.publish(j, NOTE, 10.0)                                         # a tie with the entry's time
    j.read("s1", 10.0)
    assert put(j, wr, "c2", CITY, "goa", 10.0) == ("APPENDED", 10.0)  # equal to the served r: lands inside it
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


# ============================================================================== Case 4: concurrency across subjects
def test_case4_two_subjects_and_a_publication_with_skewed_clocks():
    wr, j = setup()
    assert put(j, wr, "a1", CITY, "pune", 13.0, subj="s1") == ("APPENDED", 13.0)    # node A, clock +3
    _, pending = j.prepare("s2", "b1", CITY.predicate, wr.stamp(CITY), 7.0,        # node B, clock -3, in flight
                           wr.claim(CITY, "goa", "s2"))
    T = wr.publish(j, CITY, 10.0, breaking=True)                                   # node P
    assert T > 13.0
    assert j.finish(pending) == ("APPENDED", 7.0)              # dated before T: evaluated before the publication
    stale = put(j, wr, "b2", CITY, "delhi", 8.0, subj="s2", stamp=1)               # gate ran before publication
    assert stale[0] == "STALE_POLICY_STAMP" and stale[1] > T
    assert put(j, wr, "b2", CITY, "delhi", 8.5, subj="s2")[0] == "APPENDED"       # re-gated under v2
    for s, c in (("s1", 9.0), ("s2", 16.0), ("s1", 20.0)):
        j.read(s, c)
    served_prefixes_are_immutable(j)
    acknowledged_stamps_hold(j)


def test_break_case4_store_local_clocks_per_source():
    wr, j = setup(STORE_LOCAL)
    put(j, wr, "a1", CITY, "pune", 13.0, subj="s1")              # partition shard clock reads 13
    wr.publish(j, CITY, 10.0, breaking=True)                     # policy shard clock reads 10: monotone, but behind
    with pytest.raises(AssertionError):
        acknowledged_stamps_hold(j)


def random_run(mode, seed, n=45, skews=(3.0, -3.0, 0.0, 1.0)):
    rng = random.Random(seed)
    wr, j = setup(mode)
    true, pending, views, issued = 1.0, [], [], []
    for i in range(n):
        true += rng.uniform(0.1, 2.0)
        clock = true + rng.choice(skews)
        x = rng.random()
        if x < 0.40:
            pol, s = rng.choice([CITY, NOTE]), rng.choice(["s1", "s2"])
            vf = rng.choice([None, None, clock + rng.uniform(0.5, 6.0)])
            st, p = j.prepare(s, f"c{i}", pol.predicate, wr.stamp(pol), clock,
                              wr.claim(pol, rng.choice(VALUES), s, vf))
            if st == "PREPARED":
                if rng.random() < 0.3:
                    pending.append(p)                            # in flight: reads and publications interleave
                else:
                    issued.append((clock, j.finish(p)))
        elif x < 0.50 and pending:
            issued.append((clock, j.finish(pending.pop(rng.randrange(len(pending))))))
        elif x < 0.62:
            try:
                wr.publish(j, rng.choice([CITY, NOTE]), clock, breaking=rng.random() < 0.5)
            except Exception:                                    # noqa: BLE001  writer modes: out-of-order publication
                pass
        elif x < 0.88:
            j.read(rng.choice(["s1", "s2"]), clock, closing=rng.random() < 0.7)
        elif x < 0.94:
            views.append(j.snapshot())
        elif views:
            j.read_view(rng.choice(views), rng.choice(["s1", "s2"]), clock)
    return j, issued


@pytest.mark.parametrize("seed", range(20))
def test_property_case4_chosen_model_keeps_every_served_prefix_and_stamp(seed):
    j, _ = random_run(JOURNAL, seed)
    served_prefixes_are_immutable(j)
    acknowledged_stamps_hold(j)
    assert len(j.served) >= 3


@pytest.mark.parametrize("mode", [WRITER, WRITER_READ_WATERMARK, STORE_LOCAL])
def test_break_property_rejected_interpretations_violate_the_invariant(mode):
    assert any(violated(random_run(mode, seed)[0]) for seed in range(20))


def test_global_serialization_consistent_clock_is_a_conformant_special_case():
    """Interpretation A done fully (one strictly increasing clock for every source, reads at that clock): the
    journal never has to adjust a time. It is conformant, and stronger than required."""
    wr, j = setup()
    t = 1.0
    for i in range(30):
        t += 0.5
        if i % 3 == 0:
            assert put(j, wr, f"c{i}", CITY, VALUES[i % 3], t, subj=("s1", "s2")[i % 2]) == ("APPENDED", t)
        elif i % 3 == 1:
            assert wr.publish(j, CITY, t, breaking=i % 2 == 0) == t
        else:
            assert j.read(("s1", "s2")[i % 2], t).r == t
    served_prefixes_are_immutable(j)
    acknowledged_stamps_hold(j)


# ============================================================================== Case 5: boundary between reads
def test_case5_future_validity_boundary_between_reads_without_an_entry():
    """Not discriminating: every physical-time model handles it (the boundary is a deterministic point)."""
    for mode in (JOURNAL, WRITER):
        wr, j = setup(mode)
        put(j, wr, "c1", CITY, "pune", 1.0)
        put(j, wr, "c2", CITY, "goa", 2.0, valid_from=20.0)
        a, b = j.read("s1", 15.0), j.read("s1", 25.0)
        assert values(a) == [("text", "pune")] and values(b) == [("text", "pune"), ("text", "goa")]
        served_prefixes_are_immutable(j)


# ============================================================================== Case 6: crash boundaries
def test_case6_crash_after_durable_before_ack_retry_returns_the_original_time():
    wr, j = setup()
    with pytest.raises(Crash):
        put(j, wr, "c1", CITY, "pune", 5.0, crash_after_durable=True)
    j.crash()
    sv = j.read("s1", 10.0)
    assert put(j, wr, "c1", CITY, "pune", 12.0) == ("DUPLICATE", 5.0)  # idempotency before time assignment
    assert len(j.store.facts().partitions["s1"]) == 1 and values(sv) == [("text", "pune")]
    served_prefixes_are_immutable(j)


def test_case6_crash_before_durable_leaves_only_a_harmless_frontier():
    wr, j = setup()
    st, p = j.prepare("s1", "c1", CITY.predicate, wr.stamp(CITY), 5.0, wr.claim(CITY, "pune"))
    j.crash()                                                         # never written
    assert put(j, wr, "c1", CITY, "pune", 6.0) == ("APPENDED", 6.0)
    assert wr.publish(j, CITY, 4.0) > 6.0                             # the closed policy frontier survived
    acknowledged_stamps_hold(j)


def test_break_case6_closure_lost_on_crash_lets_a_late_entry_into_a_served_read():
    wr, j = setup(durable_frontiers=False)
    put(j, wr, "c1", CITY, "pune", 5.0)
    j.read("s1", 10.0)
    j.crash()
    assert put(j, wr, "c2", CITY, "goa", 8.0) == ("APPENDED", 8.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


# ============================================================================== Case 7: stale writer, OCC
def _scheduled_change(mode, **kw):
    wr, j = setup(mode, **kw)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=20.0)
    sv = j.read("s1", 22.0)
    assert len(values(sv)) == 2                                      # served: the slot is at version 2
    return wr, j


def stale_command(j, wr, clock):
    return put(j, wr, "op1", CITY, "delhi", clock, expected_version=1,
               say={"source": "OPERATOR", "writer": "operator", "expected_version": 1})


def test_case7_stale_writer_gets_state_conflict_at_the_journal_assigned_time():
    wr, j = _scheduled_change(JOURNAL)
    assert stale_command(j, wr, 15.0) == ("STATE_CONFLICT", 2)        # version 1 was read before 22
    served_prefixes_are_immutable(j)


def test_break_case7_occ_at_the_callers_time_accepts_a_stale_command():
    wr, j = _scheduled_change(WRITER)
    assert stale_command(j, wr, 15.0) == ("APPENDED", 15.0)           # OCC evaluated at 15, before the boundary
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


@pytest.mark.parametrize("occ_at_write", [True, False])
def test_occ_must_run_inside_the_serialized_write(occ_at_write):
    wr, j = setup(occ_at_write=occ_at_write)
    put(j, wr, "c1", CITY, "pune", 1.0)
    st, p = j.prepare("s1", "op1", CITY.predicate, wr.stamp(CITY), 5.0,
                      wr.claim(CITY, "delhi", source="OPERATOR", writer="operator", expected_version=1),
                      expected_version=1)
    assert st == "PREPARED"
    put(j, wr, "c2", CITY, "goa", 4.0)                                # lands before the command's time
    res = j.finish(p)
    assert res == (("STATE_CONFLICT", 2) if occ_at_write else ("APPENDED", 5.0))   # weakened: stale accepted


# ============================================================================== Case 8: lagging view
def test_case8_lagging_view_serves_only_at_its_incorporated_frontier():
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 1.0)
    j.read("s1", 5.0)
    v = j.snapshot()                                                  # replica lags from here
    put(j, wr, "c2", CITY, "goa", 6.0)
    sv = j.read_view(v, "s1", 10.0)
    assert sv.r == 5.0 and values(sv) == [("text", "pune")]           # as of 5, labelled by r; not "now"
    assert j.read_view(j.snapshot(), "s2", 10.0) is None              # nothing closed: not servable
    served_prefixes_are_immutable(j)


def test_break_case8_lagging_view_served_at_the_callers_clock():
    wr, j = setup(WRITER)
    put(j, wr, "c1", CITY, "pune", 1.0)
    v = j.snapshot()
    put(j, wr, "c2", CITY, "goa", 6.0)
    j.read_view(v, "s1", 10.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


def test_break_case8_view_frontier_taken_from_its_last_entry_time():
    """O1 allows equal times, so "the time of my last replicated entry" is not a closed frontier."""
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 5.0)
    snap = j.store.facts()
    put(j, wr, "c2", CITY, "goa", 5.0)                                # same commit time, later position
    j.read_view(View(snap, {"s1": 5.0}, {CITY.predicate: 5.0}), "s1", 10.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


# ============================================================================== read closure mechanics and cost
def test_in_flight_append_is_refused_by_a_closure_that_overtook_it():
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 5.0)
    _, p = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 8.0, wr.claim(CITY, "goa"))
    j.read("s1", 10.0)
    assert j.finish(p) == ("READ_CLOSED", 8.0)
    status, at = put(j, wr, "c2", CITY, "goa", 9.0)                  # retry: a new time
    assert status == "APPENDED" and at > 10.0
    served_prefixes_are_immutable(j)


def test_break_without_the_write_time_closure_check_an_in_flight_append_enters_a_served_read():
    wr, j = setup(recheck_at_write=False)
    put(j, wr, "c1", CITY, "pune", 5.0)
    _, p = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 8.0, wr.claim(CITY, "goa"))
    j.read("s1", 10.0)
    assert j.finish(p) == ("APPENDED", 8.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


def test_as_of_reads_need_no_write_and_return_their_position():
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 5.0)
    j.read("s1", 10.0)
    writes = j.writes
    rs = [j.read("s1", c, closing=False).r for c in (11.0, 30.0, 50.0)]
    assert rs == [10.0, 10.0, 10.0] and j.writes == writes            # served at the closed frontier, no writes
    put(j, wr, "c2", CITY, "goa", 31.0)
    served_prefixes_are_immutable(j)


def test_read_closes_only_the_predicates_it_evaluates():
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 5.0)
    j.read("s1", 10.0)
    assert set(j.f_pol) == {p.predicate for p in ALL} and j.f_pol[NOTE.predicate] == 0.0
    assert j.f_pol[CITY.predicate] == 10.0                            # NOTE's log was not written by the read


def test_break_partition_frontier_ahead_of_the_clock_misstates_knowledge_time():
    """Correctness of served prefixes survives, but commit time stops meaning "when OLBrain accepted it"
    (architecture contract §2): a knowledge-cutoff query wrongly excludes a claim accepted long before."""
    wr, j = setup(partition_lease=100.0)
    put(j, wr, "c1", CITY, "pune", 5.0)
    j.read("s1", 10.0)
    status, at = put(j, wr, "c2", CITY, "goa", 12.0)                  # accepted at real time 12
    assert at > 110.0
    assert values(j.read("s1", 50.0, closing=False) or j._serve(j.store.facts(), "s1", 50.0)) == \
        [("text", "pune")]                                            # "what did we know at 50?" misses goa
    served_prefixes_are_immutable(j)


# ============================================================================== history stability, state_version
@pytest.mark.parametrize("seed", range(10))
def test_property_state_version_is_monotone_across_served_reads(seed):
    j, _ = random_run(JOURNAL, seed + 100)
    final = j.store.facts()
    by_subject = {}
    for sv in sorted(j.served, key=lambda x: x.r):
        by_subject.setdefault(sv.subject, []).append(reconstruct(final, sv.subject, sv.r).trace)
    for traces in by_subject.values():
        for a, b in zip(traces, traces[1:]):
            for slot, hist in a.items():
                assert b.get(slot, ())[:len(hist)] == hist                # prefix: no ABA, no rewind


# ============================================================================== read ordering and read-your-writes
@pytest.mark.parametrize("snapshot_first", [False, True])
def test_a_current_read_closes_its_partition_before_it_reads(snapshot_first):
    """An append that completes INSIDE a read (between its snapshot and its closure) must not be missed."""
    wr, j = setup(snapshot_first=snapshot_first)
    put(j, wr, "c1", CITY, "pune", 5.0)
    _, p = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 8.0, wr.claim(CITY, "goa"))
    token = j.begin_read("s1", 10.0)
    res = j.finish(p)                                                 # lands while the read is in progress
    j.end_read(token)
    if not snapshot_first:
        assert res == ("READ_CLOSED", 8.0)
        served_prefixes_are_immutable(j)
    else:                                                             # WEAKENED: snapshot first, close after
        assert res == ("APPENDED", 8.0)
        with pytest.raises(AssertionError):
            served_prefixes_are_immutable(j)


def test_current_read_with_the_callers_causal_token_sees_its_own_write_across_nodes():
    wr, j = setup()
    status, at = put(j, wr, "c1", CITY, "pune", 13.0)                # written via a node whose clock reads 13
    sv = j.read("s1", 11.0, after=at)                                # read via a node whose clock reads 11
    assert sv.r == at and values(sv) == [("text", "pune")]
    served_prefixes_are_immutable(j)


def test_break_current_read_without_a_causal_token_misses_its_own_acknowledged_write():
    wr, j = setup()
    put(j, wr, "c1", CITY, "pune", 13.0)
    assert values(j.read("s1", 11.0)) == []                          # read-your-writes violated
