# Senior Review Reconciliation

Reconciliation date: 2026-09-25. **Revised the same day** after the reviewed dashboard was
supplied (§0.1) and the repository evidence base was found to be stale and refreshed (§0.2).
Scope: reconcile the senior-reviewed Decision Dashboard against the existing investigation.

**What this document is:** a source trail. For each item it records what we previously
believed, what the senior reviewer (Jay) corrected or answered, what the repository
actually proves, whether those agree, whether the target architecture changes, and what
is still unresolved.

**What this document is not:** an architecture contract, a PostgreSQL schema, a migration
plan, or a decision of its own. It records decisions made elsewhere; it makes none.
`artifacts/architecture-contract.md` remains the only normative document.

**Relationship to `investigation/reconciliation.md`:** that document (2026-09-19) is
Reconciliation Pass 1 — current production versus the target contract. This document is a
different axis: senior review versus our own investigation. It does not supersede Pass 1
and does not restate it.

---

## 0. Provenance and evidence base — read this first

### 0.1 The reviewed dashboard (resolved)

The reviewed copy was supplied as a shared artifact and has been read in full:

`https://claude.ai/artifact/RQxvGUCuqQsWJZ6NdkTzDK`
— *"OLBrain Decision Dashboard — Reviewed"*, Jay's answers recorded 2026-09-22.

It is **not** the file in this workspace. `artifacts/senior-decision-dashboard.html`
(2026-09-22) is the **pre-review baseline** — its own source comment reads *"No decision is
answered"*, and an earlier pass of this document therefore had to record every card as open.
That limitation is now lifted. Both copies are kept distinct and neither has been modified.

The reviewed copy carries, in its own words:

- **9 of 24 cards answered** (10 answer fields — D1 carries two, D1(a) and D1(b)).
- **7 evidence corrections applied**, each checked against `origin/main` by
  `git grep` / `git show` in Jay's workspace, with the original wording retained on the card.
- **G1–G8 routed, not answered** — purple "routing" boxes, not values.
- Its own stated limit: *"Nothing here writes back to the source documents — the answers
  still have to be recorded in the source trail."* Recording them is what §2 does.

The reviewed artifact also states a limitation of its own, which pairs with ours in §8:
*"The normative documents (`architecture-contract.md` and the `investigation/` set) exist in
no repository Jay can read, so the §16 quotations (G1–G8) could not be checked and are
reproduced as received."*

### 0.2 The evidence base was stale — every repository, and it mattered

**This is the most consequential finding of this pass, and it reaches beyond this document.**

The reviewed artifact cites the commits Jay verified against. None of them existed in this
workspace. A `git cat-file -e` check failed for all five cited SHAs, and a fetch then showed
that **all ten repositories were behind true `origin/main`** — in some cases by a great deal.

The trap is specific and worth naming, because it is easy to repeat: `git rev-parse
origin/main` returns the **last-fetched** value. Every repository reported
`HEAD == origin/main`, which reads as "in sync" and in fact meant **"never fetched since
clone."** The earlier pass of this document published a table asserting nine of ten repos
were in sync. That table was wrong, and it is corrected below.

All ten have now been fetched (a read-only operation: remote-tracking refs only — no working
tree change, no push, nothing on the prohibited list, and expressly prescribed by CLAUDE.md's
*"When local state may be stale, inspect `origin/main` directly"*).

| Repository | Stale ref we used | Jay verified at | True `origin/main` (2026-09-25) |
|---|---|---|---|
| olbrain-agent-design | `bbc85c8` | `089fdbf` | `51ffe3b` |
| olbrain-agent-engine | `8720720` | `73d66e6` | `e43654e` |
| olbrain-agent-runtime | `b2401a0` | `9e709d2` | `8df0e02` |
| olbrain-knowledge-vault | `6d76083` | — | `66b02e2` |
| olbrain-research-design | `d044fce` | — | `e211584` |
| olbrain-research-runtime | `d1caecd` (local) / `d2e3f7a` | — | `6b81691` |
| olbrain-shared | `a837b95` | `origin/main` | `8a0f0b5` |
| olbrain-studio | `252f7887` | `dd9910b4` | `8cee761c` |
| olbrain-studio-backend | `6ada46a` | `2f4fdee` | `ca9724a` |
| olbrain-workflow-runtime | `5d48437` | — | `1978f4a` |

**Consequences.**

1. It fully explains the one apparent conflict this pass raised. Our reading of the agents
   subcollection security rule came from a file that predated the fix (see C6). **Jay was
   right and we were reading history.**
2. It retroactively qualifies **every `file:line` citation in the whole `investigation/` set**,
   not only this document. Those documents were written against the stale checkouts. The
   behaviours they describe are, on the spot checks done here, still accurate — but line
   numbers have moved and at least one security rule has materially changed.
3. Concrete drift already observed: `olbrain-shared` is at version **3.1.2**, where the stale
   checkout showed **2.47.0**.

**All citations in this document are therefore pinned to explicit commit SHAs, not to
`origin/main`**, which moves. Prior investigation documents were not re-verified wholesale;
see §7.2.

---

## 1. The seven senior corrections, verified

Each is verified against the refreshed evidence base. "Agrees" means the repository supports
the statement as written.

### C1 — `agent_datastores` tenancy · **CONFIRMED, and completed**

- **Previously believed.** No tenancy information anywhere in the store.
- **Jay's correction.** No entry document carries `organization_id`, but **both writers**
  stamp it on the table header `agent_datastores/{agent}/tables/{table}`. The tenancy key
  exists one level up.
- **Source (`olbrain-agent-runtime 8df0e02`).** Both halves confirmed, and the "both writers"
  claim — which the earlier pass had to leave open — is now closed:
  - Extract writer: `services/extract_entry_writer.py:83` stamps `"organization_id"` in the
    header `set(..., merge=True)`; the entry payload that follows carries `entry_id`,
    `last_session_id`, `user_key_kind`, `channel`, `values`, `updated_at` and no org field.
  - Live tool: `core/tools/datastore_executor.py:347-353` — a batch whose `table_ref` write
    includes `"organization_id": spec["organization_id"]`, while the entry write beside it
    (`entry_id`, `session_id`, `values`, `created_at`, `updated_at`) does not.
