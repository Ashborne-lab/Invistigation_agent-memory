# OLBrain v2.0 — Implementation Specification

Spec date: 2026-09-22. Status: **investigation artifact, not an implementation mandate.**

> **Semantic scope is frozen; remaining §16 governance parameters are unresolved and must not
> be silently invented.**

**Normative source:** `artifacts/architecture-contract.md` (Consolidated State Semantics
Contract v2.0, incorporating Corrective Patch Set 1–18), md5
`97c1fa3bcea1d71210c0429b1d113d07`, unmodified.

**Scope freeze:** `investigation/architecture-freeze.md` (2026-09-22).

**Current-production basis:** `investigation/store-inventory.md`,
`investigation/reconciliation.md`, `investigation/repo-notes/*.md`, verified across ten
repositories.

### How to read this document

Every statement carries one of these labels. They are never merged.

| Label | Meaning |
|---|---|
| `NORMATIVE REQUIREMENT` | Stated by the contract. Not negotiable by implementation. |
| `PROPOSED IMPLEMENTATION` | This document's suggestion. Not approved. May be replaced. |
| `PRODUCTION PRECEDENT` | A mechanism that already exists in production, cited as a reference. Never assumed contract-compliant. |
| `OPEN DECISION` | Genuinely undecided. Must not be defaulted. Usually needs a named owner. |
| `IMPLEMENTATION QUESTION` | A detail to be settled while building. Does not block architecture. |
| `VERIFIED CURRENT` / `LEGACY` / `IN-FLIGHT MIGRATION` / `TARGET ARCHITECTURE` / `OPEN QUESTION` / `CONTRADICTED BY SOURCE` | Current-production classification, carried forward from the investigation. |

No table, field list or schema in this document is approved unless it is quoted from the
contract and marked `NORMATIVE REQUIREMENT`.

---

## 1. Executive Summary

OLBrain's target state model is fully specified and semantically frozen. What does **not**
exist in production today is any shared implementation of it. The investigation found the
target architecture is not being proposed into a vacuum — three or four isolated fragments of
its core mechanisms already run in production, independently invented, in three different
repositories — but the platform has not organically converged on it either.

**The five object classes are frozen:** Evidence, Claim, Current State, Memory, Narrative
Memory. No sixth class. Procedural / heuristic memory is explicitly outside v2.0.

**The single largest structural gap** is the §9 crossing rule. Every asynchronous learning
pipeline in production today writes directly to its own final store: agent-runtime's
extract-mode memory writer, agent-engine's fact consolidator, research-design's learning
agent. The contract requires each to submit a candidate through the same policy engine, with
the same `expected_version`, `expected_status`, idempotency and generation checks as any
agent mutation. No such engine exists anywhere. This is the contract's central invariant
(§9, §12 rule 5) and it is verifiably absent as a shared mechanism.

**The second-largest gap is structural, not technical:** there is no Predicate Policy
Registry anywhere in production. Not one store declares per-predicate authority, cardinality,
conflict policy, source ranking or `allowed_operations_by_status`. The status progressions
that do exist gate transitions by convention in code. Because the registry is the thing every
other mechanism reads from, it is on the critical path for almost everything else.

**What already exists and is worth building from** (all `PRODUCTION PRECEDENT`, none
contract-compliant as-is): `context_facts`' bi-temporal store with a genuine
verify-before-active gate; research-design's compare-and-swap `write_profile`;
workflow-runtime's `orchestrator_generation` fencing counter; `agent_sessions.summary` as a
clean Narrative-Memory shape; `context_logs` as an append-only, idempotent-on-id event log.

**What blocks starting:** §16 of the contract lists eight governance parameters. Five are
Open with no proposed default; three are proposed but unconfirmed. **Zero are confirmed.**
The contract's own text states it is semantically frozen only once every row is filled or
formally marked deployment-time configuration with a named owner, and explicitly forbids
implementation teams inventing any of them. The Evidence / Claim / Policy-Registry core can
be built without them; capability caching, external-authority freshness and bulk deletion
cannot ship without theirs.

**The hardest migration problem is `agent_datastores`** — one Firestore path, three
independently-authored writers, three different entry schemas, no `organization_id` on any
entry, no versioning on any of them. It is not one semantic object and must not be migrated
as one. See §18.

## 2. Implementation Readiness / Current Status

| Area | Status | Blocking? |
|---|---|---|
| Semantic object model (5 classes) | **Frozen** — `architecture-freeze.md` | No |
| Procedural memory scope question | **Closed** — out of v2.0 scope | No |
| Contract normative text | **Complete and stable** — Patch Set 1–18 consolidated | No |
| §16 governance parameters | **8 rows, 0 confirmed** | **Yes, partially** — see §4 |
| Predicate Policy Registry content | **Does not exist** in any form | **Yes** — critical path |
| Current-state evidence base | **Complete** — ten repos source-verified | No |
| Target↔current mapping | **Complete** — `reconciliation.md` §4 | No |
| PostgreSQL logical schema | **Not designed** — this document proposes one | No (proposal only) |
| Memory Gateway API surface | **Not designed** — conceptual only here | No |
| Contract scope-exclusion clause | **Deferred** — Patch 19, owner: contract owner | No |

**Readiness verdict:** implementation of the Evidence plane, Claim model, Predicate Policy
Registry and Mutation Contract can begin as soon as the registry's first policies are
authored. Everything touching capability caching, external freshness, or bulk deletion is
gated on §16.

## 3. Frozen Assumptions

These are settled. An implementation that contradicts any of them is wrong, not innovative.

1. **Five object classes**, definitions non-overlapping, `MUST NOT be merged`. (`NORMATIVE
   REQUIREMENT`, contract §1.)
2. **No sixth object class.** (`architecture-freeze.md` §1–2.)
3. **Procedural / heuristic memory is outside v2.0** — `agent_learned_patterns`,
   `ExceptionPattern`, tool-sequence recipes. Mark `NO V2.0 TARGET MAPPING`. Do not force into
   Claim or Narrative Memory. (`architecture-freeze.md` §2.)
4. **`LearnedOverride` is structurally an assertion** and maps to a Claim governed by
   Predicate Policy — not a new class, and not a contract change.
   (`architecture-freeze.md` §3; `architecture-decisions.md` Decision 1a.)
5. **Current State is a materialized projection**, never a second truth store, and MUST be
   reproducible by replaying Claims through the resolver. (§2.)
