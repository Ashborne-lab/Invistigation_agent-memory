# Memory Integration Harness v1 (target architecture, prototype)

**Date:** 2026-10-03.
**Scope:** investigation prototype only. In memory: no Firestore, PostgreSQL, Redis, network, LLM or embeddings. No production, Memory Gateway, migration or shadow writes. No subagents.

**Code:**
- `memory-prototype/memory_core/integration/__init__.py`: the `Pipeline` composition. It is TEST-ONLY and adds no new semantics.
- `memory-prototype/tests/test_integration.py`: 108 tests.

**Full prototype suite: 761/761.**

## 1. What the harness is

```text
Evidence ──► Policy Registry ──► Claim Gate ──► Commit / Journal ──► Current State ──► Typed Retrieval ──► Context
 ingest()      publish()         decide()        commit()            project()          retrieve()          context()
```

`Pipeline` holds only in-memory stores and passes values between the **real** components:

| Store | Content |
|---|---|
| `registry` | Policy history |
| `evidence` | Append-only evidence store |
| `gate_ledger` | Gate idempotency |
| `store` | Journal and commit ledger |
| `fence_ctx` | Fence context |
| `keys` | Per-subject keys, a TEST_ONLY provider; custody is C-1, still open |
| `episodes`, `commitment_events` | Narrative and commitment inputs |

**Write path:**
- `ingest(evidence)` records the evidence, independently of any proposal.
- `propose(proposal, now, expected_version)`:
  - the gate sees the slot's current state, derived **from the journal** (`current_for`);
  - commit receives only the gate's **attested** outcome;
  - observations carry no `expected_version`; typed commands are checked against the projected `state_version`.
- `retract`, `lifecycle`, `supersede_by_policy` and `sync` call the commit layer.
- `publish(policy, now)` publishes to the registry **and journals the publication** as an evaluation point.

**Read path:**
- `project`: the live path uses incremental projection with the policy history.
- `retrieve`: all four typed retrievals.
- `context`: the Context Compiler.

**`rebuild()`** builds a new pipeline from **durable facts only**: policy history, evidence, journal plus commit ledger, keys, episodes and commitment events.
- Claims are re-derived from the journal (`rebuild_claims`).
- **The gate is never re-run.** Recorded outcomes are applied as recorded.
- The rebuilt pipeline projects on the exhaustive path, independent of the live incremental path.

Every policy, task profile, budget, staleness value, retention class and authority rank in the tests is `TEST_ONLY_*`.

## 2. Scenarios (each also asserts live == rebuild through retrieval and context)

| # | Scenario | Proven |
|---|---|---|
| 1 | User states a preference | evidence → ACCEPT → claim → slot VALUE → retrieval item → `[CURRENT_STATE] … = "pune"` in context |
| 2 | Preference changes | Old claim kept (SUPERSEDED, with its `valid_until`); new value current; history line in context |
| 3 | Equal-authority disagreement | Slot CONFLICT with no value; the context line has `[CONFLICT]` and neither value |
| 4 | Higher authority overrides | HR_SYSTEM's value wins; history keeps both (CURRENT / NOT_SELECTED) |
| 5 | Stale external value | A **recorded** sync makes it FRESH; time passes and it becomes STALE / DISPLAY_ONLY, with `[CURRENT_STATE][STALE] … use=DISPLAY_ONLY` in context. A stale write is refused (`stale_write_forbidden`) |
| 6 | Rejected evidence | Evidence stays in the evidence store; the decision is recorded (`unsupported:value_not_in_quote`); no claim; current state unchanged |
| 7 | Erasure / quarantine | PENDING_ERASURE or QUARANTINED: slot UNKNOWN, absent from history, context and manifest |
| 8 | Future-dated claim | Inactive before its `valid_from`; active after it; `state_version` +1 with no commit; rebuild agrees |
| 9 | Duplicate proposal | Replay is a duplicate; the same content under a new id makes no new claim; exactly one claim |
| 10 | Policy upgrade | A breaking v2 makes the old claim REVALIDATION_REQUIRED (slot UNKNOWN, not reinterpreted; history label kept). A proposal under v1 is refused. A v2 claim plus `supersede_by_policy` gives SUPERSEDED_BY_POLICY. A non-breaking v3 keeps v2 claims operational |
| 11 | Authorization | Two authorized callers get identical retrieval and context. A stranger gets ACCESS_DENIED everywhere, an empty context and a manifest with no values |
| 12 | Context injection | `SYSTEM:` text, a forged `[CURRENT_STATE]` label and `<<MEMORY>>` inside a stored value stay quoted, escaped data on their own labelled line; no forged state line appears |

