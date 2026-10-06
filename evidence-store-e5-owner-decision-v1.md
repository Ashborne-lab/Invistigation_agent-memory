# Evidence Store E-5: Owner Decision Packet v1

**Date:** 2026-10-04.

**For:** Product/Ops and Infrastructure. Product/Ops owns RPO/RTO in every source that names an owner (§2.4). Infrastructure is included because of C-5.

**Classification:** TARGET ARCHITECTURE. A decision request only: no code, test, contract or Gateway change.

**Labels:** [PROVEN], [STATED], [INFERENCE], [OWNER], [CONTRACT_GAP], [LEGACY].

**Status:** **[OWNER DECISION REQUIRED].**

---

## 1. Decision required

> **Must an evidence ingest acknowledgement imply durable recoverability, meaning acknowledged evidence cannot be lost on restore?**
>
> **OR**
>
> **Is Lane A's existing RPO-window semantic intentional, where acknowledged evidence may be lost within the evidence store's RPO window and supported claims become `invalidated(lost_in_restore)`?**

"Evidence" here means captured conversation messages, tool results and operator assertions: the source material that claims anchor to (`model.Evidence`). It is not the journal's own entries.

## 2. Evidence

Paths are relative to `investigation/`. Code paths are relative to `memory-prototype/memory_core/`.

### 2.1 Current acknowledgement semantics

| Source | Location | What it says |
|---|---|---|
| Durable journal contract v1.1, Part 1 | `durable-journal-rebuild-contract-v1.md:72` (item 8) | "Evidence and its status: **Durable fact** (evidence store)". It does **not** say when evidence becomes durable relative to acknowledgement |
| Same, Part 3 | `durable-journal-rebuild-contract-v1.md:305` (S3) | "Durable before acknowledgement" applies to **journal** facts through the storage boundary. Evidence is not written through that boundary |
| Decision closure v1 | `target-architecture-decision-closure-v1.md:110` | "Durable before acknowledgement" is listed as a semantic requirement of the **C-5 journal**, not of the evidence store |
| Lane A ingest | `runtime/__init__.py:222-245` (`write_message`), `:285` (`ingest`) | The ingest returns the evidence object. The prototype has no durability concept and no acknowledgement contract |
| Gateway v0.1 | `gateway/__init__.py:50-54` | `EVIDENCE_STORE_GUARANTEES`: `durability`, `ordering`, `closure`, `transactions` and `consistency` are all `"CONTRACT_GAP"` |
| Plan candidate | `next-architecture-work-decision-v2.md:120` | Lists "(E-5) durable before the ingest acknowledgement" as a **candidate** only. It was not derived from source |

### 2.2 Restore behaviour

| Source | Location | What it says |
|---|---|---|
| Restore protocol (Lane A, A8) | `memory-restore-protocol-v1.md:18` | Firestore (FS) holds the "Messages (sealed evidence)". It is restorable from PITR/backup |
| Same | `:30` | "What evidence exists? **FS**" |
| Same, scenario 1 | `:56` | "Firestore only: Later evidence lost (RPO). Claims supported only by it are invalidated `lost_in_restore`. **No invariant violation**". Test: `test_1_fs_only_restore…` |
| Test | `memory-prototype/tests/test_restore.py:46, :53` | `test_1_fs_only_restore_loses_later_evidence_and_bounds_claims` asserts `lost_in_restore == 1` with no invariant breach |
| Same protocol | Document header (`:7-10`) | The protocol is executed by a 2,000-seed randomised property |

### 2.3 `lost_in_restore`

| Source | Location | What it says |
|---|---|---|
| Restore protocol, step 7 | `memory-restore-protocol-v1.md:48` | "Support edges to evidence that no longer exists are dropped. Claims left with no support become `invalidated(lost_in_restore)`. Their content was lost with the evidence store's RPO window" |
| Same, §6 | `:97` | "Evidence lost by an FS restore: **Unrecoverable by design.** The RPO of the evidence store is the RPO of memory" |
| Code | `runtime/restore.py:198-206` | It drops support to missing evidence, and moves an ACTIVE claim with no remaining support to INVALIDATED, with cause `lost_in_restore` |
| Red team (earlier) | `memory-architecture-v2-red-team.md:1001` | "PG has a row, Firestore has no message: Mark `lost_in_restore`; **claims stay**, and explain shows it as unavailable" |

**Recorded without reinterpretation:** the earlier red-team text (claims stay) and the later A8 protocol, which "Builds on: red-team C-8 and §L" (`memory-restore-protocol-v1.md:12`), differ. A8 invalidates claims that are left with **no** support. Both sources agree that acknowledged evidence can be lost within the RPO window. Option B below uses the A8 wording, because the question names it.

### 2.4 RPO ownership

| Source | Location | Owner |
|---|---|---|
| Restore protocol §6 | `memory-restore-protocol-v1.md:96` | "RPO/RTO per tenant: `[BLOCKED:Product/Ops]`" |
| Red team, HA/DR | `memory-architecture-v2-red-team.md:478` | "RPO/RTO targets are `[BLOCKED:Product/Ops]`" |
| Red team, owner table | `memory-architecture-v2-red-team.md:935` | "RPO/RTO per tenant: Product + Ops", with no default |
| Roadmap | `memory-implementation-roadmap-v1.md:280, :394` | C1 depends on "RPO/RTO decisions (E)"; RPO/RTO has no default and affects "C1 sizing" |

**No source chooses between the options below.** The search covered every `investigation/` and `artifacts/` document that mentions RPO, `lost_in_restore` or durable-before-ack, and the docket answers were checked. No organisational record authorises either option.

