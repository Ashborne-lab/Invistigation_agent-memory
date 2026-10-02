# B0 implementation: cross-repository contracts

These contracts are fixed **before** the parallel implementation, so that every repository builds against the same shapes. Changing one needs an entry here and in the status document.

## Ground rules

**Branches.** Every repository works on the local branch `b0/security`, created from the exact commit audited in B0. Push is disabled (`remote.origin.pushurl = DISABLED…`).
- Commit locally.
- Never push, deploy or create PRs.
- Never touch production data.

**Executable specification.** `investigation/lane-b/acceptance/` (`reference.py` pins the behaviour). Tests are never weakened.

**Owner adapter.** Each repository writes `investigation/lane-b/acceptance/owner_parts/<repo_short>.py`, exposing that repository's subset of the `reference.py` functions (same names and signatures).
- Each function must call the **real** B0 code, loaded from the committed `b0/security` branch via `extract.load(..., ref=extract.OWNER_REF)` or `extract.function_source(..., ref=...)`.
- The synthetic `World` is mapped onto fakes: a dict-backed Firestore stand-in, for example.
- Anything not exercised through real code must be marked `# [WIRING-ONLY: proven by <repo test path>]`. It must also have a TestClient or unit test **in the owning repository** proving the route calls the real decision code.

**Short names:**

| `<repo_short>` | Repository |
|---|---|
| `studio_backend` | olbrain-studio-backend |
| `agent_design` | olbrain-agent-design |
| `agent_runtime` | olbrain-agent-runtime |
| `agent_engine` | olbrain-agent-engine |
| `mcp` | olbrain-mcp-deployer, workflow-runtime and research-runtime callers |
| `research` | olbrain-research-runtime admin gate |

## C1. Org access (B0-12, B0-13, B0-14, B0-22)

```text
require_org_access(user: UserContext, org_id: str) -> None   # raises HTTP 403
  if not org_id                  -> 403 "organization_required"
  API key principal              -> org_id == key.organization_id (server record of the key) else 403
  Firebase principal             -> memberships_index/{uid}_{org_id} exists (server read, every call) else 403
  anything else                  -> 403
```

- `org_id` is **always** resolved from a server record: the agent doc, project doc, invitation, or key. It is never read from a body, query or header.
- View/edit checks:
  - **view** = owner, **or** passes `require_org_access`;
  - **edit** = owner, **or** a role in {owner, super_admin, admin, editor} in that org's `memberships_index` row (`roles`).

## C2. Platform admin (B0-18): identical in every repository

```text
is_platform_admin(decoded_token) =
     decoded_token.get("admin") is True        # explicit custom claim set by a backend (Admin SDK)
  OR ( email.lower().endswith("@olbrain.com")
       AND decoded_token.get("email_verified") is True
       AND decoded_token["firebase"]["sign_in_provider"] == "google.com"
       AND decoded_token.get("hd") == "olbrain.com" )
```

There is no fallback. If a gate has no decoded token available (for example only the email), it must be refactored to receive the token.

## C3. MCP agent binding (B0-20)

**Header:** `X-OLBrain-Agent-Binding: v1.<b64url(json claims)>.<b64url(sig)>`

**Claims:** `{"agent_id", "org_id", "aud": <mcp server/project name>, "iss": <calling service>, "iat", "exp"}`, with `exp - iat <= 300`.

**Interface:**
- `mint_agent_binding(agent_id, org_id, aud, iss, ttl=120) -> str`
- `verify_agent_binding(token, expected_aud, now=None) -> claims`. It raises on malformed input, a bad signature, expiry or a wrong audience.

**Signing:**
- The local and test implementation is HMAC-SHA256, with the key from the env `MCP_AGENT_BINDING_KEY`.
- **No key configured → mint and verify both fail closed.**
- The production signing scheme and key custody (KMS, rotation) are **BLOCKED on the Security owner**. Keep the signer behind one function, so it can be swapped.

