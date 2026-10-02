# Firestore Completeness & Security Audit

**Date:** 2026-09-22
**Type:** read-only investigation, document-only output. No schema, no RLS, no migration design.

Labels used exactly as in `investigation/storage-reality-audit.md`: `CURRENT FACT`,
`TARGET REQUIREMENT`, `PROPOSED`, `UNKNOWN`, `DECISION REQUIRED`, plus `SECURITY FINDING`.

---

## 1. Purpose

Close the factual gap the storage audit identified: roughly 45 collections declared in the
canonical registry, about 30 meaningfully investigated, and three security-relevant names
(`secrets`, `permissions`, `team_memberships`) never examined at all.

This session set out to complete the inventory. **It did something more useful and more
uncomfortable: it disproved the framing of the gap itself.**

## 2. Executive Findings

**F1 — The registry is not the collection inventory, and never was.** `CURRENT FACT`
`olbrain-agent-engine/alchemist/constants/collections.py` declares **50 collection-name
constants** under a class whose own docstring calls it the "v3 enterprise schema" and asserts
"All collections are organization-scoped." That assertion is **demonstrably false** — several
declared collections carry no organization field at all, a fact already established in
`store-inventory.md` (Security Finding B).

More importantly, the registry **omits most of the collections this programme cares about**.
`agent_datastores`, `agent_user_memory`, `lead_profiles`, `context_facts`, `context_logs`,
`vibe_sessions` and the entire research family are **not in it**. The registry is one
service's partly-aspirational view, not a platform index.

**F2 — The real live surface is substantially larger than either prior count.** `CURRENT FACT`
`olbrain-studio/firestore.rules` contains **56 match blocks** naming roughly **40 top-level
collections** with dedicated rules, plus a further ~30 named only inside catch-all exclusion
lists. Many appear in neither the registry nor any prior investigation: `memberships_index`,
`billing_ledger`, `wallet_grants`, `wallet_recharges`, `twilio_accounts`, `agent_users`,
`agent_senders`, `human_agents`, `app_subscriptions`, `agent_subscriptions`,
`organization_subscriptions`, `superagent_threads`, `superagent_definitions`,
`superagent_runs`, `superagent_delegations`, `research_plans`, `research_chat_sessions`,
`research_golden_templates`, `outreach_campaigns`, `agent_webhook_logs`,
`api_key_usage_events`, `whatsapp_integrations`, `whatsapp_user_phones`, `whatsapp_webhooks`,
`synapse_sessions`, `agent_billing_summary`, and an entire **Finance department** family
(~17 P&L collections) served by `olbrain-finance-engine` — a repository not in this workspace.

**The Firestore rules file, not the registry, is the closest thing to an authoritative index
of the live surface.**

**F3 — `secrets` is real, security-critical, and correctly protected.** `CURRENT FACT` It is
not a top-level collection. The live path is
`organizations/{org_id}/secrets/llm_api_keys`, holding **KMS-encrypted** per-provider LLM API
keys, written by studio-backend when a user saves a key in Organization Settings and read by
`olbrain-shared`'s `OrgApiKeyService` (decrypt via KMS, 5-minute cache).

Its rule is `allow read: if false; allow write: if false;` **and** it is explicitly excluded
from the `organizations/{orgId}/{sub}/{rest=**}` catch-all. Double-protected. **This closes
the storage audit's AMB-04 concern for `secrets` in the reassuring direction.**

**F4 — `permissions` is not a Firestore collection.** `CURRENT FACT` Every reference is to a
**field**: `permissions: List[str]` on API-key records and user-context objects in
`olbrain-agent-design/app/middleware/auth.py`. The registry declaration is unused. There is
nothing to secure and nothing to migrate.

**F5 — `team_memberships` is declared and never used.** `CURRENT FACT` Zero references outside
the registry file. The **actual** authorization store is `memberships_index`, which is
`allow read, write: if false` — fully server-only — and is the collection
`isOrgMember()` resolves through (`exists(orgIndexPath(orgId))`). The authorization primitive
is correctly locked down.

**F6 — Ten registry collections are confirmed declared-only.** `CURRENT FACT` No reader, no
writer, no test: `team_memberships`, `billing_accounts`, `usage_metrics`,
`compliance_reports`, `system_health`, `feature_flags`, `knowledge_chunks`, `test_runs`,
`channel_configurations`, `aster_threads`.

**F7 — The most severe prior security finding is CONFIRMED still live at HEAD.**
`SECURITY FINDING` `agents/{agentId}` has a **real ownership rule** checking
`resource.data.userId == request.auth.uid || resource.data.owner_id == request.auth.uid` on
both the existing and incoming document. It is **OR-superseded** by the two-segment catch-all
`match /{collection}/{docId}`, in whose read **and** write exclusion lists `agents` does not
appear. Firestore ORs rules, so the catch-all governs. Any signed-in user can read or write
any agent document on the platform, including reassigning `owner_id` / `organization_id`.

**F8 — A systemic read/write asymmetry, documented by the rules file itself.**
`SECURITY FINDING` The top-level catch-all excludes **9** collections from read and **24**
from write. The ~15 collections in the write list but not the read list are therefore
**write-protected but readable by any authenticated user in any org** — including
`knowledge_library`, `research_plans`, `superagent_definitions`, `superagent_runs`,
`research_chat_sessions`, `agent_senders`, `outreach_campaigns` and `agent_users`.

