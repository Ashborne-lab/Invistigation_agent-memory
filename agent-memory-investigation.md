# Agent Memory: current-state investigation and target architecture

**Date:** 2026-09-28. **Track:** Agent Memory. **Deliverable:** this document. No repository, production or configuration change was made.

**Evidence base:**
- Every code citation is at `origin/main`, read with `git show origin/main:…`.
- **Local working trees are stale.** For example, runtime HEAD is `b2401a0` but `origin/main` is `daee3f9`. `cs_packet_builder.py` differs by about 316 lines between them. The memory write path and the memory router are identical in both.
- SHAs are listed in §20.

**Labels:**
- Evidence types: `[CODE]` `[CONTRACT]` `[DATA]` `[INFERENCE]` `[DERIVED]` `[UNDECIDED]` `[UNRESOLVED]` `[UNMEASURED]`.
- **PRESENT** means a concrete code path produces the behaviour on ordinary inputs. **POSSIBLE** means the behaviour is possible but no triggering path was shown.
- No production data was accessed, so every frequency is `[UNMEASURED]`.

**Not repeated here.** These topics are already covered, and this document only references them:
- the person read inventory, the P1–P4 prompt paths, and org and agent isolation: [person-identity-read-paths.md](person-identity-read-paths.md)
- identity write paths, merge, undo and transfer: [person-identity-resolution-spec.md](person-identity-resolution-spec.md) and [person-merge-current-state-memory-research.md](person-merge-current-state-memory-research.md)
- the `agent_datastores` key spaces and the deletion map: [storage-reality-audit.md](storage-reality-audit.md) §10–11
- settled identity policy: [final-identity-docket-2026-09-28.md](final-identity-docket-2026-09-28.md) and [identity-patch-draft-2026-09-28.md](identity-patch-draft-2026-09-28.md)

---

## 1. Executive conclusion

**The current memory is a disposable per-(agent, channel-id) profile, not memory.** `[CODE]`
- A Haiku call rewrites the whole profile after each production turn.
- It is stored as a list of at most 30 undated, unattributed strings.
- Every string is injected into the system prompt on every turn.

It has none of the properties the standard requires: provenance, time, supersession, correction, recovery or measurement. Several failure modes are PRESENT, not just possible.

**The five failures that matter most:**
1. **Silent destruction.** `[CODE]`
   - A well-formed but empty reply (`{"facts": []}`), or a list holding no strings, passes validation and is written over the whole profile.
   - Output is capped at `max_tokens=1024`, and the stop reason is never checked. A long profile can therefore produce truncated JSON, which is silently discarded. The profile then **freezes**: `[INFERENCE]`, frequency `[UNMEASURED]`.
2. **Contamination.** `[CODE]`
   - The extractor reads the assistant's reply as input, so the agent's own statements become "facts about the user".
   - User text is inlined with no delimiter and no injection rule.
   - The result is placed in the **system prompt** as "Known facts".
3. **Concurrency and deletion.** `[CODE]`
   - Writes are read → LLM (seconds) → blind `set(merge=True)`, with no transaction, idempotency key or tombstone.
   - Concurrent turns lose updates.
   - A GDPR delete that lands during an extraction is **written back**.
   - The next turn re-creates the document anyway.
4. **Shadow memory that "forget" does not reach.** `[CODE]`
   - WhatsApp, Instagram and Slack session ids are deterministic per endpoint, so a "session" never ends.
   - Its history, up to 500 messages and 8,000 tokens, and its rolling LLM summary carry facts across every conversation, indefinitely.
   - This happens outside every memory flag, and memory deletion does not touch it.
   - A second shadow layer, agent-wide `learned_patterns`, stores verbatim user messages with **no org field** and injects `key_facts` as "ground truth".
5. **Blindness.** `[CODE]`
   - There are no metrics.
   - The billing client drops `feature="user_memory"`.
   - The eval harness cannot exercise memory at all: it sends no `user_id`, it forces draft mode, and draft mode skips every memory write.
   - No extraction-quality test runs a real model.

**Recommended target** `[DERIVED]`: the smallest architecture that meets the invariants in §13.
- **Evidence:** the messages that already exist, with the person's subject id attached.
- **Extraction:** returns grounded **deltas** (add / supersede / retract), each citing a quote from the **user's** text in that turn. A deterministic check rejects any ungrounded delta.
- **Store:** an **append-only memory ledger per subject**. Items carry kind, evidence, time, status and merge epoch.
- **Hot path:** a rebuildable **projection document** per subject, which is one read on the hot path.
- **Current state:** a small predicate registry that produces current-state slots for a handful of predicates.
- **Context:** a single, dated, labelled context budget.
- **Evaluation:** three evaluation lanes.

This works on Firestore today. PostgreSQL and the Memory Gateway change where the ledger lives, not what it is. **Vectors, graphs and embeddings are not required** by any failure found, and are deferred until measured need (§14.9).

---

## 2. Current memory architecture

There are three things an agent "knows about a person", plus two agent-wide layers. Only the first is called "memory". `[CODE]`

| Layer | Store | Written by | Read into prompt | Gated by memory flags? |
|---|---|---|---|---|
| **A. User memory (facts)** | `agent_user_memory/{agent}__{sha256(key)[:32]}` | post-turn Haiku extractor | P1, "Known facts about this user" | yes |
| **B. Person records (fields)** | `agent_datastores/…/entries/{person_hash}` (Stage 2); legacy `field_values*` on the doc in A | the same Haiku call's `sets` output | P2, "What you already know about this person" | partly (read needs `user_id`) |
| **C. Session history + summary** | `agent_messages`, `agent_sessions.summary` | every turn; rolling summariser | P4 plus the `[Conversation Memory]` pair | **no** |
| D. Learned patterns (agent-wide) | `agent_learned_patterns/{agent}/patterns` | post-turn pattern learner | forced `recall_learnings` result, "ground truth" | `learned_patterns_enabled` |
| E. Owner lessons / workflow memory / research overlays | see §4.4 | operators / workflow / research | agent-specific | n/a |

The platform flags `user_memory_enabled`, `prompt_cache_v2` and `channel_profiles_enabled` all default to False. No deploy config in the repo sets them. `runtime@daee3f9:config/settings.py:191,203,235`. Their production values are `[UNMEASURED]`.

---

## 3. End-to-end memory lifecycle

`[CODE]` unless marked. Runtime `daee3f9`.

1. **Observation.**
   - Channel routers (`agent_webhook`, `meta_whatsapp`, `meta_instagram`, `email`, `slack`, `directives`) call `process_message`.
   - `user_text` is the raw `user_message.content`, with a placeholder such as `"[Image]"` for media (`meta_whatsapp.py:543`).
   - The assistant message is saved (`lightweight_processor.py:1419-1426`).
