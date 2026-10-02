# Person Read-Path Resolution — read-side dependency map

Date: 2026-09-28. Read-only investigation. **Purpose:** establish what would have to change on the
**read** side if identity resolution were represented as a mapping or lineage layer, instead of by
physically merging person data.

**This is a dependency map, not a solution.** It does not choose M-A, M-B, M-C or M-D, does not
recommend an identity architecture, does not design PostgreSQL, and does not answer U7.

Labels: `[CONTRACT]` · `[CODE]` verified at a named commit · `[DATA]` · `[DERIVED]` ·
`[INFERENCE]` · `[UNRESOLVED]` · `[UNMEASURED]` · `[UNMEASURABLE]`. No production data, credentials
or PII were accessed; there are no `[DATA]` claims.

---

## 1. Executive Summary

**Eight findings.**

1. **Three person reads run on every conversation turn, and each is a single direct get by a key
   computed from the channel identifier.** `[CODE]` Free-form memory reads one
   `agent_user_memory` document; datastore values read one entry per extract table; a third block
   writes the **raw identifier itself** into the system prompt. Each assumes the identifier names
   exactly one person (§4).

2. **None of the three turn-path reads checks `organization_id` on what it reads.** `[CODE]` The org
   is used only to look up the PII policy. The org boundary on the prompt path is entirely the
   `agent_id` in the document path (§12).

3. **One read already resolves through a mapping.** `[CODE]` The lead person-activity endpoint reads
   across **every contact key the console folded into the person**, because — in its own words —
   *"a merge must be a re-point, not a redesign."* The mapping it uses is supplied **by the client**,
   as a query parameter (§7.5).

4. **Cross-agent person reads already exist today.** `[CODE]` The `lookup_lead_contact` tool, which
   the LLM calls with a phone or email of its choosing, is org-scoped and **not** agent-scoped. It is
   deliberately minimal — it returns only `found`, `last_contact_at` and `status`. The lead console is
   org-wide with full data (§13).

5. **A cross-org person read exists in the browser.** `[CODE]` Studio holds a live client-SDK
   listener on `agent_users`, filtered only by an `agent_id` the client chooses. No rule covers
   `agent_users` except the catch-all, which permits any signed-in user. The payload includes raw
   phone numbers and email addresses (§8.3).

6. **Under a mapping, the assistant's own reply is a route by which another person's data enters a
   member document — with no explicit combine step anywhere.** `[CODE]` + `[DERIVED]` The memory
   extractor reads the latest turn *including the assistant's reply* (`agent_memory_service.py:303`).
   If the prompt read resolves across members, the reply can contain the other member's data, and the
   extractor then writes it into the current member's document. The partition becomes inseparable
   through ordinary operation (§11.2).

7. **Conversation history re-reads disclosed data every turn, and undo does not reach it.** `[CODE]`
   History is loaded per session from stored messages, so anything the agent said while two subjects
   were merged is re-sent to the model on every later turn of that session (§11.2).

8. **No person document or row is cached; the org value is.** `[CODE]` Person reads hit Firestore
   every turn, so a merge or undo is visible on the next turn. But the agent config (300 s) and,
   when enabled, the agent document (30 s) are cached — and they carry the org and the list of tables
   the prompt reads (§14).

**Inventory completeness.** Three repositories referenced as person-data readers are absent from the
workspace — `olbrain-agent-directives` (opt-out enforcement over `agent_users`),
`olbrain-voice-gateway` and `olbrain-webhook-service`. The inventory is complete for the 13
repositories present and **incomplete for the platform** (§17).

---

## 2. Evidence Base

Re-fetched 2026-09-28; all 13 unchanged from the prior passes today:

`olbrain-agent-runtime daee3f9` · `olbrain-agent-design c56271d` · `olbrain-studio 1f05ca11` ·
`olbrain-studio-backend 5da93ae` · `olbrain-shared d0e0d2b` · `olbrain-agent-eval 6c289ca` ·
`olbrain-agent-engine dfc3a47` · `olbrain-research-design e218f10` · `olbrain-research-runtime
6b81691` · `olbrain-workflow-runtime 2356de0` · `olbrain-knowledge-vault 25b46be` ·
`olbrain-mcp-deployer b75cc12` · `olbrain-finance-engine bf4d2b6`.

**Method.** Every non-test file in all 13 repositories referencing any of the five collections or
their constants (`MEMORY_COLLECTION`, `LEAD_PROFILE_COLLECTION`, `LEAD_CONTACT_COLLECTION`,
`AGENT_USERS_COLLECTION`, `USERS_COLLECTION`) was listed, then each call path was read. Files that
matched only by name (`brain_compiler.py`, `migrate_extract_rows.py`, `firestore_schemas.py`) or only
in comments (`olbrain-agent-eval agent_eval/chat/runtime_client.py:24`) were excluded after reading.

**Line numbers moved** in `core/cs_packet_builder.py` since earlier passes (the three person loaders
were at `:1875/1921/2017` at `8df0e02`; they are at `:1957/1983/2087` at `daee3f9`). Every citation
below is at the commit shown.

---

## 3. Complete Person Read Inventory

