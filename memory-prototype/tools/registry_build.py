"""Lifecycle Registry v1 (Lane A4): the single source for memory-lifecycle-registry-v1.{json,md table}.

Run:  python tools/registry_build.py      (writes ../memory-lifecycle-registry-v1.json and prints the md table)
      python tools/registry_build.py --check   (completeness + schema check; non-zero exit on any gap)

Every entry answers the A4 questions. Abbreviations in the compact rows below are expanded in the JSON.
"""
import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "memory-lifecycle-registry-v1.json")

FIELDS = ["id", "store", "system", "class", "scope_type", "subject_columns", "tenant_columns", "lookup",
          "erasure_handler", "handler_version", "retention_class", "legal_retention", "rebuild_source",
          "index_requirements", "external_dependency", "raw_customer_text", "derived_knowledge",
          "restore_participation", "can_regenerate_deleted", "owner", "status"]

# status vocabulary: target_v2 | legacy_handler_needed | legacy_quarantine | legacy_retire | retention_only |
#                   pseudonymise | external_gap | blocked_missing_repo | not_person_data
R = []


def e(id, store, system, cls, scope, subj, tenant, lookup, handler, hv, ret, legal, rebuild, idx, ext, raw, derived,
      restore, regen, owner, status):
    R.append(dict(zip(FIELDS, [id, store, system, cls, scope, subj, tenant, lookup, handler, hv, ret, legal, rebuild,
                               idx, ext, raw, derived, restore, regen, owner, status])))


NONE = "none"
# ------------------------------------------------------------------------------------------------ v2 stores
e("v2.bindings", "memory_bindings/{hmac(org,channel,identifier,assurance)}", "Firestore", "identity", "PERSON/ENDPOINT",
  "subject_id; identifier HMAC", "org (in HMAC + field)", "by identifier HMAC (get)", "tombstone: status=erased, epoch+1 "
  "(binding first, C-1a)", "h1", "life of subject + suppression", "suppression HMAC [BLOCKED:Legal]", "identity_events",
  NONE, NONE, False, False, "FS restore → WORM replay raises epochs", False, "Identity authority", "target_v2")
e("v2.identity_events", "identity_events/{event_id}", "Firestore + WORM mirror", "identity", "PERSON",
  "subject ids (opaque)", "org", "by subject / time", "rekey to erasure request id", "h1", "permanent (PII-free)",
  "proof of erasure [BLOCKED:Legal]", "itself (authoritative)", "subject, seq", NONE, False, False,
  "never restored (WORM authoritative; LA-5 sync append)", False, "Identity authority", "target_v2")
e("v2.inbound_dedup", "inbound_dedup/{hmac(org,channel,provider_msg_id)}", "Firestore", "coordination", "MESSAGE",
  "evidence_id", "org (HMAC)", "get", "delete with evidence", "h1", "TTL [UNMEASURED]", "n/a", NONE, NONE, NONE, False,
  False, "loss = possible duplicate (tolerated)", False, "Runtime", "target_v2")
e("v2.evidence_seal", "agent_messages.{sealed_hash, seal_state, stamps, commit_records}", "Firestore", "evidence",
  "MESSAGE", "subject_id stamp", "org stamp", "with message", "deleted with the message", "h1", "= evidence",
  "= evidence (R-M3)", NONE, NONE, NONE, True, False, "FS restore → re-seal/verify (LA-7)", False, "Runtime",
  "target_v2")
e("v2.evidence_meta", "evidence_meta", "PostgreSQL", "evidence index", "MESSAGE", "subject_id, source_member_id",
  "org_id (RLS)", "subject_id, extraction_state index", "delete row", "h1", "= evidence", "= evidence",
  "Firestore messages", "(subject_id, extraction_state, observed_at), (evidence_id) PK", NONE, False, False,
  "PG restore → re-register gap", False, "Memory Gateway", "target_v2")
