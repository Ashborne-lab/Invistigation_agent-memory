# New repository inventory — closure of the QF-3 scope gap

Date: 2026-09-26. Read-only. **Does not rewrite `firestore-inventory-closure.md` or any prior
inventory; it extends them.**

**Authority to clone.** QF-3 was answered by Jay: *"Yes — clone all three real repositories
(mcp-deployer, agent-eval, finance-engine) and finish the Firestore inventory. olbrain-agent-cloud
is dropped from the list as a duplicate of agent-runtime. This is a clone, not a programme
decision."* Done this pass. Working trees untouched.

| Repository | Commit | Files | Primary language |
|---|---|---|---|
| `olbrain-mcp-deployer` | `0efd05f` | 523 | Python (254), YAML (150) |
| `olbrain-agent-eval` | `6c289ca` | 217 | Python (141) |
| `olbrain-finance-engine` | `109a838` | 565 | Python (504) |

**The workspace now holds 13 repositories.** `olbrain-agent-cloud` is confirmed a former name of
`olbrain-agent-runtime` and is not a missing repository.

---

## 1. Headline findings

1. `[CODE]` **No person-identity mechanism exists in any of the three.** Searched for
   `person_hash`, `user_key`, `memory_doc_id`, `channel_user_id`, `lead_contact` — zero hits in
   all three repositories. **Confirmed separately by collection name**: `agent_datastores`,
   `agent_user_memory`, `lead_profiles` and `lead_contacts` each return zero hits in all three.
   The three logical `agent_datastores` writer lanes (extract-mode, live agent tool, operator
   CRUD) are therefore unchanged by the scope expansion — unlike QF-1's `agents/{id}` writer
   set, which gains mcp-deployer (§2.2). **The person-identity inventory is therefore closed and bounded at six
   mechanisms across two subject classes**, exactly as `person-identity-measurement-pass.md` §9.4
   recorded for the ten-repo scope.
2. `[CODE]` **`olbrain-mcp-deployer` is the platform's second credential store** — `oauth_tokens`,
   `oauth_connections`, `credentials`, `connector_credentials`, `oauth_callback_results` — and it
   encrypts tokens with Fernet under an `OAUTH_ENCRYPTION_KEY`, a different scheme from the
   KMS-based `organizations/{org}/secrets`.
3. `[CODE]` **`olbrain-finance-engine` scopes by path, not by field** — 206 references to
   `organizations`, meaning its collections live under `organizations/{org_id}/…`. This has a
   direct and favourable consequence for S7 (§5).
4. `[CODE]` **`olbrain-agent-eval` is small and low-risk** — four collections, one of which
   (`agent_qa_runs`) was a known unknown and is now resolved.
5. `[CODE]` A previously unknown collection appears: **`privacy_compliance_log`** in mcp-deployer.

---

## 2. `olbrain-mcp-deployer` (`0efd05f`)

### 2.1 Collections

`[CODE]` By reference count: `agents` (13), `oauth_connections` (10), `oauth_tokens` (9),
`public_mcp_servers` (8), `oauth_callback_results` (8), `credentials` (8), `mcp_configs` (4),
`workflow_definitions` (2), `organizations` (2), `mcp_tool_executions` (2),
`connector_credentials` (2), `users` (1), `servers` (1), `privacy_compliance_log` (1),
`mcp_projects` (1).

### 2.2 What this resolves

`[INFERENCE]` `firestore-inventory-closure.md` listed `mcp_tool_executions` as an unknown whose
writer was unidentified because the repository was absent. **It is written here.** Likewise
`agents/{id}/mcp_configs/*` gains a second writer outside the ten-repo set — relevant to QF-1,
whose answer makes `agent-design` the owner-of-record for `agents/{id}`: mcp-deployer is a writer
that the QF-1 transition plan (*"studio-backend and agent-engine become clients"*) does not
currently name. **This should be added to QF-1's writer inventory.**

### 2.3 Credentials and PII

