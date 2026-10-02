# OLBrain — Decision Board

Date: 2026-09-26. **Consolidation only.** Every entry is drawn from an existing investigation
artifact; nothing new is investigated, nothing is recommended, and no decision is taken.

**How to read an entry.** *Evidence* is pinned to a commit or to the contract. *Options* are only
those the investigation actually produced — where none emerged, the entry says so rather than
inventing a menu. *Blocks* states what each option forecloses or releases.

Evidence commits: `olbrain-agent-runtime 8df0e02` · `olbrain-agent-design 51ffe3b` ·
`olbrain-agent-engine e43654e` · `olbrain-shared 8a0f0b5` · `olbrain-studio 8cee761c` ·
`olbrain-studio-backend ca9724a` · `olbrain-research-runtime 6b81691` ·
`olbrain-research-design e211584` · `olbrain-workflow-runtime 1978f4a` ·
`olbrain-mcp-deployer 0efd05f` · `olbrain-agent-eval 6c289ca` · `olbrain-finance-engine 109a838`.
Contract: `architecture-contract.md`, md5 `97c1fa3bcea1d71210c0429b1d113d07`, unmodified.

---

## Board at a glance

| # | Decision | Owner | Blocks PostgreSQL? |
|---|---|---|---|
| 1 | Cross-channel recognition needed? | Jay (product) | Indirectly — via 2, 5 |
| 2 | Person identity: who owns the definition? | Jay | No |
| 3 | Merge policy: operator / automatic / both | Jay | No |
| 4 | G5 + QF-2: how long parked? | Jay (programme) | **Yes** |
| 5 | Opaque surrogate person id? (D4) | Jay + architecture | **Yes** |
| 6 | Is person-merge forbidden or unmodelled? (J2) | Contract owner | No |
| 7 | Is an LLM-extracted person row an identity assertion? (J4) | Contract owner | No |
| 8 | Is a merge a deletion of the retired scope? (N10) | Contract owner | No |
| 9 | Adopt Patch 19? (D7) | Contract owner | No |
| 10 | Does freshness belong to the Policy Registry, not the value row? | Contract owner | **Yes — releases G3** |
| 11 | Capability TTL + online-only set (G1+G6) | Security | No |
| 12 | Rejected-work disposition (G8) | Operations | No |
| 13 | Recompute window, Operations half (G4) | Operations | No |
| 14 | Per-predicate freshness values (G3) | Domain owners (R2) | No |
| 15 | Operational-correction authority domain (D5) | Workflow-design owner | No |
| 16 | Retain or retire the Firestore config path (QF-5) | Runtime owner | No |
| 17 | Org-transfer policy for person data (J6) | Tenancy/programme | No |
| 18 | Who claims WB-006 (S7)? | Programme owner | No |

---

# Part 1 — Jay decisions

### 1. J1 — Does OLBrain need to recognise one human across channels?

**Evidence.** `[CODE]` `user_id` is a different identifier *type* per channel: `from_number`
(`meta_whatsapp.py:965`), `from_email` (`email.py:311`), `sender_igsid`
(`meta_instagram.py:314`), `phone_number or session_id` (`directives.py:215`), `None`
(`chat.py:224`). One human on two channels becomes two unrelated `person_hash` values, with no
alias mechanism anywhere. `[CODE]` The gap has never been *decided against*: the write path's own
comment anticipates *"a later dedup pass"* that does not exist, and `lead_people` was built to
defragment within one org. `[CODE]` Every other entity class has a working identity story —
`organizations.merged_into`, `research_clients` aliases+merge, `member_identity`.

**Options.** (a) Yes — cross-channel continuity is a product requirement. (b) No — identity is
per-channel by policy, stated honestly.

**Dependencies.** None upstream. Everything in the identity programme hangs downstream.

**Blocks.** (a) requires a resolution layer; makes 3, 5, 6 live; makes the co-occurrence
measurement the sizing input. (b) makes Track E's merge research moot rather than wrong, and
promotes the simpler candidate (per-tenant keyed hash + typed identifiers + `agent_users`
promoted) to leading option. **Neither is blocked by anything.**

