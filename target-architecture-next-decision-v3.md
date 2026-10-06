# Target Architecture: Next Decision v3

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Decision record only. No code, contract, environment or owner decision is changed by this document.

**Inputs:**
- `durable-journal-x1-decision-v1.md` (X-1);
- `storage-technology-evaluation-v1.md`;
- `durable-journal-rebuild-contract-v1.md`;
- `target-architecture-next-decision-v2.md`;
- `target-architecture-engineering-closure-v1.md`;
- the prototype code named below.

**Labels:** [PROVEN], [INFERENCE], [OWNER], [STATED], [CONTRACT_GAP].

---

## 1. Current proven boundary

| Item | State | Label |
|---|---|---|
| Durable-journal semantics (O1–O3, history stability, rebuild, erasure, intent/claim/outcome) | Proven on two in-memory journals, 144 conformance tests | [PROVEN] |
| X-1: commit-time ownership, served-prefix immutability, K1–K10 | Decided; proven by the X-1 model (64 tests, 12 mutations) | [PROVEN] (model) |
| Storage obligations S1–S5 | Stated in prose (X-1 §7) | [STATED] |
| Normative contract file | Still v1: caller-supplied `at`/`T`; R-READ assumed | Stale |
| Firestore | Emulator: the v1 suite passes 144/144. Concurrency isolation is not established (P5-conc). Durability is not shown by the emulator | [PROVEN] (emulator) / NEEDS_ENVIRONMENT |
| PostgreSQL | Paper only. The A7 design is a projection behind Firestore, not a journal | NOT_SHOWN |
| Full suite | 969/969 | [PROVEN] |

## 2. What X-1 resolution unblocked

**Contract readiness: unblocked.** It is now decided:
- who assigns time;
- what commit time means;
- which acts consume a prefix;
- how reads close, and how views read;
- where OCC runs.

There is no remaining semantic ambiguity in O4/R-READ [PROVEN in the model].

**Executable acceptance: not unblocked.** X-1 §9 says rows C1 and B5 become "evaluable against K5–K7 and S1–S4". That holds **for the semantics only**. Nothing can execute those rows against a store today:

| Evidence | Consequence |
|---|---|
| `durable_journal/__init__.py:107-112`: the storage hooks are `_durable`, `_publications`, `_write`, `_write_publication`, `partitions`, `crash`. **No frontier, no conditional append, no closure operation** | A store adapter written to the v1 interface cannot express S1, S2 or S4 [PROVEN by inspection] |
| `commit_time/__init__.py:69-72`: the X-1 model hard-wires `PartitionedJournal` as storage, and keeps `f_part` / `f_pol` **in process memory** | Frontier durability (S2) and closure ordering (S4) are proven only as model state, not as storage behaviour. The model cannot be pointed at any store [PROVEN by inspection] |
| `storage-technology-evaluation-v1.md` §6: the Infrastructure request lists "the unchanged conformance suite" plus `firestore_probes.py` | The suite tests the v1 interface. The probes are Firestore-specific and ad hoc, so they can't be used to compare candidates |
| X-1 §11: "Minimum additions for any store adapter… **not built here**" | Acknowledged gap |

**Infrastructure readiness: not reached.** Running a real environment now would measure the v1 interface. It would leave S1, S2 and S4 to improvised, store-specific probes, which is exactly what the evaluation phase was meant to avoid. [INFERENCE]

## 3. Remaining dependencies

