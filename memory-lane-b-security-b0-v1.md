# Lane B / B0: Security and Authority Boundary v1

**Date:** 2026-10-01.

**Classification:**
- *Current behaviour* columns: **VERIFIED CURRENT** at `origin/main`.
- *Proposed fix* columns: **TARGET ARCHITECTURE**.

**Commits:**

| Repository | Commit |
|---|---|
| studio | `1f05ca11` |
| studio-backend | `5da93ae` |
| agent-design | `c56271d` |
| agent-runtime | `daee3f9` |
| agent-engine | `dfc3a47` |
| mcp-deployer | `b75cc12` |
| research-runtime | `6b81691` |

**What was and wasn't touched:**
- no production repository edited, nothing deployed, no production data read;
- rules work is a derived copy, tested only in the local Firestore emulator with synthetic identities;
- the architecture contract is unchanged (no contradiction found).

**Artifacts (`investigation/lane-b/rules-lab/`):**

| File | What it is |
|---|---|
| `firestore.current.rules` | Read-only copy of production `firestore.rules` |
| `make_b0_rules.py` → `firestore.b0.rules`, `firestore.b0-stage2.rules` | Every change is a named substitution |
| `b0.diff` | Reviewable diff |
| `probe_b0.mjs` | 26 attack probes, each with a legitimate twin |
| `make_b0_tests.py` → `tests-b0/` | Studio's 17 suites, with 3 adjusted and the reason for each |
| `run_lab.sh` | Re-runs everything |
| `results/` | Before/after records |

**Lane A probe of record:** `memory-prototype/security_probe/results-studio-1f05ca11.jsonl`.

---

## A. Security findings

**Status values:**
- **Fix proven (emulator):** the fix is implemented in the B0 rules and the probe proves it.
- **Fix specified:** code fix designed; it must be implemented in the named repository during Lane B.
- **Blocked:** needs a missing repository or an owner decision.

### A.1 Firestore rules (client SDK)

**Shared root cause:** three **default-allow catch-alls**:
- `match /{collection}/{docId}` (L888);
- `/{collection}/{docId}/{sub}/{rest=**}`;
- `organizations/{orgId}/{sub}/{rest=**}`.

Each grants any signed-in user access to everything not on a deny-list. Rules OR together, so a catch-all **defeats every stricter block above it**: the `agents` ownership block (L23) never took effect.

The dedicated-tenant file `firestore.clix.rules` is already strict for the same collections (studio L162-251). The shared-platform file never received the same treatment.

**Common fix basis:**
- Membership is proved by `memberships_index/{uid}_{org}`, which only studio-backend writes. So "org member" in rules is server-derived, never caller-asserted.
- An agent's organization is read from the agent document, which clients can no longer change (B0-01).

