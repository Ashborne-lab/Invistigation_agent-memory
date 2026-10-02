# Architecture Freeze — v2.0 Semantic Scope

Freeze date: 2026-09-22.

Inputs reviewed: `investigation/architecture-decisions.md`, `investigation/reconciliation.md`,
`investigation/store-inventory.md`, `artifacts/architecture-contract.md` (read for
verification only, **not modified**).

**What this document is:** the record of the v2.0 semantic-scope decision, taken after the
current-state investigation and the explorer reconciliation were complete. It closes
Decision 1b — the last unresolved semantic question in the program.

**What this document is not:** it does not modify `artifacts/architecture-contract.md`, does
not modify `artifacts/state-semantics-explorer.html`, does not touch any repository under
`repos/`, and does not begin implementation. It adds no sixth object class.

---

## 0. Contradiction check — the verification this decision was conditioned on

The decision was to be adopted *unless a direct contradiction with the existing contract was
identified*. The contract was checked directly. **No direct contradiction exists. Adopted.**

The check, and what it actually found:

**There is no exhaustive-coverage rule.** Searching the contract for any requirement that all
system data fall inside the five object classes returns nothing: no "MUST be one of", no
"every memory", no "exhaustive". §12's ten inviolable rules are without exception statements
about how the classes *behave* when used — never statements that everything must be one of
them. §15's nine control planes and central invariant are likewise about authority, not
coverage.

**The one totality-shaped sentence is not normative, and could not be.** §1 opens: "Five
object classes carry all meaning in this system." Two independent reasons this cannot be read
as a coverage requirement:

1. *The contract's own normative-language rule.* The preamble states: "MUST and MUST NOT are
   absolute... Everything not marked is descriptive context for the rules around it." The
   sentence carries no MUST. The normative rule it introduces is the one immediately
   following — that the five definitions "MUST NOT be merged in implementation," which this
   decision honours exactly, by declining to merge procedural memory into any of them.
2. *Internal consistency.* Read as a coverage requirement, the sentence would contradict the
   contract elsewhere. The preamble names "graph, vector, cache and queue layers" as
   "replaceable projections." §8 states "vector chunks are retrieval containers, not truth
   objects." §15's durable statements say plainly: "the graph is not the memory, the session
   is not the memory, the vector index is not the memory, the Evidence Log is not current
   truth." These are real objects that carry meaning in the system and are not one of the
   five classes. The contract already operates with things outside the taxonomy. The
   non-totality reading is the only self-consistent one.

**Precedent for objects outside the five classes is therefore already established** — by the
contract itself, for projections, indexes, sessions and queue layers. This decision extends an
existing pattern rather than introducing a new kind of statement about coverage.

### Residual tension, recorded rather than resolved

One point of genuine friction is recorded here honestly rather than argued away.

The Memory class is defined as "retained knowledge intended for future retrieval: historical
facts, preferences, episodes, relationships, **lessons**, summaries." A learned tool-call
sequence — "when the intent looks like this, this sequence worked" — can reasonably be read as
a lesson. Someone could argue procedural memory is already covered by Memory and needs no
exclusion.

The exclusion is admissible because **nothing in the contract requires exhaustive coverage** —
not because procedural memory provably fails the Memory definition. That is the weaker claim,
and it is the accurate one.

A note on one argument deliberately *not* relied upon: §8 contains "Memory is therefore
structured at claim level rather than treating a whole text chunk as one truth unit," which
appears to gate Memory on claim-level decomposability and would neatly exclude an ordered
procedure. Read in place (line 642), that sentence sits inside a retrieval-chunking discussion
about a stale graph projection and chunk granularity. It is about not treating a text blob as
one atomic truth during retrieval. It is corroborating context at most, and this document does
not treat it as a normative gate.

---

## 1. Final v2.0 semantic scope

The v2.0 semantic contract covers exactly five object classes, unchanged, with their
definitions unmerged:

```text
Evidence  →  Claim  →  Predicate Policy  →  Current State / Memory  →  Narrative Memory
```

- **Evidence** — append-only, immutable record of what happened or was observed.
- **Claim** — structured `(subject, predicate, object)` assertion derived from Evidence.
- **Current State** — the materialized result of applying Predicate Policy to currently valid
  Claims; never a second source of truth.
- **Memory** — retained knowledge intended for future retrieval; does not automatically become
  Current State.
- **Narrative Memory** — non-assertive contextual material; may inform the LLM, may never
  establish Current State, override Claims, or establish authority.

Also in scope and unchanged: the Predicate Policy Registry model, scope and authorization
semantics, bitemporal validity, mutation and concurrency semantics (OCC, `expected_version`,
`STATE_CONFLICT`), state-machine validation, entity resolution, provenance and lineage,
deletion propagation and generations, projection freshness, LLM capability boundaries, and
fail-closed behaviour.

