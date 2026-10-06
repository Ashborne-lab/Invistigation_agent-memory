# Durable Journal Compaction v1: Implementation Report

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Prototype and test only.

**Contract:** `durable-journal-compaction-contract-v1.md`.

**FINAL VERDICT: JOURNAL COMPACTION V1 CONFORMANT.** Two scope limits apply (§6).

---

## 1. What was built

| File | Change |
|---|---|
| `memory-prototype/memory_core/journal_compaction/__init__.py` | **New.** The rebuild fold (a mirror of `reconstruct` → `project_subject` → `slot_versions`, rebuild path), checkpoints, validation, `rebuild` (checkpoint + suffix, or full replay), `CheckpointStore` (derived index, compaction = retiring superseded checkpoints), `full_replay` (the reference) |
| `memory-prototype/tests/test_journal_compaction.py` | **New.** 93 tests |
| `investigation/durable-journal-compaction-contract-v1.md` | **New.** The contract, including the Phase 0–3 analysis |

**Not modified:** Durable Journal v1.1 and A1, K1–K10, StorageBoundary and both reference stores, `TimedJournal`, the Gateway, the Claim Gate, commit, typed retrieval, the Context Compiler, the Evidence Boundary, the identity layer, `episode_commitment`, and **every existing test**.

## 2. Phase 0 result

Feasible with no K-rule change, no new truth source and no cross-partition step. The rebuild is a left fold whose state is finite and explicit (contract Part 0 table).

**Two hazards were found and handled fail-safe. Neither needed a rule change.**
- **Late publication (explicit store).** A publication for a predicate this partition never closed can land at T ≤ c.
  - The checkpoint records the policy-log position, and validation falls back to full replay.
  - A probe showed the **already-served** result unchanged in that case. That was **not observed in the probed case only** [INFERENCE].
  - **Open v1.1 question (not a compaction issue):** the rebuild path evaluates every slot at every point, so an unrelated late publication at T ≤ r adds an evaluation point inside the served past. Whether that can ever change a served version has not been established. Compaction is unaffected, because the policy-position check falls back to full replay.
- **Read-time policy content.** A claim whose predicate has no publication in force is evaluated under the policy visible at read time.
  - Checkpoint creation refuses such folds (`UNSUPPORTED`).

## 3. Tests: 93, both reference stores

| Area | Tests |
|---|---|
| **Equivalence property:** 8 random histories × 2 stores. Checkpoints at the empty partition and at every entry, publication and boundary instant; reads at c, c+ε, a midpoint, the last instant and beyond. Two subjects each, with a merge | 16 |
| Only the suffix is read (guarded partition) | 2 |
| Empty partition and exactly at an entry; **two publications of one predicate at exactly the checkpoint instant**; before and exactly at a future validity boundary; before and after a breaking publication; before and after a retraction including LA-9 on a claim committed after c; freshness (max sync, with a lower sync after c) and claims version; lifecycle and erasure state | 16 |
| **Crash/recovery:** crash before seal, after seal (orphan), and torn; crash before the suffix is durable then retry; a durable suffix append then restart and duplicate; corrupted bytes; a forged payload with a matching digest; an incompatible contract version; a stale checkpoint; a checkpoint from another history (shorter, and of equal length) | 18 |
| **Concurrency:** an append during creation; multiple writers with independent per-subject checkpoints; a read in flight across creation; a typed OCC command right after a checkpoint; a publication after the checkpoint; a late publication on an unclosed predicate; an entry landing at or before c after creation; a checkpoint newer than the read | 16 |
| **Idempotency:** Gateway duplicate before and after a checkpoint plus restart (same outcome and time); COMMAND_ID_REUSED; the same id on another subject; a journal duplicate after a checkpoint | 4 |
| **New record types:** never evaluation points (positive assertion); commitment projection through a checkpoint, including an earlier business time after c and expiry; newest episode generation, duplicate generation, derived status | 6 |
| **Erasure:** a checkpoint before erasure (unreadable, nothing recoverable); after erasure (no content); a destroyed key without an erasure entry; no checkpoint after key destruction | 8 |
| **Not a truth source:** checkpoints are never entries; `reconstruct` is identical with and without them; removing them all changes nothing; compaction retires superseded checkpoints and deletes no fact | 4 |
| **Determinism:** same facts + checkpoint give the same result; two creations at the same c give the same signature; read-time-policy folds refused | 3 |

