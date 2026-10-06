"""Incremental checkpoint signature v1: feasibility evidence. TEST_ONLY.

Result under test: the EXISTING canonical signature (SHA-256 over repr of one canonical tuple) cannot be computed
incrementally and exactly. Every checkpoint advance changes the first 64-byte block of the hashed input (the
covered position c is its second element), and SHA-256 can only be resumed over an unchanged prefix. So the
definition is kept unchanged, nothing is optimised, and replacing the definition is an owner decision
(``investigation/cto-owner-decision-request-v1.md``).

These tests pin:
- the impossibility evidence (first changed byte of the input, on both stores);
- that the canonical signature is still exactly what it was (no silent redefinition);
- that the CURRENT signature detects corruption of every field it covers, and that the fields it does not cover
  are caught by their own validation checks;
- that identity is semantic, not serializer layout (full, compact, incremental, fresh: one signature).
Contract: ``investigation/incremental-checkpoint-signature-v1.md``."""
import copy
import dataclasses
import hashlib
import pickle

import pytest

from memory_core import episode_commitment as EC
from memory_core import journal_compaction as JC
from memory_core.model import QUARANTINED
from test_durable_journal_conformance import history
from test_durable_storage_boundary import make
from test_integration import CITY, NOTE
from test_journal_compaction import KEY, act, ev, gen, instants, load, retract, same, sync
from test_x1_commit_time import put

KINDS = ["explicit", "implied"]


def canonical_input(f):
    """The exact byte string ``state_signature`` hashes (kept literally, to pin the definition)."""
    canon = (f.subject, f.at, f.position, f.erased, f.cv, sorted(f.versions.items()), sorted(f.last.items()),
             sorted(f.in_force.items()), sorted(f.pending), sorted(f.sync.items()),
             sorted((k, tuple(v)) for k, v in f.trace.items()), sorted((k, repr(c)) for k, c in f.claims.items()),
             repr(f.retractions), repr(f.events), sorted((k, repr(g)) for k, g in f.generations.items()),
             sorted(f.predicates))
    return repr(canon).encode()


# ============================================================================================ 1. impossibility
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(4))
def test_every_checkpoint_advance_changes_the_first_block_of_the_signature_input(kind, seed):
    """SHA-256 (Merkle-Damgard, 64-byte blocks) can be resumed only over an unchanged byte prefix. If every advance
    changes the first block, an exact incremental reproduction must re-hash the whole input."""
    st = load(kind, history(seed))
    ts = instants(st.facts())
    for subj in ("s1", "s2"):
        for a, b in zip(ts, ts[1:]):
            x = canonical_input(JC.build_fold(st.facts(), subj, a))
            y = canonical_input(JC.build_fold(st.facts(), subj, b))
            if x != y:
                first = next(i for i in range(min(len(x), len(y))) if x[i] != y[i])
                assert first < 64, (subj, a, b, first)


