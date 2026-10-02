# Repo Notes: olbrain-agent-design

- **Repo**: `olbrain-agent-design`
- **HEAD reviewed**: `bbc85c8e87d85432a89e9ea3319e40a8c4b46aea` (confirmed via `git rev-parse HEAD`; matches origin/main per task brief)
- **Review date**: 2026-09-19
- **Scope note**: Targeted read only, per task brief — `app/services/config_generator_service.py`, MCP write path, `agent_datastores` HTTP surface, and the datastore/blueprint-store question. Not a full-repo survey (~296 source files). All claims below are grep-then-read, file:line cited.

---

## 1. `active_config.json` / `draft_config.json` — publish flow, cache invalidation, org-resolution precedence

### 1a. GCS path

Confirmed **matches** agent-runtime's read path exactly.

- `app/services/config_storage_service.py:29`: `self.bucket_name = f"{project_id}-deployment-configs"`.
- `app/services/config_storage_service.py:347`: `blob_path = f"configs/{agent_id}/active_config.json"` (written in `upload_active_config`, the path used by the current versioning/publish flow).
- `app/services/config_storage_service.py:96` / `:253`: the older `upload_config`/`update_active_config` paths write the identical `configs/{agent_id}/active_config.json` destination.
- `app/services/config_storage_service.py:295`: `draft_config.json` sibling path, same `configs/{agent_id}/` prefix.
- Multi-tenant fan-out: `upload_active_config` (`config_storage_service.py:307-400`) resolves publish targets via `app/services/tenant_buckets.py::resolve_publish_targets` and writes the **identical relative path** (`configs/{agent_id}/active_config.json`) into each dedicated tenant's `{project}-deployment-configs` bucket, not just the shared one — this is a detail agent-runtime's single-project read view could not see.

**Classification: VERIFIED CURRENT.**

### 1b. Cache-invalidation signal on publish

Searched the entire write path (`draft_config_service.py`, `config_storage_service.py`, `agent_service.py`'s publish/`activate_version` flow, `tenant_buckets.py`) for any of: Pub/Sub, a version-suffixed object path, an ETag/generation check, a cache-bust query parameter, a webhook/notify call to agent-runtime.

- `grep -rniE "pubsub|pub/sub"` across `app/` → **zero matches**.
- `grep -rni "invalidat"` across `app/` → one match, `tenant_buckets.py:10`, and it concerns a *different* cache (this repo's own in-process 5-minute org→bucket routing cache, not anything served to agent-runtime).
- `grep -rni "etag"` / `"cache_bust"` / `"cache_version"` across `app/` → **zero matches**.
- `app/services/draft_config_service.py::refresh_active_config` (lines 132-227) does: read `agents/{id}.current_version` (176-179) → `generator.generate_config(...)` (186-191) → `storage.upload_active_config(...)` (192) → write a **separate bookkeeping doc** `agent_config_actives/{agent_id}` (194-221) containing a `content_hash` (computed by `_content_hash()`, lines 46-49) — but this hash is written only to Firestore for this repo's own audit/UI purposes; it is never appended to the GCS object path, never set as a GCS custom-metadata/generation check, and never published anywhere agent-runtime could observe it.
- `config_storage_service.py::upload_active_config` (307-400) does a plain `bucket.blob(blob_path).upload_from_string(...)` (373-375) — a raw overwrite of the same object path, no `if_generation_match`, no versioned object name.
- `app/services/agent_service.py::activate_version` (1597-1704, the Settings-tab rollback/adopt-latest flow) and the main `publish_agent` flow (per earlier grep: `agent_service.py:1401-1479`) both call `refresh_active_config` the same way — no additional signal is emitted from either caller.

**Finding: CONFIRMED from the writer's side.** There is no cache-invalidation mechanism anywhere in this repo's publish/activate/rollback flow. Agent-runtime's finding ("nothing busts this cache when a version is published") is not a gap in agent-runtime's own visibility — the writer genuinely never emits an invalidation signal of any kind (no Pub/Sub, no version-suffixed path, no ETag). A reader inside agent-runtime's 5-minute TTL will serve a stale config after a publish, exactly as agent-runtime's own docstring warns, and this repo does nothing to prevent it.

**Classification: VERIFIED CURRENT** (as a confirmed absence, not an open question).

### 1c. Org-resolution precedence for `resources.knowledge_base.gcs_prefix`

Found the exact resolver, `app/services/config_generator_service.py:849-861`:

```python
@staticmethod
def _resolve_org_id(agent_data: Dict[str, Any]) -> Optional[str]:
    """3-claim precedence — matches knowledge-vault middleware.

    ``tenant_id`` is canonical (newer agents); ``organization_id`` is
    the legacy backend field; ``primaryOrganization`` is what older
    Studio-issued Firebase tokens carry. Try each in order.
    """
    for key in ('tenant_id', 'organization_id', 'primaryOrganization'):
        v = agent_data.get(key)
        if v:
            return v
    return None
```

This is called at `config_generator_service.py:808` from `_get_knowledge_base()` (779-847), specifically to build `gcs_prefix = f'gs://{bucket}/{org_id}/{agent_id}'` (829) that lands in `resources.knowledge_base.gcs_prefix` in the assembled config (per the docstring at 816-818: "DCI fields are emitted FLAT... the runtime reads them as `kb_config.get('gcs_prefix')`").

This is a **narrower — not differently-ordered — subset** of knowledge-vault's own 5-field `resolve_agent_org_id` (`tenant_id > organization_id > primaryOrganization > org_id > owner_id`, per `olbrain-knowledge-vault`'s `services/dci/tenancy.py:238-244`): the first three fields are in the **identical order**; this repo simply never falls through to `org_id` or `owner_id`. Practical consequence, precisely stated: for an agent whose org is resolvable ONLY via `org_id` or `owner_id` (not `tenant_id`/`organization_id`/`primaryOrganization`), knowledge-vault's own ingestion-time `_reject_unresolvable_org` guard (per knowledge-vault's repo-note) could still succeed and place a corpus under that org — while THIS repo's `_get_knowledge_base()` would compute `org_id = None`, return `gcs_prefix: None`, and disable the KB entirely for that agent (829-838). It is a **fail-to-resolve-at-all** risk for this repo's compiled config, not a **resolve-to-a-different-org** risk — the mismatch is in coverage, not in disagreement, given the shared field order for the first three keys.

