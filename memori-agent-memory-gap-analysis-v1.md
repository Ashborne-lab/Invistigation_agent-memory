# Memori / Agentic Memory Capability Gap Analysis v1

**Date:** 2026-10-05.

**Classification:** architecture review (analysis only). No code, contract, schema, repository or infrastructure was changed.

**Labels:**
- **[MEMORI-PROVEN]:** stated in a Memori public source reviewed here;
- **[OLBRAIN-PROVEN]:** established by an OLBrain project artifact;
- **[INFERENCE]:** reasoning from comparing the two;
- **[UNKNOWN]:** the sources are insufficient;
- **[NOT ESTABLISHED BY PUBLIC SOURCE]:** Memori's public material is silent. This does **not** mean Memori lacks the property.

**Method note: a source-integrity incident.** The first automated summary of the arXiv paper (a fetch-and-summarise tool) attributed to it content it does not contain:
- procedural memory;
- agent-trace memory;
- conflict flagging;
- deletion controls;
- decay;
- graph traversal in retrieval.

That summary was **discarded**. Every claim below comes from:
- the paper's own extracted text (9 pages, read in full);
- the Memori documentation pages, fetched as raw HTML on 2026-10-05 and read in full.

---

## 1. Executive conclusion

**Memori does not reveal a fundamental hole in the OLBrain target architecture.** It mostly validates choices OLBrain already made, and it sharpens one existing, already-recorded gap: agent execution and procedural memory.

**What Memori validates.** Memori's core thesis is that memory is "a data structuring problem", not a storage problem. Its key moves [MEMORI-PROVEN, paper §1, §2.1]:
- distil dialogue into compact atomic units (semantic triples) plus conversation summaries;
- link each triple to its source conversation;
- inject a small, ranked set into the prompt.

OLBrain's target already has the stronger form of every element:
- typed Claims with explicit provenance back to Evidence;
- Narrative Memory (Episode summaries) as a separate, non-assertive layer;
- a Context Compiler with a budget and a manifest.

Memori's LoCoMo result (81.95% accuracy at 1,294 tokens per query, against a full-context ceiling of 87.52% at 26,031) is supporting evidence for OLBrain's "structured and budgeted, not raw history" direction. It is not evidence for any particular storage technology.

**What Memori does that OLBrain intentionally does not.** Memori resolves contradictions at answer time: its own answer prompt says "If the memories contain contradictory information, prioritize the most recent memory" (paper Appendix A).

OLBrain rejects recency-wins for important state:
- typed conflict status;
- authority, policy versions and OCC;
- deterministic admission before anything becomes truth.

These are deliberate differences toward governed truth, not gaps. The Memori public sources establish **none** of OLBrain's truth properties: immutable truth, policy governance, deterministic admission, OCC, replay equivalence, temporal correctness or erasure. They are [NOT ESTABLISHED BY PUBLIC SOURCE]. That does not prove Memori lacks them.

**What Memori shows that OLBrain's target genuinely lacks.** Memori markets **Agent Trace & Execution** memory [MEMORI-PROVEN, docs "Agent Trace & Execution", "How Memori Works"]:
- tool calls, decisions, workflow steps and outcomes are captured;
- they are structured into "precise, queryable records of facts, decisions, constraints, actions, tool results, and outcomes";
- they are paired with "rolling summaries";
- so agents "remember not only what users said, but what actually happened".

OLBrain's contract already counts "a trusted tool observation, a system observation, an agent decision" as **Evidence** [OLBRAIN-PROVEN, contract §1 line 22]. But the target has **no derived or retrievable form of agent execution history**:
- Episode summaries are generated "from USER, active evidence only" [OLBRAIN-PROVEN, `durable-home-episodes-commitments-decision-v1.md` S8];
- typed retrieval has no operation for "what did an agent do and with what outcome" [OLBRAIN-PROVEN, `memory-typed-retrieval-v1.md`];
- the AGENT scope is in the contract vocabulary but unsupported in the prototype (S-3).

This is a real capability gap for an agent platform. Its priority is **MEDIUM**, not HIGH: the current target use case is customer-state memory, and the capture layer (Evidence) already exists.

