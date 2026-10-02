# olbrain-agent-engine — Repository Notes

**Repo:** `olbrain-agent-engine`
**HEAD verified:** `87207201a0b78c52f6986703ff09b2d899b81c6e` (2026-09-16 14:31:10 +0530), via `git -C repos/olbrain-agent-engine rev-parse HEAD`. Note this is one commit ahead of the `8720720` short-hash recorded in MASTER.md/task brief — same commit (`8720720` is the abbreviation of `87207201a0...`), no drift.
**Review date:** 2026-09-19

---

## 1. Context Service (`alchemist/context/`)

### 1a. Immutable event log

- **Store:** `context_logs/{scope_key}/events/{event_id}` (Firestore). `scope_key` is a deterministic, percent-escaped encoding of `(level=id)` pairs from the scope cascade GLOBAL→ORG→PROJECT→AGENT→SESSION.
  Evidence: `alchemist/context/log_store.py:8-16,28-44,83-88`.
- **Writer:** `ContextService.record()` (`alchemist/context/service.py:39-76`), called by every fleet write path (see §1d for actual scopes used).
- **Reader:** `ContextService.retrieve()` (recency recall, most-recent k events, session-scoped only — `service.py:78-88`); `context_broker.py:308` (slice read for dispatch); `context_routes.py` audit writer also uses `record()` for CRUD audit trail.
- **Data shape:** `ContextEvent` — `id, scope{org,project,agent,session}, user_id, ts, type, payload, provenance, source_event_ids[], author?, correlation_id?, client_event_id?`. `payload` carries **full-fidelity raw content**, including real `tool_use`/`tool_result` blocks and, via `vibe_record.py`, raw `user_msg`/`agent_msg` text from Vibe sessions. Evidence: `alchemist/context/events.py:31-68`, `alchemist/context/vibe_record.py:1-18,43-56`.
- **Immutability:** `LogStore.append()` is idempotent-on-id but never updates/deletes an existing doc (`log_store.py:90-96`). No delete/erasure code path for `context_logs` was found anywhere in this repo (`grep` for `context_logs`/`context_facts` outside the store modules returned nothing).
- **Scope/org binding:** `ScopePath` supports `org/project/agent/session` (`alchemist/context/scope.py:26-30`), and `to_dict()` always writes all four fields into the stored event (`events.py:52-53`). **However**, every construction site of `ContextService` found in this repo passes `ScopePath(session=<vibe_session_id>)` only — org/project/agent are never populated on the live turn-time write/read path. Evidence (all call sites): `alchemist/context/vibe_record.py:94`, `vibe_dispatch.py:165,201,249`, `alchemist/agents/orchestrator_agent.py:89`, `alchemist/agents/agentify_agent.py:3005-3007`, `alchemist/agents/synapse_agent.py:7977-7979`, `alchemist/services/context_broker.py:271-272`, `routes.py:3929-3930`. The only place ORG/PROJECT/AGENT `ScopePath`s are actually constructed is `context_routes.py:102-113,256`, which is the CRUD surface (see §1c) — gated off in prod.
- **PII:** payload can contain verbatim user/agent conversational text (design-time conversation with Alchemist/Cortex/etc, not end-customer chat). Soul map calls this "low, design conversation" — plausible but not independently verified line-by-line here; flagged as OPEN QUESTION below.
- **Authorization on read/write of the live path:** none beyond normal route auth — `record`/`retrieve` are called in-process by the fleet's own turn loop, not exposed as a direct user-facing endpoint (the only user-facing surface, `context_routes.py`, is separately gated and separately authorized — see §1c).
- **Classification: VERIFIED CURRENT** — the immutable log and its Firestore layout are real, live code, exercised whenever `CONTEXT_SERVICE_ENABLED`/`VIBE_CONTEXT_CONVERGENCE_ENABLED` are on (confirmed `"true"` in `env.template.yaml`, see §1e). The multi-scope hierarchy (ORG/PROJECT/AGENT) is **VERIFIED CURRENT as schema/CRUD-surface capability but effectively LEGACY-UNREACHED on the live write path**, since no runtime call site populates those scopes.

