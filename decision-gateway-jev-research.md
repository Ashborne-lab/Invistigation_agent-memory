# Decision Gateway / "Jev" — boundary research

Date: 2026-09-26. Read-only. **Jev is not implemented, not designed, and not assumed to belong in
the system.** No model is inserted anywhere.

**What this is.** A survey of places where OLBrain currently asks an LLM or application code to
make a *bounded judgement*, assessed for whether that judgement could in principle be represented
as a typed decision. The output is a set of candidate boundaries and — equally important — a set
of places where a decision model would be **wrong**.

Commits as listed in the companion reports.

---

## 1. The contract's constraints come first

`[CONTRACT]` Any Decision Gateway proposal is bounded by rules the contract already states. These
are not preferences; they are normative and they eliminate several otherwise-plausible candidates
before analysis begins.

1. *"The conversation remains evidence. It **cannot modify identity, role, authorization, tenant
   membership, or security policy**."* (`architecture-contract.md:1219`)
2. `account_role` — authority domain `IDENTITY_SECURITY`, `allowed_writers = IDENTITY_SYSTEM`,
   **`LLM_WRITE = FORBIDDEN`, `USER_WRITE = FORBIDDEN`** (`:1212-1213`).
3. The resolver *"MUST NOT select a value on the basis of recency alone, embedding similarity,
   **LLM confidence**, or number of mentions."* (§6)
4. *"A value is authoritative only where Policy, Authority, Temporal Validity, Scope and
   Resolution Semantics jointly establish it — never because it is recent, frequently mentioned,
   semantically similar, vector-retrieved, LLM-generated, or present in a graph."* (`:1007`)

`[INFERENCE]` Taken together: **a model may inform a judgement, but may never be the thing that
makes a value authoritative, and may never touch identity or authorization.** Every candidate
below is assessed against that line.

---

## 2. Candidate inventory

### C1 — Identity candidate resolution

- **Input state.** Two subjects, the observed identifiers attached to each, and any co-occurrence
  evidence.
- **Allowed output space.** `[INFERENCE]` A ranked candidate list with an evidence citation —
  **never** a merge.
- **Nature.** Mixed, and the split is unusually clean. `[CODE]` Normalisation is deterministic
  (`normalise_contact_phone`); co-occurrence detection is *evidence-based and deterministic*
  (`lead_people` reads a profile carrying both values — it does not infer); anything weaker
  (name + city, fuzzy match) is **probabilistic**.
- **Affects authority?** No, if output is a candidate. **Yes**, if it merges — and then it is
  writing identity, which is `LLM_WRITE = FORBIDDEN` territory by analogy with `account_role`.
- **Affects authorization?** `[CONTRACT]` Must not — `RESOLVES_TO` is explicitly non-authorizing
  and the canonical entity is *"a semantic anchor, not a privacy bridge"*.
- **Affects current-state truth?** Indirectly and substantially — merging changes which Claims
  resolve for a subject (`person-merge-current-state-memory-research.md` §2).
- **Verdict.** `[INFERENCE]` **The single strongest candidate**, and precisely because it can be
  bounded to *triage*: "given this pair and this evidence, is it worth asking a human?" Deterministic
  code handles the strong evidence; a model would only rank the weak. Execution stays human —
  `[CODE]` which is what `research_clients` already chose (operator-initiated, `updated_by` audit).
- **Falsification.** If §2's co-occurrence measurement shows strong evidence is common, the weak-
  evidence tier is small and the candidate loses most of its value. `[UNMEASURED]`

### C2 — Memory classification

- **Input state.** An extracted statement plus its conversational context.
- **Output space.** Which object class it becomes — Evidence, Claim, Memory, Narrative Memory — or
  nothing.
- **Nature.** **Semantic.** There is no deterministic rule; the contract's classes are defined by
  meaning.
- **Affects authority?** Yes — classifying something as a Claim makes it subject to resolution;
  classifying as Memory does not.
- **Affects current-state truth?** Yes, via the Claim path.
- **Verdict.** `[INFERENCE]` An LLM is already doing this today, implicitly, in the extract
  pipeline. Making it a **typed** decision with an explicit output space would be a genuine
  improvement in auditability — the decision currently happens inside a prompt and leaves no
  record of what was considered and rejected. **But** `[CONTRACT]` §4's prohibition means the
  classification must not by itself make a value authoritative; the Predicate Policy still governs.
  **A typed classifier is admissible; an authoritative one is not.**