**Note.** `[UNMEASURABLE]` The cost of *not* doing it cannot be measured — measuring fragmentation
requires the resolution that is missing. `[UNMEASURED]` The opportunity can be sized by the
co-occurrence query (Part 3, E1), but that sizes, it does not settle.

---

### 2. J3 — Who owns person identity?

**Evidence.** `[CONTRACT]` Identity is assigned to `IDENTITY_SYSTEM` under authority domain
`IDENTITY_SECURITY`, `LLM_WRITE = FORBIDDEN`, `USER_WRITE = FORBIDDEN` (`:1212-1213`). `[CODE]`
**Zero hits for `IDENTITY_SYSTEM` / `IDENTITY_SECURITY` across all 13 repositories** — the named
authority has no implementation. `[CODE]` Six identity mechanisms exist across two subject
classes; four are unlinked person mechanisms, each invented locally.

**Options.** No option set emerged from the investigation — this is a naming, not a choice between
analysed alternatives.

**Dependencies.** None. **Blocks.** Until owned, further subsystems will keep inventing their own —
which is how the present state arose.

---

### 3. J5 — Merge: operator-confirmed, automatic on proof, or both?

**Evidence.** `[CODE]` One in-house precedent chose explicitly: `research_clients`
(`olbrain-research-design e211584:app/routers/org_research_clients.py:297`) is
**operator-initiated and audited** (`updated_by`), with `aliases` inheritance and a `merged_into`
redirect on the archived loser. `[CODE]` `lead_people` merges only on *proof* — a single profile
carrying both an email and a phone — and refuses to mint identity where none is provable.
`[CODE]` `lead_contacts:181-188` states the safety property: *"exact match beats clever match
where a wrong merge reads a stranger's history to the caller."*

**Options.** (a) Operator-confirmed only. (b) Automatic on co-occurrence proof, operator for
weaker evidence. (c) Both, with a declared evidence threshold.

**Dependencies.** Gated behind 1 and 6.

**Blocks.** (a) and (c) require a human review surface. (b) requires the threshold to be a
*declared policy*, not a model output — `[CONTRACT]` §6 forbids selecting on confidence. All three
inherit Part 2 item 8 (scope generation) and, per Track E, **G4 and G8**.

---

### 4. G5 + QF-2 — How long do these stay parked, and what proceeds meanwhile?

**Evidence.** Jay's recorded answer parks both: *"no contractual or legal work is to be done right
now, so this and G5 stay parked with no Legal seat named… This row stays a hard block until
then."* `[CODE]` The affected dataset family is now enumerable — `olbrain-finance-engine 109a838`
holds `finance_rm`, `pnl_inputs`, `pnl_drivers`, `pnl_projections`, `pnl_statements`,
`finance_model`, `finance_lines`, `pnl_exports`, `rm_proposals`, `finance_policy`, plus `runs` /
`versions` / `workflow_runs`. `[CODE]` A further candidate appeared: `privacy_compliance_log`
(mcp-deployer).

**Options.** (a) Unpark now. (b) Stay parked; schema design proceeds **excluding**
aggregate-bearing tables, added later. (c) Stay parked; schema design waits.

**Dependencies.** None upstream. **This is the binding constraint on the PostgreSQL gate.**

**Blocks.** (b) requires accepting a later schema addition touching retention and deletion
cascades. (c) defers PostgreSQL indefinitely. `[INFERENCE]` Drifting into (c) by default, without
choosing it, is the risk the investigation flags.

---

### 5. D4 — Does person identity move to an opaque surrogate id?

**Evidence.** `[CODE]` `person_hash` = `sha256(strip+lower(key))[:32]`, unsalted, global —
`olbrain-shared 8a0f0b5:columns.py:35`. The digest is identical across tenants for the same phone
number, and the input domain (phone numbers, emails) is enumerable, so the digest is testable
rather than pseudonymous. `[CODE]` Re-keying requires the raw key, which is never stored —
`extract_entry_writer.py:87-93` keeps `user_key_kind` only. `[CODE]` A second implementation of
the same digest exists inline in `memory_doc_id` (`agent_memory_service.py:92-97`).

