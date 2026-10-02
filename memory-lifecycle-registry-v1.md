# Lifecycle Registry v1 (Lane A, A4)

**Date:** 2026-10-01.

**Classification:** TARGET ARCHITECTURE. Legacy rows describe VERIFIED CURRENT stores (see the census).

**Source of truth:** `memory-prototype/tools/registry_build.py`. It generates `memory-lifecycle-registry-v1.json` (the machine-readable draft) and the table in §4.

**Completeness check:** `python tools/registry_build.py --check` exits non-zero on any gap. Current result: **"registry complete: 92 entries, 92 expected stores covered"**.

**Inputs:**

| Input | What it contributes |
|---|---|
| `memory-ecosystem-map.md` (MAP) §3–§4 | Stores already identified |
| `memory-legacy-erasure-census-v1.md` (A5) | Legacy stores, with source tracing |
| `memory-architecture-v2-red-team.md` (RT) C-7 / R-7 | Requirement for a schema-driven registry |
| The Lane A prototype | New stores it adds: retraction records, commit records, replay watermark |

## 1. Why a registry (and why schema-driven)

A hand-written store list failed in v2: the list omitted v2's own manifests, events and proposals (RT C-7). The registry is therefore:
- **data, not prose.** Every store is an entry with fixed fields, and CI fails on a missing entry or an empty field;
- **the driver of erasure.** The orchestrator iterates the entries, and an entry without a handler is a build failure;
- **the scanning list for the completeness auditor** (INV-5).

## 2. Entry schema (draft)

| Field | Meaning |
|---|---|
| `id` | `v2.<name>` or `legacy.<name>` |
| `store` | Collection, table, path or external system |
| `system` | Firestore / PostgreSQL / GCS / GCP / external / memory |
| `class` | evidence, claims, projection, identity, agent knowledge, telemetry, billing, external copy, … |
| `scope_type` | PERSON / ACCOUNT / RELATIONSHIP / SESSION / AGENT / TEMPLATE / ORG / … |
| `subject_columns` | The fields that identify a person today. For legacy stores this is often only a raw identifier or `session_id` |
| `tenant_columns` | The org binding (and its reliability) |
| `lookup` | How a handler finds a subject's rows **today** (equality, prefix, collection-group, content scan) |
| `erasure_handler` | What the handler does |
| `handler_version` | Versioned, so the ledger records which handler erased what |
| `retention_class` | The bounded retention or lifecycle |
| `legal_retention` | Legal basis or `[BLOCKED:Legal]` |
| `rebuild_source` | What a projection or derived store is rebuilt from |
| `index_requirements` | Indexes the handler or the queries need |
| `external_dependency` | A system outside the platform or outside the workspace |
| `raw_customer_text` | Whether the store may hold verbatim customer text |
| `derived_knowledge` | Whether the store holds learned or derived knowledge |
| `restore_participation` | Behaviour under the restore protocol |
| `can_regenerate_deleted` | Whether a job can re-create erased content from this store or into it. True means a tombstone check (fence library) is mandatory |
| `owner` | Owning team or service |
| `status` | One of the values in §3 |

## 3. Status summary

| Status | Count | Meaning |
|---|---|---|
| `target_v2` (+1 deferred) | 26 | New stores. Handler designed and specified in A7. Several are prototyped (bindings, seals, claims, retraction records, manifests, outbox, ledger, watermark) |
| `legacy_handler_needed` | 34 | Phase B3 handler. Design in the census |
| `legacy_quarantine` | 4 | Cannot be made reliably subject-erasable (verbatim cross-user text). Quarantined, then erased at cutover |
| `legacy_retire` | 2 | The writer is retired. Data deleted or re-derived |
| `retention_only` | 8 | Bounded by TTL or lifecycle only (logs, caches, backups, exports, eval). The window value is `[BLOCKED:Legal]` |
| `pseudonymise` | 1 | `usage_events`: rekeyed, retained under a billing basis `[BLOCKED:Legal]` |
| `external_gap` | 6 | Outside platform control: Slack/email excerpts, subprocessors, third parties in research outputs. Minimised at source, recorded in the ledger |
| `blocked_missing_repo` | 7 | `[UNRESOLVED: missing repository]`: Noesis, voice gateway, billing, directives, analytics-service, cloud-functions (billing records), the PII token vault |
| `not_person_data` | 4 | Payments chain, API keys, policy registry, replay watermark |

