# Next Architecture Work Decision v1 (independent of C-5)

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Decision record. C-5 is parked at READY / DELIVERY-BLOCKED and is not revisited.

**Labels:** [PROVEN], [INFERENCE], [OWNER], [STATED], [CONTRACT_GAP].

**DECISION: PROCEED.** Workstream: **Memory Gateway Contract v0 (CUSTOMER scope), an in-memory reference over the proven core and storage boundary.** Its feasibility gate (the write-path bridge) is already executed and passed (§5).

---

## 1. Current state (proven and closed)

| Area | State | Source |
|---|---|---|
| Core pipeline: Evidence → Policy Registry → Claim Gate → Commit/Journal → Current State → Typed Retrieval → Context Compiler | [PROVEN], in memory | Component records, integration harness |
| Engineering closure items: C-A scope vocabulary, C-B/N-1 policy versioning (SUPERSEDED_BY_POLICY, historical policy), C-C sync journaling, C-D/G-1 typed-only status gating, C-E commitment identity (`subject_id`, `agent_id`, tenant), S-2 boundary points, N-5 | Closed in code | `target-architecture-engineering-closure-v1.md`; code checked (`commitments` has `subject_id`/`agent_id`) |
| Durable journal contract **v1.1** (time ownership, served-prefix immutability, K1–K10, S1–S5) | [PROVEN] on two reference stores | Contract v1.1; boundary suite 86/86 |
| Read and commit semantics for any caller: served position r, current vs stale-tolerant reads, causal tokens, OCC at the journal time, duplicate before time | [PROVEN] (K5–K9) | X-1, v5 |
| C-5 storage technology | **READY / DELIVERY-BLOCKED** | MASTER |
| Full suite | 1055/1055 | — |

## 2. Open-work inventory

| Item | Status | Dependency | Can proceed now? | Architectural leverage |
|---|---|---|---|---|
| **Memory Gateway contract (API semantics, CUSTOMER scope)** | Deferred in next-decision v2 §11 "until the evaluation shows real R-READ and commit-protocol characteristics". **That condition is now met for API semantics:** X-1 and v1.1 fixed them technology-neutrally (K5–K9). Cost (E5) and stale-tolerant read classes (Product) remain parameters | None for CUSTOMER scope; write-path bridge (§5: passed) | **Yes** | **Highest.** It is the single entry point the architecture assumes (v2 §U, A7 §4 "Gateway is the only client"). It closes the open boundary between callers and the proven core, and fixes red-team C-4 (bearer subject references) at the API |
| Memory Gateway **service** (roadmap C2: separate service, single PG client) | Blocked | C1 PostgreSQL infrastructure → **C-5** | No | High, but its semantics come from the contract above |
| C-2 lifecycle state machine (decision closure §2a) | The engineering table is decided. `lifecycle()` still accepts any listed status (code checked) | Two owner-held edges (PENDING_ERASURE → ACTIVE: Legal; QUARANTINED → ACTIVE: identity owner). **Enforcing it changes existing test expectations:** `test_excluded_lifecycle_never_becomes_current_state` (reactivates INVALIDATED) and the conformance history generator's random lifecycle transitions | **Needs explicit authorisation to revise named tests** (and owner input for 2 edges) | Medium (lifecycle correctness) |
| X-4 structural data channel; X-1 injected-size measure | ENG direction decided | None | Yes, **inside** the Gateway's `compile_context` output contract | Medium; folded into the chosen workstream at that level only |
| C-6 `slot_entered_conflict` event | ENG direction decided | The workflow itself is Product | Yes | Low |
| T-2 narrative `security_class` derivation | ENG direction decided | The floor value is Security | Yes (derivation only) | Low |
| N-3 fence epoch rename | Documented mapping | None | Yes | Low (naming) |
| Pipeline OCC to K9 | Deferred (v3, v4, v5) | Sequencing | — | **Superseded for the Gateway path:** the bridge (§5) composes the real gate and commit with the journal **without** modifying Pipeline. Pipeline stays the test harness |
| Evidence-store storage boundary | Lane A semantics exist (ingest, fence, epochs). **No storage guarantees are specified** like S1–S5. Contract Part 1 item 8 lists it as a durable fact | Not C-5-blocked for an in-memory reference | Named as an explicit dependency of the Gateway contract, **not invented** | Needed by the Gateway's `ingest_evidence` |
| Erasure APIs (`forget_fact`, `forget_me`, `erase_scope`, reversal) | Cluster erasure [PROVEN] in the journal | C-1 key custody (Security); C-2 reversal and erasure metadata/window (Legal) | Partly; excluded from v0 | High, but owner-bound |
| Non-CUSTOMER read grants (TENANT/AGENT/SESSION, cross-agent commitments, Agent Knowledge) | Not modelled | Security / Product [OWNER] | No | High, owner-bound |
| `identity_event` (merge/undo/transfer) | Lane A fence exists | Identity authority | Excluded from v0 | Medium |
| Real policies (B-1, B-2, B-4, G-3, B-3 catalogue) | TEST_ONLY only | Governance, domain owners, Legal [OWNER] | No | High, owner-bound |
| C-6 workflow, X-2 task profiles, T-4 audit mode, T-5 k, X-4 monitoring, T-2 floor, commitment scope | — | Product / Legal / Security / contract owner [OWNER] | No | Feature completeness |
| **C-5**, key custody C-1, retention B-3 | Parked / owner | Infrastructure / Security / Legal | **No (parked)** | — |

## 3. Blocked work