**No sixth object class is added.** The count stays at five.

## 2. Procedural / heuristic memory — explicitly out of scope

**Adopted, verbatim:**

> Procedural / heuristic memory is outside the v2.0 Evidence / Claim / Current State / Memory /
> Narrative Memory semantic contract.

### What this covers

- `agent_learned_patterns` (olbrain-agent-runtime) — `intent_examples` plus `tool_sequence`,
  with usage and failure counters.
- `workflow_agent_memory.exception_patterns` / `ExceptionPattern` (olbrain-workflow-runtime) —
  `what_failed` / `what_human_did` / `resolution` plus `resolution_data`.

### Why these, specifically

Both are **procedures, not assertions**: an ordered sequence of actions to replay when a
situation recurs. There is no natural `(subject, predicate, object)` decomposition — the
content is a recipe, not a fact about a subject.

### What this decision explicitly refuses to do

- It does **not** classify procedural memory as a **Claim**. Forcing it there would require
  inventing a predicate of the shape `procedure_for_X = [step1, step2, …]`, which every Claim
  example in the contract avoids.
- It does **not** classify it as **Narrative Memory**. That category is defined as retained
  *conversational context* — tone, the way a problem was described, unresolved discussion —
  not retained *action sequences*.
- It does **not** create a sixth object class. Per §1, the five definitions MUST NOT be merged,
  and adding a sixth would be a change to the contract's foundational terminology, not an
  implementation detail.
- It does **not** silently park the data in the nearest available bin.

### Practical consequence

Procedural memory continues to exist and function in production exactly as it does today. It
simply carries no v2.0 semantic guarantees: no Predicate Policy, no claim lifecycle, no
authority resolution, no bitemporal validity, no OCC. Anything built on it is outside the
contract and MUST NOT be treated as authoritative under §12 rule 10 — a value is authoritative
only where Policy, Authority, Temporal Validity, Scope and Resolution Semantics jointly
establish it.

If procedural memory is later brought inside the contract, that is a **contract change**, not
an implementation decision.

## 3. `LearnedOverride`-shaped corrections map to Claims through Predicate Policy

Confirmed as the v2.0 position (Decision 1a, unchanged).

`workflow_agent_memory.learned_overrides[]` (`LearnedOverride`) is structurally an assertion
and maps onto a **Claim** through a **Predicate Policy Registry entry** — not through a new
object class:

| `LearnedOverride` | Claim |
|---|---|
| `step_id` + `field` + `selector` | subject |
| the corrected field | predicate |
| `correction` | object |
| `evidence_exception_ids` / `evidence_run_ids` | provenance |
| `suggested` → `active` → `retired` | `pending` → `active` → `retracted` |

**This requires no change to the contract's normative text.** It requires a registry entry —
an operational-correction authority domain, with a candidate/pending write and human approval
required to reach `active`. §5's authority matrix already has a governance lane for exactly
this shape (`Semantic inference` → `Candidate only`, must retain provenance), and §16 already
reserves registry population to domain owners.

**The conceptual mapping is not the implementation.** Today a `LearnedOverride` is a plain
array entry inside one mutable Firestore document: no `state_version`, no OCC, and no
`organization_id` at the schema level (confirmed in `olbrain-shared` under `extra="forbid"`).
That gap is real and stays classified as TARGET ARCHITECTURE — not as "already effectively a
Claim."

**Note the deliberate asymmetry with item 2.** `LearnedOverride` and `ExceptionPattern` both
live inside `workflow_agent_memory` and are frequently discussed together, but they are not
the same shape. One is an assertion and maps to Claim; the other is a procedure and is out of
scope. They are treated separately and must not be collapsed back together.

## 4. Current-production annotation approach in the HTML explorer

`artifacts/state-semantics-explorer.html` remains a **target-first** artifact. It was not
converted into a current-vs-target application, and no toggle or side-by-side view was added.

The approach, implemented 2026-09-20 and now frozen as the baseline:

- **An annotation overlay**, not a restructuring. 22 annotations across 13 of the 18 sections,
  rendered as a native `<details>` block appended beneath the target content, collapsed by
  default. `overview`, `matrices` and `examples` are deliberately unannotated.
- **Each annotation carries** the current production analog, a fit value
  (EXACT / PARTIAL / FRAGMENT / NO FIT), the missing semantics, a migration classification, an
  optional production-precedent flag, and an evidence pointer back into the investigation
  trail. The authorization entry deliberately carries no fit value, because it is a pointer
  rather than a mapping.
- **A separate `.mig-*` badge family** for the six classifications (VERIFIED CURRENT / LEGACY /
  IN-FLIGHT MIGRATION / TARGET ARCHITECTURE / OPEN QUESTION / CONTRADICTED BY SOURCE), squared
  rather than the rounded `.b-*` pills, so documentation confidence is never read as runtime
  resolution status. `CONTRADICTED BY SOURCE` deliberately does not reuse the denial red.
