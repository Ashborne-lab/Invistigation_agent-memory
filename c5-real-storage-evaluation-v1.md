# C-5 Real Storage Evaluation v1

**Date:** 2026-10-05.

**Classification:** evidence collection for C-5 (TARGET ARCHITECTURE prototype). **No storage technology is selected. C-5 remains undecided.** A passing result here is not production-readiness approval.

**Verdict:** **PARTIALLY CONFORMANT.**
- **PostgreSQL:** every E1–E9 test was executed against a real (disposable, local) PostgreSQL 16.2 cluster and passed, or was measured, with the gaps stated.
- **Firestore:** not executed, **[BLOCKED:Infrastructure]**.

**Written against:** `storage-technology-evaluation-v2-request.md` v2.0 (unchanged, still SHA-pinned); durable-journal rebuild contract v1.1 (S1–S5, K2, K5–K9, O1–O4, SPI); the executable `StorageBoundary`.

**Labels:** [PROVEN] (executed here), [CONTRACT], [CODE], [DATA], [DOC] (provider documentation, not executed), [INFERENCE], [UNMEASURED], [CONTRACT_GAP], [BLOCKED:<owner>].

---

## 1. Authorisation and environment

**Authorisation.**
- The user directed this run on 2026-10-05. It supersedes MASTER "C-5 STATUS: READY / DELIVERY-BLOCKED" for the PostgreSQL half.
- The v2.0 request's §4 provisioning is "under Infrastructure's authorisation". No Infrastructure recipient has been established, so nothing was requested from or sent to anyone.

**Choices the user made (recorded, not derived):**
- Firestore is marked BLOCKED.
- PostgreSQL runs as a local, pip-bundled disposable cluster.
- Version 16 is the evaluation target. **No Cloud SQL target version is documented anywhere** in the investigation or the repos.