| ID | File | Current behaviour | Exploit / trust failure | Required invariant | Fix (in `firestore.b0.rules`) | Dependencies | Risk | Verification | Status |
|---|---|---|---|---|---|---|---|---|---|
| B0-01 | studio `firestore.rules` L23 + L888 | `agents` is not excluded from the catch-all: any signed-in user can create, read, update or delete any agent | **Create an agent claiming any org; take over any org's agent** (owner_id rewrite); repoint `organization_id`. The agent doc is the tenancy root for API-key org match, `canUseAgent`, DCI/KV placement and `mcp_configs` | INV-S1, S2, S3 | `agents` excluded from both catch-alls. `create`/`delete: false` (Studio creates through `POST /api/agents`). Read if owner, org member, project member or team member. Update by the owner or an org editor, **never** `organization_id`, `owner_id`, `userId`, `project_id`, `runtime`, `billing_config`, `lifecycle_state`, `team_access`, `api_keys` | Studio's only client write, `features.learned_overrides`, still works. Studio queries that list agents by `project_id` keep working through the project-member clause | Medium: owner-only screens and Noesis `[UNRESOLVED]` | Probes K1-forge, K1-takeover, K1-repoint, K1-read, K1-delete, K1-editor-update, K1-editor-repoint | **Fix proven** |
| B0-02 | L888 (no block) | `agent_messages` read/write by any signed-in user | Read every tenant's conversations; **forge or overwrite evidence** (Lane A C-2) | INV-S1, S2, S6 | Explicit block: read if org member of the row's org, **or** `canUseAgent(row.agent_id)` (legacy rows without an org). `write: false` (Studio never writes it; the runtime uses the Admin SDK) | Studio queries filtered only by `session_id` or `project_id` (usageService.js:910, :3347, :3506; messagesService.js:156) **must add an `agent_id` or `organization_id` constraint**, because Firestore rejects queries the rule can't prove | Medium (client query changes) | E1-read/write/create/list | **Fix proven** |
| B0-03 | L888 | `agent_sessions` read/write by anyone; `agent_sessions/*/messages` via the 4-segment catch-all | Read a session's phone number and summary; rewrite the summary (prompt poisoning) | INV-S1, S2 | Same as B0-02. The subcollection reads through a parent `get()` | Unscoped Studio queries (handoffService.js:235; analyticsService.js:672 without an org; FirestoreDataAccess.js:1138 by `agent_id` works) | Medium | S-read, S-write | **Fix proven** |
| B0-04 | L1335 | `organizations/*/members` readable by any signed-in user | Enumerate any org's member names and emails | INV-S1 | Read if org member, **or your own row** (onboarding slow path) | Legacy Onboarding.js:898 fallback (lists orgs unfiltered), already a cross-tenant listing | Low | N3-members | **Fix proven** |
| B0-05 | L1340 | Every other `organizations/{org}/<sub>` (departments, activities, private_mcp_servers, metrics …) read/write by anyone | Read or forge another org's departments and activities | INV-S1, S2 | `isOrgMember(orgId)` added to the catch-all | None for real members | Low | N4-departments, N4-dept-read | **Fix proven** |
| B0-06 | L1279 | `agents/{id}/<sub>` read by anyone; written by anyone except owner_lessons/mcp_configs/oauth_tokens | **Rewrite another org's agent `versions` (the brain) or `documents`** | INV-S2 | Read: `canUseAgent`. Write: owner or org editor, never `versions`/`owner_lessons`/`documents` (server-written) | Studio writes only `outreach_*`, which keeps the owner path (explicit `ownsAgent` blocks) | Low | N6-versions, N6-documents; tests-b0 outreach owner-positive | **Fix proven** |
| B0-07 | L888 | `tickets` readable by anyone | Read customer PII on support tickets | INV-S1 | Read by the filer or members of the ticket's org. The filer may update **only** `csat`/`csat_at`. Create/delete server-only | Studio supportService.js:160/:203 unchanged | Low | N5-tickets | **Fix proven** |
| B0-08 | L888 read list | `agent_users` readable by anyone (writes were already excluded) | Read end-user identifiers (phones) | INV-S1 | Read: `canUseAgent(row.agent_id)` or org member | Studio agentUserService.js:22 is filtered by `agent_id` (works) | Low | AU-read; tests-b0 outreach | **Fix proven** |
| B0-09 | `{path=**}/months\|days\|hours` | Any signed-in user reads every rollup | Read another org's usage analytics | INV-S1 | Generic readers removed. `agent_analytics/{agent}/{period}/{doc}` gets `canUseAgent` | Other rollup readers (Noesis `[UNRESOLVED]`) need explicit blocks | Medium (unknown readers) | AN-read | **Fix proven** |
| B0-10 | L418 | Org doc `update` of `runtime`/`auto_recharge` by **any** signed-in user | Re-point another org's dedicated runtime Firebase config | INV-S2 | Any client update requires org admin/owner | DedicatedRuntimeConfigCard.js:181 is an admin screen | Low | Studio suite (org doc tests) | **Fix proven** (suite) |
| B0-11 | L888 | **New** top-level collections are born client-writable | `memory_bindings`, `identity_events` and `inbound_dedup` would be writable on day one: identity takeover (Lane A R-1, C-1a) | INV-S4, S5 | Explicit `read, write: false` for `memory_bindings`, `identity_events`, `inbound_dedup`, `evidence_meta`, `memory_control`. **Stage 2:** the top-level catch-all becomes an **allow-list**, so unknown collections are denied by default | Stage 2 needs the Noesis client inventory (missing repository) | Stage 1: none. Stage 2: medium | V2-bindings, V2-identity-events, V2-dedup, V2-own-org-binding (stage 1); V2-new-collection (stage 2) | Stage 1 **fix proven**; stage 2 **proven in the emulator, deploy blocked** on the Noesis inventory |

