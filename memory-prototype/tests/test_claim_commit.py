"""Claim Commit Protocol. All policies are TEST_ONLY_* (placeholder governance values; never production policy)."""
import dataclasses
import random

import pytest

from memory_core.claimgate import ACCEPT, Proposal, decide
from memory_core.commit import (COMMITTED, EXISTING_CLAIM, FENCED, NOT_COMMITTED, REJECTED,
                                STATE_CONFLICT, CommitStore, CrashAfterWrite, CrashBeforeWrite, Projection,
                                RetractionRecord, apply_retraction, claim_identity, commit, lifecycle,
                                rebuild_claims, retract)
from memory_core.config import AMENDED
from memory_core.fence import Context
from memory_core.model import (ACTIVE, CONFLICT as S_CONFLICT, EXPLICIT_NONE, INVALIDATED, NEVER_TRUE,
                               NO_LONGER_TRUE, PENDING_ERASURE, QUARANTINED, RETRACTED, UNKNOWN, VALUE, Claim,
                               ClaimContent, ClaimState, Evidence)
from memory_core.registry import PolicyRegistry, PredicatePolicy, resolve_slot
from memory_core.runtime import Memory

NOW = 100.0
OPS = {VALUE: frozenset({"SET"}), EXPLICIT_NONE: frozenset({"SET"}), UNKNOWN: frozenset({"SET", "ESTABLISH"}),
       S_CONFLICT: frozenset({"RESOLVE_CONFLICT"})}
CITY = PredicatePolicy("TEST_ONLY_city", 3, "SINGLE", frozenset({"llm_extractor", "operator"}),
                       frozenset({"USER", "OPERATOR"}), OPS, "TEST_ONLY_DOMAIN", {"USER": 1, "OPERATOR": 1},
                       retention_class="TEST_ONLY_RETENTION", llm_write_mode="PROPOSE_VIA_GATE")
REG = PolicyRegistry(allow_test_only=True)
REG.publish(CITY)
KEYS = {}


def subject_key(subject):                       # per-subject key provider (custody is an open decision)
    return KEYS.setdefault(subject, bytes([len(KEYS) + 1]) * 32)


def ev(eid, text, subj="s1", role="user", member="m1", observed=NOW - 1, seq=1, merge_ids=(), epochs=None,
       status="active"):
    return Evidence(evidence_id=eid, org_id="o1", subject_id=subj, source_member_id=member, agent_id="a1",
                    session_id="sess1", author_role=role, text=text, observed_at=observed,
                    epochs=epochs or {"org": 0, "subject": 0, "session": 0}, merge_ids_at_ingestion=tuple(merge_ids),
                    receipt_seq=seq, status=status)


def ctx(**kw):
    base = dict(epoch_log={}, merged_into={}, merges_undone=set(), subject_erased_at={}, org_erased_at={},
                org_of={"s1": "o1", "s2": "o1"}, known_subjects={"s1", "s2"})
    base.update(kw)
    return Context(**base)


def current(claims=()):
    return resolve_slot(CITY, list(claims), NOW, NOW, AMENDED, NOW)


def proposal(pid, value, quote, eid="e1", writer="llm_extractor", source="USER", subj="s1", **kw):
    return Proposal(pid, subj, "o1", CITY.predicate, CITY.policy_version_id, "SET", writer, source,
                    ("text", value), ((eid, quote),), **kw)


def gate_and_commit(store, pr, evid, cur=None, fctx=None, **kw):
    out = decide(pr, REG, evid, cur or current(store.claims.values()), NOW)
    return out, commit(store, pr, out, evid, fctx or ctx(), subject_key, NOW, **kw)


E = {"e1": ev("e1", "I live in Pune", seq=1), "e2": ev("e2", "I moved to Delhi", observed=NOW - 0.5, seq=2),
     "e_op": ev("e_op", "address Delhi confirmed", role="operator", member="op1", seq=3)}


