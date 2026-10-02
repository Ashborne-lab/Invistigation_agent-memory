# Firestore Inventory Closure Pass

**Date:** 2026-09-22
**Type:** read-only. No schema, no RLS, no migration design, no architecture decision.

Labels as in the prior audits: `CURRENT FACT`, `UNKNOWN`, `DECISION REQUIRED`,
`SECURITY FINDING`, plus `BLOCKED BY ABSENT REPOSITORY`, `NOT A COLLECTION` and
`CONTRADICTION`.

---

## 1. Purpose

Exhaust everything establishable from the **ten repositories already in this workspace** — no
cloning, no guessing — and state precisely what remains, and why.

The target is **maximum verified completeness with the current workspace**, not a complete
platform inventory. Those are different claims and this document makes only the first.

## 2. Scope and Safety

Ten repositories inspected: agent-runtime, agent-engine, research-design, research-runtime,
workflow-runtime, knowledge-vault, shared, studio, studio-backend, agent-design.

**Not inspected and not cloned**, per instruction: `olbrain-mcp-deployer`,
`olbrain-agent-eval`, `olbrain-finance-engine`, `olbrain-agent-cloud`. Their absence remains a
known scope blocker and is marked as such throughout.

Redis was not re-investigated — already confirmed dormant, and nothing found this pass
contradicts that.

## 3. Results Summary

| Outcome | Count |
|---|---|
| Previously unknown items carried in (U-1 … U-9, plus 12 low-reference registry names) | **~35 named collections** |
| **Resolved LIVE** (reader and/or writer opened in source) | **21** |
| **Resolved NOT A COLLECTION** (field or dict key, not a Firestore collection) | **3** |
| **Resolved DECLARED-ONLY** (new this pass) | **2** |
| **Resolved RULES-ONLY** (named in `firestore.rules`, zero readers/writers in the workspace) | **5** |
| **Resolved READER-ONLY here** (consumer present, writer outside the workspace) | **4** |
| **BLOCKED BY ABSENT REPOSITORY** | **3 collection families** |
| **Still UNKNOWN after this pass** | **1** |
| **New collections discovered** (in none of the three registries) | **9** |
| **New CONTRADICTIONS recorded** | **2** |

**The headline:** every unknown that the ten repositories could answer has been answered. What
remains is bounded and categorised — absent repositories, one genuinely unresolvable schema
question, and decisions that are not code questions.

## 4. Registry Resolution

### 4.1 NOT A COLLECTION — resolved by opening the reference site

| Name | Previous status | Final status | Evidence |
|---|---|---|---|
| `knowledge_repositories` | UNKNOWN (1 ref) | **`NOT A COLLECTION`** — a dict key in an agent schema default | `olbrain-agent-engine/alchemist/schemas/agent.py` — `'knowledge_repositories': []` |
| `test_cases` | UNKNOWN (1 ref) | **`NOT A COLLECTION`** — same schema default | `olbrain-agent-engine/alchemist/schemas/agent.py` — `'test_cases': []` |
| `agent_performance` | UNKNOWN (1 ref) | **`NOT A COLLECTION`** — a field in sentiment-analysis output | `olbrain-agent-runtime/buildin_tools/sentiment_analysis/executor.py` |

This joins `permissions` (resolved last pass) as the fourth registry entry that names something
that is not a collection at all.

### 4.2 DECLARED-ONLY — confirmed zero references

| Name | Final status | Evidence |
|---|---|---|
| `agent_configurations` | **CONFIRMED DECLARED-ONLY** | Zero references anywhere outside the registry |
| `credit_transactions` | **CONFIRMED DECLARED-ONLY** | Appears only in the Python registry and `olbrain-studio/src/constants/collections.js` — two declarations, no reader, no writer |

Added to last pass's ten, this makes **12 confirmed declared-only** registry entries.

### 4.3 LIVE — newly confirmed by opening the reference site