**The rules file states the cause explicitly, and it is the missing-`organization_id`
problem.** Its own comment: *"Reads are NOT excluded, deliberately, and the gap is real...
Closing it needs org-scoped reads, and these documents carry no `organization_id` —
campaign_store.create_run writes none — so the rule that works elsewhere
(`isOrgMember(resource.data.organization_id)`) denies everyone when the field is absent."*
The stated remedy sequence is *"stamp organization_id, backfill, then move these into their
own org-scoped block."*

**This causally links Security Finding B to Security Finding E** — a connection no prior pass
made. The schema-level absence of `organization_id` is not merely a target-architecture
inconvenience; it is the **direct blocker** preventing the security team from closing the read
exposure today.

**F9 — Prior "legacy" classification of the Firestore config service is CONTRADICTED.**
`CURRENT FACT` `core/agent.py::Agent.__init__` takes `use_firestore_config: bool = True` —
**defaulting to on**. `core/agent_factory.py:57`'s `create_agent()` constructs
`Agent(agent_id)` with no settings, taking that default. `create_agent()` is called from
`dependencies.py:63` and `main.py:743` — live application paths. The legacy path is
**reachable**, not dead. (Whether it carries production traffic volume is not established;
the alternative `create_agent_with_settings()` passes `use_firestore_config=False`.)

**F10 — Redis confirmed dormant.** `CURRENT FACT` Outside the already-known settings fields,
the only reference is a **commented-out** line in `olbrain-agent-runtime/.env.example`
labelled "(Optional - for distributed caching)". No deployment configuration sets it.

## 3. Canonical Collection Registry

`CURRENT FACT` There are **three** collection registries, and they disagree.

| Registry | Declares | Notes |
|---|---|---|
| `olbrain-agent-engine/alchemist/constants/collections.py` | **50** collection constants | Self-described "v3 enterprise schema"; asserts all collections are org-scoped (false); omits most memory/state collections |
| `olbrain-knowledge-vault/constants/collections.py` | **9** constants | Includes names absent from the above: `conversations`, `knowledge_library`, `user_profiles`, `user_accounts`, `documents`; `KNOWLEDGE_FILES` marked `@deprecated` |
| `olbrain-studio/src/constants/collections.js` | frontend constants | A separate JS registry; `credit_transactions` appears here and in the Python registry but nowhere else |

Additionally, `olbrain-agent-design` references `Collections.AGENT_SENDERS` and
`Collections.TOOLS`, **neither of which exists in the agent-engine registry** — implying a
fourth constants source or a local definition. `UNKNOWN` — not traced this session.

**Consequence:** no single registry can be used as the migration scope. Any inventory built
from one of them will be incomplete.

## 4. Live vs Dead vs Unknown Collections

Classification of the 50 agent-engine registry constants. "Refs" counts literal-string
occurrences across all ten repositories including the registry declaration itself.

### Confirmed DECLARED-ONLY — no reader, no writer, no test `CURRENT FACT`

`team_memberships` · `billing_accounts` · `usage_metrics` · `compliance_reports` ·
`system_health` · `feature_flags` · `knowledge_chunks` · `test_runs` ·
`channel_configurations` · `aster_threads`

**10 collections.** These are aspirational schema names. Nothing reads or writes them.

### Confirmed LIVE — verified readers and/or writers `CURRENT FACT`

| Collection | Refs | Notes |
|---|---|---|
| `agents` | 501 | Central ownership record; writers in **three** repos (§9) |
| `organizations` | 129 | Parent for `secrets`, `connector_credentials`, finance family |
| `agent_sessions` | 58 | Prior inventory |
| `workflow_definitions` | 29 | Prior inventory |
| `workflow_items` | 27 | §10 |
| `mcp_servers` | 27 | Not previously inventoried |
| `agent_messages` | 23 | Prior inventory |
| `workflow_runs` | 22 | Prior inventory |
| `workflow_proposals` | 17 | Not previously inventoried — "co-designer improvement proposals" |
| `events` | 16 | Not previously inventoried |
| `workflow_agent_memory` | 15 | Prior inventory |
| `secrets` | 13 | **§5 — subcollection, KMS-encrypted, locked down** |
| `tickets` | 10 | Not previously inventoried |
| `lumen_sessions` | 6 | Observability agent |
| `agent_traces`, `agent_qa_runs`, `agent_learned_patterns`, `agent_deployments` | 5 each | §7 |
| `support_sessions`, `notifications`, `mcp_tool_executions`, `agent_config_drafts`, `agent_config_actives` | 4 each | §7 |
| `workflow_agent_decisions`, `prompt_templates`, `alchemist_sessions`, `alchemist_conversations` | 3 each | — |

### Confirmed DEAD / LEGACY `CURRENT FACT`

| Collection | Evidence |
|---|---|
| `knowledge_embeddings` | 2 refs; prior investigation confirmed zero live readers/writers |
| `permissions` | **Not a collection** — a field name (F4) |

### UNKNOWN — reference count does not establish live use

