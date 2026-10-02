# G8 — Bulk-deletion retry and dead-letter semantics (research)

Date: 2026-09-26. Read-only. **No policy is chosen here — G8 remains Jay's/Operations' decision.**

Commits: `olbrain-workflow-runtime 1978f4a` · `olbrain-research-runtime 6b81691` ·
`olbrain-agent-runtime 8df0e02` · `olbrain-shared 8a0f0b5` · `olbrain-studio-backend ca9724a`.
Labels per the standing scheme.

---

## 1. The question, restated from the contract

`[CONTRACT]` §16 row 8. Per §12, a worker whose scope generation changed before commit is
**rejected**. G8 asks what becomes of that rejected work. The contract offers no default and says
so deliberately: *"Without a defined disposition, rejected work is either silently dropped or
retried forever. There is no safe default."*

---

## 2. Current behaviour

### 2.1 `scope_generation` does not exist in any repository

`[CODE]` `git grep -n "scope_generation"` across all thirteen repositories at their current
commits returns **nothing**. The mechanism G8 governs is entirely prospective. Nothing today is
rejected by a scope-generation bump, because nothing computes one.

`[INFERENCE]` G8 therefore blocks *designing* bulk deletion, not *fixing* it. There is no
in-flight population of rejected work awaiting a policy.

### 2.2 There is no dead-letter handling anywhere in the platform — but there is a dormant DLQ

`[CODE]` One dead-letter artifact exists:
`olbrain-research-runtime 6b81691:.github/workflows/provision-dead-letter.yml`, a **one-shot,
manually dispatched** infra job. Its own header is the most valuable evidence in this report:

> *"Until this has run in a project there is no dead-letter topic attached to anything, which
> makes a docstring in `app/routers/pubsub_push.py` false and means **a persistently-rejected
> run-event is silently dropped when the subscription's 1-day retention expires**. Read
> `scripts/provision-dead-letter.sh`'s header for which of the four policies actually bites
> today, which are deliberately dormant, and **why nothing alerts on a dead-lettered message
> yet**."*

`[INFERENCE]` So the platform's most mature async pipeline has already reached G8's question in a
different subsystem, and left it in exactly the state the contract warns against: **silent drop
after a retention window, with no alerting**. That is current behaviour, not a proposal.

### 2.3 Existing retry conventions — three independent subsystems, one consistent doctrine

`[CODE]`

**(a) Fencing → abandon.** `olbrain-workflow-runtime 1978f4a:app/core/orchestrator.py:423-435`:

```python
async def _is_orchestrator_superseded(run_id: str, my_generation: int) -> bool:
    """... When /resume increments orchestrator_generation and spawns a new pass,
    the stale pass detects the mismatch here and exits cleanly without writing
    duplicate workflow_items docs."""
    run = await firestore_service.get_run(run_id)
    return run is not None and run.orchestrator_generation != my_generation
```

Polled at item boundaries alongside cancel/pause. Disposition on rejection: **exit cleanly. No
retry, no dead-letter, no record.** This is the closest existing analogue to §12's rejection rule.

**(b) Bounded transient retry, then a human path.**
`olbrain-workflow-runtime 1978f4a:app/core/job_dispatcher.py:26-28`: *"Three attempts, short
backoff — transient Jobs API blips only. A ... `/retry` endpoint (which accepts FAILED runs) is
the recovery path."* Retry is scoped to transport faults; semantic failure becomes a terminal
`FAILED` state a human re-drives.

**(c) Ack-always + sweeper.** `olbrain-research-runtime 6b81691:app/pubsub_worker/subscriber.py`
acks even on failure (`:230`, `:233`), with the rationale at `:212-213` — the subscription has
**no `retryPolicy`** (verified in prod 2026-08-22, `messageRetentionDuration 604800s`), so a nack
would redeliver immediately with no backoff. Recovery is a **sweeper that "does not retry"**
(`:13`), and duplicate-safety comes from a claim-based idempotency check (`:18`, `:106`, `:201`).

`[INFERENCE]` **The in-house doctrine is consistent across all three:** bounded retry for
transient faults only; no infinite retry anywhere; no dead-letter consumption anywhere; semantic
failure surfaces as a terminal state with a human-triggered recovery endpoint. G8 would be
choosing *whether to continue that doctrine*, not inventing one.

### 2.4 Idempotency today

`[CODE]` `mutation_id` does not exist. Idempotency is achieved ad hoc: deterministic document ids
(`person_hash`, `lead_contact_doc_id`), claim-based dedup in the Pub/Sub worker, `if_generation_match`
preconditions on GCS objects (`olbrain-studio-backend ca9724a`), and guarded `created_at` re-stamping
(`agent-runtime 8df0e02:services/extract_entry_writer.py:94-97`). `[CONTRACT]` §7 mandates
per-mutation `mutation_id` idempotency independently of G8, and it is buildable now.

---

## 3. Precedents relevant to the decision