**The MCP service must:**
- require caller auth always (no `MCP_REQUIRE_AUTH=false` open path);
- check the expected audience;
- take the agent **only** from the verified binding (a body or query `agent_id` must be absent or equal, else 403);
- reject an empty agent;
- never fall back to `credentials/default:{server}` for tenant-scoped servers;
- serve credential-management routes only to the studio-backend service account, with a user edit check passed via its own binding.

## C4. Share credential exchange (B0-23, B0-15)

**Issuance (studio-backend).** Validating a share token (existing validate endpoint) returns:

```json
{"credential": "shc_<32 random urlsafe>", "agent_id": "...", "session_id": "...", "expires_at": <epoch s>}
```

- It **never** returns the stored `api_key`.
- `session_id` is chosen by the server (new random) unless the client presents one it already holds for this token.
- The server stores `share_credentials/{sha256(credential)}` = `{agent_id, organization_id, session_id, share_token_id, permissions: ["agents:invoke"], expires_at, created_at}`.
- **TTL** comes from env `SHARE_CREDENTIAL_TTL_SECONDS`. If it is missing or invalid, validation fails closed (503). The value is a Product decision; it is not hard-coded.

**Acceptance (agent-runtime API-key middleware).** A bearer or `X-API-Key` value starting with `shc_` is looked up by its sha256. The request is rejected (401/403) if it is:
- unknown;
- expired;
- for an agent other than the request's agent;
- for a session other than the request's session/chat id;
- on a route outside the share-route allow-list `{webhook, upload_attachment, feedback, session_insights}`.

The webhook `user_id` for a share credential is forced to `share_<share_token_id>_<session_id>`.

**Firestore rules:** `share_credentials` is server-only (`read, write: false`).

## C5. Memory subject (B0-16): Lane A rule, not reopened

- `memory key = memory_doc_id(agent_id, f"{channel}:{assurance}:{subject}")`.
- `assurance` ∈ {`channel_verified`, `asserted`}.
- **Channel-verified ingress:** WhatsApp/Meta-verified sender, Telegram, verified email (C6). These use `channel_verified`.
- **API-key or share webhook:** `asserted`, with `channel = api:<key_id>`; share → the C4 forced id.
- An asserted identity never resolves a `channel_verified` key.
- Legacy keys (`memory_doc_id(agent, user_id)`) are read **only** on channel-verified paths, as a compatibility window, behind an explicit flag `MEMORY_LEGACY_KEY_READ` (default on) that is logged.
- **No rekey or migration in B0.**
- **BLOCKED (Product/Security):** whether an org server may assert trusted end-user ids. Default **no**; do not add an opt-in.

## C6. Email ingress (B0-17)

- Parse-URL secret: env `EMAIL_INBOUND_PARSE_SECRET`, compared in constant time against the query `?key=` or the basic-auth password, **before** any parsing. Missing configuration → 503 (fail closed).
- Verified only if SPF == `pass` **and** a DKIM result containing `pass` for the From domain.
- Unverified mail gets no memory subject, no memory in context, and replies only to the sender (no cc).
- Payload parsing lives in one function, with fixture tests. Live SendGrid formats are **unvalidated** until staging.

## C7. Directives (B0-19)

- `POST /api/agent/send-directive` is removed from `public_endpoints`.
- It requires a Google OIDC ID token from an allow-listed service account (env `DIRECTIVES_ALLOWED_SERVICE_ACCOUNTS`, comma-separated; empty → deny), with audience = the runtime URL (env).
- The target must be an `agent_users` row of that agent, not opted out.
- **Caller repository (agent-directives) missing:** integration BLOCKED.

## C8. Membership revocation (INV-S13)

When studio-backend removes an org member (the existing remove/leave paths plus `sync_org_membership_index` deletion), the same path must also:
- delete every `projects/{p}/members/{uid}` where the project's `organization_id == org`;
- remove the uid from `agents.team_access.team_member_ids` for agents of that org.

It must be idempotent. Re-grant recreates only the org membership; project and team grants are not resurrected.

## C9. B0-25 org document

