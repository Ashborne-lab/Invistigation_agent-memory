# olbrain-workflow-runtime — Repo Notes

- Repo: `olbrain-workflow-runtime`
- HEAD verified: `5d48437d87589e5c927b2018eea0954da87cc13b` (2026-08-31 21:21:59 +0530), matches `origin/main` per workspace setup; local working tree clean at review time.
- Review date: 2026-09-19
- Reviewer scope: read-only source inspection under `repos/olbrain-workflow-runtime` (app/, scripts/, docs/, tests/, firestore.indexes.json). The `olbrain_shared` package (models, `firestore.service`, etc.) is an external wheel dependency — **not vendored in this clone** — so its Pydantic model source (e.g. `AgentMemory`, `WorkflowDefinition`, `WorkflowRun`) could not be read directly here. Where noted, findings about those models are inferred from how this repo's code constructs/reads/writes them, not from the model source itself.

---

## Store: `workflow_agent_memory/{agent_id}`

**Path**: Firestore top-level collection `workflow_agent_memory`, one document per `agent_id` (not per workflow, not per run).

**Writers** (all in-repo, `app/services/agent_memory_service.py`):
- `append_exception_pattern()` (lines 148–253) — writes on `db.collection(WORKFLOW_AGENT_MEMORY).document(agent_id).set(...)`, called from `app/routers/exceptions.py::_learn_from_resolution` (line 21) as a `BackgroundTask` after a human resolves a workflow exception (`resolve_exception` and `resolve_all_exceptions` routes). Only fires when the Haiku enricher (`app/services/pattern_enricher.py`) returns a usable summary — the module docstring states "happy-path runs never touch this collection."
- `record_pattern_match()` (line 256) — bumps `match_count`/`last_matched_at` when the agentic resolver reuses a pattern; called from `app/core/agentic_resolver.py:371`.
- `delete_pattern()` (line 278) — manual delete of one pattern.
- `set_override_status()` (line 296) — approve/retire a `LearnedOverride`.
- `record_override_applications()` (line 458) — fire-and-forget bump of `applied_count` plus a companion write to `workflow_agent_decisions/{decision_id}`.
- `app/routers/internal_transfer.py::archive_agent_memory` (line 154) — on agent transfer, copies the whole doc into `workflow_agent_memory_archive/{agent_id}__{from_org_id}__{ts}` and deletes the source (see Corrections section).

**Readers** (in-repo):
- `get_memory()` / `match_patterns()` in `agent_memory_service.py`, called from `app/core/agentic_resolver.py::try_resolve` (line 205) to narrow+rank candidate patterns for an auto-resolution attempt.
- `load_active_overrides()` — called once at run start to apply active `LearnedOverride`s to item data (`apply_overrides_to_item`).
- `app/routers/exceptions.py::get_agent_memory` (`GET /agents/{agent_id}/memory`) — feeds the Studio "Learned Patterns" tab.
- `app/services/co_designer_service.py::_load_memory` (line 596) — reads the raw dict for the internal co-designer proposal flow (`/api/internal/co-designer`), still workflow-side, not agent-runtime.

