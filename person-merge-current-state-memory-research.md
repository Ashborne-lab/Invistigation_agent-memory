# Person merge vs Current State vs Memory (research)

Date: 2026-09-26. Read-only. **Does not decide whether merging is allowed — that is J2/J5.**

**Premise, as instructed:** assume only that Jay *may* answer that merges are permitted. Nothing
here argues for or against permitting them. The question is what the target contract can and
cannot express **if** they are.

Normative source: `artifacts/architecture-contract.md` (unmodified, md5
`97c1fa3bcea1d71210c0429b1d113d07`). Code at the commits listed in
`person-identity-measurement-pass.md`.

---

## 0. Headline — one prior conclusion is refined, and it is the important one

`person-identity-architecture-research.md` N1 and `person-identity-measurement-pass.md` §10 E both
state that merge produces *"a `CONFLICT` the contract forbids resolving by recency"* and call it
the deepest unsolved problem. **That overstates the gap.** `[CONTRACT]`

`CONFLICT` is not an error condition the contract leaves dangling. It is one of four first-class
resolution statuses for `SINGLE` predicates — `VALUE`, `EXPLICIT_NONE`, `UNKNOWN`, `CONFLICT`
(`architecture-contract.md:353-367`) — and §6 states its recovery path explicitly:

> *"The resolver returns `CONFLICT`. It MUST NOT select a value on the basis of recency alone,
> embedding similarity, LLM confidence, or number of mentions. The agent then either requests
> clarification or invokes the domain's conflict-resolution workflow. **Per §3, `CONFLICT` permits
> only the policy's declared `RESOLVE_CONFLICT` operation, so the state is recoverable without a
> blind overwrite.**"*

`[INFERENCE]` So the contract **already has the machinery** for two authoritative values colliding
on one subject/predicate. Merge does not create a novel semantic problem in the Claim/Current
State plane; it creates *more instances of a case the contract already models*. What the contract
lacks is anything about identity merge as an **event** — not a way to represent its consequence.

That refinement moves the deepest problem elsewhere. On the analysis below it is **Memory**
(§3), not Current State.

---

## 1. Claims

**Setup.** A has active Claim `(A, P, X)`. B has active Claim `(B, P, Y)`. A and B are then
resolved as the same human.

### 1.1 What the contract provides

`[CONTRACT]`

- **Statuses.** `candidate → active/invalid`, plus `SUPERSEDED_BY_POLICY` (terminal for
  resolution, queryable for provenance) and `REVALIDATION_REQUIRED`.
- **Two temporal axes, which MUST NOT be collapsed.** Valid time (`valid_from`, `valid_until`) and
  system/knowledge time (`observed_at`, `committed_at`, `invalidated_at`), plus
  `produced_at_position` as a third distinct concept.
- **Non-destructive revocation precedent.** *"A1 RESOLVES_TO iphone_17_pro → REVOKED. A1 and its
  evidence are untouched."*
- **Authority domains** decide who may assert a predicate; different domains are explicitly *not*
  contradictions (Example 5).
- **Support counting follows the lineage graph** — a Claim with two supporting Evidence records
  survives the deletion of one.

### 1.2 Valid semantic models

**C-M1 — Re-subject.** Both Claims are rewritten to the surviving subject.
*Consequence:* `[CONTRACT]` **violates the bitemporal separation.** The Claims were committed when
the system believed two subjects existed; rewriting the subject falsifies `committed_at`'s
meaning. It also destroys the ability to answer "what did we believe before the merge?"
`[INFERENCE]` Hard to reconcile with a contract that forbids collapsing the temporal axes.

**C-M2 — Re-resolve, don't rewrite.** Claims keep their original subject. The merge is recorded as
a separate resolution link, and *resolution* (§6) follows links when collecting Claims for the
merged subject.
*Consequence:* history is untouched; the merged subject's resolution collects both `(A,P,X)` and
`(B,P,Y)`, yielding `CONFLICT` for a `SINGLE` predicate — a **legitimate, recoverable** status per
§0. Provenance trivially preserves the pre-merge state because nothing changed.
`[INFERENCE]` This is the model most consistent with the contract as written, and it is the
`RESOLVES_TO`/revocation pattern applied one level up.

