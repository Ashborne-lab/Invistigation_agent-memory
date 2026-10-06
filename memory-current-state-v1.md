# Current State Projection / Subject Head v1 (target architecture, prototype)

**Date:** 2026-10-03.
**Scope:** investigation prototype only. No production, PostgreSQL, Memory Gateway, migration or shadow writes. No subagents.

**Code:**
- `memory-prototype/memory_core/state/__init__.py`: pure, standard library only;
- `memory-prototype/tests/test_current_state.py`.

**Builds on:** Claim Commit (journal, `_insert` / `apply_retraction` / `_transition`), the Registry (`resolve_slot`, which wraps the Lane A resolver unchanged) and the Lane A lifecycle exclusions (`temporal.EXCLUDED`).

**Tests:** 79 (19 focused, plus 60 property seeds). **Full prototype suite: 597/597.**

**Mutation check.** Removing each rule fails tests:

| Rule removed | Tests that fail |
|---|---|
| Boundary re-evaluation | 26 |
| Claim ids leaking into the signature | 2 |
| Conflict values in the signature | 1 |
| The final evaluation at `now` | 1 |
| Subject filter | 1 |

## 1. Projection contract

```text
project_subject(claims, lifecycle_events, policies, as_of, now, *, subject,
                d=AMENDED, last_sync=None, incremental=False) -> CurrentState
```

**Inputs:**

| Input | Content |
|---|---|
| `claims` | Committed claim journal entries |
| `lifecycle_events` | The recorded retraction and lifecycle journal entries |
| `policies` | Predicate → **pinned** `PredicatePolicy`. The version used is explicit on every slot |
| `as_of` | Valid time |
| `now` | Knowledge cutoff and freshness clock |
| `last_sync` | External-sync times, for freshness |

**Output:** `CurrentState(subject_id, as_of, now, claims_version, slots, unprojected_keys)`.
- `claims_version` counts the committed claims for this subject. It is never an expected version.
- `unprojected_keys` lists claim keys that have no policy. They are reported, never guessed: there is no fallback.

**What the projection never does:** take a caller, run authorization (that stays in `registry.authorize`, §6 step 9), call an LLM, mutate its inputs, or keep state between calls. The same arguments always give an equal result.

**Pipeline:**
1. Replay the journal into claim states, using the commit layer's own recorded-outcome rules.
2. Select the subject's claims. Claims merged onto the survivor live on the survivor; quarantined ones from an undone merge stay out.
3. For each current-state-eligible predicate, call `resolve_slot`, which is the Lane A resolver plus the registry's MAP, STATE_MACHINE and freshness handling.
4. Attach the `state_version` values.

## 2. `StateSlot`

| Field | Content |
|---|---|
| `subject_id`, `predicate` | `predicate[key]` for a MAP key slot |
| `scope` | (`CUSTOMER`, subject) |
| `policy_version` | The version used to resolve |
| `status` | VALUE / EXPLICIT_NONE / UNKNOWN / CONFLICT / UNAVAILABLE |
| `value` | None under CONFLICT: **there is never a silent winner** |
| `elements` | SET: per-element value and status |
| `keys` | MAP: child `StateSlot`s, each with its own status and version |
| `winning_claim_ids`, `conflict_claim_ids` | Provenance references |
| `valid_from`, `valid_until` | Validity |
| `freshness_status`, `usage` | Freshness, kept **separate from validity**. `usage` is OPERATIONAL, DISPLAY_ONLY, REFRESH_REQUIRED or NONE |
| `authority_domain`, `source` | |
| `state_version` | See §3 |

**Lifecycle is respected by reuse, not re-implementation.**
- Quarantined, pending-erasure and invalidated claims never become current state (Lane A `EXCLUDED`).
- Retractions follow LA-9 through the commit layer.
- A claim returned to ACTIVE counts again.

## 3. `state_version` semantics

**Definition.** For each slot, `state_version` is the number of evaluation points at which the slot's **semantic signature** changed. It is a deterministic function of the journal and `now`, so a rebuild reproduces it exactly.

**The semantic signature** is:
- status;
- value;
- the SET elements' (value, status) pairs;
- the **set of conflicting values**.

**Claim ids are excluded.**
- A new supporting claim for the same value does **not** advance the version; `claims_version` does.
- A change in *which* values conflict **does** advance it.

**The evaluation points** are after every journal entry, at the entry's time, plus once at `now`.

**Slots evaluated at each point:**

| Path | Re-evaluates |
|---|---|
| Live (`incremental=True`) | The slots the entry touched, **plus** slots with a validity boundary (`valid_from` / `valid_until`) passed since the previous point. This is the spec's `next_boundary_at ≤ now` rule: a scheduled value takes effect without any commit |
| Rebuild (`incremental=False`) | Every slot at every point |

