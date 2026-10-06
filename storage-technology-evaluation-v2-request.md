# Storage Technology Evaluation v2: Infrastructure Request (v2.0, ISSUED)

**Date:** 2026-10-04.

**Status:** **ISSUED, v2.0, 2026-10-04**, for **Firestore and PostgreSQL**, under the owner's authorisation. The issuance record is `target-architecture-c5-issuance-v1.md`. **C-5 remains undecided.**

**Baseline at issue:**
- full prototype suite 1055/1055;
- boundary suite 86/86 on both reference stores;
- X-1 64/64 (explicit) and 53/64 (implied).

**Written against:**
- `durable-journal-rebuild-contract-v1.1` (the file `durable-journal-rebuild-contract-v1.md`): Part 0 time, §B closure (K4–K7), Part 3 S1–S5;
- the executable boundary: `memory_core/storage_boundary/` plus `tests/test_durable_storage_boundary.py`.

**Supersedes:** §6 of `storage-technology-evaluation-v1.md`, which asked for the unchanged v1 suite plus Firestore-only probes.

**No storage technology is selected. No benchmark targets are set.** Every figure produced is a measurement to report, not a pass threshold. **The evaluation collects evidence for C-5. It does not make C-5:** results must not be turned into a storage choice except by a separate C-5 decision.

---

## 1. What every candidate must provide

A candidate adapter implements the technology-neutral `StorageBoundary`:
- the durable fact set;
- `assign`, `close`, `closed`;
- conditional `append` with an in-step check;
- `publish` / `publish_at`;
- `snapshot` / `view_position`;
- `seal` / `destroy_key`;
- `crash`.

**Closed-position form (K4).** The candidate **chooses** one, and the choice is recorded:
- **Explicit:** a closed position stored per source (partition, predicate log).
- **Implied:** only if the deployment provides a **global** time service (timestamp-oracle form, or equivalent) whose single increasing sequence spans all sources and survives crashes, with:
  - time drawn inside the commit step;
  - the entry durable only if the time service has not passed its time.

  A store whose commit time is known only after commit (so the record cannot carry it, K2) **cannot** use the implied form natively [INFERENCE]. The time service is then a global component to provision and evaluate in its own right.

## 2. Suites to run unchanged

| Suite | Tests | Applies to | Notes |
|---|---|---|---|
| `test_durable_storage_boundary.py` | 86 | Every candidate, through a connector plugin that registers the adapter in the suite's `STORES` / `KINDS` before collection (feasibility checked in v5; the suite file stays unchanged) | The acceptance suite for S1–S5, O1–O4, SPI, K2, K5–K9 (including K9 with a write landing in flight), erasure, rebuild. **Guarantee tests** apply to every candidate. **Break tests** demonstrate necessity on the reference stores, and apply to a candidate only if it exposes equivalent weakening switches |
| `test_x1_commit_time.py` | 64 | Every candidate. Reference result: 64/64 on the explicit store, 53/64 on the implied store. The 11 differences assert the explicit-frontier mechanism, exact served positions or explicit-only conditions: **mechanism-specific evidence, not semantic failures**. Their guarantees are proven for both forms by the boundary suite (v4 §3, v5) | Run with the adapter as the journal's default storage |
| `test_durable_journal_conformance.py` | 144 | Every candidate, as storage-level replay | Unchanged from v1 |

**These suites run in one process.** They establish logical behaviour and **step ordering**, not isolation, durability or behaviour at scale.

**One shared concurrency driver.** E1–E9 are run by one technology-neutral, multi-client driver written against `StorageBoundary`. It applies the suite's own invariant checks (`served_prefixes_are_immutable`, `acknowledged_stamps_hold`, `committed_at_is_commit_time`) and is used **unchanged for every candidate**, so that results are comparable.

## 3. Tests that require a real environment

The in-memory references and the emulator **cannot** establish the following (storage-technology-evaluation-v1: P5-conc; FS-EMU). Each test is run concurrently, from several processes or clients, against the real service.

