"""Supplementary EMULATOR probes for guarantees the unchanged conformance suite cannot reach. TEST ONLY.

Evidence class: "emulator-observed". It is never proof of production-scale or production-operational behaviour
(the emulator does not implement all production transaction behaviour, and it keeps data in memory).

    bash ../storage-eval-results/run_emulator.sh <out> -q -rA memory_core/storage_adapters/firestore_probes.py

P1 concurrent writers to one partition (ordering, idempotency under concurrent duplicates)
P2 restart: a fresh adapter instance (no process memory) sees identical durable facts
P3 R-READ is not enforced by the interface (any store): a late write dated before a served read is accepted
P4 O4 is not enforced by the interface (any store): a back-dated publication is accepted after a later append
P5 one closed-read mechanism (a per-partition read watermark), NOT chosen: sequentially it holds on the emulator;
   the concurrent variant FAILS on the emulator (a non-serializable interleaving was admitted; see
   storage-eval-results/p5-concurrent-trace.txt). Google documents that the emulator "does not currently implement
   all transaction behavior seen in production", so the concurrent variant is the test to run on real Firestore.
P0/P0b characterise the emulator's transaction behaviour (no assertions)."""
import threading
import uuid

import pytest

from memory_core.commit import SyncRecord
from memory_core.durable_journal import AppendRejected, Entry, PartitionedJournal, Publication, in_force

from .firestore_emulator import FirestoreEmulatorJournal


def sync(part, idem, at, predicate=None, stamp=None):
    return Entry(part, "sync", idem, at, predicate, stamp, SyncRecord(idem, part, "x", "t", at))


IMPLS = {"memory_partitioned": PartitionedJournal, "firestore_emulator": FirestoreEmulatorJournal}


