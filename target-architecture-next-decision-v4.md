# Target Architecture: Next Decision v4

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Decision record only. No test, contract, code, environment or owner decision is changed by this document.

**Inputs:**
- `durable-journal-contract-v1.1-implementation-report.md`;
- `durable-journal-x1-decision-v1.md`;
- `durable-journal-rebuild-contract-v1.md` (v1.1);
- `storage-technology-evaluation-v2-request.md`;
- `tests/test_x1_commit_time.py` (read, not edited);
- `tests/test_durable_storage_boundary.py`.

**Labels:** [PROVEN], [INFERENCE], [OWNER], [STATED], [CONTRACT_GAP].

**DECISION: 5. REJECT DEVIATION / STOP.** One of the 11 tests represents a semantic guarantee (K9 under an in-flight interleaving) that no committed test proves for the implied form (§3, §4). The v2 request is therefore **not** evaluated for issue (§7–§8).

---

## 1. Current proven boundary

| Item | State |
|---|---|
| Contract | v1.1 (time, served-prefix immutability, K4–K10, S1–S5) |
| Boundary suite | 78/78 (39 scenarios × explicit / implied) [PROVEN] |
| Full suite | 1047/1047 [PROVEN] |
| X-1 | 64/64 on the explicit store; 53/64 on the implied store (11 tests fail; none edited) |

**"The prototype is green" ≠ "the guarantees are proven for both forms".** This record concerns only the second.

## 2. The X-1 deviation

The previous brief asked for the X-1 tests to run against both stores, and to stop if any test needed reinterpreting. The v1.1 report classified all 11 failures as mechanism-specific and asked for acceptance.

This audit re-reads each test definition. It replays each scenario on the implied store (scratch: `audit_implied.py`), and it maps coverage by mutation: each rule removed, failing test names listed (scratch: `k9_coverage.py`).

## 3. Test-by-test deviation analysis

"Covered" means a committed test that runs on **both** stores asserts the same guarantee.

