# Predicate Policy Registry v1 (target architecture, prototype)

**Date:** 2026-10-03.
**Scope:** the investigation prototype only. No production reads or writes, no migration, no Memory Gateway, no PostgreSQL.
**Code:**
- `memory-prototype/memory_core/registry/__init__.py`, which is pure and uses the standard library only;
- `memory-prototype/tests/test_policy_registry.py`: **37 tests, all pass.** The full prototype suite passes at 425/425, so the Lane A suites are unaffected.

**Sources:**
- contract §3 (policy structure, freshness, status gating, cardinality), §5 (authority), §6 (resolution steps and authorization), §10 (policy migration), §11 (result granularity);
- the existing Lane A resolver, reused rather than rewritten.

## 1. Design

| Concern | Decision |
|---|---|
| Relationship to the Lane A registry | `memory_core.policy` (a dict with namespaces) stays as it is, because the Lane A suites depend on it. The new `memory_core.registry` is the contract-shaped registry. SINGLE and SET resolution delegates to the Lane A bitemporal resolver, which covers supersession, retraction, CONFLICT and EXPLICIT_NONE, through an adapter. |
| Publication | Append-only and versioned. A version is validated before it is accepted, and a published version can never be rewritten: its mappings are frozen. Versions must strictly increase. A cardinality change is reported (`cardinality_changed`), so §10 policy migration applies. |
| Lookup | Exact predicate and optional pinned version. **There is no fallback policy:** an unknown predicate or version raises `UnknownPredicate` (§3, "the registry is mandatory"). |
| Resolution | `resolve_slot(policy, claims, as_of, cutoff, d, now, last_sync)` covers §6 steps 1–8. **It takes no caller argument by construction**, and a test asserts this. The freshness contract is applied after resolution and produces a `usage` label. |
| Authorization | `authorize(resolved, slot_scope, caller)` is §6 step 9. It decides only whether the caller may read the result. A denied caller gets `ACCESS_DENIED` with no value and no provenance. It never changes the value. |
| Write gating | `check_write(policy, command, current_resolved)` validates a mutation command against the policy **and the slot's current status** (§3, §7). |

## 2. Data model (`PredicatePolicy`, contract §3 fields)

| Field | Type / vocabulary | Notes |
|---|---|---|
| `predicate`, `policy_version_id` | str, int | |
| `cardinality` | SINGLE, SET, MAP, STATE_MACHINE, ORDERED_SET, COUNTER | ORDERED_SET and COUNTER are declared by the contract but **rejected as not implemented**; no domain needs them yet |
| `allowed_writers` | llm_extractor, user_command, operator, system_sync, import | Writer vocabulary added here (§3 names the field, not the values) |
| `allowed_sources` | Source classes | |
| `allowed_operations_by_status` | status → operations: SET, ESTABLISH, TRANSITION, RESOLVE_CONFLICT, CLEAR, ADD, REMOVE, PUT_KEY, REMOVE_KEY | Required for all four statuses (SINGLE, MAP, STATE_MACHINE) or for VALUE and UNKNOWN (SET) |
| `authority_domain` | str | |
| `authority_rank` | source → int | This is the contract's `resolution_policy`. It must rank exactly `allowed_sources` |
| `conflict_policy` | `resolve_operation`, `resolvers` | Resolvers must be allowed writers |
| `temporal_model` | stable, volatile, expiring | |
| `security_class` | standard, sensitive, identity_security | |
| `retention_class` | str, required | Its values are governance (G5) |
| `current_state_eligible` | bool | |
| `llm_write_mode` | FORBIDDEN, PROPOSE_VIA_GATE, TYPED_COMMAND | |
| `freshness` | `max_staleness`, `stale_read_policy` (READ_ALLOWED, DISPLAY_ONLY, REQUIRES_REFRESH, UNAVAILABLE), `stale_write_policy` (WRITE_ALLOWED, WRITE_FORBIDDEN, REQUIRES_REFRESH), `freshness_source` (observed_at, external_sync) | The contract's five stale uses, split into read and write. `WRITE_ALLOWED` was added here |
| `map_keys` | frozenset | MAP: a bounded key set (§3: "bounded collection") |
| `transitions`, `initial_states` | state → next states | STATE_MACHINE |

**Validation rules** (`validate_policy`; every violation is listed):
- the cardinality is known and implemented;
- writers are drawn from the vocabulary;
- ranks cover exactly the sources;
- `llm_extractor` is a writer **if and only if** `llm_write_mode == PROPOSE_VIA_GATE`;
- `identity_security` predicates have no LLM or user writer (§5 `account_role`);
- `retention_class` is declared;
- an external-sync freshness source requires `max_staleness`;
- the status map covers the cardinality's statuses;
- **CONFLICT allows the declared resolve operation and no blind write** (§3);
- conflict resolvers are allowed writers;
- MAP has keys;
- STATE_MACHINE has declared targets and initial states.

## 3. Interfaces

