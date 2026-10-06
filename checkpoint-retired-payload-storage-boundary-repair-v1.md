# Checkpoint Retired-Payload Storage-Boundary Repair v1

**Date:** 2026-10-06.

**Classification:** **ENGINEERING CLOSURE.** A prototype code + test repair. Derived checkpoint payloads only. No contract change, no journal semantics change.

---

## 1. Observed defect

`CheckpointStore.discard` (retirement or rejection) and `CheckpointStore.drop_staged` (a staged payload that failed verification) deleted the payload with `self.storage.vault.pop(...)`. That reaches into the storage object's in-memory dict instead of calling a storage operation.

| Store | Effect |
|---|---|
| Explicit and implied reference stores | The dict **is** the storage, so the payload was really removed. Correct by accident |
| `PgFrontierStore` (PostgreSQL, C-5) | `vault` is an unused in-memory attribute; the payload lives in `c5.vault`. The retired or dropped **row survived**. Answer (d) of the brief's Phase 1 for the reference stores; answer (a) for PostgreSQL |

First observed by probe P-CKPT in the C-5 evaluation (`storage-eval-results/c5-postgres-v1-final/P-CKPT.json`: payload rows 2 → 2 after discard).

## 2. Reproduction

The "old behaviour" mutation reinstates `vault.pop` and runs the new suite with PostgreSQL available. **10 failures**, including:
- every PostgreSQL retirement case (the row is still present by owner-level SQL);
- the PostgreSQL staged-drop case;
- PostgreSQL CPD-3, CPD-4 and CPD-14.

The reference-store retirement cases pass under the old code. That confirms the defect was specific to database-backed stores.

## 3. Existing intended semantics (no contract change)

- `checkpoint-maintenance-v1.md` §5: **"Retirement removes a derived payload and marks it unusable. No fact is ever touched."**
- `durable-journal-compaction-contract-v1.md`: "deletion of a derived payload (retirement)"; "v1 'compaction' retires superseded checkpoints (derived data). It deletes no fact."
- **Logical retirement:** the ref goes into `unusable`, so it is never a candidate (`candidates` excludes it).
- **Physical cleanup:** the payload is deleted through the storage boundary.
- **Authoritative data:** journal facts are never deleted, changed or rewritten.

**Outcome A:** the existing contract already requires this. Code and test repair only.

## 4. Exact storage-boundary change

| File | Change |
|---|---|
| `memory_core/storage_boundary/__init__.py` | `DERIVED_REF = "ckpt:"` (the existing checkpoint ref prefix). **New `StorageBoundary.drop_derived(key_id, ref)`:** deletes one derived payload; **refuses** any non-derived ref (`AppendRejected("not_a_derived_payload")`), so a journal fact's sealed payload can never be deleted by it (facts leave only through `destroy_key`, i.e. erasure); idempotent (absent → no-op) |
| `memory_core/storage_adapters/postgres_boundary.py` | `PgFrontierStore.drop_derived`: the same ref guard, then `DELETE FROM c5.vault WHERE key_id = %s AND ref = %s` inside one transaction under `SET LOCAL app.ns` (RLS-scoped to the tenant) |
| `memory_core/journal_compaction/__init__.py` | `discard` and `drop_staged` now call `self.storage.drop_derived(...)`. No other change |

It is deliberately not a generic delete: one exact (key, ref), derived refs only.

## 5. Lifecycle interaction

BUILD → STAGE → VERIFY → PUBLISH → RETIRE is unchanged.
- `discard` still marks the ref unusable **before** the physical delete, so a crash in between leaves it logically retired and never served.
- `maintain` and `compact` still retire only non-newest checkpoints, after publication.
- Canonical signatures, validation, fallback, both encodings, retrieval and authorization are untouched.

## 6. Crash and retry behaviour

**Crash between logical and physical retirement.** The ref is unusable in that process, and reads fall back or use the newer checkpoint (identical answers, tested). The payload remains until a retry.
- Retrying `discard` or `drop_derived` deletes it. Repeating either is a deterministic no-op.
- Other payloads are never affected.