# --------------------------------------------------------------------------------------------- P1
def test_p1_concurrent_writers_to_one_partition_keep_a_gapless_order_and_exactly_once():
    ns, threads, per = uuid.uuid4().hex, 4, 5
    commits0, attempts0 = FirestoreEmulatorJournal.tx_commits, FirestoreEmulatorJournal.tx_attempts
    errors = []

    def writer(k):
        j = FirestoreEmulatorJournal({}, namespace=ns)
        try:
            for i in range(per):
                j.append([sync("s1", f"w{k}-{i}", 1.0)])
                j.append([sync("s1", f"shared-{i % 3}", 1.0)])            # concurrent duplicate delivery
        except Exception as e:                                           # noqa: BLE001  (recorded, then asserted)
            errors.append(repr(e))

    ts = [threading.Thread(target=writer, args=(k,)) for k in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    stored = FirestoreEmulatorJournal({}, namespace=ns).facts().partitions["s1"]
    idems = [s.entry.idem for s in stored]
    assert len(idems) == len(set(idems)) == threads * per + 3          # no lost write, no duplicate
    assert [s.pos for s in stored] == list(range(len(stored)))         # gapless per-partition order
    print(f"P1 commits={FirestoreEmulatorJournal.tx_commits - commits0} "
          f"bodies={FirestoreEmulatorJournal.tx_attempts - attempts0} "
          f"position_conflicts={FirestoreEmulatorJournal.position_conflicts}")


# --------------------------------------------------------------------------------------------- P2
def test_p2_a_fresh_instance_without_process_memory_sees_identical_facts():
    j = FirestoreEmulatorJournal({})
    j.publish(Publication("p", 1, 0.5))
    j.append([sync("s1", "a", 1.0, "p", 1)])
    j.append([Entry("s1", "claim", "c1", 2.0, "p", 1, j.seal("key:s1", "c:1", ("content", 1)))])
    j.append([sync("s2", "b", 1.5)])
    j.destroy_key("key:s2")
    before, ns = j.facts(), j.ns
    del j
    assert FirestoreEmulatorJournal({}, namespace=ns).facts() == before


# --------------------------------------------------------------------------------------------- P3
@pytest.mark.parametrize("impl", IMPLS)
def test_p3_rread_is_not_enforced_by_the_interface(impl):
    j = IMPLS[impl]({})
    j.append([sync("s1", "a", 5.0)])
    served = [s.entry.idem for s in j.facts().partitions["s1"] if s.entry.at <= 10.0]   # a read served at r=10
    assert j.append([sync("s1", "late", 8.0)]) == "APPENDED"           # dated before the served read; accepted
    now = [s.entry.idem for s in j.facts().partitions["s1"] if s.entry.at <= 10.0]
    assert served != now                                               # the served read is no longer reproducible


# --------------------------------------------------------------------------------------------- P4
@pytest.mark.parametrize("impl", IMPLS)
def test_p4_o4_is_not_enforced_by_the_interface(impl):
    j = IMPLS[impl]({})
    j.append([sync("s1", "a", 6.0, "p", None)])                        # correctly stamped: nothing in force at 6
    assert j.publish(Publication("p", 1, 5.0)) == "APPENDED"           # back-dated before an acknowledged append
    f = j.facts()
    e = f.partitions["s1"][0].entry
    assert e.policy_version != in_force(f.publications, "p", e.at)     # O3/O4 now violated in the durable facts


# --------------------------------------------------------------------------------------------- P5
class Watermarked(FirestoreEmulatorJournal):
    """Probe-only mechanism: a closed read at r records r on the partition head inside a transaction; an append
    dated at or before the head's watermark is refused. Demonstrates feasibility only."""

    def closed_read(self, partition, r):
        def body():
            stored = self._durable(partition)
            wm = max(self._head[partition].get("wm", float("-inf")), r)
            self._tx.set(self._part(partition), {"name": partition, "wm": wm,
                                                 "n": self._len[partition]}, merge=True)
            return [s.entry.idem for s in stored if s.entry.at <= r]
        return self._in_tx(body)

    def _write(self, partition, entries, crash_after):
        wm = self._head.get(partition, {}).get("wm", float("-inf"))
        if any(e.at <= wm for e in entries):
            raise AppendRejected("read_closed")
        super()._write(partition, entries, crash_after)


def test_p5_read_watermark_is_enforceable_sequentially():
    j = Watermarked({})
    j.append([sync("s1", "a", 5.0)])
    assert j.closed_read("s1", 10.0) == ["a"]
    with pytest.raises(AppendRejected, match="read_closed"):
        j.append([sync("s1", "late", 8.0)])
    assert j.append([sync("s1", "next", 11.0)]) == "APPENDED"
    assert j.closed_read("s1", 10.0) == ["a"]                          # the served read is reproducible


def test_p5_read_watermark_holds_under_concurrent_readers_and_writers():
    ns = uuid.uuid4().hex
    Watermarked({}, namespace=ns).append([sync("s1", "seed", 0.0)])
    served, refused, errors = [], [], []

    def writer(k):
        j = Watermarked({}, namespace=ns)
        for i in range(8):
            try:
                j.append([sync("s1", f"w{k}-{i}", 1.0 + i)])
            except AppendRejected as e:
                refused.append(str(e))
            except Exception as e:                                       # noqa: BLE001
                errors.append(repr(e))

    def reader():
        j = Watermarked({}, namespace=ns)
        for r in (2.5, 4.5, 6.5):
            try:
                served.append((r, sorted(j.closed_read("s1", r))))
            except Exception as e:                                       # noqa: BLE001
                errors.append(repr(e))

    ts = [threading.Thread(target=writer, args=(k,)) for k in range(2)] + [threading.Thread(target=reader)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    final = Watermarked({}, namespace=ns).facts().partitions["s1"]
    for r, ids in served:                                              # every served read is still exact
        assert sorted(s.entry.idem for s in final if s.entry.at <= r) == ids, r
    print(f"P5 position_conflicts={FirestoreEmulatorJournal.position_conflicts} served={len(served)} refused={sorted(set(refused))} n_refused={len(refused)} stored={len(final)}")


# --------------------------------------------------------------------------------------------- P0
def test_p0_characterise_emulator_lost_update_under_concurrent_transactions():
    """Two transactions each read a counter, pause, and write counter+1. Serializable isolation (documented for
    production) requires the final value 2. This probe records what the EMULATOR does; it asserts nothing."""
    import time
    from google.cloud import firestore as fs
    from .firestore_emulator import client
    ref = client().collection("dj_probe").document(uuid.uuid4().hex)
    ref.set({"n": 0})
    bodies = []

    def bump():
        @fs.transactional
        def run(tx):
            bodies.append(1)
            n = ref.get(transaction=tx).get("n")
            time.sleep(0.5)
            tx.set(ref, {"n": n + 1})
        try:
            run(client().transaction())
        except Exception as e:                                           # noqa: BLE001
            bodies.append(repr(e))

    ts = [threading.Thread(target=bump) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    print(f"P0 final={ref.get().get('n')} bodies={bodies}")


# --------------------------------------------------------------------------------------------- P0b
def test_p0b_characterise_emulator_read_locks():
    """T1 reads doc A inside a transaction, then waits while T2 (another transaction) writes A, then T1 writes B
    and commits. Documented production behaviour: "Transactions place locks on the documents they read", so T2
    must wait for T1 (or one must abort). Records the EMULATOR's order of events; asserts nothing."""
    import time
    from google.cloud import firestore as fs
    from .firestore_emulator import client
    a = client().collection("dj_probe").document(uuid.uuid4().hex)
    b = client().collection("dj_probe").document(uuid.uuid4().hex)
    a.set({"v": 0})
    t1_read, log, t0 = threading.Event(), [], time.monotonic()

    def t1():
        @fs.transactional
        def run(tx):
            v = a.get(transaction=tx).get("v")
            log.append(("T1 read A", v, round(time.monotonic() - t0, 2)))
            t1_read.set()
            time.sleep(2.0)
            tx.set(b, {"copied_from_a": v})
        run(client().transaction())
        log.append(("T1 committed", None, round(time.monotonic() - t0, 2)))

    def t2():
        t1_read.wait()
        @fs.transactional
        def run(tx):
            tx.set(a, {"v": 1})
        run(client().transaction())
        log.append(("T2 committed", None, round(time.monotonic() - t0, 2)))

    ts = [threading.Thread(target=t1), threading.Thread(target=t2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    print(f"P0b log={log} final_b={b.get().to_dict()}")