# ------------------------------------------------------------------------------------------------- commit
def test_successful_commit_is_immutable_with_full_provenance():
    store = CommitStore()
    pr = proposal("p1", "pune", "I live in Pune")
    out, res = gate_and_commit(store, pr, E)
    assert out.decision == ACCEPT and res.status == COMMITTED
    c = store.claims[res.record.claim_id]
    k = c.content
    assert (k.subject_id, k.key, k.source, k.source_member_id) == ("s1", "TEST_ONLY_city", "USER", "m1")
    assert k.anchor == (("e1", "I live in Pune"),) and k.policy_version == 3          # pinned policy version
    assert (k.valid_from, k.valid_until, k.observed_at, k.committed_at) == (None, None, NOW - 1, NOW)
    assert k.written_via == "llm" and k.learned_by_agent_id == "a1"
    rec = store.records["p1"]                                                         # operation/writer provenance
    assert (rec.proposal.op, rec.proposal.writer, rec.decision.decision) == ("SET", "llm_extractor", ACCEPT)
    assert store.provenance[c.id] == [rec.seq]
    with pytest.raises(dataclasses.FrozenInstanceError):
        k.value = ("text", "delhi")


def test_claim_id_is_deterministic_and_distinct():
    pr = proposal("p1", "pune", "I live in Pune")
    d = decide(pr, REG, E, current(), NOW).draft
    k = subject_key("s1")
    assert claim_identity(k, d, "orig") == claim_identity(k, d, "orig")
    assert claim_identity(k, d, "orig") != claim_identity(k, d, "recovery:m9")        # re-derivation never collides
    assert claim_identity(k, d, "orig") != claim_identity(subject_key("s2"), d, "orig")
    for change in (dict(source_member_id="m2"), dict(valid_from=1.0), dict(key="TEST_ONLY_other"),
                   dict(value=("text", "delhi")), dict(anchor=(("e2", "x"),))):
        assert claim_identity(k, dataclasses.replace(d, **change), "orig") != claim_identity(k, d, "orig")


def test_duplicate_retry_creates_no_second_claim():
    store = CommitStore()
    pr = proposal("p1", "pune", "I live in Pune")
    out, first = gate_and_commit(store, pr, E)
    again = commit(store, pr, out, E, ctx(), subject_key, NOW)
    assert again.duplicate and again.record == first.record and len(store.claims) == 1
    assert store.claims_version["s1"] == 1


def test_reused_proposal_id_with_different_content_rejected():
    store = CommitStore()
    gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E)
    pr2 = proposal("p1", "delhi", "I moved to Delhi", eid="e2")
    res = commit(store, pr2, decide(pr2, REG, E, current(), NOW), E, ctx(), subject_key, NOW)
    assert (res.status, res.reason) == (REJECTED, "proposal_id_reused_with_different_content")


def test_same_claim_from_a_new_proposal_is_existing_not_duplicated():
    store = CommitStore()
    _, a = gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E)
    _, b = gate_and_commit(store, proposal("p2", "pune", "I live in Pune"), E)
    assert b.status == EXISTING_CLAIM and b.record.claim_id == a.record.claim_id and len(store.claims) == 1
    assert store.provenance[a.record.claim_id] == [a.record.seq, b.record.seq]


def test_decision_must_belong_to_the_proposal():
    store = CommitStore()
    pr1, pr2 = proposal("p1", "pune", "I live in Pune"), proposal("p2", "delhi", "I moved to Delhi", eid="e2")
    res = commit(store, pr2, decide(pr1, REG, E, current(), NOW), E, ctx(), subject_key, NOW)
    assert (res.status, res.reason) == (REJECTED, "decision_does_not_match_proposal")


def test_rejected_gate_decision_is_recorded_but_commits_nothing():
    store = CommitStore()
    pr = proposal("p1", "mumbai", "I live in Mumbai")                  # not in the evidence
    out, res = gate_and_commit(store, pr, E)
    assert res.status == NOT_COMMITTED and not store.claims and store.records["p1"].decision == out


# ------------------------------------------------------------------------------------------------- partial failure
def test_crash_before_write_leaves_nothing_and_retry_commits_once():
    store = CommitStore()
    pr = proposal("p1", "pune", "I live in Pune")
    out = decide(pr, REG, E, current(), NOW)
    with pytest.raises(CrashBeforeWrite):
        commit(store, pr, out, E, ctx(), subject_key, NOW, crash="before_write")
    assert not store.claims and not store.records and not store.journal
    assert commit(store, pr, out, E, ctx(), subject_key, NOW).status == COMMITTED
    assert len(store.claims) == 1


