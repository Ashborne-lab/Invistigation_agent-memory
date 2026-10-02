# OLBrain Memory Architecture v2: platform memory subsystem

**Date:** 2026-09-30. **Status:** architecture package (design), not implementation.

**Classification:** TARGET ARCHITECTURE. Nothing in this document is VERIFIED CURRENT. Current-state claims are cited to the MAP and to the existing investigation documents.

**What this supersedes and what it builds on.**
- It supersedes the per-feature memory designs where they conflict.
- It keeps and builds on:
  - the contract (`artifacts/architecture-contract.md`);
  - the settled identity policy (J1–J6, Q1–Q20, X2/X3/X5, R1–R6b; PI-1…PI-12);
  - the reconciliation (`memory-contract-reconciliation.md`, E1–E13);
  - the implementation spec (`memory-implementation-spec.md`);
  - the prototype findings (`memory-prototype/prototype-findings.md`, F-1…F-10);
  - the platform map (`memory-ecosystem-map.md`, cited as **MAP §n**).

**Tags.**

| Tag | Meaning |
|---|---|
| `[CONTRACT]` | normative contract |
| `[CODE]` | verified at `origin/main` |
| `[DATA]` | measured (none available) |
| `[DERIVED]` | follows from evidence |
| `[DECISION]` | an engineering choice made here, with its reasoning; reversible unless stated |
| `[BLOCKED:<owner>]` | a genuine business, legal or security-authority decision, isolated behind a policy boundary |
| `[UNRESOLVED]` / `[UNMEASURED]` | as before |

**Mapping to the brief's tag set.**
- `[DECISION]` means a choice whose basis is `[DERIVED]` or `[INFERENCE]`. The basis is given in the table in §X.
- `[BLOCKED:<owner>]` means `[UNDECIDED]`, with the named owner who must decide it.
- Every numeric budget and threshold in this document is `[UNMEASURED]`: a starting value, set in config, to be calibrated by Lane 1-real and Lane 2.

---

## A. Philosophy and invariants

**The premise.** OLBrain already has at least nine uncoordinated memories (MAP §1). They are built by different teams, with different scoping, no common provenance and no common erasure. Several derive durable, cross-user knowledge from customer conversations without tenant fields or deletion paths. **The architecture's job is to put every piece of durable, learned or person-derived knowledge under one semantic contract and one lifecycle.** That means one set of rules for what may be written, by whom, with what provenance, under what scope, how it is read, and how it is erased. Only person memory being "smarter" is the lesser goal.

**Platform invariants.** These are binding on every repository, and each item traces to evidence in the MAP.

| # | Invariant |
|---|---|
| P1 | **One write authority.** Durable learned knowledge (person, account, agent-wide, template-wide) is written only through the Memory Gateway. A store that does this today outside the Gateway is legacy and must migrate (M1–M8) |
| P2 | **Lifecycle registry.** Every durable store or object prefix holding person-derived data is registered. Each registration names the owning scope key, the erasure handler, the retention class and the rebuild source. CI fails a change that adds an unregistered store `[DECISION]` |
| P3 | **Opaque keys.** No raw identifier (phone, email, platform user id, customer id) appears in a document id, object path, session id, log line, analytics key, billing key or cache key. Keys are opaque subject ids or keyed HMACs (MAP §3: session ids embed phone numbers, and those ids reach billing) |
| P4 | **Proven identity.** A memory subject is bound to an identifier only at a declared **assurance level**. An asserted identifier never unlocks memory created under a verified one (MAP §5 N1) |
| P5 | **Server-owned tenancy.** Org and scope for any memory operation come from a server-verified resource (subject, agent, evidence), never from a request body, a client-writable document or a service caller's claim (MAP §5 K1/N2, service auth) |
| P6 | **No hidden truth.** LLM output, summaries, patterns, indexes, caches, traces and vector projections never establish current state or authority. Only Claims resolved by policy do (contract rule 10) |
| P7 | **Grounded writes.** Every Claim has support edges to evidence the source is authorised to assert. An agent's words never support a claim about another subject, except through recorded assent (E1) |
| P8 | **Content-immutable claims, recorded lifecycle.** Supersession is computed at read time (F-10). Physical deletion happens only through erasure |
| P9 | **Fenced derivation.** Every derived write (claim, summary, pattern, overlay, index, trace-derived fact) is fenced at commit by the erasure epochs stamped on its inputs, and is idempotent under replay (E3) |
| P10 | **Archive first, then erase.** Deletion makes data unreachable synchronously. Physical removal follows a governed window, R6b `[BLOCKED:Legal+Jay]` for the value |
| P11 | **Complete erasure.** An erasure request is complete only when every registered store reports done. The ledger is PII-free and survives restores (MAP §4) |
| P12 | **Aggregates keep lineage or keep no person text.** Agent- and template-wide learning either keeps contributor lineage, so erasure can remove a contribution, or stores no person-derived text at all (MAP §1 M4–M6) |
| P13 | **Declared and labelled context.** Every memory item entering a prompt carries its status, time, source and scope. The manifest is recorded (E8) |
| P14 | **Mode isolation.** Draft, test and eval sessions never write production memory of any kind, including patterns, summaries and learned overlays. They may write only to an isolated eval namespace (MAP §2: the pattern learner and summariser ignore mode today) |
| P15 | **Model-replaceable.** The semantic contract is independent of vendor and model. Extraction is a versioned, schema-validated proposal protocol with provider adapters, and every model output passes the deterministic gate |
| P16 | **Measured.** Nothing ships without passing the benchmark and emitting its counters |

---

## B. Memory taxonomy

Every durable thing an agent can "know" falls into exactly one class. Each class has one authority and one durability tier.

| Class | Definition | Authority | Durable? | Truth? | Examples in OLBrain |
|---|---|---|---|---|---|
| **Evidence** | What was observed or said: messages, tool observations, operator entries, imports, agent actions | The originating event | Yes, under retention (R-M3) | No (it is the record, not the truth) | `agent_messages`, uploads, trigger payloads |
| **Claim** | A structured assertion `(subject, key, value, validity)` with support lineage | The Predicate Policy | Yes | Only via resolution | Preferences, attributes, historical facts |
| **Current State** | A policy-resolved projection of claims per slot | Derived from Claims | Rebuildable | Yes, operationally | Preferred language, consent, opt-out |
| **Commitment** | A promise or obligation between parties, as a state machine (§C.4) | The agent action or tool result that created it, plus the counterparty's assent | Yes | The state machine's current status | "Callback Friday 3pm", "refund pending" |
| **Episode** | A bounded grouping of evidence (one conversation segment) | Deterministic rule: a 24 h gap `[UNMEASURED]` or an explicit close | Yes | No | Chat or call segments |
| **Narrative** | A summary of one episode, from evidence only | Derived by an LLM, labelled non-assertive | Rebuildable while evidence is retained | **Never** | Episode summaries |
| **Agent Knowledge** | Learned guidance at agent, template or workflow scope | Owner-approved (becomes config) or candidate | Yes, with lineage | Never *about a person*; guidance only | Patterns, research learned profile, workflow overrides, owner lessons |
| **Org Knowledge** | Documents the org provides | The org (document owner) | Yes | Documentary | Knowledge vault |
| **Operational state** | Workflow runs and items, research runs, bookings in external systems | The owning engine or external system | Owned elsewhere | The engine's own state | Workflow items |
| **Identity** | Subjects, identifiers, merges | The identity authority (PI-2) | Yes | Yes, for resolution only | Identity mapping |
| **Authorization** | Memberships, grants, keys | The IAM (memberships) | Yes | Yes, for access only | `memberships_index` |
| **Telemetry** | Traces, trajectories, logs, metrics | Ops | Bounded retention | Never | `agent_traces`, trajectories |
| **Caches and indexes** | Speed copies | Derived | Rebuildable, TTL | Never | Head projections, FTS, vectors |

