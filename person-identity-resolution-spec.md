# Identity Resolution Specification — automatic person resolution, merge, and undo

Date: 2026-09-28. Read-only investigation. **Scope:** what an engineering specification must
contain to implement Jay's J1, J2, J3 and J5. **Not in scope:** PostgreSQL schema, security
remediation, memory-tier design, and any unresolved product or contract question — those are marked
`[UNRESOLVED]` where they block a detail, and left unanswered.

**This document specifies requirements, not designs.** Where more than one mechanism satisfies a
requirement, mechanisms are compared and none is chosen.

Labels: `[CONTRACT]` normative text · `[CODE]` verified at a named commit · `[DATA]` measured ·
`[DERIVED]` follows necessarily from Jay's answers, the contract, or code · `[INFERENCE]` reasoning
beyond strict derivation · `[UNRESOLVED]` needs a human answer · `[UNMEASURED]` needs unavailable
data · `[UNMEASURABLE]` no ground truth exists.

**Evidence base** — re-fetched 2026-09-28, unchanged since the derivation pass:
`olbrain-agent-runtime daee3f9` · `olbrain-agent-design c56271d` · `olbrain-shared d0e0d2b` ·
`olbrain-studio-backend 5da93ae` · `olbrain-research-design e218f10`.
Contract: `architecture-contract.md`, md5 `97c1fa3bcea1d71210c0429b1d113d07`, unmodified.

No production data was accessed. There are no `[DATA]` claims in this document.

---

## 1. Executive Summary

**Seven findings a specification must absorb.**

1. **There are eight person-keyed write paths, not three.** `[CODE]` Extraction writes two stores;
   operators write through two paths; lead capture writes a profile and an index; `agent_users` has
   its own upsert; a one-shot migration script also writes. The live agent datastore tool is **not**
   a person-keyed writer — extract-mode tables compile to no tools (§3).

2. **Identifiers arrive from two sources of very different reliability, and J5 does not distinguish
   them.** `[CODE]` Channel-supplied identifiers come from the transport (`from_number`,
   `from_email`). Lead-capture identifiers come from **the LLM's tool-call input** — values a caller
   dictated, transcribed by speech-to-text. The lead module's own history records STT mishearing a
   name. J5's "exact normalised phone or email match merges immediately" applies to both unless the
   spec says otherwise (§5.4, R1).

3. **The named interim resolver is a display fold, not a resolver.** `[CODE]` It runs on reads,
   over one page of lead profiles, persists nothing, takes the lexically smallest contact id as the
   person, and folds transitively. It satisfies none of J3's "evaluated on every person-keyed write"
   (§4).

4. **Full undo is impossible for one store under its current write semantics.** `[CODE]` +
   `[DERIVED]` `agent_user_memory` stores its facts as a list the LLM **regenerates in full every
   turn** — reworded, merged, dropped to fit a cap — with no per-fact provenance. Once two subjects'
   facts share a document and one more turn runs, which fact came from whom is gone. Undo can restore
   the identity *partition* in every store; it cannot restore *combined, regenerated content* (§8).

5. **A non-persistent undo is immediately reversed.** `[DERIVED]` J3 requires resolution on every
   person-keyed write; J5 merges exact matches immediately. So the next write carrying the same
   identifier re-merges the pair an operator just split. An undo that works must persist a record
   that prevents that — and a persistent record of "these two are not the same person" is a human
   identity decision, which J3 forbids. **J3 and J5 pull against each other here** (§8.4, R2).

6. **No write path is transactional across its read and its write, and four swallow failures.**
   `[CODE]` A resolver inserted into those paths inherits both properties unless the spec forbids it
   (§12).

7. **Nothing in the identifiers enforces J1's cross-organisation ban.** `[CODE]` The digest is the
   same in every org; the org value comes from a cached config file, a sender document, or a
   client-writable agent document, and **falls back to an empty string** (§10).

**Also verified this pass:** no automated entity-merge undo exists anywhere in the platform — three
precedents exist, each with a different mechanism and none with a restore path (§8.2). The platform's
audit mechanism is a structured log line, not a record that can be committed with a merge (§7.4).

---

## 2. Jay Policy Inputs

Authoritative, not reinterpreted. Full restatement in `j1-j6-derivation.md` §2. Per the task brief,
**Jay is the contract owner**; items the derivation routed to "contract owner" (U6, U16) therefore
route to Jay.

| ID | Requirement used in this document |
|---|---|
| **J1** | Same human recognised across channels within an org and across that org's agents. **Never across orgs.** |
| **J2** | Contract permits merges within an org, forbids them across orgs. Two `CUSTOMER` subjects in one org may resolve to one human. |
| **J3** | Identity authority is the Memory Gateway. Interim: agent-runtime's org-scoped `person_key` fold. **Purely code, evaluated on every person-keyed write. No human routes, approves or merges.** |
| **J4** | An LLM-extracted person-keyed row is not an identity assertion; key is system-asserted from the channel-supplied phone or email. *(Used only in §5.4 and §9; its object-class ambiguity, U5, is not resolved.)* |
| **J5** | Automatic. Exact normalised phone/email match within an org merges **immediately**. Weaker evidence merges above a threshold **the spec must state**. Every merge writes `merged_into` + an audit record. Every merge is **undoable**; operator may undo, **never approves**. Reuse `research_clients`' record shape, **not its trigger**. |
| **J6** | Used only in §11. |

---

## 3. Current Identity Write Paths

### 3.1 How the identifier enters

`[CODE]` `olbrain-agent-runtime daee3f9:core/lightweight_processor.py:4152-4156`:

```python
user_key = (getattr(user_message, "user_id", None) or "").strip()
user_key_kind = "identity"
if not user_key:
    user_key = (user_message.session_id or "").strip()
    user_key_kind = "session"
```