2. **Extraction trigger.** A single call site at `lightweight_processor.py:1464`.
   - It runs inside `_persist_inbound_message`, so nudges are skipped.
   - It is `asyncio.create_task` with no reference kept, and every exception is swallowed into a warning (`:4199-4203`).
   - **Gates** (`:4025-4166`):
     1. platform flag;
     2. agent flag **or** a non-empty `wanted_fields/sets`;
     3. an org id;
     4. **`is_production`**;
     5. a `user_id`, **falling back to `session_id`** with `user_key_kind="session"`;
     6. PII policy off;
     7. provider available.
3. **Extraction.** `agent_memory_service.update_user_memory`.
   - It reads the existing doc (`:276`).
   - It calls Haiku `generate_json` (`:305-315`) with:
     - `CURRENT FACTS`;
     - `WANTED SETS`;
     - on legacy sets only, the current field values;
     - `LATEST TURN: User: {user_text[:4000]} / Assistant: {assistant_text[:4000]}`.
   - The model returns the "UPDATED COMPLETE list of facts" plus set values (`:40-65`).
4. **Persistence.**
   - `_clean_facts` runs (`:147-159`).
   - Set values go to `write_extract_entry`, which does `set({"values"}, merge=True)` (`extract_entry_writer.py:100`).
   - The doc is written with `set(data, merge=True)` (`:398-421`): `facts` is replaced whole; `last_session_id` and `last_message_id` are overwritten; `turns_observed` gets `Increment(1)`.
5. **Retrieval.** On the next turn, `CSPacketBuilder.build` (`cs_packet_builder.py:611-1244`) runs:
   - P1 `_load_user_memory_block` (`:1957-1981`);
   - P2 person records (`:1983-2078`);
   - P4 history and summary.

   These are synchronous `.get()` calls inside async functions.
6. **Context.** Facts are rendered unconditionally, in stored order, undated (`format_memory_block`, `agent_memory_service.py:129-144`).
   - They go into the dynamic system tail, or, with `prompt_cache_v2` off, into the cached system block (`:789-816`).
7. **Subsequent update.** The next writing turn regenerates the list from the current list plus the new turn. Nothing anchors a fact to its original wording.
8. **Correction.**
   - **`agent_user_memory` has no correction path.** The API is GET and whole-document DELETE only (`routers/agent_memory.py:48,88`), and Firestore rules deny client writes (`studio@1f05ca11:firestore.rules:692-695`).
   - Datastore entries can be PATCHed (`agent-design@c56271d:app/routers/datastore.py:256`), but the next extraction overwrites them (§10).
9. **Deletion.** `delete_user_memory` does a get, an org compare, then `delete()` (`agent_memory_service.py:498-529`).
   - It removes one doc. There is no cascade (§8).

---

## 4. Current storage model

### 4.1 `agent_user_memory` document `[CODE]` (`agent_memory_service.py:399-420`, `:468-488`)

- **Tenancy fields:** `agent_id`, `organization_id`, `project_id`, `channel`, `channel_user_id` (**plaintext raw identifier**).
- **Content:**
  - `facts: string[]`, capped at 30 (`settings.py:247`), each at most 300 chars (`:38`);
  - `facts_count`, `user_key_kind` (`identity` or `session`).
- **Lineage:** `last_session_id` and `last_message_id`, overwritten on each write.
- **Counters and timestamps:** `turns_observed` (counts writes, not turns), `updated_at`, `created_at` (first write only), `schema_version`.
- **Legacy:** `field_values`, `field_values_by_set`, `field_values_updated_at`.

**What is missing per fact:** confidence, source, evidence, observed/valid time, status, kind (stated/inferred), extractor version.

**`schema_version` is unreliable.**
- It is written but never read. A v2 write leaves v1 maps in place because of `merge=True`.
- Handling actually branches on the config shape, not on the version (`lightweight_processor.py:4059-4126`).

### 4.2 Classification against the contract (does the implementation genuinely fit?)

| Current thing | Closest contract class | Fit |
|---|---|---|
| `agent_messages` (user turns) | **Evidence** | Genuine. Append-only in practice, but it lacks a person `user_id` (`lightweight_processor.py:2948-2965`) `[CODE]` |
| `facts[]` | none cleanly | **Mixes four classes in one list:** durable Memory ("recurring issues, important history"), Current State ("prefers email"), identity attributes, and model inference. No status, provenance or time, so it is not a Claim. It is regenerated, so it is not Memory in the contract sense of retained knowledge `[CODE]` `[CONTRACT]` §1 |
| datastore entry `values` | Current-State-like slots without Claims | Violates "never written independently of Claims" (rule 2, `:999`). D1(a) already classifies migrated rows as un-provenanced Memory `[CONTRACT]` |
| session `summary` | **Narrative Memory**, but non-compliant | It lacks the scope, provenance, `observed_at` and status that Narrative Memory MUST carry (`:60`). It is presented to the model as the user's own message, not as labelled non-assertive `[CONTRACT]` `[CODE]` |
| learned-pattern `key_facts` | Memory derived across customers | Presented as "ground truth", which violates rule 10 (`:1007`). It is also an aggregate derived from customer content, so §10 `:796-824` dataset governance applies (G5) `[CONTRACT]` `[DERIVED]` |

### 4.3 Where the contract is insufficient `[DERIVED]`

- **Plain Memory has no required fields or lifecycle.** Only Claims (`:40`) and Narrative Memory (`:60`) do. A free-text memory item needs status, provenance, time and supersession too, or it recreates today's `facts[]`.
- **Agent output as evidence.** §1 lists "an agent decision" as Evidence (`:22`). The contract never says that agent output is **not** evidence for claims **about the user**. That is the gap through which today's contamination occurs.
- **Context assembly.** No precedence or budget rule exists across Current State, Memory, Narrative Memory and history (§15 ends at "CONTEXT BUILDER" without semantics).
- **Evaluation.** The contract says nothing on evaluation.

### 4.4 Other memory-like stores `[CODE]`

| Store | Reaches prompt | Per person | Org binding | Note |
|---|---|---|---|---|
| `agent_learned_patterns/{agent}/patterns` | yes, forced recall | no, but holds **up to 3 verbatim user messages** (`core/learning/pattern_store.py:64-70`) | **none**: `LearnedPattern` has no org field (`core/firestore_schemas.py:352-375`) | Earlier correction **re-confirmed at `daee3f9`** |
| `agents/{id}/owner_lessons` | yes, applied to the published brain (`agent-engine@dfc3a47:alchemist/trainer/apply.py:30-60`) | no | parent path only; client-writable per the rules catch-all | The only memory-like store with a lifecycle: `status`, `created_by`, `applied_version`, `source` |
| `workflow_agent_memory/{agent}` | yes, and overrides are **auto-applied** (`workflow-runtime@2356de0:app/core/orchestrator.py:926-945`) | no | none | already documented |
| `research_templates/{id}/learned/*` | yes | no | via template | out of person scope |
| vector memory | **none**. `knowledge_embeddings` is LEGACY and dead | — | — | Knowledge retrieval is BM25 plus LLM, "NO embeddings, NO vectors" (`knowledge-vault@25b46be:services/dci/fts_index.py:4-8`) |

