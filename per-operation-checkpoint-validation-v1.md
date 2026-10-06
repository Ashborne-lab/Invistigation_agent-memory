# Per-Operation Checkpoint Validation Reuse v1

**Date:** 2026-10-05.

**Classification:** TARGET ARCHITECTURE. Prototype and test only. No production repository, infrastructure or database was touched.

**Result:** **CONFORMANT.** Within one logical operation, a checkpoint is now fully validated once, and later uses in the same operation reuse that validation. Measured full canonical-signature computations:

| Operation | Before | After |
|---|---:|---:|
| Gateway read | 3 | 1 |
| Context compile | 3 | 1 |
| Typed command | 4 | 2 |
| Maintenance | 5 | 3 |

**What did not change:**
- every result, error, side effect, fallback and OCC outcome;
- the canonical signature definition;
- what a reader can detect;
- the K9 in-write check and the staged checkpoint's verification, which each still run their own full validation.

**Labels:** [PROVEN] (by test), [DECISION] (engineering, within the brief), [INFERENCE].

**Tests:** `tests/test_per_operation_checkpoint_validation.py`, **120** tests.

---

## 1. Phase 0: the duplicate-validation call graph (from source)

A **full validation** is the existing `checkpoint_fold` path. It has three steps:
1. `validate(cp, facts)`, which checks contract, encoding, payload present, digest, prefix, tail, suffix after c, and policy position;
2. `load` (decode; with compact encoding, one vault read per referenced fact);
3. `state_signature(f) == cp.state_signature`.

Every number below was measured by instrumenting `state_signature`, `load` and `_deref`, not taken from a model.

### Gateway `get_current_state` / `search_history` / `compile_context` (3 validations each)

```text
Gateway._read
├─ journal.read → begin_read (close partition through r) → end_read
│   ├─ facts F1 = store.facts()
│   ├─ _read_preds(F1, s, r) → _checkpoint(advance=False) → checkpoint_fold      [validation 1]
│   ├─ close policy logs of those predicates through r
│   ├─ facts F2 = store.facts()
│   └─ _serve → served_trace(F2, s, r) → checkpoint_fold(advance to r)           [validation 2]
├─ facts F3 = store.facts()
└─ _view(F3, s, r) → open_view → checkpoint_fold(advance to r)                   [validation 3]
```

`compile_context` builds both its retrieval results from the one source opened in `_read`, so it also does 3.

### Typed command (4 validations)

```text
Gateway._admit
├─ _scratch(s, clock) → open_view(Fa, s, clock)                                  [validation 1: gate]
├─ journal.prepare → store.assign (O4 closure at `at`) → build(at)
│   ├─ _scratch(s, at) → open_view(Fb, s, at)                                     [validation 2]
│   └─ journal._version(s, pred, at) → checkpoint_fold(Fb', s, at)                [validation 3]
└─ journal.finish → store.append(check=…) → check(at) → _version(s, pred, at)    [validation 4: K9, in the write]
```

### Maintenance step (5 signature computations)

```text
JC.maintain → create
├─ j.read(s, clock): _read_preds [validation 1], served_trace [validation 2]
└─ checkpoint_at(facts, cps, s, c=sv.r)
    ├─ base = checkpoint_fold(facts, s, c)                                        [validation 3]
    ├─ sig = state_signature(new fold)                                            [build]
    └─ cps.verify(new cp): validate + load + state_signature                       [staged verification]
```

### Is the repetition redundant? Checked condition by condition

| Condition | Gateway read | Typed command (gate / build / version) | Maintenance (read / base) |
|---|---|---|---|
| Same subject | Yes | Yes | Yes |
| Same checkpoint | Yes in a quiet store. Selection re-runs on every use, so a concurrently published newer checkpoint would be selected and fully validated | Same | Same |
| Same lookup position | `_read_preds`, served trace and view all use r | Gate at `clock`, build and version at `at ≥ clock` | Read at r, base at c = r |
| Same relevant facts | F1 → F2 differ only by **closure marks**. A late publication inside c is caught by the re-run `validate` (`policy_position`). New appends fall in the suffix, which each use advances from its **own** facts | `Fa` → `Fb`: `assign` closes the partition; a write in between is suffix. A transient retry re-seals at a new `at`, and the witness check (§2) catches a re-sealed fact | Same as read |
| What the repetition actually re-derives | Decoding the same payload bytes and hashing the same canonical state | Same | Same |

