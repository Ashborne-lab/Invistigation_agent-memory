# Target Architecture: Engineering Closure v1

**Date:** 2026-10-03.
**Scope:** resolves the five cross-component contradictions (C-A…C-E) from `target-architecture-decision-closure-v1.md` §8 in the investigation prototype, and wires every component together (`memory-integration-harness-v1.md`).

**Not touched:** no normative document, no production, no storage technology, key custody, retention, or policy, legal or product decision.

**Prototype suite: 761/761.** It was 648 before this pass.

## 1. C-A…C-E resolution

| ID | Contradiction | Resolution in the prototype | Evidence |
|---|---|---|---|
| **C-A** | Retrieval used a non-contract scope name (`ORG`) | Scope vocabulary is exactly contract §2: GLOBAL, TENANT, WORKSPACE, CUSTOMER, SESSION, AGENT, RESOURCE. CUSTOMER is the only projected scope. Other **contract** scopes return `UNSUPPORTED_SCOPE`; **non-contract** names return `INVALID_SCOPE`. `get_org_knowledge` became `get_tenant_knowledge` (UNSUPPORTED_SCOPE) | `test_unsupported_scopes_are_explicit[6]`, `test_non_contract_scope_names_are_invalid_not_unsupported` |
| **C-B** | Old-policy claims were silently re-read under the current policy; the §10 statuses were missing | **Registry:** `breaking` (declared by the author; a cardinality change is always breaking), `grandfather_prior_claims`, and a computed `revalidate_before`. **Projection and retrieval:** a claim bound to a version below `revalidate_before` is **REVALIDATION_REQUIRED**. It is derived deterministically, excluded from operational truth, listed in `CurrentState.revalidation_required`, and labelled in history. **Commit:** `supersede_by_policy(old, new)` records the explicit, terminal **SUPERSEDED_BY_POLICY** transition (same slot, newer policy). No revalidation workflow was invented: the replacement claim arrives through the normal gate and commit | Scenario 10; `test_cb_superseded_by_policy_never_manufactures_a_conflict` |
| **C-C** | Freshness depended on a caller-supplied `last_sync` | **`SyncRecord` journal events** (`record_sync`, idempotent on `sync_id`; future syncs refused). Freshness everywhere (projection, gate current state, history) is derived by `last_sync_from(journal, subject, predicate, cutoff)`. **The `last_sync` parameter was removed** from projection and retrieval | `test_cc_freshness_rebuilds_identically[30]`, scenario 5 |
| **C-D** | Gate and commit disagreed on LLM extraction vs commands | **Observation vs command is explicit in every layer:** (1) `claimgate.is_observation`: the LLM extractor's proposals are observations; (2) the registry's `check_write(assertion=True)`: observations are not status-gated, may only propose `SET`/`ADD`/`PUT_KEY`, and must still use declared map keys and states; (3) typed commands keep status gating, resolver rules, state-machine transitions, stale-write rules and `expected_version`; (4) **the gate attests every outcome** (in-process HMAC), and commit refuses an outcome the gate did not issue (`decision_not_attested_by_gate`), including a tampered one; (5) evidence is recorded independently of any proposal, so a rejected proposal leaves its evidence and a recorded decision, but no claim | Scenario 6; the three `test_cd_*` tests |
| **C-E** | Two commitment models; the event log had no identity | **One model:** the reviewed Lane A event log, unchanged in behaviour. `Event` and `Head` gain `subject_id`, `agent_id` and `tenant_id`. Events whose identity differs from the creating event are refused (`identity_mismatch`). Retrieval serves only commitments whose recorded subject is the requested one, and **never serves identity-less commitments** (fails closed); `agent_id` and `tenant_id` are carried in the item. **CUSTOMER vs relationship scope is still undecided** (see §3) | `test_commitments_carry_identity_and_mismatched_events_are_refused`, `test_commitments_use_the_existing_event_projection` |

## 2. What changed, per component

| Component | Change |
|---|---|
| Registry | `breaking`, `grandfather_prior_claims`, `revalidate_before`, `requires_revalidation()`; `check_write(assertion=…)` with `ASSERTION_OPS` |
| Claim Gate | Observation vs command (`is_observation`); outcome attestation (`_attest`, `verify_attestation`) |
| Claim Commit | Attestation check; `SyncRecord` / `record_sync` / `last_sync_from`; `SUPERSEDED_BY_POLICY` / `supersede_by_policy`; `record_policy` (journaled publication) |
| Current State | `operational()` excludes REVALIDATION_REQUIRED and SUPERSEDED_BY_POLICY claims; freshness from journaled syncs (the `last_sync` parameter is removed); `revalidation_required` reported; **policy publications are evaluation points, evaluated under the policy in force** (`policy_history`) |
| Typed Retrieval | Contract scope vocabulary plus `INVALID_SCOPE`; journaled freshness; REVALIDATION_REQUIRED and SUPERSEDED_BY_POLICY history labels; commitment identity filter; `get_tenant_knowledge` |
| Commitments (Lane A) | Identity fields and the mismatch check. Behaviour is otherwise unchanged; all Lane A tests pass |
| Context Compiler | Unchanged |
| New | `integration.Pipeline` (test-only composition) and 108 integration tests |

