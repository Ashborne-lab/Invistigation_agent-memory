# Evidence Store Boundary v1: Implementation Report (Phase 2 stop at E-5)

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. **Stopped in Phase 2 at E-5**, by the brief's own rule. No contract, code, test or Gateway wiring was created or changed.

**Labels:** [PROVEN], [INFERENCE], [OWNER], [CONTRACT_GAP], [LEGACY], [DECISION].

**Supersedes:** the Phase 1 report previously held in this file. Phase 1 was BLOCKED on the commit-ledger home, and that block is now resolved by `commit-ledger-authority-decision-v1.md` (journal authority).

**VERDICT: EVIDENCE BOUNDARY V1 BLOCKED.**

---

## 1. Why the workstream stopped

The brief for E-5 says:

> Determine from source whether ingest acknowledgement requires durable recoverability. If source does not prove durable-before-ack: **mark E-5 CONTRACT_GAP and stop.** Do not manufacture a production durability guarantee.

Source does not prove durable-before-ack. Source in fact documents the **opposite** semantic (§3, E-5). Two hard stops also apply: "a guarantee is not actually supported by source" and "a production durability/availability property is being invented". A third would follow from imposing the guarantee anyway: "a Lane A semantic must change".

E-5 is the only guarantee whose text includes "and stop". E-8 marks its open items owner-held without a stop. The stop is therefore taken as written.

Durability is also the purpose of this workstream. Its job is to replace the Gateway's process-memory evidence authority with a durable boundary (`next-architecture-work-decision-v2.md` §4: "a durable property currently rests on process memory"). A boundary contract that leaves acknowledgement durability undefined cannot close that gap.

## 2. Status of E-1 … E-8

| Guarantee | Status | Note |
|---|---|---|
| E-1 Identity / idempotency | Derivation findings recorded (§3). **Not promoted to contract** | Stopped before Phase 3 |
| E-2 Sealed content integrity | Derivation findings recorded. Not promoted | — |
| E-3 Receipt ordering | Derivation findings recorded. Not promoted | — |
| E-4 Lifecycle | Partial derivation recorded. Not promoted | The Legal-owned reversal edges are untouched |
| **E-5 Acknowledgement** | **[CONTRACT_GAP]: the stop point** | §3, §4 |
| E-6 Fence reads | **Not derived** (stopped at E-5) | — |
| E-7 Commit relationship | **[DECISION], recorded** | Closed decision, verbatim (§3) |
| E-8 Erasure | **Not derived** as a contract (stopped at E-5). Source paths are listed in §3 for the resumption | — |

## 3. Derivation findings

All of the following are **findings**, not contract. Paths are relative to `memory-prototype/memory_core/`. Line numbers are from the current local prototype.

### E-1 Identity and idempotency

| Finding | Label | Source |
|---|---|---|
| The evidence id is **store-assigned and opaque** (`_id("ev_")`). Lane A callers never supply it | [PROVEN] | `runtime/__init__.py:233` (`write_message`), `:993` (`operator_assert`) |
| Redelivery dedup key = `ids.dedup_key(org_key, channel, provider_msg_id)`, an org-keyed value. It is gated by the Decisions flag `inbound_dedup` | [PROVEN] (mechanism: HMAC; semantic: per-org, per-channel provider id) | `runtime/__init__.py:228-231, 243-245`; `ids/__init__.py:50` |
| A dedup hit **returns the existing evidence unchanged** (redelivery = the same evidence) | [PROVEN] | `runtime/__init__.py:230-231` |
| **Dedup precedes receipt ordering:** the hit returns before `self._rseq += 1`, so a duplicate consumes no `receipt_seq` | [PROVEN] | `runtime/__init__.py:228-232` |
| "Same id + different content → refused" is a **Gateway/reference rule** (EVIDENCE_ID_REUSED), not Lane A semantics, because Lane A ids are never caller-supplied | [PROVEN] (as the location of the rule) | `gateway/__init__.py` `ingest_evidence` |
| Same provider message id with **different text**: Lane A returns the original evidence and does not compare content | [PROVEN] (behaviour); whether that is intended is [INFERENCE] | `runtime/__init__.py:230-231` |
| Binding: `_stamp` sets subject = source member = the bound subject, and records the org/subject/session epochs and the merge ids at ingestion | [PROVEN] | `runtime/__init__.py` `_stamp` |

