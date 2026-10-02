# Restore and Disaster-Recovery Protocol v1 (Lane A, A8)

**Date:** 2026-10-01.

**Classification:** TARGET ARCHITECTURE. The protocol is executable in the prototype (`memory_core/runtime/restore.py`) and tested by `tests/test_restore.py`.

**Evidence:**
- 8 named scenarios;
- the LA-1 regression;
- a randomised property over **2,000 seeds**, with random operation sequences, a random snapshot point and a random restore target (FS, PG or both): all pass.

**Builds on:** red-team C-8 and §L; A7 (`memory-postgres-design-v1.md`).

## 1. Stores and authority

| Store | Holds | Restorable? | Authoritative for |
|---|---|---|---|
| **FS** (Firestore) | Messages (sealed evidence); identity bindings; `identity_events`; inbound dedup; consent/suppression; **commit records** (proposals plus recorded decisions, LA-1) | Yes (PITR/backup) | Evidence content; identifier → subject resolution |
| **PG** (Cloud SQL) | Claims, support, transitions, retraction records, slots, commitments, episodes, knowledge, manifests, outbox, events, erasure ledger copy, `identity_events_applied`, `replay_watermark` | Yes (PITR/backup) | Nothing that FS + WORM cannot re-derive. PG is a **rebuildable projection** with recorded outcomes |
| **WORM** (GCS, retention-locked) | Erasure records (with epoch high-water marks), identity events, withdrawals, forget-facts, transfers, all PII-free (keyed `worm_ref`) | **Never** | That an erasure or identity event happened, in journal order |

**Authority per recovery decision:**

| Decision | Authoritative source |
|---|---|
| Is this subject erased? | **WORM** (the restored stores may say otherwise) |
| Epoch value | max(store, WORM high-water) |
| Did this merge/undo happen? | WORM; the PG `identity_events_applied` projection covers WORM mirror lag **only if PG did not also regress** (see LA-5) |
| What did a commit decide? | The FS commit record. Gate and identity outcomes are **applied, not re-decided** (LA-1) |
| What evidence exists? | FS |
| Is evidence content intact? | The seal (keyed hash), re-verified at recovery (LA-7) |
| Where the roll-forward stands | `replay_watermark` (PG, same transaction as each applied entry; LA-10) |

## 2. The protocol (any restore)

1. **Freeze.** Pause the extraction workers, sweepers and outbox dispatchers. Turns continue; memory reads render as "unavailable".
2. **Restore** the affected store(s) to the chosen point. Store-assigned id counters are not rewound: Firestore ids are random, so no reissue.
3. **Interleaved roll-forward from the floor**, where floor = max(snapshot seq, `replay_watermark`). Take, in journal order:
   - WORM entries above the floor: re-apply to whichever store regressed. The PG side is always applied, idempotently;
   - if PG regressed: the FS commit records above the floor, applied via `replay_record` with recorded outcomes;
   - advance `replay_watermark` with each entry.
4. **Identity reconciliation** (FS regressed): re-apply merges and undos found in the PG `identity_events_applied` projection but missing from FS.
5. **Epoch high-water.** Raise every erased subject's epoch to its WORM value.
6. **Seal re-verification** over evidence referenced by active claims:
   - re-seal evidence rolled back to "unsealed" (same content, same hash);
   - quarantine anything whose content no longer matches its seal;
   - drop support whose quote is no longer in the restored text (LA-7).
7. **Lost evidence.** Support edges to evidence that no longer exists are dropped. Claims left with no support become `invalidated(lost_in_restore)`. Their content was lost with the evidence store's RPO window.
8. **Rebuild projections:** slots, search index, commitment heads. Run the invariant checker and the completeness auditor for recent erasures.
9. **Resume.**

## 3. Scenarios (each executed in the prototype)

