# Memory Gateway Contract v0.1 (CUSTOMER scope)

**Date:** 2026-10-04.

**v0.1 (2026-10-04)** fixes the audit defects GW-1, GW-2 and GW-3 and corrects the identity-authority text (GW-G2):
- see `memory-gateway-defect-decisions-v1.md` and `memory-gateway-v0-patch-v1.md`;
- changed sections: §2, §6, §8, §11, §12, §13, §16.

**Classification:** TARGET ARCHITECTURE. A reference contract with an in-memory, test-only implementation. Not a production service.

**Executable form:**
- `memory-prototype/memory_core/gateway/__init__.py`, the reference composition;
- `memory-prototype/tests/test_memory_gateway_v0.py`: **38 tests**, 19 scenarios run against both reference stores.

**Labels:** [PROVEN] (by a test that runs against both reference stores, or by mutation), [CONTRACT_GAP], [OWNER], [INFERENCE].

**Builds on, and does not change:**
- Durable Journal Contract **v1.1** (K1–K10, S1–S5);
- X-1;
- the Claim Gate;
- the commit layer;
- typed retrieval;
- the Context Compiler;
- Lane A handles;
- the read rule `may_read`.

The Pipeline is not used: it remains a test harness.

---

## 1. Purpose and boundary

The Gateway is the **only** caller-facing boundary to person memory. Callers never reach the core directly. The core it fronts:

```text
caller ──► Gateway ──► Evidence ─► Policy Registry ─► Claim Gate ─► Commit / Journal (TimedJournal over StorageBoundary)
                                                                       ─► Current State ─► Typed Retrieval ─► Context Compiler
```

**What v0 does:**
- binds every call to a conversation;
- admits writes through the gate and the journal;
- serves reads at a position the journal closed;
- returns context as data.

It adds **no** semantics of its own beyond the composition rules stated here [PROVEN by composition: no core module was modified].

## 2. Trust model and caller binding

- **A subject reference is never authority** (fixes red-team C-4).
- Every read and every write presents a **conversation handle**: Lane A `memory_core.handle`, HMAC-signed and binding org, agent, session, subject and member-set version, with an expiry.
- The Gateway verifies the handle (`verify`), then authorises it for the subject (`authorize(..., scope="person")`: same org, same subject, member-set version).
- **Binding authority (v0.1, GW-G2):** the org, merge root and member-set version used here are **identity-layer state**: the subject head (Lane A heads; A7 `subjects` fed only by identity events; identity bindings are authoritative, C-1a). **Evidence is not the identity authority.** v0's mapping derived from ingestion is a **test/reference stub**, used only because identity events are excluded.
  - **Both reads and writes** depend on this identity-layer binding.
  - Its production durability, availability and interface to the Gateway are an explicit **[OWNER]** dependency (identity owner, plus Infrastructure).
  - Without the binding (for example after a restart of the reference without its stub), binding **fails closed** [PROVEN].
- It then builds a `Caller` scoped only to `("CUSTOMER", handle.subject)` and applies the single read rule `may_read` inside retrieval.
- **Handles are issued** per turn by `ingest_evidence` and `issue_handle`, from the evidence's own conversation (Lane A issuance).

**Refusals [PROVEN]:**

| Situation | Result |
|---|---|
| No handle | HANDLE_REQUIRED |
| A handle for another subject | ACCESS_DENIED:wrong_subject |
| Forged handle | ACCESS_DENIED:bad_signature |
| Expired handle | ACCESS_DENIED:expired |

These apply to **reads and to mutations**. A refused mutation leaves nothing durable.

**v0 simplifications, stated:**
- no merges exist (identity events are excluded), so the subject root is the subject and the member-set version is 0;
- assurance uses Lane A's default requirement. Raising it per operation is [OWNER].
- Service-to-service authentication of the calling service (OIDC in v2 §U) is outside the in-memory reference [OWNER: Security / Infrastructure].

## 3. CUSTOMER scope

- Only `CUSTOMER` is served.
- A name outside the contract's scopes (for example `ORG`, `RELATIONSHIP`) gives **INVALID_SCOPE**.
- A contract scope other than CUSTOMER (TENANT, WORKSPACE, AGENT, SESSION, RESOURCE, GLOBAL) gives **UNSUPPORTED_SCOPE** [PROVEN].
- Non-CUSTOMER grants are [OWNER] (Security / Product).

## 4. Operations

