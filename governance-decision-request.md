# Governance Decision Request

**To:** the architecture / contract owner
**Date:** 2026-09-22
**Status:** decision packet — no implementation has started, and none will until these are answered.

---

## 1. Purpose

The v2.0 **semantic scope is frozen**. The five object classes — Evidence, Claim, Current
State, Memory, Narrative Memory — are settled, procedural memory is explicitly out of scope,
and the implementation specification is complete.

What is **not** closed is the contract's own §16 governance table. The contract states its own
freeze criterion and its own prohibition:

> *"The contract is semantically frozen once every row below is either filled or formally
> marked as deployment-time configuration with a named owner."*
>
> **"No implementation team may silently invent a value for any of them."**

Eight parameters. **Zero confirmed.** This document exists because engineering cannot supply
these values itself without violating that rule.

This is a decision packet, not another architecture document. It does not restate the
138 KB implementation specification; it extracts only what requires your input.

## 2. Current Gate Status

| Gate | Status |
|---|---|
| Semantic scope (five object classes) | **FROZEN** |
| Procedural-memory scope question | **CLOSED** — out of v2.0 scope |
| Implementation specification | **COMPLETE** |
| §16 governance parameters | **NOT CLOSED — 8 rows, 0 confirmed** |
| Code implementation | **NOT STARTED** |

**The architecture is not "frozen" without qualification.** Semantic scope is frozen; §16 is
not. Both statements are true simultaneously and the distinction is load-bearing.

## 3. Executive Decision Summary

| Category | Count | Status |
|---|---|---|
| §16 governance parameters | **8** | 0 confirmed · 3 proposed-but-unconfirmed · 5 open with no default |
| Architecture-level open decisions | **9** identified in the spec | 7 require owner input (§6 below); 2 reclassified as implementation questions |
| Implementation questions | **11** in the spec, plus 4 design-shape gaps | Non-governance — engineering can proceed |

**Of the eight §16 rows, two are hard implementation blocks and six block partial
implementation.** None blocks design of the Evidence / Claim / Predicate Policy Registry
foundation — that work can start immediately.

**Minimum to unblock the most valuable next step:** nothing in §16. The foundation is
buildable today. §16 rows 5 and 8 must be closed before anything deletes at scale.

---

## 4. §16 Governance Decisions

Owners, proposed defaults and statuses below are **quoted verbatim** from
`artifacts/architecture-contract.md` §16. Nothing is paraphrased, inferred or filled in.

### G1 — Capability revocation TTL

| | |
|---|---|
| **Status** | `PROPOSED / UNCONFIRMED` |
| **Proposed default** | "60s general, tighter for sensitive operations" |
| **Owner** | **Security** |
| **Blocking** | `BLOCKS PARTIAL IMPLEMENTATION` |
| **Source** | contract §16 row 1; spec §4 |

**Decision required:** Is 60s general, with a tighter value for sensitive operations, the
approved capability revocation TTL — and what is the tighter value?

- **Current proposal:** 60s general, tighter for sensitive operations (unconfirmed).
- **Alternative documented:** none. The contract records no competing proposal.
- **Why implementation depends on it:** it defines the window in which a revoked grant still
  authorizes a read. The contract's own note on item 6 states the trade-off explicitly:
  *"Zero revocation lag and auth-outage tolerance are mutually exclusive: checking revocation
  requires the service that is down. The TTL in item 1 is the accepted lag."*
- **Impacted components:** Memory Gateway authorization path, capability cache, Context Builder.
- **If left unresolved:** every capability check must be performed online with no caching.
  Safe and correct, but slower. **Shipping a cache without this value is forbidden.**

### G2 — Policy compatibility window

| | |
|---|---|
| **Status** | `PROPOSED / UNCONFIRMED` |
| **Proposed default** | "Current + immediate predecessor, only where explicitly marked compatible" |
| **Owner** | **Architecture** |
| **Blocking** | `BLOCKS PARTIAL IMPLEMENTATION` |
| **Source** | contract §16 row 2; spec §4, §8 |

**Decision required:** How many Predicate Policy versions may be simultaneously
resolution-active, and under what marking?

