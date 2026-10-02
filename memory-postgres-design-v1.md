# PostgreSQL Design Validation v1 (Lane A, A7)

**Date:** 2026-10-01.

**Classification:** TARGET ARCHITECTURE, design only. No database is created, and no runnable DDL is given: tables are specified as column sets.

**Inputs:**
- v2 §P/§V;
- red-team M-1/M-13/M-16/C-1a/C-8;
- the Lane A findings LA-1…LA-18 (`memory-lane-a-status-v1.md`);
- the registry (`memory-lifecycle-registry-v1.md`).

**Tags:**
- `[DERIVED]` from the invariants;
- `[INFERENCE]` from PostgreSQL / Cloud SQL behaviour, not measured here;
- `[UNMEASURED]` for capacity figures.

## 0. What Lane A changed in the storage design

| Change | Consequence for PostgreSQL |
|---|---|
| **LA-11:** one claim per evidence-anchored assertion; dedup is a read-time concern | More, smaller, insert-only claim rows. No support folding, so **no hot-row updates on claims**. `claim_support` is mostly one row per claim (multi-anchor quotes only) |
| **LA-9:** retraction records | A new `retraction_records` table. Every new claim checks it (indexed lookup by subject group, key, value) |
| **LA-1 / LA-10:** commit records (proposals + recorded decisions) kept **with the evidence in Firestore** | PG is fully rebuildable from FS evidence + WORM. PG backups are a recovery accelerator, not the only copy. A `replay_watermark` row makes roll-forward resumable |
| **C-1a:** bindings in Firestore are authoritative for identity | PG `subjects` is a projection, fed by `identity_events`, with an applied-events table for idempotency |
| **LA-3:** merge ids = merges on the current path | Computed from `merged_into` at ingestion. No per-subject `merge_ids_in_force` arrays to maintain |
| **M-9:** no person-content caches; index hits re-validated | Every context build is a few indexed reads. Read latency matters more than cache design |

## 1. Entities and keys

All memory tables use a **leading `org_id` in the primary key**. That makes RLS predicates and partition pruning cheap, and puts every row physically in a tenant's partition.

| Table | Primary key | Main columns | Notes |
|---|---|---|---|
| `subjects` (projection) | (org_id, subject_id) | kind (person/account/endpoint), assurance, status, merged_into, member_set_version, erased_at | Fed from `identity_events`. Never written by extraction |
| `identity_events_applied` | (org_id, event_id) | kind, merge_id, absorbed, survivor, seq, applied_at | Idempotency of the projection (C-1a) |
| `evidence_meta` | (org_id, evidence_id) | subject_id, source_member_id, agent_id, session_id, author_role, receipt_commit_ts, receipt_seq, said_at, stamps (epochs, merge_ids), seal_state, sealed_hash, extraction_state, status | `evidence_id` = the Firestore doc id (R-3) |
| `claims` | (org_id, claim_id) | subject_id, owning_scope, key, value (jsonb), source, source_member_id, assertion_mode, value_check, valid_from, valid_until, observed_at, observed_seq, committed_at, extractor_version (composite), policy_version, derivation, written_via, status, retract_cause, attributed, merge_ids text[] | Content columns are immutable (trigger-enforced). Lifecycle columns change only through transitions |
| `claim_support` | (org_id, claim_id, evidence_id) | source_class, source_member_id, observed_at, quote, merge_ids | The quote lives here (F-5) |
| `claim_transitions` | (org_id, claim_id, seq) | at, from, to, cause, cause_ref, effective_at, merge_ids | Append-only |
| `retraction_records` | (org_id, record_id) | subject_group (source, member), key, value, cause, observed_at, observed_seq, evidence_id, committed_at, merge_ids | LA-9. Lookup index: (org_id, member, key, value) |
| `suppressions` | (org_id, subject_id, fingerprint) | created_at, observed_before | Keyed fingerprints only |
| `slots` (projection) | (org_id, subject_id, key) | result jsonb, state_version, computed_at, policy_version, member_set_version | Rebuildable; never authoritative (INV-3) |
| `commitment_events` | (org_id, event_id) | commitment_key, relationship_ref, kind, at, actor, evidence_id, due_until, external_ref | Projection computed on read or cached in `commitment_heads` |
| `episodes`, `narratives` | (org_id, episode_id) | subject_id, agent_id, started/ended, merge_ids; summary, generator_version, input_evidence_ids | Narratives off by default in prompts (R-25) |
| `accounts`, `account_links` | (org_id, account_id), (org_id, person_root, account_id) | aliases, merged_into; link source, valid_from, valid_until | Links come only from authoritative sources (C-5) |
| `agent_knowledge`, `knowledge_contributions` | (org_id, item_id), (org_id, item_id, subject_id) | statement, status, k; merge_ids per contribution | Lineage table enables erasure (M-3) |
| `prompt_manifests` | (org_id, message_id) | subject_ref (rekeyed on erasure), manifest jsonb, block_hash, truncated | R-22 |
| `memory_events` | (org_id, at, event_id) | kind, ids jsonb | Ids only. Monthly partitions |
| `outbox` | (org_id, id) | topic, payload (ids only), dedup_key UNIQUE, dispatched_at | Daily partitions, dropped |
| `erasure_requests`, `erasure_steps` | (request_id), (request_id, store) | scope ref (keyed HMAC), status, handler_version | Mirrored to WORM. Global, not per-org-partitioned (the auditor scans them) |
| `replay_watermark` | (instance) | seq | LA-10 |
| `claims_search` | (org_id, claim_id) | tsv (normaliser tokens, M-11), trigram column | Rebuildable projection |

