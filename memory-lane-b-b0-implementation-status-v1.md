# Lane B / B0: Implementation Status v1

**Date:** 2026-10-02.

**Scope:**
- Local implementation on the `b0/security` branches.
- **Nothing pushed, deployed or migrated.** Push is disabled in every workspace repository (`pushurl = DISABLED-no-push-b0-investigation`).
- No cloud credentials were present in the environment.
- Tests used only fakes, SQLite, and the local Firestore emulator with `demo-*` projects.

**Contract documents:**
- [`lane-b/b0-impl-contracts.md`](lane-b/b0-impl-contracts.md): C1–C10. C10 was added during implementation for B0-29.
- [`memory-lane-b-b0-blockers-v1.md`](memory-lane-b-b0-blockers-v1.md): everything code here cannot resolve.

## 1. Headline

### Acceptance suite (`investigation/lane-b/acceptance`, 74 tests)

| Target | Result |
|---|---|
| `current` (`origin/main`) | 62 RED / 12 GREEN (unchanged baseline) |
| `reference` (spec) | 73 GREEN / 1 skipped |
| **`owner`** (real `b0/security` code, `owner.py` aggregating `owner_parts/*`) | **57 GREEN / 16 RED / 1 skipped** |

- **The 16 RED tests are exactly B0-14 (8) and B0-20 (8).** Their implementation was **not started**: the session's permission classifier refused to launch it (blockers §1).
- **Control run:** the owner adapter pointed at `origin/main` (`B0_OWNER_REF=origin/main`) errors on all 73 tests. The GREEN results therefore come from branch code.
- **WIRING-ONLY entries** (real decision code; route wiring proven by a named repository test): 9 in `owner_parts/agent_runtime.py`, 1 in `owner_parts/studio_backend.py`, 0 in `agent_engine.py`.

### Firestore rules

These are the repository's own `firestore.rules`, run in the emulator (lab labels `repo-c10-*`). The probe set grew to 51 rows, adding the B0-25, `share_credentials` and C10 cases.

| Rules | Attacks allowed | Legitimate twins denied | Revocation | Studio rules suite |
|---|---|---|---|---|
| Current production | **51/51** | — | 0/12 hold | — |
| B0 stage 1 (`firestore.rules`) | **1/51** (V2-new-collection: stage 2 by design) | 0 | **12/12** | **456/456** |
| B0 stage 2 (`firestore.stage2.rules`, not deployable) | **0/51** | 0 | **12/12** | 454/456. The 2 failures are intended flips: the catch-all "over-reach control", and the stage-1 V2 pin |

The repository rules suite holds 62 attack rows and about 25 legitimate twins. Every earlier expectation still holds.

## 1b. Evidence provenance and harness changes

- **Re-run by the coordinator:**
  - the acceptance targets (`current`, `reference`, `owner`, and `owner` against `origin/main`);
  - the repository-rules probe JSONL counts;
  - the commit lists;
  - the direct source reads for B0-28c, B0-30 and B0-31.
- **Reported by the implementing agents, not re-run by the coordinator:**
  - the repository suite counts (§3);
  - the Studio rules-suite counts;
  - the revocation counts.
- **Studio's full Jest suite was not re-run by anyone after `22b25b50`.**
- **Harness change by the coordinator:** `owner_parts/studio_backend.py` `share_validate` records the World's session label (`sess_1`) mapped onto the server-minted `shs_…` id. The real service ignores client-invented session ids, which is stricter than C4. The binding check itself is unchanged; the runtime still rejects another session or agent. No test, `world.py`, `reference.py` or `current.py` was edited.
- **Extractor change:** `extract.py` gained a `ref=` parameter, and `OWNER_REF` defaults to `b0/security`. The `current` result is unchanged (62/12).
- **Local git configuration change:** `remote.origin.pushurl` was set to `DISABLED-no-push-b0-investigation` in all 13 workspace repositories. This is reversible.

## 2. Commits (local, `b0/security`)

| Repository (base) | Commits |
|---|---|
| olbrain-studio (`1f05ca11`) | `e16f2e48` rules stage 1, B0-25, share_credentials · `eb018f0e` org-scoped queries and dead-code deletion · `2ac0b906` B0-25 client · `53aa5da9` B0-23 share page · `22b25b50` test fix · `16c7747c` B0-29/C10 rules |
| olbrain-studio-backend (`5da93ae`) | `149e417` B0-12/13/18 · `9838f54` B0-22/23/25 · `07db37f` C8 revocation · `684b32a` B0-28 · `2e47a29` B0-29/C10 · `33c5dc8` B0-28b |
| olbrain-agent-runtime (`daee3f9`) | `c745a85` B0-15/16/17/19/23-runtime/20-caller · `4b20e9e` test fakes |
| olbrain-agent-engine (`dfc3a47`) | `ac12593` B0-18/21/24 · `0c75915` Lumen hardening · `92e262b` composite indexes |
| olbrain-agent-design, olbrain-mcp-deployer, olbrain-research-runtime, olbrain-workflow-runtime | **none** (blocked) |

