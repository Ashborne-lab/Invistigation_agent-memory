"""Temporal resolution (spec §9) and supersession/conflict (spec §8)."""
from conftest import P, World
from memory_core.config import DEFAULT, with_


def residence_story(w, final):
    e1 = w.say("u1", "I live in Delhi", 1)
    s = e1.subject_id
    w.extract(s, [P("residence.city", "Delhi", e1, expr="present")], 1)
    e2 = w.say("u1", "I moved to Gurugram", 100)
    w.extract(s, [P("residence.city", "Gurugram", e2, quote="Gurugram", expr="present")], 100)
    e3 = w.say("u1", "I shifted to Pune", 200)
    w.extract(s, [P("residence.city", "Pune", e3, quote="Pune", expr="present")], 200)
    e4 = w.say("u1", final, 250)
    cause = "never_true" if "never" in final else "no_longer_true"
    w.extract(s, [P("residence.city", "Pune", e4, quote="Pune", op="retract", cause=cause)], 250)
    return s


def test_never_moved_to_pune(w):
    s = residence_story(w, "I never moved to Pune")
    assert w.cur(s, "residence.city", now=260).value == ("text", "gurugram")          # current
    assert w.cur(s, "residence.city", as_of=50, now=260).value == ("text", "delhi")   # historical
    assert w.cur(s, "residence.city", as_of=220, now=260).value == ("text", "gurugram")   # Pune was never true
    assert w.cur(s, "residence.city", as_of=220, cutoff=230, now=230).value == ("text", "pune")  # belief on d230
    hist = w.m.search_history(w.caller, s, "residence.city", 260)
    assert [r["value"] for r in hist] == ["delhi", "gurugram"]                        # Pune hidden by default
    hist2 = w.m.search_history(w.caller, s, "residence.city", 260, include_retracted=True)
    assert "retracted:never_true" in [r["status"] for r in hist2]


def test_moved_out_of_pune_differs(w):
    s = residence_story(w, "I moved out of Pune")
    r = w.cur(s, "residence.city", now=260)
    assert r.status == "UNKNOWN" and "retraction" in r.note          # not Gurugram, and no Delhi resurrection
    assert w.cur(s, "residence.city", as_of=220, now=260).value == ("text", "pune")   # Pune was true until d250


def test_iphone_sold_does_not_revive_predecessor(w):
    e1 = w.say("u1", "I use an iPhone 14", 1)
    s = e1.subject_id
    w.extract(s, [P("device.phone.primary", "iPhone 14", e1, quote="iPhone 14", expr="present")], 1)
    e2 = w.say("u1", "I upgraded to an iPhone 17", 200)
    w.extract(s, [P("device.phone.primary", "iPhone 17", e2, quote="iPhone 17", expr="present")], 200)
    e3 = w.say("u1", "I actually sold the iPhone 17", 300)
    w.extract(s, [P("device.phone.primary", "iPhone 17", e3, quote="iPhone 17", op="retract",
                    cause="no_longer_true")], 300)
    assert w.cur(s, "device.phone.primary", now=350).status == "UNKNOWN"
    assert w.cur(s, "device.phone.primary", as_of=250, now=350).value == ("text", "iphone 17")
    assert w.cur(s, "device.phone.primary", as_of=100, now=350).value == ("text", "iphone 14")


def test_finding_F2_literal_E7_overlap_revives_predecessor():
    """E7's literal wording ("over the interval where their valid times overlap") uses the later claim's EFFECTIVE
    interval, so iPhone 14 comes back once the iPhone 17 is sold. The "asserted" interval is the fix."""
    w = World(with_(DEFAULT, supersession_interval="effective_overlap"))
    e1 = w.say("u1", "I use an iPhone 14", 1)
    s = e1.subject_id
    w.extract(s, [P("device.phone.primary", "iPhone 14", e1, quote="iPhone 14", expr="present")], 1)
    e2 = w.say("u1", "I upgraded to an iPhone 17", 200)
    w.extract(s, [P("device.phone.primary", "iPhone 17", e2, quote="iPhone 17", expr="present")], 200)
    e3 = w.say("u1", "I actually sold the iPhone 17", 300)
    w.extract(s, [P("device.phone.primary", "iPhone 17", e3, quote="iPhone 17", op="retract",
                    cause="no_longer_true")], 300)
    assert w.cur(s, "device.phone.primary", now=350).value == ("text", "iphone 14")   # the resurrection defect


def test_change_of_mind_future_plan_cancelled(w):
    e1 = w.say("u1", "moving to Pune in October", 10)
    s = e1.subject_id
    w.extract(s, [P("residence.city", "Pune", e1, quote="Pune", expr="in 20 days")], 10)
    e2 = w.say("u1", "cancelled, staying in Delhi", 11)
    w.extract(s, [P("residence.city", "Delhi", e2, quote="Delhi", expr="present")], 11)
    assert w.cur(s, "residence.city", as_of=40, now=40).value == ("text", "delhi")


