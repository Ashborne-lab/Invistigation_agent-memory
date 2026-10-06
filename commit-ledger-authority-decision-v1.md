# Commit Ledger Authority Decision v1

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. Decision and reconciliation only. **No code, test, schema or contract changed. Lane A is untouched. Nothing is retired or migrated.**

**Labels:** [PROVEN], [DECISION], [OWNER], [CONTRACT_GAP], [LEGACY], [MIGRATION], [INFERENCE].

**FINAL GATE: JOURNAL AUTHORITY — EVIDENCE BOUNDARY MAY RESUME.**

---

## 1. Problem statement

The Evidence Store Boundary workstream stopped at Phase 1 because two homes for the commit ledger exist:
- **Lane A:** commit records kept with the evidence in FS, replayed into a PG projection by the restore protocol.
- **Durable Journal v1.1:** commit records and outcomes as journal facts.

The question: is one of them authoritative for the **target** architecture, and what does that make the other?

## 2. Evidence from Lane A [PROVEN by source trace]

| # | Question | Finding | Source |
|---|---|---|---|
| 1 | Who writes the evidence-held records? | **Only** Lane A `runtime.Memory`'s extraction-job commit. **One record per job**, appended to every evidence item of the job | `runtime/__init__.py:483-490` |
| 2 | Who reads them? | **Only** the Lane A restore protocol. It iterates `ev.commit_records` above `floor = max(snapshot seq, replay_watermark)` and applies them through `replay_record` | `runtime/restore.py:132-148` |
| 3 | What depends on them? | Lane A recovery when **PG regressed**: the PG projection (claims, support, transitions…) is rolled forward from them in journal order, interleaved with WORM | `memory-restore-protocol-v1.md` §1, restore steps; `test_restore` |
| 4 | Authoritative, or a restore mechanism? | **Authoritative within the Lane A topology:** PG is "a rebuildable projection", and the FS commit record answers "what did a commit decide?". Their authority **derives from that topology** (FS durable, PG regressable), not from any semantic need to co-locate them with evidence | Protocol §1 store table |
| 5 | Can the target journal reconstruct the same outcome? | **Yes, for commit decisions.** A journal `CommitRecord` carries the proposal, fingerprint, attested gate decision, status, claim id and content, the fence result (initial status, attributed, merge ids), the reason, state conflict and `committed_at`. Rebuild applies recorded outcomes only and never re-decides | `commit/__init__.py:107-121`; durable contract v1.1 §E; `rebuild_uses_durable_facts_only…` |
| 6 | Information in `ev.commit_records` absent from the journal? | **Yes, but none of it is commit authority.** It is **extraction-job bookkeeping**: per-evidence `extraction_state` (done, fenced, pending), `context_ids`, `q17` (recovery-of), the `reextract` flag, the `superseded` list, and the extractor `version` at job level. The target core has **no extraction-job model** (none of these terms appears in the gate, commit, journal or Gateway) | `runtime/__init__.py:483-487`; grep of the target modules |
| 7 | Does the restore protocol need them for correctness, or only because it predates the journal? | **Because of its topology.** With PG as a regressable projection and no durable journal, they are the only durable record of decisions. In the target model the journal is that durable record (contract v1.1 Part 1 item 7; §D, §E) | As above |
| 8 | What breaks if they stop being authoritative? | **In the target architecture: nothing** (no target module reads them). **In Lane A: its restore protocol**, if that topology were deployed. The prototype's Lane A model and its `test_restore` remain as they are | Grep: readers in §2 row 2 only |
| 9 | Production or legacy? | **Prototype/design only.** No production repository contains `commit_records`, `replay_record` or `replay_watermark`. In the store registry they are a **planned** v2 field (`tools/registry_build.py:44`: `agent_messages.{…, commit_records}` "Firestore") | Grep of `repos/` (none found); registry tool |

## 3. Evidence from the target journal architecture [PROVEN]

- **Ledger:** contract v1.1 Part 1 lists the "commit outcome / intent (ledger)" as a **durable fact**, and §C puts proposal idempotency in the proposal subject's partition.
- **Rebuild:** §E: rebuild consumes **only** journal partitions, the policy log, policy content, the vault and the served r. It never re-decides, and it equals the live projection [PROVEN].
- **Gateway v0.1:**
  - claims seal their full `CommitRecord` in the journal;
  - non-claim terminal outcomes are `commit_outcome` entries;
  - idempotency is decided only from durable journal outcomes (GW-3 fix);
  - CONFORMANT.