| Collection | Purpose | Reader | Writer | Org field | Evidence |
|---|---|---|---|---|---|
| `user_analytics` | Per-user analytics doc, id = `userId` | studio browser | **studio browser (client SDK)** | keyed by user, not org | `olbrain-studio/src/services/analytics/analyticsService.js` |
| `alchemist_actions` | Subcollection `agents/{agentId}/alchemist_actions` | studio browser | agent-design | via parent agent | `olbrain-agent-design/app/services/agent_service.py`; `olbrain-studio/.../alchemistService.js` |
| `agent_servers` | Agent service URL + server status, doc id = `agent_id` | **agent-runtime's legacy config service**, agent-design | agent-design (`agent_service`, `deployment_service`, `system_prompt_optimizer`) | none observed | `olbrain-agent-design/app/services/agent_service.py`; `olbrain-agent-runtime/config/firestore_config.py` |
| `audit_logs` | "Configuration mutations" | **agent-engine Lumen** (`evidence/firestore.py`) | **not found in workspace** | `UNKNOWN` | `olbrain-agent-engine/alchemist/agents/lumen/evidence/firestore.py` |
| `memberships` | Collaborator membership rows | agent-design | agent-design | per-membership | `olbrain-agent-design/app/routers/collaborators.py` |
| `conversations` | Conversation records | studio browser (`useLiveItems`) | agent-design | `user_id`, via `agent_id` | `olbrain-agent-design/app/services/conversation_service.py` |
| `messages` | **Subcollection** `alchemist_sessions/{id}/messages` — not top-level | agent-design | agent-design | via parent | `olbrain-agent-design/app/services/conversation_service.py` |
| `user_profiles` | User profile documents | agent-design, agent-engine admin tools | agent-design | n/a — user-keyed | `olbrain-agent-design/app/services/firestore_service.py`; `olbrain-agent-engine/.../admin_tools.py` |
| `users` | User records | agent-design, agent-engine | agent-design | n/a | `olbrain-agent-design/app/services/user_profile.py`; `olbrain-agent-engine/routes.py` |
| `recommendations` | **Subcollection** `agentify_sessions/{id}/recommendations` | agent-engine | agent-engine | via parent | `olbrain-agent-engine/alchemist/agents/brain_builder.py`; a migration tool `migrate_recommendations_to_subcollection.py` confirms it moved from top-level |
| `capability_types` | Capability catalogue | studio browser | agent-design sync | platform-wide | `olbrain-agent-design/app/services/capability_types_sync.py` |
| `step_types` | Workflow step catalogue | studio browser | agent-design (`routers/capability_types.py`) | platform-wide | `olbrain-studio/src/services/workflow/stepTypesFirestore.js` |
| `agentify_sessions` | Cortex/agentify design sessions | agent-engine | agent-engine | `UNKNOWN` | `olbrain-agent-engine/alchemist/agents/brain_builder.py`, `routes.py` |
| `synapse_sessions` | Synapse agent sessions | agent-engine | agent-engine | `UNKNOWN` | `olbrain-agent-engine/alchemist/agents/synapse_agent.py`, `scripts/backfill_dendrite_sessions.py` |
| `lumen_sessions` | Observability agent sessions | agent-engine | **agent-engine** (`lumen_agent.py`) | `UNKNOWN` | `olbrain-agent-engine/alchemist/agents/lumen_agent.py` |
| `alchemist_sessions` | Design chat sessions + `messages` subcollection | agent-design | agent-design | `UNKNOWN` | `olbrain-agent-design/app/services/conversation_service.py` |
| `alchemist_conversations` | User-scoped assistant conversations, doc id = `user_id`, with a `status` subcollection | agent-design, agent-engine | agent-design, agent-engine | user-keyed | `conversation_service.py`; `orchestrator_agent.py`; `standalone_ports.py` |
| `agent_traces` | **Per-turn counter index** — see §6 | agent-engine Lumen, `brain_lifecycle` | **`olbrain-shared` `TraceCollector.finalize_and_persist`** | **`organization_id` present** | `olbrain-shared/src/olbrain_shared/agent/trace_collector.py` |
| `workflow_items` | Per-row execution record — see §7 | workflow-runtime orchestrator, co-designer | `olbrain-shared` workflow service | **absent** | `olbrain-shared/src/olbrain_shared/workflow/firestore/service.py` |
| `integration_channels` | Channel integration records | — | — | `created_by`, via `agent_id` | Named in `olbrain-studio/scripts/backfill-clix-organization-id.js` |
| `conversation_feedback`, `business_intelligence` | Feedback; BI records | — | — | `user_id` / via `agent_id` | Same backfill script |

The last three are confirmed to **exist as collections** (a production backfill script
enumerates them with their ownership fields) but no live reader or writer was found in the ten
repositories. Recorded as existing-but-unattributed rather than live.

### 4.4 Nine collections discovered that appear in **no** registry

`CURRENT FACT` From `olbrain-studio/scripts/backfill-clix-organization-id.js` (a
`clix-capital-prod` org-stamping backfill) and from the legacy config service:

`agent_usage_summary` · `communication_logs` · `billing_records` · `billing_deployments` ·
`billing_tools` · `billing_kb_storage` · `training_jobs` · `activities` ·
`mcp_server_templates`

