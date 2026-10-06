"""Durable Journal read/version fast path v1.2: the journal's served trace, read-predicate set and K9 version lookup
come from a VALIDATED checkpoint plus the durable suffix, and equal the v1.1 full replay exactly. Closure, time
assignment and the in-write K9 check are unchanged. TEST_ONLY.

"No replay" is proven, not assumed: in every fast-path test ``reconstruct`` (the full replay) is patched to raise.
Every store-dependent test runs on both reference stores.
Contract: ``investigation/durable-journal-read-version-fastpath-v1.md``."""
import contextlib
import dataclasses

import pytest

import memory_core.commit_time as ct
import memory_core.gateway as gw
from memory_core import episode_commitment as EC
from memory_core import journal_compaction as JC
from memory_core.commit_time import JOURNAL, TimedJournal, acknowledged_stamps_hold, served_prefixes_are_immutable
from memory_core.durable_journal import DurableFacts, reconstruct
from test_checkpoint_consumers import check_gateway, gateway, say, typed as gtyped, with_checkpoints, write
from test_durable_journal_conformance import history
from test_durable_storage_boundary import make, typed, until_settled
from test_integration import CHAT, CITY, NOTE
from test_journal_compaction import KEY, erase, ev, gen, instants, load, retract, sync
from test_x1_commit_time import put

KINDS = ["explicit", "implied"]


@contextlib.contextmanager
def no_replay():
    """Any full replay inside the journal (or the compaction fallback) raises."""
    def boom(*a, **k):
        raise AssertionError("full replay on the fast path")
    saved = ct.reconstruct, JC.reconstruct, gw.reconstruct
    ct.reconstruct = JC.reconstruct = gw.reconstruct = boom
    try:
        yield
    finally:
        ct.reconstruct, JC.reconstruct, gw.reconstruct = saved


def preds_of(facts, s):
    return sorted({x.entry.predicate for x in facts.partitions.get(s, ()) if x.entry.predicate})


def fast(j):
    """Give a journal a checkpoint store."""
    j.checkpoints = JC.CheckpointStore(j.store)
    return j.checkpoints


def full_version(j, s, p, at):
    return len(reconstruct(j.store.facts(), s, at).trace.get(p, ()))


def full_trace(j, s, r):
    rb = reconstruct(j.store.facts(), s, r)
    return {} if rb.erased else rb.trace


