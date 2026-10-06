# Memory Gateway v0: Adversarial Security and Semantic Audit

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE audit. Test-only. **No code was changed:** the Gateway, the core, the contracts and the existing tests are untouched.

**Suite:** `memory-prototype/tests/test_memory_gateway_adversarial_v0.py`, **63 tests**:
- 31 per reference store (27 pass, 4 are defect reproducers);
- 1 store-independent check.

**Labels:** [PROVEN], [DEFECT], [CONTRACT_GAP], [OWNER], [INFERENCE].

**VERDICT: DEFECTIVE.**
- Caller binding, cross-org isolation, conflict handling, policy stamps and the data channel **survive** every attack.
- **Three defects** break claims of Gateway contract v0:
  - **GW-1:** an unvalidated causal token;
  - **GW-2:** a reused command id with different content is reported as already applied;
  - **GW-3:** a cross-subject command-id collision depends on process state.
- Each is a Gateway-level issue (no foundational component needs to change), but **each needs a design decision** that is not taken here (§6). Per the stop rules: reproduced, recorded, not patched.

---

## 1. Threat model

- **Every caller input is untrusted:** handles, the `subject` argument, proposals (ids, org, anchors, versions), `after` tokens, scopes, memory values, evidence.
- **The adversary** may hold a valid handle for one conversation and attempt to read, write or confuse another. They may replay, collide ids, race the Gateway with writes, publications and closures, and plant hostile memory.
- **Simulated credential issues:** handles are crafted with the TEST_ONLY secret only to simulate stale or mis-issued credentials (another org, another member-set version, another agent or session).
- **Out of scope:** secret theft, service-to-service authentication, non-CUSTOMER scopes, erasure, identity events.

## 2. Properties audited

| # | Property (from contract v0) |
|---|---|
| P1 | A subject reference is never authority. Binding happens before any core access |
| P2 | No cross-subject or cross-org data is returned, and no unauthorised mutation becomes durable |
| P3 | A stale typed command never becomes durable; STATE_CONFLICT is typed and never retried into success |
| P4 | A policy stamp is authoritative; an old decision is never reinterpreted |
| P5 | Idempotency: the terminal outcome is stable; a duplicate is decided before time; a transient refusal is not terminal |
| P6 | Every read returns r; causal tokens behave as specified; callers cannot select an arbitrary truth position |
| P7 | Misrouting gives stable typed refusals |
| P8 | Memory remains data: one frame, no forged labels, size measure and budget hold |
| P9 | Evidence ingestion claims only what §11 states; no unstated guarantee is relied on |

## 3. Attack scenarios (all run against both stores unless noted)

1. **Handles:**
   - missing, empty, garbage, no-dot and bad-base64 tokens;
   - forged signature; tampered payload;
   - expired, including the exact boundary;
   - another org; a stale member-set version;
   - replay within and after TTL;
   - the same handle against another subject.
2. **Confused deputy:**
   - a valid handle swapping the `subject` argument for reads, history, context and mutations, with a spy confirming **no core access**;
   - a mutation for another subject;
   - a proposal anchoring another subject's evidence;
   - agent and session swaps.
3. **Cross-org and cross-subject:**
   - the same subject id under another org;
   - a guessed subject id;
   - a foreign org label on a proposal;
   - an evidence id reused across orgs;
   - a command id reused across subjects.
4. **Replay and idempotency:**
   - duplicates after state and policy changes;
   - the same id with different content;
   - the same id on another subject, with and without process state;
   - transient exhaustion, then process-state loss, then a retry;
   - no API input accepts a gate decision.
5. **TOCTOU:**
   - a policy published between the gate and the commit;
   - a slot change plus a closing read while a typed command is in flight.
6. **Reads:**
   - stale, NaN, future and infinite `after`;
   - two conversations;
   - reads across a validity boundary and immediately after a write;
   - a Gateway restarted over the same durable store.
7. **Routing:**
   - invalid scope names (RELATIONSHIP, ORG, PERSON, EPISODE, lower-case, empty) and unsupported contract scopes;
   - a write-shaped payload as a subject;
   - read-shaped payloads as proposals.
8. **Context:**
   - instruction-like text and role markers;
   - a forged `</MEMORY>` / `<<MEMORY>>` frame and forged `[CURRENT_STATE]` labels;
   - XML and JSON system blocks;
   - `[INST]`, RTL and NUL control characters, injected section headers;
   - a 200 000-character value.
9. **Evidence:**
   - identical and different re-ingestion;
   - an un-ingested evidence id;
   - evidence from another subject;
   - evidence from another conversation of the same person.

## 4. Results by category

