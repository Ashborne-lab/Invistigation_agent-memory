"""Per-operation checkpoint validation reuse v1. TEST_ONLY.

One logical operation (a Gateway read, history read, context compile, typed command, or one maintenance step)
validates a checkpoint FULLY (validate + load + canonical signature) once, and later uses inside the SAME operation
re-run ``validate`` against their own facts and skip only load + signature while the payload and every sealed fact
the decode read are the very same objects. The in-write K9 check and the staged checkpoint's publication
verification never use it. The canonical signature is unchanged.

"OLD" in these tests is the same code with reuse disabled (``OperationValidation.reuse`` always misses): every use
then validates independently, exactly as before this workstream. Every equivalence test runs both and compares.
Contract: ``investigation/per-operation-checkpoint-validation-v1.md``."""
import collections
import contextlib
import dataclasses
import hashlib
import itertools
import random
import types

import pytest

from memory_core import episode_commitment as EC
from memory_core import journal_compaction as JC
from memory_core.durable_journal import Publication
from memory_core.gateway import APPENDED, STALE_POLICY_STAMP, STATE_CONFLICT
from memory_core.journal_compaction import OperationValidation, checkpoint_fold
from memory_core.projection_view import memory_source, open_view
from test_checkpoint_consumers import CALLERS, answers, check_gateway
from test_durable_journal_conformance import history
from test_durable_storage_boundary import make, typed, until_settled
from test_incremental_checkpoint_signature import canonical_input
from test_integration import CHAT, CITY, NOTE
from test_journal_compaction import KEY, erase, ev, gen, instants, load, retract, sync
from test_memory_gateway_v0 import gateway, say, typed as gtyped, write
from test_x1_commit_time import put

KINDS = ["explicit", "implied"]
ENCS = ["full", "ref"]


# ============================================================================================ harness
@contextlib.contextmanager
def counting():
    """Counts full canonical-signature computations, payload decodes and vault reads of referenced facts."""
    n = collections.Counter()
    saved = {k: getattr(JC, k) for k in ("state_signature", "load", "_deref")}

    def wrap(k, fn):
        def counted(*a, **kw):
            n[k] += 1
            return fn(*a, **kw)
        return counted
    for k, fn in saved.items():
        setattr(JC, k, wrap(k, fn))
    try:
        yield n
    finally:
        for k, fn in saved.items():
            setattr(JC, k, fn)


@contextlib.contextmanager
def mode(reuse):
    """reuse=False: the OLD behaviour (every use validates independently). Refs are made deterministic so the two
    runs of one scenario can be compared byte for byte."""
    saved_reuse, saved_secrets = OperationValidation.reuse, JC.secrets
    c = itertools.count()
    JC.secrets = types.SimpleNamespace(token_hex=lambda k: "%016x" % next(c))
    if not reuse:
        OperationValidation.reuse = lambda self, cp, facts: None
    try:
        yield
    finally:
        OperationValidation.reuse, JC.secrets = saved_reuse, saved_secrets


def both(scenario, *a):
    """Run a scenario OLD and NEW; every result and every side effect must be identical."""
    outs = []
    for reuse in (False, True):
        with mode(reuse):
            outs.append(scenario(*a))
    assert outs[0] == outs[1]
    return outs[1]


def side_effects(store, cps):
    f = store.facts()
    return (sorted((p, list(v)) for p, v in cps.index.items()), sorted(cps.unusable), list(cps.rejections),
            sorted(f.vault), {p: [x.entry for x in v] for p, v in f.partitions.items()})


def gw_setup(kind, enc):
    g = gateway(kind)
    g.checkpoints = JC.CheckpointStore(g.journal.store, encoding=enc)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    write(g, 2, "s1", "goa", 1.5)
    assert JC.maintain(g.journal, g.checkpoints, "s1", 2.0, threshold=0)[0] == "CREATED"
    say(g, 3, "s1", "set delhi", 2.5, source="OPERATOR")
    return g, tok


OPS = [("read", lambda g, tok: g.get_current_state(tok, "s1", 3.0)),
       ("history", lambda g, tok: g.search_history(tok, "s1", 3.2)),
       ("context", lambda g, tok: g.compile_context(tok, "s1", CHAT, 4000, 3.5, request={"request_id": "T"})),
       ("command", lambda g, tok: g.command(tok, gtyped(3, "s1", "delhi", "set delhi"), 2, 4.0)),
       ("maintain", lambda g, tok: JC.maintain(g.journal, g.checkpoints, "s1", 5.0, threshold=0))]


