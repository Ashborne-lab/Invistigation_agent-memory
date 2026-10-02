# Parallel work synthesis — while J1–J6 are with Jay

Date: 2026-09-26. Read-only investigation. **No architecture decision is taken in this pass or in
any report it summarises.**

**Standing rule observed throughout.** Nothing here says *"therefore OLBrain will…"*. Findings are
phrased as *evidence supports…*, *this remains undecided…*, *if Jay chooses X, then…*.

---

## 1. What was completed

Eleven new investigation artifacts, plus three repository clones authorised by QF-3.

| Track | Artifact | Subject |
|---|---|---|
| A1 | `governance-g8-research.md` | Bulk-deletion retry / DLQ semantics |
| A2 | `governance-g1-g6-research.md` | Capability caching and online authorization |
| A3 | `governance-g3-research.md` | Predicate freshness |
| A4 | `d5-authority-research.md` | Operational-correction authority domain |
| A5 | `d7-patch19-research.md` | Procedural-memory exclusion / Patch 19 |
| B1 | `qf5-current-path-research.md` | Session/configuration path |
| B2 | `security-current-head-reverification.md` | S1–S5, QF-4/S7 at current commits |
| C | `new-repo-inventory-closure.md` | mcp-deployer, agent-eval, finance-engine |
| E | `person-merge-current-state-memory-research.md` | Merge vs Current State vs Memory |
| F | `s7-backfill-correction-note.md` | M1 correction to the S7 procedure |
| G | `decision-gateway-jev-research.md` | Bounded-judgement boundaries |

`[CODE]` Repositories cloned: `olbrain-mcp-deployer 0efd05f`, `olbrain-agent-eval 6c289ca`,
`olbrain-finance-engine 109a838`. The workspace now holds **13** repositories, all working trees
clean, none modified.

**Track D produced no measurements.** See §3.

---

## 2. What was conclusively closed

`[CODE]` unless noted. These no longer need revisiting.

1. **`scope_generation` does not exist in any repository.** G8 governs a prospective mechanism;
   there is no backlog of rejected work awaiting a policy. *(A1)*
2. **There is no dead-letter handling in the platform.** One dormant provisioning workflow exists
   whose own header states that a persistently-rejected event is *"silently dropped when the
   subscription's 1-day retention expires"* and that *"nothing alerts on a dead-lettered message
   yet"*. *(A1)*
3. **An authorization-cache precedent exists and its shape answers more of G1/G6 than expected.**
   `hotpath_cache` — TTL default **30s**, **default OFF**, and only the credential *fetch* is
   cached while every check (hash, status, expiry, org membership, scope pin, rate limit) runs per
   request. Production is therefore **online-only today**. *(A2)*
4. **No predicate-freshness machinery exists.** Every `freshness`/`stale` occurrence is cache
   lifetime, not predicate validity. *(A3)*
5. **The `LearnedOverride` lane is fully implemented** — `suggested → active → retired`, a
   per-agent feature gate, and `approve`/`retire` endpoints carrying actor and reason. *(A4)*
6. **The contract contains no scope-exclusion vocabulary at all** — zero matches for *out of
   scope*, *outside the scope*, *does not model*, *not modelled*, *procedural memory*. *(A5)*
7. **QF-5's two methods were removed on 2026-04-01** (*"chore: remove deprecated MessageProcessor
   pipeline"*). The call sites at `routers/sessions.py:462` and `:568` have referenced an undefined
   method for ~6 months. The `Agent` class has **no message-processing method at all** — it is a
   session-management and introspection object. *(B1)*
8. **Security posture improved materially since the stale checkout** — catch-all read exclusions
   9 → **17**, write exclusions 24 → **33**. S3 stays withdrawn; S1 confirmed unchanged; S4 and S5
   confirmed with corrected citations. *(B2)*
9. **No person-identity mechanism exists in any of the three new repositories.** The person-identity
   inventory is now **closed and bounded** at six mechanisms across two subject classes. *(C)*