### A.2 Server code (rules cannot fix these)

| ID | Repository / file | Current behaviour | Exploit | Required invariant | Proposed fix | Dependencies | Risk | Verification | Status |
|---|---|---|---|---|---|---|---|---|---|
| B0-12 | studio-backend `middleware/auth.py:243`; agent-design `app/middleware/auth.py:253` | `require_permission` checks scopes for API keys only; **Firebase users always pass**; it never sees the resource | Every route gated only by `require_permission` is open to any signed-in user (open sign-up) | INV-S7 | Add `require_org_access(user, org_id)` next to it. API key: `org_id == key.org`. Firebase: `check_membership_exists`. Otherwise deny. Call it, plus `check_view/edit_permission`, in every route listed in B0-13/14 | None | Low | New route tests per row (pytest + TestClient with Firebase and API-key principals across two orgs) | Fix specified |
| B0-13 | studio-backend `routes/agent_routes.py` :65, :128, :191, :212; `services/store_studio_calls.py:342` | Create agent in any org's project; list forks of any agent; fork preflight/fork with no checks | **Fork any agent into the victim org with yourself as owner and inherit its knowledge access** (`_extend_knowledge_access`) | INV-S2, S7 | `_require_org_member(target project org)` on create and fork; `check_view_permission(source)` on forks, preflight and fork | — | Low | Route tests | Fix specified |
| B0-14 | agent-design `app/routers/agent.py:103, :172, :563, :1043`; `agent_user.py:44-161`; `store.py:95, :231-275` | `get_agent` has `if owner_id != user_id: pass`; list by `project_id` ignores org; `/organization/{org}/active` open to Firebase users; `agent_users` CRUD unchecked; blueprint install into any project; **store admin approve has a TODO in place of a check** | Read or list any org's agents; edit any end-user row (incl. opt-out); approve any blueprint | INV-S1, S2, S7 | `check_view_permission` in `get_agent`/`model`; resolve the project's org, then `require_org_access`; check edit permission for `agent_users`; verified-admin gate on store admin | B0-18 for the admin gate | Low | Route tests | Fix specified |
| B0-15 | agent-runtime `core/api_key_middleware.py` ~515-627 | No scope check: a share-link key (`is_system`, `scoped_agent_id`) is accepted by every org-wide route | **A share visitor can list, export, import or erase all of the org's leads** (`leads_router` :488-879) and read or **delete any end user's memory in the org** (`agent_memory.py:48-109`) | INV-S7, S8 | Enforce `key.permissions` against the route's scope. Share keys are allowed only on webhook, upload-attachment, feedback and session-insights. `agent_memory`: require `path agent_id == X-Agent-ID == scoped_agent_id` | Studio share page (SharedAgentChat.js) uses only the webhook | Low | Middleware tests per route class | Fix specified |
| B0-16 | agent-runtime `routers/agent_webhook.py:2746`, `core/cs_packet_builder.py:1972`, `services/agent_memory_service.py:92` | `user_id` is caller-asserted (≤100 chars, any string) and used as the memory key with no channel component | **Lane A N1:** assert a WhatsApp customer's phone through a share key or any API key and load or poison that person's memory | INV-S8 | (a) Share keys: force `user_id = share_<token>_<chat>`. (b) The memory key gets a channel-plus-assurance component (`memory_doc_id(agent, f"{channel}:{user}")`). (c) Asserted identities never read verified memory (Lane A R-13 / M-5) | Existing memory documents keyed without a channel: a one-time rekey (registry handler) | Medium (memory continuity for API integrations) | Runtime unit tests; Lane A `test_M5_*` already models it | Fix specified |
| B0-17 | agent-runtime `routers/email.py:67-138` (public endpoint) | `/api/email/webhook`: no Inbound Parse secret or basic-auth, no SPF/DKIM/DMARC; `from` is trusted and becomes the memory key; reply-all includes `cc` | **Spoof `from=victim`, `cc=attacker`**: the victim's memory reaches the attacker, who can also poison it | INV-S8, S9 | Secret in the Parse URL (or basic auth) checked first. If `SPF`/`dkim` ≠ pass → unverified: no memory key, no cc reply | SendGrid Parse configuration (ops) | Low | Webhook tests with and without the secret and with SPF fail | Fix specified |
| B0-18 | studio-backend `auth.py:471-494`; agent-engine `routes.py:1119-1185`; research-runtime `middleware/firebase_auth.py:104` | Platform admin = email ends with `@olbrain.com`; **`email_verified` never read** | Sign up with an unused `@olbrain.com` address through open email/password sign-up: wallet grants to any org, ticket admin, Nexus admin mode, Lumen admin, org-wide metrics | INV-S10 | Require `email_verified is True` **and** `sign_in_provider == "google.com"` with `hd == "olbrain.com"` (or an explicit admin custom claim set by a backend) | Firebase sign-up configuration `[UNRESOLVED]` | Low | Auth unit tests | Fix specified |
| B0-19 | agent-runtime `routers/directives.py:66` (public endpoint, `--allow-unauthenticated`) | `POST /api/agent/send-directive` has **no auth** | Make any agent message any phone with an attacker-written directive, billed to the org, using that user's memory | INV-S9 | Require Google OIDC from allow-listed service accounts (the existing `_verify_webhook_dispatcher_token` pattern) or the internal secret | agent-directives (missing repository) is the caller | Low | Endpoint tests | Fix specified, **caller blocked** (missing repository) |
| B0-20 | mcp-deployer `runtime/main.py:2107-2149`, `auth_middleware.py:61-150` | `tools/call` takes `agent_id` from the body or query. `MCP_REQUIRE_AUTH` defaults to `false`. When on, any allow-listed runtime SA may assert any agent. Empty `agent_id` skips the tool ACL and uses `credentials/default:{server}`. Credential management routes take `agent_id` from the body or path | **Call tools with another tenant's OAuth/KMS credentials** on public projects (cratio, ecommerce, olbrain-test, playwright-recorder, base config) or from any service in the project | INV-S9, S11 | (1) Auth on everywhere, an expected audience, allow-lists. (2) `agent_id` comes from a **short-lived agent-binding token** signed by the calling service for a verified session (or from the verified OIDC subject plus a signed claim). Never from the body. (3) Empty `agent_id` → reject. (4) No `default:` credentials for tenant-scoped servers. (5) Credential management only from studio-backend's SA, after a user org check | Runtimes, workflow-runtime and research-runtime callers mint the token | Medium (every caller changes) | Contract tests on the MCP service; probe with a spoofed `agent_id` → 403 | Fix specified |
| B0-21 | agent-engine `alchemist/agents/lumen/evidence/bigquery.py:16-40` | Tenant isolation is a regex over LLM-authored SQL (`any(m == agent_id …)`) | `OR` / `UNION` / comment / string-literal bypass reads other tenants' log rows (Lane A A9, reproduced on SQLite) | INV-S12 | An authorised view, or BigQuery row-access policy, keyed on the agent with a **bound parameter**. The LLM SQL runs only against that view | BigQuery dataset IAM (ops) | Low | Lane A `test_sec_lumen_*` (structural model passes); staging probe | Fix specified |
| B0-22 | studio-backend `routes/activity_routes.py:55, ~95` | Activity log write (org and actor from the body) and list accept any Firebase user | Forge or read any org's activity feed (it feeds notifications) | INV-S2, S7 | Membership check; ignore `actor_id` for Firebase callers | — | Low | Route tests | Fix specified |
| B0-23 | studio-backend `share_token_service.py:143-242` | Share keys are org-bound live keys pinned to one agent; plaintext on `share_tokens/{id}.api_key`; no expiry in channel mode; 48-bit `short_id` alias | A leaked link becomes a long-lived key (B0-15 shows what it can reach) | INV-S8 | Exchange the token for a short-lived, agent- and session-scoped share credential at validation time. Never return the stored key. Expire channel tokens | Studio share page | Medium | Token tests | Fix specified |
| B0-24 | agent-engine `alchemist/utils/auth.py:94/114` | `require_permission` calls `check_permission` with 4 args where 3 are defined: every `require_agent_access` raises a TypeError (500) | Fails closed, but broken | — | Fix the signature; add tests | — | Low | Unit test | Fix specified |

