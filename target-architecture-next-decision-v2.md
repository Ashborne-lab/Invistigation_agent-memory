# Target Architecture: Next Decision v2

**Date:** 2026-10-03.
**Basis:**
- `durable-journal-rebuild-contract-v1.md` and its suite (144 tests; full suite 905/905);
- `target-architecture-next-decision-v1.md`, `target-architecture-engineering-closure-v1.md`, `memory-integration-harness-v1.md`;
- for the storage candidates: `storage-reality-audit.md` (F2), `memory-lane-a-status-v1.md` (A7), `memory-architecture-decision.md` (§E.4);
- a local environment check.

Nothing was executed beyond reading evidence.

**Labels:**

| Label | Meaning |
|---|---|
| [PROVEN] | Test, code or artefact |
| [INFERENCE] | Engineering inference |
| [OWNER] | Owner decision |
| [STATED] | Requirement stated and its violation demonstrated, but not enforced by the simulator |

## 1. Current proven architecture boundary

| Area | State |
|---|---|
| Write semantics: registry → gate → commit | [PROVEN] Deterministic and attested. Observation vs command is explicit |
| Read semantics: projection → retrieval → context | [PROVEN] Caller-independent truth; history never promoted; no silent winners |
| Rebuild | [PROVEN] From durable facts only; never re-runs the gate; live == rebuild through context |
| Ordering | [PROVEN] **No global total order is needed.** The minimum is O1–O4 plus R-READ. History stability holds on a partitioned simulator; a weaker placement rule fails |
| Cross-subject operations | [PROVEN] No multi-subject atomicity required (intent / claim / outcome; erasure completion barrier) |
| Erasure | [PROVEN] Sealed values are unrecoverable after key destruction; partitions are sealed; the rebuild returns ERASED |
| Durable-fact model | [PROVEN] Facts vs projections vs caches vs caller input are separated, and verified by rebuilding with the live pipeline deleted |

**The point the project has reached.** The *semantics* are proven. The remaining uncertainty is no longer "what must be true" but **"can a real store provide it, at what cost, and with what store-specific failure modes"**.
- Every guarantee so far was proven only on in-memory implementations. [PROVEN]
- No real store has been exercised against the contract. Lane A A7 records the PostgreSQL design as **"untested on real PG"**. [PROVEN]

## 2. Newly enabled capabilities from the durable-journal result

1. **Infrastructure has an executable acceptance test for storage.** The conformance suite is parameterised over `DurableJournal` implementations, so a store adapter can be judged by the *same* 144 tests, including the break tests that show which guarantees matter. [PROVEN]
2. **Candidate stores can be compared on guarantees, not features or familiarity.** [INFERENCE]
3. **The partitioning question is narrowed.** A store only needs a per-subject total order and a small ordered policy log. Requirements that would have forced a single global sequencer or cross-subject transactions are gone. [PROVEN]

## 3. Remaining blockers and owners

| Item | Owner | Blocks |
|---|---|---|
| **Storage technology and partitioning (C-5)** | Infrastructure [OWNER] | Any durable implementation. The contract now supplies its acceptance criteria |
| Key custody and rotation (C-1); per-claim physical-erasure granularity | Security [OWNER] (+ Legal) | Production erasure. Not the evaluation (keys are tested through key-id indirection) |
| Retention catalogue (B-3); erasure metadata; reversal window; erasure latency bound | Legal [OWNER] | Production configuration. Not the evaluation |
| Non-CUSTOMER read grants | Security / Product [OWNER] | Gateway beyond CUSTOMER scope |
| Policy governance B-1, B-2, B-4, G-3 | Governance / domain owners [OWNER] | Real policies |
| C-6 workflow, X-2 task profiles, T-2 floor, X-4 monitoring, T-4 audit mode, T-5 `k`, commitment scope | Product / Security / Legal / contract owner [OWNER] | Feature completeness, not the persistence path |
| Engineering: C-2 transition table, X-1, C-6 event, T-2 derivation, X-4 channel, N-3 rename | Engineering | None on the critical path (decision closure §2) |

**Dependency spine:**

```text
proven semantics ──► [storage evaluation against the contract] ──► Infrastructure selects C-5 ──► durable adapter
                                     │                                                             │
                                     └──► may refine R-READ / commit-protocol mechanisms ──────────┤
                                                                                                   ▼
                          Memory Gateway (also needs: Security grants beyond CUSTOMER; X-4 channel)
```

## 4. Candidate next moves considered

