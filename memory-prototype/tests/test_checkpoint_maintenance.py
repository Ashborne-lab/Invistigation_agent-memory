"""Checkpoint maintenance v1: incremental creation (validated checkpoint + durable suffix), a stage -> verify ->
publish protocol, replacement only after publication, and an operational cadence trigger. Checkpoints stay derived
acceleration state; the journal stays the only authority. TEST_ONLY.

Every store-dependent test runs on both reference stores. "No full build" is proven: ``build_fold`` and the full
replay are patched to raise on every incremental path.
Contract: ``investigation/checkpoint-maintenance-v1.md``."""
import contextlib
import pickle

import pytest

import memory_core.commit_time as ct
import memory_core.gateway as gw
from memory_core import episode_commitment as EC
from memory_core import journal_compaction as JC
from memory_core.durable_journal import DurableFacts
from memory_core.projection_view import open_view
from test_checkpoint_consumers import check_gateway, gateway, say, typed as gtyped, with_checkpoints, write
from test_durable_journal_conformance import history
from test_durable_storage_boundary import make, typed, until_settled
from test_integration import CHAT, CITY, NOTE
from test_journal_compaction import KEY, erase, ev, gen, instants, load, retract, same, sync
from test_x1_commit_time import put

KINDS = ["explicit", "implied"]
INF = float("inf")


@contextlib.contextmanager
def no_full_build():
    """A full-history fold or replay anywhere raises."""
    def boom(*a, **k):
        raise AssertionError("full-history build or replay")
    saved = JC.build_fold, JC.reconstruct, ct.reconstruct, gw.reconstruct
    JC.build_fold = JC.reconstruct = ct.reconstruct = gw.reconstruct = boom
    try:
        yield
    finally:
        JC.build_fold, JC.reconstruct, ct.reconstruct, gw.reconstruct = saved


def payload(store, cp):
    return pickle.loads(store.vault[("key:" + cp.partition, cp.ref)])


def meta(cp):
    """The checkpoint fields that identify its content (not its creation metadata or transport bytes)."""
    return (cp.partition, cp.covered_at, cp.covered_count, cp.tail, cp.policy_position, cp.contract,
            cp.state_signature)


def journal(kind):
    wr, j = make(kind)
    j.checkpoints = JC.CheckpointStore(j.store)
    return wr, j, j.checkpoints


def read_ok(j, subj, clock, expect="checkpoint"):
    r = j.read(subj, clock).r
    return same(j.store.facts(), subj, r, j.checkpoints, expect=expect)


