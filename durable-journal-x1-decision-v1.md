# Durable Journal X-1 Decision v1: commit-time ownership, O4 and R-READ

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Contract-owner decision for the durable journal. Test-only executable proof. No storage technology is selected and no production system is touched.

**Resolves:** X-1 in `storage-technology-evaluation-v1.md` §5 (CONTRACT_GAP).

**Executable proof:**
- `memory-prototype/memory_core/commit_time/__init__.py`: a new, test-only model;
- `memory-prototype/tests/test_x1_commit_time.py`: **64 tests**.

**Full suite: 969 / 969** (the 905 baseline plus 64). No existing module or test was changed.

**Labels:** [PROVEN] (by test or mutation), [INFERENCE], [OWNER], [STATED] (a normative requirement already in an architecture document), [CONTRACT_GAP].

---

## The answer

> **Who owns commit time?** The **journal layer**. It assigns the commit time of every entry (`at`) and every policy publication (`T`) inside the commit step. A writer, gate, agent or caller **never** supplies it. A store may *supply the value* (for example, its own commit timestamp) only as an implementation of the journal's obligations below. It never defines them.
>
> **What does commit time mean?** OLBrain's **knowledge time**: the instant at which OLBrain accepted the fact, on the same physical time axis as valid time. It is not observation time and not valid time. It is not the ordering primitive on its own: the ordering primitive is a **position in a source's evaluation order** (time, then entries before publications, then position within the partition).
>
> **What enforces O4 and R-READ?** The **journal layer**, through **closed frontiers**: one durable, monotone frontier per source of evaluation points (each subject partition, each predicate's policy log). A prefix of a source may be consumed only once the source is closed through it. Every fact acknowledged from that source afterwards is placed **strictly after** the frontier.
>
> Storage provides only per-source primitives: an atomic conditional append against that source's frontier, frontiers that survive crashes (stored explicitly or implied by commit order), and durability before acknowledgement. **No global order and no multi-subject transaction.**
>
> Stale-tolerant reads need no write. A **current** read is served at r = max(clock, the caller's causal token) and must close its partition through r **before** it reads. That closure is a write where the frontier is stored explicitly, and free where the store's commit order implies it.

---

## 1. Problem statement

The contract states O4 ("a publication with time T is visible to every append and every read at a time ≥ T") and R-READ ("no acknowledged entry is ever dated at or before a read already served"). It never says **who assigns** the times those rules compare. The v1 interface accepts a caller-supplied `at` and `T` and enforces only:
- O1 within one partition;
- O2 within one predicate's log.

Two probes in the storage evaluation showed the consequence [PROVEN]. Both behaved the same on the in-memory reference journal and on the Firestore emulator:
- **P4:** a publication back-dated before an already-acknowledged entry was accepted.
- **P3:** an entry dated before an already-served read was accepted.

The suite passed only because its driver publishes first and reads last. The two readings of the gap (store-assigned versus writer-assigned time) put the requirement in different layers, so Infrastructure could not evaluate C-5 rows C1–C3, B3 and B5.

## 2. Existing evidence

| # | Evidence | Label |
|---|---|---|
| E1 | Architecture contract §2: valid time and "system / knowledge time — `observed_at`, `committed_at`, `invalidated_at` — when **OLBrain** observed, accepted, or invalidated the claim. These axes MUST NOT be collapsed" | [STATED] |
| E2 | Architecture contract §8: "Every committed evidence and state event **receives** an ordered source position"; the abstraction is `source_partition + monotonic_position`; "Wall-clock freshness MUST NOT substitute for source-position freshness"; a projection's `consumed_through_position` "MUST represent the highest **CONTIGUOUS** committed source position… fully incorporated" | [STATED] |
| E3 | Architecture contract §7: `STATE_CONFLICT` is a typed semantic outcome, returned to the agent and never retried by infrastructure. Transient transaction failures may be retried | [STATED] |
| E4 | Architecture contract §2: `state_version` "MAY advance with no agent mutation". §2, Retroactive claims: "Historical truth MAY be revised… Decision history MUST NOT be rewritten" | [STATED] |
| E5 | Journal contract §B: history stability, i.e. reads at increasing r extend one another (no ABA, no rewind) | [PROVEN] |
| E6 | Journal contract §B: placing a publication at the subject's next own entry ("adoption") gives ABA (`break_publication_placement_by_adoption`) | [PROVEN] |
| E7 | N-1 (engineering closure): `state_version` rewound 2 → 0 when history was replayed under the current policy. N-5 (journal contract): the same flaw in retrieval. Both were fixed by evaluating each point under the policy in force at it | [PROVEN] |
| E8 | `state/__init__.py:178`: a validity boundary becomes an evaluation point only if it lies **after the claim's commit time**. Evaluation therefore lives on the knowledge axis but is ordered against valid-time instants | [PROVEN] (S-2 tests) |
| E9 | `temporal/__init__.py:19`: a claim with `committed_at > knowledge cutoff` is excluded. The record's `committed_at` must therefore equal the entry's commit time | Source |
| E10 | `integration/__init__.py:92`: `Pipeline.propose` computes the OCC "actual version" at the **caller-supplied `now`** | Source |
| E11 | `PublishReport` carries only (predicate, version, cardinality_changed). Publishing reads no other subject | Source |
| E12 | Storage evaluation P3/P4 (above); P5: a per-partition read watermark fixes R-READ only, at the cost of a write on every read | [PROVEN] (emulator / in-memory) |

E1 and E2 already settle **ownership** at the architecture level: commit time is an act of OLBrain, and positions are *received* at commit. The journal contract had not carried that rule down into its interface. That missing step **is** the gap.

## 3. Semantic invariant

### 3.1 Definitions

- **Source:** a stream of evaluation points with its own order. Sources are:
  - each subject **partition**: entries in (commit time, position) order;
  - each predicate's **policy log**: publications in T order.
  - Validity-boundary points are not a source. They are derived deterministically from entries already in the partition (E8).
- **Evaluation order** of subject s at read time r: all of s's points with time ≤ r, ordered by (time, entries before publications, position). This is `evaluation_order`, unchanged.
- **Consumer:** an act that uses a prefix of a source and is **externally observable or binding**:

| Consumer | Prefix consumed | Why it binds |
|---|---|---|
| A **served read** at r, including a read from a lagging view | Partition s through r **inclusive**. The policy logs of the predicates it evaluates through r **inclusive** (a read at r includes publications at T = r) | The caller acts on the result. OCC `expected_version` is taken from it |

**Two read classes:**
- A **current** read (current state, OCC base) uses r = max(journal clock, the caller's **causal token**: the time of its last acknowledged write or last served read). This mirrors the architecture contract §7 `causal_parent_position`.
- A **stale-tolerant** read (history, search, lagging views, historical as-of) is served at an already-closed frontier.
| An **acknowledged entry** at t (predicate p) | The policy log of p **strictly before** t (its O3 stamp). Its own partition up to itself (its commit-time OCC check) | Its admission decision and its OCC outcome are durable decisions, and decision history is never rewritten (E4) |

**Not consumers:**
- **Gate reads.** The commit step re-validates the stamp and OCC; a gate decision binds nothing until committed.
- **Publications.** They read no subject (E11).
- **Publication reports.** They are notifications derived from the projection, which stays the truth.
- **Internal rebuilds** at any r. They serve nothing.

### 3.2 The invariant: served-prefix immutability (SPI)

> **Once a prefix of a source has been consumed, every fact acknowledged from that source afterwards is placed, in evaluation order, after every point of that prefix.**

**Consequence** [INFERENCE, proof sketch; PROVEN by the tests in §11]:
- For every slot of every consumed read, the version history the consumer saw is exactly the history any later reconstruction gives at the same r.
- Membership, order and **interpretation** of the served points never change.

**Proof sketch:**
- A slot's history at r depends only on three things:
  - the partition's points with time ≤ r;
  - its predicates' publications with T ≤ r;
  - boundary instants of claims known before them (E8).
- Under SPI no later fact is placed among those points, so the set and order are unchanged.
- Each point's policy is the latest publication before it (O3). Under SPI none can be added, so the interpretation is unchanged.
- A later claim's boundary points sit at max(boundary, its own commit time), which is after the prefix.

**Necessity.**
- Any projected fact placed inside a consumed prefix *can* change a signature. Cases 1, 2, 3, 7 and 8 below construct one each [PROVEN].
- Whether a given late fact would change a signature cannot be known at commit time without re-evaluating every consumer. So the rule must constrain **placement**, not effect [INFERENCE].

### 3.3 What the earlier rules really are

| Rule | Instance of SPI for… |
|---|---|
| R-READ | Partition source vs served reads (membership) |
| O4 | Policy-log source vs acknowledged entries (stamps) and served reads (membership **and** interpretation) |
| O3 stamp + historical policy selection (N-1, N-5 fixes) | Interpretation of a point fixed at its own time, not re-read under a later policy |
| S-2 boundary points | Grouping and order of points fixed (two boundaries never merge across reads) |
| O1 | Partition source vs its own earlier entries (an entry consumes its partition up to itself) |

**O4 and R-READ are not independent.** They are the same invariant applied to the two kinds of source.

**Refinements of the candidate wording.** The brief proposed: "once an evaluation point has been externally acknowledged/served, no later acknowledged fact may be inserted into the semantic history before that point". The invariant above differs in four ways:
1. **Consumption, not only serving.** An acknowledged entry consumes the policy log through its stamp (Case 1 has no read at all).
2. **"At or before", made exact.** A read at r includes points at r, so later facts must be **strictly** after r (Case 3 break and the equal-time view break).
3. **Per source, not global.** No order between different subjects is implied.
4. **Interpretation is included.** N-1 changed no membership; it changed which policy a served point was evaluated under.

### 3.4 Why a caller-supplied timestamp is unsafe

Each item below is [PROVEN] by a break test.
- **Back-dated publication:** a back-dated publication invalidates an acknowledged entry's stamp (`break_case1…`).
- **Late entry:** a late entry lands inside a served read (`break_case2…`), including an entry at exactly the served time (`break_case3…`).
- **OCC evaluated at the caller's time:** it accepts a command against a version that an already-served read had moved past (`break_case7…`). That is the prototype's own `Pipeline.propose` pattern (E10).
- **Lagging views served at the caller's clock:** they serve a prefix that is not closed (`break_case8…`).
- **Retries with a fresh caller time:** they conflict with idempotency, because the same command arrives as different content. The journal model avoids this by deciding duplicates before any time exists (Case 6).

## 4. Candidate commit-time models

### 4.1 The five time concepts, separated

| Concept | Fields | Assigned by | Used for |
|---|---|---|---|
| **Observation time** | `observed_at`, `synced_at`, `effective_at`, evidence receipt times | The source or writer, as **payload** | Freshness (C-C), provenance, recency inside resolution |
| **Valid time** | `valid_from`, `valid_until` | The writer or gate, as **payload** | Truth in the modelled world; boundary instants |
| **Commit / knowledge time** | Entry `at` = record `committed_at`; publication `T` | **The journal** | Placement of points on the knowledge axis; knowledge-cutoff queries (E9) |
| **Logical position** | Position within a partition; version within a predicate's policy log; `idem` | **The journal** (positions); the writer (`idem` = logical command id) | Total order within a source when times are equal (O1 allows equality); idempotency |
| **Read position** (as-of token) | The served r, and the frontier it was served from | **The journal**, returned with every result | R-READ; OCC base; freshness labelling of lagging views |

**All five are needed. None may stand in for another:**
- **Commit time must be physical.** Boundary instants are valid-time instants that must be ordered against commit points (current state reads valid time at knowledge time; E8). Knowledge-cutoff queries are physical (E1).
- **Logical position must exist beside commit time.** Equal commit times are legal within a partition (O1).
- **The read position must be explicit.** Otherwise two implementations can serve "now" from different closures.
- `state_version` remains a **derived** counter. It is never a position (architecture contract §12 rule 1).

### 4.2 Models evaluated

| Id | Model |
|---|---|
| **M-W** | Writer-assigned `at` / `T` (the v1 interface as it stands) |
| **M-WB** | Writer-assigned, plus an upper-layer barrier per partition (the P5 read watermark) |
| **M-SL** | Store-assigned from a monotone clock **per source**, with no closure between sources (e.g. per-shard clocks, or `now()` per transaction) |
| **M-SG** | Store-assigned from **one** clock consistent with the store's serialization across **all** sources, with reads served at that clock ("interpretation A" done fully) |
| **M-L** | Pure logical: no physical commit time. Publications are placed by stamps and positions only |
| **M-J** | **Journal-assigned knowledge time plus closed frontiers per source** |

## 5. Adversarial analysis

✔ = the invariant holds; ✘ = violated. Test names are in `tests/test_x1_commit_time.py`.

| Case | M-W | M-WB | M-SL | M-SG | M-L | **M-J** |
|---|---|---|---|---|---|---|
| **1** Claim acknowledged at x; publication attempted dated before x | ✘ `break_case1[writer]` | ✘ `break_case1[writer+read_watermark]` | ✘ `break_case4_store_local…` (same pattern) | ✔ (T is later by construction) | n/a: no T; reduces to adoption, see Case 5 | ✔ `case1…`: T > x |
| **2** Read served at r; entry attempted before r | ✘ `break_case2…` | ✔ `read_watermark_alone_fixes_case2_only` (a write on every read) | ✔ only if reads use the same shard clock and are serialized with appends [INFERENCE] | ✔ | ✔ only with as-of tokens | ✔ `case2…`: at > r |
| **3** Entry and publication at the same time | ✘ when a read at that instant was served (`break_case3…`) | ✘ (Case 1 pattern) | ✘ (Case 1 pattern) | ✔ | n/a | ✔ `case3…`: the journal never assigns an entry and a publication of the same predicate the same time; the tie rule remains for determinism |
| **4** Two subjects concurrent with a publication, skewed clocks | ✘ property break | ✘ property break | ✘ property break | ✔ `global_serialization_consistent_clock…` | ✘ (adoption ABA, E6) | ✔ `case4…` (in-flight entry, stale stamp re-gated) plus `property_case4` (20 seeds, in-flight appends, views) |
| **5** Validity boundary between two reads, no new entry | ✔ | ✔ | ✔ | ✔ | **✘ [PROVEN for adoption placement, E6; INFERENCE for every logical scheme**: a valid-time instant cannot be ordered against points that have no time] | ✔ `case5…`. Not discriminating among the physical-time models |
| **6** Crash between logical commit and acknowledgement | ✘ a retry with a fresh time is refused as `idem_reused` | as M-W | ✔ if the store dedups | ✔ if the store dedups | ✔ | ✔ `case6…`: DUPLICATE returns the original time; a crash before durability leaves only a harmless frontier. **Break:** a frontier lost on crash lets a late entry in |
| **7** Stale writer retries after another change (OCC) | ✘ `break_case7…`: OCC at the caller's time accepts a stale command **and** rewrites a served read | ✔ for the read; OCC is still at the caller's time | ✘ if OCC runs outside the serialized write | ✔ if OCC runs in the serialized write | ✔ | ✔ `case7…`: STATE_CONFLICT at the journal time; `occ_must_run_inside_the_serialized_write[True]` (the False variant accepts a stale command) |
| **8** Read from a lagging view | ✘ `break_case8…served_at_the_callers_clock` | ✘ (the view has no barrier) | ✘ | ✔ only at the view's incorporated timestamp | ✔ with tokens | ✔ `case8…`: served at the incorporated frontier, r returned. **Break:** a frontier taken from the view's last entry time fails, because equal times are legal |

**Evidence level of the cells:**
- Cells naming a test are [PROVEN].
- The M-SG cells other than Case 4, the M-L cells other than Case 5, and the M-SL Case 2 cell are [INFERENCE].

**Verdicts:**
- **M-W, M-WB and M-SL are rejected** [PROVEN]. Each fails at least one case, and the random property finds violations for each (`break_property_rejected_interpretations…`, 3 modes).
  - M-WB fixes R-READ only, and it costs a write on every read. It cannot fix O4: closing a publication against entries in **other** partitions would need a cross-partition check.
- **M-L is rejected** [PROVEN for adoption placement; INFERENCE in general]. Validity boundaries need a time coordinate.
- **M-SG is conformant but not mandated.** It is M-J with a perfect clock: the journal never has to adjust a time (`global_serialization_consistent_clock_is_a_conformant_special_case`). Mandating it would require one store-wide, serialization-consistent clock across every partition and policy log. That is stronger than the contract needs, effectively a global timestamp order, and it would bias C-5 towards stores that natively provide it.
- **M-J is chosen** (§6).

## 6. Chosen model (M-J)

These clauses are normative. They replace the time-related parts of the v1 contract (see §8).

| # | Clause |
|---|---|
| **K1. Ownership** | The journal layer assigns `at` (entries) and `T` (publications) inside the commit step. Callers supply observation and valid times as payload only. A caller-supplied `at` or `T` is not part of the write interface |
| **K2. Meaning** | Commit time is OLBrain's knowledge time on the physical axis (E1). The stored record's `committed_at` **equals** the entry's `at`, because the record is built in the commit step after time assignment (E9) |
| **K3. Accuracy** | At assignment, `at ≥` the clock of the **node doing the assignment**. A **partition** frontier never runs ahead of the reading node's clock, or of an already-assigned time carried as a causal token. Cross-node clock skew therefore bounds how wrong knowledge time can be (the tolerance in §12). A **policy-log** frontier may run ahead (a lease), in which case a publication takes effect up to the lease length later than requested. Clock-error tolerance: [OWNER] (§12). History stability does **not** depend on clock accuracy. Whether a boundary activates at the correct real-world moment **does**. Break: `break_partition_frontier_ahead_of_the_clock…` (a knowledge-cutoff query misses a claim accepted long before) |
| **K4. Frontiers** | Every source (each partition s, each predicate's policy log p) has a closed frontier F that is **monotone** and **survives crashes**. F is either **stored explicitly** or **implied by commit order**: a store whose commit order assigns every later commit a later time, and whose reads see everything committed at or before their read position, has an implied frontier (M-SG). Either form is conformant. F is the journal-level counterpart of the architecture contract's contiguous `consumed_through_position` (E2) |
| **K5. Consumption requires closure** | A read at r may be served only if F(s) ≥ r and F(p) ≥ r for every predicate p it evaluates. An entry at t for predicate p may be acknowledged only if F(p) ≥ t. Closing (raising F) must be **durable before** the consumer is served or acknowledged. **Order of a read:** the partition is closed through r **before** its entries are read, or in the same serialized step. Each policy log is closed before its publications are read. Break: a snapshot taken before closure misses an append that completes during the read (`a_current_read_closes_its_partition_before_it_reads[True]`) |
| **K6. Placement after closure** | An entry is accepted only if `at > F(s)` **at the moment of its durable write**, checked atomically with the write. A rejection there (READ_CLOSED) is a transient failure: re-preparing assigns a later time, and OCC is re-evaluated. A publication receives `T > F(p)` and `T >` every earlier publication of p. An entry receives `at >` every earlier publication of its predicate. `at ≥` the partition's last entry time (O1) |
| **K7. Reads return their position** | Every served result carries the r it was served at. A **current** read (current state, OCC base) is served at r = max(clock, the caller's causal token), after closing through r (K5). This is required for read-your-writes across nodes (`current_read_with_the_callers_causal_token…`; break: without the token, a read misses its own acknowledged write) and for validity boundaries to activate. A **stale-tolerant** read is served at the existing closed frontier, with no write. A **lagging view** serves only at the frontier values it has fully incorporated, **never** at the time of its last replicated entry. A **historical** query (knowledge cutoff ≤ the frontier) needs no closure |
| **K8. Idempotency before time** | A duplicate is decided on the logical command identity **before** any time is assigned or any record is built. A DUPLICATE returns the **original** `at`. Storage-level idempotency (same idem, different content: reject) is unchanged, because storage receives fully timed entries |
| **K9. OCC at commit** | The OCC check (`expected_version`) and the O3 stamp check are evaluated at the journal-assigned `at`, inside the partition's serialized write. A stamp mismatch is STALE_POLICY_STAMP (the writer re-runs the gate). An OCC mismatch is STATE_CONFLICT (returned to the agent, never retried; E3) |
| **K10. Ties** | The tie rule (entries before publications at equal time) remains as an evaluation-order determinism rule. Under K6 the journal never assigns an entry and a publication **of the same predicate** the same time |

## 7. Enforcement boundary

**Choice: split responsibility, with the semantics owned by the journal layer.** The journal layer is a component of the memory core, below any Gateway. It may execute inside the store's transactions; the Gateway is not decided here.

| Layer | Guarantees | Does **not** guarantee |
|---|---|---|
| **Journal contract (journal layer)** | K1–K10: time assignment, frontier rules, consumption and placement rules, idempotency before time, OCC and stamp at commit, the r returned with reads | Physical durability or replication; how frontiers are stored |
| **Storage adapter** | **S1.** An atomic conditional write per source: compare against that source's durable frontier and last time, then write, in one serialized step. **S2.** A monotone frontier per source that survives crashes, stored explicitly or implied by commit order (K4). **S3.** Durable before acknowledgement (D1). **S4.** A read of one source that is consistent with, and ordered after, its closure (K5). **S5.** Idempotent, all-or-nothing single-partition group append (unchanged) | A global order; multi-source or multi-subject transactions (closure-then-write is **ordering**, not atomicity; a crash in between leaves only a harmless frontier, Case 6); a write per **stale-tolerant** read; a particular clock API |
| **Projection / read** | Evaluates only facts with time ≤ the served r; obtains r from the journal; never serves a current read beyond a closed frontier; labels lagging views by their r (as with Example 10's STALE label) | Choosing r on its own |
| **Writers / gate / agents** | Supply payload times and the gate's policy version; re-run the gate on STALE_POLICY_STAMP; handle STATE_CONFLICT | Choosing `at` or `T` |

**Why this boundary, not "storage" or "the journal alone":**
- **Not storage alone.** M-SL shows that "the store assigns" is ambiguous: per-source store clocks fail. M-SG, the only fully store-native reading, mandates a global clock property. The semantics must hold for any store, so they are stated once, in the journal contract.
- **Not the journal alone.** Atomic conditional writes, frontier durability and the durability of entries are physical properties that only a store can provide. They are stated as minimal, per-source primitives (S1–S5).
- **Why two implementations cannot disagree.** Each consumer is listed together with the exact prefix it consumes (§3.1). Strictness is fixed (K5, K6). Every read returns its r (K7). Commit time has one meaning and one owner (K1, K2).

## 8. Exact contract implications

The normative v1 contract file is **not edited in this phase**. The amendment below is complete and is the text to apply as v1.1.

| v1 clause | Replacement |
|---|---|
| Part 1, row "Read time r … Caller input" | "**Requested** read time: caller input. **Served** read position r: assigned by the journal under K5/K7 and returned with every result. The caller affects visibility only" |
| §A table, column "Causal / evaluation position": "Commit time" (each kind) | "Commit time **assigned by the journal** (K1, K2); position within the partition; O3 stamp **checked at the assigned time** (K9)" |
| §A append rules, row **Idempotency** | Add: "decided on the logical command identity **before** time assignment; a DUPLICATE returns the original commit time (K8)" |
| §A append rules, row **O1** | Unchanged, plus: "and `at > F(s)` checked atomically with the write (K6)" |
| §A append rules: new row **Closure** | K5 and K6 |
| §B **O3** | Unchanged definition. Add: "the stamp is checked at the journal-assigned time, inside the serialized write" |
| §B **O4** | "A publication receives T greater than its predicate log's frontier and than every earlier publication of the predicate. The frontier is raised to ≥ t before any entry at t of that predicate is acknowledged, and to ≥ r before any read at r evaluating that predicate is served (K5, K6). Hence a publication is never placed before a consumed point" |
| §B **R-READ** ([STATED] → normative) | "A read at r is served only if the partition is closed through r. Every entry acknowledged afterwards has `at > F(s) ≥ r`. Lagging views serve at their incorporated frontier (K7)" |
| §B: new paragraph **SPI** | §3.2, as the invariant behind history stability |
| §D, new rows | "Closure written, consumer not served or acknowledged: harmless. Consumer served before its closure is durable: forbidden (K5)." "Crash after a durable append, before acknowledgement: the retry gets DUPLICATE with the original time (K8)" |
| §E "Rebuild may consume … the read time" | "… the **served** read position r" |
| Results: requirements 1–3 | 1. "Per-partition total order; atomic conditional append against the partition frontier (S1, K6)". 2. "Ordered policy log with a durable frontier; causal stamps checked at the journal-assigned time (K5, K6, K9)". 3. "Closed reads: reads served at or below closed frontiers, r returned (K5, K7)" |

**Ambiguity removed:**
- who assigns time (the journal);
- what time means (knowledge time, the record's `committed_at`);
- which acts consume (§3.1);
- strictness ("> r", "> F");
- how views read;
- where OCC is evaluated;
- how retries keep their time.

**Existing tests: none obsolete, some reinterpreted:**

| Test(s) | Reinterpretation |
|---|---|
| Conformance tests that construct entries with explicit `at` (all of `test_durable_journal_conformance.py`, through `load`) | Now **storage-level** and import/replay tests. Storage receives fully timed entries, so they stay valid as written. `load` is the replay path, not a writer path |
| `commit_time_regression_is_rejected`, `idem_reused…`, `stale_policy_stamp_is_rejected` | Storage-level guards. Unchanged |
| `break_without_monotone_commit_time_a_late_write_rewrites_read_history` | Now a special case of Case 2 |
| `entry_and_publication_at_the_same_instant` | Still the tie rule (K10). The journal never produces such a tie for one predicate |
| Storage probes P3/P4 | Become the expected **rejections** of the rejected interpretations (they are the same scenarios as `break_case2` / `break_case1`) |
| `Pipeline.propose` OCC at caller `now` (E10) | The behaviour M-J rejects (Case 7). The integration harness is **not** changed in this phase; it remains a single-process prototype harness. A durable implementation must follow K9 |

## 9. Impact on the Firestore evaluation

Only evidence already in `storage-technology-evaluation-v1.md` is used.

- **Rows unblocked:**
  - C1 and B5 move from CONTRACT_GAP to evaluable against K5–K7 and S1–S4.
  - C3 ("store-assigned commit time") becomes "one conformant way to satisfy K6/K7", not a requirement.
- **S1 (conditional write per source).** This is a single transaction on the partition head (and on the predicate's log head for an append's closure). Production: documented serializable isolation (FS-TX). **The emulator cannot establish it**: P5-conc admitted a non-serializable interleaving. So **NEEDS_ENVIRONMENT**. The adapter's P5 watermark is the *closing read* variant of K7. It is no longer the only option, and it is not mandated.
- **Reads and writes.**
  - **Stale-tolerant reads** need no write (`as_of_reads_need_no_write…`).
  - **Current reads** need closure through r. With a stored frontier on the partition head, that is a write per current read, unless the frontier already covers r.
  - An implied frontier (snapshot reads bound to commit order) would avoid the write, but needs `at` to equal commit order, while the record must contain `at` before commit (K2). That variant is **[INFERENCE] and NEEDS_ENVIRONMENT**. It is not assumed.
- **Cost to measure (B3, C-cost):**
  - every append closes its predicate's log head through `at`, a write to a per-predicate document;
  - a lease amortises that write, but makes publications take effect up to the lease length later;
  - current reads write the partition head when it is stored explicitly. This is the largest cost to measure;
  - per-document write-rate guidance applies (FS-BP: "depends highly on the workload").
- **Unchanged:**
  - no global order;
  - no multi-subject transaction (closure, then write, is ordering only);
  - partitioned layout preserved.

## 10. Impact on the PostgreSQL evaluation

- **No reliance on `now()`.** K1/K6 require `at > F(s)`, `at ≥` the last time, and `at >` the last publication time, evaluated **under the partition's serialization**. A plausible realisation [INFERENCE] takes the value from `clock_timestamp()` under a `FOR UPDATE` lock on a per-partition head row, guarded by `greatest(...)` against clock steps. `now()` (transaction start, PG-TIME) is never commit order and is not used.
- **Design consequences.** These are not in the A7 design and are **NOT_SHOWN** until designed:
  - a journal table with a position;
  - a frontier column per partition head;
  - a policy-log table with a frontier per predicate (A7 §1 has no publication table).
- **Lagging replicas.** The A7 §7 rule (`gateway_ro` serves only lag-tolerant data, "never the slot for an OCC command") is compatible with K7. A replica serves at its replicated frontier, with r returned.
- **Reads and writes.** Stale-tolerant reads need no write; replicas serve them at their frontier. A current read needs closure through r. With a frontier column, that is an `UPDATE` (or a lock-taking read) per current read unless the frontier already covers r. Per-predicate log rows are contention points, with the same lease trade-off as Firestore.
- **No global order and no multi-subject transaction.** A7 §5's lock on the full member set still exceeds the contract and remains a non-requirement.
- **Status:** everything executable is still **NEEDS_ENVIRONMENT**.

### Bias check

| Question | Answer |
|---|---|
| Technology-neutral? | Yes. S1–S5 are per-source primitives. Neither candidate's native clock is required. M-SG is permitted, not mandated |
| Can Firestore satisfy it without emulator-only assumptions? | It is plausible from documented serializable transactions. **Unproven**: NEEDS_ENVIRONMENT (P5-conc) |
| Can PostgreSQL satisfy it without `now()` as order? | Plausible with row locks and a guarded clock [INFERENCE]. NEEDS_ENVIRONMENT |
| Does either candidate need a mechanism that belongs in the journal layer? | Yes, and it is placed there: time assignment, frontiers and consumption rules are journal semantics. Stores supply S1–S5 only |
| Write on every read? | **Stale-tolerant reads: no** [PROVEN in the model]. **Current reads: closure through r is required** [PROVEN necessary: the causal-token and read-order breaks]. It is a write for explicitly stored frontiers and free for frontiers implied by commit order [INFERENCE]. This is a real cost difference between implementations, to be measured. It is not a preference |
| Global total order? | No. Frontiers are per source. Times are compared only within one subject's evaluation order (its partition plus its predicates' logs) |
| Multi-subject transactions? | No. An append touches its partition and its predicate's log by **ordering** (close, then write), never by atomicity. The crash case is harmless [PROVEN, Case 6] |
| Conflict with partitioned journals? | No. The model runs on `PartitionedJournal` as storage |

## 11. Required tests

**Proof of the decision:** `tests/test_x1_commit_time.py`, 64 tests, all passing.

| Group | Tests |
|---|---|
| Back-dated publication (Case 1) | Chosen: 1. Breaks: writer, writer + read watermark |
| Late back-dated entry (Case 2) | Chosen: 1. Break: writer. The watermark-only variant: fixes Case 2 only |
| Equal time (Case 3) | Chosen: 1 (no same-predicate ties; read at T). Break: an equal-time entry after a served read |
| Concurrent subjects and policy (Case 4) | Deterministic: 1 (in-flight entry, stale stamp re-gated). Property: 20 seeds (chosen). Break: store-local clocks. Break property: writer, writer + watermark, store-local. Conformant special case: global clock |
| Read closure | In-flight append refused by an overtaking closure, and its break. A current read closes before it reads, and its break (snapshot first). As-of reads need no write. A read closes only the predicates it evaluates |
| Read-your-writes | A current read with the caller's causal token sees its own write across skewed nodes; break: without the token it does not |
| Retries and crash (Case 6) | DUPLICATE with the original time; crash before durability; break: volatile frontier |
| OCC (Case 7) | STATE_CONFLICT at the journal time; break: OCC at the caller's time; OCC inside versus outside the serialized write (2) |
| Lagging view (Case 8) | Served at the incorporated frontier; breaks: served at the caller's clock; frontier taken from the last entry time |
| Boundary between reads (Case 5) | 1 (not discriminating; documented) |
| Commit-time meaning | Break: a partition frontier ahead of the clock misstates knowledge time |
| History stability and `state_version` monotonicity | Property: 10 seeds; the served-prefix check runs in every test |

**Mutation run.** Each chosen rule was removed from the model in turn. Every removal is caught, so each rule is necessary [PROVEN].

| Rule removed | Tests failing |
|---|---|
| Entry after partition frontier | 4 |
| Entry after last publication | 1 |
| Append closes the policy log | 17 |
| Publication after the policy frontier | 19 |
| Read closes the partition | 18 |
| Read closes the policy logs | 8 |
| Write-time closure check | 7 |
| OCC at write | 2 |
| Idempotency before time | 1 |
| View serves at its frontier | 15 |
| Close before snapshot | 1 |
| Causal token | 1 |

The model was restored byte-identical afterwards.

**Minimum additions for any store adapter.** These are to be run by Infrastructure; they are not built here:
- an atomic conditional append against a durable partition frontier under concurrent closing reads (the P5-conc pattern);
- the publish versus append contention under K6;
- frontier durability across a crash;
- an as-of read from a replica at its incorporated frontier.

## 12. Remaining owner decisions

None of these changes who assigns time or which layer enforces O4/R-READ. Each is a parameter of a mechanism.

| Decision | Owner |
|---|---|
| Policy-log lease length, i.e. whether and by how much a publication may take effect after it is requested. A lease amortises policy-log closure for appends and reads. It cannot amortise **partition** closure for current reads (K3 forbids partition frontiers ahead of the clock) | [OWNER] Product / policy owners, with Infrastructure |
| Whether stored-frontier implementations accept one partition-head write per current read, or must provide a frontier implied by commit order | [OWNER] Infrastructure (C-5 cost input). The rule is unchanged either way |
| The journal clock source and its error tolerance (K3: accuracy of boundary activation and of knowledge-cutoff queries) | [OWNER] Infrastructure |
| Which retrieval types may be served as-of from lagging views, and how they are labelled | [OWNER] Product. The architecture contract's Example 10 already labels STALE |
| Retry budget for transient READ_CLOSED / COMMIT_TIME_REGRESSED (architecture contract §7 already allows retrying transient failures) | [OWNER] Infrastructure |
| Whether the integration harness (`Pipeline`) is migrated to K9 now or when the durable journal is built | Engineering sequencing; not blocking |

## 13. Final status

- **X-1 is resolved.** The CONTRACT_GAP is removed.
  - The journal owns commit time.
  - Commit time is OLBrain's knowledge time (the record's `committed_at`).
  - O4 and R-READ are one invariant, served-prefix immutability. The journal layer enforces it through durable per-source closed frontiers, on top of per-source storage primitives.
- **The infrastructure storage evaluation can resume** against one contract:
  - K1–K10 for the semantics;
  - S1–S5 for storage;
  - the §11 adapter additions for executable checks.
- **Normative contract:** the amendment text is ready (§8). The v1 file has not been edited.
- **Baseline:** 905/905 before. **969/969 after** (the 64 new tests; nothing weakened, skipped or changed).

---

## Evidence-scope addendum (2026-10-04, `target-architecture-next-decision-v5.md`)

The decisions above are unchanged. Only the scope of some [PROVEN] citations is corrected, now that the guarantees are tested on two storage forms (contract v1.1: explicit and implied closed positions).

| Citation | Correction |
|---|---|
| K9, `occ_must_run_inside_the_serialized_write` | Explicit-form evidence. **K9 with a write landing in flight is now [PROVEN] for both forms** by `test_durable_storage_boundary.py::test_k9_a_stale_typed_command_is_never_acknowledged_when_its_slot_changes_in_flight` (both stores, both orders), with breaks on both. On the implied store the in-write OCC check is necessary on its own: removing it fails the common test there too |
| K7, causal token (`current_read_with_the_callers_causal_token…`, `break_…without_a_causal_token…`) | The token is **necessary when commit times are assigned by skewed per-node clocks**, not universally. A global time sequence (the implied form) gives read-your-writes without one. Read-your-writes itself is [PROVEN] for both forms (`s4_a_current_read_with_the_callers_causal_token…`) |
| K7, as-of reads "need no write" (`as_of_reads_need_no_write…`) | They need **no data-store write**. The implied form draws from its time service instead (`current_read_closure_cost_is_measurable_in_both_forms`) |
| §5 table, M-J cells for Cases 3, 4 and 8 | Explicit-form evidence. Cases 3 and 8 are [PROVEN] for both forms by the boundary suite. In Case 4, accepting the in-flight entry is permitted behaviour, not a guarantee; the implied form refuses it transiently |
