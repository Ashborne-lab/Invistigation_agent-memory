# Checkpoint Representation Pruning v1 (technology-neutral)

**Date:** 2026-10-05.

**Classification:** TARGET ARCHITECTURE. Prototype and test only.

**Result in one line:** **no semantic pruning is proven safe, so nothing is pruned.** Instead there is a lossless, opt-in reference encoding: the checkpoint stores references to sealed journal facts instead of copies of them, and drops two fields derivable from the trace.

**Unchanged:** K1–K10, S1–S5, O1–O4, SPI, R-READ, the gate, Current State, OCC, idempotency, erasure, causal semantics. The Durable Journal stays the sole truth source.

**Builds on:** compaction v1, consumer interface v1, fast path v1.2, maintenance v1.

**Labels:** [PROVEN], [DECISION], [CONTRACT_GAP], [INFERENCE].

**Executable form:**
- `memory_core/journal_compaction/`:
  - `encode` / `decode` / `load`;
  - `Checkpoint.encoding`;
  - `CheckpointStore(encoding=...)`;
  - reference capture in the fold;
  - globally unique checkpoint refs;
- `tests/test_checkpoint_representation_pruning.py`.

---

## 1. Phase 0: where the bytes are, and what each field is

**Measured composition of a full checkpoint** (N claims; explicit store):

| N | total | claim map | trace | everything else |
|---|---|---|---|---|
| 25 | 6,872 | 6,063 (88%) | 509 | ~300 |
| 100 | 25,023 | 22,789 (91%) | 1,784 | ~450 |
| 400 | 98,125 | 90,143 (92%) | 6,929 | ~1,050 |

**The claim map is the payload, and every claim's content is a copy of a sealed claim record that already sits in the journal's vault.**

**Classification of every fold field.** Categories:
- **A** must remain;
- **B** smaller derived form;
- **C** reconstructible from another field;
- **D** may move to the journal;
- **E** not removable without a contract change.

| Field | Class | Basis |
|---|---|---|
| Claim **set** (which claims exist) | **A**, and **E** for semantic pruning | §2: any claim can affect a later result, and history at r needs every claim |
| Claim **content** | **B**: a reference to the sealed claim record | The content *is* the journal fact (`vault[(key id, ref)]`), immutable. Copying it adds no information |
| Claim lifecycle **state** (status, transitions, support, merge ids, …) | **A** (it is fold output, not a fact). Kept, as a field tuple | Derived by replaying lifecycle/retraction entries; the only alternative is replay |
| Retractions | **A** as a set (LA-9: they end claims committed later); **B** for content: a reference | `commit._insert` applies every prior retraction |
| Pending validity boundaries | **A** (small) | Future evaluation points |
| Version in force per predicate | **A** (small) | O3 at later points |
| Trace (version history) | **A** for the served trace (the full version history is served); `_version` needs only its length | Moving it to the journal (**D**) would bring back the replay that fast path v1.2 removed. Kept |
| `versions`, `last` | **C**: `versions[k] = len(trace[k])` and `last[k] = trace[k][-1][1]` | `_evaluate` updates all three together. The invariant is checked at encode time, and encoding refuses if it fails |
| Max sync, `claims_version`, erased, unsafe, position, c | **A** (small) | — |
| Commitment events | **A** as a set (the projection is a set function, and `reopen_operator` revives terminal commitments); **B** for content: references | §2 scenario 10 |
| Episode generations | Already latest-only; **B**: references | Generations are sealed facts |
| Entry predicates | **A** (small) | Read closure (fast path v1.2) |
| State signature | Index metadata, recomputed from the decoded fold | — |
| History labels | Not stored; derived at read | — |

## 2. Why semantic pruning is not proven: the counterexamples

A test-only **naive pruner** keeps only the claims that win or conflict in some slot at c, and drops the events of commitments that are terminal at c. Each scenario is run with the naive pruner and with the real (compact) checkpoint, and both are compared with the journal at a later r.