**A never-populated slot has no version.** It starts at 1 on first population.

**MAP:** each key has its own version. The map's version advances when any key changes.

## 4. Rebuild semantics

- Current State is never stored as truth. It is recomputed from the journal and claims alone.
- **The live and rebuild paths are independent.** One is touched-slot tracking with boundary scheduling; the other is an exhaustive recomputation. They must produce equal `CurrentState`s.
- **Property test: 60 seeds × 30 random operations.** The operations mix:
  - claims across SINGLE, SET, MAP, STATE_MACHINE and external-freshness predicates;
  - three authority levels and two members;
  - past and future `valid_from` (supersession and scheduled values);
  - retractions (both causes) and lifecycle transitions (quarantine, pending erasure, invalidation, reactivation).
- Each seed asserts:
  - live == rebuild;
  - the projection is repeatable;
  - every CONFLICT has a `None` value;
  - the live and rebuild version maps are equal.

**What the property test found.** Its first run failed 25 of 60 seeds. Tracking only touched slots missed **scheduled changes**: a claim with a future `valid_from` takes effect when time passes, without any commit. The diagnosis was confirmed by re-running with only past `valid_from` values, which passed 60/60. The fix is the boundary rule above.

## 5. Tests (`test_current_state.py`, 79)

| Edge case | Test |
|---|---|
| First claim creates a slot (version 1, policy version, scope) | `test_first_claim_creates_a_slot` |
| Supporting same-value claim does not advance `state_version` (while `claims_version` does) | `test_supporting_same_value_claim…`, `test_claims_version_and_state_version_are_distinct` |
| Higher authority changes value and version; lower authority does not | `test_higher_authority_changes_value_and_version` |
| Equal-authority disagreement → CONFLICT, value None; the version moves only when the conflicting values change | `test_equal_authority_disagreement_is_conflict_never_a_winner` |
| Retraction, live == rebuild | `test_retraction_rebuilds_correctly` |
| Supersession across time; bitemporal `as_of` | `test_supersession_across_time_is_bitemporal` |
| A stale value is kept with the DISPLAY_ONLY label; freshness ≠ validity ≠ version | `test_stale_value_is_kept_with_usage_label…` |
| Quarantined, pending-erasure and invalidated claims never current; reactivation restores | `test_excluded_lifecycle_never_becomes_current_state[3]` |
| Merge lands on the survivor; an undone merge stays quarantined and out | `test_merge_projects_on_survivor_and_undone_merge_stays_out` |
| MAP keys project and version independently | `test_map_keys_project_independently` |
| State machine resolves only declared states | `test_state_machine_resolves_only_declared_states` |
| SET elements | `test_set_elements_project_and_version` |
| Delete and rebuild equals live | `test_delete_and_rebuild_equals_live` |
| A scheduled value takes effect without a commit | `test_scheduled_value_takes_effect_without_a_commit` |
| Unknown predicate reported, not guessed; no caller; pure | `test_unknown_predicate…`, `test_projection_has_no_caller_and_is_pure` |
| Rebuild property | `test_property_live_equals_rebuild[0..59]` |

## 6. Unresolved

**Still open from earlier, untouched:**
- **C1** claim-id inputs and key custody;
- **C2** lifecycle transition governance;
- **C3** mutation-id reuse after STATE_CONFLICT;
- **C4** transaction groups;
- **C5** durable ledger and journal storage;
- **C6** conflict-resolution task creation;
- all real policy governance (B1–B4).

**New, found directly while building this:**

| # | Issue | Current prototype behaviour |
|---|---|---|
| S-1 | **Signature divergence from the spec.** Spec §13 says `state_version` advances when "status, value, winners or conflict set" change, which includes winner **ids**. The brief's rule 6 says a new supporting claim must not advance it | Follows rule 6: claim ids are excluded, and conflicts compare **values**. The contract or spec owner should confirm which definition governs OCC |
| S-2 | **Scheduled changes and OCC.** A scheduled value taking effect (no commit) advances `state_version`. So an agent that read before the boundary and writes after it gets STATE_CONFLICT. This is consistent with "has this slot changed since I read it", but it is a behavioural choice | Versions advance at evaluation points (journal entries and `now`), not at the exact boundary instant. Two boundaries crossed between points count once. The durable head therefore needs `next_boundary_at` scheduling (spec), which is not modelled as a job |
| S-3 | **Scope.** Contract §2 makes state scope explicit and allows non-CUSTOMER scopes (org, agent, session) | Only the subject (`CUSTOMER`) scope is projected. Multi-scope slots need the scope-assignment rules, which are not in the prototype |

No production schema, retention, policy ownership, key custody or infrastructure was decided. Every policy is TEST_ONLY.
