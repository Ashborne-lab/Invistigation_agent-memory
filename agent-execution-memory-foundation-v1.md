# Agent Execution Memory Foundation v1 (visibility-policy-neutral)

**Date:** 2026-10-06.

**Classification:** TARGET ARCHITECTURE specification. Analysis only: no code, test, schema, contract or production change.

**Builds on:** `agent-execution-memory-scope-v1.md` (Model E, customer partition) and `agent-execution-memory-scope-owner-decision-v1.md`.

**Labels:**
- [CONTRACT]: `artifacts/architecture-contract.md`;
- [JOURNAL]: `durable-journal-rebuild-contract-v1.md` v1.1 + A1;
- [CODE]: the prototype at the paths cited, read-only;
- [SPEC]: what this document specifies;
- [CONTRACT_GAP];
- [OWNER DECISION REQUIRED].

**VISIBILITY_POLICY = CUSTOMER_SHARED** (owner decision, 2026-10-06, recorded in §K). **Commitment events follow the same rule.** AGENT_PRIVATE is the rejected alternative and is not implemented.

**Implementation:** tests only. The selected policy is the retrieval layer's existing behaviour, so no production or prototype module changed (§H). Tests: `tests/test_execution_memory_visibility.py`.

---

## A. Object model

| Layer | Existing class | What it holds | Authority | Durable home |
|---|---|---|---|---|
| Raw execution evidence | **Evidence** [CONTRACT §1: "a trusted tool observation, a system observation, an agent decision"] | One record per tool invocation, tool result, agent decision, retry or fallback, failure, outcome | Immutable record; **not truth** | Evidence store ([GAP-1]: E-5 durability is owner-blocked) |
| Episode generation | **Durable fact `episode_summary`** [JOURNAL A1, row 11] | One recorded summarisation of one execution episode: member evidence ids, usable members, generator version, summary, merge ids, classes [CODE `episode_commitment.EpisodeGeneration`] | Authoritative **as a record**; replayed, never regenerated | Journal, the customer subject's partition |
| Narrative Memory episode | **Narrative Memory** [CONTRACT §1, Patch 9] | The served view of the latest generation, with a derived `summary_status` | **Non-assertive**: "MUST NOT establish Current State, override Claims, establish authority" | Derived at read time from the journal |
| Claims (where applicable) | **Claim** | Facts about the **external or customer world** observed by a **trusted** tool (for example a resource's status), under a Predicate Policy | Per policy authority domain | Journal (claim entries) |
| Commitment events (where applicable) | **Commitment event** [JOURNAL A1, row 10] | A promise the agent made (create, confirm, start, fulfil, cancel, …) | Authoritative event; the head is a projection | Journal |

**No sixth class [SPEC].** Every element of an execution episode (§B) maps to one row above. Nothing remains that the five classes cannot hold without ambiguity, so the contract's "MUST NOT be merged" rule needs no exception.

## B. Execution episode definition

| Raw event | Evidence? | Enters the episode summary as |
|---|---|---|
| Tool invocation (name, target, arguments reference) | **Yes**: the agent's decision to act | "called X" |
| Tool result (success payload reference, status) | **Yes**: a trusted tool observation | "X returned S" |
| Agent decision (choice made, state version it was made against [CONTRACT line 395]) | **Yes** | "decided D" |
| Retry / fallback | **Yes**: each attempt is its own record | "retried X" / "fell back to Y" |
| Failure (error, timeout, refusal) | **Yes** | "X failed with E at t" |
| Successful outcome | **Yes** | "outcome O" |
| Sequence of related actions | No: a **grouping**, not an event | The episode itself |

**Episode [SPEC].**
- An execution episode is the ordered set of execution evidence records produced by **one agent** serving **one customer subject**, sharing **one correlation identity** (the task or turn chain that produced them).
- It is bounded by the first and last member's `observed_at`.
- Membership is decided **deterministically** from the correlation identity. Unlike the conversation episode's observed-time gap (a config value, [UNMEASURED]), no time heuristic is needed.
- **Durable output:** one `EpisodeGeneration` whose `summary` narrates **single past occurrences only**. A generator must not produce generalisations ("X is generally bad", "when X, do Y"); those are procedural, D7 / Decision 1b.

**Telling it apart from conversation episodes [SPEC].**
- An execution episode is distinguished by a **declared execution generator** recorded in the existing `generator_version` field (for example a registered generator family).
- The episode class is resolved from a deterministic generator registry, so A1 is unchanged.
- An explicit class field on the sealed generation would be an additive change to A1's content row. It is **not proposed**, because the version field suffices.

## C. Provenance / attribution

| Field | Required for | Where it exists today | Justification |
|---|---|---|---|
| Customer subject (`subject_id`) | Partition, erasure, read scope | `EpisodeGeneration.subject_id` [CODE] | Partition ownership (§D) |
| Tenant (`tenant_id`) | Tenant isolation, transfer | `EpisodeGeneration.tenant_id` [CODE] | J1/J2: never cross-org |
| Originating agent (`agent_id`) | Attribution only (it gates nothing under CUSTOMER_SHARED) | `EpisodeGeneration.agent_id` [CODE]; `Episode.agent_id` | Must be set by the server-side generator from the Gateway-bound context, never from a caller payload (C-4). No caller-facing write path for execution episodes exists today; this is a requirement on the future generator |
| Session (`session_id`) | Session erasure fence; attribution | On each member Evidence record (Lane A) | Session fence epochs (decision closure S-3) |
| Member evidence ids (`evidence_ids`) | Deterministic reconstruction; dead-evidence filter; audit | [CODE] | Provenance [CONTRACT] |
| Usable members (`active_at_generation`) | Regeneration identity | [CODE] | A1 generation key |
| Episode boundaries (`started_at`, `ended_at`) | Valid window; recency ranking | [CODE] | Narrative Memory fields [CONTRACT §1] |
| Correlation / trace identity | Deterministic membership | **Not a generation field.** It is carried on member Evidence, and the episode id is derived from it | The episode id must be deterministic; see the derivation below |
| Outcome | Retrieval relevance | Inside `summary` (narrative) and on member Evidence | No separate field: outcome as a structured value would be an assertion (§F) |
| Generator version | Replay identity; episode class | [CODE] | A1 |
| Security / retention class | Read clearance; retention | [CODE] (`TEST_ONLY_*` values) | T-2 (Security floor), B-3 (Legal) are existing owner items |
| Merge ids | Undo / quarantine | [CODE] | Identity decisions (J5) |
| Policy version | **Not required** for narrative (no policy evaluates it) | — | Claims carry their own policy version (§F path) |

**Episode identity [SPEC].** `episode_id` = keyed hash of (subject key, `"exec"`, agent id, correlation id), following the existing `ep|v1|agent|first_evidence_id` construction (`ids._h`). This makes it deterministic and unlinkable after crypto-shred.

## D. Durability (journal v1.1 + A1, unchanged)

| Property | Verification |
|---|---|
| Partition ownership | The `episode_summary` entry goes to the episode subject's partition [JOURNAL row `episode_summary`]; identity-less generations are refused (`identity_required`) [CODE] |
| Ordering | O1 per partition; journal-assigned commit time (X-1) |
| Replay | Recorded-outcome replay: the same inputs give DUPLICATE with the recorded text (`generation_idem`) [CODE] |
| Rebuild | `generations` are part of the checkpoint fold and of the canonical state signature (compaction v1); `reconstruct` serves the latest generation per episode |
| Erasure | Partition erasure entry (fence) plus key destruction; `_visible` returns nothing for an erased partition, and nothing for a destroyed-key payload [CODE] |
| Crash / recovery | S1–S5 on both reference stores and on PostgreSQL (C-5 v1): an acknowledged generation is durable; a crashed un-acknowledged one is retried idempotently by its input key |
| Checkpoints | Already covered: a generation in the suffix is folded; validated checkpoints carry `generations` (full and compact encodings) |

**No journal contract change [SPEC].** The only durability dependency outside the journal is raw Evidence (**[GAP-1]**, E-5, an existing owner item).

## E. Retrieval

**Path:** Durable Journal → `search_memory` (Typed Retrieval) → Context Compiler. No new operation.

| Aspect | Specification |
|---|---|
| Retrieval type | `NARRATIVE` (existing). Execution episodes are narrative items whose generator family marks them as execution |
| Provenance | `provenance` = member evidence ids (references only), as today. The originating agent stays on the stored generation (`agent_id`). It is **not** added to the narrative `MemoryItem`: CUSTOMER_SHARED does not need it, and the earlier [SPEC] suggestion to put it in `source` is withdrawn as not required by the decision |
| Authority label | `usage = HISTORICAL` and status `NARRATIVE` (existing). Never `CURRENT_STATE` |
| Eligibility | `summary_status == ok`; no dead member evidence; the caller passes `may_read(caller, ("CUSTOMER", X), class)`. There is **no agent filter** (CUSTOMER_SHARED) |
| Relevance | Existing deterministic ranking: query-token overlap, then recency (`started_at`), then episode id. No vectors (MAD §G.3 trigger unmet) |
| Volume control | One episode per correlation id; latest generation only; `limit`; compiler budget |
| Context compilation | Placed in the existing section "Narrative context (background only; not authoritative)". The compiler already refuses narrative with any usage other than `HISTORICAL` (`narrative_claims_authority`) [CODE]. Optional by default; mandatory only if a task profile says so (X-2) |
| Distinguishable from Claims | Different retrieval type, section, label and usage; it never appears in current-state results |

## F. Claim-Gate boundary

**The boundary [SPEC + CODE].**
1. Execution evidence enters the evidence store. It is not a Claim.
2. The execution generator writes an `episode_summary` journal entry. That kind is **not consumed by the claim projection** [JOURNAL rows 10–11: "Not consumed by the claim projection"].
3. Narrative Memory "MUST NOT establish Current State, override Claims, establish authority" [CONTRACT §1].
4. No path exists from `EpisodeGeneration` to the Claim Gate: the gate takes proposals from extraction over Evidence, never from summaries ("from evidence only, never from summaries", S8).

**Required test:** an execution summary stating a world fact must leave every slot and `state_version` unchanged (§J, CG-1/CG-2).

**The legitimate Claim path [SPEC, existing machinery].** A trusted tool observation about the external or customer world (for example "order 123 status = SHIPPED" from the order system) becomes a Claim only through these steps:
- Evidence (the trusted observation);
- extraction proposal;
- the **deterministic Claim Gate** under the predicate's Predicate Policy (an authority domain for that system, for example the contract's `BILLING_SYSTEM`-style domain);
- commit at journal time, with OCC and stamp checks.

