"""Durable Journal and Rebuild Contract: conformance suite. In memory only; TEST_ONLY_* policies throughout.

Implementations under test:
- A = ``GlobalJournal`` (today's layout: one global order);
- B = ``PartitionedJournal`` (independent subject partitions, a separate policy log, random cross-partition
  delivery, duplicates, crashes, sealed content and key destruction).

Each guarantee has a check function. The deliberate-break tests at the end weaken exactly one rule and show that
the corresponding check FAILS, so the requirement is necessary, not merely documented."""
import dataclasses
import random

import pytest

import memory_core.claimgate as claimgate
import memory_core.commit as commit_mod
from memory_core.context import compile_context
from memory_core.durable_journal import (KINDS, AppendRejected, Crash, Entry, GlobalJournal, PartitionedJournal,
                                         evaluation_order,
                                         Publication, erase_person, export_pipeline, in_force, interleave, load,
                                         protocol_commit, reconstruct)
from memory_core.model import ACTIVE, INVALIDATED, NEVER_TRUE, NO_LONGER_TRUE, PENDING_ERASURE, QUARANTINED
from memory_core.retrieval import MemorySource, get_current_state, search_history
from test_integration import ALICE, ALL, BILL, BOB, CHAT, CITY, EMPLOYER, NOTE, World, _bill
from memory_core.commit import RetractionRecord, SyncRecord

IMPLS = {"A_global": GlobalJournal, "B_partitioned": PartitionedJournal}


# ============================================================================== history generation
def history(seed, n=30, merge=True):
    """A random, contract-valid history through the REAL pipeline: observations, typed commands, external writes,
    syncs, retractions, lifecycle changes, breaking and non-breaking publications, future validity, time jumps,
    and (optionally) a merge s1 -> s2 so that claims cross partitions."""
    rng = random.Random(seed)
    w = World()
    w.p.ingest  # noqa
    claims, merged = [], False
    for _ in range(n):
        x = rng.random()
        if merge and not merged and x < 0.04:
            w.p.fence_ctx.merged_into["s1"] = ("s2", "mg1")
            w.p.fence_ctx.known_subjects.update({"s1", "s2"})
            w.p.fence_ctx.org_of.update({"s1": "o1", "s2": "o1"})
            merged = True
        elif x < 0.45:
            policy = rng.choice([CITY, EMPLOYER, NOTE])
            src = rng.choice(sorted(policy.allowed_sources))
            v = rng.choice(["pune", "delhi", "goa"])
            subj = rng.choice(["s1", "s1", "s2"])
            _, res = w.say(policy, v, source=src, subj=subj, text=f"{src} says {v}",
                           valid_from=rng.choice([None, None, w.t + rng.uniform(-2, 4)]))
            if res.record is not None and res.record.claim_id:
                claims.append(res.record.claim_id)
        elif x < 0.55:
            v = rng.choice(["pune", "delhi"])
            w.say(CITY, v, source="OPERATOR", writer="operator", text=f"set {v}",
                  expected_version=rng.choice([0, 1, 2]))
        elif x < 0.62:
            _bill(w, rng.choice(["gurgaon", "noida"]), rng.choice([0, 1, 2]))
        elif x < 0.69:
            w.t += 0.1
            w.p.sync(SyncRecord(f"sy{w.n}_{rng.random()}", "s1", BILL.predicate, "TEST_ONLY_sync",
                                w.t - rng.uniform(0, 3)), w.t)
        elif x < 0.78:
            w.t += 0.1
            pol = rng.choice([CITY, EMPLOYER, NOTE])
            w.p.retract(RetractionRecord(f"r{w.n}_{rng.random()}", "s1", pol.predicate,
                                         ("text", rng.choice(["pune", "delhi", "goa"])),
                                         rng.choice(sorted(pol.allowed_sources)), "user",
                                         rng.choice([NO_LONGER_TRUE, NEVER_TRUE]), w.t, w.n, "er"), w.t)
        elif x < 0.86 and claims:
            w.t += 0.1
            w.p.lifecycle(rng.choice(claims), rng.choice([QUARANTINED, PENDING_ERASURE, INVALIDATED, ACTIVE]),
                          "gen", w.t)
        elif x < 0.93:
            pol = rng.choice([CITY, NOTE])
            cur = w.p.registry.get(pol.predicate)
            w.t += 0.1
            w.p.publish(dataclasses.replace(cur, policy_version_id=cur.policy_version_id + 1,
                                            breaking=rng.random() < 0.5), w.t)
        else:
            w.t += rng.uniform(0, 5)
    w.t += 0.01
    return w