### 1b. Bi-temporal facts

- **Store:** `context_facts` (flat Firestore collection, not sub-collected by scope). Evidence: `alchemist/context/facts_store.py:11,23-24`. Confirms the soul map's claimed collection name exactly.
- **Bi-temporal:** Real. `ContextFact` carries `t_valid`/`t_invalid`, `status ∈ {candidate, active, invalid}`, `superseded_by`, and `source_event_ids` back to the log (`alchemist/context/facts.py:10-30`). "invalidate-don't-delete" is enforced: `supersede()`/`decay()` only ever `.update()` status/`t_invalid`, never delete a fact doc (`facts_store.py:40-48`). This is a genuine bi-temporal design (valid-time via `t_valid`/`t_invalid`, transaction/observed-time implicitly via `created_at`/`updated_at`), not aspirational.
- **Verify-before-active gate:** Real and code-enforced, not a claim. `Consolidator.consolidate()` (`alchemist/context/consolidation.py:65-115`) always creates a fact as `CANDIDATE` first (never surfaced — `facts.py:11`, `service.py:104`), then judges the claim against ONLY its cited source events via `judge_answer_against_evidence` (`consolidation.py:85-97`); an uncited candidate is never promoted (`consolidation.py:88-90`), and a judge-transport exception leaves the fact a candidate rather than fail-open-promoting it (`consolidation.py:93-95`, comment: "NO fail-open here"). Only `_supported()` (`verdict == "approve"`) promotes via `FactsStore.promote()`.
- **Writer:** `Consolidator` (via `ContextService.maybe_consolidate()`, `service.py:135-206`), itself invoked from `routes.py:3929-3931` after a turn.
- **Reader:** `ContextService.active_facts()` / `active_facts_as_records()` (`service.py:101-119`) — only `status==active` facts are ever surfaced into a turn's recalled context.
- **Scope binding:** `scope_key` on each fact is the same encoding as the log (`log_store.scope_key`), so facts inherit whatever scope was live when consolidation ran — which, per §1a, is session-only in every call site found. **No org/project/agent-scoped fact was found being written by any live path in this repo.**
- **PII:** facts are extracted by an LLM from event payloads' `text`/`content` fields (`consolidation.py:23-33`), so they can embed distilled (not necessarily verbatim) end-user/design-session text.
- **Deletion/retention:** no deletion code found; invalid facts are retained forever ("kept for history" per `facts.py:1-3`).
- **Classification: IN-FLIGHT MIGRATION / TARGET-LEANING BUT LARGELY DARK IN PROD.** The code is real and non-trivial (not vaporware), but its trigger is gated behind `CONTEXT_CONSOLIDATION_ENABLED`, which is **`"false"`** in `env.template.yaml:95` — the file that is rendered into the actual Cloud Run env at deploy time (`.github/workflows/deploy-main.yml` renders `env.template.yaml`; comment at `env.template.yaml:85-92` confirms "A–E live... CONSOLIDATION → durable bg execution... first" i.e. not yet flipped). **Practical consequence: in production today, candidate/active fact promotion effectively never fires**, so `context_facts` is expected to be empty or near-empty in prod even though the log (`context_logs`) is actively being written. This directly qualifies the soul map's "Forge session facts (Context Service)" row — the store exists and its logic is verified-before-active, but it is not currently populating.

### 1c. Guardrails (scoped) + Context CRUD surface