def test_crash_after_write_retry_is_exactly_one_logical_commit():
    store = CommitStore()
    pr = proposal("p1", "pune", "I live in Pune")
    out = decide(pr, REG, E, current(), NOW)
    with pytest.raises(CrashAfterWrite):
        commit(store, pr, out, E, ctx(), subject_key, NOW, crash="after_write")
    retry = commit(store, pr, out, E, ctx(), subject_key, NOW)
    assert retry.duplicate and retry.status == COMMITTED
    assert len(store.claims) == 1 and len(store.journal) == 1 and store.claims_version["s1"] == 1


def test_failure_inside_the_write_rolls_back_everything(monkeypatch):
    store = CommitStore()
    import memory_core.commit as cm
    monkeypatch.setattr(cm, "_insert", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    pr = proposal("p1", "pune", "I live in Pune")
    with pytest.raises(OSError):
        commit(store, pr, decide(pr, REG, E, current(), NOW), E, ctx(), subject_key, NOW)
    assert not store.claims and not store.records and not store.journal and not store.provenance


# ------------------------------------------------------------------------------------------------- concurrency
def _op_proposal(pid):
    return proposal(pid, "delhi", "address Delhi", eid="e_op", writer="operator", source="OPERATOR")


def test_expected_version_success_and_versions():
    store, proj = CommitStore(), Projection()
    v0 = proj.observe("s1:TEST_ONLY_city", current(store.claims.values()).slot.signature())
    out, res = gate_and_commit(store, _op_proposal("p1"), E, expected_version=v0, actual_version=v0)
    assert res.status == COMMITTED and store.claims_version["s1"] == 1                 # claims_version advanced
    v1 = proj.observe("s1:TEST_ONLY_city", current(store.claims.values()).slot.signature())
    assert v1 == v0 + 1                                                                 # result changed -> advances
    assert proj.observe("s1:TEST_ONLY_city", current(store.claims.values()).slot.signature()) == v1   # unchanged


def test_typed_command_without_expected_version_rejected():
    _, res = gate_and_commit(CommitStore(), _op_proposal("p1"), E)
    assert (res.status, res.reason) == (REJECTED, "expected_version_required_for_state_command")


def test_stale_expected_version_is_typed_state_conflict():
    store = CommitStore()
    _, res = gate_and_commit(store, _op_proposal("p1"), E, expected_version=3, actual_version=4,
                             expected_status=UNKNOWN, actual_status=VALUE)
    sc = res.record.state_conflict
    assert res.status == STATE_CONFLICT and not store.claims
    assert (sc.predicate, sc.expected_version, sc.actual_version, sc.expected_status, sc.actual_status) == \
        ("TEST_ONLY_city", 3, 4, UNKNOWN, VALUE)


def test_state_conflict_is_never_silently_retried():
    store = CommitStore()
    pr = _op_proposal("p1")
    out = decide(pr, REG, E, current(), NOW)
    commit(store, pr, out, E, ctx(), subject_key, NOW, expected_version=3, actual_version=4)
    # infrastructure retries the SAME mutation, even with versions that would now match: the recorded semantic
    # rejection stands; the caller must re-read and issue a NEW mutation
    again = commit(store, pr, out, E, ctx(), subject_key, NOW, expected_version=4, actual_version=4)
    assert again.status == STATE_CONFLICT and again.duplicate and not store.claims
    fresh = commit(store, _op_proposal("p2"), decide(_op_proposal("p2"), REG, E, current(), NOW), E, ctx(),
                   subject_key, NOW, expected_version=4, actual_version=4)
    assert fresh.status == COMMITTED


# ------------------------------------------------------------------------------------------------- fencing
def test_erasure_generation_fence():
    fctx = ctx(epoch_log={"subject:s1": [(1, "erasure", NOW - 0.5)]})
    _, res = gate_and_commit(CommitStore(), proposal("p1", "pune", "I live in Pune"), E, fctx=fctx)
    assert res.status == FENCED and res.reason.startswith("b:subject_advanced_by_erasure")


def test_dead_evidence_fence():
    evid = {**E, "e1": ev("e1", "I live in Pune", status="pending_erasure")}
    pr = proposal("p1", "pune", "I live in Pune")
    out = decide(pr, REG, E, current(), NOW)                   # gate saw it alive
    res = commit(CommitStore(), pr, out, evid, ctx(), subject_key, NOW)   # by commit time it is pending erasure
    assert res.status == FENCED and "pending_erasure" in res.reason


def test_merge_path_lands_on_survivor_and_undone_merge_quarantines():
    store = CommitStore()
    _, res = gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E,
                             fctx=ctx(merged_into={"s1": ("s2", "mg1")}))
    c = store.claims[res.record.claim_id]
    assert res.status == COMMITTED and c.content.subject_id == "s2" and c.state.merge_ids == ["mg1"]
    store2 = CommitStore()
    _, res2 = gate_and_commit(store2, proposal("p1", "pune", "I live in Pune"), E,
                              fctx=ctx(merged_into={"s1": ("s2", "mg1")}, merges_undone={"mg1"}))
    c2 = store2.claims[res2.record.claim_id]
    assert c2.state.status == QUARANTINED and c2.state.attributed is False and c2.content.subject_id == "s1"


