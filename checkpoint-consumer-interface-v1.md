# Checkpoint Consumer Interface v1 (technology-neutral)

**Date:** 2026-10-05.

**Classification:** TARGET ARCHITECTURE. Prototype and test only.

**Builds on:** `durable-journal-compaction-contract-v1.md` (whose consumer-interface [CONTRACT_GAP] this closes), journal v1.1 plus A1, Gateway v0.1.

**Labels:** [PROVEN], [DECISION], [CONTRACT_GAP], [OWNER], [INFERENCE].

**Executable form:**
- `memory_core/projection_view/` (new);
- `memory_core/retrieval/` (one optional `MemorySource.view` field, plus routing of its three journal reads);
- `memory_core/gateway/` (an optional `checkpoints` store; read path and write-path scratch);
- `memory_core/journal_compaction/` (`checkpoint_fold` factored out of `rebuild`, plus a wrong-partition check);
- `tests/test_checkpoint_consumers.py`.

**Key invariant:** **if the checkpoint is rejected, the consumer falls back to authoritative journal replay. A bad checkpoint never changes truth.**

---

## 1. Purpose

Let the Gateway and typed retrieval consume a **validated checkpoint plus the retained suffix** instead of replaying the whole journal view, while the Durable Journal stays the sole source of truth:

```text
journal facts → authoritative replay ≡ validated checkpoint(c) + suffix(c, r] → ProjectionView(subject, r) → Gateway / Retrieval
```

The checkpoint stays an acceleration structure. The ProjectionView is a read representation, derived per read and never stored.

## 2. ProjectionView definition

### Phase 0: what each consumer needs, verified against source

| Consumer input | Used by | In the validated fold? |
|---|---|---|
| Current state (`CurrentState` at as_of = now = r) | `get_current_state`, `search_history` labels, context | **Yes** (compaction §3, [PROVEN]) |
| `state_version` per slot | Read items; the typed-command OCC base | Yes (inside the state) |
| Version trace | Served-trace/SPI checks (journal-side) | Yes |
| Policies visible at r, plus the policy history | Retrieval policy lookups, security class, labels | Yes (computed from the policy log at r) |
| Claim map (content plus lifecycle, all claims of the partition) | `search_history` (`retrieval._claims`); the gate's current slot; `commit()`'s claim-existence check (`store.claims`) | **Yes.** The fold never drops a claim |
| Retractions | Already applied inside the claim map. Needed again only to continue the fold | Yes (carried for the suffix) |
| Freshness (max `synced_at` per predicate for the subject at r) | `search_history` `_freshness`; the gate's `resolve_slot(..., last_sync)` | **Yes** (`Fold.sync`) |
| Commitment events / episode generations | `get_commitments` / `search_memory` inputs | Yes |
| Erasure state | Every consumer | Yes. **An erased fold yields no view** (§10) |
| Idempotency outcomes (`outcome:<id>`) | The Gateway's duplicate check (`_outcome_of`) | **No** (by design). Answered by the journal's `idem` lookup |
| The journal view (`JournalEntry` list) | Nothing on the proven paths once routed (§6–§8) | **No.** It is never synthesized |

`commit()` reads only `store.records` (empty in a scratch store), `store.claims` and `store.retractions` (empty in a scratch store, both before and now). It appends to its own scratch journal and needs no prior entries (`commit/__init__.py:181-251`) [PROVEN by source].

### ProjectionView fields

| Field | Meaning |
|---|---|
| `subject` | Partition identity |
| `r` | The served position this view answers for. Exactly one position |
| `covered_at` | c of the validated checkpoint it came from (diagnostic) |
| `policies`, `policy_history` | Policy context at r |
| `state`, `trace` | The state projection at r |
| `claims` | The partition's claim map at r: provenance and lifecycle |
| `sync` | Freshness: predicate → max `synced_at` for this subject, at r |
| `commitment_events`, `generations` | The A1 projections at r |
| Historical availability | **The served position only.** No as-of reads, no positions before r, no journal entries |
| Erasure | Never present for an erased partition (no view) |

**Not in the view:**
- idempotency identities and outcomes;
- journal entries;
- history before r;
- a durable identity of its own (it is not a checkpoint, not a fact, and never persisted).