| Precedent | Disposition of rejected work | Why it is safe *there* |
|---|---|---|
| `_is_orchestrator_superseded` | Abandon silently | A **newer pass exists** and will do the work |
| `job_dispatcher` 3-attempt | Retry transient, then terminal `FAILED` | Failure is visible and human-re-drivable |
| Pub/Sub ack-always + sweeper | Ack, rely on sweeper | Sweeper re-derives state from the source of truth |
| Dormant DLQ | Silent drop at retention | **Not safe — the file says so itself** |

`[INFERENCE]` **The asymmetry that matters for G8.** In (a) abandoning is correct precisely
because a successor will redo the work. A `scope_generation` bump is different: it means the scope
was **deleted**. For *deletion* work, abandoning is arguably correct — the work is moot, the scope
is gone. For **any other work in flight against that scope**, abandoning silently means an
operation the caller believes succeeded did not happen. **G8's answer may legitimately differ by
work class**, and the existing precedent does not settle it.

---

## 4. Possible semantic models

Each stated with consequences. **None is recommended.**

**M1 — Abandon (extend the orchestrator precedent).** Rejected work is discarded; the scope is
gone so the work is meaningless.
*Consequences:* simplest; matches (a); zero new machinery. **But** it is indistinguishable from the
silent-drop failure the DLQ file calls a defect, and it gives no evidence that a bulk deletion
completed — which is exactly what a deletion audit needs.

**M2 — Abandon + durable record.** Discard the work, write a terminal record (scope, generation,
worker, reason).
*Consequences:* preserves auditability, which `[CONTRACT]` §10's deletion obligations arguably
require; costs one write per rejection; needs a retention policy of its own — **which inherits
G5**, see §6.

**M3 — Re-derive and re-check (sweeper model, from (c)).** Rejected work is re-queued once against
the *current* generation; if the scope is gone the re-derivation is a no-op.
*Consequences:* converges without unbounded retry; matches the most mature existing pipeline.
**But** requires work to be re-derivable from the source of truth, which is true for a deletion
cascade and may not be for other work.

**M4 — Bounded retry then dead-letter (conventional).** N attempts, then a DLQ with alerting.
*Consequences:* the only model that surfaces persistent failure operationally. **But** it is the
only model with no in-house precedent that works — the one DLQ that exists is dormant and
unconsumed, so adopting M4 means building alerting and a triage process that does not exist.

**M5 — Split by work class.** Deletion work abandons (M1/M2); non-deletion work rejected by the
same bump retries or dead-letters.
*Consequences:* semantically the most defensible per §3's asymmetry; the most complex to specify,
because "work class" must be a typed property of queued work that does not currently exist.

---

## 5. The exact unresolved decision

`[UNDECIDED]` G8 requires **three** answers, not one. The card's phrasing implies a single policy;
the evidence says otherwise:

1. **Disposition** — abandon, record, re-derive, or dead-letter (M1–M5).
2. **Retry bound, if any** — and whether it differs for transient vs generation rejection. The
   in-house convention is 3 attempts for transport faults only; a generation bump is not a
   transport fault.
3. **Observability** — whether a rejected item must be *visible* (alert, terminal record, metric),
   or may vanish. `[CODE]` Today nothing alerts on a dead-lettered message, by admission.

---

## 6. Hidden dependencies

`[INFERENCE]`

- **On G5 — real, and previously unnoted.** M2 and M4 both **persist a record of work concerning a
  deleted scope**. That record may itself contain customer-derived identifiers, so it becomes a
  dataset requiring a §10 classification — i.e. it inherits G5, which is **parked**. Choosing M2 or
  M4 while G5 is parked creates a store nobody has classified. M1 and M3 avoid this entirely.
  **This is the strongest practical argument to surface to Operations**, because it means G8's
  answer is not independent of a decision that is currently deferred indefinitely.
- **On G1/G6 — none.** Authorization caching and replay windows do not interact with rejected-work
  disposition. Verified by inspection of the contract rows and by the absence of any shared
  mechanism in code.
- **On G4 — partial.** G4 bounds how long an invalidated derived object may remain un-recomputed.
  If G8 chooses M3 (re-derive), the re-derivation is itself recompute work and falls inside G4's
  window. Choosing M3 without G4's bound leaves the convergence time undefined.
- **On §7 `mutation_id`** — `[CONTRACT]` idempotency is mandated independently and is a
  prerequisite for M3 and M4 (both replay work). It is buildable now and is not blocked by G8.

---

## 7. What can proceed without the G8 decision

`[INFERENCE]`

- Per-mutation `mutation_id` idempotency (`[CONTRACT]` §7, independent).
- Single-scope deletion — the dashboard already records this as implementable.
- A typed work-class property on queued work, which M5 would need and which no other model is
  harmed by.

**Blocked:** all bulk deletion, per the contract.

---

## 8. Limitations

1. `scope_generation` is prospective; all statements about rejection behaviour are about
   *analogous* mechanisms, not the mechanism itself. `[INFERENCE]`
2. The Pub/Sub subscription configuration was read from source comments asserting a 2026-08-22
   production verification, not re-verified against live infrastructure. `[UNMEASURED]`
3. Whether any of the four dead-letter policies has since been provisioned in a given project is
   `[UNMEASURED]` — the workflow is manually dispatched and its run history was not inspected.
