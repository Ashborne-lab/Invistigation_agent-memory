# Memory Gateway Defect Decisions v1 (GW-G1, GW-G3, GW-G2)

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE decision closure. **No code, test, contract or storage change.**

**Labels:** [PROVEN], [INFERENCE], [OWNER], [CONTRACT_GAP], [DECISION].

**FINAL GATE: READY TO PATCH.**
- GW-G1 and GW-G3 are decided from existing architecture evidence. Neither introduces a new owner dependency.
- GW-G2 is clarified: the authority source is established, and the remaining work is identity-layer integration plus an [OWNER] item. It does **not** block GW-1…GW-3.

---

## 1. Current defect state (as proven in `memory-gateway-adversarial-audit-v0.md`)

| Defect | Proven behaviour (both stores) | Reproducer |
|---|---|---|
| **GW-1** | A caller-supplied `after` is not validated. `after=1e9` → the read is served at 1e9 and the next write is committed at 1e9 (knowledge time misstated). `after=inf` → explicit store: the subject's writes are READ_CLOSED forever; implied store: the next commit is at `inf` on the **global** sequence | `test_defect_gw1_*` (xfail strict) |
| **GW-2** | The same command id with **different content** → DUPLICATE with the original APPENDED | `test_defect_gw2_*` |
| **GW-3** | The same command id on **another subject** → GATE_REFUSED with the in-process gate ledger, APPENDED after process-state loss | `test_defect_gw3_*` |

**Additional observation from this phase** [PROVEN by probe; not a new defect]:
- The gate's in-process ledger also de-duplicates **identical content under a new id**.
- The terminal status is the same with or without the ledger (GATE_REFUSED), but the **reason** differs: `duplicate_of_p1` with the ledger, and the commit layer's existing-claim path without it.
- This confirms the root cause of GW-3: a non-durable ledger takes part in deciding outcomes.

## 2. GW-G1: the command-id namespace

### Evidence

| # | Evidence | Label |
|---|---|---|
| E1 | Architecture contract §7: "Every mutation carries a unique `mutation_id`. Replaying it produces the same result… idempotency MUST attach to the logical command" | [STATED] |
| E2 | Durable contract v1.1 §C: "**Proposal idempotency:** `commit_intent` / `commit_outcome` in the **proposal subject** [partition] (stable across target changes)" | [PROVEN] (`exactly_once_across_retries_and_target_change`) |
| E3 | Journal `Entry.idem`: "idempotency identity, **unique within the partition**". S1–S5 provide single-partition conditional writes and **no** cross-partition atomicity (v1.1 Part 3) | [PROVEN] |
| E4 | A7 §1: subjects are keyed `(org_id, subject_id)`. Every memory table leads with `org_id` | [STATED] |
| E5 | Gateway v0 binds every write to one `(org, subject)` before any core access | [PROVEN] (audit §4) |

### Candidates

| Criterion | 1. Per CUSTOMER subject `(org, subject, id)` | 2. Per tenant `(org, id)` | 3. Global `(id)` |
|---|---|---|---|
| Idempotency semantics | Replay of a command = same subject plus same id. Exactly E2 | Same | Same |
| Durable lookup | One S4 read of the bound subject's own partition (`outcome:<id>`) | A **tenant-wide index**: a store outside any partition, or a scan of every partition of the org | A **global index** across every partition |
| Uniqueness enforcement | A conditional append in one partition (S1/S5) | Needs an atomic check-and-insert across **all** partitions of a tenant, or a new tenant-level source with its own closure. That is cross-source coordination S1–S5 do not provide (E3) | The same, globally. It reintroduces a global serialization point, which the durable contract proved unnecessary |
| Process restart | Durable: the outcome lives in the partition | Durable only if the new index is durable (unspecified) | Same |
| Partition ownership | Matches E2: the command belongs to the proposal subject | Crosses partitions | Crosses everything |
| Fit with Durable Journal v1.1 | **Native** | Requires a new storage capability beyond S1–S5 | Same |
| Same id reused for another subject | An **independent** command (deterministic) | Refused | Refused |
| Cross-org collision | Impossible to address: binding refuses a foreign org (E5), and subject identity is org-qualified (E4) | — | — |
| Operations and debugging | Ids are interpreted with their subject. Callers that already mint globally unique ids (UUIDs) lose nothing | A global-unique feel, at the cost of a new index | Same |

### [DECISION] Namespace = per CUSTOMER subject: `(org_id, subject_id, command_id)`

