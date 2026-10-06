# Durable Journal and Rebuild Contract v1.1 (technology-neutral)

**Date:** 2026-10-03 (v1). **v1.1:** 2026-10-04.

**Status:** prototype-proven requirements for durable storage. **No storage technology, key custody, retention value or other owner decision is made here.**

**v1.1 changes** (time and storage boundary only; everything else is v1 unchanged):
- commit time is owned by the journal and means knowledge time (Part 0);
- served-prefix immutability is the normative invariant, with closure rules (§B);
- the storage boundary S1–S5 (Part 3), proven against an explicit-frontier and an implied-frontier store.

**Amendment A1 (2026-10-04, additive):** commitment events and episode generations become journal facts (Part 1 rows 10–11; §A). No existing rule or kind changes.

The basis is `durable-journal-x1-decision-v1.md` and `durable-journal-contract-v1.1-implementation-report.md`.

**Executable form:**
- `memory-prototype/memory_core/durable_journal/__init__.py`, containing:
  - the interface and shared append rules;
  - implementation **A** `GlobalJournal`, today's single global order;
  - implementation **B** `PartitionedJournal`, the adversarial simulator;
  - `reconstruct` and `evaluation_order`;
  - `protocol_commit` and `erase_person`;
- `memory-prototype/tests/test_durable_journal_conformance.py`: **144 tests**;
- v1.1, the time model: `memory_core/commit_time/` with `tests/test_x1_commit_time.py` (**64 tests**);
- v1.1, the storage boundary: `memory_core/storage_boundary/`, with the `ExplicitFrontierStore` and `ImpliedFrontierStore` reference implementations and `tests/test_durable_storage_boundary.py` (**78 tests**, one suite run unchanged against both).

**Full prototype suite: 1047/1047** (v1: 905).
- The v1 conformance tests construct fully timed entries through `load()`. In v1.1 they are **storage-level replay tests**: storage receives fully timed entries. They are valid as written.

**Evidence labels:**

| Label | Meaning |
|---|---|
| [PROVEN] | By test or mutation |
| [INFERENCE] | Engineering inference |
| [OWNER] | Owner decision |
| [STATED] | Requirement stated and its violation demonstrated, but not enforced by the simulator |
| [CONTRACT_GAP] | An ambiguity in this contract; must be resolved by its owner |

---

## Part 0. Time (v1.1)

| # | Rule |
|---|---|
| **K1. Ownership** | The **journal layer** assigns the commit time of every entry (`at`) and every publication (`T`) inside the commit step. A writer, gate, agent or caller never supplies it. A store may supply the value only as an implementation of K3–K6 |
| **K2. Meaning** | Commit time is OLBrain's **knowledge time**, on the same physical axis as valid time. The record's `committed_at` **equals** the entry's `at`: the record is built inside the commit step, after the time is drawn and before the entry is durable. Nothing is rewritten after commit |
| **K3. Accuracy** | `at` ≥ the clock of whatever draws it. A partition's closed position never runs ahead of that clock or of an already-assigned time carried as a causal token. A policy log's closure may run ahead (a lease), so publications take effect later. History stability does not depend on clock accuracy; the moment a validity boundary activates does. The clock source and its tolerance are [OWNER] |
| **K10. Ties** | Entries precede publications at equal time (determinism). Under §B closure, the journal never gives an entry and a publication **of the same predicate** the same time |

**The five time concepts**, never interchangeable:

| Concept | Assigned by |
|---|---|
| Observation time (`observed_at`, `synced_at`, `effective_at`) | Source or writer, as payload |
| Valid time (`valid_from`, `valid_until`) | Writer or gate, as payload |
| Commit / knowledge time (`at` = `committed_at`, `T`) | The journal (K1) |
| Logical position (position within a partition, version within a policy log, `idem`) | The journal; the writer supplies `idem` |
| Read position r | The journal, returned with every served result (K7) |

---

## Part 1. Durable-fact model