| # | Scenario | Naive pruner diverges? | Compact checkpoint |
|---|---|---|---|
| 1, 4 | The winner is superseded at c; the newer claim is retracted as NEVER_TRUE, so the superseded claim is current again | **Yes** | Exact |
| 2, 7 | A claim not yet valid at c (`valid_from` later) becomes current at its boundary | **Yes** | Exact |
| 3 | A claim excluded by a breaking policy at c becomes eligible under a later version | **Yes** | Exact |
| 5 | A retraction arrives for a claim that would have been pruned (history at r changes) | **Yes** | Exact |
| 6, 8 | A claim quarantined or invalidated at c is reactivated by a lifecycle change | **Yes** (both statuses) | Exact |
| 9 | Erasure | **No.** Erasure ends everything, so the naive answer agrees. **Not counted as a counterexample** | Exact |
| 10 | A commitment terminal at c is reopened by an operator | **Yes** | Exact |

**Three independent reasons the claim set is class A (and E for pruning):**
1. **Resolution can reach any claim.** Lifecycle accepts any target status (the C-2 transition graph and its Legal-owned reversal edges are undecided). LA-9 retractions apply to claims committed later. A NEVER_TRUE retraction of a newer claim revives the older one.
2. **History at r needs every claim**, independently of resolution.
3. **Policy migration can re-include an excluded claim.**

**Precondition for any future semantic pruning:**
- a decided lifecycle graph: C-2, already routed (Legal owns its reversal edges), so no new owner packet;
- a dominance proof over the resolver;
- history served from somewhere other than the claim map.

None of these is available in v1.

## 3. The compact ("ref") encoding

```text
payload = { fold core (claims, retractions, events, generations, versions, last and every reference field emptied),
            claims:      [(key-id index, claim record ref), claim state as a field tuple]   (claim map order),
            retractions: [(key-id index, ref)],  events: [(key-id index, ref)],  generations: [(key-id index, ref)],
            keys:        [key ids] }
```

- **Decode:**
  - each claim is `Claim(vault[ref].claim_content, ClaimState(*state))`, keyed by the content's own claim id (the map key, so it is not stored);
  - retraction records, events and generations are read from the vault;
  - `versions` and `last` are derived from the trace.
- **The decoded fold is identical to the full encoding's** (§5). Every existing validation then runs on it unchanged, including the state signature.
- **Opt-in:** `CheckpointStore(storage, encoding="ref")`. Each checkpoint records its `encoding`, and readers decode by it, so full and compact checkpoints coexist and maintenance can move from one to the other.
  - **The default stays `"full"`.** Five existing tests decode the full payload directly (forging, inspecting, comparing). Changing the default would mean editing them, which is a stop condition.
  - Choosing the encoding in production is engineering configuration, not an owner value.
- **Fail-safe rules:**
  - **A missing referenced fact rejects the checkpoint** (`unreadable_reference`). It is never skipped, because a partial claim map would diverge silently.
  - An unknown encoding is rejected (`encoding`).
  - A fold whose derived fields or references do not hold is **refused at encode time**: `UNSUPPORTED compact_encoding_invariant`.
- **No second truth source.** The references point at immutable journal facts. Nothing is copied, and erasing the facts (key destruction) makes the checkpoint unreadable, exactly as before.

**Found and fixed: a ref-collision defect.** Two checkpoint stores over one storage both numbered their refs from 1, so the second seal **overwrote the first's payload**. Maintenance v1's per-store sequence was not unique across stores or restarts. Refs now carry a random 64-bit nonce. Every earlier suite stays green.

## 4. No full-history work (proof)

The full-history fold (`build_fold`), every `reconstruct`, **and full-encoding decode** are patched to raise. With a compact store all of these succeed:
- incremental maintenance;
- Gateway current reads and history;
- typed commands, including the in-write K9 check with an in-flight conflict;
- context compilation.

The first checkpoint of a partition legitimately needs a full build.

**Compact decoding reads only the tail anchor and the suffix of the partition.** The referenced facts are point reads from the vault, not partition scans [PROVEN with a counted partition].

## 5. Equivalence

**For every compact checkpoint, against the full checkpoint at the same c** (random histories × both stores × checkpoints at the beginning, a third, two thirds and past the tail, plus a 40-claim history with retractions, syncs and boundaries):
- the **state signatures are identical**;
- the decoded folds are equal, with the claim map in the same order;
- every read r ≥ c gives the same rebuild, equal to full replay;
- every ProjectionView answer is the same: current state for every predicate, history at r and compiled context.

**Also covered:**
- commitment events and episode generations, with expiry and newest generation;
- maintenance chains on a compact store, including **incremental maintenance from a full-encoded base** into compact checkpoints (signature equal to a fresh full build at every step);
- erasure and key destruction.

