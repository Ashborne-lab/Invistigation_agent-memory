# Memory ↔ Contract Reconciliation (Track A)

**Date:** 2026-09-28. **Status:** v2, after council review.

**Method.**
- Three reconciliation agents each took one slice of the contract:
  1. objects, authority and extraction;
  2. deletion, T3 and identity;
  3. time, mutation, retrieval, authorization and §16.
- A council of three independent reviewers then attacked the v1 draft:
  - **A**, a contract lawyer;
  - **B**, a failure hunter;
  - **C**, an identity and security reviewer.
- Every council finding is either absorbed below or recorded as a dissent (§11).

**Scope.** This document changes nothing in the contract, the MAD, the investigation, the identity documents or any code.

**Sources:**
- `artifacts/architecture-contract.md` v2.0, cited as `:line`;
- `investigation/memory-architecture-decision.md`, cited as **MAD §x**;
- `investigation/agent-memory-investigation.md`, cited as **INV**;
- the identity docket and patch draft, cited as **Q/X/R-n** and **PI-n**.

Code is cited at `origin/main`: runtime `daee3f9`, studio `1f05ca11`.

**Labels:**
- `[CONTRACT]`: the contract says it.
- `[CODE]`: the implementation does it.
- `[DERIVED]`: a consequence of the above.
- `[UNDECIDED]`: the documents are silent. No rule was invented.
- `[BLOCKED — PENDING JAY]`: Jay decides.

---

## 1. Answer to the core question

> *Can the MAD be inserted into the contract without contradictions, ambiguous authority, broken invariants, or identity conflicts?*

**Not as written.** It becomes consistent with:
- **8 required contract edits** (§7.1);
- **5 clarifications** (§7.2);
- **29 corrections to the MAD** (M1–M27, plus M5b and M6b; §8.7);
- **5 items blocked on Jay** (§6);
- **22 points recorded as `[UNDECIDED]`** (§8.4).

**Semantic closure is not claimed.** It needs the blocked and undecided items to be resolved first.

**Where the defects sit.** Most of them are in the MAD. The contract already gets the following right, and the MAD departs from each silently:
- lineage-based support (`:781`);
- no pick-by-recency between independent sources (Ex.7);
- historical valid-time queries (Ex.2);
- a `state_version` per slot (`:127`);
- the §11 result contract;
- historical labels, where `source` is a MUST (`:679`);
- **typed retrieval operations** (`:657`: "no generic memory answer"; MAD `recall_memory` conflicts with this).

**The contract's own genuine defects:**
- the §10 fence wording measures from worker start (`:774`, Ex.13 `:1224`);
- the tension inside the contract between `:23` (evidence is immutable) and §10 (evidence is deleted), and that tension also collides with rule 7 once erasure physically removes evidence;
- `:18`'s rule that the five classes "MUST NOT be merged";
- the missing statuses PI-6 requires;
- an internal contradiction between Ex.1 and Ex.20 over interval conventions, and between both examples and `:1434`;
- an undefined value domain for `llm_write_mode`, and model-chosen keys that can escape authority.

**Identity.**
- **The v1 draft's E3, E5 and E7 contradicted settled policy** (PI-6, Q17, PI-4.4, R2). The council caught this and this version corrects it.
- **With the v2 edits, no settled identity decision is contradicted.** One clarification of the PI-4 patch is still needed: B still accepts *lifecycle* transitions (C-8, §7.2).

---

## 2. Reconciliation matrix

**Status values:**
- **COMPATIBLE**: already consistent.
- **CLARIFY**: the contract implies it, but the wording is ambiguous.
- **AMEND**: the contract must change.
- **MAD-FIX**: the contract is right and the MAD must change.
- **BLOCKED**: pending Jay.
- **IMPL**: an implementation detail only.
- **UNDECIDED**: the documents are silent.

### 2.1 Object classes and authority

