# Checkpoint Maintenance v1 (technology-neutral)

**Date:** 2026-10-05.

**Classification:** TARGET ARCHITECTURE. Prototype and test only.

**Scope:** derived-state maintenance only. The Durable Journal stays the sole authority, no journal fact is ever modified, and K1–K10, S1–S5, O1–O4, SPI, R-READ, the gate, Current State, OCC, erasure and causal semantics are unchanged.

**Builds on:** compaction contract v1, checkpoint consumer interface v1, journal read/version fast path v1.2.

**Labels:** [PROVEN], [DECISION], [CONTRACT_GAP], [INFERENCE].

**Executable form:**
- `memory_core/journal_compaction/`:
  - incremental `checkpoint_at` / `create`;
  - `CheckpointStore.stage` / `verify` / `publish` / `drop_staged` / `next_id`;
  - `uncovered`, `maintain`;
  - `Fold.predicates` as a sorted tuple;
- `memory_core/commit_time/` (one line: reads `set(fold.predicates)`);
- `tests/test_checkpoint_maintenance.py`.

---

## 1. The checkpoint lifecycle before v1 (Phase 0, from source)

| Question | Answer |
|---|---|
| **A. Creation** | `checkpoint_at(facts, store, subject, c)` called `build_fold`, a **full-history** fold. It then refused unsafe folds, pickled the fold, computed the canonical state signature and the payload digest, and called `add`, which sealed the payload under the subject key and then appended it to the index. `create` takes c from a closing current read |
| **B. Identity** | A `Checkpoint` record: partition, `covered_at` (c), covered count, tail anchor, policy-log position, contract, state signature, payload digest, `created_at`, ref |
| **C. Coexistence** | A per-partition index list, holding any number of checkpoints |
| **D. Selection** | `candidates(subject, r)`: c ≤ r, not unusable, newest first. `checkpoint_fold` validates them in that order, marks each failure unusable, and uses the first valid one |
| **E. Atomic publication?** | Partly. A checkpoint became selectable at the index append. A seal without an index append was an invisible orphan, and a torn payload was caught at read time by the digest. **But nothing verified the payload before publishing it,** and the ref `(subject, c, signature)` could collide when an identical checkpoint was re-created, so retiring the old one would delete the new payload |
| **F. Enough for incremental creation?** | Yes. `checkpoint_fold` already returns a validated fold advanced through the suffix. The only gap was canonical serialization: `Fold.predicates` was a set. It is now a sorted tuple |

## 2. Incremental creation

```text
newest VALID checkpoint at c0 ≤ c  (every reader validation: partition, contract, readability, digest, prefix
                                    length, tail anchor, next entry after c0, policy-log position, state signature)
+ durable facts in (c0, c]
= the checkpoint a fresh full build at c would produce                              [PROVEN]
```

**The algorithm:**
- `base = checkpoint_fold(facts, subject, c, store)`. This decodes a **fresh object** from the sealed payload, so the published checkpoint is never mutated [PROVEN: its bytes are unchanged and it stays valid].
- If there is a base, it is advanced through the suffix only. If there is none, or validation fails, the code does a full build.
- The same unsafe-fold refusal applies in both cases.
- **The tail, covered count, policy position and signature are recomputed from the result**, not carried over.

**Equality.** On random histories × both stores × c0 at the beginning, middle and near the tail × an empty, one-entry, medium or long suffix, all of these are equal:
- the decoded fold, covering every field: claims, retractions, pending boundaries, versions, last signatures, version in force, trace, sync, `claims_version`, commitment events, generations, predicates, erased flag and position;
- the canonical state signature;
- the identifying metadata: partition, c, covered count, tail, policy position, contract.

The same holds for:
- a chain of 8 maintenance steps with retractions, syncs and scheduled changes;
- breaking and non-breaking publications, commitment events and episode generations.

**What is not byte-identical: the payload bytes and their digest.** A 480-case probe found equal folds and equal signatures in every case, but different pickle bytes in 354. The serializer lays out object sharing differently for an object decoded from a payload than for one built from vault records. This carries no semantics. **Identity is the canonical state signature, and the digest is integrity only**, exactly as the compaction contract defines them [DECISION, unchanged].

## 3. The publication state machine

```text
BUILD → SERIALIZE → (digest, signature) → STAGE (seal payload; invisible) → VERIFY (re-read staged payload; every
reader check + decode + canonical signature) → PUBLISH (one index append: the atomic step) → RETIRE older (maintain)
                                                     │ verify fails
                                                     └→ DROP staged payload; result REJECTED; nothing published
```

**A checkpoint is selectable only after `publish`.** The ref now carries a per-store sequence number, so a re-created identical checkpoint never collides with an older one.

## 4. Crash safety