---

## 5. Extraction behaviour

`[CODE]`, `agent_memory_service.py` at `daee3f9` unless noted. This answers each question in the brief.

| Question | Answer |
|---|---|
| **Input** | Current facts (JSON), wanted sets, legacy field values (legacy only), and the **latest turn only**: user text and **assistant text**, each truncated to 4,000 chars (`:299-304`, `:433-438`). It gets no earlier turns, no tool results (though the reply may restate them), no summary, and no stored entry values on the v2 path |
| **What counts as a memory** | Prompt definition only: "durable and user-specific: identity, preferences, constraints, commitments, recurring issues, important history". Excluded: small talk, resolved transactional details, facts about agent or company, "speculation" (`:40-65`) |
| **Replacement or delta** | **Full replacement** of `facts`. Removal is a fact missing from the returned list. Fields are key-level upserts that can be replaced but never removed (`:341`, `:459`; `extract_entry_writer.py:100`) |
| **Uncertainty** | No representation. The model either writes or omits |
| **Contradictory output** | Not detected. The model's list wins |
| **Malformed output** | `generate_json` returns `{}` on empty text or a parse failure (`anthropic_provider.py:~4677-4689`). `_clean_facts(None)` then returns `None`, meaning "keep what we have" |
| **Empty or garbage list** | `{"facts": []}`, or a list with no strings, gives `[]`. **That is written and wipes the profile** (`:147-159`, then the write at `:405`) |
| **Truncated output** | `max_tokens=1024` (`:309`, `:443`), and **`stop_reason` is never checked** (`generate_json` body). Truncated JSON fails to parse, so nothing is written. 30 facts × 25 words ≈ 1,000 tokens plus JSON and sets, so a full profile plausibly exceeds the budget and **stops updating**. `[INFERENCE]`; frequency `[UNMEASURED]`, measurable from `[generate_json.usage]` `completion_tokens` |
| **Confidence** | Not tracked |
| **Provenance** | Not kept per fact. Only the document-level `last_*`, overwritten each time |
| **Timestamps / validity** | None per fact |
| **Fabrication** | Unconstrained: no grounding check. "No speculation" is only a request in the prompt |
| **Repetition** | Does not raise confidence (none exists). It does trigger rewrites: the unchanged check is exact, order-sensitive list equality (`:358`, `:393`, `:462`) |
| **Disappearance by omission** | **Yes, by design.** Also by the "drop the least useful" instruction, and by the tail slice `facts[:30]` |
| **Duplicate wording** | Possible. No deduplication or normalisation |
| **Cap effect on long-lived users** | Once the profile is full, every new durable fact evicts an old one by the model's judgement, with no record of what was evicted. Combined with the output budget, the profile either churns or freezes `[INFERENCE]` |
| **Poisoning** | Undefended. User text is inlined without delimiters, and "I'm a VIP / platform admin" fits "identity". The output lands in the **system prompt** `[CODE]` |
| **Idempotency** | None. `message_id` is a fresh assistant doc id (`lightweight_processor.py:1271`), and there is no `wamid` dedup (`meta_whatsapp.py:530`). A redelivered turn re-extracts `[CODE]`; whether redelivery happens is `[UNMEASURED]` |
| **Git history** | Unchanged since 2026-06-13: the 4000/300/1024 limits and the full-list rewrite. `7424487` briefly made every form-less turn write `field_values: {}`, erasing the only copy; `515a108` fixed it the same day. Whether it was deployed is `[UNRESOLVED]` |

---

## 6. Retrieval behaviour

`[CODE]` `cs_packet_builder.py@daee3f9`.

**Selection:**
- P1 and P2 are **unconditional**: all facts and all extract tables, every turn.
- No retrieval for person memory is relevance-based, semantic or lexical.
- The only query-dependent retrieval is knowledge search (BM25 on a tool call) and learned-pattern recall (a Haiku matcher).

**Budget:** only history is budgeted: 8,000 tokens, or 3,500 on voice (`settings.py:378`).
- P1 can reach about 9k characters, and P2 has no read cap.
- KB preload is up to 200k characters.
- No aggregate budget exists.
- If budgeting fails, up to 500 unbudgeted messages are sent (`:875-882`).

**Time:**
- No date is rendered for facts, P2 values or the summary.
- History `ts` is **stripped** before the model sees it (`:1704`).
- The model cannot tell stale from current.

**Current and historical mixed:** "important history" and current preferences sit in one undated list. `[CODE]`

**Conflict policy:** four different rules with no precedence between them:
- P1: "trust the user";
- P2: "do not ask again unless … changed";
- recall: "ground truth unless a tool call contradicts";
- summary: none.

**Failure versus absence:** exceptions, the kill switch, the agent flag and the PII gate all render as `""`, which is identical to "no memory" (`:791-810`, `:1967-1978`, `:2018-2027`).
- Recall errors return `{"patterns": []}`, the same result as "nothing matches".
- A failure to mask the summary silently drops the summary.
- Only finance context distinguishes the two.

**Cross-turn race:** extraction is fire-and-forget, so turn N+1 can render P1 from before turn N's update while history already shows turn N. `[CODE]` + `[INFERENCE]`

**Read and write gates disagree:**
- Writes accept "agent flag **or** memory node" and a session-key fallback (`lightweight_processor.py:4130`, `:4152-4158`).
- Reads require the agent flag **and** `user_id` (`cs_packet_builder.py:1968-1975`).
- So facts for extract-only agents and for anonymous sessions are **written and never read back**. They are still visible to operators (Noesis reads Firestore directly).

**Blocking:** P1 and P2 are sync `.get()` calls on the event loop. A Firestore brownout on reads can therefore stall unrelated turns. `[CODE]` + `[INFERENCE]`

**Voice:** per a runtime comment, the gateway sends no caller identity, so P1–P3 are empty on voice. The gateway repo is absent, so this is `[UNRESOLVED]`.

---

## 7. Failure-mode analysis

