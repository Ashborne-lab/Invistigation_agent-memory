# Evidence → Claim Gate v1 (target architecture, prototype)

**Date:** 2026-10-03.
**Scope:** investigation prototype only. No production, no PostgreSQL, no Memory Gateway, no migration, no shadow writes.

**Code:**
- `memory-prototype/memory_core/claimgate/__init__.py`: pure and deterministic, standard library only;
- `memory-prototype/tests/test_claim_gate.py`.

**Builds on:**
- `predicate-policy-registry-v1.md` (registry, `check_write`, `resolve_slot`, `authorize`);
- the Lane A gate's grounding helpers (`_grounded`, `_source_of`, `_value_in`), reused unchanged.

**Tests:**
- 27 gate tests, plus 1 registry guard test, all pass.
- **Full prototype suite: 453/453.**
- Mutation check: removing any one of four gate rules makes exactly one test fail:
  - evidence-source match;
  - value-in-quote;
  - idempotency-key reuse;
  - the conflict flag.

## 1. Input / output contract

```text
decide(proposal, registry, evidence, current, now, ledger=None) -> GateOutcome
```

**Inputs:**

| Input | Content |
|---|---|
| `Proposal` (frozen) | `proposal_id` (idempotency key), `subject_id`, `org_id`, `predicate`, `policy_version_id`, `op` (registry operation vocabulary), `writer`, `source`, `value` as (kind, canonical value), `anchor` as ((evidence_id, quote), …), `map_key`, `valid_from`, `valid_until` |
| `registry` | A `PolicyRegistry` |
| `evidence` | The evidence metadata the anchor cites (Lane A `Evidence`) |
| `current` | The slot's current `Resolved` result, from `resolve_slot` (§6 steps 1–8). The gate never resolves state itself |
| `now` | Gate clock |
| `ledger` | Idempotency memory, keyed by proposal id and by content fingerprint |

**Output:** `GateOutcome(decision, reason, proposal_id, fingerprint, step, effect, draft, duplicate)`.

| Decision | Meaning |
|---|---|
| `ACCEPT` | Commit `draft` as an immutable claim |
| `REJECT` | Nothing is committed. `reason` and `step` say why |
| `CONFLICT` | The claim is admissible and `draft` is returned (it is evidence and is kept), but accepting it puts the slot into CONFLICT: an equal-authority, independent source disagrees. The caller knows deterministically that clarification or the policy's resolve operation is needed |
| `REQUIRES_ESTABLISHMENT` | The slot is UNKNOWN and this operation is not allowed there, but ESTABLISH is (for example, TRANSITION on an unestablished state machine) |

**`effect`** is informational, because resolution decides the value:

| Effect | Meaning |
|---|---|
| NEW_VALUE | No current value to compare against |
| REPLACEMENT | Same source group or higher rank: temporal supersession |
| SAME_VALUE | Support for the existing value |
| SHADOWED | Lower rank: kept as evidence, cannot win |
| RESOLUTION, TRANSITION, ESTABLISH, ELEMENT | The operation's own effect |

**`ClaimDraft`** holds everything an immutable `ClaimContent` needs, except the ids and commit time:
- key: `predicate`, or `predicate[map_key]` for MAP;
- value, source;
- `source_member_id`, taken from the evidence;
- `written_via`: `llm` or `command`;
- anchor and validity interval;
- `observed_at`: the latest anchoring evidence time;
- the pinned policy version, and the operation.

## 2. Gate ordering

The first failing step decides. Static checks run before evidence, and evidence before dynamic state.

| Step | Check | Rejection reasons |
|---|---|---|
| 0 | Idempotency: the same `proposal_id` with the same content returns the prior outcome, `duplicate=True`, no draft. The same id with different content is rejected. Identical content under a new id is a duplicate of the accepted one | `proposal_id_reused_with_different_content` |
| 1 | Predicate exists in the registry (no fallback) | `unknown_predicate` |
| 2 | The proposal names the **current** policy version | `stale_policy_version` |
| 3 | Schema: known operation, value kind, MAP key present | `unknown_operation`, `bad_value`, `map_key_required` |
| 4 | Writer allowed; source allowed; LLM write mode; security class. Identity-security predicates cannot list LLM or user writers (registry validation), so here they fail as `writer_not_allowed` | `writer_not_allowed`, `source_not_allowed`, `llm_write_forbidden` |
| 5 | **Evidence supports the assertion.** Every anchor exists; is active and sealed; is not agent or system text; contains the quote; is not an echo of the agent's own arguments. **The evidence's own source equals the claimed source.** The quote carries the value | `no_supporting_evidence`, `evidence_not_found`, `unsupported:<why>`, `evidence_source_mismatch`, `unsupported:value_not_in_quote` |
| 6 | Subject and org binding: the evidence belongs to the proposal's subject and org. This is binding, not authorization | `evidence_subject_or_org_mismatch` |
| 7 | Temporal validity: evidence is not from the future; the interval is non-empty | `evidence_from_the_future`, `empty_validity_interval` |
| 8 | Dynamic rules, through the registry's `check_write` (a single implementation): status gating against the current resolved status, per-key for MAP; resolver identity for the resolve operation; declared MAP keys; state-machine graph and initial states; stale-write policy. An UNKNOWN slot where ESTABLISH is allowed returns REQUIRES_ESTABLISHMENT | `op_<OP>_not_allowed_in_<STATUS>`, `not_a_conflict_resolver`, `map_key_not_declared`, `illegal_transition`, `not_an_initial_state`, `stale_write_forbidden`, `slot_access_denied` |
| 9 | Effect classification; CONFLICT flag | — |

