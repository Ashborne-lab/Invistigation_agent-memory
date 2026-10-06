"""Checkpoint representation pruning v1. TEST_ONLY.

Result under test: NO semantic pruning is proven safe (the claim map, retractions, commitment events and the trace
must stay complete), so the smaller representation is LOSSLESS: the "ref" payload encoding stores a vault
reference instead of a copy of every object that is a sealed journal fact (claim content, retraction records,
commitment events, episode generations), and drops the fields derivable from the trace (versions, last).

Two kinds of evidence:
- the compact encoding is exactly equivalent to the full one (same canonical state signature, same decoded fold,
  same answers for every fast-path operation), and needs no full-history work;
- a deliberately NAIVE semantic pruner (test-only: keep only claims that win or conflict at c, drop events of
  terminal commitments) diverges from the journal in the "dead claim" scenarios. That is why v1 prunes nothing.

Every store-dependent test runs on both reference stores.
Contract: ``investigation/checkpoint-representation-pruning-v1.md``."""
import contextlib
import copy
import dataclasses
import pickle

import pytest

import memory_core.commit_time as ct
import memory_core.gateway as gw
from memory_core import commitments as CM
from memory_core import episode_commitment as EC
from memory_core import journal_compaction as JC
from memory_core.durable_journal import DurableFacts, Publication
from memory_core.commit import RetractionRecord
from memory_core.model import ACTIVE, INVALIDATED, NEVER_TRUE, QUARANTINED
from memory_core.projection_view import memory_source, open_view
from test_checkpoint_consumers import answers, check_gateway, gateway, say, typed as gtyped, write
from test_durable_journal_conformance import history
from test_durable_storage_boundary import make, typed, until_settled
from test_integration import CHAT, CITY, NOTE
from test_journal_compaction import KEY, act, erase, ev, gen, instants, load, retract, same, sync
from test_x1_commit_time import put

KINDS = ["explicit", "implied"]
INF = float("inf")


def stores(st):
    return JC.CheckpointStore(st), JC.CheckpointStore(st, encoding="ref")


def both_at(st, subj, c):
    full, ref = stores(st)
    _, a = JC.checkpoint_at(st.facts(), full, subj, c, incremental=False)
    _, b = JC.checkpoint_at(st.facts(), ref, subj, c, incremental=False)
    return full, ref, a, b


def assert_equivalent(st, subj, c, reads):
    full, ref, a, b = both_at(st, subj, c)
    assert b.encoding == "ref" and a.encoding == "full"
    assert a.state_signature == b.state_signature                    # the strongest single check
    fa, fb = JC.load(a, st.facts())[0], JC.load(b, st.facts())[0]
    assert fa == fb and list(fa.claims) == list(fb.claims)           # same fold, same claim order
    for r in [x for x in reads if x >= c]:                           # a checkpoint never serves r < c
        va, vb = JC.rebuild(st.facts(), subj, r, full), JC.rebuild(st.facts(), subj, r, ref)
        assert va.view() == vb.view() == JC.full_replay(st.facts(), subj, r).view()
        assert va.source == vb.source == "checkpoint"
        xa, xb = open_view(st.facts(), subj, r, full), open_view(st.facts(), subj, r, ref)
        if xa is not None:
            caller = __import__("test_checkpoint_consumers").CALLERS[subj]
            assert answers(memory_source(xa), subj, r, caller) == answers(memory_source(xb), subj, r, caller)
    return a, b


@contextlib.contextmanager
def no_full_work():
    """Full-history fold, full replay and FULL-encoding decode all raise: only the compact path may run."""
    def boom(*a, **k):
        raise AssertionError("full-history work or a full payload decode")
    real_decode = JC.decode

    def decode(blob, encoding, facts):
        if encoding == "full":
            boom()
        return real_decode(blob, encoding, facts)
    saved = JC.build_fold, JC.reconstruct, ct.reconstruct, gw.reconstruct, JC.decode
    JC.build_fold = JC.reconstruct = ct.reconstruct = gw.reconstruct = boom
    JC.decode = decode
    try:
        yield
    finally:
        JC.build_fold, JC.reconstruct, ct.reconstruct, gw.reconstruct, JC.decode = saved


