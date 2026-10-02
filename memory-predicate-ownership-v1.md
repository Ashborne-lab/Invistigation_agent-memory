# Predicate Ownership v1 (Lane A, A6)

**Date:** 2026-10-01.

**Classification.** The current-state columns are **VERIFIED CURRENT** at `origin/main`. The target columns are **TARGET ARCHITECTURE**.

**Evidence.** Read-only trace of these repositories:

| Prefix | Repository | Commit |
|---|---|---|
| R | agent-runtime | `daee3f9` |
| AD | agent-design | `c56271d` |
| SB | studio-backend | `5da93ae` |
| SH | shared | `d0e0d2b` |
| RR | research-runtime | `6b81691` |
| WR | workflow-runtime | `2356de0` |
| EN | agent-engine | `dfc3a47` |

**Inputs:** `memory-architecture-v2-red-team.md` (RT C-6 / R-6), `memory-ecosystem-map.md` (MAP).

**Goal.** No important person attribute has two competing *semantic* owners. Where an attribute is genuinely two different things that today share a name, it is **split**, and the boundary is marked. It is not forced into one owner.

## 1. Owner classes (target)

| Owner | Owns | Write path | Read path into prompts |
|---|---|---|---|
| **IDENTITY** (identity authority: Firestore bindings plus `identity_events`, RT C-1a) | Channel identifiers, verified contact points, assurance, merges | Channel metadata; signed tokens; operator identity console | **Never as raw values.** The prompt gets a handle-scoped `contact_on_file: yes/no` and channel type only |
| **MEMORY** (Memory Gateway, claims) | What the person told us, or what was confirmed: preferences, attributes, history, intents, commitments | The gate (LLM proposes) or typed commands | `compile_context` T0/T1 |
| **LEAD** (lead engine, operational) | Pipeline status, stage vocabulary, assignment, activity log | Operator; system default | Lead tools return status only |
| **CONSENT** (consent ledger, typed) | Opt-out, do-not-contact, memory consent | User keyword; operator; erasure (suppression HMAC) | T0 consent slot |
| **ANALYTICS** (pseudonymous) | Session judgements: sentiment, disposition, goal outcome, closing summary | Judges, through the derivation fence (R-6) | **Never in customer prompts** |
| **NARRATIVE** (Gateway, non-assertive) | Episode recaps | One writer, from evidence | Off by default (R-25) |
| **WORKFLOW** (engine) | Item and trigger data | Workflow engine | Step templates, from declared fields only |
| **AGENT KNOWLEDGE** (Gateway, aggregate) | Cross-user guidance | Learners: candidate, then approved | T4, approved items by id only |

## 2. Attribute table

★ = two or more competing writers today. "Prompt paths" uses the agent's labels P1–P5 and T1 (§4).