| # | Item | Class | Notes |
|---|---|---|---|
| 1 | Claim (immutable content plus commit record) | **Durable fact**, sealed | Content sealed under the owning subject's key id |
| 2 | Lifecycle transition (claim id, `Transition`) | **Durable fact** | Carries no value |
| 3 | Retraction record | **Durable fact**, sealed | Carries the retracted value |
| 4 | Policy publication (predicate, version, T) | **Durable fact** (policy log) | The policy *content* is configuration (policy history, immutable per version) |
| 5 | Sync success (subject, predicate, source, `synced_at`) | **Durable fact** | The only basis of external freshness (C-C) |
| 6 | Erasure entry (cluster) | **Durable fact** | Seals the partition. Key destruction follows it |
| 7 | Commit outcome / intent (ledger) | **Durable fact** | The intent is sealed; the outcome carries no value |
| 8 | Evidence and its status | **Durable fact** (evidence store) | Claims reference evidence ids in their sealed anchor |
| 9 | Subject key ids | **Durable fact** (reference) | Custody is C-1 [OWNER] |
| 10 (A1) | Commitment event (red-team M-2, C-E) | **Durable fact**, sealed | The head is a projection (`commitments.project`). Not consumed by the claim projection |
| 11 (A1) | Episode generation (a recorded summarisation: membership, usable inputs, generator version, summary, merge ids, classes) | **Durable fact**, sealed | Narrative Memory, non-assertive (contract §1). `summary_status` is derived. Not consumed by the claim projection |
| — | Merge links (`merged_into`), undone merges, erased-subject times | **Durable fact** of the identity layer (Lane A identity events) | Consumed by the gate and fence at commit time; recorded in outcomes. Not re-read by rebuild |
| — | Policy content per version | **Policy / configuration** | Immutable once published |
| — | Current state, `state_version`, freshness status, usage, history labels, revalidation status, retrieval results, compiled context | **Derived projection** | Never stored as truth. **Verified:** `reconstruct` computes all of them from facts alone, and a deleted pipeline does not matter (test `rebuild_uses_durable_facts_only…`) [PROVEN] |
| — | A persisted head or slot | **Cache** | Allowed only if it equals `reconstruct` at the same read time |
| — | **Requested** read time, caller, task profile, budget | **Caller input** | The caller affects visibility only (Property 3) [PROVEN] |
| — | **Served** read position r | **Assigned by the journal** (K5, K7) and returned with every result | |

---

## Part 2. The contract

### A. Entry model

All entries are immutable. Every entry belongs to **exactly one partition**: the owning subject.

| Kind | Owner partition | Idempotency identity | Causal / evaluation position | Replay payload | Participates in rebuild |
|---|---|---|---|---|---|
| `claim` | The **target** subject: the survivor after a merge | `claim:<claim_id>`; the claim id is deterministic (C-1 function) | Commit time **assigned by the journal** (K1, K2); position; O3 stamp **checked at that time** (K9) | Sealed commit record (content, provenance) | Yes |
| `retraction` | The retraction's subject | `retraction:<id>` | Commit time; O3 stamp | Sealed `RetractionRecord` | Yes (LA-9, including claims committed later) |
| `lifecycle` | The claim's partition | `lifecycle:<claim>:<t>:<to>` | Commit time; O3 stamp | (claim id, transition) | Yes |
| `sync` | The subject | `sync:<sync_id>` | Commit time | `SyncRecord` | Yes (freshness only) |
| `erasure` | **Every** partition of the merge cluster | `erasure:<cluster>` | Commit time | Cluster | Yes: the partition becomes ERASED |
| `commit_intent` | The **proposal's** subject | `intent:<proposal_id>` | Commit time | Sealed (target, claim id) | No (protocol only) |
| `commit_outcome` | The proposal's subject | `outcome:<proposal_id>` | Commit time | (status, claim id) | No (acknowledgement) |

| `commitment_event` (A1) | The event's `subject_id` (the creating subject; identity-less events are refused) | `cevent:<event_id>`. Same id + different content: EVENT_ID_REUSED, decided before time. Under a race the boundary refuses the loser; the original is never overwritten | Commit time (visibility at r). The event's own `at` is business time and orders the projection | Sealed `Event`; seal reference = keyed content fingerprint | **No** (commitment heads only) |
| `episode_summary` (A1) | The episode's subject | `episode:<episode_id>:<keyed hash of members, usable members, generator version>`. The same inputs return the recorded generation | Commit time; the latest generation per episode wins | Sealed `EpisodeGeneration` | **No** (narrative only) |

