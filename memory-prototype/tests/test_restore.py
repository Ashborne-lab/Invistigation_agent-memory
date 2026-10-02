"""Lane A8: restore / disaster-recovery protocol (memory-restore-protocol-v1.md).

Scenarios 1-8 from the Lane A brief, plus a randomised property: any restore of FS, PG or both to any point,
followed by the protocol, must leave
  (a) epochs >= the WORM high-water marks (monotonic),
  (b) no erased subject with active memory or retrievable content,
  (c) no WORM-recorded merge silently undone,
  (d) projections equal to a rebuild (invariants clean),
  (e) the protocol idempotent (running it twice changes nothing),
  (f) for a PG-only restore: the recovered ACTIVE memory equal to the live ACTIVE memory.
"""
import os

import pytest

from conftest import ORG, P, World
from memory_core.config import AMENDED, with_
from memory_core.runtime.restore import recover, restore, snapshot
from test_redteam_properties import Run

A = AMENDED


def active_view(m):
    return {c: (x.content.subject_id, x.content.key, x.content.value,
                tuple(sorted(e.evidence_id for e in x.state.support.values())))
            for c, x in m.claims.items() if x.state.status == "active" and x.state.attributed}


def state_view(m):
    return (active_view(m), {c: x.state.status for c, x in m.claims.items()},
            {s: (h.status, h.member_set_version) for s, h in m.heads.items()}, dict(m.epoch),
            dict(m.merged_into), set(m.merges_undone))


def _base():
    w = World(A)
    a = w.say("alice", "I am vegan", 1)
    w.extract(a.subject_id, [P("diet.pattern", "vegan", a, quote="vegan")], 1)
    b = w.say("bob", "my pet is dog", 1)
    w.extract(b.subject_id, [P("note.pet", "dog", b, quote="dog")], 1)
    return w, a.subject_id, b.subject_id


# 1 Firestore only
def test_1_fs_only_restore_loses_later_evidence_and_bounds_claims():
    w, sa, sb = _base()
    snap = snapshot(w.m)
    e = w.say("alice", "my pet is cat", 2)
    w.extract(sa, [P("note.pet", "cat", e, quote="cat")], 2)
    restore(w.m, "fs", snap)
    rep = recover(w.m, "fs", snap, 3)
    assert rep["invariants"] == [] and rep["lost_in_restore"] == 1          # cat's only evidence was lost
    assert not [c for c in w.m.claims.values() if c.content.value[1] == "cat" and c.state.status == "active"]


# 2 PostgreSQL only
def test_2_pg_only_restore_replays_recorded_commits_exactly():
    w, sa, sb = _base()
    snap = snapshot(w.m)
    e = w.say("alice", "my pet is cat", 2)
    w.extract(sa, [P("note.pet", "cat", e, quote="cat")], 2)
    live = active_view(w.m)
    restore(w.m, "pg", snap)
    assert active_view(w.m) != live
    rep = recover(w.m, "pg", snap, 3)
    assert rep["invariants"] == [] and rep["commits_replayed"] == 1
    assert active_view(w.m) == live


# 3 both stores
def test_3_both_restored_to_same_point_then_worm_replay():
    w, sa, sb = _base()
    snap = snapshot(w.m)
    w.m.forget_me(sb, 2)
    restore(w.m, "both", snap)
    assert w.m.heads[sb].status == "active"                                 # the restore resurrected bob
    rep = recover(w.m, "both", snap, 3)
    assert rep["invariants"] == [] and w.m.heads[sb].status == "pending_erasure"
    assert not [c for c in w.m.claims.values() if c.content.subject_id == sb and c.state.status == "active"]


# 4 restore to a point before erasure (each store)
@pytest.mark.parametrize("store", ["fs", "pg", "both"])
def test_4_restore_before_erasure_never_resurrects(store):
    w, sa, sb = _base()
    snap = snapshot(w.m)
    w.m.forget_me(sb, 2)
    hw = w.m.epoch["subject:" + sb]
    restore(w.m, store, snap)
    recover(w.m, store, snap, 3)
    assert w.m.epoch["subject:" + sb] >= hw                                 # monotonic
    assert w.m.heads[sb].status != "active"
    assert w.m.build_context(w.caller, sb, 4) == (None, None)
    late = w.say("bob", "my pet is cat", 5)                                 # same phone, after erasure
    assert late.subject_id != sb                                            # a new relationship, not bob


# 5 restore to a point before merge
@pytest.mark.parametrize("store", ["fs", "pg", "both"])
def test_5_restore_before_merge_keeps_the_merge(store):
    w, sa, sb = _base()
    snap = snapshot(w.m)
    mid = w.m.merge(sb, sa, 2)
    restore(w.m, store, snap)
    rep = recover(w.m, store, snap, 3)
    assert rep["invariants"] == []
    assert w.m.merged_into.get(sb, (None,))[1] == mid and mid not in w.m.merges_undone
    assert w.m.root(sb) == sa