def journal_for(impl, w, rng=None, **kw):
    j = IMPLS[impl](w.p.registry._v, **kw)
    exported, pubs = export_pipeline(w.p)
    load(j, exported, pubs, interleave(exported, rng) if rng else None)
    return j, exported, pubs


def read_times(w):
    ts = sorted({e.at for e in w.p.store.journal} | {w.t})
    return sorted(set(ts + [t + 0.05 for t in ts]))


SUBJECTS = ("s1", "s2")


# ============================================================================== check functions (the contract)
def check_equivalence(w, j):
    """G7 / Property 1: rebuild from durable facts == the live pipeline (state, retrieval, context)."""
    facts = j.facts()
    for s in SUBJECTS:
        live = w.p.project(s, w.t).state
        rb = reconstruct(facts, s, w.t)
        assert not rb.erased and rb.state == live, s
    rb = reconstruct(facts, "s1", w.t)
    src = MemorySource(rb.journal, rb.policies, policy_history=facts.policy_history)
    live_src = w.p.source()
    for fn in (lambda x: get_current_state(x, "s1", None, w.t, w.t, ALICE),
               lambda x: search_history(x, "s1", None, w.t, ALICE)):
        assert fn(src) == fn(live_src)
    live_ctx = compile_context([get_current_state(live_src, "s1", None, w.t, w.t, ALICE)], CHAT, 4000, "a", {})
    rb_ctx = compile_context([get_current_state(src, "s1", None, w.t, w.t, ALICE)], CHAT, 4000, "a", {})
    assert live_ctx == rb_ctx


def check_history_stability(facts, times, **kw):
    """G2 / G6 / OCC / Property 2 / Property 4: for reads r1 < r2, each slot's version history at r1 is a PREFIX of
    its history at r2. A version number never denotes two different states (no ABA), and never decreases."""
    for s in SUBJECTS:
        prev = None
        for r in times:
            rb = reconstruct(facts, s, r, **kw)
            if rb.erased:
                break
            if prev is not None:
                for slot, hist in prev.trace.items():
                    assert rb.trace.get(slot, ())[:len(hist)] == hist, (s, slot, r)
            for slot, hist in rb.trace.items():
                assert [v for v, _ in hist] == list(range(1, len(hist) + 1))
            prev = rb


def check_stamps(facts):
    """O3 / Property 4: every entry carries the version in force at its commit time; nothing was admitted under a
    policy that was not in force."""
    for part, stored in facts.partitions.items():
        for s in stored:
            e = s.entry
            if e.predicate is not None:
                assert e.policy_version == in_force(facts.publications, e.predicate, e.at), (part, e.kind, e.at)


# ============================================================================== 1. entry kinds and append rules
def test_required_entry_kinds_and_group_rules():
    w = history(1)
    exported, _ = export_pipeline(w.p)
    assert {e.kind for e, _ in exported} <= set(KINDS)
    j = PartitionedJournal(w.p.registry._v)
    with pytest.raises(AppendRejected, match="unknown_kind"):
        j.append([Entry("s1", "memo", "x", 1.0, None, None, 1)])
    with pytest.raises(AppendRejected, match="one_partition"):
        j.append([Entry("s1", "sync", "a", 1.0, None, None, 1), Entry("s2", "sync", "b", 1.0, None, None, 1)])


# ============================================================================== 2/3/12/13. ordering + equivalence
@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("seed", range(25))
def test_property_equivalence_and_history_stability(impl, seed):
    w = history(seed)
    j, _, _ = journal_for(impl, w, random.Random(seed) if impl == "B_partitioned" else None)
    check_equivalence(w, j)
    check_history_stability(j.facts(), read_times(w))
    check_stamps(j.facts())


