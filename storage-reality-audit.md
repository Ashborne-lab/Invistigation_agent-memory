# Storage Reality & Ambiguity Audit

**Date:** 2026-09-22
**Type:** read-only investigation, document-only output. No schema was designed, no migration
planned, no implementation performed.

### Labelling discipline

Every statement carries one of these. They are never merged, and nothing is upgraded from one
to another by inference.

| Label | Meaning |
|---|---|
| `CURRENT FACT` | Verified against repository source this session, at the HEADs in §18 |
| `TARGET REQUIREMENT` | Stated by `artifacts/architecture-contract.md` |
| `PROPOSED` | Suggested in an investigation document; not approved |
| `UNKNOWN` | Repository evidence insufficient. **Not** inferred |
| `DECISION REQUIRED` | Needs an owner's input before it can be settled |

---

## 1. Purpose

Answer one question before any PostgreSQL schema, migration or production change is designed:

> **What storage infrastructure does OLBrain actually use today, how is it used, and what is
> still unknown before we can safely design the target PostgreSQL implementation?**

The prior investigation passes were memory- and state-focused and mapped Firestore
collections against the target semantic model. **They never audited PostgreSQL.** The target
contract names PostgreSQL as the MVP realisation, which makes "does OLBrain already run
PostgreSQL, and if so where and for what?" a question with implications for every later
decision. This audit answers it directly.

Where this audit found ambiguity it **records the ambiguity rather than resolving it** (§14).

## 2. Executive Findings

**F1 — PostgreSQL is not OLBrain's persistence layer today, in any service.** `CURRENT FACT`

Exactly one repository declares a PostgreSQL driver: `olbrain-agent-runtime`,
`asyncpg>=0.29.0`. It is used for a single purpose — an **outbound, read-only query capability
through which an agent queries a customer's or third party's database**. It is one of four
providers (`dynamics365`, `dynamics365_fno`, `postgres`, `salesforce`) behind a `data_query`
tool. OLBrain neither owns nor writes those databases.

There is **no** ORM, no migration framework, no schema definition, no model layer, no
`DATABASE_URL`, no Cloud SQL reference, no RLS, no pgvector, no outbox table and no job table
anywhere in the ten repositories.

**F2 — Firestore is the sole authoritative persistence for everything this programme cares
about.** `CURRENT FACT` All ten repositories use the Firestore client; 496 source files
reference it.

**F3 — The real Firestore surface is materially larger than the prior inventory.**
`CURRENT FACT` `olbrain-agent-engine/alchemist/constants/collections.py` is a canonical
registry declaring roughly **45 collections**. The prior `store-inventory.md` covers about 30,
selected for memory/state relevance. Names never previously inventoried include `secrets`,
`permissions`, `team_memberships`, `audit_logs`, `credit_transactions`, `billing_accounts`,
`agent_traces`, `mcp_tool_executions`, `agent_deployments`, `agent_configurations`,
`prompt_templates`, `feature_flags` and `compliance_reports`. **Declaration in a registry is
not proof of live use** — `knowledge_embeddings` is declared there and is known-dead — so this
is recorded as a scope gap, not as 15 new live stores (see AMB-03).

**F4 — Redis is a dormant declared dependency, not infrastructure.** `CURRENT FACT`
`redis>=5.0.0` is in `olbrain-agent-runtime/requirements.txt` and `redis_url` /
`rate_limit_storage` exist as settings fields, but **no Redis client is imported anywhere in
application code**. `rate_limit_storage` defaults to `"memory"`, `redis_url` defaults to
`None`, and `REDIS_URL` appears only in a local `docker-compose.yml`. Nothing in production
configuration sets it.

**F5 — BigQuery is real, OLBrain-owned, and used for analytics/audit, not memory.**
`CURRENT FACT` Two independent uses: agent-engine's Lumen agent runs SELECT-only aggregate
evidence queries with a **server-side enforced `agent_id` filter** (`QueryRejected` if
missing, explicitly "not LLM-trusted"), and `olbrain-studio-backend/routes/audit_routes.py`
queries it with parameterised jobs. This is consistent with the contract's
`Analytics — Separate pipeline and system from customer memory`.

**F6 — A persistence layer the prior investigation never recorded: Firebase Realtime
Database.** `CURRENT FACT` `olbrain-agent-design/app/services/rtdb_service.py` writes
`/agentAccess/{agentId}/{userId}` for editor cursor visibility; `olbrain-studio`'s
`cursorService.js` reads it. Feature-flagged, silent no-op when `FIREBASE_DATABASE_URL` is
unset, and write failures are deliberately swallowed. This is **ephemeral collaboration
presence**, not state or memory in the contract's sense.

**F7 — Firestore transactions are concentrated in one repository and largely absent from the
memory/state stores.** `CURRENT FACT` `@firestore.transactional` appears mostly in
`olbrain-agent-design` (agent, brain, draft-field services) and in two agent-engine *lease*
claims. The person-keyed memory write path uses no transaction at all.

**F8 — One prior claim was tested and survives, with a material refinement.** `CURRENT FACT`
`vibe_sessions.active_conversant.state` **is** written inside a Firestore transaction
(`transition_to`, `@firestore.transactional`) and carries a genuine provenance field,
`last_transition_event_id`. **But the transaction validates only that the document exists.**
There is no from-state check and no `expected_status`; `InvalidTransitionError` is raised
solely on not-found, despite its name. Atomicity yes; transition legality no. Every other
`vibe_sessions` write is a plain non-transactional `.set()` / dotted-path `.update()`.

**F9 — `agent_datastores` is three code paths over two key spaces, and the collision between
two of them is acknowledged in the source.** `CURRENT FACT` See §11. The operator writer's own
comment states that the extractor "guards the same thing on its own side of **this same
document**." The coexistence is deliberate; what is absent is any representation of which
writer's value should win.

## 3. Current Firestore Architecture

`CURRENT FACT` throughout this section. Firestore is the authoritative store for agents,
configuration, sessions, messages, memory, learned material, workflow and research state.

### 3.1 Access pattern by repository

| Repository | Firestore files | Access style |
|---|---|---|
| `olbrain-studio` | 166 | **Browser client SDK** — direct reads/writes from the user's browser |
| `olbrain-studio-backend` | 75 | Admin SDK, server-side |
| `olbrain-agent-runtime` | 60 | Admin SDK, server-side |
| `olbrain-shared` | 36 | Admin SDK helpers shared by every Python service |
| `olbrain-agent-engine` | 33 | Admin SDK |
| `olbrain-agent-design` | 32 | Admin SDK |
| `olbrain-research-runtime` | 45 | Admin SDK |
| `olbrain-research-design` | 21 | Admin SDK |
| `olbrain-workflow-runtime` | 17 | Admin SDK |
| `olbrain-knowledge-vault` | 11 | Admin SDK |

The `olbrain-studio` row is the architecturally significant one: a **browser client talks to
Firestore directly**, which is why the security-rules layer (not the REST layer) is the real
authorization boundary for anything Studio reads.

### 3.2 Verified collection inventory — memory and state relevant

Carried forward from `store-inventory.md` where that document's evidence stands, with this
session's verifications marked. Columns: Auth = the binding authorization layer; Org = whether
the *record itself* carries an organization key.

