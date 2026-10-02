# Architecture Decision Gate — Pre-Explorer-Modification Decisions

Review date: 2026-09-19. Inputs: `investigation/reconciliation.md`, `investigation/store-inventory.md`,
`investigation/MASTER.md`, `artifacts/architecture-contract.md` (read for reference only).

**What this document is:** five architectural decisions that must be settled before
`state-semantics-explorer.html` can be modified, since modifying it without first resolving
them would mean inventing answers to open design questions inside the HTML itself — exactly
the kind of silent decision `CLAUDE.md` and the contract's own governance language (§16: "No
implementation team may silently invent a value for any of them") both prohibit.

**What this document is not, per explicit instruction:** it does not modify
`artifacts/architecture-contract.md`, does not modify `artifacts/state-semantics-explorer.html`,
does not touch any repository, and does not implement anything. Every recommendation below that
would require a contract change is flagged as such and left unmade — a contract change is a
governance action for whoever owns `architecture-contract.md` (the document's own precedent is
the versioned "Corrective Patch Set 1–18" mechanism; a new decision adopted here would become
Patch 19+ through that same explicit process, not a silent edit).

---

## Decision 1 — Procedural / Heuristic Memory

**The evidence, re-examined before choosing:** the reconciliation groups `agent_learned_patterns`
and `workflow_agent_memory`'s `exception_patterns`/`learned_overrides` together as "doesn't fit
Claim or Narrative Memory," but they are not actually one shape. Two distinct things are being
asked about:

- **`LearnedOverride`** (`field`, `selector`, `correction`, `status: suggested→active→retired`,
  `confidence`, `evidence_exception_ids`/`evidence_run_ids`, `approved_by`/`approved_at`,
  `contradiction_count`) is, structurally, an assertion: *"for this step/field/selector, the
  correct value is X."* It has a subject (the step+field+selector combination), a predicate
  ("correct value"), an object (the correction), an evidence trail, and a lifecycle vocabulary
  (`suggested`/`active`/`retired`) that is a near-direct relabeling of the contract's own
  `pending`/`active`/`retracted`.
- **`ExceptionPattern`** (`agent_learned_patterns`'s `intent_examples`+`tool_sequence`, and
  workflow's own `what_failed`/`what_human_did`/`resolution`+`resolution_data`) is not an
  assertion about a subject's state at all — it is a **procedure**: an ordered sequence of
  actions to take when a situation recurs. It has no natural `(subject, predicate, object)`
  decomposition; the "content" is a recipe, not a fact.

Treating these as one question and picking one option for both would misfit one of them no
matter which option is chosen. The two are addressed separately below.

### 1a. `LearnedOverride`-shaped data (value corrections)

**Decision: Option B — model as Claims**, using the existing Predicate Policy mechanism, not a
new object class.

**Reasoning:** A `LearnedOverride` already has everything a Claim needs: a subject
(`step_id`+`field`+`selector`), a predicate (the corrected field name), an object (the
correction), `source`/`provenance` (evidence_exception_ids/evidence_run_ids), and an
`assertion_status` lifecycle that maps cleanly (`suggested→pending`, `active→active`,
`retired→retracted`). The contract's authority-domain model already anticipates exactly this
kind of thing: §5's authority matrix lists `Semantic inference` → `Inference pipeline` →
`Candidate only`, `Evidence`, `Derived`, `Must retain provenance` — a `LearnedOverride` is a
semantic-inference-derived candidate correction, which the contract already has a governance
lane for. Modeling it this way requires **no change to the contract's normative text** — it
only requires a new Predicate Policy Registry entry (e.g. `authority_domain =
OPERATIONAL_CORRECTION`, `llm_write_mode` permitting a `candidate`/`pending` write with human
approval required to reach `active`) — precisely the kind of "intentionally configurable
parameter" §16 already reserves for domain owners, not a contract edit.

**Impact on the architecture contract:** none required. This is a Predicate Policy Registry
population exercise, which the contract already defers to implementation/governance (§16).

**Impact on the HTML explorer:** the explorer's existing Predicate Policy Registry panel would
need one or more example policy rows for this authority domain, and the "current production"
annotation (Decision 2) attached to the Claim concept would note `LearnedOverride`
(`workflow_agent_memory`) as a partial-fit current analog.

**Does the contract need to change:** **No.**

**Unresolved issues:** the CAS/versioning half of this is not yet a real Claim in production —
`LearnedOverride` today is a plain array entry inside one mutable `workflow_agent_memory`
document, with no `state_version`, no OCC, and (per store-inventory.md) no `organization_id` at
all. Recommending the *conceptual* mapping does not resolve the *implementation* gap; that gap
is real and is correctly left in "TARGET ARCHITECTURE, not yet built" territory rather than
"already effectively a Claim."

### 1b. `ExceptionPattern`/`agent_learned_patterns`-shaped data (tool-sequence recipes)

**Decision: neither A nor B cleanly applies — deferred, not resolved, and explicitly not forced
into either bucket.**

**Reasoning:** Forcing a tool-call sequence into Claim would violate the contract's own
definition (a Claim is a `(subject, predicate, object)` assertion; a sequence of steps is not
reducible to one without inventing a predicate like `"procedure_for_X = [step1, step2, ...]"`,
which every other Claim example in the contract explicitly avoids — see §13 Example 20's
treatment of "Customer prefers Pro models" as a scalar preference Claim, never as an ordered
plan). Forcing it into Narrative Memory would also violate that category's own definition (§1:
"non-assertive... the tone of a previous conversation... unresolved conversational context" —
Narrative Memory is explicitly about *retained context*, not *retained action sequences*).
Introducing a new object class (Option A, a sixth category alongside Evidence/Claim/Current
State/Memory/Narrative Memory) is the only clean fit for the *shape* of this data — but §1 is
explicit that the five classes "MUST NOT be merged" and, by clear implication of that framing,
adding a sixth is a change to the contract's foundational terminology, not an implementation
detail like 1a's policy-registry entry. That is exactly the kind of decision this document is
not authorized to make silently.