**C-M3 — Merge with supersession.** One Claim becomes `SUPERSEDED_BY_POLICY`-like, the other stays
active.
*Consequence:* requires a rule for *which* — and §6 forbids recency, similarity, confidence and
mention count, which eliminates every automatic tiebreak the system could compute.
`[INFERENCE]` Only admissible if authority differs (C-M4) or a human chooses. Otherwise it
smuggles in a forbidden heuristic.

**C-M4 — Authority-mediated.** If `(A,P,X)` and `(B,P,Y)` come from different authority domains,
existing precedence rules decide without any merge-specific machinery.
*Consequence:* `[CONTRACT]` Example 5 already establishes that different authority domains are not
contradictions. `[INFERENCE]` This handles a real subset — e.g. operator-asserted vs
LLM-extracted, where **D1(b)'s answer already gives operator precedence** — but not the common
case where both claims share a domain.

### 1.3 Falsification

- *Against C-M2:* "a permanent `CONFLICT` is a degraded product." True — but it is *visible*
  degradation with a defined recovery operation, versus C-M1's invisible history loss.
  `[INFERENCE]` The contract's whole posture (`UNKNOWN` is a real state; `null` must not mean
  "none") favours explicit degradation over silent resolution. **C-M2 survives.**
- *Against C-M4:* it only helps when domains differ. **Survives as a partial mechanism, not a
  general answer.**
- *Against C-M1:* the bitemporal objection appears decisive. **Falsified**, unless the contract
  owner reads subject as mutable metadata rather than claim identity — `[UNDECIDED]`.

### 1.4 Does invalidation rewrite history?

`[CONTRACT]` No, if the existing vocabulary is used. `SUPERSEDED_BY_POLICY` is *"terminal for
resolution and remains queryable for provenance and history only"*. `[INFERENCE]` A merge-induced
status change could follow the same pattern — terminal for resolution, queryable forever. The
contract already demonstrates the shape; it simply has no merge-specific status name.

---

## 2. Current State

### 2.1 Is merge a state mutation?

`[INFERENCE]` **No — under C-M2 it is a resolution-input change.** Current State is a materialized
projection, not a source of truth. Merging changes which Claims the projection collects, so the
projection must be recomputed, but no state value is directly mutated. This matters: it keeps
merge out of the mutation/OCC path (§7) and inside the projection/invalidation path (§12), which
is where the contract already has machinery.

### 2.2 Recomputation

`[CONTRACT]` §12: *"When evidence is deleted, dependent derived objects are invalidated
synchronously … Recomputation of expensive downstream projections happens asynchronously"*, with
the binding invariant that **an invalidated object not yet recomputed MUST be excluded from
retrieval, not served stale.**

`[INFERENCE]` A merge should follow the same discipline: synchronously invalidate every slot of
both subjects, recompute asynchronously, and **exclude rather than serve** in the interim. The
machinery exists and needs no extension. The window is bounded by **G4**, which is open — so merge
inherits G4, a dependency not previously noted.

### 2.3 Does merge need a new scope generation?

`[INFERENCE]` **Probably yes, and this is a genuine gap.** `scope_generation(scope_id)` exists for
deletion containment. If a person is a `CUSTOMER` scope, merging two persons either retires one
scope or creates a third. In-flight workers holding a snapshot of the retired scope's generation
should be rejected — exactly the protection §12 provides for deletion.

`[CONTRACT]` But scope generations are described as *deletion* protection. Whether a merge counts
as a deletion of the non-surviving scope is **not stated**. `[UNDECIDED]` — and it interacts with
**G8**: if merge bumps a generation, rejected in-flight work needs a disposition, which is exactly
G8's open question. **Merge therefore inherits G8 as well as G4.**

### 2.4 Two states conflicting

`[CONTRACT]` Covered by §0: `CONFLICT` with a declared `RESOLVE_CONFLICT` operation. `[INFERENCE]`
No new machinery required. The practical consequence is a merged subject may present more
`CONFLICT` slots than either predecessor, and the product must be able to surface that —
a UX consequence, not a semantic gap.

---

## 3. Memory — the actual deepest problem

### 3.1 Why Memory is harder than Claims

`[CONTRACT]` Memory is **non-assertive**. It carries no `(subject, predicate, object)` shape, no
authority domain, no resolution status, and therefore **no `CONFLICT` state**.

`[INFERENCE]` Everything that makes §1 and §2 tractable is absent here. Two Claims colliding
produce a visible, recoverable `CONFLICT`. Two Memories colliding produce **recall** — the agent
simply knows more things, with no mechanism to notice that some of them came from a different
human. A wrong merge in the Claim plane degrades loudly; in the Memory plane it degrades silently
and in the agent's own voice.