# ============================================================================================ 1. measured counts
BEFORE = {"read": 3, "history": 3, "context": 3, "command": 4, "maintain": 5}
AFTER = {"read": 1, "history": 1, "context": 1, "command": 2, "maintain": 3}
LOADS_BEFORE = {"read": 3, "history": 3, "context": 3, "command": 4, "maintain": 4}
LOADS_AFTER = {"read": 1, "history": 1, "context": 1, "command": 2, "maintain": 2}


def measured(kind, enc):
    g, tok = gw_setup(kind, enc)
    out = {}
    for name, op in OPS:
        with counting() as n:
            res = op(g, tok)
        out[name] = (n["state_signature"], n["load"], n["_deref"], res)
    return out, side_effects(g.journal.store, g.checkpoints)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
def test_measured_validation_counts_drop_to_one_per_operation_and_results_are_identical(kind, enc):
    """Instrumented, not asserted from a model: the same operations, OLD then NEW."""
    runs = {}
    for reuse in (False, True):
        with mode(reuse):
            runs[reuse] = measured(kind, enc)
    old, new = runs[False], runs[True]
    assert {k: v[0] for k, v in old[0].items()} == BEFORE and {k: v[0] for k, v in new[0].items()} == AFTER
    assert {k: v[1] for k, v in old[0].items()} == LOADS_BEFORE and {k: v[1] for k, v in new[0].items()} == LOADS_AFTER
    for k in BEFORE:
        if enc == "full":
            assert old[0][k][2] == new[0][k][2] == 0                  # a full payload reads no referenced fact
        else:
            assert 0 < new[0][k][2] < old[0][k][2]                    # vault reads drop with the decodes
    assert [v[3] for v in old[0].values()] == [v[3] for v in new[0].values()] and old[1] == new[1]
    assert new[0]["command"][3].status == APPENDED and new[0]["maintain"][3][0] == "CREATED"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
def test_the_in_write_k9_check_performs_its_own_full_validation(kind, enc):
    """K9 authority is never reused: of a command's two validations, one runs INSIDE the serialized write."""
    g, tok = gw_setup(kind, enc)
    inside, real_append = [False], g.journal.store.append
    counted = collections.Counter()

    def append(*a, **k):
        inside[0] = True
        try:
            return real_append(*a, **k)
        finally:
            inside[0] = False
    g.journal.store.append = append
    real_sig = JC.state_signature

    def sig(f):
        counted["inside" if inside[0] else "outside"] += 1
        return real_sig(f)
    JC.state_signature = sig
    try:
        res = g.command(tok, gtyped(3, "s1", "delhi", "set delhi"), 2, 4.0)
    finally:
        JC.state_signature = real_sig
    assert res.status == APPENDED and counted == {"inside": 1, "outside": 1}


@pytest.mark.parametrize("kind", KINDS)
def test_every_operation_validates_again_on_its_own(kind):
    """No cross-operation trust: each operation's first use recomputes the canonical signature."""
    g, tok = gw_setup(kind, "full")
    for name, op in OPS[:3] + OPS[:3]:
        with counting() as n:
            op(g, tok)
        assert n["state_signature"] == 1, name


# ============================================================================================ 2. equivalence
def gateway_run(kind, enc, seed):
    rng = random.Random(seed)
    g = gateway(kind)
    g.checkpoints = JC.CheckpointStore(g.journal.store, encoding=enc)
    toks, t, n, out = {}, 1.0, 0, []
    for _ in range(30):
        subj = rng.choice(["s1", "s1", "s2"])
        t += rng.uniform(0.1, 1.0)
        n += 1
        x = rng.random()
        if x < 0.35 or subj not in toks:
            toks[subj], res = write(g, n, subj, rng.choice(["pune", "goa", "delhi"]), t)
            out.append(res)
        elif x < 0.55:
            say(g, n, subj, f"set {n}", t, source="OPERATOR")
            v = next((i.state_version for i in g.get_current_state(toks[subj], subj, t).result.items
                      if i.predicate == CITY.predicate), 0)
            out.append(g.command(toks[subj], gtyped(n, subj, rng.choice(["pune", "goa"]), f"set {n}"),
                                 v if rng.random() < 0.7 else v + 5, t + 0.01))
        elif x < 0.63:
            cur = g.registry.get(CITY.predicate)
            g.publish_policy(dataclasses.replace(cur, policy_version_id=cur.policy_version_id + 1,
                                                 breaking=rng.random() < 0.5), t)
        elif x < 0.78:
            out.append(JC.maintain(g.journal, g.checkpoints, subj, t, threshold=rng.choice([0, 1, 2])))
        else:
            out += [g.get_current_state(toks[subj], subj, t), g.search_history(toks[subj], subj, t),
                    g.compile_context(toks[subj], subj, CHAT, 4000, t, request={"request_id": "T"}),
                    g.last_read_source]
    return out, side_effects(g.journal.store, g.checkpoints)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