- **Store:** `context_guardrails` flat collection. Evidence: `alchemist/context/guardrails_store.py:12` (`_COLLECTION = "context_guardrails"`).
- **Resolution:** `ContextService.guardrails_resolve()`/`.pins()` (`service.py:94-99`) reads active guards across the scope cascade (`GuardrailStore.list_active(levels_ids=scopes_for(self._scope))`) — but again, in every live call site the scope is session-only, so effectively only SESSION- and GLOBAL-level guardrails are ever resolved at runtime today.
- **Mutation surface:** `context_routes.py` — a full CRUD+resolve HTTP API keyed by `(role × scope × origin/locked)`. **Dark by default**: every route 404s unless `CONTEXT_CRUD_ENABLED` is truthy (`context_routes.py:78-85`), and that flag is **`"false"`** in `env.template.yaml:96`. Even if flipped on, v1 authorization is deliberately narrow: `_resolve_role()` always returns `Role.END_USER` (no claims-based role mapping yet, `context_routes.py:88-99`), and `is_scope_owner`/`can_read_scope` (`alchemist/context/ownership.py`) fail-closed for ORG/PROJECT/AGENT scopes — only an owned `alchemist_sessions/{id}` (session) is writable/readable by an end user; GLOBAL is world-readable. Agent-origin (LLM) writes go through `approve_write()`, which is hard-coded to `return False` — i.e., **adversarial/agent-originated guardrail writes are unconditionally denied** pending a "Spec 2" reviewer (`context_routes.py:70-75`).
- **Classification: VERIFIED CURRENT (as dark/disabled code)** — the guardrail CRUD surface exists, is real, and is currently inert in prod (`CONTEXT_CRUD_ENABLED=false`). The read path used by the live fleet (`guardrails_resolve()`/`pins()`) is **VERIFIED CURRENT** and live, but effectively session/global-scope-only in practice.

### 1d. Feature-flag defaults (source: `env.template.yaml`, rendered at deploy time by `.github/workflows/deploy-main.yml`)

| Flag | Default in `env.template.yaml` | Meaning |
|---|---|---|
| `CONTEXT_SERVICE_ENABLED` | `"true"` (line 93) | Runtime adoption (log + recall + window mgmt) is LIVE for standalone Alchemist. |
| `VIBE_CONTEXT_CONVERGENCE_ENABLED` | `"true"` (line 52) | Vibe-session writes route through `vibe_record`→`ContextService` (session-scoped) instead of the legacy narrative. |
| `CONTEXT_COMPACTION_ENABLED` | `"true"` (line 94) | Native `compact_20260112` window edit is live. |
| `CONTEXT_CONSOLIDATION_ENABLED` | `"false"` (line 95) | Fact extraction/verify/promote pipeline is OFF — `context_facts` promotion does not fire in prod. |
| `CONTEXT_CRUD_ENABLED` | `"false"` (line 96) | Guardrail CRUD HTTP surface 404s in prod. |
| `ALCHEMIST_REWORK_ENABLED` | `"true"` (line 83) | `GuardrailGate`+`Judge` wired into `OrchestratorCore` for the Vibe conductor (see §4). |
| `CORTEX_SESSION_OWNERSHIP_GUARD` | `"true"` (line 101) | Per-session owner-only Cortex writes enforced. |

These are treated as the actual production values per the file's own header comment ("Cloud Run env-vars template — rendered at deploy time by each GitHub Actions workflow") and confirmed present in `.github/workflows/deploy-main.yml`. This is a live-repo artifact, not a guess — but note it is a *template*, not a live `gcloud services describe` dump of the running Cloud Run revision, so a manual out-of-band flip that was never committed here (the file's own comments describe this exact failure mode happening historically, e.g. the `ALCHEMIST_REWORK_ENABLED` comment at lines 77-83) could in principle mean the true live value differs. Flagged as an OPEN QUESTION below.

---

## 2. Vibe session state (`alchemist/schemas/vibe_session.py`, `alchemist/services/vibe_session_service.py`)