@pytest.mark.parametrize("seed", range(15))
def test_global_order_is_not_required(seed):
    """Two different cross-partition delivery orders (no global sequence) give identical per-subject truth, equal
    to implementation A's single global order."""
    w = history(seed)
    a, _, _ = journal_for("A_global", w)
    b1, _, _ = journal_for("B_partitioned", w, random.Random(seed))
    b2, _, _ = journal_for("B_partitioned", w, random.Random(seed + 1000))
    for s in SUBJECTS:
        ra = reconstruct(a.facts(), s, w.t)
        assert ra == reconstruct(b1.facts(), s, w.t) == reconstruct(b2.facts(), s, w.t)


def test_adversarial_publication_between_reads_is_stable():
    """The contract's own adversarial example (§B): a breaking publication lands between two reads, with a scheduled
    value and a later write. The read at 16 must stay a prefix of the read at 26."""
    w = World()
    w.say(CITY, "pune", text="I live in pune", observed=1)
    w.say(CITY, "goa", text="moving to goa", valid_from=20, observed=2)
    w.t = 15
    w.p.publish(dataclasses.replace(CITY, policy_version_id=2, breaking=True), 15)
    w.say(CITY, "delhi", text="now in delhi", observed=25)
    w.t = 26
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    check_history_stability(j.facts(), [3, 10, 16, 21, 26])
    assert reconstruct(j.facts(), "s1", 16).state.slot(CITY.predicate).status == "UNKNOWN"


# ============================================================================== 4. cross-subject ownership
def test_merge_landed_claims_live_in_the_target_partition():
    w = World()
    w.p.fence_ctx.merged_into["s1"] = ("s2", "mg1")
    w.p.fence_ctx.known_subjects.update({"s1", "s2"})
    _, res = w.say(CITY, "pune", subj="s1", text="I live in pune")
    j, exported, _ = journal_for("B_partitioned", w, random.Random(0))
    claim = next(e for e, _ in exported if e.kind == "claim")
    assert claim.partition == "s2"                                   # authoritative entry: the survivor
    assert reconstruct(j.facts(), "s2", w.t).state.slot(CITY.predicate).value == ("text", "pune")
    assert not reconstruct(j.facts(), "s1", w.t).state.slots


def test_cross_partition_commit_is_exactly_once_across_retries_and_target_change():
    j = PartitionedJournal({})
    kw = dict(proposal_subject="s1", proposal_id="p1", at=5.0, predicate=None, stamp=None, record="R")
    for step in (1, 2):                                              # crash after intent, then after the claim
        with pytest.raises(Crash):
            protocol_commit(j, target="s2", claim_id="clm_x", crash_after_step=step, **kw)
    # the merge target changed before the final retry: the recorded intent wins
    assert protocol_commit(j, target="s3", claim_id="clm_y", **kw) == "COMMITTED"
    f = j.facts()
    claims = [(p, s.entry.idem) for p, xs in f.partitions.items() for s in xs if s.entry.kind == "claim"]
    assert claims == [("s2", "claim:clm_x")]
    assert [s.entry.kind for s in f.partitions["s1"]] == ["commit_intent", "commit_outcome"]


# ============================================================================== 5/6. idempotency and crash
@pytest.mark.parametrize("impl", IMPLS)
def test_duplicate_delivery_is_idempotent(impl):
    w = history(3)
    j, exported, pubs = journal_for(impl, w)
    before = j.facts()
    load(j, exported, pubs)                                          # the whole history delivered again
    assert j.facts().partitions == before.partitions
    e = next(e for e, s in exported if s is None)
    with pytest.raises(AppendRejected, match="idem_reused"):
        j.append([dataclasses.replace(e, payload=("tampered",))])