**Options.** From the research: (A) status quo; (B) per-tenant keyed hash / HMAC; (C) opaque
surrogate + persisted identifier mapping; (D) event-sourced identity (C plus Evidence/Claim
shape); (E) channel endpoints only, no canonical person; (F) derived resolution, never persisted.

**Dependencies.** Answering **5 first changes what D2 and D3 are asking**. Conditional on 1.

**Blocks.** It sets the primary key of every person-keyed table. (A) and (B) cannot merge — two
identifiers stay two subjects permanently. (C)/(D) require the mapping table to be structurally
barred from authorization decisions. (E) forecloses cross-channel continuity. (F) is bounded to
read-time list views by scale.

---

# Part 2 — Other-owner decisions

### 6. J2 — Contract: is person-merge forbidden, or merely unmodelled? *(Contract owner)*

**Evidence.** `[CONTRACT]` Cross-customer `SAME_AS` is **forbidden**; *"Entity destructive merges —
Rejected in initial implementation"*; `RESOLVES_TO` is non-authorizing. But the `SAME_AS` operands
in Example 4 are **mentions** (`A1`, `A2`, `B1`), not customers, and persons never appear as
operands anywhere. Entity resolution is listed as an **asynchronous** operation that *"improves
future recall"*.

**Options.** (a) Forbidden — persons are `CUSTOMER` scopes, so person-merge is cross-scope
`SAME_AS`. (b) Unmodelled — `SAME_AS` relates mentions; the contract simply has no vocabulary for
relating two customer scopes, because identity is assumed settled upstream.

**Blocks.** (a) voids Track E's models entirely and reduces the identity work to privacy and
fragmentation-honesty. (b) makes 8 the next contract question and leaves Track E's surviving
models (nothing rewritten; resolution re-pointed) available as a starting point.

---

### 7. J4 — Is an LLM-extracted person row an identity assertion? *(Contract owner)*

**Evidence.** `[CONTRACT]` `LLM_WRITE = FORBIDDEN` on `IDENTITY_SECURITY` predicates; *"The
conversation … cannot modify identity, role, authorization, tenant membership, or security
policy"* (`:1219`). `[CODE]` The extract pipeline writes person-keyed rows from LLM output, keyed
by an identifier the LLM did not verify.

**Options.** (a) Yes — the current pipeline contradicts the contract. (b) No — the row is memory
*about* a person, not an assertion *of* identity.

**Blocks.** (a) means the fix is to the pipeline, not to a schema. (b) leaves the pipeline as-is
and the question closed.

---

### 8. N10 — Is a merge a deletion of the retired scope? *(Contract owner)*

**Evidence.** `[CONTRACT]` `scope_generation(scope_id)` is described as **deletion** protection.
`[CODE]` `scope_generation` exists in **no repository**.

**Options.** (a) Yes — merge bumps the generation and fences in-flight workers. (b) No — merge is
a separate event class needing its own fencing rule.

**Dependencies.** Live only if 6 = (b). **Blocks.** (a) pulls **G8** directly into merge design —
rejected in-flight work needs a disposition. (b) requires new machinery.

---

### 9. D7 — Adopt Patch 19? *(Contract owner)*

**Evidence.** `[CODE]` The contract contains **no scope-exclusion vocabulary at all** — zero
matches for *out of scope*, *outside the scope*, *does not model*, *not modelled*, *procedural
memory*. The exclusion lives only in `architecture-freeze.md` §2, which is candid that it is
admissible *"not because procedural memory provably fails the Memory definition"* — Memory's §1
definition enumerates *"lessons"*, and a learned tool-sequence can be read as one.

**Options.** (a) Adopt. (b) Decline. Sub-choices if (a): name exemplars or state only the
principle; one-off sentence or reusable exclusion vocabulary.

