"""E3 fencing, merge/undo quarantine, Q17 recovery, and R6b Option B erasure (mandatory scenarios)."""
import pytest

from conftest import ORG, P, World
from memory_core.config import DEFAULT, with_


def test_forget_me_during_extraction_rejects(w):
    e1 = w.say("u1", "I'm vegetarian", 1)
    s = e1.subject_id
    job = w.m.prepare(s)                                   # the worker starts (evidence at subject epoch 0)
    w.m.forget_me(s, 2)                                    # epoch advances with cause erasure
    rep = w.m.commit(job, [P("diet.pattern", "vegetarian", e1)], 3)
    assert not rep.created and rep.fenced
    assert not [c for c in w.m.claims.values() if c.state.status == "active"]


def test_merge_during_extraction_retargets(w):
    eb = w.say("bob", "I'm vegetarian", 1)
    ea = w.say("alice", "hello", 1)
    a, b = ea.subject_id, eb.subject_id
    job = w.m.prepare(b)
    mid = w.m.merge(b, a, 2)
    rep = w.m.commit(job, [P("diet.pattern", "vegetarian", eb)], 3)
    c = w.m.claims[rep.created[0]]
    assert c.content.subject_id == a and mid in c.state.merge_ids       # retargeted; B got no content write
    assert c.content.source_member_id == b


def test_evidence_during_merge_then_undo_then_commit_quarantines(w):
    ea = w.say("alice", "hi", 1)
    eb0 = w.say("bob", "hi", 1)
    a, b = ea.subject_id, eb0.subject_id
    mid = w.m.merge(b, a, 2)
    e1 = w.say("bob", "I'm vegetarian", 3)                 # ingested during the merge → carries mid
    assert mid in e1.merge_ids_at_ingestion
    job = w.m.prepare(b)
    w.m.undo_merge(mid, 4)
    rep = w.m.commit(job, [P("diet.pattern", "vegetarian", e1)], 5)
    assert rep.quarantined and not rep.created
    q = w.m.claims[rep.quarantined[0]]
    assert q.state.status == "quarantined" and q.state.attributed is False
    assert w.cur(a, "diet.pattern").status == "UNKNOWN" and w.cur(b, "diet.pattern").status == "UNKNOWN"


def test_F1_pre_merge_evidence_committed_during_merge_quarantined_on_undo(w):
    ea = w.say("alice", "hi", 1)
    eb = w.say("bob", "I'm vegetarian", 1)                 # before any merge
    a, b = ea.subject_id, eb.subject_id
    mid = w.m.merge(b, a, 2)
    rep = w.extract(b, [P("diet.pattern", "vegetarian", eb)], 3)    # committed during the merge → under A
    assert w.cur(a, "diet.pattern").value == ("text", "vegetarian")
    w.m.undo_merge(mid, 4)
    c = w.m.claims[rep.created[0]]
    assert c.state.status == "quarantined"                 # F1 closed: recorded through merges_traversed
    assert w.cur(a, "diet.pattern").status == "UNKNOWN"


def _quarantined_during_merge(w):
    ea = w.say("alice", "hi", 1)
    eb0 = w.say("bob", "hi", 1)
    a, b = ea.subject_id, eb0.subject_id
    mid = w.m.merge(b, a, 2)
    e1 = w.say("bob", "I'm vegetarian", 3)
    w.extract(b, [P("diet.pattern", "vegetarian", e1)], 3)   # committed under A during the merge
    w.m.undo_merge(mid, 4)
    return a, b, mid, e1


def test_q17_recovery_creates_new_claim_never_restores(w):
    a, b, mid, e1 = _quarantined_during_merge(w)
    before = {cid: c.state.status for cid, c in w.m.claims.items()}
    rep = w.m.commit(w.m.recovery_job(mid, b), [P("diet.pattern", "vegetarian", e1)], 5)
    assert rep.created and rep.created[0] not in before              # a NEW claim, under B
    assert w.m.claims[rep.created[0]].content.subject_id == b
    assert all(w.m.claims[cid].state.status == st for cid, st in before.items())   # nothing restored in place
    assert w.cur(b, "diet.pattern").value == ("text", "vegetarian")


