# Legacy Erasure Census v1 (Lane A, A5)

**Date:** 2026-10-01.

**Classification.** Current-state columns are **VERIFIED CURRENT** at `origin/main`, unless marked otherwise. Handler design and disposition columns are **TARGET ARCHITECTURE**.

**Commits:**

| Prefix | Repository | Commit |
|---|---|---|
| RT | agent-runtime | `daee3f9` |
| EN | agent-engine | `dfc3a47` |
| AD | agent-design | `c56271d` |
| EV | agent-eval | `6c289ca` |
| KV | knowledge-vault | `25b46be` |
| MCP | mcp-deployer | `b75cc12` |
| RR | research-runtime | `6b81691` |
| SH | shared | `d0e0d2b` |
| SB | studio-backend | `5da93ae` |
| WF | workflow-runtime | `2356de0` |

**Builds on:** MAP §3–§4, `store-inventory.md`, `storage-reality-audit.md`, `firestore-inventory-closure.md`.

**Feeds:** `memory-lifecycle-registry-v1.md` (A4), roadmap B3.

## 0. Cross-cutting facts

1. **There is no canonical person key anywhere.** The only way to find a person is the **session spine**: person → sessions → everything keyed by `session_id`. How to find a person's sessions depends on the channel:

   | Channel | How to find a person's sessions |
   |---|---|
   | WhatsApp | Doc-id prefix `{sanitised phone}-{agent}`, **plus** the raw `phone_number` field. Both forms must be queried (RT `meta_whatsapp.py:718-751`) |
   | Directives | The same id scheme (`directives.py:113-136`) |
   | Instagram | `ig-{igsid}-{agent}`. The IGSID is stored in **`phone_number`** (`meta_instagram.py:203,222`) |
   | Slack | `slack-{channel}-{user}-{agent}` (`slack.py:140`) |
   | Email | `email-{thread}-{agent}`: **one session per thread, not per person**. Find by `from_email` (`email.py:270,459`) |
   | Web/webhook | Random session id, with `user_id` asserted by the caller. Reassignment leaves `identity_migrated_from` (`agent_webhook.py:2295-2310`), so **both fields must be queried** |
   | LLM-extracted `user_name/email/phone` | An unreliable extra recall path (`agent_webhook.py:769-779`) |

2. **Indexes.** Six repositories ship `firestore.indexes.json`, and none has `fieldOverrides`. So:
   - there are no TTL policies;
   - there are no COLLECTION_GROUP single-field indexes;
   - equality lookups work today;
   - cross-agent sweeps over subcollections need new collection-group overrides: `patterns.source_session_id`, `entries.session_id`, `learning_ledger.captured_by`.

   Which index file is actually deployed is `[UNRESOLVED]`.
3. **No tombstone exists, and every post-turn writer upserts.** Merge-writers on `agent_sessions` (summariser, insights, sentiment, identity capture, judges, disposition, escalation stamp, finance context, the message write itself) recreate a deleted document (`set(merge=True)`). A tombstone check (the derivation fence, RT R-6) is a **precondition** for any handler that deletes.
4. **Corrections to the earlier map** (CONTRADICTED BY SOURCE):

   | Earlier claim | What the source shows |
   |---|---|
   | `agent_traces` and `workflow_run_traces` hold content | They are **counters only** in Firestore. The 240 KB bodies go to Cloud Logging and OTel (SH `trace_collector.py:24,742-800`; WF `trace_collector.py:12-17`) |
   | `workflow_items` has no org field | It **has** `organization_id` (WF `orchestrator.py:3296-3307`) |
   | Gemini is used only for MCP captcha | Gemini **also receives raw end-user text** for session identity capture (RT `agent_webhook.py:~726-778`). This is a new subprocessor path |
   | `mcp_tool_executions` is "never purged / unmasked" | Logging is **opt-in** per deployer project. Shopify `shop/redact` purges. Secret-named keys are redacted. **PII is still not redacted**, and `customers/redact` deletes nothing |
   | Contact erasure is a complete person erasure | It is complete for lead stores **only**. Sessions, messages, memory and datastores are untouched |
   | `agent_messages` org is "PARENT" only | Live rows carry `organization_id`. Legacy rows carry none, or `'default'` (`message_processor.py:586-672`), so an org sweep misses them |

