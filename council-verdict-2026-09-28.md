# Council verdict on the open identity decisions (2026-09-28)

Input: Jay's docket answers ([docket-answers-2026-09-28.md](docket-answers-2026-09-28.md)). Jay asked for a council of at least three Opus 5.5 members.

The council had three members. They worked independently, from the same brief, and none saw the others' output. Each weighted the questions through a different lens:

| Member | Lens |
|---|---|
| A | safety and privacy |
| B | engineering cost against current code |
| C | contract coherence and product |

All three worked read-only. Their briefs forbade reopening any decision Jay had already made.

Classification: everything below is a **TARGET ARCHITECTURE** recommendation. It is not a current-state fact. The exceptions are the items marked **VERIFIED CURRENT** or **CONTRADICTED BY SOURCE**.

## 1. Tally

| # | Question | Votes | Verdict |
|---|---|---|---|
| C1 | Q3 what undo restores | 3/3 on the core, with split details | A proper undo in two tiers (§2) |
| C2 | Q8 P(A)+E(B) record | **3/3** | Weak. It attaches to the channel-supplied subject; the other identifier becomes a non-transitive candidate edge |
| C3 | Q10 MEMORY vs Claims | **3/3** | J4 names the authority domain only. **D1(a) stands**: extractions build Claims |
| C4 | Q12 contract rule | **3/3** | Add a separate in-tenant person-merge rule. Leave the `SAME_AS` mention row untouched, but add a cross-reference to it |
| C5 | D4 key form | **3/3** | An opaque random subject id, plus a mapping keyed by `(org_id, identifier_type, HMAC_org,keyver(normalised id))` |
| C6 | G5 + QF-2 | **3/3** | Option (b): design without aggregate tables and add them later. Identity records are designed now |
| C7 | G8 disposition | 3/3 split by kind, with details differing | Table in §3 |
| C8 | D2 review | **3/3 flag a serious condition** | HMAC per org is correct. Transfer and key rotation require the raw identifier (§4) |
| C9 | Q6 transfer override | 2 yes, 1 conditional | Yes, narrow. **B's precondition goes back to Jay** (§5) |
| C10 | Q2 scorer | **3/3** | A deterministic weighted rule table in code, with a versioned threshold. No LLM on the merge path |

## 2. C1: undo

**Tier 1: exact (unanimous).** Undo guarantees all of the following:
- The pre-merge partition is restored.
- Each member's content is restored to its last state before the merge.
- The Q4 "not the same person" record is written in the same transaction.
- Chained merges that depended on the undone one are undone first, in reverse order.
- The audit lineage is kept.

**Tier 2: content written while the merge was live.** Two options, with a split vote:
- **Quarantine (A, C):** that content is never served and never silently assigned to either member.
- **Best-effort re-derive (B):** re-run extraction over that member's own **user text only**. Assistant text is excluded, because it is the reply-laundering route.

The council recommends **quarantine by default** (2/3). Re-derivation is an optional, costed recovery. **This choice is Jay's.**

**Fail-safe (A and C, not opposed by B).** Any opt-out or "forget me" set during the merge stays on **both** members after undo. Without this, undo would make a person messageable again.

**Never guaranteed (unanimous):**
- replies already sent
- outbound side effects
- exports
- content the LLM blended from both members

History exclusion is split. A and C would exclude stored session turns from the merge epoch from later prompts (P4). B lists that as not guaranteed. The recommendation is to exclude them.

**Minimal write-time mechanism (union of the three votes):**
1. **Never combine member storage (M-A).** The extractor's read-before-write reads only its own member's document ([agent_memory_service.py:276]).
2. **Versioning.** Use B's **copy-on-first-write** snapshot at `versions/{merge_id}`. It is cheaper than A and C's append-every-write versions and is enough for Tier 1.
3. **Attribution tags.** Every write made during the merge epoch carries `(merge_id, session_id, message_id, prompt_view_was_merged)`. The `prompt_view_was_merged` flag is A and C's addition. Without it, quarantine cannot find the versions contaminated through the reply route.
4. **Ordering.** Items 1–3 must exist **before the first automatic merge ships**.

