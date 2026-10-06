# Execution-Episode Generator Contract v1

**Date:** 2026-10-06.

**Classification:** TARGET ARCHITECTURE. An implementation-ready contract for a **future** server-side generator. No production deployment.

**Status:** **ENGINEERING CLOSURE.**

**Builds on:**
- `agent-execution-memory-foundation-v1.md` (visibility = CUSTOMER_SHARED; commitments the same);
- journal v1.1 + A1;
- the prototype `memory_core/episode_commitment`.

**No new memory class. No journal contract change.**

**Labels:**
- [CONTRACT]: `artifacts/architecture-contract.md`;
- [JOURNAL]: journal v1.1 + A1;
- [CODE]: the prototype;
- [REQ]: a requirement on the future generator;
- [TEST]: a test exists (§J).

**What exists today [CODE].**
- The durable surface the generator writes through: `EpisodeGeneration`, `record_episode_generation`, `generations_at`, `episodes_at`, `derive_status`, `search_memory`.
- **No execution-episode generator exists.** The only generator surface is Lane A's conversational `Memory.assign_episodes` (a time gap over USER evidence), which this contract does not reuse.
- No caller-facing write operation for episodes exists, and none is created here.

---

## A. Generator inputs (the closed set)

| Input | Source | Rule |
|---|---|---|
| Member Evidence records | The evidence store: trusted tool observations, agent decisions [CONTRACT §1] | Only records whose kind is execution (tool invocation, tool result, decision, retry, fallback, failure, outcome). **Never** user messages or assistant text |
| Customer subject identity | The bound execution context (Gateway handle subject, C-4) | Exactly one subject |
| Tenant identity | The bound context (handle org) | Must equal every member's tenant |
| Originating agent | **Trusted server-side execution context**: the authenticated Gateway-bound agent | [REQ] Never from a payload (§D) |
| Session identity | Member Evidence (where present) | Attribution and session fence only; not part of identity |
| Correlation / trace identity | Member Evidence (the execution runtime stamps it) | Exactly one per episode |
| Evidence lifecycle / usability | The evidence store status at generation time | Determines `active_at_generation` |
| Timestamps | Member `observed_at` | — |
| Security / retention class | Existing class inputs (T-2 / B-3 values are existing owner items; prototype uses `TEST_ONLY_*`) | [REQ] Not lower than the most restrictive member's class (a requirement of this contract; the class values themselves stay with T-2 / B-3) |
| Generator version | A registered execution-generator family (foundation §B) | Fixed per release |

Nothing else is an input: no prior summaries ("from evidence only, never from summaries", Lane A S8), no other customer's data, no model memory.

## B. Episode boundary (deterministic)

**Rule:** **one agent × one customer subject × one correlation identity.** No time-window heuristic.

| Case | Behaviour [REQ] |
|---|---|
| Required member conditions | Execution kind; same subject, tenant, agent and correlation id; evidence exists in the store |
| Ordering | Members sorted by (`observed_at`, evidence id). Deterministic |
| Boundaries | `started_at` = the first member's `observed_at`; `ended_at` = the last member's `observed_at` |
| Missing subject identity | Refused: `identity_required` (also enforced by the durable surface [CODE] [TEST GEN-7]) |
| Missing correlation id or agent | Refused: no episode (never grouped by time instead) |
| Mixed agents within one correlation id | **Refused** (`mixed_agents`). Never split silently, never re-attributed |
| Mixed customers within one correlation id | **Refused** (`mixed_subjects`). Each customer's execution must carry its own correlation id |
| Mixed correlation ids | Separate episodes, one per correlation id [TEST GEN-4, surface level] |
| A member becomes dead, withdrawn or erased | The served episode is excluded by the dead-evidence filter at read [CODE] [TEST]. A regeneration over the surviving usable members is a **new** generation (the usable set is part of the key) [CODE] [TEST] |

**Episode id [REQ]:** keyed hash of (subject key, `"exec"`, agent id, correlation id), the existing `ids._h` construction. Deterministic, and unlinkable after crypto-shred.

## C. Generator output: one `EpisodeGeneration` (existing type, no new field)

| Field | Value |
|---|---|
| `episode_id` | §B |
| `subject_id` | The bound subject |
| `tenant_id` | The bound tenant |
| `agent_id` | The trusted execution-context agent (§D) |
| `evidence_ids` | All members, in §B order |
| `active_at_generation` | Members usable at generation time |
| `started_at`, `ended_at` | §B |
| `summary` | §E: the canonical rendering, or a paraphrase that passes the guardrail |
| `generator_version` | The registered execution family + version |
| `merge_ids` | Existing merge lifecycle (J5); usually empty |
| `security_class`, `retention_class` | §A |

