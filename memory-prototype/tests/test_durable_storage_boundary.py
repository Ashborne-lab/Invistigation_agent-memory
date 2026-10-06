"""Durable-journal contract v1.1: the STORAGE BOUNDARY conformance suite. TEST_ONLY_* policies only.

Every test runs UNCHANGED against both reference implementations:
- ``explicit``: frontiers are durable values in the store;
- ``implied``: no frontier value is stored; closure is implied by a serialization-consistent time source.

Assertions are about guarantees (served-prefix immutability, stamps, committed_at, refusal vs acceptance,
exactly-once), never about how closure is represented. The break tests weaken one rule in each implementation and
show a semantic failure (a served history changes, a stamp is invalidated, a command is half-applied, ...)."""
import dataclasses

import pytest

import memory_core.claimgate as claimgate
import memory_core.commit as commit_mod
from memory_core.commit import SyncRecord
from memory_core.commit_time import (JOURNAL, WRITER, Crash, TimedJournal, acknowledged_stamps_hold,
                                     served_prefixes_are_immutable)
from memory_core.durable_journal import AppendRejected, Entry, Publication, Sealed, reconstruct
from memory_core.storage_boundary import ExplicitFrontierStore, ImpliedFrontierStore, SerialClock
from test_integration import ALL, CITY, NOTE
from test_x1_commit_time import VALUES, Writer, put, values

STORES = {"explicit": ExplicitFrontierStore, "implied": ImpliedFrontierStore}
KINDS = list(STORES)


def make(kind, mode=JOURNAL, store_kw=None, **jkw):
    wr = Writer()
    ph = wr.w.p.registry._v
    j = TimedJournal(ph, mode, storage=STORES[kind](ph, **(store_kw or {})), **jkw)
    for p in ALL:
        j.publish(p.predicate, 1, 0.0)
    return wr, j


def committed_at_is_commit_time(j):
    """K2: every durable claim record's committed_at equals its entry's (journal-assigned) commit time."""
    f = j.store.facts()
    for xs in f.partitions.values():
        for x in xs:
            e = x.entry
            if e.kind == "claim" and isinstance(e.payload, Sealed):
                rec = f.vault.get((e.payload.key_id, e.payload.ref))
                if rec is not None:
                    assert rec.claim_content.committed_at == e.at, e.idem


def holds(j):
    served_prefixes_are_immutable(j)
    acknowledged_stamps_hold(j)
    committed_at_is_commit_time(j)


def sync_entry(subj, idem, at):
    return Entry(subj, "sync", idem, at, None, None, SyncRecord(idem, subj, "x", "TEST_ONLY_sync", at))


def raw(entry):
    return lambda at: [(dataclasses.replace(entry, at=at), None)]


# ============================================================================== S1 conditional append
@pytest.mark.parametrize("kind", KINDS)
def test_s1_an_entry_is_never_written_into_a_consumed_prefix(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 5.0)
    sv = j.read("s1", 10.0)
    assert j.store.append("s1", sv.r, [sync_entry("s1", "late", sv.r)])[0] == "READ_CLOSED"
    status, at = put(j, wr, "c2", CITY, "goa", 8.0)                  # the writer's clock is behind
    assert status == "APPENDED" and at > sv.r
    holds(j)


@pytest.mark.parametrize("kind", KINDS)
def test_s1_a_publication_is_never_placed_before_an_acknowledged_entry(kind):
    wr, j = make(kind)
    _, at = put(j, wr, "c1", CITY, "pune", 6.0)
    with pytest.raises(AppendRejected, match="log_closed"):
        j.store.publish_at(Publication(CITY.predicate, 2, 5.0))      # a back-dated publication
    T = wr.publish(j, CITY, 5.0, breaking=True)                      # the journal assigns T instead
    assert T > at
    holds(j)


# ============================================================================== S2 closure survives a crash
@pytest.mark.parametrize("kind", KINDS)
def test_s2_closure_survives_a_crash(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 5.0)
    sv = j.read("s1", 10.0)
    j.crash()
    assert j.store.append("s1", 9.0, [sync_entry("s1", "late", 9.0)])[0] == "READ_CLOSED"
    status, at = put(j, wr, "c2", CITY, "goa", 8.0)
    assert status == "APPENDED" and at > sv.r
    holds(j)


