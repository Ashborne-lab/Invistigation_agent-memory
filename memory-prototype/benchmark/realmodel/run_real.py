"""Lane A2/A3: real-model extraction baseline. Reproducible run command:

  PYTHONIOENCODING=utf-8 python benchmark/realmodel/run_real.py --extractor new --model claude-haiku-4-5-20251001 \
      --datasets lane1_v1,lane1_rt_v1 --reps 2 --workers 6
  PYTHONIOENCODING=utf-8 python benchmark/realmodel/run_real.py --extractor legacy --model claude-haiku-4-5-20251001 \
      --datasets lane1_rt_v1,lane1_v1 --reps 1
  add --offline to re-score from the response cache without any model call (e.g. under another --config).

Writes benchmark/results/realmodel/<run_id>.json (machine-readable, one record per model call and per scenario).
Synthetic data only. Thresholds are NOT defined here: this is a baseline.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

from memory_core.config import AMENDED, DEFAULT, F_ONLY  # noqa: E402
from memory_core.normalise import future_marker, fold, tokens  # noqa: E402
from memory_core.runtime import Memory  # noqa: E402
from realmodel import legacy as LEG  # noqa: E402
from realmodel import protocol as PR  # noqa: E402
from realmodel.providers import AnthropicAPIProvider, CachedProvider, ClaudeCLIProvider  # noqa: E402
import run as LANE1  # noqa: E402

ORG = "org1"
PROMPT = "v1"
CONFIGS = {"amended": AMENDED, "default": DEFAULT, "f_only": F_ONLY}
FILLER = ("We had a long discussion about many unrelated things, the weather, cricket scores, a recipe my aunt "
          "shared, delivery timings and so on. ") * 40
SECURITY_CODES = {"security_key", "authority"}


def _text(t):
    return t.replace("LONG_FILLER", FILLER)


SCRIPTED_ONLY = {"anomalies_at_least", "claim_count"}   # assume a scripted adversarial/duplicate proposal


def check(m, caller, subj, st):
    if st["expect"] in SCRIPTED_ONLY:
        return None                                       # not applicable to a real model (reported n/a)
    if st["expect"] == "current_not":
        r = m.get_current_state(caller, subj[st["user"]], st["key"], now=st.get("now", 1e6))
        return not (r.value is not None and r.value[1] == st["value"])
    if st["expect"] == "no_claim_key":
        return not [c for c in m.claims.values() if c.state.status == "active" and c.content.key.startswith(st["key"])]
    return LANE1._check(m, caller, subj, st)


def classify(m, proposals, rep, batch_ids):
    """Per-proposal outcome categories from the gate report plus the evidence."""
    out = Counter()
    rejected = {r.index: r for r in rep.rejections}
    fenced = {i for i, _ in rep.fenced}
    agent_text = " ".join(fold(m.evidence[e].text) for e in batch_ids if e in m.evidence
                          and m.evidence[e].author_role == "agent")
    user_text = " ".join(fold(m.evidence[e].text) for e in batch_ids if e in m.evidence
                         and m.evidence[e].author_role == "user")
    for i, p in enumerate(proposals):
        out["proposals"] += 1
        r = rejected.get(i)
        key = str(p.get("key", ""))
        v = str((p.get("value") or {}).get("v", "")) if isinstance(p.get("value"), dict) else ""
        if r is None and i not in fenced:
            out["accepted"] += 1
        elif i in fenced:
            out["fenced"] += 1
        else:
            out["rejected"] += 1
            out["reject:" + r.code + ":" + (r.detail.split(":")[0] if r.detail else "")] += 1
            if r.code in SECURITY_CODES:
                out["security_key_proposal"] += 1
            if r.code == "grounding" and r.detail == "quote_not_in_evidence":
                out["hallucinated_quote"] += 1
            if r.code == "grounding" and r.detail == "agent_or_system_text":
                out["agent_anchor_proposal"] += 1
            if r.detail == "future_without_validity":
                out["future_marker_rejected"] += 1
        if v and fold(v) and all(t in agent_text for t in tokens(v)) and not all(t in user_text for t in tokens(v)):
            out["value_only_in_agent_text"] += 1
        if (p.get("valid_time") or {}).get("expression") in ("next week", "next month", "tomorrow") or \
                str((p.get("valid_time") or {}).get("expression", "")).startswith("in "):
            out["future_valid_time"] += 1
        if key.startswith(("account.role", "entitlement", "billing")):
            out["security_key_proposal_by_key"] += 1
    return out


def run_new(sc, provider, d, rep_no):
    m = Memory(d)
    caller = {"org": ORG, "agent": "agentA", "kind": "agent", "handle": lambda s: m.handle_for_subject(s, 0)}
    evs, subj, jobs, merges, results, calls = {}, {}, {}, {}, [], []

    def model_commit(job, t):
        msgs = [{"evidence_id": e, "role": {"user": "user", "agent": "agent", "tool": "tool"}.get(
            m.evidence[e].author_role, m.evidence[e].author_role), "text": m.evidence[e].text}
            for e in job.context_ids if e in m.evidence]
        existing = sorted({(c.content.key, c.content.value[1]) for c in m._member_claims(job.subject_id)
                           if c.state.status == "active"})
        system, user = PR.build_request(msgs, [{"key": k, "value": v} for k, v in existing], PROMPT)
        text, meta = provider.complete(system, user)
        props, err = PR.parse_response(text)
        r = m.commit(job, props, t)
        cls = classify(m, props, r, job.context_ids)
        calls.append({"scenario": sc["id"], "rep": rep_no, "parse_error": err, "meta": meta,
                      "classes": dict(cls), "proposals": props,
                      "rejections": [(x.index, x.code, x.detail) for x in r.rejections],
                      "created": len(r.created), "retracted": len(r.retracted)})

    for st in sc["steps"]:
        do = st.get("do")
        if do == "say":
            ev = m.ingest(ORG, "agentA", "wa", st["user"], "s-" + st["user"], st.get("role", "user"), _text(st["text"]),
                          st["t"], source_system=st.get("source_system"))
            evs[st["as"]] = ev
            subj[st["user"]] = ev.subject_id
        elif do == "extract":
            job = m.prepare(subj[st["user"]])
            if job.evidence_ids:
                model_commit(job, st["t"])
        elif do == "prepare":
            only = [evs[x].evidence_id for x in st["only"]] if "only" in st else None
            jobs[st["as"]] = m.prepare(subj[st["user"]], only)
        elif do == "commit":
            model_commit(jobs[st["job"]], st["t"])
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
            model_commit(m.recovery_job(merges[st["merge"]], subj[st["user"]]), st["t"])
        elif do == "transfer":
            m.transfer(subj[st["user"]], st["t"])
        elif "expect" in st:
            try:
                ok = check(m, caller, subj, st)
            except Exception as e:                               # an expectation the run cannot evaluate
                ok = None
                st = dict(st, error=str(e)[:100])
            results.append({"metric": st["metric"], "expect": st["expect"], "ok": ok})
    return {"scenario": sc["id"], "lang": sc["lang"], "category": sc.get("category"), "rep": rep_no,
            "expectations": results}, calls


def _legacy_expect(sc):
    if "legacy_expect" in sc:
        return sc["legacy_expect"]
    le = {"recall": [], "forbidden_final": []}
    for st in sc["steps"]:
        if st.get("expect") == "current" and st.get("value") and st.get("status", "VALUE") == "VALUE":
            le["recall"].append((st["value"], st.get("user")))
        if st.get("expect") == "context_excludes":
            le["forbidden_final"].append((st["text"], st.get("user")))
    return le if (le["recall"] or le["forbidden_final"]) else None


FUTURE_WORDS = ("next month", "planning", "plans to", "will ", "moving", "shift", "relocat", "upcoming", "intend")


def run_legacy(sc, provider, rep_no):
    le = _legacy_expect(sc)
    if le is None or any(st.get("do") in ("merge", "undo", "forget_me", "forget_fact", "erase", "recover", "transfer",
                                          "prepare", "commit") for st in sc["steps"]):
        return None, []
    facts, calls, msgs, done = {}, [], [], 0
    for st in sc["steps"]:
        if st.get("do") == "say":
            msgs.append((st["user"], st.get("role", "user"), _text(st["text"])))
        elif st.get("do") == "extract":
            while done < len(msgs):                               # one call per user turn, paired with the reply
                u, role, text = msgs[done]
                done += 1
                if role != "user":
                    continue
                reply = msgs[done][2] if done < len(msgs) and msgs[done][1] == "agent" else ""
                system, user = LEG.build_request(facts.get(u, []), text, reply)
                out, meta = provider.complete(system, user)
                new, err = LEG.parse(out)
                calls.append({"scenario": sc["id"], "rep": rep_no, "parse_error": err, "meta": meta, "facts": new})
                if new is not None:
                    facts[u] = new
    def final(user=None):            # scored per user when the expectation names one
        return " ".join(f.lower() for u, fs in facts.items() if user is None or u == user for f in fs)
    res = []
    for item in le.get("recall", []):
        alt, user = item if isinstance(item, (list, tuple)) else (item, None)
        res.append({"metric": "recall", "ok": any(a.lower() in final(user) for a in alt.split("|"))})
    for item in le.get("forbidden", []) + le.get("forbidden_final", []):
        tok, user = item if isinstance(item, (list, tuple)) else (item, None)
        res.append({"metric": "false_memory", "ok": tok.lower() not in final(user)})
    final = final()
    for pat in le.get("forbidden_pattern", []):
        res.append({"metric": "false_memory", "ok": pat.lower() not in final})
    if "future_value" in le:
        bad = any(any(a in f.lower() for a in le["future_value"].split("|")) and
                  not any(w in f.lower() for w in FUTURE_WORDS) for fs in facts.values() for f in fs)
        res.append({"metric": "future_as_current", "ok": not bad})
    if "max_facts" in le:
        res.append({"metric": "hallucinated_memory", "ok": sum(len(v) for v in facts.values()) <= le["max_facts"]})
    return {"scenario": sc["id"], "lang": sc["lang"], "category": sc.get("category"), "rep": rep_no,
            "expectations": res, "final_facts": facts}, calls


def summarise(scen, calls):
    per_metric = defaultdict(lambda: [0, 0, 0])
    per_lang = defaultdict(lambda: [0, 0])
    for s in scen:
        for e in s["expectations"]:
            idx = 0 if e["ok"] else (2 if e["ok"] is None else 1)
            per_metric[e["metric"]][idx] += 1
            if e["metric"] == "recall" and e["ok"] is not None:
                per_lang[s["lang"]][0 if e["ok"] else 1] += 1
    cls = Counter()
    for c in calls:
        cls.update(c.get("classes", {}))
        cls["calls"] += 1
        cls["malformed"] += bool(c["parse_error"])
        cls["truncated"] += (c["meta"].get("stop_reason") == "max_tokens")
        cls["provider_errors"] += bool(c["meta"].get("error"))
    return {"per_metric": {k: {"pass": v[0], "fail": v[1], "n_a": v[2]} for k, v in sorted(per_metric.items())},
            "recall_per_language": {k: {"pass": v[0], "fail": v[1]} for k, v in sorted(per_lang.items())},
            "proposal_classes": dict(sorted(cls.items())),
            "failing": sorted({"%s/%s" % (s["scenario"], e["metric"]) for s in scen for e in s["expectations"]
                               if e["ok"] is False})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", choices=["new", "legacy"], default="new")
    ap.add_argument("--provider", choices=["claude-cli", "anthropic-api"], default="claude-cli")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--datasets", default="lane1_v1,lane1_rt_v1")
    ap.add_argument("--config", default="amended", choices=list(CONFIGS))
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--prompt", default="v1", choices=["v1", "v2"])
    a = ap.parse_args()
    global PROMPT
    PROMPT = a.prompt
    inner = ClaudeCLIProvider(a.model) if a.provider == "claude-cli" else AnthropicAPIProvider(a.model)
    cache = os.path.join(ROOT, "benchmark", "results", "realmodel", "cache")
    scenarios = []
    for ds in a.datasets.split(","):
        d = json.load(open(os.path.join(ROOT, "benchmark", ds + ".json"), encoding="utf-8"))
        scenarios += [(d["version"], s) for s in d["scenarios"] if not a.only or s["id"] in a.only.split(",")]
    jobs = [(ds, s, r) for r in range(a.reps) for ds, s in scenarios]

    def one(job):
        ds, sc, r = job
        prov = CachedProvider(inner, cache, rep=r, offline=a.offline)
        if a.extractor == "new":
            res, calls = run_new(sc, prov, CONFIGS[a.config], r)
        else:
            res, calls = run_legacy(sc, prov, r)
        if res is not None:
            res["dataset"] = ds
        return res, calls

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        out = list(ex.map(one, jobs))
    scen = [r for r, _ in out if r is not None]
    calls = [c for _, cs in out for c in cs]
    run_id = "%s__%s__%s__%s__%s" % (a.extractor, a.model.replace("/", "_"),
                                     PR.PROMPT_VERSIONS[a.prompt] if a.extractor == "new" else "legacy-daee3f9", a.config,
                                     time.strftime("%Y%m%dT%H%M%S"))
    report = {"run_id": run_id, "extractor": a.extractor, "protocol": PR.PROTOCOL_VERSION if a.extractor == "new"
              else "legacy-facts", "schema": PR.SCHEMA_VERSION if a.extractor == "new" else "legacy-facts-json",
              "prompt_version": PR.PROMPT_VERSIONS[a.prompt] if a.extractor == "new" else "legacy@daee3f9",
              "provider": inner.name, "provider_version": getattr(inner, "version", None), "model": a.model,
              "core_config": a.config, "datasets": a.datasets, "reps": a.reps, "offline": a.offline,
              "wall_s": round(time.time() - t0, 1), "summary": {
                  ds: summarise([s for s in scen if s["dataset"] == ds],
                                [c for c in calls if any(c["scenario"] == s["id"] for _, s in scenarios
                                                         if _ == ds)])
                  for ds in sorted({x[0] for x in scenarios})},
              "scenarios": scen, "calls": calls}
    os.makedirs(os.path.join(ROOT, "benchmark", "results", "realmodel"), exist_ok=True)
    path = os.path.join(ROOT, "benchmark", "results", "realmodel", run_id + ".json")
    json.dump(report, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
    print(json.dumps({"run_id": run_id, "wall_s": report["wall_s"], "summary": report["summary"]}, indent=1,
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