**Generation identity [CODE]:** `episode:<episode_id>:<keyed hash(episode, sorted members, sorted usable members, generator version)>`.
- The summary text and `agent_id` are **not** part of the key.
- Same inputs, therefore, give DUPLICATE and the recorded generation [TEST GEN-2, GEN-3, GEN-10].

**No explicit class field** is added; the generator family in `generator_version` identifies execution episodes.

## D. Agent attribution security

**Requirements [REQ]:**
- `agent_id` comes only from the trusted server-side execution context: the authenticated agent of the Gateway-bound turn (signed handle, C-4), carried by the runtime alongside the correlation id.
- The generator **must not** take it from:
  - a request or payload field;
  - narrative or summary text;
  - an arbitrary caller value;
  - inference from content.

**What the durable surface already guarantees [CODE] [TEST GEN-10].**
- Attribution is fixed by the first durable write of a generation's inputs.
- A later write of the same inputs with a different `agent_id` returns DUPLICATE and serves the original attribution.

**What it does not guarantee.** `record_episode_generation` is a server-internal function and takes `agent_id` as given. Binding it to the trusted context is the future generator's job. This is stated as a requirement, not hidden behind an invented public write API.

## E. Non-procedural output (deterministic guardrail)

**Allowed content:** single past occurrences only. What the agent did, which tool, what it returned, what failed, what was retried, what eventually happened, with times.

**Prohibited:** any generalisation over occurrences. Examples: "X is generally unreliable", "always use Y when X fails", "X should never be used". Those are procedural (D7 / Decision 1b).

**Mechanism [REQ]:**
1. **Canonical rendering (the guarantee).** The `summary` is a deterministic template over the ordered members: one line per member, `<observed_at> <kind> <tool/target> → <status/result reference>`, plus a final outcome line. It describes occurrences only, so it **cannot express a rule**, and it is byte-identical for the same inputs (GEN-20).
2. **Optional paraphrase.** A model may paraphrase the canonical rendering only if the paraphrase passes a deterministic validator. The validator rejects generalising markers ("always", "never", "generally", "usually", "in general", "whenever", "should", "must", "best to", "avoid", "prefer", "rule", "policy"; plus imperative mood at sentence start). On any rejection, the **canonical rendering is written instead** (transformed, never committed as a rule).
3. **Ceiling (stated, not hidden).** A lexical validator has false negatives, especially outside English. The canonical rendering is the only path that is generalisation-free by construction. Deployments that need the guarantee should write the canonical rendering only.

## F. Claim-Gate isolation

**The generator cannot reach the Claim Gate:**
- `episode_summary` is not in the projected kinds (`PROJECTED_KINDS = claim, retraction, lifecycle, sync`) [CODE] [TEST];
- A1 states "Not consumed by the claim projection" [JOURNAL];
- Narrative Memory "MUST NOT establish Current State, override Claims, establish authority" [CONTRACT §1].

A world fact in a summary stays narrative [TEST GEN-11].

**The legitimate path:** Evidence (a trusted tool observation) → extraction proposal → deterministic Claim Gate under the predicate's policy → Claim Commit → journal. The proposal cites the Evidence, never the episode [TEST].

**[REQ]** The generator never emits proposals.

## G. Durable Journal fit (v1.1 + A1, unchanged)

| Property | Fit |
|---|---|
| Entry kind | `episode_summary` (A1 row 11) |
| Partition | The episode subject's partition; identity-less writes are refused [CODE] |
| Commit ordering | O1; journal-assigned commit time (X-1); the latest generation per episode wins |
| Idempotency | The input key (§C); decided before time (K8) |
| Recorded-outcome replay | Same inputs → DUPLICATE, recorded text served, including after process loss and from a fresh journal over the same store [TEST GEN-13] |
| Rebuild | `generations_at` from facts |
| Checkpoint folding | Generations are in the fold and the canonical signature [TEST GEN-14] |
| Erasure | The partition fence plus key destruction: nothing served, appends refused [TEST GEN-15] |
| Crash / retry | Acknowledged → durable (S3). Un-acknowledged retry → DUPLICATE or APPENDED, exactly one entry [TEST] |

**No incompatibility found; no [CONTRACT_GAP] for the journal.**

## H. Retrieval

Journal → `search_memory` → Context Compiler, all unchanged:
- `NARRATIVE` type, `HISTORICAL` usage;
- the "background only; not authoritative" section;
- provenance = member evidence ids;
- access = `may_read(caller, ("CUSTOMER", X))` (**CUSTOMER_SHARED**), with **no agent filter**;
- deterministic ranking (token overlap, recency, id);
- dead-evidence and quarantine exclusion.

All of this is covered by `test_execution_memory_visibility.py`.

## I. Commitment separation

