"""Lane A1 property suite: try to FALSIFY the reviewed architecture with randomised sequences.

Operations interleave: delayed registration (PG lag), sealing and seal sweeps, in-place edits and deletes,
extraction (assert/retract, valid and invalid proposals), retries, provider redelivery, merges, undos,
Q17 recovery, forget-me, forget-fact, evidence erasure, re-extraction by a new version, handle reads with
swapped subjects, commitment events in shuffled order, and context builds whose manifests are replayed.

The 12 invariants required by the Lane A brief are checked after EVERY operation (AMENDED). The same
generator is run under DEFAULT to show the suite has teeth: it must find violations there.
"""
import os
import random

import pytest

from conftest import ORG, P, World
from memory_core import commitments as CM
from memory_core.config import AMENDED, DEFAULT
from memory_core.model import ACTIVE, QUARANTINED, RETRACTED

SEEDS = int(os.environ.get("PROP_SEEDS", "40"))
STEPS = int(os.environ.get("PROP_STEPS", "80"))
VALUES = {"residence.city": ["Delhi", "Mumbai", "Pune"], "diet.pattern": ["vegan", "vegetarian"],
          "note.pet": ["dog", "cat"], "travel.planned": ["Goa", "Pune"]}
USERS = ["alice", "bob", "carol", "dave"]