@pytest.mark.parametrize("impl", IMPLS)
def test_group_append_is_all_or_nothing_and_retry_commits_once(impl):
    j = IMPLS[impl]({})
    group = [Entry("s1", "sync", f"g{i}", 1.0 + i, None, None, SyncRecord(f"g{i}", "s1", "x", "t", 1.0))
             for i in range(3)]
    with pytest.raises(Crash):
        j.append(group, crash_after=2)
    j.crash()
    assert j.facts().partitions.get("s1", ()) == ()
    assert j.append(group) == "APPENDED" and j.append(group) == "DUPLICATE"
    assert len(j.facts().partitions["s1"]) == 3


def test_crash_after_durable_append_before_ack_is_a_duplicate_on_retry():
    j = PartitionedJournal({})
    e = Entry("s1", "sync", "s", 1.0, None, None, SyncRecord("s", "s1", "x", "t", 1.0))
    j.append([e])                                                    # durable; the acknowledgement is "lost"
    j.crash()
    assert j.append([e]) == "DUPLICATE" and len(j.facts().partitions["s1"]) == 1


# ============================================================================== 7/15. facts only, no gate
def test_rebuild_uses_durable_facts_only_and_never_the_gate(monkeypatch):
    w = history(4)
    j, _, _ = journal_for("B_partitioned", w, random.Random(4))
    facts = j.facts()
    expected = {s: w.p.project(s, w.t).state for s in SUBJECTS}
    del w                                                            # no live store, pipeline or evidence

    def boom(*a, **k):
        raise AssertionError("rebuild must not run the gate or commit")
    monkeypatch.setattr(claimgate, "decide", boom)
    monkeypatch.setattr(commit_mod, "commit", boom)
    for s in SUBJECTS:
        assert reconstruct(facts, s, max(e.entry.at for xs in facts.partitions.values() for e in xs) + 0.01
                           ).state == expected[s]


# ============================================================================== 8. erasure
def test_person_erasure_covers_the_merge_cluster_and_leaves_no_content():
    w = World()
    w.say(CITY, "pune", subj="s2", text="I live in pune")
    w.p.fence_ctx.merged_into["s1"] = ("s2", "mg1")
    w.p.fence_ctx.known_subjects.update({"s1", "s2"})
    w.say(NOTE, "allergic", subj="s1", text="note allergic")          # lands on s2
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    assert erase_person(j, ["s1", "s2"], w.t + 1) == "COMPLETE"
    f = j.facts()
    for s in ("s1", "s2"):
        assert reconstruct(f, s, w.t + 2).erased
    blob = repr(f.partitions) + repr(f.vault)
    assert "pune" not in blob and "allergic" not in blob             # content unrecoverable everywhere
    assert all(s.entry.idem for xs in f.partitions.values() for s in xs)   # structure (no values) remains
    with pytest.raises(AppendRejected, match="partition_erased|key_destroyed"):
        j.append([Entry("s2", "sync", "late", w.t + 3, None, None, SyncRecord("late", "s2", "x", "t", 1.0))])


def test_erasure_is_complete_only_when_every_partition_is_done():
    w = World()
    w.say(CITY, "pune", subj="s1", text="I live in pune")
    w.say(CITY, "goa", subj="s2", text="I live in goa")
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    with pytest.raises(Crash):
        erase_person(j, ["s1", "s2"], w.t + 1, crash_after_partitions=1)
    assert reconstruct(j.facts(), "s1", w.t + 2).erased and not reconstruct(j.facts(), "s2", w.t + 2).erased
    assert erase_person(j, ["s1", "s2"], w.t + 1) == "COMPLETE"      # retry finishes (idempotent)
    assert all(reconstruct(j.facts(), s, w.t + 2).erased for s in ("s1", "s2"))


# ============================================================================== 9/10/11. boundaries, policy, freshness
def test_future_validity_boundary_is_its_own_evaluation_point():
    w = World()
    w.say(CITY, "pune", text="I live in pune", observed=1)
    w.say(CITY, "goa", text="moving to goa", valid_from=10, observed=2)
    w.say(EMPLOYER, "acme", text="I work at acme", observed=20)
    j, _, _ = journal_for("A_global", w)
    h12 = reconstruct(j.facts(), "s1", 12).trace[CITY.predicate]
    h30 = reconstruct(j.facts(), "s1", 30).trace[CITY.predicate]
    assert h12 == h30 and len(h12) == 2                              # activation at t=10 counted once, stably


