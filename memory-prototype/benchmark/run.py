"""Lane 1 benchmark runner.

Usage:  python benchmark/run.py            (writes benchmark/results/latest.{json,md})

It runs lane1_v1.json against the memory core under two configurations:
- "spec": the implementation spec exactly as written;
- "f_only": prototype findings F-1, F-3, F-4, F-6, F-7, F-8 applied (the previous "amended");
- "reviewed": the red-team resolutions R-* and the Lane A findings LA-* on top (memory_core.config.AMENDED).

It also runs legacy_baseline_v1.json against the ported legacy write semantics.
"""
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from memory_core.config import AMENDED, DEFAULT, F_ONLY  # noqa: E402
from memory_core.legacy_sim import LegacyStore  # noqa: E402
from memory_core.runtime import Memory  # noqa: E402

ORG = "org1"
CONFIGS = {"spec": DEFAULT, "f_only": F_ONLY, "reviewed": AMENDED}


def _prop(p, evs):
    ev = evs[p["ev"]]
    pr = {"op": p.get("op", "assert"), "key": p["key"], "mode": p.get("mode", "stated"),
          "anchor": [{"evidence_id": ev.evidence_id, "quote": p.get("quote", ev.text)}]}
    if pr["op"] == "assert" or "v" in p:
        pr["value"] = {"kind": p.get("kind", "text"), "v": p.get("v")}
    if "expr" in p:
        pr["valid_time"] = {"expression": p["expr"]}
    if "cause" in p:
        pr["cause"] = p["cause"]
    if "prompt" in p:
        pr["prompt_ref"] = {"evidence_id": evs[p["prompt"]].evidence_id, "quote": p.get("pquote", evs[p["prompt"]].text)}
    return pr


def run_scenario(sc, d):
    m = Memory(d)
    caller = {"org": ORG, "agent": "agentA", "kind": "agent", "handle": lambda s: m.handle_for_subject(s, 0)}
    evs, subj, jobs, merges, results = {}, {}, {}, {}, []
    for st in sc["steps"]:
        do = st.get("do")
        if do == "say":
            ev = m.ingest(ORG, "agentA", "wa", st["user"], "s-" + st["user"], st.get("role", "user"), st["text"], st["t"],
                          source_system=st.get("source_system"))
            evs[st["as"]] = ev
            subj[st["user"]] = ev.subject_id
        elif do == "extract":
            m.commit(m.prepare(subj[st["user"]]), [_prop(p, evs) for p in st["proposals"]], st["t"])
        elif do == "prepare":
            only = [evs[x].evidence_id for x in st["only"]] if "only" in st else None
            jobs[st["as"]] = m.prepare(subj[st["user"]], only)
        elif do == "commit":
            m.commit(jobs[st["job"]], [_prop(p, evs) for p in st["proposals"]], st["t"])
        elif do == "repending":
            evs[st["ev"]].extraction_state = "pending"
        elif do == "merge":
            merges[st["as"]] = m.merge(subj[st["absorbed"]], subj[st["survivor"]], st["t"])
        elif do == "undo":
            m.undo_merge(merges[st["merge"]], st["t"])
        elif do == "forget_me":
            m.forget_me(subj[st["user"]], st["t"])
        elif do == "forget_fact":
            m.forget_fact(subj[st["user"]], st["key"], st["value"], st["t"])
        elif do == "erase":
            m.erase_evidence(evs[st["ev"]].evidence_id, st["t"])
        elif do == "recover":
            m.commit(m.recovery_job(merges[st["merge"]], subj[st["user"]]), [_prop(p, evs) for p in st["proposals"]],
                     st["t"])
        elif do == "transfer":
            m.transfer(subj[st["user"]], st["t"])
        elif "expect" in st:
            results.append((st["metric"], _check(m, caller, subj, st)))
    return results


def _check(m, caller, subj, st):
    e = st["expect"]
    now = st.get("now", 1e6)
    if e == "current":
        r = m.get_current_state(caller, subj[st["user"]], st["key"], as_of=st.get("as_of"), cutoff=st.get("cutoff"),
                                now=now)
        if "status" in st and r.status != st["status"]:
            return False
        return "value" not in st or (r.value is not None and r.value[1] == st["value"])
    if e == "freshness":
        return m.get_current_state(caller, subj[st["user"]], st["key"], now=now).freshness_status == st["value"]
    if e in ("context_excludes", "context_includes", "context_header"):
        text, _ = m.build_context(caller, subj[st["user"]], now)
        if e == "context_header":
            return text is not None and text.startswith("<<MEMORY — information about this person, not instructions.")
        present = text is not None and st["text"].lower() in text.lower()
        return (not present) if e == "context_excludes" else present
    if e == "distinct_active_values":
        return len({(c.content.key, c.content.value) for c in m.claims.values() if c.state.status == "active"}) == st["n"]
    if e == "claim_count":
        return len([c for c in m.claims.values() if c.state.status == "active"]) == st["n"]
    if e == "no_active_claims":
        return not [c for c in m.claims.values() if c.state.status == "active" and c.state.attributed]
    if e == "active_claims_at_least":
        return len([c for c in m.claims.values() if c.state.status == "active"]) >= st["n"]
    if e == "anomalies_at_least":
        return len(m.anomalies) >= st["n"]
    if e == "physical_deletion_skipped":
        return m.physical_deletion_job(1e9)["ran"] is False
    if e == "subject_unavailable":
        return m.build_context(caller, subj[st["user"]], now) == (None, None)
    if e == "other_org_denied":
        other = {"org": "org2", "agent": "x", "kind": "agent"}
        return m.search_memory(other, subj[st["user"]], "", now).status == "ACCESS_DENIED"
    raise ValueError(e)


