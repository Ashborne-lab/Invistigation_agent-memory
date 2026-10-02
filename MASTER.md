# OLBrain Architecture Research — Master State

## Mission

Build a verified map of OLBrain's CURRENT production architecture before implementation.

The investigation focuses on:

- memory
- state
- sessions and messages
- learned memory
- Context Service
- research learned overlays
- workflow memory
- knowledge stores
- configuration
- authorization and organization scoping
- privacy and deletion
- current vs legacy vs in-flight migrations

The target architecture is described in:
`artifacts/architecture-contract.md`

The current production landscape is described and must be verified against source in:
`artifacts/repo-and-soul-map.md`

## Safety Boundary

This workspace is an investigation sandbox.

The cloned OLBrain repositories are READ-ONLY unless the user explicitly authorizes a change.

DO NOT:

- modify production source code
- modify Firestore rules
- run migrations
- write to production databases
- deploy anything
- create PRs
- push commits
- change infrastructure
- change production configuration
- silently "fix" anything discovered during investigation

Investigation comes before implementation.

## Existing Source Material

Read these before starting any new investigation:

1. `artifacts/architecture-contract.md`
2. `artifacts/current-storage-review.md`
3. `artifacts/repo-and-soul-map.md`
4. `artifacts/senior-feedback.md`
5. `artifacts/state-semantics-explorer.html`

These are existing project knowledge. Do not restart the architecture analysis from zero.

## Important Distinction

Keep these concepts separate:

CURRENT SYSTEM
- what the production repositories actually do today

LEGACY
- an older path that still exists but is no longer the primary live path

IN-FLIGHT MIGRATION
- a transition where both old and new paths may coexist

TARGET ARCHITECTURE
- the proposed State / Memory architecture in the contract

OPEN QUESTION
- something that has not yet been verified from source

Never silently convert one category into another.

## Current Repository Set

The investigation workspace currently contains:

- `olbrain-agent-runtime`
- `olbrain-agent-engine`
- `olbrain-research-design`
- `olbrain-research-runtime`
- `olbrain-workflow-runtime`
- `olbrain-knowledge-vault`

All were cloned from `main` and verified clean at workspace setup.

Recorded local HEADs at setup:

- agent-runtime: `b2401a0`
- agent-engine: `8720720`
- research-design: `d044fce`
- research-runtime: `d1caecd`
- workflow-runtime: `5d48437`
- knowledge-vault: `6d76083`

## Known Architecture Context

The current understanding is broader than `agent-runtime`.

The documented Soul inventory includes, among other things:

- Context Service facts
- knowledge corpora
- research learned profiles/designs
- learned tool-call patterns
- per-person facts
- structured memory values
- rolling session summaries
- leads and contacts
- workflow memory
- Engram
- audit/protection events
- credentials and MCP bindings

This inventory must be verified against source rather than assumed.

## Senior Review Corrections Already Known

The previous runtime-only picture was incomplete.

Known corrections requiring source verification:

1. Extract-mode memory writes to `agent_datastores`; the legacy path is `agent_user_memory`.
2. The live conversational config path is `active_config.json`; the old Firestore config service is legacy.
3. MCP bindings are held under `agents/{id}/mcp_configs/*`.
4. The unsalted person hash has privacy implications.
5. Session documents can contain plaintext phone/profile information.
6. Session/message authorization needs explicit organization-scoped verification.
7. Learned patterns contain verbatim end-user material and lack an organization field.
8. The memory/data landscape includes stores outside `agent-runtime`.

## Investigation Method

For every important store or data path, determine:

- exact store / collection / bucket / path
- owning repository
- writer(s)
- reader(s)
- write path
- read path
- data shape
- scope
- organization binding
- PII
- authorization enforcement
- deletion / retention behavior
- current / legacy / in-flight status
- evidence from source

Prefer evidence from:

- `origin/main`
- exact file path
- exact symbol/function/class
- commit/ref

Do not infer when source can verify the answer.

## Investigation Priority

Start with data ownership, not repository breadth.

Priority:

1. `olbrain-agent-runtime`
2. `olbrain-agent-engine`
3. `olbrain-research-design`
4. `olbrain-research-runtime`
5. `olbrain-workflow-runtime`
6. `olbrain-knowledge-vault`

Expand only when a verified dependency requires another repository.

## Initial Stores to Verify

- `agent_user_memory`
- `agent_datastores`
- learned patterns
- sessions
- messages
- Context Service / `context_facts`
- research learned profiles/designs
- `workflow_agent_memory`
- knowledge-vault
- leads / contacts
- Engram
- active runtime configuration
- MCP bindings
- credentials

## Current Progress

Completed:

- architecture contract established
- current Firestore/storage review established
- State Semantics Explorer established
- cross-repository / Soul map established
- senior review corrections captured
- investigation workspace created
- six source repositories cloned
- repository working trees verified clean (all match `origin/main` except `olbrain-research-runtime`, one merge commit behind — confirmed unrelated to every finding below)
- five artifact files placed in `artifacts/`
- **first source-verification pass complete for all six priority repositories** (2026-09-19): `investigation/repo-notes/olbrain-agent-runtime.md`, `olbrain-agent-engine.md`, `olbrain-research-design.md`, `olbrain-research-runtime.md`, `olbrain-workflow-runtime.md`, `olbrain-knowledge-vault.md`
- **second source-verification pass complete for all four dependency-gap repositories** (2026-09-19, same day): `investigation/repo-notes/olbrain-studio.md` (Firestore rules only, scoped), `olbrain-shared.md`, `olbrain-studio-backend.md`, `olbrain-agent-design.md` — all four repos were already present in the workspace and already matched `origin/main`, no cloning was needed
- `investigation/store-inventory.md` updated in place: now covers all ten repos, with a platform-wide section for stores that don't belong to any single owning repo (`agents/{id}`, `connector_credentials`, org-deletion), a definitive Firestore-rules verdict per collection (Security Finding E, previously unresolved), and a deletion/transfer-cascade analysis
- `investigation/reconciliation.md` created: the first CURRENT → LEGACY/IN-FLIGHT → SECURITY+GAPS → TARGET ARCHITECTURE → HTML-change-list pass, per the user's explicit five-stage request
- `investigation/architecture-decisions.md` created (2026-09-19): the five architecture decisions that gated modifying the explorer — 1a `LearnedOverride`→Claim via Predicate Policy, 1b procedural memory left deliberately unresolved, 2 annotation layer over toggle/side-by-side, 3 security findings kept out of the explorer, 4 `.mig-*` badge family, 5 fragments as an orthogonal flag
- **explorer reconciliation executed (2026-09-20)** — `artifacts/state-semantics-explorer.html` now carries the current-production annotation layer. See the Session 3 report at the end of this file.

In progress:

- none — both investigation passes and the explorer reconciliation are complete

Not yet completed:

- a small residual list of open questions that don't block reconciliation (see store-inventory.md's final section: storage-layer internals for `workflow_definitions`' Storage-body blobs, the `is_enabled` MCP spelling's origin, a frontend-only provisional-agent-filter question, `scripts/merge_organizations.py` semantics)
- **Decision 1b** — whether procedural/heuristic memory (`agent_learned_patterns`, `ExceptionPattern`) needs a sixth object class or an explicit out-of-scope statement. Requires the owner of `architecture-contract.md`. Annotated in the explorer as "no target-architecture mapping yet", never silently filed under Claim or Narrative Memory.

## Do Not Repeat

Do not rediscover or recreate the following unless new source evidence contradicts them:

- target state semantics already documented in the contract
- the existing State Semantics Explorer structure
- the initial Firestore memory review
- the senior review corrections listed above
- the repository/Soul inventory already captured in the artifacts

Instead, verify and extend them.

## Current Next Action

**This section supersedes the two Stop Condition Reports below, both of which still describe
the explorer as gated on authorization. That gate was opened and the work is done.**

Status as of 2026-09-20: both source-verification passes, the reconciliation, the architecture
decision gate, and the explorer annotation layer are all **complete**. Nothing in the
investigation program is outstanding except the two items under "Not yet completed" above.

The next action is a decision for the user, not more investigation. Two independent tracks:

1. **Decision 1b** — escalate the procedural-memory modelling question to whoever owns
   `architecture-contract.md`. Either a sixth object class (a multi-section contract change) or
   an explicit statement that procedural memory sits outside the five-class model. Until then
   `agent_learned_patterns` and `ExceptionPattern` stay annotated as "no mapping yet."
2. **Outside this program entirely** — the platform-wide Firestore-rules exposure (Security
   Finding E: `agents/{id}` and `organizations/{org}/connector_credentials` above all) is a live
   production authorization gap on its own timeline. It does not depend on the architecture
   program and should be routed to whoever owns `olbrain-studio`'s rules file.

Still do not implement the target architecture. No PostgreSQL, no Memory Gateway, no
migrations, no workers, no APIs, no production fixes.

**Note on `CLAUDE.md`:** its Critical Rule still reads "DO NOT modify the State Semantics
Explorer yet." That rule was explicitly and specifically lifted by the user for this one piece
of work on 2026-09-20, after the decision gate was complete; the authorization named
`artifacts/state-semantics-explorer.html` as the only artifact permitted to change. The rule
otherwise stands, and `artifacts/architecture-contract.md` was never in scope.

## Stop Condition Report (2026-09-19, first source-verification pass)

### 1. Verified findings

Full detail with file:line evidence lives in `investigation/repo-notes/*.md`; the consolidated,
cross-referenced table is `investigation/store-inventory.md`. Headlines:

- **agent-runtime**: all 8 senior-review claims addressed with source citations (7 CONFIRMED or
  CONFIRMED-with-detail-correction, one split CONFIRMED/OPEN QUESTION). `agent_datastores` has
  **two** independent writers (an extract-mode person-keyed upsert and a live agent-tool
  session-keyed insert) — the senior review only described the first. No HTTP route of any kind
  exists for `agent_datastores` entries; a code comment claiming one exists is stale.
- **agent-engine**: Context Service (`context_logs`, `context_facts`, `context_guardrails`) is
  real, non-trivial, bi-temporal, and code-enforces a genuine verify-before-active gate — but its
  multi-scope design (GLOBAL/ORG/PROJECT/AGENT/SESSION) is populated only at GLOBAL/SESSION in
  every live call site found, and fact-consolidation promotion is currently flag-disabled in the
  deploy template even though the underlying log is actively written.
- **research-design/-runtime**: the "opt-in overlay flag" claimed for learned-overlay resolution
  is **CONTRADICTED BY SOURCE** — resolution is unconditional at every load site once an overlay
  document exists. No `organization_id` field exists on learned records (confirmed). The G4
  "duplicate model catalog" finding is mostly **CONTRADICTED** at current HEADs — both repos now
  delegate the selectable catalog to a shared package — though each still hardcodes its own
  default-model constants and (research-runtime) an unshared context-window table.
