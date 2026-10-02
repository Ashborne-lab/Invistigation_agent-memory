"""Seeded adversarial sequences (the stdlib stands in for hypothesis, which is not installed).

After every operation the invariants must hold:
- no active claim without live support; no active claim under an erased subject;
- the head always equals a rebuild (projection determinism);
- retrieval and manifests never contain quarantined, erased, pending-erasure or foreign-subject claims;
- re-committing the same job is idempotent;
- no resurrection after forget-me.
"""
import random

import pytest

from conftest import P, World

VALUES = {"residence.city": ["Delhi", "Mumbai", "Pune", "Gurugram"], "diet.pattern": ["vegan", "vegetarian"],
          "note.pet": ["dog", "cat"]}
USERS = ["alice", "bob", "carol"]
OPS = ["assert", "assert", "assert", "retract", "merge", "undo", "erase_ev", "forget_fact", "retry", "forget_me"]


def _check(w, now, erased):
    v = w.m.invariants(now)
    assert not v, v
    for s, h in w.m.heads.items():
        if h.status != "active":
            continue
        text, man = w.m.build_context(w.caller, s, now)
        members = set(w.m.members(s))
        for cid, _ in man.claims:
            c = w.m.claims[cid]
            assert c.content.subject_id in members, "cross-subject context"
            assert c.state.status not in ("quarantined", "pending_erasure", "invalidated"), c.state.status
            assert c.state.attributed
    for s in erased:
        assert not [c for c in w.m.claims.values() if c.content.subject_id == s and c.state.status == "active"]


@pytest.mark.parametrize("cfg", ["spec", "amended"])
@pytest.mark.parametrize("seed", range(int(__import__("os").environ.get("PROP_SEEDS", "40"))))
def test_random_sequences_hold_invariants(seed, cfg):
    from memory_core.config import AMENDED, DEFAULT
    rnd = random.Random(seed)
    w = World(DEFAULT if cfg == "spec" else AMENDED)
    t = 1.0
    subj, merges, erased, last = {}, [], set(), {}
    for step in range(40):
        t += rnd.choice([0.1, 1, 5])
        op = rnd.choice(OPS)
        u = rnd.choice(USERS)
        if op in ("assert", "retract"):
            key = rnd.choice(list(VALUES))
            val = rnd.choice(VALUES[key])
            text = ("I no longer %s %s" if op == "retract" else "my %s is %s") % (key, val)
            ev = w.say(u, text, t)
            subj[u] = ev.subject_id
            pr = P(key, val, ev, quote=val, op=op, cause=rnd.choice(["no_longer_true", "never_true"])
                   if op == "retract" else None, expr="present" if op == "assert" else None)
            job = w.m.prepare(ev.subject_id)
            last[u] = (job, [pr])
            w.m.commit(job, [pr], t)
        elif op == "merge" and len(subj) >= 2:
            a, b = rnd.sample(sorted(subj.values()), 2)
            if w.m.root(a) != w.m.root(b) and all(w.m.heads[x].status == "active" for x in (a, b)):
                merges.append(w.m.merge(w.m.root(b), w.m.root(a), t))
        elif op == "undo" and merges:
            mid = merges.pop(rnd.randrange(len(merges)))
            if mid not in w.m.merges_undone:
                w.m.undo_merge(mid, t)
        elif op == "erase_ev" and w.m.evidence:
            w.m.erase_evidence(rnd.choice(sorted(w.m.evidence)), t)
        elif op == "forget_fact" and u in subj and w.m.heads[subj[u]].status == "active":
            key = rnd.choice(list(VALUES))
            w.m.forget_fact(subj[u], key, rnd.choice(VALUES[key]), t)
        elif op == "retry" and u in last:
            job, pr = last[u]
            for e in job.evidence_ids:
                if e in w.m.evidence and w.m.evidence[e].extraction_state == "done":
                    w.m.evidence[e].extraction_state = "pending"
            w.m.commit(job, pr, t)                       # a late replay may legitimately change state...
            snap = {c: (x.state.status, len(x.state.support)) for c, x in w.m.claims.items()}
            for e in job.evidence_ids:
                if e in w.m.evidence and w.m.evidence[e].extraction_state == "done":
                    w.m.evidence[e].extraction_state = "pending"
            w.m.commit(job, pr, t)                       # ...but an immediate second commit must change nothing
            after = {c: (x.state.status, len(x.state.support)) for c, x in w.m.claims.items()}
            assert snap == after, "retry was not idempotent"
        elif op == "forget_me" and u in subj and w.m.heads[subj[u]].status == "active":
            erased |= set(w.m.members(subj[u]))
            w.m.forget_me(subj[u], t)
            subj.pop(u)
        _check(w, t, erased)


def test_commutativity_of_independent_commits():
    def run(order):
        w = World()
        e1 = w.say("u1", "I'm vegetarian", 1)
        e2 = w.say("u1", "I have a dog", 1.5)
        s = e1.subject_id
        jobs = {1: (w.m.prepare(s, [e1.evidence_id]), [P("diet.pattern", "vegetarian", e1)]),
                2: (w.m.prepare(s, [e2.evidence_id]), [P("note.pet", "dog", e2, quote="I have a dog")])}
        for k in order:
            w.m.commit(*jobs[k], 2)
        slots = {k: (v[0], v[1]) for k, v in w.m.rebuild_head(s, 3).items()}      # ids are keyed per run
        return sorted((c.content.key, c.content.value, c.state.status) for c in w.m.claims.values()), slots
    assert run([1, 2]) == run([2, 1])


def test_two_turns_same_predicate_order_independent():
    """Race B: commit order must not decide the winner; observed_at does."""
    def run(order):
        w = World()
        e1 = w.say("u1", "I live in Delhi", 1)
        e2 = w.say("u1", "I live in Mumbai", 2)
        s = e1.subject_id
        j1 = (w.m.prepare(s, [e1.evidence_id]), [P("residence.city", "Delhi", e1, quote="Delhi", expr="present")])
        j2 = (w.m.prepare(s, [e2.evidence_id]), [P("residence.city", "Mumbai", e2, quote="Mumbai", expr="present")])
        for j in (order and [j1, j2] or [j2, j1]):
            w.m.commit(*j, 3)
        return w.cur(s, "residence.city", now=4).value
    assert run(True) == run(False) == ("text", "mumbai")