| Candidate | Needs | Enables | Owner-dependent? | Could invalidate prior work? | Reversible? | Uncertainty reduced | Verdict |
|---|---|---|---|---|---|---|---|
| **A. Storage technology evaluation** against the contract | The contract and suite [PROVEN]; a local Firestore emulator [PROVEN available]; a PostgreSQL runtime [**not available locally**] | Gives Infrastructure the evidence for C-5; shows whether R-READ and the commit protocol are cheap, native or impossible on real stores | No for the evaluation; **the selection stays Infrastructure's** | Only by finding a contract gap, which is exactly what is wanted now | Yes (adapters and tests, no commitment) | **The largest remaining real-world unknown** | **Chosen** |
| B. A formal persistence API beyond `DurableJournal` | — | — | No | Yes: freezing an abstraction **before** seeing a real store risks mismatch | Medium | Low. `DurableJournal` (append / publish / facts / seal / destroy_key) already is the boundary [PROVEN] | Not now. Let A refine it |
| C. Memory Gateway architecture | Storage behaviour (R-READ cost, read-your-writes); Security grants [OWNER] | API shape | Yes (grants) | **Yes:** if a store can only give closed reads by waiting or with an "as of" frontier, the Gateway read contract changes | Medium | Medium | Wait for A |
| D. Remaining engineering items | Nothing | Read-side polish, lifecycle table | No | No | Yes | Low; none is on the persistence critical path | Not the bottleneck |
| E. A security contract closure | Owner input | — | **Yes** (custody, grants) | — | — | The open items are owner policy; key interaction is testable through key-id indirection | Not blocking A |
| F. Wait for Infrastructure to choose | — | — | — | — | — | — | It would make Infrastructure choose without evidence of conformance. A produces that evidence |

## 5. Chosen next move

**NEXT DECISION/ACTION.** A **storage technology evaluation phase**. Run the existing durable-journal conformance suite, **unchanged**, against adapters for the storage candidates the evidence supports. Produce, per guarantee, an evidence matrix that Infrastructure can use for C-5. **No technology is selected in this phase.**

**WHY NOW.** The architecture-proving stage is complete for persistence semantics, and the transition point to technology evaluation **has been reached**:
- every remaining persistence question is about real-store behaviour;
- the suite is the instrument to answer it;
- the Gateway (C) and any finalised persistence API (B) depend on the answer.

**Candidates supported by evidence** (as evaluation hypotheses, not selections):

| Candidate | Why it is a candidate | Executable locally? |
|---|---|---|
| **Firestore** | The current sole authoritative OLBrain store (`storage-reality-audit.md`, F2) [PROVEN] | Yes, through the **local emulator** (already used in this workspace) [PROVEN] |
| **PostgreSQL** | The prior memory design's target (Lane A A7 "hybrid by tier… untested on real PG"; `memory-architecture-decision.md` §E.4) [PROVEN] | **No local runtime** (`psql` / `pg_ctl` / `docker` absent) [PROVEN]. Executable evaluation needs a non-production instance from Infrastructure. Until then, evaluate against the existing `memory-postgres-design-v1.md` on paper, clearly labelled |

**WHY NOT THE OTHERS:**
- **B** would freeze an abstraction before real-store evidence.
- **C** depends on A's R-READ and commit-protocol findings and on Security grants.
- **D** is off the critical path.
- **E** is owner policy, not an engineering gap.
- **F** has no evidence to decide on.

## 6. Evidence supporting it, and the self-challenge

| Challenge | Answer |
|---|---|
| 1. What assumption does this rely on? | That the contract is correct and complete for persistence, and that the candidates are the right ones |
| 2. Is that proven? | The contract: yes, on two implementations, with break tests (`durable-journal-rebuild-contract-v1.md`). The candidates: evidenced by F2 (Firestore in production) and A7 (PostgreSQL design target). Other stores are not excluded: the adapter-plus-suite method applies to any candidate Infrastructure adds |
| 3. Which artefact proves it? | As above. The local runtime availability was checked directly |
| 4. Could an owner decision invalidate substantial work? | **No.** Custody is abstracted by key-id indirection; retention does not change a guarantee; selection remains Infrastructure's. The output is evidence, not commitment |
| 5. Is there a cheaper or more reversible experiment? | A paper-only evaluation is cheaper but cannot prove guarantees. **An adapter for an already-parameterised suite is the cheapest executable form.** Paper review is used only where no runtime exists, and is labelled |
| 6. Are we converting a prototype detail into a requirement? | **Risk identified.** The contract's list of seven "requirements" mixes **guarantees** (exactly-once cross-partition commit; erasure soundness with completion) with **mechanisms** (the intent / outcome entries; per-partition erasure entries). The evaluation must test the **guarantees** and allow store-native mechanisms. A store with a native multi-document transaction may meet exactly-once differently, for example. Where a mechanism-specific test exists (the `protocol_commit` tests), a candidate may substitute an equivalent mechanism if the guarantee-level checks still pass |
| 7. Are we choosing a mechanism where only a guarantee is known? | Not if point 6 is applied: adapters may realise each guarantee natively |

The move survives the challenge, with point 6 built into its scope.

## 7. Dependencies