**Engineering-closure tests:**
- **C-B:** `test_cb_superseded_by_policy_never_manufactures_a_conflict`. Under a grandfathering change, only SUPERSEDED_BY_POLICY removes the old claim, so the old claim and its replacement never produce a manufactured CONFLICT.
- **C-D:**
  - a hand-built or tampered gate outcome is refused (`decision_not_attested_by_gate`);
  - an observation during CONFLICT is recorded, while a blind SET command is refused;
  - a typed command requires `expected_version`, and a stale one gets STATE_CONFLICT.
- **Monotonicity:** `test_state_version_is_monotonic_across_policy_publication` (§4).

## 3. Properties

| Property | Seeds | Asserts |
|---|---|---|
| **C-C freshness** | 30 | No, one or several syncs, plus optional budget changes through a new policy version. Live freshness == rebuilt freshness == the value computed from the latest recorded sync and the budget in force |
| **Strong integration** | 40 | Random observations from all sources, with past or future `valid_from`. Typed commands (STATE_CONFLICT or status-gated). External writes. Syncs. Retractions (both causes). Lifecycle changes. Breaking and non-breaking policy versions. Time jumps. Then: live == rebuild for the projection, all four retrievals and the compiled context; truth is caller-independent; a stranger gets nothing; no CONFLICT carries a value |
| **Monotonic `state_version`** | 20 | `state_version` never decreases through observations, breaking and non-breaking publications and time |

**Mutation check.** Each rule removed fails at least one test:

| Rule removed | Result |
|---|---|
| Attestation check | Caught |
| Revalidation filter | Caught |
| SUPERSEDED_BY_POLICY filter | Initially survived; closed by the grandfathering test |
| Journal-derived freshness | Caught |
| Commitment identity check | Caught |
| Commitment subject filter | Caught |
| Contract-scope check | Caught |
| Breaking flag | Caught |
| Observation op restriction | Caught |
| Observation-vs-command split | Caught |
| Policy-in-force evaluation | Caught |

## 4. Defect found by integration (fixed)

**`state_version` rewound after a breaking policy publication** (probe: version 2 → 0).
- **Cause:** version history was replayed under the *current* policy set. A breaking publication therefore retroactively excluded old claims at every past evaluation point.
- **Effect:** version numbers could repeat. That is an ABA hazard under OCC: a writer holding `expected_version=0` from before the slot existed would match again.
- **Why rebuild did not catch it:** both paths computed it the same way, so live == rebuild still held.
- **Fix:**
  - publications are journaled as evaluation points (`commit.record_policy`, `Pipeline.publish`);
  - `slot_versions` evaluates each point under the policy **in force at that point** (`policy_history`).
- **Result:** the version now advances (v → v+1), consistent with contract §2 ("MAY advance with no agent mutation… policy revalidation"), and never rewinds.
- **Tests:** a focused test plus a 20-seed property. Removing the fix fails the focused test. The property did not reproduce the rewind within 20 seeds.

## 5. What the harness deliberately does not decide

C-1 production key custody; B-1 policy ownership; B-2 production staleness budgets; B-3 retention values; B-4 operator vs user authority; legal erasure cancellation; production storage choice; the production scheduler.