---

## B. Security invariants (testable)

| ID | Invariant | Tested by |
|---|---|---|
| INV-S1 | **Cross-org reads are denied** on every tenant-scoped collection and subcollection | Probe: every attack row with "read" |
| INV-S2 | **Cross-org writes are denied**, including creating documents that claim another org | Probe: write/create rows |
| INV-S3 | **Agent ownership and tenancy can't be forged or changed by a client**: no client create or delete; `organization_id`/`owner_id`/`userId`/`project_id` are immutable from clients | K1-* probes |
| INV-S4 | **Clients can't create or modify identity bindings**, even in their own org | V2-bindings, V2-own-org-binding |
| INV-S5 | **Clients can't write identity events, dedup or evidence metadata**; unknown new collections are deny-by-default (stage 2) | V2-* probes |
| INV-S6 | **Evidence is server-written only**; a client can't create or alter a message or session | E1-write/create, S-write |
| INV-S7 | **Authorization is server-derived**: every route resolves the resource's org from a server record and checks the caller against it (membership index or key org), never from a body field | B0-12…14, 22 route tests |
| INV-S8 | **A caller can't choose another subject**: memory keys carry channel and assurance; asserted ids never reach verified memory; share credentials are agent- and session-scoped | B0-15/16/23 tests; Lane A `test_M5_*`, `test_C4_*` |
| INV-S9 | **Service-to-service identity is explicit**: every non-user ingress (email parse, directives, MCP, internal routes) authenticates the calling service | B0-17/19/20 tests |
| INV-S10 | **Platform-admin authority needs a verified identity** (`email_verified`, Google-hosted domain, or an admin claim) | B0-18 tests |
| INV-S11 | **No tenant credential resolves without a verified agent binding**; there is no default-credential fallback for tenant-scoped tools | B0-20 contract tests |
| INV-S12 | **LLM-authored queries can't widen their tenant scope**; isolation is structural, never a string check | Lane A `test_sec_lumen_*`; staging probe |
| INV-S13 | **Stale credentials can't bypass current authorization**: membership comes from `memberships_index` on every rule evaluation (no client claim); server routes check membership online for mutating calls (PI-12) | Removing an index row then retrying denies (rules lab: to add); route tests |