**Impact on the architecture contract:** IF Option A were adopted, §1 (add a sixth object
class), §14's master decision matrix and authority matrix (add a row), and §15's final
normative ordering diagram (decide where "Procedural Memory" sits in the
Evidence→Claim→Policy→Resolution→State/Memory→Retrieval→Context→LLM chain) would all need
edits. This is a real, multi-section contract change, not a footnote.

**Impact on the HTML explorer:** until this is resolved, the explorer's current-state annotation
layer (Decision 2) should represent `agent_learned_patterns` and `ExceptionPattern` with an
explicit **"no target-architecture mapping exists yet"** marker — not silently parked under
Memory or Narrative Memory just because those are the closest existing bins.

**Does the contract need to change:** **Only if Option A is chosen — and this document does not
choose it.** The recommendation here is to *not* decide between A and B for this specific data
shape in this pass; a real decision requires the contract's owner, not this investigation.

**Unresolved issues:** this is the one item in this whole document that is a genuine open
question rather than a resolved recommendation. Two paths forward, both legitimate: (a) escalate
to whoever owns `architecture-contract.md` for an explicit sixth-category decision, or (b)
deliberately scope tool-sequence/recipe memory as **out of the contract's five-class model
entirely** — treated the way the contract already treats retrieval projections (non-authoritative,
rebuildable, outside the Evidence/Claim/State/Memory taxonomy) — which would require no contract
edit at all, just an explicit statement that this data type isn't covered by this contract.
Recommend (b) as the lower-risk default only because it requires no contract change, but this
document does not have the authority to make that call the actual answer.

---

## Decision 2 — Current vs. Target Explorer Structure

**Decision: neither a full toggle nor a literal side-by-side. An annotation/overlay layer on
the existing target-only structure** — the explorer keeps its current pipeline-first,
target-architecture-first design, and gains a per-node "current production" annotation that can
be expanded/collapsed, sourced directly from `store-inventory.md`/`reconciliation.md`.

**Reasoning:** Reconciliation §4's own mapping table shows the current↔target relationship is
**asymmetric and fuzzy**, not a clean 1:1: some current mechanisms map cleanly to one target
concept (`context_logs`→Evidence, `agent_sessions.summary`→Narrative Memory), some map partially
with named gaps (`context_facts`→Claim, missing a Predicate Policy Registry and typed
subject/predicate/object shape), some map to a *fragment* of a target mechanism rather than the
whole concept (`orchestrator_generation`→OCC-adjacent fencing, `write_profile`'s CAS→a working
fragment of `expected_version`), and some don't map at all (`agents/{id}`, credentials — outside
the contract's five-class scope entirely). A binary toggle would force every panel into either
"current" or "target" framing and lose the fragment/partial-fit nuance that is the single most
useful output of the whole reconciliation effort. A literal side-by-side view would force an
artificial pairing for the ~40% of stores that don't have a clean 1:1 counterpart, misrepresenting
confidence the investigation doesn't have. An annotation layer, by contrast, naturally
represents "no current analog," "partial fit with named gaps," and "structural fragment already
in production" (Decision 5) as different annotation *contents* on the same underlying node,
without forcing the explorer's core information architecture to change. It also directly reuses
`state-semantics-explorer.html`'s own existing extensibility points — the explorer already has a
plane-coloring system (`.plane-ev`/`.plane-cl`/`.plane-st`/`.plane-pr`/`.plane-na`) and a badge
system (`.b-VALUE`, `.b-CONFLICT`, etc.) that an annotation layer can extend rather than replace.