`[CODE]` And the exposure is immediate, not theoretical: `core/packet/person_records.py` renders a
person's rows into the system prompt on every packet build. `[INFERENCE]` A bad Memory merge is
therefore an in-conversation disclosure on the very next turn.

### 3.2 Models

**Mem-M1 — Merge Memory.** Both sets become one.
*Consequence:* maximum continuity, maximum blast radius. No mechanism to detect or undo
contamination once the merged set has been rendered into prompts.

**Mem-M2 — Partition and tag.** Memory stays attached to its originating subject; the merged
subject reads across partitions, each item retaining its origin.
*Consequence:* a split is a re-partition, not a reconstruction; provenance is preserved by
construction. **Retrieval must then be origin-aware**, which is new machinery.
`[INFERENCE]` This is the analogue of C-M2 and is the only model under which §5's rollback is
mechanically possible.

**Mem-M3 — Merge with confidence gating.** Merge only Memory above a confidence threshold.
*Consequence:* `[CONTRACT]` §6 forbids selecting authoritative values by confidence. `[INFERENCE]`
Memory is not authoritative, so the prohibition does not literally apply — **but importing a
confidence heuristic into the one plane with no conflict machinery inverts the contract's
posture.** Weakest of the three.

### 3.3 Is provenance enough?

`[INFERENCE]` **No, and this is the crux.** Provenance records *where a memory came from*. It does
not prevent the memory being *used*. Because Memory is rendered into the prompt wholesale, a
provenance field that nothing consults at retrieval time is inert. Provenance is necessary for
rollback (§5) and insufficient for prevention. Prevention requires either partitioning (Mem-M2) or
not merging Memory at all.

### 3.4 Does D1(b)'s per-field authority marker help?

`[INFERENCE]` **Partially, and less than one would hope.** D1(b) is answered: operator wins, with a
per-field authority marker (writer + timestamp). Under merge that marker:

- **Does** resolve field-level collisions where one side was operator-corrected — a genuine and
  useful subset, and it is the same mechanism as C-M4.
- **Does not** help where both sides are machine-extracted, which is the common case.
- **Does not** address the disclosure problem at all. An operator-corrected fact about the wrong
  human is still the wrong human's fact, asserted with *higher* authority.

`[INFERENCE]` So D1(b) improves merge outcomes without making merge safe. Worth stating plainly,
because the answered-D1 status could be mistaken for more coverage than it gives.

### 3.5 Privacy

`[INFERENCE]` A wrong merge is a **disclosure event**, not a data-quality event. `lead_contacts`'
own rationale already names it: *"exact match beats clever match where a wrong merge reads a
stranger's history to the caller."* The asymmetry in
`person-identity-architecture-research.md` §8.3 holds and is reinforced: over-merge is acute and
possibly unrecoverable; under-merge is chronic and recoverable.

---

## 4. Narrative Memory

`[CONTRACT]` Narrative Memory is retained *conversational context* — tone, how a problem was
described, unresolved discussion.

`[CODE]` `person-identity-measurement-pass.md` §9.3 confirmed: session summaries are
**session-scoped** and carry no independent person key. The person association is indirect,
through the session.

`[INFERENCE]` That indirection is protective and should probably be preserved:

- **Merge** — narratives need not move. They stay attached to sessions; sessions attach to whatever
  subject the resolution layer currently resolves their identifier to. Merge is then automatically
  reflected without touching narrative records.
- **Split** — likewise automatic, because nothing was rewritten.
- **Deletion** — a person's narratives are reachable only via their sessions, so deletion must
  traverse sessions. `[CODE]` No mechanism does this across stores today.
- **Re-registration** — `[INFERENCE]` the danger case. If a new subject resolves an identifier that
  a deleted subject previously held, session-linked narratives could attach to the new person.
  This is the narrative form of F6 (deterministic ids resurrecting deleted people) and is
  **unaddressed in every model**.

---

## 5. Split and rollback

**Setup.** A and B were merged in error.

`[INFERENCE]` Reversibility is determined almost entirely by choices made at merge time:

| Merge model | Reversible? |
|---|---|
| C-M2 (re-resolve) + Mem-M2 (partition) | **Yes.** Revoke the link, re-partition, recompute. Nothing was rewritten. |
| C-M1 (re-subject) | **No.** Original subjects are not recoverable without a separate audit log that would itself have to store the pre-merge state. |
| Mem-M1 (merge Memory) | **No.** Once sets are unioned, origin is lost unless separately recorded. |

**Irreversible contamination is the thing to avoid**, and the contract's own precedent points the
way: *"A1 RESOLVES_TO iphone_17_pro → REVOKED. A1 and its evidence are untouched."* `[INFERENCE]`
Applied here: revoke the resolution link; the underlying records were never altered, so prior
boundaries are restored by recomputation.

`[INFERENCE]` **One contamination channel survives even under the fully reversible models, and it
cannot be rolled back:** anything already rendered into a prompt and said to a customer. Messages
sent are not revocable state. A split restores the data model; it cannot unsay the disclosure.
This is an argument for making merge *hard to do accidentally*, independent of how reversible the
storage is.

`[CODE]` In-house precedent for the reversible shape exists — `merge_organizations.py` snapshots
every affected document to JSONL before any delete, explicitly for rollback, and
`research_clients` archives the loser with a `merged_into` pointer rather than deleting it.

---

## 6. Scope generation

`[INFERENCE]` Merge interacts with `scope_generation` in three ways, none currently specified:

1. **Which scope survives?** If subjects are `CUSTOMER` scopes, a merge retires one. Its generation
   must move so in-flight workers are fenced, or work commits against a scope that no longer
   exists.
2. **In-flight writes.** A write in flight against the retired scope must be rejected — the §12
   mechanism — but the *disposition* of that rejected work is **G8**, which is open. §2.3's
   dependency, restated.
3. **Outbox/async work.** Anything queued against either subject must be re-evaluated. `[CODE]` No
   outbox exists; `scope_generation` exists nowhere in code. Both are prospective.

`[UNDECIDED]` The contract describes scope generations as *deletion* protection. Whether a merge
constitutes a deletion of the retired scope is not stated and is a question for the contract owner
— related to, but narrower than, J2.

---

## 7. Security — can a merge widen visibility?

`[INFERENCE]` **Yes, by construction, and this is the one place where the contract's own
prohibitions bite directly.**

`[CONTRACT]` Cross-customer `SAME_AS` is **forbidden**; `RESOLVES_TO` is explicitly
**non-authorizing**; *"the canonical entity is a semantic anchor, not a privacy bridge"*; and scope
hierarchy for deletion MUST NOT imply authorization inheritance (stated twice).

`[INFERENCE]` Every one of those exists to prevent a link becoming a visibility edge. A person
merge is precisely such a link. Three conditions follow:

1. **Merges must not cross tenants.** A cross-tenant merge would make one organization's customer
   data reachable through another's subject — the exact harm the forbidden cross-customer
   `SAME_AS` names.
2. **The resolution link must never appear in an authorization decision.** `[CODE]` The good news
   from `person-identity-measurement-pass.md` §8: the codebase's existing habit is already correct
   — three independent gates (API key, caller org, document `organization_id`) and none consults
   the identity value. The discipline exists; it would need to be *preserved*, not established.
3. **Within a tenant, merge widens visibility legitimately** — that is its purpose — but the
   widening must be bounded by the tenant, not by the resolution graph.

`[INFERENCE]` **Falsification attempt:** could a merge widen visibility even within one tenant in
an unintended way? Yes — if agent-scoped data becomes visible across agents because the subject is
tenant-scoped while today's person stores are agent-scoped by path
(`agent_datastores/{agent}/...`). **A tenant-scoped subject spanning two agents is a visibility
change that no current mechanism expresses.** This is a real and previously unstated issue; it is
recorded as N8 below.

---

## 8. Which parts of identity resolution are deterministic, evidential, probabilistic, policy or
human

As the task asks — identifying *boundaries*, not proposing a model.

| Step | Nature | Appropriate mechanism |
|---|---|---|
| Normalise an observed identifier | **Deterministic** | Code. `[CODE]` `normalise_contact_phone` already is. No judgement involved. |
| Detect that two identifiers co-occur on one record | **Evidence-based, deterministic** | Code. `[CODE]` `lead_people`'s union-find already does this — it reads a fact, it does not infer. |
| Propose that two subjects *might* be one human on weaker signals (name+city, fuzzy match) | **Probabilistic** | A scored candidate list. **Never an automatic merge** — §3.5's asymmetry. |
| Decide whether a given evidence strength suffices | **Policy** | A declared threshold, versioned like a Predicate Policy. Not a model output. |
| Execute the merge | **Human-governed** | `[CODE]` `research_clients` already chose operator-initiated with `updated_by` audit. |
| Resolve a resulting `CONFLICT` | **Policy + human** | `[CONTRACT]` the declared `RESOLVE_CONFLICT` operation; §6 forbids automatic tiebreaks. |
| Roll back a wrong merge | **Human-governed** | Revocation, per §5. |