**Why.** The architecture already puts proposal idempotency in the proposal subject's partition (E2), with uniqueness inside one partition (E3). Options 2 and 3 would need a storage capability outside S1–S5 (a cross-partition uniqueness index), which the contract does not provide and does not need. E1's "unique `mutation_id`" is satisfied: within its namespace an id denotes exactly one logical command. This is derived from existing contracts, not chosen for convenience.

| Item | Decision |
|---|---|
| **Durable home** | The bound subject's journal partition. A `commit_outcome` entry with `idem = "outcome:" + command_id` and payload (status, at, reason, …, **content fingerprint**). The subject is org-qualified (E4); in the v0 reference, subject ids are org-unique because binding enforces one org per subject (E5) |
| **Exact lookup key** | `(org_id, subject_id)` → partition; `"outcome:" + command_id` → entry. Decided **before any time is assigned** (K8) |
| **Duplicate** (same key, same fingerprint) | DUPLICATE with the **original** recorded outcome and time |
| **Same id, different content** (same subject) | A typed refusal, **COMMAND_ID_REUSED**. Nothing is evaluated and nothing is recorded (fixes GW-2) |
| **Same id, different subject** (same org) | A **different command**. It is decided on its own merits, deterministically from durable facts (fixes GW-3) |
| **Same id, different org** | Not addressable: caller binding refuses a foreign org before the namespace is consulted |
| **Process state** | **Never decides an outcome.** The gate is called with a **fresh, per-call ledger**: the gate is unchanged, and its step-0 idempotency is subsumed by the durable lookup. Pending decisions across transient retries are an optimisation only. After loss, the retry re-decides from durable facts, which is permitted because nothing terminal was recorded (audit category 4, proven) |

## 3. GW-G3: causal-token validity

### Requirements (from existing contracts; no new time model)

- K3: a partition's closed position never runs ahead of the reading node's clock, **or of an already-assigned time carried as a causal token**.
- K7: a current read is served at `r = max(clock, token)`, where the token is the caller's last acknowledged write time or last served read position.

So a valid token is **an already-assigned position**. Anything else must not move closure.

### Candidates

| Criterion | 1. Signed tokens only | 2. Durable-position bound only | 3. **Hybrid: bound ∪ signed** |
|---|---|---|---|
| Mechanism | The Gateway issues `token = MAC(key, org, subject, position)` with every write and read. `after` must verify | Accept a numeric `after` only if finite and `≤ B = max(gateway clock, the subject's latest durable commit time)` | Accept `after` if it is a **finite number ≤ B**, **or** a **valid signed token** for the same (org, subject). Otherwise a typed refusal |
| Arbitrary future position / `inf` / NaN | Prevented: never issued | Prevented: above B, or not finite | Prevented: both paths |
| Denial of service through closure | Prevented | Prevented: closure never exceeds B, which is at most "now" or an existing commit | Prevented |
| Read-your-**writes** (own write time) | Yes | Yes: the write time ≤ the latest durable commit ≤ B | Yes |
| Monotonic reads across skewed Gateway nodes (a read token from a node ahead) | Yes | **No.** The token (> local B) is refused until the clock catches up. That is safe but a K7 regression | **Yes**, through the signed path |
| Fit with X-1 / K1–K10 | Yes | Yes for safety; weaker on K7 for read tokens | **Yes; enforces K3's "already-assigned"** |
| Store read needed | No | One S4 read of the subject partition (its last commit time) | Bound path: yes (the same read the current read already performs); signed path: no |
| Transferable between conversations | Within the same (org, subject): yes, since CUSTOMER = the person | A number has no binding; it is harmless because it is ≤ B | Signed: bound to (org, subject); number: harmless |
| Subject- and org-bound | Yes (MAC) | Bound by computing B for the **bound** subject | Yes |
| Restart behaviour | Needs the signing key to persist | Durable: B comes from durable commits and the clock | Both paths survive with the key persisted; the bound path needs nothing more |
| Explicit and implied stores | Neutral | Neutral. On the implied form this also protects the **global** sequence from `inf` | Neutral |
| Compatibility with the existing v0 API | **Breaks** it: v0 and its tests pass plain numbers | Keeps it | **Keeps it.** Plain numbers within B still work, and signed tokens are additive |

### [DECISION] Hybrid: bounded numbers OR Gateway-signed tokens

**The rule:** `after` is accepted if either of these holds; otherwise the result is the typed refusal **INVALID_CAUSAL_TOKEN**, before closure and with no core write:
1. it is a finite number with `after ≤ B`, where `B = max(gateway clock, latest durable commit time in the bound subject's partition)`; or
2. it is a token signed by the Gateway for the **same (org, subject)**, carrying a position the journal assigned or served.