| # | Failure | Status | Evidence / trigger |
|---|---|---|---|
| F1 | Silent forgetting | **PRESENT** | Omission-as-deletion; an empty or garbage list wipes the profile (§5); the cap slice |
| F2 | Silent rewriting | **PRESENT** | The full list is regenerated each writing turn; "keep verbatim" is only a prompt request |
| F3 | Stale-memory use | **PRESENT** | No dates rendered; stored fields persist forever; the cross-turn race (§6) |
| F4 | Contradictory facts | **PRESENT** (path) | P1 is rewritten while P2 is merge-kept, so they diverge; P1, P2, summary, history and recall are rendered side by side with no reconciliation |
| F5 | Duplicated memories | POSSIBLE | No deduplication; depends on model behaviour |
| F6 | Loss of provenance | **PRESENT** | Bare strings; `last_*` overwritten |
| F7 | Loss of temporal information | **PRESENT** | No per-fact time; history `ts` stripped |
| F8 | Hallucination persisted | POSSIBLE (unconstrained) | No grounding check |
| F9 | Assistant-response contamination | **PRESENT** (input path) | `assistant_text` is extractor input (`agent_memory_service.py:303`, `lightweight_processor.py:4176`) |
| F10 | Memory poisoning | POSSIBLE, undefended | Undelimited user text; output placed in the system prompt |
| F11 | Incorrect extraction | POSSIBLE | A single unvalidated call; the v2 path is blind to stored entry values |
| F12 | Drift over many sessions | **PRESENT** (mechanism) | Repeated regeneration plus re-summarising already-summarised slices (summariser dropped-slice logic, `cs_packet_builder.py:1920-1924`) |
| F13 | Cross-person contamination | **PRESENT** (identity-dependent) | One doc per raw channel id, so a shared number is one "person" (`lead_contacts.py:828-833`). After a merge, the reply route contaminates (read-paths §11.2) |
| F14 | Cross-agent leakage | not present today | Memory is keyed per agent (read-paths §13). Q5 will change this deliberately |
| F15 | Cross-org leakage | **PRESENT exposures** | See §8 |
| F16 | Wrong memory after identity merge or undo | **PRESENT** (no mechanism) | No epoch, no versions (resolution spec §8) |
| F17 | Deletion/erasure inconsistency | **PRESENT** | §8.2 |
| F18 | Race / lost update | **PRESENT** | Read → LLM → blind write; no inflight guard (the summariser has one, `lightweight_processor.py:3990`; memory does not) |
| F19 | Non-idempotent writes | **PRESENT** | §5 |
| F20 | Partial writes | **PRESENT** | Entries are written before the doc (`:371-421`), with errors swallowed; header and entry are separate |
| F21 | Retry corruption | POSSIBLE | A retried turn re-extracts non-deterministically on top of the updated list |
| F22 | Artificial truncation | **PRESENT** | 4,000-char turn, 300-char fact (a mid-word cut), 30 facts, 1,024 output tokens |
| F23 | Unbounded growth | **PRESENT** | One session-keyed doc per anonymous conversation, never reaped; messages and sessions kept forever; TTL inert (§10) |
| F24 | Retrieval failure looks like absence | **PRESENT** | §6 |
| F25 | Prompt-context overload | POSSIBLE | No aggregate budget (§6) |
| F26 | Relevance failure | **PRESENT** | Everything is always injected |
| F27 | Inferred treated as fact | **PRESENT** | No stated/inferred flag; rendered as "Known facts"; recall as "ground truth"; the summary as the user's own words |
| F28 | Cannot reconstruct why a memory exists | **PRESENT** | No evidence link |
| F29 | Cannot recover from a bad update | **PRESENT** | No history; backups exist only for one customer project (§10) |
| F30 | Memory freeze at the output budget | PRESENT path, frequency `[UNMEASURED]` | §5 |

---

## 8. Security and isolation analysis

Only findings **not** already in read-paths §12–13 or in the security re-verification.

- **S-M1. Cross-tenant update and delete of `agent_users`.** **VERIFIED CURRENT, new.** `[CODE]`
  - `agent-design@c56271d:app/routers/agent_user.py` `PUT` and `DELETE /{user_id}` check only `require_permission(user, "agents:write")`.
  - The service does a get → `update()` / `delete()` by document id, with no org or agent comparison (`app/services/agent_user_service.py:99-157`).
  - This is the write-side twin of the known browser-read exposure.
  - Practical exploitability depends on whether document ids are guessable `[UNRESOLVED]`.
- **S-M2. Every org member reads every end-user's plaintext facts.** `[CODE]`
  - Noesis subscribes to `agent_user_memory` directly (`studio@1f05ca11:firestore.rules:635-643, 692-695`): `isOrgMember`, with no role gate.
  - The Noesis repo is absent from the workspace.
- **S-M3. Learned patterns carry verbatim user messages and have no org field.** Re-confirmed at `daee3f9` (§4.4).
- **S-M4. Raw identifiers in keys and logs.** `[CODE]`
  - WhatsApp session doc id is `{phone}-{agent}` (`meta_whatsapp.py:719`).
  - The memory-delete log line prints the raw `channel_user_id` (`routers/agent_memory.py:104-106`).
  - `channel_user_id` is stored in plaintext on the memory doc (`:404`).
- **S-M5. `memory-config` has no org check.** `_require_operator` only (`routers/agent_memory.py:116`; `routers/handoff.py:67-71`). It exposes field names, which is config, not PII. `[CODE]`
- **S-M6. Poisoned text reaches system-prompt authority** (F10). Undefended. `[CODE]`
- **S-M7. `owner_lessons` is client-writable** per the rules catch-all (`apply.py:36-40`), and it is applied into the published brain. `[CODE]` Exploitability is `[UNRESOLVED]`.

### 8.2 Erasure coverage `[CODE]`

| Store | Memory DELETE | Contact erasure (`lead_contacts.py:715-`) | Datastore DELETE | `agent_users` DELETE | Other |
|---|---|---|---|---|---|
| `agent_user_memory` | ✔ one agent | ✘ | ✘ | ✘ | ✘ |
| datastore entries | ✘ | ✘ | ✔ one row | ✘ | ✘ |
| `lead_*` | ✘ | ✔ | ✘ | ✘ | |
| `agent_users` | ✘ | ✘ | ✘ | ✔ (S-M1) | |
| `agent_sessions` (+`summary`, `phone_number`) | ✘ | ✘ | ✘ | ✘ | test-session delete only, which is inert (`studio-backend:services/testing_service.py:260-266`) |
| `agent_messages` | ✘ | ✘ | ✘ | ✘ | abort cleanup only |
| learned patterns | ✘ | ✘ | ✘ | ✘ | ✘ |

**Keys do not join across these stores:**
- Memory is keyed by a raw channel key.
- Contacts are keyed by a normalised phone or email.
- Anonymous rows are keyed by session id.

**Resurrection is PRESENT:**
- A delete that lands during an in-flight extraction is written back by the blind `set(merge=True)`.
- Any later turn re-creates the doc.
- Nothing records "forget me". `opted_out_at` gates outreach only.

---

## 9. Temporal and state analysis

- **No two-axis time.** `[CODE]` + `[CONTRACT]` §4 requires valid time and knowledge time. The current memory has neither per item, and the only document-level `updated_at` is never rendered.
- **Supersession is destruction.** A changed fact replaces the old string. "Used to own an iPhone 14" survives only if the model happens to write it. `[CODE]`
- **Current State is not separated.** Predicates the contract would put in State Slots (communication preference, language, opt-out) are stored as free text among historical facts. `[CODE]`
  - Opt-out is actually held elsewhere, as `agent_users.opted_out_at` and outreach gates. So the prompt's "facts" and the operational state can disagree. `[INFERENCE]`
