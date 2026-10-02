# Senior Architecture Decision Pack

**To:** architecture / contract owner · **Date:** 2026-09-22

**What this is:** the decision interface — every unresolved owner-level question, the evidence
already established, and the exact answer required. **24 decisions, none answered here.**
Answer template in §11.

**What this is not:** an architecture document, storage audit, implementation spec, schema
proposal or migration plan. Those exist and are cited; this does not repeat them.

---

## 1. Current Status

| | |
|---|---|
| Architecture semantic scope | **FROZEN** |
| Implementation specification | **COMPLETE** |
| Current 10-repo investigation | **EXHAUSTED** |
| PostgreSQL schema | **NOT DESIGNED** |
| Migration architecture | **NOT DESIGNED** |
| RLS architecture | **NOT DESIGNED** |
| Production implementation | **NOT STARTED** |

**The distinction that must not be collapsed:** the **current workspace is exhausted** — every
question the ten repositories could answer has been answered from source. The **platform
storage inventory remains incomplete**, because several production writers live in repositories
outside the workspace, and because some ownership and governance questions cannot be determined
from code at all. "Exhausted" and "complete" are different claims; only the first is true.

*Source: `firestore-inventory-closure.md` §13; `architecture-freeze.md` §8.*

---

## 2. Routing Decisions — answer first

### R1 — Governance decision routing

**Decision:** are the §16 rows routed through the existing decision board, or handled separately?

**Why it matters:** determines who receives everything below.

**Established:** `repo-and-soul-map.md` records a working mechanism for a *different* programme
— the agent-design / "potion" work took nine decisions to a decision board, six answered
2026-09-17, three standing on documented defaults, confirmation recorded from Jay as final
verdict. **Nothing in any source routes §16 through that board.** §16's owners are named by the
contract as Security, Architecture, Operations and Legal.

**Status:** `OPEN DECISION`, owner not documented. **Answer required:** name the route.

*Source: `governance-decision-request.md` §6; `repo-and-soul-map.md` "Decisions taken, phasing,
risks".*

### R2 — Per-predicate domain ownership

**Decision:** who are the "domain owners per predicate" the contract names for §16 row 3?

**Why it matters:** the contract assigns G3 to a **responsibility, not a party**. G3 cannot be
asked of anyone until this is answered.

**Affects:** G3 directly; D5 (authority-domain name); every Predicate Policy for an
externally-owned predicate.

**Status:** `OWNER UNRESOLVED`. **Answer required:** name the owners, or the party who assigns
them.

*Source: `architecture-contract.md` §16 row 3; `governance-decision-request.md` §4, §8.*

---

## 3. §16 Governance Decisions

Owners, proposals and statuses **quoted from the contract**. Blocking classifications carried
from `implementation-spec.md` §4, **not reclassified**.

### G1 — Capability revocation TTL
- **Question:** is "60s general, tighter for sensitive operations" approved, and what is the
  tighter value?
- **Proposal:** `60s general, tighter for sensitive operations` — **PROPOSED / UNCONFIRMED**
- **Owner:** **Security** · **Blocking:** partial
- **Why:** defines the window in which a revoked grant still authorizes a read.
- **Components:** Gateway auth path, capability cache, Context Builder.
- Build online-only checks now; **shipping a cache without this value is forbidden.**
  **Coupled to G6 — see G6.**

### G2 — Policy compatibility window
- **Question:** how many policy versions may be simultaneously resolution-active, and under what
  marking?
- **Proposal:** `Current + immediate predecessor, only where explicitly marked compatible` —
  **PROPOSED / UNCONFIRMED**
- **Owner:** **Architecture** · **Blocking:** partial
- **Why:** decides when a claim becomes `REVALIDATION_REQUIRED`; §10 requires a revalidated claim
  not remain active beside its replacement, or resolution returns a spurious `CONFLICT`.
- **Components:** Policy Registry, resolver, migration worker. Single-version resolution is
  buildable now; the migration path cannot be completed.

### G3 — External predicate freshness SLAs
- **Question (two parts):** (1) who are the domain owners (= R2); (2) per externally-owned
  predicate: `max_staleness`, `stale_read_policy`, `stale_write_policy`.
