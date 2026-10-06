"""C-5 shared concurrency driver (``storage-technology-evaluation-v2-request.md`` §2-§3). TEST ONLY.

Technology-neutral: every test talks to storage only through ``StorageBoundary`` (via ``TimedJournal``) built by an
``Env`` object (``make_store``). Backend-only actions (crash the server, start a replica, inspect files) go through
the Env hooks and are reported as such. Real OS processes (``spawn``) are the concurrent clients. Synthetic data
only (``TEST_ONLY_*`` policies; subjects ``hot``, ``p<k>``, ``e9``...).

    python -m memory_core.storage_adapters.c5_driver ENV_SPEC OUT_DIR [E1 E2 ...]

Every acknowledgement a worker receives is appended to its log and fsync'd BEFORE the next operation, so a killed
worker's log is a lower bound of what was acknowledged. Checks applied (the suite's own, plus entry-level ones):
``served_prefixes_are_immutable``, ``acknowledged_stamps_hold``, ``committed_at_is_commit_time``; served entry sets
re-derived from the final facts; acknowledged-but-missing facts; K9 exactness of every admitted typed command."""
import dataclasses
import importlib
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
import traceback
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATHS = [ROOT, os.path.join(ROOT, "tests")]
TRANSIENT = ("READ_CLOSED", "COMMIT_TIME_REGRESSED")
BILL_VERSIONS = 40


# ============================================================================================ plumbing
def boot():
    for p in PATHS:
        if p not in sys.path:
            sys.path.insert(0, p)


def load_env(spec):
    mod, cls = spec["cls"].split(":")
    return getattr(importlib.import_module(mod), cls)(**spec["kw"])


def clock(cfg):
    return time.time() - cfg["t0"]


class Log:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")

    def __call__(self, **rec):
        self.f.write(json.dumps(rec) + "\n")
        self.f.flush()
        os.fsync(self.f.fileno())                      # durable before the next operation: a lower bound on acks


def read_log(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass                               # a line torn by a kill
    return out


def logs(cfg, prefix):
    d = cfg["run"]
    return [r for n in sorted(os.listdir(d)) if n.startswith(prefix) for r in read_log(os.path.join(d, n))]


def world():
    """Deterministic in every process: the four TEST_ONLY policies, plus BILL versions 2..N (published by E2)."""
    boot()
    from test_x1_commit_time import Writer
    from test_integration import BILL
    wr = Writer()
    ph = wr.w.p.registry._v
    for v in range(2, BILL_VERSIONS + 1):
        ph[BILL.predicate][v] = dataclasses.replace(ph[BILL.predicate][1], policy_version_id=v)
    return wr, ph


def journal(cfg, replica=False, **kw):
    from memory_core.commit_time import JOURNAL, TimedJournal
    wr, ph = world()
    store = load_env(cfg["env"]).make_store(ph, cfg["ns"], replica=replica, **kw)
    return wr, TimedJournal(ph, JOURNAL, storage=store)


def fresh(cfg, name):
    """A new namespace (one journal) with every policy published at version 1 at time 0."""
    from test_integration import ALL
    cfg = dict(cfg, ns=f"c5{name.lower()}{uuid.uuid4().hex[:10]}", t0=time.time() - 1.0)
    _, j = journal(cfg)
    for p in ALL:
        j.publish(p.predicate, 1, 0.0)
    return cfg, j


def sync_build(subj, idem, predicate=None, stamp=None, n=1):
    from memory_core.commit import SyncRecord
    from memory_core.durable_journal import Entry

    def build(at):
        return [(Entry(subj, "sync", idem if i == 0 else f"{idem}#{i}", at, predicate, stamp,
                       SyncRecord(f"{idem}#{i}", subj, predicate or "x", "TEST_ONLY_sync", at)), None)
                for i in range(n)]
    return build


def typed_build(wr, subj, value):
    from test_integration import CITY

    def build(at):
        v = wr.w.p.project(subj, at).slot_version(CITY.predicate)
        return wr.claim(CITY, value, subj, source="OPERATOR", writer="operator", expected_version=v)(at)
    return build


def capture_served(j, sink):
    """Record, for every read the journal serves, the exact entry set it served from (position, idem, at <= r)."""
    real = j._serve

    def serve(facts, subject, r, op=None):
        sv = real(facts, subject, r, op)
        sink.append(served_set(facts, subject, r))
        return sv
    j._serve = serve


def served_set(facts, subject, r):
    """(subject, r, entries at or before r, publications at or before r of every predicate those entries carry)."""
    ents = sorted((s.pos, s.entry.idem, s.entry.at) for s in facts.partitions.get(subject, ()) if s.entry.at <= r)
    preds = {s.entry.predicate for s in facts.partitions.get(subject, ()) if s.entry.at <= r and s.entry.predicate}
    pubs = sorted((p.predicate, p.version, p.at) for p in facts.publications if p.at <= r and p.predicate in preds)
    return subject, r, ents, pubs


def served_contradictions(final, served):
    """Served entry and policy sets that the final facts no longer reproduce (must be 0: S4 / SPI / K6)."""
    bad = []
    for subject, r, got, pubs in served:
        _, _, now, now_pubs = served_set(final, subject, r)
        if now != got or now_pubs != pubs:
            bad.append({"subject": subject, "r": r, "served": len(got), "final": len(now), "pubs": len(pubs),
                        "final_pubs": len(now_pubs)})
    return bad


def guarded(fn, log, **ctx):
    """Run one storage call; backend errors (connection lost, server crashed) are logged, never hidden."""
    try:
        return fn()
    except Exception as e:                               # noqa: BLE001 - recorded, then the caller decides
        log(ev="error", err=type(e).__name__, msg=str(e)[:200], **ctx)
        return ("ERROR", type(e).__name__)


def run_workers(targets, timeout):
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=t, args=a) for t, a in targets]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout)
        if p.is_alive():
            p.kill()
    return [p.exitcode for p in procs]


