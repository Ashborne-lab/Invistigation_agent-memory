# Target Architecture: Decision Closure v1

**Date:** 2026-10-03.
**Scope:** one decision pass over every open question raised while building the prototype components. This is not an audit. **No component was built, no normative document was modified, and no production value was invented.**

**Evidence base:**
- **Prototype:** 648/648 tests across six components:

| Component | Document |
|---|---|
| Predicate Policy Registry | `predicate-policy-registry-v1.md` |
| Evidence → Claim Gate | `memory-claim-gate-v1.md` |
| Claim Commit | `memory-claim-commit-v1.md` |
| Current State | `memory-current-state-v1.md` |
| Typed Retrieval | `memory-typed-retrieval-v1.md` |
| Context Compiler | `memory-context-compiler-v1.md` |

- **Contract:** `artifacts/architecture-contract.md`, re-read for §1 (Narrative Memory), §2 (`state_version`, scope), §7, §8 and §10.
- **Spec:** `memory-implementation-spec.md`, for §10.4 and §13 and the commitment rows.

**Classification legend:**

| Code | Meaning |
|---|---|
| ENG | Engineering-resolvable: decided here |
| GOV | Governance or owner decision |
| SEC | Security decision |
| PROD | Product decision |
| LEGAL | Legal / privacy decision |
| INFRA | Infrastructure decision |

A row can carry two classes: the engineering part is decided here, and the rest is escalated.

---

## 1. Executive decision map

**Coverage:** 25 questions were reviewed:
- C-1…C-6, B-1…B-4, S-1…S-3, T-1…T-5, X-1…X-4 (as asked);
- the four Claim-Gate questions G-1…G-4, which were also still open.

**Resolved by engineering here (12):**
- C-3, C-4 (semantics), S-1, S-2, S-3 (scope semantics), X-1, X-3, G-1, G-2, G-4;
- the engineering parts of C-1, C-2, C-5, T-1, T-2, T-3, T-4, X-2 and X-4.

**Already settled by the contract or a later component, so obsolete as questions (5):**
- **C-3:** contract §7 idempotency;
- **S-1:** contract §2 says "need not advance";
- **X-3:** contract §8 says "the tool schema is the intent classifier";
- **T-2:** contract §1 says Narrative Memory MUST carry a `security_class`, so only its derivation and default remain;
- **G-4:** merged into C-5.

**Escalations that remain:**

| Decision | Owner |
|---|---|
| B-1 predicate ownership | Governance |
| B-2 staleness values | Domain owners |
| B-3 retention catalogue | Legal |
| B-4 operator vs user authority | Domain owners, via B-1 |
| C-1 key custody and rotation | Security / Infra |
| C-2 reversal of PENDING_ERASURE, and re-activation of QUARANTINED | Legal / identity owner |
| C-5 storage technology and retention | Infra / Legal |
| C-6 conflict workflow | Product |
| S-3 / T-1 / T-5 read grants for non-CUSTOMER scopes and cross-agent visibility | Security / Product |
| T-2 default security floor for narrative | Security |
| T-4 whether an audit-history mode exists, and who may use it | Legal / Security |
| T-5 the value of k | Legal |
| X-2 per-task mandatory and degraded choices | Product |
| X-4 injection monitoring and response | Security |
| G-3 temporal admission horizons | Domain owners |

**Five cross-component contradictions** were found (§8). All five are engineering fixes.

**What blocks the next step (durable storage plus the Gateway skeleton).** Only these:
- **INFRA:** C-5 storage choice;
- **SEC:** C-1 key custody;
- **LEGAL:** B-3 catalogue interface and C-2 erasure reversal;
- **SEC:** grants for any scope beyond CUSTOMER, needed only if the next step includes such scopes.

Everything else can proceed against TEST_ONLY policies (§10).

---

## 2. Engineering decisions resolved