**Conclusion [PROVEN].** The signature check depends on three things only: the checkpoint record, the payload bytes, and (compact encoding) the referenced sealed facts. When all three are unchanged, repeating `load` + `state_signature` in the same operation is redundant. Everything else (`validate`, candidate selection, suffix advance) stays per use. **Stop condition 2 does not apply.** No closure boundary needs a second *signature* validation for any semantic reason. Closure adds no facts, and every fact-dependent check is re-run against the facts each use sees.

## 2. The operation-scoped validation model

There is one new class, `journal_compaction.OperationValidation`, plus an optional `op=None` parameter on the existing call chain. With `op=None`, every path is byte-for-byte the previous code.

```text
operation (Gateway read | Gateway command | one maintain call)
   │  op = OperationValidation(subject)      ← a local, opened and closed by the operation itself
   │
   ├── use 1: candidates(subject, r) → validate(cp, facts) → load → state_signature   (FULL)  → remember
   ├── use 2: candidates(subject, r') → validate(cp, facts') → witness? → reuse a COPY  (no load, no signature)
   └── use k: …                                     witness changed → FULL again
   │
   └─ close: the object refuses every later use
```

**Each requirement of the brief, and where it holds:**

| # | Requirement | How it holds |
|---|---|---|
| 1 | Scoped to the operation | Created with `with OperationValidation(subject) as op:` inside `Gateway._read`, `Gateway._admit` and `JC.maintain`. Never an attribute of Gateway, TimedJournal or CheckpointStore. The public Gateway methods take no `op` |
| 2 | Never persisted as truth | In memory only. It holds a decoded fold and object references, never a fact or checkpoint |
| 3 | Never shared across operations | Every operation creates its own. After close, any use raises `operation_validation_closed` |
| 4 | Immutable after validation | The pristine decoded fold is deep-copied when remembered and **never handed out**. Every use gets a fresh deep copy, which it then advances |
| 5 | Invalidated when the position matters | Selection by r and `validate` (prefix, tail, suffix after c, policy position) run on **every** use, against that use's facts. Each use advances from c through its own suffix |
| 6 | Bypasses no check | Partition, contract, encoding, payload present, digest, prefix, tail, suffix and policy position all re-run on every use. Erasure is still handled in the advance: an erasure in the suffix gives an erased fold, and the view is refused |
| 7 | Signature computed exactly as before | `state_signature` is untouched, and the first use in each operation calls it |
| 8 | No trust in a previous operation | Enforced by #1 and #3, and proven by counts (§7) |

**The memo key and the witness:**
- **Key:** the full `Checkpoint` value, which covers partition, `covered_at`, count, tail, policy position, contract, signature, digest, ref and encoding. Any change to the index record is a miss.
- **Witness:** a hit also requires every vault entry that `load` read to be the **same object** (`is`) in the current facts. That means the payload bytes and, for compact encoding, every referenced claim, retraction, commitment event and episode generation. Sealed records are frozen dataclasses, so an unchanged object means unchanged content.
- **Exactness argument [PROVEN].** `load` + `state_signature` is a deterministic function of (the checkpoint record, the payload object, the referenced objects). On a hit all three are identical, so the skipped result would have been identical. On any difference, the full path runs again with the existing rejection reasons and `discard` behaviour. Reuse is therefore **exact, not probabilistic**, and it does not change the integrity guarantee. That is why `cto-owner-decision-request-v1.md` is **not** reopened.

## 3. Gateway changes