# ============================================================================================ workers
def w_appender(cfg, wid, subjects, n_group=1, predicate=None, stop_at=None):
    """Appends synthetic sync entries (optionally stamped) until the deadline; retries transients with a new time."""
    boot()
    wr, j = journal(cfg)
    from memory_core.durable_journal import in_force
    log = Log(os.path.join(cfg["run"], f"app-{wid}.jsonl"))
    rng, i, deadline = random.Random(wid), 0, cfg["t_end"]
    while time.time() < deadline:
        subj = rng.choice(subjects)
        idem = f"w{wid}-{i}"
        tries = 0
        while time.time() < deadline + 5:
            tries += 1
            stamp = in_force(j.store.publications(), predicate, clock(cfg)) if predicate else None
            t = time.perf_counter()
            res = guarded(lambda: j.commit(subj, idem, predicate, stamp, clock(cfg),
                                           sync_build(subj, idem, predicate, stamp, n_group)), log, idem=idem)
            dt = time.perf_counter() - t
            if res[0] in ("APPENDED", "DUPLICATE"):
                log(ev="ack", idem=idem, subj=subj, at=res[1], stamp=stamp, n=n_group, tries=tries, ms=dt * 1e3)
                break
            log(ev="refused", idem=idem, subj=subj, status=res[0], detail=str(res[1])[:80])
            if res[0] == "ERROR":
                time.sleep(0.2)
                try:
                    j.store.crash()                          # reconnect (a lost connection is process state)
                except Exception:                            # noqa: BLE001
                    pass
            elif res[0] not in TRANSIENT and res[0] != "STALE_POLICY_STAMP":
                break                                        # terminal refusal: not retried
        i += 1


def w_reader(cfg, rid, subject, replica=False):
    """Current (closing) reads on the primary, or lagging snapshot reads on a replica."""
    boot()
    from memory_core.storage_boundary import View  # noqa: F401
    wr, j = journal(cfg, replica=replica)
    served = []
    capture_served(j, served)
    log = Log(os.path.join(cfg["run"], f"read-{rid}.jsonl"))
    while time.time() < cfg["t_end"]:
        t = time.perf_counter()
        w0 = j.store.writes
        if replica:
            def lagging():
                v = j.store.snapshot()
                r = j.store.view_position(v, subject, [], clock(cfg))
                if r is None:
                    return None
                return r, served_set(v.facts, subject, r), v.f_part.get(subject)
            res = guarded(lagging, log)
            if res and res[0] != "ERROR":
                served.append(res[1])
                log(ev="served", r=res[0], n=len(res[1][2]), incorporated=res[2], ms=(time.perf_counter() - t) * 1e3)
        else:
            res = guarded(lambda: j.read(subject, clock(cfg)), log)
            if res is not None and not isinstance(res, tuple):
                log(ev="served", r=res.r, n=len(served[-1][2]), writes=j.store.writes - w0,
                    ms=(time.perf_counter() - t) * 1e3)
        time.sleep(cfg.get("read_pause", 0.0))
    with open(os.path.join(cfg["run"], f"served-{rid}.json"), "w") as f:
        json.dump(served, f)
    import pickle
    with open(os.path.join(cfg["run"], f"traces-{rid}.pkl"), "wb") as f:
        pickle.dump(j.served, f)


def w_publisher(cfg, versions, pause, predicate=None):
    boot()
    from test_integration import BILL
    predicate = predicate or BILL.predicate
    wr, j = journal(cfg)
    log = Log(os.path.join(cfg["run"], "pub-0.jsonl"))
    for v in versions:
        t = time.perf_counter()
        res = guarded(lambda: j.publish(predicate, v, clock(cfg)), log, version=v)
        log(ev="published" if not isinstance(res, tuple) else "pub_error", version=v, T=None if isinstance(res, tuple)
            else res, ms=(time.perf_counter() - t) * 1e3)
        time.sleep(pause)


def w_typed(cfg, wid, subject, max_cmds=10**9):
    """Typed commands: current read -> expected version -> command. STATE_CONFLICT is terminal (never retried);
    READ_CLOSED / COMMIT_TIME_REGRESSED are retried with a new time (every check again)."""
    boot()
    from test_integration import CITY
    wr, j = journal(cfg)
    log = Log(os.path.join(cfg["run"], f"typed-{wid}.jsonl"))
    i = 0
    while time.time() < cfg["t_end"] and i < max_cmds:
        cmd = f"t{wid}-{i}"
        value = f"v{wid}x{i}"
        learn_versions(wr, j.store.publications(), CITY.predicate)   # versions another process published
        sv = guarded(lambda: j.read(subject, clock(cfg)), log, cmd=cmd)
        if isinstance(sv, tuple):
            if sv[1] != "KeyError":                                  # KeyError: a version published meanwhile
                j.store.crash()
            continue
        v = j._version(subject, CITY.predicate, sv.r)
        tries = 0
        while True:
            tries += 1
            t = time.perf_counter()
            res = guarded(lambda: j.commit(subject, cmd, CITY.predicate, wr.stamp(CITY), clock(cfg),
                                           typed_build(wr, subject, value), expected_version=v), log, cmd=cmd)
            dt = (time.perf_counter() - t) * 1e3
            if res[0] in TRANSIENT and tries < 50:
                log(ev="transient", cmd=cmd, status=res[0])
                continue
            log(ev="outcome", cmd=cmd, status=res[0], expected=v, at=res[1] if res[0] == "APPENDED" else None,
                actual=res[1] if res[0] == "STATE_CONFLICT" else None, tries=tries, ms=dt)
            if res[0] == "STALE_POLICY_STAMP":
                learn_versions(wr, j.store.publications(), CITY.predicate)   # the writer re-runs with the new stamp
            break
        i += 1


def learn_versions(wr, pubs, predicate):
    """The writer side learns versions published by another process (non-breaking copies of version 1)."""
    reg = wr.w.p.registry
    for p in sorted(pubs, key=lambda x: x.version):
        if p.predicate == predicate and p.version not in reg._v[predicate]:
            wr.w.p.publish(dataclasses.replace(reg.get(predicate), policy_version_id=p.version), p.at)