The proposal cites the **Evidence**, never the episode. The episode may mention the same fact, non-assertively; the two remain separate objects.

## G. Commitment boundary

| | Commitment | Execution episode |
|---|---|---|
| Object | `commitment_event` (A1 row 10), sealed `commitments.Event` | `episode_summary` (A1 row 11) |
| Identity | `cevent:<event_id>`; `commitment_key` | Generation key |
| Semantics | Authoritative typed transition; the head is a projection | Non-assertive narrative |
| Retrieval | `get_commitments` → section "Commitments" | `search_memory` → narrative section |

**Rule [SPEC].** A promise made during execution is recorded as a commitment event, backed by its own live evidence (`evidence_not_live` refusal otherwise) [CODE]. The execution episode may *mention* it, but a summary never creates, changes or fulfils a commitment. Fulfilment is a separate `fulfil` event backed by outcome evidence.

## H. Authorization boundary (decided)

```text
VISIBILITY_POLICY = CUSTOMER_SHARED          (owner decision 1; §K)
COMMITMENT_VISIBILITY = CUSTOMER_SHARED      (owner decision 2: the same rule)
```

**Rule.** A principal may read customer X's execution episodes, and X's commitments, **if and only if** `may_read(caller, ("CUSTOMER", X), security_class)` holds. That holds whichever agent created them.
- The `Caller` is built by the Gateway from the verified signed handle: principal = the handle's agent; scopes = the handle's subject.
- No request field carries an agent identity.
- An `agent_id` on a record is attribution only; it can neither grant nor restrict access.

