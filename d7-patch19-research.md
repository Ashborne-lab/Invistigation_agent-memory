# D7 / Patch 19 — Recording the procedural-memory exclusion in the contract (research)

Date: 2026-09-26. Read-only. **The contract is not modified and adoption is not recommended.**

Sources: `artifacts/architecture-contract.md` (normative, unmodified, md5
`97c1fa3bcea1d71210c0429b1d113d07`) · `investigation/architecture-freeze.md` ·
`olbrain-agent-runtime 8df0e02` · `olbrain-workflow-runtime 1978f4a`.

---

## 1. What is normative today

`[CONTRACT]` `architecture-contract.md:3,9` — *"Version 2.0 — Baseline contract with Corrective
Patch Set 1–18 applied … This document is the single normative source for OLBrain state
semantics."* The patch mechanism is therefore established and has been used eighteen times; Patch
19 would be routine in form.

`[CONTRACT]` The contract defines five object classes — Evidence, Claim, Current State, Memory,
Narrative Memory — and states that the five definitions MUST NOT be merged.

**`[CODE]` The contract contains no scope-exclusion vocabulary at all.** A case-insensitive search
of `architecture-contract.md` for `out of scope`, `outside the scope`, `does not model`,
`not modelled` and `procedural memory` returns **zero matches**. The contract nowhere states what
it declines to cover.

---

## 2. What exists only in investigation artifacts

`[INFERENCE]` The exclusion is fully reasoned, but it lives entirely outside the normative source.
`investigation/architecture-freeze.md` §2 adopts, verbatim:

> *"Procedural / heuristic memory is outside the v2.0 Evidence / Claim / Current State / Memory /
> Narrative Memory semantic contract."*

with three supporting elements:

- **What it covers** — `agent_learned_patterns` (`olbrain-agent-runtime`: `intent_examples` plus
  `tool_sequence`, with usage/failure counters) and
  `workflow_agent_memory.exception_patterns` / `ExceptionPattern` (`olbrain-workflow-runtime`:
  `what_failed` / `what_human_did` / `resolution` plus `resolution_data`).
- **Why** — *"Both are procedures, not assertions … the content is a recipe, not a fact about a
  subject."* There is no natural `(subject, predicate, object)` decomposition.
- **What it refuses to do** — it does not classify procedural memory as a Claim (which would
  require inventing a predicate shaped `procedure_for_X = [step1, step2, …]`, *"which every Claim
  example in the contract avoids"*), does not classify it as Narrative Memory (defined as retained
  *conversational context*, not retained *action sequences*), and **does not create a sixth object
  class**.

`architecture-freeze.md:359-360` records the disposition: *"Recording the exclusion in the contract
itself would be **Patch 19** through the existing Corrective Patch Set mechanism, owned by whoever
owns `architecture-contract.md`."* `:378` lists it **DEFERRED**, owner: contract owner.

`[CODE]` Deferred by instruction, not declined — consistent across the freeze document and the
decision dashboard.

---

## 3. Exactly what Patch 19 would change

`[INFERENCE]` It would add, to the normative contract, a statement of a **boundary** — the first
such statement in the document. Specifically:

1. A sentence placing procedural/heuristic memory outside the five-object contract.
2. Optionally, the two named current-system exemplars (`agent_learned_patterns`,
   `workflow_agent_memory.exception_patterns`) as illustrations.
3. Implicitly, a *vocabulary* for exclusion that the contract currently lacks, and which future
   patches could reuse.

**What it would not change:** the five definitions, their relationships, resolution semantics,
authority domains, deletion rules, or any §16 row. `[INFERENCE]` The object count stays at five —
`architecture-freeze.md:103` states *"No sixth object class is added. The count stays at five."*

---

## 4. Does anything currently depend on Patch 19?

`[INFERENCE]` **No document's correctness depends on it, but two depend on it being *read
alongside* the contract.**

- `architecture-freeze.md` §2 is the only place the exclusion is stated. Without Patch 19, anyone
  reasoning from `architecture-contract.md` alone would find procedural memory unaddressed and
  could reasonably map `agent_learned_patterns` into Memory.
- `investigation/architecture-decisions.md` Decision 1b left procedural memory *deliberately
  unresolved*; the freeze later resolved it. Patch 19 would make that resolution normative rather
  than investigative.
