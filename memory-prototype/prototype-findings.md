# Prototype findings: OLBrain memory core

**Date:** 2026-09-30.

**Basis.** 173 tests and 33 benchmark scenarios, run against the pure core under two configurations:
- `DEFAULT`: the spec exactly as written;
- `AMENDED`: the findings applied.

Everything here is `[DERIVED]` from executable behaviour, unless labelled otherwise.

**Scope limits.**
- No real model was run. All proposals are scripted.
- No Firestore was used.

---

## 1. Which semantics survived executable testing

| Semantics | Evidence |
|---|---|
| **The LLM proposes; deterministic code decides.** Every rejection code fires, and one bad proposal never blocks the rest of its batch | `test_every_rejection_code_and_batch_independence` |
| **Exact-script grounding with a soft value check.** Hindi, Telugu and Hinglish statements are grounded and kept verbatim. A quote in the wrong script fails grounding (no transliteration) | `test_multilingual_grounding_exact_script`, `test_quote_in_wrong_script_is_not_grounded` |
| **`confirmed` as distinct from acknowledgement.** Assent is recognised in en/hi/te; "okay"/"thanks" are refused; the agent turn must be a proposal; the source becomes USER; a user cannot establish billing facts even by assent | the `test_confirmed_*` and billing tests |
| **Keyed claim ids** are idempotent, cannot be reversed for low-entropy values without the key, contain no raw identifiers, and are crypto-shredded on erasure | `test_ids_support.py` |
| **Lineage-based support.** Erasing one of two evidence items keeps the claim; erasing the last invalidates it; a zero-support active claim never appeared in 400 random sequences | support tests, property invariants |
| **Read-time supersession** handles everything the tests require: change of mind, never-true (the predecessor correctly comes back), no-longer-true (no predecessor resurrection), cancelled future plans, and a policy change from SINGLE to SET by pure rebuild. **This is strong evidence for the M27 decision.** The persisted alternative fails never-true without extra reversal logic | `test_temporal_conflict.py` |
| **Authority beats recency. Independent equal-rank sources give CONFLICT. Merged members follow R2** | conflict tests |
| **E3 fence (RECON v2 wording).** Every branch is unit-tested directly (`test_fence_unit_episodes.py`). All four mandatory scenarios pass: erasure rejects (decided by the fence itself, not only by the head check), a merge re-targets, an undo quarantines, Q17 creates a new claim. The F1 blocker is closed by recording merges at commit. Two anchors with one erased reject the whole write. A transient failure defers without advancing coverage. A transfer fails closed | `test_fence_identity_erasure.py` |
| **R6b Option B, archive-first.** A forget-me through the absorbed member archives the whole merged subject at once. Retrieval, context and search become unavailable; do-not-contact is set; late work is fenced; a new contact gets a new subject; physical deletion **does not run** while `ERASURE_ARCHIVE_WINDOW` is UNSET | `test_forget_me_during_wrong_merge_archives_whole_subject` |
| **Absorbed B takes lifecycle transitions but no content writes** (the PI-4 note) | `test_absorbed_subject_gets_lifecycle_not_content` |
| **Typed retrieval** carries every `:679` label. `search_memory` never serves current-state keys. Access is org-checked per row. R-M4 is switchable | `test_retrieval_manifest.py` |
| **Manifests** are deterministic, and a deleted or quarantined claim never appears in a new one | manifest tests, property invariants |
| **Head = rebuild** after every operation in every random sequence. The projection is always rebuildable | `invariants()`, both configs |
| **Episodes.** A gap over 24 h opens an episode; summaries come from evidence only; forget-fact regenerates without the suppressed text; undo quarantines merge-epoch episodes | `test_fence_unit_episodes.py` |
| **Physical deletion leaves no trace** of the erased person's text in claims, evidence, episodes, suppressions, manifests, erasure log or heads. This caught, and fixed, an implementation bug: episodes were not deleted | `test_physical_deletion_leaves_no_trace_of_the_person` |
| **The legacy baseline** reproduces every failure class the investigation reported | `test_legacy_baseline.py`, benchmark |

---

## 2. Assumptions that failed (the architecture flaws found)

Each finding has a test that reproduces it under `DEFAULT`. The spec was **not** patched. Every proposed amendment is behind a flag, and `AMENDED` turns them on together.

**One caveat on the property tests.** The random-sequence invariants (support, isolation, head = rebuild, idempotency, no resurrection) pass under **both** configurations. So F-7 and F-8 are *semantic* errors that the current invariant set does not catch. The invariant set should gain two rules:
- a retraction never targets a later-observed claim;
- a retraction never crosses source groups.

### F-1. The soft value check admits same-script inference

**Severity: BLOCKER.** Under the spec config, a blocking benchmark metric fails.