def test_finding_F3_recovery_collides_with_same_subject_quarantine():
    """Undo happens BEFORE commit, so the quarantined claim sits under the source member B with
    id = HMAC(k_B, evidence|key|value). Recovery computes the same id and becomes a no-op,
    so Q17 recovery is impossible under the spec formula."""
    def run(d):
        w = World(d)
        ea = w.say("alice", "hi", 1)
        eb0 = w.say("bob", "hi", 1)
        a, b = ea.subject_id, eb0.subject_id
        mid = w.m.merge(b, a, 2)
        e1 = w.say("bob", "I'm vegetarian", 3)
        job = w.m.prepare(b)
        w.m.undo_merge(mid, 4)
        w.m.commit(job, [P("diet.pattern", "vegetarian", e1)], 5)          # quarantined under B
        rep = w.m.commit(w.m.recovery_job(mid, b), [P("diet.pattern", "vegetarian", e1)], 6)
        return rep, w.cur(b, "diet.pattern").status
    rep, st = run(DEFAULT)
    assert not rep.created and st == "UNKNOWN"               # the defect: recovery silently does nothing
    rep2, st2 = run(with_(DEFAULT, claim_id_derivation_tag=True))
    assert rep2.created and st2 == "VALUE"                   # the amendment: derivation tag in the id


def test_q17_recovery_skips_confirmed(w):
    ea = w.say("alice", "hi", 1)
    eb0 = w.say("bob", "hi", 1)
    a, b = ea.subject_id, eb0.subject_id
    mid = w.m.merge(b, a, 2)
    ag = w.say("bob", "Should I book the Friday slot?", 3, role="agent")
    u = w.say("bob", "yes", 3.01)
    w.extract(b, [P("commitment.appointment", "friday slot", u, mode="confirmed", prompt=ag,
                    pquote="book the Friday slot")], 3.1)
    w.m.undo_merge(mid, 4)
    rep = w.m.commit(w.m.recovery_job(mid, b), [P("commitment.appointment", "friday slot", u, mode="confirmed",
                                                   prompt=ag, pquote="book the Friday slot")], 5)
    assert not rep.created


def test_absorbed_subject_gets_lifecycle_not_content(w):
    ea = w.say("alice", "hi", 1)
    eb = w.say("bob", "I'm vegetarian", 1)
    a, b = ea.subject_id, eb.subject_id
    w.extract(b, [P("diet.pattern", "vegetarian", eb)], 1)          # B's own pre-merge claim
    cb = next(iter(w.m.claims.values()))
    w.m.merge(b, a, 2)
    e2 = w.say("bob", "I love hiking", 3)
    rep = w.extract(b, [P("note.hobby", "hiking", e2, quote="hiking")], 3)
    assert w.m.claims[rep.created[0]].content.subject_id == a       # new content goes to the survivor
    w.m.erase_evidence(eb.evidence_id, 4)                            # a lifecycle transition on B is allowed
    assert cb.state.status == "invalidated" and cb.content.subject_id == b


def test_chained_merge_undo_middle(w):
    ea, eb, ec = w.say("a", "hi", 1), w.say("b", "hi", 1), w.say("c", "hi", 1)
    a, b, c = ea.subject_id, eb.subject_id, ec.subject_id
    m1 = w.m.merge(c, b, 2)
    m2 = w.m.merge(b, a, 3)
    e1 = w.say("c", "I'm vegetarian", 4)
    rep = w.extract(c, [P("diet.pattern", "vegetarian", e1)], 4)
    cl = w.m.claims[rep.created[0]]
    assert cl.content.subject_id == a and set(cl.state.merge_ids) >= {m1, m2}
    w.m.undo_merge(m2, 5)
    assert cl.state.status == "quarantined"


