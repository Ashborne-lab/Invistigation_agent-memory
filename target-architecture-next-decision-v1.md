# Target Architecture: Next Decision v1

**Date:** 2026-10-03.
**Basis:** `target-architecture-engineering-closure-v1.md`, `memory-integration-harness-v1.md`, `target-architecture-decision-closure-v1.md` (§2 and C-5), and the prototype code (`commit`, `state`, `integration`). This was a narrow evidence check, not an audit. No code, contract or repository was changed.

**Evidence labels:**

| Label | Meaning |
|---|---|
| [PROVEN] | By test or code |
| [INFERENCE] | Engineering inference |
| [OWNER] | Unresolved owner decision |
| [BLOCKED] | Blocked dependency |
| [UNMEASURED] | Not yet measured |

## 1. Current proven boundary

| Proven | Evidence |
|---|---|
| Claim, state, retrieval and context semantics compose end to end; live == rebuild through context | [PROVEN] harness: 12 scenarios plus three properties; suite 761/761 |
| A **single in-memory journal** (one global sequence) plus the policy history, evidence store and commit ledger are sufficient to rebuild everything | [PROVEN] `Pipeline.rebuild()` re-derives without re-running the gate |
| Policy publications must be **evaluation points ordered relative to subject entries**, or `state_version` rewinds (ABA) | [PROVEN] N-1: probe 2 → 0, fixed by journaling publications |
| The external owner decisions are identified and routed | [PROVEN] closure §3 |

**Not proven** (this matters for the next step):