- **The contradiction.** Spec §5.5 #7 says "Flying to Bangalore for the client meeting" → `note.travels_frequently = true` is REJECTED. But §6.1 step 6 says an unverified value "never rejects". Run as written, the inference is **accepted as unverified memory**.
- **Why it matters.** The soft check was introduced for script mismatch (Hindi or Telugu evidence with a Latin canonical value). Applied to every case, it re-opens the persisted-inference path R-M1 is meant to keep closed.
- **Proposed amendment:** `unverified_scope = cross_script_only`. A same-script quote whose value is not deterministically present is rejected (`mode`). Cross-script cases stay `unverified`. With the amendment, the blocking metrics pass and Telugu recall is unchanged.

### F-2. RECON E7's "overlap" wording is ambiguous (a clarification)

- **The ambiguity.** E7 says a later same-source claim supersedes the earlier one "over the interval where their valid times overlap". It does not say *which* interval of the later claim counts.
- **The failure under one reading.** Read with the later claim's *effective* interval (which a retraction shortens), the iPhone 14 comes back after the iPhone 17 is sold. The prototype implements both readings (`supersession_interval`).
- **Correct rule:** use the later claim's **asserted** interval. An open-ended later claim supersedes from its `valid_from` onward. A later claim with an explicit past interval (for example "I lived in Mumbai in 2019") supersedes only within that interval.
- **Amend RECON E7:** "…over the later claim's asserted valid interval (a retraction of the later claim does not revive the earlier one)."

### F-3. The claim-id formula makes Q17 recovery impossible

- **Where.** Spec §7.2 computes the id as `HMAC(k_subject, evidence|key|value)`.
- **The failure.** When an undo lands **before** commit, the quarantined claim is stored under the source member B. Q17 recovery from B's own evidence then computes the **same id** and silently becomes a no-op. Recovery never produces a claim.
- **Amendment:** add a derivation tag to the id (`orig` vs `recovery:<merge_id>`). Every other idempotency property still holds.

### F-4. Support edges from merge-epoch evidence are unspecified

- **The gap.** During a merge, A's statement can restate a fact held on B's pre-merge claim. The dedup path then adds A's evidence as a support edge on B's claim.
- **What the spec leaves open.**
  - It classes support as lifecycle, so this is allowed on the absorbed B.
  - It never says the edge must record the merge or be removed on undo.
  - Without that, B's claim stays supported by A's words after the undo, which is lineage across people.
- **Behind a flag (`undo_reverses_merge_support`):** support edges carry `merge_ids`, and undo removes them, invalidating the claim if it is left unsupported. `test_F4_*` shows that, under the spec, Alice's claim is still supported by Bob's words after the undo.
- **The spec should state:** *"Support edges and lifecycle transitions caused by merge-epoch evidence are recorded with their merge ids and reversed on undo."* This generalises M17.

### F-5. Anchor quotes in immutable content cannot be removed on erasure

- **The contradiction.** Spec §7.1 and §7.3 put `anchor` quotes in the immutable claim content. E3b/M20 requires quotes from erased evidence to be removed from claims that survive on other support.
- **The result.** Both cannot hold at once. The erased evidence's text ("12 Park Street") stays physically stored in the surviving claim.
- **Recommended fix:** store quotes on support edges, which are lifecycle-managed and deletable. Keep only the evidence ids, or a keyed quote hash, in the immutable content.
- **Verdict:** this is a spec schema change, and it needs an owner decision.

### F-6. Dedup across source classes erases authority

- **The ambiguity.** Spec §6.1 step 10 dedups against *any* active claim with the same key and value.
- **The failure.** An HR_SYSTEM confirmation of a user-stated employer would become a support edge on the USER claim, losing its higher authority. A later user change would then beat it.
- **Behind a flag (`dedup_scope`):** dedup is limited to the same source group. `test_F6_*` shows that, under the spec, a later user statement beats the folded HR confirmation. Under the amendment, HR_SYSTEM keeps its authority.
- **The spec should state:** *"Dedup/support applies within the same source group."*

### F-7. A retraction can reach a claim observed after it

This was found by the property test.
- **The failure.** A delayed or replayed retraction ("I no longer live in Pune", observed at t = 5) retracted a claim first observed at t = 10.
- **Behind a flag (`retract_observed_before`):** a retraction targets only claims observed at or before the retraction's evidence.
- **The spec should state this rule.**

### F-8. One member's retraction can erase another member's claim

This was also found by the property test.
- **The failure.** After Carol was merged into Bob, a replay of Bob's earlier "no longer have a cat" retracted **Carol's** claim. That bypasses R2, under which members are independent sources and contradictions become CONFLICT.
- **Behind a flag (`retract_same_group`):** a retraction targets only claims in the same source group.
- **The spec should state:** *"Cross-member contradiction is expressed only by assertion (→ CONFLICT under R2), never by retraction."*
- **Contract fit:** this is derived from R2. No identity policy is reopened.

### F-9. Unverified claims on registered keys never reach the model

**Severity: MAJOR.** This is the multilingual silent-loss risk the spec itself warned about.

- **Where the claim falls through.** An unverified value on a current-state key (the Telugu "moved to Warangal") is excluded twice:
  - from the slot, correctly, by M9 (the slot resolves UNKNOWN);
  - from memory search, by E8(5), which forbids current-state keys there.