| # | Scenario | Result | Test |
|---|---|---|---|
| 1 | Firestore only | Later evidence lost (RPO). Claims supported only by it are invalidated `lost_in_restore`. No invariant violation | `test_1_fs_only_restore…` |
| 2 | PostgreSQL only | Exact roll-forward: active memory after recovery == live active memory | `test_2_pg_only_restore…`; property (f) |
| 3 | Both stores | WORM re-applies the erasures and identity events after the point. A restore that "resurrected" bob is corrected | `test_3_both_restored…` |
| 4 | Point before erasure (each store) | Erased subject stays erased. Epoch ≥ high-water. A new message from the same identifier binds a **new** subject | `test_4_…[fs/pg/both]` |
| 5 | Point before merge (each store) | The merge is reinstated with its original merge id | `test_5_…[fs/pg/both]` |
| 6a | FS restore with the WORM mirror lagging | The merge is recovered from the PG projection | `test_6a_…` |
| 6b | **Both** restored with the WORM mirror lagging | **The merge is silently lost** (LA-5). Undetectable | `test_6b_…` (asserts the defect) |
| 7 | Outbox lag (PG had not applied an identity event) | Applied on recovery from WORM | `test_7_…` |
| 8 | Search index missing | Rebuilt identical to before | `test_8_…` |

## 4. Properties proven (prototype, randomised)

These are **evidenced by the prototype**, not proven formally. Each property is checked after recovery.

| Property | Check | Result |
|---|---|---|
| Erasure epochs are monotonic | Every erased subject's epoch ≥ its WORM high-water mark | 2,000/2,000 |
| Deleted subjects do not reappear | Erased subject: not active, no active claims; `build_context` → None | 2,000/2,000 |
| Identity merges are not silently undone | Every WORM merge without a WORM undo is in force | 2,000/2,000 (with a synchronous WORM append; see LA-5) |
| Projections are rebuildable | `invariants()` == [] (head == rebuild; support live and sealed) | 2,000/2,000 |
| Erased data is not reintroduced | Same as "deleted subjects do not reappear", plus the LA-8 bound on forget commands | 2,000/2,000 |
| Outbox/event replay is idempotent | Recovery run twice: the second run is a no-op through the watermark | 2,000/2,000 |
| PG-only roll-forward is exact | Active memory == live | All PG-only seeds |

## 5. Lane A findings that shaped the protocol

| # | Finding | Consequence |
|---|---|---|
| **LA-1** | Replaying commits by *re-running the gate and fence* against today's evidence and identity state misattributes claims: an evidence item erased later rejects at replay; a merge-then-undo attributes differently | Commit records carry the **recorded outcomes**, and replay applies them. Later journal entries then re-apply in order |
| **LA-5** | With an asynchronous WORM append, a restore of **both** stores loses identity events inside the mirror-lag window, silently | **Identity events must be appended to WORM synchronously** (part of the binding-first transaction: write the WORM object, then commit the binding), or both stores must never be restored to a point inside the lag window. Recommended: the synchronous append |
| **LA-7** | A PG restore loses tamper quarantines; an FS restore rolls seals back to "unsealed" | Seal re-verification is a recovery step |
| **LA-8** | Replaying an old forget-fact or re-extraction over later state over-erases (it hits a fact the person re-stated) | Every replayable command is **bounded by its own knowledge time** (forget: claims observed ≤ its time; re-extraction: claims committed ≤ its time) |
| **LA-10** | Identity operations do not commute with records (undo drops merge-epoch retraction records). Replaying "the same entries again" over a recovered state is unsafe even when each operation is idempotent | A **transactional replay watermark**. Idempotency comes from the watermark, not from commutativity |

## 6. What this does not cover

| Item | Status |
|---|---|
| Real Firestore PITR semantics (point granularity, consistency of collection-group reads during restore) | `[UNRESOLVED]` until a staging drill (roadmap C7) |
| Cloud SQL PITR plus WAL retention values | `[BLOCKED:Legal]` (the window) |
| RPO/RTO per tenant | `[BLOCKED:Product/Ops]` |
| Evidence lost by an FS restore | Unrecoverable by design. The RPO of the evidence store is the RPO of memory |
| Commit records lost by an FS restore | Claims re-extracted by the model. The model is nondeterministic, so re-extraction may differ; it is labelled `recovered_by_reextraction` when implemented |