| ID | Class | Current behaviour | Options | Recommended direction | Why | Blocks what | Owner |
|---|---|---|---|---|---|---|---|
| **S-1** state-version signature | ENG (spec wording: spec owner) | Signature = status, value, SET (value, status) pairs, set of conflicting **values**. Claim ids, source and freshness are excluded | (a) include winner ids, as the spec's §13 wording "winners or conflict set" can be read; (b) values only, as the prototype does | **(b) values only.** Also exclude source and authority-domain changes when the value is unchanged. Amend spec §13 to say "winner *values*" | Contract §2: "committing a Claim that does not change the resolved slot **need not** advance `state_version`". OCC exists to protect a decision taken on a read value. Under (a), every corroborating claim spuriously fails concurrent agent writes with STATE_CONFLICT. Write-time rules (stale-write, authority) are evaluated against the slot at commit, so they don't need the version to move | Durable head schema; OCC tests | Engineering. Spec owner to amend §13's wording |
| **S-2** scheduled boundaries | ENG | Evaluation points are journal entries plus `now`. A boundary is counted at the next point. Two boundaries between points count once | (a) evaluate only at commits (scheduled changes invisible to OCC); (b) evaluate at commits and at **each boundary instant**; (c) as now: commits plus `now` | **(b).** `state_version` is a pure function of (journal, boundary instants ≤ now): every `valid_from` / `valid_until` instant is an evaluation point, merged in time order with journal entries. **Reads never create evaluation points.** The durable head keeps `next_boundary_at`; any access first processes, in order, every boundary ≤ now (lazy catch-up), and a scheduler is optional. An agent that read before a boundary and writes after it gets STATE_CONFLICT | Contract §2: `state_version` "MAY advance with no agent mutation… when another authoritative event changes the resolved slot", and agents "MUST treat OCC failure as normal". Under (c) a persisted live head would count differently depending on **when it was read**, which breaks rebuild == live once the head is stored. The prototype only avoids that because it never persists a head | Durable head design. **Small prototype change:** make each boundary its own evaluation point | Engineering |
| **S-3** scope model | ENG (semantics); SEC (grants) | CUSTOMER only. Retrieval names `ORG`/`AGENT`/`SESSION` as unsupported | (a) infer scope from data; (b) **policy declares scope** | Use the **contract vocabulary**: GLOBAL, TENANT, WORKSPACE, CUSTOMER, SESSION, AGENT, RESOURCE. "ORG" is not contract vocabulary; it becomes TENANT (§8 C-A). Each policy declares exactly one `state_scope_type` for its mutable slot (§2: one authoritative scope). A claim's scope id is **assigned at commit** from the ingress context (TENANT ← org, CUSTOMER ← subject, SESSION ← evidence session, AGENT ← agent id), never inferred from the value. Cross-scope values are explicit **derived predicates** with version vectors (§2), never mutable. Deletion generations exist per scope class (§10), mapped from the Lane A fence epochs (org → TENANT, subject → CUSTOMER, session → SESSION). WORKSPACE, AGENT and RESOURCE generations still have to be added. **Access is separate**: grants are per (principal, scope id); scope hierarchy never implies access (§2, §10) | The contract already defines all of this. The prototype's single-scope behaviour is a strict subset | Any non-CUSTOMER predicate; T-1; T-5 | Engineering (semantics). **Security: the grant model for TENANT, AGENT and SESSION reads** |
| **C-3** mutation-id reuse | ENG (**obsolete: decided by the contract**) | Recorded STATE_CONFLICT is returned for the same id forever | (a) allow deliberate reuse after a re-read; (b) single-use | **(b) single-use.** After a re-read the caller mints a **new** `mutation_id` | Contract §7: "Every mutation carries a unique `mutation_id`. Replaying it produces the same result." Reuse would let a retried old command become a new one, which is exactly what the contract forbids | — | Contract (settled) |
| **C-4** transaction groups | ENG (semantics); INFRA (cross-partition) | Not modelled | Minimum semantics only | A group = {`transaction_group_id`, `mutation_ids`, actor, `causal_parent`} (§7). It is **idempotent on the group id**; member ids are unique and unusable outside the group. Every member passes the gate and OCC **against one snapshot**. Any member failure → the whole group returns STATE_CONFLICT or REJECT, naming the failing member, and **nothing** commits. The commit is **one journal entry**, so rebuild sees all or nothing. The projection treats the group as **one evaluation point**, so no intermediate state is visible. **Start with groups within one subject** (one journal partition); cross-partition groups are an INFRA decision | Contract §7 text; the projection's evaluation-point model (S-2) | Multi-slot mutations | Engineering; INFRA for cross-partition |
| **G-1** evidence during CONFLICT | ENG (contradiction fix) | The gate status-gates LLM-extracted SET proposals, so a user statement made during a conflict is rejected and never recorded | (a) keep rejecting; (b) **separate ASSERT (evidence) from state commands** | **(b).** LLM-extracted assertions are claims (evidence), recorded regardless of slot status; resolution decides. Status gating (§3 `allowed_operations_by_status`) applies to **typed state commands** (writer ≠ `llm_extractor`), the same split the commit layer already uses for `expected_version` | Contract §3 gates *operations*. The spec's race A commits LLM claims without `expected_version`. Rejecting evidence can discard the very statement that resolves the conflict. See §8 C-D | Gate behaviour | Engineering |
| **G-2** conflict-flag granularity | ENG | Advisory gate flag at source-class level | (a) member level; (b) drop the flag | Keep it **advisory**. Make it member-level by adding the winner's `source_member_id` to `StateSlot` provenance. Resolution stays authoritative | Cheap; avoids false negatives | — | Engineering |
| **G-4** idempotency ledger durability | (**merged into C-5**) | — | — | — | — | — | — |
| **X-1** budget unit | ENG | Characters | Hard-code a tokenizer; or an **injected measure** | `Budget(limit, measure_id)` with `measure(text) -> int` injected. The compiler only compares measured sizes. The manifest records `measure_id` and its version. A character measure stays the test default; a tokenizer-aware measure plugs in later | Determinism is preserved per measure; no model coupling | Compiler production use | Engineering |
| **X-3** ambiguous-request default | ENG (**obsolete: decided by the contract**) | Profiles make intent explicit | Gateway, compiler, retrieval, or schema | **The tool / request schema**, mapped deterministically by the gateway router. An entry point that does not declare an intent maps to `get_current_state`. The compiler and retrieval never infer intent | Contract §8: "the tool schema is the intent classifier… a separate stochastic intent classifier MUST NOT be inserted" and "MUST default toward current-state semantics" | Gateway design | Engineering |

