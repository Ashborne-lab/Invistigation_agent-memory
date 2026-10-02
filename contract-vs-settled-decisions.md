# Where the current contract contradicts the settled identity decisions (2026-09-28)

**Contract:** `artifacts/architecture-contract.md`, v2.0 with Patches 1–18 (not modified by this pass).

**Settled decisions:**
- Jay's answers J1–J6
- the docket answers in [docket-answers-2026-09-28.md](docket-answers-2026-09-28.md)
- the unanimous verdicts in [council-verdict-2026-09-28.md](council-verdict-2026-09-28.md)

**Scope:** only places where the contract text, read literally, contradicts a settled decision or makes it unimplementable. Contract rules that a decision simply has not yet filled in are listed separately in §3.

**Labels:**
- **KNOWN** means the contradiction was already recorded in [j1-j6-derivation.md](j1-j6-derivation.md) and is still unfixed in the contract.
- **NEW** means it was first identified in this pass.

## 1. Contradictions

### X1: The cross-customer `SAME_AS` ban forbids in-org person merges (KNOWN, P-A)
- **Contract:** the §14 matrix row "Cross-customer `SAME_AS` — Forbidden" (`:2168-2173`), and Example 4, "A1 SAME_AS B1 FORBIDDEN, cross-scope" (`:1091`).
- **Decision:** J2 and C4. Two `CUSTOMER` subjects in one org may be merged, under a separate person-merge rule.
- **Why it contradicts:** read literally, a person merge links two `CUSTOMER` scopes, and that row forbids exactly this.
- **Status:** Route 2 (a separate row) was drafted in P-A and confirmed 3/3 by the council. It has not been applied. B adds that the `SAME_AS` row needs a cross-reference to the new rule; without one, the ban still reads as covering person merges.

### X2: The single-scope rule makes the merged person unresolvable (NEW)
- **Contract:**
  - §2: "A mutable current-state predicate MUST resolve within exactly one authoritative state scope". A resolver that combines two scopes is "PROHIBITED" (`:140-157`). A combined value must be "an explicit derived predicate whose policy names its inputs" (`:159-173`).
  - The §14 row "Multi-scope resolution of mutable predicates — Rejected".
  - §6: "one StateSlot → one system-authoritative resolved result" (`:476`).
- **Decision:**
  - The merge only re-points the mapping. Member storage is never combined (J5 undo and council C1 M-A).
  - Q5: agents share what they know.
  - Q14: opt-out follows the person.
- **Why it contradicts:** after `CUSTOMER:A` and `CUSTOMER:B` merge, each keeps its own slots, for example `preference.communication_mode` at its own `state_version`. Reading the person's current value means combining both scopes, and §2 prohibits that. The contract's only permitted form, a derived predicate, has a static list of named inputs. Nothing in the contract lets the input set change when a merge or undo happens.
  - **Writes are equally undefined.** An agent mutating the merged person's preference has no single `expected_version` to pass.
  - **The alternative is excluded.** Moving the slots into one scope (re-subjecting) is what J5's undo requirement and the "Entity destructive merges — Rejected" row rule out.
- **Consequence:** Q14's "opt-out follows the person" cannot be expressed today. Neither can Q5's cross-agent reads of current-state predicates.
- **Correction to the P-B draft in j1-j6-derivation.md §3.** P-B says a merge that produces two authoritative values "yields `CONFLICT` … No new contract machinery is needed." That holds only if both values are Claims collected for **one** slot. Under a resolution-only merge they sit in **two scopes**, and §6 never collects them together. So new contract machinery **is** needed.

### X3: Entity resolution is listed as asynchronous, but merges are immediate and the next turn depends on them (NEW)
- **Contract:**
  - §9: "The next turn depends only on the synchronous state contract. It MUST NOT depend on semantic consolidation having completed" (`:696`).
  - The asynchronous list includes "entity resolution" (`:719`).
  - The crossing rule says asynchronous results must go through the State Mutation Contract (`:731`).
- **Decision:**
  - J5 and Q1: exact channel-supplied matches merge **immediately**.
  - Q9: resolution runs on every write.
  - Q5: the next prompt reads across the merged members.
- **Why it contradicts:** the next turn's context depends on the merge. If person resolution is the "entity resolution" in §9, it must be asynchronous, and the next turn is then barred from depending on it. The contract never says whether "entity resolution" means only mention → entity (`RESOLVES_TO`) or also person subjects.
- **Also:** the contract defines no mutation command type for a merge or an undo. Under the crossing rule, an asynchronous merge would have no legitimate write path.

### X4: "The conversation cannot modify identity" versus caller-stated identifiers driving merges (NEW)
- **Contract:**
  - Example 12: "It cannot modify identity, role, authorization, tenant membership, or security policy" (`:1219`).
  - The authority matrix row for Identity / security: LLM direct write Forbidden, User evidence Forbidden (`:1611-1636`).
- **Decision:**
  - Q2: caller-stated identifiers count towards a merge, weighted by confidence. Today these are LLM tool-call input from lead capture.
  - C2: a caller-stated bridge record is weak evidence but can still cross the threshold.
- **Why it contradicts:** read literally, a merge driven by a caller-stated identifier is the conversation modifying identity. Q11 (person resolution is a separate authority from `IDENTITY_SYSTEM`) implies "identity" at `:1219` means **account** identity, but the contract does not say so.
- **Also:** the contract has no authority domain for person resolution at all (see §3, G1).

