# Final identity decision docket (2026-09-28)

This docket closes residuals R1–R6 from [identity-patch-draft-2026-09-28.md](identity-patch-draft-2026-09-28.md) §3. It adds no new council, research pass or alternative.

Each residual is marked:
- **DERIVED**, where it is already implied by Jay's answers or the contract; or
- **PARAMETER**, where it is a value for the §16 table; or
- **POLICY**, where it needs a decision.

The DERIVED items are closed. Only §2 goes to Jay.

## 1. Closed

### R5: lost text, recovered from the surviving fragments and earlier evidence
| Gap | Recovered as | Basis | Confidence |
|---|---|---|---|
| Name of the second X3 mutation | **`MERGE_SUBJECTS`**. The three mutations are resolve person, merge subjects, undo/revoke merge | The surviving fragment "resolve pers…subjects" sits between "resolve" and "undo/revoke a merge". [contract-vs-settled-decisions.md](contract-vs-settled-decisions.md) X3 asked for exactly a merge command and an undo command | High |
| The fifth X5 gate | **There is no fifth gate.** The text reads "…independent corroboration requireme[nt, each a pa]ss/fail check". There are four gates, each pass/fail. The not-same-person veto sits inside the tenant/safety gate | The fragment "requireme…s/fail check" together with "No composite score". The tenant/safety gate already carries the Q4 veto (PI-3, council C10) | High |
| The start of the Q19 online-authorization list | **The characters cannot be recovered, but the list can be derived.** Online authorization applies to: `IDENTITY_SECURITY` writes, grant and revocation operations, erasure/deletion, merge and undo, agent transfer, export, and any cross-org operation | The first two items must be online whatever G6 says: caching the authorization to change authorization is circular, and only `IDENTITY_SYSTEM` may write `IDENTITY_SECURITY` ([governance-g1-g6-research.md](governance-g1-g6-research.md) §6 items 1–2, from the contract). The rest survive in Jay's text | High for the list, none for the exact words |

G1 is **confirmed** by a separate answer in the docket store: "60 s on whole capabilities" (answers/G1, 08:12 UTC).

### R1: which subject survives (DERIVED)
**The older subject survives**: the earliest `created_at`, with ties broken by the lower id.
- X2 requires a single canonical subject.
- J5 requires that merges be non-destructive and undoable.
- Choosing the older subject keeps the most persisted references valid, and the rule is deterministic.

This is an engineering determinism rule, not policy.

### R2: A and B disagree on a predicate before the merge (DERIVED from the contract)
The merged projection collects the **Claims of every member**. It then applies the **ordinary Predicate Policy** to them, meaning cardinality, temporal validity and authority.
- **Incompatible authoritative values** give `CONFLICT`, which is recoverable through the policy's `RESOLVE_CONFLICT` (§6 `:491-503`).
- **"A wins because A is canonical" is ruled out.** That would be selecting a value by which subject it came from, and §6 forbids silently selecting a value.
- **"Canonical" (X2)** governs where writes land and which `expected_version` applies. It does not decide which value is true.
- **Consent predicates** (opt-out, do-not-contact) resolve **most-restrictive-wins** across members. This follows from Q14 ("follows the person") and the contract's fail-closed rule.

### R3: which generations advance on a merge (DERIVED)
- **Only B's scope generation advances.** X2 says so, and Q20 already implies it: merge-rejected work "re-targets through `merged_into`", which is meaningless for A, since A has no `merged_into`.
- **A's derived projections**, such as summaries and indexes, are **invalidated** because their input set changed. They are excluded from retrieval and recomputed asynchronously (§10 `:777-781`).
- **In-flight writes against A** are not rejected.

### R6a: an opt-out made during the merge epoch (DERIVED)
After an undo, the opt-out stays on **both** subjects. It is written as a Claim whose evidence is the undo event, per rule 2 (`:999`). This follows from Q14, fail-closed behaviour, and R2's most-restrictive rule. The worst outcome is that one person is over-suppressed, and that is reversible.

### R4: the hot-path time budget (PARAMETER)
This is a §16 row, not a question for Jay.
- **Proposed default:** a **200 ms** p99 budget for exact-lane resolve plus merge. If the budget is exceeded, the turn proceeds unmerged and `MERGE_SUBJECTS` completes asynchronously (X3).
- **Owner:** Architecture.
- **Status:** it must be confirmed against a measured latency for the prompt path.

The other §16 identity rows keep their owners and have no value yet: the U3 threshold, the U2 normaliser, and HMAC/KMS key custody.

## 2. For Jay: one policy decision

### R6b: "Forget me" through a wrongly merged person
Q14 says erasure follows the person. If the merge was wrong, erasing everything irreversibly deletes a **third party's** data. Undo cannot bring it back, and the code already admits it over-deletes on shared numbers (`core/lead_contacts.py:828-833`).

**Recommended decision:**
1. **The requester's own data is erased at once.** An erasure request immediately hard-erases the member or members whose identifier the request came through. It is also recorded in the Q20 erasure-completion metadata.
2. **Every other member is hidden, then erased.** Their data is **invalidated immediately**: excluded from retrieval, from prompts, from export and from outreach. This follows §10 `:780`, so from the person's point of view erasure is complete at once. The data is hard-erased only after an **undo window** closes with no undo.
3. **If an undo happens inside the window,** that member is restored as a separate person. Its data remains invalidated only where it came from the merge epoch (Q17 quarantine).
4. **The undo window must be shorter than the legal erasure deadline.** Legal owns that number. It is a §16 row tied to G5/legal.

**Why:** this keeps "follows the person" for everything a user or agent can see. It also keeps a wrong merge from being able to destroy an innocent person's data.

**The alternative:** erase all members immediately. This is simpler, and irreversible third-party loss is then accepted as a cost of merging shared numbers automatically (Q1).
