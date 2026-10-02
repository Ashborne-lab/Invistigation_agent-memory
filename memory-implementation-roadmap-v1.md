# Memory Implementation Roadmap v1

**Date:** 2026-09-30.

**Classification:** TARGET ARCHITECTURE plan. It contains no code.

**Inputs:**
- `memory-architecture-v2.md` (v2);
- `memory-architecture-v2-red-team.md` (RT). Its required changes are cited as **R-n**, its findings as **C-n / M-n**, and the v2 security gates as **S0-n**.

**How to read it.**
- The roadmap is a **dependency graph of work packages (WPs)**, not a timeline.
- A WP can start as soon as all its dependencies are complete.
- Each WP names its lane:

| Lane | Can start when |
|---|---|
| **A** | Now, in read-only or investigation mode |
| **B** | The security fixes (S0) have landed |
| **C** | PostgreSQL infrastructure exists |
| **D** | The missing repositories are available |
| **E** | An owner or legal decision has been made. Until then, the WP ships with a safe default behind a flag |

**Rule.** No WP writes memory data in production until **G-SEC** (the security gate) and **G-ERASE** (the erasure gate) have both passed.

---

## 1. Dependency graph

```text
Lane A (now)                 Lane B (after S0)            Lane C (PG)                  Lane D/E
───────────                  ─────────────────            ──────────                   ────────
A1 core-hardening ─────────────────────────────────────► C2 gateway-core
A2 real-model harness ─► A3 L1-real baseline ──────────► C2
A4 registry schema  ─────────────────────────────────►  C3 registry+orchestrator(PG)
A5 store census (legacy) ─► B3 erasure-legacy ──────────► C3
A6 predicate ownership ──► B5 derivation-fence lib ─────► C5 integration
A7 schema + migrations design ──► C1 PG infra ──► C2 ──► C4 ingest-registration ─► C5 ─► C6 cutover
A8 restore-drill design ──────────────────────────────►  C7 DR drills
A9 red-team suites ─► (gates every C*)
S0 security (B0) ─► G-SEC ─► B1 binding txn + seal ─────► C4
                         ─► B2 memory handle ────────────► C5
                         ─► B4 Lumen isolation
B3 + C3 ─► G-ERASE
D1 noesis-os ─► S0-1, R-4 UI         D2 voice-gateway ─► voice in C5
D3 olbrain-llm ─► C2 adapter (prod)   D4 billing/analytics ─► C3 handlers (prod)
E* decisions ─► flags flipped (never block construction)
```

**Critical path:** B0 (S0 security) → B1 (binding transaction plus seal) → C4 (ingest registration) → C5 (retrieval and context integration) → C6 (org cutover).

**Can run in parallel from day one:** every A-lane WP, and C1 (PG provisioning, once infrastructure approval exists).

---

## 2. Gates

| Gate | Passes when |
|---|---|
| **G-SEC** | All of the following are in place in the target environments: S0-1…S0-10 (v2 §M.1), S0-11 (share tokens, M-5), and the Lumen row isolation fix (C-6). Each has emulator or integration tests, and a security owner has signed off |
| **G-ERASE** | Across **all registered legacy stores**, an erasure drill leaves zero surviving rows, and the completeness auditor has run clean for 14 days in staging `[UNMEASURED window]` |
| **G-CORE** | L1 deterministic suites pass with zero failures; the blocking metrics are at zero; the L1-real baseline is recorded (it is not a threshold) |
| **G-DR** | Restore drills for Firestore only, PG only and both pass (RT §L) |
| **G-SHADOW** | Shadow extraction has run for at least N days per org `[UNMEASURED]`, the diff is reviewed, and there are zero isolation-fuzz hits |
| **G-CUTOVER** | L2 passes for the org's surfaces; the org owner has approved; rollback has been rehearsed |

---

## 3. Work packages

### Lane A: can begin now (read-only or investigation workspace)