| Path | Service (writer) | Readers | Auth boundary | Org scope | Purpose | Status | Deletion |
|---|---|---|---|---|---|---|---|
| `agent_user_memory/{agent}__{hash}` | agent-runtime | agent-runtime prompt builder | Rules: org-scoped read, server-only write | **Y** on doc | Per-person memory blob | IN-FLIGHT MIGRATION | GDPR route, 404-oracle-safe |
| `agent_datastores/{agent}/tables/{t}/entries/{e}` | **3 writers** (§11) | prompt builder (unconditional), Studio operator UI | Rules: **fully denied to all clients**, tested | **N** on entry, Y on table | Structured per-person / per-session rows | IN-FLIGHT MIGRATION | Hard delete via agent-design route |
| `agent_learned_patterns/{agent}/patterns/{id}` | agent-runtime | agent-runtime | Rules: **open r/w/create/delete** | **N** | Tool-sequence heuristics | VERIFIED CURRENT · `NO V2.0 TARGET MAPPING` | none found |
| `agent_sessions/{id}` | agent-runtime | Studio, Noesis (browser), runtime | Rules: **open r/w** | Y | Session record + `.summary` | VERIFIED CURRENT | none found |
| `agent_messages/{id}` | agent-runtime | Studio, Noesis, runtime | Rules: **open r/w** | PARENT | Per-turn record, plaintext | VERIFIED CURRENT | none found |
| `lead_profiles`, `lead_contacts` | agent-runtime | agent-runtime | API key + org match | Y / Y | Contact records | VERIFIED CURRENT | per-call and org-wide erase |
| `context_logs/{scope}/events/{id}` | agent-engine | agent-engine | Rules: **open r/w** (tighter rule dormant) | via scope_key | Append-only event log | VERIFIED CURRENT | **none — no erasure path** |
| `context_facts` | agent-engine | agent-engine | Rules: **open r/w**, no rule at all | same caveat | Bi-temporal extracted facts | VERIFIED CURRENT; promotion flag-disabled | invalidate-only, retained forever |
| `context_guardrails` | agent-engine | agent-engine | Rules: **open r/w**; app CRUD dark | same caveat | Scoped guardrails | VERIFIED CURRENT | n/a |
| `vibe_sessions/{id}` | agent-engine | agent-engine, Studio | Rules: **open r/w** | optional, set-once | Design session + state machine | VERIFIED CURRENT | soft-delete only, no TTL |
| `research_templates/{id}` (+ `learned/*`, `learning_ledger/*`) | research-design | research-design/-runtime | Rules: **open r/w** | Y on template; **N** on learned records | Templates and learned overlays | VERIFIED CURRENT | ledger: "no API to delete one" |
| `research_runs/{id}` | research-runtime | research services | Rules: **open r/w on the parent doc** | Y | Run metadata and phase | VERIFIED CURRENT | none found |
| `workflow_agent_memory/{agent}` | workflow-runtime | workflow orchestrator | **No REST auth; no rule** | **N** (schema-level) | Exception patterns + overrides | VERIFIED CURRENT | per-pattern delete, wipe script |
| `workflow_definitions`, `workflow_runs`, `workflow_items` | workflow-runtime | workflow services | Rules: **open r/w** | Y on defs/runs; items UNKNOWN | Workflow design and execution | VERIFIED CURRENT / IN-FLIGHT | none found |
| `knowledge_library` | knowledge-vault | knowledge-vault | Rules: read open cross-org, write server-only | **N** (resolved via agent doc) | DCI corpus metadata | VERIFIED CURRENT | soft delete |
| `agents/{id}` | agent-design, studio-backend, agent-engine | everything | Rules: **open r/w — most severe finding** | Y | Central ownership record | VERIFIED CURRENT | n/a |
| `agents/{id}/mcp_configs/{server}` | agent-design | agent-runtime | Rules: effectively open | via parent | MCP bindings | VERIFIED CURRENT | n/a |
| `organizations/{org}/connector_credentials/{id}` | studio-backend | studio-backend | Rules: **open, no org predicate at all** | path-scoped | Credential pointers | VERIFIED CURRENT | n/a |
| `organization_api_keys`, `organization_documents` | studio-backend | studio-backend | Org-membership gate | Y | Keys; org docs | VERIFIED CURRENT | api keys: no sweep; docs: **hard delete + deindex** |
| `protection_events` | agent-runtime | internal | internal only | **N** | Audit event stream | VERIFIED CURRENT | none found |

### 3.3 Collections declared but not covered by any prior investigation

`CURRENT FACT` — declared in `olbrain-agent-engine/alchemist/constants/collections.py`.
Reference counts are non-test files across all ten repos.

| Collection | Non-test refs | Investigated before? |
|---|---|---|
| `secrets` | 5 | **No** |
| `permissions` | 1 | **No** |
| `team_memberships` | 2 | **No** |
| `credit_transactions` | 2 | **No** |
| `agent_traces` | 2 | **No** |
| `audit_logs`, `billing_accounts`, `usage_metrics`, `agent_deployments`, `agent_configurations`, `agent_servers`, `mcp_servers`, `mcp_tool_executions`, `alchemist_sessions`, `alchemist_conversations`, `knowledge_repositories`, `knowledge_chunks`, `prompt_templates`, `test_cases`, `test_runs`, `integration_channels`, `channel_configurations`, `user_analytics`, `agent_performance`, `business_intelligence`, `events`, `notifications`, `system_health`, `feature_flags`, `compliance_reports`, `support_sessions`, `tickets`, `aster_threads`, `lumen_sessions`, `agent_qa_runs`, `agent_config_drafts`, `agent_config_actives`, `workflow_proposals` | not individually counted | **No** |

`secrets`, `permissions` and `team_memberships` are the ones that matter most: the first is
credential-adjacent and the other two are authorization-adjacent, and **none has a verified
Firestore-rules verdict**. See AMB-03 and AMB-04.

## 4. Current PostgreSQL Architecture

### 4.1 The thirteen questions, answered

| # | Question | Answer |
|---|---|---|
| 1 | Does OLBrain currently have PostgreSQL in production? | **No — not as OLBrain-owned persistence.** `CURRENT FACT`. The only PostgreSQL contact is an outbound read-only query to a **customer's or third party's** database. |
| 2 | Which services use it? | **One:** `olbrain-agent-runtime`, via `core/tools/_dispatchers/postgres.py`, reached from `core/tools/data_query_executor.py`. `CURRENT FACT` |
| 3 | Which tables/models exist? | **None.** No schema, no model, no table definition anywhere. Queries are operator-authored SQL strings in design-time config. `CURRENT FACT` |
| 4 | Which services own those tables? | **OLBrain owns none of them.** The databases are external. `CURRENT FACT` |
| 5 | Is there a migration framework? | **No.** No Alembic, no `migrations/` directory, no `.sql` file, no Prisma schema in any repo. `CURRENT FACT` |
| 6 | Is there a standard connection/transaction layer? | **No.** `asyncpg.connect(...)` opens a fresh connection per query and closes it in a `finally`. No pool, no session, no transaction wrapper. `CURRENT FACT` |
| 7 | Is there existing RLS? | **No.** Zero occurrences of row-level security anywhere. `CURRENT FACT` |
| 8 | Is pgvector already used? | **No.** No `pgvector`, no `CREATE EXTENSION`, no vector column, no `ivfflat`/`hnsw`. `CURRENT FACT` |
| 9 | Is there outbox/job infrastructure? | **No outbox.** Async work is dispatched via **Google Cloud Pub/Sub** (research-design, research-runtime) and fire-and-forget in-process tasks (agent-runtime). `CURRENT FACT` |
| 10 | Is there a database ownership convention? | **Not for PostgreSQL** — nothing to own. For Firestore, see §6. `CURRENT FACT` |
| 11 | Are there multiple PostgreSQL databases? | Potentially many, all **external**: one per `data_query` capability node per agent config. OLBrain holds credentials for them but owns none. `CURRENT FACT` |
| 12 | Is PostgreSQL only local/test/dev? | **No — it is neither.** It is a live production *client* capability against foreign databases. There is no local, dev or test OLBrain PostgreSQL instance either. `CURRENT FACT` |
| 13 | Is any PostgreSQL usage dormant/legacy? | The driver is live and current. `redis` is the dormant dependency, not `asyncpg` (F4). `CURRENT FACT` |