# 6 restore with identity events partially missing (WORM mirror lag)
def test_6a_fs_restore_with_worm_lag_recovers_merge_from_pg_projection():
    w, sa, sb = _base()
    snap = snapshot(w.m)
    n = len(w.m.worm)
    mid = w.m.merge(sb, sa, 2)
    restore(w.m, "fs", snap)
    rep = recover(w.m, "fs", snap, 3, worm_visible=n)                       # the merge never reached WORM
    assert rep["identity_from_pg"] == 1 and w.m.root(sb) == sa


def test_6b_both_restored_with_worm_lag_silently_undoes_the_merge():
    """LA-5: if the WORM append is asynchronous, a both-store restore loses merges in the lag window.
    Nothing can detect it. The protocol therefore requires a synchronous WORM append for identity events."""
    w, sa, sb = _base()
    snap = snapshot(w.m)
    n = len(w.m.worm)
    w.m.merge(sb, sa, 2)
    restore(w.m, "both", snap)
    recover(w.m, "both", snap, 3, worm_visible=n)
    assert w.m.root(sb) == sb                                               # merge silently gone


# 7 restore with outbox lag (PG has not applied an identity event yet)
def test_7_outbox_lag_identity_event_applied_on_recovery():
    w, sa, sb = _base()
    snap = snapshot(w.m)
    mid = w.m.merge(sb, sa, 2)
    w.m.identity_applied = [x for x in w.m.identity_applied if x["mid"] != mid]   # PG had not applied it
    restore(w.m, "pg", snap)
    rep = recover(w.m, "pg", snap, 3)
    assert any(x["mid"] == mid for x in w.m.identity_applied) and rep["invariants"] == []


# 8 restore with search indexes missing
def test_8_missing_search_index_rebuilds_identically():
    w, sa, sb = _base()
    w.m.reindex_all()
    before = {k: (v["subject"], v["key"], v["value"], v["status"]) for k, v in w.m.fts.items()}
    w.m.fts = {}
    snap = snapshot(w.m)
    recover(w.m, "pg", snap, 3)
    after = {k: (v["subject"], v["key"], v["value"], v["status"]) for k, v in w.m.fts.items()}
    assert before == after and before


def test_LA1_replay_must_use_recorded_identity_decision():
    """Evidence ingested before a merge, committed after it, merge later undone. Re-deciding identity during
    replay (current graph) attributes the claim to the absorbed member instead of quarantining it."""
    out = {}
    for mode in ("redecide", "recorded"):
        w = World(with_(A, replay_identity=mode))
        a = w.say("alice", "hi", 1)
        b0 = w.say("bob", "hi", 1)
        sa, sb = a.subject_id, b0.subject_id
        snap = snapshot(w.m)
        e = w.say("bob", "I am vegan", 2)                                   # ingested before the merge
        mid = w.m.merge(sb, sa, 3)
        w.extract(sb, [P("diet.pattern", "vegan", e, quote="vegan")], 4)     # committed under the merge
        w.m.undo_merge(mid, 5)
        live = active_view(w.m)
        restore(w.m, "pg", snap)
        recover(w.m, "pg", snap, 6)
        out[mode] = active_view(w.m) == live
    assert out == {"redecide": False, "recorded": True}


# ---------------------------------------------------------------- randomised property
SEEDS = int(os.environ.get("RESTORE_SEEDS", "40"))


@pytest.mark.parametrize("seed", range(SEEDS))
def test_random_restore_protocol(seed):
    import random
    rnd = random.Random(10_000 + seed)
    run = Run(A, seed)
    steps = rnd.randint(20, 70)
    cut = rnd.randint(0, steps - 1)
    snap = None
    for i in range(steps):
        if i == cut:
            snap = snapshot(run.m)
        run.step()
    m = run.m
    store = rnd.choice(["fs", "pg", "both"])
    live_active = active_view(m)
    erased_refs = {r for rec in m.worm if rec["kind"] == "forget_me" for r in rec["subjects"]}
    hw = {}
    for rec in m.worm:
        if rec["kind"] == "forget_me":
            for ref, ep in rec["epochs"].items():
                hw[ref] = max(hw.get(ref, 0), ep)
    merges_live = {rec["mid"] for rec in m.worm if rec["kind"] == "merge"} - \
                  {rec["mid"] for rec in m.worm if rec["kind"] == "undo"}
    restore(m, store, snap)
    rep = recover(m, store, snap, run.t + 1)
    assert rep["invariants"] == [], rep
    for s, h in m.heads.items():
        if h.kind == "account" or h.org_id not in m.org_keys:
            continue
        ref = m.wref(s)
        if ref in erased_refs:                                              # (b) no resurrection
            assert h.status != "active", "erased subject reactivated"
            assert not [c for c in m.claims.values() if c.content.subject_id == s and c.state.status == "active"]
            assert m.epoch.get("subject:" + s, 0) >= hw[ref], "epoch regressed"   # (a)
    for mid in merges_live:                                                 # (c) no silent undo
        if mid in m.merges:
            assert mid not in m.merges_undone
    if store == "pg":                                                       # (f) exact roll-forward
        assert active_view(m) == live_active
    s1 = state_view(m)                                                      # (e) idempotent protocol
    recover(m, store, snap, run.t + 2)
    assert state_view(m)[0] == s1[0] and state_view(m)[1:] == s1[1:]