**Issuing:** every `WriteResult` and `ReadResult` additionally returns a signed causal token for its position. The key is domain-separated from the handle MAC.

**Why the hybrid:**
- **The bound alone** prevents every GW-1 attack but refuses legitimate read tokens from skewed nodes, which is a K7 regression.
- **Signing alone** fixes K7 fully but breaks the existing v0 numeric API, whose tests must not be edited.
- **The hybrid** keeps K7 intact, keeps v0 compatible, and makes K3's "already-assigned time" enforceable: no caller can manufacture a future knowledge position, since a number is capped at B and a token cannot be forged.

**Owner dependency.** The signing key falls in **the same custody class as the existing handle secret** (C-1 key custody, already [OWNER] Security). It is **not a new owner dependency**. The bound path needs no key at all.

## 4. GW-G2: clarifying the org-authority dependency

| Question | Answer | Basis |
|---|---|---|
| Is org authority identity-layer state? | **Yes** | Lane A binding takes `subject_org` and `current_msv` from the **subject head** (`runtime._authorize`: `self.heads[...]`). A7 §0: "bindings in Firestore are authoritative for identity" (C-1a); `subjects` is keyed `(org_id, subject_id)` and fed only by `identity_events` [PROVEN by source] |
| Should it be recovered from durable subject/identity state? | **Yes.** From the identity layer's durable bindings, not from the process | Same sources |
| May evidence be the authority? | **No.** Evidence carries a subject id stamped by identity resolution (Lane A ingest), but it is not the binding authority. v0's `org_of` from ingestion is a reference stand-in | Lane A ingest and heads; A7 "Never written by extraction" |
| Does binding need subject-head/member-set authority? | **Yes:** org, merge root and member-set version, exactly what `handle.authorize` already checks. v0 fixes root = subject and msv = 0 only because identity events are excluded | `memory_core/handle.authorize` |
| Owner decision needed? | **For the semantics: no.** The authority source is established. **For the identity store's durability and availability guarantees, and its interface to the Gateway: [OWNER]** (identity owner, plus Infrastructure for storage). That is the same class as the evidence-store gap | — |
| Is the CONTRACT_GAP classification enough? | It is **inaccurate in emphasis**. Gateway contract v0 §2 and §11 should say that caller binding depends on the **identity layer's subject head** (org, root, member-set version), which v0 stubs from ingestion, and that **reads as well as admission** depend on it. The gap is "identity-layer interface and guarantees for the Gateway" [CONTRACT_GAP → identity owner], **not** an evidence-store property. Text clarification to be applied with the patch, which is a contract-text change, not a semantic one | Audit GW-G2 |

**Effect on the fixes:** none. GW-1…GW-3 are fixed with binding unchanged. The v0 stub keeps failing closed, which is proven safe.

## 5. Consequences for fixes (not implemented here)

| Defect | Decision needed | Proposed Gateway fix |
|---|---|---|
| **GW-1** | GW-G3 → **[DECIDED] hybrid** | Validate `after` before closure: a finite number ≤ B = max(clock, the subject's latest durable commit time), or a valid Gateway-signed token for the same (org, subject); otherwise INVALID_CAUSAL_TOKEN. Return a signed causal token on every read and write result |
| **GW-2** | None | Record the proposal **fingerprint** in the `commit_outcome` payload. DUPLICATE only on a fingerprint match; otherwise **COMMAND_ID_REUSED** (typed, not recorded) |
| **GW-3** | GW-G1 → **[DECIDED] per (org, subject)** | Durable lookup only, in the bound subject's partition; the gate called with a **fresh per-call ledger**. The same id on another subject is an independent command, decided only from durable facts |
| (doc) | GW-G2 clarified | Amend Gateway contract v0 §2 and §11 text: binding authority = the identity-layer subject head (stubbed in v0); the identity-interface guarantees are [OWNER] |

**Patch acceptance:**
- the 8 strict defect reproducers turn green, and their `xfail` markers are removed with the fix (strict xfail forces this);
- every other existing test passes unchanged;
- new tests are added for COMMAND_ID_REUSED, INVALID_CAUSAL_TOKEN, signed-token monotonic reads across skewed nodes, and process-state independence;
- no change to v1.1, StorageBoundary, the gate, the commit layer, retrieval or the compiler.

---

**READY TO PATCH.**
