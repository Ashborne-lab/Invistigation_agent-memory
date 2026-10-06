# Claim Commit Protocol v1 (target architecture, prototype)

**Date:** 2026-10-03.
**Scope:** investigation prototype only. No production, no PostgreSQL schema, no Memory Gateway, no migration, no shadow writes.

**Code:**
- `memory-prototype/memory_core/commit/__init__.py`: pure, in-memory, standard library only;
- `memory-prototype/tests/test_claim_commit.py`.

**Builds on:**
- the Claim Gate (`memory-claim-gate-v1.md`) and the Registry (`predicate-policy-registry-v1.md`);
- Lane A, reused rather than redesigned:
  - keyed ids (`memory_core.ids`);
  - the E3 fence (`memory_core.fence`);
  - the LA-9 retraction rule;
  - the LA-1 recorded-outcome replay.

**Tests:** 65 (25 focused, plus 40 property seeds). **Full prototype suite: 518/518.**

**Mutation check:**

| Rule removed | Tests that fail |
|---|---|
| OCC check | 2 |
| Proposal-fingerprint check | 1 |
| Retraction applied on insert | 1 |
| Atomic rollback | 1 |
| Evidence fence | 4 |
| Decision-to-proposal binding | 1 |

One mutation survived: disabling the Lane A `include_derivation` flag. It is an **equivalent mutant**, because `claim_identity` already puts the derivation into the hashed input, and the recovery-collision test still passes.

**Separation of responsibilities** (unchanged):

| Layer | Answers |
|---|---|
| Registry | What is allowed |
| Gate | Is this proposal admissible |
| **Commit** | **Record the approved decision safely** |
| Resolver | What is current |
| Authorization | Who may see it |

Commit never resolves a value and never takes a caller.

## 1. Input / output contract

```text
commit(store, proposal, decision, evidence, fence_ctx, subject_key, now, *,
       extractor_version, expected_version=None, actual_version=0,
       expected_status=None, actual_status=None, derivation="orig", crash=None) -> CommitResult
retract(store, RetractionRecord, now) -> CommitResult
lifecycle(store, claim_id, to_status, cause, now) -> CommitResult
rebuild_claims(journal) -> {claim_id: Claim}
Projection.observe(slot_key, resolved_signature) -> state_version
```

**Inputs:**

| Input | Content |
|---|---|
| `proposal` | The gate's `Proposal` |
| `decision` | The gate's `GateOutcome` **for that proposal** (bound by id and content fingerprint) |
| `evidence` | Evidence as it is **at commit time**, so the fence sees changes since the gate ran |
| `fence_ctx` | Lane A fence context: epoch log, `merged_into`, undone merges, erasure times |
| `subject_key(subject)` | The key provider. **Key custody is open:** the prototype uses a dict |
| `actual_version` / `actual_status` | The slot's current `state_version` and status, from the projection |

**`CommitResult(status, record, duplicate, reason)`:**

| Status | Meaning |
|---|---|
| COMMITTED | A new immutable claim was recorded |
| EXISTING_CLAIM | The same claim id was already committed by another proposal. Provenance is linked; no new claim |
| NOT_COMMITTED | The gate's REJECT or REQUIRES_ESTABLISHMENT was recorded, so replay knows. Nothing committed |
| FENCED | Refused by the evidence fence. Recorded |
| DEFERRED | Transient evidence unavailability. **Not** recorded, so a retry is allowed |
| STATE_CONFLICT | Typed failure (contract §7). Recorded and never retried |
| REJECTED | Not recorded: reused id with different content; decision/proposal mismatch; a typed command without `expected_version`; a valueless operation |

**`CommitRecord` keeps proposal, decision and outcome apart:**
- `proposal`, `proposal_fingerprint`;
- `decision` (the gate outcome, verbatim);
- `status`, `claim_id`, `claim_content`;
- `initial_status`, `attributed`, `merge_ids`, `reason`;
- `state_conflict`, `committed_at`.

**Provenance** of a committed claim:

| Where | What |
|---|---|
| `ClaimContent` | subject; key; source; source member; anchor (evidence ids and quotes); policy version; validity interval; `observed_at`; `observed_seq`; `committed_at`; `written_via`; `learned_by_agent_id`; derivation |
| `CommitRecord` | Operation and writer |
| `store.provenance[claim_id]` | Every commit record that produced or re-confirmed the claim |

