"""Checkpoint consumer interface v1: the Gateway and typed retrieval consume a ProjectionView built from a VALIDATED
checkpoint plus the durable suffix, and return exactly what the authoritative journal path returns. TEST_ONLY.

Every store-dependent test runs on both storage-boundary reference implementations. The reference ("old path") is
the v0.1 code path: ``reconstruct`` at the served position, then retrieval over the journal view.
Contract: ``investigation/checkpoint-consumer-interface-v1.md``."""
import dataclasses
import pickle
import random

import pytest

import memory_core.gateway as gw
from memory_core import episode_commitment as EC
from memory_core import journal_compaction as JC
from memory_core.context import compile_context
from memory_core.claimgate import Proposal
from memory_core.commit import SyncRecord
from memory_core.durable_journal import DurableFacts, Entry, reconstruct
from memory_core.gateway import APPENDED, STATE_CONFLICT
from memory_core.projection_view import memory_source, open_view, scratch
from memory_core.registry import Caller
from memory_core.retrieval import MemorySource, get_commitments, get_current_state, search_history
from test_durable_storage_boundary import make
from test_integration import BILL, CHAT, CITY, NOTE
from test_journal_compaction import KEY, erase, ev, gen, instants, load, retract, sync
from test_memory_gateway_v0 import gateway, say, typed, write
from test_x1_commit_time import put

KINDS = ["explicit", "implied"]
CALLERS = {s: Caller("a1", frozenset({("CUSTOMER", s)})) for s in ("s1", "s2")}


# ============================================================================================ helpers
def old_source(facts, subject, r):
    rb = reconstruct(facts, subject, r)
    return MemorySource(rb.journal, rb.policies, policy_history=facts.policy_history)


def answers(src, subject, r, caller):
    """Everything a consumer derives at r: typed current state (all and per predicate), history, context."""
    out = [get_current_state(src, subject, None, r, r, caller), search_history(src, subject, None, r, caller)]
    out += [get_current_state(src, subject, p, r, r, caller) for p in sorted(src.policies)]
    cc = compile_context(out[:2], CHAT, 4000, caller.principal, {"request_id": "TEST_ONLY"})
    return out, (cc.status, cc.text, dict(cc.manifest))


def check_view(facts, subject, r, cps, caller=None):
    v = open_view(facts, subject, r, cps)
    assert v is not None, cps.rejections
    caller = caller or CALLERS[subject]
    assert answers(memory_source(v), subject, r, caller) == answers(old_source(facts, subject, r), subject, r, caller)
    return v


def gw_old(g, subject, r, caller):
    return answers(old_source(g.journal.store.facts(), subject, r), subject, r, caller)


def gw_now(g, tok, subject, clock):
    """The Gateway's three reads at one served position."""
    a = g.get_current_state(tok, subject, clock)
    src_kind = g.last_read_source
    h = g.search_history(tok, subject, clock, after=a.token)
    c = g.compile_context(tok, subject, CHAT, 4000, clock, after=a.token, request={"request_id": "TEST_ONLY"})
    return a, h, c, src_kind


def check_gateway(g, tok, subject, clock, expect="checkpoint"):
    a, h, c, src_kind = gw_now(g, tok, subject, clock)
    caller = CALLERS[subject]
    ref_a = get_current_state(old_source(g.journal.store.facts(), subject, a.r), subject, None, a.r, a.r, caller)
    ref_h = search_history(old_source(g.journal.store.facts(), subject, h.r), subject, None, h.r, caller)
    src = old_source(g.journal.store.facts(), subject, c.r)
    ref_c = compile_context([get_current_state(src, subject, None, c.r, c.r, caller),
                             search_history(src, subject, None, c.r, caller)], CHAT, 4000, "a1",
                            {"request_id": "TEST_ONLY"})
    assert a.result == ref_a and h.result == ref_h
    assert (c.status, c.memory_data, c.manifest) == (ref_c.status, ref_c.text, dict(ref_c.manifest))
    if expect is not None:
        assert src_kind == expect and g.last_read_source == expect
    return a


def with_checkpoints(g):
    g.checkpoints = JC.CheckpointStore(g.journal.store)
    return g.checkpoints


def checkpoint(g, subject, clock):
    assert JC.create(g.journal, g.checkpoints, subject, clock)[0] == "CREATED"