```text
PolicyRegistry.publish(policy) -> PublishReport        # PolicyError on any violation or non-increasing version
PolicyRegistry.get(predicate, version=None) -> policy  # UnknownPredicate; no fallback
resolve_slot(policy, claims, as_of, cutoff, d, now, last_sync=None) -> Resolved(slot, usage, keys, security_class)
check_write(policy, WriteCommand(predicate, policy_version_id, op, writer, source, value, map_key), current) -> WriteDecision
authorize(resolved, slot_scope, Caller(principal, authorized_scopes, cleared_classes)) -> Resolved
```

**Resolution granularity (§11):**

| Cardinality | Returns |
|---|---|
| SINGLE | VALUE / EXPLICIT_NONE / UNKNOWN / CONFLICT |
| SET | Per-element `elements` |
| MAP | Per-key `keys[k]`, each with its own status, freshness and usage. Claims are addressed by `predicate[key]` |
| STATE_MACHINE | Like SINGLE. A resolved value that is not a declared state is not operational (UNKNOWN) |

**Freshness usage labels:**

| Label | When |
|---|---|
| OPERATIONAL | Fresh, or stale under READ_ALLOWED. A stale value keeps `freshness_status=STALE` |
| DISPLAY_ONLY | Stale under DISPLAY_ONLY |
| REFRESH_REQUIRED | Stale under REQUIRES_REFRESH |
| NONE | Stale under UNAVAILABLE: status UNAVAILABLE, value withheld. Also returned for ACCESS_DENIED |

**Write-check order:**
1. predicate;
2. **policy version must be current**;
3. writer;
4. source;
5. LLM mode;
6. MAP key is declared, then **the per-key status is used**;
7. the slot is not UNAVAILABLE or ACCESS_DENIED;
8. the operation is allowed in the current status;
9. a resolve operation needs a declared resolver;
10. state-machine graph and initial states;
11. stale-write policy.

## 4. Tests (`tests/test_policy_registry.py`, 37)

| Area | What is proven |
|---|---|
| Validation (15) | All example policies are valid. Each rule rejects its violation, and publishing is refused |
| Registry (2) | No fallback (unknown predicate or version). Append-only versions; old versions stay readable and frozen; a cardinality change is flagged |
| Cardinality (5) | The same claims give CONFLICT under SINGLE and two ACTIVE elements under SET, so **cardinality comes from policy, not data**. Equal-authority disagreement gives CONFLICT, never recency. MAP keys resolve independently (VALUE / CONFLICT / UNKNOWN in one map). State-machine graph and initial states are enforced. An undeclared state is not operational |
| Authority (3) | A user statement cannot override `billing_address` (BILLING_SYSTEM). `account_role` cannot be written by the LLM, a user, or a user-sourced sync. **39 repeated user claims lose to one HR_SYSTEM claim** |
| Freshness (5) | **The contract's own example:** synced 6 h ago against a 15 min budget, so STALE and DISPLAY_ONLY even though `observed_at` is recent. A fresh sync is operational. The UNAVAILABLE, REQUIRES_REFRESH and READ_ALLOWED read policies. A stale write is forbidden. No recorded sync means STALE regardless of support |
| Status gating (4) | Under CONFLICT a blind SET is refused, a non-resolver is refused, and the declared resolver is allowed. UNKNOWN allows ESTABLISH but not TRANSITION. EXPLICIT_NONE allows SET. MAP gating is per key. An undeclared map key is refused. A command naming an old policy version is refused |
| Authorization (4) | `resolve_slot` has no caller parameter. Two authorized callers get an identical slot, even when the winning claim comes from a member one of them cannot see. A denied caller gets ACCESS_DENIED with no value and no provenance. A sensitive class needs clearance. A denied result cannot be written through |

## 5. Genuinely blocking decisions

Only items that stop the **next step**: authoring the first real policies and wiring `check_write` into the gate. Everything else in §6 is non-blocking.

| # | Decision | Blocks | Owner (as already recorded) |
|---|---|---|---|
| B1 | **Who authors and owns each predicate's policy.** The contract names "domain owner per predicate", a role, not a party (Session 5, R2) | Publishing any real policy | Architecture owner (R2) |
| B2 | **Staleness budgets** (`max_staleness`, stale read/write policy) for externally owned predicates (G3) | Real policies for BILLING_SYSTEM, CRM and other external domains. Customer-preference predicates are not blocked | Domain owners / contract owner (G3) |
| B3 | **`retention_class` values** (G5, parked) | Publishing any real policy: the registry requires the field by design. A placeholder class would quietly decide G5 | Legal (G5) |
| B4 | **Operator vs user authority on the same field** (D1(b) / O11: equal, above or below) | Every person-attribute policy's `authority_rank` | Already recorded as D1(b) |

## 6. Recorded, not blocking

- **ORDERED_SET and COUNTER semantics:** implement when a domain needs them.
- **Open namespaces** (`note.*`, `family.*`): the Lane A registry has them, the new one does not. Whether the contract permits wildcard policies is a contract question. Add them only if B1 needs them.
- **Vocabulary additions made here:** the writer kinds and `WRITE_ALLOWED`. They need contract-owner confirmation, but they don't block.
- **Clearance model for `sensitive` / `identity_security` reads** (who grants it) is a Security question for rollout, not for the core.

**Context only:** the CTO's independently fixed current-system baselines are recorded in `cto-latest-code-reconciliation-v1.md` §6. They do not change this target-architecture work.