| # | Attribute | Current stores and writers (count) | Current prompt readers | Target owner and scope | Authoritative source | Derived and non-authoritative | Migration disposition | Prompt paths that must change |
|---|---|---|---|---|---|---|---|---|
| 1 | **Channel identifier** (phone on WA/IG, `user_id` on webhook, Slack id, email thread) | Session `user_id`/`phone_number`, doc ids `{phone}-{agent}`, `agent_users.channel_user_id`, memory doc `channel_user_id`, datastore entry `channel`, lead `channel`, `documents.shared_with[]`. ★2 writers on session `user_id` (create R `agent_webhook.py:2533`; migrate `:2305`) | **P3** "Current user", raw id (R `cs_packet_builder.py:2087-2131`). It is also the key for P1/P2 | **IDENTITY**: binding per (org, channel, identifier, assurance) | Channel metadata (WA, IG, Slack); signed end-user token; webhook = `asserted` | Session copies; memory/datastore keys | Keys become opaque `subject_id` (P3 from RT). Raw ids leave doc ids. Identity migration (`:2305`) becomes an identity event that moves memory too (today it re-keys the session only) | **P3**: stop injecting the raw id; inject channel type plus assurance. P1/P2: key by handle subject |
| 2a | **Display name on record** (channel or CRM name) | Session `profile_name` (Meta, R `meta_whatsapp.py:728`); `agent_users.display_name` (upsert `firebase_service.py:309`; operator AD `agent_user_service.py:112`); voice `caller_name`; session `metadata.user_name`. ★ | Voice grounding (`voice_grounding.py:254-257`, gateway-dependent) | **IDENTITY**: an identity attribute with provenance (channel, operator, CRM) | Channel metadata; operator | — | Upsert must stop overwriting operator values (today it overwrites on every inbound message, `firebase_service.py:309-313`) | Voice grounding reads identity only |
| 2b | **Name the person told us / how to address them** | Facts (Haiku, R `agent_memory_service.py:405`); datastore name columns (extractor plus operator); lead `fields.name` (LLM tool `lead_capture_tool.py:528`, CSV); session `user_name` (Gemini fill-blanks `agent_webhook.py:770-781`; backfill script). ★ ≥10 | P1, P2 | **MEMORY**: `person.preferred_name` (SINGLE, PERSON scope) | User-stated, or confirmed through the gate | Gemini `user_name` capture (**retire**; it is also a subprocessor path, A5 §4.4) | Legacy facts and datastore name values import as `legacy` (never current). The Gemini capture is retired | P1/P2 replaced by `compile_context` |
| **Boundary 2a/2b** | These are **two attributes**: what the channel or CRM says the name is, and what the person asked to be called. They stay separate, because merging them is how an operator-set name gets overwritten by an LLM guess | | | | | | | |
| 3 | **Phone** | Session `phone_number` (Meta), `user_phone` (LLM only), `agent_users.phone_number` (upsert, directives, operator), lead `contact_phone`, `lead_contacts`, datastore, facts, voice `caller_number`, `session_name`. ★ ≥8 | P3 (as identifier), voice grounding, P1/P2 (in facts) | **IDENTITY** (a contact point with assurance). **Never a memory key** (policy `contact.phone` is FORBIDDEN by default; PI-3) | Channel (WA verified); operator; CRM | LLM-extracted `user_phone`: at most an `asserted` candidate | `user_phone` retired. Lead `contact_phone` becomes an identity input (lead stays the operational owner of *contact records*, not of identity) | P3 and voice grounding: handle-scoped `phone_on_file` only. Facts must not carry phones (the gate forbids `contact.*`) |
| 4 | **Email** | Session `user_email` (metadata, LLM, backfill, transfer patch), `agent_users.email`, lead, datastore, facts, email `from_email`. ★ ≥8 | **Email channel instructions inject raw `from_email` with no PII-policy check** (R `email_instructions.py:25-26`, via `cs_packet_builder.py:2726-2731`) | **IDENTITY** (verified only with DMARC alignment, RT M-5) | Channel (DMARC-aligned); operator; CRM | LLM `user_email`: an asserted candidate | Same as phone | **Email instructions: gate them on the PII policy** (VERIFIED CURRENT gap, flag it for the PII owner) |
| 5 | **Open business attributes** (company, interest, product, budget, city, age, income, callback time…) | Lead `fields{free key}` (LLM tool, CSV); datastore extract columns (extractor, operator); facts. ★ 3–4 per attribute, **no shared schema** | P2 (datastore values), P1 (facts). Lead fields never reach prompts | **Split by meaning:** person preferences and attributes → **MEMORY** (registered keys or namespaces); pipeline-qualifying fields (budget, product interest) → **LEAD** (operational record), visible to memory only by reference | Memory: user-stated through the gate. Lead: the lead tool (user-stated, `stated-only` rule) or operator | Extractor datastore rows (today they overwrite operator edits) | Datastore extract columns become **declared memory predicates** (the operator-declared list is the policy registry input). Lead fields stay in LEAD. Facts become `legacy` | P2 is replaced by T0/T1. **The `Details worth collecting` declaration (`cs_packet_builder.py:367-409`) becomes the agent's `memory_profile`** |
| **Boundary 5** | Whether a given open field is "memory about the person" or "lead qualification" is **per-org product configuration**. The architecture provides both owners and requires every declared field to name exactly one. `[BLOCKED:Product]` per field type; default: declared datastore columns → MEMORY, lead tool keys → LEAD | | | | | | | |
| 6 | **Lead stage / status** | `lead_contacts.status` (system default `new` `lead_contacts.py:476`; operator `lead_admin.py:253-309`) | T1 tool returns status | **LEAD** (already a single owner) | Operator | — | Unchanged. Reference it from memory; never copy it | None |
| 7 | **Last contact / recency** | `lead_contacts.refs[].last_contact_at`, `agent_users.last_seen_at…`, memory `last_session_id`, session `last_message_at` (4 notions) | T1 | **Derived** (projection over evidence), never stored as truth | Evidence timestamps | All four copies | Compute from `evidence_meta`. The copies become caches with a declared source | T1 reads the projection |
| 8 | **Free-form durable facts** | `agent_user_memory.facts[]` (Haiku, full-list replace; reads assistant text) | **P1** | **MEMORY** (typed claims; open namespaces for the rest) | User-stated through the gate | — | Import as `legacy`, unverified, never current (v2 §S) | P1 is replaced |
| 9 | **Declared attributes to collect** (declaration, not value) | `resources.datastores[].spec` (AD `datastore_compile.py:301-344`); legacy `agent.memory.fields/sets` | "Details worth collecting" | **MEMORY policy** (`memory_profile` plus the per-org predicate registry) | Operator | — | Compiled into the policy registry at publish | Prompt says what to *ask for*. The gate allow-list comes from the same declaration |
| 10 | **Conversation summary** | `agent_sessions.summary`, ★2 writers (rolling summariser `session_summarizer.py:74`; insights `agent_webhook.py:427,562`) | **P5**, as a *user-role* message, **no PII gate** | **NARRATIVE**: one writer, from evidence, non-assertive | Evidence | Both current writers retire | Not migrated. Regenerated | P5 is removed. T3 is off by default (R-25) |
| 11 | **Sentiment** | `sentiment_score` (Gemini full `:656`; blend `:1076`), `sentiment_analysis` (writer present, no invocation found). ★2 | None (drives session status) | **ANALYTICS**, pseudonymous | Judge (fenced, R-6) | — | Key moves to a pseudonymous session ref | None (must never enter prompts) |
| 12 | **Goal outcome / closing summary** | ★3 writers with **three vocabularies** (`agent_webhook.py:1996`, `:2173`; `lightweight_processor.py:4467`) | None | **ANALYTICS**. One enum, versioned | Judge | Farewell text (not an outcome) | Split `closing_summary` (judge text) from `farewell_text` (agent output = evidence). Normalise the enum | None |
| 13 | **Disposition** (+ taxonomy) | Live classifier `lightweight_processor.py:4303`; backfill `disposition_backfill.py:180`; taxonomy `agent_disposition_taxonomy` | None | **ANALYTICS** (the label). The taxonomy is **AGENT KNOWLEDGE** (lineage, k, no verbatim) | Classifier over the operator taxonomy | — | Taxonomy candidates: lineage added or retired | None |
| 14 | **Consent / opt-out** | `agent_users.opted_out_at/opt_out_source` (inbound STOP `outreach_optout.py:229`; operator SB `outreach_optout_service.py:189`) | None (enforced in directives `[UNRESOLVED]`) | **CONSENT** (typed). Survives erasure as a keyed HMAC suppression (`[BLOCKED:Legal]`, default keep) | User keyword; operator | — | **Today, deleting the `agent_users` row drops the opt-out** (A5). Move to the consent ledger before any erasure handler runs on `agent_users` | T0 consent slot |
| 15 | **`agent_users` status / notes** | Upsert resets `status:"active"` on every inbound message (`firebase_service.py:305`); operator AD `:118,120`. ★ | None | **LEAD**/operator console (operational) | Operator | — | The upsert must stop writing status (VERIFIED CURRENT defect) | None |
| 16 | **Language / locale / timezone** | **No typed field.** Voice `[[LANG:]]` per turn from the gateway; otherwise facts or datastore text | Voice LANG directive (`channel_profiles.py:96-106`) | **MEMORY**: `preferred_language` (SINGLE, volatile; exists in the prototype registry). Per-turn channel language stays a **turn signal**, not memory | User-stated or confirmed | Gateway `[[LANG]]` (turn-scoped; **never** a claim) | New predicate | T0 renders `preferred_language` |
| **Boundary 16** | "The language this turn is in" (channel signal) ≠ "the language the person prefers" (memory). Collapsing them makes one Hinglish message rewrite a stated preference | | | | | | | |
| 17 | **Channel / how reached** | Session `channel` (caller metadata), voice transport | Channel profile blocks | **Evidence attribute** (per message), not a person attribute | Channel | — | — | Unchanged |
| 18 | **Cross-user learned content** | `agent_learned_patterns` (verbatim user messages) | `recall_learnings`, "ground truth" | **AGENT KNOWLEDGE** | Learner, through the gate (k, PII check) | — | Quarantine, then re-derive (v2 §S) | Replaced by T4 guidance (approved only) |
| 19 | **Directive instruction** | `message.metadata.directive` (agent-directives `[UNRESOLVED]`) | `cs_packet_builder.py:2208-2236` | **Operator config / evidence** (operator role), never memory | Operator or campaign | — | `[UNRESOLVED: missing repository]` | It is an instruction source: platform/owner tier only (RT §P.4) |
| 20 | **Workflow person fields** | `trigger_payload.*`, items (undeclared) | `{{trigger.X}}` templates (SH `step.py:489`) | **WORKFLOW** (operational). Memory only by reference | External system | — | Declare the person fields in the workflow schema so the registry can find them (A5) | Templates render declared fields only |

