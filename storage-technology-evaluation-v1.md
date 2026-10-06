# Storage Technology Evaluation v1 (C-5 evidence)

**Date:** 2026-10-03.

**Classification:** TARGET ARCHITECTURE evidence. Test-only work: a local emulator and a paper design. Nothing touches production.

**Purpose:** give Infrastructure, per guarantee of the durable-journal contract (`durable-journal-rebuild-contract-v1.md`), the evidence it needs for C-5. This document does **not** choose a database. It does not score, rank, or name a winner, and it does not turn prototype mechanisms into storage requirements.

**Outcome: ARCHITECTURE ESCALATION** (§5). The R-READ and O4 rows are stopped at CONTRACT_GAP. Every other row is complete.

---

## 0. What was run, and against what

| Item | Detail |
|---|---|
| Baseline before | `pytest tests` gave **905 passed** (2026-10-03, before any change) |
| Candidates | **Firestore**: the production store, per `storage-reality-audit.md` F2. **PostgreSQL**: the prior design target, per `memory-postgres-design-v1.md` (A7). No other candidates were added |
| Firestore environment | Local Firestore **emulator** (firebase-tools 14.1.0) on port 8086, project `demo-olbrain-storage-eval`, anonymous credentials, Python client `google-cloud-firestore` 2.30.0. No rules file, so the emulator is open and the admin client bypasses rules anyway. **No application rules were changed** |
| PostgreSQL environment | **None.** psql, pg_ctl, postgres and docker are all absent. Paper evaluation only; nothing was fabricated |
| Adapter | `memory-prototype/memory_core/storage_adapters/firestore_emulator.py`, class `FirestoreEmulatorJournal`. It implements the `DurableJournal` hooks. The contract's append rules stay in `DurableJournal.append` and `publish`; they are not reimplemented, only run inside **one Firestore transaction**. It refuses to start unless `FIRESTORE_EMULATOR_HOST` is a loopback address |
| Connector | `memory_core/storage_adapters/pytest_firestore_conformance.py`, a pytest plugin. It substitutes the adapter for `PartitionedJournal` before the suite is imported, then reports which tests reached the emulator. **The suite file is unchanged** |
| Supplementary probes | `memory_core/storage_adapters/firestore_probes.py` (P0–P5), for guarantees the single-process suite cannot reach. It sits outside `tests/`, so the baseline run is unaffected |
| Runner and outputs | `storage-eval-results/run_emulator.sh`. Outputs: `storage-eval-results/firestore-emulator-conformance.txt`, `firestore-emulator-probes.txt` and `p5-concurrent-trace.txt` (trace produced by `p5_trace_probe.py`) |
| Baseline after | **905 passed** (§7) |

### 0.1 Conformance suite on the Firestore emulator

The suite ran **unchanged**: **144 passed of 144**.

- **114 tests reached the emulator adapter:**
  - 129 adapter instances;
  - 4,666 committed transactions;
  - 4,674 transaction bodies (the difference is rolled-back rejects and crashes).
- **30 tests did not reach the emulator, by construction:**
  - 28 are the `A_global` parameter cases (the in-memory reference);
  - 2 build `A_global` explicitly: `test_future_validity_boundary_is_its_own_evaluation_point` and `test_break_historical_policy_selection_rewinds_versions`.
  - These 30 are rebuild-side checks that do not depend on storage.

Run on the final adapter. Output: `storage-eval-results/firestore-emulator-conformance.txt`.

### 0.2 Supplementary emulator probes

These are emulator observations only, never production evidence.

| Probe | What it checks | Result |
|---|---|---|
| P0 | Lost update with two concurrent read-modify-write transactions on one document | **No lost update.** One run: both committed, final value 2, 7 bodies. Earlier run: both aborted after 5 attempts, final value 0, i.e. livelock. Safe in both runs; nondeterministic |
| P0b | T1 reads A; T2 writes A; then T1 writes B | **T2 waited for T1's commit:** the read lock was honoured |
| P1 | 4 threads × (5 own entries + redelivery of 3 shared idems), all appending to one partition | **PASSED:** 23 entries, gap-free positions, no duplicates. Cost: 41 commits, 95 bodies, **54 position conflicts**. It passed because of the deterministic position ids, the `create` precondition and the adapter retry. **Not** because of transaction isolation (see P5) |
| P2 | A fresh adapter instance (no process memory) over the same namespace | **PASSED:** identical `facts()`, including vault deletions |
| P3 | Read served at r=10; a later append dated 8 | **Accepted** by the in-memory `PartitionedJournal` **and** by Firestore. The served read is no longer reproducible |
| P4 | Append at 6, stamped "nothing in force"; then publish v1 dated 5 | **Accepted** by both. The durable facts now violate O3/O4 |
| P5-seq | A per-partition read watermark (probe-only mechanism, **not chosen**), sequential | **PASSED** |
| P5-conc | The same watermark with 2 writers and 1 closed reader | **FAILED on the emulator.** A read served at 2.5 excluded an entry dated 1.0 that committed afterwards. The trace shows two transactions that both read the partition head and both wrote it, both committed: a non-serializable interleaving. See `p5-concurrent-trace.txt` |