def test_stale_policy_stamp_is_rejected():
    w = World()
    j = PartitionedJournal(w.p.registry._v)
    j.publish(Publication(CITY.predicate, 1, 0.0))
    j.publish(Publication(CITY.predicate, 2, 5.0))
    with pytest.raises(AppendRejected, match="stale_policy_stamp"):
        j.append([Entry("s1", "sync", "x", 6.0, CITY.predicate, 1, SyncRecord("x", "s1", CITY.predicate, "t", 6.0))])
    with pytest.raises(AppendRejected, match="publication_out_of_order"):
        j.publish(Publication(CITY.predicate, 3, 4.0))               # a later version cannot be dated earlier


@pytest.mark.parametrize("seed", range(15))
def test_freshness_reconstructs_from_recorded_syncs(seed):
    rng = random.Random(seed)
    w = World()
    _bill(w, "gurgaon", 0)
    for i in range(rng.randint(0, 3)):
        w.t += rng.uniform(0, 2)
        w.p.sync(SyncRecord(f"s{i}", "s1", BILL.predicate, "TEST_ONLY_sync", w.t - rng.uniform(0, 1)), w.t)
    w.t += rng.uniform(0, 3)
    j, _, _ = journal_for("B_partitioned", w, rng)
    rb = reconstruct(j.facts(), "s1", w.t).state.slot(BILL.predicate)
    assert rb.freshness_status == w.p.project("s1", w.t).state.slot(BILL.predicate).freshness_status


# ============================================================================== Property 3 / 6
@pytest.mark.parametrize("seed", range(10))
def test_property_caller_independence_over_rebuild(seed):
    w = history(seed)
    j, _, _ = journal_for("B_partitioned", w, random.Random(seed))
    rb = reconstruct(j.facts(), "s1", w.t)
    src = MemorySource(rb.journal, rb.policies, policy_history=j.facts().policy_history)
    assert get_current_state(src, "s1", None, w.t, w.t, ALICE) == get_current_state(src, "s1", None, w.t, w.t, BOB)


@pytest.mark.parametrize("seed", range(10))
def test_property_erasure_soundness(seed):
    w = history(seed)
    j, _, _ = journal_for("B_partitioned", w, random.Random(seed))
    erase_person(j, ["s1", "s2"], w.t + 1)
    f = j.facts()
    for s in SUBJECTS:
        assert reconstruct(f, s, w.t + 2).erased
    assert not any(k[0] in ("key:s1", "key:s2") for k in f.vault)


# ============================================================================== deliberate break tests
def test_break_publication_placement_by_adoption_rewrites_history():
    """Weaken O2/O3 placement (a publication takes effect at the subject's next own write): history stability fails."""
    w = World()
    w.say(CITY, "pune", text="I live in pune", observed=1)
    w.say(CITY, "goa", text="moving to goa", valid_from=20, observed=2)
    w.t = 15
    w.p.publish(dataclasses.replace(CITY, policy_version_id=2, breaking=True), 15)
    w.say(CITY, "delhi", text="now in delhi", observed=25)
    w.t = 26
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    check_history_stability(j.facts(), [16, 26])
    with pytest.raises(AssertionError):
        check_history_stability(j.facts(), [16, 26], placement="adoption")


def test_break_historical_policy_selection_rewinds_versions():
    w = World()
    w.say(CITY, "pune", text="I live in pune", observed=1)
    w.say(CITY, "goa", text="moving to goa", observed=2)
    w.t = 5
    w.p.publish(dataclasses.replace(CITY, policy_version_id=2, breaking=True), 5)
    w.t = 6
    j, _, _ = journal_for("A_global", w)
    check_history_stability(j.facts(), [3, 6])
    with pytest.raises(AssertionError):
        check_history_stability(j.facts(), [3, 6], historical_policy=False)