**Engineering parts of mixed questions (decided here; the remainder is escalated in §3–§7):**
- **C-1:** the logical identity is
  `claim_id = ID_v(subject_key, {subject, predicate_key, canonical value, sorted anchor evidence ids, source_member_id, asserted interval, derivation})`.
  - It is versioned by an `id_version` prefix.
  - It is computed in one function, keyed per subject, as in Lane A, so crypto-shredding the subject key unlinks leftover ids.
  - This extends spec §7.2's evidence|key|value to avoid collisions; the spec owner should amend it.
  - The hash algorithm and key custody are configuration (SEC / INFRA).
- **C-2:** the lifecycle state machine is in §2a below.
- **C-5:** the semantic requirements of the journal:
  - append-only, with a total order per subject partition;
  - **durable before acknowledgement**;
  - immutable entries;
  - carries the **recorded outcomes** (proposal, decision, claim content, retraction and lifecycle records), so replay never re-decides;
  - sufficient for full rebuild;
  - erasure-compatible: claim **content** must be removable or unreadable (crypto-shred, via C-1) while the structural sequence survives for ordering;
  - **external-sync success events must be journaled** (§8 C-C).
- **T-1, T-2, T-3, T-4, X-2, X-4:** see their rows below.

### 2a. Claim lifecycle state machine (C-2, engineering part)