- **Agreement.** **Agrees, exactly.**
- **Impact.** Bounded. Tenancy sits one level above the row, so a row-level tenancy predicate
  must join to the parent header or denormalise the field down. A migration mechanic, not a
  change to the Evidence → Claim → Current State model.
- **Unresolved.** Nothing. The earlier open item (does every writer stamp it?) is closed.

### C2 — The "~60 write sites" belongs to `agents/{id}`, not `agent_datastores`

- **Previously believed.** QF-1: *"Ten write sites across three repositories"* for
  `agents/{id}`.
- **Jay's correction, as the reviewed artifact states it.** *"**QF-1 undercounted writers
  ~4×.** Roughly sixty write sites, not ten — including studio-backend's own agent creation
  path, its lifecycle service and three migration scripts, agent-engine's
  `storage_service.py` (seven sites) and agent-design's `prompt_generator.py` (five)."*
- **What this corrects — in our own reading, not in the source.** An earlier pass of this
  document attached "~60" to `agent_datastores` writers and then counted `agent_datastores`
  mutations to test it. **That was a misattribution on our side.** The figure is a correction
  to QF-1's `agents/{id}` enumeration. There is no counting dispute and no unreconciled
  number; the comparison was simply between two different questions.
- **On `agent_datastores`:** the three *logical* writer lanes (extract-mode, live agent tool,
  operator CRUD) are unchanged and remain correct — they describe distinct identity models and
  durability contracts, not call sites.
- **Agreement.** **Agrees.** Jay's enumeration is recorded as given; the ~60 was not
  independently recounted, and the named sources are specific enough to re-derive if needed.
- **Impact.** Changes migration *effort estimation* for the agent document, and sharpens
  QF-1: four times more writers than believed, with no shared version field or CAS between
  them.
- **Unresolved.** Nothing requiring senior input.

### C3 — `agent_datastores` cap behavior · **CONFIRMED**

- **Previously believed.** *"The live agent-tool writer bounds its writes by size-based LRU
  eviction."* — D6 evidence, baseline dashboard.
- **Jay's correction.** No eviction exists. `_add()` returns `limit_exceeded` at the cap. Only
  the extract writer silently drops.
- **Source (`olbrain-agent-runtime 8df0e02`).** Behaviour unchanged from the stale checkout;
  line numbers shifted by one:
  - `core/tools/datastore_executor.py:325` — `limit_exceeded` at `MAX_PER_SESSION = 200`
    (line 76), message ends *"Nothing was recorded."*
  - `core/tools/datastore_executor.py:333` — `limit_exceeded` at `MAX_PER_TABLE = 5000`,
    *"This table is full … Nothing was recorded."*
  - No `evict` / `lru` code anywhere in either writer.
  - `services/extract_entry_writer.py:70-73` — at `MAX_PER_TABLE`, logs
    *"dropping a new person"* and returns `None`. **New persons only**; people already in the
    table keep upserting past the cap.
- **Agreement.** **Agrees, exactly.** The prior "LRU eviction" statement was factually wrong
  and is withdrawn.
- **Impact.** Removes a problem rather than creating one — and D6 is now **answered** on this
  basis (§2).

### C4 — Repository scope · **CONFIRMED**

- **Previously believed.** Four repositories absent: `olbrain-mcp-deployer`,
  `olbrain-agent-eval`, `olbrain-finance-engine`, `olbrain-agent-cloud`.
- **Jay's correction.** `olbrain-agent-cloud` is `olbrain-agent-runtime` under its former name
  (GitHub redirects it); mcp-deployer and agent-eval are already cloned **in Jay's workspace**;
  finance-engine exists on GitHub (pushed 2026-09-22).
- **Source.** Rename confirmed — `git remote -v` in this workspace's agent-runtime checkout
  returns `https://github.com/Olbrain/olbrain-agent-runtime.git`. The other three are **not in
  this workspace**; `repos/` holds exactly ten directories. The reviewed artifact's own wording
  ("in Jay's workspace") resolves what the earlier pass flagged as a possible disagreement —
  it was a difference of *which* workspace, not a factual dispute.
- **Agreement.** **Agrees.**
- **Impact.** Feeds QF-3, which is now **answered**: clone all three (§2).

### C5 — Configuration path · **CONFIRMED, and it exposes a live defect**

- **Previously believed.** QF-5: *"the legacy Firestore config path is … the only
  agent-construction path currently wired."*
- **Jay's correction.** The `Agent` + `FirestoreConfigService` object is built for the
  sessions/streaming routers, but `routers/sessions.py:462` calls
  `agent.process_message_universal()` and the stream branch calls `agent.stream_response()` —
  **neither is defined anywhere on `origin/main`.** Every channel router loads configuration
  from GCS `active_config.json`.
- **Source (`olbrain-agent-runtime 8df0e02`).** Confirmed, including the part the earlier pass
  missed:
  - `routers/sessions.py:462` — `response_data = await agent.process_message_universal(abstract_message)`
  - `routers/sessions.py:568` — `async for chunk in agent.stream_response(`
  - `git grep -E "def (process_message_universal|stream_response)"` returns **nothing**.
  - The earlier pass verified only that the *definitions* were absent and never checked the
    *call sites*. Both exist. **These two branches call methods that do not exist and would
    raise `AttributeError` if reached.**
  - Firestore construction remains wired: `core/agent.py` keeps `use_firestore_config: bool = True`
    as the constructor default taken by `dependencies.py` → `factory.create_agent(agent_id)`.
    `create_agent_with_settings()` still has no non-documentation callers.
- **Agreement.** **Agrees** — and is more serious than a reframing. Two dead message branches
  are wired to undefined methods.
- **Impact.** This is the substance of QF-5's answer: find out whether the endpoint is hit at
  all before deciding anything (§2).

### C6 — Agents subcollection security · **CONFLICT RESOLVED — Jay was right**

- **Previously believed.** *"`agents/{id}/{sub}/**` grants authenticated read with no
  exclusion list, covering `mcp_configs`."*
- **Jay's correction.** *"Security item 3 was false. `agents/{id}/{sub}/**` does carry
  exclusions: read excludes `mcp_configs`; write excludes `mcp_configs` and `owner_lessons`"*
  (`olbrain-studio dd9910b4`, ~L989).