---

## C. Executable acceptance tests (emulator)

**What is run.** Every probe action allowed in the Lane A probe now has a regression row in `probe_b0.mjs`. That covers 26 attack rows (the Lane A 15 plus more) and 15 legitimate twins.

**The G-SEC acceptance condition:**
1. every attack is denied;
2. every legitimate twin is still allowed (except K1-forge's twin, removed because clients never create agents);
3. Studio's own **346-test** rules suite passes. The 3 suites that pinned closed gaps are adjusted in `tests-b0/`; the originals are kept, and the reasons are listed in `make_b0_tests.py`.

**Proof that the rule changed rather than the expectation.**
- The **same** probe file runs against `firestore.current.rules` (attacks allowed) and `firestore.b0.rules` (attacks denied).
- The rules differ only by the 129-line diff in `b0.diff`.
- The legitimate twins prove the tightened rules still grant access to members and owners.

**Results:**

| Run | Studio suite | Attacks allowed | Legitimate twins denied |
|---|---|---|---|
| `before` (current production rules) | 346/346 | **24/24** (first run; 26/26 with the K1 additions) | 0 |
| `b0-stage1` | **346/346** (tests-b0) | **1 of 26** (V2-new-collection: by design, stage 2) | **0** |
| `b0-stage2` | **345/346**. The one failure is Studio's own "over-reach control" test, which asserts the catch-all grants read on an unrelated top-level document: the exact default-allow stage 2 removes (intended flip) | **0 of 26** | **0** |

The tests-b0 overlay is required because three Studio suites asserted the old gaps or seeded membership outside `memberships_index` (see `make_b0_tests.py`).

**Server-code fixes (B0-12…24)** can't be proven in the rules emulator. Their acceptance tests (route tests across two orgs and two principal types) are specified per row and must be written in the owning repositories during Lane B. **Until then, G-SEC is not passed.**

---

## D. Repository impact map

| Repository | Changes required in B0 | Items |
|---|---|---|
| olbrain-studio | `firestore.rules` (stage 1 now; stage 2 after the Noesis inventory); client query constraints (`agent_id` or `organization_id` on message, session and usage queries); share page (short-lived credential); rules tests (add the B0 suites) | B0-01…11, 23 |
| olbrain-studio-backend | `require_org_access`; agent create/fork/forks/preflight checks; admin gate (`email_verified`); activity routes; share-token exchange | B0-12, 13, 18, 22, 23 |
| olbrain-agent-design | `require_org_access`; `get_agent`/`list`/`active`/`agent_users`/store install/store admin | B0-12, 14 |
| olbrain-agent-runtime | API-key scope enforcement; share-key route allow-list; `user_id` binding and channel-aware memory keys; email webhook authentication; directive endpoint authentication; agent_memory path/header match | B0-15, 16, 17, 19 |
| olbrain-agent-engine | Lumen structural isolation; admin gates (`email_verified`); `require_permission` signature | B0-18, 21, 24 |
| olbrain-research-runtime | `is_internal_user` → `email_verified` | B0-18 |
| olbrain-mcp-deployer | Auth on, audience, agent-binding token, no default credentials, credential-route authority | B0-20 |
| Callers of MCP (agent-runtime, workflow-runtime, research-runtime) | Mint and send the agent-binding token | B0-20 |
| **Must stay untouched in B0** | The architecture contract; `memory-architecture-v2.md`; identity documents; the memory prototype's semantics; workflow-runtime/finance-engine/knowledge-vault business logic; all data; all deploy configuration except the MCP auth flags and the email Parse secret, which are B0 rollout items for ops | — |
| **Missing repositories (blocking parts of B0)** | olbrain-noesis-os (client inventory for stage 2 and for B0-02/03/09 query compatibility); agent-directives (B0-19 caller); webhook service (`webhook.olbrain.com` pass-through of the share key and `user_id`); Firebase Auth project configuration (B0-18 sign-up providers) | — |

---

## E. Migration and rollout hazards

| Hazard | Effect | Staged mechanism (never re-opens the hole) |
|---|---|---|
| Studio and Noesis queries that the new read rules can't prove (by `session_id` or `project_id` only) | Those screens get permission-denied | **Order:** ship the client query changes first (add the `agent_id`/`organization_id` constraint, harmless under the current rules), then the rules. The rules are not loosened to fit an unscoped query |
| Noesis is unknown | Its unscoped reads may break | Deploy stage 1 to a **staging project**, run Noesis against it, and capture the denials (emulator request coverage report). Fix them client-side, then deploy. Stage 2 (allow-list) only after a full Noesis inventory |
| Legacy `agent_messages` rows without `organization_id` | Readable only through the agent clause | Covered by `canUseAgent(row.agent_id)`. A backfill of `organization_id` (Admin SDK) is a later cleanup |
| Clients that wrote agent tenancy fields | None found (the inventory shows Studio creates agents via the API) | — |
| `memberships_index` drift (a member without an index row loses access) | Real members denied | Run `scripts/backfill_memberships_index.py` (studio-backend) before deploying; alert on denial spikes after deploy. **Not** a fallback to `organizations/*/members`, because members documents were client-forgeable until recently |
| Server routes gaining membership checks | API integrations that relied on a cross-org key break | They were exploiting the hole. Announce, and add per-route tests first |
| Share links | Old links would hold a live key | Validation keeps working; the returned credential becomes short-lived; existing stored keys are revoked after a grace window |
| MCP auth on | Callers without the token fail | Mint and send the token in the callers first (accepted but not required), then enforce per project, starting with the public ones |
| Email webhook secret | Mail drops until the Parse URL is updated | Update the Parse URL to the secret form first, accept both for a short window **only for SPF/DKIM-pass mail**, then require the secret |
| Channel-aware memory keys | Existing memory not found under the new key | A one-time rekey of `agent_user_memory` / datastores, keyed by the channel recorded on the session (registry handler); read old-or-new during the window **only for channel-verified callers** |

---

## F. Gate report (B0 → B1/B2)

**1. Did every G-SEC probe flip from allowed to denied?**
- **Rules (client-SDK) probes: yes, in the emulator.**
  - Stage 1 denies 25 of 26 attacks.
  - Stage 2 denies **26 of 26**.
  - Neither denies any legitimate twin.
  - Studio's suite passes: 346/346 in stage 1, and 345/346 in stage 2 with only the intended flip (`results/`).
- **But G-SEC is not passed.** The fix exists only as a derived rules file in the lab (not deployed). The server-code exposures B0-12…24 have no implementation yet.

**2. Are there any remaining client-controlled tenancy roots?**
- **In rules: no**, under `firestore.b0.rules`. The agent doc's tenancy fields are client-immutable, and membership comes from the server-written index.
- **In server code: yes.**
  - API-key callers can assert `user_id` (B0-16).
  - MCP accepts a caller-asserted `agent_id` (B0-20).
  - studio-backend and agent-design routes accept `project_id`/`organization_id`/`agent_id` without a membership check (B0-13/14/22).
  - The email `from` is trusted (B0-17).

**3. Can any client directly mutate future memory or identity collections?**
- Under B0 stage 1: **no** for the named collections (probes V2-*).
- Under the **current** rules: **yes**. That's why R-1 must not ship before the rules change is deployed.
- Unknown future collections are protected only by stage 2.

**4. Unresolved security dependencies on missing repositories:**

| Repository / system | Needed for |
|---|---|
| olbrain-noesis-os | Client inventory for stage 2 and for read compatibility |
| agent-directives | The B0-19 caller |
| webhook service | The share-key and `user_id` pass-through |
| Firebase Auth project configuration | B0-18 sign-up providers |
| GCP | MCP project ingress and IAM (`allow_unauthenticated` services); deployed-rules confirmation (is `firestore.rules` the file that is deployed?) |

**5. What must be completed before B1/B2 can proceed safely:**
- The B0 stage-1 rules **deployed** (after the client query changes), with the probe re-run against a staging project showing all attacks denied.
- **B0-15, B0-16, B0-17, B0-19** implemented with tests. These are the paths by which a caller chooses another subject or writes evidence, which is exactly what B1 (binding transaction) and B2 (handles) depend on.
- **B0-12/13/14** (org access) and **B0-18** (admin gate), because B2's operator reads depend on a trustworthy user-to-org check.
- **B0-20 and B0-21** can run in parallel with B1/B2: they don't touch the memory write path, but they block G-SEC as a whole.

**6. What evidence is still required for G-ERASE:**
- Handlers for the in-workspace legacy stores (census order), with drills on synthetic data in a staging project.
- The 7 missing-repository stores.
- The consent ledger ahead of the `agent_users` deletion.
- Lumen and BigQuery retention.
- Legal decisions on windows.

None of this was started in B0; it is Lane B3.

**Decision.** Stop at this gate. Do not proceed to B1/B2 implementation until the items in (5) are done.

**Work that can continue now without touching production:**
- write the server-code acceptance tests (B0-12…24) as runnable specifications against local test clients;
- extend the rules lab with INV-S13 (revocation);
- prepare the client query-change list for Studio.

**This report is the hand-off to the repository owners.**


## Addendum (2026-10-01, B0 handoff pass)

- **Probes re-run with 32 rows (previously 26).** The new rows are RU-* (rollups), ORG-doc-read, and the K1 editor cases. Results:

  | Rules | Attacks allowed |
  |---|---|
  | current | 32/32 |
  | stage 1 | 2/32 |
  | stage 2 | **1/32** (ORG-doc-read) |

  No legitimate twin is denied in any run. This supersedes "stage 2 = 0/26" above.
- **Rollup trees were cross-tenant readable** through the 4-segment catch-all (VERIFIED CURRENT). Affected: `organization_analytics`, `project_analytics`, `workflow_analytics`, `billing_aggregates`, `agent_analytics/**`. They are now org-scoped in the lab rules, with collection-group `months/days/hours` readers. This assumes every rollup doc carries `organization_id` (analytics-service is a missing repository).
- **B0-25 (VERIFIED CURRENT):** `organizations/{org}` documents are readable by any signed-in user (studio rules L418). This is left open in the lab because the invite and onboarding flows depend on it. See the query audit §3 and the handoff matrix.
