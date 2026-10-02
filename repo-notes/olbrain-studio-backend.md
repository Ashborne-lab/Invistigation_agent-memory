# olbrain-studio-backend — Repo Notes

- **Repo:** `olbrain-studio-backend`
- **HEAD:** `6ada46a5af7bf4b6f661547ebdfa7011f365b19a` (short `6ada46a`), verified to match `origin/main`, committed 2026-09-18 08:54:15 +0530
- **Review date:** 2026-09-19
- **Scope note:** Targeted grep-and-trace pass only (~466 source files in repo; not surveyed generally). Scoped to: agent-transfer/deletion cascade, `organization_api_keys`, `organization_documents`, provisional-agent list filtering, `agent_datastores` HTTP surface, and a bonus check on org-connector-credential scoping. All findings below are read-only source citations against this exact commit.

---

## 1. `services/agent_transfer_service.py` — org-transfer/deletion cascade

The org-scoped teardown policy is a named tuple, stated once and asserted by tests:

```python
# services/agent_transfer_service.py:79-89
_ORG_SCOPED_TEARDOWN_STEPS = (
    "archive_usage_rollups",
    "archive_agent_memory",
    "update_billing_subscription",
    "reset_billing_config",
    "suspend_senders",
    "revoke_share_tokens",
    "revoke_agent_memberships",
    "detach_knowledge_library",
    "detach_mcp_configs",
)
```

This tuple is consumed inside `relocate_agent()` (`services/agent_transfer_service.py:1398-1859`), which is the single cascade body called from both `accept_transfer` (agent-transfer-invite acceptance, call site `agent_transfer_service.py:2252`) and `move_agent` (an org-admin-driven move, call site `agent_transfer_service.py:3120`). There is **no separate org-deletion cascade in this repo** — see finding below; the only two callers of this teardown are cross-tenant *transfer* flows, gated entirely on a boolean `org_changed` computed from a pre-batch tenancy snapshot (`agent_transfer_service.py:1454-1460`). When `org_changed` is `False` (same-org move), every step in the tuple is recorded `"skipped"` and none of it runs — teardown only fires on an actual organization boundary crossing, never on a same-org project/owner change.

Step-by-step, gated on `org_changed`:

1. **DCI corpus (agent_transfer_service.py:1481-1532):** `knowledge_vault_client.move_corpus(agent_id, old_org_id, target_org_id)` → POSTs `{base}/api/dci/internal/corpus/move` (`services/knowledge_vault_client.py:95-140`). This is a **copy to the destination org's GCS prefix**, not a delete of the source; verified via a `CorpusMoveResult.verified` flag before the agent's retrieval config is repointed. Best-effort/non-raising; on `not_configured` or unverified failure, the agent is stamped `kb_migration_pending` and keeps reading the old org's corpus. **CASCADED** (as a copy/repoint, not a source-side delete).
2. **Config blobs (`active_config.json`/`draft_config.json`) (agent_transfer_service.py:1534-1563):** patched in GCS; detach mode depends on which boundary crossed (org vs. project). Not a "store" per the inventory, but the mechanism that actually re-points/severs the knowledge and connector bindings referenced by `active_config.json`.
3. **`agent_deployments` doc (agent_transfer_service.py:1565-1596):** `organization_id`/`project_id` repointed.
4. **`agent_sessions` (agent_transfer_service.py:1598-1640):** batch-updates every `agent_sessions` doc with `agent_id == agent_id` to the new `organization_id`/`project_id` (no `org_changed` gate — this runs on every relocation, same-org or cross-org). **CASCADED** — but note this is a re-labeling of ownership fields, not a delete/archive; `agent_messages` docs are not touched directly here (their org binding is derived transitively via the parent session per the agent-runtime repo-note).
5. **Senders re-pointed (ungated) then, if `org_changed`, suspended** (agent_transfer_service.py:1642-1661, 1729-1739).
6. **`archive_usage_rollups`** (agent_transfer_service.py:1668-1687 → `services/agent_transfer_platform_ops.py:69`): copies `agents/{id}/usage/*`, `agents/{id}/analytics/*`, and the project/org usage rollups to sibling `_archive` paths, then deletes the canonical copy. Soft, recoverable.
7. **`archive_agent_memory`** (agent_transfer_service.py:1691-1705) → `workflow_runtime_client.archive_agent_memory(agent_id, old_org_id)` (`services/workflow_runtime_client.py:86-109`), which POSTs `{WORKFLOW_RUNTIME_URL}/api/internal/transfer/memory/archive`. **This confirms the store-inventory's cross-repo flow #5 exactly** — the call site exists, is named `/api/internal/transfer/memory/archive`, and fires only when `org_changed` is true. It's the platform's sole concrete mitigation for `workflow_agent_memory` lacking an `organization_id` field (per workflow-runtime's own repo-note). **CASCADED.**
8. **Billing repoint/reset, senders suspend, share-token revoke, per-agent membership revoke** (agent_transfer_service.py:1707-1766, delegating to `agent_transfer_platform_ops.py`) — all soft/status-flip operations, not delete.
9. **`migrate_api_keys`** (agent_transfer_service.py:1767-1776, ungated) — re-owns `api_keys` collection docs pinned to this agent (by `agent_id` or `metadata.scoped_agent_id`); keys are **not rotated**, just re-orged.
10. **Knowledge library metadata** (agent_transfer_service.py:1777-1805): if the corpus provably moved (step 1 verified), `repoint_knowledge_library` updates `knowledge_library` docs' org/project fields (`agent_transfer_platform_ops.py:821`); otherwise `detach_knowledge_library` soft-marks them `status: "detached_on_transfer"` (`agent_transfer_platform_ops.py:609-634`) — a cross-repo contract string that agent-design's listing and the MCP gateway both filter on.
11. **`detach_mcp_configs`** (agent_transfer_service.py:1806-1813 → `agent_transfer_platform_ops.py:654`): every `agents/{id}/mcp_configs/{server}` doc is flipped to disabled + `status: "detached_on_transfer"` (both `enabled` and `is_enabled` fields, for legacy/private convention parity), and the denormalized `agents/{id}.mcp_service` cache is flipped too so a re-publish can't re-hydrate the old org's MCP runtime URL. **CASCADED** for `agents/{id}/mcp_configs/*` (credentials are disabled/soft-detached, not deleted or rotated).
12. **Workflow ownership rewrite** (agent_transfer_service.py:1815-1859, `is_workflow` only): every `workflow_definitions` doc for the agent is re-pointed to the new org/project via `workflow_design_client.rewrite_workflow_ownership`.

**`agent_datastores` and `agent_learned_patterns` are absent from this entire cascade and from this repo.** Repo-wide grep for `agent_datastores` returns **zero matches** in any `.py` file (including tests). Repo-wide grep for `agent_learned_patterns`/`learned_patterns` returns matches only in `services/notification_recipients.py` (a notification-preference key `learned_patterns_weekly_digest`, confirmed unrelated to the Firestore collection by reading its context at line 396/841/1698) — **zero references to the actual `agent_learned_patterns` collection anywhere in this repo.** **NOT CASCADED**, confirmed by absence rather than inference.

### No org-deletion route/service exists in this repo

Grepped for `delete_organization` and any org-level hard-delete: `services/organization_service.py` defines only `archive_organization` (`:512`) / `restore_organization` (`:606`) and `delete_organization_whatsapp_config` (`:747`, an unrelated sub-resource). **There is no `delete_organization` function, route, or hard-delete path for an organization anywhere in this repo.** `routes/organization_routes.py:197` explicitly documents `archive_organization` as "Archive an organization (soft delete)."