**Scope representation.** `owning_scope` is an enum (PERSON / ACCOUNT / RELATIONSHIP / SESSION). `scope_ref` is a tagged reference: `subject_id` for PERSON and ACCOUNT, `(agent_id, subject_id)` for RELATIONSHIP, `session_id` for SESSION. Scopes are never inherited (v2 §C.2).

## 2. Tenancy and physical isolation: the decision

**Options compared** against OLBrain's real shape:
- many small orgs plus a few large ones;
- dedicated physical tenants already exist (`runtime.type=dedicated`, clix-capital-prod with its own IaC);
- erasure and audit queries are always per-org;
- no query in the Gateway API spans orgs.

| Option | Isolation | Ops at 10³–10⁵ orgs | Migrations | Noisy neighbours | Cost | Verdict |
|---|---|---|---|---|---|---|
| A. Shared multi-tenant PG + RLS only | Logical | One fleet | One run | Poor without partitioning | Lowest | Insufficient alone |
| B. Database (or instance) per tenant | Physical | Unmanageable at 10⁴+ orgs: connections, migrations, monitoring, backups each multiplied | N runs | Excellent | Highest | **Rejected for the shared tier** |
| C. Shared instance + hash partitioning by `org_id` + RLS | Logical, plus physical locality per partition | One fleet | One run | Bounded: vacuum and bloat per partition; per-org limits | Low | **Chosen for the standard tier** `[DECISION←DERIVED]` |
| D. Hybrid by tier: C for standard, a dedicated instance per **dedicated physical tenant** | Physical where contracted | Fleet plus a few dedicated | Pipeline fan-out to N_dedicated | Excellent for dedicated | Proportional to contracts | **Chosen overall** |

**Validation of v2's "Cloud SQL HA per physical tenant".** It stays justified **only** in the sense of *physical tenant* = a dedicated GCP project that already exists for contractual or regulatory reasons. It is **not** justified per org.

- The v2 wording is kept.
- The decision basis is stated: an instance follows the existing physical tenancy (project boundary, residency, key custody), not the org count.
- A dedicated instance is HA only if the tenant's RPO/RTO requires it `[BLOCKED:Product/Ops]`. A single-zone instance with PITR plus a WORM ledger is an acceptable default for small dedicated tenants, because PG is rebuildable from FS (LA-1).

## 3. Partitioning, retention, vacuum