| # | Memory decision | Contract | Status | Why | Action | Owner |
|---|---|---|---|---|---|---|
| O1 | Memory is not a stored object: Claims plus Narrative | `:18` "MUST NOT be merged"; `:54`; `:68`; `:13` (the distinction is reserved to the contract) | **AMEND** | Code: an untyped `facts[]` list [CODE]. The contract already overlaps Memory with Claims (`:68`) | **E2** | Architecture |
| O2 | Agent-scope lessons (`owner_lessons`, `workflow_agent_memory`, learned patterns) | `:54` "lessons" | UNDECIDED / BLOCKED | E2 must leave a placeholder, not an exhaustive list. Learned patterns are **R-M2** | Placeholder in E2 | Architecture; Jay |
| O3 | Keyed Claims, including open namespaces | `:27`, `:178` | **AMEND** | Open keys without a policy make MAD §I a universal rule | **E11** | Architecture |
| O4 | Immutable content, derived effective `valid_until` | `:1434`; Ex.1 `:1037`; Ex.20 `:1339` | **AMEND** | The contract contradicts itself: it has two interval conventions, and its examples write `valid_until` | **E12** | Architecture |
| O5 | Support counters | `:447-450`, `:779-781`, Ex.14 | MAD-FIX | Counters cannot evaluate "E1 was the only support" | Support is a set of lineage edges per evidence item (M5) | Memory |
| O6 | Source folded into mode | `:32` `source` | MAD-FIX | The source axis and the derivation axis are separate | Keep `source` separate (M6) | Memory |
| O7 | Replace `extraction_confidence` | `:27` ("carrying", not a MUST), `:434` "may carry", `:444` | **CLARIFY** | It is **not** a required field [CONTRACT] (council A). The `:432` heading says "Four" measures but the list has **five** | **E4** | Architecture |
| O8 | `confirmed` (assent to an agent proposition) | `:22-23`, `:27` | **AMEND** | Nothing today stops agent text supporting a user Claim [CONTRACT]. The code does exactly that at `agent_memory_service.py:303` [CODE] | **E1** | Architecture |
| O9 | `value_check` gating resolution eligibility | §6 step 3 `:465` | AMEND (inside E11) | Eligibility has no stated criteria | E11 | Architecture |
| O10 | Acceptance gate vs `llm_write_mode` | `:188-200`, Ex.12, `:13` | **AMEND** | The value domain is undefined; the registry model is reserved to the contract (`:13`) | **E11** | Architecture + Security |
| O11 | Operator correction authority | Authority matrix `:1596-1816` | UNDECIDED | MAD §I.6 invents a default | Ranks per predicate class | Domain owners |
| O12 | No persistent inference | `:1761-1786`; **Ex.20 step 3 `:1344` persists an inference** [CONTRACT] | **BLOCKED (R-M1)** | The contract permits it and demonstrates it | See §6 | Jay |
| O13 | Episode summaries as Narrative Memory | `:59-61` | MAD-FIX | MAD episodes lack `retention_class` and `security_class` | M14 | Memory |
| O14 | Suppression fingerprints | `:18` | UNDECIDED (class) / **answered (form)** | Form: it **must be keyed**, per subject, with the subject inside the HMAC (council C; D2/PI-11 precedent). The class is undecided: a control record like PI-7, or a new class. It must not be the Firestore doc id (MAD E.3 does that) | M21 | Architecture + Security |
| O15 | Sensitive categories | `:197` | MAD-FIX | MAD L.8 bars `stated` but allows `normalized`, which is inconsistent | M15 | Security / Legal |
| O16 | Security keys reached through model-chosen keys | `:430` ("under any framing"), `:178`, Ex.12 `:1216` | **AMEND (in E11)** + MAD-FIX | `note.admin_access` or `residence.billing_address` escapes authority. Ex.12 requires a security-anomaly log | E11 (a model-chosen leaf key carries no authority); M16 | Security |
| O17 | Claim id = `hash(subject, evidence, key, value)` | E5 (value destroyed), manifests | MAD-FIX | A low-entropy value can be recovered from the id. Precedent: `memory_doc_id` is an unsalted truncated SHA-256 (`agent_memory_service.py:92-97`) [CODE] | The claim id is keyed or value-free (M22) | Memory + Security |

### 2.2 Time, mutation and projection

| # | Memory decision | Contract | Status | Why | Action | Owner |
|---|---|---|---|---|---|---|
| T1 | MAD §I as one global order | `:178`, `:194` | AMEND (via E11) | The order must be per predicate | E11 | Architecture |
| T2 | Same-source change of mind | `:419-421`, `:502`; Ex.1, Ex.20 | **CLARIFY** | The examples already supersede. Plain "later valid time wins" fails for "moving to Pune in October" followed by "cancelled, staying in Delhi" (council B F12) | **E7** | Architecture |
| T3 | Later-observed beats an independent source outside a "window" | Ex.7, `:491-503` | MAD-FIX | This is picking by recency between independent sources | Drop the window (M1) | Memory |
| T4 | Merged members as sources | R2 | **Answered for resolution (R2 → CONFLICT)**; support counting is UNDECIDED | E7 must say it is "subject to R2" across members | E7 | — |
| T5 | Time fields and precision | `:370-381` | CLARIFY (via E12) | The transition time generalises `invalidated_at` | E12; the precision rule is UNDECIDED | Architecture |
| T6 | §F.1 drops superseded claims from valid-time queries | `:404-417`, Ex.2 | MAD-FIX | Gurugram case, as_of 07-15: the MAD returns `UNKNOWN`, but the right answer is Delhi | M2 | Memory |
| T7 | `claims_version` used as `state_version` | `:127-133`, rule 1 | MAD-FIX | False `STATE_CONFLICT`s | M3 | Memory |
| T8 | Extraction commits without OCC | `:731`, rule 5 | **CLARIFY** | `:132-133` already expects `state_version` to advance with "no agent mutation" | **E6** | Architecture |
| T9 | A later statement clears `CONFLICT` | `:238-249`, `:503` | UNDECIDED | Which claim classes count as `RESOLVE_CONFLICT` | E6 records it; the values are UNDECIDED | Architecture |
| T10 | Deterministic claim ids | `:595-597` | COMPATIBLE for idempotency; MAD-FIX for security | See O17. Support must be keyed by evidence id | M4, M22 | Memory |
| T11 | Watermark = last message id | `:607-629` | MAD-FIX | Out-of-order delivery breaks it; after a merge it must be a vector | M5b | Memory |
| T12 | §F.1 output | §11 `:832-844` | MAD-FIX | Several fields are missing | M6b | Memory |
| T13 | A valid-time boundary passes without re-resolving | `:44` ("currently valid Claims"), `:593` | MAD-FIX | The contract already defines current state over currently valid claims. A projection that ignores a passed boundary is simply stale. Council B's race (a commit at T+ε against an expired value) is fixed in the MAD, not the contract | M7: boundaries ≤ t are applied at read and commit time, before the `expected_*` checks | Memory |
| T14 | Head stale after a policy, member-set or B-side change | `:780`, `:794` | MAD-FIX | Staleness not detected | M7 | Memory |
| T15 | Expiry treated as freshness | `:202-207` (freshness is on every policy), `:213` | MAD-FIX | Valid-time expiry is not freshness. **No contract edit is needed**: E9 is withdrawn (council A) | M8 | Memory |
| T16 | Stale volatile T0 slot hidden | `:225` | MAD-FIX | It must stay `VALUE` with `freshness_status = STALE` | M8 | Memory |
| T17 | iPhone "sold" resolves to `UNKNOWN` | Ex.20 `:1351-1352`, `:757` | MAD-FIX | `:757` already makes the `CLEAR` outcome policy-dependent | M10 | Memory |
| T18 | One `retract` for both "no longer true" and "never was true" | `:756` RETRACT vs INVALIDATE | MAD-FIX / UNDECIDED | The two need opposite answers for the past interval | M11 | Memory |
| T19 | Serialised commit per subject | §2 `:81-93` | COMPATIBLE / IMPL | — | — | Engineering |
| T20 | Mutable member-set slot on the survivor | `:173` | CLARIFY (PI-4 patch) | One `state_version`. B-side changes re-resolve A | §7.2 note; M12 | Identity patch owner |