`archive_organization`/`restore_organization` invoke their own, **entirely separate** cascade — `_cascade_archive_resources`/`_cascade_restore_resources` (`services/organization_service.py:803-949`) — which does nothing but batch-flip `projects.project_info.status` and `agents.lifecycle_state` to `"archived"`/`"active"`. **Critically, this org-archive cascade does NOT invoke any `_ORG_SCOPED_TEARDOWN_STEPS`** — no `archive_agent_memory`, no DCI corpus move, no `knowledge_library`/`mcp_configs` detach, no session reassignment. Archiving an organization in this platform is a pure status-flip on `projects`/`agents`; it does not touch `agent_datastores`, `agent_learned_patterns`, `workflow_agent_memory`, `knowledge_library`, the DCI corpus, or `agent_sessions`/`agent_messages` at all.

One deliberate exception inside that archive cascade: agents with `lifecycle_state == "provisional"` are explicitly skipped from the bulk archive (`organization_service.py:846-852`) and from the bulk restore (`organization_service.py:932-937`), with an explicit comment that provisional agents (vibe background-materialized drafts, hidden until a user opens them) must not be flipped to `"archived"` by a bulk org-archive, because the matching restore would then wrongly reveal them as `"active"`.

**Classification: VERIFIED CURRENT** for both cascades as coded. The absence of any `agent_datastores`/`agent_learned_patterns` call site, and the absence of any org-hard-delete route, are both confirmed-by-absence findings, not inferences.

---

## 2. `organization_api_keys` provisioning

Fully resolved. `services/api_key_service.py` documents two distinct systems up front (`:1-14`): `api_keys` (org-level runtime invocation tokens) vs. `organization_api_keys` (Sinch/dashboard integration auth — the collection knowledge-vault reads but does not write, per the store-inventory).

- **Creation:** `create_organization_api_key()` (`api_key_service.py:638-723`) generates a `org_live`-prefixed secret via `generate_api_key()`, stores only `hash_api_key(api_key)` (SHA-256, `:53`) plus metadata (`organization_id`, `user_id`, `name`, `permissions`, `status: "active"`, optional `expires_at`), and logs an activity event. The plaintext key is returned once in the response and never persisted.
- **HTTP route:** `POST /api/organization-api-keys` (`routes/api_key_routes.py:208-219`), gated by `verify_firebase_token` + `_verify_org_membership(user.user_id, request.organization_id)` — the caller must be a member of the target org, no admin-role requirement found at this specific route.
- **List:** `GET /api/organizations/{organization_id}/api-keys` (`routes/api_key_routes.py:222-231`), same org-membership gate; `key_hash` is stripped from every returned row (`api_key_service.py:773`).
- **Rotation/regeneration:** `POST /api/organizations/{organization_id}/api-keys/regenerate` (`routes/api_key_routes.py:234-243` → `api_key_service.regenerate_organization_api_key`). This is **manual, user-triggered only** — no scheduled/cron rotation job was found (grepped for `cron`/`scheduler` near API-key code, zero hits).
- **Revoke:** `DELETE /api/organization-api-keys/{key_id}` (`routes/api_key_routes.py:246-259`), which reads the key doc first to resolve its `organization_id` and re-checks membership against *that* org (not a caller-supplied org_id) before revoking — closes an IDOR that a naive re-use of the create route's pattern would have left open.
- **Expiry enforcement:** checked lazily, only at verification time — `verify_organization_api_key()` (`api_key_service.py:725-761`) compares `expires_at` against "now" on each use and returns `None` (auth failure) if expired. **No background job disables/deletes expired keys** — an expired key simply stops authenticating; it is not proactively revoked or purged.

**Classification: VERIFIED CURRENT.** Closes the store-inventory's open question — `olbrain-studio-backend` is confirmed as the sole writer of `organization_api_keys`, with self-service create/list/regenerate/revoke behind Firebase-token + org-membership checks, and no automated rotation or expiry-sweep job anywhere in this repo.

---

## 3. `organization_documents`

Fully resolved via `services/organization_documents_service.py` (module docstring, `:1-4`): "Organization-level document library — registry over the `organization_documents` Firestore collection. File bytes live in Firebase Storage (client-uploaded, resumable); this module only manages metadata and never touches bytes. No agent scope (that is phase 2 via `knowledge_library`)."