| Dependency | Kind | Blocks C-5? |
|---|---|---|
| **An executable storage boundary for S1–S5:** interface plus conformance suite plus reference implementations | **Architecture → executable contract** | **Yes.** Without it, no candidate can be evaluated on C1, B3, B5 or the S2 rows |
| **The §8 amendment text contradicts K4 in two places:** S1 ("compare against that source's **durable frontier**") and requirement 2 ("Ordered policy log **with a durable frontier**"). K4 explicitly allows a frontier **implied by commit order**, which has no stored value | [CONTRACT_GAP] (internal, textual) | Indirectly. Applied as written, it would mandate a mechanism (stored frontiers) and bias C-5 |
| **K2 against implied frontiers:** K2 requires the record's `committed_at` = `at`, built **before** commit. An implied frontier needs `at` to **be** commit order. X-1 §9 already flags this tension for Firestore | Possible [CONTRACT_GAP]: unverified | Possibly. If the two cannot both hold, K4's "implied" allowance is empty |
| Real-environment isolation, durability, limits and cost | Infrastructure | Yes, but only **after** an executable suite exists to run |
| Pipeline OCC at caller time (E10) | Prototype harness | No. Nothing in storage evaluation consumes `Pipeline` as a writer. The conformance suite uses it only through `export_pipeline`/`load`, the replay path X-1 §8 reinterprets |
| Owner parameters: lease, clock tolerance, per-current-read write cost, lagging-read classes, retry budget | [OWNER] | No. They set **what is measured**, not what is built |
| C-1 key custody, retention, erasure metadata/reversal, grants, commitment scope | [OWNER] | No. Unchanged by X-1; none is on the storage-boundary path |

## 4. Candidate next actions

| | A. Apply the §8 amendment | B. Real storage evaluation | C. Pipeline to K9 | **D. Executable storage boundary (contract v1.1 with its executable form)** | E. An owner decision |
|---|---|---|---|---|---|
| Prerequisite | None | An executable S1–S5 suite; environments | None | X-1 (done) | Evidence that a parameter blocks |
| Unlocks | A normative text | C-5 evidence | Harness consistency | Comparable, technology-neutral acceptance of S1–S5; a validated amendment text; the Infrastructure request | — |
| Changes normative semantics? | Yes, and freezes text that contradicts K4 | No | No | It **corrects** the §8 text to match K4. No new semantics | Possibly |
| Depends on C-5? | No | It **is** C-5 input | No | No; it must admit every candidate | — |
| Depends on Security/Legal/Product? | No | No | No | No | Yes, by definition |
| Rework risk | **High.** Applying it now bakes in stored frontiers; a correction (v1.2) is needed as soon as an implied-frontier store is considered | **High.** Results against the v1 interface don't answer C1/B3/B5; the run would be repeated | Medium. The Pipeline is a harness that a durable journal replaces | Low. Technology-neutral, reversible, test-only | — |
| Reversible? | Yes (text) | Environments cost money and time | Yes | Yes | — |
| Risk of postponing | Low for one bounded phase: no Infrastructure request is issued meanwhile, and MASTER points to X-1 | Medium. Real-world unknowns remain. But nothing executable exists to run | None for C-5 | **The bottleneck:** everything downstream waits on it | None shown |

**Also considered:**
- **Gateway design.** Premature. Current-read closure cost (X-1 §9, §10) is unmeasured, and the Gateway's read path depends on it.
- **A new retrieval/projection abstraction.** Not needed. Retrieval already takes r. Returning r maps to the architecture contract §11 `source_position` and does not block storage.

## 5. Chosen next action

**NEXT ACTION.** Produce **durable-journal contract v1.1 together with its executable storage boundary**, the same pattern by which v1 was produced (its header lists the contract and its "Executable form": interface, two implementations, conformance tests). Concretely:
1. A technology-neutral **storage-boundary interface** that expresses S1–S5 as **guarantees**. Closure is an abstract operation that an explicit-frontier store implements as a conditional write and an implied-frontier store as a wait or no-op.
2. **Two reference implementations** behind that same interface, mirroring v1's A/B:
   - (i) **explicitly stored frontiers**;
   - (ii) a frontier **genuinely implied** by one serialization-consistent clock, with **no stored frontier value**.
3. A **boundary conformance suite** that asserts guarantees, not hook calls. It covers:
   - served-prefix immutability and stamp integrity;
   - conditional append against closure;
   - closure before snapshot;
   - closure surviving a crash (frontiers live **only in storage**; the process holds none);
   - publish versus append;
   - as-of reads without writes;
   - deterministic interleavings and break modes.
