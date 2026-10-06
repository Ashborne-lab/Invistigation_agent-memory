# Incremental Checkpoint Signature v1

**Date:** 2026-10-05.

**Classification:** TARGET ARCHITECTURE. Prototype and test only.

**Result:** **NOT FEASIBLE as specified. The existing canonical signature cannot be computed incrementally and exactly.** The signature definition is **preserved unchanged** and nothing is optimised. Replacing the definition is a contract decision, packaged in `cto-owner-decision-request-v1.md`.

**Labels:** [PROVEN], [DECISION], [CONTRACT_GAP], [INFERENCE].

**Tests:** `tests/test_incremental_checkpoint_signature.py` (feasibility evidence only).

---

## 1. Phase 0: the existing signature, from source

`journal_compaction.state_signature(f) = SHA-256(repr(canon).encode())`, where `canon` is one tuple:

```text
(subject, at, position, erased, cv, sorted(versions), sorted(last), sorted(in_force), sorted(pending),
 sorted(sync), sorted(trace), sorted((claim id, repr(claim)) …), repr(retractions), repr(events),
 sorted((episode id, repr(generation)) …), sorted(predicates))
```

| Question | Answer from source |
|---|---|
| **A.** What is hashed | One flat byte string: the repr of the tuple above. It covers **full claim content and state**, the retraction records, commitment events and generations, the version state, the trace, the pending boundaries, the version in force, freshness, `claims_version`, the erased flag, the covered position and count, and the predicates |
| **B.** What a new fact changes | **Always `at` and `position`** (elements 2 and 3). Depending on the kind, also: the claim map (a new claim, or a changed state through lifecycle or retraction, possibly on old claims, LA-9), `versions` / `last` / `trace`, `cv`, `pending`, `sync`, `in_force`, `retractions`, `events`, `generations`, `predicates` |
| **C.** What is inherited unchanged | The content of untouched claims and older trace entries. Their **byte positions shift**, though, whenever anything earlier changes: claims are sorted by id, so a new claim is inserted mid-stream |
| **D.** Order-sensitive? | Yes. A fixed tuple order; claims sorted by id; retractions and events in partition order |
| **E.** Retractions / lifecycle | Yes: the claim-state repr plus the retraction records |
| **F.** Policy publications | Yes: `in_force`, and the versions and trace they produce. The policy-log position is not hashed; it is checked separately |
| **G.** Erasure | Yes: the erased flag, and an erased fold carries no content |
| **H.** Commitments / episodes | Yes: the repr of the events and generations |
| **I.** `versions` / `last` | Yes, both participate, although they are derivable from the trace |
| **J.** Compositional? | **No.** It is a single SHA-256 over a flat serialization, not a composition of sub-digests |

**Not covered by the signature, each validated separately:**

| Item | Validated by |
|---|---|
| Reference fields | The decoded content |
| Policy position | `policy_log_changed` |
| Partition | `wrong_partition`, plus `subject` inside the hash |
| Contract | `contract_version` |
| Encoding | `encoding` |
| `unsafe` | Unsafe folds are never checkpointed |

[PROVEN by test]: the current signature detects corruption of each of 18 covered fields, and each uncovered field is rejected by its own check.

## 2. Feasibility: NOT FEASIBLE (exact reproduction)

**1. Hash resumption.** SHA-256 is Merkle–Damgård over 64-byte blocks. A hash state can be resumed only over an **unchanged byte prefix**. `at` is the second element of the canonical tuple, so it sits in the **first 64-byte block**, and every advance changes it.

Producing the same signature bytes therefore requires re-hashing the whole input every time. **No algorithm can produce SHA-256(M) for a new M without processing every byte after its first change.**

**2. Reordering does not escape it.** Claims are sorted by id, and lifecycle and retraction changes alter claim states in the middle of the stream. Moving `at` to the end would still not give an append-only input. The move would itself be a **change of definition**.

**Measured** (`sig_prefix_probe`, 10 random histories, 556 advances): the first changed byte of the input is at offset **7 to 12** in **every** advance. A test pins this on both stores.