**Why this matters beyond the names.** The backfill script's entire purpose is to *stamp
`organization_id` onto documents that lack it*, resolving ownership through `owner_field` or
`viaAgentId`. It is direct, independent evidence that the missing-row-level-org problem
(Security Finding B) spans at least **20 collections**, and that the platform has already built
tooling to address it — for one dedicated tenant.

## 5. Firestore Rules Resolution

### 5.1 Named in `firestore.rules`, zero readers or writers in the workspace

| Collection | Client read | Client write | Classification | Evidence |
|---|---|---|---|---|
| `databases` | per its block | per its block | **RULES-ONLY** — zero references in any of the ten repos | exhaustive grep |
| `dev_conversations` | per its block | per its block | **RULES-ONLY** | exhaustive grep |
| `whatsapp_user_phones` | per its block | per its block | **RULES-ONLY** | exhaustive grep |
| `whatsapp_webhooks` | per its block | per its block | **RULES-ONLY** | exhaustive grep |
| `whatsapp_integrations` | per its block | per its block | **RULES-ONLY in code**; named in the clix backfill script with `user_id` / `viaAgentId` | backfill script |

A dedicated rule block exists for each, so each is presumed to exist in production. Their
readers and writers are outside this workspace — most plausibly `olbrain-studio-backend`'s
WhatsApp services for the `whatsapp_*` family, though no reference was found there this pass.
`UNKNOWN — writer not located.`

### 5.2 Reader present here, writer elsewhere

| Collection | Reader in workspace | Writer | Security classification |
|---|---|---|---|
| `agent_webhook_logs` | `olbrain-studio` browser component | **not found in the ten repos** | Webhook delivery logs; content `UNKNOWN` |
| `api_key_usage_events` | `olbrain-studio` AccessKeysCard (browser) | **not found** — presumably studio-backend's key service | API-key usage telemetry |
| `mcp_tool_executions` | agent-engine Lumen `evidence/firestore.py` | **`BLOCKED BY ABSENT REPOSITORY`** — `olbrain-mcp-deployer` per the registry comment | Tool execution records; payload `UNKNOWN` |
| `agent_qa_runs` | agent-engine Lumen `evidence/eval_runs.py` | **`BLOCKED BY ABSENT REPOSITORY`** — `olbrain-agent-eval` | Registry states a top-level `org_id` field — the one row-level org binding in this group |

Both browser-read collections are read **client-side**, so whatever their rule permits is what
a signed-in user gets. Neither has a dedicated match block found this pass, so both fall to
the two-segment catch-all → **open read and write to any authenticated user**.
`SECURITY FINDING`, consistent with SF-I.

### 5.3 What did not change

The effective-rule verdicts established last pass are unchanged and were not re-derived:
`secrets` and `memberships_index` server-only; `agents/{id}` world read/write via catch-all
supersession (SF-J); `agents/{id}/{sub}/**` authenticated read with no exclusions (SF-K); the
read/write asymmetry (SF-I); the finance family excluded from the org catch-all.

## 6. Trace / Execution Resolution

### `agent_traces` — FULLY RESOLVED, and materially less sensitive than feared

`CURRENT FACT` Writer located in the workspace after all:
`olbrain-shared/src/olbrain_shared/agent/trace_collector.py::TraceCollector.finalize_and_persist`
→ `db.collection("agent_traces").document(message_id).set(metadata, merge=True)`.

**Exact persisted payload** (read directly, not inferred):

```text
agent_id · session_id · organization_id · project_id · message_id · timestamp
total_duration_ms · llm_total_tokens · llm_prompt_tokens · llm_completion_tokens
llm_cost · llm_duration_ms · model_id · finish_reason
tool_call_count · tool_failure_count · kb_search_count
dci_call_count · dci_failure_count
cs_baseline_total_tokens · cs_used_total_tokens · cs_saved_tokens_total · cs_saved_pct
```

**Findings:**

- **Identifiers and counters only. No user content, no tool inputs or outputs, no reasoning
  text, no prompt text.** PII exposure in the Firestore document is limited to identifiers.
- **It carries `organization_id` as a row-level field** — one of the few stores in the whole
  investigation that does.
- The module docstring is explicit about where the content goes instead: *"the heavy body
  stays in Cloud Logging where logs belong."* Large fields — reasoning, tool outputs — are
  truncated to 240 KB **at the Cloud Logging event boundary**, not in Firestore.
- Writes are best-effort: *"a Firestore write failure never breaks the reply to the user."*