**Dependencies.** None. Blocks nothing. **Drafting risk:** a loosely-drawn boundary could
accidentally exclude `LearnedOverride`, which D5 is trying to include.

**Blocks.** (a) removes `agent_learned_patterns` and `workflow_agent_memory.exception_patterns`
from target-model scope. (b) returns them, and someone must then decide what they are.

---

### 10. Does freshness belong to the Policy Registry rather than the value row? *(Contract owner)*

**Evidence.** `[CONTRACT]` `freshness_contract` is required *on the policy*; `freshness_status` is
a derived `StateSlot` property, and materialising it would contradict Current State being a
projection. `[CODE]` No freshness machinery exists — every `freshness`/`stale` hit is cache
lifetime (`context_broker.py:185`, `cs_packet_builder.py:731`).

**Options.** (a) Confirm — G3 blocks the Policy Registry schema and the resolver, not the core
schema. (b) Reject — freshness columns belong on the value row.

**Blocks.** **This is the one contract question that moves the PostgreSQL gate.** (a) removes G3
from the blocker list. (b) keeps it.

---

### 11. G1 + G6 — Capability TTL and the online-only operation set *(Security, as a pair)*

**Evidence.** `[CODE]` A precedent exists and its shape reframes the question:
`core/hotpath_cache.py` — TTL **default 30s** (`HOTPATH_DOC_CACHE_TTL_SECONDS`), **default OFF**
(`HOTPATH_DOC_CACHE_ENABLED`). `api_key_middleware.py:288-293`: *"Only the fetch is cached — every
check below (hash re-compare, status, expiry, org membership, scoped-agent pin, rate limit) still
runs per request."* `[CODE]` `TTLDocCache` has `clear()` but **no targeted invalidation and no
caller invokes it on revocation** — so TTL *is* the revocation lag. `[CODE]` Production is
online-only today, the flag being off by default.

**The factual discrepancy to settle first:** the contract proposes **60s**; the codebase
implemented **30s** for the analogous case. Unreconciled.

**Options.** (a) Keep online-only for MVP. (b) Adopt the fetch/check split at 30s. (c) Adopt a
60s TTL on whole capabilities.

**Blocks.** (a) blocks nothing and costs latency already borne. (b) shrinks G6's list to
operations where even a stale *credential document* is unacceptable, and makes a revocation
invalidation hook the one new requirement. (c) makes 60s the real revocation lag on every check
including org membership, and G6's list must then be **exhaustive**, not indicative.

**Not cacheable under any option** `[INFERENCE]`: writes to `IDENTITY_SECURITY` predicates;
grant-management; operations whose failure mode is disclosure rather than denial; bulk deletion.

---

### 12. G8 — Disposition of work rejected by a `scope_generation` bump *(Operations)*

**Evidence.** `[CODE]` `scope_generation` exists nowhere — G8 governs a prospective mechanism, with
no backlog awaiting policy. **In-house doctrine, three independent subsystems:**
`_is_orchestrator_superseded` (`orchestrator.py:423-435`) — *exit cleanly, no retry, no record*;
`job_dispatcher.py:26-28` — 3 attempts for transient faults only, then a terminal `FAILED` with a
human `/retry`; the Pub/Sub worker acks even on failure and relies on a sweeper that *"does not
retry"*. **No dead-letter consumption anywhere** — the one DLQ artifact is a dormant provisioning
workflow whose header admits a persistently-rejected event is *"silently dropped when the
subscription's 1-day retention expires"* and *"nothing alerts on a dead-lettered message yet"*.

**Options.** M1 abandon · M2 abandon + durable record · M3 re-derive/sweeper · M4 bounded retry
then DLQ · M5 split by work class.

**Dependencies — one is material.** `[INFERENCE]` **M2 and M4 persist a record of work concerning
a deleted scope. That record is itself a dataset needing a §10 classification — i.e. it inherits
G5, which is parked.** M1 and M3 avoid this. M3 additionally falls inside **G4**'s window.

**Blocks.** All bulk deletion, until answered. Single-scope deletion and `mutation_id`
idempotency proceed regardless.