- **workflow-runtime**: `workflow_agent_memory` has no organization_id field and — more
  significantly — **no application-level authentication anywhere in its main routers**, a
  materially weaker posture than every other repo reviewed. A previously undocumented
  `workflow_agent_memory_archive` mechanism is the platform's only real mitigation for the missing
  org field (wipes memory on agent org-transfer).
- **knowledge-vault** (first-ever read, no prior clone): the soul map's one-line description was
  incomplete — this is two generations of system layered together (a fully dead legacy
  Firestore-embeddings/OpenAI-Vector-Store design, and the current GCS-text-based "DCI" system).
  Scope is 4-way (agent/org/client-project/skill), not the 3-way previously claimed. Auth is OIDC
  only for machine-to-machine paths; Studio-facing ingestion uses Firebase tokens instead. No
  org-deletion cascade exists.
- **Cross-repo**: `agent_user_memory`/`agent_datastores` and `workflow_agent_memory` are confirmed,
  bidirectionally, to never read each other (soul map's G9, now fully verified both directions). A
  previously undocumented direct coupling was found: agent-runtime's `standup.py` reads
  `research_templates` directly from Firestore, bypassing research-design's service layer and its
  org-scoping guard entirely (best-effort, exception-swallowed, not a hard dependency).

### 2. Corrections to previous understanding

- Senior-feedback.md's 4 numbered claims: see each repo-note's "Corrections to Senior Review" /
  "Corrections to prior soul-map claims" section for the full CONFIRMED/PARTIALLY
  CONFIRMED/CONTRADICTED verdict on every sub-claim. None were fully contradicted; several were
  confirmed with a materially more precise mechanism than originally stated (see item 1 above).
- repo-and-soul-map.md's section 06 Soul inventory table required correction on: Context Service
  scope population (dark for ORG/PROJECT/AGENT), the `VIBE_CONTEXT_CONVERGENCE_ENABLED` flag
  (soul map said "dark," current deploy template says `"true"` — it shipped dark and was since
  flipped on), the research learned-overlay "opt-in flag" (does not exist), the G4 model-catalog
  duplication (mostly resolved at current HEADs), and the knowledge-vault scope/auth model (4-way
  scope, mixed OIDC/Firebase auth, not a single "OIDC, org-enforced" line).

### 3. Unresolved questions

Deduplicated list in `investigation/store-inventory.md`'s final section, organized by which
missing repository would resolve them. Highest-priority: whether `agent_datastores`' `person_hash()`
is salted (needs `olbrain-shared`); whether a Firestore catch-all rule actually makes
`agent_sessions`/`agent_messages`/etc. browser-readable across orgs (needs `olbrain-studio` —
this is the one open item that would fully resolve or refute the senior review's most serious
privacy claim); what protects workflow-runtime's unauthenticated routers (needs
`olbrain-studio-backend` or infra/IAM configuration, outside any repo).

### 4. Missing repositories or dependencies

- `olbrain-shared` — the pip/wheel package backing every repo's core Pydantic models; not vendored
  anywhere in this workspace.
- `olbrain-studio` — holds `firestore.rules`/`firestore.clix.rules`, the single artifact needed to
  confirm or refute the senior review's Firestore-catch-all claim.
- `olbrain-studio-backend` — provisions `organization_api_keys`, likely owns `organization_documents`,
  and is the presumed (unverified) home of any cross-service org-deletion cascade.
- `olbrain-agent-design` — the presumed home of any `agent_datastores` HTTP surface, the
  3-field org-resolution precedence knowledge-vault's code warns about, and `WorkflowTransferService`.

### 5. Next recommended investigation step

Two independent, non-blocking options — either can proceed without the other:

- **(a) Clone `olbrain-shared`** and re-verify the items flagged OPEN QUESTION across every
  repo-note that trace back to it (person_hash salting, exact model field lists, the
  `workflow_definitions` Firestore-doc-vs-Storage-body split). This is the single highest-value
  clone: it closes questions in four of the six repos already investigated.
- **(b) Clone `olbrain-studio`** (or obtain its `firestore.rules`) to resolve Security Finding E —
  the senior review's Firestore-catch-all claim — which is the most serious unresolved privacy/
  authorization question in the investigation and cannot be resolved by any repo already cloned.

Recommend NOT expanding further (e.g. into `olbrain-studio-backend` or `olbrain-agent-design`)
until (a) and/or (b) are done, per MASTER.md's "expand only when a verified dependency requires
another repository."

Reconciliation with the target architecture contract, and any update to the State Semantics
Explorer, remains explicitly out of scope until the user authorizes that phase.

## Stop Condition Report (2026-09-19, second source-verification pass — dependency-gap repos)

### 1. Verified findings

Full detail in `investigation/repo-notes/{olbrain-studio,olbrain-shared,olbrain-studio-backend,
olbrain-agent-design}.md`; consolidated in the updated `investigation/store-inventory.md`.
Headlines:

- **olbrain-shared**: `agent_datastores`' `person_hash()` is **confirmed unsalted** — the same
  bare `sha256(strip().lower())[:32]` construction as agent-runtime's own `agent_user_memory`
  hash, deliberately shared by design (the function's own docstring says so). Every "learned"/
  "memory" Pydantic model across both research and workflow domains was read directly and
  confirmed to carry no organization field at the schema level (not just unused — genuinely
  absent, and in most cases structurally impossible to add without a model change, since they
  use `extra="forbid"`). The `workflow_definitions` Firestore-doc-vs-Storage-body split and its
  legacy inline-JSON fallback were both fully confirmed.
- **olbrain-studio** (Firestore rules only): **Security Finding E is resolved.** The senior
  review's headline privacy claim is confirmed and understated — the exposure reaches at least
  eleven collections, not two, via a catch-all rule that OR-supersedes several real, named,
  tighter rules that the file's own comments admit are currently dormant. The single most severe
  finding: the `agents/{id}` document itself — the platform's central ownership record — is
  readable and writable by any signed-in user, any org. One correction in the other direction:
  `agent_datastores`, which the senior review assumed was exposed "by the same logic," is in fact
  the one collection in this set that is fully, deliberately, and correctly locked down.
- **olbrain-studio-backend**: there is **no hard organization-delete capability anywhere in the
  platform** — only a soft archive/restore that is entirely disjoint from the nine-step
  cross-org agent-transfer cascade. That transfer cascade itself does not touch `agent_datastores`
  or `agent_learned_patterns` at all. `organization_api_keys` and `organization_documents`
  ownership are both fully resolved (both owned here), and `organization_documents` has the only
  genuine hard-delete-plus-deindex path found anywhere in the investigation.
- **olbrain-agent-design**: confirmed, from the writer's side, that `active_config.json` has zero
  cache-invalidation mechanism on publish. Found the actual HTTP surface for `agent_datastores`
  (`routers/datastore.py`) — resolving agent-runtime's "stale comment" and "no GDPR route" open
  questions simultaneously; the route was never stale, it just lives in a different repo. Found
  a **third** independent writer into `agent_datastores` (operator-authored via Studio), which
  reproduces the identical no-org-on-entry pattern the other two writers already showed.

### 2. Corrections to previous understanding

- The first pass's Security Finding E was framed as "cannot be confirmed or refuted" — it is now
  fully resolved, confirmed, and found to be broader than originally suspected.
- The first pass could not determine whether `person_hash()` was salted — now confirmed unsalted.
- The first pass left "does anything cascade agent_datastores/agent_learned_patterns on org
  transfer or deletion" open — now confirmed NOT cascaded, and further, that no org-deletion
  capability exists at all in the platform to cascade from.
- One transcription error was caught and corrected during this pass's synthesis: an
  agent-design subagent's draft note initially mis-stated the `agent_datastores` Firestore path
  as nested under `agents/{id}`; direct re-verification against the actual source in both
  `olbrain-agent-design` and `olbrain-agent-runtime` confirmed both repos use the identical flat
  top-level path — corrected in `investigation/repo-notes/olbrain-agent-design.md` before this
  file was updated.

### 3. Unresolved questions

See `investigation/store-inventory.md`'s final section — a short list, none of which blocks
reconciliation: the GCS storage-layer internals beneath `workflow_definitions`' Storage-body
split, the one-time legacy-migration script for it, `workflow_items`' own org-binding model, the
origin of the `is_enabled` MCP-config spelling (neither confirmed writer repo uses it), whether a
frontend-only filter hides provisional agents from the dashboard (moot given `agents/{id}` is
already platform-wide-readable regardless), and `scripts/merge_organizations.py`'s semantics.

### 4. Missing repositories or dependencies

None block the reconciliation phase. The residual open questions above would require: deeper
`olbrain-shared` storage-layer reads (not a new repo), `olbrain-studio`'s frontend JS beyond the
firestore.rules scope used this pass, or a dedicated read of `merge_organizations.py`.

### 5. Next recommended step

Two tracks, independent of each other:

- **Investigation track**: proceed to reconciliation (`investigation/reconciliation.md`, done
  this pass) — current-state evidence is now sufficiently complete per this document's own
  Definition of Done, below.
- **Outside this program entirely**: Security Finding E (the `agents/{id}` and
  `connector_credentials` exposure specifically) is a live production authorization gap, not an
  architecture-documentation question. It doesn't require the target-architecture reconciliation
  to act on — recommend flagging it to whoever owns `olbrain-studio`'s Firestore rules
  independently of this program's timeline.

## Definition of Done for This Phase

The investigation phase is complete only when we can explain, with source evidence:

CURRENT
What exists today.

OWNERSHIP
Which repository/service owns each store.

DATA FLOW
Who writes and reads each store.

AUTH
How access is actually enforced.

MIGRATION
Which paths are legacy, active, or in-flight.

GAPS
Where current behavior conflicts with the target architecture.

Only after that should architecture implementation work begin.

## Session 3 Report (2026-09-20) — Explorer Reconciliation Executed

### What was already complete when this session resumed

Determined from the filesystem, not from this document's own claims — which were stale.

- Both source-verification passes: all ten repo-notes present.
- `store-inventory.md`, `reconciliation.md` complete.
- `investigation/architecture-decisions.md` complete — all five decisions resolved, 1b
  deliberately left open. MASTER.md did not mention this file at all, because MASTER.md was
  last written at 16:43 and the decisions document at 17:06.
- All ten repos clean, on `main`, at the HEADs recorded above.
- `artifacts/architecture-contract.md` untouched.

### What was missing

- The explorer itself. `state-semantics-explorer.html` still carried its original
  `2026-09-19 09:28` timestamp, identical to the four other original artifacts — target-only
  content, no current-state data of any kind.
- No `state-semantics-explorer.pre-reconciliation.html` backup existed.
- MASTER.md's "Current Next Action" and both Stop Condition Reports still stated the explorer
  was gated on authorization.

There is no `investigation/findings/` directory and there never was one; the findings live in
`store-inventory.md`'s Security Findings A–H section.

### What changed

Backup, created before any edit and byte-identical to the original
(md5 `33760bc49d1bf91d352f702911a25e2b`):

    artifacts/state-semantics-explorer.pre-reconciliation.html

`artifacts/state-semantics-explorer.html` — three insertions, 238 lines added, **zero lines
removed or modified**, CRLF line endings preserved:

1. **`.mig-*` badge CSS** (after the `.b-na` rule). A namespaced family, squared rather than
   the `.b-*` pill shape, so migration classification is never confused with runtime
   resolution status. Uses only existing theme tokens, so both themes work with no new
   `:root` entries. Per Decision 4, `CONTRADICTED BY SOURCE` is violet with a doubled border
   and deliberately does not reuse the `--deny` red that belongs to target authorization-denial
   semantics; `OPEN QUESTION` is dashed.
2. **`CURRENT_ANNOTATIONS` data + `annoHTML()` + `renderAnnotations()`** (after the `SECTIONS`
   array). 22 annotations across 13 sections, carrying: current production analog, fit
   (EXACT / PARTIAL / FRAGMENT / NO FIT — omitted on the authorization pointer, which is
   deliberately not a mapping), missing semantics, migration classification, an optional
   production-precedent flag, and an evidence pointer back into the investigation trail.
   Rendered as a native `<details>`, collapsed by default.
3. **One line in `go()`**, after `AFTER[id](arg)` so it cannot disturb any simulator wiring.

No `VIEWS` function, no `AFTER` hook, and no simulator state object (`RS CC TM LG AZ ER QP MX
EX PIPE_SEL`) was touched. The explorer remains target-first; the annotation layer is
commentary appended beneath it, never a rewrite of the contract content.

`overview`, `matrices` and `examples` are deliberately left unannotated — no clean current
analog, and leaving them clean preserves the target-first framing.

Per Decision 3, the Authorization section carries a pointer only: 712 characters, no table,
no collection names, no severity data, directing to `store-inventory.md`. Production security
bugs are not target architecture semantics.

Per Decision 1b, `agent_learned_patterns` and `ExceptionPattern` carry the literal marker
"No target-architecture mapping yet - procedural memory is outside v2.0 scope." They are not
filed under Claim and not under Narrative Memory, and no sixth object class was invented.

### Validation results

Served locally and driven with Playwright, against both the modified file and the untouched
backup so that pre-existing behavior could be told apart from regression.

- All 16 sections render. Zero JavaScript errors. The only console entry was a `favicon.ico`
  404 from the temporary test server.
- All nine simulators plus Decision Matrices and Normative Examples respond to their controls:
  State Engine (9-step trace intact), OCC, Temporal, Freshness, Deletion + Lineage,
  Authorization, Entity Resolution, Query Playground, Predicate Policy Registry (7 policy
  cards still present), matrix filter, and the 20-example step-through.
- Two results that looked suspicious were checked against the backup and are **pre-existing,
  not regressions**: `#fr-sync` produces no DOM change on an already-synced projection, and
  the Policy Registry renders cards rather than a table.
- All seven `.mig-*` classes emitted match the seven CSS rules defined, 1:1 — no unstyled
  badge. All six migration statuses plus the production-precedent flag are exercised by real
  content.
- Annotations are collapsed by default and expand correctly; badges re-colour correctly when
  the theme is toggled.
- `go()` is the **sole** writer of `#main.innerHTML` (verified by grep: one assignment, inside
  `go()`), so the hook cannot be bypassed. Confirmed empirically as well — the annotation
  block survives every simulator interaction tested, including the pipeline node click, which
  writes to `#nodedetail`, a child of `#main`, rather than replacing `#main` itself.
- One bug was found during validation and fixed: the badge class normaliser replaced spaces
  only, so `IN-FLIGHT MIGRATION` produced an unstyled `mig-IN-FLIGHT_MIGRATION`. The
  normaliser now collapses every non-alphanumeric run.

### Integrity

- `artifacts/architecture-contract.md` — **unmodified**, still `2026-09-19 09:28`.
- `current-storage-review.md`, `repo-and-soul-map.md`, `senior-feedback.md` — all unmodified.
- All ten repositories under `repos/` — **clean**, `git status --porcelain` empty, unchanged
  HEADs.
- The explorer diff against its backup is three pure-insertion hunks with zero deletions.

An intermediate attempt converted the file's CRLF endings to LF, which would have made the
diff a whole-file rewrite. It was caught by byte comparison, reverted from the backup, and
redone in binary mode. The final file preserves the original CRLF endings.

### Remaining architectural open question

**Decision 1b only.** Procedural/heuristic memory has no target-architecture mapping and
resolving it requires the owner of `architecture-contract.md`. Everything else the
reconciliation raised is either decided or explicitly recorded as out of scope.

## Session 4 Report (2026-09-22) — Implementation Specification

### What was investigated

The contract's implementable core was read directly rather than relied on second-hand:
§2 (State Slots, scope, `state_version` semantics), §3 (Predicate Policy, cardinality,
freshness contract, status-gated operations), §4 (four resolution statuses, two temporal axes,
retroactive claims), §5 (authority, the five separate measures), §6 (nine-step resolution),
§7 (mutation, OCC, `STATE_CONFLICT`, idempotency, causality), §8 (source position, contiguous
watermark, typed query capabilities), §9 (sync/async split, the crossing rule), §10 (deletion,
scope generations, policy migration, aggregate governance), §11 (result contract, granularity
by cardinality), plus §14's authority and architecture decision matrices and §13's entity-
resolution examples. Prior sessions had only read §1, §12, §15 and §16.

Three load-bearing claims were re-verified directly against repository source rather than
taken from the investigation notes:

| Claim | Source read | HEAD | Result |
|---|---|---|---|
| `person_hash` is unsalted | `olbrain-shared/src/olbrain_shared/agent/datastore/columns.py` | `a837b95` | **Confirmed** — bare `sha256(strip().lower())[:32]`; the docstring itself states it is the digest half of `memory_doc_id`, i.e. deliberately shared between both keying schemes |
| Extract writer's Firestore path | `olbrain-agent-runtime/services/extract_entry_writer.py` | `b2401a0` | **Confirmed** — `agent_datastores/{agent}/tables/{table}/entries/{person_hash}` |
| `context_facts` bi-temporal shape | `olbrain-agent-engine/alchemist/context/facts.py` | `8720720` | **Confirmed** — `status`/`t_valid`/`t_invalid`/`superseded_by`, invalidate-don't-delete |

### File created

`investigation/implementation-spec.md` — 31 sections, ~138 KB.

### What is now specified

- Target logical architecture, the nine control planes, and their implementation loci.
- Evidence, Claim, Predicate Policy Registry, Current State (StateSlot), Memory and Narrative
  Memory models, each separating `NORMATIVE REQUIREMENT` from `PROPOSED IMPLEMENTATION`.
- The Mutation Contract: OCC plus policy plus state machine, `STATE_CONFLICT` never retried by
  infrastructure, idempotency on `mutation_id`, transaction groups.
- Memory Gateway role, read path, write path — with the structural rule that resolution under
  system policy and caller authorization are separate steps in that order.
- A proposed PostgreSQL MVP logical schema: twelve entities, each with authoritative-vs-
  projection status, keys, scope boundary, versioning, temporal and deletion implications, and
  the indexes/constraints the architecture directly implies. Marked proposal throughout.
- Full current-store mapping across all five domains, classified with the investigation's
  six-label scheme and confidence ratings.
- **The `agent_datastores` decomposition** — the section most likely to be mis-executed.
  Decomposed by writer rather than by store: extract-mode (person-keyed, async), agent tool
  (session-keyed, in-turn), operator CRUD (authenticated, audited). Three writers, one
  Firestore path, three different entry schemas, no `organization_id` on any entry, no
  versioning on any of them.
- Research, workflow, knowledge-vault and session integration boundaries; multi-writer hazard
  analysis answering all eight required questions per store.
- Privacy/identity migration, deletion/erasure, temporal semantics, a seven-phase migration
  strategy, testing translated from the contract's invariants, rollout strategy, and a
  dependency-ordered implementation sequence.

### Key findings recorded

1. **Lossless migration of extract-mode entries is impossible.** A target Claim requires
   provenance as explicit lineage back to supporting Evidence. Extract entries carry no
   session id (deliberately — the row is per person), no message id and no extraction run id.
   The Evidence a compliant Claim needs does not exist and cannot be reconstructed. Recorded
   as `OPEN DECISION` A1 with two named options, neither chosen.
2. **Writer 1 and writer 3 can silently overwrite each other.** An operator correction and a
   later async extraction both merge-write the same `person_hash` row. The operator's higher
   authority is represented nowhere, so recency wins — exactly the last-write-wins outcome the
   contract rejects for important state.
3. **`agent_datastores` is the right first migration target**, precisely because it is already
   fully denied to all clients (`allow read, write: if false`) and covered by a passing rules
   test, so no client read path breaks during cutover. It is the only PII-bearing store that
   is *fully denied* and test-covered — `agent_user_memory` is also correctly protected, but
   through an `isOrgMember` read gate rather than full denial, so clients do read it.
   `agent_sessions`/`agent_messages` are the opposite case and are therefore last.
4. **The research CAS precedent is half-reusable.** The compare-and-swap is the correct shape;
   the application-level retry of a semantic conflict is not, and must not be carried forward
   unexamined.
5. **`org_id` in research's learning pipeline is a dead parameter** — present in
   `run_learn_agent`'s signature, never stored, never used for scoping.

### What remains unresolved

- **Eight §16 governance parameters, zero confirmed.** Tracked as a live table in spec §4 with,
  per parameter: the issue, why implementation depends on it, affected components, whether
  work can proceed without it, and the owner **exactly as the contract documents it**. Row 3's
  owner is "Domain owner per predicate" — a role, not a party, so ownership itself is
  unresolved and is flagged as such rather than filled in.
- **Nine architecture-level `OPEN DECISION` items** (spec §29): extract-mode provenance,
  the `person_hash` replacement construction, unrecoverable-key rows, surrogate person ids,
  gap-free `source_offset` allocation, `MAP`/`SET` status representation, the
  operational-correction authority domain name, the eviction-cap disposition, and Patch 19.
- **Eleven `IMPLEMENTATION QUESTION` items**, deliberately listed separately from the
  governance gates so they do not dilute what actually blocks work.

### Deliberate non-inventions

No TTL, retention window, SLA, staleness budget, hashing algorithm, key-rotation procedure,
authority-domain name, REST route or policy value was invented. Where the obvious guess was
available it was recorded as `OPEN DECISION` instead. Redis, Kafka, Neo4j and dedicated vector
infrastructure are named only as the contract names them — optional, added on measured need.

### Where the source material was insufficient

- No API surface exists for the Memory Gateway in any source material; §13 of the spec is
  conceptual and says so.
- The contract specifies the object model but not storage; the entire PostgreSQL schema is
  marked `PROPOSED IMPLEMENTATION`.
- `source_offset` allocation is left open — a plain sequence does not give the contiguity
  §8's watermark rule requires, and the contract does not choose a mechanism.
- Per-key/per-element status representation for `MAP` and `SET` is required semantically by
  §11 but no storage shape is established.

### Repository safety

**No repository under `repos/` was modified.** All ten verified clean at unchanged HEADs
before and after. `artifacts/architecture-contract.md` unmodified (md5
`97c1fa3bcea1d71210c0429b1d113d07`). `artifacts/state-semantics-explorer.html` unmodified
since the 2026-09-20 reconciliation. No production system was contacted, no migration run, no
commit, push, PR or deployment performed.

**Files created or modified this session:** `investigation/implementation-spec.md` (new),
`investigation/MASTER.md` (this report). Nothing else.

### Next step

Governance, not code. Spec §30 step 1 is closing or formally deferring the §16 rows with named
owners; step 2 is authoring the first Predicate Policies, which has a different owner from the
code and can run in parallel. Neither is an implementation task, and step 3 cannot sensibly
begin until step 2 has produced at least one real policy.

## Session 5 Report (2026-09-22) — Governance Decision Request

### File created

`investigation/governance-decision-request.md` — a decision packet for the architecture /
contract owner. No new investigation was performed; this is a transformation of existing
findings into an answerable form.

### Structure and separation

The document keeps three categories **visibly distinct**, which was the point of producing it:

| Category | Count | Where |
|---|---|---|
| **§16 governance parameters** | 8 (G1–G8) | §4, full per-parameter detail |
| **Architecture-level open decisions** | 7 (D1–D7) requiring owner input | §6 |
| **Implementation questions** | 15 (Q1–Q15) | §7, explicitly not governance blocks |

All §16 proposed defaults, owners and statuses are **quoted verbatim** from the contract.
Nothing was inferred, defaulted or filled in. Where the contract records no proposal the row
reads `NO DEFAULT PROPOSED`; where it records an unconfirmed one, `PROPOSED / UNCONFIRMED`;
where ownership is a role rather than a party, `OWNER UNRESOLVED`.

### Blocking analysis, from the spec's own dependency column

- **HARD IMPLEMENTATION BLOCK:** G5 (aggregate retention/deletion classification) and G8
  (bulk-deletion retry/DLQ).
- **BLOCKS PARTIAL IMPLEMENTATION:** G1, G2, G3, G4, G6, G7.
- **None blocks design of the Evidence / Claim / Predicate Policy Registry foundation** — that
  work is unblocked today, which is the practically useful finding.

G5 is flagged as the one to start first: it needs a legal owner rather than an engineering
one, so it has the longest lead time, and the contract is explicit that engineering may not
substitute a judgement for it.

### Material captured this session that earlier passes had missed

1. **The contract's own "Notes on the open items"** for §16 items 4, 5 and 6 had not been read
   in prior sessions. They are substantive and are now quoted in the packet:
   - item 4 is identified by the contract as *the one with legal exposure*, and its note makes
     clear the SLA bounds the degraded-recall window — it does **not** license relaxing §10's
     exclusion rule;
   - item 5 was *"answered inconsistently across the two predecessor documents"* and §10
     deliberately refuses to pick, because the classification is a legal decision per dataset,
     not an architectural preference;
   - item 6 is coupled to item 1 — *"Zero revocation lag and auth-outage tolerance are mutually
     exclusive."* G1 and G6 are therefore flagged to be answered together.
2. **An existing governance mechanism was found** in `artifacts/repo-and-soul-map.md`
   ("Decisions taken, phasing, risks"): the parallel agent-design / "potion" programme took
   nine decisions to a decision board, six answered 2026-09-17, three standing on documented
   defaults, with confirmation recorded from Jay as final verdict. That programme's Phase 0
   preconditions include fixing the shared Firestore ruleset — the same exposure this
   investigation independently confirmed as Security Finding E.

   Recorded in the packet as **context, not an owner assignment.** The §16 owners are named by
   the contract as Security, Architecture, Operations and Legal; nothing routes §16 through
   that board. Whether it should is raised as decision R1 — and placed first, because it
   determines who receives the other eight.

### Two items deliberately reclassified, and flagged rather than moved silently

Spec §29 recorded `source_offset` allocation (A5) and `MAP`/`SET` status representation (A6)
as architecture-level open decisions. In the packet they appear under **implementation
questions** (Q1, Q2) because they need an engineering choice, not an owner's. The
reclassification is stated in the packet so the two documents do not appear to disagree; they
remain A5 and A6 in the specification.

### D1 nuance preserved

The `agent_datastores` decision is stated at full precision rather than compressed: three
independently-authored writers on one Firestore path with three different entry schemas, no
`organization_id` and no versioning on any entry; `agent_datastores → Memory` is an invalid
oversimplification; competing writers can overwrite one another with the operator's higher
authority unrepresented in the data model; the resulting recency/last-write-wins behaviour
conflicts with the target concurrency semantics; and lossless migration of extract-mode
entries is impossible where the supporting Evidence does not exist. Both documented options
are presented with consequences and **no recommendation**, because the specification offers
none.

### Repository safety

**No repository under `repos/` was modified.** All ten verified clean at unchanged HEADs.
`artifacts/architecture-contract.md` unmodified (md5 `97c1fa3bcea1d71210c0429b1d113d07`).
`artifacts/state-semantics-explorer.html` unmodified since the 2026-09-20 reconciliation. The
senior's source artifacts untouched. No production system contacted; no migration, deploy,
commit, push or PR.

**Files created or modified this session:** `investigation/governance-decision-request.md`
(new) and `investigation/MASTER.md` (this report). Nothing else.

### Next gate

**Architecture-owner review of the governance decisions.** Routing decisions R1 and R2 should
be answered first — R1 determines who receives the rest, and R2 must be answered before G3 can
be asked of anyone. Implementation remains not started and should stay that way until the
gate clears; the unblocked foundation work listed in packet §5 is available in the meantime.

## Session 6 Report (2026-09-22) — Storage Reality & Ambiguity Audit

### File created

`investigation/storage-reality-audit.md` — 18 sections, ~63 KB. Unlike Sessions 4 and 5, this
was **not** a transformation of existing findings: it required genuinely new repository work,
because no prior pass had audited PostgreSQL at all.

### PostgreSQL — the headline answer

**OLBrain does not use PostgreSQL as its own persistence layer, anywhere.** `CURRENT FACT`

Exactly one repository declares a driver: `olbrain-agent-runtime`, `asyncpg>=0.29.0`. It backs
an **outbound, read-only query capability** through which an agent queries a customer's or
third party's database — one of four providers (`dynamics365`, `dynamics365_fno`, `postgres`,
`salesforce`) behind a `data_query` tool. Writes are blocked by regex; a fresh connection is
opened and closed per query; credentials arrive in a `connection` dict from frozen design-time
config. OLBrain neither owns nor writes those databases.