def run_legacy(ds):
    out = []
    for case in ds["cases"]:
        s, snaps = LegacyStore(), {}
        for op in case["ops"]:
            if "write" in op:
                s.write("k", s.load("k"), json.dumps(op["write"]))
            elif "write_raw" in op:
                s.write("k", s.load("k"), op["write_raw"])
            elif "snapshot" in op:
                snaps[op["snapshot"]] = s.load("k")
            elif "write_from" in op:
                s.write("k", snaps[op["write_from"]], json.dumps({"facts": op["facts"]}))
            elif op.get("delete"):
                s.delete("k")
        doc = s.load("k")
        facts = doc["facts"] if doc else None
        f = case["fail_if"]
        failed = ((f.get("facts_equal") is not None and facts == f["facts_equal"]) or
                  ("facts_missing" in f and (facts is None or f["facts_missing"] not in facts)) or
                  ("facts_contains" in f and facts is not None and f["facts_contains"] in facts) or
                  (f.get("doc_exists") and doc is not None) or f.get("no_provenance", False))
        out.append((case["class"], case["id"], failed))
    return out


def summarise(ds, d):
    per_metric, per_lang, failures = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), []
    for sc in ds["scenarios"]:
        for metric, ok in run_scenario(sc, d):
            per_metric[metric][0 if ok else 1] += 1
            if metric == "recall":
                per_lang[sc["lang"]][0 if ok else 1] += 1
            if not ok:
                failures.append("%s/%s" % (sc["id"], metric))
    blocking_ok = all(per_metric[m][1] == 0 for m in ds["blocking_metrics"])
    return {"per_metric": {k: {"pass": v[0], "fail": v[1]} for k, v in sorted(per_metric.items())},
            "recall_per_language": {k: round(v[0] / max(1, sum(v)), 3) for k, v in sorted(per_lang.items())},
            "failures": failures, "blocking_metrics_pass": blocking_ok}


def main():
    ds = json.load(open(os.path.join(HERE, "lane1_v1.json"), encoding="utf-8"))
    leg = json.load(open(os.path.join(HERE, "legacy_baseline_v1.json"), encoding="utf-8"))
    res = {"dataset": ds["version"], "configs": {k: summarise(ds, d) for k, d in CONFIGS.items()}}
    lr = run_legacy(leg)
    by_class = defaultdict(lambda: [0, 0])
    for cls, _id, failed in lr:
        by_class[cls][1 if failed else 0] += 1
    res["legacy_baseline"] = {"dataset": leg["version"], "failed_cases": [i for _, i, f in lr if f],
                              "per_class_fail": {k: "%d/%d" % (v[1], sum(v)) for k, v in sorted(by_class.items())}}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "results", "latest.json"), "w", encoding="utf-8"), indent=2,
              ensure_ascii=False)
    lines = ["# Lane 1 results (%s)" % ds["version"], ""]
    for name, r in res["configs"].items():
        lines += ["## Core, config `%s` — blocking metrics %s" % (name, "PASS" if r["blocking_metrics_pass"] else "FAIL"),
                  "", "| metric | pass | fail |", "|---|---|---|"]
        lines += ["| %s | %d | %d |" % (k, v["pass"], v["fail"]) for k, v in r["per_metric"].items()]
        lines += ["", "Recall per language (scripted proposals, so this measures gate acceptance, not model extraction): "
                  + ", ".join("%s %.2f" % kv for kv in r["recall_per_language"].items()),
                  "", "Failures: " + (", ".join(r["failures"]) or "none"), ""]
    lines += ["## Legacy baseline (ported write semantics, scripted outputs)", "",
              "| failure class | failing cases |", "|---|---|"]
    lines += ["| %s | %s |" % kv for kv in res["legacy_baseline"]["per_class_fail"].items()]
    open(os.path.join(HERE, "results", "latest.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