**Asymmetry to weigh** `[INFERENCE]`: abandoning is safe in the orchestrator precedent *because a
newer pass will redo the work*. A scope-generation bump means the scope is **gone** — correct for
deletion work, silent failure for anything else in flight. This is why M5 exists.

---

### 13. G4 — Recompute window, Operations half *(Operations)*

**Evidence.** `[CONTRACT]` Correct exclude-don't-serve behaviour is implementable now; only the
bound is missing. Jay's routing parks the Legal half and states *"the Operations half of this row
can still be voted."*

**Options.** None emerged — this is a number, not a choice between analysed alternatives.

**Dependencies.** `[INFERENCE]` If merges are permitted, merge recomputation falls inside this
window (Track E). **Blocks.** A bounded recompute window; the behaviour itself is not blocked.

---

### 14. G3 — Per-predicate freshness values *(Named domain owners, per R2)*

**Evidence.** `[CODE]` No freshness machinery exists. `[INFERENCE]` The ask is **three values per
predicate**, not a design exercise: `max_staleness`, `stale_read_policy`, `stale_write_policy`.
Roughly half of G3 is mechanical and code can supply it — observation timestamp, source identity,
the `freshness_status` arithmetic, and whether a predicate is externally owned at all.

**Candidate first predicates** `[INFERENCE]`: external `data_query` results (owner unmapped);
finance figures — **`olbrain-finance-engine 109a838`** is versioned (`versions`) and reconcilable
(`app/finance_reconcile.py`), so validity windows are plausibly real business quantities; MCP tool
results via `olbrain-mcp-deployer 0efd05f` (owner unmapped).

**Owners.** Shivam — memory/soul/person-attribute. finance-engine owner — finance.
workflow-design owner — operational-correction. **Unmapped: `data_query` and MCP results** — R2
maps no domain; falls to *"assigned by Jay as it arises."*

**Dependencies.** Unblocked by R2. `[CONTRACT]` §3 eliminates "serve stale silently" from
`stale_read_policy`. **Blocks.** Every externally-owned predicate. Internal predicates proceed.

---

### 15. D5 — Operational-correction authority domain and approver *(Workflow-design owner)*

**Evidence.** `[CODE]` The lane is implemented: status `suggested → active → retired`
(`olbrain-shared 8a0f0b5:workflow/models/agent_memory.py:52`), a per-agent feature gate
(`orchestrator.py:899`), and `approve`/`retire` endpoints carrying `actor` and `reason`
(`olbrain-workflow-runtime 1978f4a:app/routers/exceptions.py:274-311`). `[CODE]` **No
authority-domain identifier exists in any repository.** `[CODE]` `LearnedOverride` is a
workflow-memory record, not a Claim — no subject/predicate/object, no provenance, no
`policy_version`, no bitemporal fields.

**Four bounded sub-questions.** (i) the domain identifier; (ii) who may approve, and whether that
differs from who may retire — the code already distinguishes them and retirement is documented as
an *"operator kill switch"*; (iii) whether promotion requires authentication at all — see Part 4,
R6; (iv) whether an active override expires — `[CODE]` it does not, and if it should, that is a
`max_staleness` and becomes a **G3** input for the same owner.

**Blocks.** The first operational-correction Predicate Policy. If declined, `LearnedOverride`
cannot map to a Claim and joins procedural memory outside the five-object model.

---

### 16. QF-5 — Retain or retire the Firestore config path *(Runtime owner)*

**Evidence.** `[CODE]` The `Agent` class has **no message-processing method at all** — it defines
17 methods, all session CRUD and introspection. `process_message_universal` was removed
**2026-04-01** (`7a51069` / `4cbed37`, *"chore: remove deprecated MessageProcessor pipeline"*), so
`routers/sessions.py:462` and `:568` have called an undefined method for ~6 months. Every channel
router reads GCS `active_config.json`. `create_agent_with_settings()` has no non-doc callers.