**Org-member attributes** (RT C-7, MEMBER class):
- Names and emails in `user_profiles` and members are owned by **IAM**.
- Research team preferences (`learned/*`, with uid contributors) are owned by **AGENT KNOWLEDGE**, at template scope with lineage.
- The R script `backfill_operator_session_identity.py:50-80` copies **operator** identity onto **end-user** session fields. This is a category error: an org member's PII lands in an end-customer's session record. **Retire it.** `[CODE]`

## 3. Attributes with competing owners today, and the resolution

| # | Attribute | Competing writers today | Resolution |
|---|---|---|---|
| 1 | Name | ≥10 writers | Split into 2a IDENTITY and 2b MEMORY. Retire the Gemini fill-blanks and the operator backfill |
| 2 | Phone / email | ≥8 each | IDENTITY only. LLM-extracted values become `asserted` candidates. Facts may not carry them (gate) |
| 3 | `agent_users` fields | Upsert vs operator | The upsert stops overwriting operator-owned fields and `status` |
| 4 | Goal outcome / closing summary | 3 writers, 3 vocabularies | One ANALYTICS enum; the farewell is evidence |
| 5 | Session summary | 2 pipelines | One NARRATIVE writer |
| 6 | Sentiment / disposition | 2 writers each | ANALYTICS, one writer each, fenced |
| 7 | Session `user_id` | create vs migrate | Identity event; memory moves with it (today it does not) |
| 8 | Open business fields | lead `fields`, datastore columns, facts | Each declared field names exactly one owner (MEMORY or LEAD). `[BLOCKED:Product]` on classification; default as in row 5 |