- **Proposal:** **NO DEFAULT PROPOSED** (contract: default "None", status "Open")
- **Owner:** "Domain owner per predicate" — a role, not a party. **OWNER UNRESOLVED** ·
  **Blocking:** partial
- **Why:** `freshness_contract` is required on every policy for an externally-owned predicate.
  Without it `freshness_status` cannot be computed and a stale value cannot be distinguished
  from a fresh one — which §3 forbids presenting as unqualified operational truth.
- **Components:** Policy Registry, resolver, `StateSlot.freshness_status`, Gateway read path.
  Internal predicates proceed; **every externally-owned predicate is blocked.**

### G4 — Derived-object recomputation SLA
- **Question:** maximum window during which an invalidated derived object may remain
  un-recomputed?
- **Proposal:** **NO DEFAULT PROPOSED** · **Owner:** **Operations + Legal** · **Blocking:** partial
- **Components:** async workers, projection rebuild, deletion cascade. Correct
  exclude-don't-serve behaviour is implementable now; only the bound is missing.
- **Contract note — preserved:** this is **the item with legal exposure**. *"The window between
  synchronous invalidation and completed recomputation is a window in which deleted data would
  be reachable if §10's exclusion rule were ever relaxed. The rule must not be relaxed; the SLA
  merely bounds how long the degraded-recall state persists."*

### G5 — Aggregate retention and deletion classification, per dataset
- **Question:** for each aggregate dataset, the §10 classification — `dataset_id`,
  `legal_basis_classification`, `retention_class`, `contains_customer_contribution`,
  `customer_deletion_behavior`, `recomputable`, `lineage_policy`.
- **Proposal:** **NO DEFAULT PROPOSED — deliberately.**
- **Owner:** **Legal / compliance / data governance** · **Blocking:** **HARD IMPLEMENTATION BLOCK**
- **Components:** deletion cascade, analytics, aggregate stores, `retention_class` vocabulary.
  No aggregate containing customer contribution can ship — §10 forbids claiming a legal
  exemption absent explicit classification by the responsible owner.
- **Contract note — preserved:** *"Item 5 was answered inconsistently across the two predecessor
  documents — one said aggregates survive deletion, the other said contributions are removed and
  recomputed. §10 deliberately refuses to pick. The architecture supports either; the
  classification is a legal decision per dataset, not an architectural preference."*
- §10's permitted behaviours: `REMOVE_AND_RECOMPUTE`, `RETAIN_AS_NON_IDENTIFIABLE_AGGREGATE`, or
  another explicitly approved category. None assigned. **Fed by QF-2.**

### G6 — Online authorization vs. cached capability
- **Question:** which operations require online authorization rather than a cached capability?
- **Proposal:** **NO DEFAULT PROPOSED** · **Owner:** **Security** · **Blocking:** partial
- **Components:** Gateway auth path, typed capabilities. Treat everything as online-only until
  decided.
- **Contract note — preserved:** *"Item 6 interacts with the auth-outage behaviour. Zero
  revocation lag and auth-outage tolerance are mutually exclusive: checking revocation requires
  the service that is down. The TTL in item 1 is the accepted lag. Item 6 names the operations
  for which that lag is unacceptable and online authorization is required instead."*
- **G1 and G6 must be answered together by Security.** Either alone leaves the pair incoherent.

### G7 — Nonce and replay-cache scope for sensitive operations
- **Question:** is a Postgres-backed nonce table with TTL sweep approved, and which operations
  are "sensitive"?
- **Proposal:** `Postgres-backed table with TTL sweep; no Redis in MVP` — **PROPOSED /
  UNCONFIRMED**. Consistent with §14 marking Redis `Optional; add only on measured SLO or
  workload need`.
- **Owner:** **Architecture** · **Blocking:** partial
- **Components:** mutation contract, outbox, Gateway write path. Per-mutation `mutation_id`
  idempotency is independently mandated by §7 and buildable now.

### G8 — Bulk-deletion retry and dead-letter policy
- **Question:** what is the disposition of work from a worker rejected by a `scope_generation`
  bump?