- **To start:** none. The contract, suite and emulator are present.
- **Executable PostgreSQL evaluation:** a non-production PostgreSQL instance provided by **Infrastructure**. This is an environment dependency, not a decision.
- **Authoritative documentation:** the published consistency and transaction semantics of each candidate, cited for any claim the emulator cannot show (production consistency, commit-timestamp guarantees, failover behaviour).

## 8. Rework risk

**Low.**
- The adapters sit behind the existing `DurableJournal` interface.
- The suite is unchanged.
- No schema, deployment or selection is produced.

**The one way this phase could cause rework is by finding a contract gap.** For example:
- a guarantee no realistic store can provide cheaply (most likely R-READ, or policy-log visibility O4);
- a need for cross-subject transactions after all.

That is precisely the uncertainty to surface before Gateway or implementation work, so it is desired rework, discovered early.

## 9. Exact scope of the next phase

**Create:**
- `investigation/storage-evaluation-v1.md`: a per-guarantee × per-candidate evidence matrix. Each cell is one of PASS (executable), PASS (documented, cited), FAIL, NOT SHOWN, or NEEDS ENVIRONMENT, with the exact test or citation.
- `memory-prototype/memory_core/durable_journal/adapters/`: candidate adapters implementing `DurableJournal` (evaluation only):
  - **Firestore emulator adapter**: a subject partition as a collection or sub-collection; a policy log; idempotent writes keyed by `idem`; group append as one transaction or batch; commit time from the store's own time source where possible;
  - **PostgreSQL**: no adapter until Infrastructure provides an instance. Map `memory-postgres-design-v1.md` to each guarantee on paper, labelled NEEDS ENVIRONMENT for anything executable.
- The suite is run parameterised over the new adapter(s) with **no changes to the tests**. The single exception is the documented substitution of an equivalent mechanism for the mechanism-specific `protocol_commit` and `erase_person` tests (§6 point 6).

**Must be evaluated for every candidate, with evidence:**

| # | Guarantee |
|---|---|
| 1 | O1: per-partition total order, with commit times non-decreasing **as assigned by the store** |
| 2 | O2, O3, O4: an ordered policy log; causal stamping; **publication visibility**; the **equal-time** entry / publication rule |
| 3 | **R-READ:** how a read obtains a closed frontier, read-after-write and read-your-writes, and their cost; whether waiting or an "as of" frontier is needed |
| 4 | Idempotent, all-or-nothing single-partition append, durable before acknowledgement; behaviour under duplicate delivery and partition recovery |
| 5 | The exactly-once cross-partition commit **guarantee**: by the intent protocol or a native equivalent; and whether the candidate **forces** any cross-subject transaction requirement |
| 6 | Erasure soundness and the completion barrier, plus the key-id interaction. Custody itself is **not** chosen |
| 7 | Rebuild from durable facts only; history stability; `state_version` monotonicity; caller independence (all through the unchanged property tests) |

**Must not be touched:**
- production;
- credentials;
- normative contracts;
- the semantics of existing components (except a minimal, recorded fix if a conformance failure exposes a genuine contradiction, which must stop the phase first);
- no technology selection, no performance numbers that were not measured, no Memory Gateway, no migration, no shadow writes.

**Acceptance:**
- every cell of the matrix is filled with an executable result, a citation, or an explicit NOT SHOWN / NEEDS ENVIRONMENT;
- the Firestore emulator adapter's suite result is recorded in full;
- every emulator-vs-production gap is listed.

## 10. Stop and escalation condition

**Stop at success:**
- the matrix is complete for Firestore (emulator plus documentation) and for PostgreSQL (paper, plus NEEDS ENVIRONMENT);
- the findings are handed to Infrastructure for C-5.

**Stop and escalate, without designing around it, if:**
- a guarantee cannot be met by a candidate without cross-subject transactions (Infrastructure: C-4 / C-5);
- R-READ or O4 is shown to be infeasible or prohibitively expensive on a candidate. Return to architecture decision-making: this would change the Gateway read contract;
- key destruction cannot be made to make content unrecoverable on a candidate (Security: C-1);
- an executable PostgreSQL evaluation is required to proceed (Infrastructure: provide an instance).

## 11. Explicitly undecided items

- **The storage technology** (C-5, Infrastructure). This phase only produces evidence.
- Key custody and per-claim erasure granularity (Security).
- Retention, erasure metadata, the reversal window and the erasure latency bound (Legal).
- Non-CUSTOMER grants (Security / Product).
- Policy governance (domain owners).
- C-6 workflow and X-2 profiles (Product).
- T-2 floor and X-4 monitoring (Security).
- T-4 audit mode and T-5 `k` (Legal).
- Commitment scope (contract owner / Product).
- **The Memory Gateway design:** deferred until the evaluation shows the real R-READ and commit-protocol characteristics.
- Engineering items C-2, X-1, C-6, T-2, X-4 and N-3: off the critical path.