**Never stored** `[DECISION]`:
- raw identifiers in keys or logs;
- model self-reported confidence;
- inferred sensitive attributes (health, religion, sexuality, finances, children);
- persisted inference in v1 (R-M1 `[BLOCKED:Jay]`; default *not persisted*; the prototype showed same-script inference leaks through the soft value check unless F-1 is applied);
- secrets in tool arguments or results (the MCP logger stores these today; MAP §3);
- detokenised plaintext summaries for orgs with PII protection (the insights writer does this today, MAP §3).

**Decisions on the ambiguous classes:**
- **Workflow and operational state stays owned by its engine.** Memory holds only *claims derived from workflow evidence*, with a reference to the item (id plus key), never copies of item data. Copying makes memory a second source of truth for operational state `[DECISION]`, and today `workflow_agent_memory` stores raw `original_data` (MAP §1 M6).
- **Tasks** in the agent-task sense are either Commitments (between parties) or workflow items (operational). There is no third "task memory" `[DECISION]`.
- **Relationships** between people, agents, companies and entities are Claims whose object is an entity reference (`relationship.works_at → ACCOUNT:acme`). No graph store is needed. A relationship is authoritative under the predicate's policy `[DECISION]` (see §G for why no graph).

---

## C. Entity and scope model

### C.1 Scopes

Every memory object has **exactly one owning scope**, following the contract's single-scope rule (`:140-173`). Visibility across scopes is always an explicit grant, never inheritance (`:138`).