**Procedural memory.** Memori's public sources give **no object model, governance or lifecycle** for procedural or heuristic memory. "Attributes" are process-level notes ("Handles billing and subscription queries"); execution primitives are retrievable records. Nothing defines reusable strategies or how they are validated. Memori therefore **clarifies but does not change Decision 1b**.

The architecture freeze excluded procedural / heuristic memory from v2.0, and Patch 19 (D7) is still undecided. The comparison does sharpen the existing risk:
- production already has an ungoverned procedural store (`agent_learned_patterns`: verbatim user text, no org field, injected as "ground truth");
- exclusion from v2.0 means the target neither governs it nor replaces it.

That is an existing owner question (D7 / Decision 1b scope), not a new one.

**Scoping.** Memori scopes memory by caller-supplied `entity_id` / `process_id` / `session_id`. Its public material describes these as **attribution and isolation keys**, with the entity id set "from the authenticated user" by the application. It describes no server-side authorization binding [NOT ESTABLISHED BY PUBLIC SOURCE]. OLBrain separates attribution from authority: a subject reference alone is never authority (C-4), and handles and causal tokens are signed.

One design point is worth noting, not copying. Memori deliberately **shares entity facts across all processes (agents)** while keeping conversations per process. OLBrain's settled identity decisions (J1/J2) already choose one person across an org's agents, never across orgs. That is the same sharing direction, but with a tenant boundary Memori's docs do not state.

**Graph and vectors.** Memori's knowledge graph is semantic triples per entity, deduplicated by mention count and timestamps [MEMORI-PROVEN, docs "Knowledge Graph", "Advanced Augmentation"]:
- recall is vector similarity, plus BM25 in the paper's benchmark;
- the docs say only that recall "searches across both extracted facts and the knowledge graph";
- no graph traversal, multi-hop query or relationship API is documented.

Nothing in the Memori evidence meets OLBrain's recorded trigger for adding an embedding index (MAD §G.3: a measured paraphrase-recall miss that key synonyms cannot close). **The deferral of graph and vector infrastructure stands.**

**Verdict: CAPABILITY GAPS IDENTIFIED.** Two bounded gaps (agent execution memory; a governed home for procedural memory, already owner-routed) and one minor one (relationship retrieval). No redesign or reopening of any closed decision is warranted.

## 2. Memori architecture summary

**Components** [MEMORI-PROVEN, docs "Architecture"]:
- **SDK:** LLM-client wrapper plus attribution plus the Recall API.
- **Memori Cloud:** "processes captured conversations and agent trace".
- **Managed Storage:** "conversations, agent trace, sessions, and facts for each attribution scope".
- **Advanced Augmentation:** "fact extraction, embeddings, and knowledge graph construction".
- **Recall Engine:** "semantic search over stored memory, intelligent ranking and decay, and seamless injection".

**Data flow** [MEMORI-PROVEN, docs "Architecture", "Advanced Augmentation"]:
1. **Capture:** every wrapped LLM call is captured; "your app gets the response immediately".
2. **Attribution:** links each conversation to an entity and a process.
3. **Augmentation:** asynchronous, after a conversation completes. The engine "reads the full conversation (user messages and AI responses)", identifies facts, preferences, skills and attributes, extracts triples by named-entity recognition, and generates embeddings.
4. **Recall:** on the next LLM call, "embeds the query, performs vector search across the entity's stored facts, and injects the most relevant memories into the context" (automatic). `mem.recall(query, limit)` is also available, returning `id`, `content`, `similarity`, `rank_score`, `date_created`.

**Paper** (Borro et al., arXiv 2603.19935, 2026-03-20/23) [MEMORI-PROVEN]:
- **§2.1:** Advanced Augmentation is "a background memory creation pipeline". Triples come from "concrete facts, user preferences, constraints, and evolving attributes", and "each triple is then linked to the exact conversation in which it was mentioned". Conversation summaries carry "why a decision was made or how a user's goal evolved". Triples link to their conversation's summary.
- **§3:** the evaluation embeds triples with Gemma-300 and stores them in FAISS. Retrieval is "cosine similarity over embeddings with BM25 keyword matching". Answers come from GPT-4.1-mini; the judge is also GPT-4.1-mini (LLM-as-judge); the adversarial category is excluded.
- **§3.8:** temporal reasoning (80.37%) trails Zep and LangMem: "isolated semantic triples … often miss the temporal context needed to identify changes in user states".
- **The paper contains nothing on:** agent traces, procedural memory, multi-agent scoping, deletion, conflict handling beyond the answer prompt, provenance beyond the conversation link, or consistency.