### 2.3 Deletion, erasure and identity

| # | Memory decision | Contract | Status | Why | Action | Owner |
|---|---|---|---|---|---|---|
| D1 | Fence stamped on evidence | `:774`, Ex.13 `:1224` | **AMEND** | "When it starts" lets a later-started job pass. The code has no fence at all [CODE] | **E3** | Architecture |
| D2 | Scope chain narrowed to org, subject and episode | `:765-771` | MAD-FIX | "Every deletable scope class". Episode ≠ session | E3 says "every deletable scope"; the conversation unit is UNDECIDED | Architecture |
| D3 | Separate counters for erasure and merge | PI-4.4, PI-9, Q18, Q20 | MAD-FIX | "A single counter cannot do both" is false. The settled wording is "**rejected** … re-targeted" | E3 uses the PI-4.4 wording (M13) | Memory |
| D4 | Re-target onto an erased survivor | PI-9 | MAD-FIX + AMEND | Mainly the MAD bumps only "that scope", which violates PI-9. Clause (c) is still needed for the race between enumeration and merge | E3(c); M13 | Memory |
| D5 | Merge epoch recorded at ingestion only | PI-6, Q17, X2 | **AMEND** | **Council B F1 and C C-1 (BLOCKER).** Pre-merge evidence committed during the merge would escape quarantine on undo. Merges must be recorded **both** at ingestion and at commit | E3 | Architecture |
| D6 | Undo leaves A's claims superseded by quarantined claims | PI-6 | MAD-FIX | A's slot stays `UNKNOWN` | M17 | Memory |
| D7 | Quarantined claims restored in place | PI-6 ("never assigned to A or B"), Q17 | **AMEND (fixes E5 v1)** | **Council A #6 and C C-4 (BLOCKER).** A quarantined claim is terminal. Recovery creates new claims | E5 | Architecture |
| D8 | Hard erasure | `:23` vs §10 `:765`, `:779-781`; Ex.13, Ex.20 step 6; rule 7 | **AMEND** | The contract is **internally in tension**: evidence is "immutable" yet also "deleted". Erasure also collides with rule 7, because agent decisions are evidence (`:22`) | **E3b + E13** | Architecture + Legal |
| D9 | Invalidated evidence as a derived input | `:780` | AMEND (in E3) | `:780` covers retrieval only | E3 | Architecture |
| D10 | Replaying the erasure record on restore | none | **AMEND** (required for the erasure invariant; council A dissents, §11) | Without replay, a restore resurrects erased data. Merge-undo records must be replayed too (council B F7) | E3b | Architecture + Ops |
| D11 | Epoch stored in a doc that erasure deletes | — | MAD-FIX | The counter resets | E3 (counters survive) | Memory |
| D12 | Forget-fact redaction | rule 3, `:756`, `:1434`, `:40` | **BLOCKED (Legal)** for destroying content; CLARIFY otherwise | Whether a per-fact forget counts as the "legal policy" of `:756` is Legal's call. `:1434` must be edited if redaction is adopted | E5 (conditional) | Legal |
| D13 | Summary jobs and echoing agent turns after a forget | — | MAD-FIX | — | M19 | Memory |
| D14 | Anchor quotes from erased evidence | `:781` | MAD-FIX | — | M20 | Memory |
| D15 | Transfer while work is queued; split subjects | PI-10 | UNDECIDED | What moves, whether evidence moves, whether work re-targets across orgs. E3 fails closed until this is decided | Architecture + Identity | Identity + Memory |
| D16 | Consent / "stop remembering me" | `:707` | COMPATIBLE | — | — | — |
| D17 | Org erasure = O(1) bump | `:774` | COMPATIBLE after E3 | — | — | — |
| D18 | Queued jobs fenced | Q20, PI-12 row 8 | COMPATIBLE | Row 8 **by reference** to the Q20 table (council C C-13). The semantic rule lives in §10 (E3), not §16 | — | Ops |
| D19 | R6b hidden members | PI-9; docket R6b | **BLOCKED (R6b)** | Clause (c) is safe under both branches and is adopted. Three things depend on R6b: whether rejection of a hidden member's work is final (reject vs defer), physical removal before the window closes, and new inbound messages for hidden members | §6 | Jay |
| D20 | Erasure reaching quarantined material after an undo | Q14, PI-9 | **AMEND** (council C C-7) | After an undo, quarantined material belongs to no member, so erasing B would miss B's quarantined claims | E3b: erasure by `source_member_id` | Architecture |
| D21 | B "accepts no further writes" vs lifecycle writes on B | X2, PI-4.4; `:781`; E5 | CLARIFY (PI-4 patch) | Status changes, redactions and invalidations on B are still required (council C C-8) | §7.2 | Identity patch owner |
| D22 | Erasure enumeration racing a merge | PI-9 "in force at the time" | UNDECIDED / CLARIFY | Evidence on the not-enumerated survivor keeps the erased person's data (council B F9) | Serialise enumeration against merges | Identity |
| D23 | Cross-member supersession at commit (Case 8) | X2, PI-4.2, PI-6 | **Answered** | It happens only at read time. No transition is written onto B (council C) | — | — |

### 2.4 Retrieval, context, caching and authorization