`[CODE]` `runtime/generate_oauth_key.py` generates a `Fernet` key exported as
`OAUTH_ENCRYPTION_KEY`; `runtime/core/mcp_manager.py:381` documents a `credential_source` of
`"oauth" | "kms" | "config"`.

`[INFERENCE]` So three credential schemes coexist platform-wide: KMS-encrypted
`organizations/{org}/secrets` (studio), Fernet-encrypted `oauth_tokens` (mcp-deployer), and
plaintext `twilio_accounts` (previously recorded). Token *encryption* is present here, which is
better than the `twilio_accounts` precedent; **whether `OAUTH_ENCRYPTION_KEY` is itself managed,
rotated or shared across environments is `[UNMEASURED]`** and is the natural follow-up question.

`[CODE]` `privacy_compliance_log` is documented as a Firestore audit-logging collection
(`docs/deployment-guide.md:445`, `docs/shopify-integration.md:147`). `[INFERENCE]` A compliance
audit log is a candidate §10 dataset with its own retention question — i.e. it plausibly belongs in
**G5's** classification set, which is parked. Recorded, not classified.

### 2.4 Catch-all exposure

`[INFERENCE]` Cross-referencing the current rules (`olbrain-studio 8cee761c`, per
`security-current-head-reverification.md`): **none** of `oauth_connections`, `oauth_tokens`,
`credentials`, `oauth_callback_results`, `public_mcp_servers`, `mcp_tool_executions`,
`mcp_projects` or `privacy_compliance_log` appears in either catch-all exclusion list. If these are
top-level collections in the same Firestore database, they are catch-all readable and writable by
any authenticated user.

**`[UNDECIDED]` — this is not asserted as an exposure.** Two things must be established first, and
neither was determined this pass: (i) whether mcp-deployer uses the *same* Firestore database as
studio, or a separate project; (ii) whether these are top-level collections or nested under
`agents/{id}` or `organizations/{org}` (`mcp_configs` is known to be a subcollection). **This is
the highest-value follow-up from Track C** and it is answerable from code plus deployment config
without any data access.

---

## 3. `olbrain-agent-eval` (`6c289ca`)

`[CODE]` Collections: `api_keys` (8), `agents` (6), `organizations` (2), `agent_qa_runs` (2).

`agent_qa_runs` is written at `agent_eval/core/report.py:742` —
`firestore_client.collection("agent_qa_runs").document(report.run_id).set(doc)`, a thin
pass-through that is a no-op when no client is configured (`:739`). The run document nests the
agent id under `request`, requiring a composite index `request.agent_id ASC, created_at DESC`
(`README.md:72`).

`[INFERENCE]` This closes the second of the three unknowns that existed only because of absent
repositories. Evaluation runs are operational telemetry about agents, not person data: no
`organization_id` field was found on the run document, and the org association is indirect via the
agent. **`agent_qa_runs` is not in either catch-all exclusion list** — same caveat as §2.4 about
database identity applies.

---

## 4. `olbrain-finance-engine` (`109a838`)

### 4.1 Collections

`[CODE]` `organizations` (206 — the path root), `versions` (59), `runs` (50), `finance_lines` (45),
`pnl_projections` (27), `pnl_drivers` (26), `finance_rm` (26), `finance_model` (22),
`rm_proposals` (17), `pnl_inputs` (13), `workflow_runs` (12), `pnl_statements` (9),
`finance_policy` (9), `pnl_exports` (8), `user_profiles` (6), `dispatched` (6), `memberships` (5),
`commentary` (5).

### 4.2 Tenancy — path-scoped, and this is good news for S7

`[CODE]` The dominance of `organizations` (206 references) indicates the finance collections live
under `organizations/{org_id}/…`. Authorization is `require_org_role(org_id, x_user_authorization)`
(`app/auth.py:63`), which queries memberships filtered by
`FieldFilter("organization_id", "==", org_id)` (`:76`).

`[INFERENCE]` **Path-scoped tenancy needs no `organization_id` stamping and no backfill.** The S7
sequence (stamp → backfill → tighten) does not apply to the finance family, because the org is
already in the document path. This is consistent with Jay's QF-2 note (*"the finance / P&L
collections are already server-only under `organizations/{org}` per the rules comments"*) and
means **the finance family is outside S7's scope** — a useful reduction.