**Options.** (a) Retain for session CRUD and `/agent/info`. (b) Retire — GCS canonical; remove the
Firestore path, the two dead branches and `create_agent_with_settings`.

**Dependencies.** **Gated on evidence, not on a decision** — Part 3, E2. `[INFERENCE]` Two readings
survive six months of silence: dead traffic, or erroring traffic tolerated. Source cannot
distinguish them.

**Blocks.** Neither option blocks anything else. **The defect at `:462`/`:568` is separable and
true either way** — see Part 4, R1.

---

### 17. J6 — Org transfer: does person data follow the agent, sever, or block the transfer? *(Tenancy/programme)*

**Evidence.** `[CODE]` The transfer cascade handles **16 collections including `agent_sessions`**
and omits **every** person-keyed store; `agent_datastores` returns zero hits in the entire
`olbrain-studio-backend ca9724a` repository. `[CODE]` Both `agent_datastores` table headers and
`agent_user_memory` documents self-heal on any durable write, so the residue is **quiet tables**
and **dormant persons**, not the whole transferred population.

**Options.** (a) Follow — re-stamp person stores in the cascade. (b) Sever. (c) Block transfer
while person data exists.

**Dependencies.** Interacts with 5 — if subjects are tenant-scoped, re-parenting one into another
tenant is the cross-tenant identity event the design exists to prevent.

**Blocks.** This is a **present-tense defect**, not only a future design question: person data is
already stranded today.

---

### 18. Who claims WB-006? *(Programme owner)*

**Evidence.** QF-4 is decided and sequenced — stamp, backfill india-prod, then tighten rules;
tightening first would break live reads. `[CODE]` WB-006 is recorded **unclaimed**.

**Options.** None — an assignment. **Blocks.** Closing the cross-org read exposure, and any
tenancy predicate needing a row-level org key. The procedure needs the M1 correction first
(Part 4, R8).

---

# Part 3 — Evidence-required (no decision to make; someone must run these)

`[UNMEASURED]` **This workspace has no production access** — no credentials, `gcloud` absent,
`firebase` CLI on an unrelated account, `projects:list` fails. No attempt was made to obtain
access or read PII. All specifications below are already written; only execution is missing.

| ID | Query | Feeds | Threshold / read |
|---|---|---|---|
| **E1** | Co-occurrence: `lead_profiles` by org — profiles with normalised email **and** phone, over profiles with ≥1 usable key. Use `normalise_contact_email` / `normalise_contact_phone` verbatim; exclude `_WITHHELD_CONTACT_KEYS` | 1, 3, 5 | **<5%** defeats the resolution layer · **>20%** justifies it on measured evidence · between: 1 must be answered directly |
| **E2** | `POST /sessions/{id}/messages` since **2026-04-01**, grouped by status **and Cloud Run revision** | 16 | ≈0 requests → dead traffic · all 5xx → a live caller exists, identify before removing · **any 2xx → the source analysis is wrong and must be redone** |
| **E3** | S7 Phase 0: transferred agents from `activities` (`activity_type='agent_transferred'`), reconciled against `agent_transfer_invites` (`status='accepted'`); compare `agents/{id}.organization_id` against `agent_datastores` table headers, `agent_user_memory`, `lead_profiles` | 17, 18 | Output three disjoint counts: `missing` / `present-and-correct` / **`present-and-wrong`** |
| **E4** | `agent_users` recovery join — `person_hash(channel_user_id)` against `agent_datastores` entry ids, per agent | D2/D3 sizing | Recovery covers only channels calling `upsert_agent_user`; web-chat-only agents report separately |
| **E5** | Session-row count by `user_key_kind`, grouped by agent and table | 5, migration | Expected to concentrate in web-chat agents; material presence elsewhere is a new finding |
| **E6** | Does mcp-deployer / agent-eval / finance-engine use the **same Firestore database** as studio, and are their collections top-level? | Security scope | **Highest-value follow-up** — until answered, their catch-all exposure cannot be assessed. Answerable from code + deployment config, no data access |
| **E7** | S2 recount — enumerate every collection reachable by the catch-all at `8cee761c` | S2 | The earlier *"~15 collections"* figure came from the stale checkout and is withdrawn |
| **E8** | `HOTPATH_DOC_CACHE_ENABLED` per environment | 11 | If already on in prod, 30s is the *de facto* accepted lag and G1 ratifies rather than chooses |
| **E9** | Are `context_facts` candidates human-verified, or auto-promoted? | Decision-gateway scoping | If auto-promoted, the `candidate → active` gate is not a real gate |