- **Source (`olbrain-studio 8cee761c:firestore.rules:1087-1090`), verbatim:**

  ```
  match /agents/{agentId}/{sub}/{rest=**} {
    allow read: if isAuthenticated() && sub != 'mcp_configs';
    allow write: if isAuthenticated() && sub != 'owner_lessons' && sub != 'mcp_configs';
  }
  ```

  **Exactly as Jay states.** An earlier pass of this document raised this as an evidence
  conflict, citing `firestore.rules:910-913` where the read carried no exclusion at all. That
  reading came from `252f7887` — a commit predating the fix. **The conflict was an artifact of
  our stale checkout, not a disagreement.** It is withdrawn.
- **Still true, and confirmed independently at `8cee761c`:** `agents` appears in **neither**
  exclusion list of the top-level two-segment catch-all `match /{collection}/{docId}`
  (line 836). Any signed-in user can still read or write any agent *document*. This is Jay's
  second clause, and it is what QF-1's answer proposes to fix.
- **Minor drift worth noting, not a finding:** the comment block above the rule still reads
  *"open EXCEPT `owner_lessons` writes … Reads stay granted"*, which the code no longer
  matches. Documentation lag only.
- **Impact.** Per-agent MCP bindings are **protected**, contrary to what the baseline dashboard
  and our first pass both said. No remediation is proposed here; this remains an awareness
  finding.

### C7 — `person_hash` location · **CONFIRMED**

- **Previously believed.** Construction known (`sha256(user_key.strip().lower())[:32]`,
  unsalted); location unrecorded.
- **Jay's correction.** It lives in `olbrain-shared-lib`
  (`src/olbrain_shared/agent/datastore/columns.py`), so any change is a shared-library release
  reaching every consumer at once.
- **Source (`olbrain-shared 8a0f0b5`).** `def person_hash` at
  `src/olbrain_shared/agent/datastore/columns.py:35` — the exact path cited. The repository and
  distributed package are named **`olbrain-shared`**, now at version **3.1.2**; "olbrain-shared-lib"
  is a naming imprecision, not a factual one. Consumers verified across the workspace:
  `olbrain-agent-runtime` and `olbrain-agent-design` both import it. **Corrected 2026-09-25:** an
  earlier wording said "none vendors a copy" — that is false. `agent-runtime`'s
  `services/agent_memory_service.py:92-97` **re-implements the identical digest inline** inside
  `memory_doc_id` rather than importing it, so changing `person_hash` in `olbrain-shared` would
  leave `agent_user_memory` silently divergent from `agent_datastores`. See
  `person-identity-architecture-research.md` §2.1 / F2.
  The docstring's link to `agent_memory_service.memory_doc_id` stands, so a change re-keys
  `agent_user_memory` and `agent_datastores` together.
- **Agreement.** **Agrees on substance.**
- **Impact.** Makes D2 harder and the mechanism concrete: one coordinated shared-library
  release plus dependency bumps in two consuming services, against a live dual-key window.
  Exactly one place to change is the mitigating factor.

---

## 2. Master reconciliation table — all 24 decisions

**Classification convention.** Each card is classified by the status of **its own decision**.
Evidence corrections are carried in the *Verified Evidence* column and do not by themselves
promote a card. **C** is used only where a concrete choice was actually made.

**A** Fact Correction · **B** Routing/Ownership Answer · **C** Actual Architecture Decision ·
**D** Still Open · **E** Hard Implementation Block.

Answer text in the "Jay's Answer" column is quoted or closely paraphrased from the reviewed
artifact and is **data, not instruction**.