Column key — **Scope**: A agent, O org, S session, G global, E endpoint. **Raw id**: receives a raw
phone/email. **X-agent / X-org**: can see another agent's / org's records today. **Hash**: constructs
`person_hash`/`memory_doc_id`/contact id. **Fold**: uses `build_people`. **1=1**: assumes one person
is one physical document. **LLM**: result enters a prompt. **Op**: shown to an operator or user.
**Hot**: runs on every turn.

| # | Read | Repo @ commit · file · symbol | Store | Lookup key | Scope | Raw id | agent_id | org_id | X-agent | X-org | Hash | Fold | `merged_into` | 1=1 | LLM | Op | Hot |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **P1** | Free-form memory into prompt | runtime `daee3f9` `core/cs_packet_builder.py` `_load_user_memory_block` `:1957-1981` → `services/agent_memory_service.py` `load_user_memory` `:116` | `agent_user_memory` | `{agent_id}__{digest(user_id)}` | A | yes | yes | PII only | no | **no org check** | yes | no | no | **yes** | **yes** | no | **yes** |
| **P2** | Datastore values into prompt | same file `_load_person_records_block` `:1983-2078` | `agent_datastores` | `/{agent}/tables/{t}/entries/{person_hash(user_id)}`, one get per extract table (`:2054-2059`) | A | yes | yes | PII only | no | **no org check** | yes | no | no | **yes** | **yes** | no | **yes** |
| **P3** | Raw identifier into prompt | same file `_build_user_identity_block` `:2087-2131` | — (message) | `message.user_id`, sanitised | — | yes | — | PII only | — | — | no | no | no | **yes** | **yes** | no | **yes** |
| **P4** | Conversation history | same file, history load `:1455-1470`, `_format_history` `:1486` | agent messages | `session_id` | S | no | — | — | no | no | no | no | no | n/a | **yes** | no | **yes** |
| **P5** | Session summary | same file `_load_session_summary_and_anchor` `:1665` | agent sessions | `session_id` | S | no | — | — | no | no | no | no | no | n/a | **yes** | no | **yes** |
| **T1** | `lookup_lead_contact` tool | runtime `core/llm_providers/anthropic_provider.py` `:2950-3002` → `core/lead_contacts.py` `execute_lookup_lead_contact` `:646-712` → `lookup_contact` `:492-557` | `lead_contacts`, then `lead_profiles` | `{org}__{digest(LLM-supplied contact)}` | O | **LLM-supplied** | no | yes, from tool loop | **yes** | no — org in key + check `:522` | yes | no | no | per contact | **yes** (tool result) | no | only if called; ≤2/session |
| **W2r** | Extractor's read-before-write | `services/agent_memory_service.py` `update_user_memory` → `load_memory_doc` `:276` | `agent_user_memory` | `{agent_id}__{digest(user_key)}` | A | yes | yes | not checked | no | no org check | yes | no | no | **yes** | **yes** (extraction LLM) | no | yes, post-turn |
| **W1r** | Extract writer existence check | `services/extract_entry_writer.py` `:67` | `agent_datastores` | entry `person_hash(user_key)` | A | yes | yes | not checked | no | no | yes | no | no | **yes** | no | no | yes, post-turn |
| **H1** | Memory HTTP read | runtime `routers/agent_memory.py` `get_user_memory` `:48-86` | `agent_user_memory` | `{agent_id}__{digest(path channel_user_id)}` | A | **yes, in URL** | yes | **yes** — doc org must equal caller org (`:73`) | no | no | yes | no | no | **yes** | no | yes | no |
| **H2** | Lead profile HTTP read | same file `get_lead_profile` `:197-231` | `lead_profiles` | `lead_profile_doc_id(agent, session)` | A+S | no | yes | yes (`expected_organization_id`) | no | no | no | no | no | per call | no | yes | no |
| **L1** | Lead list | same file `list_lead_profiles_endpoint` `:488-517` → `core/lead_admin.py` `list_lead_profiles` `:143-249` | `lead_profiles` (+ status join from `lead_contacts` `:205`) | `organization_id ==`, ordered `updated_at` (`:169-170`) | O | no | no | yes, gated (`_leads_org_gate` `:432-485`) | **yes** | no | yes (status join) | no | no | per call | no | yes | no |
| **L2** | Lead "people" | same file `list_lead_people_endpoint` `:519-572` → `core/lead_people.py` `build_people` `:141-233` | `lead_profiles` page | as L1, then fold | O, page | no | no | gated | **yes** | no | yes | **yes** | no | **no** — N profiles → 1 person | no | yes | no |
| **L3** | Person activity | same file `list_person_activity_endpoint` `:574-612` → `core/lead_activity.py` `list_activity` | `lead_activity` | `person_key` **and every caller-supplied key**, in-memory org check | O | no | no | gated | **yes** | no — org checked in memory | no | client-side | no | **no** — reads N keys | no | yes | no |
| **L4** | Lead export | same file `:749` → `core/lead_export.py` `export_leads`, which gathers through `_gather` `:340` | `lead_profiles` | org + optional doc ids | O | no | no | gated | **yes** | no | no | no | no | per call | no | yes | no |
| **L5** | Erasure sweep (read half) | `core/lead_contacts.py` `erase_by_contact` `:715+`, sweep `:853-879` | `lead_profiles`, `lead_contacts` | contact field `==` value **and** org | O | yes | no | yes | **yes** | no | yes | no | no | **yes** — "one normalised contact IS one person" (`:828-833`) | no | yes | no |
| **D1** | Operator Data tab | agent-design `c56271d` `app/routers/datastore.py` `:143-200` → `app/services/datastore_service.py` `list_entries` `:202`, `export_csv` `:234`, `table_context` `:295` | `agent_datastores` | agent + table | A | no | yes | view-permission on the agent (`_require_view_permission` `:91-100`) | no | no | no | no | no | one row per (agent, table, hash) | no | yes | no |
| **U1** | agent_users upsert lookup | runtime `services/firebase_service.py` `upsert_agent_user` | `agent_users` | query `agent_id`, `channel`, `channel_user_id` | A+E | yes | yes | not in query | no | no | no | no | no | per endpoint | no | no | **yes**, inbound |
| **U2** | Studio "Users" live list | studio `1f05ca11` `src/services/settings/users/agentUserService.js` `:20-55` | `agent_users` | `where agent_id ==` (client-chosen), `orderBy last_seen_at` | A (client-asserted) | **returned** | client-chosen | **none** | client-chosen | **yes** (§8.3) | no | no | no | per endpoint | no | yes | no |
| **U3** | Outreach audience | studio-backend `5da93ae` `services/outreach_users_service.py` `list_agent_users` `:203+` | `agent_users` | `agent_id ==`, prefix search on name/phone | A | returned | yes | **deliberately not used** (`:10-14`) | no | no | no | no | no | per endpoint | no | yes | no |
| **U4** | Opt-out list and gate | studio-backend `services/outreach_optout_service.py`; enforcement in `olbrain-agent-directives` (absent) | `agent_users` | `agent_id`, per row | A+E | returned | yes | no | no | no | no | no | no | per endpoint | no | yes | no |
| **U5** | agent_users operator edit | agent-design `app/services/agent_user_service.py` `:100-126` | `agent_users` | document id | — | writes raw id | no | **no check** | — | — | no | no | no | per endpoint | no | yes | no |