Verified absent across all ten repositories: ORM, migration framework (no Alembic, no
`migrations/`, no `.sql`, no Prisma), schema or model layer, `DATABASE_URL` or Cloud SQL
reference, RLS, pgvector, outbox table, job table. All thirteen questions the brief posed are
answered individually in audit §4.1.

**This matters for sequencing:** the capability proves OLBrain can *talk* to PostgreSQL. It
proves nothing about readiness to *own* one — there is no schema discipline, pooling,
transaction layer or operational ownership anywhere to build on.

### Firestore — verified, and larger than previously recorded

Firestore is the sole authoritative persistence for everything this programme covers; 496
source files reference it across all ten repos. `olbrain-studio` (166 files) uses the **browser
client SDK directly**, which is why the rules layer — not the REST layer — is the real
authorization boundary for anything Studio reads.

**Scope gap found.** `olbrain-agent-engine/alchemist/constants/collections.py` is a canonical
registry declaring roughly **45 collections**. `store-inventory.md` covers about 30, selected
for memory/state relevance. Never previously inventoried: `secrets`, `permissions`,
`team_memberships`, `audit_logs`, `credit_transactions`, `billing_accounts`, `agent_traces`,
`mcp_tool_executions` and ~25 more. Recorded as a scope gap, **not** as new live stores —
declaration in the registry does not prove live use, and `knowledge_embeddings` is declared
there while being known-dead.

### Other persistence found

- **BigQuery** — real and OLBrain-owned; Lumen aggregate evidence with a server-enforced
  `agent_id` filter, plus studio-backend audit queries. Analytics/audit, not memory.
- **Firebase Realtime Database** — never recorded by any prior pass. Cursor-presence state at
  `/agentAccess/{agentId}/{userId}`, feature-flagged, no-op when unprovisioned, write failures
  swallowed by design. Ephemeral UI state.
- **GCS** — config, template/workflow bodies, DCI corpus.
- **Pub/Sub** — async job dispatch in research; *not* a transactional outbox.
- **Redis** — **dormant**. Declared dependency plus `redis_url` / `rate_limit_storage` settings
  fields, but no client import anywhere; defaults to in-memory; `REDIS_URL` appears only in a
  local docker-compose. Not infrastructure.
- **Absent everywhere:** Kafka, Neo4j, any vector database, any OLBrain-owned SQL database.

### Prior claims tested against source

- **`vibe_sessions` transactional write — CONFIRMED, with a refinement that matters.** An
  initial grep suggested the prior note was wrong; a direct read showed it was right.
  `active_conversant.state` transitions do run inside `@firestore.transactional` and carry a
  real provenance field (`last_transition_event_id`). **But the transaction checks only that
  the document exists** — there is no from-state check and no `expected_status`, and
  `InvalidTransitionError` fires solely on not-found despite its name. Atomicity yes,
  transition legality no. Every other `vibe_sessions` write is non-transactional.
- **`agent_datastores` writer collision — prior framing corrected.**
  `implementation-spec.md` §18 called the writer-attribution difficulty "an accident, not a
  design." That is too strong. The operator writer's own comment shows the shared document is
  **deliberate and coordinated** — both writers guard `created_at` re-stamping, and
  `source:"manual"` is a real if partial writer marker. The accurate, narrower statement:
  entry provenance is partial and writer attribution is derivable only by field presence.
- **Writer 3 is bimodal** — it keys by `person_hash` for extract-fill tables and by `uuid4`
  otherwise, deliberately mirroring both runtime writers. So the three writers span **two key
  spaces**, not three.

### Mandatory conclusion recorded

> **Can the three `agent_datastores` writer types safely map to one PostgreSQL semantic table?**
> **NO** — on four independent grounds proven from source: two different identity models
> (a person vs. one capture event), two different cardinalities over time, two different
> authority levels with no field to express them, and two different failure/durability
> contracts (writer 1 is non-atomic with swallowed exceptions; writers 2 and 3 are atomic
> batches that surface errors).

The answer deliberately stops there. **No decomposition was invented** — how many tables there
should be, and which target class each maps to, remains `PROPOSED` in `implementation-spec.md`
§18 and `DECISION REQUIRED`.

### Ambiguities recorded rather than resolved