4. The **X-1 model running over that interface**, with no process-held frontiers.
5. The **§8 amendment text corrected** to K4 (S1 and requirement 2 no longer presuppose stored frontiers), revalidated against the suite, and **ready to apply as v1.1**. Applying it is the act that closes the phase.

**WHY THIS IS NOW THE BOTTLENECK.**
- C-5 needs evidence on S1, S2 and S4. Those guarantees exist only as prose and as model state in process memory (§2).
- The prepared normative text contradicts K4 in two places (§3).
- So neither "apply the amendment" nor "run real stores" can produce a correct result today. Each needs this step first.

**WHAT IT UNBLOCKS.**
- A normative v1.1 that matches X-1.
- One acceptance suite that any candidate (Firestore, PostgreSQL, another store) runs unchanged.
- A rewritten Infrastructure request whose tests are defined in advance, not improvised.
- Evidence of whether the "implied frontier" allowance is real (§3, K2 versus K4).

**WHY THE OTHER CANDIDATES SHOULD WAIT.**

| Candidate | Why it waits |
|---|---|
| A, applying the amendment alone | Would freeze two clauses that bias C-5 towards stored-frontier stores. It is applied **inside** D, after validation, not skipped |
| B, real storage evaluation | Would test the v1 interface. S1/S2/S4 would rest on store-specific probes. It would be repeated once D exists |
| C, Pipeline to K9 | A harness change with no consumer on the C-5 path. A durable journal replaces this OCC path |
| E, an owner decision | No owner parameter blocks D. Lease, clock tolerance and per-read cost are measurement inputs for B |

**Challenge** (brief §4), each answered:

| # | Challenge | Answer |
|---|---|---|
| 1 | Does D bake in a mechanism? | That is the main risk. It is mitigated by the implied-frontier reference: if (ii) must fake a stored value, the interface has leaked a mechanism, and the phase stops (§9) |
| 2 | Could C-5 invalidate D? | Not if both references pass the same suite, since the suite then admits both frontier forms. C-5 chooses among stores; it does not change S1–S5 |
| 3 | Could an owner decision invalidate D? | No. Owner items are parameters (X-1 §12) |
| 4 | Is the prototype being changed only because it differs? | No. Only the X-1 model's frontier placement moves (into storage), because S2 cannot be tested otherwise. Pipeline is deliberately left alone |
| 5 | Is real-world validation being delayed although the architecture is ready? | The **semantics** are ready; the **acceptance suite** is not (§2). A run now would be repeated |
| 6 | Is the Gateway being designed early? | No |
| 7 | Is the amendment being treated as optional? | No. Its application is part of this action's stop condition, after correcting the two K4 contradictions. Until then the v1 file stays stale for **one bounded phase**: no Infrastructure request is issued, and MASTER points to X-1 as the governing decision |

## 6. Evidence

- **Interface lacks S1/S2/S4:** `durable_journal/__init__.py:107-112` [PROVEN by inspection].
- **Frontiers held in process memory; storage hard-wired:** `commit_time/__init__.py:69-72` [PROVEN by inspection].
- **§8 contradicts K4:** X-1 §7 S1 ("durable frontier") and §8 requirement 2 ("with a durable frontier"), against K4 ("stored explicitly **or implied by commit order**") [PROVEN by text].
- **K2 versus implied frontiers:** X-1 §9 ("needs `at` to equal commit order, while the record must contain `at` before commit") [STATED, open].
- **v1 precedent of contract plus executable form:** `durable-journal-rebuild-contract-v1.md` header [STATED].
- **Infrastructure request depends on the unchanged v1 suite and Firestore-only probes:** storage evaluation §6 [STATED].
- **The emulator cannot establish isolation:** storage evaluation P5-conc, FS-EMU [PROVEN] / documented. Deterministic in-memory interleavings in D therefore test **step ordering only**, never isolation. Isolation stays NEEDS_ENVIRONMENT.

## 7. Sequencing rationale