## 3. Memori capability matrix

| Concept | Memori evidence | What is established |
|---|---|---|
| Conversational memory | Architecture; How Memori Works | Raw conversations captured and stored per entity + process + session [MEMORI-PROVEN] |
| Semantic facts / triples | Paper §2.1; Advanced Augmentation; Knowledge Graph | Subject–predicate–object, by NER, linked to the source conversation, deduplicated (mention count, timestamp update) [MEMORI-PROVEN] |
| Narrative summaries | Paper §2.1; Agent Trace ("rolling summaries") | Conversation summaries linked to their triples; rolling summaries for execution [MEMORI-PROVEN] |
| Agent execution traces | Agent Trace & Execution; How Memori Works | Tool calls, decisions, workflow steps and outcomes, sent by integrations (OpenClaw, Hermes, Claude Code) [MEMORI-PROVEN]. Record schema [NOT ESTABLISHED BY PUBLIC SOURCE] |
| Decisions / tool calls / failures / outcomes | Agent Trace & Execution | "which paths succeeded or failed"; "actions, tool results, and outcomes" [MEMORI-PROVEN, as capability statements] |
| Procedural / heuristic memory | — | **No public object model.** "Attributes" = process-level descriptions; execution primitives = records. Learned strategies with validation or lifecycle: [NOT ESTABLISHED BY PUBLIC SOURCE] |
| Attribution | How Memori Works; Multi-User Support | `entity_id` (who), `process_id` (agent / program / workflow), `session_id` (thread) [MEMORI-PROVEN] |
| Multi-agent sharing | Multi-User Support; Knowledge Graph | Facts, preferences, skills and the graph are per entity, shared across processes; attributes per process; conversations per entity + process + session [MEMORI-PROVEN] |
| Knowledge graph | Knowledge Graph | Triples connected per entity; nodes, edges, mention counts, first/last-seen times; used during recall [MEMORI-PROVEN]. Traversal queries [NOT ESTABLISHED BY PUBLIC SOURCE] |
| Embeddings | Architecture; Paper §3.2 | Vector embeddings on extracted facts [MEMORI-PROVEN] |
| Hybrid retrieval | Paper §3.3 | Cosine + BM25 in the benchmark [MEMORI-PROVEN]. Product recall is described as semantic search with a relevance threshold and an embeddings limit |
| Ranking / recall | How Memori Works | Similarity score, `rank_score`, threshold 0.1 by default [MEMORI-PROVEN]. The ranking formula [NOT ESTABLISHED BY PUBLIC SOURCE] |
| Async augmentation | Advanced Augmentation | Queued in the background; no response-path delay [MEMORI-PROVEN] |
| Decay / freshness | Architecture ("intelligent ranking and decay") | The word only. The mechanism [NOT ESTABLISHED BY PUBLIC SOURCE] |
| Conflict handling | Paper Appendix A | Answer prompt: prioritise the most recent memory [MEMORI-PROVEN, as the evaluation prompt]. Storage-level conflict semantics [NOT ESTABLISHED BY PUBLIC SOURCE] |
| Deletion / erasure | — | [NOT ESTABLISHED BY PUBLIC SOURCE] in the reviewed pages |

## 4. OLBrain mapping