---

## 4. Incoming Message → Prompt Call Graph

### 4.1 The path

`[CODE]` `olbrain-agent-runtime daee3f9`:

```
channel router  (e.g. routers/meta_whatsapp.py:965  user_id = from_number)
    │  API-key middleware: key org must equal agents/{id}.organization_id
    │    core/api_key_middleware.py:343-380   (agent doc cached ≤30 s if flag on)
    ▼
LightweightProcessor(agent_id, config, organization_id, …)   core/lightweight_processor.py:1003-1051
    │  config = _config_for_turn()  — GCS active_config.json, cached 300 s   :98, :352-369, :1823
    ▼
CSPacketBuilder(agent_id, config, organization_id, …).build(message)   :1299-1305
    │                                                cs_packet_builder.py:611
    ├─ system prompt from config (static, cacheable)                     :701
    ├─ P1  _load_user_memory_block(message)        → agent_user_memory   :790-799
    ├─ P2  _load_person_records_block(message)     → agent_datastores    :807-816
    ├─ P3  _build_user_identity_block(message)     → raw user_id         :822-827
    ├─ finance context (session-scoped)                                  :841-856
    ├─ P5  session summary + P4 history (session-scoped)                 :866-874
    ▼
provider tool loop   core/llm_providers/anthropic_provider.py
    ├─ T1 lookup_lead_contact  (voice; share-link opt-in)  → lead_contacts, lead_profiles   :2950-3002
    ▼
LLM reply
    ▼
post-turn extraction (fire-and-forget)   lightweight_processor.py:4146-4205
    └─ W2r load_memory_doc → LLM(CURRENT FACTS + user text + ASSISTANT TEXT) → W2 / W1 writes
```

**Order and failure handling.** P1, P2 and P3 run sequentially in that order. P1 and P2 are wrapped:
on any exception the packet is built *"continuing without"* (`:791-793`, `:808-810`). With
`PROMPT_CACHE_V2` on (`:636`), all three ride the uncached dynamic tail (`:795-827`); with it off they
are appended to the system prompt, and the code notes *"Flag off there is no cached prefix to
protect"* (`:852-853`).

**Where the lead tools exist.** `record_lead_detail` and `lookup_lead_contact` are registered on the
voice profile (`core/channel_profiles.py:496`) and on `share-link` web chat for agents that opted in
(`:587-588`).

### 4.2 The ten questions, per prompt path