for t, d in [("claims", "claims (content-immutable, per-evidence: LA-11)"), ("claim_support", "claim_support (quotes)"),
             ("claim_transitions", "claim_transitions"), ("retraction_records", "retraction_records (LA-9)"),
             ("suppressions", "suppressions (keyed fingerprints)"), ("slots", "slots (head projection)")]:
    e("v2." + t, d, "PostgreSQL", "claims" if t != "slots" else "projection", "PERSON/ACCOUNT/RELATIONSHIP",
      "subject_id, source_member_id", "org_id (RLS)", "subject_id index; evidence_id index (support)",
      "archive (pending_erasure) then physical delete" if t != "slots" else "recompute", "h1",
      "life of subject", "R-M3 window [BLOCKED:Legal]", "commit records + evidence (LA-1)" if t != "slots"
      else "claims + policy + identity", "GIN(merge_ids), (subject_id,key,status), claim_support(evidence_id)",
      NONE, t == "claim_support", False, "PG restore → recorded replay (LA-1) + watermark (LA-10)",
      t == "slots", "Memory Gateway", "target_v2")
e("v2.commitment_events", "commitment_events (+ projection)", "PostgreSQL", "commitments", "RELATIONSHIP",
  "subject_id via evidence", "org_id", "relationship ref", "drop events of erased evidence/subject", "h1",
  "life of relationship", "[BLOCKED:Legal] for financial obligations", "events (projection rebuild)",
  "(relationship_ref, at)", "external booking systems (mirror)", False, False, "PG restore → event replay", False,
  "Memory Gateway", "target_v2")
e("v2.episodes", "episodes", "PostgreSQL", "evidence grouping", "SESSION", "subject_id", "org_id", "subject_id",
  "delete", "h1", "= evidence", "= evidence", "evidence", "subject_id", NONE, False, False, "rebuild", True,
  "Memory Gateway", "target_v2")
e("v2.narratives", "narratives", "PostgreSQL", "narrative", "SESSION", "subject_id via episode", "org_id", "episode",
  "delete; regenerate from evidence", "h1", "= evidence", "= evidence", "evidence (regenerate)", "episode_id", NONE,
  True, True, "rebuild", True, "Memory Gateway", "target_v2")
e("v2.accounts", "accounts + account_links", "PostgreSQL", "entity", "ACCOUNT", "linked person subject ids",
  "org_id", "account_id; person→account", "drop links of erased persons; erase-org", "h1", "life of account",
  "contract records [BLOCKED:Legal]", "authoritative imports", "(person_root)", "CRM", False, False, "PG restore",
  False, "Memory Gateway", "target_v2")
e("v2.agent_knowledge", "agent_knowledge + contributions", "PostgreSQL", "agent knowledge", "AGENT",
  "contributor subject ids (lineage)", "org_id", "contributor index", "remove contribution; retire below k", "h1",
  "life of item", "n/a", "learner re-derivation", "contributions(subject_id)", NONE, False, True, "PG restore",
  True, "Memory Gateway", "target_v2")
e("v2.extraction_proposals", "commit records / proposals (LA-1: kept with evidence in FS)", "Firestore (on message)",
  "audit", "MESSAGE", "subject via message", "org", "with message", "deleted with the message", "h1",
  "R-M3 proposals [BLOCKED:Jay] (default 90 d [UNMEASURED])", "n/a", NONE, NONE, "model provider (input)", True, False,
  "FS restore loses post-snapshot records (claims re-extracted)", False, "Memory Gateway", "target_v2")
e("v2.manifests", "prompt_manifests", "PostgreSQL", "audit", "MESSAGE", "subject_id", "org_id", "message_id",
  "rekey subject → erasure request id", "h1", "audit window [UNMEASURED]", "n/a", NONE, "message_id PK", NONE, False,
  False, "PG restore", False, "Memory Gateway", "target_v2")
e("v2.memory_events", "memory_events (ids only)", "PostgreSQL → BigQuery aggregates", "telemetry", "ORG",
  "subject ids (opaque)", "org_id", "time partition", "rekey; BQ export aggregates only (M-16)", "h1",
  "90 d then aggregate [UNMEASURED]", "n/a", NONE, "monthly partitions", "BigQuery", False, False, "loss tolerated",
  False, "Memory Gateway", "target_v2")
e("v2.outbox", "outbox (PII-free payloads)", "PostgreSQL", "coordination", "ORG", "ids only", "org_id",
  "dispatch state", "payloads carry no content; drop with partition", "h1", "days (partition drop)", "n/a", NONE,
  "daily partitions, dedup_key unique", "Cloud Tasks", False, False, "replay idempotent", False, "Memory Gateway",
  "target_v2")