**The consequence worth flagging:** the PII question for turn traces does not disappear, it
**relocates to Cloud Logging**, which is outside Firestore, outside this audit's scope, and
governed by IAM rather than Firestore rules. That is a genuinely different control surface and
no prior document has examined it. `UNKNOWN — out of scope for a Firestore audit.`

Supporting evidence of a deliberate no-content-in-telemetry posture: agent-runtime's
`core/trace_collector.py` shim states *"Both emit COUNTS ONLY. A struck figure is the
organisation's own data; the whole point of the guard is to keep a figure out of places nobody
computed it for, and a log line is one of those places."*

### `mcp_tool_executions` — `BLOCKED BY ABSENT REPOSITORY`

Readers only in this workspace (Lumen, via `Collections.MCP_TOOL_EXECUTIONS`). No writer. The
registry attributes it to `olbrain-mcp-deployer`. **Schema not inferred.**

### `agent_qa_runs` — `BLOCKED BY ABSENT REPOSITORY`

Readers only (Lumen `evidence/eval_runs.py`). Writer is `olbrain-agent-eval` per the registry
comment, which also states org scoping is via a **top-level `org_id` field**. Schema not
inferred beyond that.

### `lumen_sessions`, `alchemist_sessions`, `alchemist_conversations` — LIVE, writers present

All three have writers in the workspace (agent-engine `lumen_agent.py`; agent-design
`conversation_service.py`; agent-design + agent-engine respectively). `alchemist_sessions`
carries a `messages` subcollection and `alchemist_conversations` a `status` subcollection.
Payload shapes were **not** individually opened this pass — design-conversation content is
plausible but unverified. `UNKNOWN — content not established.`

### `audit_logs` — LIVE as a read target, writer not in the workspace

Lumen reads it for *"Configuration mutations."* No writer found in the ten repositories.
`UNKNOWN — writer not located.`

### CONTRADICTION-1 · stale source citation

| | |
|---|---|
| **Source A** | `olbrain-agent-engine/alchemist/agents/lumen/evidence/firestore.py` docstring: *"Per-turn execution summary written by olbrain-agent-runtime (core/trace_collector.py:495)."* |
| **Source B** | `olbrain-agent-runtime/core/trace_collector.py` is **106 lines**, and is a re-export shim: *"Moved to olbrain_shared.agent.trace_collector."* Line 495 does not exist. |
| **Why they conflict** | The citation points at a file and line that no longer hold the writer. The writer moved to `olbrain-shared`. |
| **Can code resolve it?** | **Yes — already resolved.** The real writer was located in `olbrain-shared`. This is a stale comment, not a factual dispute. No senior input needed. |

## 7. Workflow Resolution — `workflow_items`

`CURRENT FACT` The service layer is in `olbrain-shared`, not workflow-runtime:
`src/olbrain_shared/workflow/firestore/service.py`.

| Question | Finding |
|---|---|
| **Exact write code** | `db.collection(WORKFLOW_ITEMS).document(item_id).set(item_data)` — plain `set`, no merge, no transaction, no batch |
| **Exact read code** | `list_workflow_items_for_run(run_id)` → `db.collection(WORKFLOW_ITEMS).where("run_id", "==", run_id)`; plus per-item `.get()` / `.update()` |
| **Document id** | **Deterministic**: `sha256(f"{run_id}\|{record_id}\|{item_idx}")[:24]`, with the code's own rationale — *"Two concurrent orchestrator passes for the same (run_id, record_id, item_idx) produce the same document ID, so set() calls converge on a single doc rather than creating duplicates."* |
| **Does `organization_id` exist on the item?** | **No.** `organization_id` appears in this service file only for `WORKFLOW_DEFINITIONS` queries and one snapshot read — **never on a `workflow_items` write** |
| **Is the parent run's org copied down?** | **No.** The only link is `run_id` |
| **How does authorization work?** | It does not. No Firestore rule at all, and workflow-runtime's routers carry no app-layer auth (established previously) |
| **Effective Firestore rule** | Two-segment catch-all → **any authenticated user may read and write** `SECURITY FINDING` |
| **Step-output PII** | `orchestrator.py` states larger step outputs are written to the item document while smaller ones stay inline on the run. Whether those outputs carry customer PII depends on the workflow definition and is **not determinable from the runtime code**. `UNKNOWN` |

**New production precedent worth recording.** The deterministic document id is a genuine
**idempotency mechanism** — convergent writes under concurrent passes, achieved by key
derivation rather than by OCC. It is the third distinct concurrency device found in production
(alongside research-design's CAS and workflow's `orchestrator_generation` fencing), and the
only one that achieves idempotency without a version field.