@pytest.mark.parametrize("seed", range(3))
def test_gateway_reads_history_context_commands_and_maintenance_are_identical(kind, enc, seed):
    out, _ = both(gateway_run, kind, enc, seed)
    assert "checkpoint" in out


def op_read(j, cps, subj, clock):
    """One journal-level logical read: closing read, view and K9-style version lookup share one validation."""
    with OperationValidation(subj) as op:
        sv = j.read(subj, clock, op=op)
        f = j.store.facts()
        v = open_view(f, subj, sv.r, cps, op=op)
        ver = j._version(subj, CITY.predicate, sv.r, op)
    return sv, None if v is None else answers(memory_source(v), subj, sv.r, CALLERS[subj]), ver


def journal_run(kind, enc, destroy):
    """Retraction, freshness, commitment and episode entries, a breaking publication, a scheduled version change,
    incremental maintenance, current / stale / in-flight commands, then erasure."""
    wr, j = make(kind)
    cps = j.checkpoints = JC.CheckpointStore(j.store, encoding=enc)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=7.0)               # scheduled version advance
    out = [JC.maintain(j, cps, "s1", 2.5, threshold=0), op_read(j, cps, "s1", 3.0)]
    retract(j, wr, "r1", "pune", 3.5)
    sync(j, wr, "sy1", 3.6, 4.0)
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 4.1, "agent"), 4.2)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1"], "recap"), 4.4)
    wr.publish(j, CITY, 4.6, breaking=True)
    out += [op_read(j, cps, "s1", 5.0), JC.maintain(j, cps, "s1", 5.5, threshold=0), op_read(j, cps, "s1", 8.0)]
    v = out[-1][2]
    out.append(j.commit("s1", "t1", CITY.predicate, wr.stamp(CITY), 8.5, typed(wr, "delhi"), expected_version=v))
    out.append(j.commit("s1", "t2", CITY.predicate, wr.stamp(CITY), 9.0, typed(wr, "goa"), expected_version=v))
    v = op_read(j, cps, "s1", 9.5)[2]
    st, pr = j.prepare("s1", "t3", CITY.predicate, wr.stamp(CITY), 10.0, typed(wr, "pune"), expected_version=v)
    out.append(put(j, wr, "c3", CITY, "goa", 10.0))                  # lands in flight
    out.append(until_settled(j.finish(pr), lambda: j.commit("s1", "t3", CITY.predicate, wr.stamp(CITY), 10.5,
                                                            typed(wr, "pune"), expected_version=v)))
    erase(j, "s1", 11.0, destroy=destroy)
    out += [op_read(j, cps, "s1", 12.0), JC.maintain(j, cps, "s1", 12.5, threshold=0)]
    return out, side_effects(j.store, cps)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
@pytest.mark.parametrize("destroy", [False, True])
def test_journal_operations_through_retraction_policy_schedule_occ_and_erasure_are_identical(kind, enc, destroy):
    out, _ = both(journal_run, kind, enc, destroy)
    assert out[5][0] == "APPENDED" and out[6][0] == "STATE_CONFLICT" and out[8][0] == "STATE_CONFLICT"
    assert out[9][0].trace == {} and out[9][1] is None               # erased: no view, nothing served