- **Schema written** (`register_document`, `:77-100`): `organization_id`, `filename`, `content_type`, `size_bytes`, `storage_path` (IDOR-pinned to require the `organizations/{org_id}/documents/` prefix, `:82-83`), `uploaded_by`, `status`, `tags`, `category`, timestamps. Later stamped with `dci_status`/`dci_source_id` by the ingest step.
- **Writer/reader:** this repo (`organization_documents_service.py`) is the sole owner. `list_documents`/`register_document`/`delete_document` are all gated by `_authorize_org()` → `is_org_member()` (any active org role qualifies; `:26-50`), which itself delegates to the canonical `services.org_roles.is_org_member` per an in-code "MERGE ADAPTER (2026-08-12)" note (`:30-44`).
- **Relationship to knowledge-vault's org corpus (confirming the store-inventory's hypothesis):** `register_and_ingest()` (`:116-147`) calls `kv.ingest_org_document(org_id, doc_id, storage_path, filename)` — i.e., `services/knowledge_vault_client.py`'s client for knowledge-vault's DCI ingest endpoint — immediately after the Firestore metadata row is committed, and stamps the resulting `dci_status`/`dci_source_id` back onto the `organization_documents` row. This is exactly the feed path the knowledge-vault repo-note inferred for its org-wide DCI corpus.
- **Deletion:** `delete_and_deindex()` (`:167-198`) hard-deletes the `organization_documents` row (`delete_document` does `ref.delete()`, `:112` — a genuine hard delete, not soft, unlike almost every other store surveyed in this workspace) and, if no other active row in the org still references the same `dci_source_id` (`_source_still_in_use`, `:150-164`), calls `kv.remove_org_source(org_id, source_id)` to de-index it from knowledge-vault. This is a real, working per-document DCI de-index path — best-effort (swallows errors, logs a warning) but present and invoked on every document delete, which is a narrower but real analog to the org-wide cascade the store-inventory asked about.

**Classification: VERIFIED CURRENT.** `organization_documents` is a Studio-backend-owned Firestore metadata registry over org-uploaded documents whose bytes live in Firebase Storage; it is the confirmed feed source for knowledge-vault's org-wide DCI corpus, with a genuine (not merely per-source-generic) per-document hard-delete + de-index path.

---

## 4. Provisional-agent list-view filtering

