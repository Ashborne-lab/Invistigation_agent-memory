# Memory Lane A Status v1

**Date:** 2026-10-01.

**Scope:** roadmap Lane A (A1–A9), executed in `investigation/` and `investigation/memory-prototype/` only. Synthetic data only.

**What was not touched:**
- no production repository edited;
- no deploy;
- the contract, the identity documents, `memory-architecture-v2.md` and the State Semantics Explorer were not modified.

**Machine-readable summary:** [`memory-lane-a-status-v1.json`](memory-lane-a-status-v1.json).

## Status by work package

| WP | Status | Evidence |
|---|---|---|
| **A1** pure-core hardening | **Done** | 13 red-team resolutions and 20 Lane A findings implemented behind named flags (`DEFAULT` = defect, `AMENDED` = reviewed). **388 tests** at default seeds. Stress: invariant suite **1,000 seeds × 150 steps**, restore suite **2,000 seeds**, original property suite **400 seeds** (final run: §Stress). All 12 required invariants checked after every operation; a control test shows the generator finds violations under `DEFAULT` |
| **A2** real-model harness | **Done** | `olb.memory.extract/1`; provider-independent adapters (Claude CLI, Anthropic API, cache/replay); a machine-readable record per call; reproducible command; offline re-scoring |
| **A3** L1-real baseline | **Done (baseline, no thresholds)** | 496 model responses, USD 14.08, plus a 12-scenario held-out set run after prompt v2 was frozen. Legacy vs new extractor on Haiku 4.5 (the production model); prompt v1 vs v2; Sonnet 5; the same responses under the `DEFAULT` core. [`memory-real-model-baseline-v1.md`](memory-real-model-baseline-v1.md) |
| **A4** lifecycle registry | **Done as a design. Not complete in substance** | 92 entries, 21 fields each; the generator plus `--check` reports every expected store covered. **7 entries `blocked_missing_repo`** [`memory-lifecycle-registry-v1.md`](memory-lifecycle-registry-v1.md) |
| **A5** legacy erasure census | **Done for the 13 workspace repositories** | 35 stores traced at `origin/main`, with handler design, resurrection writers and the required ordering. 6 contradictions with earlier documents recorded [`memory-legacy-erasure-census-v1.md`](memory-legacy-erasure-census-v1.md) |
| **A6** predicate ownership | **Done** | 20 attribute rows; 8 attributes with competing owners resolved or split; 3 explicit boundaries (name, open business fields, language) [`memory-predicate-ownership-v1.md`](memory-predicate-ownership-v1.md) |
| **A7** PostgreSQL design | **Done (design). Untested on real PG** | Hybrid by tier (shared + hash(org) partitioning + RLS; a dedicated instance only for dedicated physical tenants). Per-table keys, partitions, indexes, RLS and `SET LOCAL`, lock order, backups [`memory-postgres-design-v1.md`](memory-postgres-design-v1.md) |
| **A8** restore/DR | **Done in the model** | The protocol is executable; scenarios 1–8 plus randomised restore (2,000 seeds) pass. LA-1/5/7/8/10 came from it [`memory-restore-protocol-v1.md`](memory-restore-protocol-v1.md) |
| **A9** adversarial suites | **Done, with the infrastructure-dependent parts modelled or probed** | 48 catalogue tests across all six categories, plus the Lumen bypass on SQLite against a faithful copy of the production check, plus a **Firestore rules probe in the local emulator against the current production rules** (§Security probe) |

## Findings discovered in Lane A (LA-*)

Each finding was reproduced by a failing test or a measured run, then fixed behind a flag, with a regression in `tests/test_redteam_findings.py` (or `test_restore.py`).