#### A1: Harden the pure core against red-team findings
| Field | Detail |
|---|---|
| Objective | Extend `investigation/memory-prototype` so it implements R-1 (stamps as inputs), R-2 (sealed hash), R-9, R-10, R-14, R-15, R-16, R-12 (structured render) and R-21 (lock-order model) as pure logic |
| Dependencies | None |
| Repositories and services | `investigation/memory-prototype` only |
| Artifacts | Updated core; decision flags for each R-change; an updated findings document |
| Tests | New scenarios in the validation matrix: VM-SEM, VM-TMP, VM-CS, VM-CM, VM-MOD |
| Security gates | None (no production contact) |
| Migration gates | None |
| Rollback | A git revert in the workspace |
| Observability | The benchmark emits results per finding |
| Complete when | All new scenarios pass under the amended config; the spec config still reproduces the original defects |

#### A2: Real-model extraction harness
| Field | Detail |
|---|---|
| Objective | A provider adapter for the proposal protocol, run against the Lane-1 dataset with a real model, recording the composite extractor version |
| Dependencies | None. It needs an API key in a **sandbox** account, never production data |
| Repositories and services | Prototype only. The adapter interface is designed for later reuse in `olbrain-llm` (D3) |
| Artifacts | Adapter; recorded proposals; a per-language recall report |
| Tests | VM-MOD model evaluation |
| Security gates | Synthetic data only |
| Migration gates | — |
| Rollback | — |
| Observability | Per-proposal accept and reject codes |
| Complete when | The baseline is recorded for the current model (this is **A3**) |

#### A3: L1-real baseline
| Field | Detail |
|---|---|
| Objective | Record the real-model baseline over `lane1_v1` plus the red-team scenarios (future markers, cross-script, injection, narrative laundering) |
| Dependencies | A2 |
| Repositories and services | Prototype only; a sandbox provider account |
| Artifacts | `benchmark/results/real-<model>.json`; a per-language report |
| Tests | VM-MOD, VM-SEM M, VM-INJ M |
| Security gates | Synthetic data only |
| Migration gates | — |
| Rollback | — |
| Observability | Accept and reject codes per proposal; the composite extractor version |
| Complete when | The baseline is recorded and reviewed. **No thresholds are invented**; owners set them from this baseline |

#### A4: Registry schema design
| Field | Detail |
|---|---|
| Objective | Specify the schema-driven Lifecycle Registry (R-7): the declaration format, `subject_columns`, the handler contract (`done`, `partial`, `not_applicable`, `retained_legal_basis`), and the CI lint rules |
| Dependencies | None |
| Repositories and services | Investigation documents |
| Artifacts | A registry specification, and a registry entry draft for every store in MAP §3 and §4 plus the v2 tables |
| Tests | A review against MAP §4: every surviving store has an entry |
| Complete when | No store in the MAP is missing an entry |

#### A5: Legacy store census for erasure
| Field | Detail |
|---|---|
| Objective | A per-store erasure design for every legacy store in MAP §4: the keying available today, the lookup that finds a subject's rows, the missing indexes, and the soft-delete fixes |
| Dependencies | A4 |
| Repositories and services | Read-only tracing of all 13 repositories; the missing ones are marked |
| Artifacts | An erasure census table (store, key, lookup path, handler design, gap) |
| Tests | Review: every MAP §4 survivor appears |
| Security gates | — |
| Migration gates | — |
| Rollback | — |
| Observability | The census is an input to the auditor's scan list |
| Complete when | Every store has a handler design or an explicit `[UNRESOLVED: missing repo]` |

#### A6: Predicate ownership registry
| Field | Detail |
|---|---|
| Objective | Assign every person-describing attribute in the MAP to exactly one owning system: identity, lead engine, memory, analytics or workflow (R-6) |
| Dependencies | None |
| Repositories and services | Investigation only |
| Artifacts | An ownership table; the list of prompt paths that must change their source; the list of derived writers for B5 |
| Tests | Review: no attribute has two owners |
| Security gates | — |
| Migration gates | Input to C6 legacy classification |
| Rollback | — |
| Observability | — |
| Complete when | Every attribute found in `cs_packet_builder` inputs, the lead tools and the session fields has an owner |

