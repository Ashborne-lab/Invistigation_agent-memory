# olbrain-research-design — Repository Notes

HEAD used: `d044fce851995ec51372b9427683ffc3d8f3a84a` (2026-09-18 16:28:18 +0530), local working tree — verified equal to `origin/main` at review time (per task briefing).

Review date: 2026-09-19.

Scope note: this repo imports its core Pydantic models (`TemplateBody`, `TemplateMeta`, `RunMeta`, `LearnedProfile`, `LearnedItem`, `LedgerEntry`, `LearnedDesign`, `MODEL_CATALOG`, etc.) from the **`olbrain_shared`** pip package (`olbrain_shared.research.*`). That package is not vendored in this repo and is not one of the two repos I was authorized to clone/read (`olbrain-shared` has no local checkout in this workspace). Every field name and Firestore/GCS path below is therefore verified from **usage sites** in this repo's own source (imports, service code, docstrings, and Firestore/GCS calls), not from reading the shared model class bodies directly. Where the exact literal collection/subcollection path could not be confirmed from this repo alone, it is marked OPEN QUESTION.

---

## 1. `research_templates` — TemplateMeta + TemplateBody

**Store**: Firestore collection `research_templates` (literal string confirmed at `scripts/list_research_templates.py:27` `db.collection("research_templates")`; also `scripts/backfill_template_org_id.py:83` `TEMPLATES = "research_templates"`). The doc holds **TemplateMeta only** (metadata + draft/published pointers); the design-time body blob is **not** stored inline on the Firestore doc.

**TemplateBody storage**: GCS blob, loaded lazily. Evidence: `app/services/template_service.py::get_meta` docstring — "`get()` would load the draft blob from GCS (`olbrain-shared research/firestore/templates.py:164-165`) — a wasted read" (`template_service.py:163-172`). `TemplateService.get()` calls `get_template()` from `olbrain_shared.research.firestore.templates`, which returns a `TemplateDefinition(meta, body)` where `body` is hydrated from GCS; `get_meta()` calls the metadata-only `get_template_meta()` specifically to avoid that GCS read.

**Writers**: `app/services/template_service.py::TemplateService` — `create()` (`template_service.py:104-129`, builds `TemplateMeta(... org_id=org_id ...)` then `create_template(settings, meta, body)`), `save_draft()` (`:157-172`, `save_template_draft(settings, template_id, body)`), plus `update_metadata`, `publish` (router `app/routers/templates.py`), `rollback`. Body is parsed/validated via `TemplateService._parse_body()` (`:88-100`) which routes `output_profiles` through `parse_output_profile`, calls `TemplateBody.model_validate`, then `ensure_selectable_model()` (§7 below) and `validate_playbook_against_schema()`.

**Readers**: `TemplateService.get`/`get_meta` (design-time editing, Studio Builder); `olbrain-research-runtime`'s `app/lifecycle/effective_template.py::load_effective_template` (cross-repo read at run/chat load time — see that repo's notes).

**Scope**: template (`template_id`), nested under an org via `TemplateMeta.org_id`.

**Organization binding**: `TemplateMeta.org_id`, set at create time from the caller's `UserContext.org_id` (`template_service.py:104-116`). Enforced on every read/write via `TemplateNotInOrgError` (raised in `get()`, `:138-148`, and `get_meta()`, `:187-197` when `meta.org_id != org_id`) and `MissingOrgError`/`_require_org()` (`:63-75`) which **denies** (rather than coerces to `""`) an org-less caller.

**Historical correction (LEGACY, fixed)**: `MissingOrgError`'s docstring (`template_service.py:60-67`) and `scripts/backfill_template_org_id.py` document a real production bug: an invited member whose `UserContext.org_id` resolved to `None` could still create/list a template stored with `org_id=""`; `get()` compared raw values so `"" != None` denied every read (404 loop in Studio's Builder tab), and — worse — `org_id==""` was a **single shared bucket across every org-less caller/tenant**, and `list()` leaked template metadata cross-org; the backfill script's own docstring states this held rows "from at least two distinct orgs" in production. The code path is fixed (deny instead of normalize); `backfill_template_org_id.py` is a one-time, dry-run-by-default remediation script for legacy rows, gated on two safety checks (creator must be a live member of the target org; only repairs rows still at `org_id==""`). Classification: **LEGACY** (bug fixed in code; remediation script exists for historical rows) — not an open/in-flight issue in current code.

