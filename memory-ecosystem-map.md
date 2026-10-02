# OLBrain Ecosystem Information Map (memory architecture v2, Phase 1)

**Date:** 2026-09-30.

**Method.** Read-only tracing at `origin/main` of all 13 repositories:

| Repository | Commit |
|---|---|
| agent-runtime | `daee3f9` |
| agent-engine | `dfc3a47` |
| agent-design | `c56271d` |
| agent-eval | `6c289ca` |
| finance-engine | `bf4d2b6` |
| knowledge-vault | `25b46be` |
| mcp-deployer | `b75cc12` |
| research-design | `e218f10` |
| research-runtime | `6b81691` |
| shared | `d0e0d2b` |
| studio | `1f05ca11` |
| studio-backend | `5da93ae` |
| workflow-runtime | `2356de0` |

This extends the existing inventories, which are not repeated here: `store-inventory.md`, `storage-reality-audit.md`, `firestore-*`, `person-identity-*`, `agent-memory-investigation.md`.

**Tags.** `[CODE]` unless marked `[INFERENCE]` or `[UNRESOLVED]`.

**Repositories referenced by code but absent from the workspace** `[UNRESOLVED]`:
- olbrain-noesis-os (operator UI and BFF)
- olbrain-voice-gateway
- olbrain-llm (the LLM metering seam)
- the billing service
- olbrain-analytics-service (writes `agent_analytics`)
- olbrain-cloud-functions (billing scheduler)
- olbrain-agent-directives, the webhook service and the admin dashboard

---

## 1. The headline: OLBrain already has at least nine memories, and only one is called "memory"

Agents today take durable knowledge from many stores built independently. Their scoping, provenance, erasure and trust models differ. **Treating "memory" as `agent_user_memory` alone is the core architectural error to correct.**

| # | De-facto memory | Surface | Scope | Learned from | Reaches prompts | Org field | Erasable |
|---|---|---|---|---|---|---|---|
| M1 | `agent_user_memory` facts plus `agent_datastores` entries | CS runtime | agent × raw channel key | the end user (extractor reads the assistant text too) | yes, every turn | yes | partially (one document) |
| M2 | `agent_sessions.summary`, written by **two** writers: the rolling summariser and the "insights" job (plaintext, detokenised) | CS runtime | session. On WhatsApp, IG and Slack the session is effectively permanent (`{phone}-{agent}`) | the conversation | yes, every turn | via session | no (session delete = `status: completed`) |
| M3 | `agent_sessions.user_name/user_email/user_phone`, extracted by an LLM | CS runtime | session | user text | [UNRESOLVED] | via session | no |
| M4 | `agent_learned_patterns` | CS runtime | **agent-wide**, across users | up to 3 verbatim user messages plus tool outputs, including finance figures | yes, forced recall, rendered as "ground truth" | **none** | no |
| M5 | Research `learned/*` profile, design, substance and enforcement, plus the `learning_ledger` | research | **template-wide, across users** | the model records learnings silently; the consolidator reads **raw transcripts** | yes, every chat turn and every run | **none** | no; orphaned by template delete; the consolidator reads *archived* sessions |
| M6 | `workflow_agent_memory`: patterns and overrides, with raw item copies | workflow | agent-wide | human exception resolutions over item data | yes, to the critic and co-designer; overrides **auto-mutate items** | **none** | no; a concurrent learn can re-create a deleted pattern |
| M7 | `owner_lessons` into `agent_core.additional_context`, plus version snapshots | builder (Dendrite) | agent | owner-authored, confirmed | yes, baked into the brain | via agent | apply is irreversible in the snapshots |
| M8 | `context_facts` / `context_consolidation`; Cortex compaction markers | builder (Cortex/Alchemist) | session to platform, a cascade in `scope.py` | builder conversations | yes | via scope | **no delete path** |
| M9 | `agent_traces/{message_id}` (full tool results, up to 240 KB per field); research **trajectories** in GCS (full wire prompts, on by default); `workflow_run_traces`; eval `agent_qa_runs` transcripts | all | per message, run or eval | everything | not directly, **but** Axon/Lumen (the debug agent) queries logs and traces through BigQuery and Firestore | mixed | no |