def test_persisted_supersession_breaks_never_true():
    """M27 alternative: persisted supersession needs explicit reversal on never_true (and on policy change)."""
    w = World(with_(DEFAULT, supersession_storage_mode="persisted"))
    s = residence_story(w, "I never moved to Pune")
    assert w.cur(s, "residence.city", now=260).status == "UNKNOWN"        # Gurugram is not restored


def test_policy_change_single_to_set(w):
    e1 = w.say("u1", "I speak Hindi", 1)
    s = e1.subject_id
    w.extract(s, [P("preferred_language", "Hindi", e1, quote="Hindi", expr="present")], 1)
    e2 = w.say("u1", "I speak Telugu", 2)
    w.extract(s, [P("preferred_language", "Telugu", e2, quote="Telugu", expr="present")], 2)
    assert w.cur(s, "preferred_language", now=3).value == ("text", "telugu")
    # read-time supersession: rebuilding under policy v2 (SET) makes both active with no rewrite
    w.m.reg = __import__("memory_core.policy", fromlist=["registry"]).registry(w.m.d, 2)
    r = w.cur(s, "preferred_language", now=3)
    assert {e[0] for e in r.elements if e[1] == "ACTIVE"} == {"hindi", "telugu"}


def test_freshness_stale(w):
    e = w.say("u1", "I speak Hindi", 1)
    s = e.subject_id
    w.extract(s, [P("preferred_language", "Hindi", e, quote="Hindi", expr="present")], 1)
    assert w.cur(s, "preferred_language", now=50).freshness_status == "FRESH"
    r = w.cur(s, "preferred_language", now=200)
    assert r.status == "VALUE" and r.freshness_status == "STALE"          # stale stays VALUE (M8)


def test_same_message_two_values_conflict(w):
    e = w.say("u1", "I live in Delhi and Mumbai", 1)
    s = e.subject_id
    w.extract(s, [P("residence.city", "Delhi", e, quote="Delhi"), P("residence.city", "Mumbai", e, quote="Mumbai")], 1)
    assert w.cur(s, "residence.city").status == "CONFLICT"


def test_higher_authority_wins(w):
    e = w.say("u1", "I work at Apple", 1)
    s = e.subject_id
    w.extract(s, [P("work.employer", "apple", e, quote="Apple")], 1)
    t = w.say("u1", "HR record: Google", 2, role="tool", source_system="HR_SYSTEM")
    w.extract(s, [P("work.employer", "google", t, quote="Google")], 2)
    e3 = w.say("u1", "I work at Apple", 3)
    w.extract(s, [P("work.employer", "apple", e3, quote="Apple")], 3)
    r = w.cur(s, "work.employer")
    assert r.value == ("text", "google") and r.source == "HR_SYSTEM"       # repetition cannot beat authority


def test_operator_rank_is_injectable():
    for rank, expect in [("equal_to_user", "CONFLICT"), ("above_user", "VALUE")]:
        w = World(with_(DEFAULT, operator_rank=rank))
        e = w.say("u1", "call me Ravi", 1)
        s = e.subject_id
        w.extract(s, [P("residence.city", "Delhi", e, quote="Delhi") if False else
                      P("diet.pattern", "vegan", w.say("u1", "I'm vegan", 1.5), quote="vegan")], 1.5)
        o = w.say("u1", "operator correction: vegetarian", 2, role="operator")
        w.extract(s, [P("diet.pattern", "vegetarian", o, quote="vegetarian")], 2)
        assert w.cur(s, "diet.pattern").status == expect, rank


def test_unverified_winner_gives_unknown(w):
    e1 = w.say("u1", "I live in Delhi", 1)
    s = e1.subject_id
    w.extract(s, [P("residence.city", "Delhi", e1, quote="Delhi", expr="present")], 1)
    e2 = w.say("u1", "నేను వరంగల్‌కి మారాను", 5)
    w.extract(s, [P("residence.city", "Warangal", e2, expr="present")], 5)
    r = w.cur(s, "residence.city")
    assert r.status == "UNKNOWN" and "unverified" in r.note               # never falls back to stale Delhi (M9)


def test_explicit_none(w):
    e = w.say("u1", "I don't eat anything special, no diet", 1)
    s = e.subject_id
    w.extract(s, [P("diet.pattern", None, e, quote="no diet", kind="none")], 1)
    assert w.cur(s, "diet.pattern").status == "EXPLICIT_NONE"


def test_merged_members_conflict_r2(w):
    ea = w.say("alice", "I live in Delhi", 1)
    eb = w.say("bob", "I live in Mumbai", 1)
    a, b = ea.subject_id, eb.subject_id
    w.extract(a, [P("residence.city", "Delhi", ea, quote="Delhi")], 1)
    w.extract(b, [P("residence.city", "Mumbai", eb, quote="Mumbai")], 1)
    w.m.merge(b, a, 2)
    assert w.cur(a, "residence.city", now=3).status == "CONFLICT"          # R2