Ten entries (AMB-01 … AMB-10), each classified and carrying the exact question, the evidence,
affected systems, why it matters, what input is required, and whether work can continue.
Three are `ASK SENIOR`, two are `USER → SENIOR`, four are resolvable by further repository
inspection, one is a governance dependency on §16.

**Two are new and were not previously captured anywhere:**

- **AMB-02 / Q-S2** — when a machine extraction and a human operator have both written the
  same field of the same person row, which is authoritative? The source deliberately merges a
  later extraction into an operator-corrected row, and no authority, source-rank or version
  field exists on the entry. Today write order decides, which is the `Last-write-wins →
  Rejected for important state` outcome.
- **AMB-08 / Q-S4** — how are credentials for external `data_query` PostgreSQL targets stored,
  scoped and rotated, and who reviews the operator-authored SQL? The dispatcher enforces
  read-only but performs no tenancy check; any row the credential can see is reachable. A live
  production credential path no prior pass covered.

Also notable: **AMB-04 / Q-S3** — `secrets`, `permissions` and `team_memberships` were never in
scope for the Firestore-rules review, so Security Finding E's collection list may be
incomplete. Worth checking before anyone treats that finding as a full exposure inventory.

### Safety

**No repository under `repos/` was modified.** All ten verified clean at unchanged HEADs. No
database was contacted; no Firestore or PostgreSQL write; no migration, deployment, commit,
push or PR. `artifacts/architecture-contract.md` unmodified (md5
`97c1fa3bcea1d71210c0429b1d113d07`); `artifacts/state-semantics-explorer.html` unmodified since
2026-09-20; senior source artifacts untouched. No schema designed and no implementation
decision made to fill a gap.

**Files created or modified this session:** `investigation/storage-reality-audit.md` (new) and
`investigation/MASTER.md` (this report). Nothing else.

### Next gate

