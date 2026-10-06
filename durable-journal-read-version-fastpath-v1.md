# Durable Journal Read/Version Fast Path v1.2 (technology-neutral)

**Date:** 2026-10-05.

**Classification:** TARGET ARCHITECTURE. Prototype and test only.

**An engineering optimisation of journal internals.** No memory semantics change: K1–K10, S1–S5, O1–O4, SPI and R-READ are all unchanged.

**Builds on:** journal v1.1 + A1, the compaction contract v1, checkpoint consumer interface v1.

**Labels:** [PROVEN], [DECISION], [CONTRACT_GAP], [INFERENCE].

**Executable form:**
- `memory_core/commit_time/` (`TimedJournal`: an optional `checkpoints`; `_checkpoint`, `served_trace`, and a checkpoint-aware `_version` and `_read_preds`);
- `memory_core/journal_compaction/` (`Fold.predicates`, the entry-predicate metadata; `checkpoint_fold(advance=…)`);
- `memory_core/gateway/` (`checkpoints` is now a property: one store, held by the journal);
- `tests/test_journal_read_version_fastpath.py`.

---

## 1. Purpose

Remove the journal-side full replay that remained after checkpoint consumer v1:
- every current read replayed the full history to compute the served trace;
- every typed command replayed it at least twice for K9.

The Journal stays the sole authority. Checkpoints stay derived and validated.

## 2. The existing replay dependency (Phase 0, from source)

| Journal step | What it took from the full replay | Source |
|---|---|---|
| **Served position r** (`begin_read`) | **Nothing.** r = max(clock, causal token), then a partition closure write or time draw | `commit_time.begin_read` |
| **Policy-log closure** (`end_read`) | **No replay, but an O(history) scan:** the predicates of **every** partition entry at or before r (`_read_preds`), whose logs must be closed through r | `_read_preds` |
| **Served trace** (`_serve`) | `reconstruct(facts, s, r).trace` (`{}` if erased) | `_serve` |
| **OCC base / K9 in-write check / Gateway `actual_version`** (`_version`) | `len(reconstruct(facts, s, at).trace[predicate])`, which covers policy-driven, scheduled-boundary, retraction and lifecycle version changes | `_version`; `finish.check` |
| Duplicate check (`prepare`) | A scan for `idem` (idempotency index, not replay; out of scope) | `prepare` |

**What a validated checkpoint already holds:** the exact rebuild fold, including the **trace**, which is everything `_serve` and `_version` read (compaction contract Part 0) [PROVEN].

**The hidden dependency:** the read-predicate set is **entry metadata** (`Entry.predicate`), including entries whose payload is unreadable and syncs whose entry predicate differs from the payload's. The fold did not carry it. Deriving it from claims would not be exact.

**Phase 0 result: FEASIBLE WITH FALLBACK.**
- The fold now also carries `predicates`: the metadata of every covered entry, derivable from the facts and covered by the state signature.
- Any unusable checkpoint keeps the v1.1 replay.

## 3. Internal interface

| Concern | v1.2 implementation | Fallback |
|---|---|---|
| Closure | **Unchanged**: `begin_read` closes the partition; `end_read` closes the evaluated predicates' logs, then refetches the facts | — |
| Served position | **Unchanged** (from closure) | — |
| `_read_preds(facts, s, r)` | Validated fold at c (not advanced): `fold.predicates` ∪ the suffix entries' predicates (metadata only, no evaluation) | Full scan |
| `served_trace(facts, s, r)` | Validated fold advanced through (c, r]: `fold.trace` (`{}` if erased) | `reconstruct` |
| `_version(s, predicate, at)` | Validated fold advanced through (c, at]: `len(trace[predicate])` | `reconstruct` |
| `_checkpoint(facts, s, r, advance)` | The single entry point: `journal_compaction.checkpoint_fold` | None |

## 4. Closure and trace separation

1. Closure is performed exactly where v1.1 requires it, and before anything is served.
2. r comes from closure alone.
3. The trace is a separate computation over the facts after closure.

Consequences:
- An append racing a read is placed after r and is not in the trace [PROVEN].
- Every served trace equals the final full replay at the same r (`served_prefixes_are_immutable`) [PROVEN].
- A predicate present only in the checkpoint prefix, or only in the suffix, still gets its policy log closed through r. A later lagging-clock publication lands after r [PROVEN, both cases].

## 5. Checkpoint-aware version lookup

```text
validated checkpoint at c  +  durable suffix (c, at]  =  exact version at at      [PROVEN equal to v1.1]
```

**Validation is exactly the consumers'** (`checkpoint_fold`):
- partition;
- contract version;
- payload readable and its digest;
- prefix length and tail anchor;
- the next entry after c;
- policy-log position;
- state signature;
- c ≤ at.

Any failure → full replay, and the checkpoint is marked unusable.

## 6. K9 authority

- **The in-write check still runs inside the serialized append** (`finish.check`) against the facts at that moment.
- Its version computation is now checkpoint + suffix, where the suffix **contains any write that landed in flight**.
- An in-flight write is still caught as STATE_CONFLICT on both stores [PROVEN with replay disabled].
- Removing the check is caught (§11).
- The checkpoint never decides a write. It only shortens the computation of a value the journal checks.

## 7. Concurrency

- Nothing new is cached in process memory; every lookup is recomputed from the facts plus a validated checkpoint.
- Appends after closure land after r.
- In-flight appends are in the suffix at write time.
- The checkpoint store is derived state, held by the journal; the Gateway's `checkpoints` points to the same object.