**`[UNMEASURABLE]` — do not commission.** Fragmentation per human. Computing it requires knowing
which `person_hash` values are one human — the mapping whose absence *is* the finding. No access
would fix it.

---

# Part 4 — Routed defects (no decision; assign an owner)

| ID | Defect | Evidence | Route to |
|---|---|---|---|
| **R1** | `routers/sessions.py:462` and `:568` call `process_message_universal` / `stream_response`, **defined nowhere** since 2026-04-01 | `[CODE]` `8df0e02`; `Agent` defines 17 methods, neither among them | Runtime owner. **True whichever way 16 goes** |
| **R2** | `person_hash` and `memory_doc_id` are textually independent implementations of the identical digest, with no test, import or shared constant linking them | `[CODE]` `olbrain-shared 8a0f0b5:columns.py:35` vs `agent_memory_service.py:92-97`. **They have never diverged** — verified by pickaxe across both histories | Shared-lib owner. One assertion closes it: `memory_doc_id(a,k).endswith(person_hash(k))` |
| **R3** | `README.md`, `WEBHOOK_ARCHITECTURE.md`, `OUTREACH_EXECUTION_GUIDE.md` still document the API removed six months ago | `[CODE]` `README.md:340,348,355,385`; `WEBHOOK_ARCHITECTURE.md:21` | Runtime owner |
| **R4** | **S1** — `agents` is in **neither** catch-all exclusion list; any authenticated user can read or write any agent document | `[CODE]` `olbrain-studio 8cee761c:firestore.rules`, read=0 / write=0 matches | Already routed: QF-1's answer attaches the fix to the ownership move |
| **R5** | **S6** — `agent_users` is **write-excluded but not read-excluded**, and it is the one person store holding identifiers **unhashed** | `[CODE]` 33-entry write list, 17-entry read list at `8cee761c`; `firebase_service.py:274-295` | Security owner. **Verify client-SDK readers before acting** — the S3 episode is the caution |
| **R6** | Override `approve` / `retire` endpoints have no router-, endpoint- or global-middleware authorization; `approved_by` is a caller-supplied string | `[CODE]` `exceptions.py:18, 274-311`; `main.py:111`; only `CORSMiddleware` added globally | Workflow-design owner. **Finding requiring confirmation, not a confirmed exposure** — deployment gating (Cloud Run ingress, IAP) was not traced |
| **R7** | `olbrain-mcp-deployer` writes `agents` (13 refs) and `mcp_configs` (4) — an `agents/{id}` writer QF-1's transition plan does not name | `[CODE]` `0efd05f` | QF-1 / agent-design. Add to the writer inventory |
| **R8** | S7's *"fill only missing values"* backfill would preserve non-null-but-wrong `organization_id` on transferred agents | `[CODE]` transfer cascade omits person stores. Severity bounded — both stores self-heal on write; residue is quiet tables and dormant persons | S7 owner. Procedure in `s7-backfill-correction-note.md` §4 |

---

## Precision note

*Investigation complete* ≠ *decision made*. *Evidence missing* ≠ *production access missing*.
*Implementation blocked* ≠ *implementation merely not yet authorised*.

**Ready but not authorised** (investigation complete, design unambiguous, awaiting instruction):
per-mutation `mutation_id` idempotency (`[CONTRACT]` §7, independent of G8); single-scope
deletion; a typed work-class property on queued work; R2's guard test; R3's documentation fix;
E3's read-only Phase 0.

**No entry in this document constitutes a decision, and no option is recommended.**