# ============================================================================================ 1. equivalence
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(6))
def test_served_trace_versions_and_read_predicates_equal_the_full_replay(kind, seed):
    """Random histories (claims, typed commands, retractions, lifecycle, syncs, breaking publications, future
    validity, a merge), checkpoints at several positions, reads with an empty, one-entry and long suffix: the
    fast path computes every result with NO replay and equals v1.1 exactly."""
    w = history(seed)
    st = load(kind, w)
    ts = instants(st.facts())
    plain = TimedJournal(w.p.registry._v, JOURNAL, storage=st)
    for subj in ("s1", "s2"):
        for c in (ts[0] - 1.0, ts[len(ts) // 3], ts[2 * len(ts) // 3], ts[-1]):
            j = TimedJournal(w.p.registry._v, JOURNAL, storage=st)
            cps = fast(j)
            JC.checkpoint_at(st.facts(), cps, subj, c)
            later = [t for t in ts if t > c]
            reads = sorted({c, *(later[:1]), *(later[len(later) // 2:len(later) // 2 + 1]), ts[-1], ts[-1] + 5.0})
            for r in reads:
                f = st.facts()
                want = (full_trace(plain, subj, r), [full_version(plain, subj, p, r) for p in preds_of(f, subj)],
                        plain._read_preds(f, subj, r))
                with no_replay():
                    got = (j.served_trace(f, subj, r), [j._version(subj, p, r) for p in preds_of(f, subj)],
                           j._read_preds(f, subj, r))
                assert got == want, (subj, c, r)


@pytest.mark.parametrize("kind", KINDS)
def test_real_reads_and_commits_run_without_replay_and_keep_every_invariant(kind):
    wr, j = make(kind)
    cps = fast(j)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=6.0)              # a scheduled (boundary) version change
    JC.create(j, cps, "s1", 3.0)
    with no_replay():
        a = j.read("s1", 4.0)
        put(j, wr, "c3", NOTE, "allergic", 4.5)
        b = j.read("s1", 7.0)                                       # after the boundary
        v = j._version("s1", CITY.predicate, b.r)
        res = j.commit("s1", "t1", CITY.predicate, wr.stamp(CITY), 8.0, typed(wr, "delhi"), expected_version=v)
        c = j.read("s1", 9.0)
    assert res[0] == "APPENDED" and len(c.trace[CITY.predicate]) == v + 1
    assert len(b.trace[CITY.predicate]) > len(a.trace[CITY.predicate])   # the boundary advanced the version
    served_prefixes_are_immutable(j)                                 # every served trace = the final full replay
    acknowledged_stamps_hold(j)


# ============================================================================================ 2. OCC and K9
def setup_typed(kind):
    wr, j = make(kind)
    cps = fast(j)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.create(j, cps, "s1", 2.0)
    return wr, j


@pytest.mark.parametrize("kind", KINDS)
def test_a_current_command_is_admitted_and_a_stale_one_is_a_state_conflict(kind):
    wr, j = setup_typed(kind)
    with no_replay():
        v = j._version("s1", CITY.predicate, j.read("s1", 3.0).r)
        assert j.commit("s1", "t1", CITY.predicate, wr.stamp(CITY), 4.0, typed(wr, "goa"), expected_version=v)[0] \
            == "APPENDED"
        assert j.commit("s1", "t2", CITY.predicate, wr.stamp(CITY), 5.0, typed(wr, "delhi"), expected_version=v) \
            == ("STATE_CONFLICT", v + 1)                            # stale: a write landed after the read
    served_prefixes_are_immutable(j)


@pytest.mark.parametrize("kind", KINDS)
def test_an_in_flight_write_is_still_caught_by_the_in_write_k9_check(kind):
    """The command is prepared, then another write lands before the durable write. Only the serialized write's own
    check can see it; with the fast path that check is computed from the validated checkpoint + the suffix that now
    contains the landed write."""
    wr, j = setup_typed(kind)
    with no_replay():
        v = j._version("s1", CITY.predicate, j.read("s1", 3.0).r)
        st, pr = j.prepare("s1", "t1", CITY.predicate, wr.stamp(CITY), 4.0, typed(wr, "delhi"), expected_version=v)
        assert st == "PREPARED"
        assert put(j, wr, "c2", CITY, "goa", 4.0)[0] == "APPENDED"   # lands in flight
        res = until_settled(j.finish(pr), lambda: j.commit("s1", "t1", CITY.predicate, wr.stamp(CITY), 5.0,
                                                           typed(wr, "delhi"), expected_version=v))
    assert res[0] == "STATE_CONFLICT"
    assert all(x.entry.idem != "t1" for x in j.store.entries("s1"))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("breaking", [False, True])
def test_policy_publications_after_the_checkpoint_change_versions_exactly_as_v11(kind, breaking):
    wr, j = setup_typed(kind)
    wr.publish(j, CITY, 3.0, breaking=breaking)
    put(j, wr, "c2", CITY, "goa", 4.0)
    r = j.read("s1", 5.0).r
    want = (full_version(j, "s1", CITY.predicate, r), full_trace(j, "s1", r))
    with no_replay():
        assert (j._version("s1", CITY.predicate, r), j.served_trace(j.store.facts(), "s1", r)) == want


@pytest.mark.parametrize("kind", KINDS)
def test_retraction_sync_commitment_and_episode_entries_in_the_suffix(kind):
    wr, j = setup_typed(kind)
    retract(j, wr, "r1", "pune", 3.0)
    sync(j, wr, "sy1", 3.5, 4.0)
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 4.0, "agent"), 4.5)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1"], "text"), 5.0)
    put(j, wr, "c2", CITY, "goa", 5.5)
    r = j.read("s1", 6.0).r
    want = (full_trace(j, "s1", r), full_version(j, "s1", CITY.predicate, r))
    with no_replay():
        assert (j.served_trace(j.store.facts(), "s1", r), j._version("s1", CITY.predicate, r)) == want


# ============================================================================================ 3. erasure, fallback, binding
@pytest.mark.parametrize("kind", KINDS)
def test_an_erasure_in_the_suffix_is_served_as_erased_without_replay(kind):
    wr, j = setup_typed(kind)
    erase(j, "s1", 3.0, destroy=False)
    with no_replay():
        sv = j.read("s1", 4.0)
        assert sv.trace == {} and j._version("s1", CITY.predicate, sv.r) == 0
    assert reconstruct(j.store.facts(), "s1", sv.r).erased


@pytest.mark.parametrize("kind", KINDS)
def test_a_destroyed_key_falls_back_to_the_full_replay(kind):
    wr, j = setup_typed(kind)
    j.store.destroy_key("key:s1")
    sv = j.read("s1", 3.0)
    assert sv.trace == full_trace(j, "s1", sv.r) and j.checkpoints.rejections[-1][1] == "unreadable"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("how", ["digest", "partition", "contract", "tail", "policy_position", "forged"])
def test_every_invalid_checkpoint_falls_back_and_the_result_is_unchanged(kind, how):
    wr, j = make(kind)
    cps = fast(j)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "d1", CITY, "goa", 1.5, subj="s2")
    JC.create(j, cps, "s1", 2.0)
    JC.create(j, cps, "s2", 2.0)
    cp = cps.index["s1"][0]
    k = ("key:s1", cp.ref)
    if how == "digest":
        j.store.vault[k] = j.store.vault[k][:-4] + b"zzzz"
    elif how == "partition":
        cps.index["s1"] = [cps.index["s2"][0]]
    elif how == "contract":
        cps.index["s1"] = [dataclasses.replace(cp, contract="journal-compaction-v0")]
    elif how == "tail":
        cps.index["s1"] = [dataclasses.replace(cp, tail=("bogus", cp.tail[1]))]
    elif how == "policy_position":
        cps.index["s1"] = [dataclasses.replace(cp, policy_position=(0, "x"))]
    else:
        import pickle
        f = pickle.loads(j.store.vault[k])
        f.versions = {key: v + 7 for key, v in f.versions.items()}
        f.trace = {key: [(v + 7, sig) for v, sig in vs] for key, vs in f.trace.items()}
        blob = pickle.dumps(f)
        j.store.vault[k] = blob
        cps.index["s1"] = [dataclasses.replace(cp, blob_digest=JC._sha(blob))]
    put(j, wr, "c2", CITY, "delhi", 3.0)
    sv = j.read("s1", 4.0)
    assert sv.trace == full_trace(j, "s1", sv.r)
    assert j._version("s1", CITY.predicate, sv.r) == full_version(j, "s1", CITY.predicate, sv.r)
    assert cps.rejections and cps.candidates("s1", 9e9) == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_checkpoint_newer_than_the_lookup_position_is_never_used(kind):
    wr, j = make(kind)
    cps = fast(j)
    put(j, wr, "c1", CITY, "pune", 1.0)
    r1 = j.read("s1", 1.5).r
    put(j, wr, "c2", CITY, "goa", 2.0)
    JC.create(j, cps, "s1", 3.0)
    assert j._version("s1", CITY.predicate, r1) == full_version(j, "s1", CITY.predicate, r1) == 1
    assert j.served_trace(j.store.facts(), "s1", r1) == full_trace(j, "s1", r1)


# ============================================================================================ 4. closure ordering (SPI)
@pytest.mark.parametrize("kind", KINDS)
def test_closure_still_precedes_serving_and_later_appends_land_after_r(kind):
    wr, j = setup_typed(kind)
    with no_replay():
        token = j.begin_read("s1", 3.0)
        _, at = put(j, wr, "c2", CITY, "goa", 3.0)                  # lands during the read
        sv = j.end_read(token)
    assert at > sv.r and sv.trace == full_trace(j, "s1", sv.r)
    served_prefixes_are_immutable(j)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("where", ["prefix", "suffix"])
def test_the_read_closes_the_policy_log_of_every_predicate_it_evaluates(kind, where):
    """NOTE's only entry is in the checkpoint's covered prefix, or only in its suffix. Either way the fast path must
    close NOTE's policy log through r, so a later publication cannot land inside the served position."""
    wr, j = make(kind)
    cps = fast(j)
    put(j, wr, "c1", CITY, "pune", 1.0)
    if where == "prefix":
        put(j, wr, "n1", NOTE, "allergic", 1.5)
    JC.create(j, cps, "s1", 2.0)
    if where == "suffix":
        put(j, wr, "n1", NOTE, "allergic", 2.5)
    with no_replay():
        sv = j.read("s1", 3.0)
    T = wr.publish(j, NOTE, 1.0)                                    # a writer with a lagging clock
    assert T > sv.r
    served_prefixes_are_immutable(j)


# ============================================================================================ 5. cost and isolation
@pytest.mark.parametrize("kind", KINDS)
def test_trace_and_version_read_only_the_suffix_of_the_partition(kind):
    wr, j = make(kind)
    cps = fast(j)
    for i in range(10):
        put(j, wr, f"c{i}", CITY, ["pune", "goa"][i % 2], float(i + 1))
    _, cp = JC.create(j, cps, "s1", 11.0)
    put(j, wr, "late", CITY, "delhi", 12.0)
    f = j.store.facts()
    touched = []

    class Counted(tuple):
        def __getitem__(self, i):
            touched.append(i)
            return tuple.__getitem__(self, i)

        def __iter__(self):
            raise AssertionError("the whole partition was scanned")

    g = DurableFacts({**f.partitions, "s1": Counted(f.partitions["s1"])}, f.publications, f.vault, f.policy_history)
    with no_replay():
        j.served_trace(g, "s1", 13.0)
        j._read_preds(g, "s1", 13.0)
    starts = [(i.start if isinstance(i, slice) else i) for i in touched]
    assert touched and min(starts) >= cp.covered_count - 1


def test_the_gateway_end_to_end_runs_without_any_full_replay():
    for kind in KINDS:
        g = gateway(kind)
        with_checkpoints(g)
        tok, _ = write(g, 1, "s1", "pune", 1.0)
        JC.create(g.journal, g.checkpoints, "s1", 2.0)
        with no_replay():
            a = g.get_current_state(tok, "s1", 3.0)
            say(g, 4, "s1", "set delhi", 4.0, source="OPERATOR")
            assert g.command(tok, gtyped(4, "s1", "delhi", "set delhi"), a.result.items[0].state_version, 4.0) \
                .status == "APPENDED"
            g.compile_context(tok, "s1", CHAT, 4000, 5.0)
        check_gateway(g, tok, "s1", 6.0)