**Impact on the architecture contract:** none. This is purely an explorer-presentation decision.

**Impact on the HTML explorer:** every major panel (pipeline nodes, Predicate Policy Registry,
resolution trace, state result matrix, deletion/lineage view) would need an optional annotation
slot wired to `store-inventory.md`'s per-store data. This is a real, non-trivial addition to the
explorer's data model (the explorer is currently pure target-architecture content with no
current-state data embedded at all) — but it is additive, not a restructuring of the existing
target-only views, which is the lowest-risk way to satisfy "current-state awareness" without
compromising the explorer's original purpose (per `CLAUDE.md`: "The HTML artifact is the TARGET
architecture model").

**Does the contract need to change:** **No.**

**Unresolved issues:** which specific stores get an annotation and which don't (i.e., how much
of `store-inventory.md`'s ~30 rows actually needs a home in the explorer vs. staying in the
markdown investigation trail) is a scoping question for whoever implements this, not decided
here. Also unresolved: whether annotations should be always-visible or opt-in/collapsed by
default — a UX call, not an architecture call, deliberately left open.

---

## Decision 3 — Security Findings Placement

**Decision: C — both, but asymmetrically.** Inside the explorer: a brief, clearly-labeled
pointer only, attached to the explorer's existing "Authorization" control-plane concept, stating
that current production has open authorization gaps and directing to a separate view for
specifics. The actual finding detail (per-collection verdicts, severity, evidence, git-history
signal) stays entirely in a separate security/production-risk artifact — not duplicated into the
explorer's body.