#### A7: PostgreSQL schema and operations design
| Field | Detail |
|---|---|
| Objective | The v2 §V schema with the RT changes: proposals, commitment events, `search_tokens`, scope tagged unions, partitions, RLS policies, the role model, `SET LOCAL` discipline and expand/contract rules |
| Dependencies | None |
| Artifacts | A schema document; a partition and retention plan; a connection and pooling plan; a capacity model marked `[UNMEASURED]` |
| Tests | A schema review; a load-test plan (VM-PERF) |
| Complete when | Every RT finding that touches storage is mapped to a schema element |

#### A8: Restore drill design
| Field | Detail |
|---|---|
| Objective | The restore protocol runbook (RT §L), the WORM ledger and `identity_events` formats, the epoch high-water-mark semantics, and the drill specifications |
| Dependencies | A4, A7 |
| Repositories and services | Investigation |
| Artifacts | A runbook; the drill specification; the ledger format |
| Tests | Tabletop walk-through of all three restore cases |
| Security gates | The ledger is PII-free by construction (review) |
| Migration gates | — |
| Rollback | — |
| Observability | Defines the DR metrics in VM-DR |
| Complete when | Every restore case has a deterministic reconciliation step |

#### A9: Red-team test suites
| Field | Detail |
|---|---|
| Objective | Author the adversarial suites: the isolation fuzzer specification, the injection and poisoning corpora (including narrative laundering), the Lumen OR/UNION/comment probes, the spoofing cases |
| Dependencies | None |
| Repositories and services | Prototype and investigation. The probes run **only in staging, later** |
| Artifacts | Corpora; fuzzer specification; probe list |
| Tests | Traceability to every RT finding (VM §4) |
| Security gates | Probes are never run against production |
| Migration gates | — |
| Rollback | — |
| Observability | — |
| Complete when | Every C-* and M-* finding has at least one executable adversarial case |

---

### Lane B: begins once the security fixes land (production repositories; each WP needs explicit owner approval to change code)

#### B0: Security prerequisites (G-SEC)
| Field | Detail |
|---|---|
| Objective | S0-1…S0-11 plus the Lumen isolation fix |
| Dependencies | **D1** (noesis-os) for S0-1's client query inventory. The others are independent |
| Repositories | `olbrain-agent-runtime` (rules, webhook, `require_permission` callers); `olbrain-studio-backend` and `olbrain-agent-design` (`auth.py`); `olbrain-agent-engine` (Lumen, Cortex markers, N7); `olbrain-mcp-deployer` (N8); `firestore.rules`; `olbrain-studio` (client query changes); `olbrain-noesis-os` |
| Artifacts | Rules changes; auth fixes; share tokens; Lumen views and row policies |
| Tests | Rules emulator suites (cross-tenant read and write denied); IDOR tests; a Lumen OR/UNION probe returns zero foreign rows |
| Security gate | Security owner sign-off |
| Rollback | Per-change feature flags where possible. Rules are deployed with a staged rollout and a tested prior version |
| Observability | Denied-access counters; alerts on rule-denial spikes (client breakage) |
| Complete when | G-SEC |

#### B1: Evidence binding transaction and sealing (R-1, R-2, R-3, R-23, R-24)
| Field | Detail |
|---|---|
| Objective | The runtime's message write becomes a Firestore transaction: binding read, stamps, `receipt_commit_ts`, the optional `inbound_dedup`. Sealing happens after the turn settles, plus a seal-by-timeout sweeper. Erasure and every identity operation write the binding plus an `identity_events` record first |
| Dependencies | B0 (so that clients cannot write the binding or sealed fields); A1 (semantics) |
| Repositories | `olbrain-agent-runtime` (`lightweight_processor.py` save paths, `agent_webhook.py`, `meta_whatsapp.py`, `directives.py`); rules |
| Tests | Emulator: concurrent first contact produces one subject; erasure racing a write; the dedup of a redelivered `wamid`; latency on the voice path |
| Security gate | The binding and sealed fields are server-only (rules test) |
| Migration gate | Writes the new fields only; old readers are unaffected |
| Rollback | A flag reverts to a plain write. Stamps then stop and registration pauses, which fails closed |
| Observability | Binding-transaction latency and contention; dedup hits; seal lag |
| Complete when | The voice p50 delta is measured and accepted by the voice owner `[UNMEASURED]`, and the emulator suite passes |