## 8. `agents` Ownership Facts

Factual map only. Canonical ownership is **`DECISION REQUIRED`** and is not answered here.

### Write sites — ten, across three repositories

| Repository | Site | What it changes | Concurrency device |
|---|---|---|---|
| agent-design | `app/routers/agent.py` | `.update(update_payload)` — agent CRUD | none |
| agent-design | `app/services/agent_service.py` ×3 | `.update` ×2, `.set` ×1 — publish, version activation, creation | `@firestore.transactional` on some paths (agent create, versioned deployment, nested-dict overlays) |
| agent-design | `app/services/brain_service.py` ×4 | `.update` / `.set(merge=True)` — brain payloads | transactional on some paths |
| agent-engine | `alchemist/agents/brain_builder.py` | `.update` — brain build results | transactional **lease** on a *different* document |
| agent-engine | `alchemist/provision/store_build.py` | `.update` — store provisioning | lease |
| agent-engine | `alchemist/agents/agentify_agent.py` | `.set(agent_doc)` — provisional agent creation | none |
| studio-backend | `services/agent_transfer_service.py` ×2 | `.update` — **reassigns `organization_id`** | none |

### Optimistic concurrency

**None.** `CURRENT FACT` No version field, no CAS, no `expected_version` on `agents/{id}` in
any writer. The transactional blocks in agent-design provide atomicity within one service; they
do not serialise against agent-engine or studio-backend. A cross-org transfer re-stamping
`organization_id` and a concurrent design-side publish have nothing preventing interleaving.

### Read paths and authorization

Read by effectively everything: agent-runtime's legacy config service
(`config/firestore_config.py` reads `agents`, twice), agent-design's config generator and
skill-binding resolver, knowledge-vault's transitive org resolution, studio-backend's
`AgentService`, and the studio browser directly. Application-layer authorization is org/owner
scoped in studio-backend and agent-design; the **Firestore layer is not** (SF-J).

### Transfer dependence

The nine-step cross-org transfer cascade reassigns `organization_id`/`owner_id` here, and this
document is the anchor through which `knowledge_library`, agent-design's `_get_knowledge_base`
and `skill_binding_service` all resolve organization.

`DECISION REQUIRED` — canonical owner. Unchanged from QF-1.

## 9. Legacy Config Reachability Facts

Reachability only. Whether the legacy path should remain is **not** decided here.

### Caller map — exhaustive across all ten repositories

```text
core/agent.py::Agent.__init__(agent_id, settings=None, use_firestore_config=True)   ← default ON
    └─ if self._use_firestore_config:  self.config_service = FirestoreConfigService(agent_id)

core/agent_factory.py:57   create_agent(agent_id)
                           → Agent(agent_id)                    ← takes the default: LEGACY PATH
core/agent_factory.py:72   create_agent_with_settings(id, settings)
                           → Agent(..., use_firestore_config=False)   ← NON-legacy path
```

| Caller | Location | Kind |
|---|---|---|
| `create_agent()` | `dependencies.py:63` | **Production request path** — FastAPI dependency; stores the agent on `request.state` for every handler that depends on it |
| `create_agent()` | `main.py:743` | **Production endpoint** — `get_agent_info`, "validates agent exists" |
| `create_agent()` | `tests/test_multi_agent.py` ×3 | Tests |
| `create_agent_with_settings()` | — | **ZERO CALLERS across all ten repositories** |

### The finding

`CURRENT FACT` **`create_agent_with_settings()` is defined and never called anywhere.** Only
`create_agent()` is wired, and it takes `use_firestore_config=True`. Therefore the legacy
Firestore config service is not merely reachable — **it is the only agent-construction path
actually in use in this repository.**

### Can a settings object bypass the legacy path?

**Structurally yes, in practice no.** `Agent.__init__` accepts `settings` and
`use_firestore_config=False`, and raises `RuntimeError("No configuration source available...")`
if both are absent. But the only constructor call that supplies them is
`create_agent_with_settings()`, which nothing calls.

### Does any configuration select a path globally?

**No.** `CURRENT FACT` The selection is a constructor default in code, not a flag, environment
variable or deployment setting. There is no runtime switch.

### What the legacy service actually reads

`config/firestore_config.py` reads five collections: `agents` (×2), `agent_deployments`,
`agent_servers`, `mcp_servers`, `mcp_server_templates`. This simultaneously resolves the reader
question for `agent_servers` and surfaces `mcp_server_templates`, which appears in no registry.