## 3. Invariants (each covered by a test)

1. **The LLM proposes; deterministic code decides.** `decide` is a pure function of its inputs. The same inputs give an equal outcome, and no model is called.
2. **No predicate without a policy, no write against an old version.**
3. **Evidence-grounded only.** A claim's value must appear in a quote that is in sealed, active, non-agent evidence for the same subject and org.
4. **No source laundering.** User text cannot become an OPERATOR or BILLING_SYSTEM claim: the evidence's source must equal the claimed source.
5. **Identity and security predicates are unreachable by the LLM, users and operators.** This is enforced twice: such a policy cannot be published, and the gate rejects the writer.
6. **CONFLICT is never overwritten blindly.** Only the declared resolver's resolve operation is accepted (§3).
7. **Cardinality and structure come from policy:** MAP keys are bounded, and state-machine transitions follow the graph.
8. **A stale external value cannot be written over when the policy forbids it** (§3 freshness).
9. **Idempotent.** A replayed proposal produces no second claim. A reused id with different content is refused.
10. **No caller anywhere in the gate.** Authorization stays at read time (§6 step 9). A claim the gate accepted, once resolved, is still withheld from an unauthorized caller: no value, no provenance.
11. **Test policies cannot leak into production.** Every test policy is `TEST_ONLY_*`. `PolicyRegistry()` refuses them unless it is explicitly created with `allow_test_only=True`. The registry's own earlier test policies were relabelled `TEST_ONLY_RETENTION` for the same reason.

## 4. Tests (`test_claim_gate.py`, 27)

| Requested case | Test |
|---|---|
| Valid grounded assertion → ACCEPT | `test_valid_grounded_assertion_accepted` |
| Unsupported assertion → REJECT (5 forms: quote absent, agent text, unsealed, missing evidence, no anchor), plus value not in quote | `test_unsupported_assertion_rejected[*]`, `test_value_must_be_carried_by_the_quote` |
| Wrong source → REJECT (not allowed; allowed but not the evidence's own source) | `test_wrong_source_rejected` |
| Forbidden LLM writer → REJECT | `test_forbidden_llm_writer_rejected` |
| Identity-security writer → REJECT (LLM, user, operator; such a policy is also unpublishable) | `test_identity_security_writer_rejected` |
| Conflicted slot + blind SET → REJECT | `test_conflicted_slot_blind_set_rejected` |
| Conflicted slot + declared resolver → ACCEPT (a non-resolver is rejected) | `test_conflicted_slot_declared_resolver_accepted` |
| Stale value + forbidden stale write → REJECT (fresh accepted) | `test_stale_value_forbidden_stale_write_rejected` |
| Invalid state transition → REJECT (valid accepted) | `test_invalid_state_transition_rejected` |
| Undeclared MAP key → REJECT (declared accepted) | `test_undeclared_map_key_rejected` |
| Old policy version → REJECT | `test_old_policy_version_rejected` |
| Duplicate / idempotent proposal | `test_duplicate_and_idempotent_proposal` |
| Valid temporal replacement → ACCEPT / REPLACEMENT | `test_valid_temporal_replacement` |
| Authorization after successful resolution exposes nothing | `test_authorization_after_resolution_exposes_nothing` |

**Also covered:**
- unknown predicate;
- REQUIRES_ESTABLISHMENT;
- the equal-authority CONFLICT flag;
- a lower-authority claim is shadowed, not rejected;
- subject or org mismatch;
- empty interval and future evidence;
- determinism and the absence of a caller parameter;
- TEST_ONLY policies refused by a production registry.

## 5. Genuinely unresolved architectural decisions

These are recorded, not solved. All the governance gates (B1–B4 in `predicate-policy-registry-v1.md`) still stand: every policy here is TEST_ONLY.

| # | Question | Why it matters to the gate | Current prototype behaviour |
|---|---|---|---|
| G-1 | **Should evidence that arrives while a slot is CONFLICT be recorded?** §3 forbids a blind SET under CONFLICT. An LLM-extracted user statement made during a conflict is a SET proposal, so it is rejected and that evidence never becomes a claim | It may be the very statement that resolves the conflict | Rejected. The alternative is to record it as a claim without a write effect. That is a contract-owner question about whether assertions are "operations" |
| G-2 | **Granularity of the conflict prediction.** The flag compares the proposal to the current winner's **source class**. The resolver's independence rule works per source **member** | Two users (different members, same class) are not flagged by the gate but do CONFLICT at resolution | The gate's flag is advisory; resolution remains authoritative. Member-level prediction needs the winner's member in the result contract (§11 provenance) |
| G-3 | **Temporal admission rules beyond well-formedness.** The contract defines bitemporal semantics but no admission limits: retroactive bounds, how far into the future planned values may go, and per-`temporal_model` rules | The gate enforces only a non-empty interval and no future evidence | Lane A's future-marker handling lives in its own extraction gate; it was not duplicated here |
| G-4 | **The idempotency ledger's durability and scope** (per subject? per org? retention?) | Correct replay across processes needs a durable ledger | An in-memory dict. It belongs with commit and storage, which are out of scope |

No production policy value (retention, ownership, authority rank, staleness budget) was created. The TEST_ONLY values exist only to exercise the gate.