`[INFERENCE]` **The bounded decision point is exactly one:** *given this candidate pair and this
evidence, should a human be asked?* Everything upstream is deterministic; everything downstream is
policy or human authorization. That single step — candidate ranking and triage — is where a typed
decision model could eventually sit, and it is developed further in
`decision-gateway-jev-research.md`.

`[INFERENCE]` Equally important is where such a model must **not** sit: not on executing a merge,
not on resolving `CONFLICT`, not on any authorization question. `[CONTRACT]` The contract already
forbids the analogous thing — a conversation *"cannot modify identity, role, authorization, tenant
membership, or security policy"*, and `account_role` carries `LLM_WRITE = FORBIDDEN`.

---

## 9. Falsification summary

| Model | Status after falsification |
|---|---|
| C-M1 re-subject Claims | **Falsified** on bitemporal grounds, unless the contract owner reads subject as mutable metadata `[UNDECIDED]` |
| C-M2 re-resolve, don't rewrite | **Survives.** Most consistent with the contract; yields recoverable `CONFLICT` |
| C-M3 supersession | **Falsified as a general rule** — needs a tiebreak §6 forbids |
| C-M4 authority-mediated | **Survives as partial** — only when domains differ |
| Mem-M1 merge Memory | **Survives semantically, fails on safety** — irreversible, silent, disclosure-bearing |
| Mem-M2 partition and tag | **Survives.** The only model permitting rollback; costs origin-aware retrieval |
| Mem-M3 confidence-gated | **Weakest** — imports a heuristic into the plane with no conflict machinery |
| Narrative via session indirection | **Survives**, except for re-registration (§4) |

`[INFERENCE]` The models that survive (C-M2 + Mem-M2) share one property: **nothing is rewritten;
only the resolution is changed.** That is the contract's own `RESOLVES_TO`/revocation pattern and
the platform's own `merge_organizations` / `research_clients` pattern, applied to persons. Whether
persons *may* be merged at all remains J2/J5 and is untouched here.

---

## 10. New questions surfaced

| ID | Question |
|---|---|
| **N8** | **Tenant-scoped subject vs agent-scoped storage.** Today person data is agent-scoped by path. A tenant-scoped subject spanning two agents is a visibility change no current mechanism expresses (§7). |
| **N9** | **Merge inherits G4 and G8.** The invalidate/recompute window is bounded by G4; generation-rejected in-flight work is G8. Neither dependency was previously recorded, and both are open. |
| **N10** | **Is a merge a deletion of the retired scope?** Determines whether `scope_generation` applies (§6). Contract-owner question, narrower than J2. |
| **N11** | **Narrative re-registration.** Session-linked narratives could attach to a new subject that inherits a deleted subject's identifier (§4). Unaddressed in every model. |
| **N12** | **Disclosure is not rollback-able.** Even fully reversible storage cannot unsay what was rendered into a prompt (§5). Argues for merge being hard to trigger, independent of storage design. |

**Refined:** N1 is downgraded — the contract *does* have conflict machinery (§0). **N5 is
promoted** — Memory, not Current State, is the deepest problem, because it is the only plane with
no conflict concept and a direct path to the prompt.

---

## 11. Limitations

1. No Claim, Current State, Memory or `scope_generation` implementation exists. Every statement
   about behaviour is `[CONTRACT]` + `[INFERENCE]`, never `[CODE]`.
2. Whether persons may be merged is J2/J5 and is assumed only hypothetically.
3. §0's refinement rests on reading §6's `RESOLVE_CONFLICT` sentence as applying to any
   multi-authoritative-value case, including merge-induced ones. The contract does not name merge.
   `[UNDECIDED]` — worth confirming with the contract owner alongside J2.
4. `[UNMEASURED]` No data: how many subjects would produce `CONFLICT` on merge is unknown and
   unknowable without the co-occurrence measurement that remains unrun.