def history_run(kind, enc, seed):
    """Random v1.1 histories (claims, typed commands, retractions, lifecycle, syncs, breaking publications, future
    validity, a merge). ONE operation looks the partition up at several positions, increasing and decreasing."""
    w = history(seed)
    st = load(kind, w)
    ts = instants(st.facts())
    out = []
    for subj in ("s1", "s2"):
        for c in (ts[len(ts) // 3], ts[-1]):
            cps = JC.CheckpointStore(st, encoding=enc)
            JC.checkpoint_at(st.facts(), cps, subj, c)
            later = [t for t in ts if t > c] + [ts[-1] + 5.0]
            with OperationValidation(subj) as op:
                for r in [later[-1], c, later[0], ts[0] - 1.0, later[len(later) // 2], later[-1]]:
                    f = st.facts()
                    hit = checkpoint_fold(f, subj, r, cps, op=op)
                    v = open_view(f, subj, r, cps, op=op)
                    out.append((r, hit, v and answers(memory_source(v), subj, r, CALLERS[subj])))
            out.append(side_effects(st, cps))
    return out


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
@pytest.mark.parametrize("seed", range(3))
def test_random_histories_at_several_positions_in_one_operation_are_identical(kind, enc, seed):
    out = both(history_run, kind, enc, seed)
    assert any(x[1] is not None for x in out if len(x) == 3)


# ============================================================================================ 3. typed commands
def gw_command(kind, enc, case):
    g, tok = gw_setup(kind, enc)
    v = g.get_current_state(tok, "s1", 3.0).result.items[0].state_version
    landed, real_finish = [], g.journal.finish
    if case == "write_after_read":
        write(g, 9, "s1", "pune", 3.5)
    elif case == "breaking_policy":
        cur = g.registry.get(CITY.predicate)
        g.publish_policy(dataclasses.replace(cur, policy_version_id=2, breaking=True), 3.5)
    elif case in ("in_flight_write", "in_flight_policy"):
        def finish(p, *a, **k):
            if p.cmd == "p3" and not landed:
                if case == "in_flight_write":
                    landed.append(write(g, 9, "s1", "pune", 3.9)[1].status)
                else:
                    cur = g.registry.get(CITY.predicate)
                    landed.append(g.publish_policy(dataclasses.replace(cur, policy_version_id=2), 3.9))
            return real_finish(p, *a, **k)
        g.journal.finish = finish
    res = g.command(tok, gtyped(3, "s1", "delhi", "set delhi"), v + 7 if case == "stale" else v, 4.0)
    g.journal.finish = real_finish
    return res, landed, side_effects(g.journal.store, g.checkpoints)


EXPECT = {"current": APPENDED, "stale": STATE_CONFLICT, "write_after_read": STATE_CONFLICT,
          "breaking_policy": STALE_POLICY_STAMP, "in_flight_write": STATE_CONFLICT,
          "in_flight_policy": STALE_POLICY_STAMP}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
@pytest.mark.parametrize("case", sorted(EXPECT))
def test_typed_command_outcomes_are_identical_and_in_flight_changes_are_still_caught(kind, enc, case):
    """A write or publication landing AFTER the operation's validation, inside the command, is still decided by
    the journal's own in-write check against the facts at the serialized write point."""
    res, landed, _ = both(gw_command, kind, enc, case)
    if case == "in_flight_policy":                                     # storage decides T: either it is in force
        assert res.status == STALE_POLICY_STAMP or landed[0] > res.at  # at the write (refused) or after it
    else:
        assert res.status == EXPECT[case], (res, landed)
    if case == "in_flight_write":
        assert landed == [APPENDED]


# ============================================================================================ 4. inside one operation
def unit(kind, enc):
    wr, j = make(kind)
    cps = j.checkpoints = JC.CheckpointStore(j.store, encoding=enc)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "n1", NOTE, "allergic", 1.5)
    retract(j, wr, "r1", "pune", 1.8)
    assert JC.create(j, cps, "s1", 2.0)[0] == "CREATED"
    return wr, j, cps, cps.index["s1"][0]


def change(registry, wr, j, cps, cp, how):
    k = ("key:s1", cp.ref)
    if how == "destroyed_key":
        j.store.destroy_key("key:s1")
    elif how == "bad_digest":
        j.store.vault[k] = j.store.vault[k][:-3] + b"bad"
    elif how == "forged_index_signature":                              # same ref, same payload, other identity
        cps.index["s1"] = [dataclasses.replace(cp, state_signature="0" * 64)]
    elif how == "other_encoding":
        cps.index["s1"] = [dataclasses.replace(cp, encoding="zip")]
    elif how == "late_publication":                                    # a publication inside c
        new = dataclasses.replace(registry.get(NOTE.predicate), policy_version_id=2)
        registry.publish(new)
        j.store.publish_at(Publication(NOTE.predicate, 2, cp.covered_at - 0.1), conditional=False)
    elif how == "resealed_reference":                                  # a referenced sealed fact is replaced
        ck = next(x for x in j.store.vault if x[1].startswith("c:"))
        rec = j.store.vault[ck]
        j.store.vault[ck] = dataclasses.replace(rec, claim_content=dataclasses.replace(
            rec.claim_content, value=("text", "atlantis")))
    elif how == "new_suffix_entry":                                    # not invalidating: advanced through
        put(j, wr, "c9", CITY, "goa", 3.0)
    elif how == "newer_checkpoint":
        put(j, wr, "c9", CITY, "goa", 3.0)
        assert JC.create(j, cps, "s1", 3.5)[0] == "CREATED"


CHANGES = {"destroyed_key": "unreadable", "bad_digest": "integrity", "forged_index_signature": "state_signature",
           "other_encoding": "encoding", "late_publication": "policy_log_changed",
           "resealed_reference": "state_signature", "new_suffix_entry": None, "newer_checkpoint": None}


def mid_operation(kind, enc, how, sigs):
    wr, j, cps, cp = unit(kind, enc)
    with OperationValidation("s1") as op:
        first = checkpoint_fold(j.store.facts(), "s1", 2.5, cps, op=op)
        change(wr.w.p.registry, wr, j, cps, cp, how)
        with counting() as n:
            second = checkpoint_fold(j.store.facts(), "s1", 4.0, cps, op=op)
    sigs.append(n["state_signature"])                                  # differs OLD vs NEW by design: not compared
    return first, second, list(cps.rejections)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc,how", [(e, h) for e in ENCS for h in sorted(CHANGES)
                                     if not (e == "full" and h == "resealed_reference")])   # full: no references
def test_a_change_inside_one_operation_is_seen_exactly_as_by_an_independent_validation(kind, enc, how):
    """The operation validated the checkpoint at r1; at r2 that validation is no longer enough (or a newer
    checkpoint exists). The result equals a fresh, independent validation: a rejection with the same reason, a
    new full validation, or (an appended fact) the same checkpoint advanced through the longer suffix."""
    sigs = []
    first, second, rejections = both(mid_operation, kind, enc, how, sigs)
    assert first is not None
    if CHANGES[how] is not None:
        assert second is None and rejections[-1][1] == CHANGES[how]
    elif how == "newer_checkpoint":
        assert second[0] != first[0] and sigs == [1, 1]               # the new one is fully validated, OLD and NEW
    else:
        assert second[0] == first[0] and sigs == [1, 0] and second[1].position > first[1].position


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
def test_the_validated_fold_is_immutable_and_never_handed_out(kind, enc):
    wr, j, cps, cp = unit(kind, enc)
    put(j, wr, "c9", CITY, "goa", 3.0)
    with OperationValidation("s1") as op:
        a = checkpoint_fold(j.store.facts(), "s1", 4.0, cps, op=op)[1]
        a.claims.clear()
        a.trace.clear()
        a.cv += 99                                                     # a consumer damages its copy
        lo = checkpoint_fold(j.store.facts(), "s1", 2.5, cps, op=op)[1]   # lower position after a higher one
        hi = checkpoint_fold(j.store.facts(), "s1", 4.0, cps, op=op)[1]
        assert JC.state_signature(op._seen[cp][1]) == cp.state_signature
    assert lo == checkpoint_fold(j.store.facts(), "s1", 2.5, cps)[1]
    assert hi == checkpoint_fold(j.store.facts(), "s1", 4.0, cps)[1] and hi is not a


@pytest.mark.parametrize("kind", KINDS)
def test_a_position_before_the_checkpoint_never_uses_it_even_inside_the_operation(kind):
    wr, j, cps, cp = unit(kind, "full")
    with OperationValidation("s1") as op:
        assert checkpoint_fold(j.store.facts(), "s1", 3.0, cps, op=op) is not None
        assert checkpoint_fold(j.store.facts(), "s1", cp.covered_at - 0.01, cps, op=op) is None


# ============================================================================================ 5. no cross-operation trust
@pytest.mark.parametrize("kind", KINDS)
def test_a_finished_operation_authorizes_nothing(kind):
    wr, j, cps, cp = unit(kind, "full")
    with OperationValidation("s1") as op:
        assert checkpoint_fold(j.store.facts(), "s1", 3.0, cps, op=op) is not None
    with pytest.raises(ValueError, match="operation_validation_closed"):
        checkpoint_fold(j.store.facts(), "s1", 3.0, cps, op=op)       # a leaked result cannot be injected
    with pytest.raises(ValueError, match="operation_validation_closed"):
        j.read("s1", 4.0, op=op)


@pytest.mark.parametrize("kind", KINDS)
def test_one_subjects_validation_cannot_serve_another_subject(kind):
    wr, j, cps, cp = unit(kind, "full")
    put(j, wr, "d1", CITY, "goa", 2.2, subj="s2")
    assert JC.create(j, cps, "s2", 2.5)[0] == "CREATED"
    with OperationValidation("s1") as op:
        assert checkpoint_fold(j.store.facts(), "s1", 3.0, cps, op=op) is not None
        with pytest.raises(ValueError, match="operation_validation_subject"):
            checkpoint_fold(j.store.facts(), "s2", 3.0, cps, op=op)
        cps.index["s1"] = [cps.index["s2"][0]]                         # a swapped index inside the operation
        assert checkpoint_fold(j.store.facts(), "s1", 3.0, cps, op=op) is None
    assert cps.rejections[-1][1] == "wrong_partition"


@pytest.mark.parametrize("kind", KINDS)
def test_one_encodings_validation_cannot_validate_another_encoding(kind):
    """Two checkpoint stores (full, compact) over one storage: inside one operation each checkpoint is fully
    validated on its own; both equal a fresh fold."""
    wr, j, full, cp = unit(kind, "full")
    ref = JC.CheckpointStore(j.store, encoding="ref")
    assert JC.checkpoint_at(j.store.facts(), ref, "s1", cp.covered_at)[0] == "CREATED"
    f = j.store.facts()
    with OperationValidation("s1") as op, counting() as n:
        a = checkpoint_fold(f, "s1", 3.0, full, op=op)
        b = checkpoint_fold(f, "s1", 3.0, ref, op=op)
        assert n["state_signature"] == 2 and a[0] != b[0] and a[0].state_signature == b[0].state_signature
    assert a[1] == b[1] == checkpoint_fold(f, "s1", 3.0, full)[1]


CORRUPT_B = {"bad_digest": "integrity", "destroyed_key": "unreadable", "forged_index_signature": "state_signature",
             "late_publication": "policy_log_changed"}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("how", sorted(CORRUPT_B))
def test_operation_a_validates_the_checkpoint_corrupts_and_operation_b_rejects_it(kind, how):
    g, tok = gw_setup(kind, "full")
    check_gateway(g, tok, "s1", 3.0)                                   # operation A: served from the checkpoint
    cps = g.checkpoints
    change(g.registry, None, g.journal, cps, cps.index["s1"][0], how)
    check_gateway(g, tok, "s1", 4.0, expect="journal")                 # operation B: rejected, journal path
    assert cps.rejections[-1][1] == CORRUPT_B[how]


# ============================================================================================ 6. signature unchanged
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("enc", ENCS)
def test_the_canonical_signature_is_unchanged_for_fresh_and_incrementally_maintained_checkpoints(kind, enc):
    """Every checkpoint of a maintenance chain run with reuse (the first a fresh build, the rest incremental from
    an operation-validated base) carries exactly SHA-256 of the canonical input of a fresh full build. (Every
    ``both`` comparison above also compares each published checkpoint, signature included, OLD against NEW.)"""
    wr, j = make(kind)
    cps = j.checkpoints = JC.CheckpointStore(j.store, encoding=enc)
    made = []
    for i in range(5):
        put(j, wr, f"c{i}", [CITY, NOTE][i % 2], ["goa", "delhi"][i % 2], 1.0 + i)
        res = JC.maintain(j, cps, "s1", 1.5 + i, threshold=0)
        assert res[0] == "CREATED"
        made.append(res[1])
        assert op_read(j, cps, "s1", 1.6 + i)[1] is not None
    for cp in made:
        f = JC.build_fold(j.store.facts(), "s1", cp.covered_at)
        assert cp.state_signature == JC.state_signature(f) == hashlib.sha256(canonical_input(f)).hexdigest()
