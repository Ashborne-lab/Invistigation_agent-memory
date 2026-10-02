# olbrain-shared — Repository Notes

- Package: `olbrain_shared` (PyPI, release **2.47.0**)
- Repo: `olbrain-shared`, local path `E:\OLBrain-Architecture-Research\repos\olbrain-shared`
- HEAD verified: `a837b957c566178c0627bd567a09139c3acd3873` (short `a837b95`), 2026-09-19 11:20:02 +0530 — matches `origin/main` per task briefing; working tree clean, read-only pass.
- Review date: 2026-09-19
- Method: targeted grep for the exact functions/classes named in five other repos' open questions, then full reads of the resulting files. Not a full-package read (566 files); this is a closure pass against specific named gaps.

---

## 1. `person_hash()` — is `agent_datastores`' entry-id hash salted?

**Location**: `src/olbrain_shared/agent/datastore/columns.py:35-43`, re-exported at `src/olbrain_shared/agent/datastore/__init__.py:8,18`.

```python
def person_hash(user_key: str) -> str:
    """Deterministic entry id for a person-keyed (fill="extract") row.

    Hashed so a raw phone or email never appears in a document path;
    normalised so one person is one row. The digest half of
    agent_memory_service.memory_doc_id — the agent id is dropped because the
    entry's path already carries it.
    """
    return hashlib.sha256(user_key.strip().lower().encode("utf-8")).hexdigest()[:32]
```

**Finding**: **UNSALTED.** No salt, pepper, HMAC key, or any per-org/per-agent secret is mixed into the hash input anywhere in this function or the surrounding module. The input is exactly `user_key.strip().lower()` — identical normalization to agent-runtime's own `memory_doc_id()`. The docstring is explicit and self-referential: *"The digest half of `agent_memory_service.memory_doc_id`"* — this is not a coincidentally-similar independent implementation, it is the **same digest construction**, deliberately factored out into the shared package specifically so the two entry-id schemes (`agent_user_memory` doc-id half, `agent_datastores` entry-id) stay byte-identical for the same normalized key. Checked the full module (`columns.py`, 155 lines) and its sibling `__init__.py` (21 lines, the entire public surface of the `agent.datastore` package) for any `hmac`, `secrets`, `SECRET_KEY`, `pepper`, or salt-like constant/parameter — none exists. The only imports in `columns.py` are `hashlib`, `dataclasses`, `datetime`, `typing` — no keying/secrets module of any kind.

**Open question closed** (`olbrain-agent-runtime.md`, §3 and Open Question 1, and cross-cutting `store-inventory.md` line 126): *"Whether `olbrain_shared.agent.datastore.person_hash()` (used for `agent_datastores` entry ids) is salted — requires the `olbrain-shared` package/repo source."*
**Answer: CONFIRMED — unsalted, same bare `sha256(normalized_key)[:32]` pattern as agent-runtime's own `memory_doc_id()` hash for `agent_user_memory`.** The two hashes are not merely "the same pattern" by coincidence; `person_hash()`'s own docstring states it is deliberately the same digest so the platform's two person-keying schemes converge. Practical consequence unchanged from what the senior review already flagged for `agent_user_memory`: any known/guessable phone number, email, or other `user_key` can be hashed offline (no rate limit, no secret needed) and matched directly against a leaked or enumerated `agent_datastores` entry id — there is no cryptographic barrier beyond the SHA-256 digest itself.

**`MAX_PER_TABLE`** (task item 5): `= 5000` (`columns.py:20`), re-exported unchanged. It caps the number of **rows per table** (i.e., a hard ceiling on `agent_datastores/{agent_id}/tables/{table_id}/entries/*`), not per-session or per-person. No `MAX_PER_SESSION` constant exists in this package — that constant is agent-runtime's own (`core/tools/datastore_executor.py`, per that repo's notes), confirming `olbrain-shared` supplies only the table-wide cap; the session-scoped cap is a runtime-local addition layered on top.

