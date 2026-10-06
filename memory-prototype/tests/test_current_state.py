"""Current State projection. Policies are TEST_ONLY_* (placeholder governance values; never production policy).
Journals are produced through the real gate and commit layer (C-D: a hand-built decision cannot be committed).
Freshness comes only from journaled sync events (C-C)."""
import inspect
import random

import pytest

from memory_core.claimgate import Proposal, decide
from memory_core.commit import CommitStore, RetractionRecord, SyncRecord, commit, lifecycle, record_sync, retract
from memory_core.config import AMENDED
from memory_core.fence import Context
from memory_core.model import (CONFLICT, EXPLICIT_NONE, NEVER_TRUE, NO_LONGER_TRUE, PENDING_ERASURE, QUARANTINED,
                               INVALIDATED, ACTIVE, UNKNOWN, VALUE, Evidence)
from memory_core.registry import ConflictPolicy, FreshnessContract, PolicyRegistry, PredicatePolicy, resolve_slot
from memory_core.state import project_subject, slot_versions

R = "TEST_ONLY_RETENTION"
OPS = {VALUE: frozenset({"SET"}), EXPLICIT_NONE: frozenset({"SET"}), UNKNOWN: frozenset({"SET", "ESTABLISH"}),
       CONFLICT: frozenset({"RESOLVE_CONFLICT"})}


def P(name, card="SINGLE", ranks=None, **kw):
    ranks = ranks or {"USER": 1, "OPERATOR": 1, "HR_SYSTEM": 5}
    ops = {VALUE: frozenset({"ADD"}), UNKNOWN: frozenset({"ADD"})} if card == "SET" else OPS
    return PredicatePolicy(f"TEST_ONLY_{name}", 7, card, frozenset({"llm_extractor", "operator", "system_sync"}),
                           frozenset(ranks), ops, "TEST_ONLY_DOMAIN", ranks, retention_class=R,
                           llm_write_mode="PROPOSE_VIA_GATE", **kw)


CITY = P("city")
EMPLOYER = P("employer")
LANGS = P("langs", "SET")
PREFS = P("prefs", "MAP", map_keys=frozenset({"email", "sms"}))
ORDER = P("order", "STATE_MACHINE", ranks={"OPERATOR": 1},
          transitions={"placed": frozenset({"paid"}), "paid": frozenset()}, initial_states=frozenset({"placed"}))
BILL = P("bill", ranks={"OPERATOR": 1},
         freshness=FreshnessContract(max_staleness=1, stale_read_policy="DISPLAY_ONLY",
                                     stale_write_policy="WRITE_FORBIDDEN", freshness_source="external_sync"))
POLICIES = {p.predicate: p for p in (CITY, EMPLOYER, LANGS, PREFS, ORDER, BILL)}
ROLE = {"USER": "user", "OPERATOR": "operator", "HR_SYSTEM": "tool"}


def ctx(**kw):
    base = dict(epoch_log={}, merged_into={}, merges_undone=set(), subject_erased_at={}, org_erased_at={},
                org_of={"s1": "o1", "s2": "o1"}, known_subjects={"s1", "s2"})
    base.update(kw)
    return Context(**base)


