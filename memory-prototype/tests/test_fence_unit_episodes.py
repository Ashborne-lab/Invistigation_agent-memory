"""Direct unit tests of the pure E3 fence, one per branch; episodes; the store-wide physical-deletion check."""
from conftest import P, World
from memory_core import fence as F
from memory_core.config import DEFAULT, with_


def stamp(eid="e1", subj="B", epochs=None, merges=(), status="active", exists=True, t=1.0, transient=False):
    epochs = epochs or {"org": 0, "subject": 0, "session": 0}
    return F.Stamp(eid, exists, status, epochs, {"org": "org:o", "subject": "subject:" + subj, "session": "session:x"},
                   tuple(merges), subj, t, transient_unavailable=transient)


def ctx(**kw):
    base = dict(epoch_log={}, merged_into={}, merges_undone=set(), subject_erased_at={}, org_erased_at={},
                org_of={"A": "o", "B": "o", "C": "o"}, known_subjects={"A", "B", "C"})
    base.update(kw)
    return F.Context(**base)


def test_a_dead_or_missing_evidence_rejects():
    for st in ("erased", "pending_erasure", "invalidated", "context_suppressed"):
        assert F.fence([stamp(status=st)], ctx()).action == F.REJECT
    assert F.fence([stamp(exists=False)], ctx()).reason.startswith("a:evidence_missing")


def test_b_erasure_advance_rejects_merge_advance_retargets():
    log = {"subject:B": [(1, "erasure", 2.0)]}
    assert F.fence([stamp()], ctx(epoch_log=log)).reason == "b:subject_advanced_by_erasure"
    log = {"subject:B": [(1, "merge", 2.0)]}
    r = F.fence([stamp()], ctx(epoch_log=log, merged_into={"B": ("A", "m1")}))
    assert (r.action, r.target_subject, r.merges_recorded) == (F.COMMIT, "A", ("m1",))


def test_b_session_and_org_advances_reject():
    assert F.fence([stamp()], ctx(epoch_log={"session:x": [(1, "erasure", 2.0)]})).action == F.REJECT
    assert F.fence([stamp()], ctx(epoch_log={"org:o": [(1, "erasure", 2.0)]})).action == F.REJECT


def test_c_erased_survivor_on_path_rejects():
    r = F.fence([stamp(t=1.0)], ctx(merged_into={"B": ("A", "m1")}, subject_erased_at={"A": 3.0}))
    assert r.reason == "c:subject_on_path_erased:A"


def test_c_erasure_before_ingestion_does_not_reject():
    r = F.fence([stamp(t=5.0)], ctx(merged_into={"B": ("A", "m1")}, subject_erased_at={"A": 3.0}))
    assert r.action == F.COMMIT


def test_c_org_erased_rejects():
    assert F.fence([stamp(t=1.0)], ctx(org_erased_at={"o": 2.0})).reason == "c:org_erased"


def test_c_dangling_link_and_loop_reject():
    assert F.fence([stamp()], ctx(merged_into={"B": ("Z", "m1")})).reason == "c:unresolvable_link"
    assert F.fence([stamp()], ctx(merged_into={"B": ("A", "m1"), "A": ("B", "m2")})).reason == "c:merge_loop"


def test_quarantine_on_recorded_merge_undone_and_q17_exception():
    r = F.fence([stamp(merges=("m1",))], ctx(merges_undone={"m1"}))
    assert (r.action, r.target_subject, r.attributed) == (F.QUARANTINE, "B", False)
    r = F.fence([stamp(merges=("m1",))], ctx(merges_undone={"m1"}, q17_recovery=True))
    assert (r.action, r.target_subject, r.merges_recorded) == (F.COMMIT, "B", ())


def test_quarantine_via_merge_traversed_at_commit():
    r = F.fence([stamp()], ctx(merged_into={"B": ("A", "m1")}, merges_undone={"m1"}))
    assert r.action == F.QUARANTINE           # F1: a merge traversed at commit is recorded too


