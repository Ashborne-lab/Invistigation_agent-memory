# Target Architecture: Next Decision v5

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. It closes one proof gap (test-only) and records decisions. The normative contract, `test_x1_commit_time.py`, the Pipeline and every production system are unchanged.

**Labels:** [PROVEN], [INFERENCE], [OWNER], [STATED], [CONTRACT_GAP].

**Decisions:**
1. **Deviation: ACCEPT.** K9 with a write landing in flight is now [PROVEN] on both forms (§3–§6).
2. **v2 request: READY TO ISSUE, for both Firestore and PostgreSQL.** It is not issued here: sending it is the act that commits real environments (§8–§10).

---

## 1. Current proven boundary

| Item | Before (v4) | Now |
|---|---|---|
| Boundary suite | 78 | **86 / 86** [PROVEN] |
| X-1 on the explicit store | 64 / 64 | **64 / 64** (file untouched) |
| X-1 on the implied store | 53 / 64 | **53 / 64**: the same 11, no new difference |
| Full prototype suite | 1047 | **1055 / 1055** (+8, all new tests in the boundary suite) |

## 2. The K9-in-flight proof gap

v4 found one guarantee proven only for the explicit form. K9 requires OCC to be evaluated at the journal-assigned time, **inside the serialized write**, so that a stale typed command is never acknowledged when the slot changes between its time assignment and its durable completion.

## 3. Common test and break test

All added to `tests/test_durable_storage_boundary.py`. Nothing existing changed.

**1. Common test (4 cases):** `test_k9_a_stale_typed_command_is_never_acknowledged_when_its_slot_changes_in_flight[order × kind]`.
- **Sequence (the X-1 scenario):**
  1. The slot is at version 1.
  2. The typed command (expecting version 1) is prepared, and its commit time is assigned.
  3. Another write to the same slot lands.
  4. The command finishes.
  5. Any transient refusal is retried **through the journal**: a new time, the checks run again.
- **Two orders:**
  - the intervening write is assigned *after* the command's time;
  - it is assigned *before* the command's time but finishes after it.
- **Assertions (mechanism-neutral):**
  - the final outcome is STATE_CONFLICT;
  - the command is never durable;
  - the slot's history is exactly [pune, goa];
  - served-prefix immutability, stamps and `committed_at` hold.
- **Not asserted:** the refusal path, the number of retries, times, or store internals.
- The writer side is only a record factory; **the journal performs the OCC**.

**2. Independence on the implied form (2 cases):** `test_k9_holds_on_the_implied_form_with_either_protection_alone`.
- **In-write OCC only** (refusal of overtaken steps disabled): STATE_CONFLICT.
- **Refusal of overtaken steps, with OCC checked outside the write:** STATE_CONFLICT. The refusal forces a fresh assignment, so the outside check sees the new version.

**3. Break (2 cases):** `test_break_k9_without_its_protections_a_stale_typed_command_is_acknowledged[kind]`.
- **Explicit:** OCC outside the serialized write.
- **Implied:** that, **and** refusal of overtaken steps disabled.
- **Architectural failure:** the stale command is **acknowledged** and creates version 3 (a CONFLICT including delhi) on top of version 2 (goa), which it never saw.

**Mutation of the real code paths:**

| Mutation | Common test result |
|---|---|
| In-write OCC check removed | **4 / 4 fail, on both stores.** On the implied store the refusal only delays the command; its retry is then acknowledged |
| Refusal of overtaken steps removed (implied) | Passes. The in-write OCC catches it |
| Both removed | 4 / 4 fail |

So K9 is proven on the implied form **independently** of the rule that happened to block the race in v4's replay. The in-write OCC is necessary on both forms [PROVEN]. Code was restored byte-identical (scratch: `k9_necessity.py`).

## 4. Results on the explicit store

- Common test: both orders pass. The command reaches STATE_CONFLICT directly.
- Break: the stale command is acknowledged.
- X-1: 64 / 64 unchanged.

## 5. Results on the implied store

- Common test: both orders pass. The command is first refused transiently (READ_CLOSED or COMMIT_TIME_REGRESSED), and its retry ends as STATE_CONFLICT.
- Each protection alone suffices. With both removed, the stale command is acknowledged.
- **No stale command was acknowledged in any non-weakened run** [PROVEN]. No stop condition was triggered.

## 6. Revised deviation decision: ACCEPT

The question was whether every semantic guarantee behind the 11 X-1 tests that fail on the implied store is either proven on both forms or legitimately mechanism-specific.
- **v4 §3, rows 1–3 and 6–11:** unchanged by the new evidence. Each is covered for both forms, or is mechanism-only (v4 §3).
- **Rows 4–5 (`occ_must_run_inside_the_serialized_write[True/False]`):** the guarantee is now [PROVEN] on both forms (§3–§5). Each X-1 test still asserts the explicit form's specific path (STATE_CONFLICT directly; acknowledgement when weakened). That makes them explicit-form evidence, with no change of meaning.
- **No contract ambiguity surfaced.** K9's text needed no reinterpretation.

## 7. Evidence-citation corrections (applied, minimum)