def test_the_canonical_signature_is_still_exactly_sha256_of_the_canonical_input():
    """No silent redefinition: the identity is what compaction v1 defined."""
    st = load("explicit", history(1))
    ts = instants(st.facts())
    for c in (ts[0] - 1.0, ts[len(ts) // 2], ts[-1]):
        f = JC.build_fold(st.facts(), "s1", c)
        assert JC.state_signature(f) == hashlib.sha256(canonical_input(f)).hexdigest()


# ============================================================================================ 2. detection today
def rich_fold(kind):
    wr, j = make(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "c2", CITY, "goa", 2.0, valid_from=50.0)              # a pending boundary
    put(j, wr, "n1", NOTE, "allergic", 3.0)
    retract(j, wr, "r1", "pune", 4.0)
    sync(j, wr, "sy1", 3.5, 5.0)
    cid = next(iter(JC.full_replay(j.store.facts(), "s1", 9e9).claims))
    j.commit("s1", "lc1", CITY.predicate, wr.stamp(CITY), 6.0,
             act(wr, "s1", lambda at: wr.w.p.lifecycle(cid, QUARANTINED, "gen", at)))
    EC.record_commitment_event(j, KEY, ev("x1", "k1", "create", 6.5, "agent"), 6.5)
    EC.record_episode_generation(j, KEY, gen("ep1", ["e1"], "a recap"), 7.0)
    f = JC.build_fold(j.store.facts(), "s1", 10.0)
    assert f.claims and f.retractions and f.events and f.generations and f.pending and f.sync and f.trace
    return j, f


def corrupt(f, field):
    g = copy.deepcopy(f)
    c = next(iter(g.claims.values()))
    k = next(iter(g.trace))
    if field == "claim value":
        object.__setattr__(c, "content", dataclasses.replace(c.content, value=("text", "atlantis")))
    elif field == "claim lifecycle state":
        c.state.status = "active" if c.state.status != "active" else "invalidated"
    elif field == "claim transitions":
        c.state.transitions = c.state.transitions[:-1] if c.state.transitions else ["x"]
    elif field == "retraction":
        g.retractions = []
    elif field == "commitment event":
        g.events = []
    elif field == "episode generation":
        g.generations = {k2: dataclasses.replace(v, summary="forged") for k2, v in g.generations.items()}
    elif field == "predicate":
        g.predicates = tuple(sorted(set(g.predicates) | {"TEST_ONLY_forged"}))
    elif field == "trace element":
        g.trace[k] = g.trace[k][:-1] + [(g.trace[k][-1][0], ("FORGED",))]
    elif field == "version":
        g.versions[k] += 1
    elif field == "last signature":
        g.last[k] = ("FORGED",)
    elif field == "version in force":
        p = next(iter(g.in_force))
        g.in_force[p] += 1
    elif field == "pending boundary":
        g.pending = []
    elif field == "freshness":
        p = next(iter(g.sync))
        g.sync[p] += 1.0
    elif field == "claims version":
        g.cv += 1
    elif field == "erased":
        g.erased = not g.erased
    elif field == "position":
        g.position += 1
    elif field == "covered position":
        g.at += 1.0
    elif field == "partition":
        g.subject = "s2"
    return g


COVERED = ["claim value", "claim lifecycle state", "claim transitions", "retraction", "commitment event",
           "episode generation", "predicate", "trace element", "version", "last signature", "version in force",
           "pending boundary", "freshness", "claims version", "erased", "position", "covered position", "partition"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("field", COVERED)
def test_the_current_signature_detects_corruption_of_every_field_it_covers(kind, field):
    _, f = rich_fold(kind)
    assert JC.state_signature(corrupt(f, field)) != JC.state_signature(f)


@pytest.mark.parametrize("kind", KINDS)
def test_fields_outside_the_signature_are_caught_by_their_own_checks(kind):
    """The reference fields, policy position, partition, contract and encoding are not hashed; each is validated
    by another check, so a corrupted copy is still never used."""
    j, _ = rich_fold(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    _, cp = JC.create(j, cps, "s1", 11.0)
    k = ("key:s1", cp.ref)
    good = j.store.vault[k]
    for case, expect in (("policy_position", "policy_log_changed"), ("contract", "contract_version"),
                         ("encoding", "encoding"), ("partition", "wrong_partition"), ("claim ref", "state_signature")):
        j.store.vault[k] = good
        cps.unusable.clear()
        if case == "claim ref":                                       # point a claim at another sealed fact
            raw = pickle.loads(good)
            (i0, r0), s0 = raw["claims"][0]
            (i1, r1), _ = raw["claims"][1]
            raw["claims"][0] = ((i1, r1), s0)
            blob = pickle.dumps(raw)
            j.store.vault[k] = blob
            cps.index["s1"] = [dataclasses.replace(cp, blob_digest=JC._sha(blob))]
        elif case == "partition":
            cps.index["s1"] = [dataclasses.replace(cp, partition="s2")]
        else:
            value = {"policy_position": (0, "x"), "contract": "journal-compaction-v0", "encoding": "zip"}[case]
            cps.index["s1"] = [dataclasses.replace(cp, **{case: value})]
        same(j.store.facts(), "s1", j.read("s1", 12.0).r, cps, expect="full")
        assert cps.rejections[-1][1] == expect, case


# ============================================================================================ 3. canonical identity
@pytest.mark.parametrize("kind", KINDS)
def test_full_compact_incremental_and_fresh_checkpoints_share_one_canonical_signature(kind):
    """Serialized bytes differ (encoding, object-sharing layout); the canonical identity does not."""
    wr, j = make(kind)
    full = JC.CheckpointStore(j.store)
    ref = JC.CheckpointStore(j.store, encoding="ref")
    j.checkpoints = full
    put(j, wr, "c0", CITY, "pune", 1.0)
    JC.maintain(j, full, "s1", 1.5, threshold=0)
    JC.maintain(j, ref, "s1", 1.5, threshold=0)
    for i in range(1, 5):
        put(j, wr, f"c{i}", [CITY, NOTE][i % 2], ["goa", "delhi"][i % 2], 1.0 + i)
        _, a = JC.maintain(j, full, "s1", 1.5 + i, threshold=1)     # incremental, full encoding
        _, b = JC.maintain(j, ref, "s1", 1.5 + i, threshold=1)      # incremental, compact encoding
        _, fresh = JC.checkpoint_at(j.store.facts(), JC.CheckpointStore(j.store), "s1", b.covered_at,
                                    incremental=False)
        assert b.state_signature == fresh.state_signature
        if a.covered_at == b.covered_at:
            assert a.state_signature == b.state_signature
        assert j.store.vault[("key:s1", b.ref)] != j.store.vault[("key:s1", fresh.ref)]   # bytes differ