# ============================================================================================ 1. equivalence
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(6))
def test_the_compact_encoding_is_exactly_equivalent_on_random_histories(kind, seed):
    st = load(kind, history(seed))
    ts = instants(st.facts())
    for subj in ("s1", "s2"):
        for c in (ts[0] - 1.0, ts[len(ts) // 3], ts[2 * len(ts) // 3], ts[-1] + 1.0):
            assert_equivalent(st, subj, c, sorted({c, ts[-1], ts[-1] + 5.0} | ({c + 0.05} if c < ts[-1] else set())))


@pytest.mark.parametrize("kind", KINDS)
def test_a_long_claim_heavy_history_is_much_smaller_and_still_equal(kind):
    wr, j = make(kind)
    for i in range(40):
        put(j, wr, f"c{i}", [CITY, NOTE][i % 2], ["pune", "goa", "delhi"][i % 3], float(i + 1),
            valid_from=float(i + 3) if i % 7 == 0 else None)
        if i % 9 == 4:
            retract(j, wr, f"r{i}", "pune", float(i + 1) + 0.5)
        if i % 11 == 5:
            sync(j, wr, f"s{i}", float(i), float(i + 1) + 0.6)
    a, b = assert_equivalent(j.store, "s1", 60.0, [60.0, 70.0])
    full_bytes, ref_bytes = len(j.store.vault[("key:s1", a.ref)]), len(j.store.vault[("key:s1", b.ref)])
    assert ref_bytes * 3 < full_bytes                                 # materially smaller (claims dominate)


@pytest.mark.parametrize("kind", KINDS)
def test_commitment_events_and_episode_generations_are_referenced_not_copied(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    for i in range(6):
        EC.record_commitment_event(j, KEY, ev(f"x{i}", f"k{i % 2}", "create" if i < 2 else "cancel", 1.0 + i,
                                              "agent" if i < 2 else "user", due=30.0), 2.0 + i)
        EC.record_episode_generation(j, KEY, gen("ep1", [f"e{k}" for k in range(i + 1)], f"summary {i}"), 2.5 + i)
    a, b = assert_equivalent(j.store, "s1", 20.0, [20.0, 40.0])
    raw = pickle.loads(j.store.vault[("key:s1", b.ref)])
    assert raw["events"] and all(isinstance(r, tuple) for r in raw["events"])
    assert raw["fold"].events == [] and raw["fold"].generations == {} and raw["fold"].claims == {}


@pytest.mark.parametrize("kind", KINDS)
def test_maintenance_on_a_compact_store_and_from_a_full_base_stays_exact(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store)                                 # starts FULL
    j.checkpoints = cps
    put(j, wr, "c0", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    cps.encoding = "ref"                                              # switch: the next checkpoints are compact
    t = 2.0
    for i in range(1, 7):
        put(j, wr, f"c{i}", CITY, ["goa", "delhi"][i % 2], t)
        if i == 3:
            retract(j, wr, "r3", "goa", t + 0.1)
        t += 1.0
        status, cp = JC.maintain(j, cps, "s1", t, threshold=1)      # incremental from the previous (any encoding)
        assert status == "CREATED" and cp.encoding == "ref"
        fresh = JC.CheckpointStore(j.store)
        _, ref = JC.checkpoint_at(j.store.facts(), fresh, "s1", cp.covered_at, incremental=False)
        assert cp.state_signature == ref.state_signature
        assert JC.load(cp, j.store.facts())[0] == JC.load(ref, j.store.facts())[0]
    same(j.store.facts(), "s1", j.read("s1", t + 1).r, cps)


# ============================================================================================ 2. no full work
@pytest.mark.parametrize("kind", KINDS)
def test_a_compact_store_needs_no_full_build_replay_or_full_decode(kind):
    g = gateway(kind)
    cps = JC.CheckpointStore(g.journal.store, encoding="ref")
    g.checkpoints = cps
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    JC.maintain(g.journal, cps, "s1", 1.5, threshold=0)              # the first checkpoint: a full build
    write(g, 2, "s1", "goa", 2.0)
    with no_full_work():
        assert JC.maintain(g.journal, cps, "s1", 3.0, threshold=1)[0] == "CREATED"
        a = g.get_current_state(tok, "s1", 4.0)
        say(g, 5, "s1", "set delhi", 5.0, source="OPERATOR")
        assert g.command(tok, gtyped(5, "s1", "delhi", "set delhi"), a.result.items[0].state_version, 5.0).status \
            == "APPENDED"
        g.compile_context(tok, "s1", CHAT, 4000, 6.0)
        g.search_history(tok, "s1", 6.5)
    check_gateway(g, tok, "s1", 7.0)


@pytest.mark.parametrize("kind", KINDS)
def test_k9_in_flight_conflict_with_a_compact_checkpoint(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    j.checkpoints = cps
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    with no_full_work():
        v = j._version("s1", CITY.predicate, j.read("s1", 2.0).r)
        st, pr = j.prepare("s1", "t1", CITY.predicate, wr.stamp(CITY), 3.0, typed(wr, "delhi"), expected_version=v)
        put(j, wr, "c2", CITY, "goa", 3.0)                           # lands in flight
        res = until_settled(j.finish(pr), lambda: j.commit("s1", "t1", CITY.predicate, wr.stamp(CITY), 4.0,
                                                           typed(wr, "delhi"), expected_version=v))
    assert res[0] == "STATE_CONFLICT"


@pytest.mark.parametrize("kind", KINDS)
def test_decoding_a_compact_checkpoint_reads_only_the_suffix_of_its_partition(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    for i in range(8):
        put(j, wr, f"a{i}", CITY, "pune", 1.0 + i, subj="s1")
        put(j, wr, f"b{i}", CITY, "goa", 1.5 + i, subj="s2")
    _, cp = JC.create(j, cps, "s1", 10.0)
    put(j, wr, "late", CITY, "delhi", 11.0, subj="s1")
    f = j.store.facts()
    touched = []

    class Counted(tuple):
        def __getitem__(self, i):
            touched.append(i)
            return tuple.__getitem__(self, i)

        def __iter__(self):
            raise AssertionError("a partition was scanned")

    g = DurableFacts({"s1": Counted(f.partitions["s1"]), "s2": Counted(f.partitions["s2"])}, f.publications,
                     f.vault, f.policy_history)
    hit = JC.checkpoint_fold(g, "s1", 12.0, cps)
    assert hit is not None and hit[0].ref == cp.ref
    starts = [(i.start if isinstance(i, slice) else i) for i in touched]
    assert min(starts) >= cp.covered_count - 1


# ============================================================================================ 3. safety of references
@pytest.mark.parametrize("kind", KINDS)
def test_a_missing_referenced_fact_rejects_the_checkpoint_never_skips_it(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0)
    _, cp = JC.create(j, cps, "s1", 3.0)
    raw = pickle.loads(j.store.vault[("key:s1", cp.ref)])
    idx, ref = raw["claims"][0][0]
    claim_ref = (raw["keys"][idx], ref)
    del j.store.vault[claim_ref]                                     # that record is gone; the subject key survives
    r = j.read("s1", 4.0).r
    rb = same(j.store.facts(), "s1", r, cps, expect="full")         # the journal answer (it skips the unreadable)
    assert cps.rejections[-1][1] == "unreadable_reference"
    assert len(rb.claims) == 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("breakage", ["versions", "last", "order", "retraction_refs", "claim_refs"])
def test_compact_encoding_refuses_a_fold_whose_derived_fields_or_references_do_not_hold(kind, breakage):
    """versions/last are dropped only because they equal len(trace)/trace[-1]; references only because every
    copied fact has one. A fold breaking either is refused (never derived wrongly), and creation reports it."""
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", NOTE, "goa", 2.0)
    retract(j, wr, "r1", "pune", 3.0)
    f = JC.build_fold(j.store.facts(), "s1", 4.0)
    JC.encode(f, "ref")                                               # the real fold is encodable
    k = next(iter(f.versions))
    if breakage == "versions":
        f.versions[k] += 1
    elif breakage == "last":
        f.last[k] = ("other",)
    elif breakage == "order":
        f.last = dict(reversed(list(f.last.items())))
    elif breakage == "retraction_refs":
        f.retraction_refs = []
    else:
        f.claim_refs = {}
    with pytest.raises(ValueError, match="compact_encoding_invariant"):
        JC.encode(f, "ref")


@pytest.mark.parametrize("kind", KINDS)
def test_an_unknown_encoding_is_never_decoded(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    put(j, wr, "c1", CITY, "pune", 1.0)
    _, cp = JC.create(j, cps, "s1", 2.0)
    cps.index["s1"] = [dataclasses.replace(cp, encoding="zip")]
    same(j.store.facts(), "s1", j.read("s1", 3.0).r, cps, expect="full")
    assert cps.rejections[-1][1] == "encoding"


@pytest.mark.parametrize("kind", KINDS)
def test_a_forged_compact_payload_is_rejected_by_the_state_signature(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0)
    _, cp = JC.create(j, cps, "s1", 3.0)
    k = ("key:s1", cp.ref)
    raw = pickle.loads(j.store.vault[k])
    raw["claims"] = raw["claims"][:1]                                # drop a referenced claim
    blob = pickle.dumps(raw)
    j.store.vault[k] = blob
    cps.index["s1"] = [dataclasses.replace(cp, blob_digest=JC._sha(blob))]
    same(j.store.facts(), "s1", j.read("s1", 4.0).r, cps, expect="full")
    assert cps.rejections[-1][1] == "state_signature"


@pytest.mark.parametrize("kind", KINDS)
def test_erasure_and_key_destruction_with_compact_checkpoints(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    j.checkpoints = cps
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    erase(j, "s1", 2.0, destroy=False)
    status, cp = JC.maintain(j, cps, "s1", 3.0, threshold=1)
    assert status == "CREATED" and JC.load(cp, j.store.facts())[0].erased
    assert "zanzibar" not in repr(pickle.loads(j.store.vault[("key:s1", cp.ref)]))
    j.store.destroy_key("key:s1")
    r = j.read("s1", 4.0).r
    assert open_view(j.store.facts(), "s1", r, cps) is None
    assert same(j.store.facts(), "s1", r, cps, expect="full").erased


# ============================================================================================ 4. dead claims
def naive_prune(facts, f_at_c, c):
    """TEST-ONLY counterexample generator: what a plausible but UNPROVEN semantic pruning would keep. Claims that
    neither win nor conflict in any slot at c are dropped, and events of commitments terminal at c are dropped."""
    f = copy.deepcopy(f_at_c)
    st = JC._finalize(copy.deepcopy(f), facts, c, JC.AMENDED).state
    keep = set()
    for _, s in (st.slots if st else ()):
        keep |= set(s.winning_claim_ids) | set(s.conflict_claim_ids)
        for _, k in s.keys:
            keep |= set(k.winning_claim_ids) | set(k.conflict_claim_ids)
    f.claims = {cid: x for cid, x in f.claims.items() if cid in keep}
    f.claim_refs = {cid: r for cid, r in f.claim_refs.items() if cid in keep}
    heads = CM.project(f.events, c)
    live = [i for i, e in enumerate(f.events) if heads.get(e.commitment_key) is None
            or heads[e.commitment_key].state not in CM.TERMINAL]
    f.events = [f.events[i] for i in live]
    f.event_refs = [f.event_refs[i] for i in live]
    return f


def dead_claim_check(j, c, r):
    """Compact checkpoint at c equals the journal at r; the naive pruner's answer at r is returned for comparison."""
    full, ref, a, b = both_at(j.store, "s1", c)
    facts = j.store.facts()                                         # after both payloads are sealed
    truth = JC.full_replay(facts, "s1", r)
    assert JC.rebuild(facts, "s1", r, ref).view() == truth.view()
    pruned = naive_prune(facts, JC.load(a, facts)[0], c)
    guess = JC._result(JC._advance(pruned, facts, r, JC.AMENDED), facts, r, JC.AMENDED, "naive")
    return guess.view() != truth.view()


def city_value(j, r):
    s = JC.full_replay(j.store.facts(), "s1", r).state
    slot = dict(s.slots).get(CITY.predicate) if s else None
    return slot.value if slot else None


@pytest.mark.parametrize("kind", KINDS)
def test_dead_claim_1_and_4_the_winner_is_retracted_and_the_superseded_claim_returns(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0)                               # supersedes pune
    c = j.read("s1", 3.0).r
    rr = RetractionRecord("r1", "s1", CITY.predicate, ("text", "goa"), "USER", "user", NEVER_TRUE, 4.0, 1, "er")
    j.commit("s1", "r1", CITY.predicate, wr.stamp(CITY), 4.0, act(wr, "s1", lambda at: wr.w.p.retract(rr, at)))
    r = j.read("s1", 5.0).r                                          # "goa was never true": pune is current again
    assert city_value(j, r) == ("text", "pune") and dead_claim_check(j, c, r)


@pytest.mark.parametrize("kind", KINDS)
def test_dead_claim_2_and_7_a_claim_not_yet_valid_at_c_becomes_current(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=10.0)
    c = j.read("s1", 3.0).r
    r = j.read("s1", 11.0).r
    assert city_value(j, r) == ("text", "goa") and dead_claim_check(j, c, r)


@pytest.mark.parametrize("kind", KINDS)
def test_dead_claim_3_a_claim_excluded_by_policy_becomes_eligible_again(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    c0 = j.read("s1", 2.0).r
    reg = wr.w.p.registry
    v1 = reg.get(CITY.predicate)
    reg.publish(dataclasses.replace(v1, policy_version_id=2, breaking=True))
    reg._v[CITY.predicate][3] = dataclasses.replace(v1, policy_version_id=3, revalidate_before=0)
    j.store.publish_at(Publication(CITY.predicate, 2, c0 + 1.0), conditional=False)
    c = c0 + 2.0                                                     # under v2: the claim is excluded
    j.store.publish_at(Publication(CITY.predicate, 3, c0 + 3.0), conditional=False)
    r = c0 + 4.0
    assert city_value(j, c) is None or city_value(j, c) != ("text", "pune")
    assert city_value(j, r) == ("text", "pune") and dead_claim_check(j, c, r)


@pytest.mark.parametrize("kind", KINDS)
def test_dead_claim_5_a_retraction_arrives_for_a_claim_that_would_have_been_pruned(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0)
    c = j.read("s1", 3.0).r
    retract(j, wr, "r1", "pune", 4.0)                               # ends the superseded claim (history changes)
    r = j.read("s1", 5.0).r
    assert dead_claim_check(j, c, r)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("first", [QUARANTINED, INVALIDATED])
def test_dead_claim_6_and_8_a_lifecycle_change_revives_a_claim_believed_dead(kind, first):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cid = next(iter(JC.full_replay(j.store.facts(), "s1", 9e9).claims))
    j.commit("s1", "lc1", CITY.predicate, wr.stamp(CITY), 2.0,
             act(wr, "s1", lambda at: wr.w.p.lifecycle(cid, first, "gen", at)))
    c = j.read("s1", 3.0).r
    j.commit("s1", "lc2", CITY.predicate, wr.stamp(CITY), 4.0,
             act(wr, "s1", lambda at: wr.w.p.lifecycle(cid, ACTIVE, "gen", at)))
    r = j.read("s1", 5.0).r
    assert city_value(j, r) == ("text", "pune") and dead_claim_check(j, c, r)


@pytest.mark.parametrize("kind", KINDS)
def test_dead_claim_9_erasure_is_not_a_counterexample(kind):
    """Recorded honestly: erasure ends everything, so even the naive pruner agrees. Not counted as evidence."""
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0)
    c = j.read("s1", 3.0).r
    erase(j, "s1", 4.0, destroy=False)
    r = j.read("s1", 5.0).r
    assert not dead_claim_check(j, c, r)


@pytest.mark.parametrize("kind", KINDS)
def test_dead_claim_10_a_terminal_commitment_is_reopened(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 1.0, "agent"), 1.5)
    EC.record_commitment_event(j, KEY, ev("x2", "k1", "cancel", 1.6, "user"), 1.7)
    c = j.read("s1", 2.0).r
    EC.record_commitment_event(j, KEY, ev("x3", "k1", "reopen_operator", 2.5, "operator"), 3.0)
    r = j.read("s1", 4.0).r
    assert EC.commitments_at(j.store.facts(), "s1", r)["k1"].state == CM.CONFIRMED
    assert dead_claim_check(j, c, r)