- **`_read`:** one `OperationValidation` covers `journal.read(op=op)`, which passes it to `_read_preds` and `served_trace`, and `_view(op=op)`.
- **Closure semantics are unchanged:**
  - closing the partition happens before any read;
  - the policy-log closure of the evaluated predicates happens before the served trace;
  - the served trace is computed from the post-closure facts F2;
  - the view is built from F3.
- Each use re-runs `validate` and advances from its own snapshot, so the post-closure refetch is honoured, not optimised away.
- **History, current state and context** all come from the one view opened in `_read`.

## 4. Typed command changes and K9 preservation

- `_admit` is now `with OperationValidation(subject) as op: return self._admit_op(op, …)`. The body of the former `_admit` is unchanged apart from passing `op` to:
  - the gate's `_scratch`;
  - the build's `_scratch`;
  - the build's `journal._version`.
- These three uses share one full validation, including across transient retries within the command.
- **K9 [PROVEN] is never reused.** `finish` → `check` → `_version(s, pred, at_)` is called **without** `op`. It runs a fresh full validation against `store.facts()` at the serialized write point: one of the command's two signature computations happens **inside** `store.append`, which is measured.
- **This overrides an earlier note.** `incremental-checkpoint-signature-v1.md` §4 said that reusing the validated base and advancing it would be enough for K9. This brief requires independent authority, so K9 keeps its own validation.
- **Proven outcomes**, identical OLD vs NEW on both stores and both encodings:

  | Case | Outcome |
  |---|---|
  | Current command | APPENDED |
  | Stale expected version | STATE_CONFLICT |
  | Write after read | STATE_CONFLICT |
  | Write landing in flight, after the operation's validation | STATE_CONFLICT, decided in the write |
  | Breaking policy publication | STALE_POLICY_STAMP |
  | Publication landing in flight | STALE_POLICY_STAMP when storage places it at or before the write's time; otherwise APPENDED |

- **Journal-level outcomes (current, stale, in flight)** are identical OLD vs NEW through:
  - a scheduled version advance (`valid_from`);
  - a retraction, a sync, a commitment event and an episode generation;
  - a breaking publication;
  - erasure, with and without key destruction.

## 5. Maintenance changes

`maintain` opens one `OperationValidation` and passes it through `create`. The closing read (`_read_preds`, served trace) and the incremental base in `checkpoint_at` share one full validation.

```text
validate old checkpoint once (in the closing read)
   → reuse it as the incremental base (validate re-run, witness checked)
   → build the new fold, sign it (state_signature, unchanged)
   → stage
   → cps.verify(new): an INDEPENDENT full validation from storage (never consults op)
   → publish → retire old
```

Measured: 5 → 3, made up of base 1, build signature 1 and staged verification 1.
- The existing maintenance tests still prove that a damaged staged payload (`verify:integrity`) or a mis-serializing builder (`verify:state_signature`) is never published.
- In the equivalence runs, the published checkpoints match OLD vs NEW in full: signature, digest, coverage and policy position.

## 6. Exact equivalence (OLD = reuse disabled, NEW = reuse)

Every equivalence test runs each scenario twice: once with `OperationValidation.reuse` forced to miss (every use validates independently, as before), and once normally. Checkpoint refs are made deterministic so the two runs can be compared exactly. A test passes only if **all results and all side effects** are equal.

**Results compared:**
- read, history and context results, and the served positions and tokens;
- write results, including OCC actual versions;
- maintenance results (the checkpoint records);
- served traces, versions, read predicates and views.

**Side effects compared:**
- the checkpoint index;
- the unusable set;
- the rejection list and its order;
- the vault keys;
- every partition entry.

**Scenarios:**

| Scenario | Coverage |
|---|---|
| Random Gateway drivers | 2 stores × 2 encodings × 3 seeds |
| Journal scenario | 2 stores × 2 encodings × with and without key destruction |
| Random v1.1 histories | 2 × 2 × 3: claims, typed commands, retractions, lifecycle, syncs, breaking publications, future validity, a merge |
| Six command cases | 2 × 2 × 6 |
| In-operation changes | Listed below |

