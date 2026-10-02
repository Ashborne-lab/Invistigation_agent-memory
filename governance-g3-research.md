# G3 — Predicate freshness SLAs (research)

Date: 2026-09-26. Read-only. **No freshness value is invented here.**

Commits: `olbrain-agent-engine e43654e` · `olbrain-agent-runtime 8df0e02` ·
`olbrain-shared 8a0f0b5` · `olbrain-finance-engine 109a838` · `olbrain-workflow-runtime 1978f4a`.

---

## 1. The question and its owners

`[CONTRACT]` §16 row 3: per externally-owned predicate — `max_staleness`, `stale_read_policy`,
`stale_write_policy`. `freshness_contract` is required on every policy for an externally-owned
predicate; without it `freshness_status` cannot be computed and a stale value cannot be
distinguished from a fresh one, which §3 forbids presenting as unqualified operational truth.

R2's answer (recorded in `senior-review-reconciliation.md`) names the owners by domain:

| Domain | Owner per R2 |
|---|---|
| memory / soul / person-attribute predicates | Shivam |
| finance predicates | the `olbrain-finance-engine` owner |
| operational-correction predicates | the workflow-design owner |
| anything unmapped | assigned by Jay as it arises |

`[INFERENCE]` R2 unblocked *who decides*. It did not supply values, and this report does not.

---

## 2. Current implementation: none of the required machinery exists

`[CODE]` Across all thirteen repositories at their current commits, there is **no**
`freshness_contract`, `max_staleness`, `stale_read_policy`, `stale_write_policy`, or
`freshness_status`. A search for `freshness|stale` returns only cache-lifetime concepts:

| Hit | Location | What it actually is |
|---|---|---|
| `summary_freshness: Optional[timedelta]` | `agent-engine e43654e:alchemist/services/context_broker.py:185` | age of a conversation summary, for prompt assembly |
| *"CONFIG_CACHE_TTL bounds freshness"* | `agent-runtime 8df0e02:core/cs_packet_builder.py:731` | GCS config cache lifetime |
| *"a stale goal can never be SERVED from it"* | same, `:733` | a cache-correctness assertion |
| *"serving a stale `""` for the full TTL"* | `context_broker.py:139` | negative-cache avoidance |

`[INFERENCE]` **Every occurrence is cache freshness, not predicate freshness.** They answer "how
old is this copy?", never "is this value still operationally true?". The distinction is the whole
of G3: a cache can be refreshed unilaterally; an externally-owned predicate's staleness is a
property of the *source system*, which OLBrain does not poll and cannot refresh.

`[CODE]` There is also no Policy Registry, no `StateSlot`, and no predicate table. G3's values have
nothing to attach to.

---

## 3. Where freshness semantics are already implied

`[INFERENCE]` Three places imply a freshness contract without naming one. These are the candidate
first predicates, and they are the concrete material a domain owner would need.

**(a) External `data_query` results — agent-runtime.** The `data_query` capability opens
connections to customer/third-party databases using credentials from frozen design-time config
(`storage-reality-audit.md` §4.2, Q-S4). A value read from a customer's own database is the
paradigm externally-owned predicate: OLBrain neither owns it nor is notified when it changes.
`[CODE]` No staleness is recorded on the result today; it is read and used within the turn.

**(b) Finance / P&L figures — `olbrain-finance-engine 109a838`.** Newly in scope this pass. The
repository is organised under `organizations/{org}/...` with `finance_rm` (raw material),
`pnl_inputs`, `pnl_projections`, `pnl_statements`, `finance_model`, `versions` and `runs`.
`[CODE]` It carries explicit versioning (`versions`, 59 references) and reconciliation
(`app/finance_reconcile.py`). `[INFERENCE]` A P&L figure has an obvious period-bounded validity —
a projection for a closed month is not "stale", it is historical; a projection for an open month
goes stale on every new actual. **This is the domain where `max_staleness` is most likely to be a
real business quantity rather than an engineering guess**, and R2 names its owner.

**(c) MCP tool results — `olbrain-mcp-deployer 0efd05f`.** Newly in scope. It holds
`oauth_connections`, `oauth_tokens` and `mcp_tool_executions`. `[INFERENCE]` A value fetched
through an OAuth-connected third party is externally owned by construction, and OAuth tokens
themselves have expiry semantics that are a freshness contract in miniature. R2 maps no owner for
this domain — it falls under *"anything unmapped is assigned by Jay"*.

---

## 4. Which values code can supply, and which it cannot

