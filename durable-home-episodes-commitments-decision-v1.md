# Durable Home for Episodes and Commitment Events: Decision v1

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Prototype and test only.

**Labels:** [PROVEN], [DECISION], [CONTRACT_GAP], [OWNER], [INFERENCE].

**Not reopened:** C-5, E-5, Gateway v0.1, the Evidence Boundary, identity-event semantics, Legal erasure reversal, non-CUSTOMER grants.

---

## 1. Problem statement

Engineering closure §5 lists six things durable storage must persist. Item 6 is "**episodes and commitment events (with identity)**" (`target-architecture-engineering-closure-v1.md:80`). The integration Pipeline also lists them as durable facts (`memory_core/integration/__init__.py:8-13`).

Durable Journal contract v1.1 has neither:
- its entry kinds are `claim`, `retraction`, `lifecycle`, `sync`, `erasure`, `commit_intent` and `commit_outcome` (`durable_journal/__init__.py:31`; contract §A);
- §A says "No other kinds were needed";
- its Part 1 durable-fact table has no row for either record.

The owner-dependency audit recorded this as a [CONTRACT_GAP] that engineering can resolve (`next-architecture-work-decision-v2.md:58, :76`). Today the Pipeline's rebuild **copies the in-memory lists** (`integration/__init__.py:140`), so they are process state that a rebuild trusts.

The question is **where** these facts are authoritative. "Not in the journal" does not by itself mean "add them to the journal".

## 2. Source evidence

Code paths are relative to `memory-prototype/memory_core/`.

| # | Source | What it establishes |
|---|---|---|
| S1 | Red team M-2 [DECISION] (`memory-architecture-v2-red-team.md:504-512`) | Commitments are "an **append-only `commitment_events` log plus a projection**". Each event references evidence. The head is rebuildable. Creation is idempotent on the action. Expiry is computed at read time. Terminal states accept only `reopened`. "Deletion: commitments are subject-scoped and erased with the subject". "`commitment_events` **are the typed transitions** … They do **not need a separate store technology**" |
| S2 | Decision closure C-E (`target-architecture-decision-closure-v1.md:207`) and engineering closure C-E (`target-architecture-engineering-closure-v1.md:18`) | One model: the reviewed Lane A event log. `Event` and `Head` carry `subject_id`, `agent_id` and `tenant_id`. **Scope is CUSTOMER (the person), with the agent as attribution.** Identity-mismatched events are refused. Identity-less commitments are never served |
| S3 | `commitments/__init__.py:22-121` | The state machine `_T`, actor authorisation `_AUTH`, the terminal rule and read-time expiry. `project()` is "a pure function of the event SET (sorted by (at, event_id))". Dedup is on `event_id`. A second `create` for the same key is a no-op. Dead evidence → the event is rejected (`evidence_erased`). Identity mismatch → rejected |
| S4 | `runtime/__init__.py:1046-1054` | An event is admitted only if its evidence exists and is active ("every event is backed by live evidence") |
| S5 | Contract §1, Narrative Memory (`artifacts/architecture-contract.md:56-66`) | Narrative Memory is **non-assertive**. It "MUST carry `scope`, `provenance`, `observed_at`, `valid_from`/`valid_until` where meaningful, `retention_class`, `security_class`, and `status`". It "MUST NOT establish Current State, override Claims, establish authority" |
| S6 | `model.py:135-145` (`Episode`) | `episode_id`, `subject_id`, `agent_id`, `evidence_ids`, `started_at`, `ended_at`, `summary`, `summary_status` (none, ok, regenerate_pending, quarantined, pending_erasure) and `merge_ids` |
| S7 | `ids/__init__.py:59-60` | `episode_id = "ep_" + H(subject_key, "ep|v1|agent|first_evidence_id")`: deterministic and keyed per subject |
| S8 | `runtime/__init__.py:1265-1287` (`assign_episodes`) | Membership is grouped by an observed-time gap (a **config** value, `[UNMEASURED]`, red team m-2 `:827`). The summary is produced by a **summarizer** (an LLM in production) from USER, active evidence only: "from evidence only, never from summaries". It is regenerated only when the status is none, regenerate_pending or ok |
| S9 | `runtime/__init__.py:759-762, :953-955, :826` | The status changes: forget_fact → `regenerate_pending` if any member evidence is `context_suppressed`; merge undo → `quarantined` if the undone merge id is in `merge_ids`; forget_me → `pending_erasure` |
| S10 | A7 design (`memory-postgres-design-v1.md:44-45, :82`) | Lane A placed `commitment_events (org_id, event_id)` and `episodes`/`narratives` (with `summary`, `generator_version`, `input_evidence_ids`) in the **same store and partitioning group as claims** |
| S11 | Retrieval (`retrieval/__init__.py:253-298`) | `search_memory` serves only `summary_status == "ok"` and skips episodes with dead evidence. `get_commitments` = `CM.project(...)` filtered to the requested subject. Both read a `MemorySource` and need no caller in resolution |
| S12 | Decision closure T-2 (`target-architecture-decision-closure-v1.md:163`) | The narrative `security_class` is derived at summarisation as the most restrictive class of the evidence's extracted predicates, and is never downgraded. The **default floor** belongs to Security [OWNER] |
| S13 | Journal contract v1.1 §A, §C, §E, §F, K1, K8 | One owning partition per entry. Commit time is assigned by the journal. Idempotency is decided before time. Rebuild uses durable facts only and never re-decides. Erasure seals the partition and destroys its key (crypto-shred). No cross-subject atomicity |
| S14 | `commit-ledger-authority-decision-v1.md` | Recorded interpretations and outcomes are journal facts. Evidence holds source material and anchors |
| S15 | Pipeline rebuild (`integration/__init__.py:162-175`) | `episodes=list(self.episodes), commitment_events=list(self.commitment_events)`: copied, not rebuilt |