## 1. Census

**Legend:**
- **Res.** = resurrection risk (which writer recreates data after deletion).
- **Reb.** = rebuild risk (which job re-derives the data).
- **Disp.** = migration disposition:
  - **H** = handler on the legacy store (phase B3);
  - **Q** = quarantine, then erase at cutover;
  - **R** = retire the writer;
  - **M** = migrate into v2 (as `legacy` or re-derived);
  - **P** = pseudonymise;
  - **X** = external or out of platform control.

| # | Store/path | Scope | Identifier today | Subject lookup | Org lookup | Raw text | Dup. / derived from | Deletion today | Res. / Reb. | Missing | Owner | Missing repo | Handler design (target) | Disp. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `agent_messages` | message | `session_id`, `agent_id`, `channel`; **no person key**; org on live rows only | `session_id in spine` (indexed) | `organization_id` (misses legacy) | yes. `content` stays raw even under tokenisation (`lightweight_processor.py:2642-2648`); `pii_redactions.tokenized_content` is a 2nd copy | — | none (only aborted-turn deletes, `:1743,1755`) | Res: none for the doc. Session upsert on write | `subject_id` per row; org on legacy rows | RT | PII token vault; Noesis | Delete by spine; also delete the `tokenized_content` copy and GCS attachments by `storage_path` | H, then v2 evidence (binding stamps) |
| 2 | `agent_sessions` (+summary, identity fields, judges, sentiment, disposition, title) | session (permanent per person on WA/IG/Slack) | Doc id embeds the **raw phone/IGSID**; `phone_number`, `user_id`, `identity_migrated_from`, `from_email` | Spine (equality and prefix) | `organization_id` | yes. `summary` is **detokenised** before storage (`agent_webhook.py:420-429`) | Messages | **soft** (`status:'completed'`, `sessions.py:285`) | Res: **high**: about 9 merge-writers (§0.3). Reb: insights full refresh reads 50 messages | Tombstone; opaque ids (P3) | RT | `title` writer and idle sweeper (`[UNRESOLVED: missing repository]`: Noesis, analytics-service) | Hard delete plus a tombstone checked by every post-turn writer (fence library) | H; summary R (NARRATIVE); judges P (ANALYTICS) |
| 3 | `agent_user_memory` | agent × raw key | doc id `{agent}__sha256(user_key)[:32]`; `channel_user_id` raw | Hash per agent, or `channel_user_id==` | `organization_id` | yes (facts include **assistant** text, `agent_memory_service.py:435-440`) | Messages | hard, one doc (`agent_memory.py:88`) | Res: the extractor's fire-and-forget read-then-merge recreates it | Channel in the key (N1); tombstone | RT | — | Delete across all agents of the org, for every identifier form | H, then M (`legacy`), then Q |
| 4 | `agent_datastores/.../entries` | person (extract) / session (tool) | Extract: unsalted `person_hash(user_key)`; tool: `session_id`; **no org on entries** | Hash then `get`, or `session_id==` per table. **Cross-agent needs a CG index** | Via the table only | yes | Extractor | Hard per entry (AD); not cascaded | Res: extractor `merge=True` | Org; CG index; salted key | RT + AD | — | Per agent and table delete; CG index first | H, then M (declared predicates) |
| 5 | `agent_learned_patterns/{agent}/patterns` | agent-wide | `source_session_id` only. Examples carry **other people's** verbatim messages | Per agent `source_session_id in spine`; cross-agent CG index missing. **Content scan** for embedded examples | none | **verbatim** | Messages, tool output | none (deactivate only) | Res: the learner writes a new uuid each run | Org; per-example provenance | RT `core/learning/*` | — | Cannot be made reliably subject-erasable → **quarantine the store** | Q, then R (re-derive as Agent Knowledge) |
| 6 | `agent_disposition_taxonomy` | agent-wide | none | content scan | via agent | LLM labels | Conversations | none | Res: the classifier's `record_proposal` | Provenance | RT | Noesis promotion | Lineage-or-retire (Agent Knowledge, k) | M or R |
| 7 | `agent_users` | agent × channel × id | raw `channel_user_id`, `phone_number`, `email`; org sometimes `""` | Equality (works) | **unreliable** | identifiers | Inbound messages | none | Res: **the upsert on the next inbound message**. **Deleting drops `opted_out_at` (consent lost)** | Consent ledger first | RT `firebase_service.py:274-345` | Opt-out enforcement in directives `[UNRESOLVED: missing repository]` | 1) Move consent to the CONSENT ledger (suppression HMAC); 2) delete; 3) the upsert checks the tombstone | H (ordered) |
| 8 | `lead_profiles` / `lead_contacts` / `lead_activity` | session / org / person_key | contact, hashed contact, `person_key` | `erase_by_contact` | `organization_id` | yes | Conversation, tools | **hard, phased, reports complete** (lead-scope only) | Res: a later lookup or upsert | — | RT `lead_contacts.py` | — | Reuse as is; wire it into the orchestrator as one step | H (precedent) |
| 9 | `agents/{id}/documents.shared_with[]` (**new**) | agent doc | `user_id`, `session_id` in an array of maps | per-agent scan | via agent | ids | — | none | Every share (`ArrayUnion`) | Restructure | RT `agent_webhook.py:1580-1590` | — | Remove the array entries; long term, a subcollection keyed by subject | H |
| 10 | `agent_traces` | message | `session_id` (embeds phone), counters only | `session_id==` | `organization_id` | **no** (counters) | — | none | — | Opaque session ids | SH | — | Delete by spine (it carries the phone-bearing session id) | H/P |
| 11 | Research `learned/{profile,design,substance}` | template, across users | Profile: `provenance.contributors[]` (uids) + `session_ids[]`; substance: none; no org | **scan every template**, filter in memory | parent `org_id` | LLM statements from raw transcripts | Chat transcripts | none; orphaned by template delete | Res: the consolidator reads **archived** sessions; LEARN after delete | Org; per-item subject | SH/RR | — | MEMBER-class erasure (the subjects are platform users). Remove the contributor, then re-derive or retire. Template delete cascades | M (Agent Knowledge) |
| 12 | Research `learning_ledger` | template | `captured_by`, `evidence.session_id/run_id` | Per template `captured_by==`; CG index missing | parent | statements | Transcripts | none (no API) | Capture tool | CG index | SH | — | Delete by `captured_by` / session | H |
| 13 | `research_chat_sessions` (+messages) | session | `started_by` (+name, email), `org_id`, `history_summary` | `started_by==` | `org_id` | yes | — | soft (`archived`) | The consolidator reads archived sessions | — | SH/RD | — | MEMBER erasure: hard delete; the consolidator checks the tombstone | H |
| 14 | Research trajectories (GCS, **on by default**) | run | `run_id` | runs (by uid, org) → prefix delete | `RunMeta.org_id` | **full wire prompts** | Everything | none | — | Bucket lifecycle `[UNRESOLVED]` | RR `config.py:54-60` | — | Prefix delete per run; a lifecycle TTL bounds the rest `[BLOCKED:Legal value]` | H + retention |
| 15 | Third parties named in research outputs | run | **not keyed** | — | — | yes | Web | none | — | — | RR | — | No path. RT M-14 `[BLOCKED:Legal]` | X (gap) |
| 16 | `workflow_agent_memory` (+`_archive`) | agent | `learned_from_run_id`, `evidence_run_ids`, raw `original_data`; no org | runs → load the doc → filter; **content scan** | none | **verbatim item data** | Items | `delete_pattern`; archive on transfer | Res: **whole-document read-modify-write `set()` without merge** (WF `agent_memory_service.py:246-482`) overwrites deletions | Org; CAS | WF | — | Quarantine patterns that hold `original_data`. Overrides move to workflow rules (RT M-3) | Q, then R/M |
| 17 | `workflow_runs.trigger_payload` | run | arbitrary payload | **content scan** | `organization_id` | yes | Webhook caller | none | Scheduler or webhook retries (duplicate runs) | Declared subject field at the trigger | SH/WF | Webhook service `[UNRESOLVED: missing repository]` | Declare person fields in the workflow schema; delete by declared field; retention bound for the rest | H + retention |
| 18 | `workflow_items` | item | `run_id`, `record_id`, `organization_id`, `data` | `run_id==`/`record_id==`; content scan | indexed | yes | Payload, step outputs | none | A retry re-sets a deterministic id | Subject key | WF | — | As 17 | H |
| 19 | `workflow_run_traces` / `workflow_agent_decisions` | run | ids, counters | `run_id` | via run | no | — | none | Every override apply | — | WF | — | Delete with the run (ids only) | H |
| 20 | `context_facts` / `context_consolidation` | session → platform | free-text subject/object; `scope_key` | **content scan** | `scope_key` | LLM-distilled builder chats | Builder chats | **none by design** | Consolidator (flag off) | Subject field | EN | — | MEMBER-class; retire or re-derive with lineage | R/M |
| 21 | `owner_lessons` → `versions` → `active_config.json` | agent | `session_id` (owner), `created_by`, `owner_text`, `body` | content scan | via agent | owner text (end-user text only if pasted) | Owner | `delete_lesson` (`lessons.py:49`); **applied content persists in snapshots and the published blob** | Lesson apply; deploy snapshots | — | EN/AD | `versions` content `[UNVERIFIED]` | PII scan at lesson create. Erasure re-publishes without the content; snapshots hold ids only (RT C-6.5) | H + R |
| 22 | `agent_qa_runs` | eval | `session_ids[]`, `per_call[].transcript` | `array-contains` | `org_id` | transcripts | Eval sessions | none | — | — | EV | Persona provenance `[UNVERIFIED]` | Eval namespace + TTL (P14) | H + retention |
| 23 | `mcp_tool_executions` | call | `agent_id`, `server`, `tool`, `arguments`, `result` (≤10 KB); **no session, org or user** | **none**: agent + time + content scan | via agent | yes (PII not redacted) | Tool I/O | Only Shopify shop-redact. **`customers/redact` deletes nothing and logs that nothing is stored** (`privacy_webhook_service.py:144-185`) | — | `session_id`, `org_id`, `subject_id` | MCP `tool_execution_logger.py:215-270` | Deployer project config (on/off in prod) `[UNRESOLVED]` | Add keys at write. Until then, a retention bound plus purge per agent. **Fix `customers/redact`** (flag it to the security owner) | H + retention |
| 24 | `usage_events` | event | `session_id` (phone-bearing), `message_id`, org, agent; ids `cs_{session}` | `session_id==` | indexed | no content | — | none | create-if-absent re-creates after delete | Opaque session ids | SH/RT | Billing/metering `[UNRESOLVED: missing repository]` | **Pseudonymise** (rekey session refs); retain under legal basis `[BLOCKED:Legal]` | P |
| 25 | `message_billing_records` / `payments` / `agent_analytics` | org/agent | agent/org; schema `[UNRESOLVED]` | `[UNRESOLVED]` | org | ? / no / ? | — | none | — | — | cloud-functions; analytics | `[UNRESOLVED: missing repository]` | Classify after the repositories are available | P / `[UNRESOLVED]` |
| 26 | `tickets` | ticket | `customer.{name,email,phone}`, `session_id`, `conversation[]` | `customer.email==`, `session_id==` | indexed | yes | Conversation | close only | Nexus re-files | — | EN nexus | — | Hard delete by spine and email | H |
| 27 | GCS attachments | file | `agent_sessions/{session}/attachments/*`; `webhook-uploads/{org}/{agent}/{file}`; **`whatsapp_compressed/{file_id}.jpg` has no session in the path** | Session prefix + `storage_path` from messages | org prefix (webhook only) | files | — | none | — | Subject in the path | RT | — | Delete by path from row 1 before deleting messages (order matters) | H |
| 28 | GCS generated and exports (`generated_pdfs`, charts, `exports/{org}`, `audit-exports`) | agent/org | content only | none (content) | prefix | yes | Tools | none (lifecycle on clix only) | — | Index of outputs per session | RT/SB | — | Retention lifecycle plus an output index per session going forward | retention |
| 29 | KV `text/raw/cards`, `fts.sqlite`, BlobCache | source | `source_id` under prefixes | **no person index** | prefix | yes | Uploads, conversations | `_delete_source_at_prefix` (text, cards, raw), **BlobCache not invalidated**; FTS rebuild only when `DCI_INGEST_ARTIFACTS` is set | Rebuild races | Person index for conversation-derived documents | KV `file_service.py:700-791` | — | Invalidate the cache on delete; FTS rebuild after delete; documents derived from conversations carry a subject ref | H |
| 30 | Cloud Logging / BigQuery `service_logs` | log | raw phone in messages (`meta_whatsapp.py:735`), `session_id` labels, step outputs | text search | label | yes | Everything | IAM retention only | — | Sink and retention config `[UNRESOLVED]` (no IaC) | all | — | S0-6 (PII-free logs) plus a retention bound. Lumen row isolation (RT C-6) | retention + R |
| 31 | Slack / SendGrid escalation excerpts | external | last N messages; tokenised only under the PII policy | — | — | yes | Messages | cannot be recalled | — | — | RT `escalation_notify.py:39-72` | — | Send links, not excerpts (RT R-6). Record the export in the ledger | X + R |
| 32 | Subprocessors (Anthropic, Groq, **Gemini: identity capture + MCP captcha**) | external | — | — | — | yes | Prompts | provider terms | — | DPAs | — | `olbrain-llm` `[UNRESOLVED: missing repository]` | `[BLOCKED:Legal]`. Retire Gemini identity capture (A6 row 2b) | X |
| 33 | In-process caches, provider prompt caches | memory | — | — | — | yes | — | TTL (30 s–1 h) | — | — | all | — | TTL-bounded. No person content in in-process caches (RT M-9) | retention |
| 34 | Backups / PITR | store | — | — | — | yes | Stores | clix: daily 14 d, weekly 90 d, PITR; india-prod `[UNRESOLVED]` | **Restore resurrects** | WORM ledger replay (A8) | ops | GCP config `[UNRESOLVED]` | Restore protocol (`memory-restore-protocol-v1.md`) | retention + replay |
| 35 | PII token vault | external | tokens ↔ values | `[UNRESOLVED]` | — | yes | Messages | `[UNRESOLVED]` | — | — | — | `pii_client` `[UNRESOLVED: missing repository]` | Required before production | `[UNRESOLVED]` |