| Owner | Items |
|---|---|
| **Infrastructure** | C-5 (READY / DELIVERY-BLOCKED: recipient and route not established); Gateway service deployment (roadmap C2 → C1); C-4 multi-subject groups (optional) |
| **Security** | C-1 key custody; non-CUSTOMER grants (with Product); T-2 floor; X-4 monitoring |
| **Legal** | B-3 retention catalogue values; C-2 erasure reversal; erasure metadata, window and latency; T-4 audit mode; T-5 k |
| **Product** | C-6 workflow; X-2 task profiles; stale-tolerant read classes; commitment cross-agent visibility (with Security) |
| **Governance / domain owners** | B-1, B-2, B-4, G-3 (real policies) |
| **Identity owner** | QUARANTINED → ACTIVE; merge policy |
| **Contract owner** | Commitment scope (RELATIONSHIP is not a contract scope); T-3 label names |
| **Authorisation to revise tests** | C-2 lifecycle enforcement (named tests above) |

## 4. Recommended next work

**Name:** **Memory Gateway Contract v0 (CUSTOMER scope)**: a technology-neutral API contract plus an in-memory reference composed only of the proven components over `StorageBoundary`.

**Why next:**
- It is the one remaining unspecified **boundary** between callers and the proven core. Every enterprise property is enforced or exposed there:
  - caller binding and authorisation;
  - write admission;
  - served positions;
  - typed conflicts;
  - context delivery.
- Its deferral reason (v2 §11) is now satisfied for semantics.
- It needs no owner value at CUSTOMER scope.
- It is deterministic and testable over both reference stores.

**Dependency removed:**
- the deferred Gateway design;
- the open caller-binding flaw (red-team C-4) at the API level;
- the K9 write path for real callers, through the bridge, without touching Pipeline.

**Builds on:**
- v2 §U (the operation list);
- red-team C-4, with the Lane A handle mode (`runtime.Memory`, `memory_core/handle`) and `may_read`;
- contract v1.1 K1–K10 and S1–S5;
- X-1 (current versus stale reads, causal tokens);
- the gate, commit, projection, retrieval and compiler;
- decision closure X-4 and X-1 (the data channel and size measure inside `compile_context`).

**Must not reopen:**
- contract v1.1;
- X-1;
- C-5;
- the storage boundary;
- Lane A / B0;
- any owner decision;
- the Pipeline harness;
- existing tests;
- RELATIONSHIP or other non-contract scopes.

## 5. Proposed execution boundary (phase G0)

**Inputs:** as §4 "Builds on". The reference stores are `ExplicitFrontierStore` and `ImpliedFrontierStore`.

**Step 1: the write-path bridge gate. DONE, PASSED** (scratch spike `bridge_spike.py`; nothing committed).
- The **real** gate (`decide`) plus the **real** `commit()` run as a record factory on a throwaway `CommitStore` rebuilt from durable facts at the journal-assigned time, inside `TimedJournal`'s commit step.
- On **both** reference stores:
  - every record has `committed_at == at` (K2);
  - the rebuild from durable facts **equals a reference Pipeline** driven at the same times;
  - a typed command against a stale version gives STATE_CONFLICT and is never durable;
  - served-prefix immutability and stamps hold.
- **No change** to the commit layer, Pipeline or any test [PROVEN by the spike run].

**Remaining outputs:**
- `investigation/memory-gateway-contract-v0.md`, containing:
  - the operations and their caller binding;
  - the served position r and causal token on every read;
  - typed errors (STATE_CONFLICT, STALE_POLICY_STAMP, READ_CLOSED as transient, INVALID_SCOPE);
  - idempotency by command id;
  - the `compile_context` data-channel output contract with its size measure;
  - an explicit list of exclusions and owner-held items;
  - the evidence-store dependency, named and not invented.
- `memory_core/gateway/`: the test-only reference composition.
- `tests/test_memory_gateway_v0.py`, run over both reference stores.

**Operations in v0:**
- `ingest_evidence`;
- observation proposals;
- typed `command` (with `expected_version`);
- `get_current_state` and `search_history` (returning r, accepting a causal token);
- `compile_context`.

**Excluded:**
- erasure operations;
- `identity_event`;
- Agent Knowledge;
- `explain`;
- non-CUSTOMER scopes;
- X-4 monitoring.

**Test expectations (both stores):**
- red-team C-4 scenarios (a) and (b) are refused: a subject reference without a bound handle reads nothing;
- every read returns r; read-your-writes holds with a causal token;
- STATE_CONFLICT is typed and **never retried by the Gateway**; READ_CLOSED is retried as transient;
- a duplicate command id returns the original outcome, decided before time is assigned;
- rebuild from durable facts equals the Gateway's served state;
- `compile_context` output is a separate data channel, never concatenated into instruction text;
- the 1055 baseline stays green, with **no existing test edited**.

**Hard stopping conditions:**
- an operation needs a non-CUSTOMER grant or any owner value;
- the bridge needs a semantic change to the commit layer, Pipeline or an existing test;
- the Gateway needs a **journal** storage capability beyond S1–S5 (record a CONTRACT_GAP);
- cross-source atomicity appears;
- the evidence store would need guarantees that are not specified (record a dependency; do not invent guarantees);
- a contract (v1.1, the architecture contract) would need amendment.

## 6. Decision

**PROCEED** with Memory Gateway Contract v0 (CUSTOMER scope). It is the only workstream started.

**Begun:** step 1 (the bridge gate) is executed and passed.

**Next, within this workstream:** the contract document, the reference composition and the test file (§5 outputs), under the stop conditions above.