**So an optimised signature cannot equal the existing one.** The brief permits only (1) the same signature bytes, or (2) a proven, *decided* replacement. (1) is impossible; (2) is a normative change to the compaction contract's identity definition (compaction contract §1, `state_signature`). That is an owner decision, so: **STOP.**

## 3. What a replacement would and would not buy

**This is the important correction to the premise.** A full checkpoint signature is recomputed in four places:
- validation of the base before incremental creation;
- the signature at build;
- verification of the staged payload before publication;
- **every reader validation.**

To detect a modified claim anywhere in a payload, a verifier must hash every leaf, whatever the construction (flat, Merkle, rolling). Sampling is ruled out (no probabilistic substitute).

So:

| Path | With a Merkle-style redefinition |
|---|---|
| Build | Can be incremental: the base's leaf digests plus changed leaves. **This is the only saving** |
| Staged verification | Still hashes every leaf |
| Every reader validation | Still hashes every leaf |

A redefinition alone **saves at most one pass per checkpoint creation**. The real lever is the **verification trust model**: whether a reader may rely on an earlier, recorded verification. That is the decision in the packet.

## 4. Measured: where the full signature work happens today

Full canonical-signature computations per operation, with checkpoints enabled (`sig_count`, both encodings):

| Operation | Full signature computations | Where |
|---|---|---|
| Gateway `get_current_state` | **3** | `_read_preds`, `served_trace` and the ProjectionView, each validating the same checkpoint |
| Gateway `compile_context` | **3** | Same |
| Typed command | **4** | Gateway scratch (×2: gate and `commit()`) and `_version` (×2: build and the in-write K9 check) |
| Incremental maintenance | **5** | Closing read (×2), base validation, build signature, staged verification |

**Engineering follow-up, with no definition change and no owner decision:**
- validate a checkpoint **once per operation** and reuse that validated fold within the operation;
- the K9 in-write check must still use the facts at write time; reusing the validated base and advancing it through the suffix is enough.

This would cut reads 3→1, commands 4→2 and maintenance 5→3, with the existing signature exactly preserved. **Not built in this workstream** (it is outside the brief's scope).

## 5. Canonical identity versus bytes

Semantic identity is the canonical signature. The payload digest is integrity only. [PROVEN] Full, compact, incremental and fresh checkpoints of the same state share **one** canonical signature while their serialized bytes differ (encoding, object-sharing layout). That holds through a maintenance chain on both stores.

## 6. Tests

`tests/test_incremental_checkpoint_signature.py`: **49**.

| Area | Tests |
|---|---|
| Every advance changes the first 64-byte block (4 random histories × 2 stores) | 8 |
| The canonical signature is still exactly SHA-256 of the canonical input (no silent redefinition) | 1 |
| The current signature detects corruption of each covered field (18 × 2) | 36 |
| Uncovered fields (policy position, contract, encoding, partition, a swapped claim reference) are caught by their own checks | 2 |
| One canonical signature across full, compact, incremental and fresh checkpoints | 2 |

**Mutation testing: not applicable.** No signature code was added or changed, so there is nothing new to mutate. The existing reader, publication and maintenance signature checks are already covered by the earlier mutation runs: compaction 29/29, maintenance 17/17 and pruning 15/15.

## 7. Regression

See §9.

## 8. Remaining limitations

| Limitation | Label |
|---|---|
| Signature verification remains O(total claim content) per validation, and is done 3–5 times per operation | **[OWNER]** for the trust model (packet); **engineering** for per-operation reuse (§4) |
| Compact decode does one vault read per referenced fact | Unchanged |
| Trace size | Unchanged |

## 9. Regression results

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
| Signature evidence (new) | 49 |
| **Full suite** | **1682 passed** (1633 + 49). No existing test edited, weakened or skipped; **no production code changed** |

**Owner packet created:** `cto-owner-decision-request-v1.md`.

**INCREMENTAL CHECKPOINT SIGNATURE V1 BLOCKED.**
