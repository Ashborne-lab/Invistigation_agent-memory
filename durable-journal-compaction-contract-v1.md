# Durable Journal Compaction and Checkpoint Contract v1 (technology-neutral)

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. An additive companion to the Durable Journal contract v1.1 plus Amendment A1. **No K1–K10, S1–S5, O1–O4 or served-prefix rule changes.**

**Labels:** [PROVEN], [DECISION], [CONTRACT_GAP], [OWNER], [INFERENCE].

**Executable form:** `memory-prototype/memory_core/journal_compaction/` and `memory-prototype/tests/test_journal_compaction.py`.

**One-line statement:** a checkpoint is an acceleration structure, not a second source of truth. The Journal's durable fact stream stays the only authority.

---

## Part 0. Feasibility gate

**The question:** can a partition's rebuild resume from a stored state at a closed position c, and give exactly what a full replay gives, without changing any rule?

**What the rebuild is.**
- `reconstruct` (`durable_journal/__init__.py`) orders a partition's claim-projected entries (`PROJECTED_KINDS`) together with **all** visible policy publications. The order is (time, entries before publications, position).
- It then calls `state.project_subject(..., incremental=False)`, which runs `slot_versions`.
- That is a **left fold over evaluation points**, and its state is finite and explicit:

| Fold state | Why it must be carried | Source |
|---|---|---|
| Claim map (content plus lifecycle state) | Every later point evaluates it | `state._replay` |
| Retractions seen so far | **LA-9:** a retraction also ends claims committed later (`commit._insert`) | `commit/__init__.py:259-267` |
| Pending future validity boundaries | They are evaluation points of their own (S-2) | `slot_versions` heap |
| Versions and the last semantic signature per slot | `state_version` = the number of signature changes | `slot_versions` |
| Version in force per predicate | O3: points are evaluated under the policy in force | `slot_versions.in_force` |
| Version trace | History stability (no ABA) | `trace` |
| Max `synced_at` per predicate | Freshness = the latest recorded sync (C-C) | `commit.last_sync_from` |
| `claims_version` | Counted over the claim entries | `project_subject` |
| Commitment events (set) / latest episode generations | A1 projections | `episode_commitment` |
| Erased flag | Any erasure at or before r gives ERASED | `reconstruct` |

**What can be preserved, item by item:**

| Item | Preserved? | Basis |
|---|---|---|
| Exact current state at r ≥ c | Yes [PROVEN] | Fold + suffix (c, r] = the full fold. 8 random histories × 2 stores × every entry, publication and boundary instant |
| Historical results | Yes, for every r. **No fact is deleted**, and positions r < c are served by full replay (§7) | — |
| `state_version` and trace | Yes [PROVEN] | Carried in the fold |
| Served-prefix immutability | Yes | c is a **closed** position (§5). The checkpoint adds no entry and moves no position |
| Causal positions | Unchanged | Served r is assigned exactly as before. A checkpoint only computes what is served at that r |
| Recorded commit outcomes | Unchanged | They stay journal entries. Idempotency still sees the whole partition (§10) |
| Policy publication history | Yes, with one hazard: a late publication on the explicit store (§4) | The policy-log position is checked; on mismatch, full replay |
| Erasure / retraction | Yes [PROVEN] | §6 |
| Commitment-event / episode-summary projections | Yes [PROVEN] | §8, §9 |
| Deterministic rebuild | Yes [PROVEN] | §4 |

**Stop conditions:**

| Stop condition | Status |
|---|---|
| A change to K1–K10 | **Not needed** |
| A new truth source | **Not needed for checkpoints.** It **would** be needed by any physical deletion of facts (§7) |
| Cross-partition coordination | **Not needed** |
| An owner value | Needed **only** for physical truncation of history (§7), which v1 does not do |

**Gate: FEASIBLE** for checkpoint plus retained suffix.

## Part 1. Semantic model