An **evidence-scope addendum** is appended to `durable-journal-x1-decision-v1.md`. The decisions are unchanged.

| Citation | Correction |
|---|---|
| K9 | No longer explicit-only: proven for both forms by the common test |
| Causal token | "necessary when commit times are assigned by skewed per-node clocks" (a global sequence gives read-your-writes without one) |
| As-of reads | "no data-store write; the implied form draws from its time service" |
| §5 table, Cases 3, 4 and 8 (M-J cells) | Explicit-form evidence. Cases 3 and 8 are proven for both forms; Case 4's acceptance is permitted behaviour |

**Not edited:** the normative contract. Its header still states 78 boundary tests and a 1047-test suite. These are executable-form counts, not semantics, to be refreshed at the next amendment.

## 8. C-5 readiness reassessment (fresh)

| Question | Assessment |
|---|---|
| Is v1.1 stable? | Yes. No semantic change since v1.1; this phase added proof only |
| Is the executable boundary complete? | Yes, for every C-5-critical guarantee: S1–S5, O1–O4, served-prefix immutability, K2, K5–K9 (now including in-flight K9), erasure, rebuild. All are proven on two genuinely different forms [PROVEN] |
| Can a candidate run the suite unchanged? | Yes. A connector plugin can register an adapter in `STORES`/`KINDS` before collection without editing the file: checked with a throwaway candidate, 42 cases collected. Guarantee tests then apply. Break tests need per-store weakening switches, so for a candidate they are optional. **Recorded in the request** |
| Is anything else a genuine prerequisite since v4? | No. **Two handoff requirements** (not architecture gaps), both now written into the request: one shared, technology-neutral concurrency driver for E1–E9, so results are comparable across candidates; and the connector mechanism above |
| Do owner parameters block evaluation? | No. Lease, clock source and tolerance, the time service's acceptability, the closure cost, lagging-read classes and retry budget are **what E5 and E7 measure**. C-1, retention and the rest are off this path [OWNER] |
| Does the request avoid repeated work? | Yes. It is written against v1.1 and the common suite, keeps the explicit/implied choice open per candidate, defines E1–E9 by guarantee and what to record, has no benchmark targets, does not treat A7 as a journal, and does not treat emulator results as production evidence |
| Is real-environment evaluation now the highest-value next step? | Yes. Every remaining unknown on the C-5 path is a real-environment property: isolation under concurrency (the P5-conc emulator gap), durability, closure cost, contention and limits. No further in-memory work can reduce it [INFERENCE] |

**"The prototype is green" and "the architecture has sufficient evidence for C-5" are now both true, for different reasons.** Green means every in-memory guarantee is proven on two forms. Sufficient means the only open C-5 questions are ones that real environments must answer. **Neither means C-5 is decided.**

## 9. Decision on issuing v2

**READY TO ISSUE. Not issued in this task.** Sending it is the act that commits real environments, which is outside this phase's authority (and the brief forbids issuing).

`storage-technology-evaluation-v2-request.md` is updated factually:
- status "ready to issue";
- 86 boundary tests;
- the K9-in-flight coverage;
- the connector mechanism;
- break-test applicability;
- the shared concurrency driver.

The nine environment tests E1–E9 are preserved unchanged. No benchmark was added.

## 10. Candidate scope: both Firestore and PostgreSQL

| Candidate | Why it is included | What the evaluation must build first (part of the evaluation, not a prerequisite) |
|---|---|---|
| Firestore | The production store (F2). The emulator showed the exact concurrency uncertainty that only a real project resolves (P5-conc) | A `StorageBoundary` adapter. The existing emulator adapter implements the v1 interface only. Explicit form likely [INFERENCE]: the record must carry `at` before commit (K2) |
| PostgreSQL | The prior design target (A7). C-5 is a comparison, and Firestore alone gives Infrastructure nothing to compare against | A journal adapter: no journal design exists (A7 is a projection behind Firestore). Explicit form likely [INFERENCE]: head rows locked, and a guarded clock, never `now()`. The interface and suite fully specify what it must do, so the work is building to a specification, not research |

**No other store** is added. Nothing is selected.

## 11. Exact next boundary

**An owner act:** sending `storage-technology-evaluation-v2-request.md` to Infrastructure for both candidates. Results then return as evidence for **C-5, which Infrastructure decides.**

**Out of scope until then:**
- real-store adapters;
- environments;
- Pipeline/K9;
- the Gateway.

## 12. Remaining owner decisions

- Policy-log lease length [OWNER] Product / policy, with Infrastructure.
- Clock source and tolerance; whether a global time service (timestamp-oracle form) is acceptable for implied-form stores [OWNER] Infrastructure.
- Current-read closure cost (a stored write or a time-service draw) [OWNER] Infrastructure, measured by E5.
- Lagging and as-of read classes [OWNER] Product.
- Retry budget for transient refusals, including the implied form's global over-closure [OWNER] Infrastructure, measured by E7.
- Issuing the v2 request [OWNER] (the act in §11).
- C-1 key custody, retention, erasure metadata and reversal, non-CUSTOMER grants, commitment scope [OWNER] Security / Legal / Product / Governance.