`[INFERENCE]`

**Code can supply, without a domain owner:**
- The *observation timestamp* of any externally-sourced value — when OLBrain read it.
- The *source identity* — which external system, which connection, which run.
- The *mechanical* `freshness_status` computation, once a `max_staleness` exists, because that is
  arithmetic on the observation timestamp.
- Whether a value is externally owned at all — derivable from which writer produced it.

**Code cannot supply, and must come from the named owner:**
- `max_staleness` — a judgement about how long the value remains operationally true, which depends
  on the business meaning, not the storage.
- `stale_read_policy` — serve-with-qualification, refuse, or refresh-then-serve. `[CONTRACT]` §3
  forbids presenting a stale value as unqualified truth, which **eliminates "serve silently"** but
  leaves the remaining choices open.
- `stale_write_policy` — whether a write may be accepted against a stale read.

`[INFERENCE]` **The asymmetry is useful:** roughly half of G3's per-predicate burden is mechanical
and can be specified before any owner responds. Only `max_staleness` and the two policies are
genuinely owner-decisions, and they are three values per predicate, not a design exercise.

---

## 5. Does the core PostgreSQL layer actually need freshness columns?

`[INFERENCE]` This is the question most relevant to the PostgreSQL gate, and the evidence suggests
**no — not in the core layer.**

Reasons:

1. `[CONTRACT]` `freshness_contract` is required *on the policy*, not on the value.
   `max_staleness` / `stale_read_policy` / `stale_write_policy` are **Policy Registry** columns.
   What a value row needs is only an observation timestamp and a source reference — both of which
   are provenance, which the design needs regardless of G3.
2. `freshness_status` is **derived** — `[CONTRACT]` it is a `StateSlot` property computed at
   resolution time from the observation timestamp and the policy. Materialising it would violate
   the contract's own rule that Current State is a projection, not a second source of truth.
3. `[CODE]` No predicate today is externally owned in the contract's sense, because no predicate
   exists. The first externally-owned predicate is prospective.

`[INFERENCE]` **Consequence for the PostgreSQL gate:** G3 does not appear to block core schema
design. It blocks the *Policy Registry* schema and the resolver's freshness path. If that
separation holds, G3 should be removed from the list of PostgreSQL blockers — but this is an
inference from the contract's wording, **not a decision**, and it should be checked against the
contract owner's reading before anyone relies on it.

---

## 6. What each named owner would actually be asked

`[INFERENCE]` Framed so the request is three values per predicate, not an open design question.

| Owner | Predicate family | The concrete ask |
|---|---|---|
| Shivam | memory / soul / person-attribute | For person attributes sourced from an external CRM or customer DB: how long does a value remain usable, and may the agent state it without qualification once past that? |
| finance-engine owner | finance | For each P&L figure class (actual, projection, driver): the validity window, and whether a stale figure may be read or written against. Versioning already exists to anchor this. |
| workflow-design owner | operational-correction | Whether learned overrides have a validity horizon — see `d5-authority-research.md`, which finds a `suggested → active → retired` machine but no expiry. |
| Jay (unmapped) | MCP / third-party tool results, `data_query` | Who owns these at all. R2 maps no domain for them. |

---

## 7. Blockers and non-blockers

`[INFERENCE]`

- **Blocked by G3:** any Predicate Policy for an externally-owned predicate; `freshness_status`;
  the resolver's stale path.
- **Not blocked:** internal predicates (the dashboard already records this); the core value schema
  (§5); provenance capture, which is needed anyway and supplies half of G3's inputs.
- **Newly relevant:** `olbrain-finance-engine` and `olbrain-mcp-deployer` entering scope adds two
  concrete externally-owned domains. `[INFERENCE]` G3 was previously abstract; it now has real
  candidate predicates, which makes it answerable rather than theoretical.

---

## 8. Limitations

1. No predicate, policy or `StateSlot` exists in code; every statement about what G3 governs is
   `[CONTRACT]` + `[INFERENCE]`, not `[CODE]`.
2. `[UNMEASURED]` Whether `data_query`, finance figures or MCP results are *in fact* the first
   externally-owned predicates depends on which predicates get authored first — a design choice
   nobody has made.
3. §5's conclusion that G3 does not block core schema design is an inference from contract wording
   and **requires confirmation by the contract owner** before being relied on.
4. `olbrain-finance-engine` and `olbrain-mcp-deployer` were inventoried at collection level only
   this pass; their freshness semantics were not traced in depth.
