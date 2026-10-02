# D5 — Operational-correction authority domain (research)

Date: 2026-09-26. Read-only. **The authority domain is not named here and the owner is not chosen.**

Commits: `olbrain-workflow-runtime 1978f4a` · `olbrain-shared 8a0f0b5` ·
`olbrain-agent-runtime 8df0e02`.

---

## 1. The question

`[CONTRACT]` / `investigation/architecture-freeze.md` §3 establishes that `LearnedOverride` maps to
a Claim via a Predicate Policy entry with *"an operational-correction authority domain"* and human
approval. It **describes** the lane and deliberately does not **name** it. D5 asks for the
identifier and the approver. R2 assigns the decision to the **workflow-design owner**; this report
prepares that decision and does not pre-empt it.

---

## 2. The code already has a matching concept — and it is more complete than expected

`[CODE]` The `LearnedOverride` lane is implemented end to end in `olbrain-workflow-runtime`.

### 2.1 The state machine

`olbrain-shared 8a0f0b5:src/olbrain_shared/workflow/models/agent_memory.py:52`:

```python
status: Literal["suggested", "active", "retired"] = "suggested"
```

with, at `:43`, the note that an override applies *"(when the agent's `learned_overrides` feature
is `auto`) to item_record"*. `[CODE]` A `contradiction_count` field also exists on the same model
(recorded in `investigation/reconciliation.md` and unchanged).

### 2.2 The promotion and retirement surface

`olbrain-workflow-runtime 1978f4a:app/routers/exceptions.py:274-311`:

```python
class ApproveOverrideRequest(BaseModel):
    approved_by: str

class RetireOverrideRequest(BaseModel):
    retired_by: str
    reason: Optional[str] = None

@router.post("/agents/{agent_id}/memory/overrides/{override_id}/approve")
async def approve_override(agent_id, override_id, body: ApproveOverrideRequest):
    """Flip a suggested override to active — from then on, auto-dialed
    runs apply it at extraction time."""
    updated = await agent_memory_service.set_override_status(
        agent_id, override_id, "active", actor=body.approved_by)
```

and retirement is documented as *"Retire an override from any status — **operator kill switch**"*,
carrying `actor` **and** `reason`.

### 2.3 The application gate

`olbrain-workflow-runtime 1978f4a:app/core/orchestrator.py:899`:

```python
if await agentic_resolver.feature_level(agent_id, "learned_overrides") == "auto":
```

`[INFERENCE]` So there are already **three** independent controls: a per-agent feature level
(`auto` or not), a per-override status, and a human promotion step. The lane is not a sketch.

---

## 3. What the authority domain logically covers

`[INFERENCE]` Reading the implementation rather than the contract, the lane governs assertions of
the form *"in this operational situation, do X instead of what the general rule says"* — a
correction to **operational behaviour**, derived from observed contradiction, promoted by a human,
and applied at extraction time to workflow items.

Distinguishing marks that a domain identifier should preserve:

1. **Its evidence is contradiction, not observation.** `contradiction_count` is the signal — the
   override exists because the general rule was repeatedly wrong.
2. **It is prospective.** `[CODE]` Promotion changes what *future* auto-dialed runs do
   (*"from then on"*); it does not restate history.
3. **It is retractable without deletion.** `retired` is a terminal status, not a delete —
   consistent with `[CONTRACT]` §10's non-destructive posture and with `research_clients`' archive
   pattern found elsewhere in the platform.
4. **It is agent-scoped, not person-scoped or tenant-scoped.** The route is
   `/agents/{agent_id}/memory/overrides/{override_id}`.

`[INFERENCE]` Point 4 is worth flagging: an authority *domain* in the contract's sense is a
property of the **predicate**, while this lane's natural scope is the **agent**. Whether one
authority domain spans all agents, or the domain is parameterised by agent, is an unstated
question that the naming decision will implicitly settle.

---

## 4. What is missing

`[CODE]` Three gaps, in descending order of consequence.

### 4.1 The approver is self-asserted — there is no authorization on promotion

`approved_by` and `retired_by` are **plain strings in the request body**. The router is
`APIRouter()` with no `dependencies=` (`app/routers/exceptions.py:18`), mounted at
`app.include_router(exceptions.router, prefix="/api/workflows", ...)`
(`app/main.py:111`), and the only global middleware added in `app/main.py` is `CORSMiddleware`
(`:67-68`).