---

## 1. Evidence sources

**Quotes marked "(relayed)"** were obtained through a fetch tool that summarises pages. The wording is close to the source but must be verified on the page before it is relied on contractually.

| Ref | Source | Content used |
|---|---|---|
| FS-TX | firebase.google.com/docs/firestore/transaction-data-contention | (relayed) "Cloud Firestore guarantees serializable isolation of transactions. Transactions in Cloud Firestore are serialized and isolated by commit time." "Transactions place locks on the documents they read." Standard edition uses pessimistic concurrency controls; Enterprise edition uses optimistic. After a finite number of retries: "ABORTED: Too much contention on these documents" |
| FS-EMU | firebase.google.com/docs/emulator-suite/connect_firestore | (relayed) "The emulator does not currently implement all transaction behavior seen in production… locks may take up to 30 seconds to be released." "The emulator does not enforce all limits enforced in production." |
| FS-RW | docs.cloud.google.com/firestore/docs/understand-reads-writes-scale | (relayed) Two-phase commit; quorum of replicas; "each participant records the commit decision to stable storage and the transaction is committed"; ACID plus serializability. Strong reads reflect all writes "committed up until the start of the read"; stale reads use `read_time` |
| FS-LOC | firebase.google.com/docs/firestore/locations | (relayed) Data replicated across zones (regional) or regions (multi-region) |
| FS-Q | firebase.google.com/docs/firestore/quotas | (relayed) Transaction time limit 270 s (60 s idle); document 1 MiB; API request 10 MiB |
| FS-BP | docs.cloud.google.com/firestore/docs/best-practices | (relayed) Per-document update rate "depends highly on the workload". A sequentially indexed field limits a collection to 500 writes/s. Ramp-up 500/50/5. *No numeric per-document limit was confirmed from the page; none is used here* |
| FS-PITR | docs.cloud.google.com/firestore/docs/pitr | (relayed) "PITR data is retained for 7 days", one version per minute |
| FS-BAK | docs.cloud.google.com/firestore/docs/backups | (relayed) Backup retention up to 14 weeks; restore is whole-database into a new database |
| FS-CMEK | docs.cloud.google.com/firestore/docs/cmek | (relayed) CMEK is per database. If the key is unavailable, all reads, writes and queries fail with FAILED_PRECONDITION. No per-document or per-user keys |
| PG-WAL | postgresql.org/docs/current/wal-async-commit.html | (relayed) With synchronous commit, "the server waits for the transaction's WAL records to be flushed to permanent storage before returning a success indication"; asynchronous commit has a loss window |
| PG-ISO | postgresql.org/docs/current/transaction-iso.html | (relayed) Serializable "emulates serial transaction execution"; applications must retry serialization failures. Read Committed takes a new snapshot per statement |
| PG-TIME | postgresql.org/docs/current/functions-datetime.html | (relayed) `now()`/`CURRENT_TIMESTAMP` "return the start time of the current transaction"; `clock_timestamp()` returns the actual current time |
| PG-D | `memory-postgres-design-v1.md` | Section references as §n below |

---

## 2. Evidence matrix

**Result categories:**
- PROVEN_EXECUTABLE: run here. For Firestore this means **on the emulator only**: logical behaviour, not production durability, scale or operations.
- PROVEN_DOCUMENTATION: authoritative vendor material.
- NOT_SHOWN.
- NEEDS_ENVIRONMENT.
- FAILS.
- CONTRACT_GAP.