**Completeness statement.** Every store named by MAP §3–§4, by the census, and by the v2 and Lane A design has an entry. So do the four missing-repository systems, whose entries record the dependency explicitly.

**The registry is not complete in substance** while 7 entries are `blocked_missing_repo`. Their contents cannot be described from source, and the README of the next phase must not claim otherwise.

## 4. Registry table (generated)

The full field set (21 fields per entry) is in the JSON. This table shows the decision-relevant columns.

| id | store | system | scope | subject cols | tenant cols | handler | raw text | derived | regen | status |
|---|---|---|---|---|---|---|---|---|---|---|
| v2.bindings | memory_bindings/{hmac(org,channel,identifier,assurance)} | Firestore | PERSON/ENDPOINT | subject_id; identifier HMAC | org (in HMAC + field) | tombstone: status=erased, epoch+1 (binding first, C-1a) | no | no | no | target_v2 |
| v2.identity_events | identity_events/{event_id} | Firestore + WORM mirror | PERSON | subject ids (opaque) | org | rekey to erasure request id | no | no | no | target_v2 |
| v2.inbound_dedup | inbound_dedup/{hmac(org,channel,provider_msg_id)} | Firestore | MESSAGE | evidence_id | org (HMAC) | delete with evidence | no | no | no | target_v2 |
| v2.evidence_seal | agent_messages.{sealed_hash, seal_state, stamps, commit_records} | Firestore | MESSAGE | subject_id stamp | org stamp | deleted with the message | yes | no | no | target_v2 |
| v2.evidence_meta | evidence_meta | PostgreSQL | MESSAGE | subject_id, source_member_id | org_id (RLS) | delete row | no | no | no | target_v2 |
| v2.claims | claims (content-immutable, per-evidence: LA-11) | PostgreSQL | PERSON/ACCOUNT/RELATIONSHIP | subject_id, source_member_id | org_id (RLS) | archive (pending_erasure) then physical delete | no | no | no | target_v2 |
| v2.claim_support | claim_support (quotes) | PostgreSQL | PERSON/ACCOUNT/RELATIONSHIP | subject_id, source_member_id | org_id (RLS) | archive (pending_erasure) then physical delete | yes | no | no | target_v2 |
| v2.claim_transitions | claim_transitions | PostgreSQL | PERSON/ACCOUNT/RELATIONSHIP | subject_id, source_member_id | org_id (RLS) | archive (pending_erasure) then physical delete | no | no | no | target_v2 |
| v2.retraction_records | retraction_records (LA-9) | PostgreSQL | PERSON/ACCOUNT/RELATIONSHIP | subject_id, source_member_id | org_id (RLS) | archive (pending_erasure) then physical delete | no | no | no | target_v2 |
| v2.suppressions | suppressions (keyed fingerprints) | PostgreSQL | PERSON/ACCOUNT/RELATIONSHIP | subject_id, source_member_id | org_id (RLS) | archive (pending_erasure) then physical delete | no | no | no | target_v2 |
| v2.slots | slots (head projection) | PostgreSQL | PERSON/ACCOUNT/RELATIONSHIP | subject_id, source_member_id | org_id (RLS) | recompute | no | no | yes | target_v2 |
| v2.commitment_events | commitment_events (+ projection) | PostgreSQL | RELATIONSHIP | subject_id via evidence | org_id | drop events of erased evidence/subject | no | no | no | target_v2 |
| v2.episodes | episodes | PostgreSQL | SESSION | subject_id | org_id | delete | no | no | yes | target_v2 |
| v2.narratives | narratives | PostgreSQL | SESSION | subject_id via episode | org_id | delete; regenerate from evidence | yes | yes | yes | target_v2 |
| v2.accounts | accounts + account_links | PostgreSQL | ACCOUNT | linked person subject ids | org_id | drop links of erased persons; erase-org | no | no | no | target_v2 |
| v2.agent_knowledge | agent_knowledge + contributions | PostgreSQL | AGENT | contributor subject ids (lineage) | org_id | remove contribution; retire below k | no | yes | yes | target_v2 |
| v2.extraction_proposals | commit records / proposals (LA-1: kept with evidence in FS) | Firestore (on message) | MESSAGE | subject via message | org | deleted with the message | yes | no | no | target_v2 |
| v2.manifests | prompt_manifests | PostgreSQL | MESSAGE | subject_id | org_id | rekey subject → erasure request id | no | no | no | target_v2 |
| v2.memory_events | memory_events (ids only) | PostgreSQL → BigQuery aggregates | ORG | subject ids (opaque) | org_id | rekey; BQ export aggregates only (M-16) | no | no | no | target_v2 |
| v2.outbox | outbox (PII-free payloads) | PostgreSQL | ORG | ids only | org_id | payloads carry no content; drop with partition | no | no | no | target_v2 |
| v2.erasure_ledger | erasure_requests + erasure_steps + WORM mirror | PostgreSQL + GCS (retention-locked) | ORG | subject HMAC (worm_ref) | org | never deleted (PII-free proof) | no | no | no | target_v2 |
| v2.replay_watermark | recovery watermark (LA-10) | PostgreSQL | ORG | none | per instance | n/a | no | no | no | not_person_data |
| v2.search_projection | claims_fts (normaliser tokens, M-11) | PostgreSQL | PERSON | subject_id | org_id | drop rows; every hit re-validated (M-9) | yes | no | yes | target_v2 |
| v2.vector_projection | pgvector projection (only on measured trigger) | PostgreSQL | PERSON | subject_id | org_id | drop rows; re-validated hits | yes | yes | yes | target_v2 (deferred) |
| v2.derived_artifacts | analytics judgements (sentiment, disposition, outcome) | Firestore/PG (analytics) | SESSION | pseudonymous session ref | org | fence library + handler (C-6) | no | yes | yes | target_v2 |
| v2.consent_ledger | consent + suppression HMAC list | Firestore (server-only) | PERSON | identifier HMAC | org | keep suppression entry; delete the rest [BLOCKED:Legal] | no | no | no | target_v2 |
| v2.subject_keys | subject keys (HMAC id keys, identifier ciphertext) | Firestore (identity) / KMS | PERSON | subject_id | org | destroy key (crypto-shred of ids only, not content: C-8) | no | no | no | target_v2 |
| v2.policy_registry | predicate policy registry (versioned) | config | ORG | none | org | n/a | no | no | no | not_person_data |
| legacy.agent_messages | agent_messages | Firestore | MESSAGE | session_id (spine); no person key | organization_id (missing/'default' on legacy rows) | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.agent_sessions | agent_sessions (+summary, identity, judge fields) | Firestore | SESSION | doc id embeds raw phone; phone_number, user_id, identity_migrated_from, from_email | organization_id | B3 handler (census row) | yes | no | yes | legacy_handler_needed |
| legacy.agent_user_memory | agent_user_memory | Firestore | AGENT×KEY | channel_user_id (raw) | organization_id | quarantine, erase at cutover | yes | yes | yes | legacy_quarantine |
| legacy.agent_datastores | agent_datastores/{agent}/tables/*/entries | Firestore | PERSON/SESSION | unsalted person_hash; session_id | none on entries | B3 handler (census row) | yes | yes | yes | legacy_handler_needed |
| legacy.agent_learned_patterns | agent_learned_patterns/{agent}/patterns | Firestore | AGENT | source_session_id only; verbatim other-user text | none | quarantine, erase at cutover | yes | yes | yes | legacy_quarantine |
| legacy.agent_disposition_taxonomy | agent_disposition_taxonomy | Firestore | AGENT | none | via agent | retire writer, delete | yes | yes | no | legacy_retire |
| legacy.agent_users | agent_users | Firestore | AGENT×CHANNEL | channel_user_id, phone, email | organization_id (sometimes '') | B3 handler (census row) | no | no | yes | legacy_handler_needed |
| legacy.lead_profiles | lead_profiles | Firestore | SESSION | contact fields | organization_id | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.lead_contacts | lead_contacts | Firestore | ORG | hashed contact | organization_id | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.lead_activity | lead_activity | Firestore | PERSON_KEY | person_key | organization_id | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.agent_documents_shared_with | agents/{id}/documents.shared_with[] | Firestore | AGENT | user_id, session_id in array | via agent | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.agent_traces | agent_traces/{message_id} (counters) | Firestore | MESSAGE | session_id (embeds phone) | organization_id | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.research_learned | research_templates/{t}/learned/* | Firestore | TEMPLATE | contributors (uids), session_ids; substance none | parent org_id | quarantine, erase at cutover | yes | yes | yes | legacy_quarantine |
| legacy.research_learning_ledger | research_templates/{t}/learning_ledger | Firestore | TEMPLATE | captured_by, evidence.session_id | parent | B3 handler (census row) | yes | yes | yes | legacy_handler_needed |
| legacy.research_chat_sessions | research_chat_sessions (+messages) | Firestore (olbrain_shared) | SESSION | started_by (+name, email) | org_id | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.research_trajectories | GCS research/runs/{run}/trajectory/ | GCS | RUN | run_id | RunMeta.org_id | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.research_runs_reports | research_runs + reports (+ public share tokens) | Firestore + GCS | RUN | started_by; third parties unkeyed | org_id | minimise at source; record in ledger | yes | no | no | external_gap |
| legacy.workflow_agent_memory | workflow_agent_memory (+_archive) | Firestore | AGENT | run ids; raw original_data | none | quarantine, erase at cutover | yes | yes | yes | legacy_quarantine |
| legacy.workflow_trigger_payload | workflow_runs.trigger_payload | Firestore | RUN | undeclared payload fields | organization_id | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.workflow_items | workflow_items | Firestore | ITEM | data fields | organization_id | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.workflow_run_traces | workflow_run_traces (counters) | Firestore | RUN | run_id | via run | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.workflow_agent_decisions | workflow_agent_decisions | Firestore | RUN | run_id, item_id | none | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.context_facts | context_facts / context_consolidation | Firestore | SCOPE cascade | free-text subject/object | scope_key | retire writer, delete | yes | yes | no | legacy_retire |
| legacy.owner_lessons | agents/{id}/owner_lessons | Firestore | AGENT | created_by, owner session | via agent | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.agent_versions | agents/{id}/versions (snapshots) | Firestore | AGENT | content (lessons/examples) | via agent | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.published_config | GCS configs/{agent}/active_config.json | GCS | AGENT | content (approved knowledge inlined today) | via agent | B3 handler (census row) | yes | no | yes | legacy_handler_needed |
| legacy.builder_sessions | alchemist_* / agentify_sessions/*/messages / dendrite_sessions | Firestore | SESSION | member uid | org | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.brds | BRDs | Firestore/GCS | AGENT | member uid; may contain customer data | org | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.agent_qa_runs | agent_qa_runs | Firestore | RUN | correlation.session_ids | org_id | retention bound (TTL/lifecycle) | yes | no | no | retention_only |
| legacy.mcp_tool_executions | mcp_tool_executions | Firestore | CALL | none (args/results content) | none | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.privacy_compliance_log | privacy_compliance_log | Firestore | ORG | shop/customer refs | org | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.usage_events | usage_events | Firestore | EVENT | session_id (phone-bearing) | organization_id | rekey to pseudonymous refs | no | no | no | pseudonymise |
| legacy.message_billing_records | message_billing_records | Firestore | AGENT | [UNRESOLVED] | organization_id | [UNRESOLVED: missing repository] | no | no | no | blocked_missing_repo |
| legacy.payments | payments | Firestore | AGENT | none | organization_id | n/a | no | no | no | not_person_data |
| legacy.agent_analytics | agent_analytics/{agent}/days|months | Firestore | AGENT | [UNRESOLVED] | via agent | [UNRESOLVED: missing repository] | no | yes | no | blocked_missing_repo |
| legacy.agent_standups | agent_standups | Firestore | AGENT | [UNVERIFIED] | via agent | B3 handler (census row) | yes | yes | no | legacy_handler_needed |
| legacy.tickets | tickets | Firestore | TICKET | customer.{name,email,phone}, session_id | organization_id | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.gcs_attachments | GCS agent_sessions/{session}/attachments, webhook-uploads, whatsapp_compressed | GCS | SESSION | session in path (not for whatsapp_compressed) | org prefix (webhook only) | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.gcs_generated_exports | GCS generated_pdfs/charts, exports/{org}, audit-exports | GCS | AGENT/ORG | content only | prefix | retention bound (TTL/lifecycle) | yes | no | no | retention_only |
| legacy.kv_gcs | KV {prefix}/text|raw|cards | GCS | AGENT/ORG/CLIENT | none (content) | prefix | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.kv_fts | KV fts.sqlite | GCS | PREFIX | none | prefix | B3 handler (census row) | yes | no | yes | legacy_handler_needed |
| legacy.kv_blobcache | KV BlobCache (process, 1 h) | memory | PROCESS | none | none | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.knowledge_library | knowledge_library | Firestore | ORG | [UNVERIFIED] | org | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.research_clients | research_clients | Firestore | ORG | company names/aliases (may name persons) | org | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.cloud_logging | Cloud Logging | GCP | LOG | raw phone, session ids, DM text, step outputs | labels | retention bound (TTL/lifecycle) | yes | no | no | retention_only |
| legacy.bigquery_logs | BigQuery service_logs / audit dataset | GCP | LOG | as Cloud Logging | agent_id field | retention bound (TTL/lifecycle) | yes | no | no | retention_only |
| legacy.slack_sendgrid_excerpts | Slack / SendGrid escalation excerpts | external | SESSION | content | — | minimise at source; record in ledger | yes | no | no | external_gap |
| legacy.report_emails | report emails (7-day signed URLs) | external | RUN | content link | — | minimise at source; record in ledger | yes | no | no | external_gap |
| legacy.subprocessor_anthropic | Anthropic (prompts) | external | CALL | content | — | minimise at source; record in ledger | yes | no | no | external_gap |
| legacy.subprocessor_groq | Groq (KV tables lane) | external | CALL | content | — | minimise at source; record in ledger | yes | no | no | external_gap |
| legacy.subprocessor_gemini | Gemini (identity capture + MCP captcha) | external | CALL | end-user text | — | minimise at source; record in ledger | yes | no | no | external_gap |
| legacy.provider_prompt_cache | provider prompt caches (5 min–1 h) | external | CALL | content | — | retention bound (TTL/lifecycle) | yes | no | no | retention_only |
| legacy.inprocess_caches | ~20 in-process TTL caches | memory | PROCESS | varies | — | retention bound (TTL/lifecycle) | yes | no | no | retention_only |
| legacy.backups | Firestore/Cloud SQL backups + PITR | GCP | PROJECT | all | project | retention bound (TTL/lifecycle) | yes | no | no | retention_only |
| legacy.pii_token_vault | PII token vault | external | ORG | tokens ↔ values | [UNRESOLVED] | [UNRESOLVED: missing repository] | yes | no | no | blocked_missing_repo |
| legacy.coordination | engine_jobs, agent_wakes, leases, driver claims, FE dispatched/* | Firestore | JOB | ids (session/run) | org/agent | retention bound (TTL/lifecycle) | no | no | no | retention_only |
| legacy.finance_uploads | finance-engine workbooks + deck templates | GCS/Firestore | ORG | content (may contain customer financials) | org | B3 handler (census row) | yes | no | no | legacy_handler_needed |
| legacy.iam_members | organizations/{org}/members, memberships(_index), user_profiles | Firestore | ORG | uid, name, email | org | B3 handler (census row) | no | no | no | legacy_handler_needed |
| legacy.api_keys_share_tokens | api_keys, organization_api_keys, share tokens | Firestore | ORG | creator uid | org | n/a | no | no | no | not_person_data |
| legacy.noesis_stores | olbrain-noesis-os stores | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED: missing repository] | yes | no | no | blocked_missing_repo |
| legacy.voice_gateway_stores | voice gateway (recordings/transcripts?) | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED: missing repository] | yes | no | no | blocked_missing_repo |
| legacy.billing_service_db | billing/metering service store | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED: missing repository] | no | no | no | blocked_missing_repo |
| legacy.directives_store | agent-directives (campaigns, opt-out enforcement) | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED] | [UNRESOLVED: missing repository] | yes | no | no | blocked_missing_repo |
| legacy.dedicated_tenant_copies | dedicated physical tenants (e.g. clix-capital-prod): every store above | per project | TENANT | as above | project | B3 handler (census row) | yes | no | no | legacy_handler_needed |