## 8. Erasure

| Situation | Behaviour [PROVEN] |
|---|---|
| Erasure entry in the suffix | Trace `{}`, version 0, with no replay |
| Erasure covered by the checkpoint | An erased fold |
| Key destroyed | The checkpoint is unreadable → full replay |

These match v1.1 exactly.

## 9. Fallback conditions

The fast path is not used, and v1.1 replay answers, whenever any of these holds:
- no checkpoint store;
- no checkpoint at or before the position;
- any validation failure (§5);
- an unreadable payload.

Six corruption kinds were tested. Each falls back, with the trace and the version unchanged [PROVEN].

## 10. Invariants and test plan

`tests/test_journal_read_version_fastpath.py`: **51**, on both stores. `reconstruct` is patched to raise in every fast-path test.

| Area | Tests |
|---|---|
| Equivalence: 6 random histories × 2 stores × 4 checkpoint positions × reads with empty, one-entry, mid and long suffixes. Served trace, every predicate's version, and read predicates | 12 |
| Real reads plus a typed command with no replay, including a scheduled boundary; then the SPI and stamp invariants | 2 |
| OCC: current admitted / stale → STATE_CONFLICT; in-flight write → STATE_CONFLICT | 4 |
| Breaking and non-breaking publication after c | 4 |
| Retraction, sync, commitment event and episode summary in the suffix | 2 |
| Erasure in the suffix (no replay); destroyed key → fallback | 4 |
| Six invalid-checkpoint kinds → fallback, results unchanged | 12 |
| Checkpoint newer than the lookup position is never used | 2 |
| Closure precedes serving; read-predicate closure for prefix-only and suffix-only predicates | 6 |
| Only the suffix of the partition is read | 2 |
| Gateway end to end (read, typed command, context) with no replay anywhere | 1 |

## 11. Mutation results

15 protections removed one at a time; the fast-path, compaction and consumer suites run each time; the code restored byte-identical. **15/15 caught.**

| Protection removed | Result |
|---|---|
| Checkpoint validation | caught |
| Partition validation | caught |
| Policy-position validation | caught |
| Tail validation | caught |
| State-signature validation | caught |
| Suffix advancement | caught |
| Version baseline (the checkpoint's fold) | caught |
| Erasure in the suffix | caught |
| Fallback | caught |
| Checkpoint / read-position binding | caught |
| Read predicates: suffix entries | caught |
| Read predicates: covered prefix | caught |
| Served trace from the advanced fold | caught |
| **K9 final in-write version check** | caught |
| Version lookup position | caught |

## 12. Regression

See §15.

## 13. Cost characterisation (reference implementation; relative work only)

Counted:
- partition entries read by the journal computation;
- slot-signature evaluations (`_signature`, the projection's unit of work).

The setup is one subject with N claims and a checkpoint k entries before the end. Measured for the served trace; the version lookup runs the same fold, so it costs the same.

| history N | suffix k | full: entries / signatures | fast: entries / signatures |
|---|---|---|---|
| 25 | 0 | 50 / 50 | 2 / 0 |
| 25 | 1 | 50 / 50 | 5 / 2 |
| 25 | 10 | 50 / 50 | 23 / 20 |
| 100 | 0 | 200 / 200 | 2 / 0 |
| 100 | 1 | 200 / 200 | 5 / 2 |
| 100 | 10 | 200 / 200 | 23 / 20 |
| 400 | 0 | 800 / 800 | 2 / 0 |
| 400 | 1 | 800 / 800 | 5 / 2 |
| 400 | 10 | 800 / 800 | 23 / 20 |

(Explicit store. The full replay reads the partition twice: once for the erasure check, once for the evaluation order.)

**Reading the table:**
- **Full replay:** entries read and signature evaluations grow with N.
- **Fast path:** entries read are the tail anchor plus the suffix, and signature evaluations grow with the suffix and the live slots. Neither grows with N.
- **Not counted:**
  - checkpoint payload unpickling and digest verification, which are O(checkpoint size). That size still grows with the claim map and trace (the compaction size gap);
  - the reference store's `facts()` snapshot copy, a reference-store artefact. Technology-neutral storage needs only positional partition reads.

## 14. Remaining gaps

| Gap | Label |
|---|---|
| Checkpoint size (claim map, trace, retractions, events, generations); the per-use digest and unpickle cost is O(size) | [CONTRACT_GAP] engineering (pruning; deliberately not started) |
| Duplicate check scans the partition (`prepare`, Gateway `_outcome_of`) | Storage requirement: an `idem` index |
| Validation reads the policy-log position (publications ≤ c) | [INFERENCE] per-predicate log positions would make this O(predicates) |
| Checkpoint cadence | An operational parameter; unset |
| Write-path stamp check (`in_force` over publications) | Unchanged, global small log |

## 15. Regression

| Suite | Result |
|---|---|
| Durable journal conformance | 144 |
| Storage boundary | 86 |
| X-1 commit time | 64 |
| Gateway G0 | **38** (unchanged) |
| Gateway adversarial | **109** (unchanged) |
| Episode/commitment | 82 |
| Compaction | 93 |
| Checkpoint consumers | 65 |
| Fast path (new) | 51 |
| **Full suite** | **1493 passed** (1442 + 51). No existing test edited or weakened |

No owner boundary was reached; no CTO/owner packet was created.

**JOURNAL READ/VERSION FAST PATH V1 CONFORMANT.**