| Item | Firestore | PostgreSQL |
|---|---|---|
| Environment | **[BLOCKED:Infrastructure]** No non-production GCP project, no test identity, no `gcloud` or credentials on this machine. The emulator is excluded as evidence by v2.0 §3 and §5 | One disposable cluster, **PostgreSQL 16.2**, x86_64-pc-mingw64 (the `pgserver` wheel's bundled binaries), on Windows 11, local disk. Listening on 127.0.0.1 only. A streaming standby on 127.0.0.1:54330 for E6 and failover |
| Durability settings | n/a | `fsync=on`, `synchronous_commit=on`, `full_page_writes=on`, `wal_sync_method=open_datasync`, `wal_writer_delay=200ms` (asserted, `environment.json`) |
| Identity | n/a | Adapter role `c5app`: LOGIN, NOSUPERUSER, **NOBYPASSRLS**, owns nothing. Schema owner `c5admin`, used for setup and inspection only |
| Data | n/a | Synthetic only (`TEST_ONLY_*` policies, subjects `hot`, `p<k>`, `e9`, ...). 497 namespaces (one per journal) |
| Not equivalent to Cloud SQL | | Not a managed service, no regional HA, no Cloud SQL storage layer. Every latency figure is specific to this machine and is **not** a Cloud SQL figure |

**Cleanup.**
- **Per E-test:** each test ran in its own fresh namespace (`ns`). Its synthetic rows remain in the stopped, disposable cluster; nothing was shared between tests.
- E3c restored `synchronous_commit = on`. E3f reset `synchronous_standby_names` to `''`. Both are verified in `environment.json`.
- After each failover, the promoted standby was discarded, the old primary restarted (never two primaries), and a fresh standby built. Final replication state: one async standby, streaming.
- Both servers were stopped (`pg_ctl -m fast`, verified with `pg_isready`: no response).
- The data directories remain in the session scratchpad (`c5pg/primary`, `c5pg/replica`) and contain synthetic data only. Deleting them is left to the user.
- No production system, project, credential or schema was touched. Nothing was pushed or deployed.

## 2. Artefacts

**Code** (test-only, under `memory-prototype/memory_core/storage_adapters/`):

| File | Role |
|---|---|
| `postgres_boundary.py` | `PgFrontierStore`: the v1.1 `StorageBoundary` in the **explicit** form. `PgJournal`: the v1 `DurableJournal`, used by the conformance suite |
| `postgres_local.py` | The disposable cluster (init, start, crash, promote, conf) and the driver `Env` hooks |
| `pytest_postgres_conformance.py` | Connector plugin: runs the three suites **unchanged** |
| `c5_driver.py` | The shared, technology-neutral, multi-process E1–E9 driver |
| `postgres_probes.py` | Probes P-RLS and P-CKPT |

**Authoritative evidence:** `investigation/storage-eval-results/c5-postgres-v1-final/`.
- The **whole E-set was run once with one driver revision**: `c5_driver.py` SHA-256 `5c2b454e03b76f11492eb415657ce3ddeb9f5c67b998be793665b41e7e2e8ba2` (`driver-revision.txt`). The same file is the driver a Firestore run must use.
- Each test has a `result.json` and every worker's fsync'd log. The directory also holds `environment.json`, `P-RLS.json` and `P-CKPT.json`.
- Suite output is in `c5-postgres-v1/suites.txt`. The adapter was unchanged after those runs.

**Development runs:** `storage-eval-results/c5-postgres-v1/`. They were produced with earlier driver revisions and are kept as raw history. They are **not** the reported results. They include two driver bugs, found and fixed, which are not storage results:
- `E7-superseded-run1`: both contention modes shared one log directory, so its FAIL was invalid;
- `E7` (run 2): the typed writers lacked newly published policy versions (KeyError).

### Adapter mechanism (implementation, not requirement)

**Closed-position form: explicit.**
- Per-partition head rows hold `f_part` and per-predicate head rows hold `f_pol`. They are the serialization points (`SELECT … FOR UPDATE`, always locked in one global order: partitions, then predicates, sorted).
- Each `StorageBoundary` operation is **one transaction**. It runs the unchanged reference rules (`ExplicitFrontierStore`) over a working set loaded *after* taking the locks, writes back the difference, and commits.

**Time:** the caller's reading combined with the stored frontiers. Never `now()`.

**Isolation level:** READ COMMITTED with explicit row locks. `facts()` and `snapshot()` use REPEATABLE READ (one consistent snapshot).

**Tenant scoping:**
- every row carries `ns`;
- every transaction runs `set_config('app.ns', …, true)` (= `SET LOCAL`);
- RLS `USING` / `WITH CHECK` on all six tables.

## 3. The unchanged suites on PostgreSQL ([PROVEN], `suites.txt`)

| Suite | Result | What it covers |
|---|---|---|
| `test_durable_storage_boundary.py` | **44/44** passed (the explicit kind). 42 reached PostgreSQL; 2 are implied-form tests that never touch a store kind | The 42 implied-kind tests are **not applicable** (the implied form needs a global time service, v2.0 §1) and were deselected, **not counted as passes**. The break tests ran on the weakened PostgreSQL adapter and failed as intended (necessity shown on PostgreSQL too) |
| `test_x1_commit_time.py` | **64/64**, all on PostgreSQL | The reference result for the explicit store is 64/64 |
| `test_durable_journal_conformance.py` | **144/144**. 114 reached PostgreSQL (`B_partitioned`); 30 use only the in-memory comparator | Storage-level replay, unchanged from v1 |

These suites run **in one process**. They establish logical behaviour and step ordering on the real database, including:
- current / stale / write-after-read / in-flight K9;
- breaking publications;
- erasure fence, idempotency, crash-mid-group.

They do not establish isolation or durability. The E-tests below do that.

**Full prototype suite (system Python, no PostgreSQL driver installed):** **1802 passed**, unchanged. Nothing outside the plugin imports the PostgreSQL modules.

## 4. E1–E9 on PostgreSQL

All E-tests use real OS processes (`spawn`) as concurrent clients. Every acknowledgement is fsync'd to the worker's log before its next operation, so a killed worker's log is a lower bound on what was acknowledged. Each test runs in its own fresh namespace. Results are **deterministic in outcome** (the invariants), **not in counts** (interleavings and latencies vary from run to run).

| # | Setup / operation / concurrency | Expected property | Observed | Result |
|---|---|---|---|---|
| **E1** | 6 writer processes append to one partition `hot` while 4 reader processes do current (closing) reads, for 12 s | S1, S4, SPI: no served prefix is ever contradicted | 292 served reads, **0 contradicted** (entry-level), and the suite's `served_prefixes_are_immutable` holds. 313 acknowledged, **0 missing**. Refusals: 82 READ_CLOSED, 5 COMMIT_TIME_REGRESSED (transient, retried) | **PASS** [PROVEN] |
| **E2** | 6 writers append BILL-stamped entries across 24 partitions; 1 publisher publishes BILL v2..v31 every 0.25 s; 3 closing readers race the publisher | O4, K6, O3: no stamp violation; publication versus closure never changes a served policy set | **0 stamp violations**; `acknowledged_stamps_hold` holds. 203 closing reads (196 served publications): **0 entry or policy sets contradicted**. 417 acknowledged, 0 missing. 10 STALE_POLICY_STAMP, 2 READ_CLOSED and 1 COMMIT_TIME_REGRESSED while publishing. Publication latency p50 5.0 ms, p99 15.0 ms (local) | **PASS** [PROVEN] |
| **E3** | (a) 4 rounds × 4 writers appending 3-entry groups, killed (TerminateProcess) at a random moment. (b) The **backend** crashed (`pg_ctl -m immediate`: every PostgreSQL process killed, no shutdown checkpoint) under load, then restarted (WAL crash recovery) | S3 durable before ack; S5 groups all-or-nothing under a real kill or crash | (a) 950 acknowledged, **0 missing, 0 partial groups**. (b) 1075 acknowledged in total, 125 by writers active at the crash; **0 missing, 0 partial groups**. The server log shows "not properly shut down; automatic recovery"; downtime 37 s. Every acknowledged fact is visible to a later closed read | **PASS** [PROVEN] for levels A, C, D and E (process crash). See §5 for what this does not prove |
| **E3c** (negative control) | E3(b) repeated 3 times with `synchronous_commit=off`, then restored and verified `on` | Sensitivity of E3(b) | **16 acknowledged facts lost** across 3 trials (10, 3, 3). This proves E3(b) detects **acknowledgements issued before the commit's WAL left PostgreSQL**. Because the OS page cache survives this crash, it **cannot** distinguish "WAL handed to the OS" from "WAL fsync'd to stable storage" | **CONTROL LOSES** [PROVEN] |
| **E3f** | Crash the primary under load, promote the streaming standby, check the promoted node. Run async (`sync_state = async`, verified) and sync (`synchronous_standby_names='*'`, `sync_state = sync` verified before the crash) | S3 and S2 across failover | Async: 347 acknowledged, **0 missing**; late append at the max served r → READ_CLOSED; 0 contradicted. Sync: 353 acknowledged, **0 missing**, READ_CLOSED, 0 contradicted | **PASS** in these runs. Async is **not proven safe**: [DOC] async replication can lose recently acknowledged commits on failover, and one trial with ≤ 0.6 KB lag is not evidence of safety |
| **E4** | A client closes partition `c` (a current read evaluating CITY) and exits. The backend is crashed and restarted. A new client then appends at r−1, r−1e−6 and r, assigns time, and back-dates a CITY publication | S2: closure survives a crash | Every late append → **READ_CLOSED**; `assign` after recovery gives > r; the back-dated publication → **refused: log_closed**; `f_pol[CITY] ≥ r` after recovery. **0 late appends in the served prefix** | **PASS** [PROVEN] |
| **E5** | 300 sequential current reads on a subject with one predicate; repeat reads at an already-closed r; stale-tolerant reads | K7 cost | Current read: **≤ 2 stored writes** (mean 1.90: the partition head plus the evaluated predicate's log head). Repeat at a closed r: **0**. Stale-tolerant read: **0**. Database counters agree: `heads` 285 and `polheads` 286 updates, all HOT, against 570 driver-counted frontier writes. Latency (local, environment-specific): current p50 5.4 / p99 15.1 ms; stale p50 2.9 / p99 7.3 ms | **MEASURED** [PROVEN]. Acceptance of the cost is an [OWNER] parameter (v2.0 §6) |
| **E6** | 4 writers on the primary; 1 closing reader on the primary; 2 lagging readers on the hot standby (REPEATABLE READ snapshot, served at the replica's replayed `f_part`) | K7, S4: a lagging view never serves beyond what it incorporated, and is never contradicted | 408 replica reads: **0 contradicted**; **408/408 served at or below the replica's own frontier**. Lag ≤ 96 bytes of WAL (local loopback). Replica read p50 7.7 ms | **PASS** [PROVEN] (local streaming standby; not a Cloud SQL read replica) |
| **E7** | Hot subject: 6 typed-command processes on one subject, each doing current read → expected version → command, while a publisher publishes CITY v2..v16 every 0.8 s. Hot predicate: 6 subjects, one CITY log. Plus 3 clients submitting the same 40 command ids at the same instant | S1, K9 (the serialized write is the authority), READ_CLOSED versus STATE_CONFLICT separation, exactly-once | Hot subject: 49 APPENDED, 162 STATE_CONFLICT, 50 STALE_POLICY_STAMP; retries 114 READ_CLOSED and 14 COMMIT_TIME_REGRESSED. **Stale commands accepted: 0.** Every admitted command's expected version equals the slot version recomputed from the durable prefix before it. **STATE_CONFLICT retried: 0.** `committed_at_is_commit_time` holds. Hot predicate: 308 APPENDED, 0 violations, p50 59 / p99 298 ms. Same ids: **exactly 1 durable copy each**; later attempts DUPLICATE (8), or REJECTED `idem_reused_with_different_content` (2, because the driver's record embeds the assigned time) | **PASS** [PROVEN]. 3 harness KeyErrors: a version published between a writer learning versions and its read; retried |
| **E8** | Single-partition group appends of n = 1 … 50 000 entries; for each n, a mid-group crash (`crash_after=n/2`, which rolls back the transaction) and then the full append | S5 | Every group committed atomically (durable = n). After every mid-group crash, **0 durable**. 50 000 entries commit in 6.8 s (local). **No limit reached.** E8's crash is a Python exception followed by a rollback; the real-kill and crash evidence for S5 is E3's group check | **PASS** [PROVEN] up to 50 000. Beyond that: [DOC] (§8) |
| **E9** | 4 writer processes commit claims with sealed content to subject `e9`; an eraser commits the erasure entry (the fence) mid-run, then destroys `key:e9` | Erasure fence; no append after the fence; sealed content unreadable | **0 appends after the fence; 0 sealed rows left; `reconstruct` = erased.** Writers after the fence: REJECTED `partition_erased`, or `AppendRejected("key_destroyed")` at seal time, raised as an **exception** by `TimedJournal.finish` (71). That is journal-layer behaviour, identical to the reference. **Storage residue:** see §7 | **Fence: PASS.** **"Unrecoverable everywhere": FAILS on row deletion** (§10 E-1) |

**Probes:**

| Probe | Result |
|---|---|
| **P-RLS** [PROVEN] | **PASS.** One pooled connection serving tenant A, then tenant B: B sees 0 of A's entries and 0 of A's vault rows; `app.ns` is empty after each transaction; an unscoped query sees 0 rows; a write into another tenant is **refused by the RLS WITH CHECK**; `c5app` has no BYPASSRLS and owns no table. Contrast: a **session-level** `set_config(…, false)` survives the transaction on a pooled connection and exposes the tenant's rows (1 row visible). That is the hazard `SET LOCAL` avoids. The superuser bypasses RLS, as expected |
| **P-CKPT** [PROVEN] | Full and compact checkpoints sealed under the subject key validate before erasure and give **`unreadable`** after key destruction, which also deletes their payload rows. **[CODE] gap:** `CheckpointStore.discard` / `drop_staged` delete through `storage.vault` (an in-memory attribute), not a `StorageBoundary` operation. On PostgreSQL a retired payload row stays in the database (2 → 2) until key destruction. This is a prototype gap, not a contract gap |

## 5. Durability levels (brief §4), PostgreSQL

| Level | Meaning | Evidence | Label |
|---|---|---|---|
| A | Acknowledged by the client | `COMMIT` returned; the worker fsync'd its ack line before continuing | [PROVEN] |
| B | Durably committed by the backend | Config (`synchronous_commit=on`, `fsync=on`): [DOC] says commit returns after the WAL fsync. E3c proves only that E3(b) catches acknowledgements issued before the WAL left PostgreSQL. **The fsync to stable storage itself is not exercised**, because the OS page cache survives every crash used here | [DOC]/config; the fsync step **[UNMEASURED]** |
| C | Visible to a later closed read | E3: every acknowledged fact is in a closed read after recovery. E1/E2: 0 contradictions | [PROVEN] |
| D | Survives a client or process crash | E3(a): 768 acknowledged, 0 missing, 0 partial groups | [PROVEN] |
| E | Survives backend failure and recovery | E3(b): an immediate stop (all server processes killed, WAL replay), 0 missing. E3f: failover to a standby, 0 missing in 1 async and 1 sync trial (`sync_state` verified) | [PROVEN] for a process crash. Failover: [PROVEN] for these trials only |
| — | OS crash / power loss | Windows, `open_datasync`, consumer-drive write cache unknown. The OS page cache survived every test above | **[UNMEASURED]** |
| — | Managed HA failover (Cloud SQL regional) | No managed service | **[UNMEASURED]** |

## 6. Ordering and closed reads (brief §5), with the primitive used

| Property | Primitive | Evidence |
|---|---|---|
| Per-partition commit order | The partition head row `FOR UPDATE`; position = count under the lock; `at` non-decreasing (O1) | Suites; E1 (COMMIT_TIME_REGRESSED refused, retried) |
| Policy-log order | The predicate head row `FOR UPDATE`; T > `f_pol` and > the last publication | Suites; E2; E4 (back-dated publication refused) |
| Causal visibility | The causal token = the served position; `assign` > every closure | X-1 suite on PostgreSQL |
| Stable served prefix | Closure raises `f_part` under the head lock after every earlier append committed. The read's facts are read after closure (REPEATABLE READ) | E1, E2, E6 (0 contradictions) |
| Writes racing closure | READ_CLOSED (S1) | E1, E7 |
| Publication racing closure | The publication waits on the log head; a reader closes the log through r before reading publications | E2 (203 reads, 0 contradicted) |
| Lagging and as-of reads | The standby serves only at its replayed frontier. WAL order guarantees entries ≤ f precede the frontier write | E6 |
| Firestore | — | [BLOCKED:Infrastructure] |

### Brief §6 (OCC / K9) on PostgreSQL

| Case | Covered by |
|---|---|
| Current command | Suites (single process); E7 (49 + 308 APPENDED across processes) |
| Stale expected version | Suites; E7 (162 STATE_CONFLICT) |
| Write after read | Suites; E7 (other processes' writes land between a read and its command) |
| Write landing in flight after validation | Suites (boundary and X-1 in-flight K9 tests, single process); E7 K9 exactness check (cross-process) |
| Breaking policy publication | Suites (single process) |
| Publication racing the write | E7 (50 STALE_POLICY_STAMP, 0 stale stamps acknowledged); E2 (O3/O4) |
| Concurrent writes, same subject | E7 hot subject |
| Concurrent writes, different subjects | E7 hot predicate; E2 |
| The Gateway's operation-scoped validation path | **Not run on PostgreSQL.** The Gateway is out of scope (v2.0 §6); its journal-level K9 is what is exercised |

## 7. Erasure (brief §7), separated

| Aspect | PostgreSQL behaviour | Label |
|---|---|---|
| Journal erasure fact | The erasure entry is appended under the partition lock; every later append → REJECTED `partition_erased` | [PROVEN] E9, suites |
| Reader-visible erased state | `reconstruct` = erased; no view; checkpoints → `unreadable` | [PROVEN] E9, P-CKPT |
| New writes racing erasure | 0 accepted after the fence. A seal after destruction is refused (key row `FOR SHARE` vs `FOR UPDATE`) | [PROVEN] E9 |
| Storage deletion | `DELETE` of the vault rows plus a fence row. **The plaintext bytes remain in heap pages after `DELETE`, and after a plain `VACUUM`** (final run: 553 marker occurrences after `DELETE`, 553 after `VACUUM`). Only `VACUUM FULL` removed them from the heap. **WAL still contains every occurrence** (553), and so does the **standby's WAL** (553) | [PROVEN] (byte scan of the data directories) |
| Stale snapshot | A REPEATABLE READ transaction whose snapshot predates the destruction **still reads the deleted vault row** (1 row) after the destroy commits. New snapshots see 0 | [PROVEN] |
| Backups / PITR | WAL archives and base backups would retain the bytes until they expire | [INFERENCE] (none configured here) |
| Cryptographic unreadability | Not provided by row deletion. Requires per-subject encryption with key destruction (C-1, key custody) | [CONTRACT_GAP] / C-1 [OWNER] |

## 8. Backend limits and operational constraints (PostgreSQL)

| Limit | Value | Label |
|---|---|---|
| Atomic group size | 50 000 entries in one transaction committed atomically (6.8 s locally); no failure reached | [PROVEN] up to 50 000 |
| Field size | 1 GB per `bytea` value; 32 TB per table (8 kB pages); 2^32 − 1 commands per transaction | [DOC] PostgreSQL 16 limits |
| Transaction duration | No hard limit. Long transactions pin MVCC snapshots (and, as shown in §7, keep erased rows visible to themselves), block VACUUM, and consume the XID horizon (wraparound at ~2^31) | [DOC] + [PROVEN] (§7) |
| Write contention | Per-partition and per-predicate row locks serialize writers. Hot subject: command p50 51 ms, p99 352 ms with 6 writers (local) | [PROVEN] local |
| Hot key | Every current read updates its head rows (E5, all HOT updates). One hot partition is serialized on a single row | [PROVEN] |
| Read consistency | READ COMMITTED plus row locks for writes; REPEATABLE READ for `facts` / `snapshot`; standby reads at a replayed snapshot | [PROVEN] |
| Retry semantics | READ_CLOSED and COMMIT_TIME_REGRESSED are transient (retried with a new time). STATE_CONFLICT is terminal (never retried). No serialization-failure retries are needed at READ COMMITTED with row locks; none were observed | [PROVEN] E7 |
| Idempotency primitive | The idem check under the partition lock (the reference rule). Same id and content → DUPLICATE; same id with different content → refused | [PROVEN] E7, suites |
| Deletion semantics | MVCC: deleted rows persist until VACUUM; bytes persist in WAL, replicas and backups | [PROVEN] §7 |
| TTL | None native | [DOC] |
| Practical journal growth | **This adapter** loads the whole namespace on `facts()` and the locked partition on every append: O(partition) per operation. A test-only shape, not a production schema. Not measured at scale | [CODE] / [UNMEASURED] |
| Checkpoint maintenance | Payloads are vault rows; retiring one needs a boundary-level delete (P-CKPT gap) | [CODE] |

## 9. Evidence tables

### A. Firestore

| Requirement | Result | Evidence | Risk / limitation |
|---|---|---|---|
| Suites unchanged (boundary, X-1, conformance) | **[BLOCKED:Infrastructure]** | No non-production project or identity | Emulator results exist (storage-technology-evaluation-v1, FS-EMU) and are **not** production evidence |
| E1–E9 | **[BLOCKED:Infrastructure]** | Same | The emulator previously admitted a non-serializable interleaving (P5-conc), so real-service E1 is essential |
| RLS-equivalent isolation, erasure, durability, failover | **[BLOCKED:Infrastructure]** | Same | No `StorageBoundary` (v1.1) adapter for real Firestore exists yet; the emulator adapter implements v1 only |

### B. PostgreSQL

| Requirement | Result | Evidence | Risk / limitation |
|---|---|---|---|
| S1 conditional append | Holds | Suites; E1, E7 | Local only |
| S2 closure survives crash | Holds | E4; E3f (promoted frontier = max served r) | Async failover not proven safe ([DOC]) |
| S3 durable before ack | Holds for levels A, C, D, E (process crash, failover trials) | E3 / E3c / E3f | The WAL fsync to stable storage, OS crash and power loss: [UNMEASURED]. Managed HA: [UNMEASURED] |
| S4 / SPI reads follow closure | Holds | E1, E2, E6 | — |
| S5 atomic group, idempotency | Holds | E3 (kill/crash), E8, E7 | Tested to 50 000 entries |
| O3 / O4 / K6 stamps and publications | Holds | E2, E4, suites | Per-tenant policy logs (mechanism, §11) |
| K7 closure cost | ≤ 2 stored writes per current read; 0 for stale-tolerant reads | E5 | Acceptance is [OWNER] |
| K9 in-write OCC | Holds; 0 stale accepted under contention and racing publication | E7, suites | — |
| Lagging reads | Holds on a streaming standby | E6 | Not a Cloud SQL replica |
| Erasure fence | Holds | E9 | — |
| Erasure "unrecoverable everywhere" | **Not provided by row deletion** | §7 | E-1 below; C-1 |
| Tenant isolation (RLS, `SET LOCAL`, pooling) | Holds | P-RLS | A session-level SET would leak: the adapter must keep LOCAL |

### C. Cross-backend comparison

**None is possible.** No Firestore real-service evidence exists. Comparing PostgreSQL evidence with Firestore emulator evidence is excluded by v2.0 §5.

### D. Contract gaps (demonstrated by neither backend)

| Gap | Status |
|---|---|
| Durability under OS crash or power loss, and under managed HA failover | [UNMEASURED] |
| Cryptographic key destruction ("unrecoverable everywhere", including WAL, replicas, backups, open snapshots) | [CONTRACT_GAP] → C-1 [OWNER] |
| The implied closed-position form (a global time service) | Not evaluated; PostgreSQL used the explicit form |
| Behaviour at production scale (journal growth, partition length, checkpoint cadence on a real store) | [UNMEASURED] |
| Whether a reader whose snapshot predates a key destruction may still return the destroyed content | The contract does not say. Such a read is serialized before the destruction [INFERENCE], but long-lived snapshots (exports, replicas, backups) are a retention question for C-1 |

**No v1.1 contract rule was contradicted on PostgreSQL. No contract was changed.**

## 10. E. Backend-specific incompatibilities (PostgreSQL)

| # | Exact contract | Backend behaviour | Why they conflict | Adapter fix without a contract change? | Contract change needed? |
|---|---|---|---|---|---|
| **E-1** | `destroy_key`: "every sealed payload under this key becomes unrecoverable, everywhere" (durable_journal; erasure) | `DELETE` leaves bytes in heap pages (until `VACUUM FULL` or page reuse), in WAL, on standbys and in backups. Open REPEATABLE READ snapshots keep reading the row | Deletion is not unrecoverability | **Yes**, by encrypting sealed content per subject key with the key held outside the database (destroying the key = crypto-shred). That is exactly C-1 (key custody) [OWNER]. Row deletion alone cannot satisfy it | No |
| **E-2** | S3 / S2 across failover | Async streaming replication can lose acknowledged commits and closures on promotion [DOC]. Not observed in one trial | A promoted standby may lack an acknowledged fact or frontier | **Yes:** synchronous replication (`synchronous_standby_names`, or a managed HA with synchronous storage) | No |
| **E-3** | `SET LOCAL` tenant scoping under pooling (v2.0 §4) | A session-level setting persists across pooled transactions (P-RLS) | A pool reusing a connection would expose the previous tenant | **Yes:** the adapter only uses `set_config(…, true)`; a pooler in transaction mode must never set session state | No |

**Not incompatibilities, recorded for completeness:**
- **[CODE] `CheckpointStore`** deletes payloads through `storage.vault` (P-CKPT). It is not a `StorageBoundary` operation; the fix belongs to the prototype.
- **[CODE] `TimedJournal.finish`** lets `AppendRejected("key_destroyed")` from `seal` escape as an exception. This is the same on the reference stores.

## 11. Mechanism notes (not requirements)

- **[INFERENCE] Policy logs are scoped per namespace (tenant)** in this adapter. If production policy logs are global across tenants, the predicate head row becomes a cross-tenant hot row: every assign and every current read evaluating that predicate would lock or update it.
- The adapter's per-operation load of the locked partition and of the publications is a test shape. A production schema would read only the tail and an index (not designed here, out of scope).

## 12. F. Decision packet

**None created.** The open items are existing owner decisions, not new ones:
- the Firestore environment ([BLOCKED:Infrastructure], the role named in v2.0 §4, with no named recipient);
- C-1 key custody (E-1);
- C-5 itself;
- the K7 cost and retry-budget parameters (v2.0 §6).

No owner or channel is guessed. Nothing was sent.

## 13. Next step (not started)

**[BLOCKED:Infrastructure]** Run the same driver and the three suites against real Firestore. That needs an isolated non-production project, a scoped test identity, and a v1.1 `StorageBoundary` Firestore adapter. Only then can §9 C be filled and C-5 be decided.

**C-5 REAL STORAGE EVALUATION V1 PARTIALLY CONFORMANT.**