**Not an entry kind:** policy publication. It lives in the **policy log** as (predicate, version, T).

**Amendment A1 (2026-10-04, additive).** Adds the two kinds above and nothing else. The basis is `durable-home-episodes-commitments-decision-v1.md`.
- **Rebuild (§E)** also yields, at r, commitment heads (`project(events visible at r, now = r)`) and the latest episode generations, with the status derived from the facts. It never regenerates and never re-decides.
- **Erasure (§F):** both are sealed content, so they are unrecoverable after erasure. An erasure entry hides them even before key destruction.
- **Unchanged:** K1–K10, S1–S5, O1–O4, SPI and every existing kind.
- **Executable form:** `memory_core/episode_commitment/` and `tests/test_episode_commitment_durable.py` (82 tests, both reference stores).

For every kind, the commit time is assigned by the journal (K1). The O3 stamp is checked at that time (K9).

No other kinds were needed in v1.1. The intent and outcome pair is required by §C. Amendment A1 later added `commitment_event` and `episode_summary`.

**Tenant and agent identity** live in the sealed claim content (`org_id`, `learned_by_agent_id`) and in commitment events (C-E). They are unchanged here.

**Append rules** (both implementations enforce them; each is tested):

| Rule | Requirement |
|---|---|
| G1 | Known kinds only. A group targets **one** partition |
| Idempotency | Same `idem` and same content: DUPLICATE. Same `idem`, different content: rejected. **K8:** the journal decides a duplicate on the logical command identity **before** any time is assigned or any record is built. A DUPLICATE returns the **original** commit time |
| O1 | Commit time is non-decreasing within a partition. The entry is also refused if a consumed prefix of its partition has reached it, checked atomically with the write (K6, S1) |
| Closure | K5 and K6 (§B) |
| **K9. OCC and stamp at commit** | `expected_version` and the O3 stamp are evaluated at the journal-assigned `at`, inside the partition's serialized write. A stamp mismatch is STALE_POLICY_STAMP (re-run the gate). An OCC mismatch is STATE_CONFLICT (returned to the agent, never retried). A refusal by closure is transient: the retry gets a later time and OCC is re-evaluated |
| O3 | The stamp must equal the version in force at the commit time |
| Erasure fence | No append to an erased partition. No sealing under a destroyed key |

### B. Ordering and evaluation semantics (the central result)

**Question.** Does correctness require a single global total order?

**Answer: no.** [PROVEN] The minimum sufficient guarantee is:

| # | Guarantee |
|---|---|
| **O1** | A total order of each **partition's** own entries, with non-decreasing commit times |
| **O2** | An ordered **policy log** per predicate (versions increase; publication times do not decrease) |
| **O3 (causality)** | Every entry carries the version of its predicate **in force at its commit time**, where "in force at t" means the latest publication with T **<** t. At equal time, **entries precede publications**. The stamp is checked at the journal-assigned time, inside the serialized write (K9) |
| **O4 (visibility)** (v1.1) | A publication receives a T after every consumed prefix of its predicate's log and after every earlier publication of the predicate. The log is closed through t before any entry at t of that predicate is acknowledged, and through r before any read at r evaluating that predicate is served. Hence a publication is never placed before a consumed point [PROVEN: `test_x1_commit_time`, `test_durable_storage_boundary`] |
| **R-READ (closed reads)** (v1.1, normative; was [STATED]) | A read at r is served only once its partition is closed through r. Every entry acknowledged afterwards is placed after r. Lagging views serve only at the position they have fully incorporated (K7) [PROVEN] |

**Served-prefix immutability (SPI), the invariant behind O4 and R-READ** (v1.1):

> Once a prefix of a source has been consumed, every fact acknowledged from that source afterwards is placed, in evaluation order, after every point of that prefix.

The sources are each subject partition and each predicate's policy log. The consumers are:

| Consumer | Prefix consumed |
|---|---|
| A served read at r | Its partition through r, and the logs of the predicates it evaluates through r, both inclusive |
| An acknowledged entry at t | Its predicate's log strictly before t (its stamp), and its partition up to itself (its OCC) |

