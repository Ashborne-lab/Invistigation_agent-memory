# OLBrain Memory: pure-core prototype (Lane A hardened)

This is an isolated, executable model of the memory semantics in [`../memory-implementation-spec.md`](../memory-implementation-spec.md), as reconciled in [`../memory-contract-reconciliation.md`](../memory-contract-reconciliation.md). It is reviewed in [`../memory-architecture-v2-red-team.md`](../memory-architecture-v2-red-team.md) and hardened in Lane A ([`../memory-lane-a-status-v1.md`](../memory-lane-a-status-v1.md)).

**What it touches:**
- no production repository, Firestore, rules, deployment, contract or identity code;
- a real model only through `benchmark/realmodel/`, on synthetic data.

**Dependencies:** Python 3.12 standard library, plus `pytest`. The real-model harness also needs the `claude` CLI or an `ANTHROPIC_API_KEY`.

## Configurations (`memory_core/config.py`)

| Name | Meaning |
|---|---|
| `DEFAULT` | The implementation spec / v2 **as written**. Every red-team and Lane A defect reproduces |
| `F_ONLY` | Prototype findings F-1, F-3, F-4, F-6, F-7, F-8 (the previous "amended") |
| `AMENDED` | **The reviewed architecture:** F-* + red-team R-* + Lane A LA-*. Each change is a named flag, so its effect can be isolated with `with_(AMENDED, flag=...)` |

## What is implemented

| Module | Pure? | What |
|---|---|---|
| `model`, `ids`, `normalise`, `policy`, `gate`, `temporal`, `resolve`, `fence`, `render` | yes | As before, plus: sealed hashes, dedup keys, WORM refs (ids); future markers (clause-level, LA-2), sanitiser, cross-script search tokens (normalise); seal, future-marker, anchor-to-pending (LA-13), normaliser fallback (LA-14), canonical values (LA-18), replacement-retraction drop (LA-16) and retraction records (LA-9) (gate); current-policy admission and receipt-order tie-break (resolve); structured, capped, quote-free rendering with a block hash (render) |
| `handle` | yes | Conversation-bound signed memory handles (R-4) |
| `commitments` | yes | Evidence-backed event log plus a deterministic projection, alongside the v2 mutable-row model for comparison (R-10) |
| `knowledge` | yes | Agent Knowledge: lineage, contributor threshold k, quasi-identifier check, erasure and undo handling (R-11) |
| `lockorder` | yes | Lock-order model and a deadlock detector (R-21) |
| `runtime` | no (harness) | Evidence store (FS) and memory store (PG) partitions. Write → register → seal (R-1/R-2/R-24); dedup (R-3); handles; accounts (R-5); derivation fence (R-6); re-extraction by lineage (R-9); search projection (R-17); knowledge; commitments; commit records with recorded outcomes (LA-1); retraction records (LA-9); path-based merge ids (LA-3); merge guards (LA-12) |
| `runtime/restore.py` | no | Restore model: snapshot, restore of FS, PG or both, and the protocol (WORM replay, recorded roll-forward, watermark, seal re-verification, epoch high-water) |
| `tools/registry_build.py` | — | Lifecycle Registry source, JSON generator and completeness check |
| `benchmark/realmodel/` | — | `olb.memory.extract/1` protocol; provider adapters (Claude CLI, Anthropic API, cache/replay); the legacy extractor (verbatim prompt from runtime@daee3f9); the runner |

## How to run

```bash
cd investigation/memory-prototype
python -m pytest tests -q                                   # 388 tests (default seeds)
PROP_SEEDS=1000 PROP_STEPS=150 python -m pytest tests/test_redteam_properties.py -q   # invariant stress
RESTORE_SEEDS=2000 python -m pytest tests/test_restore.py -q                          # restore stress
PYTHONIOENCODING=utf-8 python benchmark/run.py              # scripted core benchmark (spec / f_only / reviewed)
python tools/registry_build.py --check                      # registry completeness
# real-model baseline (synthetic data; responses cached by request hash; --offline re-scores without calls)
PYTHONIOENCODING=utf-8 python benchmark/realmodel/run_real.py --extractor new --model claude-haiku-4-5-20251001 \
    --datasets lane1_v1,lane1_rt_v1 --reps 2 --prompt v1
PYTHONIOENCODING=utf-8 python benchmark/realmodel/run_real.py --extractor legacy --model claude-haiku-4-5-20251001 \
    --datasets lane1_v1,lane1_rt_v1 --reps 2
```

## Test files

| File | Tests | Covers |
|---|---|---|
| `test_gate`, `test_ids_support`, `test_temporal_conflict`, `test_fence_*`, `test_retrieval_manifest`, `test_legacy_baseline`, `test_properties` | 173 | The original prototype suite (all still pass) |
| `test_redteam_findings.py` | 69 | One regression per modelable C-*/M-* finding (DEFAULT shows the defect, AMENDED the fix), plus LA-2…LA-18 |
| `test_redteam_properties.py` | 41 | Randomised falsification of the 12 Lane A invariants, plus a "teeth" test that the same generator finds violations under DEFAULT |
| `test_restore.py` | 54 | Restore scenarios 1–8, LA-1, and a randomised restore property (FS/PG/both × random point) |
| `adversarial/test_catalog.py` | 48 | The A9 catalogue: security (including the Lumen bypass, run on SQLite against a faithful copy of the production check), poisoning, erasure, identity, concurrency, commitments |

## Benchmarks

**Scripted core benchmark** (`benchmark/results/latest.md`, dataset `lane1-v1.1`):
- **spec**: blocking metrics FAIL (F-1, F-3, F-9);
- **f_only**: PASS except F-9;
- **reviewed**: PASS, with **no failures**.

**Real-model baseline:** see [`../memory-real-model-baseline-v1.md`](../memory-real-model-baseline-v1.md).