| Memori capability | Memori evidence | OLBrain equivalent | Match | Notes |
|---|---|---|---|---|
| Raw conversation capture | Architecture | Evidence (user messages; contract §1) plus the evidence store (Lane A) | **PARTIAL** | Same role. OLBrain's evidence-store durability semantics are still owner-blocked (E-5) [OLBRAIN-PROVEN] |
| Triples (facts, preferences, constraints) | Paper §2.1 | Claims under Predicate Policies (subject, predicate, value), through the Claim Gate | **DIFFERENT-BY-DESIGN** | OLBrain predicates are registered and typed; the gate is deterministic; admission is policy-governed. Memori's NER triples have open predicates (`favorite_database`, `uses_with`) and no admission gate is described |
| Triple → source conversation link | Paper §2.1 | Claim provenance → Evidence ids (contract; gate) | **EXACT** in intent, **stronger** in OLBrain | OLBrain requires provenance; Memori states the link exists |
| Mention-count dedup | Advanced Augmentation | Idempotent commit and claim identity; corroboration is not a counter | **DIFFERENT-BY-DESIGN** | OLBrain never strengthens truth by repetition count. The settled scorer (council C10) is deterministic and versioned |
| Conversation summaries | Paper §2.1 | Narrative Memory: Episode generations (A1), `search_memory` | **PARTIAL** | OLBrain summaries are non-assertive, recorded generations, lifecycle-aware, from USER evidence only. There is no triple ↔ summary link in OLBrain retrieval [OLBRAIN-PROVEN] |
| Agent trace capture | Agent Trace | Evidence includes "a trusted tool observation … an agent decision" (contract §1) | **PARTIAL** | Capture is defined conceptually. No target derivation or retrieval exists (§5) |
| Execution primitives (actions, results, outcomes) | Agent Trace | Commitment events (create, confirm, start, fulfil, cancel) are durable journal facts (A1); `commit_outcome` entries | **PARTIAL** | Commitments cover promised actions only. General tool-call outcomes have no target object |
| Rolling execution summaries | Agent Trace | — | **MISSING** | Episode summaries exclude agent turns as summarised content |
| Process-level attributes | Advanced Augmentation | The AGENT scope in the contract vocabulary; Agent Knowledge (R-11) | **PARTIAL** | AGENT scope is unsupported in the prototype (S-3); Agent Knowledge has an undefined read scope (T-5) |
| Procedural strategies | — | Excluded from v2.0 (architecture freeze §2); D7 open | **UNKNOWN** on the Memori side; **excluded** on the OLBrain side | See §5 |
| Entity / process / session attribution | How Memori Works | CUSTOMER subject (org-scoped), agent, session; signed handles | **DIFFERENT-BY-DESIGN** | See §6 |
| Cross-agent fact sharing per entity | Multi-User Support | J1/J2: one person across an org's agents, never across orgs [OLBRAIN-PROVEN, Jay] | **PARTIAL** | The same direction, plus a tenant boundary |
| Knowledge graph | Knowledge Graph | `get_relationships` → `UNSUPPORTED_CAPABILITY` (no relationship model) | **MISSING** | Claim content is per subject; there are no inter-entity edges |
| Embedding recall | Architecture | No vector index; lexical and key matching; a measured trigger (MAD §G.3) | **DIFFERENT-BY-DESIGN** | Deferred on evidence |
| Hybrid (vector + BM25) | Paper §3.3 | Deterministic token matching (`search_memory`); typed operations | **DIFFERENT-BY-DESIGN** | Typed intent via the tool schema (contract line 657) |
| Automatic prompt injection | How Memori Works | Context Compiler: a separate data channel, budget, manifest; no unconditional injection | **DIFFERENT-BY-DESIGN** | OLBrain explicitly fixed unconditional injection, a current-production defect (INV §6) |
| Ranking and decay | Architecture | Freshness via Predicate Policy (`last_sync`, staleness budget G3); bitemporal validity | **UNKNOWN** | Memori's decay mechanism is not published, so no comparison is possible |
| Async augmentation | Advanced Augmentation | Async extraction from the evidence watermark → gate → commit (MAD §F) | **EXACT** on separation; **stronger** on authority | See §8 |
| Recency-wins conflict | Paper Appendix A | Typed CONFLICT + `RESOLVE_CONFLICT`; authority; OCC (STATE_CONFLICT) | **DIFFERENT-BY-DESIGN** | Recency-wins is rejected for important state (contract) |

## 5. Declarative, episodic, procedural and commitment memory