### A. Per-partition ordering (O1)

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| A1 Total order per partition with non-decreasing commit time, under random cross-partition delivery | Firestore | PROVEN_EXECUTABLE | Emulator, unchanged suite | `test_property_equivalence_and_history_stability[B_partitioned]` (25 seeds), `test_global_order_is_not_required`, `test_commit_time_regression_is_rejected`. Position = deterministic doc id `entries/{pos}` under a partition head | Emulator only |
| A1 | PostgreSQL | NOT_SHOWN | Design | §1 has no per-subject journal or position column. Claims are keyed (org_id, claim_id) with `observed_seq` and `committed_at`. §5 serialises per subject with `SELECT … FOR UPDATE` on `subjects` rows | A journal table and position semantics are not designed. NEEDS_ENVIRONMENT for anything executable |
| A2 Order and exactly-once under concurrent writers to one partition | Firestore | PROVEN_DOCUMENTATION (isolation); emulator-observed pass (P1) | Docs plus emulator probe | FS-TX: serializable, locks on documents read. P1 passed: gap-free, no duplicates, 54 position conflicts / 41 commits | P1's correctness came from the `create` precondition on deterministic ids, which catches only conflicts that collide on the same document. Isolation under contention: **NEEDS_ENVIRONMENT** (FS-EMU; P5-conc) |
| A2 | PostgreSQL | NEEDS_ENVIRONMENT | Design plus docs | §5: per-subject `FOR UPDATE` in ascending `subject_id`, READ COMMITTED. The design says this "**must be validated by the VM-CON integration suite against real PG**". PG-ISO | No PG runtime |
| A3 Retry, duplicate or delayed delivery | Firestore | PROVEN_EXECUTABLE | Emulator, unchanged suite | `test_duplicate_delivery_is_idempotent[B]`, `test_crash_after_durable_append_before_ack_is_a_duplicate_on_retry`, interleaved delivery in the property tests | — |
| A3 | PostgreSQL | NOT_SHOWN | Design | §8 INV-7: own-derivation ids, dedup keys, outbox UNIQUE. These are per-row identities, not per-partition `idem` | NEEDS_ENVIRONMENT |
| A4 Partition recovery (state after restart) | Firestore | PROVEN_EXECUTABLE (logical restart); NEEDS_ENVIRONMENT (store recovery) | Emulator probe P2 | A fresh adapter instance sees identical facts. The emulator keeps data in memory, so a store crash and recovery were not exercised | Zone or region failover: FS-RW/FS-LOC (documentation), not exercised |
| A4 | PostgreSQL | NOT_SHOWN | Design | §7: restore through WORM replay plus roll-forward from **Firestore** commit records (LA-1/LA-10) | PG is not the recovery source in the design |

### B. Policy log and visibility (O2–O4)

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| B1 Ordered versions per predicate (O2) | Firestore | PROVEN_EXECUTABLE | Emulator, unchanged suite | `publish` runs inside a transaction reading `meta/pubs`; `publication_out_of_order` enforced; `test_adversarial_publication_between_reads_is_stable` | — |
| B1 | PostgreSQL | NOT_SHOWN | Design | §1 has **no publication or policy-log table**. Only `claims.policy_version` and `slots.policy_version` columns | Design silent |
| B2 Stamp = version in force at commit (O3), sequential | Firestore | PROVEN_EXECUTABLE | Emulator, unchanged suite | `test_stale_policy_stamp_is_rejected`, `check_stamps`, `test_property_entries_are_evaluated_under_the_policy_they_were_admitted_under` (15 seeds) | — |
| B2 | PostgreSQL | NOT_SHOWN | Design | `claims.policy_version` (§1); nothing checks it against a log | — |
| B3 O3 while a publication commits concurrently with appends | Firestore | NEEDS_ENVIRONMENT | Adapter design plus docs | Every append transaction reads `meta/pubs`; publish writes it. FS-TX (locks on documents read) would serialise them. Not probed. P0b suggests the emulator blocks this single-reader/single-writer pattern | **Cost:** each publish contends with every in-flight append. Depends on X-1 (§5) |
| B3 | PostgreSQL | NOT_SHOWN | Design | No publication table, so no lock design | — |
| B4 Equal-time rule (entries before publications) | Firestore | PROVEN_EXECUTABLE | Emulator, unchanged suite | `test_entry_and_publication_at_the_same_instant` (times stored as doubles, round-trip exact) | Rebuild-side rule; storage only has to keep `at` exactly |
| B4 | PostgreSQL | NOT_SHOWN | Design | — | Column type for `at` (timestamp precision vs double) not designed for this |
| B5 Publication visibility (O4) | Firestore | **CONTRACT_GAP** | Emulator probe P4 | A publication dated 5 was accepted after an acknowledged append dated 6. The facts now violate O3/O4. The in-memory simulator accepts it too | **Stopped. X-1** |
| B5 | PostgreSQL | **CONTRACT_GAP** | Reasoning plus probe P4 (technology-independent) | Same as Firestore | **Stopped. X-1** |
| B6 Historical replay under the policy in force at each point | Firestore | PROVEN_EXECUTABLE (publications); **NOT_SHOWN** (policy definitions) | Emulator, unchanged suite | History-stability property on B (25 seeds). **But** `policy_history` (the versioned `PredicatePolicy` definitions) is passed into the constructor and returned from process memory; the adapter does not store it | Interface-coverage gap, not a store failure. The interface needs a durable path for policy definitions |
| B6 | PostgreSQL | NOT_SHOWN | Design | — | — |

