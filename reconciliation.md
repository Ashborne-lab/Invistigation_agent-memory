# Reconciliation Pass 1 — Current Production vs. Target Architecture

Review date: 2026-09-19. Inputs: `investigation/store-inventory.md` (ten repos, both
investigation passes), `artifacts/architecture-contract.md` (the target State Semantics
Contract v2.0), `artifacts/senior-feedback.md`, `artifacts/repo-and-soul-map.md`.

**What this document is:** the first pass at the five-stage pipeline the user asked for —
CURRENT PRODUCTION → LEGACY/IN-FLIGHT → SECURITY+DATA GAPS → TARGET STATE ARCHITECTURE → WHAT
THE HTML ARTIFACT NEEDS TO CHANGE. Sections 1–3 assemble what's already verified in
`store-inventory.md`; they do not re-investigate. Section 4 is comparison against the contract,
not implementation. Section 5 is a change-list, not a change.

**What this document is not:** an implementation plan, a modification of
`state-semantics-explorer.html`, or a decision about which gap to fix first. Per `CLAUDE.md`'s
critical rule, the HTML artifact is not touched by this pass — section 5 stops at describing
what it would need to change.

---

## 1. CURRENT PRODUCTION

What actually exists and runs today, per the full ten-repo investigation. Grouped by the
contract's own vocabulary where a current store has an obvious analog, and left ungrouped where
it doesn't (forcing a mapping here would be assembly pretending to be analysis — the real
mapping work is section 4).

**Evidence-like (append-only, or close to it):**
- `agent_messages/{id}` — per-turn conversational record, plaintext content, org derived via parent session.
- `context_logs/{scope_key}/events/{id}` (agent-engine) — genuinely immutable, append-only, idempotent-on-id; the closest current analog to an Evidence Log, but populated only at SESSION/GLOBAL scope in every live call site.
- `learning_ledger` (research) — append-only intake of LLM-synthesized, third-person statements, explicitly documented as having "no API to delete one."
- `protection_events` (agent-runtime audit) — durably persisted, append-only event stream.

**Claim-like or state-machine-like (mutable, resolved, or transitioning):**
- `context_facts` (agent-engine) — bi-temporal (`t_valid`/`t_invalid`), `candidate → active/invalid` status, `superseded_by` chain, genuine verify-before-active gate. The single closest existing structural analog to the contract's Claim object anywhere in the platform.
- `research_runs.phase`/`status` (RunMeta) — a real phase progression (PLANNING→GATHERING→WRITING→RENDERING→DELIVERING→REVIEW→GAPFILL) on a mutable Firestore doc.
- `workflow_runs.status` + `orchestrator_generation` — status progression plus an integer fencing counter, incremented on every resume/retry specifically so a stale in-flight orchestrator pass exits rather than racing a newer one.
- `vibe_sessions.active_conversant.state` (agent-engine) — a small state machine (`alchemist/cortex/synapse/multi_party/awaiting_user`), written exclusively through a Firestore transaction.
- `workflow_agent_memory.learned_overrides[].status` — `suggested → active → retired`, plus a `contradiction_count` field.
- `learning_service.write_profile(..., expected_version=profile.version)` (research-design) — a genuine compare-and-swap write, raising `ProfileVersionConflict` on a version race, retried up to a fixed attempt count.

**Memory-like (retained knowledge, non-assertive or heuristic):**
- `agent_user_memory` — a single, wholesale-rewritten, per-(agent,user) profile blob (facts + field values), no versioning.
- `agent_datastores` — structured per-person or per-session rows, three independent writers, no versioning, no claim/evidence trail.
- `agent_learned_patterns` — tool-call heuristics with verbatim example text, usage/failure counters, no assertive (subject,predicate,object) shape.
- `agent_sessions.summary`/`memory_anchor_ts` — rolling narrative summary, explicitly non-assertive.
- `research_templates/{id}/learned/{profile,design,substance}` — design/behavioral overlay documents, existence-gated merge into template bodies.
- knowledge-vault's DCI corpus — plain extracted text in GCS, retrieval by regex/agentic grep, not embeddings; a genuinely rebuildable, non-authoritative retrieval projection.
- `lead_profiles`/`lead_contacts` — plaintext-then-hashed contact records, no claim structure.