Other context that is **not** learned memory but is part of what an agent "knows":
- published config and brain (GCS `active_config.json`, cached 300 s; KB preload up to 200 k chars);
- the knowledge vault (DCI: BM25 plus LLM passage selection, no vectors; index cards are LLM-derived copies of documents);
- MCP tool results, which are third-party business data;
- the finance cerebellum: deterministic tools, whose results enter as raw JSON;
- finance-engine deck templates, where LLM vision output is re-fed as later input;
- trigger payloads in workflows;
- BRDs in the builder.

---

## 2. Context construction by surface (what enters an LLM prompt)

| Surface | Person memory | Session history | Summaries | Agent-wide learned | Org knowledge | Tool results | Config |
|---|---|---|---|---|---|---|---|
| **CS turn** (runtime `cs_packet_builder.py:611-1244`) | ✔ M1 (unconditional, undated, in the system prompt when `prompt_cache_v2` is off) | ✔ up to 500 messages, 8 k tokens (3.5 k on voice), `ts` stripped | ✔ M2, framed as a user message | ✔ M4 as "ground truth" | ✔ BM25 tool plus 200 k preload | ✔ MCP, DCI, cerebellum (raw JSON), persisted in `agent_traces` | ✔ |
| **Voice** (same path; gateway missing) | ✗ unless the gateway sends a stable `user_id` (caller number hard-coded `None`, `agent_webhook.py:2745`) | ✔ 3.5 k tokens | ✔ forced backstop summariser | ✔ | ✔ | lead tools | ✔ `VOICE_PROMPT_BLOCK` |
| **Research chat and runs** (`conversational_planner.py:498-926`) | ✗ (no per-person memory) | ✔ the full session, with compaction off by default | optional compaction | ✔ M5 (preferences, insights, design, into planner and chat; the writer receives preferences only) | ✔ `search_org_knowledge` (gatherer only) | ✔ web, MCP, trajectories persisted | ✔ template |
| **Workflow steps** (shared executors) | ✗ | n/a | n/a | ✔ M6 (retriever, Opus critic, co-designer, BRD) | ✔ knowledge edges | ✔ MCP, unbounded tool JSON | ✔ identity preamble; raw `trigger_payload` via templates |
| **Cortex builder** (`agentify_agent.py`) | ✗ | ✔ 100 messages | ✔ compaction marker promoted to the system prompt, **with no provenance check** (unlike Synapse) | ✔ M8 via Vibe recall | ✗ | BRD tools | ✔ |
| **Dendrite trainer** | ✗ | ✔ 30 messages of the owner thread | ✗ | ✔ lessons list | ✗ | `propose_change` | ✔ the live brain |
| **Finance engine LLM** (ingestion and mapping) | ✗ | ✗ | ✗ | deck templates (LLM output re-fed as input) | ✗ | ✗ | raw workbook cells, **no redaction** |
| **Axon/Lumen debug agent** (engine) | indirectly: BigQuery over logs, learned patterns, eval runs | — | — | ✔ reads M4 | — | SQL results (SELECT-only, byte-capped) | — |
| **Eval persona** | ✗ | the eval transcript | — | — | — | — | persona YAML |
| **Knowledge-vault ask** | ✗ | ✗ | ✗ | ✗ | the whole corpus (up to 50–150 k tokens) or routed documents, **plus the end-user query** (Haiku; the tables lane uses **Groq**) | — | — |

---

## 3. Durable stores by class

The rows below are additions to the existing inventories. "NEW" means an earlier document did not have it.