- **Store:** Firestore collection **`vibe_sessions`** (not `alchemist_sessions`, which is a separate, older collection used for standalone-Alchemist session ownership checks — see `alchemist/context/ownership.py:31`). Evidence: every method in `alchemist/services/vibe_session_service.py` calls `self.db.collection("vibe_sessions")` (lines 59,63,76,93,127,163,172,185,196,204,211,228,249,261,271,280,290,300).
- **Schema:** `VibeSession` (`alchemist/schemas/vibe_session.py:58-87`) — `id, metadata{user_id, started_at, last_active_at, status, title, phase}, active_conversant{state, since, last_transition_event_id}, model_policy, draft_agent_id?, organization_id?, project_id?, pending_brief?, real_agent_id?, build_status?, build_progress?`.
- **"Who holds the floor":** `active_conversant.state ∈ {alchemist, cortex, synapse, multi_party, awaiting_user}` (`vibe_session.py:14-19`). Written exclusively by **`VibeSessionService.transition_to()`** (`vibe_session_service.py:294-313`), a Firestore transaction that updates `active_conversant.state/since/last_transition_event_id` and bumps `metadata.last_active_at`. Confirms the soul-map claim precisely.
- **`pending_brief`:** written by `set_pending_brief()` (`vibe_session_service.py:200-207`) and cleared by `clear_pending_brief()` (`:209-213` — not fully read but named/called per handoff comment at `vibe_dispatch.py` handoff handler, `:360`). Used to hand the "next builder" (e.g., Synapse after Cortex) an intent summary as its build instruction.
- **Handoff transition:** `_make_handoff_handler` in `vibe_dispatch.py` intercepts `handoff_to_cortex`-style tool calls, calls `VibeSessionService.transition_to`, and persists `pending_brief` (`vibe_dispatch.py:335` per soul map narrative — read via surrounding code at `vibe_dispatch.py:335-366`).
- **Org/project binding:** `organization_id`/`project_id` are top-level, optional fields, filled in by `set_tenancy()` **only when currently `None`** ("session-pinned tenancy stays authoritative" — `vibe_session_service.py:215-241`). `list_for_user()` treats org+project as **mandatory** for listing (empty result if either is missing, explicitly to avoid a cross-tenant leak — `vibe_session_service.py:104-125`), which is a real, code-enforced org scoping control on the list surface.
- **Deletion:** **No hard delete found.** `soft_delete()` (`vibe_session_service.py:160-165`) only flips `metadata.status` to `DELETED`; `end()` (`:92-95`) only flips to `ENDED`. The Firestore document and its full history (messages via linked `context_logs`, tenancy, model policy, etc.) persist indefinitely. No TTL, no scheduled purge, no GDPR-style erasure route for `vibe_sessions` was found in this repo.
- **PII:** `organization_id`/`user_id`/`title` (user-authored, could contain identifying text) live directly on the doc; the actual conversational content lives in the linked `context_logs/{session_key}/events` (session-scoped Context Service log, see §1a) rather than inline on the `vibe_sessions` doc itself.
- **Classification: VERIFIED CURRENT.** Collection name, schema, writer, and soft-delete-only behavior are all directly confirmed in source at current HEAD.

---

## 3. Provisional agent writes (`agents/{id}`)