## 3. Repository suites (before → after)

Pre-existing failures are tracked separately and were not touched.

| Repository | Before | After | Notes |
|---|---|---|---|
| studio-backend | 3574 passed / 6 failed / 1 skipped | **3679 / 6 (same six) / 1** | 105 new tests. Private wheels were stubbed outside the repository |
| agent-runtime | 5308 passed / 135 failed / 1 error | **5453 / 135 (same) / 1** | 145 new tests. The 135 come from missing private packages or the environment |
| agent-engine | 3962 passed / 20 failed | **4022 / 20 (same)** | `olbrain_llm` was stubbed in the venv only |
| studio (Jest) | 49 failed (pre-existing) | 50 → the extra one was fixed in `22b25b50`. **The full suite was not re-run after that fix** | Touched-file set: everything green except the pre-existing `sourceSeries` "hourly" test |

## 4. Per finding

**Column key:** *Before* = `current` acceptance result or probe; *After* = `owner` acceptance result or repository-rules probe.

| Finding | Status | Files changed (main) | Tests added/changed | Before → after | Remaining dependency | Staging requirement | Decision |
|---|---|---|---|---|---|---|---|
| B0-01…11 rules | **DONE (stage 1); stage 2 file kept separate** | studio `firestore.rules`, `firestore.stage2.rules` | `tests/firestore-rules/firestore.b0-probes.rules.test.js`, `…b0-revocation…`; 9 suites re-seeded with `scope` | 51/51 → 1/51 (stage 1), 0/51 (stage 2) | Backfill first (C10); Noesis inventory for stage 2 | Probes, revocation and Studio/Noesis smoke tests on staging | — |
| Studio queries (audit §2.1) | **DONE** | `usageService.js` (`_orgOfProject`), `DashboardContent.js`, `projectService`/`FirestoreDataAccess` `getProjectAgents`, `OrgProjectsContent.js` (missed by the audit) | `usageService.orgScope.test.js`, `perType` | Unscoped → org-scoped. An unknown org returns the empty shape, never an unscoped query | **Indexes built first** (agent-engine `firestore.indexes.json`, 6 entries; the `hours` and `days(month)` entries were also missed by the audit) | Additive build with `scripts/sync_firestore_indexes.py`, **never** `firebase deploy --only firestore:indexes` | — |
| Dead queries (§2.3) | **DONE** (deleted; 2 fixed) | usageService, data access, DataCacheContext, handoffService, messagesService, analyticsService, organizationService | — | — | — | — | — |
| C8 revocation (INV-S13) | **DONE** | studio-backend `membership_service.py` (`revoke_org_scoped_grants`, `remove_member`) | `test_b0_membership_revocation.py`; rules revocation hazard tests | **Source bug found:** `remove_member` never re-synced the index, so removed members kept access (CONTRADICTED BY SOURCE) | One-off C8 sweep for removals made before B0 | Staging drill | — |
| B0-12 | **DONE** (studio-backend). The agent-design half is **NOT STARTED** | `middleware/auth.py` `require_org_access`, `require_agent_view/edit` | `test_b0_org_access.py` | 4 RED → 6/6 GREEN | agent-design (blocked) | Route tests on staging | — |
| B0-13 | **DONE** | `agent_service.py`, `agent_routes.py` | Route tests (2 orgs × user/key) | 5 RED → 6/6 | — | Cross-org fork → 403 | — |
| B0-14 | **NOT STARTED** (blocked) | — | — | 7 RED → 8 RED | User authorisation | — | — |
| B0-15 | **DONE** | runtime `core/route_scope.py`, `api_key_middleware.py` | `test_b0_route_scope_middleware.py` | 8 RED → 10/10 | **Key scopes:** studio-backend `AccessKeyScope` has no `leads:*` or `agents:read/write`, so no existing key reaches leads or memory routes (fail closed) until keys are re-issued | Share key → leads export 403 | Owner: add the scopes |
| B0-16 | **DONE for the API-key and share paths** (no rekey). **INV-S8 is NOT closed while B0-26 is open:** unsigned Meta webhooks let a forger claim `channel_verified` for a victim's phone | runtime `core/memory_subject.py`, webhook, processor, memory service, GDPR routes | `test_b0_memory_subject.py`, `test_b0_webhook_memory_subject.py` | 3 RED → 4/4 | Legacy-key window flag `MEMORY_LEGACY_KEY_READ` | Asserted WhatsApp number via the API → no memory | **BLOCKED:** trusted id assertion (Product/Security); legacy-key retention (Legal) |
| B0-17 | **DONE in code**; live SendGrid unvalidated | runtime `core/email_inbound.py`, `routers/email.py` | `test_b0_email_inbound.py` (fixtures) | 4 RED → 5/5 | Ops: Parse URL secret before deploy. Follows C6 fail-closed, which supersedes §E "accept both" | SendGrid SPF pass and fail mails | Strict DKIM alignment (marked `ponytail:`) |
| B0-18 | **DONE** in studio-backend and engine (incl. `get_metrics_scope`, `require_olbrain_identity`). The research-runtime gate is **NOT STARTED** | studio-backend `auth.py` `is_platform_admin`; engine `alchemist/utils/auth.py`, `routes.py` | `test_auth_domain_gate.py` (+13 cases); studio-backend admin tests | 4 RED → 5/5 | **No backend sets an `admin` claim today.** Staff admin depends on the `hd` claim being present in Google ID tokens `[UNVERIFIED]` | Staging token check, or **staff lockout** | Security: Google SSO confirmation |
| B0-19 | **DONE in runtime**; integration **BLOCKED** | runtime `routers/directives.py`, `core/directive_auth.py`, middleware | `test_b0_directives_auth.py` | 3 RED → 4/4 | agent-directives (missing repository) must send OIDC; env `DIRECTIVES_AUDIENCE` / `DIRECTIVES_ALLOWED_SERVICE_ACCOUNTS` | Unauthenticated POST → 401 | Cold outreach to numbers with no `agent_users` row is now denied |
| B0-20 | **Caller side DONE in agent-runtime only.** The MCP service and the workflow-runtime/research-runtime callers are **NOT STARTED** (blocked) | runtime `core/mcp/agent_binding.py`, `mcp_client.py`, providers | `test_mcp_agent_binding.py` (shared vector) | 8 RED → 8 RED | User authorisation; Security: KMS/signing; `aud` = catalog server key | Spoofed agent → 403; ingress review | Security |
| B0-21 | **DONE in code**; BigQuery unproven | engine `lumen/evidence/bigquery.py`, `bigquery_service.py`, prompts | `test_lumen_bq_isolation.py` (5 forms, 21 escape forms) | 5 RED → 6/6 (**SQLite stand-in**) | Ops: authorised view, IAM, `LUMEN_BQ_AGENT_LOG_VIEW`. **The tool stays off (fail closed) until then** | `docs/security/lumen-isolation-staging.md` probe | Open: separate service account for Lumen if Axon's has raw `dataViewer` |
| B0-22 | **DONE** | `activity_routes.py` | Route tests | 3 RED → 3/3 | — | — | Actor is forced for API keys too (stricter) |
| B0-23 | **DONE** (backend issue + runtime accept + Studio page) | studio-backend `share_token_service.py`; runtime middleware; studio `SharedAgentChat.js`, `shareTokenService.js` | Token tests; wire tests | 5 RED → 5/5 | **Ship order:** runtime accept, then studio-backend and Studio together. Webhook service must forward `shc_` (missing repository). Stored keys are not yet revoked (grace window) | Old link → new credential; `api_key` never returned | **Product:** `SHARE_CREDENTIAL_TTL_SECONDS`; new `SHARE_CHANNEL_TOKEN_MAX_AGE_DAYS` (old channel links break past the max age) |
| B0-24 | **DONE** | engine `alchemist/utils/auth.py` (signature, `memberships_index` role lookup, `super_admin`), `errors.py`, `storage_service.py` | `test_utils_auth_permissions.py` | 3 RED (TypeError) → 3/3 | Permission names `agents:*` ↔ `agent:view/edit` are mapped only in the adapter | — | — |
| B0-25 | **DONE** | studio rules (`organizations` member-only, catch-all exclusion); invitationService, Onboarding; studio-backend invitation preview narrowed | Rules probes; 4 invitation tests | ORG-doc-read allowed → **denied** (member twin allowed) | Noesis org-doc reads unknown | Invite/onboarding smoke | **Studio owner to confirm:** member-only doc + backend preview (wallet and runtime not moved) |
| **B0-28** (new) | **DONE** | `agent_service._require_org_member`, agent/store routes | `test_b0_28_api_key_org_binding.py` | Cross-org key 200 → 403 | — | — | — |
| **B0-28b** (new) | **DONE for the assigned surfaces** | `access_control.build_access_request` (root), `analytics_authorization`, llm-key, connector, key-management, transfer, caller-channel routes | `test_b0_28b_api_key_creator_uid.py` (29) | RED → GREEN | — | Warn integrations: these routes now refuse API keys or bind them to the key's org | — |
| **B0-28c** (new, OPEN) | **NOT FIXED** | — | — | **OPEN QUESTION** (sub-audit, not re-verified): org owner/admin mutations via `check_user_permission(uid)`, project/user/template routes, uid==path impersonation. **VERIFIED CURRENT by direct reading:** `GET whatsapp-config` (no org check), `GET /api/analytics/power-users` (any signed-in user, platform-wide), `POST access-keys/{id}/log-event` (no ownership check), `POST /api/internal/tickets/{id}/resolved-notify` (any Firebase user), `GET …/organization/{org}/deleted` (Firebase callers unchecked). The severe ones are split out as B0-30 and B0-31 | Owner decision: reject API keys by default, with a per-route opt-in scope | — | Studio-backend owner / Security |
| **B0-30** (new, VERIFIED CURRENT on `origin/main` 5da93ae) | **NOT FIXED** | — | — | `PUT /api/organizations/{org}` and `POST …/whatsapp-config` → `organization_service.update_organization`, which only requires a signed-in user (`services/organization_service.py:263`: "Permission check removed - any authenticated user can update organizations"). **Any signed-in user can update any org** | Studio-backend owner | Two-org route test | — |
| **B0-31** (new, VERIFIED CURRENT) | **NOT FIXED** | — | — | `POST /api/organizations/{org}/members/accept` takes `invitation_email` from the **body** and never compares it with the authenticated email (`organization_service.accept_invitation` ~L1409). **Anyone can claim another person's pending invitation** and join with its role | Studio-backend owner | Route test | — |
| **B0-29** (new, VERIFIED CURRENT) | **DONE** (server + rules) | studio-backend `sync_org_membership_index`, `auth.py`, backfill script; studio rules `orgIndexScoped`, `agent_access` | `test_b0_29_index_scope.py`; backfill tests; 10 rules probes | Agent-only admin collaborator reads `billing_ledger` today → denied | **Deploy order: backfill → studio-backend → rules.** Untyped memberships must count 0. Agent memberships written by other services need a resync | Staging backfill dry run | Product: should project collaborators keep org-wide read (today via the org `member` row) |
| **B0-26** (new, OPEN) | **NOT FIXED** | — | — | Meta `X-Hub-Signature` is not verified on the WhatsApp/Instagram webhooks, so "channel_verified" is only as strong as that gap | Runtime owner | — | — |
| **B0-27** (new, OPEN) | **NOT FIXED** | — | — | A verified email sender who forges `In-Reply-To` can join another verified thread's session | Runtime owner | — | — |