| Question | Declarative ("customer uses Y") | Episodic ("agent attempted X in task Y, outcome Z") | Procedural ("when X, strategy Y worked") | Commitment / action ("agent committed to X"; "X succeeded/failed") |
|---|---|---|---|---|
| 1. Modelled by OLBrain? | **Yes** | **Partly.** Conversation episodes yes; agent execution episodes no | **No: excluded from v2.0** | **Commitments yes.** Action outcomes generally no |
| 2. Where | Claim → Current State; Predicate Policy Registry; Claim Gate; commit; journal | Episode generations (journal A1), Narrative Memory; agent decisions are Evidence (contract §1, line 395) | Freeze §2; Decision 1b; D7 / Patch 19 open. Production: `agent_learned_patterns`, `ExceptionPattern` | `commitment_event` journal kind (A1); `commitments.project` head |
| 3. Authoritative or contextual | Authoritative (Claims) | Generation = authoritative **record**, non-assertive **content** | n/a in the target. Production injects `key_facts` as "ground truth" (INV §4.4), a contract rule-10 violation | Events authoritative; head is a projection |
| 4. Provenance | Required (Evidence ids) | Members' evidence ids; generator version | Production: up to 3 verbatim user messages; no org | Evidence-backed events |
| 5. Temporal evolution | Bitemporal; `state_version`; history | Generations; latest wins; `summary_status` | — | Typed transitions; expiry |
| 6. Retract / invalidate | Lifecycle, retractions (LA-9), erasure | Quarantine / regenerate-pending; erasure | — | Cancel / reopen events |
| 7. Safe reuse by another agent | Yes, within the org's CUSTOMER scope (J1/J2) | Within the subject's scope | Undefined (cross-customer aggregate → G5, parked) | Scope open (T-1) |
| 8. Authorization / scoping | CUSTOMER scope; Gateway binding (C-4) | CUSTOMER partition | Production: readable and writable by any signed-in user at the investigated rules revision (`store-inventory.md`); the later default-deny rules baseline (studio `9509fc1c`) was not re-verified for this collection here | T-1 open |
| 9. If missing: is it the 1b question? | — | **No.** Agent execution episodes are not procedures. They are records of what happened, and their capture class (Evidence) exists. The gap is derivation plus retrieval plus AGENT scope, **not** Decision 1b | **Yes:** exactly Decision 1b / D7 | Partly T-1 |

**Memori's side, per class:**
- **Declarative:** triples, facts and preferences [MEMORI-PROVEN].
- **Episodic execution:** "structured memory primitives … decisions, constraints, actions, tool results, and outcomes" plus rolling summaries [MEMORI-PROVEN, as capability statements; schema not published].
- **Procedural:** [NOT ESTABLISHED BY PUBLIC SOURCE]. The nearest statements are "which paths succeeded or failed" and "what context should shape future decisions", but no learned-strategy object, validation or lifecycle is described.
- **Commitments:** no distinct concept in the reviewed sources.

**[INFERENCE] The important distinction this comparison surfaces.**
- The freeze's exclusion covers **procedures**: recipes to replay.
- "Agent attempted X, outcome Z" is an **episodic record of facts about the past**. It fits OLBrain's existing classes: Evidence for the raw event, Narrative Memory for its summary, possibly Claims for outcome predicates on a resource.
- So agent execution memory need **not** wait for Decision 1b. It needs a scope (AGENT / RESOURCE) and a derivation rule.

## 6. Multi-agent and multi-user scoping

| Dimension | Memori [MEMORI-PROVEN unless marked] | OLBrain [OLBRAIN-PROVEN] |
|---|---|---|
| Organization | Not described in the reviewed pages; an API key per account [UNKNOWN] | Tenant boundary; never cross-org (J1/J2, X-rules) |
| Customer / person | `entity_id` ("person, place, or thing"), caller-supplied | CUSTOMER subject: an opaque, tenant-scoped id plus an HMAC identifier mapping (council C5/C6); merge with audit and undo (J5) |
| Agent | `process_id` ("agent, program, or workflow") | `agent_id` on evidence and episodes. AGENT scope unsupported in the prototype (S-3) |
| Process / workflow | Same `process_id` | Workflow memory is a separate production store; no target scope yet |
| Session | `session_id` (UUID per thread) | SESSION scope in the contract vocabulary; unsupported in the prototype |
| Resource | — | RESOURCE scope in the contract vocabulary; unmodelled |
| Ownership | The entity owns facts; entity + process + session own conversations | Subject partition owns its journal facts; journal is the sole ledger |
| Retrieval visibility | Facts and graph visible to all processes for the entity; attributes per process | Gateway: `may_read` over a Caller scoped to (CUSTOMER, subject), after handle binding |
| Agent-specific knowledge stays agent-specific? | Attributes are per process | AGENT-scoped state is not yet supported; production `agent_learned_patterns` is agent-keyed and org-less |
| Identifier = authority? | The docs show the app setting `entity_id` "from the authenticated user". No server-side binding of entity to caller is described [NOT ESTABLISHED BY PUBLIC SOURCE] | **No.** C-4: a subject reference alone is never authority. Signed conversation handles; Gateway-signed causal tokens (GW-G3) |

