# Person-identity contract patch set: draft (2026-09-28)

**Status: DRAFTED, NOT APPLIED.** `artifacts/architecture-contract.md` is unchanged. Every item here is **TARGET ARCHITECTURE**.

Inputs:
- J1–J6
- round 1 in [docket-answers-2026-09-28.md](docket-answers-2026-09-28.md)
- the council verdict in [council-verdict-2026-09-28.md](council-verdict-2026-09-28.md)
- round 2 (§0 below)
- the contradictions X1–X7 in [contract-vs-settled-decisions.md](contract-vs-settled-decisions.md)

Jay's scope note applies throughout: *"policy choices only. No schema or mechanism is decided here."*

## 0. Round-2 answers as received

The pasted text reached us with several phrases cut. Where a phrase was cut, it is marked **[LOST]**. I kept only the meaning the surviving text supports, and nothing is filled in by guesswork. §3 lists the points that need a re-send.

| Q | Decision (surviving text) | [LOST] |
|---|---|---|
| Q15 transfer fence | **Reading (i): transfer-time only.** The transfer cascade itself never merges. A later write that carries an exact phone or email match merges normally. **No durable fence and no second human identity action.** The council's C9 override is therefore **dropped** | none |
| Q16 encrypted raw identifier | **Approved.** The identity mapping holds an encrypted copy of the raw phone or email, protected by a per-org KMS key with a key version, and it is included in the erasure cascade. Reason given: re-keying on transfer | none |
| Q17 content from the merge epoch | **Quarantine by default.** After an undo, content from the merge epoch is kept only as quarantined recovery material. Re-deriving from each person's own user messages (assistant replies excluded) is **optional, not automatic** | The middle of "merge-epoch con…son and is kept" |
| Q18 merge vs generation | **Yes, a person merge advances the scope generation.** Rejected work is re-targeted through `merged_into` to the surviving subject | Which scope generations are advanced (see R3) |
| Q19 = G1 caching | **60 s approved for ordinary reads**, on the condition that G6 requires online authorization for: erasure/deletion, merge and undo, agent transfer, export, and any cross-org operation | Possibly one item at the start of the G6 list ("…ie/deletion"); the end of the list reads "authoris." |
| Q20 = G8 | **The council's §3 table, as written.** Erasure: abandon and record opaque completion metadata. Content writes into an erased scope: abandon, never retry. External work already visible: never resent. Derived work: re-derive at the current generation. Work rejected by a merge: re-target through `merged_into` (because Q18 is yes). Operator CRUD/import: return the rejection, retry transient faults 3×, then `FAILED` with an explicit human retry. **No new dead-letter queue** | Fragments only; the meaning is intact |
| X2 current state after a merge | **The survivor is canonical.** After merge(A, B), the `merged_into` target A holds the slot and the single `expected_version`. Reads resolve over the member set {A, B} through the `merged_into` projection. Writes go to A. B accepts no further writes (its generation was bumped under Q18) and stays separately attributable. Undo returns A and B to their pre-merge state, with merge-epoch content quarantined per Q17. Q5 and Q14 evaluate against A | The phrase joining "A is" to "and the single expected_version"; the start of "…ch to A" |
| X3 hot-path resolution | **Permitted: synchronous, with a hard time budget.** Exact-identifier resolve and merge run inline on the request path. If the budget is exceeded, the request proceeds unmerged and the merge completes asynchronously. Below-threshold evidence, enrichment and calibration stay asynchronous. The contract defines **three named mutations**: resolve person, [second], undo/revoke a merge | The name of the second mutation (probably "merge subjects"); the exact budget-exceeded wording |
| X5 merge decision | **Independent gates confirmed**: a hard tenant/safety gate; an identifier-validity gate; a source-class rule; an independent-corroboration requirement; [a further pass/fail check]. A versioned threshold applies **only to the lane below exact match**. **No composite score.** Contract control-plane semantics stay unchanged | The fourth or fifth gate's name; the end of the last sentence |

These answers settle X2, X3 and X5 of the contradiction list. With C1 (Q17), C8 (Q16), C9 (Q15), N10 (Q18), G1 (Q19) and G8 (Q20) also answered, **no identity policy question remains open with Jay**, apart from the residuals in §3.

## 1. Patch drafts

These drafts are labelled **PI-1 to PI-12**, because Patch 19 (D7) is itself undecided. Each one lists the settled decisions it encodes. Nothing is added beyond those decisions.

### PI-1: Person-subject resolution rows *(J1, J2, C4; resolves X1)*
Add to the §14 architecture decision matrix, next to the existing `SAME_AS` rows (which stay untouched):