In the random-history runs, one operation looks the partition up at several positions, **in decreasing as well as increasing order**, and below c.

**In-operation changes.** The operation validates at r1, then something changes before r2 within the same operation. For each change, the result equals an independent validation:

| Change inside the operation | Result at r2 (OLD = NEW) |
|---|---|
| Key destroyed | Rejected: `unreadable` |
| Payload bytes damaged | Rejected: `integrity` |
| Index signature forged (same ref, same payload) | Rejected: `state_signature` |
| Encoding changed | Rejected: `encoding` |
| Publication lands inside c | Rejected: `policy_log_changed` |
| Referenced sealed fact replaced (compact encoding) | Rejected: `state_signature` |
| New suffix entry | Same checkpoint, advanced through the longer suffix, no new signature |
| Newer checkpoint published | The new one is selected and fully validated |

## 7. No cross-operation trust [PROVEN]

| Claim | Proof |
|---|---|
| Operation A cannot authorize operation B | Each Gateway operation's first use recomputes the signature (exactly 1 per read, repeated). Once A has validated, corruption followed by operation B is rejected for each of `integrity`, `unreadable`, `state_signature` and `policy_log_changed`, and B is served from the journal |
| A leaked result cannot be injected | A closed `OperationValidation` raises on `checkpoint_fold` and on `journal.read` |
| One subject cannot reuse another's | A different subject raises `operation_validation_subject`. A swapped index entry inside the operation is still rejected as `wrong_partition` |
| One position cannot authorize another | Selection and `validate` run per use. A lookup below c gets no checkpoint even after a hit at a higher r. A lower r after a higher r equals a fresh fold |
| One encoding cannot validate another | A full and a compact checkpoint of the same state in one operation are each fully validated (2 signatures). They share one canonical signature and equal a fresh fold |
| A destroyed key cannot be hidden | Re-run `validate` reports `unreadable`, in operation (§6) and across operations |

## 8. Mutation results: 16/16 caught

Runner: `scratchpad/mutate_ov.py` over the new suite plus the maintenance, consumers, fast-path, pruning and compaction suites, run with `-x`. The right column names the **first failing test** the run printed; other tests may also catch the mutant.

**Removing reuse altogether** is exactly the OLD mode used in every equivalence test. The count test catches it, because the counts fall back to 3/3/4/5.

| Protection removed | First failing test (`-x`) |
|---|---|
| `validate` re-run on every reuse | in-operation change tests |
| First full validation: the signature check | counts |
| Witness: payload and references are the same objects | re-sealed reference test |
| Witness covers referenced sealed facts (compact) | re-sealed reference test |
| Memo keyed on the full checkpoint value, not its ref | forged index signature test |
| Position binding (selection by r on every use) | in-operation tests |
| Subject binding | subject test |
| A closed operation authorizes nothing | leaked-operation test |
| Pristine fold never handed out | random-history positions test |
| Pristine fold copied when remembered | random-history positions test |
| Fallback: full path re-run after a failed reuse check | counts |
| Fresh operation per Gateway read | counts |
| Fresh operation per Gateway command | Gateway equivalence |
| K9 in-write check present | journal OCC scenario |
| K9 never uses the operation's validation | counts |
| Staged checkpoint verified independently | counts |

**[INFERENCE] on the last three rows.** Because reuse is exact (§2), the mutants "K9 uses the operation's validation", "one memo shared across operations" and "`verify` uses the memo" would still give correct outcomes. Outcome tests cannot catch them. They are caught by **instrumentation**: per-operation counts, and a count of signatures computed inside the serialized write. The brief requires those properties structurally, and the tests pin them structurally.

## 9. Measured counts (instrumented, both stores, both encodings)

`test_measured_validation_counts_drop_to_one_per_operation_and_results_are_identical` runs the same operations OLD, then NEW:

| Operation | Signatures OLD → NEW | Payload decodes OLD → NEW | Vault reads of referenced facts (compact) |
|---|---|---|---|
| Gateway read | 3 → **1** | 3 → 1 | 6 → 2 |
| History | 3 → **1** | 3 → 1 | 6 → 2 |
| Context compile | 3 → **1** | 3 → 1 | 6 → 2 |
| Typed command | 4 → **2** (one inside the write) | 4 → 2 | 8 → 4 |
| Maintenance | 5 → **3** | 4 → 2 | 9 → 5 |

The vault-read counts are from the reference scenario (scratch `op_count.py`); the test asserts that they drop. A full payload reads no referenced fact.

**What reuse adds:** two in-memory deep copies of the fold (one to remember, one per reuse) and one `validate` per use. That includes the payload digest, which is O(payload bytes) and not a canonical-signature computation.

**No latency improvement is claimed** from these reference measurements.

## 10. The canonical signature is unchanged [PROVEN]

- `state_signature` was not edited.
- Every checkpoint of a maintenance chain run with reuse (both encodings, both stores) equals `SHA-256(canonical_input(fresh full build))`. That covers the first, fresh checkpoint and the incremental ones built from an operation-validated base.
- Every `both` comparison also compares every published checkpoint record, signature included, OLD against NEW.
- The incremental-signature evidence suite (49) still passes unchanged.
- No Merkle signature, rolling hash, alternate identity or trust change was introduced.

## 11. Regression

See §13.

## 12. Remaining gaps

| Gap | Label |
|---|---|
| One full validation per operation is still O(total claim content). Lower than that needs the trust-model decision | **[OWNER]**, already in `cto-owner-decision-request-v1.md`. Not reopened |
| A command still does 2 and maintenance 3. K9 and staged verification are independent by design | By design |
| Compact decode still reads one vault entry per referenced fact (now once per operation) | Unchanged |
| Each reuse costs a deep copy of the fold (in memory, no I/O) | Engineering; acceptable in the prototype |
| The witness relies on sealed facts being immutable objects in the reference stores. A real store must give the equivalent: the same version or etag of each vault entry within the operation | [INFERENCE] for a production adapter; no adapter built |

## 13. Regression results

| Suite | Result |
|---|---|
| Journal conformance | 144 |
| Storage boundary | 86 |
| X-1 commit time | 64 |
| Gateway G0 | **38** (unchanged) |
| Gateway adversarial | **109** (unchanged) |
| Episode/commitment | 82 |
| Compaction | 93 |
| Checkpoint consumers | 65 |
| Fast path | 51 |
| Maintenance | 82 |
| Pruning / reference encoding | 58 |
| Incremental signature evidence | 49 |
| Per-operation validation (new) | 120 |
| **Full suite** | **1802 passed** (1682 + 120) |

No existing test was edited, weakened, deleted, skipped or disabled.

**Line endings.** My patch scripts first rewrote the four modules as CRLF. They were restored to LF, their original endings (earlier mutation runners match LF anchors in them), and the full suite was re-run: 1802 passed. Some anchors in earlier mutation runners (`mutate_cm`, `mutate_fp`, `mutate_pr`) no longer match lines that this workstream or earlier ones changed. Those runs are historical evidence. The protections they covered on the changed lines (reader signature, K9 check, base validation) are re-covered by this workstream's runner.

**Prototype modules modified:**
- `journal_compaction`: `OperationValidation`; `op` on `checkpoint_fold`, `checkpoint_at`, `create` and `maintain`;
- `commit_time`: `op` passed through `read`, `end_read`, `_read_preds`, `_serve`, `served_trace`, `_checkpoint` and `_version`. The K9 `check` passes none;
- `projection_view`: `op` on `open_view`;
- `gateway`: an operation for each of `_read` and `_admit`.

**No owner packet was created.** This is engineering-only, and reuse does not change the integrity guarantee (§2).

**PER-OPERATION CHECKPOINT VALIDATION V1 CONFORMANT.**