def history_knows(ph, pubs, predicate):
    for p in pubs:
        if p.predicate == predicate and p.version not in ph[predicate]:
            ph[predicate][p.version] = dataclasses.replace(ph[predicate][1], policy_version_id=p.version)


def w_same_idem(cfg, wid, subject, idems, barrier_at):
    """Two clients submit the SAME logical commands (same id, same content) at the same instant."""
    boot()
    wr, j = journal(cfg)
    log = Log(os.path.join(cfg["run"], f"dup-{wid}.jsonl"))
    for k, idem in enumerate(idems):
        while time.time() < barrier_at + k * 0.05:
            pass
        while True:
            res = guarded(lambda: j.commit(subject, idem, None, None, clock(cfg), sync_build(subject, idem)), log)
            if res[0] not in TRANSIENT:
                break
        log(ev="outcome", idem=idem, status=res[0], at=res[1])


def w_closer_then_die(cfg, subject):
    boot()
    wr, j = journal(cfg)
    log = Log(os.path.join(cfg["run"], "closer.jsonl"))
    sv = j.read(subject, clock(cfg))
    log(ev="served", r=sv.r, trace=len(sv.trace))
    os._exit(0)                                          # the client dies right after the acknowledged closure


def w_eraser(cfg, subject, delay):
    boot()
    from memory_core.durable_journal import Entry
    wr, j = journal(cfg)
    log = Log(os.path.join(cfg["run"], "eraser.jsonl"))
    time.sleep(delay)
    e = Entry(subject, "erasure", "erasure:" + subject, 0.0, None, None, ("cluster", (subject,)))
    res = j.commit(subject, "erasure:" + subject, None, None, clock(cfg),
                   lambda at: [(dataclasses.replace(e, at=at), None)])
    log(ev="erasure", status=res[0], at=res[1])
    j.store.destroy_key("key:" + subject)
    log(ev="destroyed", t=clock(cfg))


def w_e9_writer(cfg, wid, subject):
    """Claims with sealed content for the subject being erased, until the deadline."""
    boot()
    from test_integration import CITY
    wr, j = journal(cfg)
    log = Log(os.path.join(cfg["run"], f"e9w-{wid}.jsonl"))
    i = 0
    while time.time() < cfg["t_end"]:
        cmd = f"e{wid}-{i}"
        res = guarded(lambda: j.commit(subject, cmd, CITY.predicate, wr.stamp(CITY), clock(cfg),
                                       wr.claim(CITY, f"{cfg['marker']}w{wid}x{i}", subject)), log, cmd=cmd)
        log(ev="outcome", cmd=cmd, status=res[0], at=res[1] if res[0] == "APPENDED" else None,
            detail=str(res[1])[:60])
        i += 1


# ============================================================================================ checks
def final_journal(cfg):
    return journal(cfg)


def acked_missing(final, acks):
    have = {s.entry.idem for v in final.partitions.values() for s in v}
    return [a["idem"] for a in acks if a["ev"] == "ack" and a["idem"] not in have]


def groups_atomic(final, n):
    """S5: every group of n entries is complete or absent (acknowledged or not, e.g. in flight at a kill)."""
    have = {}
    for v in final.partitions.values():
        for s in v:
            base = s.entry.idem.split("#")[0]
            have[base] = have.get(base, 0) + 1
    return [k for k, c in have.items() if c != n]


def summary(recs, key="status"):
    out = {}
    for r in recs:
        k = r.get(key) or r["ev"]
        out[k] = out.get(k, 0) + 1
    return out


def pct(xs, q):
    xs = sorted(xs)
    return None if not xs else round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


def lat(xs):
    return {"n": len(xs), "p50_ms": pct(xs, 0.5), "p95_ms": pct(xs, 0.95), "p99_ms": pct(xs, 0.99),
            "max_ms": pct(xs, 1.0)}


def load_served(cfg):
    out = []
    for n in os.listdir(cfg["run"]):
        if n.startswith("served-"):
            with open(os.path.join(cfg["run"], n)) as f:
                out += [tuple(x) for x in json.load(f)]
    return [(s, r, [tuple(e) for e in got], [tuple(p) for p in pubs]) for s, r, got, pubs in out]


# ============================================================================================ E1..E9
def E1(cfg, writers=6, readers=4, seconds=12.0):
    """Concurrent conditional append versus closure on ONE partition (P5-conc generalised)."""
    cfg, j0 = fresh(cfg, "E1")
    cfg["t_end"] = time.time() + seconds
    run_workers([(w_appender, (cfg, w, ["hot"])) for w in range(writers)] +
                [(w_reader, (cfg, r, "hot")) for r in range(readers)], seconds + 60)
    from memory_core.commit_time import served_prefixes_are_immutable
    _, j = final_journal(cfg)
    f = j.store.facts()
    served = load_served(cfg)
    acks, refused = logs(cfg, "app-"), [r for r in logs(cfg, "app-") if r["ev"] == "refused"]
    contr = served_contradictions(f, served)
    spi = suite_spi(cfg, j)
    return {"served_reads": len(served), "contradicted": len(contr), "contradictions": contr[:5],
            "served_prefixes_are_immutable": spi,
            "acked": sum(a["ev"] == "ack" for a in acks), "acked_missing": len(acked_missing(f, acks)),
            "refusals": summary(refused), "errors": sum(a["ev"] == "error" for a in acks),
            "durable_entries": len(f.partitions.get("hot", ())),
            "append_latency": lat([a["ms"] for a in acks if a["ev"] == "ack"]),
            "result": "PASS" if not contr and not acked_missing(f, acks) and served and spi == "holds" else "FAIL",
            "_j": j}