| Item | Result |
|---|---|
| Authorization inputs | `Caller.authorized_scopes`, `Caller.cleared_classes` (existing) |
| Retrieval filtering | None beyond `may_read` (existing `search_memory` and `get_commitments` behaviour) |
| Context compilation | Unchanged |
| New authorization capability | **None.** No agent-level grant mechanism was introduced (owner ruling) |
| Code change | **None.** The existing retrieval layer already implements exactly this rule. The owner decision is recorded and pinned by tests (§J) |

**Rejected alternative: AGENT_PRIVATE.** Under it, only the originating agent would read by default, and cross-agent reads would need explicit agent-level grants.
- It is **not implemented** and is not reachable: there is no agent filter, no policy switch and no grant parameter.
- Test RJ-1 checks this, and two mutations (agent filters on narrative and commitments) are caught by the suite.

**Consequences of the decision:**
- Every agent of a tenant that holds a customer's grant sees what other agents did for that customer, including a specialised agent's execution episodes and commitments.
- Erasure stays complete (customer partition).
- There is no orphan problem when an agent is deleted (§I).
- Collaboration needs no extra mechanism.

## I. Erasure / privacy

| Event | Effect on execution memory |
|---|---|
| Customer erasure | The erasure entry fences the partition: no later append; reads return nothing (`_visible` → None). Key destruction makes sealed generations unreadable everywhere the vault reaches. Member Evidence follows the evidence store's erasure (E-5 / C-1) |
| Session erasure | The session fence epoch kills the member evidence. The dead-evidence filter excludes the episode from `search_memory`; regeneration from the surviving members follows the existing `summary_status` rules |
| Evidence withdrawal | Same dead-evidence exclusion |
| Merge undo | Merge-epoch generations are quarantined (existing J5 / Q17 behaviour) |
| Agent deleted / disabled | Records remain: customer-owned, immutable history, attribution only. Under CUSTOMER_SHARED they stay readable by every agent holding the customer's grant. No owner question remains (it existed only under AGENT_PRIVATE) |
| Agent transferred (J6) | Customer partition records follow the person data per J6; `tenant_id` interacts with the transfer rule. No new decision; noted for the implementation brief |