# ============================================================================================ 1. equivalence
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(6))
def test_typed_retrieval_and_context_over_a_view_equal_the_journal_path(kind, seed):
    """Random histories (claims, typed commands, retractions, lifecycle, syncs, breaking publications, future
    validity, a merge): current state, per-predicate state, history and compiled context from a ProjectionView are
    identical to those from the journal view. The view-backed source has NO journal (any access raises)."""
    st = load(kind, history_for(seed))
    ts = instants(st.facts())
    for subj in ("s1", "s2"):
        for c in (ts[len(ts) // 4], ts[len(ts) // 2], ts[-1]):
            cps = JC.CheckpointStore(st)
            JC.checkpoint_at(st.facts(), cps, subj, c)
            for r in sorted({c, c + 0.05, ts[-1], ts[-1] + 10.0}):
                check_view(st.facts(), subj, r, cps)


def history_for(seed):
    from test_durable_journal_conformance import history
    return history(seed)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(5))
def test_gateway_reads_and_context_with_checkpoints_equal_the_v01_path(kind, seed):
    """A Gateway driven with observations, typed commands, breaking and non-breaking publications and periodic
    checkpoints: every read and every ContextPackage equals the v0.1 journal path at the same served position."""
    rng = random.Random(seed)
    g = gateway(kind)
    with_checkpoints(g)
    toks, t, n, used = {}, 1.0, 0, 0
    for step in range(28):
        subj = rng.choice(["s1", "s1", "s2"])
        t += rng.uniform(0.1, 1.0)
        n += 1
        x = rng.random()
        if x < 0.45 or subj not in toks:
            toks[subj], _ = write(g, n, subj, rng.choice(["pune", "goa", "delhi"]), t)
        elif x < 0.65:
            say(g, n, subj, f"set {n}", t, source="OPERATOR")
            v = next((i.state_version for i in g.get_current_state(toks[subj], subj, t).result.items
                      if i.predicate == CITY.predicate), 0)
            g.command(toks[subj], typed(n, subj, rng.choice(["pune", "goa"]), f"set {n}"),
                      v if rng.random() < 0.7 else v + 5, t + 0.01)
        elif x < 0.75:
            cur = g.registry.get(CITY.predicate)
            g.publish_policy(dataclasses.replace(cur, policy_version_id=cur.policy_version_id + 1,
                                                 breaking=rng.random() < 0.5), t)
        elif x < 0.88:
            checkpoint(g, subj, t)
        else:
            check_gateway(g, toks[subj], subj, t, expect=None)
            used += g.last_read_source == "checkpoint"
    for subj, tok in toks.items():
        checkpoint(g, subj, t + 1.0)
        check_gateway(g, tok, subj, t + 2.0)
        used += 1
    assert used


@pytest.mark.parametrize("kind", KINDS)
def test_the_gateway_consumer_path_never_replays_the_journal_when_a_checkpoint_is_valid(kind, monkeypatch):
    g = gateway(kind)
    with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    write(g, 2, "s1", "goa", 2.0)
    checkpoint(g, "s1", 3.0)

    def boom(*a, **k):
        raise AssertionError("consumer-side journal replay")
    monkeypatch.setattr(gw, "reconstruct", boom)
    monkeypatch.setattr(gw, "rebuild_claims", boom)
    a, h, c, src_kind = gw_now(g, tok, "s1", 4.0)                    # reads, history, context
    assert src_kind == "checkpoint" and [i.value for i in a.result.items] == [("text", "goa")]
    say(g, 5, "s1", "set delhi", 5.0, source="OPERATOR")
    v = a.result.items[0].state_version
    assert g.command(tok, typed(5, "s1", "delhi", "set delhi"), v, 5.0).status == APPENDED   # gate + commit scratch


def test_a_view_backed_source_never_falls_through_to_a_journal():
    wr, j = make("explicit")
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    r = j.read("s1", 3.0).r
    src = memory_source(open_view(j.store.facts(), "s1", r, cps))
    with pytest.raises(ValueError):
        get_current_state(src, "s1", None, r + 1.0, r + 1.0, CALLERS["s1"])      # another position
    with pytest.raises(ValueError):
        get_current_state(src, "s2", None, r, r, CALLERS["s2"])                  # another subject
    with pytest.raises(AssertionError):
        list(src.journal)


# ============================================================================================ 2. OCC
@pytest.mark.parametrize("kind", KINDS)
def test_expected_version_from_a_checkpoint_read_admits_a_current_command(kind):
    g = gateway(kind)
    with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    checkpoint(g, "s1", 2.0)
    a = check_gateway(g, tok, "s1", 3.0)
    say(g, 4, "s1", "set delhi", 4.0, source="OPERATOR")
    assert g.command(tok, typed(4, "s1", "delhi", "set delhi"), a.result.items[0].state_version, 4.0).status == \
        APPENDED
    check_gateway(g, tok, "s1", 5.0)


@pytest.mark.parametrize("kind", KINDS)
def test_a_write_after_the_checkpoint_read_makes_the_command_a_state_conflict(kind):
    g = gateway(kind)
    with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    checkpoint(g, "s1", 2.0)
    v = check_gateway(g, tok, "s1", 3.0).result.items[0].state_version
    write(g, 2, "s1", "goa", 3.5)                                     # lands after the read
    say(g, 4, "s1", "set delhi", 4.0, source="OPERATOR")
    res = g.command(tok, typed(4, "s1", "delhi", "set delhi"), v, 4.0)
    assert res.status == STATE_CONFLICT and res.actual_version == v + 1 and res.attempts == 1
    check_gateway(g, tok, "s1", 5.0)


@pytest.mark.parametrize("kind", KINDS)
def test_a_conflict_landing_in_flight_is_still_decided_by_the_journal_k9_check(kind):
    """The command is prepared from the checkpoint-backed scratch; another write lands between preparation and the
    durable write. Only the journal's in-write check (K9, unchanged) can see it, and it returns STATE_CONFLICT."""
    g = gateway(kind)
    with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    checkpoint(g, "s1", 2.0)
    say(g, 3, "s1", "set delhi", 3.0, source="OPERATOR")
    real_finish = g.journal.finish
    landed = []

    def finish(p, *a, **k):
        if p.cmd == "p3" and not landed:
            landed.append(write(g, 2, "s1", "goa", 3.5)[1].status)
        return real_finish(p, *a, **k)
    g.journal.finish = finish
    res = g.command(tok, typed(3, "s1", "delhi", "set delhi"), 1, 4.0)
    assert landed == [APPENDED] and res.status == STATE_CONFLICT
    assert all(x.entry.idem != "p3" for x in g.journal.store.entries("s1"))
    g.journal.finish = real_finish
    check_gateway(g, tok, "s1", 5.0)


@pytest.mark.parametrize("kind", KINDS)
def test_the_scratch_store_is_a_fresh_copy_every_time(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    v = open_view(j.store.facts(), "s1", j.read("s1", 3.0).r, cps)
    a, sync_a = scratch(v)
    a.claims.clear()                                                   # commit() mutates its store
    b, _ = scratch(v)
    assert b.claims and dict(v.claims) == b.claims and a.journal == [] and b.journal == []


# ============================================================================================ 3. policy
@pytest.mark.parametrize("kind", KINDS)
def test_a_breaking_publication_after_the_checkpoint_is_seen_through_the_suffix(kind):
    g = gateway(kind)
    with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    checkpoint(g, "s1", 2.0)
    cur = g.registry.get(CITY.predicate)
    g.publish_policy(dataclasses.replace(cur, policy_version_id=2, breaking=True), 3.0)
    a = check_gateway(g, tok, "s1", 4.0)
    assert a.result.items[0].status == "UNKNOWN"                       # the old claim needs revalidation


@pytest.mark.parametrize("kind", KINDS)
def test_a_late_publication_falls_back_to_the_journal_when_it_lands_inside_the_checkpoint(kind):
    g = gateway(kind)
    cps = with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    checkpoint(g, "s1", 5.0)
    cur = g.registry.get(NOTE.predicate)
    T = g.publish_policy(dataclasses.replace(cur, policy_version_id=2), 3.0)   # NOTE: never read by s1
    landed_inside = T <= cps.index["s1"][0].covered_at
    check_gateway(g, tok, "s1", 6.0, expect="journal" if landed_inside else "checkpoint")
    if landed_inside:
        assert cps.rejections[-1][1] == "policy_log_changed"


@pytest.mark.parametrize("kind", KINDS)
def test_a_stale_checkpoint_with_a_long_suffix_still_serves_exactly(kind):
    g = gateway(kind)
    with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    checkpoint(g, "s1", 2.0)
    for i in range(8):
        write(g, 10 + i, "s1", ["goa", "delhi"][i % 2], 3.0 + i)
    check_gateway(g, tok, "s1", 20.0)


# ============================================================================================ 4. corruption
def corrupt(g, how):
    cps, store = g.checkpoints, g.journal.store
    cp = cps.index["s1"][0]
    k = ("key:s1", cp.ref)
    if how == "bad_digest":
        store.vault[k] = store.vault[k][:-5] + b"xxxxx"
    elif how == "wrong_partition":
        cps.index["s1"] = [cps.index["s2"][0]]
    elif how == "wrong_contract":
        cps.index["s1"] = [dataclasses.replace(cp, contract="journal-compaction-v0")]
    elif how == "wrong_tail":
        cps.index["s1"] = [dataclasses.replace(cp, tail=("p999", cp.tail[1]))]
    elif how == "policy_position":
        cps.index["s1"] = [dataclasses.replace(cp, policy_position=(cp.policy_position[0] + 1, "x"))]
    elif how == "forged_payload":
        f = pickle.loads(store.vault[k])
        for c in f.claims.values():
            object.__setattr__(c, "content", dataclasses.replace(c.content, value=("text", "atlantis")))
        blob = pickle.dumps(f)
        store.vault[k] = blob
        cps.index["s1"] = [dataclasses.replace(cp, blob_digest=JC._sha(blob))]


REASON = {"bad_digest": "integrity", "wrong_partition": "wrong_partition", "wrong_contract": "contract_version",
          "wrong_tail": "prefix_mismatch", "policy_position": "policy_log_changed",
          "forged_payload": "state_signature"}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("how", sorted(REASON))
def test_every_invalid_checkpoint_falls_back_to_the_journal_and_never_changes_truth(kind, how):
    g = gateway(kind)
    cps = with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    write(g, 2, "s2", "goa", 1.5)
    checkpoint(g, "s1", 2.0)
    checkpoint(g, "s2", 2.0)
    corrupt(g, how)
    a = check_gateway(g, tok, "s1", 3.0, expect="journal")
    assert [i.value for i in a.result.items] == [("text", "pune")]
    assert cps.rejections[-1][1] == REASON[how] and cps.candidates("s1", 9e9) == []
    say(g, 4, "s1", "set delhi", 4.0, source="OPERATOR")               # the write path falls back too
    assert g.command(tok, typed(4, "s1", "delhi", "set delhi"), 1, 4.0).status == APPENDED


# ============================================================================================ 5. erasure
@pytest.mark.parametrize("kind", KINDS)
def test_erasure_always_answers_from_the_journal(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "zanzibarcanary", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    erase(j, "s1", 3.0, destroy=False)                                 # erasure in the suffix
    r = j.read("s1", 4.0).r
    assert open_view(j.store.facts(), "s1", r, cps) is None
    assert reconstruct(j.store.facts(), "s1", r).erased
    j.store.destroy_key("key:s1")                                      # checkpoint made before erasure: unreadable
    JC.create(j, cps, "s1", 5.0)                                       # (an erased fold: no content)
    assert open_view(j.store.facts(), "s1", j.read("s1", 6.0).r, cps) is None
    assert "zanzibar" not in repr(j.store.facts()) + repr(cps.index)


@pytest.mark.parametrize("kind", KINDS)
def test_a_destroyed_key_without_erasure_falls_back(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    j.store.destroy_key("key:s1")
    assert open_view(j.store.facts(), "s1", j.read("s1", 3.0).r, cps) is None
    assert cps.rejections[-1][1] == "unreadable"


# ============================================================================================ 6. retractions, freshness
@pytest.mark.parametrize("kind", KINDS)
def test_retraction_and_freshness_through_a_view(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    assert sync(j, wr, "sy1", 0.5, 1.5)[0] == "APPENDED"
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    retract(j, wr, "r1", "pune", 3.0)
    put(j, wr, "c2", CITY, "goa", 4.0)
    v = check_view(j.store.facts(), "s1", j.read("s1", 5.0).r, cps)
    assert v.last_sync("TEST_ONLY_billing_address") == 0.5


@pytest.mark.parametrize("kind", KINDS)
def test_external_freshness_reaches_the_gate_and_history_through_the_view(kind):
    """A stale-write-forbidden predicate: the gate admits the command only with the recorded sync, and history
    labels its freshness from it. Both come from the view's max sync (no journal entry is synthesized)."""
    g = gateway(kind)
    with_checkpoints(g)
    tok, _ = write(g, 1, "s1", "pune", 1.0)
    sy = SyncRecord("sy1", "s1", BILL.predicate, "TEST_ONLY_sync", 4.9)
    assert g.journal.commit("s1", "sync:sy1", BILL.predicate, 1, 5.0,
                            lambda at: [(Entry("s1", "sync", "sync:sy1", at, BILL.predicate, 1, sy), None)])[0] ==         "APPENDED"
    checkpoint(g, "s1", 5.1)
    say(g, 6, "s1", "billing address: gurgaon", 5.2, source="BILLING_SYSTEM")
    pr = Proposal("p6", "s1", "o1", BILL.predicate, 1, "SET", "system_sync", "BILLING_SYSTEM", ("text", "gurgaon"),
                  (("e6", "billing address: gurgaon"),))
    assert g.command(tok, pr, 0, 5.3).status == APPENDED            # admitted
    checkpoint(g, "s1", 5.35)
    say(g, 7, "s1", "billing address: noida", 5.36, source="BILLING_SYSTEM")
    pr7 = dataclasses.replace(pr, proposal_id="p7", value=("text", "noida"), anchor=(("e7", "billing address: noida"),))
    assert g.command(tok, pr7, 1, 5.37).status == APPENDED          # a populated slot: the sync keeps it writable
    checkpoint(g, "s1", 5.4)
    h = check_gateway(g, tok, "s1", 5.5)
    assert any(i.predicate == BILL.predicate and i.freshness_status == "FRESH" for i in h.result.items)
    hist = g.search_history(tok, "s1", 5.6)
    assert any(i.predicate == BILL.predicate and i.freshness_status == "FRESH" for i in hist.result.items)


@pytest.mark.parametrize("kind", KINDS)
def test_a_foreign_subject_claim_in_a_partition_is_never_served_as_that_subjects_history(kind):
    """Defence in depth: claims live in their own subject's partition, but a stray foreign-subject claim (written
    below the journal API) is filtered exactly as the journal path filters it."""
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    stray = wr.claim(CITY, "atlantis", subj="s2")(2.0)
    for e, x in stray:
        sealed = dataclasses.replace(e, partition="s1", payload=j.store.seal("key:s1", x[1], x[2]))
        assert j.store.append("s1", e.at, [sealed], conditional=False)[0] == "APPENDED"
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 3.0)
    v = check_view(j.store.facts(), "s1", j.read("s1", 4.0).r, cps)
    assert any(c.content.subject_id == "s2" for c in v.claims.values())   # present in the partition ...
    hist = search_history(memory_source(v), "s1", None, v.r, CALLERS["s1"])
    assert all(i.value != ("text", "atlantis") for i in hist.items)   # ... never served for s1


# ============================================================================================ 7. commitments, episodes
@pytest.mark.parametrize("kind", KINDS)
def test_commitment_and_episode_projections_from_a_view(kind):
    _, j = make(kind)
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 1.0, "agent", due=20.0), 1.0)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1"], "v1"), 1.5)
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 2.0)
    EC.record_commitment_event(j, KEY, ev("x2", "k1", "confirm_assent", 0.5, "user"), 3.0)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1", "e2"], "v2"), 3.5)
    for clock in (5.0, 25.0):                                          # before and after expiry
        r = j.read("s1", clock).r
        v = open_view(j.store.facts(), "s1", r, cps)
        a = get_commitments(MemorySource((), {}, commitment_events=v.commitment_events), "s1", r, CALLERS["s1"])
        b = get_commitments(MemorySource((), {}, commitment_events=EC.commitment_events_at(j.store.facts(), "s1", r)),
                            "s1", r, CALLERS["s1"])
        assert a == b
        st = {"e1": "context_suppressed"}
        assert [EC.derive_status(g, st) for _, g in sorted(v.generations.items())] == \
            [e.summary_status for e in EC.episodes_at(j.store.facts(), "s1", r, st)]
        assert v.generations["ep1"].summary == "v2"


# ============================================================================================ 8. scalability model
@pytest.mark.parametrize("kind", KINDS)
def test_one_customers_checkpoint_and_view_never_touch_another_customers_partition(kind):
    wr, j = make(kind)
    for i in range(6):
        put(j, wr, f"a{i}", CITY, "pune", 1.0 + i, subj="s1")
        put(j, wr, f"b{i}", CITY, "goa", 1.5 + i, subj="s2")
    before = list(j.store.entries("s2"))
    cps = JC.CheckpointStore(j.store)
    JC.create(j, cps, "s1", 10.0)
    put(j, wr, "a9", CITY, "delhi", 11.0, subj="s1")
    r = j.read("s1", 12.0).r
    f = j.store.facts()

    class Untouchable(tuple):
        def __getitem__(self, i):
            raise AssertionError("another customer's partition was read")

        def __iter__(self):
            raise AssertionError("another customer's partition was read")

    guarded = DurableFacts({**f.partitions, "s2": Untouchable(f.partitions["s2"])}, f.publications, f.vault,
                           f.policy_history)
    v = open_view(guarded, "s1", r, cps)
    assert v is not None and dict(v.state.slots)[CITY.predicate].value == ("text", "delhi")
    assert list(j.store.entries("s2")) == before