- **Trigger:** `_maybe_materialize_and_build()` (`vibe_dispatch.py:369-431`), run in the background "on every Cortex turn" once a `draft_agent_id` exists on the Vibe session.
- **Writer:** `AgentifyAgent.handoff_recommendation(session_id, rec_id, user_id, lifecycle_state="provisional")` (`alchemist/agents/agentify_agent.py:3672-3763`). Creates a full `agents/{agent_id}` document (`Collections.AGENTS`, line 3748) carrying `basic_info, type, owner_id, project_id, organization_id, lifecycle_state, status, generated_prompt, recommendation_metadata, version, created_at, created_by, updated_at`.
- **Org/project binding:** `organization_id`/`project_id` are stamped directly from the source recommendation doc (`rec.get("organization_id")`/`rec.get("project_id")`, lines 3713-3714) — so provisional agents ARE org-bound at creation, contrary to a naive assumption that "provisional" might mean "unscoped." Authorization on the call itself: `handoff_recommendation` checks `rec.get("owner_id") != user_id` and raises `PermissionError` if mismatched (line 3692-3693) — i.e., only the recommendation's own owner can trigger materialization.
- **Visibility:** `lifecycle_state="provisional"` is intended to be excluded from dashboard/list queries "until finalize reveals it" (comment at lines 3715-3718) — this is a documented intent in-code, not independently verified here against the actual list-query filters (those live in agent-design/studio-backend, out of this repo's scope). Flagged as OPEN QUESTION (cross-repo).
- **Idempotency:** re-entrant — if `rec.built_agent_id` already exists, the existing id is returned without a duplicate write (lines 3695-3704).
- **Classification: VERIFIED CURRENT.** The provisional-agent-before-user-consent pattern described in the soul map is real, exercised via a concrete background task, and is org/owner-scoped at write time.

---

## 4. Guardrails and authorization (`alchemist/agents/guardrails.py`, `orchestrator_core.py`, `judge.py`)

- **`GuardrailGate`** (`alchemist/agents/guardrails.py`) is a pure, deterministic, **non-LLM** classifier: `classify(tool_name) -> RiskTier ∈ {SAFE, CONFIRM, HARD_BLOCK}` based on verb-prefix allow/deny lists (lines 13-23) plus an explicit `blocked_tools` set. Unknown verbs fail safe to `CONFIRM`, never auto-run (line 70, comment "fail-safe: unknown verb confirms, never auto-runs"). A second policy, `GuardrailPolicy.VIBE_BUILD`, implements deny-by-default for the Vibe conductor: only read-prefixed tools plus a small explicit allowlist (`_VIBE_CONDUCTOR_ALLOWLIST`, lines 37-47: `set_current_organization, save_current_project, save_current_agent, handoff_to_cortex, consult_lumen, open_support_ticket, ask_user`) are `SAFE`; everything else `HARD_BLOCK`s (lines 72-79).
- **Enforcement point:** `OrchestratorCore` (`alchemist/agents/orchestrator_core.py`) — constructed with `guardrail_gate=GuardrailGate(policy=GuardrailPolicy.VIBE_BUILD)` for Vibe dispatch, **only when `ALCHEMIST_REWORK_ENABLED` is truthy** (`vibe_dispatch.py:80-92`, via `_rework_enabled()`), which per §1d defaults `"true"` in `env.template.yaml`. Inside the turn loop, every tool call is classified BEFORE execution (`orchestrator_core.py:288`); `HARD_BLOCK` stops execution (line 289), `CONFIRM` requires explicit user approval (line 299). This is enforced **in code**, not merely described in a prompt — confirming the soul map's claim exactly.
- **Judge (two-phase verify):** `Judge.verify()` (`alchemist/agents/judge.py:42-81`) wraps `synapse_judge.judge_answer_against_evidence`, invoked from `orchestrator_core.py:230,242` after tool execution when a draft answer exists. **Fail-open is explicit and intentional**: any transport exception (429/5xx/auth/network) or a malformed/`skip`/`error` rubric returns `verdict="approve"` with the unmodified draft (lines 46-72) — i.e., the Judge can never itself block a turn on infra failure, only on an actual "not supported by evidence" verdict from a successful judge call. This matches the soul map's "fail-open on transport" claim precisely.
- **Organization scoping on fleet actions:** no blanket org check exists inside `GuardrailGate`/`Judge` themselves (they are tool-risk and evidence-verification concerns, not tenancy concerns). Org scoping instead lives at the data-write layer per-store (e.g., `vibe_sessions.list_for_user()` §2, `agents/{id}.organization_id` §3, `nexus_agent.py` session-ownership gate below) rather than as a single central authorization chokepoint.
- **Nexus session-ownership gate:** `_session_owner()` + explicit `owner != user_id` cross-user-write block, logged as `[NEXUS] cross-user write blocked` (`alchemist/agents/nexus_agent.py:41,118-126`), and the same check on reads (`:381-389`). Confirms the soul map's "session-ownership-checked writes" claim for Nexus.
- **Classification: VERIFIED CURRENT** for all of: code-enforced (not prompt-only) tool classification, fail-open Judge, and Nexus per-session ownership checks.

---

## 5. Corrections to prior soul-map claims

The soul map's §07 ("Alchemist fleet today") was explicitly read from a snapshot 210 commits behind origin/main. Against this fresh clone at `8720720`:

| Claim | Status | Detail |
|---|---|---|
| Context Service is "an immutable event log, bi-temporal facts, scoped guardrails, and native window management" | **CONFIRMED** | All four components verified in source: `context_logs` (log_store.py), `context_facts` bi-temporal facts with `t_valid`/`t_invalid` (facts.py/facts_store.py), `context_guardrails` (guardrails_store.py), and `window.py`'s native `context_management.edits`. |
| `context_facts` is the actual collection name | **CONFIRMED** | `facts_store.py:11`. |
| Bi-temporal | **CONFIRMED** | `t_valid`/`t_invalid`/`superseded_by`/`created_at`/`updated_at` on every `ContextFact`, invalidate-don't-delete semantics enforced in `supersede()`/`decay()`. |
| Scopes GLOBAL, ORG, PROJECT, AGENT, SESSION | **PARTIALLY CONFIRMED** | All five exist in `scope.py`'s `ScopeLevel` enum and are usable via `context_routes.py`. But **every live turn-time write/read path** (`vibe_record.py`, `vibe_dispatch.py`, `orchestrator_agent.py`, `agentify_agent.py`, `synapse_agent.py`, `context_broker.py`, `routes.py`) constructs `ContextService` with `ScopePath(session=...)` only — ORG/PROJECT/AGENT scopes are reachable **only** through the CRUD surface, which is dark (`CONTEXT_CRUD_ENABLED="false"`). So today's *actually populated* scopes are effectively GLOBAL and SESSION only. |
| Live in prod behind `CONTEXT_SERVICE_ENABLED` | **CONFIRMED** | Flag default is `"true"` in `env.template.yaml:93`, the file rendered at deploy time. |
| Cross-agent "context lake" ... dark behind `VIBE_CONTEXT_CONVERGENCE_ENABLED` | **CONTRADICTED** (flag value, not existence) | The mechanism (`vibe_record.py` routing Vibe writes through the shared Context Manager) exists exactly as described, but the flag's *default in this fresh clone is `"true"`* (`env.template.yaml:52`), not dark — the soul map's "dark" characterization is stale. Comment in the template itself says it "Went LIVE... Merged dark via PR #358" — i.e. it shipped dark and was **since flipped on**. |
| "verify-before-active" gate is real | **CONFIRMED** | `Consolidator.consolidate()` never promotes an uncited or judge-unsupported candidate; explicit "NO fail-open here" comment and matching code (`consolidation.py:88-97`). |
| Provisional `agents/{id}` writes before user says yes (`_maybe_materialize_and_build`) | **CONFIRMED** | Exact function name and behavior found at `vibe_dispatch.py:369-431`, writer `agentify_agent.py:handoff_recommendation(..., lifecycle_state="provisional")`. |
| `GuardrailGate` classifies SAFE/CONFIRM/HARD_BLOCK in code | **CONFIRMED** | Pure deterministic classifier, not prompt-only; enforced at `orchestrator_core.py:288-299`. |
| Two-phase Judge, fail-open on transport | **CONFIRMED** | `judge.py:42-72`. |
| Both guardrails+Judge live behind `ALCHEMIST_REWORK_ENABLED`, pinned in `env.template.yaml` | **CONFIRMED** | Flag `"true"` at `env.template.yaml:83`; gate at `vibe_dispatch.py:80-92`. |

**New finding not in the prior soul map:** the fact-consolidation pipeline (`CONTEXT_CONSOLIDATION_ENABLED`) and the guardrail CRUD surface (`CONTEXT_CRUD_ENABLED`) are both **off** in the current deploy template — meaning the "Forge session facts (Context Service)" row in the soul map's inventory table describes a store (`context_facts`) whose *promotion pipeline* does not currently run in production, even though the underlying log it's derived from (`context_logs`) is actively written. This materially qualifies "Forge session facts" as a store that exists structurally but is not currently being populated at scale.

---

## 6. Open Questions

1. **True live Cloud Run env values.** `env.template.yaml` is a deploy-time template; the repo's own comments describe at least two historical incidents where a flag was flipped live via `gcloud` and then silently wiped by the next template-based deploy (`ALCHEMIST_REWORK_ENABLED`, `VIBE_OPERATE_ENABLED` — see comments at lines 58-60, 77-83). This means the template is very likely the *current steady-state* value (both incidents describe the template being the value that "wins" after any deploy), but an out-of-band, not-yet-redeployed manual flip cannot be ruled out from source alone. Verifying the actual running revision's env vars (`gcloud run services describe olbrain-agent-engine --format=...`) is outside this repo and outside read-only source investigation.
2. **PII sensitivity of `context_logs`/`context_facts` payloads.** Confirmed these can carry raw/distilled conversational text from Forge design sessions, but this repo alone can't confirm whether real end-customer PII (as opposed to design-time B2B conversation about an agent-to-be-built) ever flows into a Vibe session's `context_logs` — that depends on what a founder/builder actually types during the Forge/Vibe conversation, which is unbounded free text. Soul map calls this "low, design conversation" — plausible given the use case (an internal fleet helping an operator design an agent) but not something source code can bound.
3. **Erasure/GDPR path for `context_logs`/`context_facts`/`vibe_sessions`.** No delete/erasure route for any of these three stores was found in this repo. Whether GDPR erasure is handled by a separate, cross-cutting deletion service outside `agent-engine` (e.g. in studio-backend, as referenced for `agents/{id}` teardown via `agent_transfer_service._ORG_SCOPED_TEARDOWN_STEPS` per the soul map) is an OPEN QUESTION requiring investigation of studio-backend or another repo, not covered by this pass.
4. **Provisional-agent list-query exclusion.** `handoff_recommendation`'s comment asserts `lifecycle_state="provisional"` agents are excluded from dashboard/list views "until finalize reveals it," but the actual filtering logic lives in a consumer (agent-design/studio-backend), outside `agent-engine`. Not verified in this pass.
5. **Whether `ORG`/`PROJECT`/`AGENT` Context-Service scopes are populated by ANY other path not found by this grep-based sweep** (e.g. a batch job, an admin tool, or code added after this repo's tests were written). All call sites found via `grep -rn "ContextService(" --include="*.py"` across the whole repo were enumerated (10 non-test call sites); none pass org/project/agent. Confidence is high but not absolute for a 46.7k-LOC repo swept by targeted grep rather than exhaustive read.
6. **Actual population level of `context_facts` in the live Firestore database** (row counts, whether any org ever flipped `CONTEXT_CONSOLIDATION_ENABLED` locally/per-environment) cannot be determined from source code alone — would require a Firestore data query, which is out of scope for a read-only source investigation.

---

## Evidence index (file:line, HEAD `8720720`)

- `alchemist/context/service.py` — ContextService facade (record/retrieve/window_config/guardrails_resolve/active_facts/maybe_consolidate)
- `alchemist/context/log_store.py:8-16,28-44,83-96` — `context_logs` collection layout, append idempotency
- `alchemist/context/facts.py`, `alchemist/context/facts_store.py:11` — `context_facts` collection, bi-temporal schema
- `alchemist/context/consolidation.py:65-115` — verify-before-active gate
- `alchemist/context/guardrails_store.py:12` — `context_guardrails` collection
- `alchemist/context/scope.py`, `alchemist/context/ownership.py` — scope cascade + IDOR checks
- `alchemist/context/__init__.py:1-63` — all feature-flag getters
- `context_routes.py` — CRUD surface, dark behind `CONTEXT_CRUD_ENABLED`
- `alchemist/context/vibe_record.py` — Vibe→Context Manager convergence chokepoint
- `env.template.yaml:44-110` — live deploy-time flag defaults
- `alchemist/schemas/vibe_session.py`, `alchemist/services/vibe_session_service.py` — `vibe_sessions` schema/service
- `vibe_dispatch.py:80-92,369-431` — rework gate, provisional materialization
- `alchemist/agents/agentify_agent.py:3672-3763` — `handoff_recommendation` (provisional `agents/{id}` write)
- `alchemist/agents/guardrails.py`, `alchemist/agents/orchestrator_core.py:111-299`, `alchemist/agents/judge.py` — GuardrailGate + Judge enforcement
- `alchemist/agents/nexus_agent.py:41,118-126,381-389` — Nexus session-ownership gate