class W:
    """A world: a commit store, plus helpers that append through the real commit protocol."""

    def __init__(self):
        self.store, self.n, self.t = CommitStore(), 0, 1.0
        self.reg, self.ledger = PolicyRegistry(allow_test_only=True), {}

    def _policy(self, pol):
        try:
            return self.reg.get(pol.predicate)
        except KeyError:
            self.reg.publish(pol)
            return self.reg.get(pol.predicate)

    def put(self, pol, value, source="USER", member=None, observed=None, kind="text", map_key=None, subj="s1",
            fctx=None, valid_from=None, valid_until=None, expect_reject=False):
        self.n += 1
        self.t = observed if observed is not None else self.t + 1
        eid, pid = f"e{self.n}", f"p{self.n}"
        member = member or source.lower()
        ev = Evidence(eid, "o1", subj, member, "a1", "sess", ROLE[source], f"v {value}", self.t,
                      {"org": 0, "subject": 0, "session": 0}, source_system="HR_SYSTEM", receipt_seq=self.n)
        gp = self._policy(pol)
        pr = Proposal(pid, subj, "o1", gp.predicate, gp.policy_version_id, "SET", "llm_extractor", source,
                      (kind, value), ((eid, f"v {value}"),), map_key=map_key, valid_from=valid_from,
                      valid_until=valid_until)
        mine = [c for c in self.store.claims.values() if c.content.subject_id == subj]
        current = resolve_slot(gp, mine, self.t, self.t, AMENDED, self.t)
        out = decide(pr, self.reg, {eid: ev}, current, self.t, self.ledger)       # the REAL gate (C-D)
        res = commit(self.store, pr, out, {eid: ev}, fctx or ctx(), lambda s: s.encode() * 4, self.t)
        if expect_reject:
            assert res.record is None or res.record.claim_id is None, "gate should have refused"
            return out
        assert res.record is not None and res.record.claim_id, (out.decision, out.reason, res.reason)
        return res.record.claim_id

    def sync(self, pol, at, sid=None, subj="s1"):
        self.n += 1
        record_sync(self.store, SyncRecord(sid or f"sy{self.n}", subj, pol.predicate, "TEST_ONLY_sync", at),
                    max(self.t, at))

    def retract(self, pol, value, source="USER", member=None, cause=NO_LONGER_TRUE, kind="text", rid=None):
        self.n += 1
        self.t += 1
        retract(self.store, RetractionRecord(rid or f"r{self.n}", "s1", pol.predicate, (kind, value), source,
                                             member or source.lower(), cause, self.t, self.n, f"er{self.n}"), self.t)

    def life(self, cid, to):
        self.t += 1
        lifecycle(self.store, cid, to, "test", self.t)

    def project(self, subj="s1", as_of=None, now=None, incremental=False, policies=None):
        j = self.store.journal
        now = self.t if now is None else now
        return project_subject([e for e in j if e.kind == "claim"], [e for e in j if e.kind != "claim"],
                               policies or POLICIES, as_of if as_of is not None else now, now, subject=subj,
                               incremental=incremental)


# ------------------------------------------------------------------------------------------------- edge cases
def test_first_claim_creates_a_slot():
    w = W()
    w.put(CITY, "pune")
    s = w.project().slot(CITY.predicate)
    assert (s.status, s.value, s.state_version, s.policy_version, s.scope) == (
        VALUE, ("text", "pune"), 1, 7, ("CUSTOMER", "s1"))
    assert s.winning_claim_ids and s.usage == "OPERATIONAL"


def test_supporting_same_value_claim_does_not_advance_state_version():
    w = W()
    w.put(CITY, "pune", member="m1")
    w.put(CITY, "pune", member="m2")                 # independent, same value
    cs = w.project()
    s = cs.slot(CITY.predicate)
    assert s.value == ("text", "pune") and len(s.winning_claim_ids) == 2
    assert s.state_version == 1 and cs.claims_version == 2   # claims_version moved, state_version did not


def test_higher_authority_changes_value_and_version():
    w = W()
    w.put(EMPLOYER, "acme")
    w.put(EMPLOYER, "globex", source="HR_SYSTEM")
    s = w.project().slot(EMPLOYER.predicate)
    assert (s.value, s.source, s.state_version) == (("text", "globex"), "HR_SYSTEM", 2)
    w.put(EMPLOYER, "initech")                       # lower authority: no change
    assert w.project().slot(EMPLOYER.predicate).state_version == 2


def test_equal_authority_disagreement_is_conflict_never_a_winner():
    w = W()
    w.put(CITY, "pune", source="USER")
    w.put(CITY, "delhi", source="OPERATOR")
    s = w.project().slot(CITY.predicate)
    assert s.status == CONFLICT and s.value is None and len(s.conflict_claim_ids) == 2 and s.state_version == 2
    w.put(CITY, "delhi", source="OPERATOR", member="op2")   # same conflicting values, another supporter
    assert w.project().slot(CITY.predicate).state_version == 2
    w.put(CITY, "goa", source="OPERATOR")                   # same source group supersedes delhi -> pune vs goa
    s2 = w.project().slot(CITY.predicate)
    assert s2.status == CONFLICT and s2.state_version == 3  # the conflicting VALUE set changed