### 4.2 What the PostgreSQL capability actually is

`CURRENT FACT` — `core/tools/_dispatchers/postgres.py`:

- **Read-only, enforced by regex.** A `_WRITE_KEYWORDS` pattern rejects
  `insert|update|delete|drop|alter|truncate|create|grant|revoke` at the start of the query
  and returns `error_kind: "write_blocked"`.
- **Fresh connection per call**, closed in a `finally`. `ssl` defaults to required unless the
  connection config says `sslmode: disable`.
- **Connection parameters come from config**, not from environment: `host`, `port`,
  `database`, `user`, `password` are read out of a `connection` dict supplied by the agent's
  frozen design-time `data_queries` spec.
- **Row and byte caps** with truncation signalling.
- Registered alongside `dynamics365`, `dynamics365_fno` and `salesforce` in the same
  dispatcher registry — the clearest evidence that this is an *integration* surface.

**Interpretive caution.** This capability demonstrates that OLBrain can *talk* to PostgreSQL.
It demonstrates nothing about OLBrain's readiness to *own* a PostgreSQL database: no schema
discipline, no migration tooling, no connection pooling, no transaction layer, no ORM, and no
operational ownership exist anywhere in the ten repositories. Treating F1 as "we already use
Postgres" would be a material misreading.

### 4.3 PostgreSQL reality table

Per the requested shape. There is exactly one row, and it is not an OLBrain-owned table.

| Table/model | Service | Owner | Readers | Writers | Transaction boundary | Tenant/org key | Versioning | RLS | Purpose | Status | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| *(none — external customer tables, schema unknown to OLBrain)* | agent-runtime `data_query` tool | **External / customer. Not OLBrain.** | Agent at turn time | **None — writes blocked** | None; single `fetch`, no txn | **TENANCY AMBIGUOUS** — scoping is whatever the operator's SQL and credentials imply | None | None | Agent answers questions from a customer system | `CURRENT FACT` | Credentials live in the agent's design-time config |

**No OLBrain-owned PostgreSQL table exists to inventory.**

## 5. Other Persistence Relevant to State/Memory

`CURRENT FACT` throughout.

| Store | Service | What it holds | Authoritative? | Notes |
|---|---|---|---|---|
| **Google Cloud Storage** | agent-design (writer), agent-runtime (reader) | `configs/{agent_id}/active_config.json` | Authoritative for runtime config | 5-minute cache, **no invalidation signal on publish** — confirmed from both sides. Multi-tenant fan-out writes the identical relative path into each dedicated tenant bucket |
| **GCS** | research-design/-runtime | Template bodies, run evidence and output blobs | Authoritative | Firestore holds metadata, GCS holds the body |
| **GCS** | workflow-runtime + `olbrain-shared` | `workflow_definitions` bodies | Authoritative | Storage body wins when present; legacy inline-JSON fallback remains |
| **GCS** | knowledge-vault | DCI corpus — plain extracted text | **Non-authoritative retrieval projection** | Retrieval by regex / agentic grep, **not** embeddings. No watermark of any kind |
| **BigQuery** | agent-engine (Lumen), studio-backend (audit) | Aggregate evidence; audit queries | Analytics/audit | SELECT-only; Lumen enforces `agent_id = '<X>'` server-side, explicitly "not LLM-trusted" |
| **Firebase Realtime Database** | agent-design (writer), studio (reader) | `/agentAccess/{agentId}/{userId}` cursor presence | **Ephemeral UI state** | Feature-flagged; silent no-op if `FIREBASE_DATABASE_URL` unset; write failures swallowed by design |
| **Google Cloud Pub/Sub** | research-design, research-runtime | Async job dispatch | Transport, not storage | This is the closest existing thing to async work dispatch; it is **not** a transactional outbox |
| **Redis** | — | — | **Dormant** | Declared dependency + settings fields; **no client import anywhere**; `rate_limit_storage` defaults to `"memory"` |

**Not present anywhere:** Kafka, Neo4j, any dedicated vector database, any OLBrain-owned SQL
database. `CURRENT FACT`

## 6. Storage Ownership Map

Ownership is recorded only where source establishes it. Repository names were not used to
infer ownership.

| Domain | Canonical owner | API/service owner | Write owner | Projection owner | UI reader | Background worker |
|---|---|---|---|---|---|---|
| `agents/{id}` | **OWNER AMBIGUOUS** — written by agent-design, studio-backend *and* agent-engine (provisional docs) | studio-backend `AgentService` | three services | — | Studio (direct Firestore) | transfer cascade |
| `active_config.json` | agent-design | agent-design | agent-design | agent-runtime reads with a 5-min cache | — | — |
| `agent_user_memory` | agent-runtime | agent-runtime `routers/agent_memory.py` | agent-runtime | — | — | post-turn extraction |
| `agent_datastores` | **OWNER AMBIGUOUS** — two repos write the same path | agent-design owns the only HTTP surface | **three paths** (§11) | prompt builder reads it back | Studio Data tab | extract-mode |
| `agent_sessions` / `agent_messages` | agent-runtime | agent-runtime | agent-runtime | — | **Studio + Noesis read directly from the browser** | summarizer |
| `agent_learned_patterns` | agent-runtime | none found | agent-runtime | — | — | post-turn |
| Context Service (`context_logs`, `context_facts`, `context_guardrails`) | agent-engine | agent-engine (CRUD dark) | agent-engine | — | — | consolidator (flag-disabled) |
| `vibe_sessions` | agent-engine | agent-engine | agent-engine | — | Studio subscribes live | headless brain builder |
| Research templates / learned / ledger | research-design | research-design | consolidator + operator | — | Studio | `run_learn_agent` |
| `research_runs` | research-runtime | research-runtime | research-runtime | — | Studio | pipeline |
| `workflow_*` | workflow-runtime | workflow-runtime (**no app auth on main routers**) | workflow-runtime | — | Studio | orchestrator |
| DCI corpus | knowledge-vault | knowledge-vault | knowledge-vault + org-document ingestion | **is itself the projection** | — | ingestion |
| `organization_documents` | studio-backend | studio-backend | studio-backend | feeds DCI | Studio | deindex |
| `connector_credentials` | studio-backend | studio-backend (org-admin gate) | studio-backend | — | Studio | — |
| `secrets`, `permissions`, `team_memberships` | **OWNER UNRESOLVED** | **UNKNOWN** | **UNKNOWN** | — | **UNKNOWN** | — |
| External PostgreSQL databases | **Customer / third party — not OLBrain** | agent-runtime holds credentials only | **nobody — writes blocked** | — | — | — |

## 7. Authorization / Tenancy Map

The architecturally important finding is the **mismatch pattern**, which recurs across most
memory and state stores.

