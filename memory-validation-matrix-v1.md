# Memory Validation Matrix v1

**Date:** 2026-09-30.

**Classification:** TARGET ARCHITECTURE: the permanent validation system.

**Inputs:**
- `memory-architecture-v2.md` (v2);
- `memory-architecture-v2-red-team.md` (RT);
- `memory-implementation-roadmap-v1.md`;
- the prototype suites, `memory-prototype/tests` (173 tests; the seed).

**Rules.**
- **Blocking invariants** have zero tolerance. A single failure blocks a release.
- **Quality metrics** have **no invented targets.** Each is measured first, and its threshold is set from the recorded baseline (L1-real, L2) by the owner of that metric. Until then each metric is `[UNMEASURED]`: tracked, and not gated.
- **Every incident becomes a scenario** before it is closed.
- **Every RT finding has at least one test.** The finding column in each table traces it.

**Test layers:**

| Code | Layer | Scope |
|---|---|---|
| **U** | unit | Pure-core functions |
| **P** | property | Seeded random operation sequences, with invariants checked after every operation |
| **I** | integration | Real Firestore emulator and real PG in staging |
| **A** | adversarial | Attack corpora and probes |
| **M** | model evaluation | Real extraction model over datasets |
| **T** | production telemetry | Counters, audits and scanners |

---

## 1. Blocking invariants (checked by P and I; monitored by T where observable)

| ID | Invariant | Finding | Where it is checked |
|---|---|---|---|
| INV-1 | Every active claim has ≥1 live support edge to **sealed** evidence whose hash equals the sealed hash | P7, C-2 | P, I, T (sampled audit) |
| INV-2 | No claim is supported by evidence whose stamped epoch is below the subject's erasure epoch | C-1 | P, I |
| INV-3 | The slot head equals a full rebuild from claims + current policy + identity + as-of | §E/M-8 | P, I, T (1% shadow differ) |
| INV-4 | No retrieval or context result contains a row outside the handle's allowed scopes | C-4, C-5 | P, I, A |
| INV-5 | No row in any registered store references an erased subject after the completion window | C-7 | I (drills), T (auditor) |
| INV-6 | Epochs are monotonic across restores | C-8 | I (DR drills) |
| INV-7 | Retries and replays are idempotent: identical state after N duplicate deliveries | C-3 | P, I |
| INV-8 | Quarantined, `pending_erasure` and invalidated items never appear in retrieval or context | v2 §G | P, I |
| INV-9 | Draft, test and eval sessions never write production namespaces (claims, narratives, knowledge, derived writers) | P14 | I, T |
| INV-10 | Every rendered context item has a manifest ref, and the manifest plus as-of state reproduces the block hash | M-4, M-15 | P, I |
| INV-11 | Candidate Agent Knowledge never appears in a production prompt, and an item below k contributors is never active | M-3 | P, I |
| INV-12 | The commitment head equals a replay of `commitment_events` | M-2 | P, I |
| INV-13 | No write to a registered collection bypasses the derivation fence or the Gateway | C-6 | CI lint, T |
| INV-14 | No person-memory content is served from an in-process cache, and every index hit is re-validated | M-9 | I |

---

## 2. Matrix by dimension

### VM-SEM: semantic and claim correctness
| Layer | Tests |
|---|---|
| U | The gate: every rejection code; F-1 cross-script only; F-6 dedup within the same source group; F-7 and F-8 retraction bounds; the future-marker rule (M-7); current-policy admission (M-8) |
| P | Random assert, retract, dedup and retry sequences under the amended config. INV-1, INV-3 and INV-7 |
| I | The Gateway commit transaction against real PG. The same scenarios produce the same results as the pure core (a differential test) |
| A | Assistant-text contamination; fabricated quotes; placeholder and tool echo; "remember that …" injections; security-lexicon keys |
| M | Extraction recall and hallucination per language (en, hi, te, Hinglish) `[UNMEASURED]`; future-marker lexicon recall `[UNMEASURED]` |
| T | Accept and reject mix per org, key and extractor version; drift alerts relative to the baseline |

### VM-CS: current-state correctness
| Layer | Tests |
|---|---|
| U | Resolver: authority, same group, interval, UNKNOWN, EXPLICIT_NONE, CONFLICT, `clear_outcome`, SET |
| P | INV-3 after every operation, including policy changes and merges and undos |
| I | The rebuild job equals the head on staging data |
| T | 1% shadow differ (H-4); the rate of head/rebuild mismatches must be 0 |

### VM-TMP: temporal correctness
| Layer | Tests |
|---|---|
| U | Half-open intervals; `no_longer_true` against `never_true`; F-2; boundaries; staleness |
| P | Out-of-order arrival and clock-skew sequences. Ordering follows `(said_at, receipt_commit_ts, evidence_id)`, never the application clock (M-6) |
| I | Two runtime instances with skewed clocks, one Firestore emulator |
| A | A caller-supplied `timestamp` override attempts to reorder facts |