Unchanged: **architecture-owner review of the governance decisions** (Session 5's packet). This
audit adds two new senior questions to that queue (Q-S2, Q-S4) and one that can be closed by
inspection first (Q-S3). Audit §17 lists what must not be designed yet and why; §16 lists the
eight questions that need no owner input and can be closed by further repository reading.

## Session 7 Report (2026-09-22) — Firestore Completeness & Security Audit

### File created

`investigation/firestore-completeness-security-audit.md` — 18 sections, ~44 KB.

The session's purpose was to close the inventory gap Session 6 identified. **It closed the
three priority questions and disproved the framing of the gap itself.**

### The three priority collections — all resolved

| Collection | Verdict |
|---|---|
| `secrets` | **Real, security-critical, correctly protected.** Not top-level — the live path is `organizations/{org_id}/secrets/llm_api_keys`, holding **KMS-encrypted** per-provider LLM API keys. Written by studio-backend on save in Organization Settings; read by `olbrain-shared`'s `OrgApiKeyService` (KMS decrypt, 5-min cache). Rule is `allow read/write: if false` **and** it is excluded by name from the organizations catch-all. Double-protected. Closes Session 6's AMB-04 for this collection in the reassuring direction. |
| `permissions` | **Not a Firestore collection at all.** A field (`permissions: List[str]`) on API-key records and `UserContext` in agent-design's auth middleware. Registry declaration is dead. Nothing to secure, nothing to migrate. |
| `team_memberships` | **Declared-only** — zero references outside the registry. The real authorization store is **`memberships_index`**, which is `allow read, write: if false` (fully server-only) and is what `isOrgMember()` resolves through via `exists(orgIndexPath(orgId))`. The authorization primitive is correctly locked down. |

### The framing correction

Session 6 described the gap as "~45 registry collections vs ~30 investigated." That framing
does not survive contact with the source:

- The registry (`alchemist/constants/collections.py`, **50** constants) calls itself the "v3
  enterprise schema" and asserts *"All collections are organization-scoped"* — **demonstrably
  false**, and it **omits** `agent_datastores`, `agent_user_memory`, `lead_profiles`,
  `context_facts`, `context_logs`, `vibe_sessions` and the whole research family.
- There are **three** mutually inconsistent registries (agent-engine, knowledge-vault,
  studio's JS), and agent-design references `Collections.AGENT_SENDERS` / `Collections.TOOLS`
  which exist in none of them.
- **`firestore.rules` — not the registry — is the closest thing to an authoritative index**:
  56 match blocks, ~40 top-level collections with dedicated rules, ~30 more named only in
  catch-all exclusion lists. Roughly 20 have never been inventoried by any pass.
- **Four repositories referenced by in-workspace source are absent**: `olbrain-mcp-deployer`
  (writes `agent_traces`, `mcp_tool_executions`), `olbrain-agent-eval` (`agent_qa_runs`),
  `olbrain-finance-engine` (~17 P&L collections), `olbrain-agent-cloud`.

### Counts

10 confirmed declared-only · ~26 confirmed live · 2 dead-or-not-a-collection · ~12 unknown
(1–2 references, not individually opened). Five of nine remaining unknowns are
security-relevant.

### New security findings

- **SF-I — systemic read/write asymmetry.** The top-level catch-all excludes 9 collections
  from read but 24 from write, leaving ~15 **write-protected but readable by any authenticated
  user in any org**, including `agent_users` (end-user names and phone numbers),
  `outreach_campaigns`, `knowledge_library`, `research_plans` and the `*_subscriptions`
  entitlement gates. **The rules file states the cause itself**: these documents carry no
  `organization_id`, so the org-scoped rule used elsewhere would deny everyone. This
  **causally links Security Finding B to Security Finding E** — a connection no prior pass
  made. Missing row-level org fields are not merely a target-architecture inconvenience; they
  are the direct blocker on closing cross-org reads today. The team's stated sequence is
  "stamp organization_id, backfill, then org-scope" — called "S7 of the Outreach migration."
- **SF-J — `agents/{id}` confirmed still superseded at HEAD `252f7887`.** A real, precise
  ownership rule exists (`userId`/`owner_id` on both resource and request.resource) and is
  OR-superseded because `agents` is in neither catch-all exclusion list.
- **SF-K — `agents/{id}/{sub}/**` grants authenticated read with no exclusion list at all**,
  covering `mcp_configs` and every other agent subcollection.
- **SF-L — historical, remediated:** `twilio_accounts` held plaintext `account_sid` +
  `auth_token` in no match block until a 2026-09-15 fix. Recorded because the file warns the
  same inheritance risk applies to any future subcollection under it.

**The working pattern, made explicit:** an explicit block only becomes effective when the
collection is *also* named in the catch-all exclusion list. `secrets` and `twilio_accounts`
have both halves. `agents` has only the first.

### Prior claims tested

- **`config/firestore_config.py` "LEGACY, reachability an open question" — CONTRADICTED.**
  `Agent.__init__` defaults `use_firestore_config=True`; `agent_factory.create_agent()`
  constructs `Agent(agent_id)` taking that default; it is called from `dependencies.py` and
  `main.py`. The legacy path is **reachable from live application paths**. (Traffic share not
  established — `create_agent_with_settings()` passes `False`.)
- **Redis dormancy — CONFIRMED.** The only reference beyond the known settings fields is a
  commented-out line in `.env.example`.
- **`agents/{id}` multi-writer — CONFIRMED and quantified.** Ten non-test write sites across
  three repos, no shared version field, no CAS, no cross-service coordination. `OWNER
  UNRESOLVED`.
- **`workflow_items` — no Firestore rule at all**, no Pydantic model anywhere, no row-level
  org field. Org binding is transitive only, and **the authorization path does not consult the
  parent**, so the transitive relationship is a data-model convenience, not a security
  boundary.

### Senior questions raised (QF-1 … QF-5)

Canonical owner of `agents/{id}`; legal classification of the wallet/ledger/subscription
family (feeds §16 row 5); whether the four absent repositories come into scope before the
inventory is called complete; whether the `organization_id`-stamping "S7" work is funded; and
whether the legacy `create_agent()` path is intended to remain reachable.

G1–G8, R1, R2, D1–D7 and Q-S1…Q-S5 all remain open and unresolved. This audit supplies
evidence relevant to several but answers none.

### Inventory completeness verdict

**Not complete enough to begin target schema design.** The session moved the answer *further*
from yes: scope grew rather than closed, four referenced repositories are absent, ~20
rule-declared collections remain uninventoried, and SF-I demonstrates that designing a tenancy
model before knowing which collections can carry a tenant key would repeat in PostgreSQL the
exact mistake now blocking Firestore.

### Safety

**No repository under `repos/` was modified.** All ten clean at unchanged HEADs. No Firestore
or PostgreSQL write, no migration, deployment, commit, push or PR. No schema, RLS policy,
migration architecture or Firestore-to-Postgres mapping produced.

**Files created or modified this session:**
`investigation/firestore-completeness-security-audit.md` (new) and `investigation/MASTER.md`
(this report). Nothing else.

### Next gate

Unchanged: **architecture-owner review of the governance decisions.** QF-3 (bring the four
absent repositories into scope?) is the one that most directly gates further inventory work,
and QF-4 is the one that most directly gates closing the live read exposure.

## Session 8 Report (2026-09-22) — Firestore Inventory Closure Pass

### File created

`investigation/firestore-inventory-closure.md` — 15 sections, ~36 KB. The final
current-workspace Firestore pass: every unknown the ten repositories could answer was
investigated by **opening the actual reference sites**, not by counting references.

**No repository was cloned.** The four absent repositories were not inspected, per instruction.

### Counts

| Outcome | Count |
|---|---|
| Resolved LIVE (reader and/or writer opened in source) | 21 |
| Resolved NOT A COLLECTION (field or dict key) | 3 |
| Resolved DECLARED-ONLY (new) | 2 |
| Resolved RULES-ONLY (rule exists, zero code references) | 5 |
| Resolved READER-ONLY here (writer outside the workspace) | 4 |
| BLOCKED BY ABSENT REPOSITORY | 3 collection families |
| Still unknown and answerable from this workspace | 1 (R-5) |
| New collections discovered, in none of the three registries | 9 |
| New CONTRADICTIONs recorded | 2 |

### The two most consequential findings

**1. `agent_traces` is fully resolved, and far less sensitive than assumed.** The writer is in
this workspace after all — `olbrain-shared/.../trace_collector.py::finalize_and_persist`. The
persisted payload is **identifiers and counters only**: no user content, no tool inputs or
outputs, no reasoning text. It also carries `organization_id` as a row-level field, which few
stores in this investigation do. The module is explicit that *"the heavy body stays in Cloud
Logging where logs belong."*

**The consequence:** the PII question for turn traces does not disappear — it **relocates to
Cloud Logging**, a data surface governed by IAM rather than Firestore rules, which **no
investigation pass has ever examined**. Recorded as R-7, out of scope for a Firestore audit.

**2. The legacy config classification was inverted (CONTRADICTION-2).** `store-inventory.md`
classified `config/firestore_config.py` as LEGACY because *"the live factory path
(`create_agent_with_settings`) explicitly disables it."* Exhaustive search across all ten
repositories shows **`create_agent_with_settings` has zero callers** — it is dead code. Only
`create_agent()` is wired, from `dependencies.py` (the FastAPI request dependency) and
`main.py`, and it takes `use_firestore_config=True`. The legacy Firestore config service is not
merely reachable; **it is the only agent-construction path actually in use**. There is no flag
or environment variable selecting between them — the choice is a constructor default.

This escalates QF-5 from a tidy-up question to a live architectural fact.

### Other resolutions worth recording

- **`workflow_items`** — service located in `olbrain-shared`, not workflow-runtime.
  **No `organization_id`**, confirmed at the write site; the parent run's org is not copied
  down; no Firestore rule at all → open read and write. Its document id is a **deterministic
  `sha256(run_id|record_id|item_idx)`**, which the code explains is so concurrent orchestrator
  passes converge on one document — a genuine idempotency mechanism, and the third distinct
  concurrency device found in production.
- **Four registry entries name things that are not collections**: `permissions` (last pass),
  plus `knowledge_repositories`, `test_cases` and `agent_performance` — all schema dict keys or
  output fields.
- **Nine collections exist in no registry at all**, found via a production org-backfill script
  and the legacy config service: `agent_usage_summary`, `communication_logs`, `billing_records`,
  `billing_deployments`, `billing_tools`, `billing_kb_storage`, `training_jobs`, `activities`,
  `mcp_server_templates`. The backfill script's purpose — stamping `organization_id` onto
  documents that lack it — is independent corroboration that Security Finding B spans at least
  20 collections, and that tooling for it exists but targets only `clix-capital-prod`.
- **`agents/{id}`** — ten write sites across three repositories now enumerated, with
  **no optimistic concurrency of any kind**. Canonical ownership left as `DECISION REQUIRED`.
- **`memberships`** (distinct from `memberships_index`) — collaborator membership rows written
  by agent-design's `routers/collaborators.py`.

### Remaining unknowns, categorised

Twelve items (R-1…R-12): three blocked by absent repositories, four by writers unattributable
within the workspace, one non-Firestore surface (Cloud Logging), **one still answerable here**
(R-5 — payload shapes of the five session collections, whose writers are known and present),
and four that are owner decisions rather than code questions.

### Is the workspace inventory sufficient?

**NO — with specific, bounded blockers.** The ten-repository workspace is *exhausted* for
practical purposes, but exhausted is not sufficient. The blockers are: four absent
repositories; four unattributed writers inside the platform; one unexamined non-Firestore data
surface; and four decisions. If the answer to QF-3 is "do not bring the absent repositories
in," this document becomes the terminal Firestore inventory and blockers 1–2 become permanent
stated limitations rather than open work.

### No architecture decisions made

No PostgreSQL schema, RLS design, migration strategy, Memory Gateway design, agent-ownership
choice, retention or aggregate classification, authorization-cache policy, Evidence-backfill
policy, or `agent_datastores` decomposition. G1–G8, R1, R2, D1–D7, Q-S1…Q-S5 and QF-1…QF-5 all
remain open and unresolved; this pass supplies evidence for several and answers none.

### Safety

All ten repositories clean at unchanged HEADs. No repository cloned. No Firestore or PostgreSQL
write, no migration, deployment, commit, push or PR. `artifacts/architecture-contract.md`
unmodified (md5 `97c1fa3bcea1d71210c0429b1d113d07`); explorer unmodified since 2026-09-20;
senior source artifacts untouched.

**Files created or modified:** `investigation/firestore-inventory-closure.md` (new) and
`investigation/MASTER.md` (this report). Nothing else.

### Next gate

Unchanged: **architecture-owner review of the governance decisions.** QF-3 now gates whether
any further inventory work is possible at all, and QF-5 has escalated on new evidence.

## Session 9 Report (2026-09-22) — Senior Architecture Decision Pack

### File created

`investigation/senior-review-pack.md` — 12 sections, ~31 KB. A consolidation only: no
repository investigation was performed and no new facts were derived.

### What it contains

**24 decisions, none answered**, with an annotation template covering all 25 answer slots
(D1 splits into (a) and (b)):

| Group | Count |
|---|---|
| Routing — R1, R2 | 2 |
| §16 governance — G1–G8 | 8 |
| Architecture — D1–D7 | 7 |
| New owner/scope — QF-1…QF-5 | 5 |
| Storage-specific — Q-S4, Q-S5 | 2 |

**Routing placed first**, because R1 determines who receives everything else and R2 must be
answered before G3 can be asked of anyone.

**Hard blocks identified as two:** G5 (per-dataset aggregate legal classification) and G8
(bulk-deletion retry / DLQ). Classifications were carried from `implementation-spec.md` §4 and
deliberately not reclassified.

**Contract notes preserved rather than paraphrased**, as instructed — G4's legal-exposure note
(the exclusion rule must not be relaxed; the SLA only bounds the degraded-recall window), G5's
note that the two predecessor documents answered it inconsistently and §10 deliberately refuses
to pick, and G6's note that zero revocation lag and auth-outage tolerance are mutually
exclusive, which is why G1 and G6 must be answered together.

### De-duplication performed

Per the brief, questions already covered elsewhere were folded rather than repeated:

- **Q-S1 → D1(a)** — the extract-mode migration path; same decision, same owner.
- **Q-S2 → D1(b)** — machine vs. operator authority on the same person field. Kept as a
  distinct sub-decision because it must be answered before any person-attribute Predicate
  Policy can be authored, independently of how migration proceeds.
- **Q-S3 → §8 (not a senior question)** — resolved in Session 7: `secrets` is correctly
  protected at both layers.

Only Q-S4 and Q-S5 survived as distinct storage-specific owner questions.

### Section 8 — what is deliberately NOT escalated

Nine already-resolved facts are listed explicitly so the senior discussion is not polluted by
them: `secrets` correctly protected; `permissions` is a field not a collection;
`team_memberships` declared-only; `memberships_index` is the real membership primitive; Redis
dormant; the 10-repo investigation exhausted; the PostgreSQL driver is only an external
customer-database integration; `workflow_items` has no `organization_id` but does have a
deterministic-hash idempotency scheme; `agent_traces` stores counters and identifiers only.

### Detailed evidence remains where it was

The pack is the decision interface, not a replacement. Evidence stays in
`implementation-spec.md`, `storage-reality-audit.md`,
`firestore-completeness-security-audit.md`, `firestore-inventory-closure.md`,
`governance-decision-request.md`, `architecture-freeze.md`, and the contract itself. Every
decision in the pack cites its source document and section; no line numbers are reproduced.

### Size note

The pack came in at ~31 KB against a 15–25 KB target. The per-item fields the brief required
(question, documented proposal, owner, why, components, blocking classification, preserved
contract note — plus full option sets for D1 and preserved factual evidence for QF-1…QF-5)
drive the length. Trimming further would have dropped content the brief explicitly asked for,
so the fields were kept and the prose was tightened instead.

### Safety

All ten repositories clean at unchanged HEADs. No repository cloned. No production, Firestore or
PostgreSQL write; no migration, deployment, commit, push or PR.
`artifacts/architecture-contract.md` unmodified (md5 `97c1fa3bcea1d71210c0429b1d113d07`);
explorer unmodified since 2026-09-20; senior source artifacts untouched. **No governance or
architecture question was answered, and no schema, RLS design or migration plan was produced.**

**Files created or modified:** `investigation/senior-review-pack.md` (new) and
`investigation/MASTER.md` (this report). Nothing else.

### Next gate

**Senior / architecture-owner review of the pack.** R1 and R2 first — they determine routing and
unblock G3 and D5. G5 and G8 have the longest lead times (Legal and Operations respectively) and
are the two hard blocks on any deletion work.

## Session 10 Report (2026-09-22) — Senior Decision Dashboard

### File created

`artifacts/senior-decision-dashboard.html` — a self-contained, offline interactive dashboard
for the architecture owner. No network dependency, no external fonts or libraries, no backend.

### What it presents

All **24 open decisions** as expandable cards, each carrying id, title, category, blocking
level, owner, one-sentence question, and on expansion: the exact decision, why it matters,
verified evidence, current proposal (or `NO DEFAULT PROPOSED`), documented alternatives (or an
explicit statement that none are recorded), what it blocks, source document + section, and an
`ANSWER NEEDED` placeholder.

| Section | Contents |
|---|---|
| 1 Routing | R1, R2 |
| 2 Governance — §16 | G1–G8, with §16 explained in plain terms |
| 3 Architecture | D1–D7, D1 given a full-width detailed card |
| 4 Owner / Scope | QF-1…QF-5, plus Q-S4 and Q-S5 |
| 5 Security awareness | five verified findings, awareness only |
| 6 What happens next | dependency flow + parallel-work statement |

Controls: filter chips (All / Governance / Architecture / Owner-Scope / Storage / Hard block),
free-text search across id, title, owner and question, expand-all and collapse-all, and a theme
toggle. Design tokens mirror `state-semantics-explorer.html` so the two artifacts read as one
family.

### Fidelity to the sources

- **No decision is answered and no recommendation was added** where the sources carry none.
  D1(a) presents Option A and Option B with consequences and an explicit "no recommendation"
  line, exactly as `implementation-spec.md` §18 leaves it.
- **G5 and G8 are marked HARD IMPLEMENTATION BLOCK**; G1 and G6 carry a visible
  "answer with" pairing badge, because the contract states they must be answered together.
- **Contract notes are reproduced, not paraphrased** — G4's legal-exposure note, G5's note that
  the two predecessor documents answered it inconsistently and §10 deliberately refuses to pick,
  and G6's mutual-exclusivity note.
- **§16 is explained** ("Section 16 of the architecture contract — the remaining governance
  parameters") rather than assumed as known terminology.
- **QF-3 lists the four absent repositories by name** and states they are referenced by current
  source but are not in the workspace.
- The page states in its own header that it is **not authoritative**, that the contract and the
  investigation documents remain the source of truth, and that the answer areas are visual
  placeholders which save nothing and write back nowhere.
- Every card cites its source document and section. **No line numbers are fabricated.**

### Verification

Rendered locally and checked once: all 24 cards present and counted, filters and search
operate, sections hide and show correctly, both themes resolve. Zero JavaScript errors — the
single console entry was a favicon 404 from the temporary local server. Test server stopped and
the screenshot and Playwright output directory removed; the workspace root is clean.

### Not done, deliberately

The dashboard was **not published** as a hosted artifact. It reproduces verified production
security exposures (`agents/{id}` write access, cross-org readable collections), so it stays a
local file for the owner to route as they see fit.

### Safety

All ten repositories clean at unchanged HEADs; none cloned. No production, Firestore or
PostgreSQL write; no migration, deployment, commit, push or PR.
`artifacts/architecture-contract.md` unmodified (md5 `97c1fa3bcea1d71210c0429b1d113d07`);
`artifacts/state-semantics-explorer.html` unmodified since 2026-09-20; senior source artifacts
untouched. **No implementation started, no schema produced, no decision invented.**

**Files created or modified:** `artifacts/senior-decision-dashboard.html` (new) and
`investigation/MASTER.md` (this report). Nothing else.

### Next gate

Unchanged: **senior / architecture-owner review.** R1 and R2 first — they set routing and
unblock G3 and D5. G5 (Legal) and G8 (Operations) carry the longest lead times and are the two
hard blocks on any deletion work.

---

## Session 11 Report (2026-09-25) — Senior Review Reconciliation

`investigation/senior-review-reconciliation.md` — new. Reconciles the senior-reviewed
Decision Dashboard against this investigation: a source trail of previous understanding →
senior correction/answer → verified evidence → current understanding → architectural impact →
remaining question, for all 24 dashboard decisions plus the security-awareness findings and
the §16 governance rows.

**Evidence-base correction — applies beyond this document.** All ten repositories in `repos/`
were stale. `git rev-parse origin/main` returns the last-fetched value, so every repo reported
`HEAD == origin/main`, which meant "never fetched since clone", not "in sync". None of the
commits the senior reviewer verified against existed locally. All ten were fetched (read-only:
remote-tracking refs only). **Every `file:line` citation in the existing `investigation/` set
was written against the stale checkouts and should be re-anchored** — one security finding
already inverted because of it: the agents subcollection rule does exclude `mcp_configs`
(`olbrain-studio 8cee761c:firestore.rules:1087-1090`), so the earlier "no exclusion list"
finding is withdrawn. Citations in the new document are pinned to explicit SHAs.

Reviewed dashboard obtained as a shared artifact (read, not modified; not copied into
`artifacts/`). `artifacts/senior-decision-dashboard.html` remains the pre-review baseline and
is unchanged.

Outcome: 24 decisions classified — **5 actual architecture decisions confirmed** (D1(a)+D1(b),
D6, QF-1, QF-3, QF-4), 2 routing/ownership answers (R1, R2), 14 still open, 3 hard blockers of
which **G5 and QF-2 are now parked by decision** and G8 alone is routable. No evidence conflicts
remain — the one raised earlier was an artifact of the stale checkout. **Not ready for
PostgreSQL design:** D4 and the parked G5/QF-2 are the remaining gates.

Also recorded: `routers/sessions.py:462` and `:568` call `process_message_universal()` /
`stream_response()`, which are defined nowhere on `origin/main`.

No source artifact, contract, explorer or repository working tree was modified.

---

## Session 12 Report (2026-09-25) — Person Identity Architecture Research

`investigation/person-identity-architecture-research.md` — new. Deep architecture research into
what "person identity" should mean in OLBrain, commissioned because D4 was blocking PostgreSQL
schema design. Read-only; all citations pinned to fetched SHAs.

**Headline: D4 is the wrong question.** It asks for a primary key and presumes one identity
mechanism is up for revision. There are **four** in production — `person_hash` (global, unsalted),
`memory_doc_id` (agent-scoped, an **inline duplicate** of the same digest), `lead_contact_doc_id`
(org-scoped, mergeable, explicitly re-pointable) and `agent_users` (composite, channel-typed) —
built on **three incompatible normalisation regimes** that disagree about who is the same human.
No person-keyed store carries an alias/canonical/merge field — though OLBrain *does* run a
persisted merge-and-redirect doctrine for **organizations** (`organizations.merged_into`, chain
resolution, rollback snapshots) that was never extended to persons. The contract has no object class for a
person: it models state *about* one (the `CUSTOMER` scope) and resolution between *mentions*, and
assigns identity to an `IDENTITY_SYSTEM` that does not exist.

Verified defects recorded: session-keyed person rows are **write-only** (the write path falls back
to `session_id`; no read path does); the digest has **two independent implementations**; `user_id`
is a **different identifier type per channel** (phone / email / IGSID / `None`), so one human
becomes several permanently unlinked persons; and the only implemented scope ladder
(`agent-engine e43654e:alchemist/context/scope.py`) has **no CUSTOMER level**.

Recommendation (labelled inference, not a decision): an explicit **resolution layer** — immutable
typed observed identifiers, opaque tenant-scoped subjects that *are* the `CUSTOMER` scope_id, and
revisable non-authorizing resolution links. Stated **conditionally**: the report attempts six
falsifications of it, one of which (rare co-occurrence) would defeat it, and the deciding
measurement is listed as answerable without senior input.

Six decisions genuinely need Jay, led by **J1: does OLBrain need to recognise one human across
channels?** — a product question on which the whole architecture hangs.

Also corrected in `senior-review-reconciliation.md` (four places): the earlier claim that no
consumer vendors a copy of `person_hash` was false.

No production code, schema, migration, contract, explorer or existing normative artifact was
modified.

---

## Session 13 Report (2026-09-26) — Person Identity Measurement Pass

`investigation/person-identity-measurement-pass.md` — new. Tests whether the previous pass's
conditional resolution-layer recommendation is justified by real evidence. Read-only.

**Finding 0: this workspace has no production data access.** No credentials, no exports, `gcloud`
absent, and the `firebase` CLI is logged into an unrelated account whose `projects:list` fails.
The five measurement sections (co-occurrence, fragmentation, recovery join, session rows,
transfer counts) therefore **cannot be measured here and are not estimated**. They are delivered
instead as executable specifications — exact collection paths, join keys, populations,
limitations, and the thresholds at which each result would change the recommendation. Production
was not queried, and reading customer PII out of production was treated as needing an explicit
decision rather than a side effect.

**Closed from code and git history:**
- **N7 closed.** `person_hash` and `memory_doc_id` have **never diverged** — byte-identical since
  introduction (`memory_doc_id` 7481c61, 2026-06-13; `person_hash` 5641e59 → shared 5bcd688, both
  2026-09-12). The risk is latent, not historical.
- **F8 not realized — corrects the prior report.** Identity is an addressing input only;
  `routers/agent_memory.py` gates on API key + caller org + document `organization_id`, returning
  404-not-403 across tenants. The prior report's "identifier is in effect the capability" claim is
  withdrawn; its privacy findings are independent and stand.
- **F4 escalated.** Transfers *are* logged (`activities`, `agent_transferred`), so this is
  measurable. The cascade handles **16 collections including `agent_sessions` and omits every
  person-keyed store** — person data is stranded on transfer today.
- **Two new mechanisms, one decisive.** `research_clients`
  (`olbrain-research-design e211584`) is a complete alias + `merged_into` + archive + audit
  entity-resolution model already in production — the third in-house precedent for the proposed
  shape. `member_identity` is the separate, correctly-distinct principal axis.
- **Fragmentation-per-human is `[UNMEASURABLE]`, not merely unmeasured** — computing it requires
  the identity resolution whose absence is the finding.

Four new questions (M1–M4), notably **M1: the S7 backfill will mis-scope transferred agents**,
whose `organization_id` is already present and already wrong. M4 was downgraded on verification:
`agent_user_memory` re-stamps `organization_id` on every durable write, so stale tenancy there
self-heals for any person who returns; `agent_datastores` has no such self-healing.

J1–J6 remain open and were not answered on Jay's behalf. No implementation recommended.
No production code, schema, migration, contract, explorer or existing investigation report was
modified.

---

## Session 14 Report (2026-09-26) — Parallel Work While J1–J6 Are With Jay

Eleven new investigation artifacts across seven tracks, plus three authorised repository clones.
Read-only; no decision taken in any of them. Index and cross-cutting summary:
`investigation/parallel-work-synthesis.md`.

**Track A (governance):** `governance-g8-research.md`, `governance-g1-g6-research.md`,
`governance-g3-research.md`, `d5-authority-research.md`, `d7-patch19-research.md`.
**Track B:** `qf5-current-path-research.md`, `security-current-head-reverification.md`.
**Track C:** `new-repo-inventory-closure.md`. **Track E:**
`person-merge-current-state-memory-research.md`. **Track F:** `s7-backfill-correction-note.md`.
**Track G:** `decision-gateway-jev-research.md`.

**Repository scope closed (QF-3).** `olbrain-mcp-deployer 0efd05f`, `olbrain-agent-eval 6c289ca`
and `olbrain-finance-engine 109a838` cloned — the workspace now holds **13** repositories. They add
**zero** person-identity mechanisms, so that inventory is now bounded unconditionally. They resolve
`mcp_tool_executions` and `agent_qa_runs`, enumerate the Finance/P&L family, reveal a second
credential store (Fernet-encrypted `oauth_tokens`) and an unnamed additional `agents/{id}` writer.

**Conclusively closed:** `scope_generation` exists nowhere; no dead-letter handling exists (one
dormant provisioning workflow that admits silent drop at retention); a cached-auth precedent exists
at **30s TTL, default OFF, caching only the credential fetch while every check runs per request**,
so production is online-only today; no predicate-freshness machinery exists; the contract has **no
scope-exclusion vocabulary at all**; QF-5's two methods were removed **2026-04-01** and `Agent` has
no message-processing method; catch-all read exclusions rose 9 → 17 and write 24 → 33 since the
stale checkout.

**Refined:** merge-induced `CONFLICT` is **not** the deepest problem — the contract already defines
`CONFLICT` as a first-class recoverable status with a declared `RESOLVE_CONFLICT` operation.
**Memory is**, being the only plane with no conflict concept and a direct path to the prompt.

**New issues:** N8 (tenant-scoped subject vs agent-scoped storage), N9 (merge inherits G4 and G8),
N10, N11, N12, **S6** (`agent_users` read-exposed while every sibling PII store is not), G8's
record-keeping options inheriting parked G5, and the override approve/retire endpoints having no
authorization gate found in source.

**PostgreSQL gate:** narrower, not open. G3 plausibly leaves it (freshness belongs to the Policy
Registry, not the value row — needs contract-owner confirmation); D1(b)'s per-field authority
marker enters it. The parked G5/QF-2 pair remains the binding constraint.

J1–J6 untouched and unanswered. Track D produced no measurements — production access remains
unavailable and was not sought; all five measurements are preserved as executable specifications
with thresholds stated in advance.

All 13 working trees clean; contract and explorer unchanged; no existing report overwritten.

---

## Session 15 (2026-09-26) — Decision Board

`investigation/decision-board.md` — new. Consolidation only: every entry is drawn from an existing
artifact, nothing new investigated, no option recommended, no decision taken.

**18 open decisions**, separated by who must decide: 5 Jay (J1 cross-channel need, J3 identity
ownership, J5 merge policy, G5/QF-2 unparking, D4 surrogate id) · 13 other-owner (5 contract
owner, 2 Operations, 1 Security pair, 1 domain owners, 1 workflow-design, 1 runtime, 2 programme).
Plus **9 evidence-required queries** (E1–E9, all specified, none runnable here — no production
access) and **8 routed defects** (R1–R8) needing an owner rather than a decision.

Each decision carries pinned evidence, only the options the investigation actually produced, its
dependencies, and what each option blocks. Where no option set emerged, the entry says so rather
than inventing a menu.

Three items flagged as gate-movers: **G5+QF-2 parking** is the binding PostgreSQL constraint;
the **freshness / Policy-Registry contract reading** is the one question that could remove G3 from
the blocker list; **D4** sets the primary key of every person-keyed table.

No repository, contract, explorer or existing report was modified.

---

## Session 16 (2026-09-28) — J1–J6 answered; derivation

Jay answered J1–J6 on 2026-09-26. `investigation/j1-j6-derivation.md` derives the contract changes
(drafted as P-A…P-E, **not applied**), the implementation impact, and the unresolved technical
questions — without inventing policy. All repositories re-fetched first; most had moved.

Decided `[JAY]`: recognise one human across channels and across an org's agents, never across orgs;
contract permits in-org merges, forbids cross-org; Memory Gateway is the identity authority, with
agent-runtime's `person_key` fold as named interim resolver, purely code, no human merges; extract
writes are MEMORY not IDENTITY_SECURITY; merges automatic with audit + undo, no approval gate;
person data follows the agent on transfer.

Verification found **two conflicts between the answers and the code they name**: the named interim
resolver is read-time, page-scoped and lead-only — it never runs on a write, which J3 requires; and
`research_clients`, whose mechanics J5 says to reuse, has **no undo** and a value-derived key. Also:
`lead_contacts` embeds the org in its document id and is shared across agents, so J6's "re-stamp"
cannot work for it — it needs re-keying, and a transfer can trigger automatic merges in the receiving
org; `agent_users` stamps `organization_id` only on create and never self-heals (correcting
`s7-backfill-correction-note.md`, which said it had no such field); the interim resolver's evidence
is capped at 20 refs per contact.

16 unresolved questions (U1–U16); six need Jay. D2, D3, D4 remain open; G5/QF-2 parked remains the
binding PostgreSQL constraint. Contract unmodified.

---

## Session 17 (2026-09-28) — Identity resolution specification

`investigation/person-identity-resolution-spec.md` — new. What an engineering spec must contain to
implement J1/J2/J3/J5: automatic resolution, merge and undo. Requirements only; no mechanism chosen,
no policy invented, no schema.

Traced eight person-keyed write paths at current commits (the live datastore tool is not one —
extract tables compile to no tools). Key results: identifiers arrive from two very different sources
— channel-supplied, and **LLM tool-call input from lead capture** (dictated, transcribed) — and J5's
immediate exact-match merge does not distinguish them (R1). The named interim resolver is a
page-scoped read-time display fold with a lexical winner and transitive joins. **Full undo is
impossible for `agent_user_memory` under current write semantics**: its facts are regenerated whole
by an LLM each turn with no provenance, so combined content cannot be split. **A non-persistent undo
is re-merged by the next write** (J3 + J5), and a persistent one is a human identity decision J3
forbids (R2). No automated entity-merge undo exists anywhere in the platform. The audit mechanism is
a log line, not a transactional record. The org stamp falls back to `""` and, after a transfer, a
300 s config cache makes writes re-stamp the old org.

10 new questions (R1–R10); four need Jay (R1, R2, R4, R6). Recommended next: trace every person
read path, since the only undo-preserving mechanisms move identity cost onto reads.

### Session 18: docket answers and council verdict (2026-09-28)

- [docket-answers-2026-09-28.md](docket-answers-2026-09-28.md): Jay answered 18 of the 19 docket questions. G1 is unanswered. These answers are TARGET ARCHITECTURE policy inputs.
- [council-verdict-2026-09-28.md](council-verdict-2026-09-28.md): verdict from a council of three independent Opus reviewers on the items Jay sent to the council.
  - **Unanimous on C2–C6 and C10:**
    - P(A)+E(B) records are weak evidence.
    - D1(a) stands.
    - A separate person-merge contract rule.
    - An opaque subject id plus an HMAC mapping.
    - Design without the G5 aggregates.
    - A deterministic, versioned scorer with no LLM on the merge path.
  - **Undo** is exact for grouping and pre-merge content. It needs copy-on-first-write versions and epoch tags before the first merge ships.
  - **Returned to Jay:** the transfer-fence precondition, the encrypted raw identifier, the Tier-2 undo content, N10, G1, and his truncated G8 note.
  - **CONTRADICTED BY SOURCE:** `agent_user_memory` docs do store plaintext `channel_user_id` (agent_memory_service.py:404/:473). This corrects person-identity-architecture-research.md §9.2.
- [contract-vs-settled-decisions.md](contract-vs-settled-decisions.md): contract v2.0 checked against the settled identity decisions. It finds seven contradictions (X1–X7). X1 was already known; X2–X7 are new.
  - X2, the §2 single-scope rule, makes a merged person unresolvable. It also withdraws the P-B claim that no new machinery is needed.
  - X5: the §5 single-scalar ban contradicts the council's additive scorer.
- [identity-patch-draft-2026-09-28.md](identity-patch-draft-2026-09-28.md): round-2 answers (Q15–Q20, X2, X3, X5) plus contract patch drafts PI-1 to PI-12. Drafted, not applied.
  - No identity policy questions remain open with Jay, except six small residuals (R1–R6).
  - R5 is three phrases that were lost when the answers were pasted.
- [final-identity-docket-2026-09-28.md](final-identity-docket-2026-09-28.md) closes R1–R6.
  - Closed as derived or parameters: R1 (the older subject survives), R2 (ordinary Predicate Policy over the members' Claims, with consent most-restrictive), R3 (only B's generation advances), R4 (a 200 ms budget, as a §16 parameter), R5 (recovered: `MERGE_SUBJECTS`, four pass/fail gates, the online list derived) and R6a (an opt-out stays on both subjects).
  - One policy item remains for Jay: R6b, erasure through a wrongly merged person.

### Session 19: Agent Memory track (2026-09-28)

- [agent-memory-investigation.md](agent-memory-investigation.md): the full memory lifecycle traced at `origin/main`, as 20 sections.
- **Repo state:** local checkouts are behind `origin/main` (runtime HEAD `b2401a0` vs `daee3f9`). All citations use `git show origin/main`.
- **PRESENT failures:**
  - wipe on an empty list, and a probable freeze at `max_tokens=1024` because `stop_reason` is never checked;
  - assistant-reply contamination;
  - a lost update from the read→LLM→blind-write sequence;
  - a delete resurrected by an in-flight extraction;
  - shadow memory through never-ending WhatsApp/IG/Slack sessions and summaries;
  - learned patterns with verbatim user text and no org field;
  - no memory eval: the harness sends no `user_id`, is draft-only, and draft skips writes;
  - billing drops `user_memory`.
- **New security finding S-M1:** `agent_users` PUT/DELETE has no tenant check (agent-design).
- **Corrections:**
  - `agent_qa_runs` does have `org_id`.
  - Several docstrings and IaC claims are contradicted (§19).
- **Target:** grounded delta extraction, an append-only per-subject ledger, a projection head document, a small predicate registry, a dated and budgeted context, and three eval lanes. No vectors until measured.
- **Open decisions:** OD1–OD6.
- [memory-architecture-decision.md](memory-architecture-decision.md): the memory architecture decision, sections A–T plus four appendices.
  - **Design:** keyed bitemporal claims with immutable content, behind a deterministic acceptance gate. Plus watermark extraction, erasure epochs stamped on the evidence (kept separate from the merge generation), a head-doc projection, tiered retrieval, a prompt manifest, and three eval lanes. No vectors, with a measured trigger for adding them.
  - **For Jay:** R-M1 to R-M4.
  - **Contract changes:** T1–T7.
  - **Key risk (`[UNMEASURED]`):** grounding recall on Devanagari, Telugu and code-mixed traffic. Mitigated by a soft value check and a recall floor per language.
- [memory-contract-reconciliation.md](memory-contract-reconciliation.md): Track A reconciliation of the memory architecture against contract v2.0. It used three reconciliation agents and a council of three reviewers.
  - **Verdict:** not insertable as written.
  - **What it needs:**
    - 8 required contract edits: E1, E2, E3, E3b, E5, E11, E12, E13;
    - 5 clarifications;
    - 29 corrections to the MAD;
    - 5 items blocked on Jay;
    - 22 points marked [UNDECIDED].
  - **Blockers the council caught in v1:**
    - E3 let pre-merge evidence committed during a merge escape quarantine;
    - E3 blocked the Q17 recovery step;
    - E5's "restore" contradicted PI-6.
  - **New verified security finding:** the `agent_messages` Firestore rules allow cross-tenant read and write (studio `1f05ca11`, `firestore.rules:888-959`).

## Lane B / B0: security handoff (2026-10-01, investigation and test only)

- Findings and gate: [memory-lane-b-security-b0-v1.md](memory-lane-b-security-b0-v1.md). **G-SEC not passed.**
- Tests: [memory-lane-b-b0-acceptance-tests-v1.md](memory-lane-b-b0-acceptance-tests-v1.md).
  - 74 server ATs: current 62 RED, 12 GREEN; reference 73 GREEN, 1 skipped.
  - 12 revocation cases: current rules 0/12 hold, B0 rules 12/12.
  - 32 rules probes: current rules 32/32 allowed; stage 1 2/32; stage 2 1/32.
- Studio query audit: [memory-lane-b-b0-query-audit-v1.md](memory-lane-b-b0-query-audit-v1.md). 11 live call sites (one conditional) must change before the rules deploy.
- Implementation matrix: [memory-lane-b-b0-implementation-handoff-v1.md](memory-lane-b-b0-implementation-handoff-v1.md).
- **New VERIFIED CURRENT finding B0-25:** `organizations/{org}` documents (wallet, runtime) are readable by any signed-in user (studio rules L418).

## Lane B / B0: implementation (2026-10-02, local `b0/security` branches only; nothing pushed or deployed)

- Status: [memory-lane-b-b0-implementation-status-v1.md](memory-lane-b-b0-implementation-status-v1.md). Blockers: [memory-lane-b-b0-blockers-v1.md](memory-lane-b-b0-blockers-v1.md).
- Acceptance results on real branch code: 57/73 GREEN. B0-14 and B0-20 were not started because the permission classifier blocked them.
- Repository rules, stage 1: 1/51 attacks allowed (by design). Twins 0 denied, revocation 12/12, Studio rules suite 456/456.
- New findings:
  - **B0-29 (VERIFIED CURRENT):** `memberships_index` merges agent and project grants into org roles. Fixed under contract C10.
  - **B0-28/28b:** API keys were authorised through their creator's uid. Fixed.
  - **Open:** **B0-30 (VERIFIED CURRENT: any signed-in user can update any org)**, **B0-31 (VERIFIED CURRENT: claim another person's pending invite)**, B0-26 (Meta signature; keeps INV-S8 open), B0-27 (email thread join), B0-28c (more creator-uid routes).
- **G-SEC: NOT PASSED.**