**Reasoning:** The contract itself already treats authorization as one of nine *independent*
control planes (§15: "Authorization — who may see or use it" — orthogonal to Predicate Policy,
Validity, State Version, etc.) and is explicit that "a failure in one MUST NOT be compensated by
another." That same orthogonality argument cuts the other way here: the contract's authorization
*principle* (resolution happens under system policy; authorization gates the read at the end,
per §6) is sound and is not what store-inventory.md's Security Finding E found broken — what's
broken is a completely different layer (Firestore client-side security rules in
`olbrain-studio`, a current-production implementation detail with no relationship to whether the
*target* architecture's authorization design is correct). Embedding live, will-eventually-be-fixed
security-bug detail inside a semi-permanent architecture reference conflates two things with
different audiences and different lifecycles: architects designing the state model (who need a
stable reference) versus whoever owns `firestore.rules` (who needs a live, fixable, ticketable
punch list that goes stale the moment a rule is patched). The user's own framing — "Keep
production security remediation separate from target-state semantics" — is a direct instruction
toward this same conclusion, which this decision follows rather than reinterprets.

**Impact on the architecture contract:** none. The contract's authorization control-plane
concept remains correct and unchanged; this decision is about where verified-production-bug
*evidence* lives, not about the target model.

**Impact on the HTML explorer:** the existing "Authorization" node/panel gains one short
annotation (something like "current production: not yet consistently enforced at the Firestore
rules layer — see [security view]") rather than an inline table of eleven exposed collections.
A separate artifact (could be a dedicated `artifacts/`-level HTML view, or simply continuing to
maintain `store-inventory.md`'s Security Findings section as the canonical source) holds the
actual detail.

**Does the contract need to change:** **No.**

**Unresolved issues:** whether the "separate view" should itself become a new HTML artifact
(with its own severity/status tracking, closer to a security dashboard) or remain the existing
Markdown investigation trail is a tooling decision, not an architecture decision, and is left
open here. Also open: who owns keeping that separate view current as fixes land (a process
question, outside this document's scope).

---

## Decision 4 — Migration Visualization (six-way classification)

**Decision: extend the explorer's existing badge system with a second, visually distinct badge
family for the six classification labels, rendered exclusively within the Decision-2 annotation
layer (never on the target-architecture pipeline nodes themselves, which are always
"TARGET ARCHITECTURE" by definition and don't need the label repeated).**

**Reasoning:** The explorer already has a working badge convention (`.b-VALUE`/`.b-CONFLICT`/
`.b-UNKNOWN`/etc., each a colored pill tied to a CSS custom property) used for Claim/resolution
*outcomes*. Reusing that exact class family for investigation-status labels would create a real
collision of meaning — a viewer could confuse "this Claim resolved to CONFLICT" with "this
store's classification is CONTRADICTED BY SOURCE," which are unrelated axes (one is a runtime
resolution result, the other is a documentation-confidence label). A visually related but
namespaced-distinct family (e.g. `.mig-*` prefixes, same pill shape and sizing for visual
consistency, different color assignments) avoids that collision while still feeling native to
the explorer's existing design language. Suggested color intent, not a final palette: VERIFIED
CURRENT and TARGET ARCHITECTURE should read as "confirmed, trustworthy" (distinct hues, since
one is present-tense fact and one is future-tense design — they must not share a color despite
both being "good news"); LEGACY as muted/deprioritized; IN-FLIGHT MIGRATION as active-attention
(closest to the existing warn/amber semantics already used for STALE/CONFLICT); OPEN QUESTION as
a dashed/hatched treatment rather than a solid fill, signaling "we don't know yet" as distinct
from LEGACY's "we know, it's old"; CONTRADICTED BY SOURCE as its own distinct treatment,
deliberately not reusing the explorer's existing `.b-deny`/`.b-ACCESS_DENIED` red, since that red
is already claimed by target-architecture authorization-denial semantics and reusing it here
would imply a security meaning that isn't intended.

**Impact on the architecture contract:** none — this classification scheme belongs to the
investigation methodology (`CLAUDE.md`), not to the contract.

**Impact on the HTML explorer:** a new, small, self-contained CSS/badge addition, applied only
within annotation content (Decision 2) — no change to the explorer's core pipeline/registry/trace
views themselves.

**Does the contract need to change:** **No.**

**Unresolved issues:** exact color values are a design-system detail properly deferred to
whoever implements this (and to the project's `dataviz`/`artifact-design` conventions, not
architecture governance). Also open: whether a store can carry more than one label
simultaneously over time (e.g., shown as IN-FLIGHT MIGRATION today with a note that it becomes
LEGACY once the migration completes) — a versioning/history question for the annotation data
model, not resolved here.

---

## Decision 5 — Structural Fragments (partial target implementations already in production)

**Decision: represent fragments as an orthogonal flag within the Decision-2 annotation layer —
not a seventh migration-status label, and not a wholly new UI section — reusing the explorer's
existing "Normative Examples" rendering pattern (numbered, expandable walkthroughs) for the
handful of fragments worth walking through in detail.**

**Reasoning:** "This store is VERIFIED CURRENT" (Decision 4's axis) and "this store already
partially implements a target mechanism" (this decision's axis) are independent facts that can
both be true of the same store at once — `context_facts`' verify-before-active gate is
simultaneously VERIFIED CURRENT (it's real, shipped code) and a structural fragment of the
target's Claim-promotion model. Collapsing these into one axis would force an artificial choice
between them. Treating "fragment" as a boolean flag alongside (not instead of) the six-way
classification preserves both facts. For the four specific fragments reconciliation identified
(`context_facts` verify-before-active, `write_profile`'s CAS pattern, `orchestrator_generation`'s
fencing, `agent_sessions.summary`'s Narrative-Memory shape), the explorer already has a proven UI
pattern for exactly this kind of "walk through a concrete scenario step by step" content — the
contract's §13 Normative Examples, already rendered in the explorer as an expandable numbered
trace. Reusing that pattern for "production precedents" keeps the explorer's visual vocabulary
consistent and avoids inventing a new interaction model for what is structurally the same kind
of content (a concrete walkthrough, evidence-backed, illustrating a principle).

**Impact on the architecture contract:** none directly — but these fragments are the strongest
available evidence that the target architecture is achievable incrementally rather than as a
rewrite, which is relevant context for the contract's own §16 "Intentionally configurable
parameters" governance process (e.g., a policy-compatibility-window decision might reasonably
cite that research-design already has a working CAS pattern to build from). That's a
governance-input observation, not a required edit.

**Impact on the HTML explorer:** a boolean "production precedent exists" flag on the annotation
layer, plus a small number of expandable walkthroughs (four, today) reusing the
Normative-Examples rendering pattern.

**Does the contract need to change:** **No.**

**Unresolved issues:** whether more fragments exist beyond the four reconciliation named (a
deeper investigation question, not an architecture-decision question) is open; this document
does not expand the search, only decides how to represent what's already been found.

---

## Cross-cutting note

Decisions 2, 4, and 5 are not independent — they collectively describe **one** annotation-layer
mechanism in the explorer (current-state content, a six-way status badge, and a fragment flag,
all attached to the same per-node annotation), not three separate subsystems. Whoever eventually
implements the explorer change should treat them as one data model with three facets, not three
separate features. Decision 3 deliberately does *not* join that same layer — production security
findings are explicitly kept out of it, per the user's own instruction to separate remediation
from semantics.

Decision 1b is the one item in this document that remains a genuinely open question rather than
a resolved recommendation, and is flagged as requiring the contract owner's explicit decision
before any procedural/heuristic-memory content can be annotated into the explorer at all. Until
it's resolved, `agent_learned_patterns` and `ExceptionPattern` should be annotated as "no target
mapping yet" rather than silently placed under Memory or Narrative Memory.

No file outside `investigation/architecture-decisions.md` was modified to produce this document.
`artifacts/architecture-contract.md`, `artifacts/state-semantics-explorer.html`, and every
repository under `repos/` remain untouched.