> | Person-subject resolution within one tenant | **Allowed**, under §[PI-3] |
> | Person-subject resolution across tenants | **Forbidden** |

Add a cross-reference to the "Cross-customer `SAME_AS`" row: *"Governs mentions. Person-subject resolution is governed by §[PI-3], not this row."*

### PI-2: The person-resolution authority *(Q11, Q13, J3; resolves X4, gap G1)*
Add an authority domain, **`PERSON_RESOLUTION`** (a placeholder name), to §5 and the authority matrix:
- Only the person-resolution authority may establish, merge or un-merge person subjects. That authority runs in code.
- The authority is **separate from `IDENTITY_SECURITY` / `IDENTITY_SYSTEM`** and never establishes roles or permissions.
- LLM direct write is Forbidden.
- User and caller statements are **evidence only**, weighed under PI-3.
- No human approves or performs a merge. The single human identity action is PI-7's clearable not-same-person record.

Amend `:1219` to: *"…cannot modify **account** identity, role, authorization…"*. Also add: *"Caller-stated identifiers are evidence to the person-resolution authority and never modify account identity."*

### PI-3: Merge decision *(J5, Q1, Q2, C2, C10, X5; resolves X5)*
1. **Gates.** Every candidate merge passes independent pass/fail gates, in this order:
   1. The tenant/safety gate. Both subjects are in the same, non-empty org, and no not-same-person record exists between them.
   2. Identifier validity. The identifier normalises under the frozen normaliser (see §16).
   3. The source-class rule.
   4. Independent corroboration, counted per §5 (`independent_support_count`, never mentions).
   5. [the fourth or fifth gate: LOST].

   **No composite score is computed.** The §5 measures stay separate.
2. **Exact lane.** An exact match of a normalised phone number or email address that the **channel supplied**, within one tenant, merges once the gates pass. This holds even if the identifier may be shared.
3. **Lane below exact match.** This lane covers caller-stated identifiers, bridge records, and other evidence. A merge here also requires a **versioned threshold**. The threshold is held in the resolver's code, is never set per org, and cannot be changed by an operator. Its version is stamped on each merge.
4. **Bridge records.** A single record whose identifiers match two different subjects is always evidence below exact match. It attaches to the subject of its channel-supplied identifier, and its other identifier is recorded as a candidate edge. Candidate edges are **non-transitive**.
5. **Shared-access signals** are recorded on the merge and **never gate** it.
6. **LLM confidence and judge models** never cause a merge (consistent with `:502`).

### PI-4: What a merge does *(J2, J5, Q18, X2; resolves X2)*
1. **Record and audit.** Merge(A, B) writes `merged_into = A` on B, together with an audit record that carries the policy and threshold versions.
2. **Non-destructive.** No Evidence, Claim or Memory row is re-subjected or combined. The existing "Entity destructive merges — Rejected" row stands.
3. **The survivor is canonical.** A holds each current-state slot and the single `expected_version`. All writes go to A.
4. **B is closed to writes.** B accepts no further writes. Its scope generation advances, so any in-flight work against B is rejected, and G8 re-targets it through `merged_into`. B stays separately attributable.
5. **Reads.** Reads resolve over the member set {A, B} through a `merged_into` projection. This projection is a declared derived projection whose input set is the member set; it is not caller-specific resolution. *[Behaviour when A's and B's pre-merge slot values disagree: R2.]*
6. **Q5 sharing and Q14 consent** evaluate against A.

Amend §2 `:159-173`: allow a derived projection whose declared input set is "the member set of a person subject". That set changes only through PI-5 mutations.

### PI-5: Named person mutations and the synchronous boundary *(X3, Q9; resolves X3)*
**Three typed mutations** are defined under §7:
- `RESOLVE_PERSON`
- [second: LOST, probably `MERGE_SUBJECTS`]
- `UNDO_MERGE` / revoke

Each one carries idempotency and generation checks in the same way as any other mutation.

**On the synchronous boundary:**
- Exact-lane resolve and merge are **synchronous**, under a hard time budget. If the budget is exceeded, the request proceeds unmerged and the merge completes asynchronously through the same mutation.
- The lane below exact match, enrichment and calibration stay asynchronous.

Amend §9 `:719` to read *"entity resolution (mention → entity)"*, and add *"exact-lane person resolution"* to the synchronous list.

### PI-6: Undo *(Q3, Q17, C1)*
`UNDO_MERGE` does the following:
1. It restores the pre-merge partition.
2. It restores A and B to their pre-merge content.
3. It undoes dependent merges first, in reverse order.
4. It keeps the audit lineage.