#### B2: Memory handle issuance (R-4)
| Field | Detail |
|---|---|
| Objective | Conversation-bound signed handles (org, agent, session, subject, assurance, allowed scopes, member-set version) issued at the binding transaction, and operator reads with pass-through end-user tokens |
| Dependencies | B1; C2 for verification; D1 for the operator pass-through |
| Repositories and services | runtime; Gateway; KMS; noesis-os (operator) |
| Artifacts | Handle format; issuance and verification; a key rotation procedure |
| Tests | VM-AUTH: swapped-id fuzz; expiry and audience; replay after undo |
| Security gates | Security owner review of the handle format and key custody |
| Migration gates | Required before any C5 read path |
| Rollback | Reads are disabled (render "unavailable"), never re-opened without handles |
| Observability | Verification failures by cause; issuance rate |
| Complete when | The fuzz suite shows zero cross-subject rows |

#### B3: Legacy erasure over existing stores (phase-1 erasure)
| Field | Detail |
|---|---|
| Objective | The Erasure Orchestrator and handlers for **legacy** stores, using A5. Fixes the soft deletes and the Shopify redact handler, makes traces and MCP logs subject-addressable, and fixes the KV delete races |
| Dependencies | A4, A5, B0. The WORM bucket is needed (no PG required; the ledger can start in Firestore plus WORM and move to PG in C3) |
| Repositories | runtime; engine; research-runtime; research-design; workflow-runtime; knowledge-vault; mcp-deployer; shared |
| Tests | VM-DEL erasure drills; the completeness auditor |
| Security gate | Online authorisation of erasure requests |
| Rollback | Handlers are idempotent. A failed handler leaves the request `partial` and alerting (never silently complete) |
| Observability | Per-store completion age; auditor hits |
| Complete when | G-ERASE |

#### B4: Lumen row isolation
Part of B0. It is listed separately because it is the only VERIFIED CURRENT cross-tenant retrieval path the red team found.

| Field | Detail |
|---|---|
| Objective | Replace the regex check with server-side isolation: an authorised view or row-access policies with the `agent_id` bound as a parameter |
| Dependencies | None (security owner approval) |
| Repositories and services | `olbrain-agent-engine` (`alchemist/agents/lumen/evidence/bigquery.py`, `services/bigquery_service.py`); BigQuery dataset `service_logs` IAM |
| Artifacts | Views and policies; a Lumen tool change |
| Tests | Staging probes with OR, UNION, comment and string-literal bypasses return zero foreign rows |
| Security gates | Security owner sign-off |
| Migration gates | — |
| Rollback | Disable the Lumen BigQuery tool (the safe fallback) |
| Observability | Rejected-query counts; query audit labels (the existing `app=axon`) |
| Complete when | The probes pass in staging and production |

#### B5: The derivation-fence library (R-6)
| Field | Detail |
|---|---|
| Objective | A shared library in `olbrain-shared` that every non-Gateway writer of person-derived data uses: judges, dispositions, titles, lead capture, `agent_users`, exports |
| Dependencies | B1 (stamps), A6 |
| Repositories | shared; runtime; engine |
| Tests | The resurrection property test extended to these writers; a CI lint for direct writes |
| Rollback | A flag to warn-only mode |
| Complete when | Every writer on the A6 list is migrated, or retired as a prompt source |

---

### Lane C: requires PostgreSQL infrastructure