| Operation | Caller | Effect |
|---|---|---|
| `ingest_evidence(evidence, clock, ttl)` | A channel service | Records evidence (never a claim). Returns `(evidence_id, handle)` for that conversation turn |
| `issue_handle(evidence_id, clock, ttl)` | A channel service | A fresh per-turn handle (Lane A issuance) |
| `propose_observation(handle, proposal, clock)` | Extraction (LLM) | An **observation**: evidence becomes a claim through the gate. Never a state command |
| `command(handle, proposal, expected_version, clock)` | Agent tool (typed writer) | A **typed state command** with OCC |
| `get_current_state(handle, subject, clock, predicate?, after?, scope?)` | Agent runtime | Current state (contract §11 result), with the served position r |
| `search_history(handle, subject, clock, predicate?, after?, scope?)` | Agent runtime | History, always HISTORICAL usage, with r |
| `compile_context(handle, subject, profile, budget, clock, after?, request?)` | Agent runtime | A context package as **data**, with r |

**Administration (not a caller operation in v0):** `publish_policy` publishes a policy version to the registry and the journal. Real policy governance is [OWNER] (B-1 and related).

## 5. Request and response semantics

| Result type | Fields |
|---|---|
| `WriteResult` | `status`, `at` (the journal-assigned commit time), `reason`, `actual_version` (STATE_CONFLICT only), `original` (DUPLICATE only), `attempts` |
| `ReadResult` | `status` (`OK` or a typed refusal), `r`, `result` (a typed retrieval result) |
| `ContextPackage` | `status`, `r`, `channel` (always `memory_data`), `memory_data`, `manifest` |

Mis-routed writes are refused:
- an observation sent to `command` gives NOT_A_COMMAND;
- a typed writer sent to `propose_observation` gives NOT_AN_OBSERVATION [PROVEN].

## 6. Served positions and causal tokens

