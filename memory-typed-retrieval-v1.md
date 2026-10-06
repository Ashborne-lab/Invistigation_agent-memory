# Typed Retrieval v1 (target architecture, prototype)

**Date:** 2026-10-03.
**Scope:** investigation prototype only. No production, PostgreSQL, Memory Gateway, migration or shadow writes. No subagents, no LLM, no embeddings, no external services.

**Code:**
- `memory-prototype/memory_core/retrieval/__init__.py`;
- `memory-prototype/tests/test_typed_retrieval.py`.

**One small refactor:** `registry.may_read` was extracted from `registry.authorize`, so every retrieval path uses the **same** read rule.

**Builds on:**
- Current State (`project_subject`);
- Claim Commit (journal replay);
- Registry (policies, `may_read`);
- the Lane A resolver's own read-time supersession rule (`_superseded_read_time`), used for history labels;
- the Lane A models `Episode` (narrative) and `commitments.project` (R-10).

**Tests:** 27. **Full prototype suite: 624/624.**

**Mutation check.** Each rule removed fails at least one test:

| Rule removed | Tests that fail |
|---|---|
| Lifecycle exclusion | 2 |
| `never_true` exclusion | 1 |
| HISTORICAL usage label | 2 |
| Dead-evidence filter on narrative | 1 |
| Listing omits uncleared predicates | 1 |
| Superseded end time | 1 |
| Up-front scope check | 1 (initially survived; the new listing-denial test closed it) |

## 1. Capability contracts (contract §8: the operation is the intent)

| Operation | Source | Status |
|---|---|---|
| `get_current_state(src, subject, predicate \| None, as_of, now, caller, scope_type)` | The Current State projection, never re-resolved independently | Supported |
| `search_history(src, subject, predicate \| None, now, caller, valid_window=None, limit)` | Immutable claims, replayed from the journal | Supported |
| `search_memory(src, subject, query, caller, limit)` | Narrative `Episode` summaries; deterministic token matching | Supported (no vectors) |
| `get_commitments(src, subject, now, caller)` | The existing commitment event-log projection: idempotent creation, read-time expiry, erased evidence rejected | Supported |
| `get_relationships(...)` | — | `UNSUPPORTED_CAPABILITY`: no relationship model exists |
| `get_org_knowledge(...)` | — | `UNSUPPORTED_SCOPE`: ORG scope is unmodelled (S-3). Agent Knowledge exists, but its read scope is undefined |

`MemorySource` is the immutable bundle the future gateway would read:
- the journal;
- pinned policies;
- episodes;
- commitment events;
- dead evidence;
- `last_sync`;
- the decisions object.

## 2. Result structures

```text
RetrievalResult(retrieval_type, status, items, reason)
    status: OK | ACCESS_DENIED | UNKNOWN_PREDICATE | UNSUPPORTED_SCOPE | UNSUPPORTED_CAPABILITY
MemoryItem(retrieval_type, subject_id, scope, predicate, value, status, valid_from, valid_until,
           freshness_status, usage, provenance, policy_version, source, authority_domain, observed_at, state_version)
```

- `provenance` holds **references only**: claim ids and evidence ids, episode evidence ids, or commitment event ids.
- No raw `Claim`, `ClaimState`, journal entry or store object is ever returned.

## 3. Filtering, labelling and ranking

**Current state:**
- Exactly the projected `StateSlot`: status (CONFLICT keeps its value `None`), freshness and usage, provenance, policy version and `state_version`.
- A requested predicate with no slot returns UNKNOWN. A listing returns only existing slots.

**History:**
- Every item has `usage = HISTORICAL`. **History never becomes operational truth.**
- Each item carries the §8 temporal labels: status, `valid_from`, `valid_until`, source, scope.

| Label | Meaning |
|---|---|
| CURRENT | It is the current slot winner |
| IN_CONFLICT | It is in the current conflict set |
| ENDED | Retracted `no_longer_true`, or `valid_until` has passed |
| SUPERSEDED | The resolver's own same-source-group rule. `valid_until` is set to where the superseding claim starts |
| NOT_SELECTED | For example, outranked by a higher-authority source |

- Freshness is labelled per policy (STALE or FRESH). It is never promoted.
- An optional valid-time window filters by interval overlap.
- **Ranking:** most recently observed first, then claim id.

**Narrative:**
- Only summaries in state `ok` are eligible.
- Summaries resting on dead evidence are excluded.
- **Ranking:** query-token overlap, then recency, then episode id. This is deterministic.

**Commitments:** exactly `commitments.project(events, now, dead_evidence)`. No new commitment semantics were added.

## 4. Lifecycle handling (reused, not redefined)

| Lifecycle state | Current State | History | Narrative |
|---|---|---|---|
| quarantined / pending_erasure / invalidated | Excluded (Lane A `EXCLUDED`) | Excluded | Summary not `ok` → excluded |
| retracted `no_longer_true` | Ends the value | ENDED, with its effective end | — |
| retracted `never_true` | Excluded | **Excluded** (it was never true, so it is not history of truth) | — |
| reactivated | Counts again | CURRENT or other labels again | — |