A scratch probe gave **120/120 equal** on 10 seeds × 2 stores × 2 subjects × 3 positions.

## 6. Cost characterisation (reference implementation; relative only)

| N | claims | trace records | full payload (= digest input) | compact payload (= digest input) | ratio | signature input (both) | decoded bytes full / compact | vault reads on compact decode |
|---|---|---|---|---|---|---|---|---|
| 25 | 25 | 25 | 8183 | 2361 | 0.29 | ~17271 | 8183 / 2361 | 25 |
| 100 | 100 | 100 | 30159 | 8139 | 0.27 | ~69200 | 30159 / 8139 | 100 |
| 400 | 400 | 400 | 118561 | 30986 | 0.26 | ~277700 | 118561 / 30986 | 400 |

(The signature input is approximate: the repr of the claim map that the canonical signature hashes. It is the same for both encodings.)

**Reading the table:**
- **Payload and digest-input bytes drop to 26–29% of full (about 3.5–3.8× smaller)** at N = 25, 100 and 400, and the ratio holds as N grows. The remaining bytes are claim states, references and the trace.
- **The signature input is now larger than either payload** (about 2.3× the full payload) and is unchanged by the encoding. That makes it the next cost to remove.
- **What still grows with history:**
  - the canonical **state signature** is recomputed over the decoded fold (claim content included) at publication and at every validation, so its input is unchanged by the encoding;
  - compact **decoding performs one vault read per referenced fact**;
  - the **trace**.
- Per-use verification and decoding therefore remain O(history size). Only the payload, its digest and its storage shrink.
- No production latency claim is made.

## 7. Tests

`tests/test_checkpoint_representation_pruning.py`: **58**, both stores.

| Area | Tests |
|---|---|
| Equivalence on random histories (6 × 2) | 12 |
| Long claim-heavy history: equal, and materially smaller | 2 |
| Commitment events and episode generations referenced, not copied | 2 |
| Maintenance on a compact store and from a full base | 2 |
| No full build / replay / full decode: Gateway end to end; in-flight K9; decode reads only the suffix | 6 |
| Missing reference rejects; unknown encoding; forged compact payload | 6 |
| Encode-time invariant refusal (5 breakages × 2) | 10 |
| Erasure and key destruction | 2 |
| Dead-claim scenarios (1/4, 2/7, 3, 5, 6/8 × 2 statuses, 9, 10) | 16 |

## 8. Mutation results

**15 compact-path protections removed one at a time, running the pruning, maintenance, compaction, consumer and fast-path suites: 15/15 caught.**

| Protection removed | Result |
|---|---|
| A missing reference rejects (never skipped) | caught |
| Claim reference capture | caught |
| Retraction reference capture | caught |
| Event reference capture | caught |
| Generation reference capture | caught |
| Derived `versions` | caught |
| Derived `last` | caught |
| Derivation-invariant check | caught |
| Encoding-field check | caught |
| Claim-map order on decode | caught |
| Claim-state field order | caught |
| Decoding by the checkpoint's own encoding | caught |
| Unreadable reference → rejection | caught |
| Partition check | caught |
| State signature after decode | caught |

**The brief's semantic-pruning mutations do not apply here.** Retention proof, lifecycle retention, retraction retention, validity-boundary handling and policy-history handling all target pruning, and v1 prunes nothing, so there is no such code to mutate. The dead-claim counterexamples (§2) are the evidence for those properties instead.

## 9. Regression

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
| Pruning (new) | 58 |
| **Full suite** | **1633 passed** (1575 + 58). No existing test edited, weakened or skipped |

## 10. Remaining gaps

| Gap | Label |
|---|---|
| **Semantic pruning of the claim set** | Blocked on a decided lifecycle graph (C-2, routed), a resolver dominance proof, and a non-claim-map home for history |
| **Signature recomputation and decode remain O(history)** | [CONTRACT_GAP] engineering: an incremental or Merkle-style state signature would remove the recomputation |
| **Trace size** | Next lossless option, not built: interned signatures with implicit version numbers |
| The `idem` index, policy-log indexing, GC of crash-orphaned staged payloads | Carried over |

No owner boundary was reached; no CTO/owner packet was created.

**CHECKPOINT REPRESENTATION PRUNING V1 CONFORMANT.**