def suite_spi(cfg, j):
    """The suite's own check over every reader process's served traces, against the final facts."""
    import pickle
    import types
    from memory_core.commit_time import served_prefixes_are_immutable
    traces = []
    for n in os.listdir(cfg["run"]):
        if n.startswith("traces-"):
            with open(os.path.join(cfg["run"], n), "rb") as fh:
                traces += pickle.load(fh)
    try:
        served_prefixes_are_immutable(types.SimpleNamespace(store=j.store, served=traces))
        return "holds"
    except AssertionError as e:
        return "VIOLATED " + str(e)[:80]


def E2(cfg, writers=6, partitions=24, versions=range(2, 32), pause=0.25):
    """Publish versus append contention on ONE predicate across many partitions (O4, K6)."""
    from test_integration import BILL
    cfg, j0 = fresh(cfg, "E2")
    seconds = len(versions) * pause + 2.0
    cfg["t_end"] = time.time() + seconds
    subjects = [f"p{k}" for k in range(partitions)]
    run_workers([(w_appender, (cfg, w, subjects, 1, BILL.predicate)) for w in range(writers)] +
                [(w_publisher, (cfg, list(versions), pause))] +
                [(w_reader, (cfg, 100 + k, f"p{k}")) for k in range(3)], seconds + 60)
    from memory_core.commit_time import acknowledged_stamps_hold
    from memory_core.durable_journal import in_force
    _, j = final_journal(cfg)
    f = j.store.facts()
    viol = [(p, s.entry.idem) for p, v in f.partitions.items() for s in v
            if s.entry.predicate and s.entry.policy_version != in_force(f.publications, s.entry.predicate, s.entry.at)]
    try:
        acknowledged_stamps_hold(j)
        suite_check = "holds"
    except AssertionError as e:
        suite_check = "VIOLATED " + str(e)[:80]
    acks = logs(cfg, "app-")
    pubs = logs(cfg, "pub-")
    served = load_served(cfg)
    contr = served_contradictions(f, served)
    spi = suite_spi(cfg, j)
    return {"stamp_violations": len(viol), "acknowledged_stamps_hold": suite_check,
            "closing_reads_racing_publication": len(served),
            "reads_with_publications_served": sum(1 for x in served if x[3]),
            "served_entry_or_policy_sets_contradicted": len(contr), "served_prefixes_are_immutable": spi,
            "acked": sum(a["ev"] == "ack" for a in acks), "acked_missing": len(acked_missing(f, acks)),
            "append_refusals_while_publishing": summary([a for a in acks if a["ev"] == "refused"]),
            "publications": sum(p["ev"] == "published" for p in pubs),
            "publication_latency": lat([p["ms"] for p in pubs if p["ev"] == "published"]),
            "versions_in_force_seen_by_acked_appends": sorted({a["stamp"] for a in acks if a["ev"] == "ack"})[:3] +
            ["..."] + sorted({a["stamp"] for a in acks if a["ev"] == "ack"})[-3:],
            "result": "PASS" if not viol and suite_check == "holds" and not acked_missing(f, acks) and served
            and not contr and spi == "holds" else "FAIL",
            "_j": j}


def E3(cfg, rounds=4, writers=4):
    """Durability before acknowledgement: (a) clients killed mid-commit; (b) the backend crashed under load."""
    env = load_env(cfg["env"])
    cfg, j0 = fresh(cfg, "E3")
    out = {"client_kill_rounds": [], "backend_crash": None}
    ctx = mp.get_context("spawn")
    for rnd in range(rounds):                                                  # (a) kill clients mid-commit
        cfg["t_end"] = time.time() + 30
        ps = [ctx.Process(target=w_appender, args=(dict(cfg, run=cfg["run"]), 100 * rnd + w, ["d1", "d2"], 3))
              for w in range(writers)]
        for p in ps:
            p.start()
        time.sleep(4.0 + random.random() * 2)
        for p in ps:
            p.kill()                                                           # TerminateProcess: no cleanup
        for p in ps:
            p.join()
        out["client_kill_rounds"].append(rnd)
    _, j = final_journal(cfg)
    f = j.store.facts()
    acks = logs(cfg, "app-")
    out["client_kill"] = {"acked": sum(a["ev"] == "ack" for a in acks),
                          "acked_missing": len(acked_missing(f, acks)), "partial_groups": groups_atomic(f, 3)[:5]}
    # (b) backend crash: immediate stop while writers commit, restart, re-check every acknowledgement
    cfg["t_end"] = time.time() + 14
    ps = [ctx.Process(target=w_appender, args=(cfg, 900 + w, ["d1", "d2"], 3)) for w in range(writers)]
    for p in ps:
        p.start()
    time.sleep(4.0)
    t_crash = time.time()
    crash_out = env.crash_backend()
    time.sleep(1.0)
    env.restart_backend()
    t_back = time.time()
    for p in ps:
        p.join(60)
        if p.is_alive():
            p.kill()
    _, j = final_journal(cfg)
    f = j.store.facts()
    acks = logs(cfg, "app-")
    before = [a for a in logs(cfg, "app-9") if a["ev"] == "ack"]
    if True:
        recovery = [l for l in open(os.path.join(env.datadir, "server.log"), encoding="utf-8", errors="replace")
                    if "redo" in l or "recovery" in l or "not properly shut down" in l][-6:]
    out["backend_crash"] = {"crash": crash_out.strip()[-80:], "downtime_s": round(t_back - t_crash, 2),
                            "acked_total": sum(a["ev"] == "ack" for a in acks),
                            "acked_by_crash_round_writers": len(before),
                            "acked_missing": len(acked_missing(f, acks)), "partial_groups": groups_atomic(f, 3)[:5],
                            "errors_seen_by_clients": sum(a["ev"] == "error" for a in logs(cfg, "app-9")),
                            "server_log_recovery_lines": [l.strip()[-110:] for l in recovery]}
    # C: visible to a subsequent closed read
    sv = j.read("d1", clock(cfg))
    served_ids = {s.entry.idem for s in j.store.facts().partitions.get("d1", ()) if s.entry.at <= sv.r}
    out["acked_visible_to_closed_read"] = all(a["idem"] in served_ids for a in acks if a["ev"] == "ack"
                                              and a["subj"] == "d1")
    ok = not out["client_kill"]["acked_missing"] and not out["backend_crash"]["acked_missing"] and \
        not out["client_kill"]["partial_groups"] and not out["backend_crash"]["partial_groups"] and \
        out["acked_visible_to_closed_read"]
    out["result"] = "PASS" if ok else "FAIL"
    out["_j"] = j
    return out


