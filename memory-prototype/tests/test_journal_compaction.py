"""Durable Journal compaction and checkpoints v1: conformance. TEST_ONLY_* policies only.

The one property: a checkpoint plus the durable suffix gives EXACTLY what a full replay of the durable facts gives
(state, version trace, policies, claim map, commitment events, episode generations, erased). A checkpoint is
derived acceleration state, never a fact, and is used only after validation.

Store-dependent tests run unchanged on both storage-boundary reference implementations (explicit and implied
frontiers). Closure and concurrency cases go through the unchanged ``TimedJournal``. Property cases replay the
existing random-history generator into the stores at storage level.
Contract: ``investigation/durable-journal-compaction-contract-v1.md``."""
import dataclasses
import pickle
import random

import pytest

from memory_core import commitments as CM
from memory_core import episode_commitment as EC
from memory_core import journal_compaction as JC
from memory_core.commit import RetractionRecord, SyncRecord
from memory_core.commit_time import JOURNAL, Crash, TimedJournal
from memory_core.durable_journal import (PROJECTED_KINDS, DurableFacts, Entry, Publication, evaluation_order,
                                         export_pipeline, reconstruct)
from memory_core.gateway import APPENDED, COMMAND_ID_REUSED, DUPLICATE
from memory_core.model import NO_LONGER_TRUE, QUARANTINED, RETRACTED
from memory_core.storage_boundary import ExplicitFrontierStore, ImpliedFrontierStore
from test_durable_journal_conformance import history
from test_durable_storage_boundary import make, typed
from test_integration import BILL, CITY, NOTE
from test_memory_gateway_adversarial_v0 import restart, shared_store
from test_memory_gateway_v0 import gateway, obs, say, write
from test_x1_commit_time import put

STORES = {"explicit": ExplicitFrontierStore, "implied": ImpliedFrontierStore}
KINDS = list(STORES)
KEY = b"c" * 32


# ============================================================================================ helpers
def load(kind, w):
    """Storage-level replay of a pipeline history into a reference store (as the v1.1 replay tests do)."""
    st = STORES[kind](w.p.registry._v)
    exported, pubs = export_pipeline(w.p)
    for pub in sorted(pubs, key=lambda x: x.at):
        st.publish_at(pub, conditional=False)
    for e, seal in exported:
        if seal is not None:
            subj, ref, content = seal
            e = dataclasses.replace(e, payload=st.seal("key:" + subj, ref, content))
        assert st.append(e.partition, e.at, [e], conditional=False)[0] in ("APPENDED", "DUPLICATE")
    return st


def instants(f):
    """Every entry time, publication time and validity-boundary instant: the checkpoint positions that matter."""
    ts = {s.entry.at for xs in f.partitions.values() for s in xs} | {p.at for p in f.publications}
    for xs in f.partitions.values():
        for s in xs:
            if s.entry.kind == "claim":
                rec = f.vault.get((s.entry.payload.key_id, s.entry.payload.ref))
                if rec is not None:
                    ts |= {b for b in (rec.claim_content.valid_from, rec.claim_content.valid_until) if b is not None}
    return sorted(ts)


def same(facts, subj, r, cps, expect="checkpoint"):
    a, b = JC.rebuild(facts, subj, r, cps), JC.full_replay(facts, subj, r)
    assert a.view() == b.view(), (subj, r)
    if expect is not None:
        assert a.source == expect, (subj, r, cps.rejections)
    return a


def act(wr, subj, fn):
    """A build callback for TimedJournal.commit: run one pipeline operation at the journal-assigned time and return
    the entries it produced for ``subj`` (claims, retractions, syncs, lifecycle)."""
    def build(at):
        fn(at)
        new = [(e, s) for e, s in export_pipeline(wr.w.p)[0] if e.idem not in wr.seen]
        wr.seen |= {e.idem for e, _ in new}
        return [(e, s) for e, s in new if e.partition == subj]
    return build


def retract(j, wr, cmd, value, clock, observed_at=100.0, subj="s1"):
    r = RetractionRecord(cmd, subj, CITY.predicate, ("text", value), "USER", "user", NO_LONGER_TRUE, observed_at,
                         1, "er")
    return j.commit(subj, cmd, CITY.predicate, wr.stamp(CITY), clock, act(wr, subj, lambda at: wr.w.p.retract(r, at)))