| Store | Client-accessible? | App-layer authz | Firestore rules | Org checked? | Mismatch |
|---|---|---|---|---|---|
| `agent_datastores` | **No — fully denied**, tested | agent-design: Firebase token + view/edit permission ladder | `allow read, write: if false` | at table level | **None. This is the correctly-protected case.** |
| `agent_user_memory` | Read via rules | API key + org match, 404-safe | Real `isOrgMember` read gate, server-only write | Yes | None |
| `agent_sessions` / `agent_messages` | **Yes — browser reads** | org-scoped at the REST layer | **open r/w to any signed-in user** | REST yes, rules no | **App layer is scoped; client layer is not** |
| `agent_learned_patterns` | Yes | none found | **open r/w/create/delete**; a real `ownsAgent` rule exists but is superseded | No | App layer absent *and* rules open |
| `context_logs` | Yes | route auth only | **open**; owner-scoped rule dormant (the file's own comment admits it) | No | Both layers ineffective |
| `context_facts`, `context_guardrails` | Yes | CRUD dark (`CONTEXT_CRUD_ENABLED=false`) | **open, no rule at all** | No | **Dark app CRUD is bypassable via the client SDK entirely** |
| `vibe_sessions` | Yes | `list_for_user()` requires org+project | **open, no rule** | app yes, rules no | Anti-leak control bypassable |
| `workflow_agent_memory` | Yes | **none on the routers** | **open, no rule** | No | **Open at both layers simultaneously** |
| `research_templates`, `research_runs` | Yes | Firebase token + org equality, 404-safe | **open r/w** | app yes, rules no | The `RunMeta.billing` docstring itself admits the store is world-writable |
| `agents/{id}` | Yes | org/owner-scoped in studio-backend | **open r/w — any user may reassign `owner_id`/`organization_id`** | app yes, rules no | Most severe |
| `connector_credentials` | Yes | org-admin role required | **open, no org predicate at all** | app yes, rules no | Credential-pointer exposure |
| `secrets`, `permissions`, `team_memberships` | **UNKNOWN** | **UNKNOWN** | **UNKNOWN — never checked** | **UNKNOWN** | AMB-04 |
| External PostgreSQL | n/a | operator-authored SQL + stored credentials | n/a | **TENANCY AMBIGUOUS** | AMB-08 |

`TARGET REQUIREMENT` for contrast: typed capability authorization is mandatory, RLS is
`Defense in depth, not the sole security model`, and authorization is enforced at the read
boundary. `CURRENT FACT`: **no RLS of any kind exists**, because there is no SQL database.

## 8. Transaction / Concurrency Map

| Mutation path | Atomic today? | Mechanism | OCC / version check | Partial success possible? | Retry style |
|---|---|---|---|---|---|
| **Extract-mode datastore write** | **No** | Two independent `.set(merge=True)` calls — table then entry | **None** | **Yes** — table can be written while the entry fails | Exceptions **swallowed**; returns `None` |
| **Live agent-tool datastore write** | **Yes** | `db.batch()` — table + entry commit together | **None** | No | Error returned to the agent |
| **Operator datastore write** | **Yes** | `db.batch()` — table + entry | **None** | No | `WriteRefused` raised to the caller |
| **`context_facts` supersede/decay** | Per-document | `.update()` only, never delete | **None** | n/a | — |
| **Research `write_profile`** | Per-document | **Genuine CAS** — `expected_version=profile.version`, raises `ProfileVersionConflict` | **Yes** | No | **Application-level retry, up to `_MAX_WRITE_ATTEMPTS = 3`** |
| **Workflow `orchestrator_generation`** | Per-field increment | Fencing counter incremented on resume/retry | Generation check, not OCC | n/a | Stale pass exits at next item boundary |
| **`vibe_sessions` state transition** | **Yes** | `@firestore.transactional`, read-then-update | **Existence check only — no from-state or `expected_status` check** | No | — |
| **Other `vibe_sessions` writes** | Per-document | plain `.set()` / dotted `.update()` | None | n/a | — |
| **Brain build / Shopify provision** | Yes | `@firestore.transactional` **lease** claim with expiry | Lease, not version | No | — |
| **Agent create / versioned deployment** | Yes | `@firestore.transactional` in agent-design | Snapshot-based | No | — |
| **Org transfer cascade** | **No** | Nine sequential steps, various semantics (copy / re-label / archive+delete / disable) | None | **Yes — steps can partially complete** | UNKNOWN |
| **Org archive/restore** | **No** | Status flip across `projects` and `agents` | None | **Yes** | UNKNOWN |
| **Session summary write** | Per-document | `.set(merge=True)` of `{summary, memory_anchor_ts}` together | None | No | — |

**Three observations that matter for any later design.** `CURRENT FACT`

1. **Exactly one genuine optimistic-concurrency mechanism exists in the entire platform** —
   research-design's `write_profile` CAS. Everything else is either a plain write, a batch, a
   lease, or a fencing counter.
2. **Its retry is application-level and semantic.** `TARGET REQUIREMENT` (§7, §12 rule 9) is
   that a semantic conflict is returned to the agent and **MUST NOT** be retried by
   infrastructure. Whether a 3-attempt application retry inside a service violates that, or
   sits outside its scope because it is not infrastructure, is **SEMANTIC AMBIGUITY** —
   recorded as AMB-06, not resolved here.
3. **Check-then-act races exist in all three datastore writers.** Each reads a count or an
   existence flag and then writes, outside any transaction. Two concurrent writers can both
   observe `count < MAX` and both insert.

## 9. Provenance / Lineage Map

Field-level verification of what each record actually carries. `CURRENT FACT`

| Store | org | agent | person | session | message | run | extraction run | source event | timestamp | version | authority/source | validity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `agent_datastores` entry — **extract** | **✗** | via path | **key** (`person_hash`) | `last_session_id` (**overwritten each turn**) | **✗** | **✗** | **✗** | **✗** | `created_at`, `updated_at` | **✗** | **✗** | **✗** |
| `agent_datastores` entry — **tool** | **✗** | via path | **✗** | `session_id` ✓ | **✗** | **✗** | **✗** | **✗** | `created_at`, `updated_at` | **✗** | **✗** | **✗** |
| `agent_datastores` entry — **operator** | **✗** | via path | key when `fill=extract` | **✗** | **✗** | **✗** | **✗** | **✗** | `created_at`, `updated_at` | `source:"manual"`, `created_by`, `updated_by` ✓ | **✗** |
| `agent_user_memory` | ✓ | key | key (hash) | **✗** | **✗** | **✗** | **✗** | **✗** | ✓ | **✗** | **✗** | **✗** |
| `context_facts` | via scope_key | via scope_key | **✗** | via scope_key | **✗** | **✗** | **✗** | **`source_event_ids` ✓** | `created_at`/`updated_at` | **✗** | **✗** | **`t_valid`/`t_invalid` ✓** |
| `context_logs` event | via scope_key | via scope_key | **✗** | via scope_key | **✗** | **✗** | **✗** | own id | ✓ | **✗** | **✗** | **✗** |
| `agent_sessions.summary` | ✓ on doc | ✓ | **✗** | key | **✗** | **✗** | **✗** | **✗** | `memory_anchor_ts` | **✗** | **✗** | **✗** |
| `agent_learned_patterns` | **✗** | ✓ | **✗** | **✗** | **✗** | **✗** | **✗** | **✗** | ✓ | **✗** | usage/failure counters | **✗** |
| `workflow_agent_memory` | **✗** (schema-level) | key | **✗** | **✗** | **✗** | `evidence_run_ids` ✓ | **✗** | `evidence_exception_ids` ✓ | ✓ | **✗** | `approved_by` ✓ | **✗** |
| Research `LearnedProfile` | **✗** (schema-level) | **✗** | **✗** | **✗** | **✗** | **✗** | **✗** | **✗** | `updated_at` | **`version` ✓** | pin/archive state | **✗** |
| `vibe_sessions.active_conversant` | optional | — | — | key | — | — | — | **`last_transition_event_id` ✓** | `since` ✓ | **✗** | **✗** | **✗** |

**The three records carrying genuine provenance links today** are `context_facts`
(`source_event_ids`), `workflow_agent_memory`'s overrides (`evidence_exception_ids`,
`evidence_run_ids`) and `vibe_sessions` transitions (`last_transition_event_id`). **Only
research's `LearnedProfile` carries a version field.**

**The extract-mode `agent_datastores` row carries no link of any kind back to the evidence
that produced it.** `last_session_id` is explicitly a *last-touch* marker, overwritten on
every turn, not the support for any particular field value. This confirms
`implementation-spec.md` §18 at field level.