#### C1: PostgreSQL infrastructure
| Field | Detail |
|---|---|
| Objective | Cloud SQL HA per physical tenant; IAM auth; the connector; PITR; the backup retention placeholder `[BLOCKED:Legal value]`; a cross-region replica only where residency allows |
| Dependencies | A7; an infrastructure owner; RPO/RTO decisions (E) |
| Services | GCP projects (shared plus dedicated). IaC is required: none exists today for `olbrain-india-prod` (MAP §3) |
| Tests | Failover drill; PITR restore to staging |
| Security gate | Private IP; no public endpoint; IAM-only roles; audit logging on |
| Rollback | Not applicable (empty instance) |
| Observability | Connections; replication lag; bloat; autovacuum; storage |
| Complete when | Staging and one production instance are provisioned by IaC |

#### C2: Memory Gateway core service
| Field | Detail |
|---|---|
| Objective | A service wrapping the hardened pure core (A1): gate, commit, fence, resolver, typed retrieval, explain, the proposals table, the outbox and events |
| Dependencies | A1, A3, C1 |
| Repositories and services | A new service repository `[DECISION: separate service, not inside the runtime]`, with a single PG client |
| Tests | L1 against real PG; concurrency properties (VM-CON); `SET LOCAL` lint |
| Security gate | Service identities with per-operation allow-lists; handle verification (B2) |
| Rollback | Not in the serving path until C5 |
| Observability | v2 §R, plus RT M-15 |
| Complete when | G-CORE on real PG |

#### C3: Registry and orchestrator on PostgreSQL
| Field | Detail |
|---|---|
| Objective | The erasure ledger in PG, mirrored to WORM; the v2 stores (manifests, events, proposals, outbox) in the schema-driven registry; the MEMBER erasure class with handlers disabled until Legal decides |
| Dependencies | B3, C2 |
| Repositories and services | Gateway; WORM bucket |
| Artifacts | Ledger tables; registry CI lint; MEMBER handlers |
| Tests | VM-DEL I drills that include the v2 tables; the schema scan for unregistered subject columns |
| Security gates | Online authorisation of erasure requests |
| Migration gates | The Firestore-based ledger from B3 is migrated without gaps (every request id is present in both) |
| Rollback | Keep the B3 ledger authoritative until parity is verified |
| Observability | Ledger mirror lag; per-store completion |
| Complete when | Drills are clean, and the CI lint is active |

#### C4: Evidence registration and shadow extraction
| Field | Detail |
|---|---|
| Objective | The register call after sealing; a sweeper over unregistered messages; the outbox; extraction in **shadow** (writes claims, nothing reads them) |
| Dependencies | B1, C2, C3 |
| Repositories | runtime (register call); Gateway |
| Tests | Ingest failure matrix (RT §K); fence property tests; resurrection tests |
| Migration gate | Shadow only. The legacy extractor continues |
| Rollback | Stop registration (flag). Shadow data is discarded |
| Observability | Registration lag; sweeper backlog; fence rejections; accept and reject mix |
| Complete when | G-SHADOW for the pilot org |

#### C5: Retrieval, context compiler and integration
| Field | Detail |
|---|---|
| Objective | Typed operations through handles; the compiler (R-12, R-25, tiers, manifests with candidates, truncation and block hash); Agent Knowledge approved-by-id loading; commitment events and mirrors (R-10); dual read per org behind a flag |
| Dependencies | C4, B2, B5. Voice also needs D2; the directives path needs D5 |
| Repositories and services | runtime (`cs_packet_builder.py` memory sources, config loading); Gateway; engine (Dendrite and config by id); workflow-runtime (overrides move to workflow rules) |
| Artifacts | Compiler; `memory_profile` in the published config; commitment reconciler |
| Tests | L2 personas; VM-CTX, VM-INJ, VM-RET; isolation fuzz; manifest replay |
| Security gates | G-SEC; handles in use; no person-content caches (INV-14) |
| Migration gates | Dual read only for pilot orgs; the legacy path remains the fallback |
| Rollback | Flag per org back to the legacy context |
| Observability | Truncation per tier; the retrieval failure rate; cost per turn |
| Complete when | L2 passes for the pilot org's surfaces |