## 3. Validity requirements

`open_view(facts, subject, r, checkpoints)` returns a view only if the newest checkpoint with c ≤ r passes **every** check: the compaction contract §4, **plus** `partition == subject` (new: `wrong_partition`). It is then advanced through the durable suffix (c, r].

Otherwise it returns **None**. Every rejected checkpoint is marked unusable.

## 4. Covered position semantics

- A view answers for exactly (subject, r), with as_of = now = r. That is the Gateway's served read.
- Retrieval **raises** if a view-backed source is asked about another subject or another position. It never falls through to an empty journal [PROVEN].
- r is the journal's served position (K7). The causal token and the closure are unchanged.

## 5. Journal relationship

- The journal remains the only authority.
- A view is recomputed from facts (checkpoint + suffix) at each use.
- No journal rule changes: K1–K10, S1–S5, O1–O4 and SPI are all untouched.
- No entry is synthesized: no sync, claim or retraction entry is fabricated for a consumer.

## 6. Current-state consumption

`get_current_state` over `memory_source(view)` returns exactly what it returns over the journal view at the same r:
- all predicates;
- each predicate individually;
- security filtering;
- UNKNOWN items.

[PROVEN]:
- 6 random histories × 2 stores × several checkpoints and reads;
- a Gateway random property (5 seeds × 2 stores);
- targeted cases.

**`search_history` at the served position** is also view-served. It needs only the claim map, the state at r, the policies and the max sync, and the fold carries all four exactly [PROVEN equal]. Scope:
- **the served position only**;
- it relies on the checkpoint carrying the **full claim map**, which is the size gap in §15.

## 7. Typed-command / OCC consumption

| Step | Source |
|---|---|
| The caller's `expected_version` | Any read, including a view-served one (its `state_version` is exact) |
| The gate's current slot and freshness input | `scratch(view at clock)`: a **fresh deep copy** of the claim map, plus `view.last_sync` |
| The `commit()` record factory at the journal-assigned `at` | `scratch(view at at)`. A checkpoint advanced through the suffix to `at` |
| `actual_version` passed to `commit()` and the **K9 in-write check** | **Unchanged: the journal** (`TimedJournal._version` inside `prepare`/`finish`) |

**The projection is never the authority for the final write.** STATE_CONFLICT is preserved in all three cases [PROVEN]:
- a stale base;
- a write after the read;
- a write landing **in flight** between preparation and the durable write, which only the journal's K9 check can see.

Removing `expected_version` from `prepare` is caught (§16).

## 8. Context consumption

- `compile_context` receives the same `get_current_state` and `search_history` results from a view as from the journal view.
- Its input source changes; its semantics, the data channel and the size measure do not.
- The `ContextPackage` (status, `memory_data`, manifest) is identical [PROVEN].
- No stale-read behaviour is added: views exist only at the served, closed position r.

## 9. History limitations

| History class | v1 source | What a checkpoint-aware path would need |
|---|---|---|
| History at the served position r (`search_history(now = r)`) | **View** | Nothing more |
| As-of history at an arbitrary earlier position (not a Gateway v0.1 operation) | Journal | A checkpoint ≤ that position, or a derived history index [CONTRACT_GAP, engineering] |
| The audit trail and the journal view itself | Journal | Retained facts. Truncation remains [OWNER] (compaction §7) |

## 10. Erasure behaviour

| Situation | Result [PROVEN] |
|---|---|
| Erased fold (erasure in the suffix or in the checkpoint) | No view. The journal path answers (ERASED) |
| Checkpoint before erasure, key destroyed | Unreadable. Rejected, so no view |
| Destroyed key without an erasure entry | Unreadable. Rejected, so no view |
| A secret after erasure | Absent from the facts and from the checkpoint index |

## 11. Policy behaviour

| Situation | Result [PROVEN] |
|---|---|
| A breaking or non-breaking publication after c | Visible through the suffix, and the view stays exact |
| A late publication at T ≤ c (explicit store, a predicate the partition never read) | Policy-log position mismatch: fallback to the journal |
| A stale checkpoint (long suffix) | Exact |
| A tampered policy position | Fallback |