def test_two_anchors_one_erased_rejects_whole_write(w):
    e1 = w.say("u1", "my dog", 1)
    e2 = w.say("u1", "his name is Bruno", 1.1)
    s = e1.subject_id
    job = w.m.prepare(s)
    w.m.erase_evidence(e2.evidence_id, 1.2)
    rep = w.m.commit(job, [P("family.dog_name", "bruno", e1, quote="my dog",
                             extra_anchor=[{"evidence_id": e2.evidence_id, "quote": "Bruno"}])], 2)
    assert not rep.created and not w.m.claims                # "Bruno" is never committed from a fenced input


def test_transient_unavailable_defers_and_keeps_pending(w):
    e1 = w.say("u1", "I'm vegetarian", 1)
    s = e1.subject_id
    w.m.unavailable.add(e1.evidence_id)
    rep = w.extract(s, [P("diet.pattern", "vegetarian", e1)], 2)
    assert rep.deferred and e1.extraction_state == "pending"
    w.m.unavailable.clear()
    assert w.extract(s, [P("diet.pattern", "vegetarian", e1)], 3).created


def test_transfer_fails_closed(w):
    e1 = w.say("u1", "I'm vegetarian", 1)
    s = e1.subject_id
    job = w.m.prepare(s)
    w.m.transfer(s, 2)
    rep = w.m.commit(job, [P("diet.pattern", "vegetarian", e1)], 3)
    assert not rep.created and rep.fenced[0][1].startswith("b:subject_advanced_by_transfer")
    with pytest.raises(NotImplementedError):
        World(with_(DEFAULT, transfer_policy="copy_to_destination")).m.transfer(s, 2)


# -------------------------------------------------------------- R6b Option B
def test_forget_me_during_wrong_merge_archives_whole_subject(w):
    ea = w.say("alice", "I'm vegetarian", 1)
    eb = w.say("bob", "I live in Mumbai", 1)
    a, b = ea.subject_id, eb.subject_id
    w.extract(a, [P("diet.pattern", "vegetarian", ea)], 1)
    w.extract(b, [P("residence.city", "Mumbai", eb, quote="Mumbai")], 1)
    w.m.merge(b, a, 2)
    late = w.m.prepare(b)
    w.m.forget_me(b, 3)                                      # the request arrives through the absorbed member
    for s in (a, b):
        assert w.m.heads[s].status == "pending_erasure" and w.m.heads[s].do_not_contact
        assert w.cur(s, "diet.pattern").status == "UNAVAILABLE"
        assert w.m.build_context(w.caller, s, 4) == (None, None)
        assert w.m.search_memory(w.caller, s, "", 4).status == "UNAVAILABLE"
    assert all(c.state.status == "pending_erasure" for c in w.m.claims.values())
    assert not w.m.commit(late, [P("residence.city", "Mumbai", eb, quote="Mumbai")], 5).created
    assert w.m.physical_deletion_job(10_000) == {"ran": False, "reason": "ERASURE_ARCHIVE_WINDOW unset", "deleted": 0}
    assert w.m.claims                                        # still archived, never silently deleted
    new = w.say("alice", "hello again", 6)
    assert new.subject_id not in (a, b)                     # a returning person gets a new subject


def test_physical_deletion_after_window(mk):
    w = mk(erasure_archive_window_days=30)
    e = w.say("u1", "I'm vegetarian", 1)
    s = e.subject_id
    w.extract(s, [P("diet.pattern", "vegetarian", e)], 1)
    w.m.forget_me(s, 2)
    assert w.m.physical_deletion_job(10)["deleted"] == 0
    assert w.m.physical_deletion_job(40)["deleted"] == 1 and w.m.keys[s] is None


def test_pending_erasure_disabled_deletes_immediately(mk):
    w = mk(pending_erasure_enabled=False)
    e = w.say("u1", "I'm vegetarian", 1)
    s = e.subject_id
    w.extract(s, [P("diet.pattern", "vegetarian", e)], 1)
    w.m.forget_me(s, 2)
    assert not w.m.claims                                     # no archive stage (settled R6b needs the archive)


def test_forget_me_session_cutoff_recorded(w):
    e = w.say("u1", "I'm vegetarian", 1)
    w.m.forget_me(e.subject_id, 2)
    assert w.m.session_erased_before.get(e.session_id) == 2