- **Production precedents are flagged orthogonally**, not as a seventh status — a store can be
  both VERIFIED CURRENT and a partial precedent. Four are flagged: `context_facts`'
  verify-before-active gate, `write_profile`'s CAS, `orchestrator_generation`'s fencing, and
  `agent_sessions.summary`'s Narrative-Memory shape. These are **partial production
  precedents, not implementations of the target contract.**
- **Procedural memory carries the literal marker** "No target-architecture mapping yet —
  procedural memory is outside v2.0 scope," consistent with item 2.

**The governing principle:** current production problems are not target architecture
semantics. The annotation layer is commentary appended to the contract model; it never alters
it.

## 5. Production security findings remain a separate remediation workstream

The Firestore security-rules findings (`store-inventory.md` Security Findings E and G) are
**not** architecture questions and are **not** modelled as target semantics.

- The contract's authorization design is sound and unchanged. §6 and §15 treat authorization as
  one of nine independent control planes — it gates who may read a resolved slot, never which
  claims resolve it.
- What Finding E documents is a different layer entirely: client-side Firestore security rules
  in `olbrain-studio`, where a catch-all OR-supersedes several tighter named rules. That is an
  implementation gap in one rules file, with no bearing on whether the target authorization
  model is correct.
- Inside the explorer, this is a **712-character pointer only** — no per-collection table, no
  severity data, no collection names — directing to the investigation trail.
- The detail stays in `investigation/store-inventory.md`, which remains the canonical source.

**These two workstreams have different audiences and different lifecycles.** The architecture
baseline is a stable reference; the security findings are a live, fixable punch list that goes
stale the moment a rule is patched. They must not be merged.

**This freeze does not gate the security work, and the security work does not gate this
freeze.** Finding E's most severe items — `agents/{id}` and
`organizations/{org}/connector_credentials` readable and writable by any signed-in user, any
org — warrant attention on their own timeline, independent of this program, by whoever owns
`olbrain-studio`'s rules file.

## 6. The architecture baseline — exact files and pinned versions

The following constitute the v2.0 architecture baseline as of this freeze.

### Normative (target architecture)

| File | State |
|---|---|
| `artifacts/architecture-contract.md` | **Unmodified throughout the investigation.** md5 `97c1fa3bcea1d71210c0429b1d113d07`, mtime 2026-09-19 09:28. Consolidated State Semantics Contract v2.0, incorporating Corrective Patch Set 1–18. |

### Interactive model of the target architecture

| File | State |
|---|---|
| `artifacts/state-semantics-explorer.html` | Modified 2026-09-20: three pure insertions, 238 lines added, **zero lines removed or modified**. |
| `artifacts/state-semantics-explorer.pre-reconciliation.html` | Pre-modification backup, byte-identical to the original — md5 `33760bc49d1bf91d352f702911a25e2b`. |

### Investigation record (current production)

| File | Role |
|---|---|
| `investigation/MASTER.md` | Program state, both stop-condition reports, Session 3 reconciliation report |
| `investigation/store-inventory.md` | Per-store current-state map, ten repos, Security Findings A–H |
| `investigation/reconciliation.md` | Five-stage CURRENT → LEGACY/IN-FLIGHT → SECURITY+GAPS → TARGET pass |
| `investigation/architecture-decisions.md` | The five decisions that gated the explorer change |
| `investigation/architecture-freeze.md` | This document |
| `investigation/repo-notes/*.md` | Ten per-repository notes with file:line evidence |

### Source repositories — pinned HEADs, all verified clean at freeze

| Repository | HEAD |
|---|---|
| `olbrain-agent-runtime` | `b2401a0` |
| `olbrain-agent-engine` | `8720720` |
| `olbrain-research-design` | `d044fce` |
| `olbrain-research-runtime` | `d1caecd` |
| `olbrain-workflow-runtime` | `5d48437` |
| `olbrain-knowledge-vault` | `6d76083` |
| `olbrain-shared` | `a837b95` |
| `olbrain-studio` | `252f7887` |
| `olbrain-studio-backend` | `6ada46a` |
| `olbrain-agent-design` | `bbc85c8` |

All ten are read-only investigation copies and were confirmed unmodified
(`git status --porcelain` empty) at this freeze. `olbrain-research-runtime`'s local HEAD is one
merge commit behind `origin/main` (`d2e3f7a`, an unrelated citation-audit change) — confirmed
irrelevant to every finding.

## 7. Remaining questions — implementation, not architecture

None of the following changes the semantic contract. Each is a decision for whoever builds or
operates the system.

**Implementation-level:**

1. Predicate Policy Registry population — the concrete authority domain name, source ranks and
   approval rule for the operational-correction lane in item 3.