`[INFERENCE]` So on the evidence available in source, any caller who can reach the endpoint can
promote an override and name themselves as the approver. **This is exactly the gap D5 exists to
close** — the contract requires *human approval* under a named authority, and what exists is a
free-text attribution with no authority behind it.

**Stated as a finding, not an exposure.** `[UNMEASURED]` Deployment-level gating — Cloud Run
ingress restrictions, IAP, an API gateway, or a service-mesh policy — was not traced, and
`app/main.py:14` references an `X-Internal-Service` auth header used elsewhere in the service.
The service may well be unreachable externally. **This should be confirmed with the
workflow-design owner rather than treated as a live vulnerability**, and no remediation is
proposed here.

### 4.2 No authority-domain identifier exists

`[CODE]` No enum, constant or column names an authority domain anywhere in any repository. The
contract names `IDENTITY_SECURITY` as an example domain; nothing corresponding exists for
operational correction. There is no Predicate Policy Registry to hold it.

### 4.3 No link to the Claim model

`[CODE]` `LearnedOverride` is a workflow-memory record, not a Claim. It has no subject/predicate/
object shape, no provenance to Evidence, no `policy_version`, and no bitemporal fields.
`[INFERENCE]` `architecture-freeze.md` §3's mapping is therefore a **target mapping**, not a
description of current structure — the lane exists operationally but not semantically.

---

## 5. What must be named by the workflow-design owner

`[UNDECIDED]` Four things, stated so the decision is bounded:

1. **The authority-domain identifier** — the token that goes in the Predicate Policy entry
   (the contract's `IDENTITY_SECURITY` is the formatting precedent).
2. **Who may approve** — a role, not a person, and whether it differs from who may *retire*.
   `[CODE]` The code already distinguishes the two actions and could carry different authorities;
   retirement is documented as a *"kill switch"*, which conventionally warrants a wider grant than
   promotion.
3. **Whether promotion requires authentication at all** — §4.1 shows it currently does not, on the
   evidence in source. This is the item most likely to need action regardless of how D5 is decided.
4. **Whether an active override expires.** `[CODE]` There is no expiry; `active` persists until
   someone retires it. `[INFERENCE]` If the answer is that overrides do expire, that is a
   `max_staleness` and it becomes a **G3** input for this predicate family — the same owner, per
   R2, so the two questions can be answered together.

---

## 6. Consequences of the plausible answers

`[INFERENCE]` Conditionally stated.

- **If the owner names a domain and keeps the existing surface:** D5 closes cheaply; the first
  operational-correction Predicate Policy becomes authorable; §4.1 remains an open question about
  the endpoint, separable from D5.
- **If the owner requires authenticated approval:** D5's closure implies a code change in
  `olbrain-workflow-runtime` (not made here, not in scope), and the authority domain becomes
  enforceable rather than documentary.
- **If the owner declines to name a domain:** `LearnedOverride` cannot map to a Claim, and
  `architecture-freeze.md` §3's mapping stays a target with no implementation path — which would
  make procedural/operational correction a second thing living outside the five-object model,
  alongside the procedural-memory exclusion that D7 concerns.

---

## 7. Dependencies

`[INFERENCE]`

- **On R2 — resolved.** The owner is named (workflow-design owner). D5 is no longer gated, only
  unanswered.
- **On G3 — latent.** §5 item 4: override expiry is a freshness question for the same owner.
- **On D7 — conceptual, not blocking.** Both concern what sits outside the five-object model.
  `[INFERENCE]` If D5 succeeds in mapping operational corrections *into* the model, the set of
  things needing an exclusion clause shrinks, which slightly strengthens the case for Patch 19
  being narrow.
- **On the contract — none.** `architecture-freeze.md` records this as a *registry-population*
  decision, not a contract change, and nothing found this pass contradicts that.

---

## 8. Limitations

1. §4.1's authorization finding is a source-level finding. Deployment-level gating was not traced
   and may render it moot. `[UNMEASURED]`
2. `agentic_resolver.feature_level` semantics were read at the call site only; the resolver's own
   authority model was not traced.
3. Whether `LearnedOverride` records exist in production, and in what volume, is `[UNMEASURED]`.
4. No attempt was made to evaluate whether the `suggested → active → retired` machine is the right
   shape for a Claim — that is target-design work and is explicitly out of scope for this pass.