| # | Test | Guarantee | Why documentation / emulator / in-memory evidence is insufficient | What to record |
|---|---|---|---|---|
| E1 | **Concurrent conditional append versus closure.** Many writers append to one partition while current readers close it (the P5-conc pattern, generalised) | S1, S4, SPI | The emulator admitted a non-serializable interleaving. In-memory interleavings test ordering only | Any served prefix later contradicted (must be 0); READ_CLOSED and abort rates |
| E2 | **Publish versus append contention** on one predicate across many partitions | O4, K6 | Unprobed. Depends on real lock and transaction behaviour | Stamp violations (must be 0); publication latency; append aborts while publishing |
| E3 | **Durability before acknowledgement:** kill the client and the process mid-commit; force failover where offered | S3 | The emulator is in-memory. Documentation is relayed only | Acknowledged-but-missing facts (must be 0) |
| E4 | **Crash and recovery of closure:** close, kill, restart, then late-dated appends | S2 | Implementation-specific (stored position, or the time source surviving the crash) | Late appends accepted into a served prefix (must be 0) |
| E5 | **Current-read closure cost** | K7 | Unmeasured. Explicit form: a stored write per current read unless already covered. Implied form: a global time-service draw per read (never free) | Explicit: stored writes per current read. Implied: time-service draws per read, and the service's latency and availability. Both: latency distribution; per-document or per-row write-rate effects |
| E6 | **Lagging and as-of reads** from replicas or read-time snapshots | K7, S4 | Replica semantics are product-specific | Served position versus the replica's incorporated position; whether any served view is later contradicted |
| E7 | **Contention and retry behaviour** for one hot subject and one hot predicate | S1, K9 | Real lock and abort behaviour | Abort and retry counts; READ_CLOSED versus STATE_CONFLICT separation (STATE_CONFLICT is never retried by infrastructure) |
| E8 | **Group-size limits** for single-partition group append | S5 | The emulator does not enforce limits | Largest group committed atomically; the failure mode beyond it |
| E9 | **Erasure:** fence and key destruction under concurrent appends | Erasure, fence | Concurrency | Appends accepted after the fence (must be 0). Key destruction itself is C-1 [OWNER] |

## 4. Per-candidate provisioning (when issued)

| Candidate | Provision | Notes |
|---|---|---|
| Firestore | An isolated non-production GCP project (Standard edition, Native mode), synthetic data only, a test identity scoped to it. A `StorageBoundary` adapter (the existing emulator adapter implements the v1 interface only). Its emulator-only guard is replaced by an explicit allow-list for that project, under Infrastructure's authorisation | Possible explicit form: per-partition and per-predicate head documents [INFERENCE]; the choice stays the adapter's. The record must carry `at` before commit (K2) |
| PostgreSQL | One disposable instance matching the Cloud SQL target version, a test role without BYPASSRLS, synthetic data. **A journal adapter implementing `StorageBoundary`**, built for this evaluation (test-only, not a production schema) | A journal design does not exist yet. The A7 design is a projection behind Firestore and is **not** evidence for these rows. Possible explicit form: head rows locked `FOR UPDATE`, time from a guarded clock, never `now()` [INFERENCE]; the choice stays the adapter's. **RLS and `SET LOCAL` under pooling are tested where the adapter uses them** (the role has no BYPASSRLS) |

## 5. Evidence classification of results

Every result is reported as one of:
- PROVEN_EXECUTABLE (with the environment named);
- PROVEN_DOCUMENTATION;
- INFERENCE;
- NEEDS_ENVIRONMENT;
- FAILS;
- CONTRACT_GAP.

Emulator results are never reported as production guarantees.

**Every result also states its dimension, kept separate:**
- semantic conformance (the suites; E1, E2, E4, E9 invariants);
- operational behaviour (aborts, refusals, retries: E1, E7);
- measured cost (E5; publication latency in E2);
- availability and durability (E3, E4, failover);
- implementation mechanism (the closed-position form chosen, and how each S-guarantee is realised).

A cost or availability figure is never reported as a conformance result, and a mechanism is never reported as a requirement.

## 5a. Evidence to return (per candidate)

1. The adapter, the connector, and the closed-position form chosen (explicit or implied, with the time service named if implied).
2. Results of the three suites run unchanged (the counts, and every failure with its classification).
3. The shared concurrency driver: its source and configuration, identical for both candidates.
4. E1–E9: for each, the classification, the environment, the recorded measurements from §3, and the raw logs.
5. Every CONTRACT_GAP found, stated as scenario, rule, observed behaviour and why it is not candidate-specific. Do not work around one.
6. Environment description (edition, version, region and topology) and confirmation that only synthetic data and test identities were used.

## 6. Out of scope

- Selecting a store: C-5 is a separate decision taken on the returned evidence. This evaluation does not make it.
- Production data, credentials or projects.
- Schemas or migrations for production; production deployment; shadow writes.
- The Gateway.
- Owner parameters (lease length, clock source and tolerance, acceptance of the current-read closure cost, lagging-read classes, retry budget). The measurements in E5 and E7 are inputs to those decisions.