**Not excluded — confirmed by reading the only project-scoped agent-listing function in full.** `AgentService.list_agents()` (`services/agent_service.py:249-320`), reachable via `GET /api/agents?project_id=...` (`routes/agent_routes.py:76-99`, the dashboard's agent list endpoint), filters only on:
- `runtime` (optional query param, matched against `basic_info.runtime`), and
- `status` (optional query param, `Literal["published", "draft"]` only — `routes/agent_routes.py:82`, matched against `status.development_stage`).

There is **no reference to `lifecycle_state` anywhere in `list_agents()`** (verified by reading the full function body, `:249-320`) and no default filter applied when the caller passes neither param — every agent doc in the project is returned as-is. Since the route's `status` literal type doesn't even accept `"provisional"` as a value, a caller cannot filter provisional agents out via that param even if they wanted to; and the frontend's default (unfiltered) dashboard call would return provisional agents indiscriminately, dependent entirely on what `status.development_stage` value agent-engine happens to stamp on a provisional agent doc — which is outside this repo.

The one place `lifecycle_state == "provisional"` **is** explicitly checked in this repo is the org-archive/restore bulk cascade (`organization_service.py:846-852`, `:932-937`, see §1) — deliberately *excluded* from bulk archive/restore so provisional agents stay invisible — but that is a completely different code path from the project dashboard's `list_agents`.

`list_org_published_agents()` (`services/agent_service.py:323-369`, used by the org-internal agent store) incidentally excludes provisional (and all unpublished) agents, but only because it filters on `current_version` truthiness (a published-version marker), not because of any `lifecycle_state` check — a provisional agent that somehow acquired a `current_version` would not be excluded here either.

**Classification: VERIFIED CURRENT — and this resolves the store-inventory's open question in the negative.** Provisional agents (`lifecycle_state="provisional"`, written by agent-engine before user confirmation) are **not excluded** from the main project-scoped dashboard list endpoint in this repo. Whatever hides them from a user today (if anything does) is not enforced by `olbrain-studio-backend`'s list route — it would have to be frontend-side filtering, or the provisional agent simply lacking a `project_id` that the dashboard queries against (unverified from this repo; agent-engine's write path would need checking).

---

## 5. `agent_datastores` HTTP surface

**No route or reference of any kind exists in this repo.** Grepped for `agent_datastores` (zero matches, any file type) and `datastore` broadly (two matches total, both unrelated):
- `services/audit_query_service.py` — see note below.
- `tests/test_audit_routes.py` — same, test coverage of the audit-log query, not a datastore CRUD surface.

The one substantive hit, `services/audit_query_service.py:100-102`, is a comment inside BigQuery audit-log SQL-building code that names **`olbrain-agent-design`'s "datastore router"** as one of three known emitters that stamp `actor.tenant_id` on audit events but never `actor.principal_type`:

```python
# services/audit_query_service.py:99-106
if principal_type:
    # Three emitters predate this convention (billing-service's
    # activity_logger, this repo's own activity_service, agent-design's
    # datastore router): they stamp actor.tenant_id but never
    # actor.principal_type. ...
```

This is a **secondary, corroborating pointer** — it confirms that whoever built this audit-log code believed a "datastore router" exists (or existed) specifically in **`olbrain-agent-design`**, not in `olbrain-agent-runtime` (where the stale comment agent-runtime's own code carries points, per the task brief) and not in `olbrain-studio-backend` itself. It is not primary-source confirmation that such a router exists today, is reachable, or serves `agent_datastores` entries specifically — it is one engineer's comment about audit-log provenance, unverifiable further from this repo.

**Classification: OPEN QUESTION** (narrowed, not resolved) — confirmed **NOT CASCADED / NO ROUTE** in `olbrain-studio-backend` itself (zero references), and the "datastore router" pointer now names a single specific candidate repo (`olbrain-agent-design`) rather than "somewhere in the platform," which is a narrower unresolved question than before this pass.

---

## 6. Bonus: `org_connectors_service.py` / connector-credential org-scoping

`services/org_connectors_service.py` implements an org-scoped connector credential vault at `organizations/{org_id}/connector_credentials/{credential_id}` (module docstring, `:1-6`), reusing the private-MCP gateway's probe + KMS encryption. Every write/read is naturally path-scoped to the `org_id` argument (Firestore subcollection under that org's doc, `_vault_collection()`, `:46-51`), and secrets are KMS-encrypted at rest and masked (`_redact`/`_mask_auth_config`, `:35-43`) in every response.

At the API layer (`routes/org_connectors_routes.py:1-45`), **every endpoint is gated by a `verify_org_admin` dependency** (`:20-29`) that calls `services.org_roles.is_org_admin(user.user_id, organization_id)` against the **path** `organization_id` and 403s otherwise — a stricter check (org-admin role, not just membership) than `organization_documents`' or `organization_api_keys`' plain-membership gates. The router is also feature-flagged: registered only when `ORG_CONNECTORS_ENABLED=true` (module docstring, `:4`).

**Classification: VERIFIED CURRENT.** This repo enforces org-scoping for connector-credential access at its own API layer via an explicit org-admin authorization dependency bound to the path `organization_id`, independent of (and stricter than) whatever Firestore security rules `olbrain-studio` may or may not separately enforce.

---

## Deletion/Transfer Cascade Verdict

| Store (from six-repo store-inventory) | Verdict | Evidence |
|---|---|---|
| `agent_user_memory` | **NOT CASCADED** | No reference anywhere in this repo (grepped; zero matches). Not touched by transfer or org-archive cascades. |
| `agent_datastores` | **NOT CASCADED** | Zero matches repo-wide for `agent_datastores`; absent from `_ORG_SCOPED_TEARDOWN_STEPS` and from `relocate_agent()`'s full body. |
| `agent_learned_patterns` | **NOT CASCADED** | Zero matches for the actual collection repo-wide (the only `learned_patterns` hits are an unrelated notification-digest preference key). |
| `agent_sessions`/`agent_messages` | **CASCADED (transfer only, re-label not delete)** | `relocate_agent()` batch-updates every `agent_sessions` doc's `organization_id`/`project_id` (`agent_transfer_service.py:1598-1640`), ungated on `org_changed` — runs on every relocation. `agent_messages` not directly touched (its org binding is derived via the parent session per agent-runtime's repo-note). Not touched at all by org-archive. |
| `workflow_agent_memory` | **CASCADED (org-transfer only)** | `archive_agent_memory()` → `POST /api/internal/transfer/memory/archive` on workflow-runtime (`agent_transfer_service.py:1691-1705`, `workflow_runtime_client.py:86-109`), gated on `org_changed`. Confirms store-inventory cross-repo flow #5 exactly. NOT invoked by org-archive. |
| knowledge-vault DCI corpus | **CASCADED (org-transfer only, copy not delete)** | `knowledge_vault_client.move_corpus()` → `POST /api/dci/internal/corpus/move` (`agent_transfer_service.py:1481-1532`), gated on `org_changed`. This is a copy-and-repoint of the destination, not a delete of the source; matches knowledge-vault's own repo-note that relocation "never reclaims a stranded source prefix." Separately, `organization_documents` deletion does invoke a real per-document DCI de-index (`organization_documents_service.py:167-198` → `kv.remove_org_source`) — a different, narrower, working cascade unrelated to org-transfer. NOT invoked by org-archive. |
| `research_templates`/`research_runs` | **NOT CASCADED** — no reference found in the transfer cascade or org-archive cascade; out of scope of this repo's transfer flow entirely (agent-runtime's own repo-note documents a separate, unrelated direct-read coupling to `research_templates`, not a delete path). |
| `context_logs`/`context_facts`/`vibe_sessions` | **NOT CASCADED** — no reference found anywhere in `agent_transfer_service.py`, `agent_transfer_platform_ops.py`, or `organization_service.py`'s archive cascade. |
| `knowledge_library` (Firestore metadata) | **CASCADED (org-transfer only)** | `repoint_knowledge_library`/`detach_knowledge_library` (`agent_transfer_service.py:1777-1805` → `agent_transfer_platform_ops.py:609-634`, `:821`), gated on `org_changed` and on whether the DCI corpus copy verified. NOT invoked by org-archive. |
| `agents/{id}/mcp_configs/*` | **CASCADED (org-transfer only, disable not delete)** | `detach_mcp_configs()` (`agent_transfer_service.py:1806-1813` → `agent_transfer_platform_ops.py:654-671`), gated on `org_changed`; soft-disables and status-flips, servers left in place "for forensic value." NOT invoked by org-archive. |
| `organization_documents` | **CASCADED (per-document delete, not org-level)** | `delete_and_deindex()` hard-deletes the row and best-effort de-indexes the DCI source if unreferenced (`organization_documents_service.py:167-198`). No org-level bulk delete of this collection was found. |

