"""Claim identity (spec §7.2) and support/lineage (spec §7.4)."""
import itertools

from conftest import P, World
from memory_core import ids
from memory_core.config import DEFAULT, with_


def test_retry_and_duplicate_are_idempotent(w):
    e = w.say("u1", "I'm vegetarian", 1)
    s = e.subject_id
    pr = [P("diet.pattern", "vegetarian", e)]
    r1 = w.m.commit(w.m.prepare(s), pr + pr, 1)            # a duplicate inside one batch
    e.extraction_state = "pending"                        # simulate a retry of the same job
    r2 = w.m.commit(w.m.prepare(s), pr, 1.1)
    assert len(w.m.claims) == 1 and len(r1.created) == 1 and r2.supported == r1.created


def test_low_entropy_value_not_recoverable_from_id(w):
    e = w.say("u1", "I have 2 kids", 1)
    s = e.subject_id
    w.extract(s, [P("family.kids", "2", e, quote="2")], 1)
    cid = next(iter(w.m.claims))
    guesses = [str(i) for i in range(100)]
    # an attacker knows the formula, the evidence id and the key, but not the subject key
    wrong_key = b"\x00" * 32
    assert not any(ids.claim_id(wrong_key, e.evidence_id, "family.kids", g) == cid for g in guesses)
    # whoever holds the key can recompute the id; this shows the key is the only secret
    assert any(ids.claim_id(w.m.keys[s], e.evidence_id, "family.kids", g) == cid for g in guesses)


def test_raw_identifiers_not_in_ids(mk):
    w = mk(phone_email_memory_keys=True)
    e = w.say("9876543210", "my number is 98765 43210", 1)
    s = e.subject_id
    w.extract(s, [P("contact.phone", "+919876543210", e, quote="98765 43210", mode="normalized")], 1)
    everything = " ".join([s, *w.m.index.keys(), *w.m.claims.keys()])
    assert "9876543210" not in everything and "98765" not in everything


def test_crypto_shred_breaks_linkage(mk):
    w = mk(erasure_archive_window_days=0)
    e = w.say("u1", "I'm vegetarian", 1)
    s = e.subject_id
    w.extract(s, [P("diet.pattern", "vegetarian", e)], 1)
    cid = next(iter(w.m.claims))
    w.m.forget_me(s, 2)
    w.m.physical_deletion_job(3)
    assert w.m.keys[s] is None and cid not in w.m.claims   # nothing left can recompute or associate the id


def test_support_lineage_erase_one_then_all(w):
    e1 = w.say("u1", "I'm vegetarian", 1)
    s = e1.subject_id
    w.extract(s, [P("diet.pattern", "vegetarian", e1)], 1)
    e2 = w.say("u1", "as I said, I'm vegetarian", 5)
    r = w.extract(s, [P("diet.pattern", "vegetarian", e2, quote="I'm vegetarian")], 5)
    c = next(iter(w.m.claims.values()))
    assert r.supported == [c.id] and len(c.state.support) == 2
    w.m.erase_evidence(e1.evidence_id, 6)
    assert c.state.status == "active" and w.cur(s, "diet.pattern").value == ("text", "vegetarian")
    w.m.erase_evidence(e2.evidence_id, 7)
    assert c.state.status == "invalidated" and w.cur(s, "diet.pattern").status == "UNKNOWN"


def _f6(d):
    w = World(d)
    e1 = w.say("u1", "I work at Acme", 1)
    s = e1.subject_id
    w.extract(s, [P("work.employer", "acme", e1, quote="Acme")], 1)
    t = w.say("u1", "employee record: Acme", 2, role="tool", source_system="HR_SYSTEM")
    w.extract(s, [P("work.employer", "acme", t, quote="Acme")], 2)
    e3 = w.say("u1", "I now work at Beta", 3)
    w.extract(s, [P("work.employer", "beta", e3, quote="Beta")], 3)
    return w.cur(s, "work.employer").value


def test_F6_dedup_across_sources_loses_authority():
    from memory_core.config import AMENDED
    assert _f6(DEFAULT) == ("text", "beta")     # spec defect: the HR confirmation was folded into the USER claim
    assert _f6(AMENDED) == ("text", "acme")     # amended: HR_SYSTEM keeps its own claim and its authority


def test_quoted_anchor_of_erased_evidence_still_physically_stored(w):
    """Finding F-5 (spec defect): the anchor quote sits in immutable claim content, so erasing one of two supporting
    evidence items cannot remove its quote (M20) without breaking content immutability."""
    e1 = w.say("u1", "I'm vegetarian, my address is 12 Park Street", 1)
    s = e1.subject_id
    w.extract(s, [P("diet.pattern", "vegetarian", e1, quote="I'm vegetarian, my address is 12 Park Street")], 1)
    e2 = w.say("u1", "I'm vegetarian", 2)
    w.extract(s, [P("diet.pattern", "vegetarian", e2)], 2)
    w.m.erase_evidence(e1.evidence_id, 3)
    c = next(iter(w.m.claims.values()))
    assert c.state.status == "active"
    leaked = any("Park Street" in q for _, q in c.content.anchor)
    assert leaked            # the defect exists: the erased evidence's text survives in the claim