**Both reference stores pass every store-dependent test.**

A 30-seed scratch run of the same property: **110,972 comparisons, 0 mismatches**.

## 4. Mutation results

29 invariants removed one at a time; the compaction suite run each time; the code restored byte-identical. **29 of 29 caught.**

| Invariant removed | Caught by |
|---|---|
| Checkpoint position advanced | equivalence property |
| Suffix boundary: entries from the covered count | equivalence property |
| Suffix boundary: publications strictly after c (`>` → `>=`) | two publications at exactly c |
| State signature check | forged payload |
| Payload integrity check | torn crash |
| Contract version check | incompatible version |
| Prefix anchor check | another history of equal length |
| Prefix length check | another, shorter history |
| Concurrent-append protection (next entry after c) | entry landing at or before c |
| Policy-log position check | late publication |
| Refuse read-time-policy folds | read-time policy fold |
| Unusable marking on rejection | torn crash |
| Only checkpoints at or before r | checkpoint newer than the read |
| Crypto-shred coupling (subject key) | checkpoint before erasure |
| Compaction deletes no fact | compaction test |
| Policy history: version in force carried | equivalence property |
| Policy history: historical version used | equivalence property |
| Retractions carried (LA-9) | retraction test |
| Pending validity boundaries carried | equivalence property |
| Boundaries drained up to the position | equivalence property |
| Max sync per predicate | lower sync after c |
| `claims_version` carried | equivalence property |
| Version trace carried | equivalence property |
| Versions carried | equivalence property |
| Commitment events carried | commitment projection |
| Newest episode generation | episode test |
| Erasure in the suffix | lifecycle/erasure test |
| Lifecycle only for live claims | no checkpoint after key destruction |
| Unreadable payloads contribute nothing | no checkpoint after key destruction |

**Survivors from the first run, and how each was closed:**

| Mutant | Fix |
|---|---|
| Prefix anchor | New equal-length other-history case |
| Only-at-or-before-r | New newer-than-read test |
| Max sync | New lower-sync test |
| Lifecycle / unreadable payloads | New key-destruction test. Also changed: `checkpoint_at` now returns `REJECTED key_destroyed` instead of raising |
| Publication boundary (`>` → `>=`) | First reported as an equivalent mutant. **That was wrong.** With two versions of one predicate published at exactly c (allowed at storage level; the journal's own `publish` never does it), re-applying them diverges. A probe confirmed it, and a test now catches it |

## 5. Regression

| Suite | Result |
|---|---|
| Durable journal conformance | 144 passed |
| Storage boundary | 86 passed |
| X-1 commit time | 64 passed |
| Gateway G0 | **38 passed**, unchanged |
| Gateway adversarial | **109 passed**, unchanged |
| Episode/commitment (A1) | 82 passed |
| Journal compaction (new) | **93 passed** |
| **Full prototype suite** | **1377 passed** (1284 + 93), 0 xfail. No existing test edited |

## 6. Scope limits (part of the verdict)

1. **No fact is deleted.**
   - v1 bounds **replay cost**, not **storage growth**.
   - Physical truncation needs [OWNER] Legal/Product (a history-retention boundary) and [OWNER] contract owner (a base snapshot as a fact).
   - Without both, truncation would create a second authority and change served history below the cut.
2. **The consumers are not wired to checkpoints.**
   - The Gateway and retrieval rebuild from the journal view, which a checkpoint cannot produce.
   - Acceleration exists at the `reconstruct` boundary. The unchanged consumers keep doing full replay, with identical results.
   - [CONTRACT_GAP]: a consumer interface that accepts projection state.

## 7. Remaining items

| Item | Label |
|---|---|
| History-retention boundary | [OWNER] Legal / Product |
| Base snapshot as a fact | [OWNER] contract owner |
| Consumer interface for projection state | [CONTRACT_GAP] |
| Bounded checkpoint size (trace held separately) | [CONTRACT_GAP] |
| Checkpoint cadence | Operational parameter, unset |
| Creation without a closure write (at an already-closed position) | [INFERENCE] option, not built |

E-5 and C-5 stay parked and were not touched.

## 8. Verdict

**JOURNAL COMPACTION V1 CONFORMANT.** All the brief's criteria are met:
- checkpoint + suffix ≡ full replay;
- both reference stores pass;
- the new record types keep their semantics;
- the mutation run establishes the necessary invariants (29/29);
- the 1284 baseline is green;
- there is no new truth source.