## 3. Semantic definitions

| Question | Commitment event | Episode (generation record) |
|---|---|---|
| **1. What it represents** | A typed transition of one commitment (create, confirm, start, fulfil, cancel, external change, operator reopen), asserted by an actor and backed by evidence (S1, S3) | A **recorded summarisation**: the membership of one conversation segment for one subject, plus the narrative summary that a nondeterministic generator produced from it (S6, S8). Narrative Memory, non-assertive (S5) |
| **2/3. Truth or projection** | **Event = authoritative fact** [PROVEN, S1 DECISION]. **Head = projection** (state, expiry) [PROVEN, S3 `project` is pure] | **Generation = authoritative record** [INFERENCE from S8 + S13: the summary cannot be re-derived, because the generator is nondeterministic, so replay must apply the recorded output (recorded-outcome replay), exactly as for gate outcomes]. It is **authoritative as a record, non-assertive as content** (S5). **`summary_status` = projection** (derived; see §9) |
| **4. Identity** | `event_id` (the writer's idempotency id) and `commitment_key` (creation idempotency on the action, an HMAC per S1) | `episode_id` (S7, deterministic). A **generation key** = keyed hash of (episode id, sorted members, sorted usable members, generator version) [DECISION, §7] |
| **5. Scope** | CUSTOMER subject; agent and tenant as attribution (S2) | CUSTOMER subject; agent attribution (S6, S7). Tenant is carried for parity with C-E (closure §5: "with identity") |
| **6. Time** | The event's own `at` is **business/observed time** (it orders the projection). Knowledge (commit) time is the journal's (K1). Expiry uses the **served r** | `started_at`/`ended_at` = observed-time window (valid window, S5). Commit time is the journal's |
| **7. Lifecycle** | The state machine in S3, evaluated by the projection | Status derived from facts (§9). Generations are superseded by later generations of the same episode |
| **8. Provenance** | `evidence_id` per event; live evidence required at admission (S4) | Input evidence ids, used evidence ids, merge ids and generator version (S5, S10) |
| **9. Replay** | Rebuild = `project(events with commit time ≤ r, now = r)`; never re-decided | Rebuild = the latest generation per episode at r; **never regenerated** |
| **10. Authorisation** | Read via `get_commitments` after resolution, using `may_read` on (CUSTOMER, subject) (S11). Cross-agent visibility = T-1 [OWNER] | Read via `search_memory`, using `may_read` (S11). Security floor = T-2 [OWNER] |

## 4. Candidate durable homes

| Option | Description |
|---|---|
| **A** | Both are Durable Journal facts in the owning subject's partition: new entry kinds `commitment_event` and `episode_summary` |
| **B** | Both have their own authoritative durable store, separate from the journal (Lane A A7 placed them in PG beside claims, but there PG was a projection store) |
| **B′** | A variant of B for commitment events: the **evidence store**, because red-team C-8.4 writes commitment transitions as command evidence |
| **C** | Commitment events in the journal, episodes in a separate store (or the reverse) |

## 5. Option comparison

| Criterion | A: journal | B / B′: separate store | C: split |
|---|---|---|---|
| **Truth ownership** | One authority for every recorded interpretation (S14) | A second authority beside the journal. B′ puts an **interpretation** into the source-material store, contradicting S14 | Two authorities |
| **Partition ownership** | Subject partition, which is already the unit of order, idempotency and erasure (S13) | Must define its own partitioning | Mixed |
| **Replay / rebuild** | `reconstruct` already consumes one fact set. Both kinds join it | Rebuild must read two stores **at one consistent position r**. That needs the store to implement K4–K7 closure itself, or reads become inconsistent across stores | Same problem for the separate half |
| **Ordering** | O1 per partition and journal-assigned time (K1) | No served-prefix immutability unless re-implemented | Same |
| **Idempotency** | K8 / S5 on `idem`, decided before time | Re-implemented | Same |
| **Lifecycle** | A projection over facts (unchanged rules) | Same rules, but a different store | Same |
| **Identity** | Deterministic `idem` per partition | Same identity, separate uniqueness domain | Same |
| **Cross-subject** | **None needed:** C-E pins every event of a commitment to the creating subject (S2, S3 `identity_mismatch`), and an episode belongs to one subject (S6). No intent/outcome protocol | Same | Same |
| **Gateway** | No change (v0.1 has no episode or commitment operations) | No change | No change |
| **Retrieval** | Unchanged functions fed from rebuilt facts (S11) | Unchanged, but fed from two sources | Same |
| **Erasure** | **Inherited:** the erasure entry seals the partition, and destroying the key crypto-shreds both kinds (§F). S1's "erased with the subject" holds automatically | A second erasure mechanism, plus a **completion barrier ordered against the journal's**. That is cross-store coordination, and the brief forbids it | Same, for the separate half |
| **Scalability** | §11: the same per-subject model as claims | Can be partitioned independently, but no benefit is shown (§11) | — |
| **Cross-store transactions** | **None** | Needed, or a new barrier, for consistent erasure and rebuild at r | Same |

**Option A is the only option that needs no new closure, erasure or consistency machinery.** B, B′ and C each need either cross-store coordination or a re-implementation of K4–K7, and both are outside the constraints. B′ is also excluded because the Evidence Boundary is parked (E-5), and because the event is an interpretation rather than source material (S14). The **command evidence** that justifies an event stays in the evidence store, referenced by `evidence_id`. That is unchanged.

## 6. Recommended architecture

**[DECISION] Option A.** Both are **Durable Journal facts in the owning CUSTOMER subject's partition**, in two new additive entry kinds:

| Kind | Owner partition | `idem` | Payload | Participates in claim projection |
|---|---|---|---|---|
| `commitment_event` | `event.subject_id` (the creating subject; C-E) | `cevent:<event_id>` | Sealed `Event` (subject key), with a keyed content fingerprint in the seal reference | **No** |
| `episode_summary` | `episode.subject_id` | `episode:<episode_id>:<generation key>` | Sealed generation record (subject key), with a keyed content fingerprint | **No** |

**How this follows from existing decisions:**
- it is M-2's "typed transitions; no separate store technology" (S1);
- it is the ledger decision's rule that recorded interpretations are journal facts (S14);
- it is closure §5's "must persist" (§1);
- it is A7's co-location with claims (S10), made authoritative under journal v1.1.

## 7. Partition and identity model

- **Commitment event:**
  - partition = `subject_id`; an identity-less event is refused (`identity_required`, as retrieval's fail-closed rule);
  - `idem = "cevent:" + event_id`;
  - **same id + same content → DUPLICATE** (original commit time; K8);
  - **same id + different content → `EVENT_ID_REUSED`**, decided before time. Nothing is sealed, so the original fact cannot be overwritten. This is the GW-2 rule applied to events;
  - **under a race** (both writes pass the pre-check), the storage boundary refuses the loser. The loser's payload has already been sealed under **its own** fingerprint reference, because `TimedJournal.finish` seals before it appends. The original is still never overwritten, since the references differ. The loser's content sits in the vault with no entry pointing to it until the key is shredded. Claims behave the same way through the unchanged `TimedJournal`, so this is inherited, not new to A1;
  - creation idempotency on `commitment_key` stays a **projection rule** (S3: a second create is a no-op). A duplicate assent with a fresh event id yields one commitment.
- **Episode generation:**
  - partition = `subject_id`; `episode_id` as S7;
  - generation key = `H(subject_key, sorted(evidence_ids) | sorted(active_at_generation) | generator_version)`; `idem = "episode:" + episode_id + ":" + generation key`;
  - the **usable (active) members** are part of the inputs. A forget_fact changes them without changing membership, so the regeneration it triggers is a **new** generation, while a plain retry is not. Implementation found this: the first version keyed on membership only, and a test against Lane A's forget_fact flow failed;
  - **the same inputs → the recorded generation is returned (DUPLICATE)** even if the new output text differs. This is recorded-outcome replay: a retry of a nondeterministic summarisation never creates a second summary for the same inputs;
  - new inputs (more evidence, or a new generator version) → a new generation. **The latest generation by partition position wins**.
- **Fingerprints and seal references** are keyed by the subject key, so they become unlinkable after crypto-shred (§F).
- **Admission:** a commitment event requires its evidence to be live (S4, unchanged). Evidence status is an existing input, read the way retrieval already reads `dead_evidence`. **No new dependency on the parked Evidence Boundary** is added.

## 8. Replay and rebuild model

- **Facts:** the entries of the partition up to the served r; the vault (sealed content); evidence status; and the identity layer's undone merges, which are existing inputs (S11, fence).
- **Commitments at r:**
  - `project(events of the partition with commit time ≤ r, now = r, dead_evidence)`;
  - the projection is **unchanged** and still sorts by the event's own `at`;
  - **commit time governs visibility; business time governs order**. Neither overwrites the other.
- **Episodes at r:** the latest generation per `episode_id` with commit time ≤ r, with status derived as in §9. They are **never regenerated** during rebuild.
- **No claim effect:** neither kind is in `PROJECTED_KINDS`. Claim state is identical with or without them. This is the executable form of contract §1 non-authority.
- **Pipeline equivalence:** the unchanged `get_commitments` and `search_memory`, fed a `MemorySource` built from rebuilt facts, return what they return from the in-memory lists (tests).

## 9. Lifecycle model

**Commitments:** unchanged (S3). The `_T` transitions, `_AUTH` actors, the terminal rule with operator reopen, read-time expiry at r, dead-evidence rejection, and identity mismatch.

**Episode status:** derived, never journaled. The precedent is N-4: revalidation status is derived, not journaled.

| Status | Derived when | Lane A source |
|---|---|---|
| (erased) | The partition is erased: nothing is served | forget_me → `pending_erasure`, then physical delete (S9) |
| `quarantined` | Any `merge_id` recorded in the generation is in the identity layer's undone merges | merge undo (S9 `:953-955`) |
| `regenerate_pending` | Any member evidence that was **active when the generation was recorded** is now `context_suppressed` | forget_fact (S9 `:759-762`) |
| `ok` / `none` | Otherwise: `ok` if a summary exists, else `none` | `assign_episodes` |

**Why the generation records which members were active:** Lane A's flag is a mutable event-driven state. It is not a function of current facts, so it cannot be rebuilt. Recording the active set at generation time makes the derivation a **pure function of facts** with the same safety property: a summary is withheld once any input that could have contributed is suppressed, and the regenerated generation (built after the suppression) is served.

[INFERENCE] **One observable difference:** Lane A also re-flags an already-regenerated episode on a **later, unrelated** forget_fact of the same subject (its rule checks every member, including members suppressed before that generation). The derived rule does not. Lane A then re-regenerates text that no suppressed input contributed to. No suppressed content is served under either rule.

## 10. Erasure implications

- **Person erasure:** inherited unchanged from §F.
  - The erasure entry seals the partition; destroying the key makes every `commitment_event` and `episode_summary` payload unrecoverable.
  - `reconstruct` returns ERASED; further appends are refused.
  - This satisfies M-2 ("erased with the subject") and Lane A's episode deletion. It is [PROVEN] by tests for both kinds on both stores.
- **Erased evidence:** commitment events backed by dead evidence are rejected by the projection (unchanged). Episodes with dead members are skipped by retrieval (unchanged).
- **forget_fact while the subject is live:**
  - Older generations remain sealed under the **live** key and are withheld (`regenerate_pending`), but their content is not destroyed.
  - This is the same situation as a forgotten claim's sealed record. It inherits the existing §F escalation (per-item physical erasure: **Security (C-1) + Legal**). It is not a new decision.
- **Not decided here:** retention values (B-3), Legal reversal, key custody (C-1), the erasure latency bound.

## 11. Scalability implications

The analysis is technology-neutral; no benchmark was run.

| Aspect | Finding |
|---|---|
| **Hot subjects / append rate** | Both kinds are per-subject appends with the same per-partition serialization as claims. Commitment events are few per commitment (state-machine bounded). [INFERENCE] **Episode generations are the growth risk:** their rate is set by the regeneration cadence and by long-running sessions (WhatsApp, IG and Slack sessions that never end, a known PRESENT failure). The cadence is a writer policy, and it should be bounded by "regenerate only on new inputs", which the generation key enforces (same inputs → DUPLICATE) |
| **History growth / replay cost** | A rebuild reads the subject's whole partition. **[CONTRACT_GAP] v1.1 has no compaction or checkpoint primitive**, for claims as well as for the new kinds. Only a cache equal to `reconstruct` is allowed (Part 1) |
| **Projection decomposability** | [PROVEN at model level] Commitment heads are a **per-`commitment_key`** function of that key's events. Episodes are **latest-per-`episode_id`**. Both decompose per key, and a checkpoint at r₁ plus the suffix (r₁, r₂] equals the full rebuild at r₂. A future compaction or index can therefore work per key without changing semantics |
| **Read amplification** | A commitment or narrative read needs only its own kind and key. Superseded generations are history, never served |
| **Implied-frontier store** | Its global closure (noted in decision v4 as a liveness cost) applies to these appends too. That cost is measured by C-5 E7, not here |
| **Retention / erasure** | Same partition, same crypto-shred. Retention classes are an [OWNER] value (B-3) |

**Conclusion [INFERENCE]:** the per-subject partition model can carry both kinds. Their scaling limits are the same as for claims (no compaction primitive), plus a writer-side bound on regeneration cadence. Nothing here requires a global order or cross-partition atomicity.

## 12. Interaction with Gateway and Retrieval

- **Gateway v0.1:** **no change.** It has no episode or commitment operations, and its contract does not require them. Adding such operations would be a new Gateway contract item, out of scope here.
- **Retrieval:** **no change.** `get_commitments` and `search_memory` keep their signatures and behaviour. The new model only produces the `MemorySource` inputs from durable facts. Caller authorisation stays outside resolution (`may_read` after projection).
- **Pipeline:** unchanged. Its in-memory lists remain a TEST_ONLY harness. The durable model is what a durable implementation uses.

## 13. Contract changes required

**Durable Journal contract v1.1, additive Amendment A1:**
- Part 1: add rows for `commitment_event` and `episode_summary` as durable facts (sealed).
- §A: add both kinds, with owner partition, `idem`, payload and "does not participate in claim projection".
- §E: rebuild also yields commitment heads and episode generations at r, under the same "never re-decide" rule.
- §F: both kinds are sealed content, so they are unrecoverable after erasure.

No K1–K10, S1–S5, O1–O4 or SPI rule changes. No existing kind changes.

**Code:**
- `durable_journal.KINDS` and `SEALED_KINDS` gain the two kinds. `PROJECTED_KINDS` is unchanged.
- New module `memory_core/episode_commitment/`.

## 14. Owner dependencies

None of these blocks the durable home. All are pre-existing.

| Item | Owner | Effect |
|---|---|---|
| T-1: cross-agent commitment visibility (CUSTOMER vs relationship) | Product + Security | A read-grant question. The identity fields make either enforceable |
| T-2: the narrative security-class floor | Security | Field required. The reference uses TEST_ONLY |
| B-3: `retention_class` values | Legal | The reference uses TEST_ONLY, as claims do |
| C-1: key custody | Security | Crypto-shred mechanism, as for claims |
| §F: per-item physical erasure (forgotten summaries and claims) | Security + Legal | Inherited, unchanged |
| The episode gap value (`[UNMEASURED]`) | Config | Changes future grouping. Recorded generations keep their identity |
| Merge-read semantics across a cluster | Identity layer (not reopened) | Commitments and episodes stay in their creating partition, as claims of an absorbed subject do |

**[INFERENCE] Lane A latent issue, recorded and not fixed:** in Lane A's single global event log, a `commitment_key` that collides across subjects lets one subject's `create` shadow another's commitment. Partitioning by subject removes this, and a test shows it. Lane A code is untouched.

**[INHERITED, E-5 territory, not touched]:** the commitment projection rejects events whose evidence is **dead**, but not events whose evidence is **missing** (for example, lost in a restore).

## 15. Final gate

The durable home follows from existing decisions (M-2, C-E, the ledger authority, closure §5, A7 co-location) and from journal v1.1's own erasure and rebuild rules. **No owner decision is missing.**

**EPISODE/COMMITMENT DURABLE HOME — PROCEED.**

Implementation results are in §16.

---

## 16. Implementation results

**Gate result: PROCEED → implemented.**

**Files:**

| File | Change |
|---|---|
| `memory-prototype/memory_core/durable_journal/__init__.py` | `KINDS` and `SEALED_KINDS` gain `commitment_event` and `episode_summary`. `PROJECTED_KINDS` is unchanged. **No other line changed** |
| `memory-prototype/memory_core/episode_commitment/__init__.py` | **New.** Records events and generations through the unchanged `TimedJournal`, and reads at r: `commitments_at`, `generations_at`, `episodes_at`, `derive_status` |
| `memory-prototype/tests/test_episode_commitment_durable.py` | **New.** 82 tests |
| `durable-journal-rebuild-contract-v1.md` | Amendment A1: Part 1 rows 10–11, two §A rows, the amendment note |

**Not changed:** the Gateway, retrieval, the Context Compiler, the gate, the commit layer, the Pipeline, `commitments`, Lane A runtime, StorageBoundary, `commit_time`, and every existing test.

**Tests (82):** 22 test functions, two of them seeded properties. That gives 40 instances on each reference store (explicit and implied frontiers), plus 2 store-independent tests.

| Required property | Tests |
|---|---|
| Deterministic, keyed identity | `identity_is_deterministic_keyed…`; generation identity ignores output text and includes the usable inputs |
| Partition-local ownership | `an_event_is_a_sealed_fact_in_its_subject_partition…`; `no_cross_subject_contamination…`; `a_foreign_identity_event…` |
| Durable/rebuild equivalence | `rebuilt_commitments_equal_the_lane_a_projection_and_unchanged_retrieval` (15 seeds × 2 stores); `search_memory_over_durable_episodes_equals…`; `a_restarted_journal…` |
| Replay correctness | `a_retried_summarisation_returns_the_recorded_generation…`; DUPLICATE with the original time; the racing reuse cannot overwrite |
| Lifecycle correctness | `duplicate_assent…`; `expiry_is_evaluated_at_the_served_position`; `commit_time_governs_visibility_and_business_time_governs_order`; derived episode status **matches Lane A** through forget_fact and regeneration, and through merge undo (driving the real runtime) |
| No duplicate truth | `both_kinds_leave_claim_state_unchanged` (claim state and trace identical with and without the new entries); retries do not add generations |
| No cross-subject contamination | A colliding `commitment_key` across two subjects keeps both. Lane A's global log shadows one, which is recorded and not fixed |
| Erasure compatibility | Nothing recoverable after erasure; further appends refused; an erasure entry alone hides both kinds; the served past is unchanged |
| Scalable append/history (model level) | Per-key decomposition; checkpoint at r₁ plus the suffix equals the rebuild at r₂ (5 seeds × 2); history grows only with new inputs |
| Served-prefix immutability | `served_positions_stay_immutable_for_both_kinds` |

**Mutation run:** 19 invariants removed one at a time, the A1 suite run, the code restored byte-identical. **19/19 caught.**

| Invariant | Caught |
|---|---|
| Identity required (events) / (generations) | yes / yes |
| Live evidence at admission | yes |
| Event fingerprint comparison | yes |
| Duplicate before time (events) | yes |
| Generation identity on inputs only / includes the usable set | yes / yes |
| Keyed fingerprint | yes |
| Latest generation wins | yes |
| Visibility by commit time ≤ r | yes |
| An erasure entry hides the partition | yes |
| Expiry at the served r | yes |
| Subject filter on heads | yes |
| Quarantine derivation / regenerate-pending derivation / pending only for inputs active at generation | yes / yes / yes |
| Refusal (not an exception) under a destroyed key | yes |
| Kinds registered | yes |
| Kinds kept out of the claim projection | yes, **by crash**: the claim projection raises a `TypeError` on these payloads. This is not a state difference |

- **One survivor was found in the first run and removed by deletion, not by a test.** The generation duplicate pre-check was redundant with the journal's own K8 duplicate-before-time rule, so it was deleted.
- An earlier anchor-mismatch pass is not counted.

**Regression:**

| Suite | Result |
|---|---|
| Gateway G0 | **38/38**, unchanged |
| Gateway adversarial | **109/109**, unchanged |
| Full prototype suite | **1284 passed** (baseline 1202 + 82 new), 0 xfail. No existing test edited |

**Remaining owner dependencies** (all pre-existing and non-blocking; §14): T-1 cross-agent commitment visibility; the T-2 narrative security floor; B-3 retention classes; C-1 key custody; §F per-item physical erasure of forgotten summaries.

**Remaining [CONTRACT_GAP]s:**
- no compaction or checkpoint primitive in v1.1 (claims included). The model-level decomposition shows that one could be added per key without semantic change;
- the regeneration-cadence bound is a writer policy.