Why this works: today the fact list is regenerated wholesale and overwritten on every turn ([agent_memory_service.py:40-50, :405]), so restore is impossible (spec §8). Versioning at the moment of write removes that cause, and it leaves the LLM's behaviour unchanged.

## 3. C7: disposition of rejected bulk-deletion work

| Kind of work | Disposition | Votes |
|---|---|---|
| Deletion or erasure cascade chunks | Abandon, and write a record containing only opaque ids: scope, generation, kind, count. This is proof that erasure completed | A, B (C: abandon with no record) |
| Content writes or post-turn extraction into an erased scope | Abandon and record. **Never retry**, because a retry resurrects a forgotten person | 3/3 |
| Work already committed externally or visible to a customer (outreach, sends, exports) | Abandon and record, and never re-send | A, C |
| Derived work (projections, summaries, indexes, resolution re-evaluation) | Re-derive once against the current generation. This is a no-op if the scope is gone | 3/3 |
| Writes rejected because a **merge** bumped the generation | Re-target through `merged_into` to the survivor. **Only applies if N10 says a merge bumps the generation** | 3/3 conditional |
| Operator-initiated work (imports, CRUD) | Return the rejection to the caller. Transient faults get 3 attempts, then `FAILED` with a human `/retry` (the `job_dispatcher` precedent) | B |
| New dead-letter queue | **Do not build one.** No consumer exists, and the dormant DLQ drops messages silently | B (A: retries for transient faults only) |

This requires a typed `work_kind` (and bump-cause) property on each queued job. That property does not exist today.

Jay's G8 note was truncated ("id lean towards "), so his exact lean is unknown.

## 4. C8: a serious condition on D2 (unanimous)

An HMAC keyed per org cannot be recomputed without the raw identifier. Two things need that recomputation:
- **J6 transfer**, which re-keys persons under the target org's key.
- **Key rotation**.

Extract entries in `agent_datastores` do not hold the raw identifier ([extract_entry_writer.py:87-94]). The council's options:
- **(a)** An encrypted raw-identifier column in the mapping, with the key held in a per-org KMS and versioned. It must be covered by the erasure cascade. This becomes the most sensitive person field, and it is a new PII store that G5 and Q14 then cover.
- **(b)** Recover the raw identifier through `agent_users`. This entrenches S6: that store is plaintext and readable from the browser. It also misses web chat.
- **(c)** Declare that the key never rotates, and that transfer drops extract rows it cannot recover.

A, B and C all lean towards **(a)**. The choice is Jay's.

Also unanimous: **freeze the normaliser (U2) before any HMAC is computed**. Changing the normaliser changes every key.

## 5. C9: transfer override, and a precondition Jay must answer first

**B's point, which A and C did not contradict.** Resolution runs on every write (Q9, J3). So a subject that arrives by transfer and exactly matches a subject in the target org will merge on its **next write** anyway. That leaves two readings of "don't merge on arrival":
- **(i)** It only means "not at transfer time". The next write merges lazily, and an override adds little.
- **(ii)** It means a durable **transfer fence** on each arrived subject. The fence would reuse the clearable Q4 record, and without it the default leaks within one message.

**Given (ii), the council's majority design is:**
- **Flag:** a boolean `merge_on_arrival` on the transfer-accept call, default false.
- **Who sets it:** only an admin of the receiving org, at acceptance.
- **Scope:** merges may use **channel-supplied exact identifiers only**. Caller-stated evidence from the origin org never enters the target org's scoring (A's rule; this blocks FM5).
- **Audit:** the transfer id, the actor, both orgs, the flag, the policy version, and each resulting `merge_id`. Undo works per merge and per batch.

A's caveat: the override is a second human identity action, and Q4 allowed only one. If Jay holds that Q4 is the only human identity action, then there is no override.

## 6. C10: the scorer (unanimous)

- **Engine.** A deterministic, additive weight table in code. It runs inside the resolver transaction and uses no LLM spend. It meets J3's "purely code" rule and I10's independence from arrival order.
- **Hard vetoes.** A Q4 not-same-person record. An org mismatch. An empty org.
- **Signals:**
  - identifier type
  - source class (channel > operator > caller-typed > STT)
  - whether normalisation parsed
  - **independent** corroboration across sessions, days or channels (contract `:1201`: "repetition cannot manufacture independence")
  - agreement of names
  - the C2 bridge flag