**Data shape** (as constructed by `agent_memory_service.py`, backed by `olbrain_shared.workflow.models.agent_memory.AgentMemory`/`ExceptionPattern`/`LearnedOverride` — models not directly read):
- `agent_id`, `exception_patterns[]` (capped at `MAX_PATTERNS_PER_AGENT=200`, LRU-evicted by `(match_count, learned_at)`), `learned_overrides[]`, `updated_at`.
- Each `ExceptionPattern` carries: `pattern_id`, `step_id`, `step_type`, `trigger_summary`, `tags`, `what_failed`, `what_human_did`, `resolution`, `resolution_data`, **`original_data`** (the failing item's raw field values, verbatim except keys starting with `_`; line 187), `learned_at`, `learned_from_exception_id`, `learned_from_run_id`, `match_count`, `last_matched_at`.
- Each `LearnedOverride` carries: `override_id`, `workflow_id`, `step_id`, `field`, `selector` (up to 4 key/value pairs from item data), `correction`, evidence exception/run ids, status (`suggested|active|retired`), `contradiction_count`.
- `pattern_enricher.py`'s example tags ("invoice", "missing_tax_id", "vendor_normalization") indicate `original_data` is real business/document-extraction data (e.g., invoice/vendor fields), not synthetic test data.

**Scope**: strictly per-`agent_id`. `workflow_id` appears only as a field *inside* `LearnedOverride` (to scope which workflow an override applies to) and as a parameter to `append_exception_pattern`/`record_override_applications` — it is never part of the document key and the memory doc is shared across every workflow version that agent has run.

**Organization binding**: **none on the live document.** Every write path (`agent_memory_service.py`) constructs/updates the doc via `AgentMemory(**doc.to_dict())` → mutate → `memory.model_dump(exclude_none=True)` → `.set(...)`; no call site ever sets an `organization_id` field, and the doc ID is `{agent_id}` alone. This holds regardless of whether the underlying Pydantic model declares such a field, since nothing populates it. `organization_id` is passed as a parameter into `match_patterns()`/`enrich_pattern()` (used only for LLM-side context/observability, e.g. `pattern_enricher.enrich_pattern(..., organization_id=...)`), not persisted onto the memory doc.

**PII / sensitivity**: HIGH. `original_data` stores raw item/document fields verbatim (per-item business data flowing from document extraction / workflow steps), and the Haiku enrichment prompt (`pattern_enricher.py` `_SYSTEM_PROMPT`) is fed this data directly, producing summaries/tags that are also persisted.

**Authorization enforcement**: **none in this repo** for the memory routes. `GET /agents/{agent_id}/memory`, `DELETE /agents/{agent_id}/memory/patterns/{pattern_id}`, and the override approve/retire routes (`app/routers/exceptions.py:258-311`) take only `agent_id`/`pattern_id`/`override_id` from the URL/body with no organization check, no auth dependency, and no caller-identity check at all. `app/main.py` registers only `CORSMiddleware` (`allow_origins=["*"]`) — there is no app-wide auth middleware in this service. The only auth-flavored dependency in the whole repo, `require_dispatcher_ingress` (`app/core/dispatcher_auth.py`), is service-to-service OIDC (verifies the caller is the webhook dispatcher / a known SA), applied only to the four run-**creating** endpoints in `app/routers/workflow_triggers.py`, and even there it is enforced only when `ENFORCE_DISPATCHER_INGRESS=true`; the code comment states the default is `false` ("log-only: unverified callers are logged, never blocked"). Whatever organization-scoping exists for these routes must therefore live upstream (studio-backend / gateway / Cloud Run IAM) — **not verifiable from this repo** (see Open Questions).

**Deletion / retention behavior**:
- Manual, per-pattern delete: `DELETE /agents/{agent_id}/memory/patterns/{pattern_id}` (`app/routers/exceptions.py:265`).
- Manual, per-agent, full-collection wipe: `scripts/wipe_agent_memory.py` — a one-shot ops script (`CONFIRM_WIPE=1` env-gated) that deletes every document in `workflow_agent_memory`; written to retire the legacy deterministic-fingerprint pattern schema.
- Automatic, structural cap only: `MAX_PATTERNS_PER_AGENT=200` LRU eviction — not a privacy control, a size control.
- Transfer-triggered archive+delete: see `internal_transfer.py::archive_agent_memory` below — this is the closest thing to an organization-boundary control this repo has for this store.
- No TTL, no scheduled purge, no GDPR-style per-end-user erasure route for this collection (there is no per-end-user key here at all — it's per-agent).

**Classification**: **VERIFIED CURRENT** — collection name, document key, writer/reader call sites, field shape, and absence of org binding / route-level authz are all confirmed directly in this repo's source at HEAD `5d48437d`.

---

## Store: `workflow_agent_memory_archive/{agent_id}__{from_org_id}__{ts}`

**Path**: Firestore collection `workflow_agent_memory_archive`, composite doc id `{agent_id}__{from_org_id}__{timestamp}`.

**Writer**: `app/routers/internal_transfer.py::archive_agent_memory` (`POST /api/internal/transfer/memory/archive`, lines 154–236). Called by olbrain-agent-design's `WorkflowTransferService` during the agent-transfer cascade (per the module docstring, referencing `olbrain-agent-design` plan doc `docs/superpowers/plans/2026-05-24-transfer-architectural-split.md`, not verifiable from this repo).

**Behavior**: reads `workflow_agent_memory/{agent_id}`, stamps `archived_at_transfer` (server timestamp), `archived_from_org_id`, `archived_from_agent_id`, writes the full doc under the archive id, then **deletes** the source `workflow_agent_memory/{agent_id}` doc. Explicit rationale in the docstring: "Letting those patterns follow the agent to a new org leaks private business context AND auto-resolves items under assumptions the new owner never made." Idempotent (returns `archived=False` if the source is already gone); if the archive write succeeds but the delete fails, it logs a warning that "recipient may see sender's patterns until cleared manually" and still returns `archived=False`.

**Authorization**: explicitly documented as none at the application layer — module docstring: "Auth: Cloud Run platform-level (caller must hold roles/run.invoker on this service). No per-request auth handled here." (`internal_transfer.py:12-13`)

**Organization binding**: the archive doc *does* carry `archived_from_org_id`, unlike the live memory doc — but this is a one-time stamp at transfer time, not an ongoing org field on active memory.

**Classification**: **VERIFIED CURRENT** for the archive mechanism and its rationale (source-confirmed). This is the concrete evidence that the "no org field" gap on `workflow_agent_memory` is a recognized issue that the platform partially mitigates procedurally (wipe-on-transfer) rather than structurally (no org field ever added to the live doc, no per-request org check added to the memory routes).

---

## Store: `workflow_definitions/{id}` (WorkflowDefinition)

**Path**: Firestore collection `workflow_definitions`, one doc per `workflow_id`. Confirmed directly: `scripts/migrate_add_trigger_input_step.py:14,60` ("Loads workflow_definitions/<id>", `coll = client.collection("workflow_definitions")`); also referenced in `docs/superpowers/plans/2026-05-25-webhook-file-upload.md:267,615` and `docs/superpowers/plans/2026-05-10-phase3-postgres-control-plane.md:124` (a planning doc, not confirmed-executed code, that explicitly lists `workflow_definitions` as staying in Firestore / out of scope for a Postgres control-plane migration — treat as **OPEN QUESTION / planning artifact**, not verified current behavior of a migration).

**Writer/reader of the body itself**: this repo does **not** author `WorkflowDefinition` documents — that's `olbrain-workflow-design`'s job per the soul map. This repo only **reads** workflow definitions, via `olbrain_shared.workflow.firestore.service.get_workflow(workflow_id, variant=...)` — the actual Firestore-doc-vs-Storage-body split and versioning mechanism live in that external shared-wheel function, which is **not present in this clone** and could not be read directly. The migration script above operates directly on the Firestore doc's `steps` array, confirming at least part of the body (steps) is readable/writable as plain Firestore doc fields, not solely a Storage blob — this is only a partial confirmation of the "Firestore doc + Storage body" split claimed by the soul map; the Storage-body side (draft/published JSON blobs analogous to `conversational_agents/{id}/draft.json`) was **not found in this repo's own source** and could not be directly verified here.

**Draft vs. published variant selection at trigger — CONFIRMED, this repo's routing logic** (`app/routers/workflow_triggers.py`):
- `trigger_workflow` (manual, `POST /{workflow_id}/trigger`, lines 89–302): variant selection priority is (1) explicit `request.workflow_version` int → pin to that historical version, (2) `request.is_test` → `variant="draft"`, (3) default → `variant="published"`. Code comment: "Pre-migration workflows still work — the shared service falls back to the legacy inline-JSON shape when neither storage pointer is set" (lines 105–110) — this is direct evidence of an **IN-FLIGHT MIGRATION** for the storage-pointer scheme (from an older inline-JSON shape to the newer draft/published pointer shape), consistent with the "config-layout migration" pattern seen elsewhere in the architecture (per `repo-and-soul-map.md` G14, for the conversational side).
- `webhook_trigger` (`POST /webhook/{workflow_id}`, lines 305–489): production webhooks always read `variant="published"` unless a verified dispatcher sets `x-olbrain-draft: 1` (then `variant="draft"`).
- `webhook_test_trigger` (`POST /webhook/{workflow_id}/test`): always reads `variant="draft"`.
- `schedule_callback` (`POST /schedule/callback/{workflow_id}`): always reads `variant="published"`.
- Status gating: `WorkflowStatus.ACTIVE` required for production triggers (`DRAFT`/`ACTIVE` both allowed for test triggers); `PAUSED` gets a distinct 409 (used for transfer-pending workflows); production webhook triggers additionally require `firestore_service.is_agent_published(workflow.agent_id)`.
- Executed version stamping: `WorkflowRun.workflow_version` is set to the pinned int, or `workflow.current_version` when variant is `"published"`, or `None` for drafts (lines 216–223).

**Organization binding**: `WorkflowDefinition.organization_id` is read and propagated onto every `WorkflowRun` created from it (`organization_id=workflow.organization_id` in all four trigger handlers) and is also used for tenant fan-out (`tenant_router.resolve_forwarding_target(workflow.organization_id)` — dedicated-tenant orgs get their trigger forwarded to a separate Cloud Run service/Firestore project, e.g. `clix-capital-prod`).

**Authorization**: trigger routes are gated by `require_dispatcher_ingress` (service-to-service, log-only by default — see above), not by verifying the caller's org against `workflow.organization_id`. No user-level org check found in this repo for trigger routes either.

**Classification**: **VERIFIED CURRENT** for the variant-selection/routing logic (directly read). **OPEN QUESTION / PARTIALLY VERIFIED** for the exact Firestore-doc-vs-Storage-body split mechanics, since `firestore_service.get_workflow` itself is not in this clone.

---

## Store: Runs, Items, Exceptions

**Collections** (confirmed via direct string literals and indexes, not solely inference):
- `workflow_runs` — confirmed in `app/core/job_dispatcher.py:157` (`.collection("workflow_runs")`) and `firestore.indexes.json` (composite indexes on `workflow_id+started_at`, `agent_id+started_at`, `agent_id+organization_id+started_at`) and `scripts/backfill_usage_events/__main__.py:56`.
- `workflow_items` — confirmed in `scripts/delete_stale_clix_capital_org_doc.py:86` and `docs/superpowers/plans/2026-05-10-phase2-per-step-output-rows.md:193` (`WORKFLOW_ITEMS = "workflow_items"`) and used throughout `app/core/orchestrator.py` (per-item hot path, "Phase 1 is idempotent and skips items that already have a final outcome in workflow_items" — `app/routers/runs.py:283`).
- `step_outputs` — confirmed in `firestore.indexes.json` (indexed on `run_id`, `run_id+step_id`, `completed_at`); `app/routers/runs.py:81-85` docstring: "spilled step outputs (stored as GCS pointers to stay under Firestore's 1 MiB doc cap)" — i.e. large per-step outputs are stored in Cloud Storage with a pointer doc in Firestore, hydrated back on `GET /runs/{run_id}` via `get_run_hydrated`.
- `workflow_agent_decisions` — companion audit-trail collection for override applications (`agent_memory_service.py:29,485-500`).
- Exceptions are **not** a separate top-level collection — they live embedded as `run.exceptions[]` on the `WorkflowRun` doc itself (`app/routers/exceptions.py:122-131`: `run = await firestore_service.get_run(run_id)`; `exceptions = run.exceptions`).

**Writers**: `app/core/orchestrator.py` (per-item execution, phase finalization, Excel/notify regen), `app/routers/workflow_triggers.py` (`create_run`), `app/routers/runs.py`/`items.py`/`exceptions.py` (status transitions, retries, resolutions), `app/core/job_dispatcher.py` (`job_execution_name`, run status on dispatch failure).

**Readers**: Studio (via these same routes, proxied), `app/services/public_run_projection.py` (a public/share-link projection with its own 15-minute signed-URL TTL — `SIGNED_URL_EXPIRES_MINUTES=15`), `app/routers/runs_public.py`.

**Data shape / PII-sensitivity of run items**: item docs (`workflow_items`) and exception records carry the actual per-item business/document data flowing through the workflow (`exc.data`/`original_data` seen in the memory-service write path above; `resolution_data`/`modified_data` on exception resolution). Given step types like `DOCUMENT_PROCESS`, `EXTRACT_AND_CLASSIFY_DOCUMENTS`, `MASTER_DATA_QUERY`, `CROP_DOCUMENT` (per `repo-and-soul-map.md` §04), and the enrichment prompt's own invoice/vendor examples, run items plausibly carry extracted document fields (e.g., invoice/vendor data) that would be PII/business-sensitive depending on the workflow's domain — **classification of overall PII exposure for this store: OPEN QUESTION as to the general case** (depends entirely on what a given workflow processes) but **VERIFIED CURRENT that the mechanism stores such data verbatim when present** (no redaction/anonymization step observed in the code read).

**Organization binding**: `WorkflowRun.organization_id` is set at creation from the workflow doc (see trigger routes above) and is indexed (`firestore.indexes.json`). `workflow_items` presumably inherit this via `run_id` (not independently confirmed — item docs were not read directly in full, this repo's `items.py` router only shows the retry endpoint).

**Authorization enforcement**: **none found at the app layer** for `runs.py`, `items.py`, `exceptions.py`, `steps.py`, `test_step.py` — none of these routers apply `require_dispatcher_ingress` or any other auth dependency; they only validate `run_id`/`workflow_id`/`item_id` existence and status-machine legality (e.g., "Cannot cancel run with status ..."). The only org-boundary-adjacent logic present is **tenant routing** (`tenant_router.resolve_forwarding_target`/`maybe_forward_for_workflow`), which forwards a request to a different dedicated-tenant Cloud Run service/Firestore project based on the workflow's `organization_id` — this achieves data-residency isolation between tenants at the infrastructure level but is not a caller-identity/authorization check.

**Deletion / retention**: no delete/purge route found for runs, items, or exceptions in this repo. The only deletion-adjacent script found, `scripts/delete_stale_clix_capital_org_doc.py`, deletes a stale `organizations/clix-capital` doc (a one-off data-residency cleanup for a specific tenant), not a general run/item retention mechanism. Signed URLs for artifacts (uploaded trigger-input files, public run projections) expire (`SIGNED_URL_EXPIRES_MINUTES` various), but the underlying Firestore/Storage records are not shown to be purged.

**Classification**: **VERIFIED CURRENT** for collection names, writer/reader call sites, absence of app-level authz, and absence of a delete route. **OPEN QUESTION** for the general PII content of run items (workflow-dependent) and for whether `workflow_items` docs themselves carry `organization_id` directly (inferred via `run_id`, not directly read).

---

## Cloud Run Jobs coordination ("leases") and the agentic resolver

No separate lease/lock document collection was found. Coordination state lives directly on the `workflow_runs/{run_id}` doc:
- `job_execution_name` — the Cloud Run Jobs execution name, set by `app/core/job_dispatcher.py::_store_execution_name` after a successful dispatch; read back by `cancel_run_execution` (`job_dispatcher.py:149-171`) to best-effort cancel the live execution when a run is cancelled.
- `orchestrator_generation` — an integer fencing counter, incremented by `firestore_service.increment_orchestrator_generation(run_id)` on every resume/retry (`app/routers/runs.py:247,336,342,351`) so a stale in-flight orchestrator pass exits at its next item-boundary poll instead of racing a newer pass.

The agentic resolver (`app/core/agentic_resolver.py`) reads/writes only `workflow_agent_memory` (via `agent_memory_service.match_patterns`/`record_pattern_match`, lines 205/371) plus feature flags (`is_enabled_for_agent`, `is_agentic_task_enabled`, `feature_level`, lines 90-171) whose backing store was not traced further (out of scope per task instruction to keep this section brief).

**Classification**: **VERIFIED CURRENT** for the run-doc fields; **OPEN QUESTION** for the feature-flag backing store (not traced).

---

## Organization scoping and authorization — summary across this repo

**VERIFIED CURRENT, repo-wide finding**: `app/main.py` wires only `CORSMiddleware` (`allow_origins=["*"]`, line 67-73); there is no authentication or organization-membership middleware anywhere in this service. The single auth-flavored control in the entire repo is `app/core/dispatcher_auth.py::require_dispatcher_ingress` — a Google-OIDC-token-plus-SA-allowlist check that verifies the caller is a trusted *service* (the webhook dispatcher, or the shared runtime's re-minted identity on tenant fan-out), not a check that a human caller belongs to the workflow's organization. It is applied only to the run-creating endpoints in `workflow_triggers.py`, and is enforced (`403` on failure) only when `ENFORCE_DISPATCHER_INGRESS=true`; the code states the default is `false` (log-only). `internal_transfer.py` and `co_designer.py` are documented as relying on Cloud Run IAM (`roles/run.invoker`) for their internal-only prefixes (`/api/internal/...`).

Every other route read in this repo (`runs.py`, `items.py`, `exceptions.py`, `steps.py`, `test_step.py`) has **no auth dependency of any kind** — organization isolation for these, if it exists, is enforced upstream (studio-backend, an API gateway, or Cloud Run ingress/IAM policy) and **cannot be confirmed or refuted from this repo's source alone**. Tenant-level isolation (different orgs' data landing in physically separate Firestore projects/Cloud Run services for "dedicated" tenants) is implemented via `app/services/tenant_router.py` and is a genuine organization-boundary control, but it operates on the workflow's own `organization_id`, not on verifying the identity of the calling user/service.

---

## Corrections to prior soul-map claims

**(a) `workflow_agent_memory` scope and fields — CONFIRMED, with additional detail.**
The soul map's summary ("`workflow_agent_memory/{agent_id}`, written by workflow-runtime, agent-scoped, PII varies") is confirmed and can be sharpened: PII is not merely "varies" but is **high when present** — `original_data` stores raw item fields verbatim, and pattern enrichment explicitly summarizes real business-document content (invoice/vendor examples in the enricher's own prompt). The soul map did not mention the `workflow_agent_memory_archive` collection or the transfer-time wipe mechanism (`internal_transfer.py::archive_agent_memory`), which is new, source-verified detail not in the prior map: it is the platform's only concrete mitigation for the "no organization_id field" gap on this store, and it is explicitly justified in the code comments as preventing cross-org leakage of "private business context."

**(b) "Never read by the conversational side" — CONFIRMED from this repo's side, cannot be confirmed from the other side.**
`grep -r "agent_user_memory\|agent_datastores"` across the entire `olbrain-workflow-runtime` tree returned **zero matches**. This repo never reads or references either of agent-runtime's per-user memory stores. This confirms one direction of the "two memory namespaces that never read each other" claim (G9 in the soul map). The reverse direction — whether `olbrain-agent-runtime` ever reads `workflow_agent_memory` — cannot be determined from this repo and is recorded as an open question below; it is in scope for the `olbrain-agent-runtime` repo-notes pass.

**(c) Draft/published variant selection at trigger — CONFIRMED, with one addition.**
The soul map's summary ("Firestore `workflow_definitions/{id}` plus Storage body; draft or published variant per trigger") is confirmed for the *selection logic* (see the `workflow_triggers.py` breakdown above: explicit-version pin → is_test/draft flag → published-by-default, plus the `x-olbrain-draft` header path for dispatcher-verified draft webhook tests). One addition the soul map did not call out: the trigger code contains an explicit **legacy-compatibility fallback** — "Pre-migration workflows still work — the shared service falls back to the legacy inline-JSON shape when neither storage pointer is set" (`workflow_triggers.py:105-110`) — indicating an **IN-FLIGHT MIGRATION** from an older inline-JSON workflow body representation to the current draft/published storage-pointer scheme, analogous to the config-layout migration already documented on the conversational side (soul map G14). The exact mechanics of the "Storage body" half of the split could not be verified in this repo since `firestore_service.get_workflow` lives in the external `olbrain_shared` wheel, not in this clone.

---

## Open Questions

1. **Cross-repo (primary handoff item)**: does `olbrain-agent-runtime` ever read `workflow_agent_memory`? This repo's side is now source-confirmed as write-only/no-cross-read; the reverse direction requires reading `olbrain-agent-runtime`'s source (its memory/config-loading services) and is out of scope for this pass.
2. What does `olbrain_shared.workflow.firestore.service.get_workflow()` actually do for the Firestore-doc-vs-Storage-body split on `workflow_definitions`? This function lives in an external wheel not vendored in this clone; only the *selection* (draft/published/version-pin) contract was verifiable here, not the storage mechanics themselves.
3. Does the `AgentMemory`/`ExceptionPattern`/`LearnedOverride` Pydantic model (in `olbrain_shared.workflow.models.agent_memory`) declare an `organization_id` field at all, even if unused by every current write path? Not resolvable without reading the shared wheel's source.
4. Is there an authorization/organization check enforced upstream of this service (studio-backend proxy, API gateway, Cloud Run ingress policy / IAM) for the routes that have no in-app auth (`runs.py`, `items.py`, `exceptions.py`, `steps.py`, `test_step.py`)? This repo's source alone shows no such check; it may exist entirely outside this codebase.
5. Do `workflow_items` documents carry `organization_id` directly, or only transitively via `run_id`→`workflow_runs.organization_id`? Not independently confirmed — item docs were not read in full (only the retry-endpoint router, `items.py`).
6. Is `docs/superpowers/plans/2026-05-10-phase3-postgres-control-plane.md` (which explicitly excludes `workflow_definitions` from a proposed Postgres migration) a live/adopted plan, an abandoned draft, or purely speculative? It reads as a planning artifact, not confirmed-executed code, and should not be treated as evidence of an actual in-flight migration without further verification.
7. What backs the agentic resolver's feature flags (`is_enabled_for_agent`, `is_agentic_task_enabled`, `feature_level` in `app/core/agentic_resolver.py:90-171`)? Not traced in this pass (kept deliberately brief per task scope).