def test_retraction_rebuilds_correctly():
    w = W()
    w.put(CITY, "pune")
    w.retract(CITY, "pune")
    live, rebuilt = w.project(incremental=True), w.project()
    assert live == rebuilt
    s = live.slot(CITY.predicate)
    assert s.status == UNKNOWN and s.state_version == 2


def test_supersession_across_time_is_bitemporal():
    w = W()
    w.put(CITY, "pune", observed=10)
    w.put(CITY, "delhi", observed=20, valid_from=20)
    assert w.project().slot(CITY.predicate).value == ("text", "delhi")
    past = w.project(as_of=15, now=w.t)
    assert past.slot(CITY.predicate).value == ("text", "pune")
    assert past.slot(CITY.predicate).state_version == w.project().slot(CITY.predicate).state_version  # history-based


def test_stale_value_is_kept_with_usage_label_and_freshness_is_not_validity():
    w = W()
    w.put(BILL, "gurgaon", source="OPERATOR", observed=10)
    w.sync(BILL, 8)
    stale = w.project(now=10).slot(BILL.predicate)                         # last recorded sync 2 days ago
    w.sync(BILL, 10)
    fresh = w.project(now=10).slot(BILL.predicate)
    assert (fresh.freshness_status, fresh.usage) == ("FRESH", "OPERATIONAL")
    assert (stale.status, stale.value, stale.freshness_status, stale.usage) == (
        VALUE, ("text", "gurgaon"), "STALE", "DISPLAY_ONLY")
    assert fresh.state_version == stale.state_version and fresh.valid_from == stale.valid_from


@pytest.mark.parametrize("to", [QUARANTINED, PENDING_ERASURE, INVALIDATED])
def test_excluded_lifecycle_never_becomes_current_state(to):
    w = W()
    cid = w.put(CITY, "pune")
    w.life(cid, to)
    s = w.project().slot(CITY.predicate)
    assert s.status == UNKNOWN and s.value is None and s.state_version == 2
    w.life(cid, ACTIVE)
    assert w.project().slot(CITY.predicate).value == ("text", "pune")
    assert w.project(incremental=True) == w.project()


def test_merge_projects_on_survivor_and_undone_merge_stays_out():
    w = W()
    w.put(CITY, "pune", fctx=ctx(merged_into={"s1": ("s2", "mg1")}))
    assert w.project(subj="s2").slot(CITY.predicate).value == ("text", "pune")
    assert not w.project(subj="s1").slots
    w2 = W()
    w2.put(CITY, "pune", fctx=ctx(merged_into={"s1": ("s2", "mg1")}, merges_undone={"mg1"}))
    assert w2.project(subj="s1").slot(CITY.predicate).status == UNKNOWN      # quarantined, unattributed
    assert not w2.project(subj="s2").slots


def test_map_keys_project_independently():
    w = W()
    w.put(PREFS, "on", map_key="email")
    w.put(PREFS, "off", map_key="sms", source="USER")
    w.put(PREFS, "on", map_key="sms", source="OPERATOR")
    m = w.project().slot(PREFS.predicate)
    keys = dict(m.keys)
    assert keys["email"].status == VALUE and keys["sms"].status == CONFLICT
    assert keys["email"].state_version == 1 and keys["sms"].state_version == 2
    assert m.state_version == 3                                             # any key change advances the map


def test_state_machine_resolves_only_declared_states():
    w = W()
    w.put(ORDER, "placed", source="OPERATOR", kind="enum")
    assert w.project().slot(ORDER.predicate).value == ("enum", "placed")
    # an undeclared state is refused at the gate (structural rule, even for observations) and never committed;
    # the projection's own guard (registry tests) is the second line of defence
    out = w.put(ORDER, "teleported", source="OPERATOR", kind="enum", expect_reject=True)
    assert out.reason == "undeclared_state"
    assert w.project().slot(ORDER.predicate).value == ("enum", "placed")