### CONTRADICTION-2 · "legacy" classification vs. caller evidence

| | |
|---|---|
| **Source A** | `investigation/store-inventory.md`: `config/firestore_config.py` classified **LEGACY**, with *"the live factory path (`create_agent_with_settings`) explicitly disables it"* |
| **Source B** | `olbrain-agent-runtime/core/agent_factory.py` — `create_agent_with_settings` has **zero callers**; `create_agent()` (which enables the legacy service) is called from `dependencies.py` and `main.py` |
| **Why they conflict** | Source A treats the settings-based factory as the live path. Source B shows it is dead code and the legacy path is the only wired one. The classification inverts the actual call graph. |
| **Can code resolve it?** | **Yes — resolved by this pass.** The caller map is unambiguous. The "LEGACY" label is factually wrong for reachability. |
| **Senior input required?** | Not to establish the fact. **Yes** to decide what to do about it — QF-5, unchanged. |

**Scope discipline:** this establishes `KNOWN REACHABILITY`, as instructed. It does not measure
traffic volume, and it does not claim the legacy service is correct, desirable, or safe to
keep.

## 10. Remaining Unknowns

Every remaining item, with its exact reason.

| # | Unknown | Reason |
|---|---|---|
| R-1 | Payload/schema of `mcp_tool_executions` | **`BLOCKED BY ABSENT REPOSITORY`** — writer in `olbrain-mcp-deployer` |
| R-2 | Payload/schema of `agent_qa_runs` beyond the stated `org_id` | **`BLOCKED BY ABSENT REPOSITORY`** — writer in `olbrain-agent-eval` |
| R-3 | The ~17-collection Finance / P&L family | **`BLOCKED BY ABSENT REPOSITORY`** — `olbrain-finance-engine` |
| R-4 | Writers of `agent_webhook_logs`, `api_key_usage_events`, `audit_logs`, and the `whatsapp_*` family | **Insufficient source evidence** — not found in the ten repos; most plausibly studio-backend or an absent repo. Not inferred. |
| R-5 | Content of `lumen_sessions`, `alchemist_sessions`, `alchemist_conversations`, `agentify_sessions`, `synapse_sessions` | **Insufficient source evidence** — writers are present and could be opened, but payload shapes were not individually read this pass. **Answerable with more inspection of the current workspace.** |
| R-6 | Whether `workflow_items` step outputs carry customer PII | **Insufficient source evidence** — depends on the workflow definition, not on runtime code. Not determinable from any repository. |
| R-7 | Cloud Logging as a data surface — the heavy trace bodies `agent_traces` deliberately excludes | **Out of scope** — not Firestore; governed by IAM, never examined by any pass |
| R-8 | The fourth constants source behind `Collections.AGENT_SENDERS` / `Collections.TOOLS` | **Insufficient source evidence** — low value; cosmetic |
| R-9 | Canonical owner of `agents/{id}` | **`DECISION REQUIRED`** — not a code question |
| R-10 | Legal classification of the wallet / ledger / subscription family | **`DECISION REQUIRED`** — §16 row 5, Legal/compliance |
| R-11 | Whether the legacy `create_agent()` path should remain | **`DECISION REQUIRED`** — QF-5 |
| R-12 | Whether the absent repositories come into scope | **`DECISION REQUIRED`** — QF-3 |

**R-5 is the only item that further inspection of the current workspace could still close.** It
was deprioritised this pass because the writers are known and present, so it is bounded work
rather than an open question. Everything else is an absent repository, a decision, a
non-Firestore surface, or not determinable from code at all.

## 11. Questions That Still Require Senior Input

Unchanged from the prior pass. This pass supplies evidence for several and resolves none.

| ID | Question | Status after this pass |
|---|---|---|
| **QF-1** | Canonical owner of `agents/{id}` | **Strengthened** — ten write sites across three repos now enumerated, and confirmed there is **no** optimistic concurrency of any kind on the document |
| **QF-2** | Legal classification of financial collections | **Broadened** — nine previously unknown collections found, including `billing_records`, `billing_deployments`, `billing_tools`, `billing_kb_storage`, `agent_usage_summary` |
| **QF-3** | Bring the four absent repositories into scope? | **Sharpened** — now the single largest remaining blocker; three of twelve remaining unknowns are solely due to their absence |
| **QF-4** | Is the `organization_id`-stamping work ("S7") funded? | **Strengthened** — an existing production backfill script proves the tooling exists and enumerates 20 affected collections, but targets only `clix-capital-prod` |
| **QF-5** | Should the legacy `create_agent()` path remain reachable? | **Materially escalated** — it is not merely reachable, it is the **only wired path**; the alternative is dead code |