**Existing tests changed (with reasons, nothing weakened):**
- **`test_claim_gate`:**
  - "blind SET under CONFLICT → REJECT" is now expressed as a typed operator **command**. The same test now also asserts that an LLM **observation** during the conflict is recorded (the C-D / G-1 decision);
  - an LLM `RESOLVE_CONFLICT` is refused as `observation_cannot_issue_command_op`.
- **`test_current_state`:**
  - the journal helper now goes through the **real gate** (C-D: hand-built decisions are uncommittable);
  - undeclared state-machine values are refused at the gate, so the state-machine test now asserts that refusal;
  - freshness comes from journaled syncs.
- **`test_typed_retrieval` and `test_context_compiler`:** journaled sync instead of `last_sync`; commitment events carry identity; contract scope names.

## 3. Remaining unresolved decisions

**Unchanged from the decision closure; not decided here:**
- **Security:** C-1 key custody (the gate's attestation key is in-process integrity, not a production credential).
- **Governance:** B-1 policy ownership; B-2 staleness values; B-4 authority ranks; G-3 temporal limits.
- **Legal:** B-3 retention; the C-2 erasure-reversal question; T-4 audit mode; T-5 `k`.
- **Infrastructure:** C-5 storage.
- **Product:** C-6 conflict workflow; X-2 task profiles.
- **Security / Product:** S-3 / T-1 / T-5 grants beyond CUSTOMER; T-2 narrative floor; X-4 monitoring.

**Commitment scope (T-1) stays open.** The brief proposed RELATIONSHIP as an option, but **RELATIONSHIP is not a contract scope** (contract §2). Choosing it would need a contract amendment by the contract owner. The prototype therefore keeps CUSTOMER presentation with agent and tenant attribution, so either outcome is enforceable.

**Engineering items from the decision closure, not part of this brief, still pending:**
- S-2: an evaluation point exactly at each boundary instant (today, boundaries are caught at the next journal or `now` point);
- the C-2 lifecycle transition table (`lifecycle()` still accepts any listed status);
- X-1: injected size measure;
- C-6: the conflict event;
- T-2: narrative `security_class` derivation;
- X-4: the data-channel contract.

## 4. New contradictions discovered in this pass

| # | Finding | State |
|---|---|---|
| **N-1** | **`state_version` rewound on a breaking policy publication** (2 → 0, an OCC ABA hazard), because history was replayed under the current policy | **Fixed**: journaled publications evaluated under the policy in force (harness doc §4) |
| **N-2** | **The brief's scope list conflicts with the contract.** PERSON, RELATIONSHIP and EPISODE are not contract scopes | The contract was followed; these names return `INVALID_SCOPE`. Adding any of them is a contract-owner decision |
| **N-3** | **The Lane A fence epoch names** (`org`, `subject`, `session`) remain internal, non-contract names | Not renamed (Lane A untouched). Documented mapping: org → TENANT, subject → CUSTOMER, session → SESSION. Rename when durable scope generations are built (§10) |
| **N-4** | **Revalidation status is derived, not journaled.** REVALIDATION_REQUIRED is computed from (claim policy version, `revalidate_before`). That is deterministic and rebuildable, but there is no recorded REVALIDATION_REQUIRED transition. SUPERSEDED_BY_POLICY *is* recorded | Consistent with "never silently rewritten" (§10). If the contract owner requires a recorded transition for audit, a journal event can be added without changing resolution |

## 5. Boundary for the durable-storage phase

**What durable storage must persist** (the facts a rebuild uses; everything else is derived):
1. the journal: claim, retraction, lifecycle, **sync** and **policy-publication** entries;
2. the commit ledger (proposal, attested decision, outcome);
3. the evidence store;
4. the policy history (all versions, immutable);
5. per-subject keys (custody: C-1);
6. episodes and commitment events (with identity).

**What it must never persist as truth:** current state, `state_version`, freshness, history labels, revalidation status, context. These are projections. A durable head is a **cache** that must equal the rebuild; the property tests are the acceptance criterion.

**Blocking decisions for that phase (unchanged):**

| Decision | Owner |
|---|---|
| C-5 storage technology and partitioning | Infrastructure |
| C-1 key custody | Security |
| B-3 retention catalogue interface | Legal |
| C-2 erasure reversal | Legal |
| Non-CUSTOMER read grants, only if those scopes are in scope | Security / Product |

**Engineering to finish with that phase** (no owner input needed):
- S-2 boundary-instant evaluation points;
- the C-2 lifecycle table;
- X-1, C-6, T-2, X-4 (decision closure §10);
- the scope-generation rename (N-3).