### E-2 Sealed content integrity

| Finding | Label | Source |
|---|---|---|
| Seal states: `unsealed`, `sealed`, `withdrawn`, `tampered` | [PROVEN] | `model.py` `Evidence.seal_state` |
| `seal()` applies only from `unsealed`. It sets `sealed_hash = ids.sealed_hash(org_key, role, author_role, channel, text)` | [PROVEN] | `runtime/__init__.py:267-273`; `ids/__init__.py:45` |
| `seal_sweep` seals unsealed active evidence older than a window (R-24) | [PROVEN] (the window value is a Decisions parameter, not fixed) | `runtime/__init__.py:275` |
| An edit of text or role on sealed evidence (with `require_seal`) → `tampered`, which quarantines the claims it supports | [PROVEN] | `runtime/__init__.py:296-321` |
| A delete of sealed evidence → status `invalidated`, seal `withdrawn`, support dropped, recorded in WORM. **Withdrawal is a lifecycle change, not a content mutation** | [PROVEN] | `runtime/__init__.py:306` |
| `_verify_seals` recomputes the hash and marks a mismatch as tampered | [PROVEN] | `runtime/__init__.py:331` |
| Extraction requires `registered` and (if `require_seal`) `seal_state == "sealed"` | [PROVEN] | `runtime/__init__.py:340` |
| Content is immutable only **after** sealing, and only under `require_seal`. Before sealing, edits are allowed. Status fields remain mutable throughout | [PROVEN] | as above |

### E-3 Receipt ordering