e("v2.erasure_ledger", "erasure_requests + erasure_steps + WORM mirror", "PostgreSQL + GCS (retention-locked)",
  "control", "ORG", "subject HMAC (worm_ref)", "org", "request id", "never deleted (PII-free proof)", "h1",
  "permanent", "[BLOCKED:Legal] basis", "itself", "request_id", NONE, False, False,
  "WORM never restored; PG copy replayed from WORM", False, "Memory Gateway", "target_v2")
e("v2.replay_watermark", "recovery watermark (LA-10)", "PostgreSQL", "control", "ORG", NONE, "per instance", "single row",
  "n/a", "h1", "permanent", "n/a", NONE, NONE, NONE, False, False, "restored with PG (that is the point)", False,
  "Memory Gateway", "not_person_data")
e("v2.search_projection", "claims_fts (normaliser tokens, M-11)", "PostgreSQL", "index", "PERSON", "subject_id",
  "org_id", "subject_id + tsvector/trigram", "drop rows; every hit re-validated (M-9)", "h1", "= claims", "= claims",
  "claims", "GIN(tsv), trigram", NONE, True, False, "rebuild", True, "Memory Gateway", "target_v2")
e("v2.vector_projection", "pgvector projection (only on measured trigger)", "PostgreSQL", "index", "PERSON",
  "subject_id", "org_id", "ANN", "drop rows; re-validated hits", "h1", "= source", "= source", "claims/narratives",
  "ivfflat/hnsw", "embedding provider", True, True, "rebuild", True, "Memory Gateway", "target_v2 (deferred)")
e("v2.derived_artifacts", "analytics judgements (sentiment, disposition, outcome)", "Firestore/PG (analytics)",
  "analytics", "SESSION", "pseudonymous session ref", "org", "session ref", "fence library + handler (C-6)", "h1",
  "analytics window [UNMEASURED]", "n/a", "evidence (re-judge)", "session ref", NONE, False, True, "rebuild optional",
  True, "Analytics owner", "target_v2")
e("v2.consent_ledger", "consent + suppression HMAC list", "Firestore (server-only)", "consent", "PERSON",
  "identifier HMAC", "org", "HMAC get", "keep suppression entry; delete the rest [BLOCKED:Legal]", "h1",
  "permanent for suppression", "[BLOCKED:Legal]", "itself", NONE, "directives (enforcement)", False, False,
  "FS restore → WORM replay", False, "Consent owner", "target_v2")
e("v2.subject_keys", "subject keys (HMAC id keys, identifier ciphertext)", "Firestore (identity) / KMS", "keys",
  "PERSON", "subject_id", "org", "subject_id", "destroy key (crypto-shred of ids only, not content: C-8)", "h1",
  "life of subject", "n/a", NONE, NONE, "KMS", False, False, "restore resurrects keys → WORM replay", False,
  "Identity authority", "target_v2")
e("v2.policy_registry", "predicate policy registry (versioned)", "config", "policy", "ORG", NONE, "org", "version",
  "n/a", "h1", "permanent", "n/a", "config repo", NONE, NONE, False, False, "config", False, "Memory team",
  "not_person_data")