- **The result.** It never reaches the agent, which contradicts spec §15.2's rendering example and MAD D.4 ("accepted as memory and rendered with its quote"). Benchmark: Telugu 0.67 under both configs.
- **Fix, a clarification.** E8(5) forbids returning such values **as current**. So T1 may render unverified claims of registered keys, labelled "unverified, not current, said: …". The renderer and search rules need that exception.
- **Status: not implemented.** It is left failing on purpose.

### F-10. Persisted supersession (the M27 alternative) is unsafe without extra machinery

- **The failure.** With supersession persisted at commit, a never-true retraction of the successor leaves the predecessor superseded. The Pune scenario then returns UNKNOWN instead of Gurugram.
- **What it would need.** Reversal logic on every retraction, undo and policy migration.
- **Conclusion.** This supports the read-time decision of spec §8.1.

---

## 3. Parts of the implementation spec that are ambiguous

The first four were hit in code.

1. **Key syntax.** §5.3 says "`ns.leaf` inside an allowed namespace", which reads as if every key must contain a dot. Registered keys such as `preferred_language` have none. Clarify that registered keys are exact names and only open-namespace keys are `ns.leaf`.
2. **`normalized` mode.** The shared value check let a literal match pass as `normalized` with no normaliser. The rule should be: `normalized` ⇒ a registered normaliser produced the value.
3. **Tokenisation.** A naive `\w` regex splits Devanagari and Telugu words at their vowel signs. The spec should require tokenisation that keeps combining marks attached, **tested per script**. This is an implementation hazard behind the multilingual risk.
4. **"Retry is idempotent" (§10.4).** This holds for repeating a commit against unchanged state. A *late replay* after a merge legitimately differs, because the member set changed. The spec should define idempotency as "the same job, committed twice, adds nothing".
5. **"okay" to a question.** The acknowledgement blocklist refuses "okay", even as a reply to "Shall I book?". That is conservative and costs recall. The lexicon policy is `[UNDECIDED]`.
6. **Support counting across members** (T4) and the precision rule (§9.2) were not exercised against a decision. They remain flags.

---

## 4. Unresolved decisions that materially affect code

| Decision | Code impact seen |
|---|---|
| **M27 supersession storage** | Decides whether undo, never-true and policy migration need reversal machinery. Read-time needs none |
| **F-1 `unverified_scope`** | Decides whether persisted inference exists at all, and interacts with R-M1 |
| **F-3 id derivation** | Recovery works only with the tag |
| **F-5 quote storage** | Schema change: quotes move from claim content to support edges |
| **D15 transfer** | Only fail-closed is implementable. Memory is stranded until D15 is decided |
| **`ERASURE_ARCHIVE_WINDOW`** (Legal + R-M3) | Physical deletion never runs while it is unset |
| **R-M1** | Gates the `inferred` mode and the E4 addition |
| **R-M4** | Gates operator read authorization |
| **Operator rank (O11)** | Flips operator-vs-user outcomes between CONFLICT and operator-wins |
| **Suppression scope (Case 15)** | Flips re-learning after a forget-fact |

---

## 5. Contract wording that still looks inconsistent

- **RECON E7** needs "asserted interval" (F-2). The contract's own Ex.1 and Ex.20 imply that reading.
- **RECON E5 plus the spec §26 `pending_erasure` addendum.** Still pending with the contract owner. The prototype uses the status throughout.
- **RECON E8(5) vs spec §15.2** (F-9). They need the clarification "as current".
- **Content immutability (E12/§7.3) vs anchor removal (E3b/M20)** (F-5).
- **Contract Ex.20 persists `SUPERSEDED`.** Read-time supersession derives it instead. This still needs the architecture owner's reading (spec §26 conflict 1).

---

## 6. What should change before the production implementation

1. **Adopt F-1, F-3, F-4, F-6, F-7 and F-8** as spec amendments, and clarify F-2's wording. All are small rule changes, and each already has an amended implementation behind a flag.
2. **Decide F-5,** where the quotes live. Recommendation: on support edges. **Implement F-9**'s rendering exception, with a test per language.
3. **Add the F-4 reversal rule to the undo spec** (merge-epoch support edges and transitions).
4. **Confirm M27 = read-time.** The prototype shows the persisted alternative is fragile.
5. **Run Lane 1 against a real extractor.** That means both the legacy prompt (the baseline) and the new delta protocol. Measure per-language recall and the rates of hallucination and contamination *proposals* before the gate. Only then can recall floors be set; they are `[UNDECIDED]` until measured.
6. **Keep the P0 security prerequisite** (`agent_messages` rules) ahead of any shadow write. This is unchanged by the prototype.

---

## Exact next implementation step

1. The architecture owner rules on F-1 to F-9, above all F-5 (schema) and F-9 (rendering).
2. Then, with an API key available, **run `benchmark/lane1_v1.json` through a real-model extraction adapter** that implements protocol `olb.memory.extract/1`, alongside the legacy prompt. That produces the first measured baseline.
3. Nothing in P2 (the production `memory_core`) should start until those amendments are folded into the implementation spec.