## 2. Identity

`claim_identity(subject_key, draft, derivation)` is **the only place a claim id is built**, so it can be swapped.
- **Construction:** the Lane A keyed formula, HMAC-SHA256 under a per-subject key.
- **Inputs:**
  - the sorted anchor evidence ids;
  - key;
  - canonical value;
  - **the derivation tag** (F-3: a recovery re-derivation never collides with the original);
  - **source member and asserted interval**, added here so that claims differing only in those never collide.
- Tests show the id is deterministic, and differs when any of these changes: derivation, subject key, member, interval, key, value, anchor.
- **Proposal idempotency and claim identity are separate.**
  - The same proposal replayed is a **duplicate**.
  - A different proposal that yields the same claim is **EXISTING_CLAIM**, and its provenance is appended.

## 3. Idempotency and partial failure

- **Exactly one logical commit per `proposal_id`.** A replay returns the recorded result with `duplicate=True`.
- A reused id with different content → `REJECTED proposal_id_reused_with_different_content`.
- **Atomicity.** Each commit's journal append, claim insert, record, provenance and `claims_version` land together or not at all. An exception mid-write restores the prior state (tested by injecting a failure inside the write).
- **Crash before write:** nothing durable; the retry commits once.
- **Crash after write:** durable, but unacknowledged; the retry returns the duplicate. One claim, one journal entry, `claims_version` = 1.
- Retraction commands are idempotent on `retraction_id` in the same way.

## 4. Concurrency (contract §7; spec §10.4 and §13)

**Established semantics, modelled exactly.** This is not a single per-subject counter.

| Number | What it is |
|---|---|
| `expected_version` | Per **slot**, carried by **typed state commands** (writer ≠ `llm_extractor`). A missing one is rejected |
| `state_version` | The projection's, advanced only when the resolved signature changes (`Projection.observe`). Commit cannot know this without resolving, and resolving is not commit's job |
| `claims_version` | Per subject, advanced on every new claim. **Never** used as an expected version (M3) |

- A mismatch gives a typed **`STATE_CONFLICT`** {predicate, scope, expected and actual version, expected and actual status}. It is recorded against the `proposal_id`.
- **It is never retried.** Replaying the same mutation, even once the versions would match, returns the recorded STATE_CONFLICT. Only a **new** mutation, after a re-read, can commit.
- LLM-extracted assertions carry no `expected_version`. They are evidence, not state commands (spec race A: two turns adding different facts both commit).

## 5. Lifecycle and retraction

- **Content is immutable.** `ClaimContent` is frozen (an assignment raises). Lifecycle changes only append `Transition`s to `ClaimState`.
- **Lifecycle statuses:** `active`, `retracted`, `invalidated`, `quarantined`, `pending_erasure`, `superseded` (persisted mode), exactly as the model defines them.
  - `lifecycle()` records any of them except `retracted`, which must go through `retract()` so that the LA-9 rule applies.
  - Unknown statuses are rejected.
  - No transition graph was invented, because the contract defines none.
- **`RetractionRecord`** is a recorded command:
  - {id, subject, key, value, source, member, cause (`no_longer_true` / `never_true`), observed_at, observed_seq, evidence_id, merge_ids}.
  - It is applied by the **LA-9 rule**: it ends every matching claim of its source group observed at or before it, **including claims committed later**.
  - `never_true` dominates; otherwise the earliest end wins. The outcome is order-independent.
  - `apply_retraction` matches Lane A's `Memory._apply_retraction_record` on **300 random cases**.
  - **Deliberate narrowing:** the commit version also requires the same `subject_id`. A retraction belongs to its subject.

## 6. Fencing

This is the Lane A E3 fence, evaluated **at commit** over the evidence as it is now, not as the gate saw it:
- (a) evidence missing, or dead (`erased`, `pending_erasure`, `invalidated`, `context_suppressed`) → FENCED;
- (b) an org, subject or session epoch advanced by a non-merge cause (for example erasure) since ingestion → FENCED;
- (c) the claim follows `merged_into` to the survivor:
  - an erased subject or org on the path → FENCED;
  - a recorded merge that was undone → committed as **QUARANTINED** and unattributed, on the source subject;
  - a merge loop or an unresolvable link → FENCED;