### C. R-READ (closed reads)

**Stopped at CONTRACT_GAP (X-1).** The mechanisms below were investigated; **none is chosen**.

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| C1 A read at r is not finalised while an acknowledged entry dated ≤ r can still appear | Firestore | **CONTRACT_GAP** | Emulator probe P3; contract §B | P3: a write dated 8 was accepted after a read served at 10, on Firestore **and** in memory. The contract already says the simulator "assumes R-READ rather than enforcing it" | **X-1** |
| C1 | PostgreSQL | **CONTRACT_GAP** | Reasoning; design §7 | Same as Firestore. Also, §7 routes `gateway_ro` replica reads only to lag-tolerant data, "never the slot for an OCC command". Closed reads on a replica would need replay-position handling, which is not designed | **X-1** |
| C2 Mechanism: read watermark (barrier) | Firestore | Sequential: PROVEN_EXECUTABLE (emulator). Concurrent: **NEEDS_ENVIRONMENT** | P5-seq passed; P5-conc **failed on the emulator** | The concurrent failure is a non-serializable interleaving, consistent with FS-EMU's caveat. FS-TX documents serializable isolation for production | Run P5-conc on real Firestore |
| C2 | PostgreSQL | NOT_SHOWN | — | Paper only: a head row `FOR UPDATE` would serialise readers and appenders [INFERENCE] | NEEDS_ENVIRONMENT |
| C3 Mechanism: store-assigned commit time | Firestore | PROVEN_DOCUMENTATION (primitive only) | FS-TX: "serialized and isolated by commit time"; FS-RW: strong reads reflect everything committed before the read | Not probed. It would change the interface, since `at` is supplied by the writer today | Applies only under one reading of X-1 |
| C3 | PostgreSQL | NOT_SHOWN | PG-TIME | `now()` is the **transaction start**, not commit order. `clock_timestamp()` is wall-clock. Neither is commit order by itself. Consistency would need a lock-ordered assignment [INFERENCE] | Applies only under one reading of X-1 |
| C4 Mechanism: as-of token | Both | NOT_SHOWN | — | Not probed | — |
| **C-cost (separate)** | Firestore | NEEDS_ENVIRONMENT | Mechanism analysis | Watermark: **every closed read becomes a transactional write** to the partition head, so reads of a hot subject compete like writes. The per-document update rate "depends highly on the workload" (FS-BP). Emulator latency is not representative | Measure in a real project |
| C-cost | PostgreSQL | NEEDS_ENVIRONMENT | — | — | — |

### D. Durable acknowledgement

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| D1 Acknowledged ⇒ durable (not merely "the write API returned") | Firestore | PROVEN_DOCUMENTATION | FS-RW (relayed): the commit decision is recorded to stable storage on a quorum before the commit is reported; FS-LOC replication | **The emulator keeps data in memory and proves nothing about durability** | Production failover: NEEDS_ENVIRONMENT |
| D1 | PostgreSQL | PROVEN_DOCUMENTATION (engine, with synchronous commit) / NOT_SHOWN (design) | PG-WAL | The design does not specify `synchronous_commit`, and its durability anchor is the **Firestore** commit record written before the PG transaction (§5 closing paragraph; §0 LA-1) | The design depends on Firestore for D |
| D2 Logical acknowledgement semantics (a crash before ack leaves nothing or everything; retry is DUPLICATE) | Firestore | PROVEN_EXECUTABLE | Emulator, unchanged suite | `test_group_append_is_all_or_nothing_and_retry_commits_once[B]`, `test_crash_after_durable_append_before_ack…` | Logical only |
| D2 | PostgreSQL | NOT_SHOWN | Design §7 Failover: "Idempotent by own-derivation ids (LA-4)" | — | NEEDS_ENVIRONMENT |