| Gap | Label |
|---|---|
| That the semantics survive a **partitioned** journal, which the closure handed to Infrastructure as "total order per subject partition" (`decision-closure` §2; C-5 row) | [UNMEASURED] |
| What a rebuild does after **crypto-shredding** a subject key, listed as a C-5 requirement but modelled nowhere: journal content is plaintext, and erasure exists only as a lifecycle status | [UNMEASURED] |
| Crash and recovery of a **durable** append (the prototype's atomicity is an in-memory snapshot) | [UNMEASURED] |

## 2. Remaining blockers, and how they depend on each other

```text
                        ┌──────────────────────────────────────────────┐
  [engineering, open]   │ PERSISTENCE CONTRACT (what any store must     │
  ordering model,       │ guarantee for rebuild == live)                │
  shred-vs-rebuild,     └───────┬───────────────┬───────────────┬──────┘
  crash semantics,              │ defines the   │ defines the   │ defines the
  S-2 points                    ▼ requirement   ▼ requirement   ▼ requirement
                        C-5 storage + partitioning   C-1 key custody   B-3 retention interface
                        [OWNER: Infra]               [OWNER: Security] [OWNER: Legal]
                                │                       │                 │
                                └──────────┬────────────┴─────────────────┘
                                           ▼
                                  durable implementation
                                           ▼
                     Memory Gateway (also needs: non-CUSTOMER grants [OWNER Sec/Prod], X-4 channel)
```

**Gate items with no edge to persistence.** These can be done any time; nothing blocks them, and they block nothing upstream:

| Item | Where it lands |
|---|---|
| X-1 size measure | Compiler |
| C-6 conflict event | Projection signal; the workflow is Product |
| T-2 narrative class | Retrieval; the floor is Security |
| X-4 data-channel contract | Gateway |

**Items that DO touch persistence:**
- **S-2**: boundary instants as evaluation points. It defines what the durable head must reproduce.
- **C-2 lifecycle table**: the legality of transitions. The journal *shape* does not depend on it; Legal's erasure-reversal answer changes one rule, not the format. [INFERENCE]
- **N-3**: scope-generation names.

## 3. Candidate next moves considered

| Candidate | Prerequisites | Value | Premature-commitment risk | Owner dependency | Chance of finding a contradiction | Verdict |
|---|---|---|---|---|---|---|
| **A.** Finish the six engineering items | None | Low to medium: four of six are read-side polish | Low | None | Low (they are well specified) | Wait. Only S-2 matters for durability, and it belongs inside D |
| **B.** Ask Infrastructure to choose storage and partitioning now (C-5) | — | High eventually | **High**: Infrastructure would choose against a requirement already shown to be incomplete (§4, finding 1) | It is the owner decision | — | **Wrong order.** The requirement is not ready to hand over |
| **C.** Design the Memory Gateway boundary and APIs | Durable layer; non-CUSTOMER grants [OWNER]; X-4 | Medium | **High**: it builds on unproven persistence and undecided grants | Security / Product | Medium | Wait |
| **D.** **Technology-neutral persistence and rebuild contract, plus an executable conformance suite** | None [PROVEN: the in-memory reference exists] | **High**: it turns C-5, C-1 and B-3 into checkable criteria | **Low**: it chooses no technology, custody or retention value | None to start. It produces the inputs owners need | **High**: §4 shows two gaps already | **Chosen** |
| **E.** Targeted security analysis of the target architecture | — | Medium | Medium | The grants are Security's | Medium | Later. The gate attestation and authorization boundary are already proven in-process; the open items are owner policy |
| **F.** Wait for an owner decision first | — | — | — | — | — | Not justified. No owner can decide C-5 or C-1 well without D's requirements |

## 4. Chosen next move

**NEXT DECISION/ACTION:**

Define and prove the **technology-neutral Durable Journal and Rebuild Contract**: the exact guarantees any storage must provide so that rebuild == live, `state_version` stays monotonic, and erasure stays sound. Express it as an abstract journal interface plus an executable **conformance suite** that runs against the in-memory reference, including a **simulated partitioned journal**.

**WHY NOW.** Integration has just proven the semantics on a *single global* journal. The very next step, durable storage, hands Infrastructure a requirement that the evidence shows is incomplete:

1. **Global ordering vs partitions.**
   - [PROVEN in code] `CommitStore` has one global `_seq`. `slot_versions` orders all entries by it. Policy publications (`kind="policy"`) are **global** events whose position relative to each subject's entries now determines `state_version` (the N-1 fix).
   - The closure told Infrastructure only that a total order **per subject partition** is required.
   - [INFERENCE] A per-subject journal, as specified, cannot place a global publication relative to subject entries without an extra rule: an epoch stamp, a broadcast, or a time-based in-force rule.
   - That rule must be decided **before** a store is chosen, or the choice may be wrong.
2. **Entries that cross partitions.** [PROVEN in code]
   - The fence lands a claim whose evidence is on subject A onto survivor B (merge).
   - The commit ledger's idempotency is keyed by a **global** `proposal_id`.
   - Which partition owns those entries, and where idempotency is checked, is undefined.
3. **Crypto-shred vs rebuild.** [PROVEN gap]
   - Shredding is a stated C-5 requirement, but the journal holds plaintext.
   - No defined rebuild behaviour exists for a destroyed subject key: tombstone, skip, or structural replay.
   - This is what Security (C-1) and Legal (B-3, and erasure reversal) need to see to decide.
4. **S-2 boundary instants** are part of what a durable head must reproduce. Today they are evaluated at the next journal point or at `now` (`engineering-closure` §3).

**WHY NOT THE OTHER CANDIDATES:**
- **A:** mostly read-side; it would not reduce durability risk.
- **B:** would put the owner decision ahead of the requirement it must satisfy.
- **C:** stacks on unproven persistence and undecided grants.
- **E:** its open items are owner policy.
- **F:** owners cannot decide without D's output.

**PREREQUISITES:** none outstanding. The in-memory reference (`commit`, `state`, `integration`) and its 761 tests are the baseline. [PROVEN]

**STOP CONDITION.** The phase ends when, and only when, one of these holds:

- **(a) Success.** All of the following are true:
  - the contract document states every required guarantee;
  - each guarantee has a conformance test;
  - the suite passes on the in-memory reference **and** on a simulated partitioned variant that satisfies the stated ordering rule;
  - the full prototype suite stays green.
- **(b) Escalation.** A guarantee is found that **cannot** be stated without choosing a storage technology, key-custody model or retention rule. The phase then stops and hands the owner a specific, evidenced question. It does not design around the gap.

## 5. Evidence supporting the choice

| Claim | Evidence | Label |
|---|---|---|
| Rebuild correctness depends on a global order including policy events | `state.slot_versions` sorts by the global `seq`; `in_force` is updated from `kind="policy"` entries; N-1 test | [PROVEN] |
| The requirement handed to Infrastructure says "per subject partition" | `decision-closure` §2 C-5; C-5 row | [PROVEN] |
| Merge writes a claim on a different subject than its evidence | `commit()`: `target = fr.target_subject` from the fence | [PROVEN] |
| Commit idempotency is global | `CommitStore.records` keyed by `proposal_id` | [PROVEN] |
| Crypto-shred is required but not modelled | C-5 requirement text; `claim_identity` takes a key, while journal entries keep plaintext `ClaimContent` | [PROVEN] |
| A wrong partition rule would cause rework after C-5 | Integration already showed the ordering is load-bearing | [INFERENCE] |

## 6. Dependencies and owner decisions

- **This phase depends on no owner decision.** It produces the inputs for C-5 (Infrastructure), C-1 (Security) and B-3 / erasure reversal (Legal).
- **Sequencing-risk check.** *Could doing this now force substantial rework after an owner decision?* **No.**
  - The contract states guarantees, not mechanisms.
  - Keys are modelled as opaque key ids, so it is independent of C-1's custody choice.
  - It references `retention_class` opaquely, so it is independent of B-3's values.
  - For erasure reversal, it records transitions without choosing which are legal (C-2 stays a commit-time rule).
  - The one place an owner answer could change it is the cross-partition C-4 rule. That is exactly stop condition (b): escalate, don't decide.
  - The artefacts are a document, an interface, tests and a simulator, all cheap to revise. [INFERENCE]

## 7. Scope for the next phase

**Create:**
- `investigation/memory-durable-journal-contract-v1.md`: the guarantees.
- `memory-prototype/memory_core/journal/`: an abstract journal interface (protocol), the in-memory reference adapter (wrapping today's behaviour), and a **simulated partitioned adapter** (in memory; test only).
- `memory-prototype/tests/test_journal_conformance.py`: the conformance suite, parameterised over both adapters.

**The contract must state, each with a conformance test:**

| # | Guarantee |
|---|---|
| G1 | Entry kinds and payloads (claim, retraction, lifecycle, sync, policy, plus the commit-ledger record), and that entries are immutable |
| G2 | **The ordering model:** per-partition total order **plus** an explicit rule for global events (policy publications) that makes `state_version` monotonic and live == rebuild under any partition interleaving the rule permits |
| G3 | **Partition ownership** of merge-landed claims, and the scope of proposal and group idempotency |
| G4 | Durable-before-acknowledge and atomic append. **Crash at every append point** recovers to a prefix-consistent state with exactly-once logical commits |
| G5 | **Crypto-shred semantics:** after a subject key id is destroyed, rebuild is deterministic, exposes none of that subject's content, and leaves other subjects' state byte-identical |
| G6 | **Evaluation points (S-2):** journal entries, policy publications and validity-boundary instants, with reads creating none. The durable head equals the rebuild for any read schedule |
| G7 | Rebuild needs only the durable fact set; the gate is never re-run |

**Properties:**
- live == rebuild and monotonic `state_version`:
  - on the partitioned adapter, under randomised interleavings;
  - under crash injection;
  - under shredding;
- the head is independent of the read schedule (G6).

**Must NOT be touched:**
- production repositories;
- normative contracts;
- the storage-technology choice;
- key-custody mechanism or KMS;
- retention values;
- erasure-reversal legality;
- non-CUSTOMER grants;
- the Memory Gateway;
- PostgreSQL, Firestore, Redis, network, LLM, embeddings;
- the closed C-A…C-E semantics, except a minimal fix if a conformance test exposes a contradiction, which must be recorded.

**Acceptance criteria:**
- G1–G7 are written and tested;
- both adapters pass;
- the full suite is green;
- every guarantee is marked technology-neutral, or escalated.

**Return to architecture decision-making if:**
- a guarantee needs a technology, custody or retention choice;
- the global-event ordering rule cannot keep monotonicity without cross-partition transactions (that is an Infrastructure question, C-4);
- shredding conflicts with the replay-recorded-outcomes rule (that is a Security / Legal question);
- a conformance failure requires changing claim or state semantics beyond S-2.

## 8. Stop condition

This repeats §4: stop at **(a)** with G1–G7 passing on both adapters, or at **(b)** with a specific escalation. Do not continue into storage selection, Gateway design or the four read-side engineering items in the same phase.

## 9. What remains explicitly undecided

| Item | Owner |
|---|---|
| C-5 storage technology and partitioning | Infrastructure; D only supplies its requirements |
| C-1 key custody | Security |
| B-3 retention catalogue | Legal |
| C-2 erasure reversal | Legal |
| Non-CUSTOMER read grants (S-3 / T-1 / T-5) | Security / Product |
| B-1, B-2, B-4, G-3 policy governance | Governance / domain owners |
| C-6 workflow, X-2 task profiles | Product |
| T-2 narrative floor, X-4 monitoring | Security |
| T-4 audit mode, T-5 `k` | Legal |
| Commitment scope (RELATIONSHIP is not a contract scope) | Contract owner / Product |

**Deferred engineering**, not part of the next phase: X-1, C-6 event, T-2 derivation, X-4 channel, the C-2 transition table, and the N-3 rename. They are independent of persistence (§2) and can follow at any time.