# -------------------------------------------------------------------------------------- legacy (census A5)
L = [
    ("agent_messages", "agent_messages", "Firestore", "evidence", "MESSAGE", "session_id (spine); no person key",
     "organization_id (missing/'default' on legacy rows)", "session_id in spine", True, "messages", "agent-runtime",
     "PII token vault", "legacy_handler_needed"),
    ("agent_sessions", "agent_sessions (+summary, identity, judge fields)", "Firestore", "evidence+derived", "SESSION",
     "doc id embeds raw phone; phone_number, user_id, identity_migrated_from, from_email", "organization_id",
     "spine (prefix + equality)", True, "messages", "agent-runtime", "Noesis (title), analytics-service",
     "legacy_handler_needed"),
    ("agent_user_memory", "agent_user_memory", "Firestore", "memory (M1)", "AGENT×KEY", "channel_user_id (raw)",
     "organization_id", "hash(user_key) per agent", True, "messages (incl. assistant text)", "agent-runtime", NONE,
     "legacy_quarantine"),
    ("agent_datastores", "agent_datastores/{agent}/tables/*/entries", "Firestore", "memory (M1)", "PERSON/SESSION",
     "unsalted person_hash; session_id", "none on entries", "hash or session_id; CG index missing", True, "extractor",
     "agent-runtime + agent-design", NONE, "legacy_handler_needed"),
    ("agent_learned_patterns", "agent_learned_patterns/{agent}/patterns", "Firestore", "agent knowledge (M4)",
     "AGENT", "source_session_id only; verbatim other-user text", "none", "content scan", True, "messages, tools",
     "agent-runtime", NONE, "legacy_quarantine"),
    ("agent_disposition_taxonomy", "agent_disposition_taxonomy", "Firestore", "agent knowledge", "AGENT", NONE,
     "via agent", "content scan", True, "conversations", "agent-runtime", "Noesis", "legacy_retire"),
    ("agent_users", "agent_users", "Firestore", "identity/consent", "AGENT×CHANNEL", "channel_user_id, phone, email",
     "organization_id (sometimes '')", "equality", False, "inbound", "agent-runtime", "agent-directives (opt-out)",
     "legacy_handler_needed"),
    ("lead_profiles", "lead_profiles", "Firestore", "lead (operational)", "SESSION", "contact fields", "organization_id",
     "erase_by_contact", True, "conversation/tools", "agent-runtime", NONE, "legacy_handler_needed"),
    ("lead_contacts", "lead_contacts", "Firestore", "lead (operational)", "ORG", "hashed contact", "organization_id",
     "erase_by_contact", False, "lead_profiles", "agent-runtime", NONE, "legacy_handler_needed"),
    ("lead_activity", "lead_activity", "Firestore", "lead (operational)", "PERSON_KEY", "person_key",
     "organization_id", "erase_by_contact", True, "operators", "agent-runtime", NONE, "legacy_handler_needed"),
    ("agent_documents_shared_with", "agents/{id}/documents.shared_with[]", "Firestore", "access list", "AGENT",
     "user_id, session_id in array", "via agent", "per-agent scan", False, "shares", "agent-runtime", NONE,
     "legacy_handler_needed"),
    ("agent_traces", "agent_traces/{message_id} (counters)", "Firestore", "telemetry", "MESSAGE",
     "session_id (embeds phone)", "organization_id", "session_id", False, "turns", "olbrain-shared", NONE,
     "legacy_handler_needed"),
    ("research_learned", "research_templates/{t}/learned/*", "Firestore", "agent knowledge (M5)", "TEMPLATE",
     "contributors (uids), session_ids; substance none", "parent org_id", "scan templates", True, "transcripts",
     "research-runtime/shared", NONE, "legacy_quarantine"),
    ("research_learning_ledger", "research_templates/{t}/learning_ledger", "Firestore", "agent knowledge", "TEMPLATE",
     "captured_by, evidence.session_id", "parent", "captured_by (CG index missing)", True, "transcripts",
     "olbrain-shared", NONE, "legacy_handler_needed"),
    ("research_chat_sessions", "research_chat_sessions (+messages)", "Firestore (olbrain_shared)", "evidence (MEMBER)",
     "SESSION", "started_by (+name, email)", "org_id", "started_by", True, "—", "olbrain-shared/research-design",
     NONE, "legacy_handler_needed"),
    ("research_trajectories", "GCS research/runs/{run}/trajectory/", "GCS", "telemetry", "RUN", "run_id",
     "RunMeta.org_id", "runs by uid/org → prefix", True, "full prompts", "research-runtime", NONE,
     "legacy_handler_needed"),
    ("research_runs_reports", "research_runs + reports (+ public share tokens)", "Firestore + GCS", "output", "RUN",
     "started_by; third parties unkeyed", "org_id", "runs by uid", True, "web + transcripts", "research-runtime",
     NONE, "external_gap"),
    ("workflow_agent_memory", "workflow_agent_memory (+_archive)", "Firestore", "agent knowledge (M6)", "AGENT",
     "run ids; raw original_data", "none", "content scan", True, "items", "workflow-runtime", NONE,
     "legacy_quarantine"),
    ("workflow_trigger_payload", "workflow_runs.trigger_payload", "Firestore", "evidence (operational)", "RUN",
     "undeclared payload fields", "organization_id", "content scan", True, "webhook caller", "workflow-runtime/shared",
     "webhook service", "legacy_handler_needed"),
    ("workflow_items", "workflow_items", "Firestore", "operational", "ITEM", "data fields", "organization_id",
     "run_id/record_id; content scan", True, "payload, steps", "workflow-runtime", NONE, "legacy_handler_needed"),
    ("workflow_run_traces", "workflow_run_traces (counters)", "Firestore", "telemetry", "RUN", "run_id",
     "via run", "run_id", False, "—", "workflow-runtime", NONE, "legacy_handler_needed"),
    ("workflow_agent_decisions", "workflow_agent_decisions", "Firestore", "audit", "RUN", "run_id, item_id",
     "none", "run_id/item_id", False, "override applies", "workflow-runtime", NONE, "legacy_handler_needed"),
    ("context_facts", "context_facts / context_consolidation", "Firestore", "agent knowledge (M8, MEMBER)",
     "SCOPE cascade", "free-text subject/object", "scope_key", "content scan", True, "builder chats", "agent-engine",
     NONE, "legacy_retire"),
    ("owner_lessons", "agents/{id}/owner_lessons", "Firestore", "config (M7)", "AGENT", "created_by, owner session",
     "via agent", "content scan", True, "owner", "agent-engine", NONE, "legacy_handler_needed"),
    ("agent_versions", "agents/{id}/versions (snapshots)", "Firestore", "config", "AGENT",
     "content (lessons/examples)", "via agent", "content scan", True, "owner_lessons", "agent-design/engine", NONE,
     "legacy_handler_needed"),
    ("published_config", "GCS configs/{agent}/active_config.json", "GCS", "config", "AGENT",
     "content (approved knowledge inlined today)", "via agent", "content scan", True, "versions", "agent-design",
     NONE, "legacy_handler_needed"),
    ("builder_sessions", "alchemist_* / agentify_sessions/*/messages / dendrite_sessions", "Firestore",
     "evidence (MEMBER)", "SESSION", "member uid", "org", "uid", True, "—", "agent-engine", NONE,
     "legacy_handler_needed"),
    ("brds", "BRDs", "Firestore/GCS", "config (MEMBER)", "AGENT", "member uid; may contain customer data", "org",
     "content scan", True, "builder", "agent-engine", NONE, "legacy_handler_needed"),
    ("agent_qa_runs", "agent_qa_runs", "Firestore", "eval", "RUN", "correlation.session_ids", "org_id",
     "array-contains", True, "eval sessions", "agent-eval", NONE, "retention_only"),
    ("mcp_tool_executions", "mcp_tool_executions", "Firestore", "telemetry", "CALL", "none (args/results content)",
     "none", "agent + time + content scan", True, "tool I/O", "mcp-deployer", "deployer project config",
     "legacy_handler_needed"),
    ("privacy_compliance_log", "privacy_compliance_log", "Firestore", "audit", "ORG", "shop/customer refs",
     "org", "[UNVERIFIED]", False, "Shopify webhooks", "mcp-deployer", NONE, "legacy_handler_needed"),
    ("usage_events", "usage_events", "Firestore", "billing", "EVENT", "session_id (phone-bearing)",
     "organization_id", "session_id", False, "—", "olbrain-shared/agent-runtime", "billing/metering service",
     "pseudonymise"),
    ("message_billing_records", "message_billing_records", "Firestore", "billing", "AGENT", "[UNRESOLVED]",
     "organization_id", "[UNRESOLVED]", False, "—", "olbrain-cloud-functions", "olbrain-cloud-functions",
     "blocked_missing_repo"),
    ("payments", "payments", "Firestore", "billing", "AGENT", NONE, "organization_id", "—", False, "—",
     "studio-backend", NONE, "not_person_data"),
    ("agent_analytics", "agent_analytics/{agent}/days|months", "Firestore", "analytics", "AGENT", "[UNRESOLVED]",
     "via agent", "[UNRESOLVED]", False, "—", "olbrain-analytics-service", "olbrain-analytics-service",
     "blocked_missing_repo"),
    ("agent_standups", "agent_standups", "Firestore", "analytics", "AGENT", "[UNVERIFIED]", "via agent",
     "[UNVERIFIED]", True, "conversations", "agent-runtime", NONE, "legacy_handler_needed"),
    ("tickets", "tickets", "Firestore", "support", "TICKET", "customer.{name,email,phone}, session_id",
     "organization_id", "email/session_id", True, "conversation copy", "agent-engine (nexus)", NONE,
     "legacy_handler_needed"),
    ("gcs_attachments", "GCS agent_sessions/{session}/attachments, webhook-uploads, whatsapp_compressed",
     "GCS", "evidence", "SESSION", "session in path (not for whatsapp_compressed)", "org prefix (webhook only)",
     "storage_path from messages", True, "uploads", "agent-runtime", NONE, "legacy_handler_needed"),
    ("gcs_generated_exports", "GCS generated_pdfs/charts, exports/{org}, audit-exports", "GCS", "outputs", "AGENT/ORG",
     "content only", "prefix", "none", True, "tools", "agent-runtime/studio-backend", NONE, "retention_only"),
    ("kv_gcs", "KV {prefix}/text|raw|cards", "GCS", "org knowledge", "AGENT/ORG/CLIENT", "none (content)",
     "prefix", "content scan", True, "uploads, conversations", "knowledge-vault", NONE, "legacy_handler_needed"),
    ("kv_fts", "KV fts.sqlite", "GCS", "index", "PREFIX", "none", "prefix", "rebuild", True, "kv_gcs",
     "knowledge-vault", NONE, "legacy_handler_needed"),
    ("kv_blobcache", "KV BlobCache (process, 1 h)", "memory", "cache", "PROCESS", NONE, NONE, "invalidate", True,
     "kv_gcs", "knowledge-vault", NONE, "legacy_handler_needed"),
    ("knowledge_library", "knowledge_library", "Firestore", "org knowledge", "ORG", "[UNVERIFIED]", "org",
     "[UNVERIFIED]", True, "uploads", "agent-design/kv", NONE, "legacy_handler_needed"),
    ("research_clients", "research_clients", "Firestore", "entity (ACCOUNT precedent)", "ORG",
     "company names/aliases (may name persons)", "org", "slug", False, "operators", "research", NONE,
     "legacy_handler_needed"),
    ("cloud_logging", "Cloud Logging", "GCP", "telemetry", "LOG", "raw phone, session ids, DM text, step outputs",
     "labels", "text search", True, "everything", "all services", "GCP config (no IaC india-prod)", "retention_only"),
    ("bigquery_logs", "BigQuery service_logs / audit dataset", "GCP", "telemetry", "LOG", "as Cloud Logging",
     "agent_id field", "SQL", True, "log sink", "agent-engine (Lumen)", "sink config [UNRESOLVED]", "retention_only"),
    ("slack_sendgrid_excerpts", "Slack / SendGrid escalation excerpts", "external", "external copy", "SESSION",
     "content", "—", "none (sent)", True, "messages", "agent-runtime", "Slack, SendGrid", "external_gap"),
    ("report_emails", "report emails (7-day signed URLs)", "external", "external copy", "RUN", "content link",
     "—", "none", True, "reports", "research-runtime", "SendGrid", "external_gap"),
    ("subprocessor_anthropic", "Anthropic (prompts)", "external", "subprocessor", "CALL", "content", "—", "n/a",
     True, "prompts", "olbrain-llm", "olbrain-llm, DPA", "external_gap"),
    ("subprocessor_groq", "Groq (KV tables lane)", "external", "subprocessor", "CALL", "content", "—", "n/a", True,
     "queries", "knowledge-vault", "DPA", "external_gap"),
    ("subprocessor_gemini", "Gemini (identity capture + MCP captcha)", "external", "subprocessor", "CALL",
     "end-user text", "—", "n/a", True, "messages", "agent-runtime, mcp-deployer", "DPA", "external_gap"),
    ("provider_prompt_cache", "provider prompt caches (5 min–1 h)", "external", "cache", "CALL", "content", "—",
     "TTL", True, "prompts", "agent-runtime", "provider", "retention_only"),
    ("inprocess_caches", "~20 in-process TTL caches", "memory", "cache", "PROCESS", "varies", "—", "TTL", True,
     "stores", "all services", NONE, "retention_only"),
    ("backups", "Firestore/Cloud SQL backups + PITR", "GCP", "backup", "PROJECT", "all", "project", "restore only",
     True, "stores", "ops", "GCP config", "retention_only"),
    ("pii_token_vault", "PII token vault", "external", "tokenisation", "ORG", "tokens ↔ values", "[UNRESOLVED]",
     "[UNRESOLVED]", True, "messages", "[UNRESOLVED]", "pii_client (missing)", "blocked_missing_repo"),
    ("coordination", "engine_jobs, agent_wakes, leases, driver claims, FE dispatched/*", "Firestore", "coordination",
     "JOB", "ids (session/run)", "org/agent", "ids", False, "—", "various", NONE, "retention_only"),
    ("finance_uploads", "finance-engine workbooks + deck templates", "GCS/Firestore", "org data", "ORG",
     "content (may contain customer financials)", "org", "content scan", True, "uploads", "finance-engine", NONE,
     "legacy_handler_needed"),
    ("iam_members", "organizations/{org}/members, memberships(_index), user_profiles", "Firestore", "IAM (MEMBER)",
     "ORG", "uid, name, email", "org", "uid", False, "signup", "studio/studio-backend", NONE, "legacy_handler_needed"),
    ("api_keys_share_tokens", "api_keys, organization_api_keys, share tokens", "Firestore", "auth", "ORG",
     "creator uid", "org", "uid", False, "—", "studio-backend", NONE, "not_person_data"),
    ("noesis_stores", "olbrain-noesis-os stores", "[UNRESOLVED]", "[UNRESOLVED]", "[UNRESOLVED]", "[UNRESOLVED]",
     "[UNRESOLVED]", "[UNRESOLVED]", True, "[UNRESOLVED]", "olbrain-noesis-os", "olbrain-noesis-os",
     "blocked_missing_repo"),
    ("voice_gateway_stores", "voice gateway (recordings/transcripts?)", "[UNRESOLVED]", "[UNRESOLVED]",
     "[UNRESOLVED]", "[UNRESOLVED]", "[UNRESOLVED]", "[UNRESOLVED]", True, "[UNRESOLVED]", "olbrain-voice-gateway",
     "olbrain-voice-gateway", "blocked_missing_repo"),
    ("billing_service_db", "billing/metering service store", "[UNRESOLVED]", "billing", "[UNRESOLVED]",
     "[UNRESOLVED]", "[UNRESOLVED]", "[UNRESOLVED]", False, "usage", "billing service", "billing service",
     "blocked_missing_repo"),
    ("directives_store", "agent-directives (campaigns, opt-out enforcement)", "[UNRESOLVED]", "outreach",
     "[UNRESOLVED]", "[UNRESOLVED]", "[UNRESOLVED]", "[UNRESOLVED]", True, "[UNRESOLVED]", "olbrain-agent-directives",
     "olbrain-agent-directives", "blocked_missing_repo"),
    ("dedicated_tenant_copies", "dedicated physical tenants (e.g. clix-capital-prod): every store above",
     "per project", "physical tenant", "TENANT", "as above", "project", "as above", True, "—", "ops", "tenant IaC",
     "legacy_handler_needed"),
]
for (i, store, sysm, cls, scope, subj, tenant, lookup, raw, derived_from, owner, ext, status) in L:
    handler = {"legacy_handler_needed": "B3 handler (census row)", "legacy_quarantine": "quarantine, erase at cutover",
               "legacy_retire": "retire writer, delete", "retention_only": "retention bound (TTL/lifecycle)",
               "pseudonymise": "rekey to pseudonymous refs", "external_gap": "minimise at source; record in ledger",
               "blocked_missing_repo": "[UNRESOLVED: missing repository]", "not_person_data": "n/a"}[status]
    e("legacy." + i, store, sysm, cls, scope, subj, tenant, lookup, handler, "l1",
      "[BLOCKED:Legal/R-M3]" if status != "not_person_data" else "n/a",
      "billing basis [BLOCKED:Legal]" if status == "pseudonymise" else "[BLOCKED:Legal]",
      derived_from if status not in ("external_gap",) else NONE,
      "see census" if status == "legacy_handler_needed" else NONE, ext, raw,
      cls.startswith(("memory", "agent knowledge", "analytics")), "restore protocol §L (WORM replay)",
      status in ("legacy_handler_needed", "legacy_quarantine") and "agent knowledge" in cls or i in (
          "agent_sessions", "agent_user_memory", "agent_datastores", "agent_users", "workflow_agent_memory",
          "kv_fts", "published_config"), owner, status)