This is derived from existing semantics: Lane A, contract §10 and the commit layer.

| From | To | Cause | Source of the rule |
|---|---|---|---|
| ACTIVE | RETRACTED | Recorded retraction (`no_longer_true` / `never_true`) | LA-9 |
| RETRACTED(`no_longer_true`) | RETRACTED(`never_true`) or an earlier end | Convergence | LA-9 |
| ACTIVE | SUPERSEDED | Persisted-supersession mode only | Spec §8.1 |
| ACTIVE, RETRACTED, SUPERSEDED, QUARANTINED | INVALIDATED | Sole supporting evidence deleted, or re-extraction lineage | Contract §10; R-9 |
| ACTIVE | QUARANTINED | Recorded merge undone | E3 fence |
| ACTIVE | REVALIDATION_REQUIRED | Breaking policy change | **Contract §10, missing from the prototype** |
| REVALIDATION_REQUIRED | SUPERSEDED_BY_POLICY | Replacement accepted | **Contract §10, missing** |
| REVALIDATION_REQUIRED | ACTIVE | Only if the new policy declares grandfathering | Contract §10 |
| any non-terminal | PENDING_ERASURE | Erasure requested | R6b |
| PENDING_ERASURE | ERASED | Physical erasure | R6b |

**Terminal states:** INVALIDATED, SUPERSEDED_BY_POLICY, ERASED. New truth comes from **new** claims (Q17 recovery derives new claims; it does not reactivate old ones).

**Escalated (not decided here):**
- **PENDING_ERASURE → ACTIVE** (cancelling an erasure): LEGAL.
- **QUARANTINED → ACTIVE** (re-attributing after a merge is redone): identity owner (J5 merge policy).

**Consequence for the prototype:** `commit.lifecycle()` currently accepts any listed status. It should enforce this table, and `test_excluded_lifecycle_never_becomes_current_state` reactivates INVALIDATED, which would become illegal. That is one small change at the next step.

---

## 3. Owner and governance decisions required

| ID | Class | Current behaviour | Options | Recommended direction | Why | Blocks what | Owner |
|---|---|---|---|---|---|---|---|
| **B-1** policy ownership | GOV | Every policy is TEST_ONLY. The registry refuses TEST_ONLY policies in production mode | (a) one central architecture owner; (b) **per-authority-domain owners** (the contract's "domain owner per predicate") with central review; (c) per predicate | Needed to publish the first real policies: **a named owner per authority domain** (CUSTOMER_PREFERENCE, BILLING_SYSTEM, IDENTITY_SECURITY, ORDER, HR…), a central reviewer, and a version-bump rule (breaking vs non-breaking, which triggers C-2's REVALIDATION_REQUIRED). **The owner must supply every policy field that is a value, not a structure:** sources and ranks, writers, LLM mode, operations by status, the conflict resolver, temporal model, security class, retention class (B-3), freshness (B-2), map keys and transitions | The registry enforces structure. The values carry the authority | Every real policy | Architecture owner (R2) |
| **B-2** external freshness budgets | GOV (domain owners) + ENG | `max_staleness` and the read/write policies are TEST_ONLY. `last_sync` is a parameter | — | **Every predicate whose `authority_domain` is an external system** (billing, CRM, HR, identity, order) needs `freshness_source=external_sync`. Domain owners supply `max_staleness`, `stale_read_policy` and `stale_write_policy`, plus the **identity of the sync process** whose success counts. **ENG:** sync successes become journaled events (§8 C-C) | Contract §3 example (15-minute billing budget) | External-domain policies | Domain owners |
| **B-4** operator vs user authority | GOV (per domain) | Ranks per source per predicate; the prototype tests all three shapes | **Equal:** disagreement → CONFLICT, so a resolve workflow is needed (C-6), and truth is never silently chosen. **Operator higher:** corrections win, but operator error silently overrides self-report. **Operator lower:** customer self-report always wins, and operator corrections are ineffective | **Not a global decision.** The registry supports any shape per predicate, so each domain owner sets it in that predicate's `authority_rank` | The authority is predicate-specific (contract §5) | Person-attribute policies | Domain owners, via B-1 (D1(b)) |
| **G-3** temporal admission limits | GOV (per `temporal_model`) | Only non-empty intervals and no future evidence | — | Domain owners declare an optional max retro-dating and a max future horizon per predicate. Engineering adds two optional policy fields **only when** an owner supplies values | Contract defines semantics, not limits | — | Domain owners |
| **T-3** history label vocabulary | ENG + contract owner | CURRENT / IN_CONFLICT / ENDED / SUPERSEDED / NOT_SELECTED | — | **Normative** (contract-backed facts, stored or derived from lifecycle and time): SUPERSEDED, ENDED (retracted `no_longer_true` or expired), plus the contract's lifecycle statuses. **Presentation-only** (relations to *current* state, recomputed at read, never persisted): CURRENT, IN_CONFLICT, NOT_SELECTED | The contract's §8 example names only SUPERSEDED. The others depend on the current resolution | Retrieval and compiler labels | Contract owner to confirm the names |