**[INFERENCE]**
- Memori's attribution keys are **scoping metadata**. OLBrain's handles are **capabilities**.
- The Gateway's signed-handle design is the boundary that makes cross-agent sharing safe: a caller may share only a subject it is bound to. Nothing in Memori argues for weakening that.
- The one transferable idea is **per-class sharing rules** (facts shared across agents, conversations per agent). OLBrain can express this through scope plus Predicate Policy; it is not a new mechanism.

## 7. Retrieval, graph and embeddings

**What these structures solve in Memori** [MEMORI-PROVEN, paper §2.1, §3]:
- noisy raw-chunk retrieval;
- token cost;
- recall of facts stated in varied wording (vectors), plus exact terms (BM25).

The graph is presented as making recall "richer"; no graph-specific query is documented.

| Retrieval problem | Typed Retrieval + Context Compiler today [OLBRAIN-PROVEN] | Status |
|---|---|---|
| Noise and token cost from raw history | Claims are compact; Context Compiler budget and manifest; no raw-history injection | **Covered** |
| Exact lookup by topic or key | `get_current_state` per predicate; `search_history` | **Covered** |
| Paraphrased recall over long narrative | `search_memory` uses deterministic token matching only | **Open but gated**: the MAD §G.3 trigger names episode summaries as the likeliest place it fires [INFERENCE] |
| Inter-entity relationships ("Alice's manager", "project uses FastAPI") | `get_relationships` → UNSUPPORTED_CAPABILITY | **Missing** (low demand evidence in the target use case) |
| Temporal change tracking | Bitemporal claims, `state_version`, history | **Covered**, and this is where Memori's paper reports weakness (§3.8) |
| Open-domain synthesis | — | Hard for every system in the paper (§3.8); no OLBrain requirement |

**Answers to the brief:**
1. These structures solve noise, cost, paraphrase recall and (claimed) relationship-rich recall.
2. Typed retrieval plus the compiler already solves noise, cost, keyed recall and temporal change.
3. Genuinely missing: a relationship model, and measured paraphrase recall over narrative.
4. No OLBrain evidence shows a current need for vector or graph infrastructure [OLBRAIN-PROVEN, MAD §G.3: no measured similarity-recall failure].
5. **No.** Memori's numbers come from LoCoMo (conversational QA, LLM-judged, adversarial category excluded). They measure retrieval quality, not graph necessity, and the paper's retrieval is triples plus vectors plus BM25, without graph traversal. **The deferral stands.** A relationship *capability* may be useful later, with its storage undecided.

## 8. Async derivation

| Aspect | Memori [MEMORI-PROVEN] | OLBrain [OLBRAIN-PROVEN] |
|---|---|---|
| Off the response path | Yes: queued after the response | Yes: watermark extraction after evidence (MAD §F) |
| Derivation engine | "The AI engine inside Memori Cloud"; NER for triples. Whether an LLM extracts facts is not explicit in the paper, though the docs call it "the AI engine" | The LLM proposes; the deterministic Claim Gate admits; commit at journal time |
| Becomes truth? | Extracted memories are stored and injected; no admission gate is described [NOT ESTABLISHED BY PUBLIC SOURCE] | **Never directly.** The gate and policy decide; episode summaries are non-assertive; "LLM extraction must not silently become authoritative truth" is an existing invariant |
| Reads AI responses? | "Reads the full conversation (user messages and AI responses)" | Assistant-reply contamination is a recorded production defect; target grounding is on user-authored evidence |

**[INFERENCE]**
- OLBrain already has the equivalent separation (evidence → deterministic admission/commit → async derivation), with a stronger authority boundary.
- One caution against copying: extracting memory from **AI responses** is exactly the contamination failure OLBrain fixed.
- Memori's derivation is described here as a derivation mechanism only. Its public sources establish no stronger semantics.

## 9. Genuine capability gaps