**Invariant:** at every point, either an older valid checkpoint remains selectable or the reader falls back to journal replay. A partially built checkpoint is never selected. [PROVEN on both stores]

| Crash point | State afterwards |
|---|---|
| During the build | Nothing staged. The old checkpoint is selected |
| After serializing, before the digest is used | Same |
| Before staging | Same |
| After staging, before publication | Invisible orphan payload. The old checkpoint is selected |
| Verification fails (storage corrupts the staged payload; a builder serializes a different fold than it signed) | REJECTED (`verify:integrity`, `verify:state_signature`). The staged payload is dropped and the old one is **not retired** |
| Right after publication | The new checkpoint is selected; the old one is still valid |
| While retiring older checkpoints | The new one plus any not yet retired. All remain valid |
| A torn payload published by a non-conforming store (the compaction v1 test) | Rejected at read time by the digest. Fallback |

**The journal is not involved.** Publication is derived-state maintenance; no journal rule is needed.

## 5. Replacement and retirement

**[DECISION] Order:**
1. The old checkpoint stays available.
2. The new one is built independently.
3. The new one is verified.
4. The new one is published.
5. **Only then** are the older ones retired.

Proven with a spy: at publish time the old one is still live, and it is retired afterwards.

**Retirement removes a derived payload and marks it unusable. No fact is ever touched.**

| Case | Reader uses [PROVEN] |
|---|---|
| Both valid | The new one |
| Old corrupt, new valid | The new one |
| Old valid, new corrupt | The old one |
| None valid | The journal |
| Every checkpoint deleted | The journal. The answer is identical, and no checkpoint payload remains |

## 6. Maintenance trigger

`uncovered(subject)` = partition entries after the newest published checkpoint's covered count. This is positional, with no replay.

`maintain(..., threshold)` creates a checkpoint when `uncovered ≥ threshold`, then retires the older ones.

**Checkpoint cadence = an operational parameter.**
- No production threshold, SLA, latency target, cost target or owner is set.
- Tests use thresholds 0, 1, 3 (small) and 1000 (large), covering not reached, reached exactly and exceeded.
- The answer is the same in every case [PROVEN].

## 7. Concurrency

| Situation | Result [PROVEN] |
|---|---|
| A fact arrives during maintenance (after closure at r) | Placed after r, so it is in the suffix, not in the checkpoint |
| Readers at later positions | Use the checkpoint plus the suffix |
| Readers before r | Never use the newer checkpoint |
| Maintenance of one customer | Never reads or writes another customer's partition (guarded partition) |
| A typed command racing maintenance | At worst a transient READ_CLOSED from the maintenance closure, retried by the Gateway. **APPENDED, never STATE_CONFLICT** |
| An in-flight conflict racing maintenance | Still STATE_CONFLICT |
| Retraction, breaking publication and writes during maintenance | Exact |

**Cost of a closing read:** maintenance takes c from a closing current read, exactly like any read. That is the only interaction with the journal.

## 8. Erased partitions

| Situation | Result [PROVEN] |
|---|---|
| Erasure before the first checkpoint, or in the suffix during incremental creation (key not yet destroyed) | The new checkpoint is an **erased fold with no content**. No ProjectionView |
| Key destruction | Old checkpoints are unreadable and rejected. Incremental creation falls back to a full build, then sealing is refused: `REJECTED key_destroyed`. The read answers from the journal |

No secret survives in the facts, the index or any checkpoint.

## 9. Fallback

| Situation | What happens |
|---|---|
| Any validation failure of the previous checkpoint | Full build (proven equal) |
| Verification failure of the new one | Not published |
| Any reader-side rejection | Next valid checkpoint, else journal replay |

Checkpoint availability is never a correctness requirement.

## 10. No full replay (proof)

`build_fold` and every `reconstruct` are patched to raise:
- **the first checkpoint of a partition fails** under the patch: it legitimately needs a full build;
- **every subsequent maintenance step succeeds**;
- **Gateway reads, typed commands and context compilation** after maintenance all succeed with no full replay anywhere [PROVEN].

## 11. Cost characterisation (reference implementation; relative work only)

Each row creates a checkpoint at the tail of a history of N entries:
- **full:** `build_fold` from the beginning;
- **incremental:** from a checkpoint k entries before the tail.