---

## 4. Security decisions required

| ID | Class | Current behaviour | Options | Recommended direction | Why | Blocks what | Owner |
|---|---|---|---|---|---|---|---|
| **C-1** key custody (custody part) | SEC / INFRA | A per-subject key from a provider callable (test dict) | KMS-wrapped per-subject keys; HSM; envelope encryption; rotation cadence | Engineering requires: one key per subject, destroyable (crypto-shred), versioned so rotation does not change existing ids (`id_version`), and never exposed to retrieval | Erasure and unlinkability depend on it | Durable storage | Security |
| **S-3 / T-1 / T-5** read grants beyond CUSTOMER | SEC (+ PROD) | Only `(CUSTOMER, subject)` grants exist (`may_read`) | Per principal × scope id grants; role-based; agent-bound | The grant model for TENANT, AGENT and SESSION reads, and specifically: (i) may a different agent of the same tenant read a commitment made by agent A to this person (T-1)? (ii) who may read Agent Knowledge: the owning agent's runtime only, tenant operators, other agents (T-5)? | The contract separates scope from access (§2). The grants are policy | Non-CUSTOMER retrieval | Security, with Product for (i) |
| **T-2** narrative security floor | ENG + SEC | Episodes have no class (treated as standard) | — | **ENG:** the narrative object carries `security_class` and `retention_class` (contract §1). It is derived at summarisation as **the most restrictive class** of the predicates extracted from its evidence, and can never be downgraded later. **SEC:** the **default floor** for summaries with no extracted predicates (`standard` vs `sensitive`), and whether free-text classification is required | Contract §1 makes the field mandatory. Derivation matches the "most restrictive" convention used for consent (R2) | Narrative retrieval in production | Security (floor) |
| **X-4** injection in memory values | SEC + ENG | Sanitiser (English role prefixes, delimiters), bracket escape, quoting, header | Sanitisation; structural separation; model-level; detection; combination | **ENG (decided):** structural defences are primary. Memory is delivered as a **separate data channel** (for example structured tool-result data), never concatenated into system or developer text; labels are compiler-owned; values are quoted and escaped; **memory can never authorise a tool call or override policy** (contract §1: narrative "MUST NOT… be used as hidden authorization evidence"). Sanitisation is hygiene only. **SEC:** whether to add multilingual detection as a **monitoring signal** (never a gate), and the response playbook | Regexes cannot make arbitrary text safe in every language. Structure and capability limits do not depend on language | Gateway prompt assembly | Security (monitoring) |