Note: this repo has a **second, unrelated, single-field org resolver** used for a different purpose — skill-binding authorization, not knowledge-base wiring: `app/services/skill_binding_service.py:61-74`, `_resolve_agent_org()`, reads only `agents/{id}.organization_id` and fails closed (`None`) on any error or missing field. `config_generator_service.py:1124-1126` calls this second resolver (via `from app.services.skill_binding_service import _resolve_agent_org`) when building the **skills** section of the config — confirming the task brief's caution that agent-ownership-style resolution and knowledge-base resolution are genuinely different code paths in this repo, not one precedence used everywhere.

**Classification: VERIFIED CURRENT.** The precedence-mismatch risk knowledge-vault's comments flagged is now source-confirmed as real, and its exact shape (subset/coverage-gap, not order-disagreement) is now precisely characterized.

---

## 2. `agents/{id}/mcp_configs/*` write path

Two independent write call sites confirmed, both in `app/services/mcp_service.py`, both invoked from `app/routers/mcp.py` (not individually re-traced — this repo's route registration for `mcp.router` was not the priority item; the service-layer write is what matters for the field-shape question).

- **Write site 1** — `mcp_service.py:522-558` (generic/KMS-credential MCP config save): writes `agents/{agent_id}/mcp_configs/{server_name}` with `{server_name, tool_id, config (non-secret only — secrets pushed to KMS, comment at 534-536), enabled, is_private, agent_id, created_by, created_at, updated_at}` (531-543). Existing `tool_access`/`order_email_verification` siblings are preserved across a re-save (547-556).
- **Write site 2** — `mcp_service.py:1577-1630` (OAuth/Shopify-style MCP config save): writes the same subcollection with `{id, server_id, server_name, config (OAuth-field-filtered or non-secret), enabled, oauth_enabled, created_at, updated_at, mcp_runtime_url}` (1606-1616). `enabled` defaults from `request.enable_immediately` (1611).

**Enablement spelling — resolved.** `grep -rni "is_enabled" app/` returns **zero** hits for MCP configs (the only two `is_enabled` matches in the whole repo are `billing_client.py:28,44`'s unrelated `_is_enabled()` billing flag). Both MCP write sites, and every other MCP-config read/query in this file (e.g. `mcp_service.py:79`, `:1316`: `.where('enabled', '==', True)`) use exclusively **`enabled`**, never `is_enabled`. This repo is not the source of the `is_enabled` spelling agent-runtime found in its own read-side fallback (`is_enabled or enabled`, `runtime_resolver.py:319`) — that alternate spelling's origin remains unaccounted for by either repo.

**`pool_ref` / `cred_source` — resolved, dead on the write side too.** `grep -rn "pool_ref"` and `grep -rn "cred_source"` across the entire repository (`.py`, all directories) return **zero matches**, both terms. Combined with agent-runtime's own finding that no organization ever held a pool and no `mcp_config` ever carried `pool_ref` on the read side, this confirms **`pool_ref` is fully dead code across both repos investigated so far** — not written here, not meaningfully read there. No candidate write site for it exists in this repo.

**Classification: VERIFIED CURRENT** (write shape and `enabled` spelling); **CONTRADICTED BY SOURCE** for any claim that `pool_ref`/`cred_source` are live fields anywhere in this repo — they are absent, full stop.

---

## 2b. `agent_datastores` HTTP surface — `routers/datastore.py`

**It exists, in this repo, exactly as named.** `app/routers/datastore.py` (355 lines) is registered in `app/main.py:191`: `app.include_router(datastore.router, tags=["agent-datastore"])`, mounted at prefix `/api/v1/datastore` (`routers/datastore.py:73`).

This is the human/operator-facing surface for the same collection agent-runtime writes to. Confirmed identical Firestore path via `app/services/datastore_service.py:57-67`:
```python
def _tables(agent_id: str):
    return (
        get_firestore_client()
        .collection("agent_datastores")
        .document(agent_id)
        .collection("tables")
    )
def _entries(agent_id, table_id):
    return _tables(agent_id).document(table_id).collection("entries")
```
**Correction (coordinator re-verification, 2026-09-19):** this repo's own source builds a **flat top-level** `agent_datastores/{agent_id}/tables/{table_id}/entries/{entry_id}` path — `.collection("agent_datastores").document(agent_id).collection("tables")`, not a subcollection nested under `agents/{id}`. The original draft of this section transposed the call chain; directly re-read against `app/services/datastore_service.py:57-67` at HEAD `bbc85c8e`, **the path is identical to agent-runtime's** (`services/extract_entry_writer.py:62`, `core/tools/datastore_executor.py:282`, both `db.collection("agent_datastores").document(agent_id)...`). This closes Open Question 1 below in the "same path, no discrepancy" direction.

Routes exposed (`routers/datastore.py`):
- `GET /agents/{agent_id}/tables` — list tables, with a `declared_unavailable` honesty flag (143-166).
- `GET /agents/{agent_id}/tables/{table_id}/entries` — paged entries, newest first, optional `session_id` filter (169-184).
- `GET /agents/{agent_id}/tables/{table_id}/entries.csv` — full CSV export (187-203).
- `DELETE /agents/{agent_id}/tables/{table_id}/entries/{entry_id}` — **hard delete**, "the only irreversible write in this feature" (206-223).
- `POST /agents/{agent_id}/tables/{table_id}/entries` — operator-authored create (224-253).
- `PATCH /agents/{agent_id}/tables/{table_id}/entries/{entry_id}` — correct one row, never re-keys/re-stamps provenance (256-289).
- `POST /agents/{agent_id}/tables/{table_id}/entries:import` — dry-run/commit CSV import, chunked, partial-failure-safe (292-355).

Auth: Firebase-token (`verify_firebase_token`) + a permission ladder (`check_view_permission` for reads, `check_edit_permission` for writes) gated on **agent ownership/org-membership/scoped API key**, per the module docstring (lines 9-16) — this is an app-layer, agent/org-scoped gate, not the "server-only" characterization agent-runtime used for its own (writer-only) view.

Every write route emits an `AuditEvent` via `olbrain_shared.agent.audit` (module docstring 18-22, e.g. `_emit_audit` calls at 218-222, 248-252, 284-288).

**This directly resolves agent-runtime's stale-comment question and its open GDPR-route question**: the comment in agent-runtime's `routers/agent_memory.py` was not stale — it was pointing (without naming the repo) at a route that genuinely exists, just in `olbrain-agent-design`, not in `olbrain-agent-runtime`. And the DELETE route here **is** the GDPR/operator-erasure surface agent-runtime found missing in its own repo.

**Classification: VERIFIED CURRENT.**

**Data-shape confirmation (org binding).** Read `datastore_service.py::create_entry` (356-451) in full: `organization_id` is written **only on the parent table doc** (`batch.set(_tables(agent_id).document(table_id), {..., "organization_id": organization_id, ...})`, lines 435-442) — the entry document itself (`entry` dict, 411-416, plus 423-428) carries `entry_id, values, updated_by, updated_at`, and conditionally `source, created_by, created_at, user_key_kind` — **no `organization_id` field**. This is a **third independent writer** into the same collection (alongside agent-runtime's extract-path and tool-path writers) and it **reproduces the identical org-binding pattern**: table carries org, entry does not. Confirms store-inventory's Security Finding B as holding across a third, independently-authored write path in a second repo.

---

## 3. "Datastores" — this repo's own vocabulary vs. agent-runtime's `agent_datastores`

**Resolved: they are the same collection, not two different concepts.** `datastore_service.py:57-67` (quoted above) operates on the literal Firestore path containing the segment `"agent_datastores"` — this is a live production-data CRUD surface over the same rows agent-runtime's extract-mode and tool-mode writers populate, not a design-time schema/table-definition abstraction. The repo-and-soul-map's attribution of "datastores" ownership to this service is **confirmed** in the sense that this repo owns the only HTTP surface for it; it is **not** a separate blueprint/schema store as the task brief raised as a possibility to check.

Supporting evidence this is treated as live production data, not a design-time artifact: `table_context()` (referenced at `datastore_service.py:374`, `479`) reads back "fill" mode (`extract` vs tool-authored) and column definitions per-table, gating validation and person-vs-session keying (378-391) — this is runtime-data-shape introspection, not a separate design catalog.

**Classification: VERIFIED CURRENT** — one collection, two repos (agent-runtime writes/reads it inline during conversations; agent-design exposes it over HTTP for operators), no separate "blueprint store" concept found for datastores specifically. (Whether a genuinely separate design-time "blueprint store" exists in this repo for *other* resource types — tools/MCP/connector/skill bindings — was outside this pass's scope; `app/services/brain_service.py`, `capability_material.py`, and `capability_assessment_service.py` were seen in file listings but not read.)

---

## Cross-repo resolution

| Claim from agent-runtime / knowledge-vault | Verdict from this repo (writer side) |
|---|---|
| "5-minute cache, nothing invalidates it on publish" (agent-runtime, `lightweight_processor.py:460-463`) | **CONFIRMED.** No Pub/Sub, no ETag/generation check, no version-suffixed path, no notify call anywhere in this repo's publish/activate/rollback flow (`draft_config_service.py`, `config_storage_service.py`, `agent_service.py`). The writer overwrites the same `configs/{agent_id}/active_config.json` object with no signal to readers. |
| Org-resolution-precedence mismatch flagged by knowledge-vault (3-field vs. 5-field) | **CONFIRMED, and precisely characterized.** This repo's `config_generator_service.py:849-861` uses `tenant_id > organization_id > primaryOrganization` — the identical first three of knowledge-vault's 5-field chain, then stops. It is a **coverage gap** (agents resolvable only via `org_id`/`owner_id` get `gcs_prefix: None` here), not a **different-order** mismatch. |
| MCP `pool_ref` / enablement-spelling findings from agent-runtime | **`pool_ref`/`cred_source`: CONFIRMED dead** — zero occurrences anywhere in this repo (write side), consistent with agent-runtime's read-side dead-code finding. **Enablement spelling: this repo writes only `enabled`**, never `is_enabled`, for MCP configs — it is not the source of the `is_enabled` variant agent-runtime found in its own fallback read (`is_enabled or enabled`); that variant's origin is still unaccounted for. |
| `agent_datastores` HTTP-route question (agent-runtime's "stale comment" naming `routers/datastore.py`) | **CONFIRMED — the route exists, here.** `app/routers/datastore.py`, mounted at `/api/v1/datastore` (`main.py:191`), full CRUD + CSV export + audit-logged writes over the same collection. The agent-runtime comment was not stale; it referred to a route in this repo without naming it. This also resolves agent-runtime's separate "no GDPR/operator route found for `agent_datastores`" open question — the DELETE route here fills that gap. |

---

## Open Questions

1. ~~Firestore path-shape discrepancy for `agent_datastores`.~~ **RESOLVED (coordinator re-verification, 2026-09-19): no discrepancy.** Both `app/services/datastore_service.py:57-67` (this repo) and agent-runtime's `services/extract_entry_writer.py:62` / `core/tools/datastore_executor.py:282` build the identical flat top-level path `agent_datastores/{agent_id}/tables/{table_id}/entries/{entry_id}`. The original draft of §2b's code excerpt contained a transposition error, now corrected in that section.
2. Whether `app/routers/mcp.py`'s own auth/permission gating on the two write endpoints identified in §2 matches the org/agent-scoping rigor seen on `routers/datastore.py` — not traced in this pass (only the service-layer Firestore write shape was prioritized per the task brief).
3. The origin of the `is_enabled` spelling agent-runtime found in its MCP read-side fallback (`core/mcp/runtime_resolver.py:319`) remains unexplained — not written anywhere in this repo. Candidate: a third repo, or truly legacy/dead data from a pre-this-repo write path never removed from Firestore documents still in production.
4. Whether a genuinely separate "blueprint store" (design-time schema, distinct from live `agent_datastores` rows) exists elsewhere in this repo for tools/MCP/connector/skill bindings, as the repo-and-soul-map's broader "datastores, blueprint store" phrasing might imply — `brain_service.py`, `capability_material.py`, `capability_assessment_service.py` were not read in this pass.
5. `app/routers/mcp.py` itself (the router wiring for the two `mcp_service.py` write sites) was not read — only the service-layer write calls were traced, per the task's "trace data paths, don't read the whole repo" instruction.