| Category | What it is | Authority |
|---|---|---|
| **1. Authoritative journal facts** | The partition entries, the policy log, policy content, and the sealed vault content that entries reference | **The only authority** |
| **2. Derived checkpoint state** | The rebuild fold of one partition at a closed position c | **None.** An acceleration structure. It is never a journal entry (no commit time, no `idem`), and `reconstruct` never reads it |
| **3. Retained historical suffix** | The facts after c | Authority (they are facts) |
| **4. Compacted / deleted obsolete facts** | **None in v1** | — |

**v1 "compaction" retires superseded checkpoints (derived data). It deletes no fact.**

**[DECISION] A checkpoint is an acceleration structure, not a second source of truth.**
- Deleting every checkpoint changes no result.
- A rejected checkpoint changes no result.
- A checkpoint is used only after validation.

## Part 2. Candidate designs

| | A: no compaction | B: per-partition checkpoint + retained suffix | C: per-key compaction | D: hybrid (checkpoint, bounded suffix, collapsed audit) |
|---|---|---|---|---|
| **Replay cost** | O(history) | O(suffix) after the checkpoint [PROVEN: only the suffix is read] | O(live keys), but the collapse must reproduce versions and trace | O(suffix) |
| **Write amplification** | None | One checkpoint write per creation (derived) | **Rewrites facts** | Checkpoint plus collapse rewrites |
| **Read cost** | Full | Checkpoint + suffix | Collapsed facts | Checkpoint + suffix |
| **History semantics** | Full | **Full** (facts kept) | **Lost below the collapse.** Served history changes, which breaks SPI | Lost below the bound |
| **`state_version` / trace** | Exact | Exact (carried) | Must be re-encoded as synthetic facts: a **new truth** | Same problem as C |
| **Policy history** | Exact | Exact, with policy-position validation | Collapsed facts must keep their O3 stamps; re-evaluation can drift | Same |
| **Retractions (LA-9)** | Exact | Carried | A collapsed retraction must still end later claims, so it cannot be dropped | Same |
| **Erasure** | Crypto-shred | Crypto-shred covers checkpoints (sealed under the subject key) | Same, if sealed | Same |
| **Commitment events** | Exact | Carried as a set | The projection is a set function ordered by business time, so events cannot collapse to heads (expiry is evaluated at read) | Same |
| **Episode summaries** | Exact | Latest kept, history retained | Superseded generations could be dropped: a history-retention decision | Same |
| **Duplicate outcomes** | Exact | Exact (entries retained) | **Idempotency identities and outcomes must survive any collapse** | Same |
| **Causal positions** | Unchanged | Unchanged | Positions below the collapse disappear | Same |
| **Crash recovery** | — | A torn or missing checkpoint → full replay | A crash mid-rewrite risks fact loss | Same risk |
| **Concurrent append** | — | Creation at a closed position | A rewrite must exclude concurrent appends | Same |
| **Checkpoint creation / validation** | — | Defined (§1, §4) | — | Defined |
| **Corruption recovery** | — | Rebuild from facts | Facts were rewritten, so a corrupt collapse **is** truth loss | Same |
| **Hot partition** | Grows | Checkpoint only the hot partition | — | — |
| **Storage growth** | Unbounded (bounded only by crypto-shred) | **Unbounded** (facts kept) | Bounded | Bounded |
| **Operational complexity** | Lowest | Low | High | Highest |

C and D (and B with truncation) **delete or rewrite facts**. Each of them turns derived state into the only record of the removed prefix (a new authority). Each also changes served history below the cut (SPI), and each needs an owner retention boundary. **Under the existing semantics they are not admissible without owner decisions** (§7, Part 15 of the report).

## Part 3. Chosen architecture

**[DECISION] B: a per-subject partition checkpoint plus the immutable retained suffix. Checkpoints are derived accelerators. No fact is deleted.**

**Why B and not another design:**
- It is the only candidate that keeps every proven property **exactly**: SPI, history stability, recorded outcomes and erasure.
- It needs no owner value.
- It meets the replay-cost goal for many agents, many customers, long-lived memory and bounded recovery:
  - recovery cost is checkpoint plus suffix, independent of total history age, given a checkpoint cadence;
  - partitions checkpoint independently.

**What B does not meet:** the **history-size** half of the objective. Storage growth stays unbounded, except through crypto-shred. Bounding it needs the owner decisions in §7.