# ============================================================================== S3 durable before acknowledgement
@pytest.mark.parametrize("kind", KINDS)
def test_s3_an_acknowledged_fact_survives_and_its_retry_returns_the_original_time(kind):
    wr, j = make(kind)
    with pytest.raises(Crash):
        put(j, wr, "c1", CITY, "pune", 5.0, crash_after_durable=True)
    j.crash()
    [stored] = j.store.facts().partitions["s1"]
    sv = j.read("s1", 10.0)
    assert values(sv) == [("text", "pune")]
    claims_before = len(wr.w.p.store.claims)
    assert put(j, wr, "c1", CITY, "pune", 12.0) == ("DUPLICATE", stored.entry.at)
    assert len(j.store.facts().partitions["s1"]) == 1
    assert len(wr.w.p.store.claims) == claims_before                # the gate did not run again
    holds(j)


# ============================================================================== S4 reads follow closure
@pytest.mark.parametrize("kind", KINDS)
def test_s4_a_current_read_is_never_overtaken_by_an_in_flight_append(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 5.0)
    _, p = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 8.0, wr.claim(CITY, "goa"))
    token = j.begin_read("s1", 10.0)
    res = j.finish(p)                                                # completes while the read is in progress
    sv = j.end_read(token)
    assert res[0] == "READ_CLOSED" and values(sv) == [("text", "pune")]
    status, at = put(j, wr, "c2", CITY, "goa", 9.0)                  # transient: the retry gets a later time
    assert status == "APPENDED" and at > sv.r
    holds(j)


@pytest.mark.parametrize("kind", KINDS)
def test_s4_a_current_read_with_the_callers_causal_token_sees_its_own_write(kind):
    wr, j = make(kind)
    _, at = put(j, wr, "c1", CITY, "pune", 13.0)                     # written through a node reading 13
    sv = j.read("s1", 11.0, after=at)                                # read through a node reading 11
    assert sv.r >= at and values(sv) == [("text", "pune")]
    holds(j)


# ============================================================================== S5 atomic group, idempotency
@pytest.mark.parametrize("kind", KINDS)
def test_s5_a_group_is_all_or_nothing_and_a_retry_commits_it_once(kind):
    wr, j = make(kind)
    at = j.store.assign("s1", None, 1.0)
    group = [sync_entry("s1", f"g{i}", at) for i in range(3)]
    with pytest.raises(Crash):
        j.store.append("s1", at, group, crash_after=2)
    j.crash()
    assert j.store.facts().partitions.get("s1", ()) == ()
    assert j.store.append("s1", at, group)[0] == "APPENDED"
    assert j.store.append("s1", at, group)[0] == "DUPLICATE"
    assert j.store.append("s1", at, [dataclasses.replace(group[0], payload=("tampered",))])[0] == "REJECTED"
    assert len(j.store.facts().partitions["s1"]) == 3


# ============================================================================== O1 / O2 / O3 / O4 / time
@pytest.mark.parametrize("kind", KINDS)
def test_o1_a_partition_never_receives_an_earlier_commit_time(kind):
    wr, j = make(kind)
    _, at = put(j, wr, "c1", CITY, "pune", 10.0)
    before = j.store.facts().partitions["s1"]
    assert j.store.append("s1", 5.0, [sync_entry("s1", "old", 5.0)])[0] != "APPENDED"
    assert j.store.facts().partitions["s1"] == before


@pytest.mark.parametrize("kind", KINDS)
def test_commit_time_is_assigned_by_the_journal_and_is_the_records_committed_at(kind):
    import inspect
    assert "at" not in inspect.signature(TimedJournal.commit).parameters      # no caller-supplied commit time
    wr, j = make(kind)
    for i, (clock, s) in enumerate([(5.0, "s1"), (13.0, "s2"), (7.0, "s1"), (9.0, "s2"), (8.0, "s1")]):
        assert put(j, wr, f"c{i}", CITY, VALUES[i % 3], clock, subj=s)[0] == "APPENDED"
        j.read(s, clock + 0.5)
    holds(j)