| # | Found by | Finding | Fix | Changes which earlier decision |
|---|---|---|---|---|
| LA-1 | Restore property | Replaying commits by re-deciding gate and identity against today's state misattributes claims | Commit records (proposals plus **recorded outcomes**) kept with the evidence in FS; replay applies them | RT M-12 (proposals table in PG) → the commit record lives in FS; PG becomes a rebuildable projection |
| LA-2 | Example test | The future-marker rule on the quote alone is bypassed by minimal quotes | Check the clause containing the quote | RT R-15 wording |
| LA-3 | Property seed 144 | "Merge ids in force" go stale after a partial undo of a chained merge, quarantining an independent subject's claims | Merges on the subject's **current path** to its root | E3 merge recording (definition) |
| LA-4 | Property seed 279 | Retry is not idempotent when a batch re-proposes a fact whose own derivation exists | Own-derivation check before dedup | Spec §6.1 step 10 |
| LA-5 | Restore scenario 6b | With an asynchronous WORM append, a both-store restore silently loses merges | **Synchronous WORM append for identity events** | RT C-8 (WORM "mirror") |
| LA-6 | Restore seed 36 | Undo moved an erased claim back to quarantined | Erasure dominates every lifecycle transition | — |
| LA-7 | Restore seeds 212, 418 | PG restore loses tamper quarantines; FS restore rolls seals back | Seal re-verification as a recovery step | RT R-2 |
| LA-8 | Restore seed 219 | Replaying forget-fact or re-extraction over later state over-erases | Every replayable command is bounded by its own knowledge time | v2 §L forget-fact semantics |
| LA-9 | Restore seed 656 | A late-extracted claim escapes an earlier "never true" retraction | Retraction **records** applied to every matching claim observed before them, order-independently | Spec retraction semantics (gate needed an active target) |
| LA-10 | Restore seed 418 | Identity operations do not commute with records; replay twice is unsafe even with idempotent operations | Transactional replay watermark | RT §L |
| LA-11 | Commit-order property | **Support folding makes history depend on commit order** (final code, identical conditions: 35/40 random 5-step scripts for both a SET and a SINGLE key) | **One claim per evidence-anchored assertion**; dedup and freshness at read time | **Spec §6.1 step 10 and F-6.** The largest semantic change in Lane A |
| LA-12 | Catalogue | Merges with erased or already-merged subjects were accepted | Identity authority guards | — |
| LA-13 | Real model | Models anchor retractions to old context | Anchors must be in the pending turn | — |
| LA-14 | Real model | Gazetteer gaps drop cross-script facts | Downgrade to unverified (never current) | F-1 boundary |
| LA-15 | Real model | Models don't restate known facts, so provenance and freshness are lost | Protocol v2 asks for restatements | Protocol |
| LA-16 | Real model | Replacement retractions block never-true revival | Dropped at the gate | — |
| LA-17 | Real model | The time vocabulary can't express "until then" or dates | **Open:** extend the protocol time grammar | Protocol |
| LA-18 | Real model | Synonym values ("Gurgaon"/"Gurugram") | Canonicalise through the key's normaliser | — |
| LA-19 | Real model | 66–90% of current-state assertions omit `valid_time`; "unbounded start" rewrites history | **Null `valid_from` = observed time** | Spec §9.5 (was undecided) |
| LA-20 | Held-out real-model run | My LA-2 clause rule rejected the present half of "I work at TCS but I'm joining Infosys next month"; the same-message current/future pair was a false CONFLICT | Clause split at commas and conjunctions; within one message, the later asserted start supersedes | LA-2 |

**Also fixed:**
- F-9 is now implemented (it had only been reported);
- commit tolerates evidence deleted mid-job;
- the LA-4 × LA-11 interaction (seeds 315/647).

**Red-team decisions challenged by implementation:**
- R-15 (LA-2), R-2 (LA-7), M-12 (LA-1), C-8 (LA-5);
- spec §6.1 step 10 / F-6 (LA-11), §9.5 (LA-19).

**Contract check (done in Lane A).**

**LA-11 conflicts with the contract's lineage model in representation, not in observable behaviour.** The contract (`artifacts/architecture-contract.md`) shows one claim with several support edges:
- Example 14, `:1239-1249`;
- §6, `:781`;
- claim-level `evidence_count` and `independent_support_count`, §5 `:436-450`.

The contract does not state that re-assertions *must* fold. Its examples assume they do.