| # | Memory decision | Contract | Status | Why | Action | Owner |
|---|---|---|---|---|---|---|
| R1 | One `recall_memory` tool with `include_history` | `:655-675` ("no generic memory answer") | **MAD-FIX** (council A) | The contract already defines `get_current_state`, `search_history` and `search_memory` | Use the typed operations (M23) | Memory |
| R2 | Precedence #1, "the user message beats T0" | `:428`, Ex.5, `:178` | MAD-FIX | A user statement doesn't override billing | M24 | Memory |
| R3 | T0 vs un-extracted evidence | — | UNDECIDED | The race is PRESENT in code [CODE] (INV §6) | Mechanism UNDECIDED. Council B's decidable proposal is in §8.4 | Architecture |
| R4 | Rendering labels | `:679` (MUST: status, `valid_from`, `valid_until`, **source**, scope) | MAD-FIX | The MAD omits several of these | M6b | Memory |
| R5 | Prompt manifest | `:393-400`, rule 7 | COMPATIBLE | The contract already requires the decision record | — | — |
| R6 | No vectors; lexical candidates re-validated | `:14`, `:644-653` | COMPATIBLE | — | — | — |
| R7 | "Never in a cached prefix" | Contract silent; `:14` | IMPL | Caches are replaceable projections under `:780`. The code puts memory in the cached block by default [CODE] | — | Engineering |
| R8 | Per-row org and grant checks | §6 step 9 | CLARIFY (E8) | They are never used to choose the claims that resolve a slot. Query-time org scoping is still allowed | E8(0) | Security |
| R9 | No direct client memory reads | `:2430` (authorized retrieval), `:780`, E5 | MAD-FIX, **not dependent on R-M4** (council C) | Noesis reads through Firestore rules (`firestore.rules:692-695`) [CODE]. Only *which* roles is R-M4 | Retire the direct read | Security |
| R10 | Memory-read roles | §6 step 9 | BLOCKED (R-M4) | §6 | — | Jay |
| R11 | G1 60 s caching | PI-12 row 6, Q19 | COMPATIBLE | Forget-fact is a deletion, memory export is an export, and both are already online by the PI-12 list | — | — |
| R12 | Adapters and memory core | `:12`, `:14` | IMPL | — | — | — |
| R13 | **Evidence store open to clients** | `:23` (immutable) | **CODE-vs-CONTRACT conflict** (council C C-12) | `agent_messages` is on neither exclusion list of the catch-all, so **any signed-in user reads and writes any org's messages** (`studio@1f05ca11:firestore.rules:888-959`) [CODE, verified]. MAD evidence stamps (`author_role`, epochs, `context_suppressed`, manifest) could be forged. The new MAD collections would also default to open | MAD precondition: server-only rules on `agent_messages` and every new memory collection, **before P3** (M25). No contract edit | Security |

### 2.5 Synchronous vs asynchronous (§9 plus PI-5)

**Synchronous:**
- exact-lane resolve and merge;
- consent directives;
- for forget-fact and forget-me: invalidation, the epoch bump and exclusion (`:777-780`). Hard delete and regeneration may be async. Hidden R6b members are BLOCKED;
- T0 / `get_current_state`;
- typed searches within a turn;
- the manifest write;
- re-resolving A inside `MERGE_SUBJECTS`.

**Asynchronous:**
- extraction and claim commit (E6);
- summaries;
- enrichment;
- indexing;
- rebuilds;
- eval.

**UNDECIDED:** registered operational slots fed only asynchronously. `:705` puts current-state mutation in the synchronous list, and the matrix says "via typed state command".

---

## 3. Patch verdicts (the MAD's T1–T7)

| Draft | Verdict | Now |
|---|---|---|
| T1 | NEEDS REVISION | **E1** (REQUIRED) |
| T2 | NEEDS REVISION | **E2** (REQUIRED) |
| T3 | NEEDS REVISION: fails scenarios (b) and (c), a pre-merge commit during the merge (F1), and Q17 recovery (F2); it is source-side only | **E3 + E3b** (REQUIRED) |
| T4 | NEEDS REVISION → mostly UNNECESSARY | **E4** (CLARIFY); the source enum becomes MAD-FIX |
| T5 | NEEDS REVISION. The v1 "restore in place" contradicts PI-6 | **E5** (REQUIRED; the redacted part is BLOCKED on Legal) |
| T6 | NEEDS REVISION: largely already in the contract (`:844`, `:692`, `:395`, `:14`); precedence #1 is wrong | **E8** (CLARIFY) plus MAD-FIX |
| T7 | NEEDS REVISION: S-5 and S-7 are IMPL; S-6 → MAD-FIX; rows 6 and 8 by reference; R-M3 row BLOCKED | none required |
| v1 E9, E10, E13-rule-3 | Withdrawn (UNNECESSARY) | T15, T13 → MAD-FIX |

---

## 4. T3 counterexamples

Notation: `E@X[m]` is evidence on X ingested during merge m.

| Scenario | v1 wording | v2 E3 |
|---|---|---|
| (a) Ingest, then episode erased, then merge, then commit | Rejected | Rejected: the evidence is missing by erasure |
| (b) `E@B` → merge B→A → erasure through A → late commit | MAD resurrects A | (c): a subject on the `merged_into` path was erased → rejected. PI-9 also bumps B |
| (c) `E@B[m1]`, then undo, then commit | Escapes quarantine | Recorded merge m1 undone → quarantined, attributed to no member |
| **F1** `E@B` before any merge → merge m1 → commit to A → undo | **Escapes quarantine** (v1 BLOCKER) | Merge m1 was traversed at commit and recorded → undo quarantines it |
| **F2** Q17 recovery from `E@B[m1]` after undo | **Recovery impossible** (v1 BLOCKER) | Q17 exception: a new claim from the subject's own user evidence |
| Chained C→B→A, B's episode erased | Over-rejects every `E@C` | (c) checks *subjects* and the org only, not episodes on the path |
| Two anchors, one erased (F3) | Ambiguous; could leak the erased content | The whole write is rejected. Re-derivation is a new write |
| Transient unavailability (F4) | Rejected finally, lost | Deferred. The watermark does not pass it |
| Quarantined claim, then forget-fact, then restore (F5) | Forgotten fact returns | Restore is itself a derived write (fenced), and redaction reaches every status |
| Transfer during a job (F6, d) | Undefined cause, so fails open | **Fails closed**: any advance not caused by a merge rejects. D15 stays UNDECIDED |
| Restore during an undo (F7) | Undone merge comes back | Merge-undo records are replayed first (E3b) |
| Erasure races a merge (F9) | Survivor keeps the data | UNDECIDED (D22), for Identity |
| Undo then re-merge (F14) | Subject unstated | Quarantined under the evidence's source member, attributed to none |