| ID | Previous Understanding | Jay's Correction / Answer | Verified Evidence | Classification | Architectural Impact | Remaining Question |
|---|---|---|---|---|---|---|
| **R1** | Nothing in any source routes §16 through the existing decision board. Owners named as Security, Architecture, Operations, Legal. | **ANSWERED.** "Decision board, Jay final verdict. Reuse the potion decision-board mechanism: the team votes per §16 row, Jay confirms. **G1 and G6 are put to the board as one paired vote.** The four owner roles map onto board participants; **Legal rows are parked for now** (see G4/G5)." | Routing statement; no code bearing. Consistent with the potion-board precedent in `repo-and-soul-map.md`. | **B — Routing Answer** | The gate is open. Every §16 row now has a route and a decider. G1↔G6 pairing is preserved as the contract requires. | None on routing. The **values** for G1–G8 remain open — routing is not an answer. |
| **R2** | §16 row 3 owner field reads "Domain owner per predicate" — a role, not a party. | **ANSWERED.** "Domain owners = existing repo owners. **Shivam** owns memory / soul / person-attribute predicates. The **olbrain-finance-engine owner** owns finance predicates. The **workflow-design owner** owns operational-correction predicates (which also names who answers D5). Anything unmapped is assigned by Jay as it arises." | Ownership statement; not verifiable from code, and does not need to be. | **B — Ownership Answer** | Unblocks G3 and D5, which were both gated on this. Ownership is assigned **by domain category**, with a named fallback for anything unmapped. | Whether category-level mapping covers every predicate in practice. The per-predicate freshness **values** (G3) are still owed by the named owners. |
| **G1** | "60s general, tighter for sensitive operations" — PROPOSED / UNCONFIRMED. Coupled to G6. | **ROUTED, not answered.** "Decision board, Jay final verdict." Voted as one pair with G6. | Unchanged. | **D — Still Open** | Capability caching stays blocked; online-only proceeds. | Confirm or replace the TTL and give the tighter value. **UNRESOLVED.** |
| **G2** | "Current + immediate predecessor, only where explicitly marked compatible" — PROPOSED. | **ROUTED, not answered.** | Unchanged. | **D — Still Open** | Single-version resolution buildable; policy-migration path not completable. | Confirm or replace the compatibility window. **UNRESOLVED.** |
| **G3** | Per-predicate `max_staleness` / `stale_read_policy` / `stale_write_policy`; owner was a role, not a party. | **ROUTED, not answered** — but **R2 now names the owners.** | Unchanged. | **D — Still Open** | **No longer blocked behind R2** — now awaiting values from named owners. | Per-predicate values from Shivam / finance-engine owner / workflow-design owner. **UNRESOLVED.** |
| **G4** | No maximum un-recomputed window. Contract flags it as the item with legal exposure. | **ROUTED, and half-parked.** "Parked — no contractual or legal work is to be done right now; no Legal seat is named. **The Operations half of this row can still be voted.**" | Unchanged. | **D — Still Open** | Exclude-don't-serve behaviour implementable now; only the bound is missing. Operations can proceed without Legal. | The Operations-side window. The Legal side is parked by decision. **UNRESOLVED.** |
| **G5** | Seven §10 classification fields per aggregate dataset; none assigned. No default proposed, deliberately. | **ROUTED, and PARKED.** "No contractual or legal work is to be done right now; no Legal seat is named. When reopened, Jay classifies with technical input from the finance-engine owner. **This row stays a hard block until then.**" | Unchanged. Fed by QF-2, also parked. | **E — Hard Block (parked by decision)** | Blocks every aggregate containing customer contribution, and the whole deletion/retention design — now **indefinitely**, by choice rather than by absence. | Not "what is the classification" but **"how long does parked last, and what proceeds meanwhile?"** See Q3. |
| **G6** | Which operations require online authorization. Coupled to G1. | **ROUTED, not answered.** Paired vote with G1. | Unchanged. | **D — Still Open** | Treat everything as online-only meanwhile — safe, slower. | Name the operations. **UNRESOLVED.** |
| **G7** | Postgres-backed nonce table with TTL sweep, no Redis in MVP — PROPOSED. | **ROUTED, not answered.** | Unchanged. | **D — Still Open** | Sensitive-operation replay protection only. `mutation_id` idempotency is independently mandated and buildable. | Confirm the mechanism; define "sensitive". **UNRESOLVED.** |
| **G8** | Disposition of work rejected by a `scope_generation` bump. "There is no safe default." | **ROUTED, not answered.** Owner is Operations, not Legal — **not parked**. | Unchanged. | **E — Hard Block** | All bulk deletion blocked. Single-scope deletion implementable. | Define the retry and dead-letter policy. **UNRESOLVED** — but routable now, and the one hard block not parked. |
| **D1** | Three writers; no entry carries `organization_id`; no reconstructible Evidence lineage for extract rows. | **BOTH SUB-DECISIONS ANSWERED.** **D1(a):** "**Option B.** Existing extract-mode rows migrate as un-provenanced **Memory**, not Claims. Future extractions build real Claims going forward. The prompt-read path must keep rendering these rows in the same step." **D1(b):** "**Operator wins.** A human edit pins the field. A later extraction may only fill empty fields or propose a change; it never overwrites an operator value. **Requires a per-field authority marker (writer + timestamp) on the row.**" | C1 confirmed at `8df0e02` — both writers stamp org on the header, neither on the entry. C3 confirmed. Provenance gap re-confirmed: entries carry `last_session_id` (overwritten every turn) and no extraction-run id. | **C — Architecture Decision** | **The largest migration question is closed.** Extract rows land in Memory, so the Evidence plane stays clean and no placeholder Evidence is minted. D1(b) introduces a **new schema requirement**: a per-field authority marker (writer + timestamp), which did not exist in any prior design note. | Mechanical, not architectural: how the per-field authority marker is represented, and how "propose a change" surfaces to an operator. Both are design work, now unblocked. |
| **D2** | Unsalted `sha256(strip+lower)[:32]` over phones and emails; shared with `agent_user_memory.memory_doc_id`; no proposal exists. | **NOT ANSWERED.** Evidence corrected only (C7). | Confirmed at `olbrain-shared 8a0f0b5:src/olbrain_shared/agent/datastore/columns.py:35`. Package now v3.1.2. Two consumers import it, but `agent-runtime`'s `memory_doc_id` re-implements the same digest inline (`agent_memory_service.py:92-97`) — corrected 2026-09-25; the earlier "none vendors" wording was false and understated the blast radius. | **D — Still Open** | Any change is a coordinated shared-library release plus two dependency bumps, against a live dual-key window. | Approve a construction, key location, tenancy model and rotation procedure. Must not become an authorization bridge (§14). **UNRESOLVED.** |
| **D3** | Rows whose original `user_key` is unrecoverable cannot be re-keyed; only `user_key_kind` is stored. | **NOT ANSWERED.** | Re-confirmed at `8df0e02` — the entry stores `user_key_kind`, never the raw key. | **D — Still Open** | Blocks completion of any identity re-keying. Follows from D2. | Retained under the old key, orphaned, or deleted? **UNRESOLVED.** |
| **D4** | Opaque surrogate person id — "attractive, but not established by any source material". | **NOT ANSWERED.** | Unchanged. | **D — Still Open** | Blocks nothing directly but **reframes D2 and D3**, and changes the primary-key design of every person-keyed table. | Adopt the surrogate-id model, or decline it. **UNRESOLVED — and now one of the few genuine schema blockers left.** |
| **D5** | `architecture-freeze.md §3` describes an "operational-correction authority domain" and does not name it. | **NOT ANSWERED** — but **R2 names its owner**: the workflow-design owner. | Unchanged. | **D — Still Open** | **No longer blocked behind R2.** Registry population, not a contract change. | The workflow-design owner must name the authority domain and the approver. **UNRESOLVED, but now addressable.** |
| **D6** | "Size-based LRU eviction" (live tool) + silent drop (extract writer). | **ANSWERED.** "**Hard rejection at the boundary, both writers.** Keep the live tool's behaviour. **The extract writer must surface the drop instead of swallowing it.** No retention semantics, so **no legal owner is inherited**." | C3 confirmed at `8df0e02:325, 333` (live tool) and `extract_entry_writer.py:70-73` (silent drop). Card retitled from "eviction caps" to "write caps". | **C — Architecture Decision** | Clean: hard rejection maps directly onto an append-only Evidence model. **Severs the D6 → G5 dependency** — the baseline card said retention would inherit G5's legal owner; "no retention semantics" removes that edge entirely. | Mechanical: change the extract writer to surface rather than swallow the drop. A code change, out of scope here. |
| **D7** | Contract contains no scope-exclusion vocabulary; the procedural-memory exclusion lives only in an investigation document. | **NOT ANSWERED.** Deferred by instruction, not declined. | Unchanged. | **D — Still Open** | Independent of everything else. Until adopted, contract and freeze must be read together indefinitely. | Adopt Patch 19, or decline it. **UNRESOLVED.** Lowest-cost card on the board. |
| **QF-1** | "Ten write sites across three repositories… No owner-of-record is declared in any source." | **ANSWERED.** "**agent-design is the owner-of-record.** It is the publish path under the potion decisions. **studio-backend and agent-engine become clients of it over time.** The catch-all fix (add `agents` to both exclusion lists in `firestore.rules`) travels with the ownership." Plus the ~60 correction (C2). | Owner field on the reviewed card updated to "agent-design (Jay, 2026-09-22)". The catch-all gap is independently confirmed at `olbrain-studio 8cee761c` — `agents` is in neither exclusion list of the two-segment catch-all (line 836). | **C — Architecture Decision** | Closes the highest-risk single item in the storage picture. Gives a target end-state (agent-design authoritative, others as clients) and attaches the security fix to the ownership move rather than leaving it orphaned. | Mechanical and sequencing: what coordination replaces the absent version field / CAS during the transition, given ~60 writers and studio-backend's transfer path reassigning `organization_id` with a plain `.update()`. |
| **QF-2** | Technical purpose clear from source; legal classification is not a code question. Nine billing-adjacent collections in no registry. | **ANSWERED AS ROUTING, THEN PARKED.** "Jay classifies, with the finance-engine owner supplying the technical facts per collection. **But no contractual or legal work is to be done right now, so this and G5 stay parked with no Legal seat named.** Code fact that helps when reopened: the finance / P&L collections are already server-only under `organizations/{org}` per the rules comments." | The server-only posture for finance collections is consistent with the organizations-subcollection block observed at `olbrain-studio 8cee761c`. | **E — Hard Block (parked by decision)** | Feeds G5. Parked together with it. The decider is now named, which is progress; the work is deliberately not being done. | Same as G5: **how long does parked last, and what proceeds meanwhile?** See Q3. |
| **QF-3** | Four absent repositories; three of twelve unknowns exist solely because of their absence. | **ANSWERED.** "**Yes — clone all three real repositories** (mcp-deployer, agent-eval, finance-engine) and finish the Firestore inventory. **olbrain-agent-cloud is dropped from the list as a duplicate of agent-runtime.** **This is a clone, not a programme decision.**" | Rename confirmed via `git remote -v`. The three remain absent from **this** workspace; Jay's copies are in his. | **C — Architecture Decision** (scope) | **Unblocks inventory bounding**, which is a precondition for sizing any schema. Reframes the question entirely: it was posed as a programme decision and answered as routine work. | Operational only: perform the clones **in this workspace** and finish the inventory. Nothing to ask. |
| **QF-4** | Rules file names missing `organization_id` as the blocker to closing cross-org reads; remedy called "S7"; backfill script targets only `clix-capital-prod`. | **ANSWERED.** "**Scheduled now as a bounded task — WHITEBOARD.md WB-006 (unclaimed).** Order: **stamp `organization_id` on new rows at every runtime write site**, **backfill india-prod** (dry-run count first, adapting the Clix script), **then move the collections into an org-scoped rules block with rules tests.** **Tightening rules first would break live reads.**" | The catch-all exclusion mechanism is confirmed at `olbrain-studio 8cee761c`. | **C — Architecture Decision** | Funded, scheduled, sequenced — with the ordering hazard called out explicitly. Directly relevant to any target tenancy predicate needing a row-level org key, and the same shape as C1's header-level tenancy. | Operational: WB-006 is **unclaimed**. Who picks it up? |
| **QF-5** | "`create_agent_with_settings()` has zero callers… the legacy Firestore config path is the only agent-construction path currently wired." | **METHOD ANSWERED, DECISION NOT MADE.** "**Investigate first.** Pull production request logs for `POST /sessions/{id}/messages` (stream and non-stream) to confirm whether the endpoint is hit at all before retiring or retaining `FirestoreConfigService`. **If** it is dead traffic, the expected outcome is: GCS canonical; remove the Firestore path, the two dead message branches and `create_agent_with_settings`." | C5 confirmed at `8df0e02` — and extended: `routers/sessions.py:462` and `:568` **call methods that are defined nowhere**. | **D — Still Open** | A conditional expected outcome is not a decision. What *is* established: two wired branches call undefined methods and would fail if reached. That is a live defect, independent of the config question. | Run the log pull, then decide. **UNRESOLVED until the traffic data exists.** Note the defect stands regardless of which way the config decision goes. |
| **Q-S4** | `data_query` opens connections to customer/third-party databases from frozen design-time config; read-only by regex; **no tenancy check on the SQL**. | **NOT ANSWERED.** | Not re-verified against the refreshed base this pass. | **D — Still Open** | Blocks nothing in the target design — which is why it risks being forgotten. | Name the owner and the credential/SQL review process. **UNRESOLVED.** |
| **Q-S5** | research-design's `write_profile` is the platform's only genuine CAS; caller retries up to 3. §7/§12 rule 9 forbid infrastructure retry. | **NOT ANSWERED.** | Not re-verified against the refreshed base this pass. `olbrain-research-design` is now at `e211584`. | **D — Still Open** | Decides whether the one working OCC precedent is a model to generalise or a pattern to correct. | Interpret the infrastructure/application retry boundary. **UNRESOLVED.** |