- **The target modules never touch `ev.commit_records`,** and the Lane A runtime never writes the journal. There is **no shared write path** between the two models.
- **Storage evaluation v1/v2 already treat A7** (PG as a projection behind FS commit records) as **"not a journal"** and not evidence for journal rows.

## 4. Mapping: legacy model versus target model

| Concept | Legacy Lane A | Target architecture | Authority (target) |
|---|---|---|---|
| Proposal | In the job record, in `ev.commit_records` (FS) | `CommitRecord.proposal` in the journal claim entry; the fingerprint in `commit_outcome` | **Journal** |
| Gate decision | `rec.decisions` (FS) | `CommitRecord.decision` (an attested GateOutcome) | **Journal** |
| Fence / identity outcome | `rec.applied` (action, target, merges, attributed) | `CommitRecord.initial_status`, `attributed`, `merge_ids`; the claim's target subject | **Journal** |
| Commit outcome | Implied by the applied entries; PG rows | `CommitRecord.status`; `commit_outcome` entries (all terminal outcomes) | **Journal** |
| Claim record | PG `claims` (a projection rebuilt from FS records) | Journal `claim` entry (sealed, immutable) | **Journal** |
| Replay | `replay_record` over FS records plus WORM, in journal order | `reconstruct(durable_facts)`, a pure function of journal facts | **Journal** |
| Watermark | `replay_watermark` (PG, LA-10: resumable roll-forward) | Not needed: rebuild is a pure function of the facts; idempotency comes from `idem` / K8 | — |
| Evidence anchor | `rec.evidence_ids`; PG `claim_support` | `ClaimContent.anchor` (evidence ids, quotes) in the sealed record; evidence in the evidence store | Journal holds the reference; **the evidence store holds the evidence** |
| Extraction-job bookkeeping (`extraction_state`, context, Q17, re-extract, superseded) | In the job record (FS), plus `Evidence.extraction_state` | **Not modelled** | [CONTRACT_GAP] (§7) |

**Disagreements:**
- (i) the ledger's **location** (FS evidence or journal);
- (ii) the **granularity** (one record per job, or per proposal);
- (iii) the **recovery model** (roll-forward with a watermark, or a pure rebuild);
- (iv) the **job bookkeeping**, which exists only in Lane A.

**None of them is a semantic disagreement about what was decided.** LA-1's rule, "apply recorded outcomes, never re-decide", holds in both models.

## 5. Three-option comparison

| Criterion | (a) Journal authoritative | (b) Evidence-held ledger authoritative | (c) Both authoritative |
|---|---|---|---|
| Fit with what is proven | **Native.** v1.1 Part 1 item 7, §E rebuild, Gateway v0.1 (all PROVEN) | **Reopens v1.1:** Part 1 (ledger), §E (rebuild could no longer use journal facts alone), and K8/Gateway idempotency (decided from journal outcomes) | Two durable records of the same decision |
| Replay semantics | Unchanged (pure rebuild) | Changed: replay from evidence-held records, with the journal reduced to a projection | **Divergent replay is possible:** two sources could disagree, with no rule for which wins |
| Commit ownership | The subject's partition (§C) | Evidence items, one record per job across all of the job's evidence | Duplicated |
| Cross-store atomicity | **None** | A commit must reach evidence (authority) **and** the journal (projection), which needs ordering or an outbox | **Required**, or else non-deterministic recovery |
| Gateway guarantees | Unchanged | Changed: idempotency, terminal-outcome stability and GW-3 would rest on the evidence store | Ambiguous |
| K1–K10 | Untouched | K8/K9 placement and the journal's role would need reconciliation | Ambiguous |
| Durable fact model | Unchanged | Changed | Changed, and contradictory |
| Production impact | **None:** the evidence-held ledger was never implemented in production (§2 row 9) | — | — |

**Verdict:**
- (b) would **reopen proven contracts** (v1.1 Part 1 and §E, Gateway K8/GW-3) to serve a topology that is not deployed.
- (c) **cannot be made deterministic** without cross-store atomicity or a tie-break rule.
- **(a) is semantically safe:** LA-1's semantic is preserved, nothing in production relies on the alternative, and the two models share no write path.

## 6. Exact authority decision

**[DECISION]** **The Durable Journal is the sole authoritative commit ledger for the target memory architecture.**
- Commit decisions and terminal outcomes are journal facts:
  - claim entries seal the full `CommitRecord`;
  - non-claim terminal outcomes are `commit_outcome` entries.
- The **evidence store holds evidence and its lifecycle**, plus nothing that decides a commit.
- Claims refer to evidence through the anchors in their sealed record.