**No entry Pydantic model exists in `olbrain_shared.agent.datastore`.** The entire public surface of this subpackage (`__init__.py:2-20`) is: `MAX_PER_TABLE`, `MAX_VALUE_CHARS`, `ColumnProblem` (a plain frozen dataclass describing a *validation failure*, not a stored entry), `coerce`, `is_blank`, `person_hash`, `validate`. There is no `class Entry`/`class DatastoreEntry`/etc. anywhere in this module — `agent_datastores` entries are plain dicts assembled ad hoc by each caller (agent-runtime's `extract_entry_writer.py` and `datastore_executor.py`, per that repo's notes), not a shared typed model. Because no such model exists here, there is nothing in this package to check for an `organization_id` field — the absence confirmed in `olbrain-agent-runtime.md` §2 (both writers omit it from the entry payload) is not contradicted or overridden by anything in `olbrain_shared`; the schema is caller-defined, not shared-package-defined.

---

## 2. `workflow.firestore.service.get_workflow()` — Firestore-doc-vs-Storage-body split

**Location**: `src/olbrain_shared/workflow/firestore/service.py:160-223` (plus supporting helpers `_split_body` at `:88-102`, `_resolve_storage_path` at `:147-157`, and collection constants at `:22-45`).

**Collections/constants confirmed by literal string** (`service.py:22-45`): `WORKFLOW_DEFINITIONS = "workflow_definitions"`, `WORKFLOW_VERSIONS_SUBCOLLECTION = "versions"`, `WORKFLOW_RUNS = "workflow_runs"`, `WORKFLOW_ITEMS = "workflow_items"`, `WORKFLOW_TEST_SESSIONS = "workflow_test_sessions"`, `STEP_OUTPUTS = "step_outputs"` (flat root collection, per a code comment citing a design doc). `_BODY_FIELDS = ("steps", "edges", "trigger", "summary")` (`:45`) — these are the fields that move to Storage.

**The split, confirmed directly**:
- `create_workflow()` (`:105-144`) splits the incoming payload via `_split_body()` into `body` (the four `_BODY_FIELDS`) and `metadata` (everything else). If there's a body, it's written first to Storage (`workflow_versions.save_draft_body(workflow_id, body, app=app)`, `:130`), and only the **path string** (`draft_storage_path`) plus a `draft_dirty=True` flag land on the Firestore doc. `trigger` is additionally **mirrored** onto the Firestore metadata doc (`:137-138`) "so list endpoints and legacy readers... keep working" even though it's also in the Storage body — Storage is authoritative, Firestore's copy is a convenience mirror.
- `get_workflow(workflow_id, *, variant="draft", app=None)` (`:160-223`) is the single read chokepoint:
  1. Reads the Firestore metadata doc (`:188-193`).
  2. `_resolve_storage_path(metadata, workflow_id, variant)` (`:147-157`) picks which Storage blob to hydrate: `variant="draft"` → `metadata["draft_storage_path"]`; `variant="published"` → `metadata["current_version_storage_path"]`; `variant=<int>` → `workflow_versions.version_path(workflow_id, variant)` (a deterministic path for a specific historical version).
  3. **Strict published semantics** (`:197-203`): if `variant="published"` and there's no storage path **and** no legacy inline `steps` on the metadata doc, returns `None` — "no published version, can't run" rather than silently executing an empty workflow.
  4. If a storage path was resolved, `workflow_versions.load_body(storage_path, app=app)` hydrates the blob (`:206`); **Storage wins** for `steps`/`edges`/`summary`/`trigger` when present (`:210-215`) — these overwrite whatever was on the Firestore metadata dict.
  5. If a storage path was set but the blob load comes back empty **and** there's no legacy inline `steps` fallback, returns `None` even for int-pinned historical versions (`:216-221`) — "a stale or bogus version number can't silently execute as an empty workflow."
  6. Returns `WorkflowDefinition(**metadata)` — the merged dict (Firestore metadata + hydrated Storage body fields where present).
- **Legacy inline-JSON fallback, confirmed exactly as workflow-runtime's own code comment claimed**: `get_workflow`'s docstring states plainly (`:183-185`): *"Falls back to the legacy inline-JSON shape when no Storage path is present (unmigrated workflows). That fallback is expected to go away once the one-time migration script has run in prod."* Mechanically this fallback is simply "if `storage_path` is falsy, skip the Storage hydration step entirely and return whatever `steps`/`edges`/`trigger`/`summary` are still sitting inline on the Firestore metadata dict from before the v0.6.0 body-to-Storage migration" (comment at `:42-44`: *"Body fields that move to Storage in v0.6.0."*).