## 3. Option A: durable-before-ack

- **Meaning:** an ingest acknowledgement means the evidence is durably recoverable.
- **Restore:** acknowledged evidence cannot be lost on restore.
- **Contract:** this becomes a **normative E-5 requirement** of the Evidence Store Boundary contract. It is the evidence-side analogue of the journal's S3.
- **Feasibility and cost:** production feasibility and cost move into **C-5** (Infrastructure).
- **Not current architecture:** this is **not** the current Lane A semantic (§2.2 and §2.3 document the opposite). Choosing it **supersedes** the A8 row "Evidence lost by an FS restore: unrecoverable by design" for the target, and that requires an explicit decision record.

## 4. Option B: RPO-window semantics (Lane A, as documented)

- **Meaning:** an ingest acknowledgement does **not** imply zero-RPO durability.
- **Restore:** evidence may be lost within the **declared RPO**.
- **Claims:** claims left with no supporting evidence become `invalidated(lost_in_restore)` (A8 step 7).
- **RPO value:** RPO stays an **owner-controlled production parameter** (Product/Ops; currently unset).
- **Not a stated preference:** no source states this is the preferred product decision. It is the **documented and tested Lane A behaviour** only.

## 5. Consequences

Comparison only. No numerical RPO/RTO is given, since none has been decided.

| Dimension | Option A: durable-before-ack | Option B: RPO window |
|---|---|---|
| **User-visible reliability** | Anything the system acknowledged survives any restore. Memory derived from it is not silently withdrawn by recovery | After a restore, memory derived from evidence acknowledged inside the RPO window can disappear. The extent depends on the chosen RPO |
| **Restore semantics** | The A8 "lost evidence" step (7) should never fire for acknowledged evidence. If it does, that is a contract violation, not an expected outcome | A8 step 7 is a normal, expected recovery outcome ("no invariant violation", scenario 1) |
| **Claim validity** | Claims never lose support because of a restore | Claims whose only support was lost become `invalidated(lost_in_restore)`. Claims with other surviving support keep it |
| **Operational complexity** | [INFERENCE] Ingest latency includes the durability guarantee. Restore drills must prove zero loss of acknowledged evidence | Ops must set and monitor an RPO. Restores need the `lost_in_restore` reporting and explanation path (already in the prototype) |
| **Storage requirements** | The evidence store needs a crash- and restore-surviving acknowledgement (S3-like), including across PITR/backup restore | The store needs PITR/backup within the declared RPO. [INFERENCE] Acknowledgement may precede durable replication |
| **C-5 implications** | C-5 must evaluate the evidence store against this guarantee as well. The issued v2.0 request (SHA-256 `9206…38bd`) covers journal S3 (E3), not evidence. Any extension is a new owner act, and C-5 stays delivery-blocked | C-5 must size the RPO once Product/Ops sets it (roadmap `:394`, "C1 sizing"). No new guarantee class is added |
| **Migration / legacy** | The Lane A A8 row is superseded for the target. The Lane A prototype and its restore tests stay as [LEGACY]. Changing them needs separate authorisation | Consistent with Lane A A8 as written. No supersession is needed |
| **Compliance / product expectations** | No source states a compliance or product requirement either way [INFERENCE: none found]. Any such requirement is the owner's input | Same. The RPO value itself is the owner's input, and it may interact with Legal's backup-retention item (`memory-architecture-v2-red-team.md:934`, "Backup retention ≤ erasure deadline", Legal + Ops) |

**[LEGACY] note:** the A8 row "Commit records lost by an FS restore" (`memory-restore-protocol-v1.md:98`) concerns the Lane A evidence-held ledger. Under `commit-ledger-authority-decision-v1.md`, commit records are journal facts, so that row is not part of this decision.

## 6. Recommendation status

**[OWNER DECISION REQUIRED].**

Neither option is authorised by existing organisational evidence (§2.4). This packet does not choose one, and it sets no engineering default to unblock the work.

## 7. Impact on the Evidence Store Boundary

| Item | State |
|---|---|
| E-1 identity/idempotency, E-2 sealing, E-3 receipt ordering, E-4 lifecycle (partial) | Findings recorded in `evidence-store-boundary-v1-implementation-report.md` §3. **Reusable** after the decision. Their own open [CONTRACT_GAP] rows (`receipt_seq` restore durability and scope) carry forward |
| E-7 commit relationship | **Resolved:** the Durable Journal is authoritative for commit records and outcomes (`commit-ledger-authority-decision-v1.md`) |
| **E-5 acknowledgement** | **Blocked** on this decision |
| E-6 fence reads, E-8 erasure | **Not started** |
| Phase 3 (contract), Phase 4 (boundary implementation), Gateway wiring, conformance tests | **Blocked by E-5** |

**After the decision:** resume exactly at E-5. Then do E-6, E-8, the contract, the boundary implementation and the conformance tests.

## 8. Correction to the earlier record

`next-architecture-work-decision-v2.md:66` (D1) states that the evidence-store guarantees are "an engineering contract, not an owner question", that their semantics are "already fixed by Lane A and the red team", and that "only technology and durability *values* belong to C-5".

**That overclaimed for E-5.** Whether an acknowledgement implies durable recoverability is a **semantic** choice that source leaves with Product/Ops. It is not merely a C-5 value.

The correction was first recorded in `evidence-store-boundary-v1-implementation-report.md:112`. D1 itself is left unchanged as the historical record. Its other conclusions (E-1 to E-4 semantics drawn from Lane A, and C-5 owning the technology) are not affected by this packet.

---

**EVIDENCE BOUNDARY V1 — BLOCKED ON E-5 OWNER DECISION.**