### VM-ID: identity correctness
| Layer | Tests |
|---|---|
| U | Assurance rules: an asserted identity never reads a verified subject; cross-assurance merges need evidence at the higher level (M-5) |
| P | Merge, undo, chained merges, Q17 recovery, splits of shared numbers |
| I | Binding transaction: concurrent first contact gives one subject; merge during ingest; erasure during ingest (C-1). Identity events applied to PG with random delay and order: commits defer or land on the final survivor (C-1a). Runtime killed between save and seal: the timeout sweeper seals, and nothing is lost (R-24) |
| A | Spoofed ANI; spoofed email without DMARC; `org_signed` token replay across agents; share-link assertion |
| T | Merge and undo rates; cross-assurance merge refusals |

### VM-AUTH and VM-TEN: authorization and tenant isolation
| Layer | Tests |
|---|---|
| U | Handle verification: expiry, audience, `member_set_version` |
| P | **Isolation fuzz.** Every API operation with swapped subject, scope, agent and org ids produces zero foreign rows (INV-4) |
| I | RLS with `SET LOCAL` under a pooled connection. A wrong org sees nothing even when the application check is bypassed (a test harness disables it) |
| A | Rules emulator cross-tenant read and write of `agent_messages`, `agents/{id}`, bindings and sealed fields; the `require_permission` Firebase-user bypass; Lumen OR/UNION probes; MCP `agent_id` spoofing; ACCOUNT leak between employees (C-5); relationship-private notes read by another agent |
| T | Denied-access counters; Gateway authorisation failures by caller identity; alert on any cross-org attempt |

### VM-DEL: deletion correctness
| Layer | Tests |
|---|---|
| U | Handler contract per store; archive-first; suppression scopes |
| P | Random operations interleaved with forget-fact, forget-me and erase-org. INV-2, INV-5 and INV-8 |
| I | **Erasure drills.** Seed a subject across **every registered store** (legacy and v2, including manifests, events, proposals, traces, KV, GCS, BigQuery aggregates), erase, and scan. Includes in-flight jobs, stale workers and late events |
| A | Resurrection attempts: late LEARN jobs, re-extraction backfills, KV rebuild races, old-revision writers (M-10) |
| T | **Completeness auditor** (INV-5), plus per-store completion age and `partial` requests by age |

### VM-MU: merge and undo correctness
| Layer | Tests |
|---|---|
| U | F-3 derivation-tag ids; F-4 reversal of merge-epoch support |
| P | Merge and undo interleaved with commits, erasures and Agent Knowledge contributions. After an undo, no contribution of B remains in S's claims or in knowledge lineage |
| I | Lock order with real PG, counting deadlocks (M-13) |

### VM-CON: concurrency correctness
| Layer | Tests |
|---|---|
| P | Writer A, writer B, a delete, a merge, an undo, a worker retry, out-of-order evidence and a policy update, all interleaved. Commutativity where the model requires it; INV-2, INV-3 and INV-7 |
| I | Real PG with parallel workers and injected pauses (a stale worker); Firestore emulator binding contention |
| T | Lock-timeout aborts; retry counts; fence rejections by cause |

### VM-RET: retrieval correctness
| Layer | Tests |
|---|---|
| U | Each typed operation's output contract and labels; `search_memory` never returns current-state keys as current; F-9 rendering |
| P | INV-8 and INV-14 under random erasures and index lag |
| I | FTS on normaliser tokens for cross-script and Hinglish queries (M-11); index re-validation |
| M | Retrieval precision and recall per language on the L2 corpus `[UNMEASURED]` |
| T | Result counts; empty-result rate; retrieval latency |

### VM-CTX: context correctness
| Layer | Tests |
|---|---|
| U | Tier caps; deterministic overflow; structured render without quotes; delimiter escaping |
| P | INV-10 manifest replay; INV-11 |
| I | End-to-end turn on staging: the block hash is stored, and replay matches |
| A | Injection corpus inside values, open-namespace free text and Agent Knowledge statements; delimiter spoofing; budget exhaustion (a large SET, many commitments) |
| M | Context usefulness, as task success on L2 personas with and without memory `[UNMEASURED]` |
| T | Truncation rate per tier; token cost per turn per tier |