# The completeness reference: every store named by the ecosystem map (§3/§4) and the census must appear.
EXPECTED = [
    "agent_messages", "agent_sessions", "agent_user_memory", "agent_datastores", "agent_learned_patterns",
    "agent_disposition_taxonomy", "agent_users", "lead_profiles", "lead_contacts", "lead_activity", "agent_traces",
    "research_learned", "research_learning_ledger", "research_chat_sessions", "research_trajectories",
    "workflow_agent_memory", "workflow_trigger_payload", "workflow_items", "workflow_run_traces",
    "workflow_agent_decisions", "context_facts", "owner_lessons", "agent_versions", "published_config",
    "agent_qa_runs", "mcp_tool_executions", "usage_events", "message_billing_records", "payments", "agent_analytics",
    "tickets", "gcs_attachments", "gcs_generated_exports", "kv_gcs", "kv_fts", "kv_blobcache", "cloud_logging",
    "bigquery_logs", "slack_sendgrid_excerpts", "subprocessor_anthropic", "subprocessor_groq", "subprocessor_gemini",
    "provider_prompt_cache", "inprocess_caches", "backups", "privacy_compliance_log", "agent_standups",
    "builder_sessions", "brds", "iam_members", "research_clients", "knowledge_library", "coordination",
    "finance_uploads", "report_emails", "pii_token_vault", "dedicated_tenant_copies", "research_runs_reports",
    "agent_documents_shared_with", "api_keys_share_tokens",
    # missing repositories, explicitly
    "noesis_stores", "voice_gateway_stores", "billing_service_db", "directives_store",
    # v2 (red-team + Lane A)
    "bindings", "identity_events", "inbound_dedup", "evidence_seal", "evidence_meta", "claims", "claim_support",
    "claim_transitions", "retraction_records", "suppressions", "slots", "commitment_events", "episodes", "narratives",
    "accounts", "agent_knowledge", "extraction_proposals", "manifests", "memory_events", "outbox", "erasure_ledger",
    "replay_watermark", "search_projection", "vector_projection", "derived_artifacts", "consent_ledger",
    "subject_keys", "policy_registry",
]