## 10. Deletion / Erasure Map

| Store | Deletable? | By whom | Hard/soft | On org delete | On org transfer | Derived invalidation | Residue elsewhere |
|---|---|---|---|---|---|---|---|
| `agent_datastores` entry | **Yes** | operator, via agent-design `DELETE` | **Hard** — "no soft-delete flag anywhere in this feature" | **Nothing** — not in any cascade | **Nothing** — excluded from the transfer cascade | **None** | Values may persist in `agent_user_memory` |
| `agent_user_memory` | Yes | GDPR route | Hard, 404-oracle-safe | Nothing | Nothing found | None | Same person's data may persist in `agent_datastores` |
| `agent_learned_patterns` | **No route found** | — | — | Nothing | **Excluded from the cascade** | None | Verbatim user text retained |
| `agent_sessions` | No route found | — | — | Nothing | **Re-labelled** (ungated, even same-org) | — | — |
| `agent_messages` | No route found | — | — | Nothing | Follows session | — | — |
| `context_logs`, `context_facts`, `context_guardrails` | **No erasure path at all** | — | — | Nothing | Nothing | — | Invalid facts retained forever |
| `vibe_sessions` | Soft only | service | **Soft** — status flip | Nothing | Nothing | — | Linked `context_logs` persist |
| `learning_ledger` | **"No API to delete one"** | — | — | Nothing | Nothing | — | — |
| `workflow_agent_memory` | Per-pattern + wipe script | service | Hard | Nothing | **Archive + delete** — the only real mitigation for its missing org field | — | Frozen copy in `_archive` |
| `knowledge_library` | Soft only | knowledge-vault | Soft | **No org cascade** | Corpus **copied**, not moved | — | Copy persists in both orgs |
| DCI corpus | Per-source | knowledge-vault | Hard per source | **No org-level bulk cascade** | Copy | — | — |
| `organization_documents` | **Yes** | studio-backend | **Hard delete + DCI deindex** if unreferenced | — | — | **Yes — the only genuine deindex path found** | — |
| Organization itself | **No hard delete exists anywhere in the platform** | — | Archive/restore status flip only | n/a | disjoint from transfer | — | Everything above persists |

**The structural facts.** `CURRENT FACT` There is no hard organization delete. The transfer
cascade and the archive/restore cascade are **entirely disjoint** code paths. `agent_datastores`
and `agent_learned_patterns` — the two most person-sensitive stores — appear in **neither**.
No store anywhere performs derived-object invalidation on delete except
`organization_documents`.

## 11. `agent_datastores` Deep Audit

All three writers re-verified directly against source this session. One Firestore path:

```text
agent_datastores/{agent_id}/tables/{table_id}/entries/{entry_id}
```

### 11.1 Writer-by-writer

| | **Writer 1 — extract-mode** | **Writer 2 — live agent tool** | **Writer 3 — operator CRUD** |
|---|---|---|---|
| **Code path** | `olbrain-agent-runtime` `services/extract_entry_writer.py::write_extract_entry()`, called from `services/agent_memory_service.py` per non-legacy `wanted_sets` entry; kicked off fire-and-forget post-turn | `olbrain-agent-runtime` `core/tools/datastore_executor.py::DatastoreExecutor._add()` | `olbrain-agent-design` `app/services/datastore_service.py::create_entry()` / `update_entry()` / `delete_entry()`, behind `app/routers/datastore.py` at `/api/v1/datastore` |
| **Key structure** | `entry_id = person_hash(user_key)` — **person-keyed, one row per person** | `entry_id = uuid.uuid4().hex[:12]` — **session-scoped, many rows** | **Bimodal**: `person_hash(user_key)` when the table's `fill == "extract"`, else `uuid.uuid4().hex[:12]` |
| **Entry fields** | `entry_id`, `last_session_id`, `user_key_kind`, `channel`, `values`, `updated_at`; `created_at` **only on first write** | `entry_id`, `session_id`, `values`, `created_at`, `updated_at` | `entry_id`, `values`, `updated_by`, `updated_at`; on first write `source:"manual"`, `created_by`, `created_at`; `user_key_kind:"identity"` when `fill=="extract"` |
| **Writer identity recorded?** | **No** | **No** | **Yes** — `source:"manual"`, `created_by`, `updated_by` |
| **Read path** | `core/cs_packet_builder.py::_load_person_records_block` — **unconditional on every packet build**, wrapped only in a no-op try/except | same collection | Studio Data tab; `GET` entries, CSV export |
| **Authorization** | none — background task | agent tool call within an authorized session | **Firebase token + `check_view_permission` / `check_edit_permission` ladder**; every write emits an `AuditEvent` |
| **Org information** | on the **table** doc only | on the **table** doc only | on the **table** doc only |
| **Versioning** | **None** | **None** | **None** |
| **Atomicity** | **Two separate `.set()` calls, no batch, no transaction** | `db.batch()` — table + entry together | `db.batch()` — table + entry together |
| **Timestamp behaviour** | `SERVER_TIMESTAMP`; guards `created_at` against re-stamping | `SERVER_TIMESTAMP` both fields | `SERVER_TIMESTAMP`; guards `created_at`, `source`, `created_by` against re-stamping |
| **Conflict behaviour** | `merge=True` — **field-level last-write-wins** | fresh unique doc — no conflict | `merge=(fill == "extract")` — merges into the same person row, **field-level last-write-wins** |
| **Cap behaviour** | `MAX_PER_TABLE`; **silently drops a new person** and logs a warning | `MAX_PER_SESSION` + `MAX_PER_TABLE`; returns a user-visible `limit_exceeded` error | `MAX_PER_TABLE`; raises `WriteRefused` |
| **Failure discipline** | **Exceptions swallowed**, returns `None` | error returned to the agent | exception raised to the caller |
| **Deletion** | none | `_delete()` via agent tool only | **Hard delete** — *"There is no soft-delete flag anywhere in this feature"* |
| **Provenance** | **None** — no message id, no extraction run id; `last_session_id` is a last-touch marker | `session_id` only | `created_by` / `updated_by` only |

### 11.2 Two key spaces, three code paths

`CURRENT FACT` The three writers do not partition cleanly by repository. Writer 3 is
**bimodal** and deliberately mirrors both runtime writers, importing `person_hash` from
`olbrain_shared`:

```text
person-keyed space (fill = "extract")   ← Writer 1  AND  Writer 3
session-keyed space (fill = tool)       ← Writer 2  AND  Writer 3
```

### 11.3 The collision is acknowledged in the source

`CURRENT FACT` Writer 3's own comment, verbatim:

> *"An upsert onto a person the extractor (or an earlier operator write) already recorded must
> not re-stamp provenance: created_at is the Data tab's 'Recorded' column and its sort order,
> and source/created_by say who first put this row here. Seeding one more field onto it is not
> that -- extract_entry_writer.write_extract_entry guards the same thing on its own side of
> this same document."*

And on the merge choice:

> *"merge=True on the extract row so a later extraction merges into this entry rather than
> replacing it outright; a tool row is a fresh document with no prior state to preserve."*

**What this establishes.** The shared document is **deliberate and coordinated**, not
accidental. Both writers guard `created_at` re-stamping. What is coordinated is *provenance
preservation*; what is **not** represented anywhere is *which writer's value should win for a
field both have written*. The design intent is explicitly that a later extraction **merges
into** an operator-corrected row.

**Correction to a prior framing.** `implementation-spec.md` §18 characterised the
writer-attribution difficulty as "an accident, not a design." That is too strong. The shared
document is designed; `source:"manual"` is a real, if partial, writer marker. The accurate
statement is narrower: **entry provenance is partial and writer attribution is derivable only
by field presence.** An entry created by writer 1 and later edited by writer 3 carries
`last_session_id` *and* `updated_by` but no `source`.