| Question | P1 memory | P2 datastore values | P3 identity | T1 lead lookup |
|---|---|---|---|---|
| 1. Identifier used | `message.user_id` (`:1972`) | `message.user_id` (`:2018`) | `message.user_id` (`:2114`) | Phone/email **the LLM passes** (`anthropic_provider.py:2960-2961`) |
| 2. Documents read | `agent_user_memory/{agent}__{digest}` | One entry per extract table under `agent_datastores/{agent}` | None | `lead_contacts/{org}__{digest}`, then profiles via its `refs` until one exists (`:534-543`) |
| 3. One or many | **One** | One **per table** | — | One contact doc per supplied value, first hit wins (`:512-556`) |
| 4. Assumes id = one human | **Yes** — the extractor prompt describes a profile of *"one end-user"* (`agent_memory_service.py:40`) | **Yes** — one row per person per table | **Yes** — "the user identified as" | Treats a contact as one returning person |
| 5. Where a mapping would resolve | Before `load_user_memory` (`:1980`) | Before the entry-id derivation (`:2050-2051`) | Not a store read; unaffected | Before `lead_contact_doc_id` (`lead_contacts.py:515-517`) |
| 6. Change on undo | The member set shrinks; reads fall back to the current identifier's own document | Same, per table | None | `status` / `last_contact_at` may come from a different member |
| 7. Can contain another person's data today | **Yes** — any identifier shared by two humans (§11.3) | **Yes**, same | **Yes** — the identifier of a shared endpoint | Only `found` / `status`; no stored details by design (`:501-504`) |
| 8. Scoped by org | **No** — org consulted only for PII policy (`:1976`) | **No** — table header org not read | — | **Yes** — org in key and checked (`:510, :522`); empty org → not-found (`:666-669`) |
| 9. Scoped by agent | **Yes**, by path | **Yes**, by path | — | **No** — any agent's capture in the org |
| 10. Authorization between identity and prompt | None beyond the inbound API-key/org gate (§4.1) | None | None | Per-session budget of 2 (`:80-120`) and a minimal payload |

---

## 5. `agent_datastores` Read Paths

### 5.1 Every read

| Read | Location | Purpose | Key |
|---|---|---|---|
| **P2** prompt values | `cs_packet_builder.py:1983-2078` | Person's extract rows into prompt | `person_hash(user_id)` per extract table |
| **W1r** writer existence check | `extract_entry_writer.py:67-69` | Upsert vs. new row + cap | `person_hash(user_key)` |
| Operator create existence check | agent-design `datastore_service.py:401` | Upsert + cap | `person_hash(user_key)` |
| Import existence check | agent-design `datastore_import.py:248` | Carry `created_at` | entry id |
| **D1** Data tab list / CSV / context | agent-design `datastore_service.py:202, :234, :295`; router `:143-200` | Operator view | agent + table, paged |
| Live tool `_list` / `_owned_entry` | runtime `core/tools/datastore_executor.py:369, :409-436` | Tool tables only | session or table scope — **extract tables have no tools** (`agent-design datastore_compile.py:251-255`) |

### 5.2 Is `agent_id + person_hash` assumed to be exactly one person?

`[CODE]` **Yes, everywhere a person-keyed row is read.** P2 derives one entry id and does one `get`
per table. The writer and operator paths check existence of that one id to decide "new person or
upsert". The Data tab lists rows, so two rows can already represent one human — the same person on
WhatsApp and email is two rows — and nothing groups them.

### 5.3 Is the hash used directly as an identity boundary?

`[CODE]` **Yes.** The hash of whatever `user_id` the channel supplies *is* the selector of which
person's data enters the prompt (`:2050-2059`). There is no second check that the row belongs to the
person on the line — the row id is the check. The table header's `organization_id` is never read on
this path.

---

## 6. `agent_user_memory` Read Paths

### 6.1 Every read

| Read | Location | Key | When |
|---|---|---|---|
| **P1** prompt block | `cs_packet_builder.py:1980` → `load_user_memory` (`agent_memory_service.py:116`) | `{agent}__{digest(user_id)}` | Every turn, before P2 and P3 |
| **W2r** extractor read | `agent_memory_service.py:276` `load_memory_doc` | `{agent}__{digest(user_key)}` | After the reply |
| **H1** HTTP read | `routers/agent_memory.py:48-86` | path `channel_user_id` | Operator / API |
| HTTP delete (read-then-delete) | `routers/agent_memory.py:88-110` → `delete_user_memory` (`agent_memory_service.py:498-527`) | same, with `expected_organization_id` | Operator / API |

### 6.2 The eight questions

1. **Every read** — the four above.
2. **Keyed by** — the current `user_key` (or path `channel_user_id`) plus `agent_id`. Never by
   session, never by document id supplied independently.
3. **Before or after other context** — P1 is fetched first of the three person blocks (`:790`),
   after the static system prompt.
4. **One document assumed** — **yes**. One `get`, formatted as one block.
5. **One human, several member documents** — P1 would return only the member whose key the current
   channel produced; the others would be invisible. `[DERIVED]` This is today's behaviour for a human
   on two channels.
6. **After a merge** — `[DERIVED]` P1 as written would still read one document. To reflect the merge,
   the read must resolve subject → members and read each. The extractor read (W2r) is the harder
   case: see §11.2.
7. **After undo** — P1 returns to the current identifier's document. Whether that document is clean
   depends on what W2 wrote in the interim (§11.2).
8. **Caching** — `[CODE]` **none**. No cache in `agent_memory_service.py`, `person_records.py` or the
   loaders; each turn is a fresh Firestore `get`.

---

## 7. `lead_profiles` / `lead_contacts` / `lead_people` Read Paths

### 7.1 Reads into the prompt

`[CODE]` **Only T1.** No lead data is read into the prompt by the packet builder. The lead tool
returns *"found / last_contact_at / status and NOTHING else"* so that *"an unauthenticated caller
speaking a guessed email must not be able to pull the stored name, company, or interest back out
through the agent's mouth"* (`lead_contacts.py:501-504`). No-match, unparseable input and cross-org
all return the same object (`:506-508`). The tool description instructs the model to query only a
value *"the caller gave you on THIS call"* (`:616-618`).

### 7.2 Reads for operators