---

## 1. Checkpoint identity

| Field | Meaning |
|---|---|
| `partition` | The subject |
| `covered_at` (c) | A **closed** position of the partition (a served r). It is a journal position, not a wall-clock timestamp |
| `covered_count` (n) | The number of partition entries (all kinds) with commit time ≤ c. Under O1 they form a prefix |
| `tail` | (`idem`, `at`) of entry n−1, which anchors the covered prefix |
| `policy_position` | Publications with T ≤ c, as a count plus a digest of (predicate, version, T): the policy context |
| `contract` | `journal-compaction-v1`, the schema and contract version |
| `state_signature` | A canonical digest of the derived fold (identity). The same facts and c give the same signature [PROVEN] |
| `blob_digest` | Integrity of the sealed payload |
| `created_at` | Creation metadata |
| `ref` | The sealed payload's reference, under the **subject key** |

The index holds no personal content. The payload is sealed in the subject's crypto-shred domain.

## 2. Coverage

`checkpoint_at = c` means: **the exact state of the partition's rebuild fold after every evaluation point with time ≤ c.** Those points are:
- the partition entries with commit time ≤ c;
- every publication with T ≤ c;
- every validity-boundary instant ≤ c.

At equal instants, entries come before publications (O3), and boundaries come before entries at the same time (S-2).

c must be **closed** when the checkpoint is created. `create` takes the served position of a current read (K5–K7), so no later append can land at or before c (S1).

## 3. Recovery

```text
rebuild(subject, r) = advance(checkpoint(c), durable suffix (c, r])   for r ≥ c
                    = full replay(subject, r)                        [PROVEN]
```

**The suffix** consists of:
- partition entries from position n, with commit time ≤ r;
- publications with c < T ≤ r.

They are evaluated in the same order as `evaluation_order`. Erasure, unreadable payloads and lifecycle for non-live claims are handled exactly as `reconstruct` handles them.

**Proof:**
- The fold is a left fold over an order that the suffix preserves.
- Points at or before c are all inside the checkpoint, by closure plus validation.
- The final resolution at r uses only the folded state and the policies visible at r.
- **Executable proof:**
  - 8 random histories (observations, typed commands, retractions, lifecycle, syncs, breaking and non-breaking publications, future validity, a merge) × 2 stores × checkpoints at the empty partition and at every entry, publication and boundary instant × several read positions;
  - plus targeted cases (§4–§9);
  - plus a 30-seed scratch run: 110,972 comparisons, 0 mismatches.

**Only the suffix is read.** A guarded partition shows that `rebuild` reads only the tail anchor and positions ≥ n [PROVEN].

**r < c:** a checkpoint newer than the read is never used [PROVEN]. Full replay serves it.

## 4. Checkpoint validation

A checkpoint is used only if **every** check passes. On any failure the read **rebuilds from the durable facts** and the checkpoint is **marked unusable**. A corrupt or incompatible checkpoint never alters truth [PROVEN].