### 11.4 Mandatory conclusion

> **Can these three writer types safely map to one PostgreSQL semantic table?**

### **NO** — the source proves they are semantically incompatible as a single semantic table.

`CURRENT FACT`, on four independent grounds:

1. **Two different identity models.** Writer 1's row identity *is* a person
   (`person_hash(user_key)`, one row per person, upserted indefinitely). Writer 2's row
   identity is a single act of capture (`uuid4`, many rows per session, never updated). A
   table whose primary key means "a person" in some rows and "one capture event" in others has
   no coherent key semantics.
2. **Two different cardinalities over time.** The person row is mutable and long-lived across
   sessions; the tool row is immutable-in-practice and scoped to one session. Row count grows
   with population in one case and with activity in the other.
3. **Two different authority levels with no field to express them.** Writer 3 is an
   authenticated, audited human correction. Writers 1 and 2 are machine capture. All three
   land in the same `values` map with no authority, source-rank or version field, so the
   surviving value is decided by write order alone.
4. **Two different failure and durability contracts.** Writer 1 swallows exceptions and can
   leave a table header written with no entry (non-atomic). Writers 2 and 3 are atomic
   batches that surface errors. A single semantic table cannot offer both guarantees.

**Important scoping of this answer.** This states that the three **cannot be one semantic
table**. It does **not** prescribe how many tables there should be, nor which target object
class each maps to. `implementation-spec.md` §18 proposes mappings; those remain `PROPOSED`.
**No decomposition is invented here.**

**The migration blocker is unchanged and is confirmed at field level by §9:** extract-mode
rows carry no link to the evidence that produced them, so the Evidence a target Claim requires
does not exist and cannot be reconstructed. That is `DECISION REQUIRED`, tracked as AMB-01 and
as decision D1 in `governance-decision-request.md`.

## 12. Firestore → PostgreSQL Migration Boundary

Classification per the requested scheme. **No migration solution is chosen where the source
does not establish one.**

### A — Likely migratable with verified semantics

| Store | Why |
|---|---|
| `agent_datastores` **tool-keyed** rows | Append-only, unique key, atomic batch write, `session_id` present. Clean shape. |
| `context_logs` | Append-only, idempotent-on-id, never updated or deleted. The cleanest existing shape on the platform. |
| `research_runs.phase`, `workflow_runs.status` | Bounded transition graphs with a single writer each. |
| `agent_sessions.summary` | Two fields written together, explicitly non-assertive. |
| `learning_ledger` | Append-only by construction. |

### B — Migratable only after semantic decomposition

| Store | Blocking ambiguity |
|---|---|
| `agent_datastores` **person-keyed** rows | AMB-01 — no provenance to supporting evidence; AMB-02 — no authority representation between machine and operator writes |
| `agent_user_memory` | Blob-shaped with no per-field versioning; decomposition target per field is `PROPOSED`, not settled |
| `workflow_agent_memory` | Contains two semantically different things in one document (overrides vs. exception patterns); the second is `NO V2.0 TARGET MAPPING` |
| `context_facts` | Freeform LLM extractions, not typed `(subject, predicate, object)`; no policy binding exists to migrate against |

### C — Projection / rebuild preferred

| Store | Why |
|---|---|
| DCI corpus | Explicitly non-authoritative, rebuildable, content-hash-addressed. Rebuilding is cheaper and safer than migrating. |
| `knowledge_library` metadata | Projection metadata for the above. |
| BigQuery analytics | `TARGET REQUIREMENT`: analytics is a separate pipeline and system from customer memory. Not a migration candidate. |

### D — Legacy / retirement candidate

| Store | Evidence |
|---|---|
| `knowledge_embeddings` + OpenAI Vector Store | Confirmed dead — zero live readers or writers |
| `config/firestore_config.py` config service | Superseded by `active_config.json`; live reachability of the remaining path is an open question |
| `agent_user_memory` legacy `field_values` / `field_values_by_set` paths | Frozen by the code's own docstrings |
| Redis dependency + `redis_url` / `rate_limit_storage` settings | Declared but never imported (F4) |
| `workflow_definitions` inline-JSON fallback | The shared package's docstring says it goes away once a migration script runs — that script was never located |

### E — Cannot determine yet

| Store | Blocking ambiguity |
|---|---|
| `secrets`, `permissions`, `team_memberships` | AMB-04 — never investigated; no owner, no rules verdict, no purpose established |
| `credit_transactions`, `billing_accounts`, `usage_metrics` | AMB-03 — financial records; neither semantics nor retention obligations established |
| `agent_traces`, `mcp_tool_executions` | AMB-03 — volume, retention and purpose unknown |
| `workflow_items` | Org binding only inferred transitively; no Pydantic model located anywhere |
| ~30 further registry-declared collections | AMB-03 — declared but live use unverified |
| Firebase RTDB `agentAccess` | Ephemeral presence; whether it survives any migration at all is undecided |

## 13. PostgreSQL Capability Gap Matrix

A capability counts as **existing** only where OLBrain source demonstrates it. PostgreSQL's
theoretical support is irrelevant here.

| Target capability | Existing PostgreSQL support | Existing Firestore support | Gap | Ambiguity | Blocker? |
|---|---|---|---|---|---|
| Transactions | **None** — single `fetch`, no txn wrapper | Yes — `@firestore.transactional` in agent-design, agent-engine leases, `vibe_sessions` transition | Whole transactional layer | — | No — greenfield |
| Optimistic concurrency | **None** | **One instance** — research `write_profile` CAS | Platform-wide OCC absent | AMB-06 (retry semantics) | No |
| Versioning | **None** | `LearnedProfile.version` only | No version on any memory/state record | — | No |
| Row-level security | **None** | n/a (rules are the analogue, and are largely open) | RLS entirely absent | — | No |
| Tenant isolation | **None** — external DBs | Partial; org on parent docs, absent on many rows | Systemic "no org on the row" | AMB-08 | No |
| Append-only evidence | **None** | `context_logs`, `learning_ledger`, `protection_events` — three independent logs, no shared structure | No single evidence plane; no `source_position` | AMB-05 | No |
| Claims | **None** | `context_facts` is the nearest analogue; freeform, untyped | No typed `(s,p,o)` anywhere | — | No |
| Predicate Policy Registry | **None** | **None** | **Complete absence** — nothing declares per-predicate authority, cardinality or conflict policy | — | **Yes — critical path** |
| Current state | **None** | Scattered status fields; no slot model | No versioned slot anywhere | — | No |
| Temporal data | **None** | `context_facts` `t_valid`/`t_invalid` — real bitemporality, system time implicit | `knowledge_cutoff` unanswerable today | — | No |
| Provenance | **None** | Three stores carry links (§9); most carry none | No lineage relations; arrays at best | AMB-01 | Partially |
| Outbox | **None** | **None** — Pub/Sub dispatch and in-process fire-and-forget instead | No transactional outbox | — | No |
| Vector search | **None** — no pgvector | **None live** — DCI is regex/grep text; embeddings retired | No vector capability in production at all | — | No |
| Memory Gateway | **None** | **None** — every service reads Firestore directly | No boundary exists | — | No |
| Deletion / invalidation | **None** | Only `organization_documents` deindexes | No cascade, no generations, no tombstones | AMB-07 | Partially |
| Idempotency | **None** | `context_logs.append()` idempotent-on-id | No `mutation_id` concept | — | No |
| Conflict handling | **None** | `ProfileVersionConflict` only | No `CONFLICT` status anywhere | — | No |

**The one entry that genuinely blocks:** the Predicate Policy Registry has no antecedent in
either technology. Every other capability is greenfield but unobstructed.