| Class | Stores |
|---|---|
| **Evidence** (raw) | `agent_messages` (client-readable **and writable**, cross-tenant, `firestore.rules:888-959`); `agent_sessions` (plus `phone_number`); `alchemist_*`, `agentify_sessions/*/messages`, `dendrite_sessions`, research chat sessions (olbrain_shared); `workflow_runs.trigger_payload`, `workflow_items`; FE uploads; GCS attachments |
| **Person-derived** | M1–M3; `agent_users` (raw identifiers, IDOR); `lead_profiles/contacts/activity`; **NEW** `agent_disposition_taxonomy`, session `sentiment_score`/`disposition`/`goal_outcome`/`closing_summary`; `tickets` (Olbrain support, customer PII, not rule-excluded) |
| **Agent- or template-wide learned** | M4–M8 |
| **Telemetry and traces** | **NEW** `agent_traces`; research trajectories (GCS); `workflow_run_traces`; `mcp_tool_executions` (**unmasked results; no org field; never purged**); `privacy_compliance_log`; Cloud Logging (email senders, IG DM text, phones, `channel_user_id`, and up to 500-byte MCP results); `workflow_agent_decisions` |
| **Analytics and billing** | `usage_events` (keys embed session ids, which **embed raw phone numbers**); `payments` (**non-idempotent id**); `message_billing_records`; `agent_analytics` (missing repo); `agent_standups`; BigQuery (audit and log dataset); audit CSV exports in GCS (never expire) |
| **Config and knowledge** | `agents/{id}` (**client-writable tenancy root**); `agents/{id}/versions` (client-writable); published blobs (retained on delete); knowledge vault GCS (text, raw, cards, `fts.sqlite`); `knowledge_library`; `research_templates`; BRDs |
| **Identity and authorization** | `memberships`, `memberships_index` (a good design); `organizations/{org}/members` (**readable by any signed-in user**); `api_keys`; `organization_api_keys`; share tokens; `research_clients` (**the only model of a customer company**) |
| **Coordination** | `research_run_driver_claims`, `agent_wakes`, leases, FE `dispatched/*`, `engine_jobs` (never deleted) |
| **Queues** | Cloud Tasks (engine consolidation, with no task name; FE jobs, with deterministic names); Pub/Sub (research runs **acked before work**; four DLQs with **no consumer**); Cloud Run Jobs; many fire-and-forget `create_task` jobs (memory extractor, insights, pattern learner, dispositions, title generation) |
| **Caches** | About 20 in-process TTL caches (30 s to 3,600 s; some unbounded); KV BlobCache (500 MB, 1 h, **not invalidated on delete**); provider prompt caches (5 min to 1 h); **no Redis in use** (optional rate-limit backend only) |
| **Other SQL** | Runtime `asyncpg` is a **customer-database query tool** (read-only SELECT), not a platform store. BigQuery is used by Axon/Lumen and audit routes |
| **External copies** | Slack and SendGrid escalation excerpts; report emails (7-day signed URLs); LLM subprocessors (Anthropic, Groq in the KV tables lane, Gemini in MCP captcha, whose billing goes to the hard-coded org `olbrain-labs`) |
| **Backups and retention** | Only clix-capital-prod has IaC: daily backups (14 d), weekly (90 d), PITR, and GCS lifecycle 365 d (audit bucket locked for 7 years). Its TTL policies are **inert**, because no code stamps `expires_at`. **No IaC** for `olbrain-india-prod` |

---

## 4. Erasure reach: consolidated

The central finding: **no delete path in the platform is complete. Most are soft deletes. Nothing hard-deletes an agent, a project cascade, an org, a template cascade or a session.**

| Operation | What it actually does |
|---|---|
| Forget memory | Deletes one `agent_user_memory` document. It does not cascade, is not fenced, and is resurrected by in-flight writes |
| Contact erasure | `lead_profiles`, `lead_contacts`, `lead_activity`. Idempotent, phased, and reports `complete`. **This is the best precedent** |
| Session "delete" | Sets `status: completed` |
| Chat session delete (research) | `archived=True`. The consolidator still reads it |
| Run delete (research) | Soft. Public share tokens keep serving the report |
| Agent delete | Soft (archive). Everything survives |
| Project delete | Deletes the root document only. The code comment claiming a cascade is false |
| Template delete | Deletes the root document. `learned/*`, the ledger and GCS survive, and late LEARN jobs can still write |
| Org delete or offboard | **Does not exist** |
| Agent transfer | Rewrites sessions. **Messages, user memory, patterns and lessons move with the agent unchanged, or keep the old org** |
| Shopify GDPR `customers/redact` | **Deletes nothing** and logs "no customer data stored", which is false |
| KV document delete | Removes GCS text. The FTS rebuild is off by default, the BlobCache is not invalidated, and rebuild races can re-create cards |
| Retention/TTL | None active anywhere |

**Where a deleted person's data survives** (the union across all slices):
- messages, sessions and their LLM-derived fields;
- summaries;
- learned patterns (verbatim text);
- research learned profiles and ledger;
- workflow memory and its archive;
- `context_facts`;
- `agent_traces`, trajectories and `workflow_run_traces`;
- `mcp_tool_executions`;
- eval transcripts;
- `usage_events`, billing and analytics keyed by phone-bearing session ids;
- Cloud Logging and BigQuery;
- Slack and email excerpts;
- exports and audit CSVs;
- published config snapshots (lessons, examples pasted by owners);
- backups (up to 90 days);
- dedicated-tenant copies;
- provider prompt caches;
- the KV BlobCache and FTS index;
- transferred agents' data, now under a new tenant.