## 12. Failure and fallback behaviour

Every invalid checkpoint falls back, and the read and write results equal the journal path [PROVEN for each case]:
- bad digest;
- **wrong partition**;
- wrong contract version;
- wrong tail;
- invalid policy position;
- forged payload with a matching digest.

The fallback is the **unchanged v0.1 code path**. A typed command after a rejected checkpoint is admitted exactly as before.

## 13. Concurrency

- **Views are built after the journal's current read closes the partition** (K5–K7), so no append can land at or before r.
- **Appends after r** are in later suffixes.
- **The scratch store is copied per use**, so `commit()` mutations never reach the view or the checkpoint [PROVEN].
- **One customer's view and checkpoint never read another customer's partition** [PROVEN: guarded partition].

## 14. Recovery

- A view is derived per read, so there is nothing to recover.
- Checkpoint recovery is as in compaction §3–§4.
- After a restart, the Gateway reads with or without checkpoints, with identical results.

## 15. Explicit exclusions and remaining gaps

**Excluded:**
- non-CUSTOMER scopes;
- as-of reads before the served position;
- idempotency through the view;
- physical truncation;
- E-5, C-5;
- identity events;
- erasure reversal.

**Remaining scalability gaps:**

| Gap | Label | Note |
|---|---|---|
| **Journal-side replay remains.** `TimedJournal.read` → `_serve` → `reconstruct` on every current read (to record the served trace). `TimedJournal._version` → `reconstruct` for K9 (in `build` and in the `finish` check) on every typed command | [CONTRACT_GAP] engineering, a future journal amendment | **Online current-state reads therefore still replay the full history inside the journal in this reference.** v1 removes only the **consumer-side** replay (Gateway `reconstruct` + `rebuild_claims`, and the retrieval journal walk) [PROVEN by raising patches]. Fix direction: separate read closure from served-trace computation, and make the version lookup inside the serialized write checkpoint-aware. No owner decision is involved |
| Checkpoint size grows with the claim map, trace, retractions, commitment events and generations | [CONTRACT_GAP] engineering | §15a |
| Idempotency lookup scans the partition in the reference | Storage requirement | A per-partition `idem` index (compaction §14) |
| Checkpoint cadence | Operational parameter | No semantic effect. Unset |

**§15a. A path to a bounded representation, without a second truth source** [INFERENCE]:
- The view separates **bounded** inputs (state, sync, policies: proportional to live slots) from **history-sized** inputs (the claim map and the trace).
- The claim map is needed for two reasons:
  - **(a)** history at r, which could move to a derived history index or back to journal replay;
  - **(b)** continuing the fold, since lifecycle, retraction (LA-9), validity boundaries and read-time supersession can reach any claim.
- Bounding (b) needs a **proof of which claims can never again affect resolution**. That is a semantic analysis of the resolver and the lifecycle graph, owned by engineering, not by an owner.
- Any pruned set stays re-derivable from the facts, so no new truth source is created.
- **Not attempted in v1.**

## 16. Conformance requirements

| Requirement | Evidence |
|---|---|
| View results ≡ journal-path results (current state, per-predicate state, history at r, context) | Random-history property; Gateway random property |
| The consumer never reads the journal when a checkpoint is valid | `reconstruct` / `rebuild_claims` patched to raise; the view-backed source's journal raises on access |
| OCC: stale base, a write after the read, an in-flight conflict decided by journal K9 | Three tests |
| Policy: a breaking publication after c, a late publication, a stale checkpoint, a policy-position mismatch | Tests |
| Erasure and destroyed key | Fallback tests |
| Commitment and episode projections (expiry, newest generation, derived status) | Test |
| Every corruption falls back safely, reads and writes alike | 6 corruption kinds × 2 stores |
| Partition isolation | Guarded other-customer partition |
| Mutation | §17 below |

**No owner boundary was reached.** No CTO/owner decision packet was created.

---

## 17. Results

**Verdict: CHECKPOINT CONSUMER V1 CONFORMANT.**

### Operations