## 14. Ambiguity Register

Recorded, not resolved.

### AMB-01 · `MIGRATION AMBIGUITY` · `ASK SENIOR`

**Question:** For extract-mode `agent_datastores` rows, which migration path is approved —
synthesize placeholder Evidence, or migrate as un-provenanced Memory?
**Evidence:** §9 confirms at field level that these rows carry no message id, no extraction
run id and no source event id; `last_session_id` is overwritten every turn.
**Affected:** agent-runtime extraction, prompt read path, any future Claim store.
**Why it matters:** a target Claim requires provenance as explicit lineage to Evidence that,
for these rows, does not exist and cannot be reconstructed.
**Required:** an architecture-owner decision. Already tracked as D1 in
`governance-decision-request.md`.
**Can work continue?** Yes — foundation work is unaffected. Migration of this store cannot start.

### AMB-02 · `SEMANTIC AMBIGUITY` · `ASK SENIOR`

**Question:** When a machine extraction and a human operator have both written the same field
of the same person row, which value is authoritative?
**Evidence:** §11.3 — the source deliberately merges a later extraction into an
operator-corrected row, and no authority, source-rank or version field exists on the entry.
**Affected:** `agent_datastores` person-keyed space, agent-design operator UI, any Predicate
Policy for person attributes.
**Why it matters:** `TARGET REQUIREMENT` §14 records `Last-write-wins → Rejected for important
state`. Today write order decides. Resolving this is a prerequisite for authoring the
predicate policy for these fields.
**Required:** owner decision on relative authority.
**Can work continue?** Yes, except for policies covering person attributes.

### AMB-03 · `FACT UNKNOWN` · resolvable by inspection

**Question:** Which of the ~45 registry-declared Firestore collections are actually live, and
what does each hold?
**Evidence:** §3.3 — the registry declares far more than the ~30 investigated, and includes at
least one known-dead entry (`knowledge_embeddings`), so declaration does not imply use.
**Affected:** scope of any migration; retention obligations; the completeness of every prior
storage claim.
**Why it matters:** an inventory believed complete is not.
**Required:** further repository inspection (§16). No owner input needed.
**Can work continue?** Yes for the foundation; **no** for any claim that the store inventory is complete.

### AMB-04 · `SECURITY AMBIGUITY` · `USER → SENIOR`

**Question:** What do the `secrets`, `permissions` and `team_memberships` collections hold,
who owns them, and what Firestore rules govern them?
**Evidence:** declared in the registry and referenced by 5, 1 and 2 non-test files
respectively; **never covered by any investigation pass**, and absent from the Security
Finding E per-collection verdict table.
**Affected:** the entire authorization picture. `permissions` and `team_memberships` are
authorization-bearing; `secrets` is credential-adjacent.
**Why it matters:** Security Finding E enumerated exposed collections from a list that did not
include these three. If they fall to the same catch-all, the exposure is broader than reported.
**Required:** inspection first, then almost certainly a security owner's attention.
**Can work continue?** Yes — but this should be checked **before** anyone relies on Finding E
as a complete exposure list.

### AMB-05 · `STORAGE AMBIGUITY` · resolvable by inspection

**Question:** Are `context_logs`, `learning_ledger` and `protection_events` intended as three
independent logs, or is one of them the intended evidence plane?
**Evidence:** three append-only logs, three repositories, no shared structure, no shared
ordering concept.
**Affected:** evidence-plane design, backfill strategy.
**Why it matters:** `TARGET REQUIREMENT` §8 needs one ordered evidence stream with contiguous
positions. Which existing log seeds it (if any) is unsettled.
**Can work continue?** Yes.

### AMB-06 · `SEMANTIC AMBIGUITY` · `ASK SENIOR`

**Question:** Does research-design's 3-attempt application-level retry of a
`ProfileVersionConflict` violate the rule that a semantic conflict must not be retried?
**Evidence:** §8 — `write_profile` raises a typed conflict and the caller retries up to
`_MAX_WRITE_ATTEMPTS = 3`. `TARGET REQUIREMENT` §7/§12 rule 9 forbids **infrastructure** retry
and requires the conflict reach the agent.
**Affected:** the only working CAS precedent on the platform, and whether it is a model to
generalise or a pattern to correct.
**Why it matters:** the distinction between "infrastructure" and "application" retry is not
defined by the contract, and this is the one place it already matters in production.
**Required:** owner interpretation.
**Can work continue?** Yes.

### AMB-07 · `GOVERNANCE DEPENDENCY` · blocked on §16

**Question:** What retention, recomputation-window and bulk-deletion-retry values govern the
deletion design?
**Evidence:** §10 — no hard org delete exists, two disjoint cascades, two of the most sensitive
stores in neither.
**Affected:** every deletion path.
**Required:** §16 rows 4, 5 and 8 — **not** answerable by this audit and not answerable by
engineering.
**Can work continue?** Correct exclude-don't-serve behaviour yes; bulk and aggregate deletion no.

### AMB-08 · `SECURITY AMBIGUITY` · `USER → SENIOR`

**Question:** How are credentials for external `data_query` PostgreSQL targets stored, scoped
and rotated, and what tenant isolation applies to the SQL an operator writes?
**Evidence:** §4.2 — `host`/`user`/`password` arrive in a `connection` dict from frozen
design-time config. The dispatcher enforces read-only but performs **no tenancy check on the
SQL**; any row the credential can see is reachable.
**Affected:** every agent with a `data_query` capability node.
**Why it matters:** this is a live production credential path that no prior investigation pass
covered, and it sits outside the Firestore rules discussion entirely.
**Can work continue?** Yes — it is unrelated to the target design, but it is a current-state
security question worth routing.

### AMB-09 · `OWNERSHIP UNKNOWN`

**Question:** Who owns `agents/{id}`?
**Evidence:** §6 — written by agent-design, studio-backend and agent-engine (provisional docs).
**Affected:** the platform's central ownership record, already the most exposed collection.
**Can work continue?** Yes.

### AMB-10 · `IMPLEMENTATION QUESTION`

**Question:** Is the Redis dependency and its settings surface dead code to remove, or a
planned capability?
**Evidence:** F4 — declared, configurable, never imported.
**Can work continue?** Yes. Cosmetic unless someone later assumes Redis is available.

## 15. Questions Requiring Senior Input

| Q-ID | Question | Why repository evidence cannot answer it | Affected components | What an answer unblocks |
|---|---|---|---|---|
| **Q-S1** | For extract-mode `agent_datastores` rows, synthesize placeholder Evidence or migrate as un-provenanced Memory? | The supporting Evidence was never recorded; no code can recover it | agent-runtime extraction, prompt read path, future Claim store | Migration of the largest person-data store |
| **Q-S2** | When a machine extraction and a human operator both write the same person field, which wins? | The code deliberately merges both with no authority field; intent is not recorded anywhere | `agent_datastores`, operator UI, person-attribute policies | Authoring the first person-attribute Predicate Policy |
| **Q-S3** | Do `secrets`, `permissions` and `team_memberships` fall under the same Firestore catch-all as the collections in Security Finding E? | These three were never in scope for the rules review; the finding's collection list did not include them | Platform authorization posture | Whether Finding E is a complete exposure list or an incomplete one |
| **Q-S4** | How are external `data_query` database credentials scoped, stored and rotated, and who reviews the operator SQL? | Credentials arrive from design-time config; no repository establishes the governance around them | Every agent with a `data_query` node | A current-state security gap unrelated to the target design |
| **Q-S5** | Is an application-level retry of a semantic `ProfileVersionConflict` permitted, or is it the behaviour §12 rule 9 forbids? | The contract forbids *infrastructure* retry without defining the boundary; production already does this | Research learning pipeline; the CAS precedent generally | Whether the one working OCC precedent is a model or a defect |