**Fold work** counts partition entries read, fold steps and slot-signature evaluations. **Payload work** counts bytes serialized, bytes hashed (digest at build plus verification) and bytes decoded (base decode plus verification). Storage overhead (the reference store's `facts()` snapshot copy) is not counted; it is a reference-store artefact.

| N | suffix k | full: entries / fold steps / signatures | incremental: entries / fold steps / signatures | full: serialized / hashed / decoded bytes | incremental: serialized / hashed / decoded bytes |
|---|---|---|---|---|---|
| 25 | 0 | 52 / 29 / 50 | 4 / 0 / 0 | 6850 / 51146 / 6850 | 6850 / 76719 / 13700 |
| 25 | 1 | 52 / 29 / 50 | 7 / 1 / 2 | 6850 / 51146 / 6850 | 6926 / 75896 / 13534 |
| 25 | 10 | 52 / 29 / 50 | 25 / 10 / 20 | 6850 / 51146 / 6850 | 7281 / 67822 / 11711 |
| 100 | 0 | 202 / 104 / 200 | 4 / 0 / 0 | 25001 / 197566 / 25001 | 25001 / 296349 / 50002 |
| 100 | 1 | 202 / 104 / 200 | 7 / 1 / 2 | 25001 / 197566 / 25001 | 25077 / 295516 / 49835 |
| 100 | 10 | 202 / 104 / 200 | 25 / 10 / 20 | 25001 / 197566 / 25001 | 25432 / 287442 / 48012 |
| 400 | 0 | 802 / 404 / 800 | 4 / 0 / 0 | 98203 / 787370 / 98203 | 98203 / 1181055 / 196406 |
| 400 | 1 | 802 / 404 / 800 | 7 / 1 / 2 | 98203 / 787370 / 98203 | 98279 / 1180224 / 196237 |
| 400 | 10 | 802 / 404 / 800 | 25 / 10 / 20 | 98203 / 787370 / 98203 | 98634 / 1172078 / 194387 |

**Reading the table:**
- **Fold work** for the incremental path grows with k and does not grow with N.
- **Payload work** grows with the checkpoint's size, for both paths. That size still grows with the claim map and trace (the size [CONTRACT_GAP]).
- **Incremental payload work is about 1.5× the full build's.** It also validates and decodes the base checkpoint, and the hashed bytes include the digest at build, the reader-style validation of the base, and the staged-payload verification.
- **The trade:** fold work drops from O(N) to O(k), and payload work rises by a constant factor of the checkpoint size. Once fold work stops growing, payload size is the term that does, which makes checkpoint-size pruning the next lever.
- No production latency claim is made.

## 12. Tests

`tests/test_checkpoint_maintenance.py`: **82**, both stores.

| Area | Tests |
|---|---|
| Incremental equivalence on random histories (6 seeds × 2), with no full build | 12 |
| Maintenance chain; policy, commitment, episode and scheduled changes | 4 |
| No full replay (initial vs subsequent; Gateway end to end) | 4 |
| Crash points (6 × 2) | 12 |
| Staged verification: integrity; builder signature mismatch | 4 |
| Retire-after-publish order; published checkpoint never mutated | 4 |
| Reader matrix (4 × 2); all checkpoints deleted | 10 |
| Trigger (7 × 2) | 14 |
| Concurrency: arrival during maintenance and earlier readers; isolation; typed race; in-flight conflict; retraction/policy/write race | 10 |
| Erasure (3 cases × 2); corrupt previous → full-build fallback | 8 |

## 13. Mutation results

17 protections removed one at a time; the maintenance, compaction, consumer and fast-path suites run each time; the code restored byte-identical. **17/17 caught.**

| Protection removed | Result |
|---|---|
| Previous-checkpoint validation | caught |
| Partition validation | caught |
| Suffix boundary | caught |
| Checkpoint position (base advanced to the new c) | caught |
| Incremental fold (the base's content) | caught |
| State-signature validation (reader) | caught |
| **State-signature verification (publication)** | caught |
| Policy-position validation | caught |
| Digest / seal validation | caught |
| Atomic publication (publish before verify) | caught |
| Unverified payload dropped | caught |
| Old retained until the replacement is published | caught |
| Erased-partition handling (erasure in the suffix) | caught |
| Corruption fallback to a full build | caught |
| Maintenance threshold | caught |
| Uncovered suffix length | caught |
| Reader selects the newest valid checkpoint | caught |

The publication-verification signature check **survived the first run**. A builder-defect test now catches it: a fold serialized differently from the one signed.

## 14. Regression

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
| Fast path | 51 |
| Maintenance (new) | 82 |
| **Full suite** | **1575 passed** (1493 + 82). No existing test edited, weakened or skipped |

## 15. Remaining gaps (not addressed here)

- **Checkpoint size pruning.** Payload serialization, hashing and decoding cost grows with the checkpoint, which is now the dominant per-maintenance cost (§11).
- **An idempotency (`idem`) index.**
- **Policy-log indexing.**
- **Real-storage evaluation (C-5), E-5, physical truncation, deployment.**
- **Choosing the cadence value: operational, unset.**
- **A crash-time orphan payload is never removed.** It is never selected; garbage collection of staged-but-unpublished payloads is an operational housekeeping task [INFERENCE].

No owner boundary was reached; no CTO/owner packet was created.

**CHECKPOINT MAINTENANCE V1 CONFORMANT.**