| Scope | Anchor today `[CODE]` | Owns | Status |
|---|---|---|---|
| TENANT (org) | `organizations/{id}`, plus physical tenancy (`runtime.type=dedicated`) | Org-level facts, erasure boundary | Exists |
| WORKSPACE | `projects/{id}` | Nothing in v1. It is an authorization grouping only | Exists; no memory |
| AGENT | `agents/{id}` | Agent Knowledge, agent config | Exists (the root of trust must become server-owned, §M) |
| **PERSON** | None cleanly. Interim is (agent × channel key). Target is the identity authority subject (PI-11) | Person claims and state | **New subject** |
| **ACCOUNT** (the end customer's company) | Only `research_clients` (research domain) `[CODE]` | Company-level claims (plan, industry, contract, contacts), shared by the persons linked to it | **New entity** `[DECISION]`; generalises `research_clients` (slug, aliases, audited `merged_into`) |
| **RELATIONSHIP** (agent × person) | Implicit: memory is keyed by agent today | Commitments this agent made to this person; agent-private notes about the person | **New scope** `[DECISION]` |
| SESSION / EPISODE | `agent_sessions` | Episode grouping, narrative summaries, session-scoped state (existing finance context) | Exists; episodes are new |
| RESOURCE | Workflow item, research run, KV document | Referenced, never owned by memory | Reference only |

**Why RELATIONSHIP exists** `[DERIVED]`. Q5 settled that agents in an org share *person* memory. But some knowledge is inherently per agent: "Sales agent promised a discount" should not become "Support agent promised a discount". Without a relationship scope, the choice is between leaking commitments across agents and keeping everything agent-private, which contradicts Q5.

### C.2 Ownership rules `[DECISION]`

- **Assignment.** A Claim's owning scope comes from its policy key's `scope_class`:
  - `person.*` goes to PERSON;
  - `account.*` goes to ACCOUNT;
  - `commitment.*` and `relationship_note.*` go to RELATIONSHIP;
  - `session.*` goes to SESSION.
- **The model does not choose the scope.** The key determines it, and the key's policy is code (E11).
- **No inheritance.** A PERSON claim never implicitly becomes ACCOUNT knowledge, or the reverse. Combining them is an explicit derived view: the context compiler reads PERSON, then its linked ACCOUNT, labelled per scope.
- **Linking persons to accounts.** A link is a claim `person.member_of_account → ACCOUNT:x`. It is authoritative only from sources the policy allows: CRM import, operator, or verified email domain plus a confirmation.

### C.3 Grants (visibility)

- **Agents in an org.** Every agent in an org may read that org's PERSON and ACCOUNT scopes, by an explicit grant (Q5, PI-8).
- **RELATIONSHIP.** Readable only by its agent. Other agents see a relationship only through an explicit **commitment disclosure** flag on the policy: for example, open commitments are visible org-wide, so another agent can say "your callback is booked" `[DECISION; per-predicate policy]`.
- **Operators.** Read through the API with a distinct `memory:read` permission (§M). Which roles get it is R-M4 `[BLOCKED:Jay]`.

### C.4 Commitments: first-class state machines `[DECISION]`

**The model.**
- Predicate `commitment.<kind>`, with contract cardinality `STATE_MACHINE` (`:325-335`).
- States: `proposed → confirmed → in_progress → fulfilled | cancelled | expired | breached`.
- Fields: counterparty, due window, `created_by_agent`, and `source_action_ref`, which points at the tool call or workflow item.

**Authority.**
- `confirmed` requires either a **system action** (a booking tool returned success: TRUSTED_TOOL evidence) or **user assent** (the `confirmed` mode, E1).
- An agent's claim alone ("I'll call you Friday") creates only `proposed`.

**Behaviour.**
- Transitions are typed commands with `expected_version` (contract §7).
- A due-date boundary drives `expired` through the time-boundary rule (M7).
- **Why:** today's promises live as free text in `facts[]` or summaries. They are unenforceable, can't be expired, and a model can invent them (MAP §1).

---

## D. Identity model

The settled identity policy is applied, not reopened: org-scoped person resolution, automatic merges with audit and undo, survivor-canonical, R2 conflicts, R6b "erase the whole merged subject".

**Additions this platform requires** `[DECISION]`:

1. **Assurance levels per identifier binding.** This answers MAP §5 N1.

   | Level | How it is established |
   |---|---|
   | `channel_verified` | The channel authenticates the sender: WhatsApp and Instagram platform ids, email with a verified sender, voice ANI from the carrier via the gateway `[UNRESOLVED gateway]` |
   | `org_signed` | The org's backend asserts an end-user id inside a **signed end-user token** (a JWT the Gateway verifies against the org's key) |
   | `asserted` | Free text from an API-key holder or a share-link visitor (today's webhook `user_id`) |
   | `anonymous` | A session only |

2. **The asserted-identity rule.** An `asserted` identifier binds only to an **endpoint subject**, isolated per (agent, api key), and **never** resolves to or reads memory of a subject established at a higher level.
   - Share-link visitors are always `asserted`.
   - Whether an org may configure "trust assertion from this server key" is `[BLOCKED:Security/Product]`. The default is no.

   This closes the impersonation path, where anyone holding a key asserts a customer's phone number and loads that person's memory.

3. **Identity is not authentication or authorization.** A resolved subject gives memory *continuity*, never access. Access is decided by grants (§C.3, §M).

4. **Keys.**
   - Subject ids are opaque.
   - Identifiers are stored as an HMAC per org, with an encrypted raw copy under a per-org KMS key (Q16/D2, PI-11).
   - The memory interim subject index (implementation spec §4.3) keeps today's keying until the identity authority lands. It never merges.

5. **Account identity.** Accounts are resolved by domain, CRM id or alias, with a reversible audited merge (the `research_clients` precedent). Linking persons to accounts is a claim (§C.2), never an identity merge.

6. **Splits** are undo of a merge (Q17 quarantine, new claims only on recovery). A *split without a prior merge* means one identifier used by two humans, such as a shared number (Q1). It is handled by creating a new subject for the second human, and *moving only future evidence*. Past claims stay put, because they are unattributable `[DECISION]`.

7. **Transfer.** D15 is resolved here `[DECISION]`, within J6 ("person data follows the agent") and PI-10:
   - Subjects whose evidence came **only** through the moving agent move whole. That means the subject, claims, evidence refs and episodes, re-keyed under the destination org's HMAC, with new subject ids and a source epoch bump.
   - For **shared** subjects (PI-10 split), only the claims whose every support edge is evidence from the moving agent's sessions are copied, as new claims with support. RELATIONSHIP-scope data for the moving agent moves in full.
   - The source keeps everything else.
   - In-flight work is fenced (the fail-closed rule already in the spec). Evidence moved with the subject is re-queued for extraction in the destination.
   - Agent Knowledge moves with the agent after being **scrubbed of contributor lineage** from the source org. Items whose lineage cannot be scrubbed are quarantined.

---

## E. Evidence → Claim → State model

Adopted from the implementation spec, with every prototype finding **resolved** `[DECISION]`:

| Finding | Resolution |
|---|---|
| F-1 same-script inference leak | `unverified` is allowed only **across scripts** (the value's script differs from the quote's) or through a normaliser family. A same-script value missing from the quote is rejected (`mode`). Prototype: blocking metrics pass with the amendment |
| F-2 E7 wording | Supersession uses the later claim's **asserted** interval. Retracting the later claim never revives the earlier one. Contract edit E7 is reworded |
| F-3 recovery id collision | The claim id includes a derivation tag: `HMAC(k_subject, evidence|key|value|derivation)` |
| F-4 merge-epoch lineage | Support edges and transitions caused by merge-epoch evidence carry the merge ids, and undo removes or reverses them (generalises M17) |
| F-5 quotes in immutable content | **Quotes move to support edges**, which are lifecycle rows that erasure can delete. Claim content keeps evidence ids and a keyed quote digest. Rendering takes the quote from a live edge |
| F-6 cross-source dedup | Dedup applies only within a source group. Authorities never fold together |
| F-7 late retraction | A retraction targets only claims observed at or before it |
| F-8 cross-member retraction | A retraction targets only its own source group. Contradiction across members is an assertion, which yields CONFLICT under R2 |
| F-9 unverified registered-key claims invisible | The context compiler renders unverified claims of current-state keys in the memory tier, labelled *"unverified; not current; said: …"*. They are never rendered as current (E8(5): "as current") |
| F-10 persisted supersession | **Supersession is computed at read time** (M27 decided). Ex.20's stored `SUPERSEDED` is a derived status in results. This is a contract clarification |

Claim lifecycle statuses: `active`, `retracted(no_longer_true|never_true)`, `invalidated`, `quarantined`, `pending_erasure`, `pending`, `revalidation_required`, `superseded_by_policy`. The E5 addendum adds `pending_erasure`.

---

## F. Write pipeline

The pipeline is one path for all learned knowledge (P1).

```text
evidence ingest (sync, stamped) ──► PG evidence_meta + outbox row (same PG txn) ──► extraction job (durable, deterministic name)
   subject + assurance, epochs, merge ids,                     batch of pending evidence per subject
   author_role, episode (async), extraction_state
                                                    ──► proposal (LLM, provider adapter, schema-validated)
                                                    ──► gate (deterministic; E11 policy; F-1/6/7/8 rules)
                                                    ──► commit txn (subject-serialised; fence E3; dedup→support;
                                                        claims + edges + transitions + slot re-resolve +
                                                        evidence state + memory_events) ──► outbox: projections
```

### Cross-store ingest order `[DECISION]`

Evidence content lives in Firestore `agent_messages`, while `evidence_meta` and the outbox live in PostgreSQL. **No transaction spans the two stores.** The write order is fixed:

1. **PostgreSQL first, in one transaction:** the `evidence_meta` row (with `status=pending_content`, keyed by the channel message id, which is unique) plus the outbox row.
2. **Then Firestore:** the message document, whose id is derived from the same channel message id.
3. **Then PostgreSQL again:** `status=ready`. The outbox dispatcher dispatches only `ready` rows.

**Orphans, one per side:**

| Orphan | Arises when | Resolution |
|---|---|---|
| **Meta without content** | Firestore write fails | A sweeper runs every 5 min `[UNMEASURED]`. It retries the Firestore write from the request replay. After TTL it marks the meta `abandoned`, so it is never extracted. It is harmless: no content, so nothing to erase |
| **Content without meta** | PostgreSQL is down at step 1 | **Not permitted.** The turn proceeds, but the message is written with `memory_state=unregistered`, and the repair job registers it later, fail-closed against the erasure log (an erased subject is never registered). Until then the message is not memory evidence |

Erasure handlers act on both stores and key off the channel message id, so an orphan on either side is still reachable.

### The LLM proposes; code decides

| The LLM MAY propose | Code decides |
|---|---|
| `assert` or `retract` over registered keys or open namespaces | grounding |
| quote anchors | mode validity |
| an assent reference | authority |
| a time expression | sensitivity |
| — | suppression |
| — | dedup and support |
| — | supersession |
| — | conflict |
| — | scope |
| — | fencing |
| — | current state |
| — | identity |
| — | deletion |

### Derived learners go through the same gate family `[DECISION]`

Summaries, patterns, overlays and workflow learning all use it.

**Episode summarizer.**
- Its input is episode evidence only.
- Its output is a Narrative row, fenced and non-assertive.
- It is the **only** writer. The insights job's summary field and the rolling summariser are retired (MAP §3: two writers today).

**Agent Knowledge learners** (pattern learner, research consolidator, workflow exception learning, context consolidator):
- Output is `agent_knowledge` items. Each is `{statement, kind, scope (agent|template|workflow), status: candidate|approved|retired, lineage: contributor evidence ids and subject ids}`.
- **No verbatim person text.** The learner must emit abstracted statements. A deterministic PII detector over each statement blocks emails, phones, names from contributing subjects' claims, and numbers from finance tools.
- **Items reach prompts only as non-assertive guidance**, never as "ground truth".
- **Auto-application** (workflow overrides) requires `approved`, which means owner approval, following the existing workflow human-approve precedent.
- **R-M2 decides whether any customer text is ever permitted** `[BLOCKED:Jay/Legal]`. The default is no.

**Owner lessons** remain owner-confirmed config (the Dendrite precedent). The owner's raw pasted end-user exchanges must pass the PII detector before becoming example nodes, or be stored as a reference to evidence `[DECISION]`.

### Mode isolation (P14)

The Gateway rejects any write from a draft, test or eval session unless it targets the eval namespace. That covers claims, narratives and agent knowledge. It fixes the pattern learner, summariser and tool writes, which ignore mode today (MAP §2).

---

## G. Retrieval architecture

The retrieval classes are the typed operations the contract names (`:657`), plus two that it permits as capabilities.

| Operation | Returns | Mechanism | Why |
|---|---|---|---|
| `get_current_state(scope, key)` | The §11 result | Deterministic slot lookup (head projection) | Exact, versioned, OCC-able |
| `get_commitments(scope, status?, due?)` | Commitment state machines | Indexed SQL | Deterministic |
| `search_history(scope, key/namespace, time range, as_of, cutoff)` | Historical claims with labels | Temporal query (bitemporal filter) | Exact |
| `search_memory(scope set, query, keys?)` | Active non-current claims, including unverified registered keys labelled per F-9, plus episode narratives | **PostgreSQL full-text (tsvector) over claim key, value and quote**, with structured filters and ranking | Lexical is sufficient for short normalised claims, and PG FTS removes the in-process BM25 of the Firestore design |
| `get_relationships(subject, predicate?)` | Entity-reference claims | SQL join over claims | A graph DB is not needed at depth ≤ 2 |
| `get_org_knowledge(...)` | KV passages | Knowledge vault (separate subsystem) | Documents, not memory |

**When vectors are justified.** Add a `pgvector` projection only when **all three** hold, measured in Lane 2:
- paraphrase recall on narrative or episode search is below target;
- the misses are vocabulary mismatch, not ranking;
- synonym expansion fails to close the gap.

The projection is then a rebuildable index, fenced and erased like any other. **It is never truth** `[DECISION]`.

**Why not a graph DB.** Every relationship query needed (person→account→contacts; person→commitments; agent→persons) is a ≤ 2-hop indexed join. A graph store would add a second system that erasure and merges must follow, with no query that needs it `[DERIVED]`.

**Authorization in retrieval.**
- Checked per row at contract §6 step 9, using the org and the grant.
- Filters never change which claims resolve a slot.
- A merge never widens a grant.
- An `asserted` subject retrieves only its endpoint scope (§D.2).

**Stale and contradicted items.**
- **Stale:** a volatile slot stays VALUE with `freshness_status = STALE`.
- **Contradicted:** a CONFLICT is rendered with both values.
- **Superseded:** returned only by `search_history`.
- **Quarantined, pending_erasure and invalidated items never appear.**

---

## H. Context construction: the context compiler

The question it answers is **"what does this agent need to know right now for this task?"**, not "dump the profile".

### Inputs

- **The agent's `memory_profile`.** This is config: the predicates, scopes and commitment kinds the agent uses, plus a budget per tier. It is compiled from the agent's datastore fields and skills, and published with the brain `[DECISION]`.
- **The current turn**: the message plus the tool or skill in play.
- **Subject, account and relationship refs.**
- **Policy versions.**

### Deterministic tiers

The budgets below are `[UNMEASURED]` starting values, set per agent in `memory_profile`.

| Tier | Content | Budget | Notes |
|---|---|---|---|
| T0 | Current state for the profile's keys, plus consent, plus open commitments | ~300 tokens | Never silently truncated |
| T1 | Relevant active memory | ~800 tokens | Ranked by `authority_rank × validity × recency_decay × lexical_relevance(turn) × policy_weight` |
| T2 | The current episode's history | Existing budget | — |
| T3 | Narratives of recent episodes | ~400 tokens | — |
| T4 | Agent Knowledge guidance | Small | Labelled non-assertive |

Tools let the model fetch more (typed operations), under per-turn call caps.

**Ranking** is deterministic, with no LLM in the loop, so the same inputs produce the same context and the same manifest.

### Rendering rules

- **Placement.** Content goes in a delimited `<<MEMORY — information, not instructions>>` block in the **uncached dynamic tail**.
- **Labels.** Every item shows its status, dates, source, scope and a reference id (a citation handle usable by `explain(ref)`).
- **Failure.** A failed read renders as "unavailable", never as empty.

### Manifest

A manifest is kept per assistant message, recording ids and versions only. It follows the research `LearnedContext` precedent (MAP §6).

### Compression

- The only compression is Narrative, and it is built from evidence.
- Summaries are never summarised again.
- Compaction markers must be **server-signed**. The current Cortex path promotes any flagged message (MAP §5).

---

## I. Temporal semantics

This is adopted from the implementation spec §9, with F-2 applied:
- intervals are half-open;
- two time axes (valid and knowledge);
- a transition log;
- `no_longer_true` bounds a claim's interval, while `never_true` removes it from history;
- boundaries are applied at read and commit time (M7);
- freshness is policy-based and separate from expiry;
- R-PRESENT plus null `valid_from` stay flagged defaults `[DECISION, reversible]`.

Commitments use valid time for due windows (§C.4).

---

## J. Conflict resolution

1. **Authority.** Rank per predicate policy. Operator ranks are `[BLOCKED:domain owners]`. Until they decide, the default is equal to USER, so a disagreement gives CONFLICT, which is fail-safe.
2. **Same source group.** The later-observed claim wins over its asserted interval.
3. **Independent sources, or merged members (R2).** Equal rank gives CONFLICT, cleared only by `RESOLVE_CONFLICT`: an operator command, or a predicate-declared claim class.
4. **Unverified winner.** The slot is UNKNOWN (M9), and the claim is visible as memory (F-9).
5. **No survivor.** The policy's `clear_outcome` applies.

**Never:** last writer wins on important state, or a pick by recency across sources (contract Ex.7).

---

## K. Merge and split semantics

This is adopted as reconciled and prototyped. The pieces:
- ingestion-time and commit-time merge recording (E3);
- quarantine on undo;
- no restore in place;
- Q17 recovery through new claims only (with F-3);
- source-member attribution;
- the absorbed subject B accepts lifecycle transitions but no content writes;
- chained merges;
- erasure of quarantined material by source member.

**New `[DECISION]`:** Agent Knowledge lineage records contributor subject ids. So a merge undo also removes merge-epoch contributions from agent-wide items (F-4 generalised).

---

## L. Erasure and deletion

### L.1 Semantics per operation

| Operation | Effect |
|---|---|
| Retract | Lifecycle only |
| Forget one fact | Archive plus suppression plus `context_suppressed` on evidence and echoes. Physical redaction is `[BLOCKED:Legal]` |
| Stop remembering | Consent slot off. Future learning stops; reads continue |
| Forget a conversation | Evidence is invalidated, derived items are re-evaluated for lineage, the narrative is dropped |
| **Forget me** (R6b settled) | The whole merged subject is archived at once; after the window, physical erasure |
| **Erase org** | All scopes of the org, including Agent Knowledge, KV, traces and backups under policy |
| Merge undo | Quarantine |
| Retention expiry | Evidence content is removed and lineage kept (R-M3 `[BLOCKED:Jay]` decides whether bounded) |

### L.2 Mechanism `[DECISION]`

**The Erasure Orchestrator** is a durable job in the Memory Gateway, driven by the **Lifecycle Registry** (P2).

1. **The request.** It is fenced by epochs, and archived synchronously:
   - subject heads are set to `pending_erasure`;
   - index entries are retired;
   - `do_not_contact` is set;
   - session cut-offs are applied.
2. **The per-store handlers.** For each registered store, the orchestrator runs that store's handler. A handler keyed by subject id or HMAC, never by a raw identifier, returns `{done | partial | not_applicable}`.
3. **The ledger.** A PII-free ledger per request records the status of each store.
4. **Completion.** The request is complete when every store reports done. It follows the phased, idempotent contact-erasure precedent.

**Registered stores**, with the handler required for each (MAP §4 survival list):

| Store | Required handler |
|---|---|
| `agent_messages`, sessions and their LLM fields | Delete, or rekey to a tombstone |
| Narratives and legacy summaries | Delete |
| `agent_traces`, trajectories, `workflow_run_traces` | Delete by subject/session prefix; **must become subject-addressable** |
| `mcp_tool_executions` | Add `org_id` and `subject_id`; delete |
| Eval transcripts | Eval namespace only; TTL |
| Agent Knowledge | Remove contributor edges, then re-derive or retire |
| Legacy M4–M8 | Handled until retired |
| `lead_*`, `agent_users` | Existing erasure, extended |
| `usage_events` and billing | Pseudonymous keys (P3), kept for billing under a legal basis `[BLOCKED:Legal]` |
| Logs | PII-free by construction (P3), so nothing to erase |
| KV documents derived from conversations | Delete, with FTS and card invalidation and BlobCache invalidation (fix the rebuild race) |
| Exports and audit CSVs | Lifecycle rule plus an index |
| External copies (Slack, email) | **Minimise at source**: send links, not excerpts. Record that the excerpt left the platform |
| Subprocessor retention | `[BLOCKED:Legal]` (DPAs covering Anthropic, Groq and Gemini) |
| Backups | Window ≤ legal deadline, plus a PII-free ledger replay on restore, from a separate control database |

**The completeness auditor** is a scheduled job. It scans every registered store for the ids of subjects erased more than the window ago, and pages on any hit. This is how "deleted from the profile, still present elsewhere" is caught `[DECISION]`.

---

## M. Security model

### M.1 Prerequisites before any memory shadow write or migration

These are hard gates.

| # | Control | Evidence |
|---|---|---|
| S0-1 | `agent_messages` writes server-only and reads org-scoped, with the client query changes and backfill. Inventory `olbrain-noesis-os` first | MAP §5 E1 |
| S0-2 | `agents/{id}` and `agents/{id}/versions` writes server-only. `organization_id` and `owner_id` are immutable from clients | K1/N2/N6 |
| S0-3 | **`require_permission` must enforce authorization for Firebase users** (role-based), not only API-key scopes. Fixes the `agent_users` IDOR class | root cause of S-M1 |
| S0-4 | Identity assurance (§D.1–2). Until it ships, **disable person memory reads for `asserted` identities** on the webhook and share paths | N1 |
| S0-5 | Every new memory collection or table is server-only, with a CI rules check | — |
| S0-6 | PII-free logging lint, plus removal of raw identifiers from log lines | MAP §3 |
| S0-7 | Compaction markers must be server-signed | Cortex |
| S0-8 | MCP `tools/call`: auth on, `agent_id` from the verified token, no `default` credential fallback for tenant tools | N8 |
| S0-9 | `email_verified` required for platform admin | N7 |
| S0-10 | `members`, `departments` and `tickets` rules | N3–N5 |

### M.2 Standing controls

- **Tenancy (P5).**
  - The Gateway derives the org from the subject and agent it owns.
  - Service callers authenticate with OIDC. The Gateway authorises the caller against the resource's org.
  - The shared `INTERNAL_SERVICE_SECRET` is not accepted.
- **Row-level security** in PostgreSQL on `org_id`, as defence in depth (contract: "RLS not the sole model").
- **Memory never authorises.** No claim, narrative or knowledge item is capability evidence (E8(2)). Security, billing, role and entitlement predicates are not extractable (E11).
- **Poisoning resistance.**
  - The gate: grounding, source authority, the security lexicon plus anomaly events, and model-chosen keys that carry no authority.
  - The render: memory marked as data.
  - Agent Knowledge learners pass the PII and instruction detector. Candidates reach prompts only as guidance.
- **Forged evidence.** Evidence stamps (author role, epochs, merge ids) are server-only (S0-1).
- **Stale authorization.** Memory operations that change or expose data are online-authorised (PI-12 row 6). Ordinary reads may use the 60 s capability cache (Q19).
- **Cross-tenant joins.** There are no cross-org queries in the Gateway API. Physical tenants get separate databases (§P).
- **Exfiltration.**
  - Retrieval results are capped per turn.
  - Operator exports are online-authorised, audited and expire.
  - `memory:read` is a distinct permission; its roles are R-M4.

---

## N. Concurrency and fencing

The design is the reconciled E3 and the spec §10, moved to PostgreSQL.

**Serialisation.** The unit is the subject: a `SELECT … FOR UPDATE` on the subject row, following merges to the survivor.

**Commit transaction.** One transaction writes:
- claims, edges and transitions;
- the slot projection, with a `state_version` per slot;
- the evidence state;
- `memory_events`;
- an outbox row.

**OCC.** Typed commands use `expected_version` per slot (commitments and consent).

**Idempotency.**
- Deterministic ids.
- Outbox `dedup_key` unique constraints.
- Evidence ingestion de-duplicated by channel message id (the `wamid` dedup does not exist today).

**Fences.**
- Erasure epochs are stamped on the evidence at ingestion and checked at commit (E3).
- A merge re-targets work (Q20).
- Transfer and other non-merge causes fail closed.

**Reused precedents.**
- The FE deterministic job names and dispatch ledger.
- The research `driver_claims/{run}:{gen}` pattern.
- The shared `expected_version` CAS.

---

## O. Async processing

**Rule `[DECISION]`:** no durable write may happen in fire-and-forget work. Today that covers the extractor, insights, pattern learner and dispositions (MAP §3), all of which lose work on an instance restart and cannot be fenced.

| Work | Mechanism |
|---|---|
| Extraction, narratives, agent-knowledge learning, projections, erasure, re-extraction | **Transactional outbox** in PostgreSQL. A dispatcher sends to Cloud Tasks with deterministic task names, and handlers are idempotent and fenced. A DLQ **with a consumer and alerting** (none exists today) |
| Synchronous | Ingestion stamping; exact-lane identity resolve and merge (X3); consent directives; forget-me archive; `get_current_state`; the manifest write |
| Asynchronous | Extraction; narratives; learners; indexing; rebuilds; the completeness auditor; evaluation |

---

## P. Storage architecture

**Decision `[DECISION]`:**
- **PostgreSQL (Cloud SQL) behind the Memory Gateway is the system of record for memory from the start.** That covers subjects, identifiers (owned by the identity authority), claims, support, transitions, slots, commitments, episodes, narratives, agent knowledge, manifests, the lifecycle registry state, the erasure ledger, the outbox and memory events.
- **Evidence content stays where it is**, in Firestore `agent_messages` and in GCS. PostgreSQL holds `evidence_meta` (stamps, ids, a content hash and a reference).

**Why PostgreSQL rather than the Firestore MVP of the implementation spec.** This revises spec §20.

| Firestore's limitation | Why it matters here |
|---|---|
| **Cross-subject operations are core, not rare.** Erasure by `source_member_id`, quarantine by merge id, completeness auditing, re-extraction by extractor version, and support-edge lookup by evidence all need secondary-indexed set queries | Firestore `array-contains` on a subcollection handles each of these poorly |
| **Transactional outbox and unique constraints** (dedup keys) are native to PostgreSQL | Firestore has neither |
| **RLS gives defence in depth** on `org_id` | — |
| **The contract already names PostgreSQL with an outbox as the MVP realisation** `[CONTRACT :14]` | — |
| **The memory tables are new either way.** Building them on Firestore first means **two migrations** | — |

**What stays true regardless.** The pure core and adapter split (from the prototype) keeps a Firestore adapter possible if Cloud SQL is blocked. Semantics do not depend on the backend.

**Physical tenancy.**
- There is one Cloud SQL instance per physical tenant (the shared platform, plus each `dedicated` tenant such as Clix).
- The shared instance separates orgs with `org_id` plus RLS.
- There are no cross-instance queries.

**Other technologies:**

| Technology | Decision |
|---|---|
| **Vector** | `pgvector` projection only on the §G trigger |
| **Graph DB** | Rejected (§G) |
| **Redis** | Not needed. Head projections are PostgreSQL rows, read in one indexed query. The in-process caches that remain are keyed with `(subject, projection_version)` and invalidated by epoch |
| **Kafka / event streams** | Rejected. Outbox plus Cloud Tasks and Pub/Sub are sufficient at the projected volumes |
| **Object storage** | GCS for large evidence (attachments, trajectories) under **subject-addressable prefixes**, so erasure can reach them |

**Thresholds for revisiting** (all `[UNMEASURED]` estimates):

| Condition | Response |
|---|---|
| Write rate > 2 k commits/s per instance, or claims > 1 bn rows per instance | Partition by `org_id` (native partitioning), then shard per tenant group |
| p95 `get_current_state` > 30 ms after head caching | A read replica |
| Measured semantic recall gap | `pgvector` |

---

## Q. Evaluation framework (permanent)

The three lanes of the spec are adopted, extended to the whole platform:

| Lane | What it runs |
|---|---|
| **L1 core** (in process) | Deterministic suites with zero tolerance (gate, fence, resolver, ids, erasure), plus model-quality suites run 5× with rate thresholds. The prototype's 173 tests and 33 scenarios are the seed |
| **L1-real** | The benchmark through the real extraction adapter, for the current model and every candidate model or vendor. This is the model-upgrade gate (P15). **This is the first missing measurement** |
| **L2 end-to-end** | Multi-session personas in an isolated eval org, over CS, voice, workflow and research surfaces. Covers isolation fuzzing (cross-person, cross-org, asserted-vs-verified identity), deletion completeness via the auditor, and context usefulness scored by task success |
| **L3 production** | Counters; the sampled weekly audit; the completeness auditor; the head-diff job |
| **Adversarial set** | Poisoning, injection, agent contamination, fabricated quotes, sensitive inference, cross-member retraction (F-8), late retraction (F-7), merge and undo races, restore drills |

**The measured dimensions:**
- extraction recall;
- false and hallucinated memory;
- contamination;
- temporal, conflict, authority and identity correctness;
- deletion correctness;
- resurrection;
- isolation;
- retrieval precision and recall;
- context usefulness;
- latency and cost;
- determinism.

**Incident rule:** every incident becomes a scenario before it is closed.

---

## R. Observability

**`memory_events`** is an append-only table of ids only. It records every:
- proposal (accepted or rejected, with its code);
- commit;
- fence decision;
- conflict;
- retrieval (tier, ids and versions);
- identity event;
- erasure step;
- rebuild.

**Explainability.** `explain(ref)` answers "why does the agent believe this?" It returns:
- the claim and its status;
- the winning resolution and the policy version;
- the support edges, with their evidence ids and quotes while those are retained;
- the extractor version;
- the transitions;
- the manifests that included the claim.

**Metrics.** The spec §22 set, plus:
- per-store erasure completion age;
- registry coverage;
- stale-read counts;
- per-model and per-prompt-version accept and reject mix;
- token and cost per turn per tier.

---

## S. Migration strategy

**Principle `[DECISION]`: build erasure first.** The Erasure Orchestrator and Lifecycle Registry are built over the **legacy stores first**, before the new memory model. That reduces present legal exposure (MAP §4) and gives the migration its deletion consistency from day one.

### Legacy trust classification

| Legacy source | Trust | Target |
|---|---|---|
| `agent_user_memory.facts` | Low: no provenance, contaminated by assistant text | `legacy` claims, unverified, never current state, superseded naturally |
| `agent_datastores` operator rows | Medium | `operator` claims |
| `agent_datastores` extractor rows | Low | `legacy` |
| Session summaries (both writers) | Low | Not migrated. Narratives are regenerated from evidence |
| Session `user_name/email/phone` (LLM-extracted) | Low; identity-sensitive | **Not migrated as identity.** At most, candidate identifiers for the identity authority at the `asserted` level |
| `agent_learned_patterns` (verbatim) | Unsafe | **Quarantined.** Re-derived through the Agent Knowledge learner with no verbatim text. Old documents are erased after cut-over |
| Research learned profile, ledger and overlays | Medium; cross-user | Import as `candidate` Agent Knowledge **only** where lineage and PII checks pass. Otherwise re-derive |
| `workflow_agent_memory` (raw item copies) | Unsafe | Keep active overrides as approved Agent Knowledge **without** `original_data`. Patterns are re-derived |
| `owner_lessons` | High (owner-confirmed) | Remain config. PII scan on example nodes |
| `context_facts` | Low | Retire or re-derive |
| `lead_*` | Medium | Identity-authority inputs (identity track) |

### Mechanics

1. **Shadow.** New extraction writes to PostgreSQL. The legacy path keeps serving.
2. **Compare.** Per-agent diffs of claims against legacy facts.
3. **Dual read** behind a flag, per agent.
4. **Cutover.**
5. **Legacy write stop.**
6. **Quarantine**, then erasure of the legacy stores through the orchestrator.

**Rollback** at every step is flag-based until the legacy writes stop. After that, it is the documented recovery playbook (spec §24).

---

## T. Failure matrix

| Operation | Expected | On failure | Retry | Idempotency | Rollback | Audit | Recovery |
|---|---|---|---|---|---|---|---|
| Ingest evidence (PG step) | `evidence_meta` plus outbox in one PG transaction | The Firestore message is written with `memory_state=unregistered`; the turn proceeds | Repair job, fail-closed against the erasure log | Channel message id (unique) | — | `memory_events` | Repair sweeper registers it |
| Ingest evidence (Firestore step) | Message document written, meta set to `ready` | Meta stays `pending_content` and is never dispatched | Sweeper retries, then marks it `abandoned` | Document id derived from the channel message id | — | `memory_events` | Sweeper |
| Extract | Proposals committed | Evidence stays pending | Outbox redelivery with backoff; DLQ plus alert | Deterministic claim and edge ids | Transaction abort | Reject codes | Re-extract by version |
| Commit | Atomic | Abort, nothing written | Bounded | As above | Transaction | Events | — |
| Fence reject | Write dropped | — | Never (final) | — | — | `fence.rejections` | — |
| Merge | Re-resolve survivor | The identity authority retries | Idempotent on `merge_id` | — | Undo | Identity events | — |
| Undo | Quarantine plus reversal | Partial undo resumes | Idempotent | — | — | Events | Q17 recovery job |
| Forget me | Archive synchronously; erase asynchronously | Archive transaction retried; the orchestrator resumes per store | Per store | Ledger per request | None (final) | Ledger | Completeness auditor |
| Restore backup | Replay ledgers first | Workers paused until the replay verifies | — | Monotonic epochs | — | Ops log | Drill |
| Retrieval | Labelled results | Rendered as "unavailable" | Client | — | — | Retrieval events | — |
| Learner (agent knowledge) | Candidate item with lineage | Dropped | Outbox | Dedup key | Retire | Events | Re-derive |
| Transfer | Move or split per §D.7 | Fail closed, then resume | Idempotent per subject | Transfer id | Reverse transfer | Ledger | — |

**Guarded against**, each covered by an invariant and a test class:

| Failure | Guard |
|---|---|
| Invented memory | P7, F-1 |
| Lost memory | Watermark, outbox |
| Duplicates | Ids, F-6 |
| Resurrection | P9, P11, epochs, tombstones |
| Leaks | P4, P5, grants |
| Silent overwrite | Immutable claims, OCC |
| Wrong identity | Assurance levels, F-8 |
| Wrong tenant | P5, RLS |
| Historical treated as current | Typed operations, labels |
| Summary treated as truth | Narrative is non-assertive |
| Weaker authority beating a stronger one | Authority-first resolution, F-6 |

---

## U. API contracts (Memory Gateway)

The API is served over service-to-service OIDC. Every call names its resource, and the Gateway derives the org itself.

| Operation | Notes |
|---|---|
| `ingest_evidence(evidence_ref, author_role, channel_identity{kind, value_ref, assurance}, session_id)` | Returns `{evidence_id, subject_id, stamps}` |
| `submit_proposals(job_id, proposals[])` | For extraction workers. Returns an accept/reject report |
| `command(scope, key, op, value, expected_version, idempotency_key)` | Typed state commands: consent, commitments, `RESOLVE_CONFLICT` |
| `get_current_state` / `get_commitments` / `search_history` / `search_memory` / `get_relationships` | Contract §11 results with `:679` labels |
| `compile_context(agent_id, subject_ref, turn)` | Returns `{block, manifest_id}` |
| `explain(ref)` | — |
| `forget_fact(subject, key, value)` | — |
| `stop_remembering(subject)` | — |
| `forget_me(subject)` | — |
| `erase_scope(scope)` | — |
| `erasure_status(request_id)` | — |
| `identity_event(merge|undo|transfer, …)` | From the identity authority only |
| `register_store(…)` | Build-time registry; not a runtime API |
| `agent_knowledge.propose(scope, statement, lineage)` / `approve(id)` / `retire(id)` | — |

---

## V. Data model (PostgreSQL, logical)

Every table carries `org_id` and has RLS on `org_id`.

```sql
subjects(subject_id PK, org_id, kind CHECK (kind IN ('person','account','endpoint')), assurance,
         status, merged_into, member_set_version, created_at)
subject_keys(subject_id PK, key_ciphertext, key_version)            -- crypto-shred on erasure
scope_epochs(scope_type, scope_id, epoch, PRIMARY KEY(scope_type, scope_id))
scope_epoch_log(scope_type, scope_id, epoch, cause, at)             -- in the separate control DB with the erasure ledger
evidence_meta(evidence_id PK, org_id, subject_id, source_member_id, agent_id, session_id, episode_id,
              author_role, observed_at, epochs JSONB, merge_ids TEXT[], status, extraction_state,
              content_ref, content_hash, channel_msg_id UNIQUE)
claims(claim_id PK, org_id, subject_id, owning_scope, scope_ref, key, value JSONB, source, assertion_mode,
       value_check, normaliser_id, valid_from, valid_until, precision, observed_at, committed_at,
       extractor_version, policy_version, derivation, status, retract_cause, attributed, merge_ids TEXT[])
claim_support(edge_id PK, claim_id FK, evidence_id, source_class, source_member_id, observed_at,
              quote TEXT, merge_ids TEXT[])                          -- F-5: quotes live here
claim_transitions(claim_id, seq, at, from_status, to_status, cause, cause_ref, effective_at, merge_ids,
                  PRIMARY KEY(claim_id, seq))
suppressions(subject_id, fingerprint, created_at, observed_before)
slots(subject_id, key, state_version, result JSONB, computed_at, policy_version, member_set_version,
      next_boundary_at, PRIMARY KEY(subject_id, key))
commitments(commitment_id PK, org_id, relationship_ref, kind, state, due_from, due_until,
            counterparty_subject_id, created_by_agent, source_action_ref, version)
episodes(episode_id PK, org_id, subject_id, agent_id, channel, first_evidence_id, last_evidence_id,
         started_at, ended_at, merge_ids TEXT[], status)
narratives(episode_id PK, summary, generator_version, status, input_evidence_ids TEXT[])
accounts(account_id PK, org_id, display_name, aliases TEXT[], merged_into)   -- generalises research_clients
agent_knowledge(item_id PK, org_id, scope_kind, scope_id, kind, statement, status,
                contributor_subject_ids TEXT[], lineage JSONB, created_at, approved_by)
prompt_manifests(message_id PK, org_id, agent_id, subject_id, manifest JSONB, created_at)
erasure_requests(request_id PK, scope, requested_at, member_set_version, status)   -- control DB
erasure_steps(request_id, store, status, updated_at, PRIMARY KEY(request_id, store)) -- control DB
outbox(id PK, topic, payload JSONB, dedup_key UNIQUE, created_at, dispatched_at)
memory_events(id, at, org_id, kind, ids JSONB)                        -- ids only, no content
```

**Indexes:**
- `claim_support(evidence_id)`
- `claims(subject_id, key, status)`
- `claims USING GIN(merge_ids)`
- `claims(extractor_version)`
- `claim_support(source_member_id)`
- `evidence_meta(subject_id, extraction_state, observed_at)`
- a `tsvector` index on `claims(key, value)` and `claim_support(quote)`

---

## W. Implementation phases

| Phase | Content | Gate |
|---|---|---|
| **0: stop the exposure** (now) | Security prerequisites S0-1…S0-10. Legacy hardening (spec P1): wipe, truncation, OCC, tombstones, no raw ids in logs, the mode gate for every learner (P14), the insights job stops writing `summary`, detokenised summaries stop for PII orgs. Billing metering. Baseline counters | Rules emulator tests; L1 baseline recorded |
| **1: erasure first** | Lifecycle Registry over **all current stores**; the Erasure Orchestrator on the control DB; the completeness auditor; fixes to soft-deletes (sessions, runs, templates, agents, projects); the Shopify redact handler corrected; KV delete races fixed; trajectory, trace and MCP-log subject addressing | Auditor reports zero survivors in drills |
| **2: Memory Gateway core** | PostgreSQL schema; the pure core (the hardened prototype with every F-decision); the outbox; `memory_events` | L1 deterministic plus L1-real (first real-model baseline) |
| **3: evidence and subjects** | Ingestion stamping; interim subjects; the identity assurance levels; shadow extraction | Shadow compare |
| **4: retrieval and context** | Typed operations; the context compiler; `memory_profile`; manifests; episodes and narratives; per-agent cut-over | L2 |
| **5: Agent Knowledge** | Migrate M4–M8 into governed Agent Knowledge; quarantine the verbatim stores | Lineage audit |
| **6: identity authority integration** | Merges, undo and transfer hooks, with the identity track | Identity suites |
| **7: accounts, relationships, commitments** | New scopes; the commitment state machines | L2 commitment scenarios |
| **8: legacy retirement; vectors only if triggered** | — | Auditor clean for 30 days |

**What can run in parallel:** phases 0 and 1 are independent of 2. The L1-real harness can start now.

---

## X. Architecture decisions and rejected alternatives

| # | Decision | Rejected alternatives | Why | Failure modes, and the guard | Evidence | Tag |
|---|---|---|---|---|---|---|
| X-1 | One write authority (the Memory Gateway) for all learned knowledge | Per-feature memories (today) | Nine uncoordinated memories, no common erasure | The Gateway becomes a single point of failure. Guard: reads degrade to "unavailable", and evidence keeps flowing (§F ingest order) | MAP §1 M1–M9 | [DERIVED] |
| X-2 | Lifecycle Registry plus Erasure Orchestrator, **built first** (phase 1, before the new model) | Per-store ad-hoc deletes; building the model first | No delete path is complete today, and building erasure first reduces present exposure | A registry entry is missed for a new store. Guard: the CI registry check plus the completeness auditor | MAP §4 | [DERIVED] |
| X-3 | ACCOUNT and RELATIONSHIP scopes; single ownership plus grants | A person profile only; hierarchical cascade (`scope.py`) | Commitments and company facts; the contract forbids implicit multi-scope resolution | A wrong scope assignment. Guard: the key determines the scope (code, not the model) | Contract `:138-173`; `research_clients` | [DECISION←DERIVED] |
| X-4 | Identity assurance levels; asserted identifiers isolated in endpoint subjects | Trusting the webhook `user_id` | Impersonation by any key holder | Continuity is lost for honest API integrations. Guard: the signed end-user token path; the org trust flag | MAP §5 N1 | [DECISION]; org option [BLOCKED:Security/Product] |
| X-5 | PostgreSQL (Cloud SQL) as the memory system of record from the start | Firestore first, then PostgreSQL (spec §20); Firestore permanently | Cross-subject erasure and quarantine queries, the outbox, constraints, RLS; avoids a second migration; the contract MVP names PG | **Costs:** a new ops surface (no platform-owned Postgres exists today; asyncpg is only a customer-DB tool); **split-store ingest** (§F order plus the sweeper); connection management from Cloud Run (pooler). Fallback: the Firestore adapter through the core split | Contract `:14`; MAP §3 | [DECISION←INFERENCE] |
| X-6 | Read-time supersession | Persisted supersession | Persisted mode breaks never-true | Read cost grows with claim history. Guard: the slot head projection | F-10; prototype test | [DERIVED] |
| X-7 | Quotes on support edges | Quotes in immutable claim content | Erasable without mutating content | The render finds the edge deleted. Guard: render the digest as "quote removed" | F-5 | [DERIVED] |
| X-8 | The F-1, F-3, F-4, F-6, F-7 and F-8 rules | The spec as written | Prototype blocking and recovery failures | F-1 rejects legitimate paraphrase. Guard: Lane 1-real recall measurement | Benchmark spec vs amended | [DERIVED] |
| X-9 | Unverified registered-key claims shown as non-current memory | Hidden | They would otherwise be invisible | The model treats them as current. Guard: the label plus a Lane 2 check | F-9 | [DERIVED] |
| X-10 | Commitments as state machines; `confirmed` only from a tool result or user assent | Free-text facts | Enforceability, expiry, anti-invention | A missed commitment (the agent promised without a tool). Guard: `proposed` state plus a Lane 2 scenario | MAP §1 | [DECISION←INFERENCE] |
| X-11 | Agent Knowledge with lineage, no verbatim text, and a PII-detector block; guidance only; approval before auto-apply | Today's patterns, overlays and workflow memory | Cross-user leakage; no tenant field; no deletion | Detector misses paraphrased PII. Guard: lineage-based erasure still reaches the item | MAP §1 M4–M6 | [DECISION]; customer text [BLOCKED:R-M2] |
| X-12 | One narrative writer, built from evidence | Rolling summary plus insights writers | Two writers conflict; summary-of-summary drift | Narrative lag. Guard: T2 history covers the current episode | MAP §3 | [DERIVED] |
| X-13 | Lexical (PostgreSQL FTS) plus structured retrieval; vectors only on a measured trigger | Vector-first memory | No similarity-recall failure has been measured; vectors are a further store to erase | Paraphrase misses. Guard: the Lane 2 trigger (§G) | — | [DECISION←INFERENCE] [UNMEASURED] |
| X-14 | No graph DB, no Redis, no Kafka | A fashionable stack | No query or throughput needs them | Hot-read latency. Guard: a read replica or head cache (§P thresholds) | §G join depth | [DECISION←DERIVED] |
| X-15 | Durable outbox jobs; no fire-and-forget durable writes | `create_task` | Work is lost and cannot be fenced | DLQ build-up. Guard: a consumer plus alerting | MAP §3 | [DERIVED] |
| X-16 | Mode isolation for every learner | Only the extractor gated | Draft and eval sessions write patterns today | Eval needs production-like learning. Guard: the eval namespace | MAP §2 | [DERIVED] |
| X-17 | The D15 transfer rule (§D.7) | Strand memory; block transfers | J6 plus PI-10 | Mixed-lineage claims stay at the source. Guard: evidence is re-queued in the destination | Settled decisions | [DECISION] |
| X-18 | A deterministic context compiler, a `memory_profile` per agent, and tier budgets | "Inject everything" (today); LLM-selected context | Relevance, budget, reproducibility, manifests | Wrong budgets starve the prompt or waste tokens. Guard: per-agent config plus Lane 2 usefulness | MAP §2 | [DECISION] [UNMEASURED] budgets |
| X-19 | Keys and logs free of raw identifiers | Status quo | Identifiers in session ids flow into billing | Debugging gets harder. Guard: `explain` plus opaque-id lookup for operators | MAP §3 | [DERIVED] |
| X-20 | A database per physical tenant | One global database | The existing dedicated-tenancy model | Schema drift across instances. Guard: a single migration pipeline | `runtime.type=dedicated` | [DERIVED] |
| X-21 | Episode boundary at a 24 h gap or explicit close | LLM-detected topic boundaries | Deterministic and replayable | Long threads split badly. Guard: the value is config | — | [DECISION] [UNMEASURED] |
| X-22 | Cross-store ingest order: PG first, then Firestore, then a sweeper | A distributed transaction; Firestore first | Every piece of evidence is registered before it can be extracted; orphans are harmless | See §F orphan table | — | [DECISION←DERIVED] |

## Long-term view (3–5 years)

**At 10× volume.**
- Nothing in the design changes.
- Partitioning `claims`, `claim_support` and `memory_events` by `org_id` is planned at the §P thresholds.
- `memory_events` goes to cold storage (BigQuery export, ids only) after 90 days `[UNMEASURED]`.

**At 100× volume.**
- Shard by tenant group, one instance per shard. The Gateway routes by org.
- No query in the API spans orgs, so sharding needs no semantic change.
- The extraction cost dominates, so it is batched per subject and triggered by salience.

**Model churn.**
- Extraction is a versioned proposal protocol, and every model passes the gate.
- A model change is a Lane 1-real run plus an `extractor_version` bump. Re-extraction by version is possible because evidence is retained, subject to R-M3.

**Multi-region and data residency.**
- A physical tenant per region follows the dedicated-tenant pattern.
- Subject keys are under regional KMS. There is no cross-region replication of memory tables.

**New subject kinds** (devices, households) are new `subjects.kind` values plus new policy keys. The contract structure does not change.

## Missing dependencies (not in the workspace; the design depends on them)

| Repository or system | Needed for |
|---|---|
| `olbrain-noesis-os` | S0-1: the client queries on `agent_messages` must be inventoried before the rules change |
| `olbrain-voice-gateway` | ANI assurance level (§D.1); voice evidence ingestion |
| `olbrain-llm` | The extraction provider adapter (P15); subprocessor data flows |
| Billing service | `usage_events` pseudonymisation and erasure handler (§L.2) |
| GCP/Firestore live configuration (indexes, TTLs, backups, IAM) | The backup window, the restore drill, the Cloud SQL provisioning path |

## Blocked decisions (isolated behind policy boundaries; everything else proceeds)

| Decision | Owner | Boundary in the design |
|---|---|---|
| R-M1: persisted inference | Jay | Gate mode `inferred` (off) |
| R-M2: customer text in Agent Knowledge | Jay + Legal | The learner PII filter (strict default) |
| R-M3: evidence retention window | Jay + Legal | Evidence TTL (off) |
| R-M4: roles holding `memory:read` | Jay | Grant table |
| `ERASURE_ARCHIVE_WINDOW`; per-fact physical redaction; backup window | Legal | Orchestrator window (unset, so no physical deletion; alert) |
| Subprocessor retention and DPAs (Anthropic, Groq, Gemini) | Legal | Provider allowlist per org |
| An org's option to trust asserted end-user ids from its server | Security/Product | API-key flag (default off) |
| Operator authority rank per predicate | Domain owners | Policy registry (default: equal ranks, which gives CONFLICT) |
| Billing records' legal basis versus erasure | Legal | Pseudonymous keys (P3); handler returns `retained_legal_basis` |

## Contract changes this package adds (drafted, not applied)

These come on top of RECON E1–E13 and the `pending_erasure` addendum.
1. §2 `:137`: add the **ACCOUNT** and **RELATIONSHIP** scopes, and define PERSON as the identity-authority subject.
2. §1: **Agent Knowledge** is a stored class. It is guidance, is never assertive about a subject, and needs lineage or no person text (P12). It is aggregate data under §10 `:796`.
3. Identity assurance: memory continuity requires an assurance level. An asserted identifier never reads memory established at a higher level.
4. §10: the **Lifecycle Registry**, plus completeness: erasure is complete only when every registered store is.
5. §9: mode isolation (P14).
6. Ex.20: `SUPERSEDED` is a derived result status (F-10).