10. **The finance family is path-scoped** (`organizations/{org_id}/…`), so it needs no
    `organization_id` stamping and is **outside S7's scope**. *(C, F)*
11. **`mcp_tool_executions` and `agent_qa_runs` are resolved** — two of the three unknowns that
    existed only because repositories were absent. *(C)*

### Refined rather than closed

`[INFERENCE]` **N1 is downgraded.** Prior passes called merge-induced `CONFLICT` *"the deepest
unsolved problem"*. `[CONTRACT]` `CONFLICT` is one of four first-class resolution statuses and §6
states its recovery path: *"`CONFLICT` permits only the policy's declared `RESOLVE_CONFLICT`
operation, so the state is recoverable without a blind overwrite."* The contract **already has the
machinery**; what it lacks is anything naming identity merge as an event. **N5 is promoted in its
place** — Memory is the plane with no conflict concept and a direct path to the prompt. *(E)*

---

## 3. What remains UNMEASURED because production access is unavailable

`[UNMEASURED]` Re-confirmed this pass: no credentials, no exports, `gcloud` absent, no relevant
environment variables, `firebase projects:list` fails. **No attempt was made to obtain access or
to read customer PII.**

| Track | Measurement | Specification preserved in |
|---|---|---|
| D1 | Co-occurrence rate (`lead_profiles`, per org, with thresholds <5% / 5–20% / >20%) | `person-identity-measurement-pass.md` §2.2–2.4 |
| D2 | `agent_users` recovery join — total / recoverable / unrecoverable / session / multi-map / cross-org | ibid. §4.4 |
| D3 | Session-row blast radius by agent and table | ibid. §5.4 |
| D4 | Transfer stale-tenancy counts | ibid. §6.4, and `s7-backfill-correction-note.md` §4 Phase 0 |
| B1 | QF-5 log query — `POST /sessions/{id}/messages` since 2026-04-01, grouped by status **and revision** | `qf5-current-path-research.md` §5 |

`[INFERENCE]` All five are now *specified rather than open*: population, method, normalisation,
biases and — for D1 and B1 — the decision thresholds stated in advance, so results cannot be
argued after the fact.

**One measurement is `[UNMEASURABLE]`, not merely unmeasured:** fragmentation per human. Computing
it requires knowing which `person_hash` values are one human — the mapping whose absence is the
finding. No access would fix it.

---

## 4. What remains UNDECIDED because Jay (or a named owner) must decide

**Unchanged and untouched: J1–J6.** No report answers any of them.

| ID | Decision | Owner | Moved this pass? |
|---|---|---|---|
| J1 | Cross-channel recognition needed? | Product/Jay | No |
| J2 | Contract: person-merge forbidden or unmodelled? | Contract owner | No — **but N10 narrows part of it** (is a merge a deletion of the retired scope?) |
| J3 | Who owns person identity? | Jay | No |
| J4 | Is an LLM-extracted person row an identity assertion? | Jay/contract owner | No |
| J5 | Merge: operator-confirmed, automatic, or both? | Jay | Informed — `research_clients` chose operator-initiated + audited |
| J6 | Organization transfer: follow, sever, or block? | Tenancy policy | **Escalated** — F shows person data is already stranded |
| G1+G6 | TTL and online-only operation set | Security, as a pair | **Materially informed** — a 30s/default-off precedent exists and the contract proposes 60s. *The discrepancy is factual and unreconciled.* |
| G3 | Per-predicate freshness values | Named domain owners (R2) | Informed — ~half is mechanical; only 3 values per predicate are owner decisions |
| G4 | Recompute window | Operations + Legal | Legal half parked |
| G5, QF-2 | Aggregate classification | Legal | Parked by decision |
| G8 | Rejected-work disposition | Operations | **Materially informed** — 5 models, in-house doctrine documented |
| D5 | Authority domain + approver | Workflow-design owner | Unblocked by R2; 4 bounded sub-questions prepared |
| D7 | Adopt Patch 19 | Contract owner | Prepared; consequences enumerated both ways |
| QF-5 | Retain or retire the Firestore path | Runtime owner | Gated on the log query, now specified |