@pytest.mark.parametrize("kind", KINDS)
def test_one_predicates_entries_and_publications_never_share_a_time(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 10.0)
    T = wr.publish(j, CITY, 10.0)
    sv = j.read("s1", T)
    status, at = put(j, wr, "c2", CITY, "goa", T)
    assert status == "APPENDED" and at > sv.r >= T > 10.0
    times = [x.entry.at for x in j.store.facts().partitions["s1"]] + \
            [p.at for p in j.store.publications() if p.predicate == CITY.predicate]
    assert len(times) == len(set(times))
    holds(j)


@pytest.mark.parametrize("kind", KINDS)
def test_a_publication_racing_an_in_flight_append_never_invalidates_it(kind):
    wr, j = make(kind)
    put(j, wr, "c0", NOTE, "pune", 1.0, subj="s2")
    _, p = j.prepare("s1", "c1", CITY.predicate, wr.stamp(CITY), 7.0, wr.claim(CITY, "pune"))
    T = wr.publish(j, CITY, 6.0, breaking=True)                      # a publisher whose clock is behind
    res = j.finish(p)
    if res[0] == "APPENDED":
        assert res[1] < T                                            # evaluated before the publication
    else:
        assert res[0] in ("READ_CLOSED", "STALE_POLICY_STAMP")       # refused: re-gate and retry
        status, at = put(j, wr, "c1", CITY, "pune", 7.5)
        assert status == "APPENDED" and at > T
    j.read("s1", 20.0)
    holds(j)


