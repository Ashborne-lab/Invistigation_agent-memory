# Lane B / B0: Implementation Handoff v1

**Date:** 2026-10-01.

**Audience:** the owners of olbrain-studio, olbrain-studio-backend, olbrain-agent-design, olbrain-agent-runtime, olbrain-agent-engine, olbrain-research-runtime and olbrain-mcp-deployer, and the security and ops owners.

**Status of this document:** investigation output. Nothing here has been implemented, deployed or merged.

**Companion documents:**
- [`memory-lane-b-security-b0-v1.md`](memory-lane-b-security-b0-v1.md): the findings and their evidence;
- [`memory-lane-b-b0-acceptance-tests-v1.md`](memory-lane-b-b0-acceptance-tests-v1.md): the tests, RED → GREEN;
- [`memory-lane-b-b0-query-audit-v1.md`](memory-lane-b-b0-query-audit-v1.md): the Studio query changes that must ship before the rules.

**Notation:**
- **AT** = acceptance test in `investigation/lane-b/acceptance/` (`test_B0_xx_*`).
- **RP** = rules probe row in `rules-lab/probe_b0.mjs`.
- **RV** = revocation case in `rules-lab/probe_revocation.mjs`.
- **G-SEC condition** = what must be observed in staging for the finding to count as closed.

## 1. Implementation matrix