---

## 5. New technical issues discovered

| ID | Issue | Source |
|---|---|---|
| **N8** | **Tenant-scoped subject vs agent-scoped storage.** Person data is agent-scoped by path today; a tenant-scoped subject spanning two agents is a visibility change no current mechanism expresses. | E §7 |
| **N9** | **Merge inherits G4 and G8.** Invalidate/recompute is bounded by G4; generation-rejected in-flight work is G8. Neither dependency was previously recorded. | E §2.2, §6 |
| **N10** | **Is a merge a deletion of the retired scope?** Determines whether `scope_generation` applies. Narrower than J2. | E §2.3 |
| **N11** | **Narrative re-registration.** Session-linked narratives could attach to a new subject inheriting a deleted subject's identifier. Unaddressed in every model. | E §4 |
| **N12** | **Disclosure is not rollback-able.** Reversible storage cannot unsay what was rendered into a prompt. Argues for merge being hard to trigger regardless of storage design. | E §5 |
| **S6** | **`agent_users` is write-excluded but not read-excluded** from the catch-all — and it is the one person store holding identifiers **unhashed**. Every sibling PII store is read-excluded. | B2 §3 |
| **G8↔G5** | **G8's "record the rejection" options inherit G5.** A durable record of work concerning a deleted scope is itself a dataset needing §10 classification — which is parked. Choosing those options creates an unclassified store. | A1 §6 |
| **C2↔D7** | A typed memory classifier is **blocked behind D7**, because it would harden a class taxonomy the contract owner has not settled. | G §2 |
| **C8↔D5** | Automating operational-correction proposals would compound D5's unenforced human gate. | G §2 |
| **mcp-deployer** | Second credential store (Fernet-encrypted `oauth_tokens`), a new `privacy_compliance_log` collection, and **an additional `agents/{id}` writer that QF-1's transition plan does not name**. | C §2 |
| **D5 §4.1** | The override `approve`/`retire` endpoints have **no router-, endpoint- or global-middleware authorization**; `approved_by` is a caller-supplied string. **Stated as a finding requiring confirmation**, since deployment-level gating was not traced. | A4 §4.1 |

---

## 6. Which work is now ready for implementation later

`[INFERENCE]` *Ready* means the investigation is complete and the design is unambiguous — **not**
that implementation is authorised. Nothing here should start without explicit instruction.

- **Per-mutation `mutation_id` idempotency** — `[CONTRACT]` mandated by §7 independently of G8.
- **Single-scope deletion** — already recorded as implementable.
- **A typed work-class property** on queued work — needed by one G8 model, harmless to the others.
- **The `person_hash` / `memory_doc_id` guard test** — one assertion that
  `memory_doc_id(a, k).endswith(person_hash(k))`. Closes the N7 seam permanently. *(Code change;
  not made here.)*
- **The S7 Phase 0 measurement** (`s7-backfill-correction-note.md` §4) — read-only, needs no
  decision, and sizes the problem before any write.
- **Documentation correction** in `olbrain-agent-runtime` — README, `WEBHOOK_ARCHITECTURE.md` and
  `OUTREACH_EXECUTION_GUIDE.md` still advertise methods removed six months ago.

---

## 7. Which work must still wait

- **All PostgreSQL schema design and all migration design** — unchanged.
- **Any person-identity redesign** — J1–J6 open.
- **Capability caching** — until G1 and G6 are answered as a pair.
- **Any Predicate Policy for an externally-owned predicate** — until G3 values arrive.
- **All bulk deletion** — G8.
- **Everything aggregate-bearing** — G5/QF-2 parked.
- **Any Decision Gateway scoping** — two candidates blocked behind D5 and D7.
- **All security remediation**, including S6 and D5 §4.1 — read-only workspace; these are awareness
  findings routed to their owners.

---

## 8. Does anything change the PostgreSQL-design gate?

`[INFERENCE]` **Yes — one item plausibly leaves the gate, and one new requirement enters it.**