---

## 5. Product decisions required

| ID | Class | Current behaviour | Options | Recommended direction | Why | Blocks what | Owner |
|---|---|---|---|---|---|---|---|
| **C-6** conflict → task | PROD (+ENG) | A CONFLICT is surfaced, and the declared RESOLVE_CONFLICT works | Auto-create a task; agent asks the user; operator queue; nothing | **ENG:** emit a deterministic, idempotent `slot_entered_conflict` event (keyed by slot and conflict value set) on the projection transition into CONFLICT, so a workflow *can* subscribe. **PROD:** whether and how a task is created, per domain | Contract §6: "the agent requests clarification or invokes the domain's conflict-resolution workflow". The workflow is product | — | Product |
| **X-2** mandatory and degraded context | ENG + PROD | Mandatory missing or over budget → fail closed | Fail closed; degrade with notice | **ENG:** the profile declares per item `MANDATORY` / `OPTIONAL` and `on_missing_mandatory ∈ {FAIL, DEGRADE_WITH_NOTICE}`. Degraded output carries an explicit `[UNAVAILABLE] predicate` line, and the manifest records it. **PROD:** which tasks choose which, and their mandatory predicates | Separates architecture behaviour from task policy | Production task profiles | Product |
| **T-1** commitment visibility | PROD + SEC | See §8 C-E | — | Covered in §4 (i) | — | — | Product / Security |

---

## 6. Legal / privacy decisions required

| ID | Class | Current behaviour | Options | Recommended direction | Why | Blocks what | Owner |
|---|---|---|---|---|---|---|---|
| **B-3** retention classes | LEGAL (+ENG interface) | `retention_class` is a required, free string; TEST_ONLY values are refused in production | — | **ENG interface:** a Legal-owned **RetentionClass catalogue** {`class_id`, version, rule (duration or event-based), erasure method, legal basis}. The registry validates `retention_class ∈ catalogue` at publication, and narrative and journal entries reference a class the same way. **LEGAL:** the classes and their rules. **No class or duration was invented** | G5 (parked) | Real policies; C-5 retention | Legal |
| **C-2 (part)** erasure reversal | LEGAL | Prototype allows any transition | Allow PENDING_ERASURE → ACTIVE within a window; never | Decide whether an erasure can be cancelled, and within what window | Erasure semantics carry legal exposure | The lifecycle table | Legal |
| **T-4** audit history | ENG + LEGAL/SEC | `never_true` claims and excluded statuses are hidden from history | One mode; **two modes** | **ENG:** keep user-facing history as it is (memory never shows `never_true` or excluded content). If needed, add a **separate typed capability** `search_audit_history`, never exposed to agents, with its own grant, that shows `never_true` and quarantined claims and **never** erased content. **LEGAL/SEC:** whether it is required, and who may use it | Compliance review needs differ from memory needs | — | Legal / Security |
| **T-5 (part)** Agent Knowledge `k` | LEGAL | `k` is a parameter (R-11) | — | The value of k, and whether quasi-identifier screening is sufficient | Already a recorded Lane A owner item | Agent Knowledge in production | Legal |

---

## 7. Infrastructure decisions deferred

| ID | Class | Current behaviour | Options | Recommended direction | Why | Blocks what | Owner |
|---|---|---|---|---|---|---|---|
| **C-5** journal storage | INFRA (+LEGAL retention) | In memory | PostgreSQL (per-partition sequence, `SERIALIZABLE`/advisory locks); Firestore (transaction plus a sequence document); a WORM log plus a PG index | Must meet the §2 semantic requirements (append-only, per-partition total order, durable-before-ack, recorded outcomes, crypto-shred compatible, sync events journaled). Choose by partition throughput and the deletion model. Retention comes from B-3 | Prior memory decisions favour hybrid PG by tier (A7). Not decided here | **Durable storage step** | Infrastructure |
| **C-4 (part)** cross-partition groups | INFRA | — | 2PC, a saga, or forbidding them | Forbid them at first (single-subject groups only) | Cross-subject atomicity requires distributed transactions | Multi-subject commands | Infrastructure |
| **S-2 (part)** boundary scheduler | INFRA | — | Lazy catch-up only; plus a scheduler | Lazy catch-up is required and sufficient for correctness. A scheduler is an optimisation for push notifications | — | — | Infrastructure |