def test_erased_subject_on_merge_path_fenced():
    fctx = ctx(merged_into={"s1": ("s2", "mg1")}, subject_erased_at={"s2": NOW - 0.5})
    _, res = gate_and_commit(CommitStore(), proposal("p1", "pune", "I live in Pune"), E, fctx=fctx)
    assert res.status == FENCED and res.reason.startswith("c:subject_on_path_erased")


def test_missing_evidence_at_commit_is_fenced():
    store = CommitStore()
    pr = proposal("p1", "pune", "I live in Pune")
    out = decide(pr, REG, E, current(), NOW)
    res = commit(store, pr, out, {}, ctx(), subject_key, NOW)          # evidence gone between gate and commit
    assert res.status == FENCED and res.reason.startswith("a:evidence_missing") and not store.claims


# ------------------------------------------------------------------------------------------------- lifecycle
def test_retraction_is_recorded_idempotent_and_replays():
    store = CommitStore()
    _, res = gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E)
    r = RetractionRecord("r1", "s1", "TEST_ONLY_city", ("text", "pune"), "USER", "m1", NO_LONGER_TRUE, NOW - 0.2, 5,
                         "e2")
    assert retract(store, r, NOW).status == COMMITTED
    assert retract(store, r, NOW).duplicate
    c = store.claims[res.record.claim_id]
    assert c.state.status == RETRACTED and c.content.value == ("text", "pune")        # content untouched
    assert rebuild_claims(store.journal) == store.claims
    bad = dataclasses.replace(r, cause=NEVER_TRUE)
    assert retract(store, bad, NOW).reason == "retraction_id_reused_with_different_content"


def test_retraction_recorded_before_claim_still_ends_it():
    store = CommitStore()
    retract(store, RetractionRecord("r1", "s1", "TEST_ONLY_city", ("text", "pune"), "USER", "m1", NEVER_TRUE,
                                    NOW - 0.2, 5, "e2"), NOW)
    _, res = gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E)
    assert store.claims[res.record.claim_id].state.status == RETRACTED
    assert rebuild_claims(store.journal) == store.claims


def test_lifecycle_records_never_touch_content():
    store = CommitStore()
    _, res = gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E)
    cid = res.record.claim_id
    before = store.claims[cid].content
    for to in (INVALIDATED, ACTIVE, QUARANTINED, PENDING_ERASURE):
        assert lifecycle(store, cid, to, "test", NOW).status == COMMITTED
    assert store.claims[cid].content is before and store.claims[cid].state.status == PENDING_ERASURE
    assert lifecycle(store, cid, "deleted_forever", "x", NOW).reason == "unknown_lifecycle_status"
    assert lifecycle(store, cid, RETRACTED, "x", NOW).reason == "use_retract_for_retraction"
    assert rebuild_claims(store.journal) == store.claims


def test_retraction_rule_matches_lane_a_runtime():
    rng = random.Random(7)
    for _ in range(300):
        c1 = _rand_claim(rng)
        c2 = Claim(c1.content, dataclasses.replace(c1.state, transitions=list(c1.state.transitions)))
        r = RetractionRecord("r", "s1", "k", ("text", rng.choice("ab")), rng.choice(["USER", "OPERATOR"]),
                             rng.choice(["m1", "m2"]), rng.choice([NO_LONGER_TRUE, NEVER_TRUE]),
                             rng.choice([1.0, 2.0, 3.0]), rng.randint(0, 3), "ev")
        rd = {"key": r.key, "value": r.value, "source": r.source, "member": r.source_member_id, "cause": r.cause,
              "observed_at": r.observed_at, "observed_seq": r.observed_seq, "evidence_id": r.evidence_id,
              "merge_ids": r.merge_ids}
        apply_retraction(r, c1, NOW)
        Memory._apply_retraction_record(None, rd, c2, NOW)
        assert c1.state == c2.state