`user_id` is set per channel router — `from_number` (WhatsApp), `from_email` (email),
`sender_igsid` (Instagram), `phone_number or session_id` (directives/voice), `None` (web chat). So
the extraction key is either a channel identifier or, failing one, **the conversation id**, labelled
`session`. Extraction runs only when `self.is_production` (`:4144`) and is fire-and-forget
(`asyncio.create_task`, `:4203`).

### 3.2 Writer map

| # | Writer | Store | Identifier received | Key built by / from | Org source | Idempotent? | Race | Swallows? |
|---|---|---|---|---|---|---|---|---|
| **W1** | `write_extract_entry` — `olbrain-agent-runtime daee3f9:services/extract_entry_writer.py:37-108` | `agent_datastores/{agent}/tables/{table}/entries/{id}` | `user_key` from §3.1 | **System**, `person_hash(user_key)` at `:61`, from a caller-supplied value | Caller argument, originating in the processor's `organization_id` (§10.2) | **Yes** for the entry (deterministic id, `merge=True`); `values` fields last-writer-wins | Check-then-write, untransacted: `exists` (`:67`) → `count` (`:69`) → header `set` (`:79`) → entry `set` (`:100`). Two first writes both see "absent", both pass the cap, both stamp `created_at`. Header and entry are **separate RPCs** — one can land without the other | **Yes** — catches all, returns `None` (`:105-108`) |
| **W2** | `update_user_memory` — `services/agent_memory_service.py:232-428`, write at `:398-421` | `agent_user_memory/{agent_id}__{digest}` | same `user_key` | **System**, `memory_doc_id(agent_id, user_key)` — an inline copy of the `person_hash` digest | Caller argument | Doc id deterministic; **`facts` replaced wholesale** by an LLM-regenerated list (§8.3) | Read (`:276`) → LLM → write (`:421`), untransacted; concurrent turns for one person race on the full fact list | **Yes** — caller wraps in `try/except` and logs (`lightweight_processor.py:4199-4200`) |
| **W3** | `create_entry` — `olbrain-agent-design c56271d:app/services/datastore_service.py:356-451` | `agent_datastores` | Operator-supplied `user_key` | **System hashes, human chooses the input** — `person_hash(user_key)` at `:384` | `agents/{id}.organization_id`, read in the router (`app/routers/datastore.py:234`) | **Yes** — upsert on extract tables | Check-then-batch (`:401` → `:447`), untransacted | **No** — raises `WriteRefused`/`TableNotFound` |
| **W3b** | `update_entry` — same file `:454-509` | `agent_datastores` | Entry id | Never re-keys: *"user_key cannot be changed on an existing row"* (`:473-477`) | — | Yes | `get` then `set`, untransacted | No |
| **W4** | `commit_import` — `app/services/datastore_import.py:195-291` | `agent_datastores` | Operator CSV `user_key` per row | **System**, `person_hash(user_key)` at `:206`; two rows hashing alike collapse with *"last row for this target wins"* (`:209`) | Router | **Yes** — retry-safe per chunk | Batched per chunk; atomic within a chunk, **not across chunks** (docstring `:10-15`) | No — raises `PartialImport` |
| **W5** | `scripts/migrate_extract_rows.py` (agent-design) | `agent_datastores` | Legacy memory documents | One-shot migration | — | — | — | *Not traced in depth* |
| **W6** | Lead profile write — `olbrain-agent-runtime daee3f9:core/lead_capture_tool.py:494-528` | `lead_profiles/{lead_profile_doc_id(agent_id, session_id)}` | **LLM tool-call input** (`details`) | **System**, per **call**, deliberately not per person (`:128-135`) | Caller; stamped only if present (`:507-508`) | Yes (`merge=True`) | — | Profile write does not swallow; see W7 |
| **W7** | `upsert_contact_refs` — `core/lead_contacts.py:429-480` | `lead_contacts/{org_id}__{sha256(contact)[:32]}` | Contacts **derived from W6's LLM-supplied fields** via `extract_contacts` (`lead_capture_tool.py:518`) | **System**, `lead_contact_doc_id` (`lead_contacts.py:410-419`) | Caller's `org_id`; **no org → no index write** (`:449-450`) | Refs de-duplicated by `profile_doc_id` | **Read-modify-write of the `refs` list, untransacted** (`:457-478`) — concurrent captures of one contact can lose a ref. Email and phone docs written separately | **Yes** — caller logs and continues (`lead_capture_tool.py:533-544`); docstring calls the index *"best-effort by contract"* |
| **W8** | `upsert_agent_user` — `services/firebase_service.py` | `agent_users/{auto-id}` | `channel_user_id` | **Composite lookup**, not a key: query on `(agent_id, channel, channel_user_id)` | `data["organization_id"]`, **create only**, default `""` | **No** | Query-then-`.add()` with an **auto-generated id**. Two concurrent first messages both find nothing and **both create a row** | **Yes** — logs, returns `None` |

### 3.3 Not a person-keyed writer: the live agent tool