## 5. Authorization boundary

**Order of every operation:**
1. Scope check: is the scope supported?
2. Predicate check: does a policy exist?
3. Caller scope check (`may_read`): an unauthorized caller gets **ACCESS_DENIED with no items and no reason**, whether it asked for one predicate or a full listing.
4. Build the result from system-resolved data, independent of the caller.
5. Per-item clearance:
   - an explicitly requested uncleared predicate gives ACCESS_DENIED;
   - **a listing omits uncleared items entirely**, so not even their existence leaks.

**What the caller can and cannot affect:**
- The caller changes only *whether* data is returned, never *which* value is true. Two authorized callers get identical results.
- The caller is accepted only to apply `may_read`, which is the registry's single §6 step-9 rule.

## 6. Unsupported scope

- Only `CUSTOMER` is projected (S-3).
- Any ORG, AGENT or SESSION `scope_type` returns `UNSUPPORTED_SCOPE` with no items. This is tested for every supported operation.
- `get_org_knowledge` returns `UNSUPPORTED_SCOPE`.

## 7. Architectural test

`test_retrieval_does_not_mutate_or_create_memory_or_depend_on_caller` runs every operation for four callers: authorized, authorized, stranger and cleared. It then asserts:
- the journal is unchanged;
- the claims are unchanged;
- no new memory was created;
- the Current State projection is unchanged;
- the results are identical across the authorized callers;
- no LLM parameter exists.

Determinism is also asserted per operation.

## 8. Tests (27)

| Case | Test |
|---|---|
| Current-state retrieval with metadata | `test_current_state_returns_projection_with_metadata` |
| Historical retrieval (labels, never promoted) | `test_history_labels_and_never_promotes` |
| History provenance | `test_history_preserves_provenance` |
| Past-window history | `test_history_for_a_past_window` |
| Narrative retrieval (lifecycle-aware, deterministic) | `test_narrative_search_is_deterministic_and_lifecycle_aware` |
| Commitment retrieval | `test_commitments_use_the_existing_event_projection` |
| Relationships / org knowledge | `test_unmodelled_capabilities_are_explicit` |
| Unauthorized caller (4 operations) | `test_unauthorized_caller_gets_access_denied_and_nothing_else[*]`, `test_unauthorized_listing_is_denied_not_an_empty_ok` |
| Sensitive predicate without clearance; listing omission | `test_sensitive_predicate_without_clearance_denied_without_leak`, `test_current_state_listing_omits_uncleared_sensitive_predicates` |
| Quarantined / pending erasure | `test_quarantined_and_pending_erasure_excluded_everywhere[*]` |
| Retracted (both causes) | `test_retracted_claims_follow_lifecycle_semantics` |
| Superseded | `test_history_labels_and_never_promotes` |
| Conflict (not resolved, labelled) | `test_conflict_is_reported_in_history_and_not_resolved` |
| Stale (current and history) | `test_stale_current_value_labelled_not_promoted`, `test_stale_history_is_labelled` |
| Unknown predicate | `test_unknown_predicate` |
| Unsupported scope (ORG / AGENT / SESSION) | `test_unsupported_scopes_are_explicit[*]` |
| Same result for every authorized caller | `test_same_request_same_result_for_every_authorized_caller` |
| No provenance on ACCESS_DENIED | `test_access_denied_carries_no_provenance_anywhere` |
| No mutation, no memory creation, caller-independent | `test_retrieval_does_not_mutate_or_create_memory_or_depend_on_caller` |

## 9. Unresolved

**Still open, untouched:**
- **C1–C6**;
- **B1–B4** (all policies here are TEST_ONLY);
- **S-1, S-2, S-3** (S-3 is unchanged: only CUSTOMER scope).

**New, found directly while building this:**

| # | Issue | Current prototype behaviour |
|---|---|---|
| T-1 | **Commitments have no subject field.** `commitments.Event` is keyed by `commitment_key` (an HMAC of the relationship and related fields), not by subject. Retrieval assumes the gateway passes the subject's own events | Whether commitments are CUSTOMER-scoped, relationship-scoped (agent × subject) or something else is not settled. It also determines their authorization scope |
| T-2 | **Narrative security class.** Episodes carry no security class, but a summary can contain sensitive content | Treated as `standard` |
| T-3 | **History label vocabulary.** The contract gives only SUPERSEDED as an example. `IN_CONFLICT`, `ENDED` and `NOT_SELECTED` were named here | Needs contract-owner confirmation |
| T-4 | **History visibility for `never_true`.** It is excluded here, as it is from resolution (Lane A). An audit-oriented history might need to show it | Excluded |
| T-5 | **Agent Knowledge read path.** It exists (R-11, k-anonymity), but has no defined scope or authorization, and ORG knowledge has no model | Left unsupported, not guessed |

No governance decision was taken. No vector search, Memory Gateway or PostgreSQL was built.