| # | X-1 test | What fails on the implied store | Class | What the implied store actually does (replay) | Same guarantee covered for both forms? |
|---|---|---|---|---|---|
| 1 | `case3_equal_clock_readings…` | `T >= sv.r` (the read is served one representable step after T) | Exact position | T > 10; entry after r; times unique; invariants hold | **Yes:** `one_predicates_entries_and_publications_never_share_a_time` |
| 2 | `case4_two_subjects…skewed_clocks` | The in-flight entry dated 7 is expected to be APPENDED; the implied store refuses it (READ_CLOSED) | Conservative refusal | Refused (transient). The retry with the old stamp gives STALE_POLICY_STAMP; re-gated, it is APPENDED after T. The stale writer gets STALE after T. Invariants hold | **Yes.** Safety (no acknowledged entry under a stale stamp): `a_publication_racing_an_in_flight_append…` (both branches) plus `acknowledged_stamps_hold` in the property tests. Acceptance of the in-flight entry is permission, not a guarantee |
| 3 | `break_case6_closure_lost_on_crash…` | The weakening (`durable_frontiers=False`) has nothing to weaken: the implied store has no data-store frontier | Deliberate break, explicit-only | A late entry gets a time after the served r | **Yes:** `break_s2…[implied]` (time sequence rebuilt from the log) |
| 4 | `occ_must_run_inside_the_serialized_write[True]` | Expected STATE_CONFLICT; the implied store returns READ_CLOSED first | **Semantic guarantee (K9 under interleaving)**, observed as a conservative refusal | READ_CLOSED; its retry gives STATE_CONFLICT; never appended | **NO.** The boundary OCC test is not interleaved. Removing the in-write OCC check fails only `occ_is_decided…[explicit, implied]` (not interleaved) and two explicit-only X-1 tests. Removing the implied store's refusal of overtaken steps fails 8 implied tests, **none an OCC test** [PROVEN by mutation listing]. No committed test asserts, on the implied store, that a stale typed command is never accepted when a write lands between time assignment and the durable write |
| 5 | `occ_must_run_inside_the_serialized_write[False]` | The weakened OCC is masked: the implied store refuses first | Deliberate break, its counterpart | Stale command not accepted | **NO** (the same gap: no implied-form break shows the necessity of either protection) |
| 6 | `case8_lagging_view…` | `r == 5.0` (served 5 plus one step); `read_view(snapshot, s2) is None` (implied: s2 is servable at the global time) | Exact position plus mechanism (an absent explicit frontier means "not servable") | Served before the later entry; invariants hold | **Yes:** `lagging_views_and_as_of_reads…`, `a_view_never_serves_a_position_an_in_flight_entry_can_still_reach` |
| 7 | `break_case8_view_frontier_taken_from_its_last_entry_time` | No equal times exist under one global sequence, so the break cannot occur | Deliberate break, explicit-only | — | **Yes:** the in-flight view test (it caught the "views draw" mutation) |
| 8 | `as_of_reads_need_no_write…` | `rs == [10, 10, 10]`: the implied store serves at the reading (11, 30, 50) | Exact position | 0 data-store writes; 4 time-service draws; a later entry at > 50; invariants hold | **Yes:** `current_read_closure_cost_is_measurable…`, `lagging_views_and_as_of_reads…` |
| 9 | `read_closes_only_the_predicates_it_evaluates` | Inspects `j.f_pol` (empty for the implied store) | Internal inspection | The implied store closes **globally**: a read of s1/CITY refused an unrelated in-flight NOTE append on s2 | **N/A, not a guarantee.** v1.1 states the prefix a read consumes (a minimum), not a ceiling. Over-closure is permitted; its cost is liveness (E7) |
| 10 | `current_read_with_the_callers_causal_token…` | `sv.r == at` (plus one step) | Exact position | Sees its own write; invariants hold | **Yes:** `s4_a_current_read_with_the_callers_causal_token…` |
| 11 | `break_current_read_without_a_causal_token…` | The global sequence gives read-your-writes without a token | Deliberate break, explicit-only | Read-your-writes holds without a token | **Yes** for the guarantee (read-your-writes, test 10's counterpart). A token is a mechanism needed when assigners are skewed per node; the global sequence is stronger and satisfies the same contract |

## 4. Whether the original stop condition was triggered

- **Tests 1–3 and 6–11: case A/B, acceptable.**
  - Meaning unchanged.
  - Where the evidence was explicit-only, the boundary suite now asserts the same guarantee on both forms.
  - The implied store's differences make explicit-only failure modes impossible, or serve a later position. They do not change contract semantics: the stronger global ordering still satisfies K5–K7 and served-prefix immutability.
- **Tests 4–5: case C, triggered.**
  - The contract's K9 says OCC and the stamp are evaluated **inside the partition's serialized write**. That clause exists precisely for a write landing between time assignment and the durable write.
  - On the implied store that guarantee is protected by S1 refusal (and redundantly by the in-write OCC check). No committed test exercises this interleaving with a typed command on the implied form, and no implied-form break shows its necessity.
  - The scratch replay shows correct behaviour (READ_CLOSED, then STATE_CONFLICT on retry, never appended). That is [INFERENCE] from a scratch run, not committed proof.
  - **The deviation is therefore not acceptable as reported.** The report's sentence "the same guarantees are proven for both forms by the boundary suite" is not true for K9-in-flight.

**Report claim checked:** "None is a guarantee violation by the implied store." [PROVEN true for all 11 by replay: no served prefix changed, no stale stamp or stale command acknowledged.] But "no violation observed" is not "proven by a committed test", and for tests 4–5 only the former holds.

## 5. Evidence coverage comparison

| Guarantee | Explicit proof | Implied proof |
|---|---|---|
| Served-prefix immutability, stamps, K2 | X-1 + boundary + property | Boundary + property [PROVEN] |
| S1–S5 | Boundary (+ X-1) | Boundary [PROVEN] |
| K7 read-your-writes, views, as-of | X-1 + boundary | Boundary [PROVEN] |
| K9 at the journal time (not interleaved) | X-1 `case7` + boundary | Boundary [PROVEN] |
| **K9 with a write landing in flight** | X-1 `occ_must_run…[True/False]` [PROVEN] | **Missing** (scratch replay only) |
| Liveness under contention (refusal rate) | Not a contract guarantee | Not a contract guarantee. The implied store refuses unrelated in-flight appends (global closure) → E7 measurement |

**X-1 decision citations: minimum corrections** (not applied here):
- **K9:** `occ_must_run_inside_the_serialized_write` is explicit-form evidence only until a common test exists.
- **K7, causal token:** "necessary" should read "necessary when commit times are assigned by skewed per-node clocks; a global time sequence provides read-your-writes without one". Read-your-writes itself stays [PROVEN] for both forms through the boundary suite.
- **K7, as-of:** "need no write" should read "need no data-store write; the implied form draws from the time service". Already worded this way in v1.1.
- **§5 table cells for Cases 3, 4 and 8 (M-J):** explicit-form evidence. Cases 3 and 8 are covered for both forms by the boundary suite. Case 4's acceptance is permitted behaviour, not a guarantee.

## 6. Decision on deviation

**REJECT / STOP.**

**Missing proof:** K9 under an in-flight write, for the implied form, at two levels:
1. **Guarantee:** with a typed command prepared, another write to the same slot landing before its durable write, then the command's finish, the command is **never acknowledged**. Its final typed outcome, after any transient refusal and retry, is STATE_CONFLICT. This must hold on both stores.
2. **Necessity:** on the implied store, weakening both protections (refusal of overtaken steps and the in-write OCC check) makes the stale command acknowledged.

Nothing else in the 11 blocks acceptance.

## 7. C-5 readiness

**Not evaluated for issue.** Per the brief, the issue decision follows only an ACCEPT.

Recorded for when it is reached: the v2 request is written against v1.1 and uses the common suite. It keeps the explicit / implied choice per candidate open, has no benchmark targets, and does not treat PostgreSQL's A7 projection design as a journal. Its suite counts and its §2 statement ("11 tests are explicit-form evidence only") will need updating once the missing test exists.

## 8. Candidate issue scope

Not determined (§7). Firestore and PostgreSQL remain the only evidenced candidates; nothing here adds or removes one.

## 9. Chosen next action

**Close the K9-in-flight proof gap, then re-decide the deviation.**

Scope:
- Add to `tests/test_durable_storage_boundary.py`, parametrized over both stores, a common test for guarantee (1) in §6.
- Add a break test for (2), weakening both protections on the implied store and the in-write OCC check on the explicit store.
- Rerun the boundary suite, the X-1 file on both stores, and the full suite.
- Record the X-1 citation corrections (§5) as an evidence-scope addendum.

**No other change. `test_x1_commit_time.py` is not edited.**

## 10. Why alternatives wait

| Alternative | Why it waits |
|---|---|
| Accept as reported | Rejected: K9-in-flight is unproven for the implied form (§4) |
| Contract escalation | Not warranted. The two forms differ in mechanism, not in contract meaning. K9's text is unambiguous; only its proof is missing |
| Issue v2 (either candidate) | It would send Infrastructure a suite that cannot tell whether an implied-form candidate (for example one using a timestamp oracle) honours K9 under interleaving. That is the exact concurrency class real environments are needed for (E1, E7). The results would be repeated |

## 11. Exact stop / escalation condition (for the next action)

| Outcome | Next step |
|---|---|
| Both stores pass the new common test, and the break fails as expected | Re-decide the deviation (expected: ACCEPT), then make the v2 issue decision |
| The implied store **acknowledges** a stale command in the new test | **REJECT stands.** K4's implied form is not conformant as built → contract owner |
| Expressing the test needs a boundary operation that only the explicit form has | [CONTRACT_GAP] → contract owner |

## 12. Remaining owner decisions (unchanged; none blocks the next action)

- Policy-log lease length [OWNER].
- Clock source and tolerance, and acceptance of a global time service for implied-form stores [OWNER] Infrastructure.
- Current-read closure cost (a stored write or a time-service draw) [OWNER] Infrastructure, measured by E5.
- Lagging-read classes [OWNER] Product.
- Retry budget for transient refusals (including the implied form's global over-closure, E7) [OWNER] Infrastructure.
- C-1 key custody, retention, erasure metadata and reversal, non-CUSTOMER grants, commitment scope [OWNER].