| Category | Result |
|---|---|
| **1. Handle security** | [PROVEN] **survives**. Every malformed or forged token is refused (HANDLE_REQUIRED / malformed / bad_signature). Expiry is inclusive at `exp` and refused just after it. Another org gives cross_org; another member-set version gives stale_handle |
| **2. Confused deputy** | [PROVEN] **survives**. A swapped subject is refused as wrong_subject for every operation, **before any core access** (spy: zero journal reads or prepares). Nothing becomes durable. A proposal anchoring another subject's evidence is refused by the gate |
| **3. Cross-org / cross-subject** | [PROVEN] **survives for data**. The same subject id in another org is cross_org for reads and writes, and only the owner's claim is durable. A guessed subject gives unknown_subject. A foreign org label is refused by the gate. An evidence id reused across orgs is refused. **The command-id collision across subjects is GW-3** |
| **4. Replay / idempotency** | [PROVEN]: terminal outcomes are stable across state and policy changes; a duplicate is decided before time (G0 suite); a transient is not terminal even after process-state loss; no gate decision can be injected. **[DEFECT] GW-2 and GW-3** |
| **5. TOCTOU** | [PROVEN] **survives**. A policy published between the gate and the commit gives typed STALE_POLICY_STAMP, never durable, with stamps intact. A slot change plus a closing read in flight gives typed STATE_CONFLICT, never durable, with no conversion to success (and the G0 in-flight test) |
| **6. Read consistency** | [PROVEN]: r on every read; stale and NaN tokens do not move the read below the clock; two conversations see the same truth; boundaries are stable; after process-state loss, binding **fails closed** (unknown_subject). **[DEFECT] GW-1:** future and infinite tokens |
| **7. Routing** | [PROVEN]: stable typed refusals for invalid and unsupported scopes and write-shaped subjects. Read-shaped payloads to write operations raise **untyped** Python errors with **no durable effect** (§5 note) |
| **8. Context** | [PROVEN] **survives**. For every hostile value: exactly one HEADER and one FOOTER (the frame cannot be closed or forged); forged labels and `[INST]` are neutralised; `used == len(memory_data) ≤ budget`; `channel == "memory_data"` |
| **9. Evidence boundary** | [PROVEN]: identical re-ingestion is idempotent and different content is refused; an un-ingested evidence id is refused by the gate; another subject's evidence is refused. Another conversation of the **same** person is accepted, as CUSTOMER-scope material [INFERENCE: CUSTOMER = the person; Lane A extraction is per subject]. No durability is assumed (§11 stays CONTRACT_GAP) |

**Mutation run** (each invariant removed in turn; both suites restored byte-identical):
- **11 of 13 caught by this suite.** Caught: authorize, unknown subject fails closed, duplicate before time, stale stamp at write, scope check, transient not terminal, signature check, expiry, cross_org, wrong_subject, stale member set.
- **Two survivors, both explained:**
  - "handle required": a missing handle is still refused, as malformed, by `verify`. That is defence in depth, and the property holds.
  - "conflict at write never retried": in these scenarios the closure refusal comes first and the conflict is then found at build. That rule is caught by the G0 suite's in-flight test.

## 5. Discovered defects

Each defect test is `xfail(strict=True)` with its id. It asserts the correct property and fails exactly on the defect, as verified with `--runxfail`.

### GW-1: the causal token `after` is not validated. Severity: high (integrity and availability)

