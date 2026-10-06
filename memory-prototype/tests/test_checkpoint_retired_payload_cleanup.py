"""Checkpoint retired-payload storage-boundary repair v1. TEST_ONLY.

Contract (unchanged): checkpoint-maintenance-v1 §5 "Retirement removes a derived payload and marks it unusable. No
fact is ever touched."; compaction contract "deletion of a derived payload (retirement)". Defect repaired: retirement
and staged-payload drops reached into ``storage.vault`` (an in-memory dict) instead of a storage operation, so on a
database-backed store the payload row survived. Now both go through ``StorageBoundary.drop_derived`` (derived refs
only; a journal fact's payload is refused).

Stores: the explicit and implied reference stores, and PostgreSQL (the disposable C-5 cluster) when ``C5_PG_DSN`` is
set and ``psycopg`` is importable; otherwise the PostgreSQL cases are skipped (not applicable in that environment).
Physical presence is checked through ``facts().vault`` (for PostgreSQL a fresh read of ``c5.vault``) and, for
PostgreSQL, also by direct SQL as the schema owner."""
import os

import pytest

from memory_core import journal_compaction as JC
from memory_core.commit_time import JOURNAL, TimedJournal
from memory_core.durable_journal import AppendRejected, Crash
from test_durable_storage_boundary import make
from test_integration import ALL, CITY
from test_x1_commit_time import Writer, put

STORES = ["explicit", "implied", "postgres"]
ENCODINGS = ["full", "ref"]


def _pg_available():
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("C5_PG_DSN"))


def journal(kind, ns=None):
    if kind == "postgres":
        if not _pg_available():
            pytest.skip("PostgreSQL disposable cluster not available in this environment")
        from memory_core.storage_adapters.postgres_boundary import PgFrontierStore
        wr = Writer()
        ph = wr.w.p.registry._v
        j = TimedJournal(ph, JOURNAL, storage=PgFrontierStore(ph, ns=ns))
        for p in ALL:
            j.publish(p.predicate, 1, 0.0)
        return wr, j
    return make(kind)


def present(j, cp):
    return ("key:" + cp.partition, cp.ref) in j.store.facts().vault


def pg_rows(ref):
    """Rows for ``ref`` as seen by the schema owner (bypasses RLS and any in-process state)."""
    import psycopg
    dsn = os.environ["C5_PG_DSN"].replace("user=c5app", "user=c5admin")
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute("SELECT count(*) FROM c5.vault WHERE ref = %s", (ref,)).fetchone()[0]


def two_generations(kind, enc, subj="s1"):
    wr, j = journal(kind)
    cps = JC.CheckpointStore(j.store, encoding=enc)
    put(j, wr, "c1", CITY, "pune", 1.0, subj=subj)
    old = JC.maintain(j, cps, subj, 1.5, threshold=0)[1]
    put(j, wr, "c2", CITY, "goa", 2.0, subj=subj)
    new = JC.maintain(j, cps, subj, 2.5, threshold=0)[1]
    return wr, j, cps, old, new


def journal_snapshot(j):
    f = j.store.facts()
    return ({p: tuple(s.entry for s in v) for p, v in f.partitions.items()}, f.publications,
            {k: v for k, v in f.vault.items() if not k[1].startswith("ckpt:")})


# ============================================================================================ CPD-1/2/6/7/8/12
@pytest.mark.parametrize("enc", ENCODINGS)
@pytest.mark.parametrize("kind", STORES)
def test_cpd1_2_6_7_8_12_a_superseded_checkpoint_payload_is_physically_gone_and_the_active_one_serves(kind, enc):
    wr, j, cps, old, new = two_generations(kind, enc)
    assert old.ref in cps.unusable and not present(j, old)                             # CPD-1, CPD-8
    if kind == "postgres":
        assert pg_rows(old.ref) == 0 and pg_rows(new.ref) == 1                          # CPD-13
    assert present(j, new) and JC.validate(new, j.store.facts()) is None                # CPD-2
    f, r = j.store.facts(), j.read("s1", 3.0).r
    assert JC.rebuild(f, "s1", r, cps).source == "checkpoint"
    assert JC.validate(old, f) == "unreadable"                                          # CPD-12: not recoverable
    assert JC.rebuild(f, "s1", r, cps).view() == JC.full_replay(f, "s1", r).view()      # CPD-12: truth unchanged