- **Narrative leaks as assertion.** The summary is framed as a user message, followed by the ack "Understood, I have this context". `[CODE]`
- **The fix is small and follows from the contract.** `[DERIVED]`
  - Every memory item carries `observed_at` (knowledge time) and optional `valid_from` / `valid_until`. Supersession sets `valid_until` and `superseded_by` rather than deleting.
  - A small, explicit set of predicates is current-state-eligible and resolves as a slot. Everything else is Memory, rendered with its date.

---

## 10. Persistence and recovery analysis

| Capability | Today | Why |
|---|---|---|
| Correction | ✘ for facts; ✔ for entries, but overwritten by the next extraction, and `updated_by` stays pointing at the operator (misattribution) | GET/DELETE only; the extractor never sees the stored entry value |
| Rollback | ✘ | No versions; the migration script deletes source maps without keeping a copy (`agent-design:scripts/migrate_extract_rows.py:553-556`) |
| Audit | ✘ for memory (log line); partial for entries (an AuditEvent without values) | |
| Historical reconstruction | ✘ | Nothing links a fact to its evidence |
| Reprocessing | POSSIBLE in principle: raw messages are kept, with no TTL | But messages lack `user_id`; replay is order-dependent and non-deterministic; PII orgs never extracted; no tool exists |
| Deletion / erasure | Fragmented (§8.2) | |
| Identity merge / undo | ✘ | No epoch; the doc is keyed by a raw key; content is regenerated |
| Migration | IN-FLIGHT | Stage 2 `fill`: on 2026-09-12 the script's own header recorded **zero writes** (10 agents, 32 docs, 18 holding values). The router docstring's claim that the map was deleted "from every document" is **CONTRADICTED / unproven** |
| Rebuild of derived data | ✘ | There is nothing to rebuild from |
| Backups | One dedicated-customer project has daily (14 d), weekly (90 d) and PITR backups (`studio:infra/gcp/clix-capital-prod/firestore_backups.tf`) | Erased memory can therefore persist in backups for up to 90 days. Nothing was found for `olbrain-india-prod` `[UNRESOLVED]` |
| TTL | Inert | The TTL on `agent_sessions.expires_at` assumes "app code stamps expires_at on create", which is **contradicted**: no writer exists. `conversation_memory_ttl` has no consumer |

**The representation destroys exactly the information recovery needs:**
- prior versions;
- the evidence behind each fact;
- which turn produced which fact;
- whether a fact came from the user or the agent.

These cannot be reconstructed after the fact. `[DERIVED]`

---

## 11. Identity interaction

This section applies the settled identity policy without reopening it. `[DERIVED]`

- **Memory is keyed by `(agent, raw channel key)`, not by person.** WhatsApp and email for one human are two memories today. This is J1 fragmentation.
- **The settled undo design (Q17 quarantine, council C1 epoch tags) needs per-item attribution.** Today's single regenerated list cannot provide it.
  - Under the target ledger (§14), each item already carries its subject, evidence and `merge_epoch`.
  - Undo therefore becomes "mark this epoch's items quarantined; the other items return to their subjects".
  - This makes council C1's copy-on-first-write snapshot **unnecessary for memory**. It is a simplification that fully satisfies Q17. **No identity policy changes.**
- **Q5 cross-agent sharing** needs agent visibility to be an explicit grant (PI-8). Items record the `agent_id` that learned them, for provenance. Visibility is evaluated at read time, not at write time.
- **Survivor-canonical current state (X2) and R2.** Memory items are not re-subjected. Reads over the member set apply R2: ordinary policy, and consent resolves most-restrictive.
- **Extraction must never read the reply.** This (§14.2) is the one memory change the identity design **depends on**, because reply laundering is the contamination route read-paths §11.2 identified.
- **Direct contradiction check:** none found. The memory investigation does not contradict any settled identity decision.

---

## 12. Evaluation gaps

`[CODE]` `olbrain-agent-eval@6c289ca`, runtime `daee3f9`.

- **The harness cannot exercise memory.**
  - It sends no `user_id` (`agent_eval/chat/runtime_client.py:94-116`).
  - `RunSpec` forces `brain="draft"` for chat and research (`core/run_spec.py:71-89`).
  - The runtime returns early when `not is_production` (`lightweight_processor.py:4144`).
  - Every conversation is a single session, with no multi-session concept (`chat/chat_session.py:56,109`).
  - Research evals blank `memory.fields` (`scripts/provision_research_agent.py:265-266`).
- **The harness runs against production.** The runtime URL is hardcoded (`deploy-prod.yml:105`) and `ARCHITECTURE.md:12` says "Prod-only". Eval sessions therefore write to production session and message stores, tagged by `metadata.source`.
- **Tests check plumbing only.** Every extraction test uses a canned `FakeProvider` (`tests/test_agent_memory_service.py:124-133`), and no test runs the real prompt.
- **Telemetry is almost absent.**
  - Metrics are stubbed out (`core/metrics.py:2`).
  - A failed extraction, a no-op, and every read hit or miss are silent.
  - `[generate_json.usage]` has no feature label.
  - `billing_client.ALLOWED_FEATURES = {"agent_runtime","dispositions"}` drops `user_memory` (`services/billing_client.py:43-46,89-94`). The meter path via `OLBRAIN_LLM_SEAM_ENABLED` defaults to false, and its production value is `[UNRESOLVED]`.
- **Correction to an earlier artifact:** `new-repo-inventory-closure.md` §3 says `agent_qa_runs` has no org field. **CONTRADICTED BY SOURCE**: `org_id` is stamped at create time (`app/run_store.py:95`).

---

## 13. Required invariants for a high-quality memory system

Each invariant is `[DERIVED]` from the brief's standard and the contract. The failures each one closes are listed after it.