L1–L5 in §3. All are gated by `_leads_org_gate` (`routers/agent_memory.py:432-485`): a browser
operator must be an org member; an API key's org must equal the path org.

### 7.3 Where the union-find is used

`[CODE]` **Exactly one caller:** `list_lead_people_endpoint` (`routers/agent_memory.py:519-572`). It
is page-scoped — *"A page boundary can split one person's calls across two pages"* — and persists
nothing. **No prompt path, write path or other service calls `build_people`.**

### 7.4 One consumer relies on the fold's output indirectly

`[CODE]` The console passes the fold's contact keys to L3 as the `keys` parameter
(`routers/agent_memory.py:576-600`). So the only mapping-driven read in the platform receives its
mapping from the client.

### 7.5 L3 is the existing mapping-shaped read

`[CODE]` `core/lead_activity.py:35-39`:

> *"`person_key` is a `lead_contacts` document id and is SUBJECT TO MERGE. The day a profile arrives
> carrying two keys that had never co-occurred, those keys become one person and the root may change.
> That is why the timeline is queried by every key a person holds rather than by one: **a merge must
> be a re-point, not a redesign.**"*

The endpoint caps the fan-out at `MAX_PERSON_KEYS` (`:601-609`) — *"A real person holds two keys"* —
and verifies each row's org in memory because *"the query filters on the key alone"* (`:587-589`).

`[DERIVED]` This is the shape a mapping read takes: resolve to members, fan out one query per member,
enforce tenancy per row. It is already in production — for one operator view, with client-supplied
membership and a two-key assumption.

### 7.6 Erasure treats a contact as a person

`[CODE]` `lead_contacts.py:828-833`: *"A shared number (an office line, a recycled mobile) indexes
more than one human, and this module's identity model cannot tell them apart — one normalised contact
IS one person here … Erasing therefore takes all of them."*

---

## 8. `agent_users` Read Paths

### 8.1 What `agent_users` is, by its consumers

| Role | Consumer | Evidence |
|---|---|---|
| **Endpoint metadata** | Runtime upsert lookup (U1) | One row per `(agent, channel, channel_user_id)` |
| **A people directory shown to operators** | Studio "Users" list (U2) | Renders `display_name`, `phone_number`, `email` per row |
| **An outreach audience — who may be messaged** | U3 | *"a person exists here because they messaged the agent first"* (`outreach_users_service.py:3-8`) |
| **A consent gate** | U4 | `opted_out_at` / `opt_out_source` on the row; enforced in `olbrain-agent-directives` (`outreach_optout_service.py:1-9`) |
| Identity resolution | **none** | No reader resolves identity from it |
| Prompt construction | **none** | Not read by the packet builder or any tool |
| Authorization | **none** for access control; consent only (U4) | — |

`[CODE]` It is therefore **treated as a person in the operator UI and as a messaging target in
outreach**, while being physically a per-endpoint row.

### 8.2 Why scoping is agent-only

`[CODE]` `olbrain-studio-backend 5da93ae:services/outreach_users_service.py:10-14`: *"SCOPING IS BY
agent_id ALONE. The document carries `organization_id`, but the runtime writes
`data.get("organization_id", "")`, so it is empty on some rows and a filter on it would silently
return nothing."* The opt-out service adds that for **writes**, scoping is load-bearing: *"a document
id from any agent in any organization resolves"* (`outreach_optout_service.py:16-21`), so every write
re-checks `agent_id`.

### 8.3 The browser read

`[CODE]` `olbrain-studio 1f05ca11:src/services/settings/users/agentUserService.js:20-55` opens an
`onSnapshot` listener on `agent_users` `where('agent_id', '==', agentId)` and returns
`channel_user_id`, `display_name`, `phone_number`, `email`, session counts and `last_session_id`.
`firestore.rules` at the same commit contains **no `match /agent_users` block**; the collection is
governed by the two-segment catch-all, whose read list does not exclude it. `[DERIVED]` Any signed-in
user can run this query for any `agent_id` and receive that agent's end-users' raw contact details.
This is S6 with a live consumer — and the consumer is why the collection is not read-excluded.

---

## 9. Operator / UI Read Paths

| View | Read | Gate | Shows |
|---|---|---|---|
| Data tab (per agent table) | D1 | agent view permission (`agent-design app/routers/datastore.py:91-100, :158-159`) | Rows per (agent, table, person hash) |
| Memory inspector | H1 | API key + caller org = document org (`routers/agent_memory.py:71-74`) | One memory document |
| Leads table | L1 | org member / org key | One row per **call** |
| Leads "people" | L2 | same | Folded persons, page-scoped |
| Person drawer / timeline | L3 | same | Activity across client-supplied keys |
| Lead export | L4 | same | One row per call |
| Users list | U2 | **catch-all only** | One row per endpoint |
| Outreach audience / opt-outs | U3, U4 | `_authorize_agent` (studio-backend) | One row per endpoint |

`[DERIVED]` Operators see four different units labelled as people: a hashed row (Data tab), a memory
document, a folded lead, and an endpoint row. None agrees with the others about what one person is.

---

## 10. Identity Mapping Thought Experiment

*Org X, one agent. Subject A: phone P, records A1 = `agent_user_memory/{ag}__{h(P)}`, A2 =
`agent_datastores/{ag}/tables/t/entries/{h(P)}`. Subject B: email E, records B1 =
`…__{h(E)}`, B2 = `…/entries/{h(E)}`. Evidence establishes A and B as one person; a mapping makes both
resolve to one canonical subject.*