Content written during the merge epoch is **quarantined**. It is excluded from retrieval under the same rule as `:780`, and it is never assigned to A or B.

Re-derivation is an optional recovery step. It uses each subject's own user messages only, never assistant replies. Undo does not guarantee to reverse replies already sent, outbound side effects, or exports.

*[Council fail-safe: an opt-out or erasure request made during the merge epoch stays on both subjects after undo, written as a Claim whose evidence is the undo event (gap G5). This is **council-recommended, not confirmed by Jay** (R6).]*

### PI-7: The not-same-person record *(Q4)*
- **What it is.** A stored record that two subjects are not the same person. It is the single human identity action.
- **Clearable.** It can be cleared.
- **Veto.** While it exists, it vetoes merges between those two subjects at the tenant/safety gate.
- **Undo.** Every undo writes one.

### PI-8: Cross-agent visibility is a grant *(Q5; resolves X6)*
Within one org, every agent is granted read access to that org's `CUSTOMER` scopes by an **explicit authorization grant**. That grant exists independently of any merge. A merge determines membership of a person, and it never creates visibility. This keeps `:138` and `:2466` intact.

### PI-9: Consent and erasure follow the person *(Q14, Q18)*
- **Erasure.** Erasing a person advances the generation of **every member scope**.
- **Opt-out.** An opt-out on the canonical subject applies to the whole person.
- **Erasure and export.** Both enumerate the members and the `merge_id`s in force at the time they run, and both are recorded.

### PI-10: Transfer *(J6, Q6, Q15, Q16)*
- **Split.** The transfer cascade splits any subject that the moving agent shares with an agent that stays.
- **Re-key.** Moved identifiers are re-keyed under the destination org's HMAC key, from the mapping's encrypted raw identifier.
- **No merging.** The cascade **never merges**. A later write in the destination org merges under PI-3 like any other write. No fence exists.

### PI-11: Person key and identifiers *(D2, D4, Q16; policy level only)*
- **Opaque key.** The person key is opaque and never derived from an identifier.
- **Lookups.** Identifier lookups use a keyed hash (HMAC) under a per-org key.
- **Raw copy.** The mapping holds an encrypted raw identifier under a per-org KMS key with a key version. That identifier is in the erasure cascade.
- **Schema.** Not decided. Jay's scope note leaves it open.

### PI-12: §16 parameter table *(Q19, Q20, gap G2; resolves X7)*
- **Row 1.** 60 s for ordinary reads. **Confirmed.**
- **Row 6.** Online authorization is required for: erasure/deletion, merge and undo, agent transfer, export, and any cross-org operation. The list may be incomplete; see R5.
- **Row 8.** Filled with the Q20 table.
- **New rows, each with an owner and each still to be filled:**
  - the value of the lane-below-exact threshold (U3)
  - the normaliser (U2), frozen before any HMAC is applied
  - HMAC and KMS key custody and rotation
  - the X3 hot-path time budget
- **`:2472`.** The sentence "contain no unresolved contradiction" stays only once PI-1 to PI-11 are applied.

## 2. Earlier drafts that these patches replace

- **P-A** is replaced by PI-1.
- **P-B** is replaced by PI-3 and PI-4. Its claim of "no new machinery" is withdrawn (X2).
- **P-C** is replaced by PI-2 and PI-5.
- **P-D** keeps reading (i): the authority domain is Memory, and D1(a) stands, so future extractions build Claims. Its sentence "the LLM supplies field values only" is narrowed as follows. The LLM supplies field values and may surface caller-stated identifiers. Those identifiers go to PI-3 as evidence below exact match.
- **P-E** is replaced by PI-10.

## 3. Residual questions (small and specific)

- **R1: Which subject survives?** X2 says A without giving a rule. Council member C proposed "the older subject, so persisted ids stay stable".
- **R2: What happens when pre-merge values disagree?** A and B can hold different values for the same predicate before the merge. After the merge, does the projection return A's value (the canonical survivor), `CONFLICT`, or B's value migrated into A as a Claim?
- **R3: Which generations advance on a merge?** Q18 says "the scope generation". X2 confirms B's. Is A's generation also advanced? That determines whether in-flight work against A is rejected.
- **R4: What is the hot-path time budget?** That covers its value and the exact behaviour when it is exceeded.
- **R5: The [LOST] text.** Three pieces were cut: the second mutation name (X3), the fifth gate (X5), and the possible first item of the online-authorization list (Q19). A re-paste of those three lines closes this.
- **R6: The consent fail-safe on undo** (PI-6). Council A and C proposed it, and Jay has not confirmed it.