- **Falsification.** `d7-patch19-research.md` shows the class boundaries are not fully settled —
  procedural memory's status is undecided. `[INFERENCE]` A typed decision over an unsettled
  taxonomy would harden a boundary the contract owner has not drawn. **This candidate is blocked
  behind D7**, which was not previously noticed.

### C3 — Claim-support judgement

- **Input state.** A candidate Claim and the Evidence records offered as support.
- **Output space.** Supported / not supported / insufficient.
- **Nature.** **Evidence-based**, with a semantic component (does this text actually assert that?).
- **Affects authority?** Yes, directly — `[CONTRACT]` support counting follows the lineage graph,
  and a Claim's survival under Evidence deletion depends on it.
- **Verdict.** `[INFERENCE]` Admissible as a *proposer*. The contract's `candidate → active` gate
  is exactly the right place for a human or policy check to sit between a model's proposal and an
  active Claim. `[CODE]` A working precedent exists: `context_facts` (agent-engine) has a genuine
  `candidate → active/invalid` status with a verify-before-active gate — the closest existing
  analogue to the contract's Claim anywhere in the platform.
- **Falsification.** If the verify gate is in practice auto-approved, the model becomes the
  authority in fact. `[UNMEASURED]` — whether `context_facts` candidates are human-verified in
  production is not known.

### C4 — Stale / fresh decision

- **Input state.** Observation timestamp, `max_staleness`, the policy's `stale_read_policy`.
- **Output space.** Fresh / stale, and the consequent read behaviour.
- **Nature.** **Deterministic arithmetic**, once the policy values exist.
- **Verdict.** `[INFERENCE]` **Not a decision-model candidate at all, and this is worth stating
  explicitly** because "freshness" sounds like a judgement. `governance-g3-research.md` §4
  establishes that roughly half of G3 is mechanical and the other half — `max_staleness` and the
  two policies — is a **domain-owner** decision, made once per predicate, not per read. A model has
  no role in either half: not in the arithmetic, and not in setting a business validity window.

### C5 — Tool routing

- **Input state.** Conversation, available tools, agent config.
- **Output space.** Which tool to call with what arguments.
- **Nature.** **Semantic.** Already an LLM decision today.
- **Affects authority / authorization / truth?** Not directly — though `[CODE]` a tool can write
  (the datastore tool) or reach external systems (`data_query`, which enforces read-only by regex
  and performs **no tenancy check on the SQL**, per Q-S4).
- **Verdict.** `[INFERENCE]` An LLM is the right mechanism; a typed decision adds little. The real
  exposure here is not the routing judgement but the **absence of a tenancy check on what the tool
  does** — a policy/code problem, not a decision-model one. Recorded so the candidate is not
  mistaken for an opportunity.

### C6 — Escalation / handoff

- **Input state.** Conversation state, confidence signals, configured handoff rules.
- **Output space.** Continue / escalate to a human.
- **Nature.** **Policy with a semantic trigger.**
- **Verdict.** `[INFERENCE]` A reasonable typed-decision candidate with low blast radius:
  escalating unnecessarily is cheap, failing to escalate is the harm, and the output space is
  binary and auditable. It touches neither authority nor truth. **The safest candidate on the
  list**, and correspondingly the least architecturally interesting.

### C7 — Conflict handling

- **Input state.** Two or more equally authoritative values for one subject/predicate.
- **Output space.** `[CONTRACT]` Only the policy's declared `RESOLVE_CONFLICT` operation.
- **Nature.** **Policy + human.**
- **Verdict.** `[INFERENCE]` **Explicitly excluded.** §6 forbids selecting on recency, similarity,
  **LLM confidence**, or mention count — which eliminates every signal a model would produce. A
  model may *present* a conflict and its provenance to a human; it may not resolve one. This is the
  clearest "must not" on the list.

### C8 — Operational-correction promotion (newly noted)

- **Input state.** A `suggested` `LearnedOverride` plus its `contradiction_count`.
- **Output space.** Promote to `active` / leave / retire.
- **Nature.** **Evidence-based with a policy threshold.**
- **Verdict.** `[INFERENCE]` `[CODE]` The lane already exists with a human step
  (`approve_override`, `d5-authority-research.md` §2.2). A model could rank which suggestions merit
  review. **But** §4.1 of that report finds the approver is currently self-asserted with no
  authorization gate — `[INFERENCE]` **adding an automated proposer to a lane whose human gate is
  unenforced would compound the weakness rather than help.** The authority question (D5) must be
  settled first.