---

## 5. Hidden-contradiction cases

| Case | Deterministic? | Answer / gap |
|---|---|---|
| 1. Historically true, not current | Yes, with M26 | Past-tense claims carry `valid_until ≤ observed_at` (`:1756` already mandates an interval). Known vs unknown valid time is UNDECIDED |
| 2. Valid claim, evidence expired | **BLOCKED (R-M3)** | `:779-781` invalidates. See §6 |
| 3. Erased claim in a backup | Yes, with E3b | Erasure, redaction, suppression and undo records are replayed |
| 4. Merge, then undo | Yes, with E3, E5, M17, M18 | F1 and F2 fixed; recovery creates new claims |
| 5. Same-authority disagreement | Partly | Same source: E7. Independent sources: CONFLICT (Ex.7). Across members: R2. `RESOLVE_CONFLICT` classes are UNDECIDED |
| 6. Operator vs later user | No | UNDECIDED (O11) |
| 7. Extraction across an erasure | Yes (E3) | — |
| 8. Extraction across a merge | Yes | Re-target; supersession across members only at read time (D23) |
| 9. Transfer with work queued | Fails closed | D15 UNDECIDED |
| 10. Manifest references an erased claim | Mostly | The manifest keeps ids only. Ids must be keyed or value-free (M22). Dangling resolution is UNDECIDED. The echoing turn needs M19 |
| 11. Stale projection | Yes, with M7 | — |
| 12. Policy change after claims exist | No | Supersession bound to its policy version vs computed at read (M27) is UNDECIDED. Who classifies a change as breaking is UNDECIDED |
| 13. Unverified Hindi/Telugu value | Yes, with M9 | An unverified claim supersedes and the slot becomes UNKNOWN; a verified restatement promotes it; verification is a recorded transition |
| 14. "Why?" after evidence expired | **BLOCKED (R-M3)** | Plus: `confirmed` must store its `prompt_ref` quote |
| 15. Forget, then repeat | MAD self-contradiction | MAD C.1 scopes suppression to "retained evidence", while D.4 blocks it forever. Coupled to O14. UNDECIDED (Legal/product) |

---

## 6. Blocked by Jay: the contract consequence of each answer

| Item | Permissive answer | Restrictive answer |
|---|---|---|
| **R-M1** inference | No change. `:1761` already permits it. E4 gains an `inferred` mode. Lineage hangs on the base claims. `:781` must extend to base-claim supersession (UNDECIDED). A ban on sensitive categories is added | AMEND Ex.20 step 3 `:1344` (drop it, or make it stated) and the `:1761` row ("read-time only") |
| **R-M2** learned-pattern content | A §10 `:796-824` dataset declaration; Legal classifies | No contract change |
| **R-M3** evidence retention | Indefinite: no change | Bounded: AMEND `:779`, "retention expiry removes Evidence content but preserves the lineage record; dependent Claims keep their own `retention_class`". Legal classifies the stored quote. Add a §16 row (Legal owns the number; backups ≤ window ≤ erasure deadline). **E3b's `:23` wording deliberately leaves out "retention expiry"** so as not to pre-empt this |
| **R-M4** memory-read roles | Org membership at step 9 | A named role (60 s capability); export online. Per-sensitivity roles are still step 9. **Retiring the direct Noesis read does not depend on this** (R9) |
| **R6b** erasure through a wrong merge | Recommended branch: E3 **defers** (does not finally reject) work on hidden members inside the window. E3b does **not** physically remove hidden members until the window closes. How new inbound messages for hidden members are handled is Jay's decision | Erase all: final rejection and immediate removal for every member |

Clause (c) of E3 is adopted under both branches.

---

## 7. Contract edits

### 7.1 Required (8)

**E1. Agent output as evidence** (`:23`, appended)

> "Agent output — agent messages and agent-supplied tool arguments, including any echo of them in a tool result — is Evidence only that the agent said, decided or requested it. It never supports a Claim, with one exception: a Claim about a subject MAY take its content from an agent proposition that the subject explicitly assented to in their own Evidence referencing that proposition. That assenting Evidence is then the Claim's support; the Claim's source and authority are the assenting subject's, never exceeding what that subject may establish for the predicate; and agent output never counts toward `evidence_count`, `independent_support_count` or `source_diversity`. Results produced by trusted tools, other than echoes of agent arguments, are observations. Agent output never establishes a capability or authorization. Caller-stated identifiers surfaced by the agent are person-resolution evidence under the identity rules, not Claims."

**E2. Memory as a category** (`:18`, `:54`)

- **`:18`:** "…The non-overlap rule applies among Evidence, Claim, Current State and Narrative Memory. Memory is the category defined below and is realised by them."
- **`:54`:** "Memory is retained knowledge intended for future retrieval. It is realised by Claims, in any status other than invalidated, quarantined, redacted or pending erasure, always labelled with their status, and by Narrative Memory (`:68`). It is a retrieval category, not a separate store, and is subject to §10. *(The classification of agent-scope lessons: `[UNDECIDED]`.)* Memory does not automatically become Current State."
- A note records that PI-4.2's "Memory row" refers to storage realising this category.

