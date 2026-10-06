# Next Architecture Work Decision v2 (owner-dependency closure and sequencing)

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Decision hygiene and sequencing. **No code, test or contract changed.**

**Labels:** [PROVEN], [INFERENCE], [OWNER], [CONTRACT_GAP], [DECISION].

**FINAL GATE: PROCEED.** The single workstream: **Evidence Store Boundary Contract v1** (§5).

---

## 1. Current proven state

| Component | State |
|---|---|
| Core: Evidence → Policy Registry → Claim Gate → Commit/Journal → Current State → Typed Retrieval → Context Compiler | [PROVEN] in memory |
| Durable Journal Contract v1.1 (K1–K10, served-prefix immutability, S1–S5), on explicit and implied reference stores | [PROVEN]; boundary suite 86/86 |
| **Memory Gateway v0.1 (CUSTOMER scope): CONFORMANT** | GW-1…GW-3 fixed; adversarial suite 109 on both stores; mutation run 19/19 |
| Full suite | **1202/1202**, 0 xfail |
| C-5 | READY / DELIVERY-BLOCKED (recipient and route [OWNER]) |

## 2. Owner-dependency audit

**Classes:**
- **A** = ENGINEERING-RESOLVABLE: existing evidence already constrains the answer.
- **B** = GENUINE OWNER DECISION, which blocks something on the path.
- **C** = OWNER, NON-BLOCKING for the next phase.