### E. Group atomicity

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| E1 All-or-nothing single-partition group | Firestore | PROVEN_EXECUTABLE (emulator) plus PROVEN_DOCUMENTATION (FS-RW ACID) | Unchanged suite | `test_group_append_is_all_or_nothing…[B]`; `test_break_non_atomic_group_leaks_a_partial_write[B]` (the weakened path leaks, as designed) | Group size limits: FS-Q lists a 10 MiB request and a 270 s transaction. The emulator does not enforce limits (FS-EMU), so the maximum group size is NEEDS_ENVIRONMENT |
| E1 | PostgreSQL | NOT_SHOWN (design) | §5: one commit transaction per extraction | Engine atomicity is standard but not fetched here | NEEDS_ENVIRONMENT |
| E2 Is multi-subject atomicity needed? | Contract | **No operation needs it** | Unchanged suite on the emulator | Cross-partition commit: `test_cross_partition_commit_is_exactly_once_across_retries_and_target_change` (intent/claim/outcome), on the emulator. Person erasure: per-partition entries plus a completion barrier, `test_erasure_is_complete_only_when_every_partition_is_done`, on the emulator | Neither candidate must provide cross-subject transactions |
| E2 | PostgreSQL | Design exceeds the contract | §5 locks the **full member set** for merge, undo and erasure | — | This is **not** a requirement (the contract needs none). Recorded so it is not turned into one |

### F. Idempotency and retries (logical exactly-once)

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| F1 Exactly-once per `idem` across redelivery and crash | Firestore | PROVEN_EXECUTABLE | Unchanged suite plus P1 | Suite (A3, D2); `idem_reused_with_different_content` rejected; P1 concurrent duplicates exactly-once | Under contention the guarantee rests on the create precondition plus re-running the append; isolation itself is NEEDS_ENVIRONMENT |
| F1 | PostgreSQL | NOT_SHOWN | Design §8 INV-7 | — | NEEDS_ENVIRONMENT |
| F2 Cross-partition exactly-once after a merge-target change | Firestore | PROVEN_EXECUTABLE | Unchanged suite | `test_cross_partition_commit_is_exactly_once…` (emulator); `test_break_without_intent…` (the break holds) | — |
| F2 | PostgreSQL | NOT_SHOWN | — | The design relies on Firestore commit records (§5) | — |

### G. Erasure

Custody and retention are not decided here.

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| G1 Sealing: an erased partition refuses appends | Firestore | PROVEN_EXECUTABLE | Unchanged suite | `test_person_erasure_covers_the_merge_cluster…` (`partition_erased`/`key_destroyed`); `test_break_without_erasure_fence…` | — |
| G1 | PostgreSQL | NOT_SHOWN | Design | §5 step 3: fence on stamped epochs; `subjects.erased_at` (§1) | NEEDS_ENVIRONMENT |
| G2 Completion barrier across the merge cluster | Firestore | PROVEN_EXECUTABLE | Unchanged suite | `test_erasure_is_complete_only_when_every_partition_is_done` | — |
| G2 | PostgreSQL | NOT_SHOWN | Design | `erasure_requests` / `erasure_steps` (§1) | — |
| G3 Content unrecoverable after key destruction | Firestore | **NOT_SHOWN** | Emulator plus docs | The adapter's `destroy_key` **deletes documents**. That is logical unreadability through the API, **not** cryptographic destruction. FS-CMEK keys are **per database**: no per-subject keys | Per-subject crypto-shred would need application-level encryption with external keys: **C-1 owner decision** |
| G3 | PostgreSQL | NOT_SHOWN | Design | §3: "Physical erasure removes rows… WAL and PITR retain the data until the backup window expires". No key destruction is designed | C-1; Legal |
| G4 Backup and replication contradictions | Firestore | PROVEN_DOCUMENTATION (windows) / inference (contents) | FS-PITR 7 days; FS-BAK ≤ 14 weeks | The pages do not say explicitly that deleted documents stay readable. That they stay recoverable within these windows is **[INFERENCE]** from documented PITR reads and whole-database restore | Retention: Legal/owner. Not decided here |
| G4 | PostgreSQL | PROVEN_DOCUMENTATION (by the design itself) | §3, §7: backups and WAL retain erased rows until the window expires; "backup retention ≤ the legal erasure deadline `[BLOCKED:Legal]`" | — | Legal |