- **Current proposal:** current + immediate predecessor, only where explicitly marked
  compatible (unconfirmed).
- **Alternative documented:** none.
- **Why implementation depends on it:** it determines when a claim becomes
  `REVALIDATION_REQUIRED` during a policy migration, and whether the resolver must handle
  more than one active version. Per §10, a claim replaced by successful revalidation must not
  remain resolution-active alongside its replacement, or resolution returns a spurious
  `CONFLICT`.
- **Impacted components:** Predicate Policy Registry, resolver, policy-migration worker.
- **If left unresolved:** single-version resolution can be built first; **the policy-migration
  path cannot be completed.**

### G3 — External predicate freshness SLAs

| | |
|---|---|
| **Status** | `NO DEFAULT PROPOSED` — contract records default "None", status "Open" |
| **Owner** | "Domain owner per predicate" — **a role, not a named party. `OWNER UNRESOLVED`.** |
| **Blocking** | `BLOCKS PARTIAL IMPLEMENTATION` |
| **Source** | contract §16 row 3; spec §4, §8 |

**Decision required — two parts:**
1. **Who** are the domain owners? The contract names a responsibility, not parties. This must
   be answered before the second part can be asked of anyone.
2. Per externally-owned predicate: `max_staleness`, `stale_read_policy`, `stale_write_policy`.

- **Current proposal:** none.
- **Alternative documented:** none. The contract enumerates the permitted *values* a stale
  authoritative value may be used for — `DISPLAY_ONLY`, `READ_ALLOWED`, `WRITE_FORBIDDEN`,
  `REQUIRES_REFRESH`, `UNAVAILABLE` — but assigns none of them to any predicate.
- **Why implementation depends on it:** `freshness_contract` is a required component of every
  Predicate Policy for an externally-owned predicate. Without it `freshness_status` cannot be
  computed, and a stale value cannot be distinguished from a fresh one — which §3 forbids
  presenting as unqualified operational truth.
- **Impacted components:** Policy Registry, resolver, `StateSlot.freshness_status`, Gateway
  read path.
- **If left unresolved:** predicates with an internal authority domain can proceed.
  **Every predicate with an external authority domain is blocked.**

### G4 — Derived-object recomputation SLA

| | |
|---|---|
| **Status** | `NO DEFAULT PROPOSED` — default "None", status "Open" |
| **Owner** | **Operations + Legal** |
| **Blocking** | `BLOCKS PARTIAL IMPLEMENTATION` |
| **Source** | contract §16 row 4 and its note; spec §4, §24 |

**Decision required:** What is the maximum window during which an invalidated derived object
may remain un-recomputed?

- **Current proposal:** none.
- **Why implementation depends on it:** the contract flags this as **the item with legal
  exposure**, and its own note is precise about what is and is not being decided:
  *"The window between synchronous invalidation and completed recomputation is a window in
  which deleted data would be reachable if §10's exclusion rule were ever relaxed. The rule
  must not be relaxed; the SLA merely bounds how long the degraded-recall state persists."*
- **Impacted components:** async workers, projection rebuild, deletion cascade.
- **If left unresolved:** the correct *behaviour* — exclude-don't-serve — is implementable
  now and is not in question. Only the bound is missing. **Do not relax the exclusion rule to
  compensate for an unbounded window.**

### G5 — Aggregate retention and deletion classification, per dataset

| | |
|---|---|
| **Status** | `NO DEFAULT PROPOSED` — default "None", status "Open" |
| **Owner** | **Legal / compliance / data governance** |
| **Blocking** | **`HARD IMPLEMENTATION BLOCK`** |
| **Source** | contract §16 row 5 and its note, §10; spec §4, §24 |

**Decision required:** For each aggregate dataset, the classification §10 mandates —
`dataset_id`, `legal_basis_classification`, `retention_class`,
`contains_customer_contribution`, `customer_deletion_behavior`, `recomputable`,
`lineage_policy`.

- **Current proposal:** none, **deliberately.** The contract's note explains why:
  *"Item 5 was answered inconsistently across the two predecessor documents — one said
  aggregates survive deletion, the other said contributions are removed and recomputed. §10
  deliberately refuses to pick. The architecture supports either; the classification is a
  legal decision per dataset, not an architectural preference."*