**Single-owner today (keep as is):** lead status (human-owned) and opt-out (provenance-tagged). They are correct, but in the wrong store for erasure purposes.

## 4. Prompt paths that must change

| Path | Today | Target |
|---|---|---|
| P1 facts (`cs_packet_builder.py:1957-1981`) | Untyped facts | `compile_context` T0/T1 through a handle |
| P2 person records (`:1983-2078`) | Datastore values, keyed by raw-id hash | Same |
| P3 current user (`:2087-2131`) | Raw identifier | Channel type plus assurance; no raw id |
| P5 summary (`:1665-1737`) | User-role message; no PII gate | Removed (T3 is off by default) |
| Email instructions (`email_instructions.py:25-26`) | Raw `from_email`; **no PII gate** | PII-gated; identity is handle-scoped |
| Voice grounding (`voice_grounding.py:197-262`) | Raw caller number and name | Identity attributes with assurance (ANI = `asserted`, RT M-5) |
| `recall_learnings` | Verbatim cross-user messages, "ground truth" | T4 approved guidance only |
| Workflow templates (`step.py:489`) | Undeclared `{{trigger.*}}` | Declared fields only |
| Judges (`disposition_service.py`, `close_judgment_service.py`, identity capture) | Summary and history to secondary LLMs | Fenced derivation; identity capture retired |

## 5. Unresolved items

- `title` writer; Noesis readers of `user_name`/`profile_name`; directive content; voice gateway `metadata.voice`: `[UNRESOLVED: missing repository]` (noesis-os, voice-gateway, agent-directives).
- `olbrain_usage_shared` event-id format: `[UNRESOLVED: missing repository]`.
- The body of the `_generate_sentiment_for_session` prompt was not fully re-read `[UNVERIFIED]`.