**Plausibly leaves: G3.** `governance-g3-research.md` §5 argues that `freshness_contract` lives on
the **Policy Registry**, not on the value row; `freshness_status` is `[CONTRACT]` a derived
`StateSlot` property and materialising it would contradict Current State being a projection. What a
value row needs is an observation timestamp and a source reference — **provenance, required
regardless of G3**. If the contract owner confirms that reading, G3 blocks the Policy Registry
schema and the resolver's freshness path, **not the core schema**.

**This is an inference and must be confirmed before anyone relies on it.** `[UNDECIDED]`

**Enters: D1(b)'s per-field authority marker.** Already-answered D1(b) requires a per-field marker
carrying writer and timestamp. `[INFERENCE]` It is orthogonal to identity and must be carried on
the value row under *every* identity option — a concrete schema requirement that exists now,
independent of J1–J6.

**Unchanged blockers:** D4; G5 + QF-2 (parked); and the identity question behind them.

`[INFERENCE]` Net: the gate is **narrower but not open**. The parked pair is the binding
constraint, and *parked is worse than open* — an open question gets answered when someone reaches
it; a parked one waits for a decision to unpark. That remains the single most important thing for
the programme owner to revisit.

---

## 9. Should the person-identity investigation change again after this pass?

`[INFERENCE]` **Its scope should be considered closed; its centre of gravity should move.**

**Closed:** the inventory. Three repositories entered scope and added **zero** person-identity
mechanisms (C §1.1). The six-mechanism, two-subject-class picture is now unconditional rather than
"across the ten repos". Further repository search is not warranted.

**Moved:** from *cataloguing mechanisms* to **merge semantics in the Memory plane** (E §3). The
Claim and Current State planes turn out to be adequately served by existing contract machinery;
Memory is not, because it has no conflict concept and renders directly into the prompt. If Jay
permits merges, that is where the unresolved design work is.

**Unchanged:** the reframing of D4 stands. Nothing this pass weakens it, and C strengthens it — the
asymmetry (every other entity class has a working identity story; the one OLBrain converses with
does not) survives the scope expansion.

---

## 10. What should happen immediately after Jay returns J1–J6

`[INFERENCE]` Ordered, and conditional on the answers.

**Regardless of the answers:**

1. Run the **S7 Phase 0 measurement** — read-only, decision-free, and it gates a live workstream.
2. Run the **QF-5 log query** — grouped by revision, since a pre-2026-04-01 revision still serving
   traffic would invalidate the source analysis.
3. Route the awareness findings to their owners: **S6** (security), **D5 §4.1** (workflow-design),
   **M1** (S7 owner), **mcp-deployer as an unnamed `agents/{id}` writer** (QF-1 / agent-design).
4. Put **G8** and the **G1+G6 pair** to the decision board — neither is parked or gated, and both
   now have prepared option sets. Surface the **30s vs 60s discrepancy** as a factual matter.

**If J1 is "yes, cross-channel recognition is needed":**
run the co-occurrence measurement to size it; then J2 becomes the pivot, and E §9's surviving
models (C-M2 re-resolve + Mem-M2 partition) are the starting point — **not a design decision, a
starting point**.

**If J1 is "no":**
`person-identity-measurement-pass.md` §10 G's simpler candidate — per-tenant keyed hash, typed
identifiers, `agent_users` promoted — becomes the leading option, and most of the merge research
(Track E) becomes moot rather than wrong. Documenting *why* it became moot would be worth doing.

**If J2 reads merge as forbidden:** Track E's models are void and the identity work reduces to
privacy and fragmentation-honesty. **If unmodelled:** N10 is the next contract question, and it is
narrower and cheaper than J2 itself.

**Not to be done on Jay's return:** starting PostgreSQL or migration design. §8 shows the gate is
narrower, not open.

---

## 11. Status table

**Precision note.** *Investigation complete* ≠ *decision made*; *evidence missing* ≠ *production
access missing*; *implementation blocked* ≠ *implementation merely not yet authorised*.