#### C6: Org cutover and legacy retirement
| Field | Detail |
|---|---|
| Objective | Cutover per org (R-18); the legacy write guard plus a revision floor; quarantine, then erasure of legacy stores; migration of M4–M8 into Agent Knowledge (k threshold, PII check) |
| Dependencies | C5, G-DR, G-CUTOVER |
| Repositories and services | runtime; research-runtime and research-design (M5); workflow-runtime (M6); engine (M7 and M8); deploy policy (revision floor) |
| Artifacts | Cutover runbook per org; legacy classification record; quarantine reports |
| Tests | VM-MIG drills: mixed revisions, rollback attempt, erasure during dual-run |
| Security gates | Legacy verbatim stores are quarantined before any re-derivation |
| Migration gates | Org owner approval; diff reviewed |
| Rollback | Before legacy writes stop: flip the flag back. After: forward-fix only |
| Observability | Legacy writes after cutover must be 0; diff rate |
| Complete when | The auditor is clean for 30 days `[UNMEASURED]`, and the legacy stores are erased |

#### C7: DR drills
| Field | Detail |
|---|---|
| Objective | Quarterly restore drills: Firestore only, PG only, and both |
| Dependencies | A8, C3, C4 |
| Repositories and services | Staging projects; Cloud SQL; Firestore PITR |
| Artifacts | Drill reports |
| Tests | VM-DR: INV-5 and INV-6; reconciliation counts |
| Security gates | Restored data stays in staging projects with production-equivalent IAM |
| Migration gates | G-DR precedes C6 |
| Rollback | — |
| Observability | Time to recover, and records reconciled per drill |
| Complete when | Three consecutive clean drills |

---

### Lane D: requires the missing repositories

| WP | Repository | Unblocks | When needed |
|---|---|---|---|
| D1 | `olbrain-noesis-os` | S0-1 query inventory; the operator explain UI; the end-user token pass-through (R-4) | Before B0 completes |
| D2 | `olbrain-voice-gateway` | ANI attestation (M-5); seal timing; the straggler contract | Before voice in C5 |
| D3 | `olbrain-llm` | The production extraction adapter; metering; the subprocessor inventory | Before C4 in production (A2 can proceed without it) |
| D4 | Billing service, `olbrain-cloud-functions`, `olbrain-analytics-service` | Pseudonymous keys; erasure handlers; `payments` idempotency | Before G-ERASE in production |
| D5 | `agent-directives`, the webhook service, the admin dashboard | Outbound evidence; `client_message_id`; admin PII views | Before C5 integration |

### Lane E: requires owner or legal decisions (never blocks construction)

| Decision | Flag or default | Unblocks |
|---|---|---|
| R-M1 inference | `inferred`: reject | Persisted inference |
| R-M2 customer text in Agent Knowledge | Strict filter | Richer learned guidance |
| R-M3 evidence and proposal retention | Unset; proposals kept 90 days `[UNMEASURED]` | TTL jobs |
| R-M4 `memory:read` roles | Named role only | Operator explain |
| Erasure archive window; backup retention | Unset (alert) | Physical deletion; backup compliance |
| Voice ANI assurance | Asserted | Voice memory continuity |
| Conversation-sourced ACCOUNT facts | None | Account memory richness |
| Transfer between controllers | Disabled | D15 transfer copy |
| Suppression HMAC and returning persons | Keep the suppression entry | — |
| Member erasure | Handlers disabled | Employee erasure |
| RPO/RTO | — | C1 sizing |
| Trusting asserted ids from an org's server | Off | API integrations with continuity |

---

## 4. What must never happen out of order

1. No production memory writes (including shadow) before **G-SEC**. With `agent_messages` client-writable, evidence can be forged (RT C-2).
2. No new store holding person data before **G-ERASE**. Otherwise the erasure debt grows.
3. No reads from the new store in prompts before **handles** (B2) and the **structured render** (R-12).
4. No legacy write stop before the **revision floor** is enforced (R-18).
5. No model change in production without an **L1-real** diff and a shadow backfill (R-9).