**Storage residue (C-5 v1, E-1).** Row deletion is not unrecoverability on PostgreSQL (heap, WAL, replicas, open snapshots). This applies equally to generations; crypto-shred (C-1) is the existing answer.

**[CONTRACT_GAP] third-party data.** An execution episode, or its member evidence, may contain data about a **third party** (for example the counterpart in a tool result).
- It is stored, retained and erased with the **served customer's** partition.
- The third party's own erasure does not reach it, and no contract rule says whether it must.
- This is the same class of problem as other cross-subject content. It is not solved here and needs the contract owner (with Legal where personal data is involved).

## J. Deterministic test matrix (implemented and run)

**File:** `tests/test_execution_memory_visibility.py`, **57 tests** = 26 store-parameterised scenarios × 2 reference stores (explicit, implied) + 5 store-independent tests. **57/57 pass.**

**Mutation check** (`scratchpad/mutate_xm.py`): **5/5 caught**:
- the rejected AGENT_PRIVATE filter on narrative;
- the same filter on commitments;
- removal of the scope-grant check;
- the projection consuming `episode_summary`;
- removal of dead-evidence exclusion.

| Spec ID | Implemented as | Result |
|---|---|---|
| EC-1…EC-4 | `test_ec1`…`test_ec4` | Pass |
| PV-1, PV-2 | `test_pv1`, `test_pv2` (attribution on the generation, provenance = member evidence) | Pass |
| AT-1 | **Revised:** `test_at1` (no retrieval operation accepts an agent identity) and `test_at2` (a forged handle agent fails signature verification). A write-side "agent from handle" check is **not applicable**: no caller-facing write path for execution episodes exists | Pass |
| PT-1 | `test_pt1` | Pass |
| RT-1…RT-3 | `test_rt1`, `test_rt2_rt3` | Pass |
| CX-1…CX-3 | `test_cx1`…`test_cx3` | Pass |
| CG-1…CG-3 | `test_cg1`…`test_cg3` | Pass |
| CM-1…CM-3 | `test_cm1_cm2_cm3` (create, confirm, a summary saying "fulfilled" changes nothing, a real fulfil event advances the head) | Pass |
| RP-1, RP-2 | `test_rp1` (checkpoint + suffix = full replay), `test_rp2` | Pass |
| ER-1…ER-3 | `test_er1` (for agents A and B), `test_er2_er3` | Pass |
| OA-1 | `test_oa1` | Pass |
| **XA-1** | `test_xa1`: **B reads A's episode** (CUSTOMER_SHARED) | Pass |
| **XA-2** | `test_xa2`: B's context includes it | Pass |
| XA-3 | **Not applicable:** no agent-level grant exists (owner ruling) | — |
| **CM-4** | `test_cm4`: **B reads A's commitment** (decision 2 = YES) | Pass |
| UA-1…UA-3 | `test_ua1` (no grant), `test_ua2` (a subject reference or another customer's or tenant's grant is not authorization), `test_ua3` (attribution confers no access) | Pass |
| RJ-1 (new) | The rejected policy and any agent grant are absent from the retrieval interface and `Caller` | Pass |
| DT-1 | `test_dt1` (byte-identical results, text and manifest) | Pass |