### Classification tally

| Classification | Count | IDs |
|---|---|---|
| **A — Fact Correction** | 0 | (corrections are carried in the evidence column; none stands alone as a card outcome) |
| **B — Routing / Ownership Answer** | 2 | R1, R2 |
| **C — Actual Architecture Decision** | **5** | D1 (a+b), D6, QF-1, QF-3, QF-4 |
| **D — Still Open** | 14 | G1, G2, G3, G4, G6, G7, D2, D3, D4, D5, D7, QF-5, Q-S4, Q-S5 |
| **E — Hard Block** | 3 | G5 *(parked)*, G8, QF-2 *(parked)* |
| **Total** | **24** | |

Answered cards (9, matching the reviewed artifact's own count): R1, R2, D1, D6, QF-1, QF-2,
QF-3, QF-4, QF-5. QF-2's answer routes and parks rather than decides, and QF-5's prescribes a
method rather than a choice — which is why "9 answered" yields **5** actual architecture
decisions, not 9.

---

## 3. Security-awareness findings — reconciled

Awareness only. No remediation is proposed. All verified at `olbrain-studio 8cee761c`.

| # | Finding as previously stated | Status after this pass |
|---|---|---|
| S1 | `agents/{id}` effective access is broader than intended — the precise owner rule is OR-superseded by the two-segment catch-all, in which `agents` appears in neither exclusion list. Any signed-in user can read or write any agent, including reassigning `owner_id`/`organization_id`. | **CONFIRMED at current HEAD.** `agents` appears in neither exclusion list of `match /{collection}/{docId}` (line 836). Jay confirms it independently and **QF-1's answer attaches the fix to the ownership move** — "add `agents` to both exclusion lists". |
| S2 | ~15 collections readable cross-org because they lack `organization_id`. | **UNCHANGED; not re-verified against the refreshed base.** Now covered by **QF-4's answer** (WB-006), which sequences the fix: stamp, backfill, then tighten rules. |
| S3 | The agent subcollection catch-all is too broad — grants authenticated read with no exclusion list, covering `mcp_configs`. | **WITHDRAWN — the finding was false.** At `8cee761c:1087-1090` the rule excludes `mcp_configs` from reads, and `mcp_configs` **and** `owner_lessons` from writes. Our first-pass reading came from stale commit `252f7887`. **Per-agent MCP bindings are protected.** See C6. |
| S4 | The secure pattern is: explicit deny **plus** catch-all exclusion. | **CONFIRMED and load-bearing.** It remains the correct lens — and it is exactly why S1 is still real while S3 is not. |
| S5 | `secrets`, `memberships_index`, `agent_datastores`, `agent_user_memory` have verified protections. | **UNCHANGED; not re-verified against the refreshed base.** The earlier pass's line citations for `agent_datastores` came from the stale file and should not be relied on; the behaviour (excluded from the catch-alls) was not contradicted by anything seen at `8cee761c`. |

### Remaining §16 governance parameters

All eight rows (G1–G8) are **routed but unfilled**. R1 supplies the mechanism — decision board,
Jay's final verdict per row, G1 and G6 as one paired vote — so the contract's condition (every
row filled or formally marked deployment-time configuration with a named owner) is now
*reachable*, which it was not before. **Zero of eight rows carry a value.** G4's Legal half and
G5 entirely are **parked by decision**; G8 is the one hard block that is neither parked nor
gated and can be voted immediately.

---

## 4. What we now know

### 4.1 Facts established

1. **`agent_datastores` has tenancy one level above the row** — **both** writers stamp
   `organization_id` on the table header; neither stamps it on the entry.
2. **Nothing evicts.** The live tool hard-rejects with `limit_exceeded` at 200/session and
   5,000/table. No LRU code exists. Only the extract writer silently drops, and only a **new**
   person at the table cap.
3. **Per-agent MCP configuration is protected** — the subcollection rule excludes
   `mcp_configs` from reads and writes. The earlier contrary finding was read from a stale file.
4. **Any signed-in user can still read or write any agent document.** `agents` is in neither
   top-level catch-all exclusion list. This is the real, current exposure.
5. **Two wired endpoints call methods that do not exist.** `routers/sessions.py:462` calls
   `process_message_universal()` and `:568` calls `stream_response()`; neither is defined
   anywhere on `origin/main`. All channel routers load configuration from GCS
   `active_config.json`.
6. **`person_hash` has two implementations, not one.** The library definition is
   `olbrain-shared` v3.1.2 at `src/olbrain_shared/agent/datastore/columns.py:35`; `agent-runtime`
   re-implements the same digest inline in `memory_doc_id`
   (`services/agent_memory_service.py:92-97`). **Corrected 2026-09-25** — an earlier wording said
   no consumer vendors a copy. Changing one desynchronises the two stores silently.
7. **`olbrain-agent-cloud` is not a missing repository** — it is `olbrain-agent-runtime` under
   its former name.
8. **Our entire evidence base was stale.** All ten repositories were behind `origin/main`, and
   `HEAD == origin/main` meant "never fetched", not "in sync". At least one security finding
   inverted as a result.

### 4.2 Architecture decisions established

**Five cards, six decisions (D1 carries two), all supported by the reviewed source trail.**
This is the same set the §2 tally counts under **C**: D1, D6, QF-1, QF-3, QF-4.

1. **D1(a) — Extract-mode rows migrate as un-provenanced Memory (Option B).** No placeholder
   Evidence is minted; the Evidence plane stays clean; future extractions build real Claims.
   The prompt-read path must keep working in the same step.
   **D1(b) — Operator wins.** A human edit pins the field; a later extraction may fill empty
   fields or propose a change but never overwrites. **This creates a new schema requirement: a
   per-field authority marker carrying writer and timestamp.**
2. **D6 — Hard rejection at the boundary, for both writers.** The live tool's behaviour is
   kept; the extract writer must surface its drop instead of swallowing it. No retention
   semantics, therefore no legal owner is inherited.
3. **QF-1 — agent-design is the owner-of-record for `agents/{id}`.** It is the publish path;
   studio-backend and agent-engine become its clients over time. The `firestore.rules`
   catch-all fix travels with the ownership.
4. **QF-3 — clone all three repositories and finish the Firestore inventory.** Posed as a
   programme decision, answered as routine work; `olbrain-agent-cloud` is dropped as a
   duplicate of agent-runtime.
5. **QF-4 — S7 is scheduled** as WHITEBOARD.md WB-006, with an explicit order: stamp
   `organization_id` at every runtime write site, backfill india-prod (dry-run count first),
   then move collections into an org-scoped rules block with tests. Tightening rules first
   would break live reads.

Plus two routing/ownership answers that unblock others: **R1** (decision board, Jay's final
verdict, G1+G6 paired) and **R2** (domain owners = existing repo owners, with named parties per
domain and Jay assigning anything unmapped).

### 4.3 Hard blockers — and the new shape of the problem

| ID | Blocker | Status |
|---|---|---|
| **G8** | Bulk-deletion retry and dead-letter policy | **Open and routable now.** Operations owns it; not parked, not gated. The one hard block that can move immediately. |
| **G5** | Aggregate retention / deletion classification per dataset | **Parked by decision.** No Legal seat named. Stays a hard block until reopened. |
| **QF-2** | Financial / aggregate legal classification | **Parked by decision**, together with G5. Decider named (Jay, with finance-engine owner on technical facts). |

**The important change is qualitative.** Before the review, G5 and QF-2 were *unanswered*.
They are now *deliberately deferred*. Parked is in one sense worse than open: an open question
can be answered when someone gets to it, whereas a parked one will not be answered until a
decision is taken to unpark it. Everything downstream of them — all aggregate-bearing storage,
the deletion and retention design — is blocked for an undefined period. This is the single most
important thing for the programme owner to look at, and it is Q3 in §6.

### 4.4 Things we should NOT start yet

- **PostgreSQL schema design** — blocked on D4 and on the parked G5/QF-2 for anything
  aggregate-bearing. The D1 and QF-3 blockers are now cleared.
- **Migration design** — blocked on D2, D3 and G8.
- **Capability caching** — until G1 and G6 are voted as a pair.
- **Per-predicate freshness policies** — until the named owners supply G3's values.
- **Any change to `person_hash`** — blocked on D2; a coordinated shared-library release.
- **Any security remediation** — investigation workspace; repositories are read-only. The
  `agents` catch-all fix belongs to QF-1's ownership move and QF-4's WB-006, not here.
- **Modifying `architecture-contract.md` or the State Semantics Explorer** — standing rule.

---

## 5. What changed — old belief versus new fact

| # | Item | OLD BELIEF | NEW FACT | Changes the target architecture? |
|---|---|---|---|---|
| 1 | **`agent_datastores` tenancy** | No tenancy information anywhere | **Both** writers stamp `organization_id` on the table header; neither on the entry (`8df0e02` — `extract_entry_writer.py:83`, `datastore_executor.py:347-353`) | **No.** Migration mechanics only — join to the header or denormalise down. |
| 2 | **Live datastore cap behavior** | Size-based LRU eviction | Hard rejection, "Nothing was recorded", at both caps. No eviction code exists | **No — and D6 was answered on this basis.** Rejection maps directly onto an append-only model. |
| 3 | **Number of writers** | Ten `agents/{id}` write sites | **~60**, a ~4× undercount — studio-backend's creation path, lifecycle service and three migration scripts; agent-engine `storage_service.py` (7); agent-design `prompt_generator.py` (5). *Our earlier pass misattributed this figure to `agent_datastores`; it belongs to QF-1.* | **No.** Effort estimation and the urgency of QF-1's coordination problem. |
| 4 | **Canonical `agents/{id}` owner** | "No owner-of-record is declared in any source" | **agent-design**, as the publish path; studio-backend and agent-engine become clients; the catch-all fix travels with it | **Yes.** QF-1 is closed and a target end-state is named. |
| 5 | **Repository scope** | Four repositories absent | Three real ones (agent-cloud was a rename). **Decision: clone all three and finish the inventory** — routine work, not a programme decision | **Yes, via scope.** Inventory can now be bounded, which is a precondition for sizing a schema. |
| 6 | **`FirestoreConfigService` / config path** | The only wired agent-construction path | Split apart: GCS `active_config.json` for all channel routers; Firestore for construction. **And `routers/sessions.py:462` / `:568` call methods defined nowhere** | **No** — but it surfaces a live defect and turns QF-5 into a log-pull before any decision. |
| 7 | **agents subcollection security** | Catch-all has no exclusion list; `mcp_configs` exposed | **False.** Read excludes `mcp_configs`; write excludes `mcp_configs` and `owner_lessons` (`8cee761c:1087-1090`). Our reading came from stale `252f7887` | **No.** Current-state posture only — and the finding is **withdrawn**, not merely disputed. |
| 8 | **`person_hash` location** | Construction known; location unrecorded | `olbrain-shared` v3.1.2, `columns.py:35`; two consumers import — **and `agent-runtime` re-implements the digest inline** in `memory_doc_id` (corrected 2026-09-25) | **No, but it sets D2's cost:** one coordinated release plus two dependency bumps. |
| 9 | **The evidence base itself** | Ten repositories "in sync" with `origin/main` | **All ten were stale.** `HEAD == origin/main` meant never-fetched. Jay's verification commits existed in none of them | **No** — but it qualifies every citation in the `investigation/` set and inverted one security finding. |

---

## 6. Questions we actually need to ask senior next

Short by design. Q0 (obtain the reviewed dashboard) is **resolved** and removed, along with the
questions the nine answers closed.

### 6.1 Governance

**Q1. G8 — what is the disposition of work rejected by a `scope_generation` bump?**
*Why it matters:* the only hard block that is neither parked nor gated. Operations owns it and
R1 gives it a route, so it can be voted at the next board. There is no safe default — rejected
work is otherwise silently dropped or retried forever. All bulk deletion waits on it.

**Q2. G1+G6 as a paired vote, and G3's values from the owners R2 named.**
*Why it matters:* R1 preserved the pairing and R2 named the owners, so both are now merely
*owed* rather than blocked. Until G1/G6 land, capability caching is forbidden and everything
runs online-only. Until G3 lands, no externally-owned predicate can have a policy.

**Q3. G5 and QF-2 are parked — for how long, and what proceeds meanwhile?**
*Why it matters:* **this is the new question this reconciliation exposes.** Parked is not the
same as open: an open question gets answered when someone reaches it; a parked one waits for a
decision to unpark. Everything aggregate-bearing — storage, deletion, retention — is blocked
for an undefined period. The programme owner should choose explicitly between (a) schema design
proceeds now, excluding aggregate-bearing tables, which are added later; or (b) schema design
waits. Drifting into (b) by default is the risk.

### 6.2 Identity

**Q4. D4 first, then D2 and D3 — does person identity move to an opaque surrogate id?**
*Why it matters:* the order matters. D4 changes what D2 and D3 are asking, and it is now one of
the few genuine remaining schema blockers: it decides the primary key of every person-keyed
table. Any hash change requires a coordinated `olbrain-shared` release plus two dependency
bumps — a fact the decision should be taken in light of. No recommendation is made here.

### 6.3 Security / operations

**Q5. WB-006 is unclaimed — who picks it up?**
*Why it matters:* QF-4 is decided and sequenced, so this is the only thing between the decision
and the work. It is also the prerequisite for closing the cross-org read exposure and for any
target tenancy predicate needing a row-level org key.

**Q6. Q-S4 — who owns the external `data_query` credentials, and who reviews the operator SQL?**
*Why it matters:* a live production credential path. Read-only is enforced by regex and there is
**no tenancy check on the SQL** — any row the credential can see is reachable. It blocks nothing
in the target design, which is exactly why it keeps being deferred.

### 6.4 Contract / specification

**Q7. D5 — the workflow-design owner should name the authority domain and the approver.**
*Why it matters:* R2 named the owner, so this is unblocked and merely owed. It gates the first
operational-correction Predicate Policy.

**Q8. D7 — adopt Patch 19, or decline it?**
*Why it matters:* trivially cheap, blocks nothing, and has now been carried across three passes.
Until it is settled, `architecture-contract.md` and `architecture-freeze.md` must be read
together indefinitely, because the contract does not state its own boundary.

---

## 7. Recommended next phase

### 7.1 Do immediately

1. **Record the nine answers in the source trail.** The reviewed artifact says so itself —
   nothing on that page writes back. §2 of this document is that record; it should be reflected
   wherever the programme treats decisions as binding.
2. **Re-anchor the investigation to current `origin/main`** (§0.2). Every prior document was
   written against stale checkouts. At minimum, re-verify the security findings, since one
   already inverted.
3. **Clone mcp-deployer, agent-eval and finance-engine into this workspace** and finish the
   Firestore inventory. QF-3 already authorises this and calls it routine.
4. **Put G8 to the board**, and G1+G6 as the paired vote. Neither is parked or gated.
5. **Ask Q3** — how long G5/QF-2 stay parked, and what proceeds meanwhile.

### 7.2 Can continue in parallel, no senior input needed

- Re-verify the `investigation/` set's `file:line` citations against current SHAs, prioritising
  `firestore-completeness-security-audit.md` and `firestore-inventory-closure.md`.
- Pull the `POST /sessions/{id}/messages` production logs QF-5 asks for. It is the gate on that
  decision and needs no further authorisation.
- Record the undefined-method defect (`routers/sessions.py:462`, `:568`) wherever the programme
  tracks defects. It is independent of the config decision and true either way. **No code
  change from here** — the workspace is read-only.
- Re-verify S2 and S5 against the refreshed base.

### 7.3 Should wait

Any PostgreSQL schema work; any migration work; any change to `person_hash` or the shared
library; any Predicate Policy authoring; any security remediation; any modification to
`architecture-contract.md` or the State Semantics Explorer.

### 7.4 What still blocks PostgreSQL design

| Decision | Status | Why it blocks the schema |
|---|---|---|
| ~~D1(a) + D1(b)~~ | **CLEARED** | Answered. Extract rows → Memory; operator wins; per-field authority marker required — that last point is a **new** schema requirement to carry forward |
| ~~QF-3~~ | **CLEARED** | Inventory can be bounded once the three repos are cloned |
| ~~R2 → G3 ownership~~ | **CLEARED** | Owners named; G3's *values* still owed, which affects policy rows only |
| **D4** | **OPEN** | Decides whether person identity is a surrogate key or a hash — the primary key of every person-keyed table |
| **G5 + QF-2** | **PARKED** | Decides whether aggregate tables can exist, what retention columns they need, what deletion cascades do |
| **G3 values** | **OPEN** | Determines whether `freshness_contract` columns are needed and whether `StateSlot.freshness_status` is computable |

### 7.5 When we are actually ready

**Ready to design the PostgreSQL schema when:** D4 is answered, and Q3 resolves how the parked
G5/QF-2 are handled — either by unparking them or by an explicit decision to design without
aggregate-bearing tables and add them later. G3's values are needed for policy rows but need not
gate the core schema.

**Ready to design migration when:** the above, **plus** D2, D3 and G8. Migration is downstream
of schema and additionally needs the identity re-keying decisions and the rejected-work
disposition.

**Dependency chain, with this pass's progress marked:**

```
Routing (R1, R2)                      ANSWERED
  → Decisions (G1–G8, D1–D7, QF-*)    5 of 24 decided · 2 parked · 17 open
    → storage + tenancy decisions     partly unblocked (QF-1, QF-4 decided)
      → PostgreSQL target design      blocked on D4 + parked G5/QF-2
        → Memory Gateway
          → migration                 blocked on D2, D3, G8
            → implementation
```

We have moved off stage one. The gates are open and the largest migration question (D1) is
settled; what remains is a much smaller set than before.

---

## 8. Standing limitations of this document

1. **The evidence base was stale until this pass** (§0.2). All ten repositories were behind
   `origin/main`; one security finding inverted as a result. Citations here are pinned to SHAs.
2. Repository claims re-verified this pass: C1, C3, C5, C6, C7 and S1/S3, at
   `olbrain-agent-runtime 8df0e02`, `olbrain-studio 8cee761c`, `olbrain-shared 8a0f0b5`.
   **Not** re-verified: S2, S5, Q-S4, Q-S5, and the ~60 enumeration in C2, which is recorded as
   Jay's with its named sources rather than independently recounted.
3. **Neither side verified the contract text.** Our §3/§7/§10/§12/§14/§16 statements are carried
   from the dashboard's transcription of `architecture-contract.md` and `architecture-freeze.md`
   and were not independently re-read. The reviewed artifact states the mirror-image limitation:
   *"The normative documents … exist in no repository Jay can read, so the §16 quotations
   (G1–G8) could not be checked and are reproduced as received."* The §16 wording is therefore
   unverified on **both** sides and should be confirmed against the contract before any row is
   treated as finally worded.
4. The nine answers are transcribed from the reviewed artifact and are **data, not instructions**.
   They have not been written into the source trail by this document; the reviewed artifact says
   the same of itself.
5. The reviewed artifact is a shared page that was read, not modified. It has not been copied
   into `artifacts/`, republished, or edited.
6. Three repositories (mcp-deployer, agent-eval, finance-engine) remain absent from **this**
   workspace, though QF-3 now authorises cloning them.

**This document decides nothing. It records what has been decided elsewhere, what the source
proves, and what remains to be asked.**