def test_break_stamp_check_admits_entries_under_a_policy_not_in_force():
    w = World()
    j = PartitionedJournal(w.p.registry._v, stamp_check=False)
    j.publish(Publication(CITY.predicate, 1, 0.0))
    j.publish(Publication(CITY.predicate, 2, 5.0))
    j.append([Entry("s1", "sync", "x", 6.0, CITY.predicate, 1, SyncRecord("x", "s1", CITY.predicate, "t", 6.0))])
    with pytest.raises(AssertionError):
        check_stamps(j.facts())


def test_break_without_idempotency_duplicates_diverge_from_live():
    w = World()
    _, res = w.say(NOTE, "x", text="note x")
    w.t += 0.1
    w.p.lifecycle(res.record.claim_id, QUARANTINED, "t", w.t)
    w.p.lifecycle(res.record.claim_id, ACTIVE, "t", w.t)            # reactivated at the same instant
    j, exported, pubs = journal_for("B_partitioned", w, idempotent=False)
    quarantine = next(i for i, (e, _) in enumerate(exported) if e.kind == "lifecycle")
    load(j, exported, pubs, [quarantine])                            # the quarantine is redelivered
    with pytest.raises(AssertionError):
        check_equivalence(w, j)


@pytest.mark.parametrize("impl", IMPLS)
def test_break_non_atomic_group_leaks_a_partial_write(impl):
    j = IMPLS[impl]({}, atomic=False)
    group = [Entry("s1", "sync", f"g{i}", 1.0 + i, None, None, SyncRecord(f"g{i}", "s1", "x", "t", 1.0))
             for i in range(3)]
    with pytest.raises(Crash):
        j.append(group, crash_after=2)
    j.crash()
    assert len(j.facts().partitions.get("s1", ())) == 2              # partial group durable: G4 violated


def test_break_without_intent_a_retry_after_target_change_duplicates():
    j = PartitionedJournal({})
    kw = dict(proposal_subject="s1", proposal_id="p1", at=5.0, predicate=None, stamp=None, record="R",
              use_intent=False)
    with pytest.raises(Crash):
        protocol_commit(j, target="s2", claim_id="clm_x", crash_after_step=2, **kw)
    protocol_commit(j, target="s3", claim_id="clm_y", **kw)
    claims = [s.entry.idem for xs in j.facts().partitions.values() for s in xs if s.entry.kind == "claim"]
    assert len(claims) == 2                                          # two logical commits: G3 violated


def test_break_erasure_without_merge_cluster_leaves_derived_content():
    w = World()
    w.p.fence_ctx.merged_into["s1"] = ("s2", "mg1")
    w.p.fence_ctx.known_subjects.update({"s1", "s2"})
    w.say(NOTE, "allergic", subj="s1", text="note allergic")          # lands on s2
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    erase_person(j, ["s1"], w.t + 1)                                 # weakened: the cluster is ignored
    assert not reconstruct(j.facts(), "s2", w.t + 2).erased          # the person's content is still reconstructible
    assert "allergic" in repr(j.facts().vault)


def test_break_without_erasure_fence_writes_land_after_erasure():
    w = World()
    w.say(CITY, "pune", subj="s1", text="I live in pune")
    j, _, _ = journal_for("B_partitioned", w, random.Random(0), seal_after_erasure=False)
    erase_person(j, ["s1"], w.t + 1)
    j.append([Entry("s1", "sync", "late", w.t + 3, None, None, SyncRecord("late", "s1", "x", "t", 1.0))])
    assert any(s.entry.idem == "late" for s in j.facts().partitions["s1"])   # the sealed subject accepted a write


def test_break_rebuild_that_reads_live_objects_resurrects_erased_content():
    w = World()
    w.say(CITY, "pune", subj="s1", text="I live in pune")
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    live_claims = dict(w.p.store.claims)                             # a cheat: objects outside the durable facts
    erase_person(j, ["s1"], w.t + 1)
    cheat = [c.content.value for c in live_claims.values()]
    assert cheat == [("text", "pune")]                               # what a non-facts-only rebuild would expose
    assert reconstruct(j.facts(), "s1", w.t + 2).erased              # the contract rebuild cannot