**Open questions closed**:
- `olbrain-workflow-runtime.md` Open Question 2 (*"What does `olbrain_shared.workflow.firestore.service.get_workflow()` actually do for the Firestore-doc-vs-Storage-body split on `workflow_definitions`?"*) — **CONFIRMED**, mechanics documented above with line citations. It is exactly the "Firestore-metadata-doc + Storage-body-blob, Storage wins when present, legacy inline fallback when no storage pointer exists" shape that repo's own trigger-routing comment ("the shared service falls back to the legacy inline-JSON shape when neither storage pointer is set") predicted, and it is a **direct structural analog** of the conversational side's `conversational_agents/{id}/draft.json` pattern (soul map G14) — same design, different domain.
- `store-inventory.md` line 67's "Storage-body split mechanics itself is an OPEN QUESTION" — **CONFIRMED / CLOSED**, same evidence.

---

## 3. `AgentMemory` / `ExceptionPattern` / `LearnedOverride` — does the model declare `organization_id`?

**Location**: `src/olbrain_shared/workflow/models/agent_memory.py` (71 lines, read in full).

```python
class AgentMemory(BaseModel):
    agent_id: str
    exception_patterns: list[ExceptionPattern] = Field(default_factory=list)
    learned_overrides: list[LearnedOverride] = Field(default_factory=list)
    updated_at: Optional[str] = None
```

`ExceptionPattern` (`:19-34`) fields: `pattern_id, step_id, step_type, trigger_summary, tags, what_failed, what_human_did, resolution, resolution_data, original_data, learned_at, learned_from_exception_id, learned_from_run_id, match_count, last_matched_at`. `LearnedOverride` (`:37-63`) fields: `override_id, workflow_id, step_id, field, selector, correction, status, confidence, evidence_exception_ids, evidence_run_ids, promoted_at, approved_by, approved_at, applied_count, last_applied_at, contradiction_count, retired_at, retired_reason`.

**Finding**: **No `organization_id` (or `org_id`) field exists anywhere on `AgentMemory`, `ExceptionPattern`, or `LearnedOverride`** — not optional, not required, not present under any name. The module docstring (`:1-11`) confirms the doc is keyed purely `workflow_agent_memory/{agent_id}` — no org segment in the path either. `LearnedOverride.workflow_id` is present (to scope which workflow an override applies to) but that is a workflow reference, not an organization/tenant reference.

**Open question closed** (`olbrain-workflow-runtime.md` Open Question 3, and `store-inventory.md` line 126): *"Does the `AgentMemory`/`ExceptionPattern`/`LearnedOverride` Pydantic model... declare an `organization_id` field at all, even if unused by every workflow-runtime write path?"*
**Answer: CONFIRMED (in the "no" direction) — the field does not exist on the model at all, at any level.** This closes the ambiguity workflow-runtime's notes correctly flagged (the repo could only prove no call site *populates* org_id; it could not rule out an unused schema field). The schema itself carries no such field — this is a genuine structural gap, not merely an unused-field oversight, and matches the "no organization_id on the individual row, only on/via the parent" pattern (`store-inventory.md` Security Finding B) with an even starker variant here: there isn't even a parent Firestore document holding org — the doc id is bare `{agent_id}` with no org segment at all. The only organization-boundary control for this store remains the transfer-time archive+delete mechanism already documented in `olbrain-workflow-runtime.md` (`workflow_agent_memory_archive`).

---

## 4. `olbrain_shared.research.*` models, pricing catalog, and literal Firestore paths

### 4a. `TemplateMeta` / `TemplateBody` — `src/olbrain_shared/research/models/template.py`

`TemplateMeta` (`:72-105`) full field list: `template_id, name, description, tags, industry, use_case, target_audience, org_id, project_id, status (TemplateStatus), locked, created_at, updated_at, created_by, draft_storage_path, draft_updated_at, draft_dirty, current_version, current_version_storage_path, current_version_published_at, current_semver`. **`org_id: str` is present and required** (no default) — confirms research-design's write-time stamping claim structurally, not just by usage.

`TemplateBody` (`:108-160`) full field list: `voice_and_audience, subject_schema, source_policy, budget, runtime_overrides, output_metadata, output_profiles, design_spec, enforcement_policy, verification, personality_traits, personality_source_fingerprint, skills, model, research_playbook, insight_schema, default_effort`. **No org field** (expected — body is design-time content, not tenancy metadata; confirms the doc-comment "Mirrors the split-storage pattern... Firestore stores TemplateMeta + version pointers. Firebase Storage stores TemplateBody" at `:3-6`).