- **Alternatives documented:** §10 names the permitted behaviours —
  `REMOVE_AND_RECOMPUTE`, `RETAIN_AS_NON_IDENTIFIABLE_AGGREGATE`, or another explicitly
  approved category. It assigns none.
- **Impacted components:** deletion cascade, analytics pipeline, aggregate stores,
  `retention_class` vocabulary on Memory and Narrative Memory objects.
- **If left unresolved:** **no aggregate containing customer contribution can ship.** §10 is
  explicit: *"The contract MUST NOT claim a legal exemption for aggregated data unless the
  responsible legal or compliance owner has explicitly classified that dataset."* Engineering
  cannot substitute a judgement here — this is the one row where the contract names the
  decision as legal rather than architectural.

### G6 — Online authorization vs. cached capability

| | |
|---|---|
| **Status** | `NO DEFAULT PROPOSED` — default "None", status "Open" |
| **Owner** | **Security** |
| **Blocking** | `BLOCKS PARTIAL IMPLEMENTATION` |
| **Source** | contract §16 row 6 and its note; spec §4 |

**Decision required:** Which operations require online authorization rather than a cached
capability?

- **Current proposal:** none.
- **Why implementation depends on it:** the contract's note ties G6 directly to G1 —
  *"Item 6 interacts with the auth-outage behaviour... The TTL in item 1 is the accepted lag.
  Item 6 names the operations for which that lag is unacceptable and online authorization is
  required instead."* **G1 and G6 should be answered together by Security; answering one
  without the other leaves the pair incoherent.**
- **Impacted components:** Gateway authorization path, typed capabilities.
- **If left unresolved:** treat every operation as online-only — safe, slower, and it forecloses
  the G1 optimisation entirely.

### G7 — Nonce and replay-cache scope for sensitive operations

| | |
|---|---|
| **Status** | `PROPOSED / UNCONFIRMED` |
| **Proposed default** | "Postgres-backed table with TTL sweep; no Redis in MVP" |
| **Owner** | **Architecture** |
| **Blocking** | `BLOCKS PARTIAL IMPLEMENTATION` |
| **Source** | contract §16 row 7; spec §4 |

**Decision required:** Is a Postgres-backed nonce table with a TTL sweep the approved
replay-protection mechanism, and what is its scope — which operations are "sensitive"?

- **Current proposal:** Postgres-backed table with TTL sweep; no Redis in MVP (unconfirmed).
  Note this proposal is consistent with §14's MVP storage decision, which marks Redis
  `Optional; add only on measured SLO or workload need`.
- **Alternative documented:** none.
- **Why implementation depends on it:** it governs replay protection for sensitive mutations.
- **Impacted components:** mutation contract, outbox, Gateway write path.
- **If left unresolved:** per-mutation `mutation_id` idempotency is independently mandated by
  §7 and is buildable now. Only the narrower sensitive-operation nonce scope is blocked.

### G8 — Bulk-deletion retry and dead-letter policy

| | |
|---|---|
| **Status** | `NO DEFAULT PROPOSED` — default "None", status "Open" |
| **Owner** | **Operations** |
| **Blocking** | **`HARD IMPLEMENTATION BLOCK`** |
| **Source** | contract §16 row 8; spec §4, §15, §24 |

**Decision required:** What is the retry and dead-letter policy for workers rejected by a
`scope_generation` bump?

- **Current proposal:** none.
- **Why implementation depends on it:** per §10 a worker whose scope generation changed before
  commit is rejected. Without a defined disposition for that rejected work, it is either
  silently dropped or retried forever. There is no safe default.
- **Impacted components:** outbox workers, deletion cascade, scope generations.
- **If left unresolved:** single-scope deletion is implementable. **Bulk deletion cannot ship.**

---

## 5. What Is Blocked vs. Unblocked

### Can proceed now — no §16 decision required