- **M1. Grounded writes.** Every memory item cites evidence: a message id plus a quote. The quote must occur in **user-authored or trusted-tool** content of that turn. Agent output is never evidence for a claim about the user. *Closes F8, F9, F27, F28.*
- **M2. No destruction by omission.** Items change only by explicit add, supersede or retract operations. Nothing disappears because a model left it out. *Closes F1, F2, F12, F30.*
- **M3. Supersession, not overwrite.** A replaced item stays queryable as history, with `valid_until` and `superseded_by`. *Closes F3, F4, F7.*
- **M4. Kind is recorded.** Each item is marked `stated`, `inferred`, `operator`, `imported` or `legacy`. Only `stated`, `operator` and allowed `imported` items render as facts; `inferred` items render labelled as inference. *Closes F27.*
- **M5. Authority per predicate.** User statements cannot establish security, role, billing or entitlement predicates (contract §5 and Example 12). *Closes F10.*
- **M6. Serialised, idempotent writes per subject.** Writes are idempotent per inbound message, and a stale read cannot overwrite a newer write. *Closes F18, F19, F21.*
- **M7. Generation-checked writes.** A write captures the subject's deletion generation and is rejected if the generation changed (contract §10). "Forget me" leaves a tombstone. *Closes resurrection.*
- **M8. Complete erasure by subject.** One erasure enumerates every store holding the subject's content: ledger, projection, entries, sessions, messages, summaries, learned-pattern samples, `agent_users`, `lead_*`, and backups per policy. *Closes F17.*
- **M9. Isolation on every read row.** Each read asserts the org, and visibility per PI-8, on every row, not only on the query. *Closes F13, F15.*
- **M10. Dated, labelled, budgeted context.** Every rendered item shows its date and kind. The layers are Current State, Memory, Narrative and history. They have fixed precedence and one shared token budget. *Closes F3, F24, F25, F26.*
- **M11. Failure is not absence.** A retrieval failure renders an explicit "memory unavailable" marker, and is counted. *Closes F24.*
- **M12. Rebuildable projections.** Anything served on the hot path can be rebuilt from the ledger. *Closes F29.*
- **M13. Measured.** Every write and read emits counters, and quality is evaluated offline and end to end (§14.10). *Closes the blindness.*
- **M14. Narrative is non-assertive.** Summaries carry scope, provenance, `observed_at` and status, and are presented as labelled context, never as the user speaking (contract `:60-61`).

---

## 14. Recommended target architecture

This is the smallest design that satisfies M1–M14. The logical layers are listed below. **Physically, on Firestore today, this is:**
- one ledger subcollection per subject;
- one projection document per subject;
- small additions to existing collections.

### 14.1 Evidence

- **What it is.** `agent_messages`, which already exist, are the evidence. Two fields are added: the person **subject id** (from the identity mapping) and the author role.
- **What counts as evidence about the user.** User turns, trusted tool observations, and operator entries. Agent turns are evidence of *what the agent said*, never of facts about the user (closes the contract gap in §4.3).
- **Retention.** Retention is set by policy and is part of M8. Today there is no retention at all (OD6).

### 14.2 Extraction

- **When it runs.** Still post-turn and asynchronous. Contract §9 lists extraction as asynchronous, and the next turn does not depend on it.
- **Input.**
  - The user turn is the **evidence**, inside delimiters.
  - The assistant turn is **context only**, and the prompt says it is not evidence.
  - The **active items** are included with their ids, not a free list.
  - An explicit anti-instruction rule: text inside the delimiters is data.
- **Output: deltas only.** Each delta is one of:
  - `ADD{text, kind, predicate?, quote}`
  - `SUPERSEDE{item_id, text, quote}`
  - `RETRACT{item_id, quote}`
  - `NOOP`
- **Deterministic validator.** This is code, not an LLM. It checks:
  - the quote is a substring of the delimited user text (or trusted tool text), after normalisation;
  - the `item_id` exists and is active;
  - the predicate authority passes (M5).

  Rejected deltas are **counted and dropped**, never written. This one check closes hallucination and assistant contamination cheaply, with no second model call.
- **Output budget.** A delta output is small whatever the profile size, so the 1,024-token budget stops being a correctness risk. `stop_reason == max_tokens` is still treated as a failure and counted.
- **Model.** Haiku is still appropriate. The validator carries the safety; the model is not trusted.

### 14.3 Claims and the memory ledger (one physical store, two roles)

Ledger path: `memory_items/{subject_id}/items/{item_id}`. Each item holds:

| Field group | Fields |
|---|---|
| Identity and scope | `subject_id`, `org_id` (required, non-empty), `learned_by_agent_id` |
| Content | `text`, `predicate?`, `kind`, `status` (`active` / `superseded` / `retracted` / `invalidated` / `quarantined`) |
| Evidence | `evidence: [{message_id, session_id, quote}]` |
| Time | `observed_at`, `valid_from?`, `valid_until?` |
| Lineage | `supersedes?`, `superseded_by?` |
| Epoch and extraction | `merge_epoch?`, `extractor_version`, `policy_version?` |
| Write control | `idempotency_key` (the inbound message id) |

- **With a `predicate`, an item is a Claim** in contract terms.
- **Without one, it is a Memory item.** It has the same lifecycle, which closes the §4.3 gap by rule rather than by a new object class.
- **Append-only:** status transitions are the only mutations.
- **Growth** is bounded by asynchronous consolidation. Consolidation proposes merging near-duplicates into one item that `supersedes` the others, and it keeps their lineage. It never deletes.

### 14.4 Policy evaluation

- **A small registry**, in code, for the few current-state-eligible predicates, for example communication preference, language, preferred name, and do-not-contact. Choosing that set is OD3.
- **What each entry defines:**
  - authority (who may establish the value);
  - cardinality;
  - whether a statement from the user is authoritative.
- **Everything else is Memory**, with no current-state claim. This avoids building a full registry of unknown size.

### 14.5 Current-state projection

- **How a slot resolves.** The resolver takes the active, valid Claims per subject and predicate, then applies the policy.
- **Conflicts.** Two authoritative values that disagree give `CONFLICT` (§6), and R2 applies over a merged member set.
- **Consent.** `opt-out` and `do-not-contact` are synchronous state mutations (contract §9, "explicit immediate directives"). They are **not** extracted.

### 14.6 Long-term memory and Narrative Memory

- **The long-term memory** is the active ledger items.
- **Session summaries become Narrative Memory.** Each summary is a document carrying `{session_id, message range, generated_at, generator_version}`. It is presented to the model as labelled context (M14), and it is included in erasure.
- **Episode boundaries for never-ending sessions (OD1).** On WhatsApp, Instagram and Slack, an idle gap starts a new episode. The history window is then bounded to the current episode, and earlier episodes survive as Narrative Memory plus ledger items. That keeps the history without letting unbounded raw history act as shadow memory.

### 14.7 Hot-path read: one projection document

- **What it is.** `memory_head/{subject_id}` holds everything the hot path renders:
  - the current-state slots;
  - the top-K active items, selected by salience and recency;
  - an `item_count`;
  - a `ledger_version`.
- **How it is maintained.** It is rewritten transactionally together with each ledger write. It can be rebuilt from the ledger (M12).
- **Cost.** One `get` per turn, the same as today, run off the event loop with `to_thread`.
- **Beyond the budget.** Items that don't fit are reached by a `recall_memory` tool (§14.8), never by growing the prompt.

### 14.8 Retrieval