# ============================================================================================ 1. equivalence
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(6))
def test_incremental_checkpoints_equal_a_fresh_full_build(kind, seed):
    """Random histories: a checkpoint at c1 (beginning, middle, near the tail) advanced through an empty, one-entry,
    medium or long suffix to c2 has the SAME fold (decoded payload), the same canonical signature and the same
    identifying metadata as a fresh full build at c2, and is built with no full-history work."""
    st = load(kind, history(seed))
    ts = instants(st.facts())
    for subj in ("s1", "s2"):
        for c1 in (ts[0] - 1.0, ts[len(ts) // 2], ts[-2]):
            later = [t for t in ts if t > c1]
            for c2 in sorted({c1, *later[:1], *later[len(later) // 2:len(later) // 2 + 1], ts[-1] + 1.0}):
                inc = JC.CheckpointStore(st)
                assert JC.checkpoint_at(st.facts(), inc, subj, c1, incremental=False)[0] == "CREATED"
                with no_full_build():
                    status, cp = JC.checkpoint_at(st.facts(), inc, subj, c2)
                fresh = JC.CheckpointStore(st)
                _, ref = JC.checkpoint_at(st.facts(), fresh, subj, c2, incremental=False)
                assert status == "CREATED" and meta(cp) == meta(ref)
                assert payload(st, cp) == payload(st, ref)
                same(st.facts(), subj, ts[-1] + 2.0, inc)


@pytest.mark.parametrize("kind", KINDS)
def test_a_chain_of_maintenance_steps_stays_equal_to_fresh_builds(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c0", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=1)                     # the initial checkpoint (may be a full build)
    t = 2.0
    for i in range(1, 9):
        put(j, wr, f"c{i}", CITY, ["goa", "delhi", "pune"][i % 3], t, valid_from=t + 2.0 if i % 4 == 0 else None)
        if i % 3 == 0:
            retract(j, wr, f"r{i}", "pune", t + 0.1)
        if i % 4 == 1:
            sync(j, wr, f"sy{i}", t - 0.5, t + 0.2)
        t += 1.0
        with no_full_build():
            status, cp = JC.maintain(j, cps, "s1", t, threshold=1)
        assert status == "CREATED"
        fresh = JC.CheckpointStore(j.store)
        _, ref = JC.checkpoint_at(j.store.facts(), fresh, "s1", cp.covered_at, incremental=False)
        assert meta(cp) == meta(ref) and payload(j.store, cp) == payload(j.store, ref)
        assert len(cps.candidates("s1", INF)) == 1                  # older ones retired after publication
    read_ok(j, "s1", t + 1.0)


@pytest.mark.parametrize("kind", KINDS)
def test_policy_commitment_episode_and_scheduled_changes_through_incremental_maintenance(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    wr.publish(j, CITY, 2.0, breaking=True)
    put(j, wr, "c2", CITY, "goa", 2.5, valid_from=4.0)               # scheduled change
    wr.publish(j, NOTE, 2.7)
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 2.8, "agent", due=9.0), 2.8)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1"], "v1"), 2.9)
    with no_full_build():
        status, cp = JC.maintain(j, cps, "s1", 3.0, threshold=1)
    fresh = JC.CheckpointStore(j.store)
    _, ref = JC.checkpoint_at(j.store.facts(), fresh, "s1", cp.covered_at, incremental=False)
    assert status == "CREATED" and meta(cp) == meta(ref) and payload(j.store, cp) == payload(j.store, ref)
    for clock in (3.5, 5.0, 10.0):                                    # before / after the boundary and the due time
        read_ok(j, "s1", clock)


# ============================================================================================ 2. no full replay
@pytest.mark.parametrize("kind", KINDS)
def test_the_first_checkpoint_may_need_a_full_build_but_maintenance_never_does(kind):
    wr, j, cps = journal(kind)
    for i in range(5):
        put(j, wr, f"c{i}", CITY, ["pune", "goa"][i % 2], float(i + 1))
    with no_full_build():
        with pytest.raises(AssertionError, match="full-history"):
            JC.maintain(j, cps, "s1", 6.0, threshold=0)               # no previous checkpoint: a full build
    assert JC.maintain(j, cps, "s1", 6.0, threshold=0)[0] == "CREATED"
    put(j, wr, "c9", CITY, "delhi", 7.0)
    with no_full_build():
        assert JC.maintain(j, cps, "s1", 8.0, threshold=1)[0] == "CREATED"
        assert j.read("s1", 9.0).trace


@pytest.mark.parametrize("kind", KINDS)
def test_gateway_reads_commands_and_context_after_maintenance_need_no_full_replay(kind):
    g = gateway(kind)
    cps = with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    JC.maintain(g.journal, cps, "s1", 1.5, threshold=0)              # initial
    write(g, 2, "s1", "goa", 2.0)
    with no_full_build():
        assert JC.maintain(g.journal, cps, "s1", 3.0, threshold=1)[0] == "CREATED"
        a = g.get_current_state(tok, "s1", 4.0)
        say(g, 5, "s1", "set delhi", 5.0, source="OPERATOR")
        assert g.command(tok, gtyped(5, "s1", "delhi", "set delhi"), a.result.items[0].state_version, 5.0).status \
            == "APPENDED"
        g.compile_context(tok, "s1", CHAT, 4000, 6.0)
        assert JC.maintain(g.journal, cps, "s1", 6.5, threshold=1)[0] == "CREATED"
    check_gateway(g, tok, "s1", 7.0)


# ============================================================================================ 3. crash-safe publication
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("crash", ["build", "digest", "before_seal", "after_seal", "after_publish", "during_retire"])
def test_every_crash_leaves_an_older_valid_checkpoint_or_the_journal_path(kind, crash):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    put(j, wr, "c2", CITY, "goa", 2.0)
    JC.maintain(j, cps, "s1", 2.5, threshold=0)                      # two generations so far (one retired)
    old = cps.candidates("s1", INF)[0]
    put(j, wr, "c3", CITY, "delhi", 3.0)
    with pytest.raises(JC.Crash):
        JC.maintain(j, cps, "s1", 3.5, threshold=0, crash=crash)
    live = cps.candidates("s1", INF)
    assert live                                                       # never zero: something valid remains
    if crash in ("build", "digest", "before_seal", "after_seal"):
        assert live == [old]                                          # nothing new became selectable
    else:
        assert live[0].covered_at > old.covered_at                    # the new one is published and selected
    for cp in live:
        assert JC.validate(cp, j.store.facts()) is None
    rb = read_ok(j, "s1", 4.0)
    assert dict(rb.state.slots)[CITY.predicate].value == ("text", "delhi")


@pytest.mark.parametrize("kind", KINDS)
def test_a_staged_payload_that_fails_verification_is_never_published(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    old = cps.candidates("s1", INF)[0]
    put(j, wr, "c2", CITY, "goa", 2.0)
    real_seal = j.store.seal

    def corrupting_seal(key_id, ref, content):                       # storage damages the staged payload
        if ref.startswith("ckpt:"):
            content = content[:-3] + b"bad"
        return real_seal(key_id, ref, content)
    j.store.seal = corrupting_seal
    res = JC.maintain(j, cps, "s1", 2.5, threshold=0)
    j.store.seal = real_seal
    assert res == ("REJECTED", "verify:integrity")
    assert cps.candidates("s1", INF) == [old]                        # the old one is NOT retired
    assert not any(k[1].startswith("ckpt:") and k[1] != old.ref for k in j.store.vault)   # staged payload dropped
    read_ok(j, "s1", 3.0)


@pytest.mark.parametrize("kind", KINDS)
def test_a_builder_that_serializes_a_different_fold_than_it_signed_is_never_published(kind, monkeypatch):
    """The digest only proves the bytes are the bytes that were written. Verification also decodes the staged
    payload and checks the canonical state signature, so a builder defect cannot publish a wrong fold."""
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    old = cps.candidates("s1", INF)[0]
    put(j, wr, "c2", CITY, "goa", 2.0)
    real_dumps = pickle.dumps

    def wrong_dumps(f, *a, **k):
        if isinstance(f, JC.Fold):
            f = pickle.loads(real_dumps(f))
            f.cv += 100                                              # a different fold than the one signed
        return real_dumps(f, *a, **k)
    monkeypatch.setattr(JC.pickle, "dumps", wrong_dumps)
    res = JC.maintain(j, cps, "s1", 2.5, threshold=0)
    monkeypatch.setattr(JC.pickle, "dumps", real_dumps)
    assert res == ("REJECTED", "verify:state_signature") and cps.candidates("s1", INF) == [old]
    read_ok(j, "s1", 3.0)


@pytest.mark.parametrize("kind", KINDS)
def test_the_old_checkpoint_is_retired_only_after_the_new_one_is_published(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    old = cps.candidates("s1", INF)[0]
    put(j, wr, "c2", CITY, "goa", 2.0)
    events = []
    real_publish, real_discard = cps.publish, cps.discard

    def publish(cp):
        events.append(("publish", old.ref in {c.ref for c in cps.candidates("s1", INF)}))
        real_publish(cp)

    def discard(cp, reason="retired"):
        events.append(("retire", cp.ref == old.ref))
        real_discard(cp, reason)
    cps.publish, cps.discard = publish, discard
    JC.maintain(j, cps, "s1", 2.5, threshold=0)
    assert events == [("publish", True), ("retire", True)]          # old still live at publish; retired after


@pytest.mark.parametrize("kind", KINDS)
def test_published_checkpoints_are_never_mutated_by_incremental_creation(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    old = cps.candidates("s1", INF)[0]
    before = j.store.vault[("key:s1", old.ref)]
    put(j, wr, "c2", CITY, "goa", 2.0)
    JC.create(j, cps, "s1", 2.5)                                     # incremental, old kept (no maintain)
    assert j.store.vault[("key:s1", old.ref)] == before and JC.validate(old, j.store.facts()) is None


# ============================================================================================ 4. replacement matrix
def two_generations(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    _, old = JC.create(j, cps, "s1", 1.5)
    put(j, wr, "c2", CITY, "goa", 2.0)
    _, new = JC.create(j, cps, "s1", 2.5)
    put(j, wr, "c3", CITY, "delhi", 3.0)
    return wr, j, cps, old, new


def corrupt(j, cp):
    k = ("key:" + cp.partition, cp.ref)
    j.store.vault[k] = j.store.vault[k][:-4] + b"zzzz"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["both_valid", "old_corrupt", "new_corrupt", "none"])
def test_readers_use_the_newest_valid_checkpoint_or_the_journal(kind, case):
    wr, j, cps, old, new = two_generations(kind)
    if case == "old_corrupt":
        corrupt(j, old)
    elif case == "new_corrupt":
        corrupt(j, new)
    elif case == "none":
        corrupt(j, old)
        corrupt(j, new)
    r = j.read("s1", 4.0).r
    hit = JC.checkpoint_fold(j.store.facts(), "s1", r, cps)
    used = None if hit is None else hit[0].ref
    assert used == {"both_valid": new.ref, "old_corrupt": new.ref, "new_corrupt": old.ref, "none": None}[case]
    same(j.store.facts(), "s1", r, cps, expect=None)


@pytest.mark.parametrize("kind", KINDS)
def test_deleting_every_checkpoint_leaves_the_journal_answer_unchanged(kind):
    wr, j, cps, old, new = two_generations(kind)
    r = j.read("s1", 4.0).r
    with_cp = JC.rebuild(j.store.facts(), "s1", r, cps)
    for cp in list(cps.index["s1"]):
        cps.discard(cp, "dropped")
    assert not any(k[1].startswith("ckpt:") for k in j.store.vault)
    assert JC.rebuild(j.store.facts(), "s1", r, cps).view() == with_cp.view() == \
        JC.full_replay(j.store.facts(), "s1", r).view()


# ============================================================================================ 5. trigger
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("threshold,writes,expect", [(0, 0, "CREATED"), (1, 0, "SKIPPED"), (1, 1, "CREATED"),
                                                      (3, 2, "SKIPPED"), (3, 3, "CREATED"), (3, 5, "CREATED"),
                                                      (1000, 5, "SKIPPED")])
def test_the_cadence_trigger_controls_only_when_a_checkpoint_is_made(kind, threshold, writes, expect):
    """Thresholds 0, 1, small (3), large (1000); not reached, reached exactly, exceeded. checkpoint cadence = an
    operational parameter: the answer is the same either way."""
    wr, j, cps = journal(kind)
    put(j, wr, "c0", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    for i in range(writes):
        put(j, wr, f"w{i}", CITY, ["goa", "delhi"][i % 2], 2.0 + i)
    assert JC.uncovered(j, cps, "s1") == writes
    assert JC.maintain(j, cps, "s1", 10.0, threshold=threshold)[0] == expect
    read_ok(j, "s1", 11.0)


# ============================================================================================ 6. concurrency
@pytest.mark.parametrize("kind", KINDS)
def test_facts_arriving_during_maintenance_belong_to_the_suffix_and_earlier_readers_never_use_it(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    r0 = j.read("s1", 1.8).r
    token = j.begin_read("s1", 2.0)                                  # maintenance starts: closure at r
    _, at = put(j, wr, "c2", CITY, "goa", 2.0)                       # a fact arrives meanwhile
    sv = j.end_read(token)
    _, cp = JC.create(j, cps, "s1", 2.0, served=sv)
    assert at > cp.covered_at and cp.covered_count == 1
    put(j, wr, "c3", CITY, "delhi", 3.0)                             # later facts
    rb = read_ok(j, "s1", 4.0)
    assert dict(rb.state.slots)[CITY.predicate].value == ("text", "delhi")
    hit = JC.checkpoint_fold(j.store.facts(), "s1", r0, cps)
    assert hit is None or hit[0].covered_at <= r0                    # never a checkpoint newer than the reader


@pytest.mark.parametrize("kind", KINDS)
def test_maintenance_of_one_customer_never_reads_or_writes_another(kind):
    wr, j, cps = journal(kind)
    for i in range(4):
        put(j, wr, f"a{i}", CITY, "pune", 1.0 + i, subj="s1")
        put(j, wr, f"b{i}", CITY, "goa", 1.5 + i, subj="s2")
    JC.maintain(j, cps, "s1", 6.0, threshold=0)
    put(j, wr, "a9", CITY, "delhi", 7.0, subj="s1")
    before = list(j.store.entries("s2"))
    f = j.store.facts()

    class Untouchable(tuple):
        def __getitem__(self, i):
            raise AssertionError("another customer's partition was read")

        def __iter__(self):
            raise AssertionError("another customer's partition was read")

    guarded = DurableFacts({**f.partitions, "s2": Untouchable(f.partitions["s2"])}, f.publications, f.vault,
                           f.policy_history)
    status, cp = JC.checkpoint_at(guarded, cps, "s1", 8.0)
    assert status == "CREATED" and cp.partition == "s1"
    assert list(j.store.entries("s2")) == before and cps.candidates("s2", INF) == []


@pytest.mark.parametrize("kind", KINDS)
def test_maintenance_racing_a_typed_command_never_makes_it_a_conflict(kind):
    """The command is prepared, maintenance runs (a closing read), then the command finishes. At worst the journal
    refuses it transiently (closure) and the retry is admitted; it is never a STATE_CONFLICT."""
    g = gateway(kind)
    cps = with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    JC.maintain(g.journal, cps, "s1", 1.5, threshold=0)
    v = g.get_current_state(tok, "s1", 2.0).result.items[0].state_version
    say(g, 3, "s1", "set delhi", 3.0, source="OPERATOR")
    real_finish, ran = g.journal.finish, []

    def finish(p, *a, **k):
        if p.cmd == "p3" and not ran:
            ran.append(JC.maintain(g.journal, cps, "s1", 3.0, threshold=0)[0])   # maintenance between the steps
        return real_finish(p, *a, **k)
    g.journal.finish = finish
    res = g.command(tok, gtyped(3, "s1", "delhi", "set delhi"), v, 3.0)
    g.journal.finish = real_finish
    assert ran == ["CREATED"] and res.status == "APPENDED"           # at worst a transient retry, never a conflict
    check_gateway(g, tok, "s1", 5.0)


@pytest.mark.parametrize("kind", KINDS)
def test_maintenance_racing_an_in_flight_conflict_keeps_it_a_conflict(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    v = j._version("s1", CITY.predicate, j.read("s1", 2.0).r)
    st, pr = j.prepare("s1", "t1", CITY.predicate, wr.stamp(CITY), 3.0, typed(wr, "delhi"), expected_version=v)
    put(j, wr, "c2", CITY, "goa", 3.0)                               # lands in flight
    JC.maintain(j, cps, "s1", 3.2, threshold=0)                      # maintenance covers it
    res = until_settled(j.finish(pr), lambda: j.commit("s1", "t1", CITY.predicate, wr.stamp(CITY), 4.0,
                                                       typed(wr, "delhi"), expected_version=v))
    assert res[0] == "STATE_CONFLICT"


@pytest.mark.parametrize("kind", KINDS)
def test_maintenance_racing_retraction_policy_and_writes(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    token = j.begin_read("s1", 2.0)
    retract(j, wr, "r1", "pune", 2.0)
    wr.publish(j, CITY, 2.0, breaking=True)
    put(j, wr, "c2", CITY, "goa", 2.1)
    JC.create(j, cps, "s1", 2.0, served=j.end_read(token))
    JC.maintain(j, cps, "s1", 3.0, threshold=1)
    read_ok(j, "s1", 4.0)


# ============================================================================================ 7. erasure
@pytest.mark.parametrize("kind", KINDS)
def test_erasure_before_or_during_maintenance_never_yields_a_usable_view(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    erase(j, "s1", 2.0, destroy=False)                               # erasure in the suffix
    with no_full_build():
        status, cp = JC.maintain(j, cps, "s1", 3.0, threshold=1)
    assert status == "CREATED" and payload(j.store, cp).erased
    assert "zanzibar" not in repr(payload(j.store, cp))
    r = j.read("s1", 4.0).r
    assert open_view(j.store.facts(), "s1", r, cps) is None
    same(j.store.facts(), "s1", r, cps, expect="checkpoint")         # an erased answer, from the erased fold


@pytest.mark.parametrize("kind", KINDS)
def test_key_destruction_rejects_old_checkpoints_and_refuses_new_ones(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    erase(j, "s1", 2.0)                                              # erasure + key destruction
    assert JC.maintain(j, cps, "s1", 3.0, threshold=0) == ("REJECTED", "key_destroyed")
    r = j.read("s1", 4.0).r
    assert open_view(j.store.facts(), "s1", r, cps) is None
    same(j.store.facts(), "s1", r, cps, expect="full")
    assert ("unreadable" in {why for _, why in cps.rejections})
    assert "zanzibar" not in repr(j.store.facts()) + repr(cps.index)


@pytest.mark.parametrize("kind", KINDS)
def test_an_erasure_already_present_before_the_first_checkpoint(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    erase(j, "s1", 2.0, destroy=False)
    status, cp = JC.maintain(j, cps, "s1", 3.0, threshold=0)
    assert status == "CREATED" and payload(j.store, cp).erased and "zanzibar" not in repr(payload(j.store, cp))
    assert open_view(j.store.facts(), "s1", j.read("s1", 4.0).r, cps) is None


@pytest.mark.parametrize("kind", KINDS)
def test_a_corrupt_previous_checkpoint_makes_maintenance_fall_back_to_a_full_build(kind):
    wr, j, cps = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    corrupt(j, cps.candidates("s1", INF)[0])
    put(j, wr, "c2", CITY, "goa", 2.0)
    status, cp = JC.maintain(j, cps, "s1", 3.0, threshold=0)
    fresh = JC.CheckpointStore(j.store)
    _, ref = JC.checkpoint_at(j.store.facts(), fresh, "s1", cp.covered_at, incremental=False)
    assert status == "CREATED" and meta(cp) == meta(ref) and payload(j.store, cp) == payload(j.store, ref)
    assert ("integrity" in {why for _, why in cps.rejections})
    read_ok(j, "s1", 4.0)
