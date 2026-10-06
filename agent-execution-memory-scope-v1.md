# Agent Execution Memory: Scope and Object Mapping v1

**Date:** 2026-10-05.

**Classification:** TARGET ARCHITECTURE analysis only. Nothing was implemented. No contract, prototype module, schema or API was changed.

**Labels:**
- [CONTRACT]: `artifacts/architecture-contract.md`;
- [OLBRAIN-PROVEN]: an established project artifact;
- [MEMORI]: `memori-agent-memory-gap-analysis-v1.md`, which is evidence only, not authority;
- [INFERENCE];
- [GAP];
- [OWNER DECISION REQUIRED].

**Owner packet:** `agent-execution-memory-scope-owner-decision-v1.md`.

---

## 1. Executive conclusion

**Agent execution memory needs no new object class.**
- **Raw execution is Evidence.** The contract already defines Evidence as including "a trusted tool observation, a system observation, an agent decision" [CONTRACT §1]. A prior agent decision is "an immutable historical event recording the state version and projection against which that decision was made" [CONTRACT §4/§6, line 395].
- **Execution episodes are Narrative Memory.** Narrative Memory explicitly covers "the context surrounding a decision … discussion sequence" and must be non-assertive [CONTRACT §1, Patch 9]. The episode-generation durable home (journal Amendment A1) already records non-deterministic summaries as replayable generations.
- **World state learned through tools stays an ordinary Claim** under a Predicate Policy (for example a trusted-system authority domain such as the contract's `BILLING_SYSTEM`).
- **Promised actions stay commitment events.**

The recommended model is therefore **Model E (existing objects with attribution metadata), stored in the CUSTOMER subject's partition**.

**The one decision engineering cannot make is visibility.** May agent B read the execution memory produced while agent A served the same customer, and is an agent-private layer required?
- The contract separates scope from access: "Security visibility is determined by authorization grants, never by automatic scope inheritance" [CONTRACT §2].
- The prototype has only `(CUSTOMER, subject)` grants [OLBRAIN-PROVEN, `may_read`].
- The grant model for AGENT, SESSION and TENANT reads, including the directly analogous question "may a different agent of the same tenant read a commitment made by agent A to this person", is a recorded **Security, with Product** owner item [OLBRAIN-PROVEN, `target-architecture-decision-closure-v1.md` S-3 / T-1 / T-5 rows and item 5].

**The verdict is OWNER DECISION REQUIRED.** The object mapping, partition placement, lifecycle and retrieval route are engineering. The cross-agent visibility rule is the owner question.

**Two concrete gaps are isolated, not solved:**
- **[GAP-1]** The durable home of raw Evidence is the evidence store, whose acknowledgement durability is owner-blocked (E-5). Execution memory inherits that dependency.
- **[GAP-2]** Execution with **no customer subject** (an agent operating on resources, a workflow, an internal job) has no durable partition in journal v1.1. Partitions are subject partitions, and AGENT / RESOURCE / WORKSPACE deletion generations do not exist yet (decision closure S-3). It stays out of scope.

## 2. Precise capability definition

**Agent execution memory** is durable, retrievable knowledge of **what an agent, process or workflow actually did, and what happened as a result**, as historical fact about past execution. It covers:
- a tool or API invocation and its result (success, error, timeout);
- a decision the agent took (and the state version it was taken against);
- an attempted action and its outcome;
- a retry, a fallback, a recovery;
- an **execution episode**: an ordered account of one task's attempts and outcomes.

**It is not:**
- user preferences or declarative customer facts (Claims under existing predicates);
- any **generalised** rule or heuristic ("when X, do Y"; "X is generally bad");
- `agent_learned_patterns`;
- `ExceptionPattern`.

The last three are procedural memory: **Decision 1b / D7, explicitly separate (§15).**

**The boundary, as a rule:** an execution memory item is about **one past occurrence**, with a time, an actor and an outcome. Anything quantified over occurrences ("always", "usually", "generally", "when … then …") is procedural.

## 3. Existing-object mapping

| Option | Fit for execution memory | Provenance | Authority | Temporal | Lifecycle | Erasure | Replay | Retrieval | Authorization | Cross-agent | Storage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **A. Raw Evidence only** | **Required base.** Tool observations and agent decisions *are* Evidence [CONTRACT §1] | Is itself provenance | Not truth ("Evidence does not automatically mean truth") | `observed_at`; immutable | Append-only; withdrawal is a lifecycle change (E-2) | Per subject erasure; crypto-shred (C-1) | Immutable input | **No typed operation reads raw Evidence**, which is deliberate (payloads can be large or sensitive) | Via the evidence-store boundary (E-5 open) | Only via derived objects | Evidence store [GAP-1] |
| **B. Claim** | **Only for world state**, e.g. `order.status = SHIPPED` observed through a trusted tool. **Not** for "the agent called X": that is not an assertion about the subject's current state | Evidence ids | Per Predicate Policy authority domain | Bitemporal | Claim lifecycle | Subject partition | Journal fact | Current state / history | `(CUSTOMER, subject)` | Same as any claim | Journal |
| **C. Episode summary (Narrative Memory)** | **Fits execution episodes**: the "context surrounding a decision … discussion sequence" [CONTRACT §1] | Member evidence ids + generator version (A1) | **Non-assertive**: "MUST NOT establish Current State, override Claims, establish authority" | Generations; latest wins | `summary_status` (quarantine, regenerate-pending) | Subject partition; dead-evidence filter | Recorded generation, replayed as recorded (A1) | `search_memory` (deterministic), context | `(CUSTOMER, subject)` today | Through grants | Journal `episode_summary` kind |
| **D. Commitment event** | **Only for promised actions** (create → fulfil / cancel) | Evidence-backed | Authoritative event; head is a projection | Typed transitions | Cancel / reopen | Subject partition | Journal fact | `get_commitments` | T-1 open | T-1 is the same open question | Journal `commitment_event` kind |
| **E. New object class** | Not needed (A–D cover every item in §2). Would breach "five classes MUST NOT be merged / overlap" [CONTRACT §1] without a demonstrated requirement | — | — | — | — | — | — | — | — | — | — |
| **F. Combination (A + C, with B and D where they already apply)** | **Recommended mapping** | — | — | — | — | — | — | — | — | — | — |

**A required derivation distinction [OLBRAIN-PROVEN constraint].**
- Today's episode generator summarises "from USER, active evidence only" (`durable-home-episodes-commitments-decision-v1.md` S8). That restriction exists to keep assistant output out of *customer facts* (the assistant-reply contamination defect).
- An **execution-episode generator** would read *trusted tool observations and agent decisions*: a different, explicitly declared member set with its own generator version (A1 already keys generations by generator version).
- It must remain non-assertive, and it must never feed the Claim Gate. That keeps the invariant "LLM interpretation may propose, never silently becomes truth".

## 4. Scope analysis

The scope vocabulary is from the contract: GLOBAL, TENANT, WORKSPACE, CUSTOMER, SESSION, AGENT, RESOURCE. Two rules apply throughout:
- scope is assigned at commit from ingress context, never inferred from the value (decision closure S-3);
- access is a separate grant per (principal, scope id).

| # | Question | CUSTOMER | AGENT | SESSION | WORKSPACE | RESOURCE | GLOBAL |
|---|---|---|---|---|---|---|---|
| 1 | Owner | The customer subject's partition, within its tenant | The agent (within its tenant) | The session (within subject and agent) | The workspace | The resource | Platform |
| 2 | Readers | Principals with a `(CUSTOMER, subject)` grant: **exists today** | **No grant model** | **No grant model** (SESSION scope unsupported, S-3) | No grant model | No grant model | No grant model |
| 3 | Contributors | Any agent bound to the subject by a signed handle | That agent | That session's agent | — | — | — |
| 4 | Consumers | Per grant **[OWNER]** | Per grant **[OWNER]** | Per grant **[OWNER]** | — | — | — |
| 5 | Cross sessions | Yes | Yes | **No** | Yes | Yes | Yes |
| 6 | Cross agents | **Only if granted [OWNER]** | No (by definition) | No | Yes | Yes | Yes |
| 7 | Cross customers | **No** (partition = subject; tenant boundary J1/J2) | **Yes**: an agent serves many customers. A **privacy hazard**: customer content would aggregate outside the customer's partition | No | Yes (hazard) | Possibly (hazard) | Yes (hazard; G5 aggregates parked) |
| 8 | Authorization | Gateway handle → `may_read` `(CUSTOMER, subject)` | **[OWNER] new capability** | **[OWNER] new capability** | [OWNER] | [OWNER] | [OWNER] |
| 9 | Metadata or boundary? | **Authority boundary** for storage and erasure; read visibility is still a grant | Today, metadata only (`agent_id` attribution) | Metadata (`session_id`) | — | — | — |
| 10 | Originating agent deleted / disabled | Records remain: Evidence is immutable and attribution is history. Transfer follows J6 (person data follows the agent), a known interaction (§10 S6) | Orphaned scope: needs a rule **[GAP]** | As AGENT | — | — | — |
| 11 | Originating session erased | Session-level deletion generation (Lane A `session` epoch → SESSION, decision closure S-3) fences the session's evidence; derived episodes are quarantined by the dead-evidence filter | — | The scope itself is erased | — | — | — |
| 12 | Customer erased | **Covered**: partition erasure plus crypto-shred covers every record (journal §F) | **Not covered**: customer content inside an AGENT partition needs cross-partition erasure **[GAP]** | Covered if nested under the subject | Not covered | Not covered | Not covered |

**Attribution is not authorization.** `agent_id`, `session_id` and `subject_id` on an execution record are **attribution metadata**. They never grant access:
- C-4: a subject reference alone is never authority;
- reads go through a signed handle bound to (org, agent, session, subject);
- causal tokens are Gateway-signed (GW-G3).

No identifier in any model below becomes a bearer credential.

## 5. Candidate models

| Model | Description | Uses existing grants? | Customer erasure | Private-agent safety | Collaboration |
|---|---|---|---|---|---|
| **A. CUSTOMER-scoped** | Every permitted agent for the customer contributes and retrieves | **Yes** (`(CUSTOMER, subject)`) | Covered | **Weak**: a specialised agent's execution is visible to any agent bound to the same customer | Good |
| **B. AGENT-scoped** | Execution belongs to the agent and is not shared | **No**: needs AGENT grants [OWNER] | **Not covered** if stored in an agent partition [GAP]; covered if stored in the customer partition and only *visibility* is agent-restricted | Strong | Poor |
| **C. CUSTOMER + AGENT layered** | Customer-visible layer plus an agent-private layer | Partly: the private layer needs a per-(agent, subject) read restriction [OWNER] | Covered **if both layers live in the customer partition** | Strong | Good |
| **D. SESSION-only** | Exists only inside the originating session unless promoted | No: SESSION grants [OWNER]; promotion rule [OWNER] | Covered (nested) | Strong | Poor; loses cross-session value, which is the point of the capability |
| **E. Existing objects + attribution metadata** | Evidence + execution episodes (+ Claims and commitments where they already apply), carrying `agent_id`, `session_id`, `subject_id`, in the **customer partition** | Yes, for storage and for Model-A visibility; other visibility rules need grants | Covered | Depends on the visibility rule chosen | Depends on the visibility rule chosen |

**[INFERENCE]**
- Models A–D mix two orthogonal choices: the **object and storage model** and the **visibility rule**.
- Model E fixes the first, using existing objects in the customer partition, and leaves the second as a grant policy. That is exactly how the contract separates them [CONTRACT §2].
- The owner packet therefore asks only the visibility question.

## 6. Lifecycle (recommended: Model E)

```text
execution begins (Gateway-bound turn: org, agent, session, subject)
   │
   ▼  tool / action observation .................. SYNC   capture; Evidence (append-only)   AUTHORITATIVE as a record, not as truth
   ▼  execution event = that Evidence ............ (no separate object)
   ▼  world-state facts from TRUSTED tools ....... ASYNC  Claim Gate (deterministic) → commit   AUTHORITATIVE (Claims), only per policy
   ▼  optional execution-episode aggregation ..... ASYNC  LLM generator, declared member set     DERIVED, non-assertive; generation recorded (A1)
   ▼  durable commit ............................. journal: episode_summary generation; Claims; commitment events
   ▼  retrieval eligibility ...................... summary_status = ok; evidence live; grant permits the caller
   ▼  future consumption ......................... Context Compiler: budgeted, labelled non-assertive, optional
   ▼  retraction / invalidation / erasure ........ evidence withdrawal or session/customer fence → dead-evidence filter quarantines
                                                   the generation; erasure covers the partition
```

**The invariant holds at two points:**
1. The execution-episode generator's output is Narrative Memory. It can never establish Current State, override a Claim or serve as authorization evidence [CONTRACT §1].
2. Claims about world state come only from trusted tool observations through the deterministic gate and a Predicate Policy, never from the episode text.

## 7. Retrieval semantics

| Path | Execution memory appears as | Notes |
|---|---|---|
| Current state | **Only** ordinary Claims from trusted tool observations (for example a resource status) | Not "what the agent did" |
| History | The history of those Claims, and commitment transitions | Unchanged |
| Narrative (`search_memory`) | **Execution episodes**, labelled non-assertive, carrying agent and session attribution | No new operation. [INFERENCE] A result attribute telling execution episodes apart from conversation episodes is a field, not an API. It belongs to a future implementation brief |
| Context compilation | Optional section, under the task profile's budget (X-2 mandatory-state policy) | Never mandatory by default |

**Answers to the brief:**
- **Raw execution events are not directly retrievable.** There is no typed Evidence-read operation, and raw tool payloads may contain third-party or sensitive content. They are reached through episodes, with evidence ids in the manifest for audit.
- **Episode summaries are retrievable.** Claims are retrievable where a trusted tool observed world state.
- **Execution memory is optional context.**
- **Relevance:** same subject, then recency of the episode, then deterministic token match on the task. No vectors; the MAD §G.3 trigger still governs.
- **Bounding volume:**
  - one episode per task segment (aggregation);
  - the latest generation only;
  - the compiler budget and manifest;
  - quarantine of episodes with dead evidence.

  Old raw details never enter context directly.

## 8. Security analysis

| Property | Preserved by |
|---|---|
| Tenant isolation | Records in the customer partition; subject ids are tenant-scoped (C5/C6); never cross-org (J1/J2) |
| Customer boundary | Partition = subject; a foreign-subject claim in a partition is never served as that subject's history (checkpoint consumers test) |
| Signed Gateway handles | All reads and writes go through bound handles (C-4) |
| Non-bearer subject references | Unchanged: identifiers are attribution only |
| Agent and session attribution | Recorded on Evidence and generations (the `agent_id` field already exists on Episode, S6) |
| Authorization outside truth resolution | Resolution under policy first, authorization second (Gateway contract, existing) |

**Does any proposed scope require a new authorization capability?**
- Model A visibility (any agent with a `(CUSTOMER, subject)` grant): **no**.
- An agent-private layer (B / C), session-only visibility (D), or any non-customer scope: **yes, [OWNER DECISION REQUIRED]**. This is the grant model for AGENT, SESSION and TENANT reads, already recorded for Security, with Product.

No authorization mechanism is designed here.

## 9. Durable Journal compatibility

| Aspect | With Model E in the customer partition |
|---|---|
| Partition ownership | Customer subject partition: **unchanged** |
| Ordering | O1 per partition: unchanged |
| Commit time | Journal-assigned (X-1): unchanged |
| Valid time | `observed_at` of the tool result for Evidence; the generation's own time for episodes |
| Causality | Causal tokens: unchanged |
| Replay | Generations replay as recorded (A1): unchanged |
| Erasure | Partition erasure plus crypto-shred covers it; the dead-evidence filter covers withdrawn evidence |
| Checkpointing | `generations` are already in the checkpoint fold and the canonical signature: unchanged |
| Idempotency | Tool call / observation ids as evidence ids; generation key = (episode id, members, usable members, generator version) |
| Cross-subject behaviour | A record about a **third party** stays in the partition of the subject the execution served. It is never re-attributed implicitly (§10 S5) |

**Result:** compatible with journal v1.1 + A1. **No contract change** for customer-scoped execution memory.

**Gaps recorded, not solved:**
- **[GAP-1]** Raw Evidence durability is the evidence store's, and E-5 is owner-blocked.
- **[GAP-2]** Executions with no customer subject would need non-subject partitions plus AGENT / RESOURCE / WORKSPACE deletion generations (decision closure S-3: "still have to be added"). That would be a journal and erasure change, and it is out of scope here.
- **[GAP-3]** The **execution-episode generator** (member-selection rule over tool and decision evidence) is a new derivation inside A1's existing kind. Its definition belongs to a future engineering brief; it needs no contract amendment [INFERENCE: A1 already keys generations by generator version and member sets].

## 10. Multi-agent sharing analysis

| Scenario | Answer under Model E | Contract basis |
|---|---|---|
| **S1.** Agent A's tool call succeeds. Can agent B benefit? | **World state:** yes, through Claims, if a trusted tool observed it under a policy. Any agent with a `(CUSTOMER, subject)` grant reads Claims. **"A did it" (the episode):** only if the visibility rule allows **[OWNER]** | §1 Evidence → Claim; §2 grants |
| **S2.** A's execution holds customer-specific data. Can B access it? | Only with a grant for that customer. Then access is to the **episode** (non-assertive), not to raw evidence. Whether a grant for the customer suffices across agents is the owner question | §2: "visibility … by authorization grants, never by automatic scope inheritance" |
| **S3.** A is specialised / private. Can its history leak into B's context? | **Under Model A visibility, yes, for the shared customer.** Preventing that needs an agent-private restriction (Model C), which is **[OWNER]** | §2; decision closure T-1(i) |
| **S4.** Two agents collaborate on one customer task | Safe under Model A visibility, or a declared collaboration grant (C). Both write into the same partition with OCC on any mutable slot; episodes are non-assertive, so no write conflict exists on them | §2 OCC; A1 |
| **S5.** An execution record holds evidence about a third party | It **stays in the served customer's partition** with that customer's retention and erasure. Re-attribution to the third party is never implicit. Third-party erasure is not reached by the third party's own partition erasure **[GAP-4]**. This is the same class of problem as the existing cross-subject cases (merge-landed claims use an explicit intent protocol), and it is not solved here | Journal §C/§F; identity decisions |

**[INFERENCE] S6, transfer.** J6 says person data follows the agent on transfer. Execution episodes about a customer, held in that customer's partition, would move with the person data under J6. Execution content that is agent-specific has no rule. This interacts with the visibility decision and is noted in the packet.

## 11. Failure and negative outcomes

| Outcome | Durable? | Retrievable as | Note |
|---|---|---|---|
| Failed API or tool call | Yes (Evidence) | Execution episode | "X failed at t, with error E": a single occurrence |
| Rejected action (policy or gate refusal) | Yes (Gateway outcome entries already record terminal outcomes: STATE_CONFLICT, STALE_POLICY_STAMP, GATE_REFUSED) | Episode; the outcome entry is already journalled | Existing `commit_outcome` kind |
| Timeout | Yes (Evidence) | Episode | |
| Retry | Yes, each attempt as Evidence; transient READ_CLOSED retries are infrastructure, not memory | Episode, aggregated | |
| Fallback | Yes | Episode | |
| Successful recovery | Yes | Episode | |

- **"X failed once"** (or n times, with times) is **execution memory**: a fact about past occurrences, reportable as such in an episode.
- **"X is generally bad"** / **"when X returns 429, use Y"** is a **generalisation**. It is procedural (D7 / Decision 1b), and it must not be produced, stored or presented by the execution-episode generator. A generator instruction to that effect is a requirement for the future engineering brief.
- Retrieval must also not present a recalled failure as a rule. The episode is labelled non-assertive, about a past occurrence [CONTRACT §1 Narrative Memory].

## 12. Recommended model

**Model E, in the customer partition, with Model-A visibility as the default:** any agent principal holding a `(CUSTOMER, subject)` grant for that tenant's customer may read execution episodes.

**Reasons:**
1. **No new object class:** every item in §2 maps to Evidence, Narrative Memory, Claim or commitment [CONTRACT §1].
2. **No new authorization capability:** existing signed handles and `(CUSTOMER, subject)` grants suffice.
3. **Erasure is complete** by construction (the customer partition), which no AGENT-partition model gives [GAP-2].
4. **Consistent with J1/J2:** one person across an org's agents, never across orgs.
5. **The journal contract is unchanged** (§9).

**The cost:** a specialised agent's execution episodes for a customer are visible to other agents serving that customer (S3). Whether that is acceptable is the owner question. If not, the upgrade is Model C (an agent-private restriction inside the same partition), which needs the AGENT grant model. Executions with no customer subject stay out of scope [GAP-2].

## 13. Owner decision required

See `agent-execution-memory-scope-owner-decision-v1.md`.

- **Question:** the cross-agent visibility of customer-scoped execution memory, plus whether an agent-private layer is required.
- **Recorded owner:** Security, with Product (decision closure v1, the grant model for non-CUSTOMER reads, item 5).
- **Joint answer:** it should be answered together with T-1(i) (commitment visibility across agents), which is the same question for commitments.

## 14. Explicit non-goals

- Procedural / heuristic memory, `agent_learned_patterns`, `ExceptionPattern`, Decision 1b, D7.
- Executions with no customer subject (AGENT / RESOURCE / WORKSPACE partitions) [GAP-2].
- A new object class, a new retrieval API, a new journal kind, vector or graph search.
- Designing the grant mechanism; defining the execution-episode generator; schema; code.
- Production `agent_traces` (counters only; bodies in Cloud Logging, R-7) and `mcp_tool_executions`: current-state stores, not mapped here.

## 15. Relationship to Decision 1b / D7

```text
Agent called API X → X returned 429 → agent used API Y → Y succeeded
    = EXECUTION / EPISODIC MEMORY: Evidence + an execution episode; this workstream

"When X returns 429, always use Y"
    = PROCEDURAL / GENERALISED STRATEGY: Decision 1b / D7; NOT this workstream
```

This document neither resolves nor reopens D7. It only fixes the boundary:
- execution memory describes single past occurrences;
- anything quantified over occurrences is procedural.

The execution-episode generator must not produce procedural content (§11).

AGENT EXECUTION MEMORY SCOPE V1 — OWNER DECISION REQUIRED