| Finding | Label | Source |
|---|---|---|
| `receipt_seq` is assigned **by the store, inside the write transaction**, from one store-wide monotone counter `_rseq` | [PROVEN] (in the prototype: the scope is the whole store) | `runtime/__init__.py:232, 994`; `model.py` comment "evidence-store commit order (server-assigned)" |
| `observed_at` is the receipt time when `order_by == "receipt"` or there is no `app_ts`; otherwise it is the caller's `app_ts`, which may be skewed | [PROVEN] | `runtime/__init__.py:234` |
| The commit layer uses `observed_seq = max(receipt_seq)` over anchors. This is separate from journal commit time (K1, K2) | [PROVEN] | `commit/__init__.py` `commit()` |
| `receipt_seq` **durability across restore:** not established. `restore.py` notes that store counters are not restored | [CONTRACT_GAP] | `runtime/restore.py` |
| Whether the production ordering scope is per-store, per-org or per-subject | [CONTRACT_GAP] (the prototype's store-wide scope is a mechanism) | — |

### E-4 Lifecycle (partial)

| Edge | Cause | Source |
|---|---|---|
| (written) → `active` | ingest | `runtime/__init__.py:222-245` |
| `active` → `pending_erasure` | registered after its subject was erased | `:261` |
| `active` → `invalidated` (seal `withdrawn`) | a delete of sealed evidence | `:306` |
| any → `erased` | `erase_evidence` (single record) | `:721` |
| → `context_suppressed` | `forget_fact` (agent echoes and anchors) | `:734, :753` |
| → `pending_erasure` | `forget_me` | `:801` |
| physical removal (and its dedup keys) after the archive window | `physical_deletion_job` (the window is a Decisions value; `None` → does not run) | `:832-866` |

- The fence refuses evidence that is missing or in `DEAD = {erased, pending_erasure, invalidated, context_suppressed}` (`fence/__init__.py:11, 55`) [PROVEN].
- No reversal edges were derived. These are Legal-owned and untouched.
- A full transition table (including guards against illegal edges) was not finished.

### E-5 Acknowledgement semantics: [CONTRACT_GAP]

**Finding: source does not prove durable-before-ack, and Lane A documents the opposite.**

| Source | What it shows |
|---|---|
| Durable contract v1.1, Part 1 item 8 (`durable-journal-rebuild-contract-v1.md:72`) | It **classifies** "Evidence and its status" as a "Durable fact (evidence store)". It says nothing about **when** evidence becomes durable relative to acknowledgement |
| `memory-restore-protocol-v1.md:48` | "Claims left with no support become `invalidated(lost_in_restore)`. Their content was lost with the evidence store's **RPO window**" |
| Same, `:56` | Firestore-only restore: "Later evidence lost (RPO)… No invariant violation" |
| Same, `:97` | "Evidence lost by an FS restore: **Unrecoverable by design.** The RPO of the evidence store is the RPO of memory" |
| Same, `:96` | RPO/RTO per tenant: `[BLOCKED:Product/Ops]` |
| `runtime/__init__.py` `write_message` / `ingest` | The function returns the evidence object. There is no durability concept or acknowledgement contract in the prototype |
| `next-architecture-work-decision-v2.md:120` | E-5 appears only as a **plan candidate** ("durable before the ingest acknowledgement"). By the brief's rule it is not promoted on that basis |

**Consequences:**
- Lane A's current semantic is that **acknowledged evidence may be lost within the evidence store's RPO window**, with recovery by `invalidated(lost_in_restore)`.
- Contracting durable-before-ack would **change that Lane A semantic** and **invent a production durability property** (RPO = 0 at acknowledgement). Both are hard stops.
- **Correction to `next-architecture-work-decision-v2.md` D1** (recorded here only, since that file is outside this brief's deliverables): D1 states that the evidence-store semantics are "already fixed by Lane A" and only durability *values* belong to C-5. That overreached for E-5. Whether acknowledgement implies durability is itself a semantic choice, and source leaves it to Product/Ops.

### E-6 Fence reads: not derived

Stopped at E-5. For the resumption: the fence reads `Stamp(evidence_id, exists, status, epochs, scope ids, merge_ids, subject_id, observed_at)`, built by `commit._stamp` [PROVEN, as an input list only].

### E-7 Commit relationship: [DECISION]

> **The Durable Journal owns authoritative commit records and outcomes. Evidence stores evidence and the references/anchors needed to associate claims with that evidence.**

- Source: `commit-ledger-authority-decision-v1.md`.
- Lane A's `ev.commit_records`, `replay_record`, the LA-10 `replay_watermark` and `restore.py` are [LEGACY], prototype-only. No production repo contains them.
- No cross-store transaction is required.
- No new contradiction was found in this pass.

### E-8 Erasure: not derived as a contract

The source paths are listed under E-4. Not decided here, and they remain owner-held: retention values, reversal, key destruction (the prototype crypto-shreds at `:852`), SLA and latency.

## 4. The decision required (not taken here)

**[OWNER] Product/Ops, with Infrastructure** (it interacts with C-5). The question:

> **Must an evidence ingest acknowledgement imply durable recoverability (no acknowledged evidence is lost on restore)? Or is the Lane A semantic intended, under which acknowledged evidence may be lost within the evidence store's RPO window and supported claims become `invalidated(lost_in_restore)`?**

| Answer | Effect on this workstream |
|---|---|
| **Durable-before-ack** | E-5 becomes a contract requirement. Lane A's "unrecoverable by design" row is superseded for the target by an explicit decision record. Production feasibility goes to C-5 |
| **RPO-window semantics (Lane A)** | E-5 is contracted as "acknowledgement does not imply durability; loss within RPO is surfaced as `lost_in_restore`". The Gateway can then only claim that, and the RPO value stays `[BLOCKED:Product/Ops]` |

Either answer lets Phase 2 resume at E-5, followed by E-6 and E-8, and then Phases 3 and 4. E-1 to E-4 above can be reused, with the open [CONTRACT_GAP] rows carried forward.

**What this blocks:** the evidence-store contract, the `evidence_boundary` module, its tests, and the Gateway wiring (Gateway §11 stays a [CONTRACT_GAP]).

**What it does not block:**
- Gateway v0.1 (CONFORMANT as a test-only reference);
- Journal v1.1;
- C-5's request (unchanged; this is not delivery);
- the rest of the backlog.

## 5. Tests, regression, mutation

| Item | Result |
|---|---|
| New tests | None. No code was written |
| Reference stores | Not built |
| Mutation run | Not applicable |
| Gateway G0 / adversarial | Untouched (38 / 109; no file changed) |
| Full suite | Untouched at **1202** (no code or test file changed; not re-run) |

## 6. Files changed

| File | Change |
|---|---|
| This report | Rewritten (the Phase 1 report is superseded) |
| `MASTER.md` | Entry |

## 7. Exact next gate

**[OWNER] Product/Ops + Infrastructure: the E-5 question in §4.**

**VERDICT: EVIDENCE BOUNDARY V1 BLOCKED.**