def test_defer_on_transient():
    assert F.fence([stamp(transient=True)], ctx()).action == F.DEFER


def test_forget_me_mandatory_scenario_rejected_by_fence_not_only_head_check(w):
    """The scenario from the brief: epoch 3 → forget-me → 4 → commit rejected. Here the fence itself decides:
    the job's source subject is the survivor A, whose head is still active; B was erased."""
    ea = w.say("alice", "hi", 1)
    eb = w.say("bob", "I'm vegetarian", 1)
    a, b = ea.subject_id, eb.subject_id
    for _ in range(3):
        w.m._bump("subject:" + b, "merge", 0.5)             # bring B to epoch 3
    eb3 = w.say("bob", "I'm vegan", 1.5)
    assert eb3.epochs["subject"] == 3
    job = w.m.prepare(b)
    w.m._bump("subject:" + b, "erasure", 2)                   # epoch 4, cause erasure (head left active on purpose)
    rep = w.m.commit(job, [P("diet.pattern", "vegan", eb3, quote="vegan")], 3)
    assert not rep.created and any(r.startswith("b:subject_advanced_by_erasure") for _, r in rep.fenced)


# ------------------------------------------------------------------ episodes
def test_episode_gap_and_summary_from_evidence_only(w):
    e1 = w.say("u1", "I'm vegetarian", 1)
    w.say("u1", "and I have a dog", 1.2)
    w.say("u1", "new topic after two days", 3.5)
    s = e1.subject_id
    w.m.assign_episodes(s)
    eps = sorted(w.m.episodes.values(), key=lambda e: e.started_at)
    assert len(eps) == 2 and "dog" in eps[0].summary and "new topic" in eps[1].summary
    before = eps[0].summary
    w.m.assign_episodes(s)                                   # rerunning never summarises a summary
    assert eps[0].summary == before and "/" in before and before.count("I'm vegetarian") == 1


def test_forget_fact_regenerates_episode_without_suppressed_text(w):
    e1 = w.say("u1", "I have a dog", 1)
    w.say("u1", "I like tea", 1.1)
    s = e1.subject_id
    w.extract(s, [P("note.pet", "dog", e1, quote="I have a dog")], 1)
    w.m.assign_episodes(s)
    ep = next(iter(w.m.episodes.values()))
    assert "dog" in ep.summary
    w.m.forget_fact(s, "note.pet", "dog", 2)
    assert ep.summary_status == "regenerate_pending"
    w.m.assign_episodes(s)
    assert "dog" not in ep.summary and "tea" in ep.summary


def test_undo_quarantines_merge_epoch_episode(w):
    ea = w.say("alice", "hi", 1)
    eb0 = w.say("bob", "hi", 1)
    a, b = ea.subject_id, eb0.subject_id
    mid = w.m.merge(b, a, 2)
    w.say("bob", "I have a dog", 5)
    w.m.assign_episodes(b)
    ep = [e for e in w.m.episodes.values() if mid in e.merge_ids]
    assert ep
    w.m.undo_merge(mid, 6)
    assert all(e.summary_status == "quarantined" for e in ep)
    text, _ = w.m.build_context(w.caller, b, 7)
    assert "dog" not in text


# ------------------------------------------------------- store-wide deletion
def test_physical_deletion_leaves_no_trace_of_the_person(mk):
    w = mk(erasure_archive_window_days=1)
    secret = "zanzibarcanary"
    e1 = w.say("u1", "my secret word is " + secret, 1)
    w.say("u1", "Should I remember " + secret + "?", 1.1, role="agent")
    s = e1.subject_id
    w.extract(s, [P("note.secret", secret, e1, quote=secret)], 1)
    w.m.forget_fact(s, "note.secret", secret, 1.5)
    w.m.assign_episodes(s)
    w.m.forget_me(s, 2)
    w.m.physical_deletion_job(10)
    store = repr((w.m.claims, w.m.evidence, w.m.episodes, w.m.suppressions, w.m.manifests, w.m.erasure_log,
                  w.m.heads))
    assert secret not in store