## 2. Required ordering for a legacy forget-me (B3)

1. **Consent first.** Write the suppression entry (keyed HMAC) to the consent ledger before deleting `agent_users` (row 7). Otherwise the opt-out is lost.
2. **Tombstone.** Write the binding tombstone (subject `erased`, epoch+1). Every post-turn writer checks it through the fence library. Without this step, rows 2, 3, 4, 7, 16 and 17 are re-created by in-flight jobs.
3. **Resolve the spine.** Query every identifier form: raw and sanitised phone, `user_id` **and** `identity_migrated_from`, `from_email`, IGSID in `phone_number`.
4. **Paths before rows.** Delete GCS objects by `storage_path` before deleting the messages that reference them (row 27 before row 1).
5. **Run the per-store handlers** (rows 1–29), each idempotent and reporting `done/partial/not_applicable/retained_legal_basis`.
6. **Pseudonymise** rows 24–25.
7. **Quarantine** stores that cannot be made subject-erasable (rows 5, 16), pending cutover.
8. **Record what cannot be reached** in the ledger: external excerpts, subprocessors, backups within the window.

## 3. Blockers

| Kind | Items |
|---|---|
| **Missing repositories** | PII token vault; noesis-os (`title`, taxonomy promotion); analytics-service; cloud-functions; billing/metering; agent-directives (opt-out enforcement); webhook service (trigger payloads); voice-gateway; olbrain-llm |
| **Unverified** | Deployed index file; `versions` snapshot content; co-designer decision variant; eval persona provenance; trajectory and BigQuery retention; whether MCP execution logging is on in production |
| **Owner decisions** | Retention values (R-M3, Legal); billing legal basis; third parties in research outputs; subprocessor DPAs |
| **Security, to flag** | Shopify `customers/redact` is a no-op that reports compliance; email instructions inject raw `from_email` without a PII gate (A6) |