- **Every read returns its served position r** [PROVEN].
- Every v0 read is a **current read** (K7): it closes the subject's sources through r = max(clock, `after`) **before** reading (K5). It is then answered from a source reconstructed from durable facts at r.
- **Read-your-writes:** pass the commit time of your write, or the r of your last read, as `after`. The read is then served at r ≥ that token and contains the write [PROVEN].
- **Causal-token validity (v0.1, GW-1 / GW-G3).** `after` is accepted only if it is **either**:
  - a **finite number ≤ B**, where B = max(Gateway clock, the latest durable commit time in the bound subject's partition); **or**
  - a **Gateway-signed causal token** for the **same (org, subject)**.

  Anything else returns **INVALID_CAUSAL_TOKEN**, decided **after binding and before any closure**, with no core access. Rejected: future and huge values, ±inf, NaN, wrong types, forged or position-modified tokens, and tokens for another org or subject [PROVEN].
- **Token issuance:** every read and write result carries a signed `token` for its position. Signed tokens give monotonic reads across Gateway nodes with skewed clocks [PROVEN]. The signing key is domain-separated from the handle MAC and in the **same custody class** as the handle secret (C-1 [OWNER]).
- `ContextPackage` keeps its v0 shape (no token field); its `r` is accepted as a numeric token within the bound.
- **No stale-tolerant read class exists in v0.** Which reads may be served from an already-closed or lagging position is [OWNER] Product (X-1 §12). The Gateway does not invent one.

## 7. Write admission and conflicts

**The write path for both operations [PROVEN]:**
1. Bind the handle.
2. Check for a recorded duplicate (§8).
3. The **real gate** (`decide`) runs on the slot state reconstructed from durable facts. Gate reads are not consumers (X-1 §3.1).
4. Inside the journal's commit step, the **real `commit()`** builds the record on a throwaway store rebuilt from durable facts at the **journal-assigned** time. The record's `committed_at` equals that time (K2).
5. The journal's serialized write re-checks closure, O1, OCC and the stamp at that time (K9).

**Outcomes:**

| Outcome | Behaviour |
|---|---|
| Observation | Recorded as a claim. Resolution decides what is current. No `expected_version` |
| Typed command | Requires `expected_version`. A mismatch gives **STATE_CONFLICT** with `actual_version`, **never retried by the Gateway**, never durable [PROVEN]. This holds whether the conflict is found when the record is built or at the serialized write when the slot changed in flight. Once a conflict is seen, no further attempt is made for that command [PROVEN] |
| READ_CLOSED / COMMIT_TIME_REGRESSED | Transient. Retried with a new time, every check again, up to a TEST_ONLY budget of 3 retries (the real budget is [OWNER] Infrastructure). On exhaustion, READ_CLOSED is returned and **not recorded**, so a later retry re-enters with the **same** attested gate decision [PROVEN] |
| A conflict is never converted into a successful write | [PROVEN] |

## 8. Idempotency

- **Command ids** (`proposal_id`) are single-use.
- **Namespace (v0.1, GW-G1):** `(org_id, subject_id, command_id)`, homed in the bound subject's journal partition, consistent with durable contract v1.1 §C. The same id on another subject or org is **another** command.
- Every **terminal** outcome (APPENDED, STATE_CONFLICT, STALE_POLICY_STAMP, a gate refusal) is recorded durably as a `commit_outcome` entry in the subject's partition (contract §A kind). It carries no value.
- A repeated command id returns **DUPLICATE** with the **original** outcome and time, even if the retry would now succeed [PROVEN].
- **Fingerprint (v0.1, GW-2):** the outcome records the command's canonical content fingerprint. This is the gate's `fingerprint`: subject, org, predicate, policy version, operation, writer, source, value, sorted anchors, map key and validity. `expected_version` is a precondition, not content.
  - The same id with a **different** fingerprint returns **COMMAND_ID_REUSED**.
  - That refusal is not recorded, and the original outcome is unaffected [PROVEN].
- **Only durable outcomes decide (v0.1, GW-3).** The gate gets a fresh ledger per call. No in-process state can change a terminal outcome, including across a restart [PROVEN].
- The duplicate is decided **before any time is assigned**: no prepare and no `assign` happen [PROVEN] (K8).
- Transient results are not terminal and are not recorded.

## 9. Policy stamps

- A proposal carries the policy version it was made under.
- If that version is not the one in force, the result is **STALE_POLICY_STAMP**:
  - at the gate (`stale_policy_version`);
  - or at the serialized write (K9).
- It is recorded as terminal: the same command id returns the same outcome. The command is **never reinterpreted** under the newer policy; the caller issues a new command [PROVEN].

## 10. Context compilation and the data channel

- `compile_context` composes **typed retrieval results only**: current state plus history at the same r. It runs the real Context Compiler unchanged (sanitisation, bracket escaping, the "not instructions" header and footer, budget, manifest).
- **The data channel [PROVEN]:**
  - the result is a `ContextPackage` with `channel = "memory_data"`, and **no instruction field**;
  - the operation **accepts no instruction text** to merge with;
  - memory is never concatenated into instruction text by the Gateway;
  - hostile text in a memory value stays inside the framed block, and its brackets are neutralised.
- **Size measure (preserved) [PROVEN]:**
  - `manifest.truncation.used == len(memory_data) ≤ budget`;
  - characters are the existing TEST_ONLY size unit;
  - a production unit (for example tokens) is not decided here.
- **Task profiles** are TEST_ONLY. Production profiles and mandatory/degraded choices are [OWNER] Product (X-2).

## 11. Evidence ingestion and identity dependencies: [CONTRACT_GAP] / [OWNER]

**v0.1 correction (GW-G2):**
- The evidence store is **not** the identity authority.
- The subject's org, merge root and member-set version come from the **identity layer** (§2), which reads and writes both depend on. In v0 that layer is stubbed from ingestion.
- Its production guarantees and interface are [OWNER] (the identity owner).

The rest of this section concerns the evidence store only.

- `ingest_evidence` needs an **evidence store**.
- No contract specifies its storage guarantees: journal S1–S5 do not cover it, and the durable-journal contract only lists evidence as a durable fact (Part 1, item 8).
- The Gateway therefore **declares, not assumes**: `EVIDENCE_STORE_GUARANTEES` marks durability, ordering, closure, transactions and consistency as **CONTRACT_GAP** [PROVEN by test].
- The only behaviour relied on is the existing ingest rule: an evidence id reused with different content is refused (EVIDENCE_ID_REUSED).
- **The rebuild of memory does not need the evidence store** (claims carry their anchors), but **admitting** new claims does: the gate and the fence read evidence.
- **Owner:** the evidence store's guarantees must be specified, which is a contract extension, before any durable Gateway [CONTRACT_GAP → contract owner + Infrastructure].

## 12. Error taxonomy

| Code | Class | Retry? |
|---|---|---|
| HANDLE_REQUIRED | Binding | Obtain a handle |
| ACCESS_DENIED:`code` (wrong_subject, bad_signature, expired, stale_handle, cross_org, unknown_subject) | Binding | No (re-issue the handle per turn) |
| INVALID_SCOPE / UNSUPPORTED_SCOPE | Scope | No |
| NOT_AN_OBSERVATION / NOT_A_COMMAND | Routing | No (use the other operation) |
| STATE_CONFLICT | Semantic, typed | **Never by infrastructure.** The agent re-reads and decides (architecture contract §7) |
| STALE_POLICY_STAMP | Semantic, typed | No: issue a new command under the current policy |
| GATE_REFUSED (with the gate's reason) | Semantic | No |
| READ_CLOSED | Transient | Yes. The Gateway retries within its budget; the caller may retry later |
| INVALID_CAUSAL_TOKEN (v0.1) | Read input | No: present a valid token, or a number within the bound |
| COMMAND_ID_REUSED (v0.1) | Idempotency | No: use a new command id |
| DUPLICATE (with `original`) | Idempotency | — |
| EVIDENCE_ID_REUSED | Ingest | No |

## 13. Durability and rebuild assumptions

- **Journal facts:** durable only to the degree the chosen `StorageBoundary` provides S1–S5. v0 runs on the in-memory references; real durability is C-5 [parked].
- **Rebuild [PROVEN]:**
  - a read served by the Gateway equals typed retrieval over a source reconstructed from durable facts at the same r, after a store crash;
  - served-prefix immutability and stamps hold.
- **Process state:** the Gateway holds two kinds, and both are non-authoritative:
  - the gate ledger and pending gate decisions, which only matter for retries within a process life;
  - the TEST_ONLY handle secret and key provider (custody C-1 [OWNER]).

  Losing them never changes durable truth: duplicates are decided from durable outcomes [**PROVEN in v0.1**: clearing process state between calls, and restarting, give identical outcomes. In v0 this was false (GW-3)].

## 14. Explicit exclusions

Not modelled in v0. These are not placeholders:
- TENANT, AGENT, SESSION, RESOURCE, WORKSPACE, GLOBAL;
- RELATIONSHIP (not a contract scope);
- cross-agent grants;
- Agent Knowledge;
- erasure operations (`forget_fact`, `forget_me`, `erase_scope`, reversal);
- identity events (merge, undo, transfer) and member-set changes;
- `explain`;
- operator (non-handle) reads and roles;
- `get_commitments` / `search_memory` (narrative);
- X-4 injection monitoring;
- service-to-service authentication;
- the Gateway as a deployed service (roadmap C2, behind C-5).

## 15. Open owner-held decisions

| Decision | Owner |
|---|---|
| Stale-tolerant read classes (which reads may be served as-of or from lagging views) | Product |
| Retry budget for transient refusals | Infrastructure |
| Assurance level required per operation | Security / identity owner |
| Service-to-service authentication of callers | Security / Infrastructure |
| Non-CUSTOMER grants; commitment cross-agent visibility | Security / Product |
| Production task profiles; mandatory and degraded context | Product (X-2) |
| Production size unit for context | Product / Engineering |
| Key custody (handle secret and subject keys) | Security (C-1) |
| Evidence-store guarantees (§11) | Contract owner + Infrastructure [CONTRACT_GAP] |
| Real policies | Governance / domain owners (B-1…) |
| Storage technology | Infrastructure (C-5, parked) |

## 16. Conformance requirements

An implementation of this contract passes `tests/test_memory_gateway_v0.py` **unchanged** on every storage it is deployed over.

**Reference result:** `ExplicitFrontierStore` 19/19 and `ImpliedFrontierStore` 19/19.

**v0.1:** `tests/test_memory_gateway_adversarial_v0.py` (109 tests) also passes on both stores, with no xfails.

**What the suite covers:**
1. Caller binding (C-4), for reads and mutations.
2. Authorised CUSTOMER read and write.
3. A served position on every read.
4. Read-your-writes with a causal token.
5. A stale typed command gives STATE_CONFLICT, at build time and **in flight**, and is never retried.
6. Transient READ_CLOSED retry, and exhaustion that is not recorded.
7. STALE_POLICY_STAMP is never reinterpreted.
8. A duplicate returns the original outcome, decided before time.
9. Rebuild equals what was served.
10. The data channel and the size measure.
11. Invalid and non-CUSTOMER scopes.
12. The evidence-store gap is explicit.
13. Caller independence (two conversations, one truth).
14. Determinism.

**Mutation run:** 10 Gateway rules were each removed in turn, and every removal is caught. The rules are:
- handle required;
- subject binding;
- duplicate before time;
- conflict at the write and at build never retried;
- transient retry;
- stale stamp typed;
- r returned;
- causal token;
- scope check.