**Regression:**
- full prototype suite **1859 passed** (1802 + 57);
- episode/commitment 82, typed retrieval 32, context compiler 24, Gateway G0 38, Gateway adversarial 109, checkpoint consumers 65, storage boundary 86: all unchanged and passing.

## K. Owner decision (recorded, 2026-10-06)

**Decision 1, execution-memory visibility: OPTION 1, CUSTOMER_SHARED.** Owner wording:
> "If Agent A creates execution memory while serving Customer X, any agent that already has valid (CUSTOMER, X) authorization may read that execution memory. No new agent-level authorization capability is required for this policy."

**Decision 2, commitment visibility: YES.** Owner wording:
> "Commitment Events follow the same customer-shared visibility rule. Therefore, if Agent A creates a commitment for Customer X, another agent with valid (CUSTOMER, X) authorization may read that commitment."

**Additional rulings (applied):**
- AGENT_PRIVATE is not the active policy;
- no agent-level grant mechanism;
- execution memory stays customer-scoped in the CUSTOMER partition;
- the signed Gateway handle and authenticated authorization model remain the source of access control;
- the third-party erasure issue stays unresolved and is not solved here.

This also closes T-1(i) (commitment cross-agent visibility within a tenant) in the customer-shared direction.

**Remaining labelled items:**
- **[CONTRACT_GAP]** Third-party data inside a customer execution episode: whether the third party's erasure must reach it (§I). Explicitly unresolved by owner ruling.
- [GAP-1] Raw Evidence durability → E-5 (existing owner item; not revisited).
- T-2 / B-3 security and retention class values (existing owner items).
- **Requirement on the future execution-episode generator:** it sets `agent_id` from the bound context and never emits generalisations. D7 / Decision 1b remain separate and untouched.

No [OWNER DECISION REQUIRED] remains for visibility. No [BLOCKED] items.
