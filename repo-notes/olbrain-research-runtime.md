# olbrain-research-runtime — Repository Notes

Local working-tree HEAD: `d1caecd4e9781a5f51f377c54c0ffa133ccb13e1` (2026-09-19 14:22:16 +0530).

`origin/main` at review time: `d2e3f7a92744db2afbdeb38df30a452077384b27` — **one merge commit ahead** of local HEAD (`git log d1caecd..origin/main`: merge of PR #280, "feat(verification): the citation audit runs on its own switch, not the umbrella one"). That commit touches only `app/lifecycle/verifier.py` and two test files (`tests/lifecycle/test_verifier_outputs.py`, `tests/test_phase_job_handlers.py`) — a citation-audit gating change, unrelated to research learned overlays, `RunMeta`, template resolution, or org-scoping. **None of the facts below depend on that diff.** Every path cited below was read from the local working tree; I additionally spot-checked that `app/lifecycle/verifier.py` differs between the two refs (confirmed via `git log d1caecd..origin/main --stat`) but did not need to cite verifier.py content for any claim in this document, so no re-read via `git show origin/main:<path>` was required. If a future pass needs `verifier.py` specifically, it should be read via `git -C repos/olbrain-research-runtime show origin/main:app/lifecycle/verifier.py` rather than the working tree, per source-of-truth discipline.

Review date: 2026-09-19.

Scope note: as with olbrain-research-design, the core Pydantic models (`RunMeta`, `TemplateDefinition`, `LearnedSubstanceOverride`, `LearnedDesign`, `LearnedProfile`, `MODEL_CATALOG`) live in the `olbrain_shared` pip package, not vendored here. Field names below are verified via attribute-access usage sites in this repo's own code, not by reading the shared model class bodies.

---

## 1. Effective-template resolution at load — `app/lifecycle/effective_template.py`

**Mechanism**: `load_effective_template(settings, template_id, *, variant)` (`effective_template.py:20-38`) is, per its own module docstring, "The single resolve-at-load chokepoint. Every template-load site that should honor learned substance calls this instead of `get_template` directly."

```python
async def load_effective_template(settings, template_id, *, variant):
    tmpl = await get_template(settings, template_id, variant=variant)
    if tmpl is None:
        return None
    try:
        overlay = await get_learned_substance(settings, template_id)
    except Exception:
        overlay = None
    if overlay is None:
        return tmpl
    effective_body = resolve_effective_body(tmpl.body, overlay)
    ...
    return TemplateDefinition(meta=tmpl.meta, body=effective_body)
```

**No opt-in flag found.** `get_learned_substance` is called unconditionally on every load; there is no check of a template-body field (e.g. an `overlay_enabled` flag) gating whether the call happens or whether its result is applied. The only conditional is whether an overlay document *exists* (`overlay is None` → skip), and a defensive try/except so a Firestore read failure degrades to the base body rather than blocking the load — this is a fail-safe, not an opt-in gate.

**Storage**: `app/lifecycle/learned_substance_store.py` — module docstring: "Always-live per-template learned-substance overlay (Firestore doc). Path: `RESEARCH_TEMPLATES_COLLECTION/{template_id}/learned/substance`." (`:1-4`). `_doc()` (`:18-25`) builds this exact Firestore path: `firestore.client().collection(RESEARCH_TEMPLATES_COLLECTION).document(template_id).collection("learned").document("substance")`. `RESEARCH_TEMPLATES_COLLECTION` resolves to the literal `"research_templates"` (confirmed via `research-design/scripts/set_template_orchestration.py:37` and `research-design/scripts/list_research_templates.py:27`, both hardcoding `"research_templates"`). `get_learned_substance`/`set_learned_substance` (`:28-47`) are the only reader/writer.

**Callers confirmed to use `load_effective_template` unconditionally** (no per-caller opt-in either):
- `app/routers/external_trigger.py:12,58` — the headless, API-key-authenticated `POST /v1/runs` endpoint calls `load_effective_template(settings, body.template_id, variant=variant)` before constructing `RunMeta`, with no flag check.
- Also referenced from `app/lifecycle/conversational_planner.py` and elsewhere per the earlier grep of files matching `effective_template` (not individually re-read line-by-line beyond the external_trigger callsite, but the module docstring's "every template-load site... calls this instead of `get_template` directly" is an explicit design invariant, not merely an observed pattern).

**Design overlay (separate mechanism, also unconditional)**: `app/lifecycle/learned_design_merge.py::merge_learned_design(operator_theme, overlay)` (`:106-218`) is a pure function (no I/O, "Run ONCE at run start... driver caches the result"). It returns `None` only if `overlay is None` or `overlay.items` has no ACTIVE/PINNED items (`:110-114`) — again, existence-gated, not flag-gated. Precedence is "operator design wins per field, learned overlay fills gaps" (module docstring `:1`) — e.g. palette keys apply only where absent from the operator's theme (`:149-151`); typography/page-geometry tokens apply only when `operator_theme is None` ("ACCEPTED theme owns ALL typography", `:153,157,161,166,170`); header/footer content applies only where the operator slot is unset (`:174-181,186-193`). This is a **field-level precedence rule**, not a toggle to disable the overlay wholesale.

**Verdict**: **CONTRADICTED BY SOURCE.** The soul map's claim that `research_templates` overlays are applied via "an opt-in overlay flag" does not match the code — resolution is unconditional/always-on at every load site once a learned-substance or learned-design overlay document exists for the template. The only "gating" that exists is (1) whether an overlay document happens to be present, and (2) field-level precedence rules that let an operator's own explicit choice win over a learned value — neither of which is a flag a template author sets to enable/disable overlays.

**What gets merged**: for substance, whatever fields `resolve_effective_body(tmpl.body, overlay)` implements in the shared package (not directly readable from this repo) — the override type is `LearnedSubstanceOverride`, and `set_learned_subject_fields.py`/`set_learned_source_policy.py`/`set_learned_output_profiles.py` tool names (found via grep) strongly suggest the override covers `subject_schema` fields, `source_policy`, and `output_profiles`. For design, per `learned_design_merge.py`: palette entries, heading/body font, type_scale keys, page size/margins, header/footer HTML (built from `header_text`/`footer_text`/boilerplate markdown, sanitized via `markdown-it` with `html=False` plus a second nh3-based sanitizer at render time, `:59-76`).

**Classification**: VERIFIED CURRENT for the mechanism and the "no opt-in flag" finding.

---

## 2. `research_runs` — RunMeta

**Store**: Firestore collection `research_runs` (literal string confirmed via `research-runtime/scripts/backfill_research_run_events.py:128` — `db.collection("research_runs")`).

**Fields confirmed present on `RunMeta` by usage** (attribute-access grep across `app/`, not an exhaustive schema read since the class itself lives in `olbrain_shared`): `org_id`, `project_id`, `template_id`, `template_version`, `phase` (`RunPhase` enum: PLANNING/GATHERING/WRITING/RENDERING/DELIVERING/REVIEW/GAPFILL — inferred from `_KIND_LABELS` in `app/routers/runs.py:75-83`), `status` (`RunStatus`: includes COMPLETED/FAILED/CANCELED, `app/lifecycle/tools/get_report.py:23`), `cost` (a nested object with its own `.model_dump()`, `app/services/report_service.py:83`), `triggered_by`, `triggered_at`, `completed_at`, `session_id`, `is_test`, `profile_ids`, `tags`, `notes`, `claim_review`, `learned_context`, `evidence_storage_path` (single string), `output_storage_paths` (dict keyed by `profile_id` → path string), `auto_retry_count`, `failure_reason`, `error_message`.

Construction site (`app/routers/external_trigger.py:78-89`):
```python
meta = RunMeta(
    org_id=ctx.org_id,
    project_id=tmpl.meta.project_id,
    template_id=body.template_id,
    template_version=(body.template_version if body.template_version is not None else tmpl.meta.current_version),
    triggered_by=f"api-key:{ctx.key_name}",
    profile_ids=profile_ids,
)
```
`org_id` is stamped from the **authenticated caller's** org (`ctx.org_id` from `verify_api_key`), not from the request body — confirms org binding is enforced at creation, not merely trusted from client input.

**Evidence/output storage — confirmed GCS-blob + Firestore-pointer split**, mirroring the template body pattern:
- `app/lifecycle/phases.py:312-318` — `evidence_path = await save_evidence(ctx.settings, ctx.run_id, pool.model_dump())`, then `await update_run_storage_paths(ctx.settings, ctx.run_id, evidence_storage_path=evidence_path)`, then `ctx.run.meta.evidence_storage_path = evidence_path`. The evidence **content** (the full `EvidencePool` — gathered source material/notes) is written to a GCS blob; only the path string lands on the Firestore `RunMeta` doc.
- `app/lifecycle/driver.py:759-771` — on a WRITING-phase resume, evidence is **rehydrated** from GCS via `artifact_io.load_evidence(self._settings, run.meta.evidence_storage_path)`, confirming the Firestore field is a path, not inline content.
- `app/lifecycle/driver.py:775-783` — output per profile is likewise a `{profile_id: storage_path}` dict written via `update_run_storage_paths(..., output_storage_paths=output_paths)`.
- `app/services/report_service.py:33-41,56-74` — `build_report()` downloads each profile's `content.json` blob from `storage.bucket(settings.research_designs_bucket)` by the stored path and parses it as JSON — this is the actual report content (markdown + citation_urls) a completed run produces, confirming output bodies are GCS JSON blobs, not Firestore documents.

**Reader/authorization pattern (org check) — verified at multiple independent call sites**, all using the same "404 for both not-found and not-yours" oracle-avoidance idiom:
- `app/routers/runs.py:48-50` (`retry_run_endpoint`) — `if run is None or run.meta.org_id != user.org_id: raise HTTPException(404, ...)`.
- `app/routers/runs.py:103-105` (`active_job_endpoint`) — identical pattern, with an explicit comment: "404 for both 'no such run' and 'not your org'... the id must not be an oracle for a caller who cannot see the run either way."
- `app/lifecycle/tools/get_report.py:26-29` — `if r is None or r.meta.org_id != ctx.org_id: return ToolResult(output={"error": "not_found"}, is_error=True)`.
- `app/routers/external_trigger.py:59` — template-side equivalent: `if tmpl is None or tmpl.meta.org_id != ctx.org_id or tmpl.meta.current_version is None: raise HTTPException(404, ...)`.

Notably, `app/services/report_service.py::build_report()` itself (the function that actually fetches the GCS content blobs) performs **no** org check internally (`report_service.py:44-89`) — it trusts that its caller (`get_report.py`, which does check) has already gated access. This is a defense-in-depth gap in principle (a future caller of `build_report` that forgets the org check would leak cross-org report content) but not a currently-exploitable path in the two call sites I found (`get_report.py` gates before calling it).

**Billing note**: `get_report.py:41-43` explicitly strips `cost` from the payload before returning it to the LLM/chat surface — comment: "spend is internal (users pay a flat report fee), and this payload reaches the chat model verbatim — it repeats any figure." This is a deliberate billing-data redaction at the tool boundary.

**Classification**: VERIFIED CURRENT for schema-by-usage, GCS/Firestore split, and org-check pattern. The lack of an org check inside `build_report()` itself is worth flagging (see Open Questions) even though the one path that calls it today is gated.

---

## 3. PII in run evidence/reports

**Evidence pool** (`pool.model_dump()`, persisted via `save_evidence`) contains whatever the gathering phase collected against the template's `subject_schema`/`source_policy` — since `subject_schema` is org/template-defined free text fields (see research-design notes §1), the PII sensitivity of a given run's evidence is **template-dependent**, not fixed by the runtime's own schema. The runtime enforces a `SourcePolicyEnforcer` (referenced in `phases.py:328`) and a citation/conflict-scan pass (`scan_conflicts`, gated by `ctx.template.body.verification`, `phases.py:304-310`) but these are quality/reliability controls, not PII controls.

**Report output** (`content.json` blobs per profile, read by `build_report`) is markdown + `citation_urls` — i.e. the finished deliverable text, which by construction may embed subject-matter content (potentially including named individuals, companies, or other subject data) at whatever sensitivity the source material carried. No redaction/anonymization step was found in `report_service.py` or the writer pipeline (`app/lifecycle/writers/`) — **OPEN QUESTION**: whether any PII-scrubbing pass exists elsewhere in `app/lifecycle/writers/` (not read in full).

**Classification**: OPEN QUESTION for the concrete PII content of any given run (template-dependent, no fixed schema); VERIFIED CURRENT for the mechanism (no redaction pass found at the report-build layer).

---

## 4. Authorization enforcement (research-runtime)

Consistent with research-design: no client-side Firestore rules are present in this repo; every access-control decision I found is enforced in application code via `org_id` equality checks after Firebase-token or API-key verification (`app/middleware/firebase_auth.py::verify_firebase_user`, `app/middleware/api_key.py::verify_api_key`). See §2 for the specific call sites. I did not find a single case in this repo where an org check was missing at a route/tool boundary that a client could reach directly — the one gap noted (`build_report()` itself) is only reachable today through an already-gated caller.

---

## 5. Model / pricing catalog (§G4 duplication check, research-runtime side)

As with research-design, **no full duplicate selectable-model catalog** exists in this repo at this HEAD:
- `app/lifecycle/run_model.py:33-37` — imports `catalog_ids` from `olbrain_shared.research.pricing`, with a graceful `ImportError` fallback (`catalog_ids = None`) for "shared < model-switching release" — i.e. this repo defers to the shared catalog and degrades safely if that shared release isn't available, rather than shipping its own list.
- `app/lifecycle/tools/session_model.py:16,131,218` — imports and directly renders `MODEL_CATALOG` from `olbrain_shared.research.pricing` for the `/model` picker UI — again, no local list.
- `run_model.py`'s own docstring (`:20-24`) states the design intent explicitly: "catalog validation is best-effort... the design service is the authoritative validator. An id outside the catalog falls back to the default with a warning; model choice must never fail a run." — i.e. research-runtime deliberately treats research-design (backed by the shared catalog) as the source of truth and only soft-validates locally.

What **is** hardcoded/duplicated in this repo, distinct from a "selectable catalog":
- `app/config.py` stage-default model ids as individual settings: `default_run_model` (`:90`, `"anthropic/claude-sonnet-5"`), `default_plan_model` (`:94`, `"anthropic/claude-opus-5"`), `default_review_model` (`:99`), `default_connector_model` (`:209`), `chat_planner_model` (`:249`, `"claude-opus-5"`), `chat_title_model`/`chat_compaction_model` (`:250,274`, `"claude-haiku-4-5-20251001"`). These are guarded by a CI invariant test the code references — `run_model.py:122-124` names `test_stage_defaults_are_catalog_models` — that checks these strings stay members of the shared catalog, and `stage_default()` (`:109-131`) logs a warning (never raises) if a configured default drifts out of the catalog.
- A hardcoded per-model context-window table, unrelated to pricing/selectability: `app/lifecycle/writers/json_parsing.py:56-64` — `{"claude-fable-5": 128000, "claude-opus-5": 128000, "claude-sonnet-5": 128000, "claude-haiku-4-5": 64000, "gpt-6-astra": 128000, "gpt-5.6-sol": 128000, "gpt-5.6-terra": 128000, "gpt-5.6-luna": 128000}` — this is a capability/limits table the shared pricing catalog does not appear to expose (per the surrounding code's need to hardcode it locally), so it is a genuine, distinct duplication risk (a new model added to the shared catalog without a corresponding entry here would silently fall through to no known limit).
- `app/llm/anthropic_client.py:56,75` — `_REFUSAL_FALLBACK_MODEL = "claude-opus-4-8"` and `_FALLBACK_CAPABLE = frozenset({"claude-opus-5", "claude-fable-5"})` — hardcoded model-capability facts (which models support a specific SDK parameter/rescue behavior), determined empirically per a comment at `:60-64` ("probed 2026-08-20 against this org and workspace").

**Verdict**: same pattern as research-design — the *selectable catalog* is centralized in `olbrain_shared.research.pricing` and both repos consume it (contradicting a literal "hardcodes... a selectable catalog" claim at this HEAD), but each repo separately hardcodes its own **defaults and capability facts** (context windows, parameter-support flags) that are adjacent to, but not sourced from, that shared catalog — a real, narrower duplication surface than G4 as originally framed.

---

## Corrections to prior soul-map claims (research-runtime)

**(a) "`research_templates` resolved with learned overlays at load" / opt-in flag** — **CONTRADICTED.** `app/lifecycle/effective_template.py::load_effective_template` is the single chokepoint and applies `get_learned_substance`'s result unconditionally whenever an overlay document exists at `research_templates/{id}/learned/substance`; `app/lifecycle/learned_design_merge.py::merge_learned_design` is likewise existence-gated, not flag-gated, and uses field-level operator-wins precedence rather than an on/off switch. No opt-in flag was found on `TemplateBody`, at any call site (including the headless API-key `/v1/runs` path in `external_trigger.py`), or in either overlay store module. The "resolved with learned overlays at load" half of the original claim is accurate; the "opt-in" half is not.

**(b) organization_id on `learned_profiles`/`learned_designs`/`learning_ledger`** — not independently re-derivable from this repo (the write path lives in research-design); see that repo's notes for the CONFIRMED verdict. This repo's `learned_substance_store.py` corroborates the same pattern for the substance-overlay doc: its Firestore path (`research_templates/{template_id}/learned/substance`) and its model (`LearnedSubstanceOverride`) are keyed purely by `template_id`, with no `org_id` field constructed anywhere in `get_learned_substance`/`set_learned_substance` (`learned_substance_store.py:28-47`).

**(c) Model catalog duplication (G4)** — **PARTIALLY CONFIRMED / mostly CONTRADICTED for the "duplicate selectable catalog" framing**, same verdict as research-design: this repo consumes the shared `MODEL_CATALOG`/`catalog_ids()` rather than maintaining its own selectable list, with an explicit fallback for older shared-package versions. It does hardcode per-stage default model ids (six settings in `config.py`, checked by a named CI test against catalog drift) and — more significantly — a standalone per-model context-window table (`json_parsing.py:56-64`) and capability-probe constants (`anthropic_client.py:56,75`) that have no corresponding source of truth in the shared catalog at all, which is a genuine duplication risk distinct from G4's original "selectable catalog defined in four or five places" framing.

---

## Open Questions

1. Exact fields inside `LearnedSubstanceOverride` and what `resolve_effective_body()` actually merges field-by-field (the function/class bodies live in `olbrain_shared`, not read); inferred only from tool names `set_learned_subject_fields.py`, `set_learned_source_policy.py`, `set_learned_output_profiles.py`.
2. Whether `app/services/report_service.py::build_report()`'s lack of an internal org check is exploitable through any call site other than the org-gated `get_report.py` tool — I found only that one caller in this repo, but did not exhaustively search for every import of `build_report`.
3. Whether any PII-redaction/anonymization pass exists in `app/lifecycle/writers/` before report content is persisted to GCS — not read in full given the "trace data paths, don't read entire repositories" instruction.
4. What publishes/schedules consolidation jobs to research-design's `/pubsub/learn-agent` (cadence) — this repo only writes ledger entries via `record_learning`; it does not appear to trigger consolidation directly from any code path I traced.
5. Firestore security-rule enforcement for `research_templates`/`research_runs` (equivalent of soul-map G12) — no rules file in this repo; unverifiable from this scope.
6. The exact diff in `app/lifecycle/verifier.py` between local HEAD (`d1caecd`) and `origin/main` (`d2e3f7a`) was not read in detail since it did not bear on any claim in this document (confirmed unrelated via the PR title/description and file list only) — a future citation-audit-specific investigation pass should read it via `git show origin/main:app/lifecycle/verifier.py`.