**Cross-cutting finding not in the original inventory:** organization-level "deletion" in this platform is `archive_organization`/`restore_organization` (soft, status-flip only) — **there is no hard org-delete anywhere in this repo** — and that org-level cascade is *entirely disjoint* from the nine-step `_ORG_SCOPED_TEARDOWN_STEPS` tuple, which only fires on a per-agent cross-org **transfer**, never on an org archive/restore. An organization being archived does not trigger any of the memory/knowledge/MCP teardown steps that an individual agent's cross-org transfer does.

---

## Cross-repo resolution

This pass closes the following open questions from `investigation/store-inventory.md` and other repo-notes:

- **Store-inventory §9 / §"Open Questions Requiring a Repository Not Present in This Workspace":**
  - `organization_api_keys` provisioning/rotation — **RESOLVED**: `olbrain-studio-backend` is the sole writer (`services/api_key_service.py`); self-service create/list/regenerate/revoke, no cron rotation or expiry-sweep.
  - `organization_documents` ownership/contents — **RESOLVED**: `olbrain-studio-backend`'s `organization_documents_service.py`; Firestore metadata registry over Firebase-Storage-hosted org documents, confirmed feed into knowledge-vault's DCI ingest via `kv.ingest_org_document`, with a real per-document hard-delete + de-index path.
  - Org-deletion cascade invoking agent-runtime's `agent_datastores`/`agent_learned_patterns` deletion — **RESOLVED as NOT CASCADED**, and further: no org-deletion capability exists in this repo at all (only soft archive/restore, itself disjoint from the per-agent transfer teardown).
  - workflow-runtime's `/api/internal/transfer/memory/archive` call site — **CONFIRMED** to exist exactly as workflow-runtime's own docstring claimed, gated on cross-org transfer only (`services/agent_transfer_service.py:1691-1705`, `services/workflow_runtime_client.py:86-109`).
  - knowledge-vault's per-source delete endpoints being invoked by a caller — **PARTIALLY RESOLVED**: not invoked by the org-transfer cascade (which does a corpus *move*, not a delete), but **is** invoked by `organization_documents_service.py`'s per-document delete path (`kv.remove_org_source`), which is a real, working, narrower cascade unrelated to org/agent transfer.
  - Whether an HTTP route for `agent_datastores` entries exists here — **RESOLVED as NO** (zero references repo-wide); the "stale comment" lead is narrowed to a named candidate, `olbrain-agent-design`'s "datastore router," per `services/audit_query_service.py:100-102`.
  - Provisional-agent list-view exclusion — **RESOLVED as NOT EXCLUDED** in the main project-dashboard `list_agents()` endpoint; provisional agents ARE deliberately excluded from the (unrelated) org-archive/restore bulk cascade.
  - `WorkflowTransferService`'s full transfer cascade — **RESOLVED**: this is `agent_transfer_service.py::relocate_agent()`, fully enumerated in §1 above.