## 5. Gate states

| Gate | State | Why |
|---|---|---|
| **1. Local code gate** | **NOT PASSED** | 57/73 acceptance tests are GREEN on real code. B0-14 and B0-20 (16 tests) are not implemented (blocked). B0-26/27/28c are open. All implemented findings are GREEN, with repository suites showing no new failures |
| **2. Staging rules gate** | **NOT PASSED (not run)** | In the emulator: stage 1 has 1/51 attacks allowed (by design), 0 twins denied, 12/12 revocation, 456/456 suite. It has never run on a staging project. It needs the backfill, the indexes and the studio-backend C10 build first. Stage 2 is held for Noesis |
| **3. Infrastructure gate** | **NOT PASSED** | Indexes, backfill, BigQuery view/IAM, SendGrid secret, MCP ingress, Firebase `hd`, env values: none done (blockers §7) |
| **4. G-SEC overall** | **NOT PASSED** | Remaining client-controlled tenancy or identity roots: **B0-30 (any user updates any org)**, **B0-31 (invite claim)**, B0-20 (MCP `agent_id`), B0-14 (agent-design routes), B0-26 (unsigned Meta webhooks, which also leaves INV-S8 open), B0-28c. Missing repositories are unresolved and not formally accepted |

**Stop.** B1/B2, the Memory Gateway, the PG schema, migration and shadow writes were **not** started.