6. **Current State MUST NOT be one giant JSON document.** The atomic unit is the StateSlot.
   (§2; "Giant mutable state JSON → Rejected" in §14's architecture decision matrix.)
7. **The Predicate Policy Registry is mandatory**, and policy versioning is
   `Mandatory and immutable`. (§3, §14.)
8. **Authorization is enforced at the read boundary, never inside state resolution.** (§6.)
9. **Asynchronous memory MUST NEVER bypass the State Mutation Contract.** (§9.)
10. **`STATE_CONFLICT` MUST NOT be retried by infrastructure** — it is returned to the agent.
    (§7, §12 rule 9.)
11. **The MVP freshness partition key is `scope_id`.** Explicitly frozen by the contract, not
    left to implementation. (§8.)
12. **MVP storage** is a single authoritative persistence layer + vector extension +
    transactional outbox/workers + Memory Gateway. Redis / Kafka / Neo4j / dedicated vector
    infrastructure are `Optional; add only on measured SLO or workload need`. (§14.)
13. **Confidence, authority, support, freshness and relevance are five separate measures.**
    Collapsing them into one scalar is prohibited. (§5.)
14. **Cross-customer `SAME_AS` is forbidden**; canonical global entities are allowed but
    `Global entity as authorization bridge` is forbidden. (§14, Examples 3, 4, 17.)

## 4. Remaining Governance Decisions (§16)

The contract states: *"The contract is semantically frozen once every row below is either
filled or formally marked as deployment-time configuration with a named owner,"* and
**"No implementation team may silently invent a value for any of them."**

Owners below are **quoted from the contract**. Where the contract names a role rather than a
person or team, that is reproduced as-is and ownership itself is unresolved.

| # | Parameter | Contract status / owner | Why implementation depends on it | Affected components | Can work proceed without it? |
|---|---|---|---|---|---|
| 1 | Capability revocation TTL | Proposed: `60s general, tighter for sensitive operations`. Owner: **Security**. Unconfirmed. | Determines whether a cached capability may be trusted and for how long; sets the window in which a revoked grant still authorizes a read. | Memory Gateway auth path, capability cache, context builder | **Partially.** Build capability checks with no cache (always-online) and the TTL becomes a later optimisation. Shipping a cache without it is forbidden. |
| 2 | Policy compatibility window | Proposed: `Current + immediate predecessor, only where explicitly marked compatible`. Owner: **Architecture**. Unconfirmed. | Decides how many policy versions may resolve concurrently during a migration, and when a claim becomes `REVALIDATION_REQUIRED`. | Policy registry, resolver, policy-migration worker | **Partially.** Single-version resolution can be built first; the migration path cannot be finished without it. |
| 3 | External predicate freshness SLAs (`max_staleness`, `stale_read_policy`, `stale_write_policy` per predicate) | Default: **None**. Owner: **"Domain owner per predicate"** — a role, not a named owner. **Ownership itself unresolved.** Status: **Open**. | `freshness_contract` is a required part of every policy for externally-owned predicates; without it `freshness_status` cannot be computed and a stale value cannot be distinguished from a fresh one. | Policy registry, resolver, StateSlot `freshness_status`, Memory Gateway read path | **Yes, for internally-owned predicates only.** Any predicate with an external authority domain is blocked. |
| 4 | Derived-object recomputation SLA, and max window an invalidated object may remain un-recomputed | Default: **None**. Owner: **Operations + Legal**. Status: **Open**. | §10 requires invalidated objects be excluded from retrieval, not served stale — the SLA bounds how long that exclusion window may last. | Async workers, projection rebuild, deletion cascade | **Partially.** Correct behaviour (exclude-don't-serve) is implementable now; the bound is a governance number. |
| 5 | Aggregate retention and deletion classification, per dataset | Default: **None**. Owner: **Legal / compliance / data governance**. Status: **Open**. | §10 requires every aggregate dataset to declare `legal_basis_classification`, `retention_class`, `customer_deletion_behavior` etc. The contract explicitly refuses a blanket rule. | Deletion cascade, analytics pipeline, aggregate stores | **No, for any aggregate containing customer contribution.** The contract forbids claiming a legal exemption absent explicit classification. |
| 6 | Which operations require online authorization rather than a cached capability | Default: **None**. Owner: **Security**. Status: **Open**. | Splits the auth path into cached and always-online lanes. | Memory Gateway auth path, typed capabilities | **Partially.** Treat everything as online-only until decided — safe, slower. |
| 7 | Nonce and replay-cache scope for sensitive operations | Proposed: `Postgres-backed table with TTL sweep; no Redis in MVP`. Owner: **Architecture**. Unconfirmed. | Governs idempotency/replay protection for sensitive mutations. | Mutation contract, outbox, gateway write path | **Partially.** Per-mutation `mutation_id` idempotency is independently required and buildable; the nonce scope is narrower. |
| 8 | Bulk-deletion retry and dead-letter policy for workers rejected by a generation bump | Default: **None**. Owner: **Operations**. Status: **Open**. | Generation-rejected writes need a defined disposition; without it rejected work is silently lost or infinitely retried. | Outbox workers, deletion cascade, scope generations | **No, for bulk deletion.** Single-scope deletion is implementable. |

**Source:** `artifacts/architecture-contract.md` §16. **Do not fill any cell above by
inference.** Each requires its named owner.

`OPEN DECISION` — row 3's ownership. The contract names "Domain owner per predicate," which
defines a responsibility, not a party. Someone must name the actual owners before any
external-authority predicate can be specified.

## 5. Target Logical Architecture

```text
                          ┌──────────────────────────────┐
   agents / application → │       MEMORY GATEWAY         │ ← the only boundary
                          │  typed capabilities, authz   │
                          └───────────────┬──────────────┘
                                          │
   ┌──────────────────────────────────────┼──────────────────────────────────┐
   │                                      │                                  │
   ▼                                      ▼                                  ▼
EVIDENCE PLANE  ──────────────►  CLAIM LAYER  ──────────►  PREDICATE POLICY REGISTRY
append-only, immutable          (subject,predicate,        per-predicate authority,
source_position ordered          object) + provenance      cardinality, conflict,
                                                           freshness, versioned+immutable
   │                                      │                          │
   │                                      └──────────┬───────────────┘
   │                                                 ▼
   │                                         RESOLUTION (§6 nine steps)
   │                                                 │
   │                            ┌────────────────────┼────────────────────┐
   │                            ▼                    ▼                    ▼
   │                      CURRENT STATE          MEMORY           NARRATIVE MEMORY
   │                      (StateSlot,            retained,        non-assertive
   │                       versioned)            retrievable      contextual
   │                            │                    │                    │
   │                            └────────────────────┼────────────────────┘
   │                                                 ▼
   │                                     AUTHORIZED RETRIEVAL (fail-closed)
   │                                                 │
   │                                                 ▼
   │                                          CONTEXT BUILDER
   │                                                 │
   │                                                 ▼
   │                                                LLM
   │
   └──► TRANSACTIONAL OUTBOX ──► ASYNC WORKERS ──┐
        (same txn as evidence)                   │
                                                 └──► re-enters via the SAME
                                                      Mutation Contract (§9)
                                                      — never a direct write

   REBUILDABLE PROJECTIONS (never authoritative): vector index, graph, caches, DCI corpus
```

`NORMATIVE REQUIREMENT` — the ordering is fixed by §15:
`EVIDENCE → CLAIM → PREDICATE POLICY → RESOLUTION → CURRENT STATE / MEMORY → AUTHORIZED
RETRIEVAL → CONTEXT BUILDER → LLM`.

### The nine independent control planes

`NORMATIVE REQUIREMENT` (§15). Each answers a different question. **A failure in one MUST NOT
be compensated by another** — this is the single most commonly violated principle in the
current production system, where REST-layer org checks were implicitly relied upon to
compensate for absent Firestore rules.

| Plane | Question | Implementation locus |
|---|---|---|
| Authorization | who may see or use it | Gateway read boundary + RLS |
| Predicate Policy | which source or authority is allowed | Policy registry |
| Validity | when it is true | `valid_from` / `valid_until` on Claims |
| State Version | concurrency control | `state_version` on StateSlot |
| Source Position | projection freshness | `produced_at_position` / `consumed_through_position` |
| Provenance | why the claim exists | explicit lineage relations |
| Lineage | what depends on it, deletion impact | lineage graph |
| Freshness Contract | is external authority recent enough | policy `freshness_contract` |
| Typed Capability | what the agent may mutate | gateway capability check |

**Evidence / source basis:** `artifacts/architecture-contract.md` §15, §14 architecture
decision matrix.

## 6. Evidence Model

### What Evidence is

`NORMATIVE REQUIREMENT` (§1): Evidence is something that happened or was observed — a user
message, a trusted tool observation, a system observation, an agent decision, or an accepted
state mutation. **Evidence is append-only and immutable. Evidence does not automatically mean
truth.**

Note the fifth type: **an accepted state mutation is itself Evidence.** The evidence plane is
not only an inbound observation log; it records the system's own accepted writes.

### Ordering and position

`NORMATIVE REQUIREMENT` (§8):

```text
source_position = partition + offset
MVP partition key = scope_id     ← frozen by the contract, not an implementation choice
```

- A StateSlot records `produced_at_position`.
- A derived projection records `consumed_through_position`.
- **Wall-clock freshness MUST NOT substitute for source-position freshness.**
- The watermark MUST be the highest **contiguous** committed position fully incorporated —
  *not* the maximum position any worker has observed. Parallel workers MUST NOT advance the
  watermark across an unprocessed gap.

`state_version` and `source_position` **MUST NEVER be compared with each other** (§7, §12
rule 1). They answer different questions: has this slot changed since I read it, versus how
far through the evidence stream has this projection incorporated.

### How Evidence becomes Claims

`NORMATIVE REQUIREMENT` (§2) — the transactional sequence:

```text
Evidence → Claim → Predicate Policy → Resolve affected StateSlot
        → Persist Claim + resolved StateSlot atomically
```

A state mutation MUST NOT update the slot independently of Claims. Synchronously, Evidence
and State commit atomically in one transaction (§9).

### Production precedents

**Existing production precedent:** `context_logs` in olbrain-agent-engine.
`alchemist/context/log_store.py::LogStore.append()` is idempotent-on-id and never updates or
deletes an existing document. No delete or erasure code path exists for `context_logs`
anywhere in that repo. Path: `context_logs/{scope_key}/events/{id}`.

**Target implication:** the append-only, idempotent-on-id property is exactly right and
directly reusable as a design reference. What is missing: there is no explicit
`source_position` (ordering is implicit in Firestore write order, which is not a contiguous
monotonic offset); scope is populated only at SESSION and GLOBAL on every live write path
despite a designed GLOBAL→SESSION cascade; and it is not the platform's sole evidence plane —
`learning_ledger` (research) and `protection_events` (agent-runtime) are independently-built
append-only logs with no shared structure.

**Existing production precedent:** `protection_events` (agent-runtime) — a durably persisted,
append-only audit event stream. **Target implication:** an audit stream is not the Evidence
plane; it has no claim-production path. It is a candidate *input* to Evidence, not a
substitute.

`IMPLEMENTATION QUESTION` — whether existing `context_logs` history is backfilled into the
target Evidence plane or left in place behind a compatibility reader. Backfill cannot
reconstruct a contiguous `source_position` retroactively with any real meaning, since the
original ordering guarantee never existed.

**Evidence / source basis:** contract §1, §8, §9; `olbrain-agent-engine`
`alchemist/context/log_store.py`; `investigation/repo-notes/olbrain-agent-engine.md`;
`investigation/store-inventory.md`.

## 7. Claim Model

### Normative fields

`NORMATIVE REQUIREMENT` (§1) — a Claim is a structured assertion derived from one or more
Evidence records, of the form `(subject, predicate, object)`, carrying:

```text
scope
authority_domain
source
valid_from / valid_until
assertion_status
policy_version
provenance
extraction_confidence
```

### Authoritative semantics vs. metadata

The contract does not itself partition these, but the distinction matters for implementation
and follows directly from §5 and §6. `PROPOSED IMPLEMENTATION` — this classification:

| Field | Role | Participates in resolution? |
|---|---|---|
| `subject`, `predicate`, `object` | **Authoritative semantics** — the assertion itself | Yes |
| `scope` | **Authoritative** — determines which slot the claim is eligible for | Yes |
| `authority_domain` | **Authoritative** — policy decides if this source may establish this predicate | Yes |
| `source` | **Authoritative** — checked against policy `allowed_sources` | Yes |
| `valid_from` / `valid_until` | **Authoritative** — temporal validity | Yes |
| `assertion_status` | **Authoritative** — only certain statuses are resolution-active | Yes |
| `policy_version` | **Authoritative** — binds the claim to the policy under which it was accepted | Yes |
| `provenance` | **Metadata, but required** — explicit lineage relations, not evidence arrays | No (but required for deletion/lineage) |
| `extraction_confidence` | **Metadata** — confidence the statement was made. **Not truth, not authority.** | Only if policy explicitly says so |

### Assertion statuses

`NORMATIVE REQUIREMENT` (§1): `active`, `superseded`, `retracted`, `invalidated`, `pending`,
`disputed`, `revalidation_required`, `superseded_by_policy`. The last two are introduced by
policy migration (§10). **Multiple contradictory claims MAY exist historically.**

`SUPERSEDED_BY_POLICY` is terminal for resolution and remains queryable for provenance and
history only (§10).

### The four separate measures — MUST NOT be collapsed

`NORMATIVE REQUIREMENT` (§5). This is the field-design rule most likely to be violated by a
well-meaning implementer reaching for a single `score` column:

```text
extraction_confidence      how sure we are the statement was made
source_authority           whether this source may establish this predicate
independent_support_count  how many independent sources support it
truth_support              aggregate epistemic support under policy
retrieval_relevance        how well it matches the current query
```

An LLM reporting `extraction_confidence = 0.99` means only that it is highly confident the
user said this. It does not imply `truth_support = 0.99` and it definitely does not imply
`authority = SYSTEM`. **Collapsing these into a single scalar score is prohibited.**

Additionally the system tracks `evidence_count`, `independent_support_count` and
`source_diversity` separately from `authority`. Repeated statements from the same source are
not independent evidence: a thousand identical user messages MUST NOT equal a thousand
independent confirmations, and repetition cannot raise `independent_support_count` above the
number of genuinely independent sources.

### Authority is predicate-specific

`NORMATIVE REQUIREMENT` (§5): there is **no** universal hierarchy such as
`SYSTEM > USER > LLM`. Authority belongs to a predicate and its domain. From §14's authority
matrix:

| Predicate class | Typical authority | LLM direct write | User evidence | External source |
|---|---|---|---|---|
| Identity / security | `IDENTITY_SECURITY` | **Forbidden** | **Forbidden** | Yes |
| Billing / financial | `BILLING_SYSTEM` | **Forbidden** | Evidence only unless policy permits | Yes (freshness contract required) |
| Operational workflow | Workflow system / state-machine policy | Via typed command only | May request change | Yes (transition table required) |
| User preference | `CUSTOMER_PREFERENCE` | Via typed state command | Often authoritative | Sometimes |
| Historical fact | Source and policy dependent | — | — | — |

### Production precedents

**Existing production precedent:** `context_facts` (olbrain-agent-engine). Verified directly
against source at HEAD `8720720` — `alchemist/context/facts.py` defines `ContextFact` with
`status: FactStatus` (`candidate` / `active` / `invalid`), `t_valid`, `t_invalid`,
`superseded_by`, and `source_event_ids` linking back to the log.
`alchemist/context/facts_store.py::supersede()` / `decay()` only ever `.update()` status and
`t_invalid` — they never delete a fact document. Invalidate-don't-delete is genuinely
enforced.

**Target implication:** this is the closest existing analog to the Claim object anywhere on
the platform, and its lifecycle vocabulary maps onto a subset of the contract's. What is
missing is substantial and must not be understated: facts are **freeform LLM extractions, not
typed `(subject, predicate, object)` assertions**; there is no `policy_version` because there
is no registry; there is no `state_version` or OCC; `extraction_confidence` is not separated
from authority; scope is session/global only; and the three-value status vocabulary is far
narrower than the contract's eight. `PRODUCTION PRECEDENT`, explicitly **not** a compliant
Claim store.

**Evidence / source basis:** contract §1, §5, §14 authority matrix;
`olbrain-agent-engine/alchemist/context/facts.py`, `facts_store.py` (read directly, HEAD
`8720720`); `investigation/repo-notes/olbrain-agent-engine.md`.

## 8. Predicate Policy Registry

### Why it exists

`NORMATIVE REQUIREMENT` (§3): *"The Predicate Policy Registry is mandatory. Every State Slot
references a Predicate Policy. The implementation MUST NOT use a universal conflict rule."*

The registry is the reason the system can refuse to guess. Without it, every conflict
resolution degenerates into last-write-wins or highest-confidence-wins, both of which the
contract rejects for important state (§14).

### Structure

`NORMATIVE REQUIREMENT` (§3) — the contract specifies this shape:

```text
PredicatePolicy {
    predicate
    policy_version_id

    cardinality
    allowed_writers
    allowed_sources
    allowed_operations_by_status

    authority_domain
    temporal_model
    resolution_policy
    conflict_policy

    security_class
    retention_class
    current_state_eligible
    llm_write_mode

    freshness_contract {
        max_staleness
        stale_read_policy
        stale_write_policy
        freshness_source
    }
}
```

### Versioning and immutability

`NORMATIVE REQUIREMENT` (§14): policy versioning is **"Mandatory and immutable."** Policy
migration is **"Background, provenance-preserving, never historical mutation."**

Old claims remain historically bound to their original `policy_version` and are never
silently rewritten (§10). But a claim replaced by successful revalidation MUST NOT remain
resolution-active alongside its replacement, or §6 would collect both and return `CONFLICT`.
The migration transaction performs:

```text
C1      status: SUPERSEDED_BY_POLICY
C1_v4   status: ACTIVE
```

For a **breaking** policy change the old claim becomes `REVALIDATION_REQUIRED` and is excluded
from authoritative current-state resolution unless the new policy explicitly defines
grandfathering.

`OPEN DECISION` — how many policy versions may be simultaneously resolution-active. This is
§16 row 2 (policy compatibility window), proposed as `Current + immediate predecessor, only
where explicitly marked compatible`, owner **Architecture**, **unconfirmed**.

### Cardinality

`NORMATIVE REQUIREMENT` (§3): every predicate has an explicit cardinality and **the state
engine MUST NOT infer cardinality from observed data.**

| Cardinality | Meaning | Contract examples |
|---|---|---|
| `SINGLE` | At most one active value represents current state | `current_device`, `billing_status`, `subscription_status` |
| `SET` | Multiple values may be simultaneously active | `preferred_languages`, `owned_devices`, `active_projects` |
| `ORDERED_SET` | Values carry explicit order | `workflow_steps`, `priority_tasks` |
| `MAP` | Bounded collection of independently addressable values | `notification_preferences` |
| `STATE_MACHINE` | Values are states with an explicit transition graph | `order_status` |
| `COUNTER` / `ACCUMULATOR` | Only where the domain explicitly requires it | `usage_count` |

### Operations gated by status

`NORMATIVE REQUIREMENT` (§3): policy MUST define `allowed_operations_by_status`. Status is
not merely descriptive. The contract's worked example:

```text
order_status
  VALUE:          allowed: TRANSITION, SET
  CONFLICT:       allowed: RESOLVE_CONFLICT;  forbidden: blind SET, ordinary TRANSITION
  UNKNOWN:        allowed: SET, ESTABLISH
  EXPLICIT_NONE:  allowed: SET
```

A `CONFLICT` therefore never wedges the system permanently — it requires an explicit
policy-defined resolution operation. **There is no implicit pick-one behaviour anywhere in the
system.**

### The freshness contract

`NORMATIVE REQUIREMENT` (§3): for predicates owned by an external system, `observed_at` does
not prove current freshness. A stale authoritative value MUST NOT be presented as unqualified
fresh operational truth. The policy declares what it may be used for: `DISPLAY_ONLY`,
`READ_ALLOWED`, `WRITE_FORBIDDEN`, `REQUIRES_REFRESH`, or `UNAVAILABLE`.

Freshness is independent of truth support, source authority, extraction confidence and
retrieval relevance. It is **also** independent of projection freshness (§8), which concerns
internal derived indexes rather than external authority.

`OPEN DECISION` — all concrete `max_staleness` values and stale-read/stale-write policies.
§16 row 3, default **None**, owner **"Domain owner per predicate"** (a role; the actual owners
are unnamed). **Do not invent a default staleness budget for any predicate.**

### First policies to author

`PROPOSED IMPLEMENTATION` — the registry is empty and someone must author its first entries.
Candidates that the investigation already supports, each still requiring a domain owner's
sign-off:

| Predicate family | Source of the shape | Cardinality (proposed) |
|---|---|---|
| Workflow run status | `workflow_runs.status` transition graph | `STATE_MACHINE` |
| Research run phase | `research_runs.phase` (PLANNING→…→GAPFILL) | `STATE_MACHINE` |
| Vibe conversant state | `vibe_sessions.active_conversant.state` | `STATE_MACHINE` |
| Operational correction | `LearnedOverride` (see §3 of the freeze) | `SINGLE` per step+field+selector |
| Person attribute | extract-mode datastore fields | per-field; mostly `SINGLE` |

`OPEN DECISION` — the authority domain name for the operational-correction lane. The freeze
document describes it as "an operational-correction authority domain" without naming it; the
name is a registry-population decision for a domain owner, not something this spec should fix.

**Evidence / source basis:** contract §3, §10, §14; `investigation/architecture-freeze.md`
§3; `investigation/store-inventory.md` (status progressions per repo).

## 9. Current State Model

### The StateSlot

`NORMATIVE REQUIREMENT` (§2) — the contract specifies this shape exactly:

```text
StateSlot {
    scope_id
    domain
    key
    value
    status

    state_version
    produced_at_position

    valid_from
    valid_until

    last_mutation_id
    authority_domain
    policy_version_id
    freshness_status
}
```

A StateSlot is **simultaneously** the write surface through which operational state is
advanced **and** a materialized projection that MUST be reproducible by replaying applicable
Claims through the resolver.

Contract examples of slot addressing:

```text
CUSTOMER:A   preference.communication_mode = EMAIL
CUSTOMER:A   device.current = iPhone 17 Pro
SESSION:101  task.active = CANCEL_ORDER
SESSION:101  workflow.checkout_state = PAYMENT
```

**Different State Slots update independently.** This is the direct rejection of the giant
mutable state document, and it is the pattern `agent_user_memory` violates today (§17, §18).

### `state_version` semantics — a subtle and load-bearing rule

`NORMATIVE REQUIREMENT` (§2): `state_version` versions **the materialized projection**, not
the count of agent mutations.

- It **MAY advance with no agent mutation** — when a late-arriving claim, an invalidation, a
  policy revalidation, or another authoritative event changes the resolved slot.
- Committing a Claim that does **not** change the resolved slot need not advance it.
- Agents MUST treat OCC failure as a normal semantic concurrency outcome, including when no
  other agent explicitly mutated the slot.

*"An implementation that assumes every `state_version` increment corresponds to an agent
command is incorrect."* This is stated in the contract in exactly those terms.

### State scope

`NORMATIVE REQUIREMENT` (§2): there is no universal "customer state". Scope is one of
`GLOBAL`, `TENANT`, `WORKSPACE`, `CUSTOMER`, `SESSION`, `AGENT`, `RESOURCE`.

**Security visibility is determined by authorization grants, never by automatic scope
inheritance.** Scope hierarchy used for deletion containment MUST NOT imply authorization
inheritance. These two mechanisms remain separate — a point worth emphasising because
conflating them is a natural implementation shortcut.

### No implicit multi-scope resolution

`NORMATIVE REQUIREMENT` (§2): a mutable current-state predicate MUST resolve within exactly
one authoritative state scope. Combining scopes is **prohibited**, because a combined value
has no single OCC version:

```text
CUSTOMER preference = EMAIL
SESSION  preference = SMS
resolver combines both → "effective preference = SMS"      PROHIBITED
```

Instead each scope holds an independently versioned slot, and where the application needs a
combined value it MUST declare an explicit **derived predicate** whose policy names its inputs
and returns a version vector. A derived multi-input value is a projection, not a directly
mutable StateSlot, and an agent MUST NOT mutate it directly.

### The four resolution statuses

`NORMATIVE REQUIREMENT` (§4) — for `SINGLE` predicates these four are distinct and **MUST NOT
all be encoded as `null`**:

```text
VALUE           current_device = iPhone 17 Pro
EXPLICIT_NONE   current_device = NONE
UNKNOWN         no authoritative current value exists
CONFLICT        multiple equally valid authoritative values cannot be resolved
```

*"`current_device = null` MUST NOT mean 'the customer owns no phone'. It may simply mean the
system does not know."*

**Implementation consequence:** a nullable column is not a sufficient representation. Status
must be an explicit, non-null, enumerated field, and `value` must be independently nullable.

### Resolution order

`NORMATIVE REQUIREMENT` (§6) — the nine steps, in order:

```text
1. Identify StateSlot
2. Load applicable Predicate Policy version
3. Collect claims eligible for that slot
4. Apply authority / source rules
5. Apply temporal validity
6. Apply cardinality rules
7. Apply conflict policy
8. Materialize resolved state
9. Authorize caller access to the resulting slot and provenance
```

**Authorization is step 9, never step 3.** The resolver MUST NOT filter Claims by the
requester's visibility before determining operational state — doing so would make one slot
resolve differently per caller, which a stored slot cannot represent and which no single
`state_version` could describe.

```text
one StateSlot → one system-authoritative resolved result
```

A caller lacking authorization receives `ACCESS_DENIED` or no authorized result. A caller MUST
NOT receive a different operational value merely because a claim exists they cannot see.

### The result contract

`NORMATIVE REQUIREMENT` (§11) — given `subject`, `predicate`, `scope`, `as_of_valid_time`,
`knowledge_cutoff` and the caller's `authorized_scopes`, the State Engine returns:

```text
status, value, valid_from, valid_until, state_version, source_position,
freshness_status, authority_domain, policy_version, provenance
```

*"This output is the only thing the current-state retrieval path treats as operational
truth."*

**Granularity by cardinality** (§11) — the four-value status contract is normative **for
`SINGLE` predicates only**. A resolver MUST return the declared granularity and no other:

| Cardinality | Result granularity |
|---|---|
| `SINGLE` | One of `VALUE`, `EXPLICIT_NONE`, `UNKNOWN`, `CONFLICT` |
| `SET` | Collection plus **per-element** resolution (`ACTIVE`, `RETRACTED`, `DISPUTED`, `INVALIDATED`, or policy-defined) |
| `MAP` | **Per-key** resolution; each key carries its own four-value status |
| `ORDERED_SET` | Ordered members plus policy-defined ordering and conflict semantics |
| `STATE_MACHINE` | Current state plus transition legality |
| `COUNTER` | Accumulator value plus policy-defined validity and conflict semantics |

A `SET` MUST NOT collapse unrelated member conflicts into one global `CONFLICT`. A `MAP` MUST
NOT carry a single status for the whole map where keys have independent semantics — a result
of `{A→VALUE, B→CONFLICT, C→UNKNOWN}` is valid and must be representable. A `COUNTER` MUST NOT
inherit `SET` or `SINGLE` semantics merely because its storage representation resembles a
scalar.

### Conflict is never silently resolved

`NORMATIVE REQUIREMENT` (§6): where two equally authoritative sources disagree and policy does
not define which controls, the resolver returns `CONFLICT`. It **MUST NOT** select a value on
the basis of recency alone, embedding similarity, LLM confidence, or number of mentions.

**Evidence / source basis:** contract §2, §4, §6, §11, §14.

## 10. Memory Model

`NORMATIVE REQUIREMENT` (§1): Memory is retained knowledge intended for future retrieval —
historical facts, preferences, episodes, relationships, lessons, summaries. **Memory does not
automatically become Current State.**

### Memory vs. Current State

| | Current State | Memory |
|---|---|---|
| Purpose | Operational decisions now | Future retrieval |
| Authority | Only where policy sets `current_state_eligible = true` | Never automatically authoritative |
| Versioning | `state_version`, OCC-controlled | Not a versioned write surface |
| Uniqueness | One authoritative slot per scope | Many coexisting records |
| Temporal | Resolved as-of a time | Retains history natively |

`NORMATIVE REQUIREMENT` (§8): Current State is **not automatically "more true."** It has
precedence only for predicates and questions where the Predicate Policy declares it
authoritative. *"What phone did they own in 2024?"* must query historical claims. **The
retrieval system MUST NOT overwrite or hide historical evidence merely because Current State
exists.**

### Memory is structured at claim level

`NORMATIVE REQUIREMENT` (§8): *"Memory is therefore structured at claim level rather than
treating a whole text chunk as one truth unit."* A retrieved chunk may simultaneously contain
a stale current-state assertion (excluded from a CURRENT query) and a still-useful historical
observation (retained).

**Note on scope:** this sentence appears within §8's retrieval-chunking discussion. It governs
retrieval granularity. The architecture freeze deliberately declined to treat it as a
normative gate on what may be a Memory object at all — see `architecture-freeze.md` §0.

### Historical context must carry temporal labels

`NORMATIVE REQUIREMENT` (§8): any historical claim entering model context MUST include
`status`, `valid_from`, `valid_until`, `source`, `scope`. **Never inject a bare "the customer
owns an iPhone 14."**

```text
Historical fact: customer owned iPhone 14
valid_from:  2024-03-01
valid_until: 2025-08-17
status:      SUPERSEDED
```

*"This labelling is the real defence against a misrouted query. It MUST hold even when routing
is correct."*

### What Memory is NOT, in v2.0

`architecture-freeze.md` §2: procedural / heuristic memory — ordered tool sequences, exception
recipes, action replay heuristics — is **outside** the v2.0 semantic contract. It is
`NO V2.0 TARGET MAPPING`. It may continue to exist and function, but it carries no v2.0
semantic guarantees and MUST NOT be treated as authoritative under §12 rule 10.

## 11. Narrative Memory Model

`NORMATIVE REQUIREMENT` (§1, Patch 9): Narrative Memory is a **non-assertive** memory
category. It preserves contextual material that does not yield a sufficiently reliable
structured assertion — the tone of a previous conversation, the context surrounding a
decision, the way a problem was described, discussion sequence, unresolved conversational
context.

### Required fields

`NORMATIVE REQUIREMENT`: each Narrative Memory object MUST carry `scope`, `provenance`,
`observed_at`, `valid_from` / `valid_until` where meaningful, `retention_class`,
`security_class`, and `status`.

### What it MAY and MUST NOT do

| MAY | MUST NOT |
|---|---|
| Be returned by semantic and history retrieval | Establish Current State |
| Provide context to the LLM | Override Claims |
| | Establish authority |
| | Be used as hidden authorization evidence |

It **MUST be clearly labelled non-assertive.**

```text
Structured Claim   = assertive semantic object
Narrative Memory   = contextual, non-assertive semantic object
```

`NORMATIVE REQUIREMENT` (§1): *"Both are legitimate memory. Requiring every useful memory to
reduce to a Claim is explicitly rejected."*

### Production precedent

**Existing production precedent:** `agent_sessions.summary` + `memory_anchor_ts`
(olbrain-agent-runtime). Writer: `core/session_summarizer.py::update_session_summary()`, a
merge-write of `{summary, memory_anchor_ts}` onto the session document, with the code's own
comment that "the anchor and the summary must always move together."

**Target implication:** this is the cleanest Narrative Memory fit found anywhere on the
platform — explicitly non-assertive, time-bounded, already labelled a summary rather than a
fact. It is missing **every** field the contract requires around it: `scope`, `provenance`,
`retention_class`, `security_class`, `status`. Today it is a bare string plus a timestamp
living on a session document that is itself world-readable at the Firestore-rules layer.

`OPEN QUESTION` (carried forward, minor) — the read call site for `.summary` was not pinned to
a line number in the investigation; `core/cs_packet_builder.py` is the evident consumer.

**Evidence / source basis:** contract §1 (Patch 9), §8;
`olbrain-agent-runtime/core/session_summarizer.py`;
`investigation/repo-notes/olbrain-agent-runtime.md`.

## 12. Mutation Contract

### Mutation is a command, not a database update

`NORMATIVE REQUIREMENT` (§7): *"The LLM never emits `UPDATE state SET ...`."* It emits a typed
mutation command:

```text
MutateState {
    mutation_id
    transaction_group_id

    predicate
    operation
    value

    expected_version
    expected_status
    precondition

    effective_at
    actor
    evidence_reference
}
```

Operations are predicate-specific: `SET`, `CLEAR`, `ADD`, `REMOVE`, `TRANSITION`, `INCREMENT`,
`ESTABLISH`, `RESOLVE_CONFLICT`. The Predicate Policy decides which are legal, and §3 gates
them by current status.

### Acceptance conditions

`NORMATIVE REQUIREMENT` (§7) — `expected_status` is **mandatory** for mutations against an
existing State Slot. A mutation is accepted only when **all** of:

```text
current.state_version == expected_version
current.status       == expected_status
policy permits operation from that status
preconditions hold
```

*"State correctness is OCC **plus** Predicate Policy **plus** the state machine — never OCC
alone."* `DELIVERED → PENDING` is rejected even when the version matches.

### Typed conflict failure

`NORMATIVE REQUIREMENT` (§7):

```text
STATE_CONFLICT {
    predicate, scope,
    expected_version, actual_version,
    expected_status,  actual_status
}
```

**`STATE_CONFLICT` MUST NOT be silently retried by infrastructure.** Infrastructure MAY retry
genuinely transient failures — serialization anomalies, connection loss. It MUST NOT retry a
semantically rejected mutation.

**Why this matters, in the contract's own words:** the agent re-reads state and decides what
to do, *"which is the only layer that can tell that 'cancel' is no longer a legal request once
the order shipped."* An infrastructure retry loop converts a semantic refusal into an
eventual success, which is precisely the failure this rule exists to prevent. A generic
retry-on-error decorator wrapped around the mutation path violates the contract.

### Transaction groups

`NORMATIVE REQUIREMENT` (§7): multiple slot mutations MAY be grouped atomically. All expected
versions, statuses and preconditions are checked together; if one fails the entire group rolls
back and **no partial state is visible**. The group carries `transaction_group_id`,
`mutation_ids`, `actor`, `causal_parent`.

### Idempotency

`NORMATIVE REQUIREMENT` (§7): every mutation carries a unique `mutation_id`. Replaying it
produces the same result, so three retries cannot produce three transitions. **For
accumulators and counters, idempotency MUST attach to the logical command, not merely to the
HTTP request.**

### Causal ordering

`NORMATIVE REQUIREMENT` (§7): when Agent B acts on Agent A's state change, B's mutation
carries `causal_parent_position` or equivalent causal metadata. An asynchronous worker MUST
NOT apply a derived write based on an earlier generation without checking its causal validity.

### Production precedents

**Existing production precedent:** `learning_service.write_profile(..., expected_version=
profile.version)` in olbrain-research-design. A genuine compare-and-swap write raising a typed
`ProfileVersionConflict` on a version race, retried up to `_MAX_WRITE_ATTEMPTS = 3`. Two
independent writers (the consolidator and the operator mutation surface) both go through the
same `get_profile → mutate → write_profile` CAS loop.

**Target implication:** the mechanism is correct in miniature and is the best existing model
to generalise from. It is also the clearest illustration of the gap: it exists for one store,
in one repo, invented independently. There is no shared `MutateState` contract, no
`expected_status`, no policy-gated `allowed_operations_by_status`, no state-machine
precondition layer, and the retry-up-to-3 behaviour is an application-level retry of a
*semantic* conflict — which the target contract forbids infrastructure from doing. Note this
carefully: the CAS half is a precedent to reuse; the auto-retry half is a precedent to
**not** carry forward without re-examination.

**Existing production precedent:** `orchestrator_generation` (olbrain-workflow-runtime) — an
integer fencing counter incremented by
`firestore_service.increment_orchestrator_generation(run_id)` on every resume/retry, so a
stale in-flight orchestrator pass exits at its next item-boundary poll rather than racing a
newer pass.

**Target implication:** real, independently-invented fencing, and a working fragment of the
idea behind `scope_generation`. It is narrower than the target: scoped to a single run rather
than to every deletable scope class, and it guards two orchestrator passes against each other
rather than guarding deletion racing a write, which is the problem §10's generation model
actually solves.

**Evidence / source basis:** contract §7, §12; `olbrain-research-design`
`app/learning/agent_pipeline.py`, `app/services/learning_service.py`;
`olbrain-workflow-runtime` `app/routers/runs.py`; `investigation/repo-notes/`.

## 13. Memory Gateway

`NORMATIVE REQUIREMENT` (contract preamble, §14): a Memory Gateway is part of the MVP
realisation. The contract does **not** specify its API surface. Everything below the first
subsection is `PROPOSED IMPLEMENTATION`.

### Role

The Gateway is the controlled boundary between agents/application code and the target
memory/state model. Its purpose is that **no caller can reach authoritative state except
through a path that applies policy, validity, freshness and authorization in the contract's
required order.**

### Typed capabilities, not a generic memory API

`NORMATIVE REQUIREMENT` (§8): *"There is no generic 'memory answer'. Intent is declared by
which typed operation the agent calls — the tool schema is the intent classifier, and a
separate stochastic intent classifier MUST NOT be inserted on this path."*

The contract names four read operations:

```text
get_current_state()      current operational state
search_history()         historical state and episodes
search_memory()          reusable semantic memory
search_relationships()   relational / graph queries
```

Intent is **per-retrieval, not per-turn** — a single user turn may call several. Where a
request is ambiguous, resolution MUST default toward current-state semantics; *"substituting
history for current state silently is prohibited."*

`PROPOSED IMPLEMENTATION` — a fifth read operation for Narrative Memory
(`search_narrative()`), since §1 permits Narrative Memory to be returned by semantic and
history retrieval but requires it be clearly labelled non-assertive, and folding it into
`search_memory()` risks losing that label at the boundary. Not established by the contract.

### Write path

`PROPOSED IMPLEMENTATION`, derived from §7 and §9:

```text
caller → Gateway
  1. authenticate actor, resolve authorized scopes
  2. check typed capability for (predicate, operation)      ← mandatory per §14
  3. load policy version for predicate
  4. validate operation legal from current status           ← allowed_operations_by_status
  5. validate preconditions, expected_version, expected_status
  6. BEGIN TXN
       append Evidence (the accepted mutation is itself Evidence, §1)
       write Claim
       re-resolve affected StateSlot
       persist Claim + StateSlot atomically                 ← §2
       enqueue outbox rows
     COMMIT
  7. on semantic rejection → return STATE_CONFLICT to the agent, never retry  ← §7
```

### Read path

`PROPOSED IMPLEMENTATION`, derived from §6 and §8:

```text
caller → Gateway
  1. typed capability check for the operation
  2. resolve under system policy — steps 1–8 of §6, NOT filtered by caller visibility
  3. apply freshness contract → freshness_status
  4. authorize caller against the resolved slot and its provenance   ← step 9
  5. return the §11 result contract, or ACCESS_DENIED
```

The critical structural property: **steps 2 and 4 are separate and in that order.** An
implementation that pushes the caller's scope filter into the claim query at step 2 is
materially wrong even though it would appear to work and would be faster.

### Provenance propagation

`NORMATIVE REQUIREMENT` (§11): `provenance` is part of the result contract, and (§14)
provenance is `Explicit lineage relations, not evidence arrays`. The Gateway must return it,
and authorization applies to the provenance as well as to the value — §6 step 9 says
*"authorize caller access to the resulting slot **and provenance**."* A caller may be
authorized to see a value but not its full derivation.

### Freshness, conflict, deletion at the boundary

- **Freshness:** for external-authority predicates the Gateway computes `freshness_status`
  from the policy's `freshness_contract` and enforces the declared stale-read policy.
  `OPEN DECISION` — the values themselves (§16 row 3).
- **Conflict:** `CONFLICT` is returned as a status, never resolved by the Gateway.
- **Deletion / invalidation:** `NORMATIVE REQUIREMENT` (§10) — an invalidated object that has
  not yet been recomputed MUST be excluded from retrieval, **not served stale**. The Gateway
  is the enforcement point for this.

`OPEN DECISION` — transport, protocol and concrete route shapes. The contract explicitly
leaves API framework, transport and serialisation to the implementation, and no current
material establishes routes. Do not infer them from the existing Firestore REST surfaces.

### What the LLM can and cannot see

`NORMATIVE REQUIREMENT`:
- Raw vector text MUST NOT pass into context without validation (§8). The path is
  `Vector search → candidate memory object → structured claims → authorization → validity →
  predicate policy → ranking → context`.
- Any historical claim entering context MUST carry `status`, `valid_from`, `valid_until`,
  `source`, `scope` (§8).
- Narrative Memory entering context MUST be labelled non-assertive (§1).
- `LLM direct security mutation` is **Forbidden** (§14).

## 14. Authorization / RLS

### Target posture

`NORMATIVE REQUIREMENT`:

| Decision | Normative outcome | Source |
|---|---|---|
| Typed capability authorization | **Mandatory** | §14 |
| RLS / backend authorization | **Defense in depth, not the sole security model** | §14 |
| Authorization inside state resolution | **Rejected** — enforced at the read boundary | §6, §14 |
| LLM direct security mutation | **Forbidden** | §14 |
| Global entity as authorization bridge | **Forbidden** | §14, Examples 3, 17 |
| Cross-customer `SAME_AS` | **Forbidden** | §14, Example 4 |
| Fail-closed behaviour | Implementation **must not** decide it away | preamble |

Note the precise wording on RLS: it is **defense in depth, not the sole security model.** An
implementation that relies on Postgres RLS alone has not satisfied the contract — the typed
capability check is the mandatory layer, and RLS backs it up. Equally, capability checks
without RLS discard the defense-in-depth the contract calls for.

### Scope hierarchy is not authorization inheritance

`NORMATIVE REQUIREMENT` (§2, §10), stated twice in the contract because it is easy to get
wrong: *"Scope hierarchy used for deletion containment MUST NOT imply authorization
inheritance. Authorization and deletion containment remain separate mechanisms."*

### Semantic connectivity is not visibility

`NORMATIVE REQUIREMENT` (§13 Examples 3, 4, 17). Two customers may both resolve mentions to
`GLOBAL PRODUCT:iphone_17_pro`. That shared entity creates semantic connectivity; it does not
create visibility. A graph query may resolve the product entity without being authorized to
enumerate who owns, dislikes or is considering it. *"The canonical entity is a semantic
anchor, not a privacy bridge."*

Cross-scope `SAME_AS` is forbidden at the schema/service level, not merely discouraged — the
contract's Example 4 states *"A worker attempting the forbidden write is rejected by
schema/service constraint."*

### Current production — a separate workstream, not a target input

This is documented here so implementers understand the environment they are migrating from.
**It does not alter the target semantic model.** Full detail:
`investigation/store-inventory.md` Security Findings E and G.

`VERIFIED CURRENT` — `olbrain-studio`'s shared `firestore.rules` has three catch-all blocks
that OR together with every other rule. Because Firestore grants an operation if *any*
matching rule allows it, a tighter named rule sitting inside the shadow of an unexcluded
catch-all is dead code. Confirmed exposed to any signed-in user, any org, read **and** write:
`agents/{id}` (the platform's central ownership document, including reassignment of
`owner_id`/`organization_id`), `organizations/{org}/connector_credentials` (with no org
predicate at all), `agent_sessions`, `agent_messages`, `agent_learned_patterns`,
`context_logs`, `context_facts`, `context_guardrails`, `vibe_sessions`, `research_templates`,
`workflow_definitions`, `workflow_agent_memory`, and the top-level `research_runs` document.
`knowledge_library` is read-exposed, write-correct.

`VERIFIED CURRENT` — none of this is covered by `tests/firestore-rules/`, whose own README
states CI does not gate on it.

`VERIFIED CURRENT` — the compounding finding: application-layer gaps (workflow-runtime's
unauthenticated routers, agent-engine's dark Context CRUD) and the rules-layer gaps are
**independent** failures. Fixing one layer does not fix the other. This is a direct, live
instance of §15's *"a failure in one control plane MUST NOT be compensated by another."*

**The important positive finding, for calibration:** `agent_datastores` is **fully denied to
all clients** (`allow read, write: if false`), excluded from every catch-all, and **backed by
a passing test** — a deliberate 2026-09 fix (commit `9fdf819b`). `agent_user_memory` has a
real `isOrgMember` read gate with server-only writes. `organization_api_keys` has an
IDOR-safe revoke flow. The `clix-capital-prod` dedicated-tenant ruleset is genuinely
default-deny. The team demonstrably can and does build this correctly; the gap is coverage
and prioritisation on a file being actively hardened one collection at a time.

**Migration implication:** because `agent_datastores` is already client-denied and tested, it
is the *safest* store to migrate behind a Gateway — no browser client depends on direct
access. `agent_sessions` / `agent_messages` are the opposite: Studio and Noesis read them
directly from the browser, so per `senior-feedback.md` §3 the remediation is
organization-scoped authorization, **not** simply denying browser access. That constrains the
migration order (§26).

`IMPLEMENTATION QUESTION` — whether the Memory Gateway fronts session/message reads for
Studio and Noesis, or whether those clients keep direct reads under corrected rules. This is
a product/infrastructure sequencing question the source material does not settle.

**Evidence / source basis:** contract §2, §6, §10, §13 Examples 3/4/17, §14;
`investigation/store-inventory.md` Security Findings E, G, H; `artifacts/senior-feedback.md`
§3; `olbrain-studio` `firestore.rules` (HEAD `252f7887`).

## 15. Async Consolidation / Outbox

### The crossing rule

`NORMATIVE REQUIREMENT` (§9), the contract's central invariant and the largest gap between
current and target:

> *"Asynchronous memory MUST NEVER bypass the State Mutation Contract. Where async processing
> discovers a possible current-state change, it submits a candidate or state-mutation request
> through the same policy engine, with the same `expected_version`, `expected_status`,
> idempotency and generation checks as any agent mutation. A worker has no privileged write
> path. This is what keeps extraction errors from silently becoming operational truth."*

Restated as §12 rule 5: *"Asynchronous semantic memory may propose knowledge but cannot bypass
the State Mutation Contract."*

### The synchronous / asynchronous split

`NORMATIVE REQUIREMENT` (§9). *"The next turn depends only on the synchronous state contract.
It MUST NOT depend on semantic consolidation having completed."*

| Synchronous — required for the next decision | Asynchronous — improves future recall |
|---|---|
| authorization | semantic extraction |
| current-state retrieval | entity resolution |
| current-state mutation | embeddings |
| state-machine transitions | graph projection |
| explicit immediate directives | summarization |
| critical operational observations | long-term memory promotion, consolidation, decay, analytics |

Evidence and State commit atomically in one transaction on the synchronous path.

### Transactional outbox

`NORMATIVE REQUIREMENT` (preamble, §14): the MVP realisation is *"a transactional outbox with
SKIP LOCKED workers."*

`PROPOSED IMPLEMENTATION` — the outbox row is written **in the same transaction** as the
Evidence/Claim/StateSlot commit, so there is no window in which state advanced but downstream
work was never enqueued. The contract names SKIP LOCKED workers as the MVP mechanism; the
exact claim-statement form is an implementation choice, not established by any source.

`OPEN DECISION` — retry and dead-letter policy for workers rejected by a generation bump.
§16 row 8, default **None**, owner **Operations**, Open. This is not a detail: a
generation-rejected write must have a defined disposition, or rejected work is either
silently dropped or retried forever.

### Generation checks in workers

`NORMATIVE REQUIREMENT` (§10): a worker captures the `scope_generation` snapshot for the
relevant scope chain when it starts. **If any required generation has changed before commit,
the write is rejected.** Generations exist per deletable scope class — `TENANT`, `WORKSPACE`,
`CUSTOMER`, `SESSION` — not for customers alone.

The contract's Example 13 and Example 20 step 7 both turn on exactly this: a background worker
holding a stale generation attempts to reinsert a claim after the scope was deleted, and is
rejected.

### Current production — every async pipeline violates the crossing rule

`VERIFIED CURRENT`. Each of these writes directly to its own final store with no policy gate,
no `expected_version`, no candidate submission:

| Pipeline | Repo | Direct write target | Trigger |
|---|---|---|---|
| Extract-mode memory | olbrain-agent-runtime | `agent_datastores` entries, `agent_user_memory` | fire-and-forget post-turn, `_kickoff_user_memory_update` |
| Session summarization | olbrain-agent-runtime | `agent_sessions.summary` | post-turn |
| Learned-pattern capture | olbrain-agent-runtime | `agent_learned_patterns` | post-turn |
| Fact consolidation | olbrain-agent-engine | `context_facts` | `maybe_consolidate` |
| Learning agent | olbrain-research-design | `research_templates/{id}/learned/*`, `learning_ledger` | `run_learn_agent` |
| Workflow memory learning | olbrain-workflow-runtime | `workflow_agent_memory` | exception/override capture |

**The closest thing to a compliant gate in production** is `context_facts`' verify-before-
active step (`alchemist/context/consolidation.py::Consolidator.consolidate()`, which never
promotes an uncited or judge-unsupported candidate and carries an explicit "NO fail-open here"
comment). **Target implication:** the *shape* is right — a candidate that must earn promotion.
But it is a bespoke, single-repo mechanism, not a shared policy engine the other five
pipelines route through, and its promotion step is currently flag-disabled in production
(`CONTEXT_CONSOLIDATION_ENABLED = "false"` in the deploy template) even though the log it
would consolidate is actively written.

### How uncertainty is represented

`NORMATIVE REQUIREMENT` (§5, §7): when the source model is uncertain, that uncertainty is
`extraction_confidence` — *"how sure we are the statement was made."* It is **not** truth, and
**not** authority. An async extraction with `extraction_confidence = 0.99` still cannot
establish a predicate whose `authority_domain` excludes it. The correct representation of an
uncertain async finding is a Claim with `assertion_status = pending` submitted through the
mutation contract, which policy may or may not promote — never a direct write with a
confidence field attached.

A conflicting async finding does not overwrite: it becomes another claim, and resolution
returns `CONFLICT` if policy cannot separate them (§6).

**Evidence / source basis:** contract §9, §10, §12, §14; `investigation/reconciliation.md` §4
(async-crossing row); `olbrain-agent-engine/alchemist/context/consolidation.py`;
`investigation/store-inventory.md`.

## 16. PostgreSQL MVP Logical Schema

`NORMATIVE REQUIREMENT` (preamble, §14): the MVP realisation is *"PostgreSQL with a vector
extension, a transactional outbox with SKIP LOCKED workers, and a Memory Gateway."* Critically:
*"They are not the architecture... the contract MUST survive substituting any of them."*
Redis / Kafka / Neo4j / dedicated vector infrastructure are `Optional; add only on measured
SLO or workload need` — they MUST NOT appear as required dependencies.

**Everything in this section is `PROPOSED IMPLEMENTATION`.** The contract establishes the
object model and the field lists quoted in §6–§12 above; it does not establish tables, column
types, or indexes. No schema here is approved.

### Entity overview

| Entity | Authoritative or projection | Rebuildable? |
|---|---|---|
| `evidence` | **Authoritative** | No — immutable source of everything |
| `claim` | **Authoritative** | No |
| `claim_lineage` | **Authoritative** | No |
| `predicate_policy` | **Authoritative** | No |
| `state_slot` | Materialized projection, **and** the OCC write surface | **Yes** — MUST be reproducible by replaying claims (§2) |
| `memory_object` | **Authoritative** | No |
| `narrative_memory` | **Authoritative** | No |
| `canonical_entity`, `entity_mention`, `entity_relation` | Mixed — canonical entity authoritative, resolutions revocable | Partly |
| `scope_generation` | **Authoritative** | No |
| `outbox` | Operational | N/A |
| `projection_watermark` | Operational | Yes |
| vector index, graph projection, DCI corpus | **Projection, never authority** | Yes |

### `evidence`

- **Purpose:** the immutable append-only record of what happened or was observed, including
  accepted state mutations.
- **Status:** authoritative, append-only. No UPDATE, no DELETE in normal operation.
- **Key identifiers:** `evidence_id` (PK); `scope_id`; `source_partition` + `source_offset`.
- **Important fields:** `evidence_type`, `actor`, `observed_at`, `committed_at`, `payload`,
  `mutation_id` (nullable, set when the evidence *is* an accepted mutation).
- **Scope/tenant boundary:** `scope_id` — also the frozen MVP freshness partition key (§8).
- **Versioning:** none; immutability is the guarantee.
- **Temporal:** `observed_at` and `committed_at` are system-time. Valid-time lives on Claims,
  not here.
- **Deletion:** deletion of evidence is an event, never a raw row delete (§10); dependent
  derived objects are invalidated synchronously.
- **Indexes/constraints implied:** UNIQUE `(source_partition, source_offset)`; monotonic
  offset per partition; index on `(scope_id, committed_at)`.
- `OPEN DECISION` — how `source_offset` is allocated so it is gap-free and monotonic per
  partition under concurrent commits. A plain sequence does not give contiguity (gaps appear
  on rollback), and the contiguous-watermark rule in §8 depends on this. Candidate approaches
  differ materially in write throughput; the contract does not choose one.

### `claim`

- **Purpose:** structured `(subject, predicate, object)` assertions derived from Evidence.
- **Status:** authoritative.
- **Key identifiers:** `claim_id` (PK); `(scope_id, subject, predicate)` for resolution lookup.
- **Important fields:** exactly the §1 list — `scope`, `authority_domain`, `source`,
  `valid_from`, `valid_until`, `assertion_status`, `policy_version`, `provenance`,
  `extraction_confidence` — plus the §5 measures kept **separate**: `independent_support_count`,
  `evidence_count`, `source_diversity`, `truth_support`.
- **Scope/tenant boundary:** `scope_id`, non-null. RLS predicate anchors here.
- **Versioning:** claims are not versioned in place; supersession creates a new claim and
  transitions the old one's `assertion_status`.
- **Temporal:** bitemporal — `valid_from`/`valid_until` (valid time) kept strictly separate
  from `observed_at`/`committed_at`/`invalidated_at` (system time).
- **Deletion:** status transition to `retracted` / `invalidated`, never row delete.
- **Indexes/constraints implied:** index supporting "claims eligible for this slot at this
  valid time under this knowledge cutoff"; CHECK that `assertion_status` is one of the eight
  normative values; FK to `predicate_policy(policy_version_id)`.
- **Directly implied by the contract:** there must be **no single `confidence` column**. §5
  prohibits collapsing the measures.

### `claim_lineage`

- **Purpose:** provenance as explicit lineage relations. `NORMATIVE REQUIREMENT` (§14):
  *"Explicit lineage relations, not evidence arrays."*
- **Status:** authoritative. This rules out a `supporting_evidence_ids[]` array column.
- **Key identifiers:** `(claim_id, evidence_id)`.
- **Why it must be a relation:** §10's support counting follows the lineage graph — where
  `E1` and `E2` both support `C1`, deleting `E1` leaves `C1` active; where `E1` was the only
  support, `C1` becomes `INVALIDATED` and is immediately excluded from retrieval. That query
  is a join, not an array scan.
- **Indexes implied:** both directions — by `claim_id` and by `evidence_id` (the deletion
  cascade traverses evidence → dependents).

### `predicate_policy`

- **Purpose:** the mandatory registry (§3).
- **Status:** authoritative, **versioned and immutable** (§14).
- **Key identifiers:** `policy_version_id` (PK); `(predicate, version)` unique.
- **Important fields:** the full §3 structure, including the nested `freshness_contract`.
- **Versioning:** immutable rows. A change creates a new `policy_version_id`. Claims bind to
  the version under which they were accepted.
- **Deletion:** never. Historical claims reference old versions for provenance.
- **Indexes/constraints implied:** UNIQUE `(predicate, version)`; an "active version per
  predicate" lookup; CHECK on `cardinality` against the six normative values.
- `OPEN DECISION` — whether more than one version may be resolution-active concurrently
  (§16 row 2, owner Architecture, unconfirmed).

### `state_slot`

- **Purpose:** Current State. Both the OCC write surface and a materialized projection.
- **Status:** **projection that must be reproducible by replay** (§2) — but simultaneously
  the authoritative operational representation and the thing OCC versions.
- **Key identifiers:** `(scope_id, domain, key)` — the natural PK, per §2's slot addressing.
- **Important fields:** exactly the §2 list — `value`, `status`, `state_version`,
  `produced_at_position`, `valid_from`, `valid_until`, `last_mutation_id`, `authority_domain`,
  `policy_version_id`, `freshness_status`.
- **Scope/tenant boundary:** `scope_id`, non-null, RLS anchor.
- **Versioning:** `state_version`, incremented on any change to the *resolved* value —
  including changes with no agent mutation behind them (§2).
- **Temporal:** carries its own validity window; `produced_at_position` is a third concept and
  MUST NOT be compared with `state_version` (§7, §12 rule 1).
- **Deletion:** `CLEAR` is an operation producing an evidence+state event; the resulting
  status depends on policy and is not automatically `EXPLICIT_NONE` (§10).
- **Indexes/constraints implied:** PK `(scope_id, domain, key)`; `status` NOT NULL with a
  CHECK against the declared granularity for that predicate's cardinality; `value` nullable
  **independently** of status — because `UNKNOWN` and `EXPLICIT_NONE` must be distinguishable
  and neither is "value IS NULL" alone.
- **Explicitly rejected by the contract:** one row per scope holding a JSON blob of all
  predicates. §14: `Giant mutable state JSON → Rejected — independently versioned State
  Slots`.
- `OPEN DECISION` — representation for non-`SINGLE` cardinalities. A `MAP` must support
  per-key status and a `SET` per-element status (§11), which a single `status` column on one
  row cannot express. Either a child table or a structured column is needed; the contract
  requires the *semantics*, not a storage choice.

### `memory_object` and `narrative_memory`

- **Purpose:** retained knowledge (§1) and non-assertive context (§1 Patch 9) respectively.
- **Status:** authoritative. Neither is a projection; neither is rebuildable from claims.
- **Kept as separate entities deliberately** — merging them would lose the non-assertive label
  that §1 requires be carried and clearly displayed.
- **`narrative_memory` required fields** (`NORMATIVE REQUIREMENT`, §1): `scope`, `provenance`,
  `observed_at`, `valid_from`/`valid_until` where meaningful, `retention_class`,
  `security_class`, `status`. These are not optional and should be NOT NULL where the contract
  says MUST.
- **Constraint directly implied:** there must be no code path by which a `narrative_memory`
  row can be promoted into a `state_slot`. §1: it MUST NOT establish Current State, override
  Claims, establish authority, or be used as hidden authorization evidence.
- `OPEN DECISION` — `retention_class` vocabulary. Ties to §16 row 5 (owner: Legal / compliance
  / data governance, Open). Do not invent classes.

### Entity resolution: `canonical_entity`, `entity_mention`, `entity_relation`

- `NORMATIVE REQUIREMENT` (§14): canonical global entities are **Allowed**; global entity as
  authorization bridge is **Forbidden**; cross-customer `SAME_AS` is **Forbidden**;
  `RESOLVES_TO` is `Mention → canonical entity, non-authorizing`; entity destructive merges
  are `Rejected in initial implementation`.
- **Constraint directly implied:** `SAME_AS` must carry a scope and a constraint rejecting
  cross-scope pairs at the schema/service level — Example 4 states a worker attempting the
  forbidden write *"is rejected by schema/service constraint."*
- **Reversibility is required:** Example 4 shows a wrong resolution being `REVOKED` with the
  mention and its evidence untouched. So `RESOLVES_TO` needs a status, not a delete.

### `scope_generation`

- **Purpose:** deletion protection (§10).
- **Key identifiers:** `(scope_class, scope_id)` → integer generation.
- `NORMATIVE REQUIREMENT`: per **every** deletable scope class — `TENANT`, `WORKSPACE`,
  `CUSTOMER`, `SESSION` — not customers alone.
- Workers snapshot the relevant scope chain at start and are rejected at commit if any
  required generation changed.

### `outbox` and `projection_watermark`

- **`outbox`:** written in the same transaction as the Evidence/Claim/StateSlot commit.
  Claimed by SKIP LOCKED workers, the mechanism the contract names. Carries `mutation_id` for idempotency and the scope
  generation snapshot.
- **`projection_watermark`:** per projection, per partition — `consumed_through_position`.
  `NORMATIVE REQUIREMENT` (§8): this MUST be the highest **contiguous** committed position
  fully incorporated, **not** the maximum observed by any worker. Parallel workers MUST NOT
  advance it across a gap. A naive `MAX(position)` update is a contract violation, and it is
  the single most likely accidental error in this area.

### Authorization metadata

- `NORMATIVE REQUIREMENT` (§14): typed capability authorization is mandatory; RLS is defense
  in depth, **not the sole model**.
- `PROPOSED IMPLEMENTATION`: RLS policies anchored on `scope_id` across `claim`, `state_slot`,
  `memory_object`, `narrative_memory`, `evidence`; capability checks performed in the Gateway
  above the database.
- `OPEN DECISION` — capability caching and its TTL (§16 rows 1 and 6). Until decided, treat
  every capability check as online.

### What is explicitly NOT in the MVP

Redis, Kafka, Neo4j and dedicated vector infrastructure. §14 marks them `Optional; add only on
measured SLO or workload need`. Introducing any of them as a required dependency contradicts
the contract's MVP boundary, which the preamble lists among the things implementation
**must not decide**.

## 17. Current Store Mapping

Classification vocabulary is the investigation's, carried forward unchanged. Confidence
reflects evidence strength, **not** a substitute for verification — every HIGH row traces to
file-level evidence in `investigation/repo-notes/`.

### Agent Runtime

| Current store | Current semantics | Classification | Target role | Migration strategy | Major gaps | Confidence |
|---|---|---|---|---|---|---|
| `agent_user_memory` | Single per-(agent,user) blob: facts + field values, rewritten wholesale, no versioning | **IN-FLIGHT MIGRATION** (legacy write path frozen) | Decompose to **Claims** → per-field **StateSlots**; historical content → **Memory** | Per §18. Freeze remaining legacy writes; do not migrate the blob shape forward | No versioning, no per-field policy, no claim layer, unsalted person key | HIGH |
| `agent_datastores` | Three writers, three entry schemas, one path | **IN-FLIGHT MIGRATION** | **Decomposes by writer** — see §18. Not one target object | Per §18, writer by writer | No org on entries, no versioning, no provenance to source evidence | HIGH |
| `agent_learned_patterns` | Tool-call heuristics, `intent_examples` (≤3 verbatim user messages), `tool_sequence`, usage/failure counters | **VERIFIED CURRENT** | **`NO V2.0 TARGET MAPPING`** — procedural memory, outside v2.0 scope | **None in v2.0.** Leave in place. Do not force into Claim or Narrative Memory | Verbatim end-user content, no org field, world read+write+delete at rules layer | HIGH |
| `agent_sessions` | Session record; plaintext `phone_number`/`mobile_number`/`profile_name`; `.summary`, `.memory_anchor_ts` | **VERIFIED CURRENT** | Session doc → episodic/provenance container (§14: `Session as memory → Rejected`). `.summary` → **Narrative Memory** | Extract `.summary` into `narrative_memory` with the required fields; keep the session as a provenance container | Summary lacks all 7 required fields; PII in plaintext; world-readable | HIGH |
| `agent_messages` | Per-turn conversational record, plaintext content | **VERIFIED CURRENT** | **Evidence** (user message is a named evidence type, §1) | Feed forward as evidence source; historical backfill optional | No `source_position`; org only via parent session; world read+write | HIGH |
| `lead_profiles` | Plaintext contact records, agent+session scope | **VERIFIED CURRENT** | **Claims** about a person, or Memory — depends on predicate policy | Requires policy authorship before mapping | Org only when known; no claim structure | MEDIUM |
| `lead_contacts` | Org-scoped hashed contacts, capped refs | **VERIFIED CURRENT** | Entity/identity layer, **not** one of the five classes | Treat with identity migration (§23) | Shares the unsalted hash construction | MEDIUM |
| `active_config.json` (GCS) | Compiled runtime config, 5-min cache, no invalidation | **VERIFIED CURRENT** | **Not modelled by the contract** — configuration | No target mapping. Keep separate | No cache invalidation on publish (confirmed both sides) | HIGH |
| `config/firestore_config.py` | Old Firestore config service | **LEGACY** | None | Retire | Reachability of the no-settings path is an `OPEN QUESTION` | MEDIUM |
| `agents/{id}/mcp_configs/*` | Per-agent MCP bindings | **VERIFIED CURRENT** | **Not modelled** — configuration/credentials | Keep separate | `is_enabled` spelling unaccounted for (`IMPLEMENTATION QUESTION`) | HIGH |
| `protection_events` | Append-only audit stream | **VERIFIED CURRENT** | Audit plane — a candidate *input* to Evidence, not the Evidence plane | Keep; optionally feed evidence | No org field | MEDIUM |

### Agent Engine / Context Service

| Current store | Current semantics | Classification | Target role | Migration strategy | Major gaps | Confidence |
|---|---|---|---|---|---|---|
| `context_logs` | Append-only, immutable, idempotent-on-id event log | **VERIFIED CURRENT** | **Evidence** — closest existing analog | Best candidate for the first Evidence-plane integration | No explicit `source_position`; only SESSION/GLOBAL populated; not the sole evidence plane | HIGH |
| `context_facts` | Bi-temporal, `candidate→active/invalid`, `superseded_by`, verify-before-active | **VERIFIED CURRENT** (promotion flag-disabled in prod) | **Claim** — closest existing analog | Strongest migration candidate; needs typing, policy binding, OCC | Freeform not `(s,p,o)`; no policy version; no `state_version`; no erasure | HIGH |
| `context_guardrails` | Scoped guardrails; CRUD surface dark (`CONTEXT_CRUD_ENABLED=false`) | **VERIFIED CURRENT** | Policy-adjacent configuration — **not** one of the five classes | Evaluate against the Predicate Policy Registry; do not auto-map | Dark CRUD is bypassable via direct Firestore access | MEDIUM |
| `vibe_sessions` | Session doc with a small state machine (`active_conversant.state`), transaction-written | **VERIFIED CURRENT** | `.state` → **StateSlot** with `STATE_MACHINE` cardinality; session → provenance container | Author the transition policy first | Soft-delete only, no TTL, no erasure; world read+write | HIGH |

### Research

| Current store | Current semantics | Classification | Target role | Migration strategy | Major gaps | Confidence |
|---|---|---|---|---|---|---|
| `research_templates/{id}` | Template metadata + GCS body; `org_id` required at schema level | **VERIFIED CURRENT** | **Not modelled** — design-time artifact | Keep separate | World read+write at rules layer | HIGH |
| `.../learned/profile`, `.../learned/design` | Overlay documents, CAS-written, existence-gated merge | **VERIFIED CURRENT** | **Memory** (learned design/behaviour), with the CAS as an OCC precedent | Needs org field, policy binding, claim structure | No `organization_id` at schema level under `extra="forbid"` | HIGH |
| `.../learned/substance` | Synthesized substance overlay, applied unconditionally | **CONTRADICTED BY SOURCE** (the "opt-in flag" claim) | **Memory** | As above | Resolution is unconditional — the flag does not exist | HIGH |
| `learning_ledger` | Append-only LLM-synthesized statements; "no API to delete one" | **VERIFIED CURRENT** | **Evidence** (append-only) — or Memory, depending on policy | Candidate second Evidence source | No erasure path at all; no org field | HIGH |
| `research_runs` | RunMeta with a real phase progression | **VERIFIED CURRENT** | `.phase` → **StateSlot**, `STATE_MACHINE` | Author the phase transition policy | Top-level doc world-writable; the model's own comment admits it | HIGH |

### Workflow

| Current store | Current semantics | Classification | Target role | Migration strategy | Major gaps | Confidence |
|---|---|---|---|---|---|---|
| `workflow_agent_memory` | Per-agent doc holding `exception_patterns` + `learned_overrides`; raw business data verbatim | **VERIFIED CURRENT** | **Split.** `learned_overrides` → **Claim** via Predicate Policy; `exception_patterns` → **`NO V2.0 TARGET MAPPING`** | Per §20 — decompose, do not migrate the document | No org field at schema level; no REST auth; no rules; no versioning | HIGH |
| `workflow_runs.status` + `orchestrator_generation` | Status progression + integer fencing counter | **VERIFIED CURRENT** | `.status` → **StateSlot** `STATE_MACHINE`; generation → precedent for `scope_generation` | Generalise fencing to scope classes | Fences pass-vs-pass, not deletion-vs-write | HIGH |
| `workflow_definitions` | Metadata doc + Storage body; legacy inline-JSON fallback | **IN-FLIGHT MIGRATION** | **Not modelled** — design-time artifact | Keep separate; complete the existing migration | Migration script not located (`IMPLEMENTATION QUESTION`) | HIGH |
| `workflow_items`, `step_outputs`, `workflow_agent_decisions` | Run-scoped records | **VERIFIED CURRENT** (org binding of items is `OPEN QUESTION`) | Evidence / operational records | Defer until item org-binding is resolved | No app-layer auth found; `WorkflowItem` model not located | MEDIUM |
| `workflow_agent_memory_archive` | One-time archive on cross-org transfer | **VERIFIED CURRENT** | Compatibility/retention artifact | Retain through migration | Only fires on transfer, never on org archival | HIGH |

### Knowledge Vault

| Current store | Current semantics | Classification | Target role | Migration strategy | Major gaps | Confidence |
|---|---|---|---|---|---|---|
| DCI corpus (GCS text) | Plain extracted text, regex/agentic-grep retrieval, 4-way scope | **VERIFIED CURRENT** | **Retrieval projection** — non-authoritative, rebuildable | Add a watermark; keep non-authoritative | **No `consumed_through_position` of any kind** — freshness undefined, not merely unenforced; retrieval unit is a text span, not a claim | HIGH |
| `knowledge_library` | Firestore metadata for the above | **VERIFIED CURRENT** | Projection metadata | Carry forward | Read-open cross-org; soft delete only | HIGH |
| `knowledge_embeddings` + OpenAI Vector Store | Previous generation | **LEGACY** (dead, zero live readers/writers) | None | Delete-in-place when convenient | — | HIGH |

### Config / Identity / Credentials — deliberately not mapped

`NORMATIVE REQUIREMENT` boundary: the contract scopes itself to Evidence / Claim / Current
State / Memory / Narrative Memory. `agents/{id}`, `active_config.json`,
`agents/{id}/mcp_configs/*`, `organizations/{org}/connector_credentials` and
`organization_api_keys` are design-time and operational configuration, identity and
credentials. **They are outside the five-class model and this specification does not force a
mapping.** They remain a separate concern with their own authorization requirements — which,
per §14, are currently the most severely exposed part of the platform.

## 18. `agent_user_memory` / `agent_datastores` Decomposition

This is the hardest migration problem in the programme and the section most likely to be
mis-executed. **`agent_datastores → Memory` is wrong.** One Firestore path currently serves
three semantically different use cases, written by three independently-authored code paths in
two repositories, with three different entry schemas.

All three write to the identical path, verified directly in both repos:

```text
agent_datastores/{agent_id}/tables/{table_id}/entries/{entry_id}
```

### Writer 1 — extract-mode, person-keyed (olbrain-agent-runtime)

- **Code:** `services/extract_entry_writer.py::write_extract_entry()`, called from
  `services/agent_memory_service.py` for each non-legacy `wanted_sets` entry. Kicked off
  fire-and-forget post-turn from `core/lightweight_processor.py::_kickoff_user_memory_update`.
- **Key:** `entry_id = person_hash(user_key)` — one row **per person**, upserted.
- **Entry fields:** `entry_id`, `last_session_id`, `user_key_kind`, `channel`, `values`,
  `updated_at`, `created_at`. **No `session_id`** (by design — the row is per person, not per
  call). **No `organization_id`.**
- **Semantics:** these are **assertions about a person** produced by asynchronous LLM
  extraction. "This person's delivery address is X."
- **Target:** **Evidence → candidate Claim → StateSlot** where the predicate is
  `current_state_eligible`. Never a direct Memory write.
- **Why:** this is the §9 crossing-rule violation in its purest form — an async LLM extraction
  writing straight into a store the prompt then reads back unconditionally
  (`core/cs_packet_builder.py::_load_person_records_block`, called on every packet build). An
  extraction error becomes operational truth with nothing in between.

### Writer 2 — live agent tool, session-keyed (olbrain-agent-runtime)

- **Code:** `core/tools/datastore_executor.py::DatastoreExecutor._add()`, dispatched from
  `_run()`.
- **Key:** random `uuid.uuid4().hex[:12]` — **multi-row per session**, bounded by
  `MAX_PER_SESSION` / `MAX_PER_TABLE`.
- **Entry fields:** `entry_id`, **`session_id`**, `values`, `created_at`, `updated_at`. No
  `organization_id`.
- **Semantics:** an **in-turn record of something the agent captured** — structurally an
  append of observations within a session, not a per-person assertion.
- **Target:** synchronous, so it **can** be a typed mutation directly — but its natural target
  is closer to **Evidence** plus, where the policy says so, a Claim. Appending rows is not
  slot mutation.
- **Migration hazard:** the LRU caps (`MAX_PER_SESSION`, `MAX_PER_TABLE`) are
  **eviction-by-size**, which has **no target analog**. Evidence is append-only and immutable;
  it is not evicted because a counter was reached. `OPEN DECISION` — whether these caps
  become a retention policy (ties to §16 row 5), a hard rejection at the boundary, or are
  dropped.

### Writer 3 — operator-authored via Studio (olbrain-agent-design)

- **Code:** `app/services/datastore_service.py::create_entry()` (plus `PATCH`, `DELETE`,
  CSV import), behind `app/routers/datastore.py` mounted at `/api/v1/datastore`.
- **Auth:** Firebase token + a permission ladder (`check_view_permission` /
  `check_edit_permission`) gated on agent ownership / org membership / scoped API key. Every
  write emits an `AuditEvent`.
- **Entry fields:** `entry_id`, `values`, `updated_by`, `updated_at`, conditionally `source`,
  `created_by`, `created_at`, `user_key_kind`. **No `organization_id`.**
- **Semantics:** a **human operator correcting or authoring** a record. This is the highest
  authority of the three.
- **Target:** **Claim** with a verified-operator source, under a policy whose
  `allowed_sources` admits operator authority. This maps cleanly.
- **Note:** this path holds the **only hard DELETE** in the whole feature — described in its
  own source as "the only irreversible write in this feature." It is the platform's de facto
  GDPR/operator erasure route for this collection.

### The core findings

1. **Three writers, one path, three different entry schemas.** No consumer can tell from an
   entry which writer produced it except by inferring from which fields are present
   (`session_id` present → writer 2; `updated_by` present → writer 3; neither → writer 1).
   That is an accident, not a design.
2. **No `organization_id` on any entry, from any writer.** Confirmed at the schema level —
   there is no Pydantic model for an entry at all; the shape is caller-defined plain dicts.
   Org lives only on the parent table document.
3. **No versioning on any of them.** No `state_version`, no CAS, no conflict detection
   between three concurrent writers to the same person row.
4. **Writer 1 and writer 3 can silently overwrite each other.** An operator correction and a
   subsequent async extraction both target the same `person_hash` row with a merge write. The
   operator's higher authority is not represented anywhere, so the extraction wins by
   recency — precisely the `Last-write-wins → Rejected for important state` outcome (§14).

### Lossless migration is not possible for writer 1

**This is an `OPEN DECISION`, not a detail to paper over.**

A target Claim requires `provenance` — explicit lineage relations back to the Evidence that
supports it (§14). Extract-mode entries carry **no reference to the evidence that produced
them**: no `session_id` (deliberately, since the row is per person), no message id, no
extraction run id. `last_session_id` records only the most recent touch, not the support for
any particular field value. The Evidence records that a compliant Claim needs **do not exist
and cannot be reconstructed** from the stored row.

The options, neither of which this document may choose:

- **(a) Synthesize placeholder Evidence** — mint a migration-provenance evidence record per
  migrated row, explicitly marked as backfill with no original observation. Honest about the
  gap; pollutes the evidence plane with non-observations.
- **(b) Migrate as un-provenanced Memory** — land the rows in `memory_object` rather than as
  Claims, and let future extractions build real Claims going forward. Keeps the evidence plane
  clean; means historical person facts never become current-state-eligible.

`OPEN DECISION` — requires an architecture owner. Note that (b) has a migration-order
consequence: the prompt-read path (`_load_person_records_block`) currently renders these rows
into the system prompt unconditionally, so whichever option is chosen must keep that path
working or change it in the same step.

### `agent_user_memory` specifically

`VERIFIED CURRENT` / `IN-FLIGHT MIGRATION`. One document per `(agent, sha256(user_key)[:32])`
holding `facts` plus `field_values` / `field_values_by_set`, rewritten wholesale.

This is **exactly** the pattern §14 rejects: `Giant mutable state JSON → Rejected —
independently versioned State Slots`, applied at person scope instead of customer scope. The
migration to `agent_datastores` already underway does **not** fix it — it moves the same blob
shape to a different collection, per-`wanted_sets`-entry via a `legacy: True` flag rather than
a module-level switch. Three paths are live in one file simultaneously: the flat
`wanted_fields` path (always frozen), the `legacy_sets` path (frozen), and the non-legacy
`wanted_sets` path (routes to `agent_datastores`).

**Target:** each field becomes its own predicate with its own policy, its own Claims and its
own independently versioned StateSlot. The `facts` free-text portion is a Memory or Narrative
Memory candidate depending on whether it yields reliable structured assertions (§1).

`IMPLEMENTATION QUESTION` — whether the in-flight `agent_user_memory → agent_datastores`
migration should be **completed** or **halted** in favour of migrating both directly to the
target model. Completing it moves data twice, through an intermediate shape the contract
rejects. Halting it leaves three live write paths in one function for longer. The source
material does not decide this; it is a sequencing judgement for whoever owns the runtime.

**Evidence / source basis:** `olbrain-agent-runtime`
`services/extract_entry_writer.py`, `services/agent_memory_service.py`,
`core/tools/datastore_executor.py`, `core/cs_packet_builder.py`,
`core/packet/person_records.py`; `olbrain-agent-design` `app/routers/datastore.py`,
`app/services/datastore_service.py`; `olbrain-shared`
`src/olbrain_shared/agent/datastore/columns.py` (read directly);
`investigation/repo-notes/olbrain-agent-runtime.md`, `olbrain-agent-design.md`;
`investigation/store-inventory.md` Cross-Repo Flow 10.

## 19. Research Integration

**Target boundary:** research owns template design and run execution. Neither is modelled by
the contract. What the contract does model is the *learned* material research produces.

| Research artifact | Target role | Notes |
|---|---|---|
| `research_templates/{id}` + GCS body | **Not modelled** — design-time artifact | Keep in research's own domain |
| `learned/profile`, `learned/design` | **Memory** | Behavioural/design overlays; not assertions about a customer |
| `learned/substance` | **Memory** | Applied unconditionally today |
| `learning_ledger` | **Evidence** (append-only) | Strong second candidate for the Evidence plane |
| `research_runs.phase` | **StateSlot**, `STATE_MACHINE` cardinality | Needs a transition policy authored |
| Model/pricing catalog | **Not modelled** | `CONTRADICTED BY SOURCE` for the "duplicate catalog" claim — one shared `MODEL_CATALOG` in `olbrain_shared.research.pricing` |

**Existing production precedent:** `learning_service.write_profile(expected_version=...)` CAS,
with two independent writers (consolidator and operator surface) both routing through the same
`get_profile → mutate → write_profile` loop, and operator mutations org-guarded through the
parent template.

**Target implication:** the two-writers-one-CAS-loop pattern is the correct shape and is
directly reusable. Two things do not carry forward: the application-level retry of a semantic
conflict (§12 forbids infrastructure retrying semantic rejections — an agent, or here an
operator, must decide), and the absence of any org field on the stored record. `org_id` is a
parameter of `run_learn_agent`'s signature but is verified **dead** — never stored, never
passed to `write_profile`, never used for scoping. Org association is implicit via the parent
template only.

**Migration hazard — multiple writers:** see §11 of the task framing, answered in §20 below
for all four multi-writer stores.

`OPEN QUESTION` (carried forward) — the `/pubsub/learn-design` exemplar-reconstruction route
is mid-migration to unified `job_type` dispatch, named "Phase 5" in code. Its completion is
independent of this programme.

## 20. Workflow Integration

### `workflow_agent_memory` must be split, not migrated

The document holds two structurally different things and the freeze treats them differently:

| Component | Target | Basis |
|---|---|---|
| `learned_overrides[]` (`LearnedOverride`) | **Claim** via Predicate Policy entry | `architecture-freeze.md` §3; Decision 1a |
| `exception_patterns[]` (`ExceptionPattern`) | **`NO V2.0 TARGET MAPPING`** | `architecture-freeze.md` §2; Decision 1b |

They live in the same document and are frequently discussed together, but one is an assertion
and one is a procedure. **They must not be collapsed back together during migration.**

`LearnedOverride` field mapping (from the freeze, §3): subject = `step_id` + `field` +
`selector`; object = `correction`; provenance = `evidence_exception_ids` / `evidence_run_ids`;
lifecycle `suggested → active → retired` maps onto `pending → active → retracted`. Also
present: `confidence`, `approved_by`, `approved_at`, `contradiction_count`. Requires a registry
entry with an operational-correction authority domain and human approval to reach `active` —
**not** a contract change.

### Workflow state

`workflow_runs.status` → **StateSlot** with `STATE_MACHINE` cardinality. Today status-gating
in `workflow_triggers.py` checks legality **by convention**, not via a policy-driven
`allowed_operations_by_status` table — which is exactly what §3 requires.

**Existing production precedent:** `orchestrator_generation`, incremented on every
resume/retry. **Target implication:** generalise to `scope_generation(scope_id)` per deletable
scope class. The existing counter solves a narrower problem (two orchestrator passes racing)
than §10's model (deletion racing a write).

### Multi-writer analysis

The task asks eight specific questions of every multi-writer store. Answered:

| | `agent_datastores` | Research learned overlays | `workflow_agent_memory` | Learning pipelines (cross-cutting) |
|---|---|---|---|---|
| **1. Who writes today?** | 3: extract-mode, agent tool, operator CRUD | 2: consolidator, operator (`pin`/`edit`/`archive`) | Workflow runtime exception/override capture | 6 async pipelines across 4 repos |
| **2. Who reads today?** | Prompt builder (unconditional), Studio operator UI | `resolve_effective_body()` at every template load | Workflow orchestrator | Each pipeline's own store |
| **3. Semantically equivalent?** | **No** — person assertion vs. session observation vs. operator correction | **Nearly** — both mutate the same profile items | **No** — overrides are assertions, patterns are procedures | **No** |
| **4. Which should be authoritative?** | **Operator** (writer 3) — highest authority, audited, authenticated | Operator over consolidator, by the same reasoning | `LearnedOverride` after human approval | N/A |
| **5. Which become evidence producers?** | Writers 1 and 2 — both become Evidence + candidate Claims | Consolidator becomes an evidence producer | Exception capture → out of v2.0 scope | **All of them** |
| **6. Where does OCC happen?** | On the target StateSlot, via the Gateway — not in Firestore | Already CAS; move to the slot | On the override's slot | At the mutation contract, uniformly |
| **7. Duplicate/replayed writes?** | Idempotent on `mutation_id`; replay produces the same result (§7) | Same | Same | Same — this is why `mutation_id` is mandatory |
| **8. Avoiding two competing truths?** | Single-writer-at-a-time cutover per table; never dual-write authoritative state | Dual-**read** during transition, single authoritative writer | Split first, then migrate the override half | Route through the Gateway before migrating storage |

The general rule that falls out: **dual-read is safe during migration; dual-write to
authoritative state is not.** Two writers producing independently-versioned truth is the exact
condition OCC exists to prevent, and a migration that creates it temporarily has created it
permanently in every record written during the window.

## 21. Knowledge Vault Integration

`NORMATIVE REQUIREMENT` (§8, §14): the vector index and graph are **projections, never
authority**. `Vector index as truth → Rejected — produces candidates, never authority`.

| Component | Target role |
|---|---|
| DCI corpus (GCS text) | **Retrieval projection** — non-authoritative, rebuildable |
| `knowledge_library` (Firestore metadata) | Projection metadata |
| `knowledge_embeddings` + OpenAI Vector Store | **LEGACY**, dead — retire |

**The single most important gap:** the DCI corpus has **no watermark of any kind**. Freshness
is therefore *undefined*, not merely unenforced. §8 requires a derived projection to record
`consumed_through_position`, and requires it be the highest **contiguous** incorporated
position. Adding this is a precondition for the corpus to participate in any freshness-aware
retrieval.

**Second gap:** the retrieval unit is a raw text span, not a claim. §8 requires memory be
structured at claim level rather than treating a whole text chunk as one truth unit, and
requires the path `Vector search → candidate memory object → structured claims →
authorization → validity → predicate policy → ranking → context`. Today DCI returns text
spans directly.

**Good news for migration:** because the corpus is explicitly non-authoritative and
rebuildable, it can be re-derived at any point without data loss. It is the *lowest*-risk
component to change and does not need to be migrated in lockstep with the authoritative
stores.

Scope is 4-way (agent / org / client-project / platform-skill), not the 3-way earlier claimed.
Auth is 5 independent Google-OIDC service allowlists for machine paths, with Firebase tokens
for Studio-facing ingestion. No org-level bulk deletion cascade exists.

## 22. Session / Conversation Memory

`NORMATIVE REQUIREMENT` (§14): `Session as memory → Rejected — session is an
episodic/provenance container`. This is a named, explicit rejection, and it constrains how
`agent_sessions` and `vibe_sessions` may be treated.

| Current element | Target role |
|---|---|
| `agent_sessions` document | Episodic / provenance container — **not** memory |
| `agent_sessions.summary` + `memory_anchor_ts` | **Narrative Memory** (cleanest fit found) |
| `agent_messages` | **Evidence** — "a user message" is a named evidence type (§1) |
| `vibe_sessions` document | Provenance container |
| `vibe_sessions.active_conversant.state` | **StateSlot**, `STATE_MACHINE` |

**PII constraint:** `agent_sessions` currently carries plaintext `phone_number`,
`mobile_number` and `profile_name` on the session document, and both sessions and messages are
world-readable and world-**writable** at the Firestore rules layer. Per `senior-feedback.md`
§3, Studio and Noesis read these from the browser, so the remediation is **organization-scoped
authorization, not blanket denial** — which means the migration cannot simply put a Gateway in
front and close the collection.

`IMPLEMENTATION QUESTION` — whether session PII moves into the identity layer (§23) as part of
this migration or is handled separately. The source material establishes the exposure, not the
remedy.

## 23. Privacy / Identity Migration

### Current behaviour — verified directly against source

`VERIFIED CURRENT`. `olbrain-shared/src/olbrain_shared/agent/datastore/columns.py`:

```python
def person_hash(user_key: str) -> str:
    """Deterministic entry id for a person-keyed (fill="extract") row.

    Hashed so a raw phone or email never appears in a document path;
    normalised so one person is one row. The digest half of
    agent_memory_service.memory_doc_id — the agent id is dropped because the
    entry's path already carries it.
    """
    return hashlib.sha256(user_key.strip().lower().encode("utf-8")).hexdigest()[:32]
```

No salt, no pepper, no keying. The docstring itself confirms this is deliberately the same
construction as `agent_memory_service.memory_doc_id` — so **both** the `agent_user_memory` and
`agent_datastores` keying schemes share it.

### The problem

The input domain is phone numbers and email addresses — small, structured, and enumerable. An
unsalted SHA-256 over a normalised phone number is trivially reversible by dictionary or
rainbow table. Anyone holding a leaked entry id can confirm whether a specific known person
has a record, and anyone holding a list of phone numbers can enumerate which of them the
system knows about.

The stated intent in the docstring — "so a raw phone or email never appears in a document
path" — is met in the narrow sense that the plaintext is absent. It does not achieve
unlinkability, which is what the privacy property requires.

**Compounding factors, all verified:** `agent_sessions` carries plaintext phone numbers and
profile names on a world-readable document, so in many cases the plaintext is separately
available anyway; and the org-mismatch GDPR delete route correctly returns 404 to avoid an
existence oracle — a good pattern that the hash construction undermines from the other
direction.

### Why the migration is hard

Changing the construction **breaks the key for every existing row in both schemes
simultaneously**, because they deliberately share it. The entry id *is* the person identity —
there is no separate stable person identifier to re-key against. Consequences:

- A rehash requires the original `user_key` (the raw phone/email) to compute the new id. That
  value is **not stored** on the entry — only `user_key_kind`. It would have to be recovered
  from session documents or from the source channel.
- Dual-key operation is therefore **implied**: a period in which both old and new ids resolve
  to the same person, with a mapping table, until every row is re-keyed.
- Rows whose original `user_key` cannot be recovered cannot be re-keyed at all.

`OPEN DECISION` — the replacement construction. **This document does not propose one.** §22 of
the task brief forbids inventing a hashing algorithm, and the source material establishes none.
What must be decided, by a named security owner: whether the replacement is keyed or salted,
where the key/salt lives, whether it is per-tenant, and the rotation procedure.

`OPEN DECISION` — disposition of rows whose `user_key` is unrecoverable.

`OPEN DECISION` — whether person identity moves to an opaque surrogate id with the hash
retained only as a lookup index, which would decouple identity from the hash construction
permanently and make future rotation cheap. Attractive, but not established by any source
material.

**Target requirement that *is* established:** identity resolution is an entity-layer concern,
and per §14 cross-customer `SAME_AS` is forbidden while `RESOLVES_TO` is explicitly
non-authorizing. Whatever construction is chosen must not become an authorization bridge — the
ability to compute that two records concern the same person must not grant visibility across
scopes.

## 24. Deletion / Erasure

### Current behaviour

`VERIFIED CURRENT`, and the gaps are substantial:

- **No hard organization-delete exists anywhere in the platform.** Only
  `archive_organization` / `restore_organization`, a soft status flip on `projects` and
  `agents`, entirely disjoint from the transfer cascade.
- **The agent org-transfer cascade** (`_ORG_SCOPED_TEARDOWN_STEPS`, olbrain-studio-backend)
  covers DCI corpus (copy), `agent_sessions` (re-label), `workflow_agent_memory`
  (archive+delete), `knowledge_library` (repoint/detach), `mcp_configs` (soft-disable) and
  usage rollups (archive) — but **excludes `agent_datastores` and `agent_learned_patterns`
  entirely**, with zero references anywhere in the cascade code. An agent's most sensitive
  per-person data follows it across an org transfer with no mitigation.
- **No erasure route** for `context_logs`, `context_facts`, `vibe_sessions`,
  `research_templates`, `research_runs`, or `learning_ledger` ("no API to delete one" per its
  own code comment). `vibe_sessions` is soft-delete only with no TTL.
- **The one genuine hard-delete-plus-deindex path** anywhere in the investigation is
  `organization_documents`. The `agent_datastores` DELETE route (writer 3, §18) is the second.

### Target requirements

`NORMATIVE REQUIREMENT` (§10):

- **`CLEAR` is an operation; `EXPLICIT_NONE`, `UNKNOWN` and `CONFLICT` are resolution states.
  They MUST NOT be conflated.** A `CLEAR` does not automatically imply `EXPLICIT_NONE` —
  clearing because the customer said "I sold it" yields `EXPLICIT_NONE`; clearing because a
  sync source was removed yields `UNKNOWN`. Policy decides.
- **Deletion is never a raw row delete.** It creates an evidence and state event indicating
  `CLEAR`, `RETRACT` or `INVALIDATE`.
- **Memory deletion and state deletion are different.** Deleting a historical memory does not
  necessarily clear current state, and vice versa.
- **Scope generations** per deletable scope class — `TENANT`, `WORKSPACE`, `CUSTOMER`,
  `SESSION` — not customers alone. Workers snapshot the chain and are rejected on change.
- **Invalidation is synchronous; recomputation is asynchronous.** The binding invariant: *"an
  invalidated object that has not yet been recomputed MUST be excluded from retrieval, not
  served stale."* Without this the recompute window is a window in which deleted data remains
  reachable.
- **Support counting follows the lineage graph.** `E1` and `E2` both support `C1` → deleting
  `E1` leaves `C1` active. `E1` was the only support → `C1` becomes `INVALIDATED` and is
  immediately excluded.

### Aggregate deletion

`NORMATIVE REQUIREMENT` (§10): there is deliberately **no** universal rule that aggregates
survive deletion, and none that they must always be recomputed — *"Both are unsafe as blanket
architecture rules."* Every aggregate dataset MUST declare `dataset_id`,
`legal_basis_classification`, `retention_class`, `contains_customer_contribution`,
`customer_deletion_behavior`, `recomputable`, `lineage_policy`. Allowed behaviours are
`REMOVE_AND_RECOMPUTE`, `RETAIN_AS_NON_IDENTIFIABLE_AGGREGATE`, or another explicitly approved
category.

*"The contract MUST NOT claim a legal exemption for aggregated data unless the responsible
legal or compliance owner has explicitly classified that dataset."*

### Everything numeric here terminates in §16

**No retention period, recompute deadline or retry budget is proposed in this document.**

| Deletion design element | Governance dependency |
|---|---|
| Max window an invalidated object may remain un-recomputed | **§16 row 4** — Operations + Legal, Open |
| Retention class vocabulary and per-dataset classification | **§16 row 5** — Legal / compliance / data governance, Open |
| Bulk-deletion retry and DLQ for generation-rejected workers | **§16 row 8** — Operations, Open |

`OPEN DECISION` — all three. Single-scope deletion and correct exclude-don't-serve behaviour
are implementable now; bulk deletion and aggregate handling are not.

## 25. Temporal Semantics

### Two axes, never collapsed

`NORMATIVE REQUIREMENT` (§4):

```text
Valid time             valid_from, valid_until        when true in the modelled world
System/knowledge time  observed_at, committed_at,     when OLBrain observed/accepted/
                       invalidated_at                 invalidated it
```

`produced_at_position` is a **third, separate** concept — the Evidence Log position that
produced the current slot value. Three concepts, three representations.

Worked example from the contract — a user says on 17 September 2026, "I bought this phone last
month":

```text
valid_from   = 2026-08-01
observed_at  = 2026-09-17
committed_at = 2026-09-17
```

### Retroactive claims

`NORMATIVE REQUIREMENT` (§4) — a claim committed today MAY carry a `valid_from` in the past.
On commit:

1. the claim is evaluated against its valid interval;
2. all affected materialized State Slots are identified;
3. each affected slot is **re-resolved**;
4. the current projection is updated transactionally;
5. historical resolution for affected `as_of` times **is allowed to change**;
6. previously executed decisions are **not** rewritten.

```text
Historical truth MAY be revised by newly learned evidence.
Decision history MUST NOT be rewritten.
```

Step 3 is the mechanism by which `state_version` advances with no agent mutation. **This is
the single most important implementation consequence in this section:** late-arriving evidence
must trigger slot re-resolution, so the write path cannot assume slots change only when an
agent calls a mutation.

### Two independent historical queries

`NORMATIVE REQUIREMENT` (§4): a historical query MAY specify both axes independently —
`as_of_valid_time` and `knowledge_cutoff`. These must be answerable **separately**:

> "What did we believe on August 15?" versus "What is now believed to have been true on
> August 15?"

A schema that stores only one axis cannot answer both, and no amount of application logic
recovers the missing one.

### Current does not mean most recently mentioned

`NORMATIVE REQUIREMENT` (§4): *"Currentness is policy resolution."* Not last-message-wins, not
highest-confidence-wins, not newest-embedding-wins.

### Production precedent

**Existing production precedent:** `context_facts` bi-temporality — `t_valid` / `t_invalid`,
`status ∈ {candidate, active, invalid}`, `superseded_by`, `source_event_ids` back to the log;
`supersede()` and `decay()` only ever update status and `t_invalid`, never delete.
Invalidate-don't-delete is genuinely enforced in code.

**Target implication:** this is real bi-temporality and a genuine precedent — valid time via
`t_valid`/`t_invalid`, system time implicitly via `created_at`/`updated_at`. But **do not
assume it satisfies the target contract.** System time is *implicit*, so the "what did we
believe on August 15" query is not answerable today; there is no `knowledge_cutoff` parameter
anywhere; there is no re-resolution of downstream slots on late-arriving facts (there are no
slots); the status vocabulary is three values against the contract's eight; and the promotion
gate that would create `active` facts is flag-disabled in production
(`CONTEXT_CONSOLIDATION_ENABLED = "false"`).

`PRODUCTION PRECEDENT` for the shape. `TARGET REQUIREMENT` for everything above.

## 26. Migration Strategy

Phased, not big-bang. Phase names are adapted from the task brief where repository evidence
suggested a better decomposition — notably, governance closure and the policy registry are
separated, because the registry is on the critical path for everything and its *content* has a
different owner from its *code*.

**No phase below claims zero downtime.** Nothing in the source material establishes that, and
several steps (the person-key re-keying in §23) plainly cannot be done transparently.

### Phase 0 — Governance closure

- **Objective:** fill or formally defer the §16 parameters with named owners.
- **Systems touched:** none. This is a document and an owner list.
- **Prerequisites:** none.
- **Why first:** the contract forbids implementation teams inventing these values. Rows 5 and
  8 hard-block aggregate and bulk deletion; rows 1 and 6 block capability caching; row 3
  blocks every external-authority predicate.
- **Minimum to unblock Phase 1:** rows 1, 2, 3, 6, 7 are **not** required to build the
  Evidence/Claim/Policy core. Rows 4, 5, 8 are required before anything deletes at scale.
- **Rollback:** N/A.
- **Verification:** every §16 row is either filled or marked deployment-time configuration
  with a named owner. Note that row 3's owner is currently a role, not a party — that itself
  must be resolved.

### Phase 1 — Predicate Policy Registry (content, then code)

- **Objective:** author the first real policies and stand up the registry.
- **Systems touched:** new. No production writes.
- **Prerequisites:** none technically; domain owners for each predicate family.
- **Why here:** every other mechanism reads from it. Building the resolver first means
  building it against an empty registry.
- **Safety constraints:** policy rows immutable from day one. Do not ship a mutable policy
  table intending to add versioning later — claims bind to `policy_version_id` and a mutable
  row silently rewrites history.
- **Rollback:** drop; nothing depends on it yet.
- **Verification:** the state-machine policies for `workflow_runs.status` and
  `research_runs.phase` reproduce the transitions those systems already enforce in code.

### Phase 2 — Evidence plane + outbox

- **Objective:** the append-only evidence store with contiguous per-scope positions, and the
  transactional outbox.
- **Systems touched:** new store; **read-only** taps on `context_logs` and `agent_messages`.
- **Prerequisites:** Phase 1 (evidence is typed against predicates in places).
- **Safety constraints:** no production store is modified. Dual-**read** only.
- **Rollback:** stop the taps; delete the new store.
- **Verification:** contiguity — no watermark advances across a gap under concurrent writers.
  This is the property most likely to be silently wrong.

### Phase 3 — Claims + Mutation Contract + StateSlots

- **Objective:** the core. `MutateState`, OCC, `STATE_CONFLICT`, slot resolution per §6.
- **Systems touched:** new. Still no production writes.
- **Prerequisites:** Phases 1–2.
- **Safety constraints:** `STATE_CONFLICT` must reach the caller. Verify no retry decorator or
  framework middleware wraps the mutation path — this is easy to introduce accidentally and
  silently violates §12 rule 9.
- **Rollback:** drop.
- **Verification:** the §27 OCC, idempotency and status-gating suites pass.

### Phase 4 — Memory Gateway + authorization

- **Objective:** the boundary. Typed capabilities, fail-closed authorization, RLS beneath.
- **Systems touched:** new; becomes the only sanctioned path to the new stores.
- **Prerequisites:** Phase 3. Capability caching is gated on §16 rows 1 and 6 — until then,
  online-only.
- **Safety constraints:** resolution under system policy at step 2, authorization at step 9,
  never merged.
- **Rollback:** the Gateway is the only consumer; disable it.
- **Verification:** cross-org isolation suite (§27); no caller-specific resolution.

### Phase 5 — First bounded migration: operator-authored datastore entries

- **Objective:** migrate **writer 3 only** (§18) — the operator CRUD path — to Claims.
- **Why this one first:** it is the cleanest mapping (operator authority → Claim with a
  verified-operator source); it is already authenticated and audited; it has the lowest volume;
  and crucially `agent_datastores` is **already fully denied to all clients
  (`allow read, write: if false`) and covered by a passing rules test**, so no client read
  path breaks during cutover. It is the only PII-bearing store that is *fully denied* and
  test-covered — `agent_user_memory` is also correctly protected, but via an `isOrgMember`
  read gate rather than full denial, so a client read path does exist there.
- **Systems touched:** olbrain-agent-design's datastore routes, behind the Gateway.
- **Prerequisites:** Phases 1–4.
- **Safety constraints:** dual-**read** (Firestore remains the read source until parity is
  proven); **single authoritative writer** at all times. Never dual-write authoritative state.
- **Rollback:** point reads back at Firestore; the Gateway writes become an unused shadow.
- **Verification:** shadow-compare resolved slot values against Firestore entries for a full
  cycle before cutting reads over.

### Phase 6 — Async learning through the crossing rule

- **Objective:** convert each async pipeline (§15's table of six) from direct writes to
  candidate submission through the mutation contract.
- **Systems touched:** all four repos with learning pipelines.
- **Prerequisites:** Phases 1–5, plus the §18 `OPEN DECISION` on extract-mode provenance.
- **Safety constraints:** one pipeline at a time. Each conversion is independently
  reversible.
- **Suggested order** (lowest risk first): agent-engine's consolidator (already has a
  verify-before-active gate and is currently flag-disabled, so it is dark anyway) →
  research-design's learning agent (already CAS) → session summarization (Narrative Memory,
  non-assertive, cannot establish state) → extract-mode (highest risk: unconditional prompt
  read, unresolved provenance).
- **Rollback:** per pipeline, revert to the direct write.
- **Verification:** no worker holds a write path that bypasses the Gateway. Assert by code
  search, not by test alone.

### Phase 7 — Remaining stores, then legacy retirement

- **Objective:** sessions/messages as Evidence and Narrative Memory; workflow and research
  state slots; DCI watermark; retire `knowledge_embeddings` and the Firestore config service.
- **Safety constraints:** `agent_sessions` / `agent_messages` are read directly from the
  browser by Studio and Noesis — per `senior-feedback.md` §3 the remediation is
  **organization-scoped authorization, not blanket denial**. This phase cannot simply close
  the collection, and that is why it is last rather than first despite the severity of the
  exposure.
- **Verification:** legacy paths have zero readers and zero writers before deletion — the
  standard the knowledge-vault embeddings retirement already meets.

### Explicitly out of the critical path

The Firestore rules remediation (§14) is **not** a phase here. It is a live production
security workstream on its own timeline and must not wait for this migration — most of the
exposed collections will still exist in Firestore throughout Phases 0–6.

## 27. Testing / Verification

Architectural invariants translated into checks. Each cites the invariant it defends.

### Schema / invariant

- `state_slot.status` is NOT NULL and `value` is independently nullable — `UNKNOWN`,
  `EXPLICIT_NONE` and `VALUE(null)` are distinguishable. (§4)
- No single `confidence` column exists on `claim`; the five measures are separate columns.
  (§5)
- No giant-JSON state document exists; slots are individually addressable rows. (§14)
- Provenance is a lineage **relation**, not an array column. (§14)
- `predicate_policy` rows are immutable — an UPDATE is rejected. (§14)

### Authorization

- Cross-org isolation: a caller authorized for org A receives `ACCESS_DENIED` or no result for
  every object scoped to org B, across claims, slots, memory and narrative memory.
- Resolution is caller-independent: the same slot resolves to the same value and
  `state_version` for two differently-authorized callers; only visibility differs. (§6)
- A global canonical entity does not bridge authorization — B cannot enumerate A's
  relationships to a shared entity. (Examples 3, 17)
- Cross-scope `SAME_AS` is rejected at the schema/service layer. (Example 4)
- Fail-closed: an authorization backend error denies, never permits.
- The LLM cannot mutate identity/security predicates under any framing. (§5, §14)

### OCC / conflict

- A mutation with a stale `expected_version` returns `STATE_CONFLICT` and does not write.
- A mutation with the right version but wrong `expected_status` is rejected. (§7)
- An illegal state-machine transition is rejected even when the version matches — the
  contract's `DELIVERED → PENDING` case. (§7)
- **`STATE_CONFLICT` is never retried by infrastructure.** Assert the conflict surfaces to the
  caller; assert no retry wrapper exists on the path. (§12 rule 9)
- Transaction groups are all-or-nothing with no partial state visible. (§7)
- Unresolvable authoritative disagreement returns `CONFLICT`, never a guess. (§6, §12 rule 4)
- From `CONFLICT`, only the policy's `RESOLVE_CONFLICT` operation is permitted. (§3)

### Idempotency

- Replaying one `mutation_id` three times produces one transition, not three. (§7)
- Counter/accumulator idempotency attaches to the logical command, not the HTTP request. (§7)

### Temporal

- Valid time and system time are independently queryable — both "what did we believe on X"
  and "what is now believed true on X" return correct, different answers. (§4)
- A late-arriving claim with a past `valid_from` re-resolves affected slots and may advance
  `state_version` **with no agent mutation**. (§2, §4)
- Prior decision records are unchanged by that re-resolution. (§4, §12 rule 7)
- Historical claims entering context carry `status`, `valid_from`, `valid_until`, `source`,
  `scope`. (§8)

### Deletion / lineage

- Deleting one of two supporting evidence records leaves the claim active; deleting the sole
  support invalidates it. (§10)
- An invalidated object is **excluded from retrieval immediately**, never served stale
  pending recomputation. (§10, §12 rule 8)
- A worker holding a stale `scope_generation` is rejected at commit. (§10)
- `CLEAR` does not automatically yield `EXPLICIT_NONE`; the resulting status follows policy.
  (§10)

### Projection / freshness

- A projection watermark never advances across an unprocessed gap under concurrent workers.
  (§8) — the highest-value test in this section.
- `state_version` and `source_position` are never compared. (§12 rule 1) Enforceable by type,
  not only by test.
- Projections are rebuildable: dropping and replaying reproduces identical slot values. (§2,
  §14)
- A stale projection value does not override authoritative current state. (§8)

### Policy versioning

- A claim resolves under the policy version it was accepted with. (§10)
- Policy migration produces `SUPERSEDED_BY_POLICY` + `ACTIVE` and never both resolution-active
  — i.e. migration does not manufacture a `CONFLICT`. (§10)
- A breaking change yields `REVALIDATION_REQUIRED`, excluded from authoritative resolution
  absent explicit grandfathering. (§10)

### Async / outbox

- Every async pipeline's write goes through the mutation contract; **no worker has a direct
  authoritative write path.** (§9, §12 rule 5)
- The outbox row commits in the same transaction as the state change.
- An async candidate with `extraction_confidence = 0.99` still cannot establish a predicate
  whose authority domain excludes its source. (§5)

### LLM boundary

- Raw vector text never reaches context unvalidated. (§8)
- Narrative Memory reaching context is labelled non-assertive and cannot establish current
  state, override a claim, or act as authorization evidence. (§1)
- Unauthorized memory never reaches the LLM under any retrieval path.
- A prompt-injection attempt cannot escalate to a security-predicate mutation. (§13
  Example 12)

### Migration

- Shadow-compare: resolved target slot values match the legacy store for a full cycle before
  read cutover.
- At no point do two writers hold authoritative truth for the same slot.
- Rollback restores the legacy read path with no data loss.

## 28. Rollout / Compatibility Strategy

- **Dual-read, single-write.** Reads may be served from legacy and target simultaneously for
  comparison; **authoritative writes go to exactly one store at any moment**. This is the
  single most important rollout rule and follows directly from OCC: two independently-versioned
  writers is the condition the contract exists to prevent.
- **Per-store, per-writer cutover** — never per-repository. `agent_datastores` alone has three
  writers that must move separately (§18).
- **Shadow mode first.** Run the target write path in parallel, discard its output, compare.
- **Feature-gate per predicate, not globally.** The registry is per-predicate, so migration
  granularity should match it.
- **Compatibility readers** for legacy shapes — the pattern `olbrain-shared`'s `get_workflow()`
  already uses for the inline-JSON fallback, whose docstring notes it "is expected to go away
  once the one-time migration script has run in prod."
- **No zero-downtime claim.** Not established anywhere in the source material; §23's re-keying
  in particular cannot be done transparently.

`IMPLEMENTATION QUESTION` — whether the Memory Gateway fronts Studio/Noesis session reads
during rollout or those clients keep direct Firestore reads under corrected rules. This
determines whether Phase 7 is a client migration or a rules fix.

## 29. Open Questions

### Governance — blocks implementation, needs a named owner (§16)

| ID | Question | Owner (as documented) |
|---|---|---|
| G1 | Capability revocation TTL | Security — unconfirmed |
| G2 | Policy compatibility window | Architecture — unconfirmed |
| G3 | External predicate freshness SLAs | "Domain owner per predicate" — **a role, not a named owner; ownership itself unresolved** |
| G4 | Derived-object recomputation SLA | Operations + Legal — Open |
| G5 | Aggregate retention / deletion classification | Legal / compliance / data governance — Open |
| G6 | Online authorization vs. cached capability | Security — Open |
| G7 | Nonce / replay-cache scope | Architecture — unconfirmed |
| G8 | Bulk-deletion retry / DLQ policy | Operations — Open |

### Architecture-level `OPEN DECISION`

| ID | Decision | Why it matters |
|---|---|---|
| A1 | Extract-mode migration: synthesize placeholder Evidence, or migrate as un-provenanced Memory? | Lossless migration is impossible; the supporting Evidence does not exist (§18) |
| A2 | Replacement construction for `person_hash` | Unsalted SHA-256 over an enumerable domain; any change breaks both keying schemes at once (§23) |
| A3 | Disposition of rows whose original `user_key` is unrecoverable | Cannot be re-keyed at all (§23) |
| A4 | Whether person identity moves to an opaque surrogate id | Would decouple identity from the hash permanently (§23) |
| A5 | `source_offset` allocation giving gap-free monotonic positions per partition | §8's contiguous-watermark rule depends on it (§16) |
| A6 | Storage representation for `MAP` / `SET` per-key and per-element status | A single status column cannot express §11's required granularity |
| A7 | Authority domain name for the operational-correction lane | Registry population; freeze describes it but does not name it (§8) |
| A8 | Disposition of `MAX_PER_SESSION` / `MAX_PER_TABLE` eviction caps | Eviction-by-size has no target analog; Evidence is append-only (§18) |
| A9 | Patch 19 — recording the procedural-memory exclusion in the contract | The contract does not yet state its own boundary (freeze §9) |

### `IMPLEMENTATION QUESTION` — does not block architecture

| ID | Question |
|---|---|
| I1 | Complete or halt the in-flight `agent_user_memory → agent_datastores` migration? |
| I2 | Backfill `context_logs` history into the Evidence plane, or leave behind a compatibility reader? |
| I3 | Does the Gateway front Studio/Noesis session reads, or do corrected rules suffice? |
| I4 | Does session PII move into the identity layer as part of this migration? |
| I5 | Origin of the `is_enabled` MCP-config spelling — no confirmed writer in either repo |
| I6 | The `workflow_definitions` one-time migration script, referenced in code, never located |
| I7 | `workflow_items` org-binding and Pydantic model — no `WorkflowItem` model found |
| I8 | `scripts/merge_organizations.py` semantics |
| I9 | Tenant routing between the shared Firebase project and `clix-capital-prod` |
| I10 | Read call site for `agent_sessions.summary` not pinned to a line |
| I11 | Reachability of the no-settings `create_agent()` path using the legacy config service |

`IMPLEMENTATION QUESTION` items I5 and I6 are unaccounted-for artifacts, **not** governance
gates. They are listed separately here deliberately: conflating them with the §16 rows dilutes
the gate that actually blocks work.

## 30. Implementation Order

Dependency-ordered, derived from the contract's own ordering and from what the repository
evidence shows is safe to touch first.

| # | Step | Depends on | Gated by |
|---|---|---|---|
| 1 | Close or formally defer §16 rows with named owners | — | G1–G8 |
| 2 | Author the first Predicate Policies (content) | Domain owners | G3 for external predicates |
| 3 | Policy registry (immutable, versioned) | 2 | — |
| 4 | Evidence plane with contiguous per-scope positions | 3 | A5 |
| 5 | Transactional outbox + SKIP LOCKED workers | 4 | G8 for rejection handling |
| 6 | Claim model + lineage relations | 3, 4 | — |
| 7 | Mutation contract — OCC, `expected_status`, `STATE_CONFLICT` | 6 | — |
| 8 | StateSlot resolution (§6 nine steps) + §11 result contract | 6, 7 | A6 |
| 9 | Memory Gateway — typed capabilities, read/write paths | 8 | G1, G6 for caching |
| 10 | Authorization + RLS beneath the Gateway | 9 | — |
| 11 | Memory + Narrative Memory stores | 9 | G5 for retention classes |
| 12 | **First bounded migration** — operator datastore entries (writer 3) | 9, 10 | — |
| 13 | Validate: shadow-compare, then cut reads over | 12 | — |
| 14 | Scope generations + deletion/invalidation cascade | 8, 11 | G4, G5, G8 |
| 15 | Async pipelines onto the crossing rule, one at a time | 9, 13 | A1 for extract-mode |
| 16 | Sessions/messages, workflow and research state slots | 15 | I3 |
| 17 | DCI watermark; retire legacy embeddings and config service | 16 | — |

**Why step 12 is the first migration:** `agent_datastores` is already fully denied to all
clients with a passing rules test, so no client read path breaks during cutover — the only
PII-bearing store that is *fully denied* and test-covered (`agent_user_memory` is also
correctly protected, but by an org-scoped read gate, so clients do read it). Writer 3 is
authenticated,
audited, low-volume, and maps cleanly to a Claim with operator authority. It exercises the
entire stack end to end at the lowest available risk.

**Steps 1 and 2 have different owners and can run in parallel with each other**, but neither
is a coding task, and step 3 cannot sensibly start before step 2 has produced at least one
real policy.

## 31. Source Traceability

### Normative

| Claim area | Source |
|---|---|
| Five object classes, non-merger | `architecture-contract.md` §1 |
| StateSlot shape, scope, no multi-scope resolution, `state_version` semantics | §2 |
| Predicate Policy structure, cardinality, freshness contract, status-gated operations | §3 |
| Four resolution statuses, two temporal axes, retroactive claims | §4 |
| Predicate-specific authority; five separate measures; diminishing support | §5 |
| Nine-step resolution; authorization at step 9; `CONFLICT` never silently resolved | §6 |
| `MutateState`, OCC, `STATE_CONFLICT`, transaction groups, idempotency, causal ordering | §7 |
| `source_position`, contiguous watermark, typed query capabilities, temporal labels | §8 |
| Sync/async split; the crossing rule | §9 |
| Deletion semantics, scope generations, policy migration, aggregate governance | §10 |
| State engine result contract; granularity by cardinality | §11 |
| Ten inviolable rules | §12 |
| Worked examples (entity resolution, injection, deletion races) | §13 Examples 3, 4, 11, 12, 13, 17, 20 |
| Authority matrix; architecture decision matrix (MVP storage, RLS, rejections) | §14 |
| Final normative ordering; nine control planes | §15 |
| Eight unresolved governance parameters | §16 |

### Investigation artifacts

| Area | Source |
|---|---|
| Semantic scope freeze; procedural memory out of scope; Patch 19 deferral | `investigation/architecture-freeze.md` |
| Five pre-explorer decisions, incl. `LearnedOverride`→Claim | `investigation/architecture-decisions.md` |
| Current→target mapping table; async-crossing gap | `investigation/reconciliation.md` §4 |
| Per-store current-state map; Security Findings A–H; migration status | `investigation/store-inventory.md` |
| Per-repository evidence with file:line citations | `investigation/repo-notes/*.md` (10 files) |
| Senior's original production map | `artifacts/repo-and-soul-map.md` |
| Senior corrections: in-flight memory path, legacy config, privacy breadth, soul scope | `artifacts/senior-feedback.md` |
| Original Firestore/storage review | `artifacts/current-storage-review.md` |

### Read directly from repository source during this session

| Claim | Repository / file | HEAD |
|---|---|---|
| `person_hash` is unsalted `sha256(strip().lower())[:32]`; docstring confirms it is shared with `memory_doc_id` | `olbrain-shared` `src/olbrain_shared/agent/datastore/columns.py` | `a837b95` |
| Extract writer targets `agent_datastores/{agent}/tables/{table}/entries/{person_hash}` | `olbrain-agent-runtime` `services/extract_entry_writer.py` | `b2401a0` |
| `ContextFact` carries `status`/`t_valid`/`t_invalid`/`superseded_by`; invalidate-don't-delete | `olbrain-agent-engine` `alchemist/context/facts.py` | `8720720` |

### Repository HEADs at spec time — all verified clean

`olbrain-agent-runtime` `b2401a0` · `olbrain-agent-engine` `8720720` ·
`olbrain-research-design` `d044fce` · `olbrain-research-runtime` `d1caecd` ·
`olbrain-workflow-runtime` `5d48437` · `olbrain-knowledge-vault` `6d76083` ·
`olbrain-shared` `a837b95` · `olbrain-studio` `252f7887` ·
`olbrain-studio-backend` `6ada46a` · `olbrain-agent-design` `bbc85c8`

### Line-number policy

Where this document cites a symbol or file it reflects the investigation's own verified
evidence or a direct read during this session. Line numbers are **not** reproduced in this
specification — they drift. `investigation/repo-notes/*.md` holds the file:line citations as
captured at the HEADs above.

---

**No repository under `repos/` was modified to produce this document.**
`artifacts/architecture-contract.md`, `artifacts/state-semantics-explorer.html` and every
other artifact under `artifacts/` remain unchanged.