| Item | Current owner | Actually owner-dependent? | Can existing evidence determine it? | Status | Why |
|---|---|---|---|---|---|
| **Evidence-store guarantees** (Gateway §11 CONTRACT_GAP) | Contract owner + Infrastructure | **Semantics: no. Durability values and technology: yes** | **Yes, for the semantics.** Lane A and the red team already fix them: immutability and sealing (`sealed_hash`, `seal_state`: unsealed, sealed, withdrawn, tampered); a server-assigned commit order (`receipt_seq`; the application clock is separate); the status lifecycle (active, invalidated, context_suppressed, pending_erasure, erased); registered and bound (R-1, R-2); `dedup_key`; LA-1 commit records with evidence; the fence reads status, existence and epochs | **A** (semantics) + **C** (technology / C-5) | The requirements are implied by settled Lane A semantics and by durable contract Part 1 item 8. Only the store choice is C-5 |
| **Identity-layer binding interface and guarantees** (GW-G2) | Identity owner + Infrastructure | **Authority source: no (resolved). Durability, availability and SLA: yes** | Authority = the subject head (org, root, member-set version) [PROVEN, defect decisions §4]. Its maintenance (merge, undo, transfer) is identity-event semantics in Lane A; identity events are excluded from current scope | Authority **A** (already decided); guarantees **C** | The interface shape is derivable. Its production guarantees are organisational |
| Handle / causal-token key custody (C-1) | Security | Yes (custody, rotation, KMS/HSM) | No | **C** | Reference keys are TEST_ONLY; the semantics (MAC, domain separation, persistence) are decided |
| Retry budget for transient refusals | Infrastructure | Yes (an operational value) | No; the semantics are decided (transient, bounded, never for STATE_CONFLICT) | **C** | The TEST_ONLY value 3 is a reference default |
| Stale-tolerant read classes | Product | Yes | No. The default "every read is current" is the safe architectural default | **C** | — |
| Assurance level per operation | Security / identity owner | Yes | No. **Hidden-dependency note:** the reference uses Lane A's default requirement ("anonymous"), **the most permissive**. This is a reference default, not a production value | **C** for reference work; **B before production** | §3 below |
| Service-to-service authentication | Security / Infrastructure | **Mechanism: no. Configuration: yes** | Partly: v2 §U (OIDC between services) and roadmap C2 ("service identities with per-operation allow-lists") already state the mechanism; the identities and allow-lists are configuration | **C** | — |
| Non-CUSTOMER grants (S-3 / T-1 / T-5) | Security / Product | Yes | No | **B** for non-CUSTOMER scopes; **C** for the next phase | — |
| Cross-agent commitment visibility (T-1) | Product / Security | Yes | No | **B** for commitment reads; C here | — |
| Commitment scope (RELATIONSHIP) | Contract owner | Yes: RELATIONSHIP is not a contract scope (a contract amendment) | No | **C** | — |
| Production task profiles / mandatory vs degraded (X-2) | Product | Yes | Architecture default decided: fail closed (MISSING_MANDATORY / BUDGET_INSUFFICIENT) | **C** | — |
| Production context size unit | Product / Engineering | Yes: it depends on the model's tokenizer, a deployment choice | Characters remain the TEST_ONLY measure | **C** | — |
| Real policy governance (B-1, B-2, B-4, G-3) | Governance / domain owners | Yes | No. The registry enforces structure; the values are authority | **B** for real policies; C here | — |
| Retention catalogue (B-3) | Legal (values) | **Interface: no** (decided: `{class_id, version, rule, erasure method, legal basis}`). **Values: yes** | Interface: yes | Interface **A** (already decided, not implemented); values **C** | — |
| C-5 storage technology | Infrastructure | Yes | No | **C** (parked, delivery-blocked) | — |
| Lifecycle owner-held transitions (PENDING_ERASURE → ACTIVE: Legal; QUARANTINED → ACTIVE: identity owner) | Legal / identity owner | Yes, for those 2 edges | The rest of the table (decision closure §2a) is decided | Edges **C**. **Enforcement** of the decided table needs **authorisation to revise named tests**, which is not an owner question | — |
| Erasure reversal, metadata and latency (C-2, F) | Legal | Yes | No | **C** | — |
| T-2 narrative security floor | Security | Floor value: yes. Derivation: no (decided: most restrictive) | Derivation: yes | Derivation **A** (decided, not implemented); floor **C** | — |
| T-4 audit mode; T-5 k | Legal / Security | Yes | No | **C** | — |
| X-4 injection monitoring | Security | Yes (monitoring and playbook) | Structural channel decided and implemented (Gateway `memory_data`) | Channel **A** (done); monitoring **C** | — |
| C-6 conflict workflow | Product | Workflow: yes. Event: no (decided) | Event: yes | Event **A** (decided, not implemented); workflow **C** | — |
| T-3 normative label names | Contract owner | Yes: naming in the architecture contract | The recommendation exists | **C** | — |
| Policy-log lease; journal clock source and tolerance; current-read closure cost | Product / Infrastructure | Yes | Semantics decided (K3, K7) | **C** (measured by E5/E7) | — |
| C-4 multi-subject groups | Infrastructure (optional) | Yes | "Forbid at first" is decided | **C** | — |
| S-2 boundary scheduler | Infrastructure | No for correctness: lazy catch-up is decided as sufficient | Yes | **A** (already decided) | — |
| C-5 delivery destination | Organisation | Yes | No | **C** | — |
| **Durable home of episodes and commitment events** (found by this audit, §4) | — | **No** | Partly: engineering closure §5 requires them durable; C-E gives them subject, agent and tenant | [CONTRACT_GAP], engineering-resolvable later | — |

## 3. Newly resolved decisions

Only items the evidence already implies. Nothing organisational is decided.

| # | [DECISION] | Evidence |
|---|---|---|
| D1 | **The evidence-store guarantees are an engineering contract, not an owner question.** Their semantic requirements are already fixed by Lane A and the red team (immutability and sealing, a server-assigned receipt order, the status lifecycle, registered and bound, dedup, LA-1 commit records, the fence inputs). Only technology and durability *values* belong to C-5. The Gateway §11 CONTRACT_GAP is therefore **closable by engineering** | `model.Evidence` fields and comments (R-1, R-2, R-3, R-14, LA-1); `runtime` ingest, withdraw and erasure paths; `fence` DEAD statuses; durable contract Part 1 item 8 |
| D2 | **Identity binding authority** = the subject head (org, root, member-set version). Already decided (defect decisions §4); recorded here so it is no longer listed as open. Only the guarantees remain [OWNER] | Lane A heads; A7 `subjects` / C-1a |
| D3 | **Service-to-service authentication mechanism** = OIDC service identities with per-operation allow-lists. Already stated (v2 §U; roadmap C2). Only identities and allow-lists are configuration [OWNER] | v2 §U; roadmap C2 security gate |
| D4 | Already decided and **not open**: the retention-catalogue interface; the T-2 derivation; the C-6 event; the X-4 structural channel (implemented); S-2 lazy catch-up. These are engineering backlog, not owner blockers | Decision closure §4–§7, §10 |