The remaining registry names (`knowledge_repositories`, `test_cases`, `integration_channels`,
`user_analytics`, `agent_performance`, `business_intelligence`, `conversation_feedback`,
`alchemist_actions`, `agent_servers`, `agent_configurations`, `audit_logs`,
`credit_transactions`) carry 1–2 references each. A count that low is consistent with either
a declaration plus one stale import, or a genuine single call site. **This audit did not
individually open each one**, and does not claim to have classified them.
`UNKNOWN — resolvable by inspection.`

**Honest count for §17.**

## 5. Security / Authorization Collections

### `secrets` — RESOLVED, and correctly secured

| | |
|---|---|
| **Actual path** | `organizations/{org_id}/secrets/llm_api_keys` — a **subcollection**, not top-level |
| **Contents** | KMS-encrypted per-provider LLM API keys (`encrypted_key` per provider) |
| **Writer** | `olbrain-studio-backend`, on save in Organization Settings → API keys |
| **Readers** | `olbrain-shared` `core/kms/org_api_key.py::OrgApiKeyService`; `olbrain-agent-runtime` `services/org_api_key_service.py`. Decrypt via KMS, 5-minute per-(org,provider) cache |
| **Also referenced by** | `olbrain-agent-cloud` — a repository **not in this workspace** |
| **Firestore rule** | `allow read: if false; allow write: if false;` — explicit block, plus **excluded by name** from the `organizations/{orgId}/{sub}/{rest=**}` catch-all |
| **Verdict** | **Correctly protected at both layers.** Contents are KMS-encrypted, so even a rules failure would not yield plaintext keys |

The rules file's own comment — *"`secrets` (backend credentials; the explicit block above is
now real)"* — indicates the catch-all exclusion was added specifically to make the explicit
block effective. That is the exact fix pattern the `agents` collection still lacks.

### `permissions` — NOT A COLLECTION

`CURRENT FACT` A field (`permissions: List[str]`) on API-key records and `UserContext` objects
in `olbrain-agent-design/app/middleware/auth.py`, checked by `require_permission` /
`check_view_permission` / `check_edit_permission`. The registry entry is dead. No rule needed,
nothing to migrate.

### `team_memberships` — DECLARED-ONLY; the real store is `memberships_index`

`CURRENT FACT` Zero references outside the registry. The live authorization store is
`memberships_index`:

- Rule: `allow read, write: if false` — **fully server-only**.
- It is the collection `isOrgMember(orgId)` resolves through: `exists(orgIndexPath(orgId))`.
- `isOrgAdmin` / owner-equivalent checks read roles from the same index.
- It is in the top-level catch-all's **read and write** exclusion lists, annotated
  "authorization data" and "a write here grants yourself any role."

**Verdict:** the authorization primitive is correctly and deliberately locked down at both
layers. There is also a separate `memberships` collection with its own match block, not
traced this session — `UNKNOWN`.

## 6. Billing / Financial Collections

`CURRENT FACT` The registry's billing names are **declared-only**: `billing_accounts`,
`usage_metrics` (zero references), and `credit_transactions` (registry files only).

The **live** financial collections are ones the registry does not declare, discovered via the
rules file:

| Collection | Rule posture | Rules file's own annotation |
|---|---|---|
| `billing_ledger` | Read **and** write excluded from catch-all; dedicated block | "org admins/owners only"; "immutable audit trail" |
| `wallet_grants` | Read + write excluded | "org members only"; "forging a credit record" |
| `wallet_recharges` | Read + write excluded | "org members only"; written by billing-service `wallet_service.add_recharge`; "the idempotency ledger those paths check before crediting" |
| `app_subscriptions` | **Write** excluded only | "entitlement dates and plan price" |
| `agent_subscriptions` | **Write** excluded only | "per-agent entitlement dates + invoicing state" |
| `organization_subscriptions` | **Write** excluded only | "status + trial_end ARE the entitlement gate" |
| `agent_billing_summary` | dedicated match block | not traced |
| `organizations` (wallet) | write excluded | "the wallet lives here" |
| Finance department (~17 P&L collections) | all excluded from the org catch-all | Served exclusively by **`olbrain-finance-engine`** Admin SDK — a repo not in this workspace |

**Technical facts established.** `billing_ledger`, `wallet_grants` and `wallet_recharges` are
described in source as audit trails and idempotency ledgers — i.e. authoritative financial
records, not derived aggregates. The three `*_subscriptions` collections are entitlement
gates.

**What this audit does NOT decide.** Whether any of these constitutes a customer financial
record with a statutory retention obligation, whether any is an "aggregate dataset" in the
sense of contract §10, and what `customer_deletion_behavior` applies. `GOVERNANCE REQUIRED` —
this is §16 row 5, owner **Legal / compliance / data governance**, and remains open.

**A scope observation for §16 row 5:** the finance family is served by a repository not in this
workspace. Any per-dataset classification exercise cannot be completed from the ten repos
alone.

## 7. Trace / Execution / Audit Collections

Reference counts and rule posture established; **contents were not individually opened** for
most. Where PII status is not established from source it is recorded as `UNKNOWN`, not
inferred.