Under LA-11 the observable outcome of Example 14 is preserved: deleting E1 leaves the value active through E2's own claim.

**This needs contract clarification CL-5,** decided by the **contract owner**:
- "A claim is an evidence-anchored assertion. Support counts (`evidence_count`, `independent_support_count`, `source_diversity`) are computed at read time across same-value claims, grouped by source group."
- Alternative for the owner: keep folding, but make validity and retraction per support edge. That is a larger change that the prototype did not test.

**Gap:** the prototype does not yet compute `independent_support_count` at read time. §5 requires that a thousand restatements count as one source group, and nothing in the current resolver violates that, but the count itself is unimplemented.

**LA-19 is compatible with the contract.** `:385` *permits* a past `valid_from`; it does not mandate an unbounded default.


## Coverage: red-team finding → executable test

| Finding | Test(s) | Notes |
|---|---|---|
| C-1 stamping | `test_redteam_findings::test_C1_*`; `test_catalog::test_erase_late_extractor`; property INV2 | |
| C-1a identity authority | `test_restore::test_5_*`, `test_6a_*`, `test_7_*`; property suite (merge/undo interleavings) | |
| C-2 sealing | `test_C2_*`, `test_R24_*`; `test_catalog::test_sec_malicious_client_write_detected_by_seal`; property INV1 | |
| C-3 dedup | `test_C3_provider_redelivery`; `test_catalog::test_conc_duplicate_event_idempotent`; property INV8 | |
| C-4 handles | `test_C4_*`; `test_catalog::test_sec_*` (swapped subject/agent/account, stale, cross-tenant); property INV9 | |
| C-5 accounts | `test_C5_*` | |
| C-6 derived writers / Lumen | `test_C6_*`; `test_catalog::test_sec_lumen_*` (8) | Lumen modelled on SQLite |
| C-7 registry | `test_C7_*`; `tools/registry_build.py --check` | |
| C-8 backups/restore | `test_restore.py` (54) | |
| C-9 re-extraction | `test_C9_*` | |
| M-1 PostgreSQL ops | **Not modelable.** Design in A7; Lane C (C1/C2) | |
| M-2 commitments | `test_M2_*`; `test_catalog::test_commit_*` (7); property INV11 | |
| M-3 Agent Knowledge | `test_M3_*`; `test_catalog::test_poison_cross_agent_*` | |
| M-4 rendering | `test_M4_*`, `test_R22_*`; `test_catalog::test_poison_fake_system_*`, `test_poison_narrative_*`; property INV12 | |
| M-5 assurance | `test_M5_*`; `test_catalog::test_identity_*`, `test_sec_spoofed_identity_isolated` | ANI attestation needs the voice gateway |
| M-6 ordering | `test_M6_*` | |
| M-7 future markers | `test_M7_*` (+ LA-2); real-model `future_as_current` | |
| M-8 policy admission | `test_M8_*`; `test_catalog::test_conc_policy_update_during_commit` | |
| M-9 caches/index | `test_M9_*`; `test_catalog::test_erase_reindex_after_erase` | In-process caches: architectural rule only |
| M-10 migration | **Not modelable** (rollout, revision floor, dual-run). Roadmap C6 / VM-MIG | Gap |
| M-11 search | `test_M11_*` | |
| M-12 proposals | Superseded by LA-1: `test_LA1_*`, `test_restore::test_2_*` | |
| M-13 lock order | `test_M13_*` | Real PG locks: Lane C |
| M-14 legal | **Not modelable** (owner decisions) | |
| M-15 observability | **Partial:** manifest replay (`test_R22_*`), commit records (LA-1). `explain()` and the resolution trace are **not implemented** | Gap |
| M-16 event volume | **Not modelable** (scale). A7 partitioning | |

## Security probe (current production rules, local emulator)

`memory-prototype/security_probe/` ran `olbrain-studio@1f05ca11 firestore.rules` in the Firestore emulator (project `demo-olbrain-probe`). The actor was a signed-in user of **another** org.

**14 of 15 probes were allowed:**