- Predicate Policy Registry (immutable, versioned) — **schema and code**
- Evidence plane, append-only, with per-scope positions
- Claim model and explicit lineage relations
- Mutation Contract — OCC, `expected_status`, `STATE_CONFLICT`
- StateSlot resolution (the §6 nine steps) and the §11 result contract
- Memory Gateway read/write paths, **with online-only authorization**
- Per-mutation `mutation_id` idempotency
- Correct exclude-don't-serve invalidation behaviour
- Single-scope deletion

### Blocked partially — a specific area cannot be finished

| Area | Blocked by |
|---|---|
| Capability caching | G1, G6 |
| Policy-migration path | G2 |
| Any externally-owned predicate | G3 |
| Recompute-window bound | G4 |
| Sensitive-operation replay protection | G7 |

### Hard blocks — cannot ship at all

| Area | Blocked by |
|---|---|
| Any aggregate containing customer contribution | **G5** |
| Bulk deletion | **G8** |

### The practical consequence

Engineering has **weeks of unblocked foundation work**. The §16 gate does not stop work
starting; it stops specific areas finishing. G5 and G8 are the two that eventually stop the
deletion story completely, and G5 needs a legal owner rather than an engineering one, so it
has the longest lead time. **G5 is the one worth starting first.**

---

## 6. Architecture-Level Open Decisions

These are **not** §16 parameters. They were discovered while writing the implementation
specification and require owner input because they change the target design or its migration,
not merely how it is coded.

Two of the nine `OPEN DECISION` items recorded in the spec (§29) — `source_offset` allocation
and `MAP`/`SET` status representation — are **presented in §7 below instead**, because they
need an engineering choice rather than an owner's. That reclassification is flagged rather
than silent; they remain A5 and A6 in the specification.

### D1 — Extract-mode `agent_datastores` migration: provenance does not exist

**Why it exists.** `agent_datastores` is a single Firestore path —
`agent_datastores/{agent_id}/tables/{table_id}/entries/{entry_id}` — written by **three
independently-authored writers with three different entry schemas**:

| Writer | Keying | Nature |
|---|---|---|
| Extract-mode (`extract_entry_writer.py`) | `person_hash(user_key)`, one row per person, upsert | async post-turn LLM extraction |
| Live agent tool (`datastore_executor.py`) | `uuid4().hex[:12]`, multi-row per session, carries `session_id` | synchronous in-turn capture |
| Operator CRUD (`datastore_service.py`, olbrain-agent-design) | operator-authored, authenticated, audited, holds the only hard DELETE | human correction |

**No entry from any writer carries `organization_id`. None carries versioning.**

The specification's conclusions, preserved precisely:

- **`agent_datastores → Memory` is an invalid oversimplification.** The three writers store
  semantically different objects and must be decomposed by writer, not migrated as one store.
- **Competing writers can overwrite one another.** An operator correction and a later async
  extraction both merge-write the same `person_hash` row. The operator's higher authority is
  **not represented anywhere in the data model**, so recency wins.
- **That recency/last-write-wins behaviour conflicts with the target concurrency semantics** —
  §14 records `Last-write-wins → Rejected for important state`.
- **Lossless migration of extract-mode entries is impossible where the supporting Evidence
  does not exist.** A target Claim requires provenance as explicit lineage back to supporting
  Evidence. Extract entries carry no `session_id` (deliberately — the row is per person), no
  message id and no extraction run id. `last_session_id` records only the most recent touch,
  not the support for any particular field value. **Those Evidence records do not exist and
  cannot be reconstructed from the stored row.**

**Decision required:** For extract-mode entries, which migration path is approved?

- **Option (a) — synthesize placeholder Evidence.** Mint a migration-provenance Evidence
  record per migrated row, explicitly marked as backfill with no original observation.
  *Consequence:* honest about the gap; pollutes the Evidence plane with non-observations.
- **Option (b) — migrate as un-provenanced Memory.** Land the rows in Memory rather than as
  Claims; future extractions build real Claims going forward.
  *Consequence:* keeps the Evidence plane clean; **historical person facts never become
  current-state-eligible.**

**No recommendation is offered.** The specification deliberately does not choose.

**Additional constraint on either choice:** the prompt-read path
(`core/cs_packet_builder.py::_load_person_records_block`) renders these rows into the system
prompt **unconditionally** on every packet build. Whichever option is chosen must keep that
path working or change it in the same step.