def _rand_claim(rng):
    content = ClaimContent("c", "s1", rng.choice(["m1", "m2"]), "o1", "a1", "k", ("text", rng.choice("ab")),
                           rng.choice(["USER", "OPERATOR"]), "stated", "verified", None, (), None, None, None,
                           rng.choice([1.0, 2.0, 3.0]), 0.0, "x", 1, observed_seq=rng.randint(0, 3))
    st = ClaimState()
    if rng.random() < 0.3:
        apply_retraction(RetractionRecord("r0", "s1", "k", content.value, content.source, content.source_member_id,
                                          rng.choice([NO_LONGER_TRUE, NEVER_TRUE]), 3.0, 3, "ev0"),
                         Claim(content, st), 1.0)
    return Claim(content, st)


# ------------------------------------------------------------------------------------------------- rebuild / replay
def test_rebuilt_projection_equals_live_projection():
    store = CommitStore()
    gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E)
    gate_and_commit(store, proposal("p2", "delhi", "I moved to Delhi", eid="e2"), E)
    rebuilt = rebuild_claims(store.journal)
    assert rebuilt == store.claims
    assert current(rebuilt.values()).slot == current(store.claims.values()).slot


def test_replay_applies_recorded_decision_not_todays_policy():
    store = CommitStore()
    gate_and_commit(store, proposal("p1", "pune", "I live in Pune"), E)
    # today's policy would refuse the same proposal (LLM writes now forbidden) ...
    reg2 = PolicyRegistry(allow_test_only=True)
    reg2.publish(dataclasses.replace(CITY, policy_version_id=4, allowed_writers=frozenset({"operator"}),
                                     llm_write_mode="FORBIDDEN"))
    pr = proposal("p1", "pune", "I live in Pune")
    assert decide(dataclasses.replace(pr, policy_version_id=4), reg2, E, current(), NOW).decision != ACCEPT
    # ... but replay applies the RECORDED outcome, so history is unchanged
    assert rebuild_claims(store.journal) == store.claims
    assert all(c.content.policy_version == 3 for c in rebuild_claims(store.journal).values())


@pytest.mark.parametrize("seed", range(40))
def test_property_rebuild_equals_live(seed):
    rng = random.Random(seed)
    store = CommitStore()
    texts = {"pune": "I live in Pune", "delhi": "I moved to Delhi", "goa": "now in Goa"}
    for i in range(25):
        op = rng.random()
        if op < 0.6:
            v = rng.choice(list(texts))
            eid = f"e{seed}_{i}"
            evid = {eid: ev(eid, texts[v], member=rng.choice(["m1", "m2"]), observed=rng.uniform(1, 90),
                            seq=rng.randint(1, 9))}
            pr = proposal(f"p{rng.randint(0, 12)}", v, texts[v], eid=eid)        # id collisions are deliberate
            out = decide(pr, REG, evid, current(store.claims.values()), NOW)
            crash = rng.choice([None, None, "before_write", "after_write"])
            try:
                commit(store, pr, out, evid, ctx(), subject_key, NOW, crash=crash)
            except (CrashBeforeWrite, CrashAfterWrite):
                pass
        elif op < 0.85:
            v = rng.choice(list(texts))
            retract(store, RetractionRecord(f"r{rng.randint(0, 6)}", "s1", "TEST_ONLY_city", ("text", v), "USER",
                                            rng.choice(["m1", "m2"]), rng.choice([NO_LONGER_TRUE, NEVER_TRUE]),
                                            rng.uniform(1, 90), rng.randint(1, 9), "er"), NOW)
        elif store.claims:
            lifecycle(store, rng.choice(sorted(store.claims)), rng.choice([INVALIDATED, ACTIVE, QUARANTINED]),
                      "prop", NOW)
    assert rebuild_claims(store.journal) == store.claims
    assert current(rebuild_claims(store.journal).values()).slot == current(store.claims.values()).slot
    assert len({r.claim_id for r in store.records.values() if r.claim_id}) == len(store.claims)