| Collection or path | What the other-org user could do |
|---|---|
| `agent_messages` | Read, overwrite and create (evidence forgery: RT C-2) |
| `agent_sessions` | Read and rewrite (phone, summary) |
| `agents` | **Create an agent claiming the victim org, and take over the victim's agent** (K1). The top-level catch-all ORs over the ownership rule |
| `organizations/*/members` | Read |
| `agents/*/versions` | Write |
| `tickets`, `agent_users` | Read |
| **New** `memory_bindings`, `identity_events`, `inbound_dedup` | **Write**: the R-1 identity root would be client-forgeable on day one |

Only `agent_user_memory` was denied.

**Caveat:** this shows what the rules **file** permits. That this file is the deployed one is `[UNRESOLVED]`. **Flagged for the security owner; nothing changed.**

## Stress (final code)

Run on the final code (after LA-20), 2026-10-01:

| Suite | Seeds / size | Result |
|---|---|---|
| Invariant stress (`test_redteam_properties`) | 1,000 seeds x 150 steps | **1,001 passed**, 0 failed |
| Restore stress (`test_restore`) | 2,000 seeds | **2,014 passed**, 0 failed |
| Original property suite (`test_properties`) | 400 seeds | **802 passed**, 0 failed |
| Full suite | default seeds | **388 passed**, 0 failed |

## Blockers

| Kind | Items |
|---|---|
| **Security (must precede any memory write)** | All 14 probe exposures; Lumen row isolation (RT C-6); `require_permission` Firebase bypass; MCP `agent_id`; `email_verified`; share-link live keys; S0-5 explicit server-only rules for every new memory collection (the probe shows they are writable by default) |
| **Missing repositories** | noesis-os (S0-1 client queries; operator reads; `title`); voice-gateway (ANI, transcripts); olbrain-llm (production adapter, subprocessors); billing / cloud-functions / analytics-service (billing and analytics erasure); agent-directives (opt-out enforcement); webhook service (trigger payloads, `client_message_id`); PII token vault |
| **Owner / Legal** | R-M1…R-M4; backup and erasure windows; subprocessor DPAs; suppression HMAC; member (employee) erasure; transfer between controllers; voice ANI assurance; conversation-sourced account facts; RPO/RTO; k for Agent Knowledge |
| **Unvalidated without infrastructure** | RLS and `SET LOCAL` under real pooling; real Firestore transaction behaviour for the binding write; PG lock behaviour and plans; real restore drills; erasure on real legacy stores |

## Resolved decisions (engineering, with evidence)

| Decision | Basis |
|---|---|
| Per-evidence claims (LA-11) | Commit-order property, same test and seeds: 35/40 → 0/40 order-dependent histories (SET and SINGLE keys) |
| Retraction records (LA-9) | Restore seed 656 plus the order property |
| Recorded-outcome replay with a watermark (LA-1, LA-10) | 2,000 restore seeds, exact PG roll-forward |
| Synchronous WORM append for identity events (LA-5) | Scenario 6b |
| Path-based merge ids (LA-3) | Seed 144 |
| Null `valid_from` = observed time (LA-19) | Real-model omission rates 66–90% |
| Anchor-to-pending, replacement-retraction drop, value canonicalisation, normaliser fallback (LA-13/14/16/18) | Real-model runs |
| Hybrid PG by tier; an instance only per dedicated physical tenant (A7) | Option analysis against OLBrain tenancy |
| Prompt v2 as the current baseline prompt | In-sample (lane1): recall 12/18 → 18/18. **Held-out (12 scenarios written after v2): recall 6/8 → 8/8, provenance 0/2 → 2/2, zero failures, no safety regression.** Directional only (small n) |

## Newly discovered problems (beyond the red-team list)

