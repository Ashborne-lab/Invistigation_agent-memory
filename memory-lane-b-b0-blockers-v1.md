# Lane B / B0: Blockers v1

**Date:** 2026-10-02.

**Companion:** [`memory-lane-b-b0-implementation-status-v1.md`](memory-lane-b-b0-implementation-status-v1.md).

This document is the single list of everything that keeps G-SEC from passing that **code in this workspace cannot resolve**. Each item names who has to resolve it.

## 1. Session permission blocks (implementation not started)

The tool-permission classifier ("modify shared resources") refused to launch implementation work for these items in this session. That decision was not worked around. **The user must authorise it** before the work is done.

| Finding | Repository | What is waiting |
|---|---|---|
| B0-14 (and the agent-design half of B0-12) | olbrain-agent-design | `require_org_access`, `get_agent`/list/active/agent_users/install/store-admin |
| B0-20 | olbrain-mcp-deployer, plus the workflow-runtime and research-runtime callers | Binding verifier, auth-always, no default credentials, credential-route authority, caller minting |
| B0-18 (research-runtime gate) | olbrain-research-runtime | `is_internal_user` → C2 |

## 1b. Open findings discovered during implementation (not fixed)

| Finding | Repository | Summary | Who decides or acts |
|---|---|---|---|
| **B0-30** (VERIFIED CURRENT) | studio-backend | `PUT /api/organizations/{org}` (and `whatsapp-config` POST): **any signed-in user can update any org** (`organization_service.py:263`, "Permission check removed") | Studio-backend owner: **urgent, live in production** |
| **B0-31** (VERIFIED CURRENT) | studio-backend | `members/accept` takes the invite email from the body and does not bind it to the caller: **claim anyone's pending invite** | Studio-backend owner: **urgent** |
| B0-26 | agent-runtime | Meta `X-Hub-Signature` not verified on the WhatsApp/Instagram webhooks; "channel_verified" depends on it. **B0-16 / INV-S8 stays open until this is fixed** | Runtime owner |
| B0-27 | agent-runtime | A verified email sender can forge `In-Reply-To` and join another verified thread | Runtime owner |
| B0-28c | studio-backend | OPEN QUESTION (sub-audit): org owner/admin mutations, project/user/template routes by creator uid; uid==path impersonation. VERIFIED CURRENT: whatsapp-config GET, power-users, log-event, resolved-notify and deleted-agents (Firebase) lack org or ownership checks | Owner/Security: reject API keys by default, with a per-route opt-in; then a fix sweep |

## 1c. Deploy ordering (hard)

1. Build the composite indexes (agent-engine file, additive sync script only).
2. Run the `memberships_index` backfill with the C10 filter in staging (dry run: untyped memberships = 0), then apply.
3. Ship agent-runtime (`shc_` accept, scopes), then studio-backend, then Studio.
4. Deploy the stage-1 rules.
5. Re-sync agent memberships written by other services.
6. Stage 2 only after the Noesis inventory.

## 2. Missing repositories

| Repository | Blocks | Formal acceptance needed from |
|---|---|---|
| olbrain-noesis-os | Stage-2 rules (allow-list); compatibility of its browser reads with stage 1 | Studio / Noesis owner |
| agent-directives | B0-19 caller must send Google OIDC | Directives owner |
| Webhook service (`webhook.olbrain.com`) | Pass-through of the share credential (C4) and of `user_id` | Runtime owner |
| analytics-service | Confirmation that every rollup document carries `organization_id` (the rollup rules assume it) | Analytics owner |
| Private wheels (`olbrain_llm`, `olbrain_agent_shared`, `olbrain_usage_shared`) | Full repository suites; they were stubbed locally | Platform owner |

## 3. Security decisions

| Decision | Finding | Default applied in code |
|---|---|---|
| MCP binding signing scheme and key custody (KMS, rotation) | B0-20 | HMAC-SHA256 behind one function; key from env; **fail closed** without a key |
| Staff sign-in = Google SSO with `hd=olbrain.com` (or an explicit admin claim) | B0-18 | C2 enforced; no fallback. **No backend sets an `admin` claim today**, so staff are locked out if `hd` is absent |
| Trusted end-user id assertion by an org's server | B0-16 | **No** (asserted ids never reach verified memory); no opt-in built |

## 4. Product decisions

| Decision | Finding | Default applied in code |
|---|---|---|
| Share credential TTL | B0-23 | `SHARE_CREDENTIAL_TTL_SECONDS` is required; missing → **fail closed** |
| Channel share-link max age | B0-23 | `SHARE_CHANNEL_TOKEN_MAX_AGE_DAYS` is required; old links break past it |
| Should project collaborators keep org-wide read? | B0-29 | Today yes, via the org `member` row the project invite creates |
| API-key scopes for leads/memory (`AccessKeyScope`) | B0-15 | None exist, so the routes are closed to keys until scopes are added |
| Do users exist who reach agents only through project or team membership (not org)? | Rules (`canUseAgent`) | Evidence reads require owner or org membership |

## 5. Legal / Privacy decisions

| Decision | Finding |
|---|---|
| Retention or deletion of memory stored under legacy keys (no channel component) during the compatibility window, and before any rekey | B0-16 |
| Memory that may already be misattributed (spoofed email `from`, asserted ids) | B0-16 / B0-17 |

## 6. Studio-owner decision (recorded)

**B0-25.** Implementation chose a **member-only org document**, with the invitation preview served by the backend (`GET /api/invitations/{token}`, minimum fields only). Wallet and runtime fields were **not** moved. The Studio owner must confirm this choice.

## 7. Infrastructure-only validations (staging / ops)

| Item | Finding |
|---|---|
| Which rules file is actually deployed (`firestore.rules`?) | Rules |
| `scripts/backfill_memberships_index.py` run in staging, then production, before the rules deploy | Rules / INV-S13 |
| Staging Firebase project: probes, revocation, Studio and Noesis smoke tests | Rules |
| Composite indexes built (3 collection-group, 1 agents) before the queries ship | Studio queries |
| SendGrid Inbound Parse URL secret; live SPF/DKIM payload formats | B0-17 |
| BigQuery authorised view / row-access policy and IAM; the 5-form adversarial probe | B0-21 |
| MCP Cloud Run ingress / IAM (`allow_unauthenticated` projects) | B0-20 |
| Firebase Auth console: enabled sign-up providers, the `hd` claim | B0-18 |
| Env rollout: `SHARE_CREDENTIAL_TTL_SECONDS`, `EMAIL_INBOUND_PARSE_SECRET`, `DIRECTIVES_ALLOWED_SERVICE_ACCOUNTS`, `MCP_AGENT_BINDING_KEY`, `MCP_EXPECTED_AUDIENCE` | Several |
| Real route behaviour in staging, for each server finding | All |