- transient unavailability → DEFERRED, and not recorded.

## 7. Replay and rebuild

- **The journal is the single source of truth.** It holds claim, retraction and lifecycle entries in sequence. `rebuild_claims(journal)` reconstructs every claim and state **only from recorded outcomes**: no gate, fence or policy is re-run.
- **Replay applies the recorded decision, not today's policy.** A test publishes a newer policy that would now refuse the original proposal; the rebuild is unchanged, and every claim keeps `policy_version = 3`.
- **Current State is derived, never independent truth.** Resolving the rebuilt claims gives an identical slot to the live store.
- **Property test (40 seeds × 25 random operations).** The operations mix commits with deliberate id collisions, injected crashes before and after write, retractions and lifecycle transitions. Each seed asserts:
  - rebuilt == live;
  - rebuilt resolution == live resolution;
  - one claim per distinct claim id.

## 8. Tests (`test_claim_commit.py`, 65)

| Requested | Test |
|---|---|
| Immutable claim commit and provenance; content cannot be mutated; policy version preserved | `test_successful_commit_is_immutable_with_full_provenance`, `test_replay_applies_recorded_decision_not_todays_policy` |
| Deterministic claim id; no collisions; re-derivation distinct | `test_claim_id_is_deterministic_and_distinct` |
| Duplicate retry | `test_duplicate_retry_creates_no_second_claim`, `test_same_claim_from_a_new_proposal_is_existing_not_duplicated` |
| Reused proposal id with different content | `test_reused_proposal_id_with_different_content_rejected` |
| Partial failure and retry | `test_crash_before_write…`, `test_crash_after_write…`, `test_failure_inside_the_write_rolls_back_everything` |
| Expected-version success; versions | `test_expected_version_success_and_versions` |
| Stale expected version → STATE_CONFLICT | `test_stale_expected_version_is_typed_state_conflict` |
| Semantic conflict not retried | `test_state_conflict_is_never_silently_retried` |
| Retraction replay | `test_retraction_is_recorded_idempotent_and_replays`, `test_retraction_recorded_before_claim_still_ends_it`, `test_retraction_rule_matches_lane_a_runtime` |
| Erasure / generation fencing | `test_erasure_generation_fence`, `test_dead_evidence_fence`, `test_missing_evidence_at_commit_is_fenced` |
| Merge-path fencing | `test_merge_path_lands_on_survivor_and_undone_merge_quarantines`, `test_erased_subject_on_merge_path_fenced` |
| Rebuilt projection equals live | `test_rebuilt_projection_equals_live_projection`, `test_property_rebuild_equals_live[0..39]` |

**Also covered:**
- decision/proposal binding;
- a recorded gate rejection;
- typed command without `expected_version`;
- lifecycle never touches content.

## 9. Genuinely unresolved

These are recorded, not decided.

| # | Question | Current prototype behaviour |
|---|---|---|
| C-1 | **The claim-id input set.** The spec formula is evidence + key + value. Source member and interval were added here to avoid collisions. Production construction, the hash algorithm and **key custody** (per-subject key storage, crypto-shredding) remain open | One swappable `claim_identity`, and a key-provider callable |
| C-2 | **Lifecycle transition graph.** The contract lists the statuses but defines no allowed transitions between them (for example, may `pending_erasure` return to `active`?) | Any listed status is recordable except `retracted`, which is reserved for `retract` |
| C-3 | **Scope of a typed command's `STATE_CONFLICT` record.** It is recorded against the `proposal_id`, so the same mutation can never commit later | Matches §7 ("not silently retried"). Whether a caller may intentionally resubmit the same `mutation_id` after a re-read is a contract question |
| C-4 | **Transaction groups** (§7: several slot mutations, all or nothing) | Not modelled: each commit is atomic on its own |
| C-5 | **Durability and retention of the commit ledger and journal** (its storage and retention class) | In memory; the retention class is governance (G5) |
| C-6 | **The gate's CONFLICT decision.** The claim is committed as evidence, as the gate defined it. Whether the commit layer should also open a conflict-resolution task is unspecified | Committed, nothing more |

No production schema, retention value, policy owner, key-custody choice or infrastructure was decided.