def check():
    ids = {r["id"].split(".", 1)[1] for r in R}
    problems = ["missing entry: " + x for x in EXPECTED if x not in ids]
    for r in R:
        for f in FIELDS:
            if r.get(f) in (None, ""):
                problems.append("%s: empty field %s" % (r["id"], f))
        person = r["status"] not in ("not_person_data",)
        if person and r["erasure_handler"] in (NONE, "n/a") and r["status"] != "target_v2":
            problems.append("%s: person data without erasure handler" % r["id"])
        if r["status"] == "blocked_missing_repo" and "UNRESOLVED" not in r["erasure_handler"]:
            problems.append("%s: missing repo not marked unresolved" % r["id"])
    return problems


if __name__ == "__main__":
    if "--check" in sys.argv:
        p = check()
        print("\n".join(p) or "registry complete: %d entries, %d expected stores covered" % (len(R), len(EXPECTED)))
        sys.exit(1 if p else 0)
    json.dump({"version": "lifecycle-registry-v1", "fields": FIELDS, "entries": R}, open(OUT, "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    print("| id | store | system | scope | subject cols | tenant cols | handler | raw text | derived | regen | status |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in R:
        print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["store"], r["system"], r["scope_type"], r["subject_columns"], r["tenant_columns"],
            r["erasure_handler"], "yes" if r["raw_customer_text"] else "no", "yes" if r["derived_knowledge"] else "no",
            "yes" if r["can_regenerate_deleted"] else "no", r["status"]))