| Gap | Evidence | Why it matters | Already partially covered? | Priority |
|---|---|---|---|---|
| **G-A. Agent execution (episodic action) memory:** a derived, retrievable record of what agents did (tool calls, decisions, outcomes), scoped to agent / resource / subject | Memori docs "Agent Trace & Execution" [MEMORI-PROVEN]. OLBrain: Evidence includes tool observations and agent decisions (contract §1); Episodes summarise USER evidence only; no retrieval operation; AGENT scope unsupported (S-3) [OLBRAIN-PROVEN] | Multi-agent platforms repeat failed actions and lose task continuity without it. A real agent-memory capability, distinct from customer facts | **Yes:** capture class (Evidence), commitment events, Episode machinery and AGENT scope vocabulary all exist | **MEDIUM** |
| **G-B. A governed home for procedural / heuristic memory** | Freeze §2 excludes it; D7 / Patch 19 open; production `agent_learned_patterns` injects org-less verbatim-derived `key_facts` as "ground truth" (INV §4.4, S-M3) [OLBRAIN-PROVEN]. Memori publishes no model [NOT ESTABLISHED] | A live production capability with no target equivalent: migration would either drop it or carry it ungoverned. It is also a cross-customer aggregate (G5, parked) | **Yes:** fully captured as Decision 1b / D7; production defects recorded | **MEDIUM** (owner-bound; Memori adds no new requirement) |
| **G-C. Relationship retrieval** (inter-entity edges) | Memori knowledge graph [MEMORI-PROVEN]; OLBrain `get_relationships` unsupported [OLBRAIN-PROVEN] | Questions about relationships between entities; multi-hop | No relationship model; Claims are per subject | **LOW** (no demand evidence in the target use case) |
| G-D. Paraphrase recall over narrative | Paper §3.3 (vector + BM25) | Long, paraphrastic episode text | **Yes:** the measured trigger (MAD §G.3) | **NONE** (already governed by the trigger) |
| G-E. Decay-based ranking | Architecture "ranking and decay" (mechanism unpublished) | Prioritising recent memory | Freshness via policy; bitemporal validity | **NONE** (no comparable evidence) |

There are no HIGH or CRITICAL gaps.

## 10. Recommended future workstreams (at most 3)

**W1. Agent Execution Memory: scope and object mapping (analysis plus prototype design).**
- **Objective:** decide how agent tool calls, decisions and outcomes, already Evidence, are derived and retrieved:
  - which scope (AGENT, RESOURCE, or the CUSTOMER subject);
  - whether outcomes become Narrative Memory (execution summaries), Claims on resource predicates, or both;
  - which typed retrieval operation serves them;
  - how they are erased and fenced.
- **Why:** gap G-A. It is the one genuinely agent-specific capability missing.
- **Dependency:** S-3 (non-CUSTOMER scopes), T-1 (commitment scope), the Gateway's non-CUSTOMER read grants (Security / Product).
- **Owner decision:** **yes, for scope and authorization** (non-CUSTOMER grants were already flagged owner-bound in decision closure v1). The object mapping itself is engineering.
- **Stop condition:** each execution-record kind is mapped to an existing class, or shown not to fit (in which case stop and route to D7). No new object class is invented.

**W2. Procedural memory: D7 / Patch 19 decision support (owner packet refresh, not new research).**
- **Objective:** re-present D7 with three things:
  - the production evidence (`agent_learned_patterns` "ground truth" injection, verbatim samples, no org, G5 aggregate);
  - the Memori finding that no public model exists to borrow;
  - the W1 boundary (episodic records are not procedures).
- **Why:** gap G-B. Exclusion is a valid choice, but it leaves a live production capability without a target.
- **Dependency:** none.
- **Owner decision:** **yes**, contract owner (D7), plus Legal for G5 if procedural memory is cross-customer.
- **Stop condition:** the owner adopts or declines Patch 19, or chooses a v2.x scope extension. The investigation does not choose.

**W3. Relationship capability: demand check (deferred).**
- **Objective:** look in production or the use-case evidence for relationship-shaped questions before any model.
- **Why:** gap G-C, LOW.
- **Dependency:** production data access (unavailable; E-queries pattern).
- **Owner decision:** no.
- **Stop condition:** demand found or not found. No graph store is proposed either way.

## 11. Explicit non-gaps (do not copy)