### 4.3 QF-2 / G5 relevance

`[INFERENCE]` The classification-relevant families are now enumerable: raw material (`finance_rm`,
`rm_proposals`, `commentary`), inputs and drivers (`pnl_inputs`, `pnl_drivers`), derived outputs
(`pnl_projections`, `pnl_statements`, `finance_model`, `finance_lines`), exports (`pnl_exports`),
policy (`finance_policy`), and execution records (`runs`, `versions`, `workflow_runs`,
`dispatched`).

`[INFERENCE]` The derived outputs are the **aggregate datasets** §10 concerns, and
`app/finance_reconcile.py` plus the `versions` collection show the family is versioned and
reconcilable — which is directly relevant to §10's `recomputable` field. **No classification is
offered here**: QF-2 and G5 are parked by Jay's decision, and classifying is a legal judgment, not
a code question. What Track C adds is that the dataset list is no longer unknown.

### 4.4 G3 relevance

`[INFERENCE]` See `governance-g3-research.md` §3(b): finance figures are the most plausible first
*externally-owned* predicate family with a real business validity window, and R2 names their owner.

---

## 5. Which prior assumptions were based on the old ten-repo scope

`[INFERENCE]` Explicitly, as the task asks:

| Prior assumption | Status now |
|---|---|
| *"Three of twelve remaining unknowns exist solely because of absent repositories"* (QF-3) | **Two resolved** — `mcp_tool_executions` (mcp-deployer) and `agent_qa_runs` (agent-eval). The Finance/P&L family is now enumerated. |
| *"The ~17-collection Finance / P&L family sits in a repository outside the workspace, so classification cannot be completed"* (G5/QF-2) | **Scope limitation removed.** 18 collection names are now known. Classification remains parked and remains a legal decision. |
| *"A second reader of secrets"* exists in an absent repo (QF-3) | **Confirmed** — mcp-deployer, with its own Fernet scheme (§2.3). |
| Person-identity inventory bounded at four/six mechanisms *"across the ten repos"* | **Now unconditional** — the three new repos add none (§1.1). |
| S7 must stamp `organization_id` across all affected collections | **Narrowed** — the finance family is path-scoped and outside S7 (§4.2). |
| QF-1's `agents/{id}` writer set spans three repositories | **Understated** — mcp-deployer writes `agents` and `mcp_configs` too (§2.2). |
| Firestore inventory is *"terminal"* if the repos stay absent | **Moot** — they are present; the inventory can now be completed. |

---

## 6. What remains open from Track C

`[UNDECIDED]` / `[UNMEASURED]`

1. **Database identity (§2.4)** — do mcp-deployer, agent-eval and finance-engine share the studio
   Firestore database and project? Until answered, their catch-all exposure cannot be assessed.
   **Highest priority; answerable from code and deployment config alone.**
2. **Collection nesting** — which of the new collections are top-level vs nested.
3. **`OAUTH_ENCRYPTION_KEY` management** — provenance, rotation, per-environment separation.
4. **`privacy_compliance_log`** — retention and classification; a candidate G5 dataset.
5. **Deletion behaviour** in all three repositories — not traced this pass beyond noting that
   finance-engine has delete paths in `app/inputs.py`, `app/presentation.py` and siblings.
6. **A full writer/reader map** for the new collections, at the depth
   `firestore-inventory-closure.md` applies to the original ten.

---

## 7. Limitations

1. Collection identification is by `collection("name")` string reference frequency at one commit;
   dynamically-constructed collection names would be missed. `[CODE]`
2. Reference **count** indicates prominence, not document volume. No data was accessed.
3. Security assessments in §2.4 and §3 are **conditional** on the unresolved database-identity
   question and are deliberately not stated as findings.
4. No prior inventory document was modified. Where this report contradicts one, the contradiction
   is recorded in §5 rather than edited into the older file.