| Check | Rejection | Detects |
|---|---|---|
| Contract version | `contract_version` | Incompatible schema |
| Payload readable | `unreadable` | Key destroyed (crypto-shred), never written |
| Payload digest | `integrity` | Torn write, corrupted bytes |
| Prefix length ≥ n | `prefix_missing` | A rolled-back or shorter history |
| Tail anchor | `prefix_mismatch` | A different history of the same length |
| Entry n is strictly after c | `suffix_not_after_c` | An entry at or before c that landed later, because c was not truly closed |
| Policy-log position | `policy_log_changed` | **A late publication at T ≤ c.** On the explicit store, a predicate whose log this partition never closed can receive one (`ExplicitFrontierStore._assign_publication` only orders after that predicate's own frontier). The implied store's global time service places it after c |
| State signature recomputed from the payload | `state_signature` | A payload replaced together with its digest |

**Creation refusals (fail-safe):**
- A fold that would consult **read-time** policy content (a claim whose predicate had no publication in force) is never checkpointed (`UNSUPPORTED`). Such content differs between creation and use.
- Nothing is sealed under a destroyed key (`REJECTED key_destroyed`).

## 5. Concurrent writes

- **Creation:** a current read closes the partition and its predicates through c. Then the fold is built from facts with time ≤ c only.
  - An append racing the creation gets a later time (S1) and belongs to the suffix [PROVEN: begin_read / append / end_read].
  - A typed command right after a checkpoint uses the checkpoint-derived `state_version` as a valid OCC base, and a stale base still gets STATE_CONFLICT [PROVEN].
- **No lost writes:** creation writes no entry.
- **No duplicated writes:** no entry is replayed twice. The suffix starts exactly at n, and a mutant that starts at n−1 is caught.
- **No replay divergence:** §3.
- **No served-position regression:** c ≤ every later served r, and a checkpoint is never used for r < c.
- **Reads in flight are unchanged** across a creation [PROVEN].
- **Multiple writers on other partitions are unaffected.** No entry is written anywhere [PROVEN].

## 6. Erasure and retraction

| Situation | Behaviour |
|---|---|
| A checkpoint made **before** erasure | Its payload is sealed under the subject key, so key destruction makes it unreadable. The read rejects it, and the full replay returns ERASED. **The secret is absent from the facts, the index and the rejection log** [PROVEN] |
| An erasure entry in the suffix | ERASED, even before key destruction (as `reconstruct`) [PROVEN] |
| A checkpoint made **after** erasure (key not yet destroyed) | The fold is ERASED with **no content** [PROVEN] |
| A destroyed key without an erasure entry | The checkpoint is unreadable; full replay [PROVEN] |
| Retraction before c, matching claim committed after c (LA-9) | Ended, because retractions are carried [PROVEN] |
| Lifecycle, invalidation, policy migration (REVALIDATION_REQUIRED, SUPERSEDED_BY_POLICY) | Carried in the claim map, or evaluated from carried state [PROVEN through the property corpus] |

**Nothing is collapsed.** Retractions, lifecycle entries, provenance (sealed records), erasure entries and policy publications all remain facts. In particular a retraction can never be dropped: under LA-9 it must still end matching claims committed after it.

## 7. Historical reads

| Class | Served from | Note |
|---|---|---|
| **Current-state acceleration** | Checkpoint + suffix | This contract |
| **Historical truth** (as-of reads at any r, and the rebuilt journal view used by `search_history`) | **Full replay of the retained facts** | Never served from a checkpoint. The journal view is not reconstructible from a fold |
| **Audit / history retention** | The retained facts | **Unchanged: v1 deletes nothing** |

**Physical truncation of the covered prefix is NOT part of v1.** It would need two decisions:
1. **[OWNER] Legal / Product:** a history-retention boundary, below which as-of reads, history and audit become unavailable. Compaction must never silently destroy a promised history class.
2. **[OWNER] Contract owner:** acceptance of a **base snapshot as a fact**. After truncation, the checkpoint at the boundary would be the only record of the prefix: a new authority. That is excluded today.

**If both are ever decided, at minimum these must remain:**
- idempotency identities and outcome entries, so duplicates still return the original outcome;
- erasure entries;
- the policy log;
- the tail anchor.

## 8. Commitment events

- The checkpoint carries the **set** of readable commitment events at or before c, in partition order.
- The suffix adds the events in (c, r].
- The unchanged `commitments.project` receives exactly the events that a full replay gives it at the same served r, with expiry evaluated at r [PROVEN, including an event with an earlier business time committed after c].
- Heads are **not** checkpointed. The projection is a set function ordered by business time, with read-time expiry.

## 9. Episode summaries

- The checkpoint carries the **latest generation per episode** at c. Suffix generations replace it in partition order, so the newest wins [PROVEN].
- Identity is unchanged (A1).
- A retry with the same inputs after a checkpoint still returns the recorded generation, and **nothing is regenerated** [PROVEN].
- `summary_status` is **not** stored. It is derived at read from the generation and the read-time inputs, as in A1 [PROVEN].

## 10. Idempotency and outcomes

Outcome and intent entries and every `idem` stay in the partition. Duplicate detection is unchanged (K8: before time, against the partition).

| Case | Result [PROVEN, both stores] |
|---|---|
| A duplicate before a checkpoint, and after a checkpoint plus a Gateway restart | The same DUPLICATE outcome and the same commit time |
| A different-content reuse of a command id after a checkpoint | COMMAND_ID_REUSED |
| The same command id on another subject | An independent APPENDED |
| A journal-level duplicate after a checkpoint | The original time |

## 11. New record types and the claim projection (explicit rule)

**[Normative] `commitment_event` and `episode_summary` are never claim-projection evaluation points.**
- They are not in `PROJECTED_KINDS`.
- `evaluation_order` and the checkpoint suffix never yield them.
- A test asserts this positively on both stores; it no longer relies on the crash observed in A1.
- The claim projection is unchanged.

## 12. Scalability properties (architectural; no benchmark)

| Property | Status |
|---|---|
| After compaction, replay cost depends on the checkpoint + suffix, not on the whole history | [PROVEN] (guarded partition) |
| Partitions compact independently. One hot customer needs no checkpoint of any other | [PROVEN] (no entry written; other partitions untouched) |
| No global checkpoint transaction | [PROVEN]: one partition per checkpoint, with no cross-partition step |
| No global serialization point **of its own** | [INFERENCE, qualified]. Creation is a current read, so it costs exactly what a current read costs. **Explicit store:** it writes the partition frontier and the frontiers of that partition's predicate logs, which are shared with other subjects. **Implied store:** it draws from the global time service. Option, not built: create at an already-closed position (stale-tolerant), with no write |
| Current-state recovery can be bounded independently of total history age | [INFERENCE], given a checkpoint cadence. The cadence is an operational parameter with no semantic effect, and v1 sets no value |
| Validation reads the policy log's position | O(publications ≤ c), independent of partition history. [INFERENCE] Per-predicate log positions would make this O(predicates) |
| Checkpoint size | **[CONTRACT_GAP]** It grows with the claim map, the version trace, the retractions and the commitment events. These are derived history needed for exact equivalence. A bounded checkpoint would need the trace served from a separate derived history structure |
| Storage growth | **Unbounded in v1** (facts kept; crypto-shred aside). Bounding it is the §7 owner decisions |
| Idempotency lookup | The reference scans the partition. **Technology requirement:** an `idem` index per partition |
| Historical semantics separated from current-state acceleration | [DECISION] §7 |

## 13. Integration

- **Gateway, Claim Gate, commit, typed retrieval, Context Compiler, Evidence Boundary and identity layer: unchanged.** The journal remains the sole authority.
- **[CONTRACT_GAP] The consumers cannot use checkpoints yet.**
  - The Gateway's reads and its write-path scratch store rebuild from `reconstruct(...).journal` (`gateway/__init__.py:220-221, 311-313`).
  - Retrieval projects from that journal view (`MemorySource.journal`).
  - A checkpoint yields state, trace, policies, the claim map, commitment events and generations, but not the journal view.
  - Using checkpoints in the Gateway therefore needs a consumer interface that accepts projection state. Modifying those components is out of scope here.
  - Until then, the consumers observe exactly the same results through full replay.

## 14. Technology-neutral storage requirements

1. Positional range reads of a partition from position n, plus a positional read of entry n−1 (the tail anchor).
2. A per-partition `idem` index (duplicate detection without a scan).
3. Sealed derived payloads in the subject key's crypto-shred domain, with deletion of a derived payload (retirement).
4. A position for the policy log (count or digest, or per-predicate versions).
5. Atomic or detectably-torn checkpoint writes. A torn write is caught by the digest.

## 15. Owner decisions and contract gaps

| Item | Kind | Owner |
|---|---|---|
| A history-retention boundary (as-of, history and audit availability) | [OWNER] | Legal / Product |
| A base snapshot as a fact (needed for any truncation) | [OWNER] | Contract owner |
| A consumer interface for projection state (Gateway, retrieval) | [CONTRACT_GAP] | Engineering, through a future Gateway/retrieval contract change |
| A bounded checkpoint size (trace held separately) | [CONTRACT_GAP] | Engineering |
| Checkpoint cadence | Operational parameter (no semantic effect) | — |