**This repair adds no stronger guarantee than maintenance v1:**
- the checkpoint index is process state;
- after a whole-process crash the retired payload is an **orphan**, never selected;
- its garbage collection remains the existing operational housekeeping item, like crash-time staged orphans.

## 7. Security and isolation

| Property | How it holds |
|---|---|
| Customer / partition | Deletion is by `(key:<partition>, ref)`. A wrong customer key deletes nothing (CPD-4, on every store) |
| Checkpoint version | Refs carry a random nonce, so one exact payload is targeted (CPD-3) |
| Journal facts | Refused by the derived-ref guard (boundary test); fact payloads unchanged after retirement (CPD-5) |
| Tenant (PostgreSQL) | RLS plus `SET LOCAL`: another namespace can neither see nor delete the row (CPD-14) |

## 8. Test matrix

`tests/test_checkpoint_retired_payload_cleanup.py`: **31 tests** = 10 scenarios.
- **6 + 8 × 3**: CPD-1/2/6/7/8/12 over 3 stores × 2 encodings, plus 8 scenarios over 3 stores;
- **+1** PostgreSQL-only (CPD-14).

| ID | Covered by | Stores |
|---|---|---|
| CPD-1, 2, 6, 7, 8, 12 | `test_cpd1_2_6_7_8_12_…` (full and ref encodings) | explicit, implied, PostgreSQL |
| CPD-3 | `test_cpd3_…` | all 3 |
| CPD-4 + Case D | `test_cpd4_…` | all 3 |
| CPD-5 | `test_cpd5_…` | all 3 |
| Fact payloads refused | `test_the_boundary_refuses_to_delete_a_journal_fact_payload` | all 3 |
| CPD-9, 10, 11 + Case C | `test_cpd9_10_11_…` | all 3 |
| Case A (verification failure, staged drop) | `test_case_a_a_staged_payload_…` | all 3 |
| Case A (crash orphan) | `test_case_a_a_crash_orphan_…` | all 3 |
| Case E | `test_case_e_…` | all 3 |
| CPD-13 | Owner-level SQL row counts inside the CPD-1 test | PostgreSQL |
| CPD-14 | `test_cpd14_rls_…` | PostgreSQL |

**Case E, stated precisely:**
- maintenance and compaction never retire the newest published checkpoint (tested);
- a **direct** `discard` of the active checkpoint is the existing fail-safe **rejection** path for a checkpoint a reader finds invalid. The contract permits it, so no refusal rule was invented. Reads then fall back to the journal with an identical answer (tested).

**Results:**
- **With PostgreSQL (venv + disposable cluster):** **31/31**.
- **System Python (no PostgreSQL driver):** 20 pass, 11 PostgreSQL cases **skipped** (not applicable in that environment).
- **Full suite:** **1888 passed, 11 skipped** (1868 + 31 new; the 11 skips are the PostgreSQL cases).
- **PostgreSQL connector suites, unchanged:** boundary 44/44, X-1 64/64, conformance 144/144.
- **Checkpoint suites, unchanged:** maintenance 82, pruning 58, compaction 93, consumers 65, fast path 51, per-operation validation 120.

## 9. Mutation result (bounded: 2)

Runner: `scratchpad/mutate_cpd.py`, with PostgreSQL available.

| Mutation | Result |
|---|---|
| Old behaviour (`vault.pop` in `discard` and `drop_staged`) | **CAUGHT**: 10 failed |
| The PostgreSQL delete ignores the customer key | **CAUGHT**: CPD-4 [postgres] failed |

Both files were restored byte-for-byte (asserted).

## 10. Final status

**ENGINEERING CLOSURE.** The defect is confirmed (PostgreSQL) and repaired through a narrow storage-boundary operation, with regression and isolation tests.
- No contract changed. No [CONTRACT_GAP].
- **Note:** the `code_gap` text in the historical `P-CKPT.json` evidence describes the pre-repair state and is kept as recorded evidence.
- Crash-orphan garbage collection remains the existing operational housekeeping item.