| Collection | Refs | What is established | PII / secrets | Rule posture |
|---|---|---|---|---|
| `agent_traces` | 5 | Named in the registry under "customer agent runtime artifacts (written by olbrain-agent-runtime + **olbrain-mcp-deployer**)" | `UNKNOWN` | Falls to catch-all → open r/w |
| `mcp_tool_executions` | 4 | Same group — tool execution records | `UNKNOWN` — tool input/output plausible but not verified | Catch-all → open r/w |
| `audit_logs` | 2 | Registry + one agent-engine test only | `UNKNOWN` | No dedicated rule found |
| `agent_deployments` | 5 | Dedicated match block exists | `UNKNOWN` | Dedicated block, not traced |
| `agent_configurations` | 1 | Declaration only | — | `UNKNOWN` |
| `agent_servers` | 2 | "Agent service URLs and server status" | Infrastructure metadata | `UNKNOWN` |
| `mcp_servers` | 27 | **Live** — MCP server URLs and configuration | Possibly credential-adjacent; `UNKNOWN` | `UNKNOWN` |
| `alchemist_sessions` | 3 | "chat sessions with messages subcollection" | Design-conversation content likely | Catch-all |
| `alchemist_conversations` | 3 | "User-scoped Alchemist assistant conversations" | Design-conversation content likely | Dedicated match block exists |
| `lumen_sessions` | 6 | Observability/explainability agent sessions | `UNKNOWN` | Catch-all |
| `agent_qa_runs` | 5 | "written by **olbrain-agent-eval**. Org-scoped via a top-level `org_id` field; read by Lumen's eval tools only" | `UNKNOWN` | Catch-all |

**Two findings worth separating out.**

`agent_qa_runs` is the **only** collection in this group whose registry comment states an
explicit top-level `org_id` field — i.e. the one row-level org binding in the group.
`CURRENT FACT`

`agent_traces` and `mcp_tool_executions` are attributed to **`olbrain-mcp-deployer`**, and
`agent_qa_runs` to **`olbrain-agent-eval`** — both repositories **absent from this workspace**.
Their writers cannot be inspected here. `UNKNOWN — repository not available.`

**Not mapped to target semantic classes.** Per the brief, this is a current-state inventory
only; none of these is classified as Evidence, Memory or execution state here.

## 8. Effective Firestore Rules

`CURRENT FACT` `olbrain-studio/firestore.rules` — 55,184 bytes, **56 match blocks**. A second
ruleset, `firestore.clix.rules` (26,132 bytes), governs the dedicated `clix-capital-prod`
tenant and was previously confirmed genuinely default-deny.

### Rule architecture

Three catch-alls OR together with every dedicated rule. Firestore grants an operation if **any**
matching rule allows it, so a tighter rule inside the shadow of an unexcluded catch-all is dead
code.

| Catch-all | Read gate | Write gate |
|---|---|---|
| `/{collection}/{docId}` (2-segment) | `isAuthenticated()` minus **9** excluded collections | `isAuthenticated()` minus **24** excluded collections |
| `/{collection}/{docId}/{sub}/{rest=**}` (4-segment) | `isAuthenticated()` minus `organizations`, `agents`, `agent_datastores`, `twilio_accounts` | same minus 8: adds `research_chat_sessions`, `research_runs`, `outreach_campaigns`, `agent_users` |
| `/organizations/{orgId}/{sub}/{rest=**}` | `isAuthenticated()` minus 18 named subcollections | same list |
| `/agents/{agentId}/{sub}/{rest=**}` | `isAuthenticated()` — **no exclusions** | `isAuthenticated()` except `sub == 'owner_lessons'` |

### Effective verdicts — previously uninvestigated collections

| Collection | Effective rule | Who can read | Who can write | Org isolation | Catch-all affected? | Confidence |
|---|---|---|---|---|---|---|
| `organizations/{org}/secrets/**` | Explicit `if false` + excluded | **Nobody (client)** | **Nobody (client)** | n/a — server-only | No — excluded | **HIGH** |
| `memberships_index` | Explicit `if false` | **Nobody (client)** | **Nobody (client)** | n/a — server-only | No — excluded both lists | **HIGH** |
| `billing_ledger` | Dedicated block + excluded both | per block | per block | org admins/owners per annotation | No | **MEDIUM** — block not read in full |
| `wallet_grants`, `wallet_recharges` | Dedicated + excluded both | org members per annotation | denied | yes | No | **MEDIUM** |
| `twilio_accounts` | Excluded from read **and** write in both catch-alls | denied | denied | n/a | No — now excluded | **HIGH** |
| `app_subscriptions`, `agent_subscriptions`, `organization_subscriptions` | Write excluded; **read not** | **any authenticated user, any org** | denied | **none on read** | **Yes — read** | **HIGH** |
| `knowledge_library`, `research_plans`, `research_golden_templates`, `agent_senders`, `superagent_definitions`, `superagent_runs`, `superagent_delegations`, `research_chat_sessions` | Write excluded; **read not** | **any authenticated user, any org** | denied | **none on read** | **Yes — read** | **HIGH** |
| `outreach_campaigns`, `agent_users` | Write excluded in both; **read in neither** | **any authenticated user, any org** | denied | **none** | **Yes — read** | **HIGH** — the file says so explicitly |
| `agents/{id}` | Real ownership rule **OR-superseded** by 2-segment catch-all | **any authenticated user** | **any authenticated user** | **none** | **Yes — both** | **HIGH** |
| `agent_traces`, `mcp_tool_executions`, `lumen_sessions`, `agent_qa_runs`, `alchemist_sessions` | No dedicated rule found | any authenticated user | any authenticated user | none | Yes | **MEDIUM** |
| `workflow_items`, `workflow_runs`, `workflow_definitions` | No rule at all | any authenticated user | any authenticated user | none | Yes | **HIGH** |
| Finance family (~17) | Excluded from org catch-all | denied | denied | server-only | No | **HIGH** |