`BODY_FIELDS = sorted(TemplateBody.model_fields.keys())` (`:163`) — this is the shared, canonical list of which fields belong to Storage vs. Firestore for research templates, mirroring `workflow/firestore/service.py`'s `_BODY_FIELDS` tuple for the workflow-definitions split (item 2 above) — same architectural pattern, independently implemented per domain.

### 4b. `RunMeta` — `src/olbrain_shared/research/models/run.py:85-197`

Full field list (extra="forbid", so this IS the complete schema, no undeclared fields possible): `run_id, org_id, project_id, template_id, template_version, triggered_by, session_id, triggered_at, started_at, completed_at, phase, status, failure_reason, error_message, cancel_requested, auto_retry_count, auto_retry_spend_base_usd, cost, billing, claim_review, awaiting_user_since, tags, notes, deleted, is_test, title, learned_context, effort_history, evidence_storage_path, output_storage_paths, rendered_artifacts, plan_storage_path, profile_ids`. **`org_id: str` is required** (no default), confirming research-runtime's construction-site finding (`org_id=ctx.org_id` from the authenticated caller) is enforced by the model itself, not just by convention. Notable finding beyond the original open questions: `billing` (`:141`) is explicitly documented as a **display mirror only** — "`research_runs` is world-writable under current rules, so nothing may price, invoice or reconcile off this field" (`:128-129`) — i.e. the model's own comment states plainly that `research_runs` docs are **NOT protected by Firestore rules from world writes**, with `billing_ledger/rr_{run_id}` as the actual authority. This is new, directly-relevant evidence toward the store-inventory's Security Finding E (Firestore-rules catch-all question) — it doesn't resolve the `olbrain-studio` rules question generally, but it is a same-codebase admission that at least `research_runs` is not write-protected by rules today.

### 4c. `LearnedProfile` / `LearnedItem` — `src/olbrain_shared/research/models/learned_profile.py`

`LearnedItem` (`:42-49`): `id, category (LearnedCategory), statement (≤500 chars), status (LearnedItemStatus), provenance (LearnedProvenance)`. `LearnedProvenance` (`:32-39`): `contributors` (Firebase uids), `session_ids`, `first_learned_at`, `last_reinforced_at`, `reinforcement_count`. `LearnedProfile` (`:52-76`): `items, version (CAS token), updated_at`. **No `organization_id`/`org_id` field on any of `LearnedProfile`, `LearnedItem`, or `LearnedProvenance`.**

### 4d. `LedgerEntry` — `src/olbrain_shared/research/models/learning_ledger.py:30-41`

Full fields: `id, category, statement (≤500 chars), evidence (LedgerEvidence: session_id, run_id, message_index), captured_by (Firebase uid), captured_at, status (LedgerStatus), claimed_at, consolidated_into`. **No `organization_id`/`org_id` field.**

### 4e. `LearnedDesign` / `LearnedDesignItem` — `src/olbrain_shared/research/models/learned_design.py:77-149`

`LearnedDesignItem`: `id, kind, statement, payload (discriminated by kind), status, provenance`. `LearnedDesign`: `items, version, updated_at`. **No `organization_id`/`org_id` field.**

### 4f. `LearnedSubstanceOverride` — `src/olbrain_shared/research/models/learned_substance.py:46-53`

Fields: `source_policy (SourcePolicyDelta, additive), subject_fields, output_profiles, version`. **No `organization_id`/`org_id` field.** `resolve_effective_body()` (`:107-128`) is the actual merge function research-runtime's `load_effective_template` calls: it applies each present delta additively onto the published `TemplateBody` (source-policy list unions, subject-field upsert-by-name, output-profile upsert-by-id), then re-validates the whole body via a round-trip through `TemplateBody.model_validate`; **on any exception, it silently falls back to the unmodified base body** (`:125-127`, explicit `except Exception` with a warning log) — confirms research-runtime's characterization of this as fail-safe/existence-gated, never flag-gated, and additionally confirms there is genuinely no field-level opt-in/opt-out anywhere in the merge logic itself.

### 4g. `MODEL_CATALOG` / `catalog_ids()` — `src/olbrain_shared/research/pricing.py:65-99`