2. Whether and how `agent_user_memory` / `agent_datastores` blobs decompose into per-field
   Claims, and the migration ordering.
3. How the three independent `agent_datastores` writers reconcile once OCC exists.
4. How the existing production fragments (CAS in research-design, `orchestrator_generation`
   fencing in workflow-runtime, `context_facts`' verify-before-active) are generalised into the
   shared mutation contract — or replaced.
5. Where the shared policy engine sits relative to the six async pipelines that currently write
   directly to their final stores (§9's crossing rule is the largest structural gap the
   reconciliation found).
6. Adding `organization_id` to the schemas that lack it — `AgentMemory`, `ExceptionPattern`,
   `LearnedOverride`, the research learned models, and `agent_datastores` entries. Note most
   use `extra="forbid"`, so this is a model change, not a field-population exercise.
7. Whether the unsalted `person_hash()` keying is replaced, and what the migration looks like.

**Operational / residual investigation** (from `store-inventory.md`, none blocking):

8. GCS storage-layer internals beneath `workflow_definitions`' metadata/body split.
9. The one-time legacy inline-JSON migration script, referenced in code but not located.
10. `workflow_items`' own org-binding model and Pydantic definition.
11. Origin of the `is_enabled` MCP-config spelling — no confirmed writer.
12. `scripts/merge_organizations.py` semantics.
13. Tenant-routing between the shared Firebase project and `clix-capital-prod`.

**Explicitly not reopened:** the five object classes, the Evidence→Claim→Policy→State ordering,
the nine control planes, and the out-of-scope status of procedural memory.

## 8. What this freeze does NOT do — §16 remains open

**This document freezes the semantic-scope question. It does not satisfy the contract's own
freeze condition.**

§16 states: *"The contract is semantically frozen once every row below is either filled or
formally marked as deployment-time configuration with a named owner,"* and *"No implementation
team may silently invent a value for any of them."*

That table was checked at this freeze. **Eight parameters; none confirmed.**

| # | Parameter | Owner | Status |
|---|---|---|---|
| 1 | Capability revocation TTL | Security | Proposed, unconfirmed |
| 2 | Policy compatibility window | Architecture | Proposed, unconfirmed |
| 3 | External predicate freshness SLAs (`max_staleness`, `stale_read_policy`, `stale_write_policy`) | Domain owner per predicate | **Open** |
| 4 | Derived-object recomputation SLA and max un-recomputed window | Operations + Legal | **Open** |
| 5 | Aggregate retention and deletion classification, per dataset | Legal / compliance / data governance | **Open** |
| 6 | Which operations require online authorization vs. a cached capability | Security | **Open** |
| 7 | Nonce and replay-cache scope for sensitive operations | Architecture | Proposed, unconfirmed |
| 8 | Bulk-deletion retry and dead-letter policy for generation-rejected workers | Operations | **Open** |

Five are Open with no proposed default; three have a proposed default that remains unconfirmed.

**Consequence:** the contract is **not** semantically frozen by its own criterion. These are
governance decisions requiring named owners — Security, Architecture, Operations, Legal — not
implementation choices, and §16 forbids inventing them. Filling this table is the next
governance gate after this document.

## 9. Deferred governance action

The contract currently contains **no scope-exclusion vocabulary at all** — searching it for
"out of scope", "outside the scope", "does not model" returns nothing. This freeze therefore
introduces the first explicit exclusion into the architecture baseline, and it currently lives
only here, in an investigation document.

Recording the exclusion in the contract itself would be **Patch 19** through the existing
Corrective Patch Set mechanism, owned by whoever owns `architecture-contract.md`. That is
deliberately deferred per instruction — but it is named here so the deferral does not quietly
become permanent. Until it lands, `architecture-contract.md` and this document must be read
together: the contract does not yet state its own boundary.

---

## Freeze summary

| Item | Status |
|---|---|
| Five object classes | **FROZEN** — unchanged, no sixth class |
| Procedural / heuristic memory | **OUT OF SCOPE for v2.0** — adopted, no contradiction found |
| `LearnedOverride` → Claim via Predicate Policy | **CONFIRMED** — no contract change required |
| Explorer annotation approach | **FROZEN** — target-first with a collapsible current-production overlay |
| Production security findings | **SEPARATE WORKSTREAM** — not architecture, not gating |
| `architecture-contract.md` | **UNMODIFIED** |
| §16 configurable parameters | **OPEN** — 8 rows, 0 confirmed; the next governance gate |
| Patch 19 (record the exclusion in the contract) | **DEFERRED**, owner: contract owner |

No file outside `investigation/architecture-freeze.md` was modified to produce this document.
`artifacts/architecture-contract.md`, `artifacts/state-semantics-explorer.html`, and every
repository under `repos/` remain untouched.