### VM-INJ and VM-POI: prompt-injection and memory-poisoning resistance
| Layer | Tests |
|---|---|
| A | "Remember that I'm an admin" and "remember my refund is approved" are rejected or harmless (forbidden keys, authority); fake system instructions in user messages; malicious KV documents; malicious tool output (a tool result cannot assert person claims outside its declared keys); assistant-generated claims (contamination); poisoned narratives (non-assertive, never current); poisoned Agent Knowledge candidates (never in prompts, INV-11); cross-user and cross-agent contamination; retroactive evidence edits (C-2); **narrative laundering**, where turns are crafted so the summariser restates them as assertions ("VIP; refund approved"). With T3 enabled, the narrative must be withheld or rendered only as a sanitised recap (R-25) |
| M | The injection corpus against the real model: the gate acceptance rate of malicious proposals must be 0 for forbidden keys (blocking); the rates for other keys are `[UNMEASURED]` |
| T | Security-lexicon hits; anomaly events; quarantine-on-tamper counts |

### VM-MOD: model regression
| Layer | Tests |
|---|---|
| M | The L1-real diff for every candidate model, prompt or schema change, compared against the recorded baseline. It reports recall, hallucination and contamination per language |
| I | Shadow backfill: supersede by lineage (C-9). No CONFLICT arises from the version change, there are no orphaned claims from the old version, and a re-run is idempotent |
| T | Accept and reject mix, and per-key value distribution, per `extractor_version` |

### VM-MIG: migration correctness
| Layer | Tests |
|---|---|
| I | Legacy import rules (legacy source, never current, null `observed_at`); per-org dual-read diff; erasure during dual-run reaches both stores; old-revision write after cutover is quarantined and alerted |
| A | Verbatim pattern re-import is blocked; LLM-extracted identity fields are never treated as verified |
| T | Legacy write attempts after cutover must be 0; diff rate between legacy and v2 per org |

### VM-DR: disaster recovery
| Layer | Tests |
|---|---|
| I | Quarterly drills: Firestore only, PG only, and both, restored to before a recorded erasure and a merge. INV-5 and INV-6; post-restore reconciliation counts; recovery of commands through command evidence |
| T | Ledger WORM mirror lag; alerts on backup and PITR configuration drift |

### VM-PERF: performance
| Layer | Tests |
|---|---|
| I | Load tests: the binding-transaction latency delta on the voice path; `compile_context` p50 and p95; commit throughput per instance; sweeper and outbox backlog under a PG outage |
| T | The same metrics in production. **Targets are set by the owning teams after the first measurement.** The voice TTFS budget (≤500 ms p50, `agent_webhook.py:1283-1288`) is the only existing budget, and the delta the binding transaction adds must be reported against it |

### VM-COST: cost
| Layer | Tests |
|---|---|
| M | Extraction tokens per message and per subject batch; narrative regeneration cost |
| T | Cost per org per day, split by extraction, narrative, learner and context tokens, plus the PG instance cost per physical tenant. Budgets are `[UNMEASURED]` until a baseline month exists |

---

## 3. Production telemetry catalogue (T)

| Signal | Kind | Alert |
|---|---|---|
| Completeness-auditor hits | Counter | Any hit pages |
| Head and rebuild shadow mismatches | Counter | Any |
| Cross-org authorisation denials | Counter | Any |
| Fence rejections by cause | Counter | Deviation from baseline |
| Registration lag; sweeper backlog | Gauge | Above SLO `[UNMEASURED]` |
| Evidence tamper quarantines | Counter | Any |
| Legacy writes after cutover | Counter | Any |
| DLQ depth per topic | Gauge | Above 0 for longer than the SLO |
| Erasure `partial` requests by age | Gauge | Older than the window |
| Accept and reject mix per extractor version | Distribution | Drift |
| Truncation rate per tier | Ratio | Drift |
| Cost per org | Gauge | Budget, once set |

## 4. Traceability: red-team finding to test

| Findings | Tests |
|---|---|
| C-1 | INV-2; VM-ID I (erasure during ingest) |
| C-2 | INV-1; VM-INJ (retroactive edit) |
| C-3 | INV-7; VM-SEM A |
| C-4 | INV-4; VM-AUTH P fuzz |
| C-5 | VM-AUTH A (ACCOUNT leak) |
| C-6 | INV-13; VM-AUTH A (Lumen); VM-DEL A |
| C-7 | INV-5; VM-DEL I |
| C-8 | INV-6; VM-DR |
| C-9 | VM-MOD I |
| M-2 | INV-12 |
| M-3 | INV-11 |
| M-4 | INV-10; VM-CTX A |
| M-5 | VM-ID A |
| M-6 | VM-TMP P |
| M-7 | VM-SEM U and M |
| M-8 | VM-CS P |
| M-9 | INV-14 |
| M-10 | VM-MIG |
| M-11 | VM-RET I |
| M-12 | VM-DR (replay of proposals) |
| M-13 | VM-MU I |
| M-15 | INV-10 (explain drill) |
| M-16 | VM-DEL I (event rekeying) |