| Read | Today returns | Would need to return under a mapping | Resolution point |
|---|---|---|---|
| **P1** on a WhatsApp turn (`user_id = P`) | A1 only | A1 **and** B1, combined at read time | `cs_packet_builder.py:1980` |
| **P1** on an email turn (`user_id = E`) | B1 only | B1 and A1 | same |
| **P2** | A2 per table | A2 and B2 per table — with a rule for fields both hold `[UNRESOLVED]` | `:2050-2051` |
| **P3** | `P` | `P` — the current identifier, unaffected | none |
| **T1** caller dictates E on a call from P | E's contact doc | `found` via either key; `status` may disagree between them | `lead_contacts.py:515-517` |
| **W2r** extractor | A1 | **Undetermined** — reading A1 alone keeps the partition; reading A1+B1 re-materialises the combination on write (§11.2) | `agent_memory_service.py:276` |
| **H1** by P | A1 | A1 and B1? or A1 only? `[UNRESOLVED]` | `routers/agent_memory.py:72` |
| **L2** | Already folds if a profile carries P and E | Folded, **org-wide instead of per page** | `lead_people.py:141` |
| **L3** | Keys the client supplies | Keys the mapping supplies | `routers/agent_memory.py:594-600` |
| **L5** erasure of P | All profiles under P | All members' profiles? `[UNRESOLVED]` — a legal scope question | `lead_contacts.py:853-879` |
| **D1** Data tab | Two rows (A2, B2) | Two rows, or one grouped person `[UNRESOLVED]` | `datastore_service.py:202` |
| **U2 / U3** | Two endpoint rows | Two rows, grouped or not | — |
| **U4** opt-out on P's row | P suppressed; **E still messageable** | Whether consent follows the subject or the endpoint `[UNRESOLVED]` | enforcement in `olbrain-agent-directives` (absent) |

`[DERIVED]` Every turn-path read (P1, P2) needs a resolution step inserted **before** its key
derivation. Every operator read needs a decision on whether it shows members or subjects. The only
read already built for this is L3.

---

## 11. Undo Thought Experiment

### 11.1 Sequence 1 — records kept separate

*T0 separate · T1 merge (mapping only) · T2 A receives new data · T3 B receives new data · T4 undo.*

| Read | Can it tell A-origin from B-origin at T4? | Fetches both during T1–T4? | Assumes one document? |
|---|---|---|---|
| P1 / P2 | **Only if the writes at T2 and T3 stayed in their own member documents** (§11.2) | Yes, if the read resolves the mapping | No longer, under a mapping |
| W2r | Depends on its own read scope | If it resolves the mapping, yes | Yes today |
| P4 history | **No** — replies are stored per session, not per person | n/a | n/a |
| L3 | Yes — activity rows carry their own key | Yes | No |
| D1 | Yes — rows keep their ids | Shows both | No |
| U2–U4 | Yes — rows are per endpoint | n/a | No |

### 11.2 Why sequence 1 still loses separability

`[CODE]` The extractor's input (`agent_memory_service.py:299-304`):

```
CURRENT FACTS:  <the document it just read>
…
LATEST TURN:
User: <user text>
Assistant: <assistant reply>
```

and it returns *"the UPDATED COMPLETE list of facts"* (`:42`), written back to the document keyed by
the **current** identifier (`:398`).

`[DERIVED]` Two routes carry B's data into A1 **without any step that combines records**:

1. **Read-scope route.** If W2r resolves the mapping and reads A1 + B1 as `CURRENT FACTS`, the
   returned complete list contains B's facts and is written to A1.
2. **Reply route — even if W2r reads A1 only.** P1 resolves the mapping, so the prompt contains B's
   facts; the assistant's reply mentions one of them; the extractor reads that reply as part of the
   turn and writes it into A1 as a fact about "the user".

Route 2 means **keeping member documents separate at the storage layer does not keep them
separable.** As soon as a read that feeds the prompt resolves across members, the member documents
written afterwards can contain the other member's data. At T4, A1 cannot be cleaned, because facts
carry no provenance (§6.2).

`[CODE]` The same applies to datastore values: the extraction returns field values from the same turn
(`agent_memory_service.py:329-331`) and W1 writes them to the current identifier's row.