**New evidence, no new senior question.** Nothing this pass uncovered requires an owner
decision that was not already on the list.

## 12. Questions Resolved By This Pass

| Prior ID | Question | Resolution |
|---|---|---|
| **U-1** (partial) | Contents/PII of trace and session collections | **`agent_traces` fully resolved** — identifiers and counters only, carries `organization_id`, content deliberately routed to Cloud Logging. `mcp_tool_executions` and `agent_qa_runs` → `BLOCKED BY ABSENT REPOSITORY`. Session collections → R-5 |
| **U-2** | ~12 low-reference registry names | **Fully resolved.** 3 are `NOT A COLLECTION`; 2 confirmed declared-only; the rest live or existing-but-unattributed |
| **U-3** | ~15 rules-named collections never inventoried | **Fully resolved.** 13 classified live or rules-only; 2 reader-only-here |
| **U-6** | Fourth constants source | Not pursued — cosmetic. Carried as R-8 |
| **U-7** | `workflow_items` model, org field, PII | **Resolved** except PII (R-6). Service located in `olbrain-shared`; **no `organization_id`**; deterministic doc id; no rule; open r/w |
| **U-8** | `create_agent` vs `create_agent_with_settings` | **Fully resolved, and inverted the prior belief** — CONTRADICTION-2 |
| **U-9** | `memberships` (distinct from `memberships_index`) | **Resolved** — collaborator membership rows written by agent-design `routers/collaborators.py` |
| **AMB-04** (storage audit) | `secrets` / `permissions` / `team_memberships` | Closed last pass; nothing here contradicts it |
| **AMB-10** (storage audit) | Redis dead code or planned? | Not re-investigated per instruction; dormancy stands |

**Two new CONTRADICTIONs recorded**, both resolvable from code and both resolved:
CONTRADICTION-1 (stale `trace_collector.py:495` citation) and CONTRADICTION-2 (the "legacy"
config classification inverts the actual call graph).

## 13. Is the Workspace Inventory Now Sufficient?

### **NO — specific blockers.**

The ten-repository workspace is **exhausted** for practical purposes: every unknown these
repositories could answer has been answered, with one bounded exception (R-5). But
*exhausted* is not the same as *sufficient*, and the distinction is the whole point of this
document.

**The blockers, precisely:**

1. **Four absent repositories.** `olbrain-mcp-deployer`, `olbrain-agent-eval`,
   `olbrain-finance-engine`, `olbrain-agent-cloud` own the writers for
   `mcp_tool_executions`, `agent_qa_runs`, the ~17-collection finance family, and a second
   reader of `secrets`. Their schemas cannot be established from here and were not inferred.
2. **Unattributed writers inside the platform.** `agent_webhook_logs`,
   `api_key_usage_events`, `audit_logs` and the `whatsapp_*` family have readers or rules but
   no writer in any of the ten repos. They belong to some service, and we cannot say which.
3. **A non-Firestore data surface nobody has examined.** `agent_traces` deliberately keeps
   reasoning text and tool outputs **out** of Firestore and puts them in **Cloud Logging**.
   That is a real repository of turn content governed by IAM, not Firestore rules, and no
   investigation pass has looked at it.
4. **Decisions, not facts.** R-9 through R-12 are owner questions.

**What *is* sufficient now:** the Firestore picture for the ten repositories is as complete as
source reading can make it. If the answer to QF-3 is "no, do not bring the absent repositories
in," then this document is the terminal Firestore inventory for this programme, and blockers 1
and 2 become permanent stated limitations rather than open work.

## 14. What Must Still NOT Be Designed

Only items genuinely blocked by unresolved scope, authority or governance.

| Must not design | Blocked by |
|---|---|
| **Final PostgreSQL schema** | Scope still unbounded — four absent repositories (R-1…R-3) and four unattributed writers (R-4). A schema sized against a knowingly partial inventory would be wrong in the same way the registry is wrong. |
| **RLS policy design** | The tenancy predicate resolves through `memberships_index` (known), but ~20 collections still lack a row-level `organization_id` — now independently corroborated by the production backfill script. SF-I proves this already blocks the equivalent design in Firestore. |
| **Deletion / retention implementation** | R-10 / QF-2 — §16 row 5. The financial surface grew this pass; the finance family remains in an absent repository. |
| **`agent_datastores` decomposition** | Unchanged — AMB-01, AMB-02, storage audit §11.4. |
| **Migration cutover strategy** | Scope (above) plus R-9 / QF-1 — `agents/{id}` has ten writers, no OCC, and no declared owner. |
| **Anything assuming the legacy config path is dead** | CONTRADICTION-2 — it is the only wired path. Any design treating `create_agent_with_settings` as live is building on dead code. |