**E3. The fence** (replaces `:774`; Ex.13 `:1224` is reworded to "E500 ingested with CUSTOMER:C9 = 17")

> "A write derived from Evidence carries, for each input Evidence record (direct or through derived inputs), the generations of that record's deletable scope chain as they were at ingestion, and the id of every merge in force over its subject at ingestion. The committed write also records every merge traversed on the `merged_into` path at commit.
> The write is rejected, whole, if:
> (a) any input Evidence has been removed by a recorded erasure, or is INVALIDATED or `context_suppressed`;
> (b) any scope in that chain has had a generation advance not caused by a merge since ingestion; or
> (c) any subject reached by following `merged_into` from the input's subject, or the organization, has been erased since the earliest ingestion among the write's inputs. A `merged_into` link that cannot be resolved counts as erased.
> A rejected write is never committed with an input removed. Re-derivation from the remaining Evidence is a new write.
> Transient unavailability of an input defers the write rather than rejecting it.
> A generation advance caused by a merge rejects the write against the absorbed subject; the write is re-targeted through `merged_into` to the survivor.
> If any merge recorded for the write has been undone by commit time, or is undone later, the write is `quarantined`. It keeps its source member and is attributed to no member for resolution, retrieval, export or recovery. There is one exception: the recovery step of the identity undo policy, which derives new Claims solely from a subject's own user-authored Evidence.
> Restoring any excluded Claim is itself a derived write under this rule.
> INVALIDATED or erased Evidence is never an input to a derived write.
> Generation counters are monotonic and survive erasure of the scope they fence."

This matches Q18, Q20 and PI-4.4 ("rejected … re-targeted"), PI-6 and Q17 (quarantine; recovery by new claims only), X2 and PI-9.

*Deferral vs final rejection for hidden R6b members is BLOCKED (§6).*

**E3b. Erasure** (`:23`; a new clause after `:779`)

- **`:23`:** "…append-only and immutable: never updated in place. Removal occurs only under §10."
- **New clause:** "Where erasure is required, Evidence is first invalidated per `:779-781`, then physically removed. Erasure of a subject or member removes every record anchored in Evidence whose source member is that subject, **including quarantined material**. A Claim still supported by other Evidence survives with its anchors to the erased Evidence removed. A PII-free erasure record remains. 'Never a raw row delete' (`:756`) governs state-deletion outcomes, not erasure. Erasure, per-fact-redaction, suppression and merge-undo records are kept outside any backup-restore domain and replayed idempotently on restore — undo, then erasure, then suppression; counters set to the maximum of current and recorded — before any read or worker commit. Suppression records are dropped on full erasure of their subject; the erasure record then dominates on replay."
- *Physical removal of hidden R6b members before the window closes is BLOCKED (§6).*

**E5. Statuses** (`:40`, appended)

> "`quarantined`: terminal for retrieval and resolution; the Claim is never assigned back to any member; recovery creates new Claims only as E3 allows. 'Candidate' denotes `pending`. `UNVERIFIED` (Example 11) denotes a Claim not eligible under policy (§6 step 3); the slot resolves per policy (it may keep an authoritative `VALUE`). `HISTORICAL` (Example 20) denotes a temporal view of an `active` or `superseded` Claim whose valid interval has ended. Neither is a status."

**Conditional on Legal (D12):**

> "`redacted`: value and anchor content destroyed on a forget request, in any status; id, transitions and time retained; excluded from retrieval and resolution."

If adopted, `:1434` ("Status transitions only") gains the exception. Whether the tombstone keeps the predicate is UNDECIDED, so the predicate is not listed as retained.

**E11. Policy vocabulary** (§3)

> "Every predicate key and every open key namespace MUST resolve to a declared PredicatePolicy; there is no fallback rule. `llm_write_mode` ∈ {FORBIDDEN, PROPOSE_VIA_GATE, TYPED_COMMAND}. `allowed_writers` is the committing component; `allowed_sources` is the class of the evidence author; a model is never a `source`. A model-chosen key within an open namespace is never `current_state_eligible` and carries no authority beyond memory; meaning that a registered predicate governs is established only under that predicate's policy. Eligibility for resolution (§6 step 3) is declared by policy and MAY require `value_check = verified`. Policy declares which claim classes act as `RESOLVE_CONFLICT`."

The concrete values are UNDECIDED. The `CLEAR` outcome is already covered at `:757`.

**E12. Interval convention** (Ex.1 `:1037`, Ex.2 `:1051`, `:1055`, `:683-684`, Ex.20 `:1339`, `:370-381`, `:1434`)

> "Valid intervals are half-open [`valid_from`, `valid_until`). On supersession, the superseded Claim's `valid_until` is effective — derived from the next Claim in valid-time order among Claims committed at or before the query's knowledge cutoff — and is not written into the Claim. Transition times generalise `invalidated_at`."

The examples are aligned to this convention. The rule for comparing values of different precision is UNDECIDED.

**E13. Rule 7** (`:1004`)

> "…Decision records are never revised; erasure or retention expiry under §10 may delete them or their personal fields, leaving a PII-free record."

This edit is required once E3b makes physical removal possible.

### 7.2 Clarifications (5)

**E4. Extraction confidence** (`:432`, `:444`)
- `:432`: "Four separate measures" becomes "**Five** separate measures".
- `:444`, appended: "`extraction_confidence` MAY be categorical (e.g., derived from assertion mode and anchor grounding); a model's self-report is never truth support."

**E6. Crossing rule** (`:731`, second sentence)