- **Recency-wins conflict resolution** (paper Appendix A): OLBrain's typed CONFLICT, authority and OCC are deliberate.
- **Mention-count reinforcement:** repetition is not authority in OLBrain.
- **Automatic, unconditional prompt injection** of top-k memories: OLBrain fixed this production defect; the compiler is budgeted, typed and manifest-tracked.
- **Extraction from AI responses:** a known contamination path in OLBrain.
- **Open-vocabulary NER predicates:** OLBrain predicates are registered policies with authority domains.
- **Vector-first recall and a graph store as infrastructure:** no measured need (MAD §G.3).
- **Caller-supplied identifiers as the scope boundary:** OLBrain binds by signed handle (C-4, GW-G3).
- **Cross-process fact sharing by default:** OLBrain already decided the equivalent with a tenant boundary (J1/J2); nothing more to adopt.

## 12. Sources

**Memori (reviewed directly, 2026-10-05):**
- https://memorilabs.ai/docs/memori-cloud/concepts/architecture/ (primary)
- https://arxiv.org/pdf/2603.19935 (primary; Borro, Macarini, Tindall, Montero, Struck, "Memori: A Persistent Memory Layer for Efficient, Context-Aware LLM Agents", v1, 2026-03-20; read in full from extracted text)
- https://memorilabs.ai/docs/memori-cloud/concepts/how-memory-works/
- https://memorilabs.ai/docs/memori-cloud/concepts/advanced-augmentation/
- https://memorilabs.ai/docs/memori-cloud/concepts/agent-trace-execution/
- https://memorilabs.ai/docs/memori-cloud/concepts/knowledge-graph/
- https://memorilabs.ai/docs/memori-cloud/concepts/multi-user-support/
- https://memorilabs.ai/docs/memori-cloud/concepts/async-patterns/ (relevant only for the SDK's async I/O; no memory semantics)

**OLBrain:**
- `artifacts/architecture-contract.md` (§1 classes and Evidence definition; §2 scopes; §5 authority matrix; line 657 typed intent)
- `investigation/MASTER.md`
- `architecture-decisions.md` §1a/§1b
- `architecture-freeze.md` §2
- `d7-patch19-research.md`
- `decision-board.md` (D7)
- `senior-review-reconciliation.md` (D7 still open)
- `store-inventory.md` (`agent_learned_patterns`)
- `agent-memory-investigation.md` §4.4 and S-M3
- `memory-architecture-decision.md` §F, §G.3
- `memory-typed-retrieval-v1.md`
- `memory-context-compiler-v1.md`
- `durable-home-episodes-commitments-decision-v1.md`
- `memory-gateway-contract-v0.md` (v0.1)
- `memory-gateway-defect-decisions-v1.md`
- `target-architecture-decision-closure-v1.md` (S-3, T-1, T-5)
- `j1-j6-derivation.md` / `council-verdict-2026-09-28.md` (J1/J2, C5/C6, C10)
- `c5-real-storage-evaluation-v1.md` (context only; no storage conclusion drawn here)

**External facts vs OLBrain facts:** every statement about Memori is [MEMORI-PROVEN] from the URLs above, or explicitly [NOT ESTABLISHED BY PUBLIC SOURCE]. Every statement about OLBrain cites a project artifact. Comparisons are [INFERENCE].

## Decision 1b impact

> Does the Memori evidence materially change the existing unresolved OLBrain question about `agent_learned_patterns` / `ExceptionPattern` and procedural memory?

### **B. Clarifies the existing question**

1. **No object model to borrow.** Memori's public sources treat "agent trace & execution" as a mainstream agent-memory capability, but publish **no object model, validation or lifecycle for procedural or heuristic memory** [NOT ESTABLISHED BY PUBLIC SOURCE]. There is nothing to adopt, so the object model is not determined.
2. **The question splits more cleanly** [INFERENCE]:
   - **episodic execution records** ("agent did X, outcome Z") fit existing classes and need scope work (W1). They are **not** Decision 1b;
   - **procedures** (replayable strategies: `tool_sequence`, `ExceptionPattern.resolution`) remain exactly the question the freeze excluded and D7 would record.
3. **No sixth object class is required by this evidence.** The status quo stands: the freeze's v2.0 exclusion, with D7 open.

## Final verdict

MEMORI GAP ANALYSIS V1 — CAPABILITY GAPS IDENTIFIED