---

## 8. Cross-component contradictions (all engineering fixes)

| # | Area | Contradiction | Fix (direction) |
|---|---|---|---|
| **C-A** | Scope vocabulary | Retrieval uses `ORG` / `AGENT` / `SESSION`. The contract's scopes are GLOBAL, TENANT, WORKSPACE, CUSTOMER, SESSION, AGENT and RESOURCE. **"ORG" does not exist**; the Lane A fence uses `org` / `subject` / `session` epochs | Rename to the contract vocabulary (ORG → TENANT, subject → CUSTOMER). Add WORKSPACE, AGENT and RESOURCE generations to the fence when those scopes ship (S-3) |
| **C-B** | Lifecycle and policy versioning | The prototype lacks REVALIDATION_REQUIRED and SUPERSEDED_BY_POLICY (contract §10). The projection resolves **claims committed under an older policy version with the current policy**, and the admission filter checks only sources and LLM mode. A breaking change (for example SINGLE → SET) therefore silently re-reads old claims instead of excluding them pending revalidation. `lifecycle()` also allows arbitrary transitions, including reactivating INVALIDATED | Add both statuses and the §2a transition table. Mark a policy version **breaking** at publication (the registry already reports `cardinality_changed`); claims under an older breaking version become REVALIDATION_REQUIRED and are excluded from resolution unless the new policy declares grandfathering |
| **C-C** | Freshness and rebuild | `last_sync` (external freshness) is a **caller-supplied parameter** to projection, retrieval and gate, not a journaled fact. Freshness, the stale-write gate and usage labels are therefore **not rebuildable from the journal**, which contradicts "Current State fully rebuildable". It is also a trust gap: a wrong `last_sync` changes the write gate | Journal external-sync success events (sync identity, predicate, time). Freshness derives from the journal; the parameter disappears |
| **C-D** | Gate vs commit (assertions vs commands) | The commit layer treats LLM assertions as evidence (no `expected_version`, spec race A). The gate applies **status gating** to the same LLM SET proposals, so evidence is rejected during CONFLICT (G-1) | G-1 direction: status gating and OCC apply to typed commands only. LLM assertions are always recorded as claims, and resolution decides |
| **C-E** | Commitment model | The spec (§5, §13 head `commitments: [claim_id…]`, `commitment.*` keys) models commitments as **claims**. The Lane A reviewed fix R-10 replaced them with an **evidence-backed event log** (`commitments.project`), which retrieval uses. The event model has **no subject, agent or tenant fields** (T-1) | Keep R-10, the reviewed fix for M-2: idempotent creation, read-time expiry, actor-authorised transitions. Add explicit `subject_id`, `agent_id` and tenant to `Event`. Scope is **CUSTOMER** (the person), with the agent as attribution. The spec owner should retire the head's `commitments: [claim_id…]` / `commitment.*` claim model. Cross-agent visibility is §4 (i) |

**Checked and consistent (no change needed):**
- **Authorization boundary:** one rule, `may_read`. The resolver and projection take no caller. Retrieval authorizes after resolution. The compiler only consumes the result.
- **Provenance:** references only, end to end.
- **Conflict behaviour:** no silent winner in the registry, projection, retrieval or compiler.
- **History visibility:** retrieval and compiler both treat history as HISTORICAL.
- **Narrative non-authority:** enforced in both retrieval and compiler.
- **Version semantics:** consistent once S-1 and S-2 are adopted. The S-2 change also removes the read-time dependence (§2).