---

## 3. Where a decision model must not sit

`[CONTRACT]` + `[INFERENCE]`, consolidated:

| Never | Because |
|---|---|
| Executing an identity merge | Writes identity; `person-merge…` §3.5 shows over-merge is a disclosure event |
| Resolving `CONFLICT` | §6 forbids every signal a model produces |
| Any authorization, tenancy or visibility decision | §1219; `RESOLVES_TO` is non-authorizing; deletion containment ≠ authorization inheritance |
| Writing `IDENTITY_SECURITY`-domain predicates | `LLM_WRITE = FORBIDDEN` |
| Making a value authoritative | `:1007` — authority comes from Policy, Authority, Temporal Validity, Scope and Resolution Semantics jointly |
| Deciding `max_staleness` | A business validity window, owned per R2 |

---

## 4. The pattern across candidates

`[INFERENCE]` Three observations that matter more than the individual entries.

1. **The admissible shape is consistently *propose*, never *decide*.** Every candidate that
   survives (C1, C2, C3, C6) survives in the form "produce a ranked, evidenced candidate for a
   policy or human to act on". Every candidate that fails (C4, C5, C7) fails either because it is
   deterministic or because the contract forbids the signal. **The contract has effectively
   pre-specified the Decision Gateway's output type**, and it is a candidate, not a verdict.

2. **The contract's `candidate → active` gate is already the boundary.** `[CODE]` It exists in
   `context_facts` today. A Decision Gateway would not need a new architectural seam — it would
   populate `candidate` and leave the gate alone. `[INFERENCE]` That is a strong argument that the
   concept is *compatible* with the target model; it is not an argument that it is needed.

3. **Two candidates are blocked by open governance decisions.** C2 is blocked behind D7 (the class
   taxonomy is unsettled); C8 is blocked behind D5 (the human gate is unenforced). `[INFERENCE]`
   Neither was previously connected to a decision-model question, and both mean a Gateway cannot
   be scoped before those close.

---

## 5. What would make this concrete

`[INFERENCE]` Not proposed as work, only as what the evidence says is missing:

1. **C1's weak-evidence tier is unsized.** The co-occurrence measurement
   (`person-identity-measurement-pass.md` §2.2) sizes the strong tier. Without it, nobody knows
   whether a ranking model would have anything to rank. `[UNMEASURED]`
2. **C3's gate behaviour is unknown.** Whether `context_facts` candidates are actually verified by
   a human or auto-promoted determines whether the precedent supports or undermines the model.
   `[UNMEASURED]`
3. **No typed decision record exists anywhere.** `[CODE]` There is no store of "a judgement was
   made, here were the options, here was the evidence, here was the outcome". Every candidate
   above would need one, and its absence is why these judgements are currently invisible.
   `[INFERENCE]` That record — not the model — is the part with standalone value, because it would
   make today's implicit LLM judgements auditable whether or not a Gateway is ever built.

---

## 6. Assessment

`[INFERENCE]` The evidence supports a narrow conclusion and does not support a broad one.

**Supported:** OLBrain contains at least four bounded judgements (C1, C2, C3, C6) whose inputs and
output spaces can be typed, and the contract's `candidate → active` gate is a natural place for
their output to land without touching authority. The contract has already drawn the line a Gateway
would have to respect, and drawn it unusually clearly.

**Not supported:** any claim that a Decision Gateway is needed, or that it would improve outcomes.
Three of the candidates are blocked behind open decisions (D5, D7) or unrun measurements, and the
one with the clearest value (C1) depends on a tier whose size is unknown.

**Neither supported nor refuted:** whether the auditability benefit in §5.3 — typed decision
records — is worth pursuing independently of any model. `[INFERENCE]` It is the only element here
with value under every branch, but assessing it was not this pass's task.

**This is research. No recommendation to build anything is made, and Jev is not assumed to belong
in the architecture.**

---

## 7. Limitations

1. Candidates were identified from architecture documents and code structure, not from a
   systematic sweep of every LLM call site. Others likely exist. `[INFERENCE]`
2. `[UNMEASURED]` No production behaviour was observed; all statements about what a model *would*
   see are inferential.
3. No evaluation of any decision-model technology, including Jev, is offered — only of where
   boundaries could exist.
4. C5's tenancy observation (Q-S4) is carried from prior investigation and was not re-verified at
   the current commits this pass.