**Owner/action:** architecture owner. **Evidence:** spec §18; repo-notes for
`olbrain-agent-runtime` and `olbrain-agent-design`; spec §29 A1.

### D2 — Replacement construction for `person_hash`

**Why it exists.** Verified directly against source this programme:
`olbrain-shared/src/olbrain_shared/agent/datastore/columns.py` computes
`sha256(user_key.strip().lower())[:32]` with **no salt**. The function's own docstring states
it is the digest half of `agent_memory_service.memory_doc_id` — i.e. the construction is
**deliberately shared** between the `agent_datastores` and `agent_user_memory` keying schemes.

The input domain is phone numbers and email addresses: small, structured, enumerable. The
construction is therefore trivially reversible by dictionary or rainbow table. The stated
intent — "so a raw phone or email never appears in a document path" — is met literally but
does not achieve unlinkability.

**Decision required:** What replacement construction is approved?

- **Current proposal:** **none.** The specification deliberately proposes no algorithm.
- **Alternatives documented:** none. No source material establishes a candidate.
- **What must be decided:** whether the replacement is keyed or salted; where the key or salt
  lives; whether it is per-tenant; and the rotation procedure.
- **Consequence of any change:** it **breaks the key for every existing row in both schemes
  simultaneously**, because they share the construction. Re-keying requires the original
  `user_key`, which is **not stored on the entry** — only `user_key_kind`. Dual-key operation
  is therefore implied: a mapping period in which both old and new ids resolve to the same
  person.
- **Established target constraint:** whatever is chosen must not become an authorization
  bridge. Per §14, cross-customer `SAME_AS` is forbidden and `RESOLVES_TO` is explicitly
  non-authorizing — the ability to compute that two records concern the same person must not
  grant cross-scope visibility.

**Owner/action:** Security, with the architecture owner. **Evidence:** spec §23;
`olbrain-shared` `columns.py` (read directly, HEAD `a837b95`); `senior-feedback.md` §3;
spec §29 A2.

### D3 — Disposition of rows whose original `user_key` is unrecoverable

**Why it exists.** Follows directly from D2. Re-keying requires the raw phone or email, which
is not stored on the entry. Where it cannot be recovered from session documents or the source
channel, the row **cannot be re-keyed at all**.

**Decision required:** What happens to those rows — retained under the old key, orphaned,
or deleted?

**Options documented:** none. The specification records the problem, not a menu.

**Owner/action:** Security + Legal. **Evidence:** spec §23; spec §29 A3.

### D4 — Whether person identity moves to an opaque surrogate id

**Why it exists.** Raised in the specification as a way to decouple person identity from the
hash construction permanently, making all future rotation cheap: the hash would be retained
only as a lookup index, not as the identity itself.

**Decision required:** Is this adopted as the target identity model?

- **Status:** the specification calls it *"attractive, but not established by any source
  material."* That is a note on its provenance, **not** a recommendation.
- **Relationship to D2/D3:** answering D4 first changes what D2 and D3 are actually asking.

**Owner/action:** architecture owner. **Evidence:** spec §23; spec §29 A4.

### D5 — Authority domain name for the operational-correction lane

**Why it exists.** `architecture-freeze.md` §3 establishes that `LearnedOverride` maps to a
Claim through a Predicate Policy entry with "an operational-correction authority domain" and
human approval required to reach `active`. It **describes** the lane but deliberately does not
**name** it, on the grounds that registry population belongs to a domain owner.

**Decision required:** What is the authority domain identifier for this lane, and who approves
a correction's promotion to `active`?

**Options documented:** none — the freeze deliberately left the naming open.

**Consequence:** this is a Predicate Policy Registry entry, **not a contract change**. It
blocks authoring the first policy for `LearnedOverride`-shaped corrections.

**Owner/action:** domain owner for workflow corrections. **Evidence:**
`architecture-freeze.md` §3; `architecture-decisions.md` Decision 1a; spec §8, §29 A7.

### D6 — Disposition of the `MAX_PER_SESSION` / `MAX_PER_TABLE` eviction caps