1. **The tenancy root takeover is live in the rules file** (K1-takeover), worse than the red team stated: not only forgery but also takeover of existing agents.
2. **The new v2 Firestore collections would be client-writable by default** under the current catch-all. S0-5 is a hard precondition for R-1.
3. **Gemini receives raw end-user text** (session identity capture). This is a subprocessor path missing from the MAP (A5).
4. **Email channel instructions inject raw `from_email` with no PII-policy gate** (A6).
5. **Shopify `customers/redact` reports compliance while deleting nothing** (A5; flag to security and legal).
6. **The operator-identity backfill script copies member PII onto end-customer sessions** (A6).
7. **The `agent_users` upsert drops an operator's status and overwrites operator edits on every inbound message.** Deleting the row also drops the opt-out (A5/A6).
8. **The legacy extractor on the production model stores privilege claims, assistant-supplied facts, health data and phone numbers** (A3, measured).

## Recommended next steps

1. **Security owner:** fix the 14 probe exposures and the other S0 items. Re-run `security_probe` as the G-SEC evidence; every line must flip to denied. This blocks everything that writes memory.
2. **Get the missing repositories,** in this order: noesis-os (S0-1 depends on it), then agent-directives (opt-out), then the billing, analytics and voice repositories.
3. **Lane B in parallel with item 1,** for work that does not write memory:
   - B4 (Lumen views);
   - B5 (the derivation-fence library), built and tested against the prototype contract;
   - B3 handlers for the in-workspace stores, in the census order.
4. **Lane C provisioning (C1)** to validate A7's untested items (RLS, pooling, locks) with VM-AUTH I / VM-CON I.
5. **Protocol:** extend the time grammar (LA-17); add a diet/lexicon normaliser; grow the L1-real corpus before setting thresholds.
6. **Contract check for LA-11 (CL-5)** before Lane C.

## READY FOR LANE B?

**Answer: partially. Yes for the Lane B work that does not write memory. No for anything that writes, reads or migrates person memory in production.**

| Brief condition ("do not claim readiness if…") | State | Verdict |
|---|---|---|
| Unresolved semantic failures in the architecture | All semantic failures found (red-team C/M and LA-1…LA-19) are fixed in the model, except **LA-17** (time grammar, an expressiveness gap). **But LA-11, the largest change, diverges from the contract's lineage representation (CL-5, contract owner), and read-time `independent_support_count` is unimplemented** | **Not fully met: CL-5 open** |
| The model baseline exposes blocking extraction failures | New extractor: **zero blocking-metric failures** across 2 models × 2 prompts × reps. Remaining misses are recall (lexicon, time grammar) | **Met** (baseline small; no thresholds) |
| The registry is incomplete | 92 entries cover every identified store, but **7 are `blocked_missing_repo`** | **Not met** |
| A security prerequisite remains untestable | Firestore rules are now testable (emulator probe) and **fail**. RLS, pooling and real-store erasure remain untestable until infrastructure exists | **Not met** (testable but failing; others untestable) |
| Erasure cannot be demonstrated | Demonstrated in the model, including restore. **Not demonstrated on any real legacy store** | **Not met for production** |
| A proposed schema cannot preserve the invariants | The schema maps every invariant to a mechanism, and the model preserves them. RLS and lock behaviour are unvalidated on PG | **Plausible, unproven** |

**Therefore:**

| Scope | Ready? |
|---|---|
| B0 (security fixes) | Ready to start now. It needs no memory semantics. The probe gives it an executable acceptance test |
| B4 (Lumen) | Ready |
| B5 (fence library) | Ready (semantics fixed by A1) |
| B3 (legacy erasure) | Ready for the in-workspace stores; blocked for the 7 missing-repository stores |
| B1 (binding transaction and sealing) and B2 (handles) | Semantics ready. **Must not ship before S0-1/S0-2/S0-5**: the probe shows the new collections would be forgeable |
| Anything that writes or reads person memory in production (shadow included) | **Not ready** until G-SEC and G-ERASE pass |

## Operational notes

- **Model spend:** USD 14.08 on the user's Claude account (CLI-reported list cost), all synthetic data.
- **One session-limit interruption.** It was detected, purged and re-run (see the baseline report §2.4).
- **Downloads.** Downloaded into the session scratchpad, outside the repositories: npm packages for the rules probe (`@firebase/rules-unit-testing`, `firebase`) and the Firestore emulator binary.
- **A lingering local emulator process** may still hold port 8089 (local only).