### Effective, not intended

Two places where source comments describe protection that the effective rule does **not**
deliver, and one where it now does:

- **`agents/{agentId}`** — a precise, correct ownership rule exists and is **superseded**. The
  intended security is not the actual security. `SECURITY FINDING`
- **The read/write asymmetry** — the file documents the read gap as deliberate and currently
  unclosable (F8), with a stated dependency on stamping `organization_id` first. This is
  intended-and-known, not intended-and-believed-closed.
- **`secrets` and `twilio_accounts`** — both have explicit blocks that **are** effective,
  because each was also added to the catch-all exclusion lists. This is the working pattern.

### A near-miss the file records against itself

The rules file documents that `twilio_accounts` held **plaintext Twilio `account_sid` +
`auth_token`**, sat in no match block at all, and was therefore readable by every signed-in
user on the platform until a 2026-09-15 fix. It further warns that
`whatsapp_service.py` writes a `webhook_secret` onto the parent document, so a future
`secrets/` or `rotations/` subcollection "would have inherited an authenticated read."

**This is evidence of an active, self-auditing hardening effort** — and simultaneously
evidence that the exposure class recurs as new collections are added.

## 9. `agents` Ownership Audit

`CURRENT FACT` Write paths confirmed in **three repositories**:

| Repository | Write sites (non-test) | What it changes |
|---|---|---|
| `olbrain-agent-design` | `app/routers/agent.py` (`.update`), `app/services/agent_service.py` (×3: two `.update`, one `.set`), `app/services/brain_service.py` (×4: `.update`/`.set(merge=True)`) | Agent CRUD, publish/version activation, brain payloads |
| `olbrain-agent-engine` | `alchemist/agents/brain_builder.py` (`.update`), `alchemist/provision/store_build.py` (`.update`), `alchemist/agents/agentify_agent.py` (`.set`) | Provisional agent creation, brain build results, store provisioning |
| `olbrain-studio-backend` | `services/agent_transfer_service.py` (×2 `.update`) | Cross-org transfer — reassigns `organization_id` |

### Can these writes conflict?

`CURRENT FACT` **Yes, structurally.** Three independent services write the same document.
`agent-design` uses `@firestore.transactional` for some paths (agent create, versioned
deployment, nested-dict overlays); `agent-engine`'s `brain_builder` uses a transactional
**lease** on a different document before updating; `studio-backend`'s transfer uses a plain
`.update()`. There is **no shared version field, no CAS, and no cross-service coordination
primitive** on `agents/{id}`. A transfer re-stamping `organization_id` and a concurrent
design-side publish are not serialised against each other by anything.

### Is a canonical owner explicit in code?

**No.** `CURRENT FACT` No source read this session declares an owner-of-record for the
document. `olbrain-studio-backend`'s `AgentService` is the org/owner-scoped **API** surface;
`olbrain-agent-design` performs the most writes; `olbrain-agent-engine` creates provisional
documents before any of that.

### Do transfers depend on this document?