> "…submits a candidate Claim, committed through the same policy engine via the late-arriving-claim path (§4) with idempotency and the §10 generation checks, or a state-mutation request with `expected_version` and `expected_status` like any agent mutation. The §4 path is part of the State Mutation Contract for rule 5. A slot in `CONFLICT` leaves `CONFLICT` by re-resolution only when a conflicting Claim leaves resolution (invalidated, erased, quarantined, redacted), or by a claim class the policy declares `RESOLVE_CONFLICT` (values `[UNDECIDED]`)."

**E7. Same-source supersession** (after `:421`)

> "A predicate's `resolution_policy` MAY declare that, among claims from the same source for the same subject, the later-observed claim supersedes the earlier over the interval where their valid times overlap. This is policy resolution, not recency. Between independent sources of equal authority §6 applies without exception unless policy names the controlling source. Claims from different members of a merged person are subject to the identity rule that incompatible values give `CONFLICT`."

Null `valid_from` coverage is UNDECIDED.

**E8. Context assembly** (a new §8 subsection; most of it restates existing rules)
- **(0)** "Only results authorized at §6 step 9 for the agent's grant enter context; membership of a merged person never widens that set."
- **(1)** "Current-state values enter context only as §11 results (`:844`)."
- **(2)** "Every memory item carries the `:679` labels (source is mandatory) plus assertion mode; no memory content is authorization or capability evidence (extends `:61` to Claims)."
- **(3)** "A retrieval failure is rendered as unavailable, never as `UNKNOWN`, `EXPLICIT_NONE` or empty (follows from `:357-368`)."
- **(4)** "Manifests per `:395`."
- **(5)** "Caches of memory content are derived projections (`:14`, `:780`)."
- §16 **rows 6 and 8** are **by reference** to PI-12 and the Q20 table. No new lists are created.

**PI-4 patch note** (identity patch owner, not the contract)
- The survivor's member-set slot is mutable, with **one** `state_version`, not the `:168` version vector.
- B is "closed to content writes". Lifecycle transitions required by §10, PI-6 and PI-9 still apply to B.

### 7.3 Withdrawn as unnecessary

| Edit | Why withdrawn |
|---|---|
| v1 E9 (freshness) | Already on every policy (`:202-207`) |
| v1 E10 (time event) | `:44` already defines current state over valid claims. The fix is MAD M7 |
| v1 E13 rule 3 | It would read as forbidding redaction |
| The `:32` source enum | MAD-FIX |
| A number derived from mode | Dropped |
| T7 S-5 and S-7 | IMPL |
| "Not in a cached prefix" | IMPL |
| Vectors | `:14` |
| Adapters and serialisation | `:12` |

---

## 8. Final patch set

### 8.1 Required
E1, E2, E3, E3b, E5 (quarantine part), E11, E12, E13.

### 8.2 Unnecessary
§7.3.

### 8.3 Clarifications
E4, E6, E7, E8, and the PI-4 note.

### 8.4 `[UNDECIDED]`: architecture owner or domain owners, not Jay

1. The class for agent-scope lessons (O2).
2. The suppression class (O14). Its form is answered: keyed.
3. Operator authority ranks (O11).
4. Support counting across merged members (T4).
5. The `RESOLVE_CONFLICT` classes and the concrete `resolution_policy` values.
6. The precision-comparison rule.
7. Null `valid_from` coverage.
8. Retract vs "never true" vocabulary (T18).
9. Cross-key ending (the iPhone case).
10. The mechanism for T0 vs un-extracted evidence (R3). Council B's decidable proposal: render evidence past the watermark raw, and label a projection "possibly superseded" when such evidence exists from a source class in the predicate's `allowed_sources`.
11. Registered slots fed only asynchronously (§2.5).
12. Supersession under policy migration (M27), and who classifies a change as breaking.
13. The deletable conversation unit: session vs episode (D2).
14. Transfer: what moves, whether evidence moves, cross-org re-targeting, whether org1 merge ids are honoured in org2, and whether suppressions are re-keyed (D15).
15. Serialising erasure enumeration against merges (D22).
16. Dangling manifest references (Case 10).
17. Forget-then-repeat (Case 15; Legal/product).
18. Tombstone predicate retention.
19. Whether a suppression on B applies after a re-target to A.
20. Quarantine of content written to A by a non-party member C during m1 (the literal PI-6 reading says yes).
21. Assent to compound propositions.
22. Agent-own commitments as memory.

### 8.5 Blocked by Jay
R-M1, R-M2, R-M3, R-M4, and R6b (the three details listed in §6).

**Legal:** D12 (whether a per-fact forget counts as legal policy, which decides whether `redacted` is added).

### 8.6 Implementation only
- counter layout;
- tier numbers and budgets;
- coalescing;
- inline vs subcollection transitions;
- watermark representation;
- cache placement;
- boundary scheduling;
- the Firestore layout;
- normaliser tables;
- the lexical index;
- adapters.

### 8.7 MAD corrections (M1–M27)

| # | Correction |
|---|---|
| M1 | Drop the "policy window" |
| M2 | Historical filter in §F.1 |
| M3 | A `state_version` per slot |
| M4 | Support keyed by evidence id |
| M5 | Support as lineage edges |
| M5b | Watermark vector on `source_position` |
| M6 | Keep `source` separate from mode |
| M6b | Full §11 result and `:679` labels |
| M7 | Head version stamps. Boundaries ≤ t are applied at read and commit time, before the `expected_*` checks |
| M8 | Expiry ≠ freshness; a stale slot stays `VALUE` + STALE |
| M9 | Unverified claims supersede, and the slot becomes UNKNOWN; a verified restatement promotes; verification is a transition |
| M10 | The `CLEAR` outcome is declared per key (`:757`) |
| M11 | Retract split by cause |
| M12 | Re-resolve A on B-side changes |
| M13 | Separate counters are optional; use the PI-4.4 wording; honour PI-9's bump of every member |
| M14 | Narrative `retention_class` / `security_class` |
| M15 | Sensitive-mode consistency |
| M16 | Security anomaly on authority rejection |
| M17 | Undo reverses transitions caused by quarantined claims |
| M18 | Recovery creates new claims |
| M19 | Fence summaries on `context_suppressed`; suppress echoing agent turns |
| M20 | Remove anchors to erased evidence |
| M21 | Keyed, per-subject suppression fingerprint, never used as a doc id |
| M22 | Keyed or value-free claim ids |
| M23 | Typed retrieval operations, replacing `recall_memory` (`:657`) |
| M24 | Precedence by authority |
| M25 | **Server-only Firestore rules for `agent_messages` and every new memory collection before P3** |
| M26 | Past-tense claims carry `valid_until` |
| M27 | Choose how supersession behaves under policy migration |