## 4. Consistency check across layers (Part 4)

| Finding | Class | Action |
|---|---|---|
| **Hidden process-state authority:** Gateway admission (gate and fence) reads evidence from an **in-process dict**, while the durable contract calls evidence a **durable fact** (Part 1 item 8). A durable property currently rests on process memory | Real gap (known as Gateway §11) | Addressed by the chosen workstream |
| **Durable fact model omission:** engineering closure §5 says durable storage must persist **episodes and commitment events** (with identity). Durable contract v1.1 Part 1 and its entry kinds include **neither**. Gateway v0.1 excludes their read operations, so nothing is currently wrong at runtime | [CONTRACT_GAP] (engineering-resolvable) | Recorded; **not** in this workstream |
| **Permissive reference default:** the Gateway uses Lane A's default assurance requirement ("anonymous") for every operation | A reference default, labelled [OWNER] in contract §15 | Kept; flagged as **B before production** |
| Terminology: architecture contract `mutation_id` ↔ Gateway `command_id` / `proposal_id`; Lane A handle scope "person" ↔ CUSTOMER | Mappings already documented (N-3; Gateway §8) | None |
| Pipeline still evaluates OCC at the caller's time | The harness only. The Gateway is the K9 path (v0.1) | None |
| Durable contract header counts (78 / 1047) lag the current suite | Metadata | Refresh at the next amendment |
| The gate's in-process attestation key | Not durable authority: attestations are only consumed within one admission; outcomes are durable | None |

**No contradiction requires reopening a settled contract.**

## 5. Recommended next workstream: **Evidence Store Boundary Contract v1**

**What:** a technology-neutral contract plus an executable boundary for the **evidence store**, in the same pattern as the journal's S1–S5. The Gateway's admission path then reads evidence through it instead of process memory.

**Why it is highest leverage now:**
- It closes the **last durable-fact boundary the Gateway depends on** (Gateway §11, the only CONTRACT_GAP on the CUSTOMER path), and removes a hidden process-state authority (§4).
- It is **fully determined by existing architecture**: Lane A and red-team semantics (D1). It needs **no owner input**.
- It is deterministic and testable over reference implementations, with no C-5 and no infrastructure.
- It feeds C-5 later: the evidence store is part of the persistence surface (A7: evidence lives in Firestore today). It does so without choosing a technology.

**Why not the alternatives:**

| Alternative | Why not now |
|---|---|
| Identity-binding reference contract | Its authority is already decided (D2). A meaningful interface involves identity-event semantics (merge, undo, member-set changes), which are excluded, and its guarantees are [OWNER]. Lower leverage until identity events are in scope |
| Durable home for episodes and commitments | A real gap, but no current Gateway operation depends on it |
| C-2 lifecycle enforcement | Needs authorisation to revise named existing tests |
| Retention catalogue, C-6 event, T-2 derivation | Low-leverage engineering backlog |

## 6. Execution boundary

**Inputs:**
- `model.Evidence` and the Lane A ingest, registration, binding, seal, withdraw and erasure paths (`runtime`);
- the fence (`fence`, DEAD statuses);
- the red team R-1, R-2, R-3, R-14; Lane A LA-1, LA-7;
- durable contract v1.1 Part 1 item 8;
- Gateway contract v0.1 §11;
- A7 `evidence_meta`.

**Outputs:**
- `investigation/evidence-store-boundary-contract-v1.md`: guarantees stated as **what must be true**, each traced to existing semantics. Candidates, to be confirmed against source, not invented:
  - (E-1) id idempotency, with different content refused;
  - (E-2) immutable content with a seal;
  - (E-3) a server-assigned receipt order;
  - (E-4) monotone status transitions per the existing lifecycle;
  - (E-5) durable before the ingest acknowledgement;
  - (E-6) a consistent read of the status the fence needs;
  - (E-7) commit records kept with evidence (LA-1);
  - (E-8) erasure semantics, excluding reversal (Legal).