**Config/identity/credential (outside the contract's five object classes entirely):**
- `agents/{id}`, `active_config.json`, `agents/{id}/mcp_configs/*`, `organizations/{org}/connector_credentials`, `organization_api_keys` — design-time and operational configuration, not memory or state in the contract's sense. The contract does not attempt to model these, and this document does not force a mapping onto them.

## 2. LEGACY / IN-FLIGHT

Pulled directly from `store-inventory.md`'s Migration Status Summary — see that file for full
evidence. Grouped here by what kind of transition each one represents.

**Mid-migration, both old and new paths live simultaneously:**
- `agent_user_memory` → `agent_datastores`, gated per-`wanted_sets`-entry via a `legacy: True` flag (not a module-level switch). Three independent writers now confirmed into `agent_datastores`.
- `workflow_definitions` inline-JSON body → Firestore-metadata-doc + Storage-body-blob split. The shared package's own code states the legacy fallback "is expected to go away once the one-time migration script has run in prod" — that script was not located anywhere in the ten repos reviewed.
- research-design's `/pubsub/learn-design` exemplar-reconstruction route → unified `job_type` dispatch, explicitly named "Phase 5" in code.

**Fully retired (legacy, not in-flight — confirmed dead, not merely deprioritized):**
- knowledge-vault's Firestore-embeddings design and OpenAI Assistants Vector Store integration → the current GCS-text "DCI" system. Zero live readers or writers of the old path.
- The old Firestore config service (`config/firestore_config.py`) → `active_config.json` from GCS. Used only by an old `Agent` class construction path whose live reachability is itself an open question, not a confirmed-live secondary path.
- research-design's `org_id==""` cross-org template-leak bug → fixed in code (deny instead of coerce); a one-time backfill script remains for historical rows.

**Structurally shipped but dormant (doesn't fit either label cleanly — flagged, not forced):**
- agent-engine's Context Service multi-scope hierarchy (ORG/PROJECT/AGENT) exists in schema and CRUD-surface capability but is populated by zero live write paths (session/global only). Fact-consolidation promotion is flag-disabled (`CONTEXT_CONSOLIDATION_ENABLED=false`) even though the log it would consolidate is actively written. This is real, shipped code that nothing is migrating *from* and nothing is migrating *toward* — it sits in a state the contract's classification scheme has no label for, and this document does not invent one.

## 3. SECURITY + DATA GAPS

Consolidated from `store-inventory.md`'s Security Findings A–H, prioritized by severity rather
than by repo. Full evidence lives there; this is triage ordering, not new analysis.

**P0 — live production authorization gaps, independent of this architecture program:**
1. `agents/{id}` — the platform's central agent-ownership document — is readable and writable by any signed-in platform user, any org, via a Firestore catch-all rule that supersedes a real, named ownership check the file's own comments describe as "dormant." This is broader and more severe than session/message exposure: it governs every agent on the platform, including reassignment of `owner_id`/`organization_id`.
2. `organizations/{org}/connector_credentials` — readable and writable by any signed-in user with **no organization-membership check of any kind** (not even a weak one — there is no `orgId` predicate in the matching rule at all).
3. `agent_sessions`, `agent_messages`, `context_logs`, `context_facts`, `context_guardrails`, `vibe_sessions`, `research_templates`, `workflow_definitions`, `workflow_agent_memory`, and the top-level `research_runs` document — all readable and writable (not merely readable) by any signed-in user, any org, via the same unexcluded-catch-all mechanism. Several of these (`agent_learned_patterns`, `context_logs`) have a real, tighter rule sitting right next to the hole, provably dead.
4. None of the above is exercised by any test in the repo's own `tests/firestore-rules/` suite, and that suite's own README states CI does not gate on it — these are not merely undiscovered, they are unverified in the one place the platform has built the tooling to verify them.

**P1 — structural, cross-store patterns (not one repo's bug):**
5. "No organization_id on the individual row, only on a parent" recurs, now schema-confirmed (not just usage-confirmed), across `agent_datastores` entries (all three writers), `agent_learned_patterns`, `workflow_agent_memory`, and every research "learned"/ledger model.
6. Verbatim or near-verbatim end-user/business content recurs across three independently-built "learning" stores in three different repos with no shared design lineage.
7. `agent_datastores`' and `agent_user_memory`'s person-keying hash (`person_hash()`/`memory_doc_id()`) is confirmed unsalted, deliberately shared between the two schemes by design — any guessable phone/email can be matched offline against a leaked entry id.
8. The application-layer authorization gaps (workflow-runtime's routers, agent-engine's dark Context CRUD) and the Firestore-rules gaps above are independent, compounding failures — fixing one layer does not fix the other, and for several stores (`workflow_agent_memory`, `context_facts`, `context_guardrails`, `vibe_sessions`) both layers are simultaneously open.

**P2 — deletion/lifecycle gaps:**
9. There is no hard organization-delete capability anywhere in the platform — only a soft archive/restore, entirely disjoint from the cross-org agent-transfer cascade.
10. That transfer cascade itself excludes `agent_datastores` and `agent_learned_patterns` entirely — an agent's most sensitive per-person data does not follow (or get cleaned up on) an org transfer, while `workflow_agent_memory` at least gets archived-and-deleted.
11. No GDPR/erasure route exists anywhere in the ten repos for `context_logs`, `context_facts`, `vibe_sessions`, or the `research_templates`/`research_runs` family.

**What is provably working correctly, for calibration:** `agent_datastores`' Firestore rule (fully denied, tested, deliberate 2026-09 fix), `agent_user_memory`'s org-scoped read rule, `organization_api_keys`' IDOR-safe revoke flow, `organization_documents`' genuine hard-delete-plus-deindex, and the `clix-capital-prod` dedicated-tenant ruleset (genuinely default-deny, separately maintained). The gap is coverage and prioritization on a rules file the team is visibly and actively hardening one collection at a time — not a lack of institutional ability to do this correctly.

## 4. TARGET STATE ARCHITECTURE — mapping, not migration

For each current mechanism, where it would land in the contract's Evidence → Claim → Predicate
Policy → Current State / Memory model, or an explicit statement that it doesn't map cleanly and
why. This section compares; it proposes no schema, no code, no migration order.

| Current mechanism | Contract concept it resembles | Fit | What's missing to actually be one |
|---|---|---|---|
| `context_logs` (agent-engine) | **Evidence** | Good — append-only, immutable, source-position-ish ordering exists implicitly via Firestore write order | No explicit `source_position` (partition+offset); no evidence beyond SESSION/GLOBAL scope; not the sole evidence plane (other repos write their own ad hoc "evidence," e.g. `learning_ledger`, with no shared log) |
| `context_facts` (agent-engine) | **Claim** | Closest analog in the whole platform — bi-temporal validity, `candidate→active/invalid`, verify-before-active, invalidate-don't-delete | No Predicate Policy Registry (no per-predicate authority/cardinality/conflict rules); no `(subject, predicate, object)` shape — facts are freeform LLM extractions, not typed assertions; no `state_version`/OCC; scope is session/global only, never resolves the contract's required "one authoritative slot per scope" |
| `learning_service.write_profile(expected_version=...)` (research-design) | **Mutation contract's `expected_version` / OCC** | A genuine, already-working fragment — CAS write, typed conflict (`ProfileVersionConflict`), retry-with-limit | Not generalized: this exists only for one store, in one repo, invented independently; no shared `MutateState`/`STATE_CONFLICT` contract, no `expected_status`, no state-machine-precondition layer |
| `orchestrator_generation` (workflow-runtime) | **Fencing / OCC-adjacent, and a fragment of `scope_generation`'s deletion-protection role** | A real, independently-invented fencing counter preventing stale-pass races | Scoped to one run, not a `scope_generation(scope_id)` per deletable scope class; doesn't protect against deletion racing a write, only against two orchestrator passes racing each other — a narrower problem than §10's generation model solves |
| `agent_user_memory`, `agent_datastores` | **Memory (structured) — but implemented as a mutable blob, not Claims** | Poor — this is precisely the contract's rejected pattern ("giant mutable state JSON... rejected — independently versioned State Slots") applied at person-scope instead of at customer-scope | No Predicate Policy per field; no Claim layer beneath the stored value (a fact is just overwritten, not superseded-with-history the way `context_facts` already does it two repos over); no OCC; no OCC-driven conflict detection between the three independent `agent_datastores` writers |
| `agent_learned_patterns`, `workflow_agent_memory.exception_patterns`/`learned_overrides` | **Memory (heuristic) — closer to Narrative Memory than to Claim, but not quite either** | The contract's Narrative Memory category ("non-assertive... the tone of a previous conversation... discussion sequence") doesn't quite fit a *procedural* heuristic ("this tool sequence worked for this kind of failure") either — this is a third shape the contract doesn't explicitly name | Open question, not a gap to silently resolve: does the target architecture need a heuristic/procedural memory category alongside Claim and Narrative Memory, or does `LearnedOverride`'s `field`/`correction`/`status` shape actually fit the Claim model better than it first appears (predicate = "the correct value for this field given this selector", authority_domain = something like `OPERATOR_CORRECTION`)? This document does not decide it. |
| `research_runs.phase`, `workflow_runs.status`, `vibe_sessions.active_conversant.state` | **StateSlot with `STATE_MACHINE` cardinality** | Structurally plausible — each is a real, bounded transition graph on a scoped subject | None currently declare a Predicate Policy, none check `expected_status` before a transition (workflow-runtime's status-gating in `workflow_triggers.py` checks legality by convention, not via a policy-driven `allowed_operations_by_status` table), and none separate "the transition command" from "a raw field write" the way §7 requires |
| knowledge-vault's DCI corpus | **Retrieval Projection** | Good — explicitly non-authoritative, rebuildable, content-hash-addressed, exactly the contract's "candidate memory object" role before any authorization/validity/policy filtering | No `consumed_through_position` watermark of any kind (freshness is undefined, not merely un-enforced); no claim-level structuring — the contract requires "memory... structured at claim level rather than treating a whole text chunk as one truth unit" (§8), and DCI's retrieval unit is a raw text span, not a claim |
| `agent_sessions.summary` | **Narrative Memory** | Good, clean fit — explicitly non-assertive, time-bounded, already labeled as a "summary" rather than a fact | Missing the contract's required fields (`scope`, `provenance`, `retention_class`, `security_class`, `status`) — it's a bare string plus a timestamp today |
| Every async "learning" pipeline (agent-runtime's extract-mode kickoff, agent-engine's `maybe_consolidate`, research-design's `run_learn_agent`) | **The §9 crossing rule: "asynchronous memory MUST NEVER bypass the State Mutation Contract... it submits a candidate or state-mutation request through the same policy engine"** | **This is the single largest structural gap in the whole comparison.** Every current async pipeline writes directly to its final store. None of them submits anything resembling a policy-gated candidate mutation. `context_facts` gets the closest (candidate→active gate) but that gate is a bespoke, one-repo mechanism, not a shared policy engine any of the other five async pipelines route through. | Not a small gap — this is the contract's central invariant (§9, §12 rule 5) and it is verifiably absent as a *shared* mechanism anywhere in current production, even though isolated fragments of the right idea (CAS writes, generation fencing, verify-before-active) already exist independently in three different repos |
| `agents/{id}`, `active_config.json`, credentials | **Not modeled by the contract** | N/A | The contract explicitly scopes itself to Evidence/Claim/State/Memory; agent configuration and credentials are a different concern (closer to the contract's own "MVP infrastructure boundary" exclusions) and this document does not force them into the five-class model |

**The clearest single sentence this section supports:** three or four isolated, independently-invented fragments of the target architecture's core mechanisms (a bi-temporal claim store, a CAS write, a fencing counter, a verify-before-promote gate) already exist in production, in three different repos, with no shared policy engine connecting them — which means the target architecture is not being proposed into a vacuum, but the platform has also not organically converged on it either.

## 5. WHAT THE HTML ARTIFACT NEEDS TO CHANGE — a change-list, not a change

`state-semantics-explorer.html` today models only the target architecture: the Evidence→Claim→
Policy→Resolution pipeline, the Predicate Policy Registry, resolution traces, projection
freshness, deletion+lineage, entity resolution, and a query playground — all built from
`architecture-contract.md` alone, with no reference to what production actually does. Based on
sections 1–4 above, here is what it would need to represent the *current* state alongside the
target, if and when that reconciliation is authorized:

1. **A "current vs. target" mode, not just a target-only explorer.** Every existing panel (the
   pipeline diagram, the Predicate Policy Registry, the resolution trace, the state result
   matrix) currently has no current-state counterpart to compare against. The explorer would
   need either a toggle or a side-by-side view showing, for a given store, what production does
   today next to what the contract says it should do.
2. **A gap-annotation layer keyed to store-inventory.md's classification scheme.** Six labels
   (VERIFIED CURRENT / LEGACY / IN-FLIGHT MIGRATION / TARGET ARCHITECTURE / OPEN QUESTION /
   CONTRADICTED BY SOURCE) exist in the investigation but have no visual representation anywhere
   in the explorer today. The explorer's existing badge system (`.b-VALUE`, `.b-CONFLICT`, etc.)
   is a plausible template to extend for this, since it already has a working
   color/badge-per-status convention.
3. **A security-severity overlay for the Firestore-rules findings specifically.** Section 3's P0
   findings (`agents/{id}`, `connector_credentials`, and nine other collections openly readable/
   writable by any signed-in user) are the single most concrete, evidence-dense finding this
   investigation produced, and they have no natural home in an explorer built around the target
   architecture's abstractions — the target contract doesn't model Firestore rules at all; it
   models authorization as a policy-engine concept (§6, "Authorization is not part of state
   resolution... controls who may read the resolved state"). Whether this belongs in the
   explorer at all, or in a separate security-tracking artifact, is an open design question this
   document raises rather than answers.
4. **A "structural fragments already in production" panel**, surfacing the four items in section
   4's mapping table that already partially implement target concepts (`context_facts`'
   verify-before-active gate, `write_profile`'s CAS pattern, `orchestrator_generation`'s fencing,
   `agent_sessions.summary`'s Narrative-Memory shape) — these are the strongest evidence that the
   target architecture is achievable incrementally rather than as a rewrite, and the explorer
   currently has no way to say "this already exists, partially, here."
5. **An explicit "no mapping" state for config/credential stores** (`agents/{id}`,
   `active_config.json`, `mcp_configs`, `connector_credentials`) — the explorer's data model is
   built entirely around the five object classes (Evidence/Claim/Current State/Memory/Narrative
   Memory); these stores don't belong to any of them, and the explorer would need a way to show
   "out of scope for this contract" rather than forcing a poor-fit label onto them.
6. **A resolution mechanism for the one open modeling question section 4 raised and did not
   answer**: whether heuristic/procedural memory (`agent_learned_patterns`,
   `workflow_agent_memory`'s exception patterns and overrides) needs a category the contract
   doesn't currently name, or maps onto Claim more cleanly than it first appears. This is a
   content question for `architecture-contract.md` itself, not an explorer-UI question — flagged
   here because it would block item 1 (the current/target comparison view) for those two stores
   specifically until it's resolved.

**None of the above is implemented in this pass.** `state-semantics-explorer.html` remains
unmodified. Per `CLAUDE.md`'s critical rule, the next step for the explorer itself requires
explicit user authorization, separate from the investigation and reconciliation work being
approved and executed here.