- **This narrows (does not fully resolve) `olbrain-agent-design`** as the specific repo to check next for: (a) any real "datastore router" HTTP surface for `agent_datastores`, and (b) whether provisional-agent filtering happens anywhere in agent-design's own agent-listing code (since agent-engine's provisional writes and agent-design historically owned agent CRUD before the "Phase 5b" split documented in `agent_transfer_service.py`'s own module docstring).

---

## Open Questions

- **`olbrain-agent-design`** is now the specifically-named (not just presumed) location for a possible `agent_datastores` HTTP router, per the audit-log comment in `services/audit_query_service.py:100-102`. This cannot be confirmed further without that repo.
- **Whether a provisional agent even has a `project_id` set** such that it would appear in a `GET /api/agents?project_id=...` call in the first place — this repo's `list_agents()` does not special-case it either way, but if agent-engine's provisional write omits `project_id` entirely, the dashboard's per-project query would incidentally never surface it. This is an agent-engine-side question, not resolvable from this repo (agent-engine's own repo-note states provisional agents ARE org-bound at creation, but is silent on `project_id`).
- **Whether the frontend applies its own provisional-agent filter** on top of the unfiltered `list_agents()` response — out of scope for a backend-only repo, genuinely unknowable from source in this workspace.
- **`api_keys` (org-level runtime invocation tokens, the OTHER collection in `api_key_service.py`, distinct from `organization_api_keys`)** was not in the six-repo store-inventory and was out of this task's scope; flagging its existence in case a future pass needs it (`services/api_key_service.py:203-389` for its CRUD surface).
- **Whether any process other than `archive_organization`/`restore_organization` ever hard-deletes an organization:** checked — `ls scripts/` has no `delete_org*`/`hard_delete*` tool; the closest related script is `scripts/merge_organizations.py` (an org-**merge** tool, a different operation not investigated further in this pass — worth a dedicated read if org-merge semantics ever matter for the reconciliation phase, since a merge would presumably need to move the same stores a transfer does, but under a different, unaudited code path). No hard-delete-organization capability was found anywhere in this repo.