class Run:
    def __init__(self, d, seed):
        self.w = World(d)
        self.m = self.w.m
        self.r = random.Random(seed)
        self.t = 1.0
        self.subj = {}
        self.merges = []
        self.undone = []
        self.erased = set()
        self.last_job = {}
        self.manifests = []          # (t, subject, block_hash, destructive_count)
        self.destructive = 0
        self.cevents = []
        self.intent = {}             # evidence id -> (key, value, form)

    # --- helpers
    def _user_ev(self, u):
        s = self.subj.get(u)
        if s is None:
            return []
        return [e for e in self.m.ev_seq if self.m.evidence[e].subject_id == s
                and self.m.evidence[e].author_role == "user" and self.m.evidence[e].registered]

    def step(self):
        r, m = self.r, self.m
        self.t += r.choice([0.01, 0.5, 1, 3])
        t = self.t
        u = r.choice(USERS)
        op = r.choice(["say", "say", "say", "write_late", "register", "seal_sweep", "extract", "extract", "extract",
                       "say", "extract", "extract", "extract",
                       "retry", "redeliver", "edit", "delete", "merge", "undo", "recover", "forget_me",
                       "forget_fact", "erase_ev", "reextract", "swap_handle", "commit_ev", "context"])
        if op in ("say", "write_late", "redeliver"):
            key = r.choice(list(VALUES))
            val = r.choice(VALUES[key])
            form = r.choice(["assert", "assert", "assert", "retract", "future"])
            text = {"assert": "my %s is %s", "retract": "I no longer %s %s", "future": "next month %s %s"}[form] % (
                key.split(".")[-1], val)
            pid = "pm-%s-%d" % (u, r.randrange(3)) if op == "redeliver" else None
            if op == "write_late":
                ev = m.write_message(ORG, "agentA", "wa", u, "s-" + u, "user", text, t, provider_msg_id=pid)
            else:
                ev = m.ingest(ORG, "agentA", "wa", u, "s-" + u, "user", text, t, provider_msg_id=pid)
            self.intent.setdefault(ev.evidence_id, (key, val, form))
            if ev.subject_id and m.heads[ev.subject_id].status == "active":
                self.subj[u] = ev.subject_id
        elif op == "register":
            pend = [e for e in m.ev_seq if not m.evidence[e].registered]
            if pend:
                e = r.choice(pend)
                m.register(e, t)
                m.seal(e, t)
        elif op == "seal_sweep":
            m.seal_sweep(t, 0.001)
        elif op == "extract" and u in self.subj and m.heads[self.subj[u]].status == "active":
            job = m.prepare(self.subj[u])
            if not job.evidence_ids:
                return
            ctx_user = [e for e in job.context_ids if m.evidence[e].author_role == "user"]
            evs = list(job.evidence_ids) * 3 + ctx_user          # prefer the pending evidence
            props = []
            for _ in range(r.randint(1, 3)):
                eid = r.choice(evs)
                ev = m.evidence[eid]
                if eid in self.intent and r.random() < 0.85:           # mostly faithful proposals
                    key, val, form = self.intent[eid]
                    opx = "retract" if form == "retract" else "assert"
                else:                                                   # adversarial / hallucinated
                    key = r.choice(list(VALUES))
                    val = r.choice(VALUES[key])
                    opx = r.choice(["assert", "assert", "retract"])
                props.append(P(key, val, ev, quote=val, op=opx,
                               cause=r.choice(["no_longer_true", "never_true"]) if opx == "retract" else None,
                               expr=r.choice([None, "present"]) if opx == "assert" else None))
            self.last_job[u] = (job, props)
            m.commit(job, props, t)
        elif op == "retry" and u in self.last_job:
            job, props = self.last_job[u]
            for e in job.evidence_ids:
                if e in m.evidence and m.evidence[e].extraction_state == "done":
                    m.evidence[e].extraction_state = "pending"
            m.commit(job, props, t)
            snap = {c: (x.state.status, len(x.state.support)) for c, x in m.claims.items()}
            for e in job.evidence_ids:
                if e in m.evidence and m.evidence[e].extraction_state == "done":
                    m.evidence[e].extraction_state = "pending"
            m.commit(job, props, t)
            assert snap == {c: (x.state.status, len(x.state.support)) for c, x in m.claims.items()}, "INV8 retry"
        elif op in ("edit", "delete") and m.ev_seq:
            e = r.choice(m.ev_seq)
            if op == "edit":
                m.mutate_message(e, t, text=m.evidence[e].text + " (edited)")
            else:
                m.mutate_message(e, t, delete=True)
            self.destructive += 1
        elif op == "merge" and len(self.subj) >= 2:
            a, b = r.sample(sorted(self.subj.values()), 2)
            if m.root(a) != m.root(b) and all(m.heads[x].status == "active" for x in (a, b)):
                self.merges.append(m.merge(m.root(b), m.root(a), t))
                self.destructive += 1
        elif op == "undo" and self.merges:
            mid = self.merges.pop(r.randrange(len(self.merges)))
            if mid not in m.merges_undone:
                m.undo_merge(mid, t)
                self.undone.append(mid)
                self.destructive += 1
        elif op == "recover" and self.undone:
            mid = r.choice(self.undone)
            absorbed = m.merges[mid]["absorbed"]
            if m.heads[absorbed].status == "active":
                job = m.recovery_job(mid, absorbed)
                props = [P(k, v, m.evidence[e], quote=v) for e in job.evidence_ids
                         for k, vs in VALUES.items() for v in vs if v.lower() in m.evidence[e].text.lower()][:2]
                rep = m.commit(job, props, t)
                quarantined = {c for c, x in m.claims.items() if x.state.status == QUARANTINED}
                assert not (set(rep.created) & quarantined), "INV7 recovery reused a quarantined id"
                for cid in rep.created:
                    assert m.claims[cid].content.derivation.startswith("recovery:"), "INV7 derivation"
        elif op == "forget_me" and u in self.subj and m.heads[self.subj[u]].status == "active":
            self.erased |= set(m.members(self.subj[u]))
            m.forget_me(self.subj[u], t)
            self.subj.pop(u)
            self.destructive += 1
        elif op == "forget_fact" and u in self.subj and m.heads[self.subj[u]].status == "active":
            key = r.choice(list(VALUES))
            m.forget_fact(self.subj[u], key, r.choice(VALUES[key]), t)
            self.destructive += 1
        elif op == "erase_ev" and m.ev_seq:
            m.erase_evidence(r.choice(m.ev_seq), t)
            self.destructive += 1
        elif op == "reextract" and u in self.subj and m.heads[self.subj[u]].status == "active":
            evs = [e for e in self._user_ev(u) if m.evidence[e].extraction_state == "done"]
            if evs:
                e = r.choice(evs)
                key = r.choice(list(VALUES))
                val = r.choice(VALUES[key])
                job = m.reextract_job([e])
                m.commit(job, [P(key, val, m.evidence[e], quote=val)], t, extractor_version="v%d" % r.randint(2, 4),
                         reextract=True)
                self.destructive += 1
        elif op == "swap_handle" and len(self.subj) >= 2:
            a, b = r.sample(sorted(self.subj.values()), 2)
            if m.root(a) != m.root(b) and m.heads[m.root(a)].status == "active":
                ha = m.handle_for_subject(a, t)
                for key in ("residence.city", "diet.pattern"):
                    res = m.get_current_state({"handle": ha}, b, key, now=t)
                    assert res.status in ("ACCESS_DENIED", "UNAVAILABLE"), "INV9 handle crossed subjects"
                assert m.search_memory({"handle": ha}, b, "", t).status in ("ACCESS_DENIED", "UNAVAILABLE")
        elif op == "commit_ev" and m.ev_seq:
            k = "k%d" % r.randrange(3)
            kind = r.choice(["create", "confirm_tool_success", "confirm_assent", "start", "fulfil", "cancel",
                             "external_cancelled", "reopen_operator"])
            actor = r.choice(["agent", "tool", "user", "operator", "external"])
            self.cevents.append(CM.Event("ce%d" % len(self.cevents), k, kind, t, actor, r.choice(m.ev_seq),
                                         due_until=t + r.choice([0.5, 5])))
        elif op == "context" and u in self.subj and m.heads[self.subj[u]].status == "active":
            s = self.subj[u]
            _, man = m.build_context(self.w.caller, s, t)
            if man:
                self.manifests.append((t, s, man.block_hash, self.destructive))

    # --- the 12 invariants
    def check(self):
        m, d = self.m, self.m.d
        v = m.invariants(self.t)
        assert not v, ("INV1/INV3", v)                                       # 1 support, 3 head == rebuild
        for c in m.claims.values():
            if c.state.status != ACTIVE or not c.state.attributed:
                continue
            for e in c.state.support.values():                            # 2 erased evidence never supports
                ev = m.evidence.get(e.evidence_id)
                assert ev is not None and ev.status in ("active", "context_suppressed"), "INV2 dead support"
                assert m.heads[ev.subject_id].status == "active", "INV2 erased subject support"
            for mid in c.state.merge_ids:                                 # 6 undo removes merge support
                assert mid not in m.merges_undone, "INV6 claim of undone merge still active"
            for e in c.state.support.values():
                assert not (set(e.merge_ids) & m.merges_undone), "INV6 undone-merge support edge"
        for c in m.claims.values():                                       # 4, 5 bounded retraction
            for tr in c.state.transitions:
                if tr.to == RETRACTED and tr.cause in ("no_longer_true", "never_true") and tr.cause_ref in m.evidence:
                    rev = m.evidence[tr.cause_ref]
                    assert rev.observed_at >= c.content.observed_at, "INV4 retraction reached a later claim"
                    assert rev.source_member_id == c.content.source_member_id, "INV5 cross-group retraction"
        for s, h in m.heads.items():                                      # 10 retrieval never leaks
            if h.status != "active" or h.kind == "account":
                continue
            _, man = m.build_context(self.w.caller, s, self.t)
            m.manifests.pop()
            members = set(m.members(s))
            for cid, _ in man.claims:
                c = m.claims[cid]
                assert c.content.subject_id in members, "INV10 cross-subject"
                assert c.state.status not in ("quarantined", "pending_erasure", "invalidated"), "INV10 status"
        for s in self.erased:
            assert not [c for c in m.claims.values() if c.content.subject_id == s and c.state.status == ACTIVE]
        dk = [e.dedup_key for e in m.evidence.values() if e.dedup_key]   # 8 duplicates
        assert len(dk) == len(set(dk)), "INV8 duplicate provider message"
        evs = list(self.cevents)                                          # 11 commitments deterministic
        base = CM.project(evs, self.t)
        self.r.shuffle(evs)
        assert {k: h.state for k, h in CM.project(evs, self.t).items()} == {k: h.state for k, h in base.items()}, \
            "INV11 commitment projection depends on delivery order"

    def check_replay(self):
        for t0, s, bh, dc in self.manifests:                              # 12 manifests reproduce
            if dc != self.destructive or self.m.heads[s].status != "active":
                continue
            _, man = self.m.build_context(self.w.caller, s, t0)
            assert man.block_hash == bh, "INV12 manifest replay differs"


@pytest.mark.parametrize("seed", range(SEEDS))
def test_amended_invariants_hold_under_random_sequences(seed):
    run = Run(AMENDED, seed)
    for _ in range(STEPS):
        run.step()
        run.check()
    run.check_replay()


def test_default_generator_has_teeth():
    """The same generator must find violations under DEFAULT (otherwise the suite proves nothing)."""
    found = set()
    for seed in range(SEEDS):
        run = Run(DEFAULT, seed)
        try:
            for _ in range(STEPS):
                run.step()
                run.check()
        except AssertionError as e:
            found.add(str(e.args[0])[:20] if e.args else "assert")
    assert found, "DEFAULT produced no violations: the generator is too weak"