**Already tracked, not re-asked here:** every §16 row (G1–G8) and decisions D1–D7 in
`investigation/governance-decision-request.md`. Q-S1 is the storage-side restatement of D1;
Q-S2 is new and was **not** previously captured.

## 16. Questions Answerable by Further Repository Inspection

No owner input required. Listed in descending value.

| # | Question | Where to look |
|---|---|---|
| 1 | Which of the ~45 registry-declared collections are live, and what does each hold? | `alchemist/constants/collections.py` as the index; then grep each name across all ten repos |
| 2 | What Firestore rules govern `secrets`, `permissions`, `team_memberships` and the other uninvestigated collections? | `olbrain-studio` `firestore.rules` — re-run the Finding E analysis against the full registry list |
| 3 | Are `credit_transactions` / `billing_accounts` / `usage_metrics` customer-contribution datasets? | studio-backend billing services — bears directly on §16 row 5 |
| 4 | Is `workflow_items` org-bound at the row level? | `olbrain-shared` and workflow-runtime; no model was ever located |
| 5 | Does any service besides agent-design write `agents/{id}`? | grep the write sites; resolves AMB-09 |
| 6 | Is the Redis settings surface referenced by any deployment config? | `env.prod.yaml` across repos; resolves AMB-10 |
| 7 | What is the live reachability of the legacy `create_agent()` / Firestore config path? | agent-runtime `core/agent.py` construction paths |
| 8 | Do `agent_traces` / `mcp_tool_executions` carry PII, and at what volume? | agent-engine and agent-runtime writers |

## 17. What Must NOT Be Designed Yet

Each item lists the specific dependency this audit actually found. Nothing is listed
speculatively.

| Must not design | Blocked by |
|---|---|
| **Final PostgreSQL schema** | AMB-03 — the collection inventory is incomplete, so the migration scope is unknown. A schema designed against ~30 of ~45 collections would be sized wrong. |
| **`agent_datastores` table design** | §11.4 (three writers cannot be one semantic table) + AMB-01 + AMB-02. The decomposition is `DECISION REQUIRED`. |
| **RLS policy design** | AMB-04 — `permissions` and `team_memberships` are authorization-bearing and uninvestigated; their contents may determine what the tenancy predicate can even be. |
| **Deletion / retention implementation** | AMB-07 → §16 rows 4, 5, 8. No values exist and engineering may not invent them. |
| **Any aggregate-bearing table** | §16 row 5 — the contract forbids claiming a legal exemption absent explicit per-dataset classification, and AMB-03 means we do not yet know which stores are aggregates. |
| **Authorization caching semantics** | §16 rows 1 and 6, which the contract's own note says are coupled. |
| **Memory Gateway API surface** | No source material establishes any of it; the contract leaves transport and framework to implementation but the *boundary* depends on which stores are in scope (AMB-03). |
| **Evidence-plane `source_offset` allocation** | AMB-05 — which existing log seeds the evidence plane is unsettled, and contiguity has no precedent to copy. |
| **`MAP` / `SET` per-element status representation** | No production precedent exists; purely a design choice, but one with no current shape to validate against. |
| **Migration cutover strategy** | AMB-01, AMB-02, AMB-03. Sequence cannot be fixed while scope and the largest store's decomposition are open. |
| **Anything assuming Redis, Kafka, Neo4j or a vector database** | F4 and §4 — none exists; the contract marks them optional on measured need. |

**What may proceed** (unchanged from `implementation-spec.md` §5 and confirmed by this audit):
the Predicate Policy Registry, the Evidence model, the Claim model, the Mutation Contract and
StateSlot resolution. None depends on a resolved ambiguity above — but note that the registry's
*content* still depends on §16 row 3 and R2 for externally-owned predicates.

## 18. Evidence / Source Traceability

### Read directly from repository source this session

| Finding | Repository / file |
|---|---|
| `asyncpg` is the only Postgres driver; purpose stated in-comment | `olbrain-agent-runtime` `requirements.txt` |
| Read-only enforcement, per-call connection, config-supplied credentials | `olbrain-agent-runtime` `core/tools/_dispatchers/postgres.py` |
| Four-provider registry (`dynamics365`, `dynamics365_fno`, `postgres`, `salesforce`) | `olbrain-agent-runtime` `core/tools/data_query_executor.py` |
| Writer 1 — person key, two non-atomic sets, swallowed exceptions, silent drop at cap | `olbrain-agent-runtime` `services/extract_entry_writer.py` |
| Writer 2 — uuid key, atomic batch, caps surfaced as errors | `olbrain-agent-runtime` `core/tools/datastore_executor.py` |
| Writer 3 — bimodal key, atomic batch, `source`/`created_by`/`updated_by`, hard delete, the shared-document comment | `olbrain-agent-design` `app/services/datastore_service.py` |
| Writer 3 authorization ladder | `olbrain-agent-design` `app/routers/datastore.py` |
| Firebase RTDB cursor presence, no-op and swallow semantics | `olbrain-agent-design` `app/services/rtdb_service.py`; `olbrain-studio` `src/services/shared/cursorService.js` |
| Canonical ~45-collection registry | `olbrain-agent-engine` `alchemist/constants/collections.py` |
| `vibe_sessions` transactional transition; existence-only check; `last_transition_event_id` | `olbrain-agent-engine` `alchemist/services/vibe_session_service.py` |
| Non-transactional `vibe_sessions` writes | `olbrain-agent-engine` `alchemist/services/context_broker.py` |
| BigQuery aggregate evidence with server-enforced `agent_id` filter | `olbrain-agent-engine` `alchemist/agents/lumen/evidence/bigquery.py` |
| BigQuery audit queries | `olbrain-studio-backend` `routes/audit_routes.py` |
| Transactional lease pattern | `olbrain-agent-engine` `alchemist/agents/brain_builder.py`, `alchemist/provision/shopify_provision.py` |
| Redis declared but unused; defaults to in-memory | `olbrain-agent-runtime` `requirements.txt`, `config/settings.py` |
| Absence of migrations, `.sql`, Prisma, `DATABASE_URL`, pgvector, RLS | repo-wide searches across all ten repositories |

### Carried forward from prior investigation (not re-derived)

`investigation/store-inventory.md` (per-store map, Security Findings A–H),
`investigation/reconciliation.md` §4, `investigation/implementation-spec.md` §4/§18/§23/§29,
`investigation/architecture-freeze.md`, `investigation/governance-decision-request.md`,
`artifacts/senior-feedback.md`, `artifacts/repo-and-soul-map.md`.

### Normative source

`artifacts/architecture-contract.md` — §3, §7, §8, §9, §10, §12, §14, §16. Unmodified, md5
`97c1fa3bcea1d71210c0429b1d113d07`.

### Repository HEADs — all verified clean at audit time

`olbrain-agent-runtime` `b2401a0` · `olbrain-agent-engine` `8720720` ·
`olbrain-research-design` `d044fce` · `olbrain-research-runtime` `d1caecd` ·
`olbrain-workflow-runtime` `5d48437` · `olbrain-knowledge-vault` `6d76083` ·
`olbrain-shared` `a837b95` · `olbrain-studio` `252f7887` ·
`olbrain-studio-backend` `6ada46a` · `olbrain-agent-design` `bbc85c8`

Line numbers are deliberately not reproduced — they drift. File:line citations as captured at
these HEADs are in `investigation/repo-notes/*.md`.

---

**No repository under `repos/` was modified.** No database was contacted, no Firestore or
PostgreSQL write performed, no migration run, no deployment, commit, push or PR. No schema was
designed and no implementation decision was made to "fill a gap."
