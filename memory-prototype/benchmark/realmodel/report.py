"""Compare real-model runs (Lane A3). Reads benchmark/results/realmodel/*.json (not superseded/ or smoke/) and
prints a markdown comparison: one column per run (extractor × model × prompt × core config).

  PYTHONIOENCODING=utf-8 python benchmark/realmodel/report.py > ../memory-real-model-baseline-tables.md
"""
import glob
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(os.path.dirname(HERE), "results", "realmodel")


def load():
    runs = []
    for f in sorted(glob.glob(os.path.join(RES, "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        runs.append(d)
    return runs


def label(d):
    return "%s · %s · %s · %s · reps %d" % (d["extractor"], d["model"].replace("claude-", ""),
                                          d["prompt_version"], d["core_config"], d["reps"])


def main():
    runs = load()
    out = ["# Real-model runs: comparison tables (generated)", ""]
    out.append("| run | calls | live calls | cost USD | malformed | truncated | provider errors | wall s |")
    out.append("|---|---|---|---|---|---|---|---|")
    for d in runs:
        calls = d["calls"]
        cost = sum((c["meta"].get("cost_usd") or 0) for c in calls if c["meta"].get("cache") == "miss")
        out.append("| %s | %d | %d | %.2f | %d | %d | %d | %s |" % (
            label(d), len(calls), sum(1 for c in calls if c["meta"].get("cache") == "miss"), cost,
            sum(1 for c in calls if c["parse_error"]),
            sum(1 for c in calls if c["meta"].get("stop_reason") == "max_tokens"),
            sum(1 for c in calls if c["meta"].get("error")), d.get("wall_s")))
    datasets = sorted({ds for d in runs for ds in d["summary"]})
    for ds in datasets:
        metrics = sorted({m for d in runs for m in d["summary"].get(ds, {}).get("per_metric", {})})
        out += ["", "## %s: expectations (pass / fail / n_a)" % ds, "",
                "| metric | " + " | ".join(label(d) for d in runs) + " |",
                "|---|" + "---|" * len(runs)]
        for m in metrics:
            cells = []
            for d in runs:
                v = d["summary"].get(ds, {}).get("per_metric", {}).get(m)
                cells.append("%d / %d / %d" % (v["pass"], v["fail"], v["n_a"]) if v else "—")
            out.append("| %s | %s |" % (m, " | ".join(cells)))
        langs = sorted({lg for d in runs for lg in d["summary"].get(ds, {}).get("recall_per_language", {})})
        out += ["", "Recall per language (pass / fail):", "",
                "| lang | " + " | ".join(label(d) for d in runs) + " |", "|---|" + "---|" * len(runs)]
        for lg in langs:
            cells = []
            for d in runs:
                v = d["summary"].get(ds, {}).get("recall_per_language", {}).get(lg)
                cells.append("%d / %d" % (v["pass"], v["fail"]) if v else "—")
            out.append("| %s | %s |" % (lg, " | ".join(cells)))
        classes = sorted({k for d in runs if d["extractor"] == "new"
                          for k in d["summary"].get(ds, {}).get("proposal_classes", {})})
        newruns = [d for d in runs if d["extractor"] == "new"]
        if newruns:
            out += ["", "Proposal outcome classes (new extractor):", "",
                    "| class | " + " | ".join(label(d) for d in newruns) + " |", "|---|" + "---|" * len(newruns)]
            for k in classes:
                out.append("| %s | %s |" % (k, " | ".join(str(d["summary"].get(ds, {}).get("proposal_classes", {})
                                                                .get(k, 0)) for d in newruns)))
        out += ["", "Failing expectations:", ""]
        for d in runs:
            out.append("- **%s**: %s" % (label(d), ", ".join(d["summary"].get(ds, {}).get("failing", [])) or "none"))
    leg = [d for d in runs if d["extractor"] == "legacy"]
    for d in leg:
        out += ["", "## Legacy final facts (%s, rep 0), for manual review" % label(d), ""]
        for s in d["scenarios"]:
            if s["rep"] == 0 and s.get("final_facts"):
                bad = [e["metric"] for e in s["expectations"] if not e["ok"]]
                if bad:
                    out.append("- `%s` (%s): %s" % (s["scenario"], ", ".join(bad),
                                                    json.dumps(s["final_facts"], ensure_ascii=False)))
    print("\n".join(out))


if __name__ == "__main__":
    main()