def test_set_elements_project_and_version():
    w = W()
    w.put(LANGS, "hi")
    w.put(LANGS, "en")
    s = w.project().slot(LANGS.predicate)
    assert {e[0] for e in s.elements if e[1] == "ACTIVE"} == {"hi", "en"} and s.state_version == 2


def test_delete_and_rebuild_equals_live():
    w = W()
    for v, src in (("pune", "USER"), ("delhi", "OPERATOR"), ("goa", "USER")):
        w.put(CITY, v, source=src)
    live = w.project(incremental=True)
    del live                                                                 # projection deleted
    assert w.project() == w.project(incremental=True)


def test_unknown_predicate_is_reported_not_guessed():
    w = W()
    w.put(P("ghost"), "x")
    cs = w.project()
    assert cs.unprojected_keys == ("TEST_ONLY_ghost",) and not cs.slots


def test_projection_has_no_caller_and_is_pure():
    params = set(inspect.signature(project_subject).parameters)
    assert not params & {"caller", "principal", "authorized_scopes", "llm", "model"}
    w = W()
    w.put(CITY, "pune")
    a, b = w.project(), w.project()
    assert a == b and a is not b
    assert w.store.journal == w.store.journal                                 # projection did not mutate the journal


def test_claims_version_and_state_version_are_distinct():
    w = W()
    for m in ("m1", "m2", "m3"):
        w.put(CITY, "pune", member=m)
    cs = w.project()
    assert cs.claims_version == 3 and cs.slot(CITY.predicate).state_version == 1


# ------------------------------------------------------------------------------------------------- rebuild property
@pytest.mark.parametrize("seed", range(60))
def test_property_live_equals_rebuild(seed):
    rng = random.Random(seed)
    w = W()
    cids = []
    for _ in range(30):
        x = rng.random()
        if x < 0.55:
            pol = rng.choice([CITY, EMPLOYER, LANGS, PREFS, ORDER, BILL])
            src = rng.choice(sorted(pol.allowed_sources))
            kind = "enum" if pol is ORDER else "text"
            val = rng.choice(["placed", "paid"] if pol is ORDER else ["a", "b", "c"])
            vf = rng.choice([None, None, w.t + rng.uniform(-3, 3)])
            cids.append(w.put(pol, val, source=src, member=rng.choice([None, "x2"]), kind=kind,
                              map_key=rng.choice(["email", "sms"]) if pol is PREFS else None, valid_from=vf))
        elif x < 0.75:
            pol = rng.choice([CITY, EMPLOYER, LANGS, BILL])
            w.retract(pol, rng.choice(["a", "b", "c"]), source=rng.choice(sorted(pol.allowed_sources)),
                      cause=rng.choice([NO_LONGER_TRUE, NEVER_TRUE]))
        elif cids:
            w.life(rng.choice(cids), rng.choice([QUARANTINED, PENDING_ERASURE, INVALIDATED, ACTIVE]))
    if rng.random() < 0.7:
        w.sync(BILL, w.t - rng.choice([0, 5]))
    live = w.project(incremental=True)
    rebuilt = w.project(incremental=False)
    assert live == rebuilt
    assert w.project() == rebuilt                                              # repeatable
    for pred, s in rebuilt.slots:
        if s.status == CONFLICT:
            assert s.value is None                                             # never a silent winner
    assert slot_versions(w.store.journal, POLICIES, "s1") == slot_versions(w.store.journal, POLICIES, "s1",
                                                                            incremental=False)


def test_scheduled_value_takes_effect_without_a_commit():
    w = W()
    w.put(CITY, "pune", observed=10)
    w.put(CITY, "delhi", observed=11, valid_from=50)          # known now, effective later
    before = w.project(now=20)
    after = w.project(now=60)
    assert before.slot(CITY.predicate).value == ("text", "pune")
    assert after.slot(CITY.predicate).value == ("text", "delhi")
    assert after.slot(CITY.predicate).state_version == before.slot(CITY.predicate).state_version + 1
    assert w.project(now=60, incremental=True) == after