**Yes.** `CURRENT FACT` The nine-step cross-org transfer cascade reassigns
`organization_id`/`owner_id` here, and this document is the anchor every other org-scoping
decision resolves through (`knowledge_library` resolves org transitively via the agent doc;
agent-design's `_get_knowledge_base` and `skill_binding_service` both resolve org from it).

**Compounding fact:** this document is also the one the catch-all leaves world-writable (F7).
A collection that is simultaneously (a) the platform's authorization anchor, (b) written by
three services with no concurrency control, and (c) client-writable by any signed-in user is
the single highest-risk item in the storage picture.

`OWNER UNRESOLVED — ASK SENIOR.` This audit does not choose an owner.

## 10. `workflow_items` Audit

| Question | Finding |
|---|---|
| Firestore rule | **None.** No dedicated match block; no appearance in any exclusion list. Falls to the 2-segment catch-all → **any authenticated user may read and write**. `CURRENT FACT` |
| Parent relationship | One document per row of a workflow run; described in `app/core/orchestrator.py` as *"the source-of-truth for aggregation"*. Related to a run via `run_id`. `CURRENT FACT` |
| Schema / model | **No Pydantic model located** — not in `olbrain-workflow-runtime`, not in `olbrain-shared`. Confirms the storage audit's prior gap. `UNKNOWN` |
| Org identifier | **Not established.** No row-level `organization_id` found; org association is inferable only transitively through the parent run. `UNKNOWN` |
| Writer / reader | `olbrain-workflow-runtime` orchestrator writes each item as it completes; re-read on `/resume` to avoid duplicate docs. `CURRENT FACT` |
| Is org binding explicit or merely transitive? | **Merely transitive — and the authorization path does not depend on it.** `CURRENT FACT` |

**The point that matters.** Per the brief's instruction not to infer an org boundary from a
parent unless the authorization path depends on it: here it demonstrably does **not**. There
is no rule on `workflow_items` at all, so no authorization path consults the parent. The
transitive relationship is a data-model convenience, not a security boundary.

`workflow_items` carries step outputs; larger outputs are written to the item document
(`orchestrator.py` notes smaller outputs stay inline). Whether those outputs contain customer
PII is `UNKNOWN` and was not established this session.

## 11. Redis / Legacy Config Reachability

### Question 1 — Redis outside the known dormant settings?

**No.** `CURRENT FACT` The only reference beyond `requirements.txt` and the
`redis_url` / `rate_limit_storage` settings fields is a **commented-out** line in
`olbrain-agent-runtime/.env.example`:

```
# REDIS (Optional - for distributed caching)
# REDIS_URL=redis://localhost:6379
```

No deployment YAML, no production environment file, no Dockerfile sets it. The storage audit's
F4 (dormant) is **confirmed**.

### Question 2 — Is the legacy Firestore config service reachable from a real production path?

**Yes — this CONTRADICTS the prior classification.** `CURRENT FACT`

```text
core/agent.py::Agent.__init__(agent_id, settings=None, use_firestore_config=True)   ← defaults ON
    └─ if self._use_firestore_config:  self.config_service = FirestoreConfigService(agent_id)

core/agent_factory.py:57   create_agent(agent_id) → Agent(agent_id)        ← takes the default
core/agent_factory.py:113  create_agent_with_settings(...) → Agent(..., use_firestore_config=False)

callers of create_agent():  dependencies.py:63  ·  main.py:743
```

`create_agent()` — the path that uses the legacy Firestore config service — is invoked from
FastAPI dependency injection and from `main.py`. Both are live application paths.

**Precise scope of this correction.** `store-inventory.md` classified
`config/firestore_config.py` as **LEGACY** with live reachability recorded as an
`OPEN QUESTION`. That question is now **resolved in the direction of reachable**. This audit
does **not** establish how much production traffic takes `create_agent()` versus
`create_agent_with_settings()`, so it does not claim the legacy path is the dominant one —
only that it is not dead, and that the earlier "legacy" label understates it.

## 12. Newly Confirmed Security Findings

Numbered continuing from `store-inventory.md`'s A–H.

### SF-I · Read/write asymmetry leaves ~15 collections cross-org readable `SECURITY FINDING`

The top-level catch-all excludes 9 collections from read and 24 from write. The difference is
readable by any authenticated user in any org, including `knowledge_library`, `research_plans`,
`superagent_definitions`, `superagent_runs`, `superagent_delegations`,
`research_chat_sessions`, `research_golden_templates`, `agent_senders`, `outreach_campaigns`,
`agent_users`, `app_subscriptions`, `agent_subscriptions`, `organization_subscriptions`,
`human_agents`.

`agent_users` holds end-user names and **phone numbers** per the file's own annotation;
`outreach_campaigns` exposes another org's campaign progress.

**Root cause is stated in the source:** these documents carry no `organization_id`, so the
org-scoped rule used elsewhere would deny everyone. **This makes Security Finding B (missing
row-level org field) the direct blocker on closing Security Finding E's read exposure.**
Known, documented, and sequenced by the team as "S7 of the Outreach migration."

### SF-J · `agents/{id}` ownership rule confirmed still superseded at HEAD `SECURITY FINDING`

The dedicated rule is correct and specific; `agents` appears in neither catch-all exclusion
list, so the catch-all's bare `isAuthenticated()` governs. Re-verified at HEAD `252f7887`.
Severity is compounded by §9: three uncoordinated writers and platform-wide authorization
dependence on the same document.

### SF-K · `agents/{id}/{sub}/**` grants authenticated read with no exclusions `SECURITY FINDING`

The dedicated subcollection catch-all is `allow read: if isAuthenticated()` with **no
exclusion list at all**, and write for everything except `owner_lessons`. This covers
`agents/{id}/mcp_configs/*` — the MCP bindings — and every other agent subcollection.

### SF-L · Historical: plaintext Twilio credentials were world-readable `SECURITY FINDING` — remediated

`twilio_accounts` held plaintext `account_sid` + `auth_token`, was in no match block, and fell
to the catch-all. Fixed 2026-09-15; now excluded from read and write in both catch-alls.
Recorded because the file's own comment warns the same inheritance risk applies to any future
subcollection under it, and because `whatsapp_service.py` already writes a `webhook_secret`
onto the parent document.

### What is provably right, for calibration

`secrets` (KMS-encrypted, explicit block **plus** catch-all exclusion), `memberships_index`
(the authorization primitive, fully server-only), `agent_datastores`, `agent_user_memory`,
`lead_profiles`, `twilio_accounts`, the wallet/ledger family, and the entire finance family
are all correctly locked down. The working pattern is consistent and visible: **an explicit
block only becomes effective when the collection is also named in the catch-all exclusion
list.** `agents` is the notable collection that has the first half and not the second.

## 13. Remaining Unknowns

| ID | Unknown | Security-relevant? |
|---|---|---|
| U-1 | Contents, PII status and retention of `agent_traces`, `mcp_tool_executions`, `lumen_sessions`, `alchemist_sessions`, `alchemist_conversations` | **Yes** — all fall to the catch-all (open r/w) and may carry conversation or tool content |
| U-2 | Classification of ~12 registry names with 1–2 references (`knowledge_repositories`, `test_cases`, `integration_channels`, `user_analytics`, `agent_performance`, `business_intelligence`, `conversation_feedback`, `alchemist_actions`, `agent_servers`, `agent_configurations`, `audit_logs`, `credit_transactions`) | Partly — `audit_logs` and `agent_servers` if live |
| U-3 | The ~20 collections with dedicated match blocks never inventoried (`memberships`, `conversations`, `messages`, `databases`, `user_profiles`, `users`, `recommendations`, `capability_types`, `step_types`, `synapse_*`, `whatsapp_*`, `agent_webhook_logs`, `api_key_usage_events`, `agentify_sessions`, `dev_conversations`) | **Yes** — `users`, `user_profiles`, `whatsapp_user_phones` are PII-bearing by name |
| U-4 | The Finance department family (~17 P&L collections) — owned by `olbrain-finance-engine`, **repo absent** | Rules-wise protected; contents unknown |
| U-5 | Writers of `agent_traces` / `mcp_tool_executions` (`olbrain-mcp-deployer`) and `agent_qa_runs` (`olbrain-agent-eval`) — **repos absent** | **Yes** |
| U-6 | The fourth constants source behind `Collections.AGENT_SENDERS` / `Collections.TOOLS` in agent-design | No |
| U-7 | `workflow_items` model, row-level org field, and PII content | **Yes** — no rule at all |
| U-8 | Production traffic split between `create_agent()` (legacy config) and `create_agent_with_settings()` | No — correctness, not security |
| U-9 | `memberships` (distinct from `memberships_index`) — purpose and rule | **Yes** — authorization-adjacent by name |

**Four repositories are referenced by in-workspace source but absent from the workspace:**
`olbrain-mcp-deployer`, `olbrain-agent-eval`, `olbrain-finance-engine`, `olbrain-agent-cloud`.
Their collections cannot be inventoried from here at all.

## 14. Questions Requiring Senior Input

Only owner-level questions. Everything answerable by reading repositories is in §13 instead.

| ID | Question | Why code cannot settle it | Affected system | Severity | ASK SENIOR? |
|---|---|---|---|---|---|
| **QF-1** | Who is the canonical owner of `agents/{id}`? | Three services write it; no source declares an owner-of-record | Platform authorization anchor, transfer cascade, org resolution | **High** | **Yes** |
| **QF-2** | Are `billing_ledger`, `wallet_grants`, `wallet_recharges` and the `*_subscriptions` collections customer financial records with statutory retention, and are any "aggregate datasets" under contract §10? | The technical purpose is clear from source; the legal classification is not a code question | Deletion design; §16 row 5 | **High** | **Yes** — this is §16 row 5, owner Legal/compliance |
| **QF-3** | Should the four absent repositories (`olbrain-mcp-deployer`, `olbrain-agent-eval`, `olbrain-finance-engine`, `olbrain-agent-cloud`) be brought into scope before the inventory is called complete? | Their collections are written outside this workspace and cannot be inspected | Inventory completeness; migration scope | **High** | **Yes** |
| **QF-4** | Is the `organization_id`-stamping + backfill sequence the rules file calls "S7" funded and scheduled? | The rules file states reads cannot be org-scoped until it lands; whether it is prioritised is a programme decision | SF-I read exposure across ~15 collections | **High** | **Yes** |
| **QF-5** | Is the legacy `create_agent()` / `FirestoreConfigService` path intended to remain reachable? | Source shows it is reachable and defaults on; intent is not recorded | agent-runtime config loading | Medium | **Yes** |

**Not re-asked here:** G1–G8, R1, R2, D1–D7, and storage-audit Q-S1…Q-S5 all remain open and
unchanged. This audit supplies evidence relevant to several — notably QF-2 feeding §16 row 5,
and SF-I materially strengthening the case that Security Finding B is a prerequisite rather
than a parallel concern — but resolves none of them.

## 15. What Is Now Safe to Design

Nothing new became designable. The three items below moved from unknown to known, which
removes them as *blockers on specific questions*, not as blockers on schema work.

| Now established | Consequence |
|---|---|
| `secrets` is a KMS-encrypted subcollection, correctly locked at both layers | It is **not** a migration candidate and **not** a security finding. Remove it from the open-risk list. |
| `permissions` is a field, `team_memberships` is declared-only, `memberships_index` is the real server-only authorization store | The authorization primitive is identified and sound. Any future tenancy predicate has a known source of truth to resolve through. |
| Redis is dormant; the legacy config path is reachable | Two factual questions closed. Neither unblocks design. |

## 16. What Still Must NOT Be Designed

Unchanged from `storage-reality-audit.md` §17, and **reinforced** — this session made the
scope problem worse, not better.

| Must not design | Why, after this audit |
|---|---|
| **Final PostgreSQL schema** | The inventory is **further** from complete than the previous audit believed. Three disagreeing registries, ~20 rule-declared collections never inventoried, four referenced repositories absent. Scope is not knowable from this workspace. |
| **RLS policy design** | Now better informed but not ready: the tenancy predicate would resolve through `memberships_index`, but ~15 collections carry **no `organization_id` to predicate on** (SF-I). The rules file proves this blocks the equivalent design in Firestore today. |
| **Deletion / retention implementation** | QF-2 is unanswered and is §16 row 5. The finance family's classification cannot even be attempted from this workspace. |
| **`agent_datastores` decomposition** | Unchanged — AMB-01, AMB-02, and the §11.4 conclusion of the storage audit. |
| **Migration cutover strategy** | Scope unknown (above) and `agents/{id}` ownership unresolved (QF-1). |
| **Anything treating the registry as the collection list** | F1 — it is neither complete nor accurate. |

## 17. Inventory Completeness — Explicit Statement

**Registry collections inspected:** 50 (the full `Collections` class in
`olbrain-agent-engine/alchemist/constants/collections.py`), by reference count across all ten
repositories, plus targeted source reads of the priority names.

| Outcome | Count |
|---|---|
| Confirmed **declared-only** (no reader, no writer, no test) | **10** |
| Confirmed **live** (verified readers and/or writers) | **~26** |
| Confirmed **dead / not-a-collection** | **2** (`knowledge_embeddings`; `permissions` is a field) |
| **Unknown** — 1–2 references, not individually opened | **~12** |

**Beyond the registry:** `firestore.rules` names roughly **40 top-level collections with
dedicated match blocks** and a further ~30 inside exclusion lists. Approximately **20** of
these were never inventoried by any pass, and the ~17-collection finance family belongs to an
absent repository.

**Security-relevant unknowns:** U-1 (trace/execution content), U-3 (`users`, `user_profiles`,
`whatsapp_user_phones`), U-5 (writers in absent repos), U-7 (`workflow_items`), U-9
(`memberships`). Five of nine remaining unknowns are security-relevant.

### Is the storage inventory now complete enough to begin target schema design?

### **No.**

The repository evidence does not support that claim, and this session moved the answer
*further* from yes:

1. **The scope grew rather than closed.** The previous audit framed the gap as "45 declared vs
   30 investigated." The real surface is larger than the registry, the registry is partly
   aspirational, and there are three mutually inconsistent registries.
2. **Four referenced repositories are absent** from the workspace, and they own collections
   including trace, eval and the entire finance family. No inventory built here can be called
   complete while their writers are uninspectable.
3. **~20 rule-declared collections have never been inventoried**, several PII-bearing by name.
4. **The one genuinely new structural insight argues for waiting**: SF-I shows the missing
   `organization_id` is already blocking the security team from closing cross-org reads in
   Firestore. Designing a tenancy model before knowing which collections can carry a tenant
   key would repeat that mistake in a new technology.

**What is complete enough:** the three priority security questions this session was called to
answer are now answered (§5), and the authorization primitive is identified. That was the
session's purpose and it succeeded. It simply revealed a larger inventory problem behind it.

## 18. Evidence / Source Traceability

| Finding | Source read this session |
|---|---|
| Registry contents, docstring, 50 constants | `olbrain-agent-engine/alchemist/constants/collections.py` |
| Second and third registries | `olbrain-knowledge-vault/constants/collections.py`; `olbrain-studio/src/constants/collections.js` |
| `secrets` path, KMS encryption, readers | `olbrain-shared/src/olbrain_shared/core/kms/org_api_key.py`; `olbrain-agent-runtime/services/org_api_key_service.py` |
| `permissions` is a field | `olbrain-agent-design/app/middleware/auth.py` |
| `secrets` rule + catch-all exclusion; `memberships_index`; `isOrgMember`; all catch-alls and exclusion lists; the read/write asymmetry commentary; the twilio history | `olbrain-studio/firestore.rules` |
| `agents/{agentId}` ownership rule and its supersession | `olbrain-studio/firestore.rules` |
| `agents` write paths in three repos | `olbrain-agent-design/app/routers/agent.py`, `app/services/agent_service.py`, `app/services/brain_service.py`; `olbrain-agent-engine/alchemist/agents/brain_builder.py`, `alchemist/provision/store_build.py`, `alchemist/agents/agentify_agent.py`; `olbrain-studio-backend/services/agent_transfer_service.py` |
| `workflow_items` role and absence of a model | `olbrain-workflow-runtime/app/core/orchestrator.py` |
| Redis dormancy | `olbrain-agent-runtime/.env.example` |
| Legacy config reachability | `olbrain-agent-runtime/core/agent.py`, `core/agent_factory.py`, `dependencies.py`, `main.py` |

**Carried forward, not re-derived:** `investigation/storage-reality-audit.md`,
`store-inventory.md` (Security Findings A–H), `implementation-spec.md`,
`governance-decision-request.md`, `architecture-freeze.md`, `reconciliation.md`,
`artifacts/senior-feedback.md`, `artifacts/repo-and-soul-map.md`.

**Normative:** `artifacts/architecture-contract.md` §10, §14, §16 — unmodified, md5
`97c1fa3bcea1d71210c0429b1d113d07`.

**Repository HEADs — all verified clean:** agent-runtime `b2401a0` · agent-engine `8720720` ·
research-design `d044fce` · research-runtime `d1caecd` · workflow-runtime `5d48437` ·
knowledge-vault `6d76083` · shared `a837b95` · studio `252f7887` · studio-backend `6ada46a` ·
agent-design `bbc85c8`.

Line numbers are not reproduced — they drift.

---

**No repository under `repos/` was modified.** No Firestore or PostgreSQL write, no migration,
no deployment, commit, push or PR. No schema, no RLS policy, no migration architecture, and no
Firestore-to-Postgres mapping was produced.