**Why it exists.** The live agent-tool writer bounds its writes by size-based LRU eviction.
**Eviction-by-size has no analog in the target model** — Evidence is append-only and
immutable; it is not evicted because a counter was reached.

**Decision required:** Do these caps become a retention policy, a hard rejection at the
boundary, or are they dropped?

**Dependency:** if they become a retention policy, this is governed by **G5** and inherits its
legal owner.

**Owner/action:** architecture owner, with Legal if retention is chosen. **Evidence:**
spec §18; spec §29 A8.

### D7 — Patch 19: recording the procedural-memory exclusion in the contract

**Why it exists.** `architecture-freeze.md` closed Decision 1b by ruling procedural /
heuristic memory outside v2.0 scope. Verification during the freeze found the contract
**contains no scope-exclusion vocabulary at all** — searching it for "out of scope", "outside
the scope" or "does not model" returns nothing. The exclusion therefore currently lives only
in an investigation document.

**Decision required:** Do you adopt the exclusion into `architecture-contract.md` as
**Patch 19**, via the existing Corrective Patch Set mechanism?

- **Status:** deliberately deferred by instruction during the freeze — **not** declined.
- **Consequence if not adopted:** `architecture-contract.md` and
  `investigation/architecture-freeze.md` must be read together indefinitely, because the
  contract does not state its own boundary.
- **Residual tension recorded honestly at the freeze:** Memory's definition in §1 enumerates
  "lessons," and a learned tool-sequence can reasonably be read as one. The exclusion is
  admissible because **nothing in the contract requires exhaustive coverage** — not because
  procedural memory provably fails the Memory definition. If you adopt Patch 19, that wording
  matters.

**Owner/action:** contract owner only. **Evidence:** `architecture-freeze.md` §0, §2, §9.

### Note — relationship to the existing decision board

`artifacts/repo-and-soul-map.md` records a **separate, parallel governance programme** (the
agent-design / "potion" monolith programme) which already has a working mechanism: nine
decisions taken to a decision board, six answered on 2026-09-17, three standing on documented
defaults, and confirmation recorded from Jay as the final verdict. That programme has its own
"Still open" list and its own Phase 0 preconditions — one of which, *"Fix the shared Firestore
ruleset (G12) with biting tests,"* is the same exposure this investigation independently
confirmed as Security Finding E.

**This is context, not an owner assignment.** The §16 owners are named by the contract as
Security, Architecture, Operations and Legal. Nothing in the source material routes §16
through that decision board, and this document does not assume it should.
`OPEN DECISION` — whether the §16 rows should be routed through the existing board or handled
separately is itself undecided, and is worth settling first because it determines who receives
the other eight.

---

## 7. Implementation Questions — Not Governance Blocks

These require **no owner input**. They are listed so the boundary is visible and so they are
not mistaken for part of the gate. Engineering can work through them.