The generator may describe a promise historically (from its evidence). It never writes `commitment_event`s. Commitments flow only through `record_commitment_event` with live evidence [CODE] [TEST GEN-12].

## J. Deterministic test matrix

**Key:**
- **EXISTING** = already covered in `tests/test_execution_memory_visibility.py` (57, from the visibility workstream);
- **NEW** = added in `tests/test_execution_episode_generator_contract.py` (this workstream);
- **REQ-ONLY** = a requirement on the future generator, which does not exist. It is not testable today, and no fake generator was built.

| ID | Requirement | Coverage |
|---|---|---|
| GEN-1 | Valid evidence → exactly one generation | EXISTING `test_ec1` |
| GEN-2 | Same inputs → same identity and output | **NEW** `test_gen2_generation_identity_depends_only_on_inputs` (key excludes text and agent; changes with members, usable set, version, episode); EXISTING `test_ec2` |
| GEN-3 | Same key, different text → recorded outcome | EXISTING `test_ec2`; **NEW** `test_gen3_gen10_…` |
| GEN-4 | Mixed correlation ids → separate episodes | **NEW** `test_gen4_distinct_episode_ids_are_served_as_separate_episodes` (surface level); the grouping itself is REQ-ONLY |
| GEN-5 | Mixed customers → refusal | REQ-ONLY (§B). The durable surface cannot see member subjects (the evidence store is outside it; E-5) |
| GEN-6 | Mixed agents → refusal | REQ-ONLY (§B) |
| GEN-7 | Missing subject → `identity_required` | EXISTING `test_ec4` |
| GEN-8 | Dead / withdrawn evidence excluded | EXISTING `test_rt2_rt3`, `test_er2_er3`; **NEW** `test_gen8_regeneration_over_surviving_members_is_a_new_generation` |
| GEN-9 | Agent from trusted context | REQ-ONLY (§D); the read side is EXISTING `test_at1`, `test_at2` |
| GEN-10 | A forged payload agent cannot alter attribution | **NEW** `test_gen3_gen10_a_retry_with_other_text_or_another_agent_keeps_the_recorded_generation` (surface guarantee); the generator-side part is REQ-ONLY |
| GEN-11 | World fact in a summary → no state change | EXISTING `test_cg1`, `test_cg3` |
| GEN-12 | A summary cannot create, change or fulfil a commitment | EXISTING `test_cm1_cm2_cm3` |
| GEN-13 | Replay produces the recorded output | **NEW** `test_gen13_recorded_output_survives_process_loss_and_a_fresh_journal` |
| GEN-14 | Checkpoint + suffix = full replay | EXISTING `test_rp1` |
| GEN-15 | Customer erasure removes visibility | EXISTING `test_er1` |
| GEN-16 | Retrievable only with CUSTOMER authorization | EXISTING `test_ua1`, `test_ua2`, `test_ua3` |
| GEN-17 | A second authorized agent reads it | EXISTING `test_xa1`, `test_xa2` |
| GEN-18 | An unauthorized agent cannot | EXISTING `test_ua1` |
| GEN-19 | Generalisations never committed | REQ-ONLY (§E: the canonical rendering plus the validator fallback). Testable once a generator exists; test spec: 12 prohibited phrasings → the canonical rendering is written |
| GEN-20 | Repeated generation is byte-equivalent | REQ-ONLY for the generator (canonical rendering); the durable and read sides are EXISTING `test_dt1` and `test_pv2` |

**Totals:**
- 20 rows: 14 fully covered by tests (EXISTING and/or NEW), 6 REQ-ONLY (GEN-5, 6, 9, 19, 20 generator side, plus the generator half of GEN-4 and GEN-10);
- NEW tests: **4 scenarios × 2 stores = 8**, plus **1** store-independent = **9**. **9/9 pass.**
- Mutation check: the generation key including the summary text, or including `agent_id`, is caught (GEN-2 / GEN-3 / GEN-10).

**Regression:** full prototype suite **1868 passed** (1859 + 9). `test_execution_memory_visibility.py` 57/57, unchanged.

## K. Implementation decision

**No generator was implemented.** No execution-generator surface exists to extend, and building one would be new feature work, not a bounded fix. The contract's durable-side rules are pinned by tests. The generator-side rules (§B grouping and refusals, §D context binding, §E guardrail) are the implementation brief for whoever builds it.

## Remaining items

- The third-party data question is now an owner packet: `third-party-erasure-in-customer-execution-memory-owner-decision-v1.md`.
- E-5 (Evidence durability) and T-2 / B-3 (class values) are existing owner items, not reopened.
- D7 / Decision 1b is separate; §E keeps procedural content out.

**EXECUTION-EPISODE GENERATOR CONTRACT V1: ENGINEERING CLOSURE.**
