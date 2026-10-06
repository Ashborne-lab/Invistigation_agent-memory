# Owner Decision Request: Agent Execution Memory Visibility v1

**Date:** 2026-10-05.

**Status:** **[OWNER DECISION REQUIRED].** Nothing has been sent; no channel or person is assumed.

**Recorded owner:** **Security, with Product.** This is the role recorded in `target-architecture-decision-closure-v1.md` for "Grant model for TENANT, AGENT and SESSION reads, including commitment cross-agent visibility and Agent Knowledge readers" (item 5, S-3 / T-1 / T-5 rows). No named individual is recorded.

**Analysis:** `agent-execution-memory-scope-v1.md`.

---

## Decision required

> Within one tenant, when agent A records execution memory while serving customer X (execution episodes in X's partition), **which agent principals may read it**? Is an agent-private execution layer required?

## Evidence

- **[CONTRACT §1]** Evidence includes "a trusted tool observation, a system observation, an agent decision". Narrative Memory covers "the context surrounding a decision" and is non-assertive. Execution memory therefore needs no new object class (analysis §3).
- **[CONTRACT §2]** "Security visibility is determined by authorization grants, never by automatic scope inheritance."
- **[OLBRAIN-PROVEN]** Only `(CUSTOMER, subject)` read grants exist (Gateway `may_read`, signed handles, C-4). AGENT and SESSION read grants do not exist (decision closure S-3).
- **[OLBRAIN-PROVEN]** The same open question already exists for commitments: T-1(i), "may a different agent of the same tenant read a commitment made by agent A to this person?"
- **[OLBRAIN-PROVEN, Jay]** J1/J2: one person is recognised across an org's agents, never across orgs.
- **[OLBRAIN-PROVEN]** Customer erasure covers whatever is stored in the customer's partition (journal §F). No erasure path exists for customer content stored in agent partitions (deletion generations for AGENT, RESOURCE and WORKSPACE "still have to be added", decision closure S-3).
- **[MEMORI, evidence only]** Memori shares facts across all agents (processes) of an entity and keeps conversations per process (`memori-agent-memory-gap-analysis-v1.md` §6).

## Options

| # | Option | Visibility |
|---|---|---|
| **1** | **Customer-shared** (Model E + A) | Any agent with a `(CUSTOMER, X)` grant reads X's execution episodes |
| 2 | **Agent-private by default** (Model E + B visibility, stored in X's partition) | Only agent A (per (agent, subject)) reads them |
| 3 | **Layered** (Model E + C) | Customer-shared by default; record classes or agents declared private by policy are readable only by the originating agent |
| 4 | **Session-only unless promoted** (Model E + D) | Visible only within the originating session; promotion to customer-shared by an explicit rule |

## Recommendation

**Option 1.** It is the only option that needs no new authorization capability: existing signed handles and `(CUSTOMER, subject)` grants suffice. It also:
- keeps erasure complete (storage in the customer partition);
- matches J1/J2;
- supports collaborating agents.

**Take Option 3 instead** if Product requires specialised agents whose execution must not reach other agents serving the same customer. That requires the AGENT / (agent, subject) grant model the owner already holds.

**Answer this together with T-1(i)**, so that commitments and execution memory follow one cross-agent rule.

## Consequences

| | 1 Customer-shared | 2 Agent-private | 3 Layered | 4 Session-only |
|---|---|---|---|---|
| Security | No new capability | New (agent, subject) read restriction | New restriction for the private layer | New SESSION grants plus a promotion rule |
| Privacy | A specialised agent's execution is visible to other agents for that customer | Strongest isolation between agents | Isolation where declared | Strong, but short-lived |
| Retrieval | One pool per customer | A per-agent pool; no collaboration | Two pools; the policy decides | Per session; little cross-session value |
| Storage | Customer partition | Customer partition (visibility only) | Customer partition | Customer partition |
| Replay | Unchanged (A1) | Unchanged | Unchanged | Unchanged |
| Erasure | Complete via the customer partition | Complete | Complete | Complete |
| Multi-agent | Collaboration works | Collaboration blocked | Configurable | Blocked across sessions |
| Complexity | Lowest | Medium (new grant check) | Highest (policy plus grant) | Medium (grant plus promotion) |

**Out of scope for every option:** executions with no customer subject (agent, resource or workspace partitions), and procedural memory (D7).

## Exact approval request

Approve one of:

1. **Option 1:** execution memory recorded for customer X is readable by every agent principal holding a `(CUSTOMER, X)` grant in the same tenant. *(recommended)*
2. **Option 2:** readable only by the originating agent for that customer.
3. **Option 3:** customer-shared by default, with policy-declared agent-private classes readable only by the originating agent.
4. **Option 4:** session-only unless promoted by an approved rule.

**State whether the same rule applies to commitments (T-1(i)).**