| Table | Partitioning | Retention | Vacuum and storage note |
|---|---|---|---|
| claims, claim_support, claim_transitions, retraction_records, suppressions, slots, evidence_meta, episodes | **HASH(org_id)**, 32 partitions at start `[UNMEASURED]`; re-partition by splitting when a partition exceeds a size threshold `[UNMEASURED]` | Life of subject; erasure deletes rows (archive first, R6b) | Mostly insert-only (LA-11), so low bloat. `slots` is the only hot-update table: fillfactor 70 `[UNMEASURED]`, HOT updates (no indexed columns change on refresh) |
| memory_events | RANGE(at) monthly | Detach and drop after the window, aggregates to BigQuery (M-16) | Drop partitions; never DELETE |
| outbox | RANGE(created_at) daily | Drop dispatched partitions after N days `[UNMEASURED]` | Same |
| prompt_manifests | RANGE(created_at) monthly | Audit window `[UNMEASURED]` | Same |
| erasure_*, replay_watermark | none | Permanent (PII-free) | Tiny |

**Large tenants.** One org larger than a partition's share is isolated by moving it to its **own partition** (LIST partition carved out of the hash set) or to a dedicated instance (tier D). RLS stays identical in both cases.

**Physical erasure** removes rows. Dead tuples are vacuumed. WAL and PITR retain the data until the backup window expires, which is why backup retention ≤ the legal erasure deadline (`[BLOCKED:Legal]`), plus WORM replay on restore (C-8).

## 4. RLS, roles, connections

| Item | Design | Why |
|---|---|---|
| Roles | `gateway_rw` (DML only, not the owner), `gateway_ro` (replica reads), `migrator` (DDL). The owner role is never used at runtime | RLS does not apply to owners |
| RLS | `ENABLE` + `FORCE ROW LEVEL SECURITY` on every memory table. Policy `org_id = current_setting('app.org_id')::text` for USING and WITH CHECK | Defence in depth (v2 §M). Handles remain the primary authorisation (C-4) |
| Setting the org | `SET LOCAL app.org_id` **inside each transaction**, first statement. A session-level `SET` is forbidden (CI lint) | With transaction-mode pooling, a session `SET` leaks to the next client of the connection `[INFERENCE: standard PgBouncer semantics]` |
| Missing org | `current_setting('app.org_id', true)` returns NULL, so no row matches: fail closed | — |
| Cross-org operations | The auditor and erasure orchestrator use a separate `auditor` role with BYPASSRLS, on a separate service identity with an allow-list. They are audited | The only cross-org reads |
| Pooling | The Gateway is the **only** client. Cloud SQL connector + IAM auth. Per-instance pool size × max Gateway instances ≤ `max_connections` × 0.8 `[UNMEASURED]`. Add a pooler (PgBouncer transaction mode or the managed pooler) only if Gateway autoscaling exceeds that | Contained surface (M-1) |
| Timeouts | `statement_timeout`, `lock_timeout` and `idle_in_transaction_session_timeout` per role `[UNMEASURED]` | Noisy-neighbour and deadlock containment |

## 5. Transactions, lock order, concurrency

**Commit transaction** (extraction):
1. `SET LOCAL app.org_id`.
2. `SELECT … FOR UPDATE` on the `subjects` rows of the target member set, **in ascending `subject_id`** (R-21, prototype `lockorder`). Merge, undo and erasure lock the full member set in the same order.
3. Fence checks against the stamped epochs; deferral if an identity event is unknown (C-1a).
4. Insert claims, support and transitions. Apply retraction records (LA-9).
5. Re-resolve affected slots (`slots` upsert).
6. Update `evidence_meta.extraction_state`.
7. Insert outbox and memory_events rows.
8. Advance nothing else.

The FS commit record is written **before** the PG transaction, as part of the job, idempotently. PG can then always be rolled forward from it.

**Deadlock handling.**
- With the global order, a deadlock is a bug.
- Postgres still detects deadlocks and aborts one transaction. The Gateway retries with jitter, up to N times `[UNMEASURED]`, and counts aborts by cause (VM-CON telemetry).