**PII**: none directly on TemplateMeta/TemplateBody (design-time artefact: prompts, `voice_and_audience`, `subject_schema`, `source_policy`, budget, model, `research_playbook`, `insight_schema` — see `app/services/scaffold.py:45,106` for `subject_schema` shape). `subject_schema` fields are org/template-defined free-form metadata about the research subject (e.g. a company, market, or product); whether a given template's subject data constitutes PII is template-configurable and not fixed by the schema — flagged as variable, not a fixed PII surface.

**Authorization**: Firebase-token org-scoping only (no Firestore-rule evidence available in this repo — rules live in a different repo per the soul map). `require_permission()` (`app/middleware/auth.py:34-49`) enforces a scoped-permission check only for `auth_method=="api_key"` callers; ordinary Firebase browser users pass by convention (mirrors `olbrain-agent-design`, per docstring).

**Deletion/retention**: `delete_template()` exists (imported in `template_service.py`) but its retention semantics (hard delete vs soft/archive, and whether GCS blobs are also removed) were not traced further — **OPEN QUESTION**.

**Classification**: VERIFIED CURRENT (split Firestore-meta/GCS-body storage, org-scoping enforcement, and the historical org_id bug/fix).

---

## 2. Learning ledger and consolidation pipeline

Two independent overlay domains exist, both keyed by `template_id`:
- **Profile overlay** (`LearnedProfile`/`LearnedItem`, category preference/process/insight) — subject-matter/behavioral learnings.
- **Design overlay** (`LearnedDesign`, category `design`) — document/deck styling tokens and boilerplate (a *different* mechanism from the exemplar-driven `DesignSpec` reconstruction in `app/learning/pipeline.py`, which writes into the template's own `design_spec` draft field, not a separate learned-overlay collection).

### 2a. `learning_ledger` (append-only intake)

**Store**: a **subcollection of the template** — explicitly stated in `app/lifecycle/tools/record_learning.py` (research-runtime) docstring: "The ledger is a subcollection of the TEMPLATE." (Exact literal subcollection name/path not visible from this repo's source — imported via `olbrain_shared.research.firestore.learning_ledger.claim_pending`/`mark_entries`/`append_entry`. **OPEN QUESTION**: literal Firestore path string.)

**Writer**: `record_learning` tool, defined and called from **olbrain-research-runtime** (`app/lifecycle/tools/record_learning.py`) during a live conversational research session — NOT this repo. It builds a `LedgerEntry(category, statement, evidence=LedgerEvidence(session_id, run_id), captured_by=ctx.user_id)` and calls `append_entry(ctx.settings, ctx.template_id, entry)`. Trigger: an LLM tool call, invoked opportunistically ("the user expresses a lasting preference... process habit... correction... domain knowledge"), never for one-off run-specific instructions — not a fixed pipeline stage, not "end of every run." Explicitly **skipped for test/play-test sessions** (`ctx.is_test` guard, `record_learning.py:56-61`) with the comment that a ledger entry "outlives its run — and there is no API to delete one." Failure is swallowed (sacrificial — "never break a turn").

**Reader**: `app/learning/agent_pipeline.py::run_learn_agent` via `claim_pending(settings, template_id)` (a lease/claim pattern — entries move to a `consolidating` status and are reclaimed on crash, `agent_pipeline.py:959-960`).

**Data shape**: `LedgerEntry{category, statement (≤500 chars per record_learning.py:39), evidence.session_id, evidence.run_id, captured_by, captured_at}`. No `organization_id` field was found on `LedgerEntry` construction anywhere in either repo (only `template_id` is threaded through as the Firestore path segment).

**PII / verbatim content**: the statement itself is an LLM-authored, third-person, self-contained sentence (per the tool schema description), not a raw quote. However, `agent_pipeline.py::_load_transcripts` (`:914-939`) reads up to `_MAX_TRANSCRIPT_SESSIONS` real session transcripts (`list_messages(settings, sid, limit=200)`, tail-windowed, per-message clipped) and feeds this **actual conversation content** into the consolidator LLM call (`consolidate()`, `:990-994`) as context — so real session text does transit the pipeline even though only a synthesized statement is persisted. This is a materially different (lower, but non-zero) exposure profile than agent-runtime's `agent_learned_patterns`, which the senior review documents as storing up to three **verbatim** end-user messages directly in `intent_examples`.

### 2b. Consolidation trigger and pipeline

**Trigger**: Google Cloud Pub/Sub push, **not** an end-of-run hook. `app/routers/learning.py` — `POST /pubsub/learn-agent` (direct entry point, `learning.py:94-`) and `POST /pubsub/design-jobs` (shared with `job_type` dispatch: `"learn_agent"` → this pipeline, absent `job_type` → legacy `run_learn_design`). Auth: no in-app token check — enforced at the Cloud Run IAM layer via `--no-allow-unauthenticated` + OIDC (documented identically in `app/routers/internal_sweep.py:12-21`, which explicitly cross-references this router). Cadence/what publishes the Pub/Sub message that triggers a consolidation run was **not traced** — **OPEN QUESTION** (likely triggered after N ledger entries or on a schedule from research-runtime or a separate scheduler; not visible in either of the two repos I reviewed).

**Pipeline**: `app/learning/agent_pipeline.py::run_learn_agent(*, template_id: str, org_id: str, settings)` (`:951-985`). Splits claimed entries into `profile_entries` (category != DESIGN) and `design_entries` (category == DESIGN); runs `_run_profile_pass` and `_run_design_pass` **independently** — a failure in one never blocks the other's `mark_entries` ack.

- **`_run_profile_pass`** (`:988-1039`): loads transcripts, calls `consolidate(entries, existing_profile, transcripts, ...)` (LLM-backed), then `enforce_invariants()` (caps per category, pin/archive rules, resolution bookkeeping), then `write_profile(settings, template_id, enforced, expected_version=profile.version)` — a compare-and-swap write (raises `ProfileVersionConflict` on race, retried up to `_MAX_WRITE_ATTEMPTS=3`). The persisted object is built at `agent_pipeline.py:506-508`: `LearnedProfile(items=result, version=old_profile.version, updated_at=old_profile.updated_at)`.
- **`_run_design_pass`** (`:1042-`): analogous, `consolidate_design()` → `enforce_design_invariants()` → `write_design_overlay()`, producing a `LearnedDesign`.

**org_id field — verified absent**: `org_id` is a parameter of `run_learn_agent`'s signature (`agent_pipeline.py:951`) but a full-file grep for `org_id`/`organization_id` in `app/learning/agent_pipeline.py` finds **no other occurrence** — it is not stored on `LearnedProfile`, not passed into `write_profile`, and not used for any org-scoping decision inside the consolidator. It appears to be a currently-unused/dead parameter. **CONFIRMED**: `LearnedProfile` (and, by the same evidence pattern, `LearnedDesign`) carries no organization_id field; org association is only implicit via the parent `template_id` (and thus the template's own `org_id`).

**Operator mutation surface**: `app/services/learning_service.py::LearningService` — `pin()`, `edit()`, `archive()` (interfaces §4.3) are a *second* writer of the profile besides the consolidator, each going through the same `get_profile → mutate → write_profile` CAS loop (`_mutate_item`, `:94-127`), org-guarded via `TemplateService.get()` (`_org_guard`, `:56-57`) — so operator mutation of learned items **is** org-checked (through the parent template), even though the stored `LearnedProfile` record itself carries no `organization_id`. `edit()` re-sanitizes operator-submitted statements through the same `_clean_statement` hygiene as the consolidator (`learning_service.py:72-78`), capped at 500 chars.

**Design language reconstruction** (a separate, non-overlay mechanism): `app/learning/pipeline.py::run_learn_design` — a 6-stage pipeline invoked from the **legacy** `/pubsub/learn-design` route (still present per `learning.py:10-11`, "stays in `design.py` until Phase 5 re-points the subscription"), which learns document/deck visual theme from an uploaded exemplar file and writes the result into the *template's own draft* `design_spec` (GCS: `design_master_path`, `design_css_path`, `design_preview_path`, via `olbrain_shared.research.storage.design_assets`). This is design-time exemplar reconstruction, distinct from the runtime learned-design **overlay** described above — the soul map's "design-language reconstruction from exemplar documents" phrase refers to this pipeline, not the `learned_designs`/`learning_ledger` overlay. Classification: **IN-FLIGHT MIGRATION** (legacy `/pubsub/learn-design` route explicitly slated for repointing to the unified `job_type` dispatch in "Phase 5", per `learning.py:9-11`).

**Classification (overall learning pipeline)**: VERIFIED CURRENT for the mechanism (ledger → claim → dual-pass consolidate → CAS write), CONFIRMED for "no organization_id field" on the learned records, IN-FLIGHT MIGRATION for the design-language legacy route.

---

## 3. Model / pricing catalog (§G4 duplication check, research-design side)

At this HEAD, **research-design does not maintain its own duplicate selectable-model catalog list** — contrary to what the senior soul map (`repo-and-soul-map.md` §04/G4, citing `research-design model_catalog.py`, `config.py:54`) describes:

- `app/services/model_validation.py::ensure_selectable_model()` (`:14-23`) validates against `catalog_ids()` imported directly from `olbrain_shared.research.pricing` (`:11`) — no local list.
- `app/routers/model_catalog.py` (`:12,20-25`) serves `MODEL_CATALOG` imported directly from `olbrain_shared.research.pricing` joined with `price_for()` — again no local list.
- No file named `model_catalog.py` with a hardcoded list exists anywhere else in the repo (confirmed by grep for `claude-fable|claude-opus|claude-sonnet|claude-haiku|gpt-` across `app/`, which found only three narrow, single-model hardcodes, not a catalog).

What **does** still exist as hardcoded, catalog-adjacent duplication in this repo:
- `app/config.py:55` — `learn_agent_model: str = "claude-sonnet-4-6"` (a single fixed model id for the internal consolidation LLM call, not a selectable-list duplicate).
- `app/learning/claude_vision.py:27` — `_MODEL = "claude-opus-4-8"`.
- `app/services/scaffold.py:25` — `_MODEL = "claude-opus-4-8"` (comment: "matches the design-synth model tier").

**Classification**: CONTRADICTED BY SOURCE for the specific claim "research-design `model_catalog.py`... hardcodes ... a selectable catalog" as a currently-existing duplicate list — at this commit the repo delegates catalog membership/pricing to the shared package. PARTIALLY CONFIRMED for the broader "model ids are duplicated/hardcoded outside the shared catalog" theme, in the narrower form of three single fixed-model constants. See the companion research-runtime notes file for the equivalent check on that side, and the "Corrections" section below for the combined verdict.

---

## 4. Reports — `audit_trail` hard-coded empty (Studio-facing report builder)

**Evidence**: `app/services/report_service.py:191-193` — comment "audit\_trail field empty here — the studio still has the noted..." immediately above `audit_trail: list[FetchedSnapshot] = []`, then passed into the constructed report object at `:211` (`audit_trail=audit_trail`). Confirmed by `tests/test_reports_router.py:80` — `assert payload["audit_trail"] == []`.

This is a **different** `build_report`/report path than the one in **olbrain-research-runtime**'s `app/services/report_service.py` (used by the `get_report` conversational tool) — that runtime-side function returns a different shape entirely (`run_id, template_id, status, phase, cost, output_storage_paths, output_bodies, ...`) and has **no `audit_trail` field at all**. The two repos each have their own, differently-shaped `report_service.py` / `build_report()` for different consumers (research-design's serves the Studio "Reports" surface via `app/routers/reports.py`; research-runtime's serves the in-session `get_report` LLM tool). Whether the Studio-facing `audit_trail` field is ever populated from the runtime's actual citation-audit verifier output (see research-runtime notes, `app/lifecycle/verifier.py`) was **not traced across the two codebases** — **OPEN QUESTION**: is there any pipeline that copies real audit findings into research-design's `report_service.py` `audit_trail`, or is it structurally always empty regardless of whether the runtime's citation audit ran?

**Classification**: VERIFIED CURRENT (the field is hard-coded empty in this exact call path, as the soul map states) — but flagged with the cross-repo inconsistency above as an open question rather than assumed resolved.

---

## 5. Authorization pattern summary (research-design)

Every service class I read enforces org-scoping the same way: resolve `UserContext.org_id` from the verified Firebase token (`app/middleware/auth.py`), then compare it against the target document's stored `org_id`/`meta.org_id`, raising a domain-specific `*NotInOrgError` (mapped to HTTP 404, not 403, so an org-less caller cannot distinguish "doesn't exist" from "not yours" — an oracle-avoidance pattern consistent with what research-runtime does, see that repo's notes). Evidence: `TemplateService` (`TemplateNotInOrgError`, `template_service.py:53-55,138-148,187-197`), `LearningService` (`_org_guard`, `learning_service.py:56-57`, delegates to `TemplateService.get`), and `RunService`/`ClaimReviewService` (`RunNotInOrgError`, `app/services/run_service.py:35-36`, org compared at `:60,91-92`; also enforced at trigger time via `tmpl.meta.org_id != user.org_id` check inside `trigger()`, `run_service.py:60`).

No Firestore security-rules file exists in this repo (rules for research collections were not located in either of the two repos in scope) — **OPEN QUESTION carried over from the soul map's G12 finding**, which was scoped to `olbrain-studio`'s ruleset and agent-domain collections; whether an equivalent allow-by-default catch-all exists for `research_templates`/`research_runs` collections could not be verified from `olbrain-research-design` or `olbrain-research-runtime` alone.

---

## Corrections to prior soul-map claims (research-design)

**(a) "`research_templates` resolved with learned overlays at load" / opt-in flag** — this claim's mechanism (`load_effective_template`) lives in **olbrain-research-runtime**, not this repo; see that repo's notes for the full verdict (CONTRADICTED — no opt-in flag found; overlay is applied unconditionally whenever a substance-overlay doc exists).

**(b) organization_id on `learned_profiles`/`learned_designs`/`learning_ledger`** — **CONFIRMED**. Read the actual write code in `app/learning/agent_pipeline.py`: `run_learn_agent`'s `org_id` parameter (`:951`) is never referenced again in the function body (verified by grep across the whole file); `LearnedProfile` is constructed at `:506-508` with only `items`, `version`, `updated_at` — no org field. `LedgerEntry` (`app/lifecycle/tools/record_learning.py` in the runtime repo, `:66-74`) likewise carries no org field, only `category`, `statement`, `evidence.{session_id,run_id}`, `captured_by`. Org association exists only indirectly, through the parent template's `org_id` and the app-layer org-guard checks (`LearningService._org_guard`) — not on the learned records themselves.

**(c) Model catalog duplication (G4)** — **PARTIALLY CONFIRMED / mostly CONTRADICTED for the "duplicate catalog" framing**, at this HEAD. Research-design's `model_validation.py` and `routers/model_catalog.py` import the catalog directly from `olbrain_shared.research.pricing` rather than maintaining their own list; the file `model_catalog.py` that exists is a thin re-export/join, not a duplicate source of truth. What remains duplicated is narrower: three single hardcoded model-id constants (`config.py:55`, `claude_vision.py:27`, `scaffold.py:25`) for specific internal LLM calls, not a selectable-catalog list. See research-runtime notes for the equivalent, and the combined verdict there.

---

## Open Questions

1. Exact literal Firestore subcollection path for `learning_ledger`, `learned_profiles`/`learned` (profile), and `learned_designs` — only inferable by analogy to the runtime's `learned_substance_store.py` pattern (`research_templates/{id}/learned/{doc}`); not confirmed by a literal string in either repo I read.
2. What publishes the Pub/Sub message that triggers `/pubsub/learn-agent` (cadence: after N ledger entries? scheduled? on session end?) — not found in either repo.
3. `TemplateService.delete_template` retention/deletion semantics (hard delete vs. soft, GCS blob cleanup) — not traced.
4. Whether research-design's Studio-facing `audit_trail` (`report_service.py:191-193`, always `[]`) is ever populated from research-runtime's real citation-audit verifier output, or is structurally dead regardless of audit results.
5. Firestore security-rule enforcement for `research_templates`/`research_runs` (equivalent of the soul map's G12 catch-all finding) — no rules file exists in either of the two repos reviewed; unverifiable from this scope.