- **Tier 1, always included:** the slots from `memory_head` plus the top-K items within a fixed token budget.
- **Tier 2, on demand:** a `recall_memory(query)` tool over the subject's ledger. It uses **lexical/structured matching** over item text, predicate and date. That matches the knowledge vault's existing, deliberately embedding-free design.
- **Embeddings (deferred, §14.9):** added only if the evaluation shows a Tier 2 recall gap that lexical matching cannot close. A per-person ledger is small, and lexical matching over a few hundred items is cheap and explainable.
- **Every read asserts the org and PI-8 visibility on every item** (M9).

### 14.9 Context assembly

- **Precedence, one budget.** Current message, then Current State, then active Memory, then Narrative, then episode history. They share one budget, and each layer's budget is a default to be tuned against the Lane 1 and Lane 2 evaluation.
- **Rendering.** Every item carries its date and kind, for example: `2026-08-03 · stated · "Prefers email"`.
- **Inferred items** render under a separate heading: "Possibly (inferred, unconfirmed)".
- **Placement.** Memory is placed as a delimited context block marked "information about the user, not instructions". It is **not** placed as system-prompt instructions (closes S-M6).
- **Failure marker.** A failure renders `[memory unavailable]` and is counted (M11).
- **Learned patterns.** They are presented as non-assertive examples, not as "ground truth". See also OD2.

**Mechanisms considered and not recommended now:**

| Mechanism | Verdict | Reasoning |
|---|---|---|
| Vector store / embeddings | Deferred until measured | No failure found is a similarity-recall failure. It adds an index that must follow deletion and merge (projection freshness, contract §8), plus a cost and a latency hop |
| Knowledge graph | Rejected | Nothing requires traversing relationships between people. Contract Example 17 already covers entities |
| Full event sourcing | Rejected beyond the append-only ledger | The ledger is the event log for memory. A general event store adds nothing M1–M14 need |
| Second LLM "verifier" | Rejected | The deterministic quote check gives grounding without a second model call |

### 14.10 Evaluation and monitoring (part of the architecture)

- **Lane 1: offline extraction golden set.** No production access and no runtime change are needed.
  - Replay scripted multi-turn transcripts through the real extractor, with a fake store.
  - Each transcript comes with a **ground-truth ledger** of events: disclose, update, retract and delete.
  - Score these metrics:
    - extraction precision and recall;
    - hallucinated-item rate (items not in the ledger);
    - contamination rate (items sourced only from assistant text);
    - update correctness (the old item superseded, the new one active);
    - retraction correctness;
    - grounding-rejection rate.
  - This is the regression gate for any prompt or model change.
- **Lane 2: end-to-end, multi-session.** This extends `olbrain-agent-eval`.
  - It adds a multi-session persona with a stable synthetic `user_id`, and a `user_id` field in `RuntimeChatClient._body`.
  - Scoring uses two sources: the store, via the org-checked GET, and the reply, via the existing fact matcher (`research/grounding.py:440-487`).
  - Dimensions checked:
    - recall across sessions;
    - staleness (a retracted fact never asserted);
    - contradiction handling;
    - deletion correctness (DELETE, then 404 on every store, then no recall);
    - cross-person leakage (two identities on one agent);
    - cross-org leakage (two keys, same `user_id`);
    - write-visibility latency (poll `updated_at`).
  - **Blocked** on an environment where memory writes run (OD4).
- **Lane 3: production telemetry.**
  - **Counters per extraction:**
    - attempted, succeeded, failed-parse, truncated (`stop_reason`), empty, no-op;
    - deltas proposed, accepted and rejected, by reason.
  - **Counters per read:** hit, miss, error, and block tokens.
  - **Latency:** write latency (turn end to ledger commit) and read latency.
  - **Cost:** fix `ALLOWED_FEATURES` or confirm the seam, so extraction cost is metered.
  - **Provenance coverage:** the fraction of active items that have evidence. Legacy items count as 0 until they are replaced.

---

## 15. Migration strategy from the current implementation

Each phase is shippable on its own and reversible. `[DERIVED]`

1. **Phase 0: measure.**
   - Add Lane 3 counters and fix billing metering.
   - Build the Lane 1 golden set.
   - Record the current baseline, including the rates of `completion_tokens` against the budget and of `[]` wipes.
2. **Phase 1: stop the bleeding, in place (§16).**
3. **Phase 2: dual-write the ledger.**
   - The extractor switches to deltas and the validator.
   - It writes ledger items and the `memory_head`.
   - It **also regenerates the legacy `facts[]` from the head**, so the read path is unchanged.
   - Backfill: each existing fact becomes an item with `kind=legacy`, **no evidence**, and `observed_at` set to the document's `updated_at`. That follows D1(a): un-provenanced, never presented as stated.
4. **Phase 3: switch reads.**
   - P1 renders from `memory_head` with dates and kinds.
   - The legacy `facts[]` is frozen, then removed.
   - Summaries move to Narrative Memory documents, and episode boundaries are applied.
5. **Phase 4: Memory Gateway and PostgreSQL.**
   - Ledger items map one to one onto Claims and Memory rows, and `memory_head` becomes a projection.
   - Subject ids come from the identity mapping (PI-11). Until then, the subject is the existing `(agent, key)` digest, **re-pointed** when the mapping lands. Memory documents are re-keyable from their plaintext `channel_user_id` (council verdict §8).

The in-flight Stage-2 `fill` migration should complete or be abandoned **before** Phase 2. It is a separate unfinished migration on the same document, and its version labels are unreliable (§4.1).

---

## 16. What can be improved immediately, without PostgreSQL

These are recommendations only. Nothing was changed. Each is small and local to the runtime.

1. **Treat `[]` as failure** unless the prior list was empty, or unless every removal is justified. As a minimum, refuse a write that removes more than N facts in one turn, and log it.
2. **Check `stop_reason`.** Treat `max_tokens` as a counted failure. Raise the output budget until Phase 2 removes the problem.
3. **Remove `assistant_text` as evidence.** Keep it as delimited context with an explicit "not about the user" rule, and delimit the user text with an anti-injection rule.
4. **Add an idempotency and precondition check.** Store `last_inbound_message_id`, and skip if it was already processed. Wrap the read and write in a Firestore transaction on the memory doc. The LLM call stays outside the transaction; a re-read inside it aborts if `updated_at` moved. This gives optimistic concurrency.
5. **Add a deletion tombstone.** A `forgotten_at` / generation field that extraction checks inside the same transaction. Delete then sets the tombstone rather than removing the doc, so resurrection stops.
6. **Cascade the memory DELETE to the matching `agent_datastores` entries.** They share the same digest (storage audit §11).
7. **Align the read and write gates.** Stop writing what is never read: extract-only agents, and anonymous session keys unless they are read.
8. **Render dates.** Show `updated_at` per document now, and per item after Phase 2. Stop stripping `ts` from history for memory-relevant turns, or render the episode date.
9. **Render failure as failure** (M11), with counters.
10. **Move P1/P2 `.get()` into `to_thread`,** as the write path already does.
11. **Learned patterns:**
    - add an `org_id`;
    - stop storing verbatim user messages, or bring them into erasure;
    - change "ground truth" to non-assertive wording.