**Not consumers:** gate reads, publications, publication reports, internal rebuilds.

O1, O3 with historical selection (the N-1/N-5 fixes), S-2, O4 and R-READ are each instances of SPI [PROVEN; see `durable-journal-x1-decision-v1.md` §3].

| # | Closure rule (v1.1) |
|---|---|
| **K4. Closed position** | Every source has a closed position that is **monotone** and **survives crashes**. It may be **stored explicitly** (per source, in the data store), or be **implied by a time service**. Implied means:<br>• every step, reads included, draws its time inside the step from **one global, strictly increasing sequence** (timestamp-oracle form) whose position survives crashes;<br>• an entry becomes durable only if the sequence has not passed its time since it was drawn.<br>Both forms are conformant [PROVEN: one suite, both reference stores].<br>**The implied form does not remove closure state.** It moves it out of the data store into the time service and makes it **global**: a single ordering of timestamps, though not of data. The contract permits this but does not require it.<br>[PROVEN] A time service with no shared sequence (each draw is a node's raw reading) admits a back-dated publication.<br>[INFERENCE] A variant with no state at all (bounded-uncertainty time plus commit-wait) would still need in-flight or safe-time tracking, or locks. |
| **K5. Consumption requires closure** | A read at r is served only if its sources are closed through r. An entry at t is acknowledged only if its predicate's log is closed through t. Closure is irrevocable before the consumer is served or acknowledged. **Order:** a read closes its partition **before** reading entries, and each log before reading its publications |
| **K6. Placement after closure** | An entry is accepted only if its time is after its partition's closed position, at the moment of its durable write. A publication's T is after its log's closed position and after every earlier publication of the predicate. An entry's time is after every earlier publication of its predicate, and not before the partition's last entry |
| **K7. Served positions** | Every served result carries its r.<br>• **Current read** (current state, OCC base): r = max(clock, the caller's **causal token**, i.e. the time of its last acknowledged write or served read), closed before reading.<br>• **Stale-tolerant read** (history, search, as-of): served at an already-closed position, with no data-store write. [PROVEN for both forms; the X-1 as-of and causal-token tests are explicit-form evidence only.]<br>• **Lagging view:** serves only at the position it has fully incorporated, never at the time of its last replicated entry.<br>• **Historical query** with a cutoff at or below the closed position: needs no closure |

**Why no global order is needed.** [PROVEN, plus INFERENCE for the general claim]
- A slot's state and version depend only on:
  1. its own subject's entries for that predicate;
  2. that predicate's publications;
  3. that slot's validity boundaries.
- No semantic in the registry, gate, commit, projection or retrieval compares entries of **different subjects**.
- Tests:
  - `global_order_is_not_required[15]`: two independent random cross-partition delivery orders give identical truth to A's single global order;
  - `property_equivalence_and_history_stability[25 seeds × 2 implementations]`: both implementations equal the live pipeline.

**What correctness actually requires: history stability.** For reads r1 < r2, every slot's version history at r1 is a **prefix** of its history at r2. A version number then never denotes two states (no ABA) and never decreases. This is exactly what N-1 violated. [PROVEN by `check_history_stability`]

**Sufficiency** [INFERENCE, supported by tests]:
- Under O1–O4 and R-READ, the evaluation points visible at r1 are exactly the points with time ≤ r1. That is:
  - the partition's entries (O1, R-READ);
  - publications (O4);
  - boundary instants of already-known claims (G6).
- Later facts only add points with time greater than r1. Each point is evaluated under the version in force at its own time (O3), never under a later one.
- So the r1 history is a prefix of the r2 history.

**Adversarial example (passes).** `adversarial_publication_between_reads_is_stable`:
- "pune" at t=1; "goa" scheduled for t=20 (v1); a **breaking** v2 at t=15; "delhi" at t=25.
- Read at 16: [1 pune, 2 UNKNOWN].
- Read at 26: [1 pune, 2 UNKNOWN, 3 delhi]. It is a prefix extension, because at t=20 goa is a v1 claim under v2 and stays excluded.

**A weaker guarantee that fails.** `break_publication_placement_by_adoption`:
- Rule tried: a publication takes effect at the subject's **next own write**. This is per-subject order plus publications, but without O3's time-causal placement.
- The read at 16 shows [pune, UNKNOWN] (the publication is applied at read time).
- The read at 26 moves the publication to t=25, so goa activates at 20 under v1. The history becomes [pune, **goa**, …].
- Version 2 now denotes two different states: **ABA**. [PROVEN]

**Also proven necessary:**

| Requirement | Test showing the violation |
|---|---|
| Historical policy selection | `break_historical_policy_selection` (rewind) |
| O3 stamp | `break_stamp_check` (an entry admitted under a policy not in force) |
| O3 tie rule | Mutation: publications before entries at equal time fails `entries_are_evaluated_under_the_policy_they_were_admitted_under` |
| O1 | Mutation fails `commit_time_regression_is_rejected` |
| R-READ consequence | `break_without_monotone_commit_time_a_late_write_rewrites_read_history` |

### C. Cross-subject entries

| Operation | Authoritative event (owner partition) | References elsewhere | Cross-subject atomicity needed? | Decidable now? |
|---|---|---|---|---|
| Merge-landed claim (evidence on A, claim on survivor B) | `claim` in **B** | Anchor evidence ids (A's evidence store); merge ids in the record | **No** [PROVEN] | Yes |
| Proposal idempotency | `commit_intent` / `commit_outcome` in the **proposal subject A** (stable across target changes) | Claim id and target in the sealed intent | **No.** Intent, then claim (idempotent on the deterministic id), then outcome. A retry re-reads the intent, so a merge target that changed between attempts cannot create a second claim [PROVEN: `exactly_once_across_retries_and_target_change`; break `without_intent` shows a duplicate] | Yes |
| Person erasure over a merge cluster | `erasure` in **every** cluster partition, then key destruction per subject | Cluster list in each entry | **No.** A **completion barrier**: the erasure is in progress until every partition is done, and a retry completes it [PROVEN: crash after one partition, then retry]. Erasing only one subject of a cluster leaves the person's content reconstructible [PROVEN: break test] | Yes. **Cluster membership comes from the identity layer** (merge links), as today |
| Policy publication | Policy log | None (no fan-out writes) | No | Yes |
| Subject erasure fencing | The erased partition's `erasure` entry seals it | — | No | Yes |
| Tenant / session generations (contract §10) | Not modelled in the prototype | — | — | Belongs with the WORKSPACE / TENANT scopes (S-3 grants) |
| Multi-subject transaction groups (C-4) | — | — | **Would** need cross-partition atomicity | **Already escalated to Infrastructure**, single-subject only for now. Nothing in this contract requires them |

**No requirement found here needs multi-subject atomic transactions.** No escalation is triggered.

### D. Crash and recovery (observable guarantees)

| Situation | Guarantee | Test |
|---|---|---|
| Append acknowledged, then a crash | The entry survives; nothing is lost | `crash_after_durable_append_before_ack…` |
| Crash during a group append | **Nothing** of the group is durable; a retry commits it exactly once | `group_append_is_all_or_nothing…[A,B]`; break `non_atomic_group…` |
| Crash between intent and claim, or between claim and outcome | A retry completes the **same** logical commit: one claim, one intent, one outcome | `exactly_once_across_retries…` |
| Ledger written, response lost | A retry gets DUPLICATE or the recorded result | Idempotency tests |
| Duplicate redelivery (whole history) | Facts are unchanged | `duplicate_delivery_is_idempotent[A,B]`; break `without_idempotency` |
| Partial visibility | Only durable entries are visible; staged writes vanish on crash (B) | Group tests |
| Replay after restart | `reconstruct(facts)` equals live | Properties |
| Closure written; the consumer is never served or acknowledged (v1.1) | Harmless: later facts are placed after it | `case6_crash_before_durable…` |
| A consumer served before its closure is irrevocable (v1.1) | **Forbidden** (K5). A lost closure rewrites a served read | Breaks: `break_s2…` (both stores), `break_case6…` |
| Crash after a durable append, before acknowledgement (v1.1) | The retry gets DUPLICATE with the original time; the gate does not run again (K8) | `s3_…`, `case6_…` |

### E. Rebuild contract

**Rebuild may consume only:**
- partitions (entries);
- the policy log;
- policy content per version;
- sealed content that is still readable (the vault);
- the **served** read position r (v1.1).

**Rebuild never:**
- runs the gate or commit (test: both monkey-patched to raise);
- reads a live store;
- re-decides an outcome;
- evaluates a point under a policy not in force at it.

**Invariant:**

```text
∀ facts, subject, r :  reconstruct(facts, subject, r)  ==  LiveProjection(subject, r)
```

Equality is checked on the full `CurrentState` (slots, values, statuses, provenance ids, `state_version`, freshness, usage, revalidation list), on `get_current_state` / `search_history`, and on the compiled context. Claim ids match too, because they are deterministic.

**History stability** (§B) is part of the invariant: reads at increasing r extend one another.

### F. Erasure

**What may remain after a completed person erasure:** structure only.
- Partition ids and idempotency keys. Claim ids are keyed HMACs and become unlinkable once the key is gone (Lane A).
- Commit times.
- Predicate names.
- Policy stamps.
- Lifecycle transitions (claim id, statuses, causes, evidence refs).
- Sync records (predicate, times, source).
- Outcome markers.
- The erasure entry.

**What must be unrecoverable:** every sealed value (claims, retractions, intents). [PROVEN]
- No erased value appears anywhere in the durable facts.
- `reconstruct` returns ERASED for every cluster partition.
- Further appends are refused.
- A destroyed key exposes nothing even without an erasure entry (defence in depth).
- A rebuild that consulted objects outside the facts **would** resurrect values (break test). The contract rebuild cannot.

**Monotonicity and OCC after erasure.** The partition is sealed, so no later write can depend on its version. There is no ABA.

**Escalations:** none block the contract. These are recorded for their owners:

| Question | Owner |
|---|---|
| Whether metadata (predicate names, timestamps, evidence ids) may remain after erasure | Legal / Security |
| **Erasing a single claim physically while the subject stays live.** Crypto-shred works at subject-key granularity; per-claim physical erasure would need per-claim keys or content rewrite. Today such a claim can only be made non-operational (PENDING_ERASURE) | Security (C-1) + Legal |
| Reversal of PENDING_ERASURE before key destruction (destruction itself is irreversible by construction) | Legal (C-2) |
| The latency bound of the completion barrier (the erasure window) | Legal |

### G. Evaluation points (explicit)

For a slot, the evaluation points are:

| Point | Order |
|---|---|
| Each own entry (claim, retraction, lifecycle, sync) | At its commit time |
| Each publication of its predicate | At T, after entries at T |
| **Each validity-boundary instant** (`valid_from` / `valid_until`) of an already-known claim | **As its own point at that exact instant**, before entries at the same time (S-2, implemented this phase) |
| Erasure | Ends the partition |

**Reads create no points.** [PROVEN]
- `two_boundaries_between_entries_are_separate_evaluation_points`.
- Mutation: evaluating boundaries at the next point instead fails history stability.

---

## Part 3. Storage boundary (v1.1)

Storage guarantees, stated as **what must be true**. How closure is represented is not prescribed. Executable: `memory_core/storage_boundary/` and `tests/test_durable_storage_boundary.py`.

| # | Guarantee |
|---|---|
| **S1. Conditional append** | An entry becomes durable only if no consumed prefix of its partition has reached its time; otherwise nothing is written (READ_CLOSED, transient). A publication is never placed at or before a consumed prefix of its log |
| **S2. Closure survives crashes** | Once a closure, assignment or served position has returned, every later fact of those sources is placed after it, also after a crash |
| **S3. Durable before acknowledgement** | An acknowledged fact is in every later fact set, including after a crash |
| **S4. Reads follow closure** | A read issued after a closure reflects every fact acknowledged before it. No fact can later appear at or before its served position |
| **S5. Single-partition atomicity and idempotency** | A group append to one partition is all-or-nothing. Same idem and content: DUPLICATE; same idem, different content: refused |

Plus, unchanged from v1:
- known kinds;
- O1;
- O3 stamp consistency;
- the erasure fence;
- key destruction makes sealed content unreadable.

**Not required:**
- a global order over partitions;
- transactions across sources (an append closes its predicate's log, then writes its partition: **ordering, not atomicity**);
- a stored write for stale-tolerant reads.

**Current reads** need closure through r, and closure is **never free**:
- explicit form: a stored frontier write, unless the position is already covered;
- implied form: a draw from the global time service, with no data-store write.

Both costs are measurable [PROVEN: `test_current_read_closure_cost_is_measurable_in_both_forms`].

## Results

| Measure | Value |
|---|---|
| Full prototype suite | **905 / 905** |
| Conformance suite | **144** tests |
| Property seeds | 115: equivalence and stability 25×2; global-order independence 15; freshness 15; caller independence 10; erasure soundness 10; stamp-faithful evaluation 15 |

**Deliberate-break tests:** each weakens one rule, and a check fails.

| Rule weakened | Result |
|---|---|
| Publication placement ("adoption") | ABA |
| Historical policy selection | Rewind |
| O3 stamp check | Admission under a non-in-force policy |
| Idempotency | Redelivered quarantine diverges from live |
| Group atomicity (A, B) | Partial group durable |
| Intent | Duplicate commit after a target change |
| Erasure cluster scope | Content survives in the survivor partition |
| Erasure fence | A write lands after erasure |
| Rebuild from live objects | Resurrects erased values |
| Monotone commit time | A late write rewrites a served read's history |

**Mutation runs (rule removed from code):**

| Rule | Tests failing |
|---|---|
| S-2 boundary points | 1 |
| O1 | 1 |
| O3 tie rule | 1 |
| Sealed-skip | 1 |
| O3 stamp | 1 |
| Erasure fence | 1 |
| Idempotency | 7 |
| Intent reuse | 1 |
| Erasure read-closure | 13 |

The first four of these **survived initially**. Each gap was closed with a targeted test.

## Contradictions found and fixed in this phase

| # | Finding | Fix |
|---|---|---|
| **N-5** | **Retrieval's internal projection did not use the policy history.** Its `state_version` could still rewind (the N-1 class); the integration harness missed it because both its paths shared the flaw | `MemorySource.policy_history`, passed by `Pipeline.source()`. Verified 2 → 3 (was → 0) |
| **S-2 (implemented)** | Boundaries were evaluated at the next journal point or at `now`. The new history-stability check shows that merges two changes into one version across reads | Boundary instants are explicit evaluation points; reads create none |
| **Ties** | Equal-time entry and publication ordering was implicit | O3 tie rule stated and tested |
| **R-READ** | Was implicit in "monotone commit time" | Stated separately, with its consequence demonstrated |

## Outcome: SUCCESS. Ready for Infrastructure

**Every guarantee is technology-neutral and executable**, and both journal implementations pass. No guarantee needed a storage technology, key-custody model, retention rule or multi-subject transaction.

**What Infrastructure must evaluate any candidate store against** (v1.1, items 1–3 amended):

| # | Requirement |
|---|---|
| 1 | Per-partition total order; a conditional append against the partition's closed position (O1, K6, S1) |
| 2 | An ordered policy log with a closed position (explicit or implied, K4); causal stamps checked at the journal-assigned time (O2, O3, O4, K9) |
| 3 | **Closed reads:** reads served at or below closed positions, with r returned (R-READ, K5, K7, S4) |
| 4 | Idempotent, all-or-nothing single-partition group append, durable before acknowledgement |
| 5 | The intent / claim / outcome protocol for cross-partition commits |
| 6 | Erasure entries per cluster partition with a completion barrier, plus irreversible key destruction that makes sealed content unrecoverable |
| 7 | Rebuild from durable facts only |

**Not required:** a global total order across subjects; multi-subject transactions.

**Still owner-held, and not blocking storage evaluation:**
- C-1 key custody and the per-claim erasure granularity question;
- Legal: erasure metadata, the reversal window and the erasure latency bound;
- B-3 retention;
- C-4 multi-subject groups (Infrastructure, optional);
- non-CUSTOMER grants.
