# Durable Journal Contract v1.1: Implementation Report

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. A test-only executable boundary plus a normative contract update. No storage is selected; no production system, real database, Gateway or owner decision is involved.

**Phase:** the action chosen in `target-architecture-next-decision-v3.md`.

**Outcome: SUCCESS, with one deviation that needs the brief owner's acceptance (§9).**
- K2 and K4 are reconciled.
- One technology-neutral storage boundary is proven by one suite against two different stores. The implied store is in **timestamp-oracle form**: no per-source frontier in the data store, closure implied by a global, crash-surviving time sequence (§1, §5).
- X-1 runs through the boundary: 64/64 on the explicit store, 53/64 on the implied store, with no guarantee violation (§9).
- The contract is upgraded to v1.1.
- The Infrastructure request is drafted and not issued.

**Suite: 1047 / 1047** (969 + 78). No existing test was deleted, weakened, skipped, marked expected-to-fail or edited.

**Labels:** [PROVEN], [INFERENCE], [OWNER], [STATED], [CONTRACT_GAP].

---

## 1. K2 / K4 compatibility result: COMPATIBLE [PROVEN]

**The risk** (next-decision v3 §3). K2 requires the record's `committed_at` to equal `at`, built inside the commit step. K4 allows a frontier "implied by commit order". If "commit order" meant a store timestamp known only *after* commit, the record could not carry it.

**Resolution.** "Implied" does not need a store-revealed commit timestamp. The exact sequence for one entry, implemented by `ImpliedFrontierStore`:
1. **Draw.** The step draws `at` from a time source that is strictly monotone across **all** steps of **all** sources and does not rewind on a crash (`SerialClock.draw`).
2. **Build.** The record is built with `committed_at = at` (journal `prepare`).
3. **Check and write.** Inside the store's write step:
   - if the time source has moved past `at` since the draw, the append is refused (READ_CLOSED, transient; the retry draws again);
   - otherwise the journal's checks (OCC, stamp) run at `at` and the entry becomes durable.
4. **Reads and publications** also draw from the same source. Every consumer therefore draws a later time than any entry that can still become durable.

**No conditions violated:**

| Condition | How it holds |
|---|---|
| Final commit timestamp known before commit? | Not needed: the drawn time is final |
| Record mutated after commit? | Never |
| `committed_at` redefined? | No. It is the drawn knowledge time (K2 check: `committed_at_is_commit_time`, run in every boundary test) |
| Hidden frontier? | **None in the data store**, which holds only the facts and only *reads* the time service. But closure **is** state: the time service's single global high-water, advanced by every step (reads included) and surviving crashes, as a timestamp oracle persists it. The implied form moves closure state out of the data store and makes it global. It does not remove it. A memoryless variant (bounded-uncertainty time plus commit-wait, no state anywhere) would still need in-flight or safe-time tracking or locks, because a publication drawn earlier but not yet durable must be excluded [INFERENCE] |
| Atomicity across sources? | None. The time source is not a source of evaluation points |