**Async paths that re-derive or resurrect deleted data** (none checks a tombstone, and none exists):
- the memory extractor;
- insights full refresh (re-reads 50 messages);
- the session summariser;
- disposition backfill;
- the pattern learner;
- the `agent_users` upsert;
- close and voice judges;
- the research consolidator (reads archived sessions);
- LEARN_AGENT after template delete;
- LEARN_DESIGN redelivery;
- wake turns;
- workflow exception learning and override apply;
- the co-designer;
- workflow duplicate runs from scheduler or webhook retries;
- the KV artifact rebuild;
- the Cortex/engine context consolidator;
- lesson apply;
- deploy snapshots.

---

## 5. Security findings that constrain the memory design

These are all verified `[CODE]`, except where an [INFERENCE] is marked. Several are new in this pass.

| ID | Finding |
|---|---|
| **K1/N2** | `agents/{id}` is readable and writable by **any signed-in user** and is the **tenancy root of trust** for at least five decisions: API-key org match, `ownsAgent`/`canUseAgent` rules, DCI corpus placement, KV `assert_agent_access`, and `mcp_configs` rules |
| **E1** | `agent_messages`: cross-tenant client read and write |
| **N1** | The **webhook end-user identity is a free-text assertion** by any API-key holder, including share-link visitors, who receive the org's live key. The memory key has no channel component, so asserting a WhatsApp customer's phone number loads that person's memory into the prompt [INFERENCE on the chain; each link is CODE] |
| **Root cause of S-M1** | `require_permission` enforces scopes **only for API keys**; Firebase users always pass (studio-backend and agent-design `auth.py`). So every route gated only on `agents:write` is open to any signed-in user |
| **N3–N6** | These are readable (and, where noted, writable) by any signed-in user: `organizations/{org}/members` (names and emails); `departments` (read/write); `tickets` (customer PII); `agents/{id}/versions` (read/write) |
| **N7** | Platform admin is decided by an `@olbrain.com` email with **no `email_verified` check** |
| **N8** | MCP `tools/call` takes a caller-supplied `agent_id`, auth is off by default, and credentials fall back to `credentials/default:{server}` |
| **Cortex** | Compaction markers are promoted to the system prompt without verification (a prompt-injection path if the messages are client-writable [UNRESOLVED]) |
| **Operator access** | There is no PII-read permission: any org member sees every end user's facts (Noesis rules) |
| **Service authorization** | The shared `INTERNAL_SERVICE_SECRET` acts across orgs, and OIDC tokens carry no org, so services take the org from request bodies |
| **PII to subprocessors** | No redaction on FE workbooks, KV ingestion (Opus OCR, Sonnet cards) or workflow prompts. Groq and Gemini are in the path |

---

## 6. Precedents worth reusing

| Precedent | Where |
|---|---|
| Idempotent phased erasure that reports completeness | runtime `lead_contacts.py:715-768` |
| Derived, self-healing, deterministic, server-only index | `memberships_index` |
| Reversible, audited merge that never rewrites history | `research_clients.merged_into` |
| Server-built tenant prefixes with reserved segments and a traversal guard | KV `resolve_corpus_prefix` |
| Transactional lease plus `expected_version` CAS on learned state | shared `learned_profiles.py` / `learned_designs.py`; the research consolidator |
| Deterministic Cloud Tasks names, a create-if-absent dispatch ledger, finalise-once, supersede-by-subject | FE jobs (`app/jobs/dispatch.py`) |
| Create-if-absent run claims keyed by generation | `research_run_driver_claims/{run}:{gen}` |
| Generation fence plus item-status CAS | workflow orchestrator |
| `usage_events` create-if-absent; billing `request_id` dedup | runtime and shared |
| Owner-confirmed lessons with a status lifecycle, applied deterministically, mutations re-derived from the payload rather than trusted from client-writable arrays | engine Dendrite |
| Guard that rejects agent payloads carrying figures; human-accepted commentary only | FE `refuse_a_figure_or_a_binding` |
| Masking of earlier assistant figures in replayed history; the finance reply guard | runtime cerebellum profile |
| A run-level audit stamp of exactly what learned data was injected | research `LearnedContext{profile_version, injected_item_ids}`, a direct precedent for **prompt manifests** |