| # | Question | Why it matters | Design can proceed? | Dependency | Source |
|---|---|---|---|---|---|
| Q1 | `source_offset` allocation giving gap-free monotonic positions per partition | §8's contiguous-watermark rule depends on it; a plain sequence leaves gaps on rollback | **Yes** — a design choice with throughput trade-offs | none | spec §16, §29 A5 |
| Q2 | Storage representation for `MAP` / `SET` per-key and per-element status | §11 requires the granularity; a single status column cannot express it | **Yes** — child table or structured column | none | spec §16, §29 A6 |
| Q3 | Memory Gateway API surface — transport, protocol, routes | No source material establishes any of it | **Yes** — contract explicitly leaves API framework, transport and serialisation to implementation | none | spec §13 |
| Q4 | PostgreSQL schema details beyond the logical model | Contract specifies the object model, not storage | **Yes** — entire schema is marked `PROPOSED IMPLEMENTATION` | none | spec §16 |
| Q5 | Complete or halt the in-flight `agent_user_memory → agent_datastores` migration | Completing moves data twice through a shape the contract rejects; halting leaves three live write paths in one function longer | **Yes** — sequencing judgement for the runtime owner | relates to D1 | spec §18, §29 I1 |
| Q6 | Backfill `context_logs` history into the Evidence plane, or leave a compatibility reader | Backfill cannot reconstruct a meaningful contiguous `source_position` retroactively | **Yes** | none | spec §6, §29 I2 |
| Q7 | Does the Gateway front Studio/Noesis session reads, or do corrected Firestore rules suffice | Determines whether Phase 7 is a client migration or a rules fix | **Yes** | product/infra sequencing | spec §14, §29 I3 |
| Q8 | Does session PII move into the identity layer as part of this migration | `agent_sessions` carries plaintext phone/profile data | **Yes** | relates to D2 | spec §22, §29 I4 |
| Q9 | Origin of the `is_enabled` MCP-config spelling | No confirmed writer in either repo | **Yes** — unaccounted-for artifact | none | spec §29 I5 |
| Q10 | The `workflow_definitions` one-time migration script | Referenced in code, never located | **Yes** | none | spec §29 I6 |
| Q11 | `workflow_items` org-binding and Pydantic model | No `WorkflowItem` model found even in `olbrain-shared` | **Yes** | none | spec §29 I7 |
| Q12 | `scripts/merge_organizations.py` semantics | Not investigated; distinct from transfer and archive cascades | **Yes** | none | spec §29 I8 |
| Q13 | Tenant routing between the shared Firebase project and `clix-capital-prod` | Out of scope for a rules-file-only review | **Yes** | none | spec §29 I9 |
| Q14 | Read call site for `agent_sessions.summary` | Not pinned to a line in the investigation | **Yes** | none | spec §29 I10 |
| Q15 | Reachability of the no-settings `create_agent()` path using the legacy config service | Determines whether the legacy config service is truly dead | **Yes** | none | spec §29 I11 |

**Q9 and Q10 are unaccounted-for artifacts, not governance items.** They are listed here
deliberately: folding them into the §16 table would dilute the gate that actually blocks work.

---

## 8. Decisions Requested From the Architecture Owner

The concrete asks, grouped by who must answer.

### Routing — answer first

| | Decision | Why first |
|---|---|---|
| R1 | Are the §16 rows routed through the existing decision board, or handled separately? | Determines who receives everything below |
| R2 | Who are the "domain owners per predicate" referenced by G3? | G3 cannot be asked of anyone until this is answered |

### Security

| | Decision |
|---|---|
| G1 | Confirm or replace the capability revocation TTL (proposed: 60s general, tighter for sensitive operations) |
| G6 | Name the operations requiring online authorization rather than a cached capability — **answer together with G1** |
| D2 | Approve a replacement construction for `person_hash`: keyed or salted, key location, per-tenant or not, rotation procedure |
| D3 | Disposition of rows whose original `user_key` is unrecoverable (with Legal) |

### Architecture / contract owner

| | Decision |
|---|---|
| G2 | Confirm or replace the policy compatibility window |
| G7 | Confirm or replace the nonce and replay-cache scope, and define "sensitive operations" |
| D1 | Extract-mode migration: option (a) synthesized placeholder Evidence, or option (b) un-provenanced Memory |
| D4 | Whether person identity moves to an opaque surrogate id — **answer before D2 and D3** |
| D6 | Disposition of the `MAX_PER_SESSION` / `MAX_PER_TABLE` eviction caps |
| D7 | Adopt the procedural-memory exclusion into the contract as Patch 19 |

### Legal / compliance / data governance

| | Decision |
|---|---|
| **G5** | Per-dataset aggregate classification — the seven §10 fields. **Longest lead time; start here.** |
| G4 | Maximum un-recomputed window for invalidated derived objects (with Operations) |

### Operations

| | Decision |
|---|---|
| **G8** | Bulk-deletion retry and dead-letter policy for generation-rejected workers |
| G4 | Recomputation SLA (with Legal) |

### Domain owners, once R2 is answered

| | Decision |
|---|---|
| G3 | Per external predicate: `max_staleness`, `stale_read_policy`, `stale_write_policy` |
| D5 | Authority domain identifier for the operational-correction lane, and who approves promotion to `active` |

---

## 9. Post-Decision Update Path

Once decisions are received, these documents are updated — **in this order**. No coding is
proposed here.