- **Proposal:** **NO DEFAULT PROPOSED** · **Owner:** **Operations** ·
  **Blocking:** **HARD IMPLEMENTATION BLOCK**
- **Components:** outbox workers, deletion cascade, scope generations. Single-scope deletion is
  implementable; bulk deletion cannot ship. Without a defined disposition, rejected work is
  either silently dropped or retried forever. **There is no safe default.**

*Source: `architecture-contract.md` §16 + its "Notes on the open items";
`governance-decision-request.md` §4; `implementation-spec.md` §4.*

---

## 4. Architecture Decisions

### D1 — `agent_datastores`

One Firestore path — `agent_datastores/{agent_id}/tables/{table_id}/entries/{entry_id}` —
written by **three independently-authored writers**:

| Writer | Identity model | Nature | Atomicity |
|---|---|---|---|
| Extract-mode | `person_hash(user_key)` — one row **per person**, upserted | async post-turn LLM extraction | two non-atomic `.set()`; exceptions swallowed |
| Live agent tool | `uuid4().hex[:12]` — many rows **per session**, carries `session_id` | synchronous in-turn capture | atomic batch; errors surfaced |
| Operator CRUD | **bimodal** — `person_hash` for extract-fill tables, `uuid4` otherwise | authenticated, audited human correction; only hard DELETE | atomic batch |

- **No entry carries `organization_id`. None carries a version field.**
- Two identity models, two cardinalities over time, two authority levels with no field to
  express them, two failure/durability contracts.
- **Established conclusion:** these **cannot safely be one semantic PostgreSQL table**.
  `agent_datastores → Memory` is an invalid oversimplification.
- **Lossless Evidence reconstruction is unavailable for extract-mode rows.** A Claim requires
  provenance as explicit lineage to Evidence. Extract entries carry no `session_id`
  (deliberately — the row is per person), no message id, no extraction run id; `last_session_id`
  is a last-touch marker overwritten every turn. **Those Evidence records do not exist and
  cannot be reconstructed.**

**D1(a) — migration path for extract-mode rows.** Which is approved?
- **Option A — synthesize placeholder Evidence:** mint a migration-provenance record per row,
  explicitly marked as backfill with no original observation. *Honest about the gap; pollutes
  the Evidence plane with non-observations.*
- **Option B — migrate as un-provenanced Memory:** land rows in Memory rather than as Claims;
  future extractions build real Claims. *Keeps the Evidence plane clean; historical person facts
  never become current-state-eligible.*
- **No recommendation** — the specification deliberately does not choose.
- **Constraint on either:** the prompt-read path renders these rows into the system prompt
  **unconditionally** on every packet build. The chosen option must keep that working or change
  it in the same step.