| Item | Status | Can proceed without Jay? | Blocks PostgreSQL? | Next action |
|---|---|---|---|---|
| G8 disposition | Investigation complete; **decision open** | No — Operations decides | No (blocks bulk deletion) | Put 5 models to the board; flag the G5 inheritance |
| G1 + G6 | Investigation complete; **decision open** | No — Security, as a pair | No | Reconcile 30s precedent vs 60s proposal |
| G3 values | Investigation complete; **decision open** | No — named domain owners | **Probably not** — confirm §8 | Ask 3 values per predicate; confirm the Policy-Registry reading |
| G4 | Open; Legal half parked | Operations half only | No | Vote the Operations half |
| G5 + QF-2 | **Parked by decision** | No | **Yes** (aggregate-bearing only) | Ask how long parked, and what proceeds meanwhile |
| D5 | Investigation complete; **decision open** | No — workflow-design owner | No | 4 bounded questions; §4.1 needs confirming |
| D7 / Patch 19 | Investigation complete; **decision open** | No — contract owner | No | Adopt or decline; watch the `LearnedOverride` drafting risk |
| QF-5 | Investigation complete; **evidence missing** | Query yes; decision no | No | Run the log query, grouped by revision |
| QF-5 undefined-method defect | **Confirmed defect** | Yes to record; fix is a code change | No | Record; fix not authorised here |
| S1 `agents/{id}` | **Confirmed at HEAD** | Yes to report | No | Routed via QF-1's ownership move |
| S2 | **Figure withdrawn**; `[UNMEASURED]` | Yes — recount from rules | No | Re-enumerate at `8cee761c` |
| S3 | **Withdrawn (false)** | Done | No | None |
| S4, S5 | **Confirmed** | Done | No | None |
| **S6** `agent_users` read-exposed | **New finding** | Yes to report | No | Security owner; verify client readers first |
| M1 / S7 procedure | **Correction prepared**; severity bounded — both affected stores self-heal on write, so the residue is quiet tables and dormant persons | **Yes — Phase 0 is read-only** | No | Run Phase 0; adopt or amend Phase 1–3 |
| New-repo inventory | **Complete at collection level** | Yes | No | Resolve the database-identity question (C §6.1) |
| mcp-deployer as `agents` writer | **New finding** | Yes to report | No | Add to QF-1's writer set |
| D1–D4 measurements | **Production access missing** | Yes, with access | Indirectly (D4/J1) | Run as specified; no PII beyond the spec |
| Fragmentation per human | **`[UNMEASURABLE]`** | No — not by anyone | No | None; the circularity is the finding |
| Merge vs Claim/Current State | Investigation complete; **contract has machinery** | Yes (research) | No | Confirm §0 reading with contract owner |
| Merge vs Memory (N5) | **Deepest open problem** | Research yes; design no | Not yet | Depends on J1/J2/J5 |
| N8–N12 | **Newly surfaced** | Research yes | N8 possibly | Fold into the next identity pass |
| Decision Gateway | Survey complete; **no recommendation** | Yes (research) | No | Nothing; two candidates blocked behind D5/D7 |
| PostgreSQL schema | **Implementation blocked** | No | — | Wait on D4 + parked pair |
| Migration design | **Implementation blocked** | No | — | Downstream of schema |
| `mutation_id`, single-scope deletion, guard test, doc fix | **Ready, not authorised** | Yes to specify | No | Await explicit instruction |

---

## 12. Workspace safety

`[CODE]` Verified at the end of this pass: all **13** repository working trees clean
(`git status --porcelain` empty for each); `artifacts/architecture-contract.md` unchanged at md5
`97c1fa3bcea1d71210c0429b1d113d07`; `artifacts/state-semantics-explorer.html` unchanged. No
existing investigation report was overwritten — the eleven artifacts are new files. No production
query, no data modification, no schema, no migration, no deploy, no commit, no push.

Three repositories were cloned under QF-3's explicit authorisation and have not been modified.