| Finding | Invariant | Repository / file | Acceptance test (must go RED → GREEN) | Implementation change | Dependency | Rollout hazard | Staging verification | G-SEC gate condition |
|---|---|---|---|---|---|---|---|---|
| B0-01…11 (rules) | INV-S1…S6, S13 | studio `firestore.rules` | RP: 32 attack rows. Stage 1 denies 30/32 (ORG-doc-read = B0-25, V2-new-collection = stage 2); 16 legit twins allowed. Rollup trees (`organization_analytics`, `project_analytics`, `workflow_analytics`, `billing_aggregates`, `agent_analytics/**`, collection-group `months/days/hours`) are now org-scoped (RU-* rows), and **assume every rollup doc carries `organization_id`** (writer = analytics-service, missing repository); Studio suite green (`tests-b0`); RV: 12/12 | Apply `rules-lab/make_b0_rules.py` stage 1 (the diff `rules-lab/b0.diff`) to `firestore.rules`. Port `tests-b0` changes and `probe_b0.mjs`/`probe_revocation.mjs` into `tests/firestore-rules/` | **The query audit's MUST-change queries ship first** | Screens whose queries can't be proved get permission-denied | Deploy to a staging Firebase project; run `probe_b0.mjs` and `probe_revocation.mjs` against staging; run Studio and Noesis smoke tests; watch rule-denial counts | Every RP attack denied **except** ORG-doc-read (closed by the B0-25 row) and V2-new-collection (closed by the stage-2 row); every legit twin allowed; RV 12/12; no denial spike in Studio smoke tests |
| B0-11 stage 2 | INV-S5 | studio `firestore.rules` | RP V2-new-collection (lab: stage 2 denies 31/32, only ORG-doc-read open); Studio suite 345/346, the one failure being the intended flip of `over-reach control › the two-segment catch-all still grants read` | `make_b0_rules.py --stage2` (allow-list) | **Noesis client inventory (missing repository)** | Unknown Noesis collections denied | As above, plus the Noesis smoke test | V2-new-collection denied; Noesis green |
| B0-12 | INV-S7 | studio-backend `middleware/auth.py`; agent-design `app/middleware/auth.py` | AT `test_B0_12_*` (6) | Add `require_org_access(user, org_id)`: API key → `org_id == key.org`; Firebase → `check_membership_exists`; else deny. Callers derive `org_id` from the **resource** (agent/project record), never the body | None | None by itself (call sites change in B0-13/14/22) | Unit tests in each service | AT green in the owner adapter |
| B0-13 | INV-S2, S7 | studio-backend `routes/agent_routes.py` :65, :128, :191, :212; `services/agent_service.py` :115, :613, :796-1040, :1255; `services/store_studio_calls.py:342` | AT `test_B0_13_*` (6) | Create: `require_org_access(project org)` for Firebase users too. Forks/preflight/fork: `check_view_permission(source)` and `require_org_access(target project org)`. `_extend_knowledge_access` only after both pass | B0-12 | Cross-org forks that worked before now fail (they were the exploit) | Route tests with two orgs in staging | AT green; manual: a stranger's fork of an org-B agent → 403 |
| B0-14 | INV-S1, S2, S7, S10 | agent-design `app/routers/agent.py` :103, :172-177, :563, :1043; `services/agent_service.py` ~834, 1978-1983; `routers/agent_user.py` :44-161 + `services/agent_user_service.py`; `routers/store.py` :95, :231-275 | AT `test_B0_14_*` (8) | `get_agent`/`model`: replace `pass` with `check_view_permission`. `list_agents`: resolve the project's org, then `require_org_access` (also for API keys). `active`: `require_org_access`. `agent_users`: load `agents/{agent_id}`, `check_edit_permission` (writes) / view (reads), and assert `row.agent_id == agent_id`. Install: `require_org_access(project org)`. Store admin: B0-18 admin gate | B0-12, B0-18 | API keys listing another org's project now fail | Route tests | AT green |
| B0-15 | INV-S7, S8 | agent-runtime `core/api_key_middleware.py` ~515-627; `routers/leads*` (:479-879); `routers/agent_memory.py` :48-109 | AT `test_B0_15_*` (10) | Enforce `key.permissions` against a per-route scope table. Share keys (`metadata.share_token_id`) only on webhook, upload-attachment, feedback and session-insights. Memory routes: `path agent == X-Agent-ID == scoped_agent_id` | None | Integrations using under-scoped keys | Middleware tests; staging call with a share key to the leads export → 403 | AT green; a staging share key cannot export leads or read memory |
| B0-16 | INV-S8 | agent-runtime `routers/agent_webhook.py` ~2660-2746; `core/cs_packet_builder.py:1972`; `core/lightweight_processor.py` ~4152; `services/agent_memory_service.py:92` | AT `test_B0_16_*` (4) | Share keys: override `user_id` to `share_<token>_<chat>`. Memory key = `memory_doc_id(agent, f"{channel}:{assurance}:{user}")`; asserted (API/share) never equals channel-verified | **Owner decision (Lane A M-5):** may an org's server assert trusted ids? Default **no** | Existing memory keyed without a channel is not found | A one-time rekey using the session's recorded channel (a registry handler). During the window, read old-or-new **only for channel-verified callers** | AT green; staging: asserting a WhatsApp number through the API returns no memory |
| B0-17 | INV-S8, S9 | agent-runtime `routers/email.py` :56-138, :311 | AT `test_B0_17_*` (5) | Secret in the Inbound Parse URL (or basic auth), checked first. `SPF`/`dkim` ≠ pass → unverified: no memory subject, no reply carrying memory | Ops: SendGrid Parse URL update | Mail dropped until the URL is updated | Two-step rollout: accept the secret, update the URL, then require the secret. SendGrid test mails with SPF pass and fail | AT green; staging spoof mail gets no memory |
| B0-18 | INV-S10 | studio-backend `middleware/auth.py:471-494`; agent-engine `routes.py:1119-1185` (3 helpers); research-runtime `app/middleware/firebase_auth.py` `is_internal_user` | AT `test_B0_18_*` (5 + the current-only gate test) | Require `email_verified is True` **and** `firebase.sign_in_provider == "google.com"` with `hd == "olbrain.com"`, **or** an explicit backend-set admin claim | **Security owner:** confirm Google SSO is the staff sign-in; check the Firebase console sign-up providers | Staff using password accounts lose admin | Staff migrate to Google SSO first | AT green; an unverified `@olbrain.com` password account is denied in staging |
| B0-19 | INV-S9 | agent-runtime `routers/directives.py:66` (remove from `public_endpoints`) | AT `test_B0_19_*` (4) | Google OIDC from allow-listed service accounts (the `_verify_webhook_dispatcher_token` pattern). The target must be an `agent_users` row of that agent and not opted out | **agent-directives (missing repository)** must send OIDC | Directives fail until the caller sends OIDC | Caller first, then enforce | AT green; an unauthenticated staging POST → 401 |
| B0-20 | INV-S9, S11 | mcp-deployer `runtime/auth_middleware.py`, `runtime/main.py` :494-720, :1558-1632, :2107-2149, :2228-2311; `config/projects/*/project.yaml`; callers in agent-runtime, workflow-runtime, research-runtime | AT `test_B0_20_*` (7) | Auth required everywhere; `MCP_EXPECTED_AUDIENCE` set. **Agent from a signed short-lived binding** (minted by the calling service for a verified session; claims agent, org, aud=server, exp). Body/query agent must equal the binding or the call is rejected. Empty agent → reject. No `default:` credentials for tenant-scoped servers. Credential routes accept only studio-backend's SA plus a user edit check | **Security owner:** choose the binding format and key custody (KMS) | Every caller changes; public projects (cratio, ecommerce, olbrain-test, playwright-recorder, base) need ingress review | Callers send the binding (accepted, not required), then enforce per project, public projects first | AT green; a spoofed `agent_id` in staging → 403; ingress no longer `allow_unauthenticated` for tenant tools |
| B0-21 | INV-S12 | agent-engine `alchemist/agents/lumen/evidence/bigquery.py:16-40`; BigQuery dataset `service_logs` IAM | AT `test_B0_21_*` (6) | The LLM SQL runs only against an authorised view or row-access policy keyed on the agent, with the agent bound **as a parameter by the server**. Keep the regex only as a lint | Ops: BigQuery IAM | None for tenants; admin dashboard rollups need their own role | Staging probe: the 5 adversarial SQL forms against the view | AT green; staging probe returns no foreign rows |
| B0-22 | INV-S2, S7 | studio-backend `routes/activity_routes.py:55, ~95`; `services/activity_service.py` | AT `test_B0_22_*` (3) | `log_activity`: Firebase callers need `require_org_access(body org)`, and `actor = user` (ignore `actor_id`). `list_activities`: `require_org_access`. Internal-service callers keep `actor_id` | B0-12 | None legitimate | Route tests | AT green |
| B0-23 | INV-S8 | studio-backend `services/share_token_service.py:143-242` + validate; studio `src/pages/chat/SharedAgentChat.js` | AT `test_B0_23_*` (5) | Validation exchanges the token for a **short-lived credential bound to agent and session**, never the stored key. Expire channel tokens; retire the 48-bit `short_id` alias or rate-limit it | **Owner/product:** the TTL value `[UNMEASURED]` | Old links keep validating but receive the new credential; stored keys revoked after a grace window | Studio share page uses the exchanged credential | AT green; a stored key is never returned in staging |
| B0-24 | INV-S7 | agent-engine `alchemist/utils/auth.py:94-130`, callers `storage_service.py` :161, :391, :474, :533 | AT `test_B0_24_*` (3) | Fix the signature to `check_permission(db, user, org, perm)`, **and** replace the `get_user_permissions` TODO (returns `[]`) with a membership-role lookup; deny as an explicit 403 | None | Storage routes that 500 today start returning data, so they must be correct first | Unit tests | AT green |
| B0-25 (new, from the query audit) | INV-S1 | studio `firestore.rules` L418 (`organizations/{org}` read: `isAuthenticated()`); studio `invitationService.js:394`, `Onboarding.js:898`; studio-backend (new invite-preview endpoint) | RP ORG-doc-read (allowed today and under B0 stages 1 and 2) | Restrict the org-doc read to `isOrgMember(orgId)`. Serve invitees through a backend endpoint (invitation token → display name only), **or** move wallet and runtime into a member-only subcollection | **Studio owner decision** (which of the two approaches) | Invitees and onboarding cannot see the org name until the endpoint ships | Invite flow and onboarding smoke tests in staging | ORG-doc-read denied; invite and onboarding work |