def E4(cfg):
    """Crash and recovery of closure: close, kill the client AND crash the backend, restart, late-dated appends."""
    from memory_core.durable_journal import Entry, Publication
    from test_integration import CITY
    from test_durable_storage_boundary import sync_entry
    env = load_env(cfg["env"])
    from test_x1_commit_time import put
    cfg, j0 = fresh(cfg, "E4")
    wr0, j0 = journal(cfg)
    assert put(j0, wr0, "c0", CITY, "pune", clock(cfg), subj="c")[0] == "APPENDED"   # the read evaluates CITY
    run_workers([(w_closer_then_die, (cfg, "c"))], 60)
    r = read_log(os.path.join(cfg["run"], "closer.jsonl"))[-1]["r"]
    env.crash_backend()
    time.sleep(1.0)
    env.restart_backend()
    _, j = journal(cfg)
    tries = {}
    for k, at in enumerate([r - 1.0, r - 1e-6, r]):                            # direct late-dated appends
        tries[f"append_at_r{'-' if at < r else '='}{r - at:g}"] = j.store.append("c", at, [sync_entry("c", f"late{k}", at)])[0]
    T = j.store.assign("c", None, r - 5.0)                                     # time assignment after recovery
    tries["assign_after_recovery_gt_r"] = T > r
    pub = None
    try:
        pub = j.store.publish_at(Publication(CITY.predicate, 2, r - 0.5))      # a back-dated publication
    except Exception as e:                                                    # noqa: BLE001
        pub = "refused:" + str(e)
    tries["backdated_publication_of_a_closed_log"] = pub
    f = j.store.facts()
    in_prefix = [s.entry.idem for s in f.partitions.get("c", ()) if s.entry.at <= r and s.entry.idem != "c0"]
    tries["f_pol_city_after_recovery_ge_r"] = j.f_pol.get(CITY.predicate, -math.inf) >= r
    return {"served_r": r, "attempts": tries, "late_appends_in_served_prefix": len(in_prefix),
            "result": "PASS" if not in_prefix and tries["assign_after_recovery_gt_r"] and
            str(pub).startswith("refused") and tries["f_pol_city_after_recovery_ge_r"] and
            all(v == "READ_CLOSED" for k, v in tries.items() if k.startswith("append")) else "FAIL", "_j": j}


def E5(cfg, n=300):
    """Current-read closure cost (K7): stored writes per current read, latency, row-write effects."""
    from test_integration import ALL
    env = load_env(cfg["env"])
    cfg, j = fresh(cfg, "E5")
    from test_x1_commit_time import put
    wr, j = journal(cfg)
    from test_integration import CITY
    put(j, wr, "k1", CITY, "pune", clock(cfg))
    with env.admin() as c:
        before = c.execute("SELECT relname, n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE schemaname='c5' "
                           "AND relname IN ('heads','polheads') ORDER BY 1").fetchall()
    cur_w, cur_ms, stale_w, stale_ms, same_w = [], [], [], [], []
    for _ in range(n):
        w0, t = j.store.writes, time.perf_counter()
        sv = j.read("s1", clock(cfg))
        cur_ms.append((time.perf_counter() - t) * 1e3)
        cur_w.append(j.store.writes - w0)
        w0 = j.store.writes
        j.end_read(("s1", sv.r, None))                                          # a repeat at an already-closed r
        same_w.append(j.store.writes - w0)
        w0, t = j.store.writes, time.perf_counter()
        j.read("s1", clock(cfg), closing=False)                                 # stale-tolerant read
        stale_ms.append((time.perf_counter() - t) * 1e3)
        stale_w.append(j.store.writes - w0)
    j.store.db.conn.close()                                                     # a backend flushes its stats on exit
    time.sleep(1.5)
    with env.admin() as c:
        after = c.execute("SELECT relname, n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE schemaname='c5' "
                          "AND relname IN ('heads','polheads') ORDER BY 1").fetchall()
    return {"current_read_stored_writes": {"min": min(cur_w), "max": max(cur_w), "mean": sum(cur_w) / n},
            "evaluated_sources_per_read": "partition + each evaluated predicate log",
            "repeat_at_closed_r_writes": max(same_w), "stale_tolerant_read_writes": max(stale_w),
            "current_read_latency": lat(cur_ms), "stale_read_latency": lat(stale_ms),
            "stored_frontier_writes_by_driver": sum(cur_w) + sum(same_w) + sum(stale_w),
            "head_row_updates_pg_stat (table, updates, hot updates)": [(a[0], a[1] - b[1], a[2] - b[2])
                                                                      for a, b in zip(after, before)],
            "result": "MEASURED", "_j": j}