---

## 9. Dependency graph

```text
B-1 owners ──┬──► B-2 staleness values ──► external-domain policies
             ├──► B-4 authority ranks ───► person-attribute policies
             ├──► G-3 temporal limits
             └──► (real policies at all) ◄── B-3 retention catalogue (Legal)

B-3 retention ──► C-5 journal retention
C-1 key custody (Sec) ◄──► C-5 storage (Infra)          (crypto-shred is how content leaves an append-only log)
C-2 lifecycle table ◄── Legal (erasure reversal), identity owner (QUARANTINED → ACTIVE)
C-B breaking-policy flag ──► C-2 REVALIDATION_REQUIRED path

S-1 signature ─┬─► durable head schema
S-2 boundaries ┘
C-C sync events ──► S-2 / freshness rebuild ──► B-2

S-3 scope model ──┬──► T-1 commitment scope (C-E) ──► Sec/Prod grant (i)
                  ├──► T-5 Agent Knowledge (AGENT scope) ──► Sec grant (ii), Legal k
                  ├──► C-4 group partitioning
                  └──► C-A vocabulary rename

G-1 / C-D ──► gate change (engineering only)
X-1 measure ──► X-2 profiles (Product) ──► compiler production use
X-3 schema default ──► Gateway router
X-4 structural channel ──► Gateway prompt assembly ◄── Sec monitoring choice
C-6 event ──► Product workflow
T-2 class derivation ──► Sec floor
T-4 audit mode ──► Legal / Sec
```

---

## 10. Exact decisions blocking the next implementation step

**Assumption:** the next step is durable storage for the journal and head, plus a Gateway skeleton over the existing pure components, using TEST_ONLY policies and CUSTOMER scope.

**Genuinely blocking (cannot be engineered around):**

| # | Decision | Owner | Needed for |
|---|---|---|---|
| 1 | **Journal storage technology and partitioning** (C-5) | Infrastructure | Any durable commit |
| 2 | **Per-subject key custody, wrapping and rotation** (C-1) | Security | Claim ids and crypto-shredding in durable storage |
| 3 | **Retention catalogue interface accepted** (B-3; the values can follow) | Legal | Storing journal entries with a retention reference |
| 4 | **Whether PENDING_ERASURE can be reversed** (C-2) | Legal | Final lifecycle table in storage |

**Needed only if the next step goes beyond CUSTOMER scope:**

| # | Decision | Owner |
|---|---|---|
| 5 | Grant model for TENANT, AGENT and SESSION reads, including commitment cross-agent visibility and Agent Knowledge readers | Security / Product |

**Needed before any real (non-TEST_ONLY) policy is published, but not blocking storage or Gateway engineering:**
- B-1, B-2, B-4, G-3 (owners);
- T-2 floor (Security);
- X-2 task profiles (Product);
- C-6 workflow (Product);
- T-4 audit mode (Legal / Security);
- T-5 k (Legal).

**Engineering to apply before or with the next step.** No owner input is needed; each is small:
1. **S-2:** boundaries become their own evaluation points; reads never create them.
2. **S-1:** keep the value-only signature, and ask the spec owner for the §13 wording.
3. **C-B / C-2:** enforce the lifecycle table; add REVALIDATION_REQUIRED and SUPERSEDED_BY_POLICY; add the breaking-policy flag.
4. **C-C:** journal the external-sync events.
5. **C-D / G-1:** status-gate typed commands only.
6. **C-E / T-1:** add subject, agent and tenant to commitment events.
7. **C-A:** adopt the contract's scope vocabulary.
8. **X-1:** injected size measure.
9. **C-6:** emit the conflict event.
10. **X-4:** a data-channel contract for the Gateway.
11. **T-2:** a narrative `security_class` derived as the most restrictive class.

**Not done here:** no normative document changed, no component built, no production value set.