```python
MODEL_CATALOG: list[CatalogModel] = [
    CatalogModel(id="anthropic/claude-fable-5",    label="Claude Fable 5",    tier="max"),
    CatalogModel(id="anthropic/claude-opus-5",     label="Claude Opus 5",     tier="max"),
    CatalogModel(id="openai/gpt-6-astra",          label="GPT-6 Astra",       tier="max"),
    CatalogModel(id="openai/gpt-5.6-sol",          label="GPT-5.6 Sol",       tier="max"),
    CatalogModel(id="anthropic/claude-sonnet-5",   label="Claude Sonnet 5",   tier="balanced"),
    CatalogModel(id="openai/gpt-5.6-terra",        label="GPT-5.6 Terra",     tier="balanced"),
    CatalogModel(id="anthropic/claude-haiku-4-5",  label="Claude Haiku 4.5",  tier="fast"),
    CatalogModel(id="openai/gpt-5.6-luna",         label="GPT-5.6 Luna",      tier="fast"),
]

def catalog_ids() -> set[str]:
    return {m.id for m in MODEL_CATALOG}
```
8 entries, each a `CatalogModel(id, label, tier)` dataclass; `id` carries a provider-routing prefix (`anthropic/`, `openai/`). This is the single, real source of truth both research-design and research-runtime import directly (per those repos' notes) — confirms the "no live duplicate selectable catalog" verdict those notes already reached; nothing here contradicts it. `price_for()`/`llm_usd()`/`compute_usd()` in the same file are the cost-rollup helpers `RunMeta.cost` (§4b) is built from; a code comment (`:74-77`) states "Every entry MUST have a row in `MODEL_PRICES` (asserted by test) so cost rollups never hit the fallback" — the per-model context-window table and capability-probe constants research-runtime separately hardcodes (`json_parsing.py`, `anthropic_client.py`, per that repo's notes) have **no counterpart in this pricing module at all** — confirmed those really are outside the shared catalog's scope, not merely underdocumented here.

### 4h. Literal Firestore path constants — `src/olbrain_shared/research/constants/__init__.py` and the `research/firestore/*.py` repo modules

Collection/subcollection name constants (`constants/__init__.py:10-36`):
```
RESEARCH_TEMPLATES_COLLECTION = "research_templates"
TEMPLATE_VERSIONS_SUBCOLLECTION = "versions"
RESEARCH_RUNS_COLLECTION = "research_runs"
RESEARCH_PLANS_COLLECTION = "research_plans"
PUBLIC_MCP_SERVERS_COLLECTION = "public_mcp_servers"
ORG_ENTITLEMENTS_COLLECTION = "org_entitlements"
ORG_RELIABLE_SOURCES_COLLECTION = "org_reliable_sources"
RESEARCH_CHAT_SESSIONS_COLLECTION = "research_chat_sessions"
RESEARCH_CHAT_MESSAGES_SUBCOLLECTION = "messages"
LEARNING_LEDGER_SUBCOLLECTION = "learning_ledger"
LEARNED_SUBCOLLECTION = "learned"
LEARNED_PROFILE_DOC = "profile"
LEARNED_DESIGN_DOC = "design"
LEARNED_VERSIONS_SUBCOLLECTION = "versions"
```