- **Shared-access signals (Q1).** Distinct names per identifier, gaps suggesting a recycled number, role addresses. These are **recorded and never gating**.
- **Merge rules:**
  - A channel-supplied exact match merges immediately, and its score is recorded.
  - A caller-stated exact match merges only at or above the threshold.
  - A bridge record is always weak.
- **Threshold.** A versioned constant in the resolver's repository, changed only through code review. It is not per org and operators cannot set it. Its version is stamped on every merge (I11). Its numeric value is still U3.
- **JEV or judge model.** Not in v1 and never on the hot path. It can never cause a merge, which follows the contract's rules at `:502` and `:1219`. At most it gets two uses: offline calibration of the weights, or an asynchronous, capped signal for pairs just under the threshold.

## 7. Cross-cutting risks (raised by two or more members)

1. **Reply-route contamination (A, C).** Storing each person's data separately does not keep it separate. Under Q5, the prompt reads across members, and the extractor then writes B's facts into A's document through the assistant's reply (read-paths §11.2). Epoch tagging must ship before the first merge.
2. **Q5 fan-out removes the only org boundary on the turn path (B, C).** P1 and P2 are org-safe only because the agent path confines them (read-paths §12.2). Every member fetch needs a per-row org check, following the L3 pattern ([routers/agent_memory.py:587-589]).
3. **Undo must never loosen consent (A, C).** See §2.
4. **Erasure and export through a wrong merge (A).** Under Q14, a "forget me" on a wrongly merged person destroys a third party's data. A subject-access export would disclose that third party's data. The code already admits over-deletion on shared numbers ([core/lead_contacts.py:828-833]). Erasure and export must therefore list the members and `merge_id`s in force at the time.
5. **Silent resolver failures (B).** The W1, W2, W7 and W8 paths swallow exceptions (spec §12.1). Resolution needs a counted failure metric.
6. **The encrypted raw identifier is the new crown jewel (A, B).** It needs its own custody arrangement and its own erasure path.

## 8. Correction: CONTRADICTED BY SOURCE

`person-identity-architecture-research.md` §9.2 (line 590) says `agent_user_memory` documents hold no raw identifier and are not re-keyable. **Source contradicts this.** Both write paths store the plaintext `channel_user_id: user_key` in the document body ([repos/olbrain-agent-runtime/services/agent_memory_service.py:404](../repos/olbrain-agent-runtime/services/agent_memory_service.py#L404) and :473). This was re-verified on the local copy at the pinned SHA daee3f9.

Consequences:
- Memory documents **are** re-keyable from their own body, so their migration is cheap. The hard part of migration is extract entries.
- It adds another store holding a raw identifier in plaintext.

The earlier document was not edited. This correction is recorded here instead.

## 9. Back to Jay (short)

1. **C9 precondition.** Does "don't merge on arrival" mean (i) only "not at transfer time", or (ii) a durable fence? If (ii), is the transfer override an acceptable second human identity action?
2. **C8.** Is an encrypted raw-identifier store in the mapping acceptable? The alternative is that the key never rotates and transfer is lossy.
3. **C1 Tier 2.** Should content written while the merge was live be quarantined (it is lost), or re-derived from user text (at an LLM cost)?
4. **N10.** Does a merge bump the generation? The C7 re-target row depends on it.
5. **G1** is still unanswered.
6. **G8.** Jay's note was cut off. Does the §3 table match his lean?

Everything else in §1 the council settled with no open question left for Jay.

[agent_memory_service.py:276]: ../repos/olbrain-agent-runtime/services/agent_memory_service.py
[agent_memory_service.py:40-50, :405]: ../repos/olbrain-agent-runtime/services/agent_memory_service.py
[extract_entry_writer.py:87-94]: ../repos
[routers/agent_memory.py:587-589]: ../repos
[core/lead_contacts.py:828-833]: ../repos/olbrain-agent-runtime/core/lead_contacts.py