### X5: The single-scalar ban versus the council's additive merge score (NEW, and the council missed it)
- **Contract:** §5: "Never create one universal 'confidence' … Collapsing these into a single scalar score is prohibited" (`:434-445`). The measures that must stay separate are `extraction_confidence`, `source_authority`, `independent_support_count`, `truth_support` and `retrieval_relevance`.
- **Decision:** the C10 verdict (3/3): "a deterministic, additive weight table… sum of per-signal log-odds". Its inputs include:
  - source class, which is source authority;
  - independent corroboration, which is `independent_support_count`;
  - normalisation validity, which is closest to extraction confidence.
- **Why it contradicts:** it is exactly the prohibited collapse, if the §5 rule applies to identity decisions. §5 is written about Claims. The contract does not say whether a merge decision is a Claim.
- **Two ways to reconcile:**
  - **(a)** Express the scorer as separate per-measure gates, for example "`source_authority` ≥ caller-stated AND `independent_support_count` ≥ N AND no veto", instead of one summed number.
  - **(b)** Have the contract explicitly place person-merge scoring outside §5.

  The choice is Jay's. (a) complies with the contract without amending it.

### X6: The "no automatic visibility" rule versus Q5 cross-agent sharing, if the merge is what grants access (NEW, conditional)
- **Contract:**
  - "Security visibility is determined by authorization grants, never by automatic scope inheritance" (`:138`).
  - "A relationship can create semantic connectivity without creating visibility" (`:2466`).
  - "Global entity as authorization bridge — Forbidden" (`:2158-2163`).
- **Decision:** Q5. Agent B sees what agent A learned about a merged person.
- **Why it contradicts:** only if the merge itself makes A's memory visible to B. That would be a relationship creating visibility. The contract is satisfied only if Q5 is realised as an **explicit authorization grant**, such as "every agent in an org may read that org's `CUSTOMER` scopes". The grant must exist independently of any merge, with the merge only deciding which scopes belong to one person.
- **Status:** council C4 already says "never an authorization bridge". The contract needs the grant to be written as a grant.

### X7: §16 claims "no unresolved contradiction" (NEW, consequence of X2–X5)
- **Contract:** "The semantics above contain no unresolved contradiction" (`:2472`).
- **Why it no longer holds:** X2–X5 make this statement false for person identity. It must be withdrawn or qualified until the person-merge patches land.

## 2. Contract drafts of our own that the new decisions make stale

These are drafts in `j1-j6-derivation.md` §3. They are not contract text.

| Draft | Now contradicted by | What changes |
|---|---|---|
| P-B item 2 (an exact phone or email match merges immediately) | Q2 and C10 | Only **channel-supplied** exact matches merge immediately. Caller-stated exact matches must clear the threshold, and a bridge is always weak |
| P-B "no new machinery" claim | X2 above | Withdrawn |
| P-C (the identity authority is the Memory Gateway) | Q11 | Person resolution is a **separate authority**, not `IDENTITY_SYSTEM`. The Gateway may host it, but it must not become the roles authority |
| P-C "the interim resolver is the `person_key` fold" | Q9 | The fold is rebuilt to run on every write. The sentence becomes true only after that rebuild |
| P-D "The LLM supplies field values only" and "the person key is system-asserted from the channel-supplied identifier" | Q2 | Caller-stated identifiers now feed the resolver. They remain separate from the key on the write, and they need their own sentence |
| P-E (no draft) | Q6 and council §5 | The default is now decided (split, and don't merge on arrival). The fence question (§9.1 of the verdict) is still open |

## 3. Gaps: the contract is silent, not contradictory

- **G1. No authority domain for person resolution.** Q11 creates one. The authority matrix (`:1596-1816`) has no row for it.
- **G2. The §16 parameter table lacks the identity parameters.** Missing are the merge threshold (U3), the normaliser (U2), and HMAC key custody and rotation (C8). Under `:2472` ("No implementation team may silently invent a value"), each needs a row with an owner.
- **G3. §16 row 8 (bulk-deletion retry and dead-letter queue) is still "Open".** The council's §3 table answers it, pending Jay's G8 lean and N10.
- **G4. §10 scope generations cover one `CUSTOMER` scope at a time (`:765-775`).** Q14 erasure that follows the person must bump the generation of every member scope. What a merge does to generations (N10) is unstated.
- **G5. Keeping consent in place after an undo.** Council C1's fail-safe keeps an opt-out on both members, which writes a value into a second scope. Rule 2 (`:999`, "never written independently of Claims") requires that write to be a Claim with the undo event as its evidence. That is not a contradiction, but the patch must say it.

## 4. Unchanged and consistent

These contract rules are consistent with the settled decisions and need no change:
- **"Entity destructive merges — Rejected"** (`:2188-2193`) and the revocation precedent (`:1095-1097`) match a merge that only changes the mapping, with undo.
- **§10 invalidation and exclusion** (`:777-781`) matches council C1's quarantine: content written during the merge epoch is never served.
- **§4 "MUST NOT select … by LLM confidence"** (`:502`) matches C10, which keeps the LLM and JEV off the merge path.
- **The G5 aggregate rule** (`:796-824`) matches C6 (b): design without the aggregate tables.

## 5. Status after round 2 (2026-09-28)

Jay answered X2, X3 and X5 in round 2. Draft patches now exist for all seven contradictions (X1–X7), in [identity-patch-draft-2026-09-28.md](identity-patch-draft-2026-09-28.md) (PI-1 to PI-12). None have been applied to the contract. Six residuals remain open (R1–R6), listed in §3 of that file.