| Operation | Uses ProjectionView? | Suffix needed? | Requires the journal? | Why |
|---|---|---|---|---|
| `get_current_state` | **Yes** | Yes, (c, r] | Closure and served trace only (journal-internal) | The state at r is exactly the fold's [PROVEN] |
| `search_history` at the served r | **Yes** | Yes | Same | Claim map + state + policies + max sync [PROVEN] |
| `compile_context` | **Yes** (both inputs) | Yes | Same | Identical inputs give an identical package [PROVEN] |
| Gate current slot (typed commands and observations) | **Yes** (scratch at clock) | Yes | — | Claim map + max sync |
| `commit()` record factory at `at` | **Yes** (scratch at `at`) | Yes, to `at` | — | Claim-existence check only |
| K9 version / OCC in the serialized write | No | — | **Yes** (`TimedJournal._version`) | The final authority. Unchanged |
| Read closure and served trace | No | — | **Yes** (`TimedJournal.read`) | Journal v1.1, unchanged ([CONTRACT_GAP] §15) |
| Idempotency outcome lookup | No | — | **Yes** (`idem` lookup) | Outcomes are not in the view, by design |
| Causal-token bound | No | — | Tail read only | Unchanged |
| Erased partition | No (no view) | — | **Yes** (fallback) | §10 |
| As-of history before r; the audit trail | No | — | **Yes** | §9 |

### Tests

`tests/test_checkpoint_consumers.py`: **65**, every store-dependent test on both reference stores.

| Area | Count |
|---|---|
| Random-history retrieval and context equivalence (6 seeds × 2), with a raising journal sentinel | 12 |
| Gateway random property (5 seeds × 2) | 10 |
| Consumer never replays (patched `reconstruct` / `rebuild_claims`) | 2 |
| View covers only its position and subject | 1 |
| OCC: current command, a write after the read, an in-flight conflict decided by K9, fresh scratch copy | 8 |
| Policy: breaking after c, late publication, stale checkpoint | 6 |
| Corruption (6 kinds × 2): reads **and** writes fall back | 12 |
| Erasure and destroyed key | 4 |
| Retraction + freshness; external freshness at the gate and in history; foreign-subject claim | 6 |
| Commitment and episode projections | 2 |
| Partition isolation | 2 |

### Mutation run

18 protections removed one at a time, running the consumer, compaction and both Gateway suites. **18/18 caught.**

| Protection removed | Result |
|---|---|
| Checkpoint validation | caught |
| **Partition validation (new)** | caught |
| State-signature validation | caught |
| Policy-position validation | caught |
| Suffix advancement | caught |
| Fallback to full replay | caught |
| Erasure handling | caught |
| Commitment projection | caught |
| Episode projection | caught |
| Freshness | caught |
| Deep-copied scratch | caught |
| View covers only its (subject, r) | caught |
| History freshness from the view | caught |
| History claim-map subject filter | caught |
| OCC re-check in the journal | caught |
| Gate freshness input | caught |
| Gateway reads use the view | caught |
| Gateway write scratch uses the view | caught |

Three mutants survived the first run: history freshness, the subject filter and gate freshness. They were closed by:
- the external-freshness test;
- the foreign-subject-claim test;
- a second command on a populated stale-write-forbidden slot.

### Regression

| Suite | Result |
|---|---|
| Journal conformance | 144 |
| Storage boundary | 86 |
| X-1 commit time | 64 |
| Gateway G0 | **38** (unchanged) |
| Gateway adversarial | **109** (unchanged) |
| Episode/commitment | 82 |
| Compaction | 93 |
| Consumers (new) | 65 |
| **Full suite** | **1442 passed** (1377 + 65). No existing test edited or weakened |

### Code changes outside the new module

All additive, and inert when no checkpoint store is set:
- **retrieval:** an optional `MemorySource.view` (the last field, default None), routed through `_projection`, `_claims` and `_last_sync`;
- **Gateway:** `checkpoints = None` by default; `_read` and `_scratch` consult a view first; `_scratch` returns the freshness input as a function;
- **compaction:** `checkpoint_fold`, plus the wrong-partition check.

**Not changed:** journal v1.1, `commit_time`, K1–K10, commit, the Claim Gate, the Context Compiler, the Evidence Boundary, the identity layer.