- `memory_core/evidence_boundary/`: an interface plus reference implementation(s).
- An additive conformance suite. **The Gateway admission path reads evidence through the boundary**, with Gateway behaviour unchanged.

**Tests:**
- the boundary conformance suite;
- the **unchanged** G0 and adversarial Gateway suites stay green;
- full suite ≥ 1202;
- break tests for each guarantee.

**May touch:**
- the new evidence-boundary module and contract;
- Gateway wiring;
- Gateway contract §11 (to close the gap).

**Must not reopen:**
- Durable Journal v1.1 / StorageBoundary / K1–K10;
- Lane A evidence semantics (it encodes them; it does not change them);
- the gate, commit layer, retrieval and compiler;
- identity events and erasure reversal;
- C-5;
- any owner value.

**Stop if:**
- a needed guarantee is not implied by existing semantics (record [OWNER] or [CONTRACT_GAP] and stop);
- a Lane A semantic would have to change;
- an existing test would have to change;
- cross-source atomicity between the evidence store and the journal appears.

  LA-1's "commit records with evidence" is a **known coupling** to examine first: if it requires an atomic write across the evidence store and the journal, **stop and escalate**.

## 7. Final gate

**PROCEED** with **Evidence Store Boundary Contract v1**.

**Remaining genuine owner decisions, none of which blocks it:**
- C-1 custody;
- the retry budget;
- stale read classes;
- assurance levels (**before production**);
- service identities and allow-lists;
- non-CUSTOMER grants and T-1;
- RELATIONSHIP;
- X-2 profiles;
- the size unit;
- B-1/B-2/B-4/G-3;
- B-3 values;
- C-5 and its delivery route;
- the two lifecycle edges;
- erasure reversal, metadata and latency;
- T-2 floor, T-4, T-5 k;
- X-4 monitoring;
- T-3 names;
- lease and clock tolerance;
- C-4.

---

## 8. Workstream started: step 0 (the stop-condition check). Passed

**Question:** does LA-1 ("commit records, proposals plus recorded outcomes, kept with the evidence") force an atomic write across the evidence store and the journal?

**Finding [PROVEN by source]: no.**
- In the target core the recorded decision is a **journal** fact:
  - every durable claim entry seals the full `CommitRecord` (proposal, attested gate decision, outcome) in the subject's partition (`gateway._admit` → `build`);
  - every non-claim terminal outcome is a journal `commit_outcome` entry (durable contract v1.1 Part 1 item 7; Gateway §8).
- Rebuild replays these recorded outcomes and never re-decides (v1.1 §E; `rebuild_uses_durable_facts_only…`).
- **LA-1's semantic** (outcomes are recorded, then replayed, never re-decided) is therefore **met by the journal**. Its Lane A *location* (with the evidence in Firestore) predates the journal.

**Consequence:**
- E-7 becomes a cross-reference: "commit records are journal facts; evidence holds only references to them". It is **not** a co-location requirement.
- **No cross-store atomicity arises.**

**Carried into the workstream as [INFERENCE] to confirm:** whether any Lane A recovery path (LA-1, LA-10 watermark) still reads commit records *from evidence*. That is checked first in the contract phase; if one does, it is a Lane A coupling to escalate, not to change silently.

**Next step in the workstream:** derive E-1…E-8 from source (fields, transitions, fence inputs), then write the contract and executable boundary under §6.

---

**Correction (2026-10-04, Phase 1 of the workstream).**
- §8's "[PROVEN by source]: no" holds for the **target core** only: there, outcomes are journal facts.
- It **overreached** in concluding that the evidence store need not hold commit records architecture-wide. The Lane A restore protocol (`memory-restore-protocol-v1.md`; `runtime/restore.py:137`) still reads FS commit records kept with the evidence, and no record retires it.
- The workstream is **BLOCKED** on the [OWNER] choice of the authoritative commit-ledger home. See `evidence-store-boundary-v1-implementation-report.md`.