**Owner decision taken in implementation (record it):** member-only org document; invitees use the existing backend endpoint `GET /api/invitations/{invitation_token}`. That endpoint must return only the minimum preview fields (organization name, project name, role, status, inviter display name, expiry): no wallet, no runtime, no billing.

**Rules:** `organizations/{orgId}` read requires `isOrgMember(orgId)`.

**Onboarding fallback** (Onboarding.js:898) must stop listing orgs. It reads the user's own `memberships_index` rows, or calls a backend endpoint instead.

## C10. Membership index scope (B0-29, added after implementation started)

**Why.** Today `memberships_index/{uid}_{org}` unions **every** active membership type (organization, project, agent) for that org. So an agent-only collaborator granted `admin` becomes an org admin in the rules and in `require_org_access`, and a project creator's `owner` role becomes org owner. Evidence: studio-backend `membership_service.py:60-85`, `access_request_service.py:318-345`, `project_service.py:122-125` @5da93ae.

**Fix.**

1. **`memberships_index/{uid}_{org}`**
   - Built **only** from `type == "organization"` memberships.
   - Field `scope: "organization"`.
   - `roles` = the union of those rows' roles only.
2. **`agent_access/{uid}_{agentId}`** = `{user_id, agent_id, organization_id, roles, scope: "agent"}`.
   - Built from active `type == "agent"` memberships.
   - Written and deleted by the same sync. Server-only.
3. **Project memberships** keep their existing `projects/{p}/members/{uid}` docs.
   - They give no org-index row of their own.
   - Project invitees are org members through the org `member` membership the invite already creates. That is unchanged and is a Product question already in the blockers.
4. **Rules.**
   - `isOrgMember`, `isOrgAdmin` and `orgRoles` additionally require `scope == "organization"`. Legacy rows without `scope` are **denied** once the backfill has run. The backfill must run first: deploy-ordering hazard.
   - `canUseAgent(agentId)` = owner OR `isOrgMember(agent org)` OR `exists(agent_access/{uid}_{agentId})`.
   - `canEditAgent` = owner, OR org editor-or-above, OR an `agent_access` role in {editor, admin}.
   - `agent_access` is `read, write: false` and excluded from the catch-alls.
5. **Server.** `require_org_access` accepts only `scope == "organization"` rows. Agent view and edit also accept `agent_access` rows for **that agent only**.
6. **Backfill.** `scripts/backfill_memberships_index.py` applies the same filter, writes `agent_access`, and removes over-broad index rows. Staging first.
7. **C8 revocation** also deletes `agent_access` rows for that org's agents.


## Amendments made during implementation (2026-10-02). These need owner or Security sign-off.

| # | Amendment | Why | Sign-off |
|---|---|---|---|
| A1 | **C10 added** (membership index scope, `agent_access`). Agent-only collaborators **lose org-wide reads**. The server and rules refuse unscoped index rows | B0-29 escalation (agent-only admin → org admin), VERIFIED CURRENT | Security + Studio/backend owner. **Semantics change:** confirm before deploy |
| A2 | C4: the server **ignores client-invented session ids**. A presented `session_id` is reused only if it was already issued for that token | Prevents a client choosing another visitor's session | Security |
| A3 | C4: for conversational tokens `expires_at` = **credential** expiry; the link expiry moves to `token_expires_at` | Shape collision | Studio owner |
| A4 | C4: new `SHARE_CHANNEL_TOKEN_MAX_AGE_DAYS` (required; missing → 503). Channel links older than it stop working | B0-23 "expire channel tokens" | Product |
| A5 | C6 supersedes security-report §E "accept both forms for a window": the secret is required immediately; ops updates the Parse URL **before** deploy | Fail closed | Ops |
| A6 | C9: onboarding cannot read its own `memberships_index` rows (client read is false). It uses `memberships` rows / `GET /api/organizations` instead. The invitation preview keeps `id, type, email, createdAt, roles` (the accept/decline pages need them) | Rules fact | Studio owner |
| A7 | C3: binding `aud` = the catalog server key (e.g. `shopify`). The MCP service's `MCP_EXPECTED_AUDIENCE` must use the same value | Caller fact | MCP owner (blocked) |