# ============================================================================== reads: views and as-of
@pytest.mark.parametrize("kind", KINDS)
def test_lagging_views_and_as_of_reads_serve_closed_positions_without_stored_writes(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    j.read("s1", 5.0)
    v = j.snapshot()
    _, at = put(j, wr, "c2", CITY, "goa", 6.0)
    sv = j.read_view(v, "s1", 10.0)
    assert sv.r < at and values(sv) == [("text", "pune")]           # served at what the view incorporated
    writes = j.writes
    asof = [j.read("s1", c, closing=False) for c in (11.0, 30.0)]
    assert all(x is not None for x in asof) and j.writes == writes  # no stored write for stale-tolerant reads
    put(j, wr, "c3", CITY, "delhi", 31.0)
    holds(j)


@pytest.mark.parametrize("kind", KINDS)
def test_a_view_never_serves_a_position_an_in_flight_entry_can_still_reach(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    j.read("s1", 5.0)
    _, p = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 6.0, wr.claim(CITY, "goa"))
    v = j.snapshot()                                                 # the replica is cut while c2 is in flight
    res = j.finish(p)
    j.read_view(v, "s1", 10.0)
    if res[0] != "APPENDED":
        assert put(j, wr, "c2", CITY, "goa", 7.0)[0] == "APPENDED"
    holds(j)


@pytest.mark.parametrize("kind", KINDS)
def test_current_read_closure_cost_is_measurable_in_both_forms(kind):
    """Closure is never free: explicit form = a stored frontier write; implied form = a time-service draw (no
    data-store write). Stale-tolerant reads add no data-store write in either form."""
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    clock = getattr(j.store, "clock", None)
    w0, d0 = j.writes, clock.draws if clock else 0
    j.read("s1", 5.0)                                                # current read
    w1, d1 = j.writes, clock.draws if clock else 0
    if kind == "explicit":
        assert w1 > w0
    else:
        assert w1 == w0 == 0 and d1 > d0
    j.read("s1", 6.0, closing=False)                                 # stale-tolerant read
    assert j.writes == w1


# ============================================================================== OCC, duplicates, protocol
@pytest.mark.parametrize("kind", KINDS)
def test_occ_is_decided_at_the_journal_assigned_time(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=20.0)
    assert len(values(j.read("s1", 22.0))) == 2                      # served: version 2
    res = put(j, wr, "op1", CITY, "delhi", 15.0, expected_version=1,
              say={"source": "OPERATOR", "writer": "operator", "expected_version": 1})
    assert res == ("STATE_CONFLICT", 2)
    holds(j)


def _intent_entry(subj, pid, target):
    return [(Entry(subj, "commit_intent", "intent:" + pid, 0.0, None, None, None),
             (subj, "intent:" + pid, (target, "claim:" + pid)))]


def protocol(j, wr, pid, proposer, target, value, clock, crash_after_step=None):
    """Intent (proposer's partition) -> claim (target) -> outcome (proposer), exactly once, over the boundary."""
    f = j.store.facts()
    prior = next((x.entry for x in f.partitions.get(proposer, ()) if x.entry.idem == "intent:" + pid), None)
    if prior is not None:
        target, _ = f.vault[(prior.payload.key_id, prior.payload.ref)]           # a retry re-reads the intent
    else:
        build = lambda at: [(dataclasses.replace(e, at=at), s) for e, s in _intent_entry(proposer, pid, target)]
        assert j.commit(proposer, "intent:" + pid, None, None, clock, build)[0] in ("APPENDED", "DUPLICATE")
    if crash_after_step == 1:
        raise Crash()
    assert put(j, wr, "claim:" + pid, CITY, value, clock, subj=target)[0] in ("APPENDED", "DUPLICATE")
    if crash_after_step == 2:
        raise Crash()
    outcome = Entry(proposer, "commit_outcome", "outcome:" + pid, 0.0, None, None, ("COMMITTED", "claim:" + pid))
    assert j.commit(proposer, "outcome:" + pid, None, None, clock, raw(outcome))[0] in ("APPENDED", "DUPLICATE")
    return target


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("step", [1, 2])
def test_intent_claim_outcome_is_exactly_once_across_crashes_and_a_target_change(kind, step):
    wr, j = make(kind)
    with pytest.raises(Crash):
        protocol(j, wr, "p1", "s1", "s2", "pune", 5.0, crash_after_step=step)
    j.crash()
    assert protocol(j, wr, "p1", "s1", "s3", "pune", 6.0) == "s2"   # the merge target changed; the intent wins
    f = j.store.facts()
    claims = [x for xs in f.partitions.values() for x in xs if x.entry.idem == "claim:p1"]
    kinds = [x.entry.kind for x in f.partitions["s1"]]
    assert len(claims) == 1 and claims[0].entry.partition == "s2" and "s3" not in f.partitions
    assert kinds.count("commit_intent") == 1 and kinds.count("commit_outcome") == 1
    holds(j)


TRANSIENT = ("READ_CLOSED", "COMMIT_TIME_REGRESSED")


def typed(wr, value):
    """A typed SET built inside the commit step. The writer side is only a record factory here (it is given its
    own current version so it never refuses); the JOURNAL performs the real OCC against expected_version."""
    def build(at):
        v = wr.w.p.project("s1", at).slot_version(CITY.predicate)
        return wr.claim(CITY, value, source="OPERATOR", writer="operator", expected_version=v)(at)
    return build


def stale_command(j, wr, clock):
    return j.prepare("s1", "op1", CITY.predicate, wr.stamp(CITY), clock, typed(wr, "delhi"), expected_version=1)


def until_settled(res, retry, limit=5):
    """Transient refusals are retried through the journal: a new commit time, the checks run again."""
    for _ in range(limit):
        if res[0] not in TRANSIENT:
            return res
        res = retry()
    return res


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("order", ["intervening_assigned_after", "intervening_assigned_before"])
def test_k9_a_stale_typed_command_is_never_acknowledged_when_its_slot_changes_in_flight(kind, order):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)                              # the slot at version 1
    pre = None
    if order == "intervening_assigned_before":
        _, pre = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 4.0, wr.claim(CITY, "goa"))
    st, cmd = stale_command(j, wr, 5.0)                              # time assigned; expects version 1
    assert st == "PREPARED"
    landed = until_settled(j.finish(pre) if pre else put(j, wr, "c2", CITY, "goa", 4.0),
                           lambda: put(j, wr, "c2", CITY, "goa", 4.0))
    assert landed[0] == "APPENDED"                                   # the slot changed before the command is durable
    res = until_settled(j.finish(cmd), lambda: j.commit("s1", "op1", CITY.predicate, wr.stamp(CITY), 5.0,
                                                        typed(wr, "delhi"), expected_version=1))
    assert res[0] == "STATE_CONFLICT"                                # typed outcome, returned to the agent
    assert all(x.entry.idem != "op1" for x in j.store.entries("s1"))   # never acknowledged, never durable
    assert values(j.read("s1", 50.0)) == [("text", "pune"), ("text", "goa")]
    holds(j)