def E6(cfg, writers=4, seconds=12.0):
    """Lagging reads from a streaming replica (read-time snapshot on the standby)."""
    env = load_env(cfg["env"])
    if not env.ensure_replica():
        return {"result": "UNMEASURED", "why": "no replica in this environment"}
    cfg, j0 = fresh(cfg, "E6")
    cfg["t_end"] = time.time() + seconds
    cfg["read_pause"] = 0.02
    lags = []
    ctx = mp.get_context("spawn")
    ps = [ctx.Process(target=w_appender, args=(cfg, w, ["lag"])) for w in range(writers)] + \
        [ctx.Process(target=w_reader, args=(cfg, 0, "lag", False)),          # closes on the primary
         ctx.Process(target=w_reader, args=(cfg, 1, "lag", True)),           # lagging reads on the replica
         ctx.Process(target=w_reader, args=(cfg, 2, "lag", True))]
    for p in ps:
        p.start()
    while time.time() < cfg["t_end"]:
        lags.append(env.replica_lag_bytes())
        time.sleep(0.2)
    for p in ps:
        p.join(60)
    time.sleep(2.0)
    _, j = final_journal(cfg)
    f = j.store.facts()
    served = load_served(cfg)
    rep = [r for r in logs(cfg, "read-1") + logs(cfg, "read-2") if r["ev"] == "served"]
    contr = served_contradictions(f, served)
    behind = [x for x in rep if x["incorporated"] is not None and x["r"] <= x["incorporated"]]
    return {"replica_reads": len(rep), "primary_reads": sum(r["ev"] == "served" for r in logs(cfg, "read-0")),
            "contradicted": len(contr), "contradictions": contr[:5],
            "served_at_or_below_replica_frontier": f"{len(behind)}/{len(rep)}",
            "replica_lag_bytes": {"max": max([x for x in lags if x is not None] or [0]),
                                  "samples": len(lags), "none": sum(x is None for x in lags)},
            "replica_read_latency": lat([x["ms"] for x in rep]),
            "result": "PASS" if rep and not contr and len(behind) == len(rep) else "FAIL", "_j": j}


def E7(cfg, writers=6, seconds=12.0, hot_predicate_subjects=6):
    """Contention: one hot subject (typed commands, K9) and one hot predicate log (many subjects)."""
    boot()
    from memory_core.durable_journal import DurableFacts, reconstruct
    from test_integration import CITY
    out = {}
    for mode in ("hot_subject", "hot_predicate"):
        cfg2, j0 = fresh(dict(cfg, run=os.path.join(cfg["run"], mode)), "E7")
        os.makedirs(cfg2["run"], exist_ok=True)
        cfg2["t_end"] = time.time() + seconds
        subj = (lambda w: "hot") if mode == "hot_subject" else (lambda w: f"h{w % hot_predicate_subjects}")
        racers = [(w_publisher, (cfg2, list(range(2, 2 + int(seconds / 0.8))), 0.8, CITY.predicate))] \
            if mode == "hot_subject" else []
        run_workers([(w_typed, (cfg2, w, subj(w))) for w in range(writers)] + racers, seconds + 120)
        _, j = final_journal(cfg2)
        history_knows(j.store.policy_history, j.store.publications(), CITY.predicate)
        f = j.store.facts()
        recs = logs(cfg2, "typed-")
        outs = [r for r in recs if r["ev"] == "outcome"]
        # K9 exactness: every admitted command's expected version equals the slot version just before it
        k9_bad = []
        for o in outs:
            if o["status"] != "APPENDED":
                continue
            s = subj(int(o["cmd"][1:].split("-")[0]))
            part = f.partitions.get(s, ())
            pos = next(x.pos for x in part if x.entry.idem == o["cmd"])
            prefix = DurableFacts({s: part[:pos]}, f.publications, f.vault, f.policy_history)
            before = len(reconstruct(prefix, s, o["at"]).trace.get(CITY.predicate, ()))
            if before != o["expected"]:
                k9_bad.append((o["cmd"], o["expected"], before))
        conflicts_retried = [r for r in recs if r["ev"] == "transient" and r["status"] == "STATE_CONFLICT"]
        out[mode] = {"outcomes": summary(outs), "transient_retries": summary([r for r in recs if r["ev"] == "transient"]),
                     "errors": sum(r["ev"] == "error" for r in recs),
                     "stale_accepted (K9 violations)": len(k9_bad), "examples": k9_bad[:3],
                     "state_conflicts_retried": len(conflicts_retried),
                     "command_latency": lat([o["ms"] for o in outs]),
                     "racing_publications": sum(p["ev"] == "published" for p in logs(cfg2, "pub-")),
                     "max_tries": max([o["tries"] for o in outs] or [0])}
        try:
            from memory_core.commit_time import served_prefixes_are_immutable  # noqa: F401
            from test_durable_storage_boundary import committed_at_is_commit_time
            committed_at_is_commit_time(j)
            out[mode]["committed_at_is_commit_time"] = "holds"
        except AssertionError as e:
            out[mode]["committed_at_is_commit_time"] = "VIOLATED " + str(e)[:60]
    # concurrent identical submissions: exactly-once
    cfg3, j0 = fresh(dict(cfg, run=os.path.join(cfg["run"], "dup")), "E7dup")
    os.makedirs(cfg3["run"], exist_ok=True)
    idems = [f"same{k}" for k in range(40)]
    run_workers([(w_same_idem, (cfg3, w, "dupsubj", idems, time.time() + 6.0)) for w in range(3)], 120)
    _, j = final_journal(cfg3)
    f = j.store.facts()
    counts = {i: sum(s.entry.idem == i for s in f.partitions.get("dupsubj", ())) for i in idems}
    dup = summary([r for r in logs(cfg3, "dup-") if r["ev"] == "outcome"])
    out["identical_concurrent_submissions"] = {"commands": len(idems), "clients": 3,
                                               "durable_copies_per_command": sorted(set(counts.values())),
                                               "client_outcomes": dup}
    ok = all(m["stale_accepted (K9 violations)"] == 0 and m["state_conflicts_retried"] == 0 and
             m["committed_at_is_commit_time"] == "holds" for m in (out["hot_subject"], out["hot_predicate"])) and \
        out["identical_concurrent_submissions"]["durable_copies_per_command"] == [1]
    out["result"] = "PASS" if ok else "FAIL"
    out["_j"] = j
    return out