The dependency graph, from the evidence:

```text
X-1 semantics (done)
   └─► executable storage boundary + validated v1.1 text   ← chosen (D)
          └─► Infrastructure request rewritten against the boundary suite
                 └─► real-environment runs, Firestore / PostgreSQL / other (B)
                        └─► C-5 (Infrastructure [OWNER])
                               └─► durable journal implementation (then Pipeline/K9, then the Gateway read path)
```

- Applying the amendment (A) is a step **inside** D, because its text depends on D's validation.
- Owner parameters feed B's measurements.
- The Pipeline (C) and the Gateway follow C-5.

This is a dependency picture, not a plan for this phase.

## 8. Exact scope (of the next phase; not executed here)

**In scope:**
- **New test-only interface module** for the storage boundary.
- **Two reference implementations:** explicit-frontier and implied-frontier.
- **The X-1 model refactored onto the interface.** Frontiers move to storage, and its 64 tests keep passing unchanged.
- **A boundary conformance suite**, technology-neutral. The guarantees asserted include:
  - S1: conditional append refused once closure has overtaken it;
  - S2: closure survives a crash, with no process-held frontier;
  - S3: durable before acknowledgement;
  - S4: closure ordered before the snapshot;
  - S5: group atomicity and idempotency;
  - publish versus append;
  - as-of reads without writes.

  Each guarantee has a break mode.
- **Corrected §8 amendment text.** On success, apply it to `durable-journal-rebuild-contract-v1.md` as **v1.1** (time and storage-boundary clauses only, with no unrelated edits), and record the change.
- **The rewritten Infrastructure request:** what to provision, and which boundary tests to run per candidate. Drafted, **not issued**.

**Out of scope:**
- any real store or environment;
- the Firestore adapter (it is updated in B);
- Pipeline OCC;
- the Gateway;
- owner parameters;
- production anything.

**Baseline:** 969 must stay green. No test is weakened or deleted.

## 9. Stop / escalation condition

**Complete when:**
- both reference implementations pass the **same** boundary suite;
- every break mode fails;
- the X-1 model runs over the interface with frontiers only in storage;
- the corrected text is applied as v1.1;
- the full suite is green.

**Stop and escalate if:**

| Trigger | Escalation |
|---|---|
| The implied-frontier reference cannot satisfy **K2** (a record carrying `committed_at` = `at`, built before commit) without the store revealing its commit time before commit | **[CONTRACT_GAP] K2 ⟂ K4** → the durable-journal contract owner. Do **not** patch it in the interface. Either K4's "implied" allowance is withdrawn, or K2 is restated |
| The interface can only express S1–S5 with stored-frontier hooks | Mechanism leak → contract owner |
| Any S-clause turns out to need atomicity across sources (partition plus policy log) | Infrastructure (C-4); the X-1 claim "ordering, not atomicity" would be falsified |
| Any existing test must change meaning | Stop. Do not reinterpret silently |

## 10. Explicitly deferred decisions

| Decision | Deferred until | Owner |
|---|---|---|
| C-5 storage technology | After B | Infrastructure [OWNER] |
| Issuing the Infrastructure request | After D (rewritten against the boundary suite) | Architecture → Infrastructure |
| Policy-log lease; clock source and tolerance; accepting a write per current read; lagging-read classes; retry budget | B's measurements | [OWNER] Product / Infrastructure |
| Pipeline OCC to K9 | Durable journal implementation | Engineering |
| Memory Gateway (including its read path and causal tokens) | After C-5 and closure-cost evidence | Architecture |
| C-1 key custody, retention, erasure metadata/reversal, non-CUSTOMER grants, commitment scope | Unchanged; not on this path | Security / Legal / Product / Governance [OWNER] |

---

**DECISION:** formalize the contract **with its executable storage boundary**: v1.1 plus a technology-neutral S1–S5 conformance suite and two reference implementations (explicit and implied frontiers), with the corrected §8 text applied on success. Not real-store validation, not prototype semantics, not an owner dependency.