## 2. Prerequisites before the owners begin

1. **Confirm the deployed rules file.** It must be `olbrain-studio/firestore.rules` at `1f05ca11` or later. That confirmation is `[UNRESOLVED]`, since there is no deploy configuration in the workspace.
2. **Run `scripts/backfill_memberships_index.py`** (studio-backend) in staging, then production, before any rules deploy. Members without an index row would lose access.
3. **The Studio query changes** in the query audit (§2.1: 11 live call sites, one of them conditional, in `usageService.js`, `DashboardContent.js` and `FirestoreDataAccess.js`, plus 3 collection-group composite indexes and 1 agents index) are merged and deployed **before** the rules. They are harmless under the current rules.
   - **Product question:** do users exist who reach an agent only through project or team membership? If so, the evidence rules need a project-member clause (query audit §4).
   - **Analytics-service owner:** confirm every rollup document carries `organization_id`.
4. **A staging Firebase project** with the B0 rules, for running `probe_b0.mjs`, `probe_revocation.mjs`, Studio smoke tests and, once available, Noesis.
5. **The missing repositories**, for the parts that depend on them:
   - olbrain-noesis-os: stage 2, and read compatibility;
   - agent-directives: the B0-19 caller;
   - the webhook service: the share pass-through.
6. **Owner and security decisions:**

   | Decision | Owner |
   |---|---|
   | Binding format and key custody | Security (B0-20) |
   | Staff sign-in = Google SSO | Security (B0-18) |
   | Trusted assertion of end-user ids by an org's server (default no) | Product / Security (B0-16) |
   | Share credential TTL | Product (B0-23) |
   | Org-doc read: invite endpoint, or field split | Studio owner (B0-25) |

7. **Revocation completeness.** The studio-backend membership-revoke path must also delete `projects/{p}/members/{uid}` and remove the uid from `agents.team_access.team_member_ids`. Both also grant agent read under B0 (acceptance doc §5).
8. **Ops:** the SendGrid Parse URL secret (B0-17); BigQuery IAM for Lumen (B0-21); MCP project ingress review (B0-20).

## 3. Ordering (dependency graph)

```text
backfill memberships_index ─┐
Studio query changes ───────┼─► rules stage 1 (B0-01…11) ─► [Noesis inventory] ─► rules stage 2
                            │
B0-12 helper ─► B0-13, B0-14, B0-22                (parallel, per service)
B0-18 admin gate ─► B0-14 store admin
B0-15 scope ─► B0-23 share exchange ─► Studio share page
B0-16 memory key ─► rekey handler (registry)       (Lane A decisions already settled)
B0-17 email (ops URL) · B0-19 directives (caller repo) · B0-20 MCP (callers + security decision)
B0-21 Lumen (ops IAM) · B0-24 engine helper · B0-25 org-doc (invite endpoint)
                            ▼
G-SEC: every RP/RV/AT green in staging + no regression in Studio/Noesis smoke tests
```

**B1/B2 must not start before:** rules stage 1 is deployed, and B0-15/16/17/19 are closed (the subject-selection and evidence-write paths B1/B2 depend on).

**B0-20 and B0-21 may run in parallel with B1/B2,** but they block G-SEC as a whole.