def test_forget_fact_suppression_scopes():
    for scope, relearn in [("evidence_before", True), ("forever", False)]:
        w = World(with_(DEFAULT, suppression_scope=scope))
        e1 = w.say("u1", "I have a dog", 1)
        s = e1.subject_id
        w.extract(s, [P("note.pet", "dog", e1, quote="I have a dog")], 1)
        ag = w.say("u1", "Nice, how is your dog?", 1.1, role="agent")
        hit = w.m.forget_fact(s, "note.pet", "dog", 2)
        assert hit and all(w.m.claims[h].state.status == "pending_erasure" for h in hit)
        assert e1.status == "context_suppressed" and ag.status == "context_suppressed"   # M19 echo
        e2 = w.say("u1", "I have a dog", 3)                    # repeated later (Case 15)
        rep = w.extract(s, [P("note.pet", "dog", e2, quote="I have a dog")], 3)
        assert bool(rep.created) == relearn, scope


def test_stop_remembering(w):
    e = w.say("u1", "I'm vegetarian", 1)
    s = e.subject_id
    w.extract(s, [P("diet.pattern", "vegetarian", e)], 1)
    w.m.stop_remembering(s)
    e2 = w.say("u1", "I live in Delhi", 2)
    w.extract(s, [P("residence.city", "Delhi", e2, quote="Delhi")], 2)
    assert e2.extraction_state == "skipped_consent"
    assert w.cur(s, "diet.pattern").value == ("text", "vegetarian")   # nothing pretends to be erased
    assert w.cur(s, "residence.city").status == "UNKNOWN"


def _f7(d):
    w = World(d)
    e_old = w.say("u1", "I no longer live in Pune", 5)          # processed late
    e_new = w.say("u1", "I live in Pune", 10)
    s = e_old.subject_id
    w.extract(s, [P("residence.city", "Pune", e_new, quote="Pune", expr="present")], 11, only=[e_new.evidence_id])
    rep = w.extract(s, [P("residence.city", "Pune", e_old, quote="Pune", op="retract", cause="no_longer_true")], 12)
    return bool(rep.retracted)


def test_F7_retraction_reaching_later_observed_claim():
    from memory_core.config import AMENDED
    assert _f7(DEFAULT) is True          # spec defect: an older retraction erases a newer statement
    assert _f7(AMENDED) is False


def _f8(d):
    w = World(d)
    ec = w.say("carol", "I have a cat", 1)
    eb = w.say("bob", "I no longer have a cat", 2)
    c, b = ec.subject_id, eb.subject_id
    w.extract(c, [P("note.pet", "cat", ec, quote="I have a cat")], 1)
    w.m.merge(c, b, 3)
    rep = w.extract(b, [P("note.pet", "cat", eb, quote="cat", op="retract", cause="no_longer_true")], 4)
    return bool(rep.retracted)


def test_F8_member_retracting_other_members_claim():
    from memory_core.config import AMENDED
    assert _f8(DEFAULT) is True          # spec defect: Bob's words erase Carol's fact, bypassing R2
    assert _f8(AMENDED) is False


def _f4(d):
    w = World(d)
    ea = w.say("alice", "I'm vegetarian", 1)
    eb = w.say("bob", "hi", 1)
    a, b = ea.subject_id, eb.subject_id
    w.extract(a, [P("diet.pattern", "vegetarian", ea)], 1)
    ca = next(iter(w.m.claims.values()))
    mid = w.m.merge(b, a, 2)
    e2 = w.say("bob", "I'm vegetarian", 3)                      # Bob's words restate Alice's fact during the merge
    w.extract(b, [P("diet.pattern", "vegetarian", e2)], 3)
    w.m.undo_merge(mid, 4)
    return any(e.source_member_id == b for e in ca.state.support.values())


def test_F4_merge_epoch_support_survives_undo_under_spec():
    from memory_core.config import AMENDED
    assert _f4(DEFAULT) is True          # spec gap: Alice's claim is still supported by Bob's words after the undo
    assert _f4(AMENDED) is False
