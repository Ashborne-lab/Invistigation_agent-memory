import threading, time, uuid
from memory_core.commit import SyncRecord
from memory_core.durable_journal import AppendRejected, Entry
from memory_core.storage_adapters.firestore_probes import Watermarked, sync

LOG = []
T0 = time.monotonic()


class Traced(Watermarked):
    def _durable(self, p):
        out = super()._durable(p)
        LOG.append((round(time.monotonic() - T0, 3), self.who, "read", self._head[p].get("wm"), self._head[p].get("n"),
                    [s.entry.idem for s in out]))
        return out

    def _write(self, p, entries, crash_after):
        LOG.append((round(time.monotonic() - T0, 3), self.who, "write", [e.idem for e in entries]))
        super()._write(p, entries, crash_after)


def test_debug():
    ns = uuid.uuid4().hex
    j = Traced({}, namespace=ns); j.who = "seed"; j.append([sync("s1", "seed", 0.0)])
    served = []

    def writer(k):
        j = Traced({}, namespace=ns); j.who = f"W{k}"
        for i in range(8):
            try:
                j.append([sync("s1", f"w{k}-{i}", 1.0 + i)])
                LOG.append((round(time.monotonic() - T0, 3), j.who, "COMMIT", f"w{k}-{i}"))
            except AppendRejected as e:
                LOG.append((round(time.monotonic() - T0, 3), j.who, "REJECT", f"w{k}-{i}", str(e)))

    def reader():
        j = Traced({}, namespace=ns); j.who = "R"
        for r in (2.5, 4.5, 6.5):
            res = j.closed_read("s1", r)
            served.append((r, res))
            LOG.append((round(time.monotonic() - T0, 3), "R", "SERVED", r, res))

    ts = [threading.Thread(target=writer, args=(k,)) for k in range(2)] + [threading.Thread(target=reader)]
    [t.start() for t in ts]; [t.join() for t in ts]
    final = Traced({}, namespace=ns); final.who = "final"
    f = final.facts().partitions["s1"]
    for x in LOG:
        print(x)
    bad = [(r, ids, sorted(s.entry.idem for s in f if s.entry.at <= r)) for r, ids in served
           if sorted(s.entry.idem for s in f if s.entry.at <= r) != sorted(ids)]
    print("BAD", bad)