def E8(cfg, sizes=(1, 10, 100, 1000, 10000, 50000)):
    """Single-partition group append: largest group committed atomically; crash mid-group leaves nothing."""
    from memory_core.durable_journal import Crash
    from test_durable_storage_boundary import sync_entry
    cfg, j = fresh(cfg, "E8")
    rows = []
    for n in sizes:
        part = f"g{n}"
        at = j.store.assign(part, None, clock(cfg))
        group = [sync_entry(part, f"g{n}-{i}", at) for i in range(n)]
        t = time.perf_counter()
        try:
            j.store.append(part, at, group, crash_after=n // 2)
            crashed = "no crash raised"
        except Crash:
            crashed = len(j.store.entries(part))
        t1 = time.perf_counter()
        res = j.store.append(part, at, group)[0]
        t2 = time.perf_counter()
        rows.append({"n": n, "after_mid_group_crash_durable": crashed, "append": res,
                     "durable": len(j.store.entries(part)), "commit_s": round(t2 - t1, 3)})
    ok = all(r["after_mid_group_crash_durable"] == 0 and r["durable"] == r["n"] for r in rows)
    return {"groups": rows, "largest_atomic_group_tested": max(sizes),
            "result": "PASS" if ok else "FAIL", "_j": j}


def E9(cfg, writers=4, seconds=8.0):
    """Erasure: fence and key destruction under concurrent appends; residue in storage; stale snapshots."""
    import psycopg
    env = load_env(cfg["env"])
    cfg, j0 = fresh(cfg, "E9")
    cfg["marker"] = "ZQXMARK" + uuid.uuid4().hex[:8]
    cfg["t_end"] = time.time() + seconds
    run_workers([(w_e9_writer, (cfg, w, "e9")) for w in range(writers)] + [(w_eraser, (cfg, "e9", seconds / 2))],
                seconds + 60)
    _, j = final_journal(cfg)
    f = j.store.facts()
    part = f.partitions.get("e9", ())
    epos = next((s.pos for s in part if s.entry.kind == "erasure"), None)
    after_fence = [s.entry.idem for s in part if epos is not None and s.pos > epos]
    vault_left = [k for k in f.vault if k[0] == "key:e9"]
    from memory_core.durable_journal import reconstruct
    rb = reconstruct(f, "e9", clock(cfg))
    recs = logs(cfg, "e9w-")
    er = read_log(os.path.join(cfg["run"], "eraser.jsonl"))
    # stale snapshot: a transaction whose snapshot predates the destroy still reads the deleted rows (MVCC)
    stale = None
    try:
        with psycopg.connect(__import__("memory_core.storage_adapters.postgres_local", fromlist=["dsn"]).dsn(env.port),
                             autocommit=False) as c1, env.admin() as adm:
            c1.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            c1.execute("SELECT set_config('app.ns', %s, true)", (cfg["ns"],))
            n0 = c1.execute("SELECT count(*) FROM c5.vault WHERE key_id = 'key:e9b'").fetchone()[0]
            st = env.make_store(j.store.policy_history, cfg["ns"])
            st.seal("key:e9b", "x1", {"t": cfg["marker"] + "snap"})
            n_before = c1.execute("SELECT count(*) FROM c5.vault WHERE key_id = 'key:e9b'").fetchone()[0]
            c1.rollback()
            c1.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            c1.execute("SELECT set_config('app.ns', %s, true)", (cfg["ns"],))
            n1 = c1.execute("SELECT count(*) FROM c5.vault WHERE key_id = 'key:e9b'").fetchone()[0]   # snapshot fixed
            st.destroy_key("key:e9b")
            n2 = c1.execute("SELECT count(*) FROM c5.vault WHERE key_id = 'key:e9b'").fetchone()[0]
            c1.rollback()
            stale = {"rows_seen_by_snapshot_opened_before_destroy": n2, "rows_at_snapshot_start": n1,
                     "visible_to_new_snapshot": len([k for k in st.facts().vault if k[0] == "key:e9b"]),
                     "rows_seen_before_seal_committed": (n0, n_before)}
    except Exception as e:                                                   # noqa: BLE001
        stale = {"error": repr(e)[:200]}
    # physical residue: the marker's bytes in heap files / WAL after DELETE, after VACUUM, after VACUUM FULL
    residue = {}
    with env.admin() as c:
        c.execute("CHECKPOINT")
        residue["after_delete"] = _grep_dir(env.datadir, cfg["marker"])
        c.execute("VACUUM c5.vault")
        c.execute("CHECKPOINT")
        residue["after_vacuum"] = _grep_dir(env.datadir, cfg["marker"])
        c.execute("VACUUM FULL c5.vault")
        c.execute("CHECKPOINT")
        residue["after_vacuum_full"] = _grep_dir(env.datadir, cfg["marker"])
    replica = None
    if env.replica_dir and os.path.exists(os.path.join(env.replica_dir, "PG_VERSION")):
        time.sleep(1.0)
        replica = _grep_dir(env.replica_dir, cfg["marker"])
    outcomes = summary([r for r in recs if r["ev"] == "outcome"])
    ok = not after_fence and not vault_left and rb.erased
    return {"erasure": er, "writer_outcomes": outcomes,
            "writer_errors": summary([r for r in recs if r["ev"] == "error"], key="err"),
            "appends_after_fence": len(after_fence), "sealed_rows_left_for_key": len(vault_left),
            "reconstruct_erased": rb.erased, "stale_snapshot": stale,
            "marker_bytes_in_files": residue, "marker_bytes_in_replica_files": replica,
            "result": "PASS" if ok else "FAIL", "_j": j}


def _grep_dir(root, marker):
    """Files under the data directory whose raw bytes still contain the marker (heap pages, WAL, ...)."""
    hits, needle = {}, marker.encode()
    for d, _, fs in os.walk(root):
        for n in fs:
            p = os.path.join(d, n)
            try:
                with open(p, "rb") as fh:
                    c = fh.read().count(needle)
            except OSError:
                continue
            if c:
                kind = "pg_wal" if "pg_wal" in p else ("heap" if os.sep + "base" + os.sep in p else "other")
                hits[kind] = hits.get(kind, 0) + c
    return hits


def E3_control(cfg, trials=3, writers=4):
    """NEGATIVE CONTROL for E3(b): the same backend crash with synchronous_commit = off (commit returns before its
    WAL is flushed). If acknowledged facts go missing here, E3(b) is sensitive to commit-before-durability."""
    env = load_env(cfg["env"])
    rows = []
    env.set_conf("synchronous_commit", "off")
    try:
        for t in range(trials):
            run = os.path.join(cfg["run"], f"trial{t}")
            os.makedirs(run, exist_ok=True)
            cfg2, _ = fresh(dict(cfg, run=run), "E3c")
            cfg2["t_end"] = time.time() + 10
            ctx = mp.get_context("spawn")
            ps = [ctx.Process(target=w_appender, args=(cfg2, w, ["d1", "d2"])) for w in range(writers)]
            for p in ps:
                p.start()
            time.sleep(4.0)
            env.crash_backend()
            time.sleep(1.0)
            env.restart_backend()
            for p in ps:
                p.join(60)
                if p.is_alive():
                    p.kill()
            _, j = final_journal(cfg2)
            f = j.store.facts()
            acks = logs(cfg2, "app-")
            rows.append({"acked": sum(a["ev"] == "ack" for a in acks), "acked_missing": len(acked_missing(f, acks))})
    finally:
        env.set_conf("synchronous_commit", None)
    with env.admin() as c:
        restored = c.execute("SHOW synchronous_commit").fetchone()[0]
    lost = sum(r["acked_missing"] for r in rows)
    return {"trials": rows, "acked_lost_total": lost, "synchronous_commit_restored": restored,
            "result": ("CONTROL_LOSES" if lost else "CONTROL_DID_NOT_LOSE") if restored == "on" else "FAIL"}


def _failover(cfg, sync, writers=4, seconds=6.0):
    """Crash the primary under load, promote the streaming standby, check the promoted node: acknowledged facts
    (S3) and closure (S2: late appends below a served position). The promoted side is then discarded and the old
    primary restarted (never two primaries)."""
    from test_durable_storage_boundary import sync_entry
    env = load_env(cfg["env"])
    env.ensure_replica()
    if sync:
        env.set_conf("synchronous_standby_names", "*")
    try:
        cfg2, _ = fresh(cfg, "E3f")
        cfg2["t_end"] = time.time() + seconds
        ctx = mp.get_context("spawn")
        ps = [ctx.Process(target=w_appender, args=(cfg2, w, ["fo"])) for w in range(writers)] + \
            [ctx.Process(target=w_reader, args=(cfg2, 0, "fo", False))]
        for p in ps:
            p.start()
        time.sleep(seconds - 1.5)
        with env.admin() as c:                                               # verify the configured mode is live
            repl_state = c.execute("SELECT sync_state FROM pg_stat_replication").fetchall()
        env.crash_backend()
        promoted = env.promote_replica()
        for p in ps:
            p.join(90)
            if p.is_alive():
                p.kill()
        wr, ph = world()
        rep = env.make_store(ph, cfg2["ns"], replica=True)
        f = rep.facts()
        acks = logs(cfg2, "app-")
        reads = [r for r in logs(cfg2, "read-") if r["ev"] == "served"]
        served = load_served(cfg2) if os.path.exists(os.path.join(cfg2["run"], "served-0.json")) else []
        r_max = max([r["r"] for r in reads] or [None]) if reads else None
        late = None
        if r_max is not None:
            late = rep.append("fo", r_max, [sync_entry("fo", "late-after-failover", r_max)])[0]
        out = {"replication_state_before_crash": [r[0] for r in repl_state],
               "promoted": promoted, "acked": sum(a["ev"] == "ack" for a in acks),
               "acked_missing_on_promoted": len(acked_missing(f, acks)),
               "served_reads_logged": len(reads), "served_sets_contradicted_on_promoted":
                   len(served_contradictions(f, served)) if served else None,
               "max_served_r": r_max, "late_append_at_max_served_r": late,
               "promoted_frontier_vs_max_served": (rep.closed("fo", [], 1e18), r_max)}
    finally:
        if sync:
            try:
                env.restart_backend()
            except Exception:                                                # noqa: BLE001
                pass
            env.set_conf("synchronous_standby_names", None)
        env.drop_replica()                                                   # discard the promoted side
        try:
            env.restart_backend()
        except Exception:                                                    # noqa: BLE001
            pass
        env.ensure_replica()                                                 # a fresh standby of the old primary
    ok = out["acked_missing_on_promoted"] == 0 and out["late_append_at_max_served_r"] in (None, "READ_CLOSED") and \
        out["replication_state_before_crash"] == (["sync"] if sync else ["async"])
    out["result"] = "PASS" if ok else "FAIL"
    return out


def E3_failover_async(cfg):
    return _failover(cfg, sync=False)


def E3_failover_sync(cfg):
    return _failover(cfg, sync=True)


TESTS = {"E1": E1, "E2": E2, "E3": E3, "E4": E4, "E5": E5, "E6": E6, "E7": E7, "E8": E8, "E9": E9,
         "E7-run3": E7, "E3c": E3_control, "E3f-async": E3_failover_async, "E3f-sync": E3_failover_sync}


def main(env_spec, out_dir, which):
    boot()
    os.makedirs(out_dir, exist_ok=True)
    import hashlib
    with open(__file__, "rb") as fh:
        rev = hashlib.sha256(fh.read()).hexdigest()
    with open(os.path.join(out_dir, "driver-revision.txt"), "a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} c5_driver.py sha256={rev} tests={' '.join(which)}\n")
    results = {}
    for name in which:
        run = os.path.join(out_dir, name)
        os.makedirs(run, exist_ok=True)
        cfg = {"env": env_spec, "run": run}
        t = time.time()
        try:
            res = TESTS[name](cfg)
        except Exception:                                                     # noqa: BLE001
            res = {"result": "ERROR", "traceback": traceback.format_exc()[-2000:]}
        res.pop("_j", None)
        res["wall_s"] = round(time.time() - t, 1)
        results[name] = res
        with open(os.path.join(run, "result.json"), "w") as f:
            json.dump(res, f, indent=1, default=str)
        print(name, res.get("result"), json.dumps(res, default=str)[:600], flush=True)
    return results


if __name__ == "__main__":
    spec = json.loads(sys.argv[1])
    main(spec, sys.argv[2], sys.argv[3:] or list(TESTS))