**What this pass did *not* newly block:** nothing. The list is unchanged in substance from the
previous audit; only the evidence beneath each item is stronger.

## 15. Source Traceability

### Read directly this pass

| Finding | Source |
|---|---|
| `knowledge_repositories`, `test_cases` are schema dict keys | `olbrain-agent-engine/alchemist/schemas/agent.py` |
| `agent_performance` is a sentiment field | `olbrain-agent-runtime/buildin_tools/sentiment_analysis/executor.py` |
| `user_analytics` written client-side | `olbrain-studio/src/services/analytics/analyticsService.js` |
| `agent_servers` writers and the legacy reader | `olbrain-agent-design/app/services/{agent_service,deployment_service,system_prompt_optimizer}.py`; `olbrain-agent-runtime/config/firestore_config.py` |
| `audit_logs` reader | `olbrain-agent-engine/alchemist/agents/lumen/evidence/firestore.py` |
| `memberships` writer | `olbrain-agent-design/app/routers/collaborators.py` |
| `conversations`, `messages` (subcollection), `alchemist_sessions`, `alchemist_conversations`, `user_profiles` | `olbrain-agent-design/app/services/conversation_service.py`, `firestore_service.py` |
| `users` | `olbrain-agent-design/app/services/user_profile.py`; `olbrain-agent-engine/routes.py` |
| `recommendations` as a subcollection + its migration tool | `olbrain-agent-engine/alchemist/agents/brain_builder.py`; `tools/migrate_recommendations_to_subcollection.py` |
| `capability_types`, `step_types` | `olbrain-agent-design/app/services/capability_types_sync.py`, `app/routers/capability_types.py`; `olbrain-studio/src/services/**` |
| `agentify_sessions`, `synapse_sessions`, `lumen_sessions` | `olbrain-agent-engine/alchemist/agents/{brain_builder,synapse_agent,lumen_agent}.py`, `routes.py` |
| **`agent_traces` writer and exact payload** | `olbrain-shared/src/olbrain_shared/agent/trace_collector.py`; shim at `olbrain-agent-runtime/core/trace_collector.py` |
| **`workflow_items` service, doc-id derivation, absent org field** | `olbrain-shared/src/olbrain_shared/workflow/firestore/service.py`; `olbrain-workflow-runtime/app/core/orchestrator.py` |
| **Nine unregistered collections + org-backfill evidence** | `olbrain-studio/scripts/backfill-clix-organization-id.js` |
| **`agents` write sites (ten, three repos)** | `olbrain-agent-design/app/routers/agent.py`, `app/services/{agent_service,brain_service}.py`; `olbrain-agent-engine/alchemist/agents/{brain_builder,agentify_agent}.py`, `alchemist/provision/store_build.py`; `olbrain-studio-backend/services/agent_transfer_service.py` |
| **`create_agent` caller map; `create_agent_with_settings` has zero callers** | `olbrain-agent-runtime/core/agent_factory.py`, `core/agent.py`, `dependencies.py`, `main.py` |
| Rules-only collections (zero code references) | exhaustive greps across all ten repos |

### Carried forward, not re-derived

`investigation/firestore-completeness-security-audit.md` (effective-rule verdicts, SF-I…SF-L),
`storage-reality-audit.md`, `store-inventory.md`, `implementation-spec.md`,
`governance-decision-request.md`, `architecture-freeze.md`, `reconciliation.md`,
`artifacts/senior-feedback.md`, `artifacts/repo-and-soul-map.md`.

### Normative

`artifacts/architecture-contract.md` — unmodified, md5 `97c1fa3bcea1d71210c0429b1d113d07`.

### Repository HEADs — all verified clean

agent-runtime `b2401a0` · agent-engine `8720720` · research-design `d044fce` ·
research-runtime `d1caecd` · workflow-runtime `5d48437` · knowledge-vault `6d76083` ·
shared `a837b95` · studio `252f7887` · studio-backend `6ada46a` · agent-design `bbc85c8`

Line numbers appear only where a specific call site was opened and are accurate at these HEADs.

---

**No repository under `repos/` was modified. No repository was cloned.** No Firestore or
PostgreSQL write, no migration, deployment, commit, push or PR. No PostgreSQL schema, RLS
design, migration strategy, or architecture decision was produced.