| Step | Document | Update |
|---|---|---|
| 1 | `artifacts/architecture-contract.md` | §16 rows filled, or formally marked deployment-time configuration with a named owner. **Contract-owner action only.** If D7 is approved, Patch 19 lands in the same pass. |
| 2 | `investigation/architecture-freeze.md` | §8 revised — it currently records "8 rows, 0 confirmed" and states the contract is not semantically frozen by its own criterion. Once §16 closes, that statement changes and the freeze becomes complete on the contract's own terms. §9 updated if Patch 19 lands. |
| 3 | `investigation/implementation-spec.md` | §4 governance table updated from "0 confirmed"; §29 open-decision lists reduced; §26 Phase 0 marked closed; §30 gating column revised. |
| 4 | `investigation/governance-decision-request.md` | This document — mark each decision answered, with date and deciding party. Retain the unanswered rows. |
| 5 | `investigation/MASTER.md` | Session report recording which decisions closed and which remain. |

**Not updated by this path:** `artifacts/state-semantics-explorer.html` and the senior's
source artifacts. The explorer models target semantics, which these decisions do not change —
they fill parameters the contract already declared.

**Independent of all of the above:** the Firestore rules remediation (Security Findings E and
G) is a live production security workstream on its own timeline. It does not wait for this
gate, and this gate does not wait for it.

---

## 10. Source References

| Source | What it provides |
|---|---|
| `artifacts/architecture-contract.md` §16 | The eight parameters, proposed defaults, owners, statuses, and the notes on items 4, 5 and 6 — quoted verbatim throughout §4 above |
| `artifacts/architecture-contract.md` §3, §6, §7, §10, §11, §14 | The normative requirements each parameter feeds |
| `investigation/architecture-freeze.md` | Semantic-scope freeze; §8 the §16 gate; §9 the Patch 19 deferral; §0 the residual "lessons" tension |
| `investigation/architecture-decisions.md` | Decision 1a (`LearnedOverride` → Claim) and Decision 1b (procedural memory), the origin of D5 and D7 |
| `investigation/implementation-spec.md` §4 | Per-parameter dependency analysis — the blocking classifications in §5 above derive from its "Can work proceed without it?" column |
| `investigation/implementation-spec.md` §18 | The `agent_datastores` three-writer decomposition behind D1 |
| `investigation/implementation-spec.md` §23 | Privacy/identity analysis behind D2, D3, D4 |
| `investigation/implementation-spec.md` §29 | The 9 architecture open decisions and 11 implementation questions this document re-sorts |
| `investigation/reconciliation.md` §4 | Current→target mapping; the async-crossing gap |
| `investigation/store-inventory.md` | Security Findings A–H, referenced but not reopened here |
| `artifacts/senior-feedback.md` §3 | The unsalted hash and session-PII findings behind D2 |
| `artifacts/repo-and-soul-map.md` "Decisions taken, phasing, risks" | The existing decision-board mechanism noted at the end of §6 |

### Repository-derived items

| Item | Repository / file | HEAD |
|---|---|---|
| D2 — unsalted `person_hash`, shared with `memory_doc_id` | `olbrain-shared` `src/olbrain_shared/agent/datastore/columns.py` | `a837b95` |
| D1 — extract-mode writer, person-keyed, no session reference | `olbrain-agent-runtime` `services/extract_entry_writer.py` | `b2401a0` |
| D1 — live-tool writer, session-keyed, eviction caps | `olbrain-agent-runtime` `core/tools/datastore_executor.py` | `b2401a0` |
| D1 — operator CRUD writer, only hard DELETE | `olbrain-agent-design` `app/services/datastore_service.py` | `bbc85c8` |
| D1 — unconditional prompt read path | `olbrain-agent-runtime` `core/cs_packet_builder.py` | `b2401a0` |

File:line citations as captured at these HEADs are in `investigation/repo-notes/*.md`. Line
numbers are not reproduced here — they drift.

---

**No repository under `repos/` was read for modification or modified to produce this
document.** `artifacts/architecture-contract.md`, `artifacts/state-semantics-explorer.html`
and every artifact under `artifacts/` remain unchanged.