K9_ALONE = {"in_write_occ_only": ({"refuse_overtaken": False}, {}),
            "overtaken_refusal_with_occ_outside_the_write": ({}, {"occ_at_write": False})}


@pytest.mark.parametrize("protection", list(K9_ALONE))
def test_k9_holds_on_the_implied_form_with_either_protection_alone(protection):
    """K9 is not proven merely because another rule happens to block the race: each protection alone suffices."""
    store_kw, jkw = K9_ALONE[protection]
    wr, j = make("implied", store_kw=store_kw, **jkw)
    put(j, wr, "c1", CITY, "pune", 1.0)
    _, pre = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 4.0, wr.claim(CITY, "goa"))
    _, cmd = stale_command(j, wr, 5.0)
    assert until_settled(j.finish(pre), lambda: put(j, wr, "c2", CITY, "goa", 4.0))[0] == "APPENDED"
    res = until_settled(j.finish(cmd), lambda: j.commit("s1", "op1", CITY.predicate, wr.stamp(CITY), 5.0,
                                                        typed(wr, "delhi"), expected_version=1))
    assert res[0] == "STATE_CONFLICT" and all(x.entry.idem != "op1" for x in j.store.entries("s1"))
    holds(j)


K9_WEAK = {"explicit": ({}, {"occ_at_write": False}),
           "implied": ({"refuse_overtaken": False}, {"occ_at_write": False})}


@pytest.mark.parametrize("kind", KINDS)
def test_break_k9_without_its_protections_a_stale_typed_command_is_acknowledged(kind):
    """Explicit: OCC checked outside the serialized write. Implied: that AND the refusal of overtaken steps."""
    store_kw, jkw = K9_WEAK[kind]
    wr, j = make(kind, store_kw=store_kw, **jkw)
    put(j, wr, "c1", CITY, "pune", 1.0)
    _, pre = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 4.0, wr.claim(CITY, "goa"))
    _, cmd = stale_command(j, wr, 5.0)                               # OCC "passes" now: still version 1
    assert j.finish(pre)[0] == "APPENDED"                            # the slot moves to version 2 (goa)
    assert j.finish(cmd)[0] == "APPENDED"                            # WEAKENED: the stale command is acknowledged
    hist = j.read("s1", 50.0).trace[CITY.predicate]
    assert len(hist) == 3 and "delhi" in repr(hist[2][1]) and hist[1][1][1] == ("text", "goa")
    # version 3 is derived from a command that expected version 1: the slot was already at version 2 (goa),
    # which the command never saw. Under the contract this command must end as STATE_CONFLICT.


# ============================================================================== boundaries, erasure, rebuild
@pytest.mark.parametrize("kind", KINDS)
def test_a_future_validity_boundary_between_reads_is_stable(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=20.0)
    a, b = j.read("s1", 15.0), j.read("s1", 25.0)
    assert values(a) == [("text", "pune")] and values(b) == [("text", "pune"), ("text", "goa")]
    holds(j)


@pytest.mark.parametrize("kind", KINDS)
def test_erasure_fences_every_cluster_partition_and_leaves_nothing_readable(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0, subj="s1")
    put(j, wr, "c2", NOTE, "allergic", 2.0, subj="s2")
    cluster = ("s1", "s2")
    for s in cluster:
        e = Entry(s, "erasure", "erasure:s1,s2", 0.0, None, None, ("cluster", cluster))
        assert j.commit(s, "erasure:s1,s2", None, None, 3.0, raw(e))[0] == "APPENDED"
        j.store.destroy_key("key:" + s)
    f = j.store.facts()
    assert all(reconstruct(f, s, 10.0).erased for s in cluster)
    assert "pune" not in repr(f.partitions) + repr(f.vault) and "allergic" not in repr(f.vault)
    assert j.commit("s2", "late", None, None, 4.0, raw(sync_entry("s2", "late", 0.0))) == \
        ("REJECTED", "partition_erased")