12. **Fix the S-M1 tenant check** on `agent_users` update and delete.

---

## 17. What requires the future Memory Gateway

These need a single write authority across stores, or cross-agent or identity semantics:
- memory shared across agents (Q5, PI-8);
- the identity mapping, merge and undo with epoch quarantine (PI-3–PI-7);
- erasure across stores by subject, including backups policy (M8, PI-9);
- the predicate registry and current-state slots with OCC (§14.4–14.5), and the move to PostgreSQL;
- a single evidence log with a subject id on every message, stamped at ingress;
- transfer re-keying (PI-10).

---

## 18. Open decisions

| # | Decision | Why it is not derivable | Owner |
|---|---|---|---|
| OD1 | Episode boundary for sessions that never end (WhatsApp, Instagram, Slack): the idle gap length, and whether raw history outside the episode is still offered | A product trade-off between continuity and shadow memory | Product + Jay |
| OD2 | Whether agent-wide learned patterns may hold customer content at all | An aggregate derived from customer contributions, so contract §10 `:796-824` applies (G5 dataset classification) | Legal / G5 |
| OD3 | The v1 set of current-state-eligible predicates | It defines the registry's scope | Architecture + Product |
| OD4 | The environment for Lane 2 evaluation. The options: (a) a production eval org in production mode, with cleanup; (b) memory writes in TEST mode to a separate namespace; (c) a non-production runtime | All three have cost or safety trade-offs, and none exists today | Engineering + billing owner |
| OD5 | Whether inferred items are stored (labelled) or dropped | The recommendation is to store them labelled and render them under "Possibly", but it is a product choice | Product |
| OD6 | Retention of raw evidence (messages): kept forever today | Legal retention class | Legal |

---

## 19. Assumptions rejected or falsified

| Assumption | Verdict | Evidence |
|---|---|---|
| "Operator edits to `agent_user_memory` get overwritten by the extractor" | **Falsified.** No operator edit path exists | `routers/agent_memory.py:48,88`; rules `write: false` |
| "Deleting memory makes the agent forget" | **Falsified.** History, summaries and learned patterns persist | §8.2 |
| "Memory is per person" | **Falsified.** It is per (agent, raw channel key), plus session-keyed rows | `agent_memory_service.py:92-97`; `lightweight_processor.py:4152-4158` |
| "Anonymous sessions never read or write memory" (module docstring) | **Contradicted.** They are written, and not read | `agent_memory_service.py:14-16` vs `lightweight_processor.py:4150-4156` |
| "The Studio Memory tab reads through studio-backend" | **Contradicted.** Noesis reads Firestore directly | `firestore.rules:635-643` |
| "Migration deleted the map from every document" | **Unproven.** The recorded dry run made zero writes | `migrate_extract_rows.py` header |
| "App code stamps `expires_at` on sessions" (TTL IaC) | **Contradicted.** No writer exists | §10 |
| "`agent_qa_runs` has no org field" | **Contradicted.** `org_id` exists | `app/run_store.py:95` |
| "The 30-fact cap is the binding limit" | **Doubtful.** The 1,024-token output budget likely binds first | §5 `[INFERENCE]` |
| "Memory quality is tested" | **Falsified.** Only plumbing is tested, with a canned provider | §12 |
| "Memory needs vectors or embeddings" | **Rejected for now** | No failure found is a similarity-recall failure (§14.9) |
| "Council C1 copy-on-first-write is needed for memory undo" | **Superseded.** The ledger's per-item epoch already provides it | §11 |
| "Voice turns use person memory" | `[UNRESOLVED]`. Per a runtime comment, voice has no caller id | §6 |

---

## 20. Source map

`origin/main` SHAs:

| Repo | SHA |
|---|---|
| `olbrain-agent-runtime` | `daee3f9` (local HEAD `b2401a0` is stale) |
| `olbrain-agent-eval` | `6c289ca` |
| `olbrain-agent-design` | `c56271d` |
| `olbrain-studio` | `1f05ca11` |
| `olbrain-studio-backend` | `5da93ae` |
| `olbrain-shared` | `d0e0d2b` |
| `olbrain-agent-engine` | `dfc3a47` |
| `olbrain-workflow-runtime` | `2356de0` |
| `olbrain-research-runtime` | `6b81691` |
| `olbrain-knowledge-vault` | `25b46be` |

| Topic | Primary source |
|---|---|
| Extractor, cap, delete | `runtime:services/agent_memory_service.py:38-65,92-97,129-159,276-529` |
| Trigger and gates | `runtime:core/lightweight_processor.py:1419-1464,4025-4203` |
| JSON call, no `stop_reason` check | `runtime:core/llm_providers/anthropic_provider.py:4570-4700` |
| Entry writer | `runtime:services/extract_entry_writer.py:46-100` |
| Prompt assembly | `runtime:core/cs_packet_builder.py:611-1244,1426-1981,1983-2078,2133-2222` |
| Summariser | `runtime:core/session_summarizer.py`; `lightweight_processor.py:3864-3994` |
| Deterministic sessions | `runtime:routers/meta_whatsapp.py:719`; `meta_instagram.py:203`; `slack.py:140` |
| Learned patterns | `runtime:core/learning/pattern_store.py:64-70`; `core/firestore_schemas.py:352-375` |
| Memory API | `runtime:routers/agent_memory.py:33-116` |
| Metrics and billing | `runtime:core/metrics.py:2`; `services/billing_client.py:43-94` |
| Rules | `studio:firestore.rules:635-643,692-695` |
| Datastore edit | `agent-design:app/routers/datastore.py:111-140,206-292`; `app/services/datastore_service.py:480-505` |
| `agent_users` edit/delete | `agent-design:app/routers/agent_user.py:48-85`; `app/services/agent_user_service.py:95-160` |
| Migration | `agent-design:scripts/migrate_extract_rows.py:509-556` |
| Eval | `agent-eval:agent_eval/chat/runtime_client.py:94-128`; `core/run_spec.py:71-89`; `chat/chat_session.py:56,109`; `app/run_store.py:95` |
| Knowledge retrieval | `knowledge-vault:services/dci/fts_index.py:4-8` |
| Contract | `artifacts/architecture-contract.md` §1 `:18-68`, §2 `:140-173`, §4, §5 `:423-450`, §9 `:694-733`, §10 `:734-824`, rules `:996-1007`, Ex. 11–12 `:1190-1219` |

**Missing repositories:**
- `olbrain-noesis-os`: the operator memory UI and BFF.
- `olbrain-voice-gateway`: voice caller identity.
- `olbrain-llm` and the billing service: the metering sink.
- Production infrastructure IaC for `olbrain-india-prod`: TTL, PITR and backups.