**D1(b) — authority representation** *(absorbs Q-S1's sibling question Q-S2).* When a machine
extraction and a human operator have both written the same field of the same person row, which
is authoritative? The source **deliberately** merges a later extraction into an
operator-corrected row — both writers coordinate on the same document and both guard `created_at`
re-stamping. What is coordinated is *provenance preservation*; what is represented nowhere is
*which value wins*. Today write order decides — the `Last-write-wins → Rejected for important
state` outcome (§14). **Must be answered before any person-attribute Predicate Policy can be
authored**, independently of migration.

*Source: `implementation-spec.md` §18; `storage-reality-audit.md` §11 (AMB-01, AMB-02);
`governance-decision-request.md` §6.*

### D2 — Replacement construction for `person_hash`
**Decision:** keyed or salted? where does the key/salt live? per-tenant? rotation procedure?
**Evidence:** verified at source — `sha256(user_key.strip().lower())[:32]`, **no salt**, over an
enumerable domain (phones, emails); the docstring states it is deliberately shared with
`agent_user_memory`'s `memory_doc_id`. **Any change breaks the key for every existing row in
both schemes simultaneously**; re-keying needs the original `user_key`, which is **not stored**.
Dual-key operation is implied. **No proposal exists.** Constraint: whatever is chosen must not
become an authorization bridge (§14 forbids cross-customer `SAME_AS`; `RESOLVES_TO` is
non-authorizing). *Source: `implementation-spec.md` §23.*

### D3 — Rows whose original `user_key` is unrecoverable
Retained under the old key, orphaned, or deleted? Follows from D2; these cannot be re-keyed at
all. **No options documented.** *(Security + Legal.)*

### D4 — Opaque surrogate person id
Does person identity move to an opaque surrogate, with the hash retained only as a lookup index?
The spec calls it *"attractive, but not established by any source material"* — a note on
provenance, **not a recommendation**. **Answering D4 first changes what D2 and D3 are asking.**

### D5 — Authority domain name for the operational-correction lane
What is the identifier, and who approves promotion to `active`? `architecture-freeze.md` §3
establishes that `LearnedOverride` maps to a Claim via a Predicate Policy entry with "an
operational-correction authority domain" and human approval — it **describes** the lane and
deliberately does not **name** it. A registry-population decision, **not a contract change**.
Blocked on R2.

### D6 — `MAX_PER_SESSION` / `MAX_PER_TABLE` eviction caps
Do these become a retention policy, a hard rejection at the boundary, or are they dropped?
**Eviction-by-size has no analog in the target model** — Evidence is append-only, not evicted on
a counter. **If retention is chosen, this inherits G5's legal owner.**

### D7 — Patch 19: record the procedural-memory exclusion in the contract
Adopt the exclusion into `architecture-contract.md` as Patch 19 via the existing Corrective
Patch Set mechanism? The contract **contains no scope-exclusion vocabulary at all** — searching
for "out of scope", "outside the scope", "does not model" returns nothing; the exclusion lives
only in an investigation document. **Deferred by instruction, not declined.** If not adopted,
contract and freeze must be read together indefinitely, because the contract does not state its
own boundary. **Wording note:** Memory's §1 definition enumerates "lessons," and a learned
tool-sequence can be read as one — the exclusion is admissible because **nothing in the contract
requires exhaustive coverage**, not because procedural memory provably fails the Memory
definition. *(Contract owner only.)* *Source: `architecture-freeze.md` §0, §2, §9.*

---

## 5. New Owner / Scope Decisions

### QF-1 — Canonical owner of `agents/{id}`
**Question:** `Who is the canonical owner-of-record for agents/{id}?`

Facts, not a recommendation:
- **Ten write sites across three repositories** — agent-design (routers/agent, agent_service ×3,
  brain_service ×4), agent-engine (brain_builder, store_build, agentify_agent), studio-backend
  (agent_transfer_service ×2, which reassigns `organization_id`).
- **No owner-of-record is declared in any source.**
- **No shared version field, no CAS, no cross-service coordination.** agent-design uses
  transactions on some paths; agent-engine uses a lease on a *different* document; studio-backend
  uses a plain `.update()`. A transfer and a concurrent publish are not serialised.
- **Transfer depends on it** (the nine-step cascade reassigns `organization_id`/`owner_id` here).
- **Org resolution depends on it** — `knowledge_library`, `_get_knowledge_base` and
  `skill_binding_service` all resolve organization through this document.
- **Its effective Firestore rule is superseded by the catch-all** (§7 item 1).

Simultaneously the authorization anchor, uncoordinated across three writers, and client-writable
— the highest-risk single item in the storage picture.
*Source: `firestore-inventory-closure.md` §8; `firestore-completeness-security-audit.md` §9.*

### QF-2 — Financial / aggregate classification
**Question:** are these customer financial records with statutory retention, and are any
"aggregate datasets" under §10?

**Technical facts** (as source describes them — *not* a legal classification): `billing_ledger`
— "immutable audit trail"; `wallet_grants` / `wallet_recharges` — credit records and "the
idempotency ledger those paths check before crediting"; `app_subscriptions`,
`agent_subscriptions`, `organization_subscriptions` — entitlement gates ("status + trial_end ARE
the entitlement gate"). Nine further billing-adjacent collections appear in no registry
(`billing_records`, `billing_deployments`, `billing_tools`, `billing_kb_storage`,
`agent_usage_summary`, others).

**Scope limit:** the ~17-collection Finance / P&L family is served by `olbrain-finance-engine`,
**outside this workspace** — per-dataset classification cannot be completed from the ten repos.

**Distinction to preserve:** technical purpose is clear from source; **the legal classification
is not a code question.** Feeds G5.
*Source: `firestore-completeness-security-audit.md` §6; `firestore-inventory-closure.md` §4.4.*

### QF-3 — Scope of absent repositories
**Question:** `Should these repositories be brought into the architecture investigation scope
before storage inventory is considered complete?`

`olbrain-mcp-deployer` · `olbrain-agent-eval` · `olbrain-finance-engine` · `olbrain-agent-cloud`

They own the writers for `mcp_tool_executions`, `agent_qa_runs`, the finance family, and a
second reader of `secrets`. Three of twelve remaining unknowns exist **solely** because of their
absence. **They were not cloned.** If the answer is no,
`firestore-inventory-closure.md` becomes the terminal Firestore inventory and those unknowns
become permanent stated limitations.
*Source: `firestore-inventory-closure.md` §10, §13.*

### QF-4 — The "S7" `organization_id` stamping / backfill programme
**Question:** is this work funded and scheduled?

**The rules source itself identifies the blocker.** `olbrain-studio/firestore.rules` states that
cross-org reads cannot be closed because the affected documents carry no `organization_id`, so
`isOrgMember(resource.data.organization_id)` "denies everyone when the field is absent." Its
stated remedy: *"stamp organization_id, backfill, then move these into their own org-scoped
block"* — "S7 of the Outreach migration." A production backfill script
(`backfill-clix-organization-id.js`) already exists, enumerating ~20 affected collections with
their ownership-resolution fields, but targets only `clix-capital-prod`.

**Not decided here:** funding or scheduling — a programme decision.
*Source: `firestore-completeness-security-audit.md` §2 F8, §12 SF-I;
`firestore-inventory-closure.md` §4.4.*

### QF-5 — Legacy Firestore config path
**Question:** `Is the currently wired FirestoreConfigService path intentionally retained, or is
its retirement/removal planned?`

**Corrected current fact — this inverts an earlier classification:**
- `Agent.__init__` takes `use_firestore_config: bool = True` — **defaulting on**.
- `create_agent()` constructs `Agent(agent_id)` with that default and is called from
  `dependencies.py` (the FastAPI request dependency) and `main.py`.
- **`create_agent_with_settings()` has zero callers across all ten repositories** — dead code.
- **The legacy Firestore config path is therefore the only agent-construction path currently
  wired in these repos.** No flag or environment variable selects between them; the choice is a
  constructor default.

*Source: `firestore-inventory-closure.md` §9, CONTRADICTION-2.*

---

## 6. Storage-Specific Senior Questions

Only those still distinct after de-duplication. **Q-S1 is absorbed into D1(a)**, **Q-S2 into
D1(b)** — same decision, same owner. **Q-S3 is resolved** and appears in §8.

### Q-S4 — External `data_query` database credentials
**Question:** how are credentials for external `data_query` targets stored, scoped and rotated,
and who reviews the operator-authored SQL?

agent-runtime's `data_query` capability opens connections to **customer / third-party**
databases using `host`/`user`/`password` from a `connection` dict in frozen design-time config.
The dispatcher enforces **read-only** by regex but performs **no tenancy check on the SQL** —
any row the credential can see is reachable. A live production credential path outside the
Firestore-rules discussion entirely, which no prior pass covered. Unrelated to the target
design; a current-state security-ownership question.
*Source: `storage-reality-audit.md` §4.2, AMB-08.*

### Q-S5 — Application-level retry of a semantic conflict
**Question:** is a 3-attempt application-level retry of a `ProfileVersionConflict` permitted, or
is it the behaviour §12 rule 9 forbids?

research-design's `write_profile` is the platform's **only** genuine compare-and-swap; it raises
a typed conflict and the caller retries up to `_MAX_WRITE_ATTEMPTS = 3`. §7 / §12 rule 9 forbid
**infrastructure** retry and require the conflict reach the agent — the contract does not define
the infrastructure/application boundary. Decides whether the one working OCC precedent is a
model to generalise or a pattern to correct.
*Source: `storage-reality-audit.md` §8, AMB-06.*

---

## 7. Security Items Requiring Awareness

Factual only. **No remediation proposed.** Detail in
`investigation/firestore-completeness-security-audit.md`.

1. **`agents/{id}`'s effective rule is broader than the intended ownership rule.** A precise
   rule checks `userId`/`owner_id` on both existing and incoming document — and is OR-superseded
   by the two-segment catch-all, in whose read and write exclusion lists `agents` does not
   appear. Any signed-in user can read or write any agent, including reassigning `owner_id` /
   `organization_id`. *(Bears on QF-1.)*
2. **~15 collections are currently readable cross-org** because the documents carry no
   `organization_id`, which prevents an org-scoped rule being applied at all. The rules file
   documents this itself. *(Bears on QF-4 and RLS design.)*
3. **`agents/{id}/{sub}/**` has an authenticated-read catch-all with no exclusions** — covering
   `mcp_configs` and every other agent subcollection.
4. **The current secure pattern is: explicit deny + catch-all exclusion.** An explicit block
   becomes effective only when the collection is *also* named in the catch-all exclusion list.
5. **`secrets` and `memberships_index` are correctly protected** — both server-only, both
   excluded from the catch-alls; `secrets` holds KMS-encrypted keys.
6. **`agent_datastores` and `agent_user_memory` are correctly protected from the client layer** —
   the former fully denied and test-covered, the latter org-scoped read with server-only write.

---

## 8. What Is NOT a Senior Question

Already resolved from source. Escalating these would waste the discussion.

| Resolved fact | Where |
|---|---|
| `secrets` is correctly protected — KMS-encrypted, explicit deny **and** catch-all exclusion | FCSA §5 |
| `permissions` is a **field**, not a collection | FCSA §5 |
| `team_memberships` is **declared-only**, zero references | FCSA §5 |
| `memberships_index` is the actual server-only membership primitive `isOrgMember()` resolves through | FCSA §5 |
| Redis is **dormant** — declared dependency, no client import, defaults to in-memory | SRA §2 F4 |
| The current 10-repo investigation is **exhausted** | FIC §13 |
| The PostgreSQL driver is **only an external customer-database integration**, not OLBrain-owned persistence — no ORM, migrations, schema, RLS, pgvector or outbox | SRA §4 |
| `workflow_items` carries no `organization_id`; its doc id is a deterministic hash giving idempotency | FIC §7 |
| `agent_traces` stores identifiers and counters only — no user content (heavy body goes to Cloud Logging) | FIC §6 |

*SRA = `storage-reality-audit.md` · FCSA = `firestore-completeness-security-audit.md` ·
FIC = `firestore-inventory-closure.md`.*

---

## 9. Decision Dependency Graph

Arrows derived from the cited documents, not invented.

```text
  R1 routing ──► determines who receives everything below
       │
       ▼
  R2 name domain owners ──┬──► G3 external freshness SLAs
                          ├──► D5 authority-domain name
                          └──► Predicate Policy CONTENT (external predicates)

  G1 capability TTL ◄──► G6 online-vs-cached     [contract note: mutually
        └──────────┬──────────┘                   exclusive; answer together]
                   ▼
           capability caching design

  QF-2 financial facts ──► G5 per-dataset legal classification  ** HARD **
                                     │
  G4 recompute bound (legal) ────────┼──► deletion / retention design
  G8 bulk-delete retry/DLQ  ** HARD **┘

  QF-3 absent repos ──► can scope be bounded? ──► migration SCOPE
                                                        │
  D1(a) migration path ─┐                               ▼
  D1(b) authority       ├──► agent_datastores ──► final storage model
  D2/D3/D4 identity     │    migration design           │
  D6 eviction caps ─────┘                               ▼
                                                 PostgreSQL schema
  §7 security findings ─┐                               │
  QF-4 S7 org_id work ──┴──► tenancy feasibility ──► RLS design
                                                        │
  QF-1 agents/{id} owner ──────────────────────► migration cutover
                                                        │
                                                        ▼
                                                  implementation

  D7 (Patch 19) — independent; contract-owner only; blocks nothing
```

**Read as:** R1 and R2 gate everything. **G5 and G8 are the two hard blocks.** QF-3 gates whether
scope can be bounded at all. D1 blocks the largest single migration. The security findings and
QF-4 jointly determine whether a tenancy predicate is even expressible.

---

## 10. What Engineering Can Continue in Parallel

A statement of dependency independence, **not** a work plan.

Independent of every unresolved decision above: the Evidence model; the Claim model and explicit
lineage relations; the **Predicate Policy Registry foundation** (immutable, versioned registry
mechanism); the Mutation Contract (OCC, `expected_status`, `STATE_CONFLICT`); StateSlot
resolution and the §11 result contract; Memory Gateway read/write paths **with online-only
authorization**; per-mutation `mutation_id` idempotency; correct exclude-don't-serve
invalidation; single-scope deletion.

**Preserved caveat:** the Predicate Policy Registry's **content** for externally-owned predicates
depends on **R2 and G3 (§16 row 3)**. The registry mechanism is unblocked; the policies that
populate it are not, for any predicate with an external authority domain.

*Source: `implementation-spec.md` §5; `governance-decision-request.md` §5.*

---

## 11. Exact Answers Requested

Annotate inline. Nothing pre-filled.

```
ROUTING
  R1  route for §16 decisions:
  R2  per-predicate domain owners:

GOVERNANCE (§16)
  G1  capability revocation TTL (answer with G6):
  G2  policy compatibility window:
  G3  external predicate freshness SLAs (blocked on R2):
  G4  recomputation SLA / max un-recomputed window:
  G5  per-dataset aggregate classification          ** HARD BLOCK **:
  G6  online auth vs cached capability (answer with G1):
  G7  nonce / replay-cache scope:
  G8  bulk-deletion retry + DLQ                     ** HARD BLOCK **:

ARCHITECTURE
  D1(a) extract-mode migration — Option A or Option B:
  D1(b) machine vs operator authority on the same field:
  D2  person_hash replacement construction:
  D3  rows with unrecoverable user_key:
  D4  opaque surrogate person id (answer before D2/D3):
  D5  operational-correction authority domain name:
  D6  MAX_PER_SESSION / MAX_PER_TABLE caps:
  D7  adopt Patch 19 into the contract?:

OWNER / SCOPE
  QF-1 canonical owner-of-record for agents/{id}:
  QF-2 financial / aggregate legal classification (feeds G5):
  QF-3 bring the four absent repositories into scope?:
  QF-4 is the S7 organization_id work funded/scheduled?:
  QF-5 FirestoreConfigService — retained, or retirement planned?:

STORAGE-SPECIFIC
  Q-S4 external data_query credential scoping / SQL review ownership:
  Q-S5 is application-level retry of a semantic conflict permitted?:
```

---

## 12. Traceability

| Decisions | Primary source |
|---|---|
| R1, R2, G1–G8, D1–D7 | `governance-decision-request.md` §2, §4, §6, §8 |
| §16 parameters, owners, proposals, notes on items 4/5/6 | `artifacts/architecture-contract.md` §16 |
| Blocking classifications | `implementation-spec.md` §4 |
| D1 writer decomposition, provenance gap | `implementation-spec.md` §18; `storage-reality-audit.md` §11 |
| D2/D3/D4 identity evidence | `implementation-spec.md` §23 |
| D5, D7, procedural-memory scope | `architecture-freeze.md` §0, §2, §3, §9 |
| QF-1, QF-2, QF-4, §7 security items | `firestore-completeness-security-audit.md` §6, §9, §12 |
| QF-1 write-site map, QF-5, §8 resolved facts | `firestore-inventory-closure.md` §4, §6, §8, §9, §13 |
| Q-S4, Q-S5 | `storage-reality-audit.md` §4.2, §8, AMB-06, AMB-08 |
| R1 existing-board context | `artifacts/repo-and-soul-map.md` "Decisions taken, phasing, risks" |

Line numbers are not reproduced — they drift. Those documents are the evidence base; this pack
is the interface.

---

**No repository under `repos/` was modified. No repository was cloned.** No schema, RLS design,
migration plan or implementation was produced, and no governance or architecture question was
answered.