@pytest.mark.parametrize("kind", KINDS)
def test_rebuild_from_durable_facts_only_equals_the_live_projection(kind, monkeypatch):
    wr, j = make(kind)
    t = 1.0
    for i in range(12):
        t += 1.0
        if i % 4 == 3:
            wr.publish(j, CITY, t, breaking=i % 8 == 3)
        else:
            assert put(j, wr, f"c{i}", (CITY, NOTE)[i % 2], VALUES[i % 3], t, subj=("s1", "s2")[i % 3 == 0],
                       valid_from=t + 3.0 if i == 5 else None)[0] == "APPENDED"
        j.read(("s1", "s2")[i % 2], t + 0.5)
    t += 10.0
    facts = j.store.facts()
    j.crash()
    assert j.store.facts() == facts                                  # nothing durable lived in the process

    def boom(*a, **k):
        raise AssertionError("rebuild must not run the gate or commit")
    live = {s: wr.w.p.project(s, t).state for s in ("s1", "s2")}
    monkeypatch.setattr(claimgate, "decide", boom)
    monkeypatch.setattr(commit_mod, "commit", boom)
    for s in ("s1", "s2"):
        assert reconstruct(facts, s, t).state == live[s]
    holds(j)


# ============================================================================== deliberate breaks
def _late_entry_scenario(j, wr, crash=False):
    put(j, wr, "c1", CITY, "pune", 5.0)
    j.read("s1", 10.0)
    if crash:
        j.crash()
    return put(j, wr, "c2", CITY, "goa", 8.0)


S2_WEAK = {"explicit": {"volatile_frontiers": True}, "implied": {"clock_resets_on_crash": True}}


@pytest.mark.parametrize("kind", KINDS)
def test_break_s2_closure_that_does_not_survive_a_crash_rewrites_a_served_read(kind):
    wr, j = make(kind, store_kw=S2_WEAK[kind])
    assert _late_entry_scenario(j, wr, crash=True) == ("APPENDED", 8.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


@pytest.mark.parametrize("kind", KINDS)
def test_break_s1_unconditional_append_lets_an_in_flight_entry_into_a_served_read(kind):
    wr, j = make(kind, recheck_at_write=False)
    put(j, wr, "c1", CITY, "pune", 5.0)
    _, p = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 8.0, wr.claim(CITY, "goa"))
    j.read("s1", 10.0)
    assert j.finish(p) == ("APPENDED", 8.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


@pytest.mark.parametrize("kind", KINDS)
def test_break_s4_snapshot_before_closure_misses_an_append_completing_during_the_read(kind):
    wr, j = make(kind, snapshot_first=True)
    put(j, wr, "c1", CITY, "pune", 5.0)
    _, p = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 8.0, wr.claim(CITY, "goa"))
    token = j.begin_read("s1", 10.0)
    assert j.finish(p) == ("APPENDED", 8.0)
    j.end_read(token)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


LOG_WEAK = {"explicit": {"close_logs": False}, "implied": {}}       # implied: a per-node clock, built per test


@pytest.mark.parametrize("kind", KINDS)
def test_break_policy_log_closure_lets_a_back_dated_publication_invalidate_an_entry(kind):
    """Explicit: the log is not closed by appends/reads. Implied: the time source is per node (skewed), not
    serialization-consistent, so nothing implies closure."""
    store_kw = dict(LOG_WEAK[kind])
    if kind == "implied":
        store_kw["clock"] = SerialClock(per_node=True)
    wr, j = make(kind, store_kw=store_kw)
    put(j, wr, "c1", CITY, "pune", 6.0)
    assert wr.publish(j, CITY, 5.0, breaking=True) == 5.0
    with pytest.raises(AssertionError):
        acknowledged_stamps_hold(j)