| Field | Content |
|---|---|
| **Reproducer** | `get_current_state(valid_handle, "s1", 2.0, after=1e9)`, then a normal write at clock 3 |
| **Observed** | The read is served at **r = 1e9**. The next write is committed at **1e9 + ε**: its `committed_at` claims OLBrain learned it at time 1e9. With `after=inf`: explicit store, **every later write to the subject is READ_CLOSED forever** (denial of service); implied store, the next write is committed at **inf**, and the implied time sequence is **global**, so every subject is affected |
| **Violates** | K2/K3 (commit time = knowledge time; a partition's closed position never runs ahead of the clock or of an **already-assigned** time carried as a token). P6 ("no caller can select an arbitrary truth position") |
| **Root cause** | Gateway v0 passes the caller's `after` straight to the journal. Contract v0 §6 says a token is "the commit time of your write, or the r of your last read", but **does not say how the Gateway knows that a presented token is one** |
| **Fix location** | Gateway (token validation). No foundational change is needed |
| **Needs a decision** | **How a token is authenticated or bounded:** a signed token issued by the Gateway (like handles); a bound by durable positions (the subject's last commit time, or its closed position); or both. Which is chosen is a contract decision (GW-G3) |

### GW-2: a reused command id with different content is reported as already applied. Severity: medium (integrity of outcomes)

| Field | Content |
|---|---|
| **Reproducer** | `p1` = "pune" APPENDED; then `p1` re-sent with **different** content ("delhi") |
| **Observed** | **DUPLICATE**, with the original APPENDED. The caller is told its (different) command took effect |
| **Violates** | The architecture contract §7 idempotency ("replaying it produces the same result" applies to the same mutation). The gate's and the commit layer's own rule (`proposal_id_reused_with_different_content` gives REJECT) |
| **Root cause** | The recorded `commit_outcome` carries no content fingerprint, so the Gateway cannot tell a replay from a reuse |
| **Fix location** | Gateway: record the proposal fingerprint with the outcome; return DUPLICATE only on a match, and a typed reuse refusal otherwise |

### GW-3: a cross-subject command-id collision depends on process state. Severity: medium (determinism, P5, contract §13)

| Field | Content |
|---|---|
| **Reproducer** | `p1` used for s1; then `p1` sent for s2 |
| **Observed** | **GATE_REFUSED** (`proposal_id_reused_with_different_content`) while the in-process gate ledger exists. **APPENDED** after process-state loss. The same request has two different terminal outcomes |
| **Violates** | Contract v0 §13 ("losing [process state] never changes durable truth; duplicates are decided from durable outcomes"). The "duplicate produces a different terminal result" stop rule |
| **Root cause** | Durable outcomes are looked up **per subject**, while the gate ledger is **global and non-durable**. Which namespace a command id lives in is **not specified** (GW-G1) |
| **Fix location** | Gateway, after the namespace decision (per subject, per tenant, or global) |

**None of the three** returns another subject's or org's data, lets an unauthorised mutation become durable, turns a conflict into success, reinterprets a policy, or crosses the data/instruction boundary.

## 6. Genuine contract gaps

| Id | Gap | Owner |
|---|---|---|
| **GW-G1** | **Command-id namespace** (per subject, per tenant, global) and its durable home. Needed to fix GW-3 | Contract owner [OWNER] |
| **GW-G2** | **The authority for a subject's org** in caller binding. v0 derives it from evidence ingestion (process memory over a store whose guarantees are themselves a CONTRACT_GAP). After process-state loss, binding **fails closed** [PROVEN]: safe, but it makes availability depend on the unspecified evidence store. **Contract v0 §11 understates this:** reads depend on it, not only admission. In the target architecture this belongs to the identity layer (subject heads, member sets) | Contract owner + identity owner [OWNER] |
| **GW-G3** | **Causal-token validity:** how a presented `after` is shown to be an already-assigned time (signed versus bounded). Needed to fix GW-1 | Contract owner (+ Security for signing) [OWNER] |
| (carried) | Evidence-store guarantees (contract v0 §11) | Contract owner + Infrastructure |

## 7. Owner-held dependencies (unchanged, surfaced by the audit)

- **Handles are bearer capabilities within their TTL:** valid for every v0 operation on their subject, not operation-scoped, and not agent-restricted at CUSTOMER scope [PROVEN as designed]. Operation-scoped or agent-restricted capabilities are a Security / Product decision (with non-CUSTOMER grants). Per-turn TTL is the Lane A mitigation.
- Assurance level per operation, and service-to-service authentication: Security / Infrastructure.
- Input-schema validation at the service edge (read-shaped payloads raise untyped errors in the in-process reference, with no durable effect): belongs to the deployed Gateway service [INFERENCE].
- The retry budget (Infrastructure); stale-tolerant read classes (Product).

## 8. Regression results

| Suite | Result |
|---|---|
| Full prototype suite | **1148 passed, 8 xfailed** (the 8 = GW-1 ×2 variants ×2 stores, GW-2 ×2, GW-3 ×2) |
| The previous 1093 tests | **All pass; none edited** |
| Adversarial suite on `ExplicitFrontierStore` | 27 passed, 4 defect xfails |
| Adversarial suite on `ImpliedFrontierStore` | 27 passed, 4 defect xfails |
| Store-independent | 1 passed |

## 9. Final security and semantic verdict

**DEFECTIVE.**

**What survives the adversarial audit [PROVEN on both stores]:**
- caller binding (P1);
- cross-subject and cross-org isolation of data and of durable mutations (P2);
- stale commands and conflict handling (P3);
- policy-stamp authority (P4);
- transient handling (part of P5);
- typed routing (P7);
- the data channel (P8);
- the evidence-boundary honesty (P9).

**What fails:**
- **GW-1** (P6, K2/K3: an arbitrary future truth position; denial of service or a global time break with `inf`);
- **GW-2 and GW-3** (P5 and contract §13: outcome integrity and process-state independence).

**Fixing them:** all three are Gateway-level and need **no** change to Durable Journal v1.1, StorageBoundary, the gate, the commit layer, retrieval, the compiler or any existing test. GW-1 and GW-3 first need the owner decisions GW-G3 and GW-G1. GW-2 needs only the fingerprint rule, but the stop rule applies and it is **not patched** here.