**Basis:**
- [PROVEN] v1.1 Part 1 item 7, §C, §E;
- [PROVEN] Gateway v0.1;
- [PROVEN] no production implementation of the alternative;
- [PROVEN] no shared write path;
- [PROVEN] the LA-1 semantic is preserved.

## 7. Legacy compatibility status

| Item | Status |
|---|---|
| Lane A `Evidence.commit_records`, `runtime.Memory` job records, `replay_record`, the LA-10 `replay_watermark`, `runtime/restore.py`, `memory-restore-protocol-v1.md` | **[LEGACY].** An earlier target-design topology (v2 / A7: FS plus a PG projection), implemented **only in the prototype**. **Not an independent authority in the target architecture.** **Retained unchanged**, with its tests green: it is not deleted, disabled or modified |
| **LA-1** | Its **semantic** (recorded outcomes are replayed, never re-decided) is **carried into the target** by the journal. Its **location** ("kept with evidence") is legacy |
| **LA-10** | Its **semantic** (recovery is resumable and safe under non-commuting identity operations) is met in the target by the pure rebuild plus `idem` (no roll-forward). The watermark is legacy. **Identity-operation interleaving with the journal** (merge, undo) remains to be covered when identity events enter the target scope [INFERENCE: no contradiction found, but not exercised] |
| Extraction-job bookkeeping (`extraction_state`, Q17 recovery, re-extraction lineage, superseded lists) | **[CONTRACT_GAP]: no target home yet.** It is **pipeline** state, not commit authority. `extraction_state` is an **evidence attribute** (`Evidence.extraction_state`), so it is in scope for the evidence boundary as evidence metadata. Job-level re-extraction and Q17 lineage need a home when the extraction pipeline is modelled on the target core. **Non-blocking** for the evidence boundary |
| Interaction of the WORM identity and erasure ledger with recovery | Out of scope here. Unchanged Lane A semantics; it belongs with identity and erasure work |

## 8. Migration requirements

| Item | Requirement |
|---|---|
| **Production** | **None:** the evidence-held ledger and its restore protocol were never implemented in production code (`repos/` grep: none) [PROVEN] |
| **Prototype** | **None now.** The Lane A model stays as a legacy reference. **[MIGRATION]** Retiring it from the prototype (removing `commit_records`, `replay_record`, `restore.py` and their tests) is an **optional clean-up** that needs explicit authorisation, because existing tests would change. It is not required for anything in the target architecture |
| **Design documents** | `memory-restore-protocol-v1.md` and the A7 design describe the legacy topology. When the target recovery runbook is written, they should be **marked superseded for the target** (a documentation change, later; not done here) |

**Who authorises retirement:** the architecture/contract owner, together with authorisation to revise named tests. **It is not on any critical path.**

## 9. Is cross-store atomicity required?

**No** [PROVEN for the target].
- The journal alone decides; the evidence store never holds commit authority.
- The only relation is **ordering**: a proposal can be admitted only against evidence the gate can read. That is evidence-boundary E-5/E-6 material, not atomicity.

## 10. Effect on the Evidence Store Boundary v1

- The workstream **may resume at Phase 2**.
- **E-7 is fixed as:** *the journal holds the authoritative commit records; the evidence store holds evidence and the references/anchors needed to associate it with those records* (claims carry evidence ids in their sealed anchor).
- `Evidence.extraction_state` is evaluated in Phase 2 as an evidence attribute. Job-level extraction bookkeeping stays out of scope (§7, CONTRACT_GAP).
- Lane A's `commit_records` field is **not** part of the target evidence contract. It remains in the Lane A model, unchanged.

## 11. Owner dependencies

| Item | Owner | Blocks |
|---|---|---|
| Retiring the legacy Lane A recovery model from the prototype (optional) | Architecture/contract owner + test-revision authorisation | Nothing on the critical path |
| A target recovery runbook marking the restore protocol and A7 superseded | Architecture owner (later) | Nothing now |
| Extraction-job ledger (re-extraction lineage, Q17) in the target core | Engineering, when the extraction pipeline is modelled [CONTRACT_GAP] | Not the evidence boundary |
| Unchanged | C-5 (parked), C-1, Legal erasure items, etc. | As before |

## 12. Final gate

**JOURNAL AUTHORITY — EVIDENCE BOUNDARY MAY RESUME.**

The evidence store boundary resumes from **Phase 2**, with E-7 = *the journal holds the authoritative commit records; evidence holds the evidence and the references/anchors needed to associate it with those records*.