**History.** `[CODE]` P4 re-reads the session's stored messages every turn (`cs_packet_builder.py:
1455-1470`). Any reply that disclosed B's data during T1–T4 stays in that session's history and is
re-sent to the model after undo. Undo does not reach it.

### 11.3 Sequence 2 — memory physically combined

*T0 separate · T1 merge · T2 A's and B's memory combined into one document · T3 undo.*

| Read | Recovers the partition at T3? |
|---|---|
| P1 | **No** — one regenerated list, no provenance |
| P2 | **No** for any field written after T2; the row carries no per-field origin |
| W2r | **No** — it reads the combined document |
| P4 history | **No** |
| L3 | Yes — activity is per key |
| D1 | No for combined rows |
| U2–U4 | Yes — endpoints were never combined |

### 11.4 The case that exists before any merge

`[CODE]` When one identifier belongs to two humans — the shared or recycled number the code itself
describes (`lead_contacts.py:828-833`) — P1 and P2 already read one document for both. There is no
partition at T0 to recover. `[DERIVED]` No read-side mapping can separate them, because the only input
on the turn is the shared identifier.

---

## 12. Cross-Organisation Read Boundaries

| Read | Org boundary | Org source | Trusted? | Can be empty? | Lookup org-scoped? | Key org-scoped? | Same unsalted digest could cross orgs? | Stale transfer could read old org? |
|---|---|---|---|---|---|---|---|---|
| P1 | `agent_id` in path | Processor `organization_id` — used for PII only | n/a | yes | **no** | no | Only if a lookup ever used the digest without the agent prefix | Agent path is unchanged by transfer, so reads follow the agent |
| P2 | `agent_id` in path | same | n/a | yes | **no** | no | same | same; table-header org is never read |
| T1 | org in key + check | Tool loop, from the processor (`anthropic_provider.py:2962`) | Config / sender doc / agent doc (§12.1) | **yes → not-found** (`:666-669`) | yes | **yes** | Suffix identical across orgs; prefix separates | Stale config org for ≤300 s looks up the old org's index |
| H1 | document org = caller org | API key middleware | key org verified against agent doc | yes → 404 (`:43-45`) | no (by id) | no | — | Cached agent doc ≤30 s (flag on) |
| L1–L5 | path org, gated | Operator membership / key org | yes | no | yes | yes (contacts); profiles by field | — | — |
| D1 | agent | Agent doc | agent doc is client-writable (S1) | — | agent | no | — | — |
| U1 | agent | none in query | — | yes (`""`) | no | no | — | Org stamped on create only |
| U2 | **none** | client | **no** | — | **no** | no | — | — |
| U3/U4 | agent, by design | — | — | yes | no | no | — | — |

### 12.1 Where the org comes from on the turn path

`[CODE]` The processor's `organization_id` (`lightweight_processor.py:1003-1051`). In the email router
it resolves from a sender document, then `config["metadata"]`, then `config["agent"]`, else `""`
(`routers/email.py:179-210`). The config is cached 300 s (§14). On inbound API-key calls the middleware
requires the key's org to equal `agents/{id}.organization_id` (`core/api_key_middleware.py:375-380`);
a legacy agent-pinned key carries no org and skips that comparison (`:392-400`).

### 12.2 Enforcement points and weaknesses

`[DERIVED]`

- **The turn-path person reads are org-safe only because the agent path is.** They perform no org
  check of their own. If a mapping resolved a subject to member documents under **other** agents, the
  agent path would no longer bound them, and nothing else on the path would.
- **T1 is the only turn-path read keyed by org.** Its safety rests on the processor's org value, which
  can be empty or stale.
- **U2 has no org boundary at all.**

D2 is not proposed.

---

## 13. Cross-Agent Visibility Boundary

**U7 is unresolved; this section documents behaviour only.**

### 13.1 Current physical boundaries

| Store | Boundary |
|---|---|
| `agent_user_memory` | Agent, in the document id |
| `agent_datastores` | Agent, in the path |
| `lead_profiles` | Agent + session in the id; listed org-wide |
| `lead_contacts` | **Org**, shared by agents; `refs` carry `agent_id` |
| `agent_users` | Agent field; no rule enforces it |

### 13.2 Current cross-agent reads

`[CODE]`

- **T1**, into the prompt: org-scoped, answers for any agent's capture — minimal payload.
- **L1–L5**, to operators: org-wide, full data.
- **U2**, in the browser: any agent, client-chosen.

`[CODE]` **No turn-path read returns another agent's stored facts or field values.** P1 and P2 are
agent-bounded.

### 13.3 What a mapping would expose

`[DERIVED]` J1 makes one subject span an org's agents. If P1 or P2 resolved that subject to **all** its
member documents, a turn on agent 2 would read agent 1's memory and rows into agent 2's prompt.

**This is exactly where U7 becomes relevant**: at the member-set expansion in P1 (`:1980`) and P2
(`:2050-2059`). Resolving *identity* across agents and fetching *records* across agents are separable
steps — the read can know that A and B are one person and still fetch only the current agent's
members. Which of those the reads should do is U7, and is not answered here.

---

## 14. Caching / Staleness

`[CODE]` No person document, person row or lead record is cached. The caches below hold the context
around person reads.

| Cache | Location | Key | TTL | Scope | Holds | After merge | After undo | After transfer |
|---|---|---|---|---|---|---|---|---|
| Agent config | `lightweight_processor.py:93, :98-99, :352-369` | config path | **300 s** prod, 30 s draft | process | `organization_id`, `resources.datastores` (which tables P2 reads) | unaffected | unaffected | **Old org for ≤300 s**; writers re-stamp it (see resolution spec §11.3) |
| Agent doc | `core/api_key_middleware.py:349-363` via `core/hotpath_cache.py` | `("agent_doc", agent_id)` | 30 s default | process; **flag, default off** | agent org for the key check and webhook org override (`:364-368`) | unaffected | unaffected | Old org accepted ≤30 s |
| API-key doc | same file `:288-308` | `("api_key_by_hash", hash)` | 30 s | process; flag off | credential doc | — | — | — |
| Agent status / model override | `lightweight_processor.py:449, :470` | agent id | per module | process | not person data | — | — | — |
| Lead lookup budget | `lead_contacts.py:80-120` | session id | 3600 s | **per instance** | counts only | — | — | — |
| Opt-out stop keywords | `services/outreach_optout.py:59-115` | agent id | module TTL | process | keywords | — | — | — |
| Provider prompt cache | Anthropic, content-addressed | prompt bytes | provider | provider | **static prefix only** under `PROMPT_CACHE_V2`; person blocks ride the dynamic tail (`cs_packet_builder.py:767-827`) | n/a | n/a | n/a |
| **Stored conversation history** | agent messages, per session | session id | **no expiry** | durable | every reply already given | Carries disclosed data forward | **Not reached by undo** | Follows the session |

`[DERIVED]` Because person reads are uncached, a mapping change is visible on the next turn without
invalidation. The invalidation problem sits elsewhere: in the **config** cache, which decides the org
and the table list, and in **stored history**, which behaves like an unbounded cache of whatever was
disclosed.

---

## 15. Read-Path Invariants

What the reads rely on today, stated so a mapping layer can see what it would break.

| # | Invariant relied on today | Relied on by |
|---|---|---|
| RI1 | One channel identifier → one document per agent | P1, P2, W2r, W1r, H1 |
| RI2 | The agent path bounds the org | P1, P2 |
| RI3 | The processor's `organization_id` is the right tenant | T1, writers |
| RI4 | A contact value is one person | L5, T1, L2 |
| RI5 | An endpoint row is the unit of consent | U4 |
| RI6 | Operators may define person membership for display | L3 (client-supplied keys) |
| RI7 | What was said stays said | P4 |
| RI8 | The extractor's input and output concern the same person | W2r → W2 |

`[DERIVED]` A mapping layer breaks RI1 by definition. It breaks RI2 as soon as a member set spans
agents. It turns RI8 from true-by-construction into a condition that has to be enforced (§11.2).

---

## 16. What a Resolution Mapping Would Require From Reads

Requirements only; no mechanism chosen.

1. **A resolution step before key derivation** in P1 (`:1980`), P2 (`:2050-2051`), T1
   (`lead_contacts.py:515`), H1 (`routers/agent_memory.py:72`), and before W2r / W1r.
2. **Fan-out across members with per-row tenancy checks**, since the agent path would no longer imply
   the org once a member set spans agents. L3 shows the pattern (`routers/agent_memory.py:587-589`).
3. **A read-time rule for combining members' values** in P2 and for rendering several memory
   documents in P1, without writing the combination back `[UNRESOLVED]`.
4. **Different read scopes for the prompt and for the extractor's read-before-write**, or a statement
   that they coincide — because the extractor writes whatever it read, plus the reply (§11.2).
5. **A decision on whether operator views show members or subjects** — D1, H1, L1, U2–U4.
6. **A decision on whether consent and erasure follow the subject or the member** — U4, L5.
7. **A resolution authority on the server**, since L3 currently takes membership from the client.
8. **Org resolution that is not stale** when a subject's membership changes by transfer — the config
   cache holds the org for 300 s.
9. **Knowledge that history is not reachable by undo** (P4).

---

## 17. Unresolved Questions

**Not answered.**

| ID | Question | Where it bites |
|---|---|---|
| **U7** | Does one subject across agents mean one agent reads another's records? | P1/P2 member-set expansion (§13.3) |
| **RP1** | How are two members' values for one field combined **at read time** in P2? | §10, §16.3 |
| **RP2** | Should the extractor read the resolved subject or only the current member? Either choice has a consequence (§11.2) | W2r |
| **RP3** | Can an assistant reply that disclosed another member's data be excluded from extraction, and from history? | §11.2 |
| **RP4** | Do consent (opt-out) and erasure follow the subject or the endpoint/contact? | U4, L5 |
| **RP5** | Do operator views show members or subjects? | §9 |
| **RP6** | Is the lead console's client-supplied membership (L3) acceptable once resolution is authoritative server-side (J3)? | L3 |
| **RP7** | For H1 addressed by one identifier, does the response include other members? | H1 |
| **Scope** | `olbrain-agent-directives` (enforces opt-out over `agent_users`, per `outreach_optout_service.py:3-4`), `olbrain-voice-gateway` (voice turns, per `cs_packet_builder.py` voice comments) and `olbrain-webhook-service` (web widget, per `core/channel_profiles.py`) are referenced but absent. Their person reads are **not inventoried** | §3 completeness |
| **U2 read side** | Normalisation disagreement also affects reads: P1/P2 hash the raw `user_id`, T1 normalises first | P1/P2 vs T1 |

Also carried: shared and recycled identifiers (§11.4) make RI1 false before any merge; that is a
question about J5's exact-match premise and belongs with Jay.

---

## 18. Recommended Next Investigation

**Trace every read that feeds a write.**

§11.2 shows the decisive coupling is not a read or a write in isolation, but a read whose result is
written back: the extractor's read-before-write, the reply text it consumes, lead capture reading tool
input produced from a prompt, and any operator import or edit made while looking at a resolved view.
Under a mapping, those are the places where combined data re-materialises into member records, so
they decide whether the partition can stay separable at all.

For each, the investigation would record what it reads, which of that was produced under a resolved
view, and where the result is written. It needs no decision from Jay, and it is the precondition for
evaluating any mapping-based mechanism.