@pytest.mark.parametrize("kind", KINDS)
def test_break_caller_assigned_commit_time_rewrites_a_served_read(kind):
    wr, j = make(kind, mode=WRITER)
    assert _late_entry_scenario(j, wr) == ("APPENDED", 8.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


@pytest.mark.parametrize("kind", KINDS)
def test_break_a_lagging_view_served_at_the_callers_clock_rewrites_a_served_read(kind):
    wr, j = make(kind, mode=WRITER)
    put(j, wr, "c1", CITY, "pune", 1.0)
    v = j.snapshot()
    put(j, wr, "c2", CITY, "goa", 6.0)
    j.read_view(v, "s1", 10.0)
    with pytest.raises(AssertionError):
        served_prefixes_are_immutable(j)


@pytest.mark.parametrize("kind", KINDS)
def test_break_duplicate_decided_after_time_re_runs_the_gate_and_loses_the_original_outcome(kind):
    wr, j = make(kind, duplicate_check_first=False)
    with pytest.raises(Crash):
        put(j, wr, "c1", CITY, "pune", 5.0, crash_after_durable=True)
    j.crash()
    claims_before = len(wr.w.p.store.claims)
    res = put(j, wr, "c1", CITY, "pune", 12.0)
    assert res[0] != "DUPLICATE"                                     # the committed command is reported as failed
    assert len(wr.w.p.store.claims) > claims_before                  # and its decision was executed again


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("atomic", [True, False])
def test_single_source_atomicity_a_crashed_group_is_never_half_applied(kind, atomic):
    wr, j = make(kind, store_kw={"atomic": atomic})
    at = j.store.assign("s1", CITY.predicate, 5.0)
    group = wr.claim(CITY, "pune")(at) + wr.claim(NOTE, "allergic")(at)   # one logical command, two claims
    sealed = [dataclasses.replace(e, payload=j.store.seal("key:" + s[0], s[1], s[2])) for e, s in group]
    with pytest.raises(Crash):
        j.store.append("s1", at, sealed, crash_after=1)
    j.crash()
    j.read("s1", 10.0)
    retry = j.store.append("s1", at, sealed)                         # the retry arrives after a read closed it
    applied = len(j.store.facts().partitions.get("s1", ()))
    assert retry[0] == "READ_CLOSED"
    if atomic:
        assert applied == 0                                          # cleanly not applied: re-prepare in full
    else:
        assert applied == 1                                          # WEAKENED: half of the command, permanently


# ============================================================================== property: both stores, random
def random_run_on(kind, seed, n=40):
    import random
    rng = random.Random(seed)
    wr, j = make(kind)
    true, pending, views = 1.0, [], []
    for i in range(n):
        true += rng.uniform(0.1, 2.0)
        clock = true + rng.choice((3.0, -3.0, 0.0, 1.0))
        x = rng.random()
        if x < 0.40:
            pol, s = rng.choice([CITY, NOTE]), rng.choice(["s1", "s2"])
            vf = rng.choice([None, None, clock + rng.uniform(0.5, 6.0)])
            st, p = j.prepare(s, f"c{i}", pol.predicate, wr.stamp(pol), clock,
                              wr.claim(pol, rng.choice(VALUES), s, vf))
            if st == "PREPARED":
                (pending.append(p) if rng.random() < 0.3 else j.finish(p))
        elif x < 0.50 and pending:
            j.finish(pending.pop(rng.randrange(len(pending))))
        elif x < 0.62:
            wr.publish(j, rng.choice([CITY, NOTE]), clock, breaking=rng.random() < 0.5)
        elif x < 0.88:
            j.read(rng.choice(["s1", "s2"]), clock, closing=rng.random() < 0.7)
        elif x < 0.94:
            views.append(j.snapshot())
        elif views:
            j.read_view(rng.choice(views), rng.choice(["s1", "s2"]), clock)
    return j


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(10))
def test_property_both_stores_keep_every_served_prefix_stamp_and_commit_time(kind, seed):
    j = random_run_on(kind, seed)
    holds(j)
    assert len(j.served) >= 3