**Concurrent writes.** Per-subject serialisation is the unit. Hot subjects (shared numbers, large ACCOUNT scopes) are the contention points: M-13 and the scale table in the red team.

**Isolation level.** READ COMMITTED with explicit row locks is enough, because every invariant-relevant read happens under the subject locks.
- SERIALIZABLE is rejected: retry storms at hot subjects, and no added safety given the lock discipline `[INFERENCE]`.
- **This must be validated by the VM-CON integration suite against real PG (Lane C).**

## 6. Indexes (minimum)

| Index | Serves |
|---|---|
| claims (org_id, subject_id, key, status) | Resolution, retrieval |
| claims GIN (merge_ids) | Undo quarantine |
| claims (org_id, extractor_version) | Re-extraction (C-9) |
| claim_support (org_id, evidence_id) | Erasure by evidence, withdraw, seal re-verification |
| claim_support (org_id, source_member_id) | Erasure of merged members |
| retraction_records (org_id, member, key, value) | LA-9 check on every new claim |
| evidence_meta (org_id, subject_id, extraction_state, receipt_seq) | Job preparation, sweepers |
| knowledge_contributions (org_id, subject_id) | Erasure and undo of contributions |
| claims_search GIN (tsv), GIN trigram | search_memory (M-11) |

**The vector projection** (pgvector) is a separate table with its own rebuild job and hit re-validation. It is created only on the measured trigger (v2 §G).

## 7. Backups, PITR, replication, failover

| Concern | Design |
|---|---|
| Backups | Automated daily, retention ≤ the legal erasure deadline `[BLOCKED:Legal]` |
| PITR | Enabled. WAL retention ≤ the same window |
| Restore | Only through the restore protocol (`memory-restore-protocol-v1.md`): WORM replay plus recorded-decision roll-forward (LA-1) plus watermark (LA-10). Proven in the prototype over 2,000 random restore scenarios |
| Replication | Regional HA where the RPO/RTO decision requires it. A read replica serves `gateway_ro`, which reads only data that tolerates lag (search, history), never the slot for an OCC command |
| Cross-region | Only where residency allows. Per physical tenant |
| Failover | Clients retry. An in-flight commit either committed (the FS commit record exists, PG has rows) or didn't (the job is redelivered). Idempotent by own-derivation ids (LA-4) |
| Region alignment | Firestore and Cloud SQL in the same region (asia-south1 suggested by runtime comments `[UNRESOLVED]` for dedicated tenants) |

## 8. Can the schema preserve the invariants? (checked against the prototype)

| Invariant | Schema mechanism | Prototype evidence |
|---|---|---|
| INV-1 support | FK claim_support → evidence_meta; seal state in evidence_meta; withdraw invalidates | `test_redteam_properties` (1,000 seeds × 150 steps) |
| INV-2 erased evidence never supports | Fence in the commit transaction on stamped epochs; subject locks | Same, plus C-1 tests |
| INV-3 head = rebuild | `slots` is a projection; rebuild query = resolver | Property suites; shadow differ planned (H-4) |
| INV-4 isolation | RLS + `SET LOCAL` + handles | Handle fuzz in the prototype. **RLS itself is untested until Lane C** |
| INV-5 erasure completeness | Registry-driven handlers + auditor | Registry check; drills are Lane B/C |
| INV-6 monotonic epochs | Epochs in FS bindings + WORM high-water | `test_restore` (2,000 seeds) |
| INV-7 idempotency | Own-derivation ids (LA-4/LA-11), dedup keys, the outbox UNIQUE constraint | Retry checks in the property suite |
| INV-11/12 | knowledge_contributions + k; commitment_events projection | `test_redteam_findings`, `test_catalog` |

**Residual risk:** RLS policies, `SET LOCAL` under real pooling, lock behaviour, and query plans are **not** validated by a pure model. They are Lane C gates (roadmap C1/C2, VM-AUTH I, VM-CON I, VM-PERF).