def sync(j, wr, cmd, synced_at, clock, subj="s1"):
    s = SyncRecord(cmd, subj, BILL.predicate, "TEST_ONLY_sync", synced_at)
    return j.commit(subj, cmd, BILL.predicate, wr.stamp(BILL), clock, act(wr, subj, lambda at: wr.w.p.sync(s, at)))


def erase(j, subj, clock, destroy=True):
    e = Entry(subj, "erasure", "erasure:" + subj, 0.0, None, None, ("cluster", (subj,)))
    assert j.commit(subj, "erasure:" + subj, None, None, clock,
                    lambda at: [(dataclasses.replace(e, at=at), None)])[0] == "APPENDED"
    if destroy:
        j.store.destroy_key("key:" + subj)


def ev(eid, key, kind, at, actor, subj="s1", due=None):
    return CM.Event(eid, key, kind, at, actor, "e1", due, None, subj, "a1", "t1")


def gen(epid, members, summary, subj="s1"):
    return EC.EpisodeGeneration(epid, subj, "a1", "t1", tuple(members), tuple(members), 1.0, 2.0, summary,
                                "TEST_ONLY_gen_v1")


def city(rb):
    return dict(rb.state.slots)[CITY.predicate]


# ============================================================================================ 1. equivalence
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(8))
def test_property_checkpoint_plus_suffix_equals_full_replay_at_every_position(kind, seed):
    """Random histories (observations, typed commands, retractions, lifecycle, syncs, breaking and non-breaking
    publications, future validity, a merge): a checkpoint at the empty partition and at every entry, publication
    and boundary instant, read at that instant and at later positions, always equals a full replay."""
    w = history(seed)
    st = load(kind, w)
    f = st.facts()
    ts = instants(f)
    for subj in ("s1", "s2"):
        for c in [ts[0] - 1.0] + ts:
            cps = JC.CheckpointStore(st)
            assert JC.checkpoint_at(st.facts(), cps, subj, c)[0] == "CREATED"
            later = [t for t in ts if t >= c]
            for r in sorted({c, c + 0.05, later[len(later) // 2], ts[-1], ts[-1] + 10.0}):
                same(st.facts(), subj, r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_rebuild_reads_the_checkpoint_and_the_suffix_only_never_the_covered_prefix(kind):
    wr, j = make(kind)
    for i in range(12):
        put(j, wr, f"c{i}", CITY, ["pune", "goa", "delhi"][i % 3], float(i + 1))
    cps = JC.CheckpointStore(j.store)
    _, cp = JC.create(j, cps, "s1", 20.0)
    put(j, wr, "late", CITY, "goa", 21.0)
    f = j.store.facts()
    touched = []

    class Guarded(tuple):
        def __getitem__(self, i):
            touched.append(i)
            return tuple.__getitem__(self, i)

        def __iter__(self):
            raise AssertionError("the whole partition was scanned")

    guarded = DurableFacts({**f.partitions, "s1": Guarded(f.partitions["s1"])}, f.publications, f.vault,
                           f.policy_history)
    r = j.read("s1", 30.0).r
    a = JC.rebuild(guarded, "s1", r, cps)
    assert a.source == "checkpoint" and a.view() == JC.full_replay(f, "s1", r).view()
    n = cp.covered_count
    starts = [(i.start if isinstance(i, slice) else i) for i in touched]
    assert min(starts) >= n - 1                                  # only the tail anchor and the suffix


@pytest.mark.parametrize("kind", KINDS)
def test_a_checkpoint_at_the_empty_partition_and_exactly_at_an_entry(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store)
    _, empty = JC.create(j, cps, "s1", 0.5)
    assert empty.covered_count == 0 and empty.tail is None
    _, at = put(j, wr, "c1", CITY, "pune", 1.0)
    st = j.store.facts()
    _, exact = JC.checkpoint_at(st, cps, "s1", at)               # c is exactly the entry's commit time
    assert exact.covered_count == 1
    same(j.store.facts(), "s1", j.read("s1", 2.0).r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_checkpoint_before_and_exactly_at_a_future_validity_boundary(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=6.0)            # a pending boundary carried by the checkpoint
    for c in (j.read("s1", 3.0).r, 6.0):                         # before it, and exactly at it
        cps = JC.CheckpointStore(j.store)
        assert JC.checkpoint_at(j.store.facts(), cps, "s1", max(c, j.store.entries("s1")[-1].entry.at))[0] == \
            "CREATED"
        for r in (6.0, 7.0, j.read("s1", 9.0).r):
            rb = same(j.store.facts(), "s1", r, cps)
        assert city(rb).value == ("text", "goa")


@pytest.mark.parametrize("kind", KINDS)
def test_checkpoint_before_and_after_a_breaking_policy_publication(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    before = JC.CheckpointStore(j.store)
    JC.create(j, before, "s1", 2.0)
    wr.publish(j, CITY, 3.0, breaking=True)
    put(j, wr, "c2", CITY, "goa", 4.0)
    after = JC.CheckpointStore(j.store)
    JC.create(j, after, "s1", 5.0)
    wr.publish(j, CITY, 6.0)
    r = j.read("s1", 7.0).r
    for cps in (before, after):
        rb = same(j.store.facts(), "s1", r, cps)
    assert rb.state.revalidation_required                        # the breaking change is visible through the suffix


@pytest.mark.parametrize("kind", KINDS)
def test_publications_at_exactly_the_checkpoint_instant_are_folded_once(kind):
    """Two versions of one predicate published at the SAME instant c (storage level; the journal's own publish never
    does this, but the boundary does not forbid it): the first excludes the claim, the second resolves it again. The
    suffix must start strictly after c, or the pair is re-applied and versions and trace diverge."""
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    c = j.read("s1", 2.0).r + 1.0
    reg = wr.w.p.registry
    v1 = reg.get(CITY.predicate)
    reg.publish(dataclasses.replace(v1, policy_version_id=2, breaking=True))
    reg._v[CITY.predicate][3] = dataclasses.replace(v1, policy_version_id=3, revalidate_before=0)
    j.store.publish_at(Publication(CITY.predicate, 2, c), conditional=False)
    j.store.publish_at(Publication(CITY.predicate, 3, c), conditional=False)
    cps = JC.CheckpointStore(j.store)
    assert JC.checkpoint_at(j.store.facts(), cps, "s1", c)[0] == "CREATED"
    rb = same(j.store.facts(), "s1", c + 5.0, cps)
    assert [v for v, _ in rb.trace[CITY.predicate]] == [1, 2, 3]


@pytest.mark.parametrize("kind", KINDS)
def test_checkpoint_before_and_after_a_retraction_including_la9_on_a_claim_committed_after_c(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cp_before = JC.CheckpointStore(j.store)
    JC.create(j, cp_before, "s1", 2.0)
    assert retract(j, wr, "r1", "pune", 3.0)[0] == "APPENDED"
    cp_after = JC.CheckpointStore(j.store)
    JC.create(j, cp_after, "s1", 4.0)                            # carries the retraction (LA-9 state)
    put(j, wr, "c2", CITY, "pune", 5.0, say={"source": "USER"})  # committed after c, observed before the retraction
    r = j.read("s1", 6.0).r
    for cps in (cp_before, cp_after):
        rb = same(j.store.facts(), "s1", r, cps)
    punes = [c for c in rb.claims.values() if c.content.value == ("text", "pune")]
    assert len(punes) == 2 and all(c.state.status == RETRACTED for c in punes)   # incl. the one committed after c


@pytest.mark.parametrize("kind", KINDS)
def test_freshness_and_claims_version_carry_over_the_checkpoint(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    assert sync(j, wr, "sy1", 0.5, 2.0)[0] == "APPENDED"
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 3.0)
    put(j, wr, "c2", CITY, "goa", 4.0)
    rb = same(j.store.facts(), "s1", j.read("s1", 5.0).r, cps)
    assert rb.state.claims_version == 2


@pytest.mark.parametrize("kind", KINDS)
def test_lifecycle_and_erasure_state_through_the_checkpoint(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cid = next(iter(JC.full_replay(j.store.facts(), "s1", 9e9).claims))
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    j.commit("s1", "lc1", CITY.predicate, wr.stamp(CITY), 3.0,
             act(wr, "s1", lambda at: wr.w.p.lifecycle(cid, QUARANTINED, "gen", at)))
    assert same(j.store.facts(), "s1", j.read("s1", 4.0).r, cps).claims[cid].state.status == QUARANTINED
    erase(j, "s1", 5.0, destroy=False)
    rb = same(j.store.facts(), "s1", j.read("s1", 6.0).r, cps)
    assert rb.erased


@pytest.mark.parametrize("kind", KINDS)
def test_max_sync_freshness_survives_a_lower_sync_after_the_checkpoint(kind):
    wr, j = make(kind)
    assert sync(j, wr, "sy0", 0.95, 1.0)[0] == "APPENDED"           # a stale-write-forbidden predicate needs it
    assert j.commit("s1", "b1", BILL.predicate, wr.stamp(BILL), 1.05,
                    wr.claim(BILL, "gurgaon", source="BILLING_SYSTEM", writer="system_sync", expected_version=0),
                    expected_version=0)[0] == "APPENDED"
    assert sync(j, wr, "sy1", 3.9, 4.0)[0] == "APPENDED"           # fresh
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 4.1)
    assert sync(j, wr, "sy2", 0.5, 4.2)[0] == "APPENDED"           # committed later, an OLDER sync time
    rb = same(j.store.facts(), "s1", j.read("s1", 4.3).r, cps)
    assert dict(rb.state.slots)[BILL.predicate].usage == "OPERATIONAL"     # max(3.9, 0.5), not the last one


@pytest.mark.parametrize("kind", KINDS)
def test_a_checkpoint_newer_than_the_read_position_is_never_used(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    r1 = j.read("s1", 1.5).r
    put(j, wr, "c2", CITY, "goa", 2.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 3.0)
    rb = same(j.store.facts(), "s1", r1, cps, expect="full")
    assert city(rb).value == ("text", "pune")


@pytest.mark.parametrize("kind", KINDS)
def test_no_checkpoint_can_be_created_once_the_subject_key_is_destroyed(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cid = next(iter(JC.full_replay(j.store.facts(), "s1", 9e9).claims))
    j.commit("s1", "lc1", CITY.predicate, wr.stamp(CITY), 2.0,
             act(wr, "s1", lambda at: wr.w.p.lifecycle(cid, QUARANTINED, "gen", at)))
    j.store.destroy_key("key:s1")                                   # unreadable claim, readable lifecycle entry
    assert JC.create(j, JC.CheckpointStore(j.store), "s1", 3.0) == ("REJECTED", "key_destroyed")


# ============================================================================================ 2. crash and recovery
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("crash", ["before_seal", "after_seal", "torn"])
def test_a_crash_during_checkpoint_creation_never_changes_a_result(kind, crash):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    with pytest.raises(JC.Crash):
        JC.create(j, cps, "s1", 2.0, crash=crash)
    put(j, wr, "c2", CITY, "goa", 3.0)
    same(j.store.facts(), "s1", j.read("s1", 4.0).r, cps, expect="full")
    if crash == "torn":
        assert cps.rejections and cps.rejections[0][1] == "integrity"
        assert cps.candidates("s1", 9e9) == []                    # marked unusable


@pytest.mark.parametrize("kind", KINDS)
def test_crash_after_checkpoint_before_the_suffix_is_durable_then_retry(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    pr = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 3.0, wr.claim(CITY, "goa"))[1]
    with pytest.raises(Crash):
        j.store.append("s1", pr.at, [e for e, _ in pr.entries], crash_after=0)     # nothing of the group is durable
    j.crash()
    same(j.store.facts(), "s1", j.read("s1", 4.0).r, cps)
    assert put(j, wr, "c2b", CITY, "goa", 5.0)[0] == "APPENDED"
    same(j.store.facts(), "s1", j.read("s1", 6.0).r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_crash_after_a_durable_suffix_append_restart_and_duplicate_retry(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    with pytest.raises(Crash):
        put(j, wr, "c2", CITY, "goa", 3.0, crash_after_durable=True)
    j.crash()
    j2 = TimedJournal(j.store.policy_history, JOURNAL, storage=j.store)            # a new process, same store
    at = j2.store.entries("s1")[-1].entry.at
    assert put(j2, wr, "c2", CITY, "goa", 4.0) == ("DUPLICATE", at)
    same(j2.store.facts(), "s1", j2.read("s1", 5.0).r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_a_corrupted_checkpoint_is_rejected_and_rebuilt_from_the_facts(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    _, cp = JC.create(j, cps, "s1", 2.0)
    k = ("key:s1", cp.ref)
    j.store.vault[k] = j.store.vault[k][:-7] + b"garbage"         # bytes corrupted in storage
    rb = same(j.store.facts(), "s1", j.read("s1", 3.0).r, cps, expect="full")
    assert city(rb).value == ("text", "pune") and cps.rejections[0][1] == "integrity"


@pytest.mark.parametrize("kind", KINDS)
def test_a_forged_payload_with_a_matching_digest_is_rejected_by_the_state_signature(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    _, cp = JC.create(j, cps, "s1", 2.0)
    k = ("key:s1", cp.ref)
    f = pickle.loads(j.store.vault[k])
    for c in f.claims.values():                                    # a value that WOULD change the answer
        object.__setattr__(c, "content", dataclasses.replace(c.content, value=("text", "atlantis")))
    blob = pickle.dumps(f)
    j.store.vault[k] = blob
    cps.index["s1"] = [dataclasses.replace(cp, blob_digest=JC._sha(blob))]
    rb = same(j.store.facts(), "s1", j.read("s1", 3.0).r, cps, expect="full")
    assert city(rb).value == ("text", "pune") and cps.rejections[0][1] == "state_signature"


@pytest.mark.parametrize("kind", KINDS)
def test_an_incompatible_contract_version_is_never_used(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    _, cp = JC.create(j, cps, "s1", 2.0)
    cps.index["s1"] = [dataclasses.replace(cp, contract="journal-compaction-v0")]
    same(j.store.facts(), "s1", j.read("s1", 3.0).r, cps, expect="full")
    assert cps.rejections[0][1] == "contract_version"


@pytest.mark.parametrize("kind", KINDS)
def test_a_stale_checkpoint_still_equals_and_one_from_another_history_is_rejected(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    for i in range(6):                                             # a long suffix: the checkpoint is old
        put(j, wr, f"c{i + 2}", CITY, ["goa", "delhi"][i % 2], 3.0 + i)
    same(j.store.facts(), "s1", j.read("s1", 20.0).r, cps)
    wr2, other = make(kind)                                        # a different (e.g. rolled-back) history
    put(other, wr2, "x1", CITY, "goa", 1.0)
    put(other, wr2, "x2", CITY, "delhi", 1.5)
    moved = JC.CheckpointStore(other.store)
    _, cp = JC.create(j, JC.CheckpointStore(j.store), "s1", 21.0)
    other.store.seal("key:s1", cp.ref, j.store.vault[("key:s1", cp.ref)])
    moved.index["s1"] = [cp]
    same(other.store.facts(), "s1", other.read("s1", 22.0).r, moved, expect="full")
    assert moved.rejections[0][1] == "prefix_missing"
    for i in range(cp.covered_count + 2):                          # now as long as the covered prefix, but different
        put(other, wr2, f"y{i}", CITY, "delhi", 23.0 + i)
    other.store.seal("key:s1", cp.ref, j.store.vault[("key:s1", cp.ref)])
    moved.unusable.clear()
    moved.index["s1"] = [cp]
    same(other.store.facts(), "s1", other.read("s1", 60.0).r, moved, expect="full")
    assert moved.rejections[-1][1] == "prefix_mismatch"


# ============================================================================================ 3. concurrency
@pytest.mark.parametrize("kind", KINDS)
def test_an_append_landing_during_checkpoint_creation_is_only_in_the_suffix(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    token = j.begin_read("s1", 2.0)                                # closure happens first
    assert put(j, wr, "c2", CITY, "goa", 2.0)[0] == "APPENDED"     # lands while the checkpoint is being made
    sv = j.end_read(token)
    _, cp = JC.create(j, JC.CheckpointStore(j.store), "s1", 2.0, served=sv)
    assert all(s.entry.at > cp.covered_at for s in j.store.entries("s1")[cp.covered_count:])
    cps = JC.CheckpointStore(j.store)
    cps.index["s1"] = [cp]
    cps.storage.seal("key:s1", cp.ref, j.store.vault[("key:s1", cp.ref)])
    rb = same(j.store.facts(), "s1", j.read("s1", 3.0).r, cps)
    assert city(rb).value == ("text", "goa")


@pytest.mark.parametrize("kind", KINDS)
def test_multiple_writers_and_independent_per_subject_checkpoints(kind):
    wr, j = make(kind)
    rng = random.Random(7)
    cps = JC.CheckpointStore(j.store)
    for i in range(16):
        subj = rng.choice(["s1", "s2"])
        put(j, wr, f"m{i}", CITY, rng.choice(["pune", "goa"]), float(i + 1), subj=subj)
        if i in (5, 11):
            before = {s: len(j.store.entries(s)) for s in ("s1", "s2")}
            JC.create(j, cps, "s1", float(i + 1))                  # one hot customer, checkpointed alone
            assert {s: len(j.store.entries(s)) for s in ("s1", "s2")} == before   # no entry anywhere
    for s in ("s1", "s2"):
        same(j.store.facts(), s, j.read(s, 30.0).r, cps, expect="checkpoint" if s == "s1" else "full")


@pytest.mark.parametrize("kind", KINDS)
def test_an_entry_landing_at_or_before_c_after_creation_invalidates_the_checkpoint(kind):
    """Defence in depth: a checkpoint made at a position storage did NOT close (here c = the last entry's time, and
    a storage-level write lands at that same instant afterwards) is detected and never trusted."""
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    pr = j.prepare("s1", "c2", CITY.predicate, wr.stamp(CITY), 2.0, wr.claim(CITY, "goa"))[1]
    cps = JC.CheckpointStore(j.store)
    c = j.store.entries("s1")[-1].entry.at
    JC.checkpoint_at(j.store.facts(), cps, "s1", c)
    sealed = [dataclasses.replace(e, at=c, payload=j.store.seal("key:" + x[0], x[1], x[2]) if x else e.payload)
              for e, x in pr.entries]
    assert j.store.append("s1", c, sealed, conditional=False)[0] == "APPENDED"
    same(j.store.facts(), "s1", c + 1.0, cps, expect=None)
    assert cps.rejections and cps.rejections[0][1] == "suffix_not_after_c"


@pytest.mark.parametrize("kind", KINDS)
def test_a_read_in_flight_across_checkpoint_creation_is_served_unchanged(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    token = j.begin_read("s1", 2.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    sv = j.end_read(token)
    assert sv.trace == reconstruct(j.store.facts(), "s1", sv.r).trace
    same(j.store.facts(), "s1", sv.r, cps, expect=None)            # a checkpoint after sv.r cannot serve it
    same(j.store.facts(), "s1", j.read("s1", 3.0).r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_a_typed_command_right_after_a_checkpoint_uses_its_version_as_the_occ_base(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    v = city(JC.rebuild(j.store.facts(), "s1", j.read("s1", 2.5).r, cps)).state_version
    assert j.commit("s1", "t1", CITY.predicate, wr.stamp(CITY), 3.0, typed(wr, "goa"), expected_version=v)[0] ==         "APPENDED"
    assert j.commit("s1", "t2", CITY.predicate, wr.stamp(CITY), 4.0, typed(wr, "delhi"), expected_version=v)[0] ==         "STATE_CONFLICT"                                            # the stale base is refused at write time
    same(j.store.facts(), "s1", j.read("s1", 5.0).r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_a_publication_after_the_checkpoint_keeps_it_exact(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    _, cp = JC.create(j, cps, "s1", 2.0)
    assert wr.publish(j, CITY, 1.5) > cp.covered_at               # a closed predicate log: T lands after c
    put(j, wr, "c2", CITY, "goa", 3.0)
    same(j.store.facts(), "s1", j.read("s1", 4.0).r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_a_late_publication_for_an_unclosed_predicate_invalidates_the_checkpoint(kind):
    """The explicit store lets a publication of a predicate this partition never read land at T <= c. The policy-log
    position detects it and the read falls back to a full replay; a later claim of that predicate is then evaluated
    under the version in force (it would not be under the stale checkpoint). The implied store's global time
    service places the publication after c, so the checkpoint stays valid there."""
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    _, cp = JC.create(j, cps, "s1", 5.0)
    cur = wr.w.p.registry.get(NOTE.predicate)
    new = dataclasses.replace(cur, policy_version_id=2, current_state_eligible=False)
    T = j.publish(NOTE.predicate, 2, 3.0)
    wr.w.p.publish(new, T)
    put(j, wr, "n1", NOTE, "allergic", 6.0)
    rb = JC.rebuild(j.store.facts(), "s1", j.read("s1", 7.0).r, cps)
    assert rb.view() == JC.full_replay(j.store.facts(), "s1", rb.r).view()
    if T <= cp.covered_at:
        assert rb.source == "full" and cps.rejections[0][1] == "policy_log_changed"
    else:
        assert rb.source == "checkpoint"


# ============================================================================================ 4. idempotency
@pytest.mark.parametrize("kind", KINDS)
def test_duplicates_and_command_id_reuse_are_unchanged_by_a_checkpoint_and_a_restart(kind):
    factory = shared_store(kind)
    g = gateway(kind, factory)
    tok, first = write(g, 1, "s1", "pune", 1.0)                   # p1 on s1
    assert first.status == APPENDED
    dup = g.propose_observation(tok, obs(1, "s1", "pune", "I live in pune"), 2.0)
    assert dup.status == DUPLICATE
    cps = JC.CheckpointStore(g.journal.store)
    JC.create(g.journal, cps, "s1", 3.0)
    g2 = restart(g, factory)
    again = g2.propose_observation(tok, obs(1, "s1", "pune", "I live in pune"), 4.0)
    assert (again.status, again.original, again.at) == (DUPLICATE, dup.original, first.at)
    say(g2, 9, "s1", "I live in goa", 4.5)
    reused = dataclasses.replace(obs(1, "s1", "goa", "I live in goa"), anchor=(("e9", "I live in goa"),))
    assert g2.propose_observation(tok, reused, 5.0).status == COMMAND_ID_REUSED
    tok2 = say(g2, 11, "s2", "I live in delhi", 6.0)
    p1_on_s2 = dataclasses.replace(obs(11, "s2", "delhi", "I live in delhi"), proposal_id="p1")
    assert g2.propose_observation(tok2, p1_on_s2, 6.0).status == APPENDED   # the same id on another subject
    same(g2.journal.store.facts(), "s1", g2.journal.read("s1", 7.0).r, cps)


@pytest.mark.parametrize("kind", KINDS)
def test_a_journal_duplicate_after_a_checkpoint_returns_the_original_time(kind):
    wr, j = make(kind)
    _, at = put(j, wr, "c1", CITY, "pune", 1.0)
    JC.create(j, JC.CheckpointStore(j.store), "s1", 2.0)
    assert put(j, wr, "c1", CITY, "pune", 3.0) == ("DUPLICATE", at)


# ============================================================================================ 5. new record types
@pytest.mark.parametrize("kind", KINDS)
def test_new_record_types_are_never_claim_evaluation_points(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 1.0, "agent"), 2.0)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1"], "talk"), 3.0)
    f = j.store.facts()
    kinds = {x.kind for _, _, _, x in evaluation_order(f, "s1", 9e9) if hasattr(x, "kind")}
    assert kinds <= set(PROJECTED_KINDS)
    assert not {EC.COMMITMENT_EVENT, EC.EPISODE_SUMMARY} & set(PROJECTED_KINDS)
    assert not {EC.COMMITMENT_EVENT, EC.EPISODE_SUMMARY} & {x.kind for _, _, _, x in JC._points(f, "s1", JC.NEG,
                                                                                                  9e9, 0)
                                                           if hasattr(x, "kind")}


@pytest.mark.parametrize("kind", KINDS)
def test_commitment_projection_through_a_checkpoint(kind):
    j = TimedJournal({}, JOURNAL, storage=STORES[kind]({}))
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 1.0, "agent", due=20.0), 1.0)
    EC.record_commitment_event(j, KEY, ev("x2", "k2", "create", 1.5, "agent"), 1.5)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    EC.record_commitment_event(j, KEY, ev("x3", "k1", "confirm_assent", 0.5, "user"), 3.0)   # earlier business time
    EC.record_commitment_event(j, KEY, ev("x4", "k2", "cancel", 4.0, "user"), 4.0)
    for clock in (5.0, 25.0):                                       # before and after the due time
        r = j.read("s1", clock).r
        rb = same(j.store.facts(), "s1", r, cps)
        assert {k: h.state for k, h in CM.project(rb.commitment_events, r).items()} == \
            {k: h.state for k, h in EC.commitments_at(j.store.facts(), "s1", r).items()}


@pytest.mark.parametrize("kind", KINDS)
def test_episode_generations_through_a_checkpoint_newest_wins_and_duplicates_stay_duplicates(kind):
    j = TimedJournal({}, JOURNAL, storage=STORES[kind]({}))
    g1 = gen("ep1", ["e1"], "v1 text")
    _, at1 = EC.record_episode_generation(j, KEY, g1, 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    assert EC.record_episode_generation(j, KEY, dataclasses.replace(g1, summary="regenerated"), 3.0) == \
        ("DUPLICATE", at1)                                          # never regenerated
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1", "e2"], "v2 text"), 4.0)
    rb = same(j.store.facts(), "s1", j.read("s1", 5.0).r, cps)
    assert rb.generations["ep1"].summary == "v2 text"
    st = {"e1": "context_suppressed"}
    assert [EC.derive_status(g, st) for g in rb.generations.values()] == \
        [e.summary_status for e in EC.episodes_at(j.store.facts(), "s1", rb.r, st)]


# ============================================================================================ 6. erasure
@pytest.mark.parametrize("kind", KINDS)
def test_a_checkpoint_made_before_erasure_becomes_unreadable_and_nothing_is_recoverable(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1"], "zanzibarcanary recap"), 1.5)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    erase(j, "s1", 3.0)
    rb = same(j.store.facts(), "s1", j.read("s1", 4.0).r, cps, expect="full")
    assert rb.erased and cps.rejections[0][1] == "unreadable"
    assert "zanzibar" not in repr(j.store.facts()) + repr(cps.index) + repr(cps.rejections)


@pytest.mark.parametrize("kind", KINDS)
def test_a_checkpoint_made_after_erasure_holds_no_content(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    erase(j, "s1", 2.0, destroy=False)                              # erasure in progress: key not yet destroyed
    cps = JC.CheckpointStore(j.store)
    _, cp = JC.create(j, cps, "s1", 3.0)
    assert "zanzibar" not in repr(pickle.loads(j.store.vault[("key:s1", cp.ref)]))
    assert same(j.store.facts(), "s1", j.read("s1", 4.0).r, cps).erased


@pytest.mark.parametrize("kind", KINDS)
def test_a_destroyed_key_without_an_erasure_entry_disables_the_checkpoint(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    j.store.destroy_key("key:s1")
    same(j.store.facts(), "s1", j.read("s1", 3.0).r, cps, expect="full")
    assert "zanzibar" not in repr(j.store.facts())


# ============================================================================================ 7. not a source of truth
@pytest.mark.parametrize("kind", KINDS)
def test_checkpoints_are_never_facts_and_removing_them_changes_nothing(kind):
    wr, j = make(kind)
    for i in range(5):
        put(j, wr, f"c{i}", CITY, ["pune", "goa"][i % 2], float(i + 1))
    plain = j.store.facts()
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 3.0)
    JC.create(j, cps, "s1", 6.0)
    f = j.store.facts()
    assert f.partitions == plain.partitions                        # no entry, no commit time, no idem
    r = j.read("s1", 7.0).r
    assert reconstruct(f, "s1", r) == reconstruct(plain, "s1", r)  # the rebuild never reads them
    with_cp = JC.rebuild(f, "s1", r, cps)
    for cp in list(cps.index["s1"]):
        cps.discard(cp, "dropped")
    assert JC.rebuild(j.store.facts(), "s1", r, cps).view() == with_cp.view()


@pytest.mark.parametrize("kind", KINDS)
def test_compaction_retires_superseded_checkpoints_and_deletes_no_fact(kind):
    wr, j = make(kind)
    cps = JC.CheckpointStore(j.store)
    for i in range(4):
        put(j, wr, f"c{i}", CITY, ["pune", "goa"][i % 2], float(i + 1))
        JC.create(j, cps, "s1", float(i + 1))
    before = j.store.facts().partitions
    assert cps.compact("s1") == 3
    assert j.store.facts().partitions == before
    assert len(cps.candidates("s1", 9e9)) == 1
    same(j.store.facts(), "s1", j.read("s1", 9.0).r, cps)


# ============================================================================================ 8. determinism
@pytest.mark.parametrize("kind", KINDS)
def test_the_same_facts_and_checkpoint_always_give_the_same_result_and_signature(kind):
    w = history(3)
    st = load(kind, w)
    c = instants(st.facts())[len(instants(st.facts())) // 2]
    a, b = JC.CheckpointStore(st), JC.CheckpointStore(st)
    _, cpa = JC.checkpoint_at(st.facts(), a, "s1", c)
    _, cpb = JC.checkpoint_at(st.facts(), b, "s1", c)
    assert cpa.state_signature == cpb.state_signature
    r = instants(st.facts())[-1] + 1.0
    assert JC.rebuild(st.facts(), "s1", r, a).view() == JC.rebuild(st.facts(), "s1", r, a).view() == \
        JC.rebuild(st.facts(), "s1", r, b).view()


def test_a_fold_that_would_consult_read_time_policy_content_is_never_checkpointed():
    """Fail-safe: a claim whose predicate has no publication in force would be evaluated under whatever policy is
    visible at READ time, which differs between creation and use. No checkpoint is created for it."""
    wr, j = make("explicit")
    put(j, wr, "c1", CITY, "pune", 1.0)
    f = j.store.facts()
    bare = DurableFacts(f.partitions, (), f.vault, f.policy_history)  # the same claim, no publication at all
    assert JC.checkpoint_at(bare, JC.CheckpointStore(j.store), "s1", 2.0)[0] == "UNSUPPORTED"