# ============================================================================================ CPD-3 / CPD-4 / CPD-5
@pytest.mark.parametrize("kind", STORES)
def test_cpd3_retiring_one_checkpoint_never_deletes_another(kind):
    wr, j = journal(kind)
    cps = JC.CheckpointStore(j.store)
    put(j, wr, "c1", CITY, "pune", 1.0)
    a = JC.create(j, cps, "s1", 1.5)[1]
    put(j, wr, "c2", CITY, "goa", 2.0)
    b = JC.create(j, cps, "s1", 2.5)[1]
    put(j, wr, "c3", CITY, "delhi", 3.0)
    c = JC.create(j, cps, "s1", 3.5)[1]
    cps.discard(b, "superseded")
    assert not present(j, b) and present(j, a) and present(j, c)


@pytest.mark.parametrize("kind", STORES)
def test_cpd4_retirement_for_customer_x_never_deletes_customer_y(kind):
    wr, j = journal(kind)
    cps = JC.CheckpointStore(j.store)
    put(j, wr, "c1", CITY, "pune", 1.0)
    put(j, wr, "d1", CITY, "goa", 1.2, subj="s2")
    y = JC.create(j, cps, "s2", 1.5)[1]
    x_old = JC.create(j, cps, "s1", 1.5)[1]
    put(j, wr, "c2", CITY, "delhi", 2.0)
    JC.maintain(j, cps, "s1", 2.5, threshold=0)
    assert not present(j, x_old) and present(j, y) and JC.validate(y, j.store.facts()) is None
    j.store.drop_derived("key:s1", y.ref)                       # Case D: the wrong customer's key for Y's ref
    assert present(j, y)


@pytest.mark.parametrize("kind", STORES)
def test_cpd5_retirement_leaves_every_journal_fact_untouched(kind):
    wr, j = journal(kind)
    cps = JC.CheckpointStore(j.store, encoding="ref")
    put(j, wr, "c1", CITY, "pune", 1.0)
    JC.maintain(j, cps, "s1", 1.5, threshold=0)
    put(j, wr, "c2", CITY, "goa", 2.0)
    before = journal_snapshot(j)
    JC.maintain(j, cps, "s1", 2.5, threshold=0)                  # retires the first checkpoint
    cps.compact("s1")
    assert journal_snapshot(j)[:2] == before[:2]                  # entries and publications identical
    assert journal_snapshot(j)[2] == before[2]                    # every sealed FACT payload still present


@pytest.mark.parametrize("kind", STORES)
def test_the_boundary_refuses_to_delete_a_journal_fact_payload(kind):
    wr, j = journal(kind)
    put(j, wr, "c1", CITY, "pune", 1.0)
    fact_key = next(k for k in j.store.facts().vault if not k[1].startswith("ckpt:"))
    with pytest.raises(AppendRejected, match="not_a_derived_payload"):
        j.store.drop_derived(*fact_key)
    assert fact_key in j.store.facts().vault


# ============================================================================================ CPD-9 / 10 / 11
@pytest.mark.parametrize("kind", STORES)
def test_cpd9_10_11_crash_before_physical_delete_then_retry_is_safe_and_idempotent(kind):
    wr, j = journal(kind)
    cps = JC.CheckpointStore(j.store)
    put(j, wr, "c1", CITY, "pune", 1.0)
    old = JC.maintain(j, cps, "s1", 1.5, threshold=0)[1]
    put(j, wr, "c2", CITY, "goa", 2.0)
    real = j.store.drop_derived
    calls = []

    def crashing(key_id, ref):
        calls.append(ref)
        raise Crash()                                            # the process dies before the physical delete
    j.store.drop_derived = crashing
    with pytest.raises(Crash):
        JC.maintain(j, cps, "s1", 2.5, threshold=0)
    j.store.drop_derived = real
    new = cps.candidates("s1", float("inf"))[0]
    assert old.ref in cps.unusable and present(j, old)          # CPD-11: logically retired, physically not yet
    assert JC.validate(new, j.store.facts()) is None
    f, r = j.store.facts(), j.read("s1", 3.0).r
    assert JC.rebuild(f, "s1", r, cps).view() == JC.full_replay(f, "s1", r).view()   # never served meanwhile
    cps.discard(old, "superseded")                               # CPD-9: the retry
    assert not present(j, old) and present(j, new)
    cps.discard(old, "superseded")                               # CPD-10: again, a no-op
    j.store.drop_derived("key:s1", old.ref)
    assert not present(j, old) and present(j, new) and JC.validate(new, j.store.facts()) is None