### H. Rebuild from facts only

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| H1 Rebuild from persisted facts, without caches, process memory, the gate, re-run decisions, or current policy | Firestore | PROVEN_EXECUTABLE (entries, publications, vault); **NOT_SHOWN** (policy definitions) | Unchanged suite plus P2 | `test_rebuild_uses_durable_facts_only_and_never_the_gate` (B, emulator); equivalence property (B, 25 seeds); P2 fresh instance | `policy_history` lives outside storage in the interface (see B6) |
| H1 | PostgreSQL | NOT_SHOWN (design dependency) | Design | §0: "PG is fully rebuildable from FS evidence + WORM"; §3 `slots` is a projection; §7 restore protocol | In the design, PG is **not** the authoritative journal. It depends on Firestore commit records and WORM |

### I. Failure and recovery

No availability percentages are given.

| Guarantee | Candidate | Result | Evidence type | Evidence | Gap / dependency |
|---|---|---|---|---|---|
| I1 Crash mid-group or before ack | Firestore | PROVEN_EXECUTABLE (logical) | Unchanged suite | As D2 | — |
| I2 Contention behaviour | Firestore | Emulator-observed only | P0, P1 | P0: no lost update, but one run livelocked (both aborted after 5 attempts). P1: 54 position conflicts / 41 commits with 4 writers | Production: pessimistic in Standard edition, optimistic in Enterprise (FS-TX), "ABORTED: Too much contention". NEEDS_ENVIRONMENT |
| I3 Zone or region loss | Firestore | PROVEN_DOCUMENTATION (replication design) / NEEDS_ENVIRONMENT (behaviour) | FS-LOC, FS-RW | — | — |
| I1–I3 | PostgreSQL | NEEDS_ENVIRONMENT | Design §7: HA per physical tenant `[BLOCKED:Product/Ops]`; failover by client retry plus idempotency | — | — |

---

## 3. Comparative analysis (no winner)

- **Firestore against the executable contract.** The unchanged suite passes on the emulator through the technology-neutral interface. Firestore's native primitives cover every single-partition guarantee:
  - a transaction per append;
  - deterministic position ids with a `create` precondition;
  - a policy-log head document read by every append.
- **What the emulator cannot establish for Firestore:**
  - durability;
  - isolation under contention (the emulator admitted a non-serializable interleaving in P5-conc);
  - limits and scale.
- **Firestore costs to measure:**
  - every append transaction reads the partition head and the policy-log head, so a publish contends with all in-flight appends;
  - a single partition head per subject serialises that subject's writes;
  - any watermark-style closed read is a write.
- **PostgreSQL.** The existing design (A7) is a **projection store behind Firestore**, not a journal:
  - Firestore holds the authoritative commit records (§0 LA-1/LA-10; §5 closing paragraph; §7 Failover);
  - there is no policy-log table (§1);
  - erasure is row deletion within the backup and WAL windows (§3, §7);
  - its lock discipline exceeds the contract (§5, full member set).
  - Most PostgreSQL rows are therefore NOT_SHOWN rather than FAILS. The design was not written for the journal role, and no PostgreSQL runtime exists here.
  - Engine-level facts are documented: synchronous-commit durability, and serializable isolation with retry. One is relevant to X-1: `now()` is transaction-start time, not commit order.
- **Shared, technology-independent findings:**
  - X-1 (§5);
  - B6/H1: policy definitions have no durable path in the interface;
  - G3: per-subject cryptographic destruction is native to neither candidate. It needs application-level encryption with externally held keys (C-1).

---

## 4. Prototype preservation

- No semantic module was modified:
  - `durable_journal`, `state`, `registry`, `commit` and the rest are unchanged;
  - the conformance suite is unchanged;
  - no test was weakened, deleted, skipped or marked expected-to-fail.