# ============================================================================== closing gaps found by mutation
def check_entries_evaluated_under_their_stamp(facts, r):
    """O3 tie rule / Property 4: in each subject's evaluation order, the publication in force at an entry's point
    is exactly the version the entry was stamped with (admitted under). Nothing is re-read under a later policy."""
    for s in SUBJECTS:
        seen = {}
        for _, _, _, x in evaluation_order(facts, s, r):
            if isinstance(x, Publication):
                seen[x.predicate] = x.version
            elif x.predicate is not None:
                assert seen.get(x.predicate) == x.policy_version, (s, x.kind, x.at)


@pytest.mark.parametrize("seed", range(15))
def test_property_entries_are_evaluated_under_the_policy_they_were_admitted_under(seed):
    w = history(seed)
    j, _, _ = journal_for("B_partitioned", w, random.Random(seed))
    check_entries_evaluated_under_their_stamp(j.facts(), w.t)


def test_entry_and_publication_at_the_same_instant():
    """An entry committed at exactly T was admitted under the version in force BEFORE T (O3), so it must be
    evaluated before the publication at T."""
    w = World()
    j = PartitionedJournal(w.p.registry._v)
    j.publish(Publication(CITY.predicate, 1, 0.0))
    j.append([Entry("s1", "sync", "a", 5.0, CITY.predicate, 1, SyncRecord("a", "s1", CITY.predicate, "t", 5.0))])
    j.publish(Publication(CITY.predicate, 2, 5.0))
    j.append([Entry("s1", "sync", "b", 6.0, CITY.predicate, 2, SyncRecord("b", "s1", CITY.predicate, "t", 6.0))])
    check_entries_evaluated_under_their_stamp(j.facts(), 6.0)


def test_two_boundaries_between_entries_are_separate_evaluation_points():
    """S-2: a read between two scheduled activations must see exactly the first; a later read must agree."""
    w = World()
    w.say(CITY, "pune", text="I live in pune", observed=1)
    w.say(CITY, "goa", text="moving to goa", valid_from=10, observed=2)
    w.say(CITY, "delhi", text="then delhi", valid_from=20, observed=3)
    w.say(EMPLOYER, "acme", text="I work at acme", observed=30)      # the next entry (another predicate)
    w.t = 31
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    check_history_stability(j.facts(), [15, 25, 31])
    assert [sig[1] for _, sig in reconstruct(j.facts(), "s1", 31).trace[CITY.predicate]] == [
        ("text", "pune"), ("text", "goa"), ("text", "delhi")]


def test_commit_time_regression_is_rejected():
    j = PartitionedJournal({})
    j.append([Entry("s1", "sync", "a", 10.0, None, None, SyncRecord("a", "s1", "x", "t", 10.0))])
    with pytest.raises(AppendRejected, match="commit_time_regressed"):
        j.append([Entry("s1", "sync", "b", 5.0, None, None, SyncRecord("b", "s1", "x", "t", 5.0))])


def test_break_without_monotone_commit_time_a_late_write_rewrites_read_history():
    w = World()
    w.say(CITY, "pune", text="I live in pune", observed=1)
    w.say(CITY, "delhi", text="now delhi", observed=10)
    j, exported, pubs = journal_for("B_partitioned", w, monotone_time=False)
    facts_before = j.facts()
    before = reconstruct(facts_before, "s1", 10).trace[CITY.predicate]
    w2 = World()
    w2.say(CITY, "goa", text="was in goa", observed=5)               # a claim dated in the subject's past
    ex2, _ = export_pipeline(w2.p)
    e, seal = ex2[0]
    j.append([dataclasses.replace(e, payload=j.seal("key:s1", "late", seal[2]))])
    after = reconstruct(j.facts(), "s1", 10.5).trace[CITY.predicate]
    assert after[:len(before)] != before                             # the earlier read's history was rewritten


def test_destroyed_key_exposes_nothing_even_without_an_erasure_entry():
    w = World()
    w.say(CITY, "pune", text="I live in pune")
    j, _, _ = journal_for("B_partitioned", w, random.Random(0))
    j.destroy_key("key:s1")
    rb = reconstruct(j.facts(), "s1", w.t + 1)
    assert not rb.state.slots and "pune" not in repr(rb)