**Also:**
- Remove MAD §O's "yearly rollups" (it conflicts with §T.1), or fence them transitively.
- MAD L.1's "embed raw phone keys" is imprecise for `agent_user_memory`, which uses an unsalted hash [CODE].
- The MAD's cache rationale (G.2) is doubtful.

---

## 9. Cross-impact map

| Edit | Architecture | Implementation | Identity | Deletion | Security | Migration | Eval |
|---|---|---|---|---|---|---|---|
| E1 | §1 | extractor input; tool echo | PI-3 caller identifiers preserved | — | contamination; no capability via memory | legacy facts contain agent text | contamination metric |
| E2 | §1, `:13`, `:68` | — | PI-4.2 note | erasure reach | — | agent-scope stores | — |
| E3 | §10, Ex.13, Ex.20 step 7, `:601`, `:731` | stamps at ingestion; merges recorded at ingestion and commit; typed cause | Q17, Q18, Q20, X2, PI-4.4, PI-6, PI-9 aligned | row 8 by reference | fail-closed on unknown causes | legacy epoch 0; counters ≥ 1 | (a)–(h), F1–F14 |
| E3b | `:23`, `:756`, §10 | TTL; erasure records; restore replay | quarantined material erased by member | erasure vs deletion | backups | current `delete()` conformant only with a record | restore drill |
| E5 | `:40`, `:1434` | statuses | PI-6 | redaction (Legal) | tombstone leak | — | recovery correctness |
| E11 | §3 | registry; gate | — | — | key routing; anomaly | registry | poisoning set |
| E12 | §4, examples | resolver intervals | — | — | — | — | temporal correctness |
| E13 | rule 7 | — | — | erasure | — | — | — |
| E4 / E6 / E7 / E8 | §5 / §9 / §4 / §8 | gate / commit path / resolver / renderer | — / Q20 / R2 / PI-8 | — | — / — / — / no merge-as-grant | — | per-language floors / concurrency / change of mind / isolation |

---

## 10. Final adversarial answers

**Where does the MAD silently change the contract's meaning?**
The MAD corrections M1–M27, above all:
- the recency window;
- the historical filter;
- monotonic support;
- `claims_version`;
- expiry treated as freshness;
- the iPhone UNKNOWN;
- user-message precedence;
- source folded into mode;
- the narrowed scope chain;
- "a merge never rejects";
- restore-in-place;
- the generic `recall_memory`.

**Where does the contract make the MAD impossible?**
- `:18` (E2)
- `:23`/§10 and rule 7 (E3b, E13)
- `:774` (E3)
- the open value domain of `llm_write_mode` (E11)
- the interval conventions (E12)
- `:781` under bounded retention (R-M3)
- Ex.20 step 3 (R-M1)
- `:173` (PI-4 note)
- `:657` (the MAD must conform, M23)

**Where was there a temptation to invent a rule?** Each case is recorded in §8.4.

**What is the smallest set of edits?** The eight in §7.1.

---

## 11. Council record

| Member | Key findings adopted | Dissent / resolution |
|---|---|---|
| **A (contract lawyer)** | O7 not a required field; `:23`/`:756` is internal tension, not a ban; E6, E8 and E4 downgraded to CLARIFY; E11 to AMEND; E12 and E13 (rule 7) to REQUIRED; `:432` count; `:657` typed operations; `:679` source MUST; PI-4.4 "rejected" wording; E5 restore vs PI-6; E3 fail-open on other causes; E2 `:13` collision; R3 not to be decided by E8 | **Restore replay:** A classed it CLARIFY. **Kept REQUIRED**, because without it E3b's erasure guarantee is false after any restore. |
| **B (failure hunter)** | F1/F2 BLOCKERs (merge recording at commit; the Q17 exception); F3 whole-write rejection; F4 defer on transient; F5 restore is a derived write, redaction in all statuses; F6 fail closed; F7 undo records replayed first; F8 subject-only path check and earliest ingestion; F11 decidable proposal recorded; F12 E7 overlap wording; F13 CONFLICT exit; F14 quarantine subject | **E10:** B wanted a contract edit; A said unnecessary. **Resolved as MAD-FIX M7** (boundary applied at read and commit), since `:44` already defines current state over valid claims. |
| **C (identity and security)** | C-1/C-4 BLOCKERs; C-2 wording; C-3 quarantine attribution; C-5; C-6 R6b conditionality; C-7 erasure by source member; C-8 lifecycle writes on B; C-9 claim-id reversibility; C-10 keyed fingerprints; C-12 **open `agent_messages` rules (verified)**; C-13 rows by reference; E1 tool-echo, capability and caller-identifier wording; E8(0); E11 key-routing; Case 8 answered; R9 not dependent on R-M4; the new R6b inbound item goes to Jay | None |

**Security note.** R13/C-12, meaning `agent_messages` open to cross-tenant read and write, is a verified current production exposure `[CODE]`. It is recorded here and not published elsewhere, following the handling used for earlier security findings.