`[CODE]` `DatastoreExecutor._add` writes `uuid.uuid4().hex[:12]`
(`core/tools/datastore_executor.py:338`). Extract tables never become tools: agent-design's compiler
returns no tool entries for them — *"An extract-mode table is filled by the runtime's memory
extractor, not by tool calls. No tools, by design"* (`olbrain-agent-design
c56271d:app/services/datastore_compile.py:251-255`) — and the runtime registers only named entries
(`core/llm_providers/anthropic_provider.py:1837-1846`). The tool's update and delete gate on the
row's `session_id` (`datastore_executor.py:433-435`), which person-keyed rows do not carry. **The live
tool is out of scope for identity resolution.**

### 3.4 Where the raw identifier survives

`[CODE]` This matters for re-keying and for undo:

- `agent_user_memory` stores it **in plaintext** as `channel_user_id: user_key`
  (`agent_memory_service.py:404`). Only the document *id* is hashed.
- `agent_users` stores `channel_user_id`, `phone_number` and `email` in plaintext.
- `lead_profiles` store LLM-supplied `fields` plus normalised `contact_email` / `contact_phone`.
- `agent_datastores` entries do **not** store it — only `user_key_kind` and `channel`.

### 3.5 What would have to move on a merge

| Store | Unit | Per-agent or org-wide | Combining two subjects means |
|---|---|---|---|
| `agent_datastores` | One entry per (agent, table, person) | Per agent | Two entries per shared table; `values` maps with per-field conflicts; no per-field origin |
| `agent_user_memory` | One document per (agent, person) | Per agent | Two documents per shared agent; fact lists LLM-regenerated each turn |
| `lead_profiles` | One per **call** | Per agent | **Nothing** — profiles are per call, not per person |
| `lead_contacts` | One per (org, contact value) | **Org-wide, shared by agents** | Two index docs (phone, email) with human-owned `status` |
| `agent_users` | One per (agent, channel, endpoint) | Per agent | Nothing moves — endpoints stay distinct; the subject maps many endpoints |

---

## 4. Existing Resolver Analysis

**The mechanism:** `build_people` — `olbrain-agent-runtime daee3f9:core/lead_people.py:141-233` —
called only from `list_lead_people_endpoint` (`routers/agent_memory.py:518-560`).

### 4.1 What it does, exactly

`[CODE]`

1. **Input:** one page of `lead_profiles`, as returned by `list_lead_profiles` (`agent_memory.py:540`).
   No other store is read.
2. **Keys:** for each profile, the `lead_contacts` document ids of its normalised `contact_email` and
   `contact_phone` (`_keys_of`, `:83-98`).
3. **Join:** keys that co-occur on one profile are unioned (`:166-171`). The comment is explicit:
   *"A profile holding both values is the only evidence this module has that two contact documents
   are one person."*
4. **Winner:** *"The LEXICALLY smaller root wins, always"* (`_Union.union`, `:76-80`), so the result
   does not depend on arrival order. The winning root becomes `person_key`.
5. **Transitivity:** union-find is transitive. Profile 1 (email E₁, phone P) and profile 2 (phone P,
   email E₂) yield one person holding E₁, E₂ and P.
6. **Disagreement:** where the contact documents' human-set `status` values differ, it reports
   `status_conflict: true` and picks deterministically by sort, rather than choosing silently
   (`_resolve_status`, `:112-128`).
7. **Leads with no usable contact** go to an `unidentified` bucket and are never merged (`:163-165`).

### 4.2 What it does not do

`[CODE]`

- **It does not run on writes.** Its only caller is a `GET` list endpoint.
- **It does not see the whole org.** The endpoint's docstring: *"A page boundary can split one
  person's calls across two pages, so `people` here means 'people as far as the loaded calls show'."*
- **It does not persist anything.** No `merged_into`, no audit, no stored `person_key`.
- **It does not read `agent_datastores`, `agent_user_memory` or `agent_users`.**

### 4.3 Properties a specification must know it would inherit

`[DERIVED]`

- **`person_key` is unstable.** Adding a profile whose key sorts lower re-roots the whole group. The
  module warns that *"Anything storing a `person_key` must therefore be re-pointable."* A spec that
  persists `person_key` as a subject id inherits root changes on new evidence.
- **One bad edge collapses two people.** Transitivity means a single profile carrying a misheard
  email joins two humans' complete histories.
- **Its evidence is capped.** `MAX_REFS_PER_CONTACT = 20` (`lead_contacts.py:52`); older refs are
  dropped silently (`:469`).
- **Its evidence is LLM-supplied.** Contacts derive from lead-capture tool input (§3.2 W6/W7).

### 4.4 A design reversal to record

`[CODE]` The lead model was built on the opposite assumption to J3. `lead_profile_doc_id`
(`lead_capture_tool.py:128-135`): *"The session id is the only identifier that is certainly correct,
and **the human reading the profile can merge by phone or name afterwards**."* J3 forbids human
merges. **J3 supersedes this, and the spec should say so explicitly**, because the lead console's
current behaviour — operators triaging per contact key — was designed around it (R6).

---

## 5. Exact-Match Resolution

### 5.1 Case A — exact phone match

*Org X: Subject A has phone P; Subject B has phone P. J5: merge immediately.*

What the spec must define, each derived from J5 plus §3–4:

| Element | Requirement | Basis |
|---|---|---|
| **Candidate lookup** | An org-partitioned index from normalised identifier to subject, consulted on **every** person-keyed write | `[DERIVED]` J3 + J5. `lead_contacts` has exactly this key shape (`{org_id}__{digest}`) but is derived, best-effort, capped and read-modify-write — it cannot serve as-is |
| **Normalisation** | One named normaliser. Three exist and disagree | `[UNRESOLVED]` **U2**. `lead_contacts` is digits-only and keeps national and international forms separate (`:180-205`); `person_hash` only strips and lowercases |
| **Transaction boundary** | The lookup, the triggering write and the merge record must commit together, or a concurrent write can observe a half-merged state | `[DERIVED]`. Today no path wraps read and write together (§3.2) |
| **Winner / loser** | A deterministic rule | `[UNRESOLVED]` **R3**. Precedents disagree: `build_people` uses lexical order; `research_clients` lets the caller choose (`"into"`, `org_research_clients.py:267`). J5 inherits the shape, not the trigger, so neither is inherited |
| **`merged_into`** | Written on the loser, naming the winner | `[JAY]` J5 |
| **Archival** | Loser archived, not deleted, and still resolvable | `[JAY]` J5 + `[CONTRACT]` *"Entity destructive merges — Rejected"* |
| **Audit event** | One per merge, committed with it (§7.4) | `[JAY]` J5 |
| **Idempotency** | Re-evaluating the same evidence must not create a second merge | `[DERIVED]` J3 re-evaluates on every write, so the same identifier recurs constantly |
| **Concurrency** | Two writes that each trigger merges touching the same subject must serialise | `[DERIVED]` §12 |
| **Cross-org protection** | The lookup key must include the org; the merge must assert both subjects share it | `[JAY]` J1/J2, `[DERIVED]` §10 |

### 5.2 Case B — exact email match

`[CODE]` Same table, with one normaliser difference: `normalise_contact_email` lowercases and trims
the whole address and rejects anything not email-shaped (`lead_contacts.py:170-177`). Provider-specific
equivalences are **not** applied. Whether they should be is part of U2, not decided here.

### 5.3 Case C — phone and email point at different subjects

*Subject A holds phone P; Subject B holds email E; new evidence carries P and E together.*

**What the system must detect** `[DERIVED]`: the evidence matches two *different* existing subjects
exactly — not one. Each identifier alone is an exact match. Together they assert A ≡ B.

**The unresolved decision** `[UNRESOLVED]` **R4**: is a join made through a single record carrying
both identifiers an *exact* merge (immediate, per J5) or *weak* evidence (threshold, per J5)? J5
names exact matching per identifier and does not address a join across two.

**What must not happen before that decision exists** `[DERIVED]`: the spec must not inherit a
default by omission. The only existing behaviour is `build_people`'s transitive fold (§4.1.5), which
**would merge A and B silently**. If the spec is silent on case C, an implementation that reuses the
interim resolver makes the decision without anyone having made it.

### 5.4 Which identifiers does "exact match" cover?

`[UNRESOLVED]` **R1 — the most consequential open question in this document.**

- J4 premises the key as *"system-asserted (the channel-supplied phone or email, hashed)"*.
- `[CODE]` Lead-capture identifiers are not channel-supplied — they are the LLM's tool-call input
  (`lead_capture_tool.py:499, 518`). The lead module records an STT mishearing (`:131`) and a case
  where the gateway supplied no number at all (`:5-8`).
- `[CODE]` The existing resolver's only evidence is these LLM-supplied values (§4.1.3).

So J5's immediate-merge rule could fire on a dictated email the transcription got wrong, joining two
different people automatically, with the agent then rendering one person's data to the other. **Jay
must say whether exact-match merging applies to conversation-extracted identifiers, or only to
channel-supplied ones.**

---

## 6. Weak-Evidence Resolution

J5 permits merges on weaker evidence above a threshold the spec must state. **No threshold is
proposed here.**

### 6.1 What evidence exists today

`[CODE]`

| Evidence | Where | Form | Strength as recorded |
|---|---|---|---|
| Email and phone on one profile | `lead_profiles.contact_email` / `contact_phone` | LLM-supplied, normalised | The only explicit identity relation in the platform (§4.1.3) |
| Same identifier string on two channels | `agent_users`, many rows per `channel_user_id` | Endpoint rows | Exact string, not two identifier types |
| Display name | `agent_users.display_name`; lead `fields` | Free text | Recorded, never used for resolution |
| Session continuity | — | — | **None.** No record links two sessions as one person |

### 6.2 What the resolver cannot see

`[CODE]` Information already lost before any resolver runs:

- Refs beyond the newest 20 per contact (`lead_contacts.py:469`).
- Which turn produced a fact — facts are unattributed strings (§8.3).
- Every session but the last on an extract row — `last_session_id` is overwritten each write.
- Which writer last set a given `values` field — `updated_by` is per row and is **not** cleared when
  the extractor later overwrites a field, so it can name an operator for a value the extractor wrote
  (`datastore_service.py:414`, `extract_entry_writer.py:87-100`).

### 6.3 Where the threshold must live

`[DERIVED]` J5 says the spec states it. Two consequences follow from J3 and J5 together:

- It is a **declared value in the specification**, evaluated by code (J3: *"purely code"*). It is not
  a model output and not an operator setting.
- **Every weak merge's audit record must identify the threshold in force.** Otherwise, once the
  threshold changes, the audit cannot explain why a past merge happened, and an undo cannot tell
  whether a merge would still occur today.

`[UNRESOLVED]` **U3** stands: the value, and whether a confidence threshold for identity is
compatible with `[CONTRACT]` §6's prohibition on selecting authoritative values by confidence.

### 6.4 Safety invariants specific to weak merges

`[DERIVED]`

- Same org only (J1/J2).
- Undoable (J5).
- Recorded with the evidence that crossed the threshold, not only the score — a score alone cannot be
  audited.
- `[INFERENCE]` The consequences of a wrong weak merge are the largest of any merge class: the
  evidence is weaker by definition, the merge is automatic, and the agent renders merged data into
  the next reply. Undo cannot retract what was said (§8.5).

---

## 7. Merge Transaction Semantics

### 7.1 Two classes of merge implementation

`[DERIVED]` Every store in §3.5 admits one of two treatments:

- **Data-moving merge** — rows are rewritten under the winner's key and the loser's rows are
  combined into them.
- **Resolution-only merge** — rows keep their keys; a subject mapping changes; reads resolve through
  the mapping.

**Neither is chosen here.** Their consequences for undo are decisive and are developed in §8.
`[CODE]` `research_clients` is a resolution-only merge: *"Nothing rewrites the runs — they keep the
free-text name they were created with, and the roster resolves them through aliases at read time.
That means a merge is reversible by editing aliases"* (`org_research_clients.py:257-264`).

### 7.2 Per-store transaction scope

| Store | Data-moving merge must | Resolution-only merge must |
|---|---|---|
| `agent_datastores` | Combine two entries' `values` maps per table and per agent; resolve per-field conflicts. `[JAY]` D1(b) says operator wins, which requires **per-field authority markers that do not exist** | Record membership; reads resolve both entries |
| `agent_user_memory` | Combine two fact lists into one document | Record membership; reads resolve both documents |
| `lead_contacts` | Reconcile two human-owned `status` values | Record membership |
| `lead_profiles` | Nothing | Nothing |
| `agent_users` | Nothing | Nothing — endpoints are members, not subjects |

### 7.3 Precedent transaction behaviour

`[CODE]` Not reusable as-is:

- `research_clients` merge is **two separate `update()` calls** (`org_research_clients.py:294-300`),
  not a transaction. A failure between them leaves the survivor holding the loser's aliases while the
  loser is still live.
- Organization merge is an operator script: dry-run by default, `--apply` to write, snapshots to a
  local `--snapshot-dir`, and an append-only JSONL audit log that *"enable a manual rollback"*
  (`olbrain-studio-backend 5da93ae:scripts/merge_organizations.py:12-16`).

### 7.4 The audit record cannot be the existing audit mechanism

`[CODE]` The platform's audit mechanism, `olbrain_shared.agent.audit`, emits a structured log line to
stdout that Cloud Run lifts into `jsonPayload` (`olbrain-shared
d0e0d2b:src/olbrain_shared/agent/audit/schema.py:1, 29-64`). agent-design emits one per operator
write (`app/routers/datastore.py:111-140`).

`[DERIVED]` That is an observability record, not a system of record. It cannot be committed
atomically with a Firestore merge, so the merge and its log line can disagree. It is subject to log
retention, and it cannot be queried by undo. J5's "audit record" — which undo must read (§8) —
therefore needs to be a **durable record written in the same transaction as the merge**. The log line
may also be emitted, but it is not sufficient.

---

## 8. Undo / Unmerge Semantics

### 8.1 The scenario

```
Before:   Subject A        Subject B
Merge:    B.merged_into = A
After:    new evidence, memory and claims arrive against A
Undo:     an operator requests undo
```

### 8.2 No platform precedent provides undo

`[CODE]` Searched across all 13 repositories. The only "rollback" hits are deployment, config-version
and template-version rollbacks. For entity merges:

| Precedent | How it is reversible | Undo mechanism that exists |
|---|---|---|
| `research_clients` | By construction — references are resolved through aliases at read time and never rewritten | **None.** Routes are list, put, delete, merge only |
| Organization merge | Pre-merge snapshot + JSONL audit | **None automated.** Snapshot to a local directory; manual rollback |
| `lead_people` | Recomputed from evidence on every read | **None needed or present** — nothing is persisted |

### 8.3 Why undo cannot always be complete

`[CODE]` The extractor's system prompt (`agent_memory_service.py:40-50`):

> *"Return the UPDATED COMPLETE list of facts … Update or remove facts the new turn contradicts or
> resolves; keep still-true facts verbatim … Prefer dropping the least useful old fact over exceeding
> the cap."*

The input is the current facts plus the latest turn (`:299-304`). The output replaces the stored list
(`:405`). Facts are plain strings with no source, session or turn.

`[DERIVED]` If A's and B's facts ever share one document and one more turn runs, the result is a
single list regenerated by an LLM — reworded, merged, some dropped — with no field saying which
subject any fact came from. **It cannot be split.** The same holds more weakly for `agent_datastores`
`values`: a post-merge write overwrites a field with no record of which subject's evidence produced
it.

### 8.4 Undo is reversed by the resolver unless it persists

`[DERIVED]` J3 evaluates resolution on every person-keyed write. J5 merges exact matches
immediately. After an operator undoes the merge of A and B, the next write carrying the shared
identifier matches both again — and merges them again. **An undo that records nothing lasts until
the next message.**

For undo to hold, something must tell the resolver not to re-merge that pair. That is a persistent
statement that two records are **not** the same human — an identity decision taken by a person. J3
says *"no human routes, approves, or merges records by hand"*; J5 says *"an operator can undo"*.

`[UNRESOLVED]` **R2.** Either a persisted undo is permitted as the one human identity act J3 allows
(and the contract should say so), or undo is not durable. This is a question about the meaning of
Jay's two answers together, and only Jay can answer it.

### 8.5 What undo can and cannot mean

`[DERIVED]`

| Layer | Can undo restore it? | Condition |
|---|---|---|
| **The identity partition** — which identifiers belong to which subject | **Yes** | The merge record preserves pre-merge membership |
| **Post-merge writes routed back to the right subject** | **Only if attributed** | Each write records the identifier or endpoint that produced it, *and* storage was not combined |
| **Combined, regenerated content** — merged fact lists, overwritten fields | **No** | It can only be discarded, restored from a snapshot, or re-derived |
| **Content already shown to a customer** | **Never** | What the agent said cannot be withdrawn (N12) |

**Answer to the critical question** `[DERIVED]`: an automatic merge **cannot be fully undone** once
new information has been written against a merged subject whose storage was combined. It can be
undone at the identity layer always, at the write-routing layer only with attribution, and at the
content layer only by losing post-merge content.

### 8.6 What must be preserved for undo to work at all

| Item | Needed because | Status today |
|---|---|---|
| **Merge record** — id, winner, loser, evidence, threshold version, time | Undo must know what was merged and why | `[CODE]` Absent in the person stores |
| **Pre-merge membership** | The partition cannot be restored without it | Absent |
| **Write attribution** — which identifier or endpoint produced each post-merge write | Routes post-merge writes back | Partial: extract rows record `channel` and `last_session_id`; memory docs record `channel_user_id`; no store records it per field or per fact |
| **Per-field / per-fact provenance** | Separates combined content | Absent |
| **Merge ids on dependent merges** | A chain A←B, A←C must undo in order | Absent |
| **A non-re-merge record** | §8.4 | Absent, and policy-dependent (R2) |
| **Timestamps / versions** | Ordering of merge vs writes | Partial: `updated_at` exists, no version counters |
| **Deterministic replay** | Only if replay is the mechanism | **Impossible for LLM-regenerated facts** unless the LLM output of every turn is itself stored |

### 8.7 Mechanisms compared

**None is chosen.**

| Mechanism | Precedent | Undo restores | Cost | Fails when |
|---|---|---|---|---|
| **M-A Resolution indirection** — rows keep their keys; the merge is a mapping | `research_clients` | Partition always; post-merge writes if keyed per identifier | Every read resolves through the mapping — a new dependency on the prompt path (N6) | Any store combines into the winner's storage |
| **M-B Snapshot and restore** | Organization merge | Pre-merge state exactly | Discards all post-merge content; snapshots contain PII, so their retention needs classifying — G5, which is parked | Post-merge content matters |
| **M-C Derived recomputation** — subjects recomputed from evidence | `lead_people` | Anything, by retracting the evidence edge | Full evidence retention; org-wide recompute; `person_key` unstable | Evidence is capped or lost (§6.2) |
| **M-D Event-sourced replay** | None | Anything replayable | Every write as an attributed event | Facts are regenerated by an LLM, so replay does not reproduce them |

`[DERIVED]` Only M-A and M-C avoid destroying the pre-merge boundary, and both require that
`agent_user_memory` facts are **not combined into one document**. That is a constraint on the
specification, not a choice between mechanisms.

### 8.8 Chained merges

`[UNRESOLVED]` **R7.** If A←B and then A←C happened, and C's merge was triggered by evidence that
arrived through B, does undoing B→A also undo C→A? `research_clients` flattens aliases on a two-step
merge (`:286-287`), so its alias set alone cannot answer that.

---

## 9. Evidence / Claim / Current State / Memory Interaction

`[CODE]` None of the five object classes exists as such in code. The mapping below is between the
**operations** a merge performs and the contract's rules, not between stores and classes.

| Operation | Reversible? | Contract basis |
|---|---|---|
| **Change identity resolution** — the mapping between identifiers and subject | **Yes** | `[CONTRACT]` Precedent: *"A1 RESOLVES_TO iphone_17_pro → REVOKED. A1 and its evidence are untouched."* |
| **Rewrite historical records** — re-subject past Evidence or Claims | **No — and the contract resists it** | `[CONTRACT]` Evidence is append-only; valid time and system time *"MUST NOT be collapsed"*; *"Entity destructive merges — Rejected"* |
| **Change Current State** | **Yes**, if the underlying Claims were not rewritten | `[CONTRACT]` Current State is a projection, recomputed. Two authoritative values yield `CONFLICT`, recoverable via `RESOLVE_CONFLICT` (§6) |
| **Combine Memory** | **No**, for LLM-regenerated memory | `[CODE]` §8.3. `[CONTRACT]` Memory is non-assertive, so there is no `CONFLICT` to surface a bad combination |
| **Narrative Memory** | **Yes** if left session-scoped | `[CODE]` Session summaries carry no person key; they reach a person only through the session |

`[DERIVED]` The operations that preserve reversibility are the ones that change the mapping and leave
records alone. That is consistent with both the contract's revocation precedent and J5's undo
requirement.

`[UNRESOLVED]` **U5** affects this section's mapping. Whether future extract writes are Claims or
Memory (J4 vs D1(a)) decides whether a merge produces recoverable `CONFLICT`s or silent combination for
person attributes.

---

## 10. Cross-Organisation Safety

J1: never across organisations. **Absolute.**

### 10.1 What each identifier enforces

| Identifier | Carries org? | Cross-org exposure |
|---|---|---|
| `person_hash` | **No** — same digest in every org | `[CODE]` Any lookup keyed only on the digest matches across orgs |
| `memory_doc_id` | Agent prefix only | `[CODE]` Digest suffix identical across orgs; a suffix search crosses them |
| `lead_contacts` id | **Yes**, prefix | `[CODE]` Separation holds only as long as the prefix value is correct; the suffix is the same unsalted digest |
| `agent_users` | Field only; **create only**; default `""` | `[CODE]` The upsert query filters on `agent_id`, not org; a lookup by `channel_user_id` alone crosses orgs |

`[DERIVED]` **No identifier makes a cross-org match impossible.** The ban is enforced only by code
remembering to scope every lookup. D2 is not proposed here.

### 10.2 Where the org value comes from

`[CODE]`

- **Runtime:** `LightweightProcessor(organization_id=…)` (`lightweight_processor.py:1003-1051`). In the
  email router it resolves from a sender document, then `config["metadata"]`, then `config["agent"]`,
  and otherwise **`""`** (`routers/email.py:179-210`). The config is the GCS `active_config.json`,
  cached for `CONFIG_CACHE_TTL = 300` seconds (`lightweight_processor.py:98`).
- **Operator writes:** `agents/{id}.organization_id` (`agent-design app/routers/datastore.py:234`).
  At `olbrain-studio 1f05ca11` the `agents` collection remains outside both catch-all exclusion lists,
  so the source document is client-writable (S1).

### 10.3 Failure modes

`[DERIVED]`

| # | Failure | Consequence |
|---|---|---|
| FM1 | Candidate lookup keyed on digest without org | Merges across orgs |
| FM2 | **Empty org `""` treated as a partition** | Every org-less write lands in one pseudo-org and can merge with every other org-less write, across real orgs |
| FM3 | Stale org after transfer — cached config, and a best-effort patch (§11.3) | Writes resolve in the wrong org for up to 300 s per instance, or indefinitely if the patch failed |
| FM4 | Operator path reads a client-writable org | A tampered agent document changes where operator writes resolve |
| FM5 | Transfer brings origin-org evidence into the target org | Target-org merges built on evidence from another tenant (§11) |
| FM6 | `agent_users` org written once, possibly `""` | Endpoint membership unattributable to an org |

### 10.4 Enforcement points a specification needs

`[DERIVED]` From J1/J2 plus §10.3:

1. The org is part of the candidate-lookup key. A lookup without it is impossible to express.
2. The org value is non-empty and from an authoritative source. `""` is rejected, not partitioned.
3. The merge asserts both subjects' orgs are equal, in the same transaction.
4. Transfer splits before any target-org evaluation (§11).

---

## 11. J6 Transfer Interaction

*Org A: agents 1 and 2 both know Subject P. Agent 1 transfers to Org B.*

### 11.1 The sequence the policies force

`[DERIVED]` from J1, J2, J5, J6:

1. **Identify** every subject referenced by agent 1's person data.
2. **Split P.** J2 forbids a subject spanning orgs, and agent 2 stays in Org A. Agent 1's membership
   leaves P; P remains in Org A for agent 2.
3. **Move per-agent stores.** `agent_datastores` and `agent_user_memory` are keyed under agent 1 and
   move with it. Re-stamp their org.
4. **Re-key `lead_contacts`.** These docs are org-wide and shared (`refs` carry `agent_id`). Agent 1's
   refs are extracted from `OrgA__{digest}` and written into `OrgB__{digest}`.
5. **Target-org match.** If `OrgB__{digest}` already exists, that is an exact match within Org B, and
   J5 merges immediately.
6. **Audit lineage** records transfer → split → any resulting merge, in order.

### 11.2 Undo after transfer

`[UNRESOLVED]` (part of **U8**):

- A merge made in Org A before the transfer, involving agent 1's identifiers: can it still be undone
  after the split, and in which org?
- A merge triggered in Org B by arrival: undoing it separates agent 1's data from Org B's existing
  subject. Whether the evidence from Org A should count toward a Org B match at all is FM5.
- Does agent 1's arrival re-evaluate *past* Org B merges?

### 11.3 An ordering hazard

`[CODE]` The transfer patches `active_config.json` and `draft_config.json` in GCS, and its own
docstring calls this best-effort (`olbrain-studio-backend 5da93ae:services/agent_transfer_service.py:926-932`,
step 8 at `:1535-1545`). Concurrent moves are guarded by a precondition (`:3070-3080`). The runtime
caches that config for 300 s (`lightweight_processor.py:98`).

`[DERIVED]` Both self-healing stores re-stamp `organization_id` from the runtime's value on every
write (`extract_entry_writer.py:83`, `agent_memory_service.py:401`). So during the cache window, **writes
after the transfer re-stamp the old org** — undoing any cascade re-stamp that ran first. The cascade
in J6 must be ordered after the runtime serves the new org, or the writers must take the org from an
authoritative source.

---

## 12. Failure / Retry / Concurrency Behaviour

### 12.1 Current behaviour

`[CODE]`

| Writer | On failure | Concurrent behaviour |
|---|---|---|
| W1 extraction entry | Swallowed, returns `None` | Check-then-write; header and entry separate |
| W2 memory document | Swallowed by caller | Read-LLM-write on the full list |
| W3 operator create | Raises | Check-then-batch |
| W4 import | Raises `PartialImport`; retry idempotent | Atomic per chunk only |
| W6 lead profile | Raises | — |
| W7 contact index | Swallowed; *"best-effort by contract"* | Read-modify-write of `refs` |
| W8 `agent_users` | Swallowed, returns `None` | Query-then-add; **duplicate rows** |
| `research_clients` merge | Raises | Two updates, non-atomic |

### 12.2 What resolution on the write path inherits

`[DERIVED]`

- **Silent loss.** W1, W2, W7 and W8 already swallow. If resolution fails inside them and the spec is
  silent, the failure is silent too, on a fire-and-forget path behind a reply already sent.
- **Retry equals re-evaluation.** Every retry of a triggering write re-runs resolution, so merges must
  be idempotent under retry (§5.1).
- **Duplicate endpoints.** W8's duplicate rows would present one endpoint as two members of a subject.

### 12.3 When the resolver is unavailable

`[UNRESOLVED]` **U15.** Options that exist, none chosen: fail the write; write unresolved and reconcile
later; queue. J3 requires evaluation on every write, and the extraction path cannot surface failure to
anyone, so "write unresolved" contradicts J3 and "fail the write" loses data silently on that path.

### 12.4 Merges and deletion

`[CODE]` `scope_generation` exists in no repository. `[UNRESOLVED]` **U12**: whether a merge counts as
a deletion of the losing subject's scope, which decides whether in-flight writes against it are
fenced, and couples the answer to G8.

---

## 13. Required Invariants

Only invariants that follow from Jay's answers, the contract, or verified code.

| # | Invariant | Basis |
|---|---|---|
| I1 | No subject spans two orgs; no merge between subjects in different orgs | `[JAY]` J1, J2 |
| I2 | The org used for resolution is non-empty and authoritative | `[DERIVED]` from I1 and FM2–FM4 |
| I3 | Candidate lookup cannot be expressed without an org | `[DERIVED]` from I1 and FM1 |
| I4 | Resolution runs on every person-keyed write, in code | `[JAY]` J3 |
| I5 | No human approval precedes a merge | `[JAY]` J3, J5 |
| I6 | Every merge writes `merged_into` and a durable audit record, in the same transaction | `[JAY]` J5; transaction from `[DERIVED]` §7.4 |
| I7 | Merges are non-destructive: loser archived and resolvable | `[JAY]` J5; `[CONTRACT]` §14 |
| I8 | Every merge preserves enough to restore the pre-merge partition | `[DERIVED]` from J5's undo |
| I9 | Merges are idempotent under re-evaluation and retry | `[DERIVED]` from I4 |
| I10 | Given the same evidence, resolution produces the same result regardless of arrival order | `[DERIVED]` — an undo or audit that depends on arrival order cannot be reproduced. `[CODE]` The interim resolver already enforces this (`lead_people.py:76-80`) |
| I11 | Weak merges record the evidence and the threshold version applied | `[DERIVED]` §6.3 |
| I12 | The LLM does not decide a merge | `[JAY]` J3 *"purely code"* |
| I13 | Undo is durable against immediate re-merge — **or** it is explicitly declared non-durable | `[DERIVED]` §8.4; which one is **R2** |

---

## 14. Existing Code Changes Implied

**Implied by Jay's answers, not authorised.** No change is proposed here, only located.

| Repository @ commit | Location | What J1/J3/J5 require of it |
|---|---|---|
| `olbrain-agent-runtime daee3f9` | `services/extract_entry_writer.py:61` | Key derivation is the insertion point for resolution; its catch-all (`:105-108`) must be reconciled with I4 |
| same | `services/agent_memory_service.py:92-97, 398-421` | Key embeds `agent_id`, contrary to J1; fact regeneration is the undo-limiting behaviour (§8.3) |
| same | `core/lightweight_processor.py:4152-4156` | Session-keyed fallback: whether these are persons is **U4** |
| same | `core/lead_contacts.py:429-480` | The only org-scoped identifier index; untransacted refs, 20-ref cap, best-effort |
| same | `core/lead_people.py:141-233` | Named interim resolver: read-time, page-scoped, lead-only (§4) — does not meet I4 |
| same | `core/lead_capture_tool.py:128-135, 494-544` | Source of conversation-extracted identifiers (R1); per-call keying; human-merge design assumption (R6) |
| same | `services/firebase_service.py` `upsert_agent_user` | Non-idempotent create; org written once |
| `olbrain-agent-design c56271d` | `app/services/datastore_service.py:356-451` | Operator chooses the key input — must pass through resolution under J3 |
| same | `app/services/datastore_import.py:206-209` | Import collapses same-hash rows with last-row-wins — a merge with no audit |
| same | `app/routers/datastore.py:234` | Org sourced from the client-writable agent document (FM4) |
| `olbrain-research-design e218f10` | `app/routers/org_research_clients.py:252-302` | Record shape to reuse; merge is non-atomic; no undo |
| `olbrain-shared d0e0d2b` | `src/olbrain_shared/agent/audit/schema.py` | Audit is a log line; J5's record needs a durable companion (§7.4) |
| `olbrain-studio-backend 5da93ae` | `services/agent_transfer_service.py:926-946, 1535-1545` | Transfer cascade and config patch; ordering against the 300 s cache (§11.3) |

---

## 15. Unresolved Questions

### 15.1 New in this pass

| ID | Question | Blocks | Who |
|---|---|---|---|
| **R1** | Does J5's exact-match merge apply to **conversation-extracted** identifiers (lead capture, dictated and transcribed), or only to **channel-supplied** ones? | Whether the platform's only existing identity evidence can trigger automatic merges | **Jay** |
| **R2** | Is a persisted undo — "these two are not the same person" — permitted as the one human identity act, given J3? Without it, undo lasts until the next message | Whether undo is implementable as a durable operation | **Jay** |
| **R3** | Winner selection rule. Lexical (interim resolver) vs caller-chosen (`research_clients`); J5 inherits neither | §5.1 winner/loser; `person_key` stability | Shivam (spec) |
| **R4** | Is a join through one record carrying two identifiers an exact merge or weak evidence? | Case C (§5.3) | **Jay** |
| **R5** | Which human-owned `status` survives when two contact subjects merge? The interim resolver surfaces the conflict rather than choosing | `lead_contacts` merge | Shivam (spec) |
| **R6** | Confirm J3 supersedes the lead model's documented "the human … can merge by phone or name afterwards" | Lead console behaviour | **Jay** (confirmation) |
| **R7** | Does undoing a merge also undo later merges that depended on it? | Undo in chains (§8.8) | Shivam (spec) |
| **R8** | How the resolver treats an empty org | FM2 | Shivam (spec) |
| **R9** | Which identifier or endpoint produced each write must be recorded — currently only partially | Write-routing layer of undo (§8.5) | Shivam (spec) |
| **R10** | Do `agent_users` endpoints ever merge, or only map to subjects? | §3.5 | Shivam (spec) |

### 15.2 Carried forward, still blocking specific details

| ID | Blocks here |
|---|---|
| **U2** normalisation | What "exact" means in §5.1–5.2 |
| **U3** weak threshold | §6 entirely |
| **U4** IGSID / session-keyed rows | Whether §3.1's session fallback produces persons |
| **U5** J4 vs D1(a) | §9 mapping for person attributes |
| **U6** Gateway as `IDENTITY_SYSTEM` | Which authority writes the merge record — now routed to Jay |
| **U7** cross-agent visibility | Whether a resolution-only merge exposes agent 1's rows to agent 2's reads |
| **U8** transfer semantics | §11.2 |
| **U11** what undo restores | Superseded in part by §8.5, which states what it *can* restore; the choice remains |
| **U12** merge vs `scope_generation` | §12.4 |
| **U15** resolver unavailable | §12.3 |
| **D2** keyed / salted hash | §10.1 enforcement by construction |
| **D3** unrecoverable rows | Rows with no raw identifier cannot enter resolution (§3.4) |
| **D4** key form | Subject id vs `person_key` root (§4.3) |

---

## 16. Recommended Next Investigation

**Trace every read path that resolves a person.**

Every mechanism that preserves undo (M-A, M-C) moves the cost of identity from writes to **reads**:
each read must resolve a subject into its member identifiers and fetch across them. Nobody has mapped
those reads. Known ones include the three prompt-injection paths in `core/cs_packet_builder.py`, the
lead console and person-activity endpoints, the memory and datastore HTTP routes, and CSV export.

For each, the investigation would establish what key it reads by, whether it could resolve through a
mapping, what latency budget it sits in (the prompt path runs on every turn), and whether cross-agent
resolution would expose one agent's rows to another's reads — which is U7 in concrete form.

It is the highest-value next step because it decides whether the only mechanisms compatible with
J5's undo are viable at all, and it needs no decision from Jay to begin.