# ============================================================================================ lifecycle cases A / E
@pytest.mark.parametrize("kind", STORES)
def test_case_a_a_staged_payload_that_fails_verification_is_physically_dropped(kind):
    wr, j = journal(kind)
    cps = JC.CheckpointStore(j.store)
    put(j, wr, "c1", CITY, "pune", 1.0)
    old = JC.maintain(j, cps, "s1", 1.5, threshold=0)[1]
    put(j, wr, "c2", CITY, "goa", 2.0)
    real_seal = j.store.seal

    def corrupting_seal(key_id, ref, content):
        return real_seal(key_id, ref, content[:-3] + b"bad" if ref.startswith("ckpt:") else content)
    j.store.seal = corrupting_seal
    res = JC.maintain(j, cps, "s1", 2.5, threshold=0)
    j.store.seal = real_seal
    assert res == ("REJECTED", "verify:integrity")
    assert [k for k in j.store.facts().vault if k[1].startswith("ckpt:")] == [("key:s1", old.ref)]
    assert present(j, old) and JC.validate(old, j.store.facts()) is None             # the active one unaffected


@pytest.mark.parametrize("kind", STORES)
def test_case_a_a_crash_orphan_is_never_selected_and_the_active_one_is_unaffected(kind):
    """Existing rule (maintenance v1): a payload sealed without publication is an invisible orphan; its garbage
    collection is operational housekeeping, not part of this repair."""
    wr, j = journal(kind)
    cps = JC.CheckpointStore(j.store)
    put(j, wr, "c1", CITY, "pune", 1.0)
    old = JC.maintain(j, cps, "s1", 1.5, threshold=0)[1]
    put(j, wr, "c2", CITY, "goa", 2.0)
    with pytest.raises(JC.Crash):
        JC.create(j, cps, "s1", 2.5, crash="after_seal")
    assert cps.candidates("s1", float("inf")) == [old] and present(j, old)


@pytest.mark.parametrize("kind", STORES)
def test_case_e_maintenance_and_compaction_never_retire_the_newest_published_checkpoint(kind):
    wr, j, cps, old, new = two_generations(kind, "full")
    assert cps.compact("s1") == 0 and present(j, new) and new.ref not in cps.unusable
    # Direct ``discard`` of the active checkpoint is the existing fail-safe REJECTION path (a reader that finds it
    # invalid). It is permitted by the contract; reads then fall back to the journal with an identical answer.
    cps.discard(new, "rejected")
    f, r = j.store.facts(), j.read("s1", 3.0).r
    assert not present(j, new) and JC.rebuild(f, "s1", r, cps).source == "full"
    assert JC.rebuild(f, "s1", r, cps).view() == JC.full_replay(f, "s1", r).view()


# ============================================================================================ CPD-14 (PostgreSQL)
def test_cpd14_rls_another_tenant_cannot_see_or_delete_the_payload():
    wr, j = journal("postgres")
    cps = JC.CheckpointStore(j.store)
    put(j, wr, "c1", CITY, "pune", 1.0)
    cp = JC.create(j, cps, "s1", 1.5)[1]
    _, other = journal("postgres")                               # another namespace (tenant) on the same cluster
    assert ("key:s1", cp.ref) not in other.store.facts().vault   # RLS: invisible
    other.store.drop_derived("key:s1", cp.ref)                    # RLS + SET LOCAL: deletes nothing
    assert present(j, cp) and pg_rows(cp.ref) == 1
    cps.discard(cp, "superseded")
    assert pg_rows(cp.ref) == 0
