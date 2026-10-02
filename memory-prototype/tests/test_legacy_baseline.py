"""Baseline: today's write semantics (legacy_sim ports agent_memory_service.py@daee3f9).

These tests PASS when the legacy failure is reproduced. They document the
baseline; they do not endorse it.
"""
import json

from memory_core.legacy_sim import LegacyStore


def test_wipe_on_empty_list():
    s = LegacyStore()
    s.write("k", None, json.dumps({"facts": ["vegetarian", "lives in Delhi"]}))
    assert s.write("k", s.load("k"), json.dumps({"facts": []})) == "written" and s.load("k")["facts"] == []


def test_wipe_on_non_string_items():
    s = LegacyStore()
    s.write("k", None, json.dumps({"facts": ["vegetarian"]}))
    s.write("k", s.load("k"), json.dumps({"facts": [1, 2, None]}))
    assert s.load("k")["facts"] == []


def test_freeze_on_truncated_output():
    s = LegacyStore()
    s.write("k", None, json.dumps({"facts": ["vegetarian"]}))
    truncated = json.dumps({"facts": ["vegetarian", "moved to Gurugram"]})[:-6]
    assert s.write("k", s.load("k"), truncated) == "extraction_failed_keep"
    assert s.load("k")["facts"] == ["vegetarian"]           # the new fact is lost, silently


def test_lost_update_on_concurrent_turns():
    s = LegacyStore()
    s.write("k", None, json.dumps({"facts": ["vegetarian"]}))
    snap_a, snap_b = s.load("k"), s.load("k")
    s.write("k", snap_a, json.dumps({"facts": ["vegetarian", "has a dog"]}))
    s.write("k", snap_b, json.dumps({"facts": ["vegetarian", "lives in Pune"]}))
    assert "has a dog" not in s.load("k")["facts"]


def test_delete_resurrected_by_inflight_write():
    s = LegacyStore()
    s.write("k", None, json.dumps({"facts": ["vegetarian"]}))
    snap = s.load("k")
    s.delete("k")                                           # a GDPR delete
    s.write("k", snap, json.dumps({"facts": ["vegetarian", "has a dog"]}))   # the in-flight turn finishes
    assert s.load("k") is not None and "vegetarian" in s.load("k")["facts"]   # the erased fact is resurrected


def test_agent_text_contamination_accepted():
    s = LegacyStore()
    # the legacy extractor receives "Assistant: Your plan renews on the 5th" and may echo it as a fact
    s.write("k", None, json.dumps({"facts": ["User's plan renews on the 5th"]}))
    assert s.load("k")["facts"] == ["User's plan renews on the 5th"]   # no gate exists


def test_cap_truncation_drops_tail():
    s = LegacyStore()
    s.write("k", None, json.dumps({"facts": ["f%d" % i for i in range(35)]}))
    assert len(s.load("k")["facts"]) == 30 and "f34" not in s.load("k")["facts"]