- **D5** (`d5-authority-research.md`) is adjacent but distinct: it concerns *operational
  corrections* (`LearnedOverride`), which the freeze maps **into** the model via a Predicate
  Policy. `[INFERENCE]` The two must not be conflated — `ExceptionPattern` is excluded, while
  `LearnedOverride` is included. A Patch 19 that was drafted loosely could accidentally exclude
  the lane D5 is trying to include. **That is the main drafting risk and it is worth stating to
  the contract owner.**

The dashboard's own evidence: *"If not adopted, `architecture-contract.md` and
`architecture-freeze.md` must be read together indefinitely."* `[INFERENCE]` That is the whole
cost — a documentation-coherence cost, not a functional one.

---

## 5. Would adopting it alter the five-object semantic scope?

`[INFERENCE]` **No, on the freeze's own reasoning — but the reasoning is weaker than it looks, and
the freeze says so.**

`architecture-freeze.md:62-66` is unusually candid:

> *"Someone could argue procedural memory is already covered by Memory and needs no [exclusion] …
> not because procedural memory provably fails the Memory definition. That is the weaker claim."*

`[CONTRACT]` Memory's §1 definition enumerates *"lessons"*, and a learned tool-sequence can be read
as one. `[INFERENCE]` So the exclusion is **admissible because nothing in the contract requires
exhaustive coverage**, not because procedural memory demonstrably fails the Memory test. Adopting
Patch 19 therefore does not *narrow* an established scope; it *declares* a boundary that was
previously undetermined.

**That distinction matters for the decision.** If the contract owner reads Memory as already
covering lessons, Patch 19 is not a clarification but a substantive narrowing — and should be
weighed as such. `[UNDECIDED]`

---

## 6. Downstream implementation consequences

`[INFERENCE]` Minimal, and they run in one direction.

- **If adopted:** `agent_learned_patterns` and `workflow_agent_memory.exception_patterns` are
  formally out of scope, so no migration of those stores into the five-object model is required,
  and no PostgreSQL tables are owed for them in the target design. They would continue to exist as
  operational stores outside the semantic contract.
- **If declined:** those two stores return to the set that the target model must eventually
  account for, and someone must decide whether they become Memory (accepting the "recipe as
  lesson" reading) or something else. `[INFERENCE]` That would be new modelling work, not a
  reclassification.
- **Either way:** nothing blocks today. `[CODE]` Both stores exist and function; neither is
  scheduled for migration; no code changes on either branch.

`[INFERENCE]` **Consequence for the PostgreSQL gate:** adopting Patch 19 slightly *reduces* schema
scope by removing two stores from consideration. Declining it slightly *increases* it. Neither
blocks schema design, because both stores are peripheral to the person/claim/state core — which is
why D7 is correctly recorded as blocking nothing.

---

## 7. The exact unresolved decision

`[UNDECIDED]` Adopt Patch 19, or decline it. Owner: the contract owner only.

Sub-questions the owner may want settled in the same breath, `[INFERENCE]`:

1. Does the exclusion name exemplars, or state only the principle? Naming current stores dates the
   contract; stating only the principle risks ambiguity about what counts as procedural.
2. Does it introduce reusable exclusion vocabulary, or a one-off sentence? `[INFERENCE]` If more
   exclusions are anticipated — and person identity may be one, per
   `person-identity-architecture-research.md` N2 — reusable vocabulary is worth more than the
   sentence.
3. Is the boundary drawn so that `LearnedOverride` remains *inside* (§4)?

---

## 8. Assessment

`[INFERENCE]` D7 is the lowest-cost open item on the board: it blocks nothing, affects no code,
needs no measurement, has a documented mechanism with eighteen precedents, and has a single named
owner. It has now been carried across four investigation passes. **Evidence supports it being
cheap to resolve either way**; the reason to resolve it is that carrying an undecided boundary is
itself the cost, and that cost compounds as more documents need reading together.

This is an observation about process, not a recommendation about the answer.

---

## 9. Limitations

1. The contract was searched for exclusion vocabulary, not read in full this pass; a boundary
   expressed in wording not matched by those five phrases would have been missed. `[INFERENCE]`
2. Whether the contract owner reads Memory's *"lessons"* as covering tool-sequences is the pivot
   of §5 and is `[UNDECIDED]`.
3. No assessment is offered of whether the exclusion is *correct* — only of what adopting or
   declining it would change.