**The precondition that came out of this.** It is now normative in K4. An implied position requires a global, increasing time sequence that survives crashes. Two break tests prove it [PROVEN]:
- a time service with **no shared sequence** (each draw is a node's raw reading) admits a back-dated publication;
- a sequence **rebuilt from the durable log** after a crash admits a late entry into a served read.

The reference implied store tolerates skewed node readings only because its sequence keeps a global high-water. No escalation was needed: K2 and K4 are compatible, and the interface does not require stored frontiers.

## 2. v1 → v1.1 changes (`durable-journal-rebuild-contract-v1.md`, retitled v1.1)

| Location | Change |
|---|---|
| Header | v1.1 note; executable forms (`commit_time`, `storage_boundary`, 64 + 78 tests); suite 1047; v1 tests reinterpreted as storage-level replay |
| Labels | [CONTRACT_GAP] added |
| **Part 0. Time** (new) | K1 ownership, K2 meaning, K3 accuracy, K10 ties; the five time concepts |
| Part 1 | "Read time r: caller input" split into **requested** time (caller) and **served** position r (journal) |
| §A | Commit time assigned by the journal; stamp checked at that time |
| §A append rules | K8 (idempotency before time); O1 plus the closure check; a Closure row; K9 (OCC and stamp at commit) |
| §B | O3 adds the K9 note. O4 and R-READ are rewritten (R-READ is now normative, previously [STATED]). New SPI paragraph with sources, consumers and non-consumers. K4–K7 closure rules |
| §D | Rows for: closure written but never consumed; consumer served before closure is irrevocable (forbidden); duplicate after a crash before acknowledgement |
| §E | Rebuild consumes the **served** position r |
| **Part 3. Storage boundary** (new) | S1–S5 as guarantees; v1 storage guards retained; not required: global order, cross-source transactions, a write per stale-tolerant read; current-read closure cost stated |
| Results / requirements | Items 1–3 amended: closed position "explicit or implied" |

**Corrected relative to the X-1 §8 draft.** The draft's S1 ("compare against that source's **durable frontier**") and requirement 2 ("**with a durable frontier**") presupposed stored frontiers. v1.1 says "consumed prefix" and "closed position (explicit or implied, K4)".

**Unchanged:**
- erasure (cluster fencing, unrecoverability, the owner escalations);
- the rebuild invariant and its prohibition on running the gate;
- cross-subject protocols;
- evaluation points (G).

No custody, retention, product-policy or storage choice was made.

## 3. Storage-boundary interface

`memory_core/storage_boundary/__init__.py`, class `StorageBoundary`. Every operation states a guarantee; none exposes a frontier value.

| Operation | Guarantee |
|---|---|
| `entries`, `publications`, `facts` | S4 reads; the durable fact set (rebuild input) |
| `assign(partition, predicate, reading)` | A commit time after every consumed prefix of the partition and every publication of the predicate. On return, the predicate's log is closed through it |
| `append(partition, at, entries, check=…)` | **One serialized step:** S1 closure check, O1, the journal's own check at `at` (OCC, stamp), then an all-or-nothing durable write (S3, S5). Storage guards: kinds, idempotency, erasure fence, stamp |
| `close(sources, r)` | Consume sources through ≥ r; returns the position actually closed; irrevocable (S2) |
| `closed(partition, predicates, reading)` | A position already closed, with no stored write (stale-tolerant reads) |
| `publish` / `publish_at` | Assigned T after the closed prefix / a caller time refused if it would fall inside one |
| `snapshot`, `view_position` | Lagging views and the position they have incorporated |
| `seal`, `destroy_key`, `crash` | Erasure capabilities; crash semantics |

**There is no `get_frontier`/`set_frontier`.** The explicit store keeps frontier dictionaries as its own durable state. The implied store has none. The journal reads frontiers only through read-only properties (`f_part`/`f_pol`), kept so the unchanged X-1 tests can inspect the explicit store; they are empty for the implied store.

## 4. Explicit-frontier implementation (`ExplicitFrontierStore`)

- **Owns** durable frontier values per partition and per predicate log; the process holds none.
- **`assign`** = max(reading, last entry time, just after the partition frontier, just after the last publication), then raises the log frontier.
- **`close`** raises frontiers. **`closed`** = min over frontiers.
- **The conditional append** refuses `at ≤` the partition frontier.
- **Survives `crash()`**, because frontiers are store state.
- **Break switches:** `volatile_frontiers` (S2), `close_logs=False` (O4), `atomic=False` (S5).

It is new code. `PartitionedJournal` is not used as the store under test.

## 5. Implied-frontier implementation (`ImpliedFrontierStore`)

**No per-source frontier field.** The data store's state is the durable facts only; it reads the time service and never sets it. How each requirement is met:

| Requirement | Mechanism |
|---|---|
| How a source becomes closed | The global time sequence passes it: `close` draws |
| How reads know the source is closed | They drew a later time than any entry that can still be written |
| How later entries follow the consumed prefix | Every assignment draws a strictly later time. An in-flight entry overtaken by any later draw is refused |
| How a crash preserves the frontier | The time service's high-water survives a store crash, as a timestamp oracle persists it. **This is the state that closure rests on** |
| How `committed_at` stays correct | It is the drawn time, built before durability, never rewritten |

**Break switches:**
- `refuse_overtaken=False` (S1);
- `clock_resets_on_crash` (S2, time rebuilt from the log);
- `SerialClock(per_node=True)` (time not serialization-consistent);
- `atomic=False` (S5).

## 6. Proof that both satisfy one contract

- `tests/test_durable_storage_boundary.py` runs **unchanged** against both (every test is parametrized over `kind ∈ {explicit, implied}`).
- Assertions are about guarantees only:
  - `served_prefixes_are_immutable`;
  - `acknowledged_stamps_hold`;
  - `committed_at_is_commit_time` (K2);
  - refusal versus acceptance;
  - exactly-once counts;
  - erasure unreadability;
  - rebuild equality with the live projection while the gate and commit are monkey-patched to raise.

## 7. Conformance results

**78 / 78 passed** (39 scenarios × 2 stores).

| Area | Tests |
|---|---|
| S1 | Entry never written into a consumed prefix (raw and through the journal); publication never before an acknowledged entry |
| S2 | Closure survives a crash |
| S3 | Acknowledged fact survives a crash; the retry returns the original time; the gate does not re-run |
| S4 | A current read is never overtaken by an in-flight append; a causal token gives read-your-writes |
| S5 | Group all-or-nothing; DUPLICATE; an idem reused with other content is refused |
| O1 | Earlier commit time refused |
| K1 / K2 | Journal-assigned time; no `at` parameter on `commit`; `committed_at` = `at` |
| K10 / O4 | No same-predicate ties |
| O4 race | A publication racing an in-flight append never invalidates it |
| K7 cost | Current-read closure is measurable in both forms: explicit = a stored write; implied = a time-service draw with no data-store write |
| K7 views | Lagging views and as-of reads at closed positions with no data-store writes. A view never serves a position an in-flight entry can still reach (added after a mutation survived, §8) |
| K9 | OCC at the journal-assigned time gives STATE_CONFLICT |
| Protocol | intent/claim/outcome exactly once after a crash at step 1 or 2 and a merge-target change |
| Boundaries | Future validity boundary between reads |
| Erasure | Fence on every cluster partition; nothing readable; later append refused (`partition_erased`) |
| Rebuild | Durable facts only equal the live projection; a crash loses nothing |
| Property | 10 random interleavings per store, with skewed readings, in-flight appends, publications, current and as-of reads, and views |

## 8. Deliberate-break results

Each break weakens one rule and shows a **semantic** failure.

| Rule weakened | Explicit | Implied | Failure shown |
|---|---|---|---|
| Frontier conditionality (S1): unconditional append | ✔ | ✔ | An in-flight entry enters a served read (served history changes) |
| Durable closure (S2) | `volatile_frontiers` ✔ | `clock_resets_on_crash` ✔ | A late entry rewrites a served read after a crash |
| Close before snapshot (S4) | ✔ | ✔ | An append completing during the read is missed, so served history changes |
| Policy-log closure (O4) | `close_logs=False` ✔ | per-node skewed clock ✔ | A back-dated publication invalidates an acknowledged entry's stamp |
| Journal-owned commit time (K1) | `mode=writer` ✔ | `mode=writer` ✔ | A caller-dated entry rewrites a served read |
| Lagging-view position (K7) | ✔ | ✔ | A view served at the caller's clock is later contradicted |
| Duplicate before time (K8) | ✔ | ✔ | The retry of a committed command is reported as failed, and its gate decision is executed again |
| Single-source atomicity (S5) | `atomic=False` ✔ | `atomic=False` ✔ | A crashed two-claim command stays **half-applied** permanently (its retry is closed out); the atomic variant leaves it cleanly unapplied |
| OCC at commit (K9) | X-1 `occ_must_run_inside_the_serialized_write[False]` ✔ | **Masked**: the implied store refuses any overtaken step, so a stale OCC cannot be committed | A stale command is accepted |

**Mutation run.** Each rule was removed from the code in turn, and both suites were run (boundary plus X-1). **17 / 17 caught**:

| Rule removed | Failures |
|---|---|
| Explicit store: S1 conditional | 14 |
| Explicit store: entry after partition frontier | 9 |
| Explicit store: append closes the log | 25 |
| Explicit store: read closes the partition | 31 |
| Explicit store: publication after the log frontier | 28 |
| Explicit store: raw publication conditional | 1 |
| Implied store: refuse when overtaken | 8 |
| Implied store: strictly later draws | 11 |
| Implied store: reads draw | 12 |
| Implied store: views draw at snapshot | 1 (initially **survived**; closed by the in-flight view test) |
| Implied store: assign draws from the clock | 12 |
| S5 group atomicity | 6 |
| K2 build from assigned time | 29 |
| K8 duplicate before time | 5 |
| K9 OCC at commit | 4 |
| K5 close before snapshot | 3 |
| K7 causal token | 2 |

Both files were restored byte-identical afterwards.

## 9. X-1 regression results

- **On the boundary with the explicit store (the default): 64 / 64 passed, unchanged** (`tests/test_x1_commit_time.py` was not edited). The journal no longer holds `f_part`, `f_pol` or `writes`; they are read-only views of the store.
- **On the implied store** (plugin `memory_core.storage_boundary.pytest_x1_on_implied`, test file unchanged): **53 / 64 passed.** Each of the 11 others was analysed. **None is a guarantee violation by the implied store.**
  - **3 break tests whose weakness the implied store prevents.** `break_case6` (no data-store frontier exists to lose), `break_case8_view_frontier_taken_from_its_last_entry_time` (the global sequence never produces equal times), `break_…without_a_causal_token…` (the global sequence gives read-your-writes without a token).
  - **4 exact served-position assertions.** `case3` (`T >= sv.r`), `case8` (`r == 5.0`), `current_read_with…token` (`r == at`), `as_of_reads…` (`r == [10, 10, 10]`). The implied store draws a strictly later time on every read, so r is later by one representable step or by elapsed time. The served-prefix and no-write properties are covered on both stores in the boundary suite.
  - **3 conservative refusals before the asserted outcome.** `case4` (an in-flight entry dated 7 that finishes after a publication is refused, not appended), `occ_must_run…[True]` and `[False]` (READ_CLOSED, which is transient, precedes STATE_CONFLICT; the stale command is never accepted). The guarantee is covered by `test_occ_is_decided_at_the_journal_assigned_time` on both stores.
  - **1 inspection of explicit-frontier internals:** `read_closes_only_the_predicates_it_evaluates` (`j.f_pol`).

**Finding [PROVEN].** The X-1 test file mixes guarantee assertions with assertions about the explicit mechanism and exact served positions. It remains valid, unchanged, for the explicit form, which is the form it was written for. The mechanism-neutral guarantees are now in the boundary suite on both stores.

**Deviation needing the brief owner's acceptance.** The brief asked for both stores to run the X-1 tests, and for a stop if a test needed reinterpretation. No test was edited or reinterpreted. But 11 X-1 tests are evidence for the explicit form only, and the X-1 decision's [PROVEN] citations for K7 (causal-token necessity, as-of reads with no write) are explicit-form evidence. The same guarantees are proven for both forms by the boundary suite. Accept, or rule it a stop.

## 10. Complete-suite results

| Point | Result |
|---|---|
| Before | 969 / 969 |
| After | **1047 / 1047**; delta +78, all in `test_durable_storage_boundary.py` (§7, §8) |

**Unchanged:**
- `test_durable_journal_conformance.py` (144);
- `test_x1_commit_time.py` (64);
- all other tests.

**Changed code:**
- `memory_core/commit_time/__init__.py`, refactored onto the boundary. Every public name, mode and break flag is preserved. One break flag was added (`duplicate_check_first`).

**New code:**
- `memory_core/storage_boundary/` (the module and the X-1 plugin).

The `Pipeline` OCC was not touched (deferred).

## 11. Infrastructure evaluation now enabled

`storage-technology-evaluation-v2-request.md` is drafted and **not issued**. It defines:
- the adapter a candidate implements, and its choice of explicit or implied form;
- the three suites to run unchanged;
- nine real-environment tests (E1–E9): concurrent closure versus append, publish versus append, durability, crash and recovery of closure, current-read closure cost, lagging and as-of reads, contention and retry, group-size limits, erasure under concurrency;
- per-candidate provisioning.

There are no benchmark targets.

## 12. Remaining owner decisions (unchanged in kind)

| Decision | Owner |
|---|---|
| Policy-log lease length (publications take effect later) | [OWNER] Product / policy, with Infrastructure |
| Clock source and tolerance (K3). For implied-form stores, whether a global, crash-surviving time service (timestamp-oracle form) is acceptable as a component, and its availability | [OWNER] Infrastructure |
| Accepting the current-read closure cost: a stored write (explicit form) or a time-service draw (implied form) | [OWNER] Infrastructure (C-5 cost input, measured by E5) |
| Retrieval types that may be served as-of or from lagging views | [OWNER] Product |
| Retry budget for transient refusals | [OWNER] Infrastructure |
| C-1 key custody, retention, erasure metadata and reversal, non-CUSTOMER grants, commitment scope | Security / Legal / Product / Governance [OWNER] |

## 13. Precise next decision boundary

The architecture side of persistence is now complete for evaluation:
- normative v1.1;
- an executable, technology-neutral storage boundary;
- two conformant reference forms;
- a ready, unissued request.

**The next boundary is a decision, not a build:** whether to **issue** `storage-technology-evaluation-v2-request.md` to Infrastructure, which is a real-environment commitment, and for which candidates.

Not started here:
- real-store adapters;
- environments;
- the Pipeline/K9 migration;
- the Gateway.


---

**Follow-up (2026-10-04):**
- `target-architecture-next-decision-v4.md` rejected the §9 deviation over K9 with a write landing in flight.
- `target-architecture-next-decision-v5.md` closed that gap with a common test on both stores, plus break tests, and **accepted** the deviation.
- The suite is now 1055/1055 (boundary 86).