- New files:
  - `memory_core/storage_adapters/__init__.py`, `firestore_emulator.py`, `pytest_firestore_conformance.py`, `firestore_probes.py`;
  - `investigation/storage-eval-results/*`.
- **P5-conc is kept as a failing probe.** It is the test to re-run on real Firestore. It is outside `tests/`, so it is not part of the 905 baseline.

---

## 5. Architecture-changing discovery: X-1. STOP for R-READ (C) and O4 (B5)

| Field | Content |
|---|---|
| **Scenario** | P4: append e at t=6 (correctly stamped: nothing in force); then publish v1 dated T=5. P3: serve a read at r=10; then append an entry dated 8 to the same partition (its last entry is dated 5) |
| **Rule** | O4: "A publication with time T is visible to every append and every read at a time ≥ T". R-READ: "no acknowledged entry is ever dated at or before a read already served" (contract §B) |
| **Behaviour** | Both are **accepted**, by the Firestore adapter **and** by the in-memory `PartitionedJournal`. The durable facts then violate O3/O4 (P4), and a served read becomes unreproducible (P3). The interface enforces O1 per partition and O2 per predicate, but nothing between a publication and the entries of other partitions, and nothing between reads and later appends. Tests pass only because the driver (`load`) publishes first and reads after everything is loaded. The contract already says this for R-READ, not for O4 |
| **Conflict** | The contract never says **who assigns commit time** (`at`). The two readings put the requirement in different places: **(a) store-assigned:** commit times must be consistent with the store's serialization order for entries **and** publications, which is a **storage requirement**. Firestore documents "serialized and isolated by commit time" (FS-TX). For PostgreSQL the design is silent, and `now()` is transaction start (PG-TIME). **(b) writer-assigned:** the store needs only serializable transactions; a barrier mechanism (watermark, as-of token, or closed-time lease) above the store must enforce R-READ and O4, with a different cost profile (e.g. reads become writes). The C-5 rows for C1–C3, B3 and B5, and the concurrency tests Infrastructure must run, differ between (a) and (b) |
| **Technology-specific?** | **No.** It reproduces on the in-memory reference implementation |
| **Owner** | The **durable-journal contract owner** (target architecture) must state the commit-time assignment rule and whether R-READ/O4 enforcement belongs to the store or to the layer above it. Then Infrastructure (C-5) |
| **Not done** | No mechanism was chosen. The watermark in P5 is a probe-only feasibility check. The interface and contract were not amended |

---

## 6. Infrastructure request

To be issued after X-1 is resolved; the concurrency tests depend on the reading chosen.

**Firestore (a non-production project):**
- **Provision:** an isolated non-production GCP project, Standard edition, Native mode, with synthetic data only. A service identity scoped to that project. The adapter's emulator guard would be replaced by an explicit allow-list for that one project, under Infrastructure's authorisation.
- **Run:**
  - the unchanged conformance suite through the adapter;
  - P1 and P5-conc, plus a publish-vs-append concurrency probe (B3);
  - group-size limits (E1);
  - contention and abort rates for one hot partition;
  - latency and cost of the closed-read mechanism chosen under X-1;
  - one failover or restore exercise for D/I.
- **Why documentation and the emulator are insufficient:**
  - the emulator keeps data in memory (D);
  - it "does not currently implement all transaction behavior seen in production" (FS-EMU), and P5-conc observed exactly such a gap;
  - it does not enforce limits;
  - its latency is not representative.

**PostgreSQL (a disposable instance matching the Cloud SQL target version):**
- **Provision:** one disposable instance plus a test role without BYPASSRLS. Synthetic data.
- **Run:**
  - a journal adapter for the same interface (not buildable meaningfully without a runtime);
  - the unchanged suite;
  - the same concurrency probes;
  - the commit-time assignment under X-1 (PG-TIME makes this non-trivial under reading (a));
  - RLS and `SET LOCAL` under pooling (design §4, §8 residual risk).
- **Why paper is insufficient:**
  - the design is not a journal (§0, §5);
  - it has no policy log (§1);
  - its own text defers lock behaviour and RLS to "real PG (Lane C)" (§5, §8).

---

## 7. Baseline after

`pytest tests`: **905 passed**, unchanged. See §0.

---

**OUTCOME: ARCHITECTURE ESCALATION.** The contract owner must resolve X-1. Infrastructure then decides C-5 with the matrix above and the §6 request.