**Exact, literal, confirmed paths** (built directly in the corresponding `research/firestore/*.py` modules, not inferred):
- **`learning_ledger`**: `research_templates/{template_id}/learning_ledger/{entry_id}` — `research/firestore/learning_ledger.py:1` (module docstring states this exact path verbatim: *"Firestore repo for research_templates/{tid}/learning_ledger/{entry_id}."*) and `_ledger_col()` (`:26-32`) builds it mechanically: `.collection(RESEARCH_TEMPLATES_COLLECTION).document(template_id).collection(LEARNING_LEDGER_SUBCOLLECTION)`.
- **`learned_profiles`** (the live `LearnedProfile` doc — task brief's "learned_profiles"): the doc is **not** at a collection literally named `learned_profiles`; it is a **single fixed-name document** at `research_templates/{template_id}/learned/profile` — `research/firestore/learned_profiles.py:3-4` (module docstring states this exact path verbatim) and `_live_ref()` (`:39-46`): `.collection(RESEARCH_TEMPLATES_COLLECTION).document(template_id).collection(LEARNED_SUBCOLLECTION).document(LEARNED_PROFILE_DOC)`. Immutable version snapshots live at `research_templates/{template_id}/learned/profile/versions/{N}` (`_version_ref()`, `:49-54`).
- **`learned_designs`**: same shape, doc name `design` instead of `profile` — `research_templates/{template_id}/learned/design`, confirmed verbatim in `research/firestore/learned_designs.py:3-4` and its own `_live_ref`-equivalent (mirrors `learned_profiles.py` per that file's own docstring, "Mirrors firestore/learned_profiles.write_profile"). Version snapshots at `research_templates/{template_id}/learned/design/versions/{N}`.

**Open questions closed**:
- `olbrain-research-design.md` Open Question 1 and `olbrain-research-runtime.md`'s corroborating note (*"Exact literal Firestore subcollection path for `learning_ledger`, `learned_profiles`/`learned` (profile), and `learned_designs`... only inferable by analogy... not confirmed by a literal string in either repo I read"*) — **CONFIRMED, exact literal paths given above**, sourced directly from the shared package's own module docstrings and path-builder functions (not inferred by analogy this time). Correction of framing: `learned_profiles`/`learned_designs` are not top-level or even independently-named subcollections — both are individual, fixed-id documents (`profile`, `design`) inside one shared `learned` subcollection per template, i.e. `research_templates/{id}/learned/{profile|design}`, matching the pattern research-runtime's own `learned_substance_store.py` already correctly guessed for the sibling `research_templates/{id}/learned/substance` overlay (that one is NOT part of this shared package's `learned_profiles.py`/`learned_designs.py` pair — `LearnedSubstanceOverride` per §4f above has its own separate, research-runtime-owned store module, `app/lifecycle/learned_substance_store.py`, confirmed in that repo's own notes — the shared package supplies the *model* but not a `firestore/learned_substance.py` repo module; no such file exists under `src/olbrain_shared/research/firestore/`, confirmed by directory listing: `chat_sessions.py, entitlements.py, learned_designs.py, learned_profiles.py, learning_ledger.py, mcp_catalog.py, reliable_sources.py, research_plans.py, runs.py, templates.py`).
- `olbrain-research-design.md`/`olbrain-research-runtime.md` field-list open questions for `TemplateBody`, `TemplateMeta`, `RunMeta`, `LearnedProfile`, `LearnedItem`, `LedgerEntry`, `LearnedDesign`, `LearnedSubstanceOverride` — **CONFIRMED**, full field lists given in §4a–4f above, all sourced directly from the Pydantic model definitions (all use `extra="forbid"`, so these are provably complete schemas, not partial usage-inferred lists).
- `store-inventory.md`'s repeated "no organization_id field" finding (Security Finding B) for `learned_profiles`/`learned_designs`/`learning_ledger` — **CONFIRMED at the schema level**, not just at the usage/write-site level: `LearnedProfile`, `LearnedItem`, `LearnedDesign`, `LearnedDesignItem`, `LedgerEntry`, and `LearnedSubstanceOverride` all declare no such field under `extra="forbid"`, meaning it is categorically impossible for any current or future caller to smuggle an `organization_id` onto these documents without a model change — this is a stronger, schema-enforced version of the "absent" finding than the usage-only evidence the two research repo-notes could produce on their own.

---

## Cross-Repo Resolution Table

| Open question (source file) | Resolution | Evidence in this file |
|---|---|---|
| `person_hash()` salting (`olbrain-agent-runtime.md` §3, Open Q1) | **CONFIRMED unsalted** — same bare `sha256(strip().lower())[:32]` as agent-runtime's own hash | §1 |
| `MAX_PER_TABLE` semantics / entry-model org field (`olbrain-agent-runtime.md` §2) | **CONFIRMED**: table-wide row cap (5000); no shared entry model exists at all, so no schema-level org field is possible or missing — it's caller-defined | §1 |
| `get_workflow()` Firestore/Storage split (`olbrain-workflow-runtime.md` Open Q2) | **CONFIRMED**: metadata doc + Storage body blob, Storage wins when present, explicit legacy inline-JSON fallback when no storage pointer set | §2 |
| `AgentMemory`/`ExceptionPattern`/`LearnedOverride` declare `organization_id`? (`olbrain-workflow-runtime.md` Open Q3) | **CONFIRMED absent** — no such field anywhere on any of the three models | §3 |
| Exact field lists: `TemplateBody`, `TemplateMeta` (`olbrain-research-design.md`, throughout) | **CONFIRMED**, full lists given | §4a |
| Exact field list: `RunMeta` (`olbrain-research-runtime.md` §2) | **CONFIRMED**, full list given; also found `billing` field's own comment stating `research_runs` is "world-writable under current rules" | §4b |
| Exact field lists: `LearnedProfile`, `LearnedItem` (`olbrain-research-design.md`/`-runtime.md`) | **CONFIRMED**, no org field | §4c |
| Exact field list: `LedgerEntry` (`olbrain-research-design.md` §2a) | **CONFIRMED**, no org field | §4d |
| Exact field lists: `LearnedDesign`, `LearnedDesignItem` (`olbrain-research-design.md` §2) | **CONFIRMED**, no org field | §4e |
| Exact field list: `LearnedSubstanceOverride` + `resolve_effective_body()` merge logic (`olbrain-research-runtime.md` Open Q1) | **CONFIRMED**, no org field; merge is additive/existence-gated, fails safe to base body | §4f |
| `MODEL_CATALOG`/`catalog_ids()` contents (`olbrain-research-design.md` §3, `-runtime.md` §5) | **CONFIRMED**, 8-entry list given verbatim | §4g |
| Literal path for `learning_ledger` (`olbrain-research-design.md` Open Q1) | **CONFIRMED**: `research_templates/{template_id}/learning_ledger/{entry_id}` | §4h |
| Literal path for `learned_profiles`/`learned` (`olbrain-research-design.md` Open Q1) | **CONFIRMED**: `research_templates/{template_id}/learned/profile` (fixed doc id `profile` inside subcollection `learned`, not a top-level `learned_profiles` collection) | §4h |
| Literal path for `learned_designs` (`olbrain-research-design.md` Open Q1) | **CONFIRMED**: `research_templates/{template_id}/learned/design` | §4h |

---

## Open Questions (remaining even after this pass)

1. **`workflow_versions.save_draft_body`/`load_body`/`version_path`** — the actual Storage read/write functions `get_workflow()` calls (`workflow.storage.output_store`, `workflow.storage.workflow_versions` modules) were not read in this pass; the *contract* between Firestore metadata and Storage body is fully confirmed (§2), but the exact GCS bucket/path naming convention for workflow version blobs was out of this pass's scope (item was about the split mechanism, not the storage-layer internals) — a follow-up pass on `src/olbrain_shared/workflow/storage/` would close this if ever needed.
2. **What actually triggers a workflow-definition migration from legacy inline JSON to the Storage-pointer scheme in production** — `get_workflow()`'s docstring states the fallback "is expected to go away once the one-time migration script has run in prod," implying a migration script exists somewhere (likely in `olbrain-workflow-design` or an ops script in `olbrain-workflow-runtime`/`olbrain-shared` itself), but no such script was located in this package during this pass (only the read-time fallback logic was in scope).
3. **`RunMeta.billing`'s "research_runs is world-writable under current rules" comment** (`run.py:129`) is new evidence directly bearing on `store-inventory.md` Security Finding E (the Firestore-rules catch-all question), but it is a comment in application code, not the rules file itself — it corroborates the senior review's suspicion for this one collection but does not substitute for reading `olbrain-studio`'s actual `firestore.rules`. Recorded as reinforcing evidence, not as closing Finding E.
4. **`workflow_items` org-binding** (workflow-runtime Open Question 5) is not resolvable from this package — no `WorkflowItem` Pydantic model was located under `olbrain_shared.workflow.models` during this pass (only `run.py`, `step.py`, `workflow.py`, `agent_memory.py` were confirmed to exist via the targeted greps run); whether item docs carry `organization_id` directly would require a further grep for the items model, which was outside this pass's five named priorities.
5. **`SubjectField`/`SourcePolicy`/`OutputProfile`/`SubjectSchema` full internals** (imported into `TemplateBody`/`LearnedSubstanceOverride`) were not individually opened — the task's priority list asked for the top-level models named, not every nested type; if a future pass needs the exact shape of e.g. `SourcePolicy.excluded_tools` validation, `src/olbrain_shared/research/models/source_policy.py` etc. would need a dedicated read.
