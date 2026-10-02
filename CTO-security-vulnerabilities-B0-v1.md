# OLBrain: Security Vulnerabilities Found in Lane B / B0

**For:** CTO
**Date:** 2026-10-02
**Classification:** Internal, security-sensitive. Do not forward outside the security and engineering owners.

## How to read this document

**Evidence base.** The investigation workspace holds read-only copies of the repositories. The audited commits are:

| Repository | Commit |
|---|---|
| olbrain-studio (incl. `firestore.rules`) | `1f05ca11` |
| olbrain-studio-backend | `5da93ae` |
| olbrain-agent-design | `c56271d` |
| olbrain-agent-runtime | `daee3f9` |
| olbrain-agent-engine | `dfc3a47` |
| olbrain-mcp-deployer | `b75cc12` |
| olbrain-research-runtime | `6b81691` |

**Testing scope.**
- Only synthetic identities and data were used.
- No production system was queried.

**Two things are not confirmed for any finding below.** Each must be read in that light.

1. **Which Firestore ruleset is deployed.** Every Firestore result comes from a **local emulator** running the `firestore.rules` file at studio `1f05ca11`. The deployed ruleset in the production Firebase project has **not** been inspected.
2. **Which code revision is deployed.** Server findings are verified against `origin/main` at the commits above. Whether those commits are the revisions running in production is **not** confirmed.

**Evidence labels:**

| Label | Meaning |
|---|---|
| VERIFIED CURRENT CODE | Read in, or executed from, `origin/main` source |
| VERIFIED CURRENT RULES | Read in the audited `firestore.rules` |
| VERIFIED IN EMULATOR | Attack succeeded against the audited rules in the local Firestore emulator |
| DEPLOYMENT STATUS UNVERIFIED | Production configuration or revision not confirmed |
| BLOCKED / MISSING REPOSITORY | Evidence needs a repository not in the workspace |
| OWNER DECISION REQUIRED | Exposure depends on a configuration or policy choice not yet confirmed |

"Modelled" means the vulnerable handler was reproduced in a test harness from its source, with file:line citations. It was not imported and executed directly.

**Severity** is the impact **if the audited code or rules are what runs in production**. Where that impact depends on unverified configuration, the severity says so.

---

## 1. Executive summary

**Firestore rules (client SDK).** The audited `firestore.rules` contains three **default-allow catch-all rules**. They give every signed-in user read, and largely write, access to every tenant's data that is not on a deny-list. Because Firestore rules combine with OR, the catch-alls also **override the stricter rules written above them**. That includes the agent-ownership rule.

In the emulator:

| Probe set | Result |
|---|---|
| Cross-tenant attack probes | **51 of 51 allowed** |
| Revocation cases | **0 of 12 denied after membership was revoked**, because access never depended on membership |

Exposed data includes:
- conversations and sessions, with end-user phone numbers;
- organization member lists and emails;
- support tickets;
- end-user identifiers;
- usage and billing analytics;
- organization documents, including wallet and runtime configuration.

The same probes show an attacker can also:
- **take over, re-point or delete any organization's agent**;
- **forge conversation evidence**.

**Server code (Firestore rules cannot fix these).** A second, independent class of vulnerabilities sits in the backend services. Authorization is missing, or decided from caller-supplied fields. The most serious:

- **Any signed-in user can update any organization** (B0-30). The source explicitly says the permission check was removed.
- **Any signed-in user can claim another person's pending organization invitation** (B0-31).
- **A share-link visitor can list, export, import or erase an organization's leads, and read or delete any end user's memory in that org** (B0-15).
- **Callers can choose whose memory they load** by supplying a phone number or user id (B0-16). Spoofed emails also reach the victim's memory (B0-17).
- **The directive endpoint has no authentication** (B0-19).
- **The MCP service takes the tenant `agent_id` from the request.** It falls back to default credentials (B0-20).
- **Platform-admin access is granted to any `@olbrain.com` address without checking it is verified** (B0-18).
- **API keys inherit their creator's rights in other organizations** (B0-28/28b).

**Acceptance tests.** Against today's code, the 74 server acceptance tests give:
- **62 attack tests RED**: every attack succeeded;
- **12 legitimate-access tests GREEN**.

**Fix status.** No fix for any finding is deployed. Every finding below therefore describes the audited code and rules.

---

## 2. Vulnerability findings

### Part A: Firestore rules (client SDK)

#### F-1. Default-allow catch-all rules expose all tenants' data (B0-02…09)

**Severity:** Critical

**Where:** olbrain-studio `firestore.rules` @1f05ca11. The three catch-alls:
- `match /{collection}/{docId}` (L888);
- `match /{collection}/{docId}/{sub}/{rest=**}` (L1220);
- `match /organizations/{orgId}/{sub}/{rest=**}` (~L1340).

They are combined with OR against every specific block.

**What is wrong:** Any authenticated user is granted access to every collection and subcollection not on a deny-list. Stricter blocks above the catch-alls never take effect, because Firestore grants access if any matching rule allows it. If Firebase sign-up is open, which is **not confirmed**, "authenticated" means anyone who creates an account.

**Attack:** Any signed-in user can, for any organization:
- read, overwrite and create `agent_messages` (forging conversation evidence);
- read and rewrite `agent_sessions` and their messages (phone numbers, summaries);
- read organization member names and emails;
- read and write departments and other org subcollections;
- write agent `versions` (the agent's brain) and `documents`;
- read support tickets;
- read `agent_users` (end-user phone identifiers);
- read agent, organization, project and billing analytics, including by collection-group queries.

**Evidence:**
- **Emulator probes against the audited rules, all allowed:** E1-read/write/create/list, S-read, S-write, N3-members, N4-departments, N4-dept-read, N6-versions, N6-documents, N5-tickets, AU-read, AN-read, RU-org-analytics, RU-project-analytics, RU-billing-aggregates, RU-group-query, RU-group-unscoped, RU-group-project-only, RU-group-project-scoped.
- **Revocation:** 0 of 12 resources were denied after the user's membership was removed.
- **Source:** the rule text, read directly.

**Firestore status:**
- *Can rules prevent it?* Yes. This is a rules defect.
- *Did the current rules prevent it in the emulator?* No: every probe was allowed.
- *For comparison:* the B0 stage-1 lab rules denied all of these probes, and so did stage 2.
- *Deployed ruleset confirmed?* **No.**
- *Server exposure:* not applicable. The server uses the Admin SDK, which bypasses rules.

**Current status:** VERIFIED CURRENT RULES · VERIFIED IN EMULATOR · DEPLOYMENT STATUS UNVERIFIED

---

#### F-2. Agent takeover and forged agent tenancy (B0-01)

**Severity:** Critical

**Where:** olbrain-studio `firestore.rules`.
- The `agents` ownership block is at L23.
- `agents` is not excluded from the L888 catch-all.

**What is wrong:** The agent document is the tenancy root. Its `organization_id` drives:
- API-key org matching;
- agent-access checks;
- knowledge and data placement;
- MCP configuration.

Under the audited rules, any signed-in user can create, edit, re-point or delete any agent document.

**Attack:**
- create an agent claiming another organization;
- rewrite `owner_id` to take over another organization's agent;
- move an agent into or out of an organization by changing `organization_id`;
- read or delete any agent's configuration.

**Evidence:** Emulator probes K1-forge, K1-takeover, K1-repoint, K1-editor-repoint, K1-editor-update, K1-read and K1-delete were **all allowed**.

**Firestore status:**
- *Can rules prevent it?* Yes.
- *Did the current rules prevent it?* No.
- *For comparison:* stage 1 and stage 2 denied every probe.
- *Deployed ruleset confirmed?* **No.**

**Current status:** VERIFIED CURRENT RULES · VERIFIED IN EMULATOR · DEPLOYMENT STATUS UNVERIFIED

---

#### F-3. Organization document readable by any user; wallet and runtime fields updatable by any user (B0-25, B0-10)

**Severity:** High

**Where:** olbrain-studio `firestore.rules` L418–425 (`match /organizations/{orgId}`).
- `allow read: if isAuthenticated()`.
- `update` is allowed for any authenticated user on `auto_recharge` and `runtime`.

**What is wrong:**
- The top-level organization document holds wallet and dedicated-runtime configuration, yet every signed-in user can read and list it.
- The rule lets any signed-in user change another organization's `auto_recharge` and `runtime`. That includes re-pointing its dedicated runtime's Firebase configuration.

**Attack:**
- read or list every organization's document;
- re-point another organization's runtime settings;
- change its auto-recharge settings.

**Evidence:**
- Emulator probes ORG-doc-read and ORG-doc-list were **allowed**.
- The update path was read directly in the rule text and is covered by Studio's own org-document rules tests.

**Firestore status:**
- *Can rules prevent it?* Yes.
- *Did the current rules prevent it?* No.
- *For comparison:* stage 1 and stage 2 denied ORG-doc-read and ORG-doc-list.
- *Deployed ruleset confirmed?* **No.**
- *Server exposure:* separately, the **server API also allows arbitrary org updates** (B0-30). Rules do not cover that path.

**Current status:** VERIFIED CURRENT RULES · VERIFIED IN EMULATOR · DEPLOYMENT STATUS UNVERIFIED

---

#### F-4. New top-level collections are born client-writable (B0-11)

**Severity:** Medium (latent: these collections do not exist yet in production)

**Where:** olbrain-studio `firestore.rules`, L888 catch-all (no allow-list).

**What is wrong:** Any new top-level collection is automatically readable and writable by every signed-in user unless someone remembers to add an exclusion. The identity and memory collections planned for the new memory system would be client-writable on day one.

**Attack:** a user could:
- create or alter identity bindings, including in their own organization;
- write identity events and dedup records;
- forge records in any newly introduced server-only collection.

**Evidence:** The following emulator probes were **all allowed**:
- V2-bindings, V2-identity-events, V2-dedup, V2-own-org-binding, V2-new-collection;
- SC-read/list/forge/sub-read/sub-write, against a share-credential collection that does not yet exist in production.

**Firestore status:**
- *Can rules prevent it?* Yes.
- *Did the current rules prevent it?* No.
- *For comparison:* stage 1 still allows V2-new-collection by design, and stage 2 (the allow-list) denies it.
- *Deployed ruleset confirmed?* **No.**

**Current status:** VERIFIED CURRENT RULES · VERIFIED IN EMULATOR · DEPLOYMENT STATUS UNVERIFIED

---

#### F-5. Agent-level and project-level grants become organization-wide roles (B0-29)

**Severity:** High

**Where:**
- **Membership index.** olbrain-studio-backend `services/membership_service.py`, `sync_org_membership_index` (~L55–90): it unions the roles of **every** active membership for the user and org, with no `type` filter.
- **Agent grants feed that index.** `create_membership` sets `type='agent'` and still writes the org id. Its callers are the access-request grant path (`access_request_service.py` ~L318–345) and the project-creator owner membership (`project_service.py:122-125`).
- **The rules read the index as org membership.** In olbrain-studio `firestore.rules`, `isOrgMember`, `isOrgAdmin` and `isOrgOwner` are evaluated from that index row.

**What is wrong:**
- A user granted `admin` or `editor` on **one agent** receives an organization-wide index row carrying that role.
- A project creator's `owner` role becomes an **organization owner** role.

**Attack:** an agent-only collaborator can act as an org editor, admin or owner:
- read other agents' messages and sessions;
- read the organization billing ledger;
- write the org's private MCP server definitions;
- update the organization document.

**Evidence:**
- **Source**, read directly: the index union and the agent-membership creation.
- **Emulator probes**, all **allowed** under the audited rules:
  - C10-collab-billing-ledger;
  - C10-collab-private-mcp-write;
  - C10-collab-org-doc-update;
  - C10-collab-other-agent-messages, -sessions, -update.

**Firestore status:**
- *Can rules prevent it?* Only together with a server change, because the rules trust the server-written index.
- *Did the current rules prevent it?* No.
- *For comparison:* the stage-1 and stage-2 lab rules, paired with a scoped index, denied every probe.
- *Deployed ruleset confirmed?* **No.**
- *Server exposure:* the server-side index construction remains vulnerable whatever the rules say. Any server check reading this index inherits the over-broad roles.

**Current status:** VERIFIED CURRENT CODE · VERIFIED CURRENT RULES · VERIFIED IN EMULATOR · DEPLOYMENT STATUS UNVERIFIED. How many such rows exist in production was **not measured**.

---

### Part B: Server code (Firestore rules cannot fix these)

These authorization failures happen inside the application before any Firestore access. The services use the Admin SDK, which bypasses security rules entirely. **No ruleset, deployed or not, mitigates them.**

#### S-1. Cross-org agent creation, forking and reads (B0-12, B0-13, B0-14)

**Severity:** High

**Where:**

| Repository | File:line | What is there |
|---|---|---|
| olbrain-studio-backend | `middleware/auth.py:243` | `require_permission` checks scopes for API keys only; **Firebase users always pass**, and it never sees the resource |
| olbrain-agent-design | `app/middleware/auth.py:253` | Same flaw as above |
| olbrain-studio-backend | `routes/agent_routes.py` :65, :128, :191, :212; `services/agent_service.py` :115, :613, :796-1040, :1255 | Create, forks, preflight and fork have no org check |
| olbrain-agent-design | `app/routers/agent.py` :103 | `get_agent` contains `if owner_id != user_id: pass` |
| olbrain-agent-design | `app/routers/agent.py` :172-177, :563 | Project listing ignores the org; `/organization/{org}/active` is open |
| olbrain-agent-design | `app/routers/agent_user.py` :44-161 | `agent_users` CRUD is unchecked |
| olbrain-agent-design | `app/routers/store.py` :95, :231-275 | Blueprint install has no project check; store-admin approval has a TODO in place of a check |

**What is wrong:** Routes trust `project_id`, `organization_id` or `agent_id` from the request, with no membership check.

**Attack:** a signed-in stranger can:
- create an agent in another organization's project;
- **fork any organization's agent into an org they control and inherit its knowledge access**;
- read and list any organization's agents;
- read, edit or delete any organization's end-user rows, including opt-out flags;
- install blueprints into any project;
- approve store submissions.

**Evidence:**
- **Real `origin/main` code:** `require_permission` in both services was executed in the acceptance harness.
- **Modelled:** the route handlers, with the file:line citations above.
- **Results:** B0-12 has 4 attack tests RED; B0-13 has 5 RED; B0-14 has 7 RED.

**Firestore status:** Rules cannot prevent it: the backend uses the Admin SDK. The rules' `agents` block does not apply to these routes.

**Current status:** VERIFIED CURRENT CODE (gate executed; handlers modelled from source) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-2. Activity feed: cross-org read and forgery (B0-22)

**Severity:** Medium

**Where:** olbrain-studio-backend `routes/activity_routes.py:55, ~95`.

**What is wrong:**
- The activity log write takes the organization and actor from the request body.
- Listing accepts any Firebase user.

**Attack:**
- write activity entries into any organization's feed under any actor's name (the feed drives notifications);
- read any organization's feed;
- read anyone's cross-org feed through `?actor_id=`.

**Evidence:** Modelled handlers; 3 attack tests RED. The `actor_id` feed read was found by the implementing agent's source review and RED test.

**Firestore status:** Rules cannot prevent it (server-side, Admin SDK).

**Current status:** VERIFIED CURRENT CODE (modelled from source) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-3. Share-link key reaches org-wide leads and end-user memory (B0-15)

**Severity:** High

**Where:**
- olbrain-agent-runtime `core/api_key_middleware.py` ~L515–627 checks no scope;
- `routers/leads*` :479–879;
- `routers/agent_memory.py` :48–109.

**What is wrong:** A public share link carries an org-bound API key pinned to one agent. The runtime never checks that key's permissions against the route, so the share key is accepted on every org-wide route.

**Attack:** Anyone holding a share link, which is public by design, can:
- list, export, import or erase **all of the organization's leads**;
- read or delete **any end user's memory** in that organization.

**Evidence:** Modelled middleware and handlers; 8 attack tests RED.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE (modelled from source) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-4. Caller-chosen memory subject (B0-16)

**Severity:** High

**Where:** olbrain-agent-runtime:
- `routers/agent_webhook.py:2746`;
- `core/cs_packet_builder.py:1972`;
- `services/agent_memory_service.py:92` (`memory_doc_id`).

**What is wrong:** The webhook's `user_id` is whatever the caller asserts: any string of up to 100 characters. It is used directly as the memory key, with no channel or assurance component.

**Attack:** A caller with a share link or any API key in the organization can supply a WhatsApp customer's phone number as `user_id`. They then **load that person's memory into the conversation, or poison it**.

**Evidence:**
- **Real `origin/main` code:** `memory_doc_id` was executed in the harness.
- **Modelled:** the lookup.
- **Results:** 3 attack tests RED.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED

---

#### S-5. Email webhook: no authentication; sender spoofing reaches the victim's memory (B0-17)

**Severity:** High

**Where:** olbrain-agent-runtime `routers/email.py` :56–138, :311. It is a public endpoint.

**What is wrong:** `/api/email/webhook` has:
- no Inbound Parse secret and no basic-auth;
- no SPF, DKIM or DMARC check.

The `from` address is trusted as the memory key, and replies go to everyone on `cc`.

**Attack:** POST, or send mail, with `from=victim` and `cc=attacker`. The agent's reply, carrying the victim's memory, goes to the attacker, who can also poison that memory.

**Evidence:**
- Modelled handler; 4 attack tests RED.
- The SendGrid payload format was modelled. It is **not validated against live payloads**.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE (modelled from source) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-6. Forged `In-Reply-To` joins another email thread's session (B0-27)

**Severity:** Medium

**Where:** olbrain-agent-runtime `routers/email.py:267–270`. The code sets `thread_id = in_reply_to or …` and then `session_id = f"email-{thread_id}-{agent_id}"`.

**What is wrong:** The session is derived directly from the sender-controlled `In-Reply-To` header.

**Attack:** A sender who knows or guesses another conversation's Message-ID joins that session and receives its conversation history in context. Today any sender can do this, because S-5 means no sender is verified.

**Evidence:** Direct source inspection at `origin/main`. It was first reported by the implementing agent and confirmed by direct reading. **Not executed.**

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED

---

#### S-7. WhatsApp and Instagram webhooks: no Meta signature verification (B0-26)

**Severity:** High, conditional on the endpoints being directly reachable (unverified)

**Where:** olbrain-agent-runtime `routers/meta_whatsapp.py` and `routers/meta_instagram.py`.

**What is wrong:**
- Neither file, nor anything else in the runtime, verifies Meta's `X-Hub-Signature-256` on inbound POSTs.
- The only check is the GET subscription `hub.verify_token` (`meta_whatsapp.py:122–125`).
- The runtime treats these channels as carrying a verified sender identity.

**Attack:** Anyone who can POST to the webhook URL can forge an inbound message "from" any phone number. They then interact with the agent as that customer, including the customer's memory.

**Evidence:** Direct source inspection: no signature handling exists in the runtime (repository-wide search).

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED · BLOCKED / MISSING REPOSITORY. It is not known whether an upstream proxy verifies signatures, or whether the endpoint is reachable directly.

---

#### S-8. Directive endpoint has no authentication (B0-19)

**Severity:** High

**Where:** olbrain-agent-runtime `routers/directives.py:66`. `POST /api/agent/send-directive` is listed in `public_endpoints`. The deploy workflow uses `--allow-unauthenticated` (`.github/workflows/deploy-main.yml:171`).

**What is wrong:** Anyone can call the endpoint, with no credential.

**Attack:** Make any agent send an attacker-written message to any phone number. The message is billed to the organization and uses that end user's memory.

**Evidence:** Modelled handler; 3 attack tests RED. The legitimate caller (agent-directives) is a **missing repository**.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE (modelled from source) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-9. MCP service: caller-controlled `agent_id` and default-credential fallback (B0-20)

**Severity:** High, conditional on deployed auth and ingress settings (unverified)

**Where:** olbrain-mcp-deployer:
- `runtime/main.py:2107–2149` (`tools/call`), :494–720, :1558–1632;
- `runtime/auth_middleware.py:61–150`.

**What is wrong:**
- `agent_id` is taken from the request body or query.
- `MCP_REQUIRE_AUTH` defaults to `false`.
- When auth is on, any allow-listed service account may assert any agent.
- An empty `agent_id` skips the tool ACL and uses `credentials/default:{server}`.
- Credential-management routes take `agent_id` from the body or path.

**Attack:** Call tools with **another tenant's OAuth or KMS-held credentials**, or with the default credentials. Exposure depends on which projects are deployed without authentication. The config lists cratio, ecommerce, olbrain-test, playwright-recorder and the base config as `allow_unauthenticated`.

**Evidence:**
- **Real `origin/main` semantics:** `require_auth_enabled`.
- **Modelled:** the handlers.
- **Results:** 8 attack tests RED.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED, for the actual auth flag and ingress per project.

---

#### S-10. Platform-admin gate accepts unverified `@olbrain.com` addresses (B0-18)

**Severity:** High, conditional on the Firebase sign-up configuration (unverified)

**Where:**

| Repository | File:line | Function |
|---|---|---|
| olbrain-studio-backend | `middleware/auth.py:471–494` | `verify_admin_user` |
| olbrain-agent-engine | `routes.py:1119–1185` | `require_olbrain_user`, `get_metrics_scope`, `require_olbrain_identity` |
| olbrain-research-runtime | `app/middleware/firebase_auth.py` | `is_internal_user` |

**What is wrong:** Platform admin is decided by the email ending in `@olbrain.com`. `email_verified` is never read.

**Attack:** Sign up through email/password with an unused `@olbrain.com` address. The account receives platform-admin powers:
- wallet grants to any organization;
- support-ticket admin;
- Nexus admin mode;
- Lumen admin;
- organization-wide metrics.

**Evidence:**
- **Real `origin/main` code** was executed: all three gates returned admin for an **unverified** password account.
- **Results:** 4 attack tests RED.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED. Whether open email/password sign-up is enabled in the production Firebase project is not confirmed.

---

#### S-11. Lumen tenant isolation can be bypassed through LLM-authored SQL (B0-21)

**Severity:** Unrated. The sensitivity of the log content was not measured.

**Where:** olbrain-agent-engine `alchemist/agents/lumen/evidence/bigquery.py:16–40`.

**What is wrong:** Tenant isolation for the model-written BigQuery SQL is a regular expression that looks for `agent_id = '<own id>'` somewhere in the query text.

**Attack:** Queries that contain the expected literal but widen the result, using `OR`, `UNION`, a comment, a string literal, or a subquery, return other tenants' service-log rows.

**Evidence:**
- The **real `origin/main` filter and validator** were executed, with SQLite as the query engine: 5 of 5 adversarial forms returned other tenants' rows.
- **This is not a BigQuery test.** Production dataset IAM was not examined.

**Firestore status:** Not applicable (BigQuery).

**Current status:** VERIFIED CURRENT CODE (on a SQLite stand-in) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-12. Share tokens expose a long-lived live API key (B0-23)

**Severity:** High, in combination with S-3

**Where:** olbrain-studio-backend `services/share_token_service.py:143–242`, plus the validation path.

**What is wrong:**
- Share links are backed by org-bound live API keys stored in plaintext on `share_tokens/{id}.api_key`.
- Validation returns that stored key to the browser.
- Channel-mode tokens never expire.
- The 48-bit `short_id` alias also resolves the token.

**Attack:** Anyone who obtains a share link, which is public by design, obtains a durable API key. Because of S-3, that key reaches org-wide leads and memory.

**Evidence:** Modelled service; 5 attack tests RED.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE (modelled from source) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-13. Engine permission helper is broken (B0-24)

**Severity:** Low. It fails closed, and no caller was found in the repository.

**Where:** olbrain-agent-engine `alchemist/utils/auth.py:94–130`.

**What is wrong:**
- `require_permission` calls `check_permission` with 4 arguments where 3 are defined, so every call raises a `TypeError` (HTTP 500).
- `get_user_permissions` is a TODO that returns `[]`, so fixing the signature alone would deny everyone.
- Authorization through this helper is therefore not functioning at all.

**Attack:** None found. The callers (`StorageServiceV3`) have no callers in the repository.

**Evidence:** Real `origin/main` code executed; 3 tests RED (TypeError).

**Firestore status:** Not applicable.

**Current status:** VERIFIED CURRENT CODE

---

#### S-14. API keys inherit their creator's rights in other organizations (B0-28, B0-28b)

**Severity:** High

**Where:** olbrain-studio-backend:
- `services/agent_service.py:64` (`_require_org_member`, which checks membership by `user_id`, i.e. the key creator for API keys);
- `services/access_control.py` `build_access_request` (roles loaded for the creator uid);
- `services/analytics_authorization.py` `_user_belongs_to_org`;
- the access-key, transfer, caller-channel, LLM-key and org-connector routes.

**What is wrong:** For an API-key principal, `user_id` is the key creator's uid. Membership and role checks evaluate that uid, so an org-A key carries its creator's roles in **any other organization** the creator belongs to.

**Attack:** A holder of an org-A key whose creator is also in org B can, in org B:
- list and read agents;
- read analytics, including session messages;
- list, mint, regenerate or revoke API keys;
- fetch org B's plaintext studio test key;
- move or transfer agents;
- manage caller channels and connectors.

The same flaw also refuses the key in its own org when the creator is not a member there.

**Evidence:**
- Direct source inspection (`agent_service.py:64`, confirmed by the coordinator).
- RED route tests written by the implementing agent against the audited tree: the cross-org request returned 200. These were not re-run by the coordinator.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED

---

#### S-15. Further routes with missing or creator-based authorization (B0-28c)

**Severity:** Medium (the verified items); the rest is unrated.

**Where and what.**

The following were **verified by direct reading** of olbrain-studio-backend. Each route only requires a signed-in user and performs no organization or ownership check:
- `GET /api/organizations/{org}/whatsapp-config`: any org's WhatsApp provider configuration;
- `GET /api/analytics/power-users` (`analytics_routes.py:343`): platform-wide data, with no admin check;
- `POST /api/v1/access-keys/{key_id}/log-event` (`api_key_routes.py:160`): writes events against any key id;
- `POST /api/internal/tickets/{id}/resolved-notify` (`admin_routes.py:122`): any Firebase user can trigger it;
- `GET /api/agents/organization/{org}/deleted` (`delete_proxy_routes.py:166`): any org's deleted or archived agents, for Firebase callers.

The following were **reported by a sub-audit and not re-verified**:
- organization owner/admin mutations that authorize via `check_user_permission(user.user_id)` (reachable by API keys);
- project, user and template routes authorized by the creator uid;
- `uid == path` routes that a key can use to act as its creator.

**Evidence:** The verified items: direct source inspection. The rest is reported only.

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE (the listed routes) · the remainder is unconfirmed (sub-audit only) · DEPLOYMENT STATUS UNVERIFIED

---

#### S-16. Any signed-in user can update any organization (B0-30)

**Severity:** Critical

**Where:** olbrain-studio-backend:
- `routes/organization_routes.py`, `PUT /api/organizations/{organization_id}` (~L127) and `POST …/whatsapp-config` (~L1104). Both depend only on `verify_firebase_token` and call:
- `services/organization_service.py` `update_organization`, which says at L263: *"Permission check removed - any authenticated user can update organizations"*.

**What is wrong:** There is no membership or role check on organization updates.

**Attack:** Any signed-in user can modify any organization's fields: basic information, WhatsApp configuration, and the other fields this method updates. The only requirement is knowing the organization id. Under the audited rules, organization documents are also listable (F-3).

**Evidence:** Direct source inspection of `origin/main`, by the coordinator. **Not executed.**

**Firestore status:** Rules cannot prevent it: the server writes with the Admin SDK. This exists **independently of F-3**.

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED

---

#### S-17. Invitation takeover by supplying another person's email (B0-31)

**Severity:** High

**Where:**
- olbrain-studio-backend `routes/organization_routes.py:673`, `POST /api/organizations/{org}/members/accept`;
- `services/organization_service.py` `accept_invitation` (~L1409).

**What is wrong:** The invitation is looked up by `invitation_email` taken from the **request body**, and is never compared with the authenticated caller's email. The caller's uid then becomes the member, with the invitation's role.

**Attack:** A signed-in user who knows, or can discover, the email address of someone with a pending invitation accepts that invitation for themselves. They join the organization with the invited role. Under the audited rules, member and invitation documents are readable by any signed-in user (F-1, probe N3-members), which would make pending invitees discoverable.

**Evidence:** Direct source inspection of `origin/main`, by the coordinator. **Not executed.**

**Firestore status:** Rules cannot prevent it (server-side).

**Current status:** VERIFIED CURRENT CODE · DEPLOYMENT STATUS UNVERIFIED

---

## 3. Firestore versus server code

**Firestore findings (F-1 … F-5)** are defects in the security rules for the browser SDK.
- They were reproduced against the audited `firestore.rules` file in a local emulator.
- They would be closed by a corrected ruleset. In the emulator, the B0 stage-1 lab rules denied 50 of 51 probes, and stage 2 denied all 51, with no legitimate access denied.
- **Emulator results are not proof of what is deployed.** Whether production runs this exact ruleset has not been confirmed. Until it is, these are **verified rules defects with unverified production exposure**.
- F-5 is a hybrid: the rules are only as strict as the server-written membership index, so its server-side half remains regardless of rules.

**Server findings (S-1 … S-17)** occur in application code that uses the Firebase Admin SDK or other back-end credentials. The Admin SDK bypasses security rules. **No Firestore ruleset, current or corrected, affects them.** A corrected ruleset could even make the system look secure from the browser while these API paths stay open.

**Two findings span both layers:**
- Organization updates are open in the rules (F-3) **and** in the API (S-16).
- Agent creation is open in the rules (F-2) **and** in the API (S-1).

Closing one layer does not close the other.

---

## 4. Evidence and status matrix

**Column meanings:**
- **Code:** reproduced in `origin/main` code. Real = executed; Modelled = handler reproduced from source; Source = read directly.
- **Rules:** whether the attack succeeded against the audited rules in the emulator.
- **Preventable by rules:** whether a corrected ruleset could close it.
- **Deployed confirmed:** whether the deployed rules (for F-rows) or the deployed code revision (for S-rows) is confirmed.

| Vulnerability | Code | Rules | Preventable by rules? | Deployed confirmed? | Current risk status |
|---|---|---|---|---|---|
| F-1 Catch-all cross-org data access | n/a | **Yes**: all F-1 probes allowed; 0/12 revocation | Yes | No | Rules defect verified; production exposure **unverified** |
| F-2 Agent takeover / forged tenancy | n/a | **Yes**: 7/7 K1 probes | Yes | No | Rules defect verified; exposure **unverified** |
| F-3 Org doc read, wallet/runtime update | n/a | **Yes**: ORG-doc-read and list | Yes (rules half) | No | Rules defect verified; exposure **unverified** |
| F-4 Client-writable new collections | n/a | **Yes**: V2-*, SC-* | Yes | No | Latent; rules defect verified |
| F-5 Agent/project grants → org roles | **Source** | **Yes**: C10-collab-* | Partly (needs a server change) | No | Server and rules defect verified; exposure **unverified** |
| S-1 Cross-org agent create/fork/read | Real gate + modelled (16 RED) | n/a | **No** | No | Code verified; deployment **unverified** |
| S-2 Activity cross-org | Modelled (3 RED) | n/a | No | No | Code verified; deployment **unverified** |
| S-3 Share key → leads and memory | Modelled (8 RED) | n/a | No | No | Code verified; deployment **unverified** |
| S-4 Caller-chosen memory subject | Real + modelled (3 RED) | n/a | No | No | Code verified; deployment **unverified** |
| S-5 Email webhook spoofing | Modelled (4 RED) | n/a | No | No | Code verified; deployment **unverified** |
| S-6 Forged `In-Reply-To` | Source | n/a | No | No | Code verified (not executed) |
| S-7 No Meta signature check | Source | n/a | No | No | Code verified; reachability **unverified** |
| S-8 Unauthenticated directives | Modelled (3 RED) | n/a | No | No | Code verified; deployment **unverified** |
| S-9 MCP `agent_id` / default creds | Real + modelled (8 RED) | n/a | No | No | Code verified; auth flag and ingress **unverified** |
| S-10 Unverified `@olbrain.com` admin | Real (4 RED) | n/a | No | No | Code verified; sign-up config **unverified** |
| S-11 Lumen SQL bypass | Real, on SQLite (5 RED) | n/a | n/a | No | Code verified; BigQuery **untested** |
| S-12 Share token exposes live key | Modelled (5 RED) | n/a | No | No | Code verified; deployment **unverified** |
| S-13 Broken permission helper | Real (3 RED) | n/a | n/a | No | Fails closed; no live caller found |
| S-14 API key inherits creator rights | Source + agent RED tests | n/a | No | No | Code verified; deployment **unverified** |
| S-15 Further missing checks | Source (listed routes) | n/a | No | No | Partly verified; remainder unconfirmed |
| S-16 Any user updates any org | Source | n/a | **No** | No | Code verified (not executed); deployment **unverified** |
| S-17 Invitation takeover | Source | n/a | No | No | Code verified (not executed); deployment **unverified** |

**Totals behind the matrix:**
- **Current rules, emulator:** 51/51 attack probes allowed; 0/12 revocations effective.
- **B0 stage-1 lab rules:** 1/51 allowed (a new-collection write, closed only by stage 2).
- **B0 stage-2 lab rules:** 0/51 allowed.
- **Server acceptance tests on current code:** 62 RED (every attack) and 12 GREEN (every legitimate-access test). S-6, S-7, S-15, S-16 and S-17 were found after that suite was written and are evidenced by source inspection.

---

## 5. Unverified deployment and configuration items

These determine whether each verified defect is exploitable in production. None has been confirmed.

| Item | Affects |
|---|---|
| The ruleset actually deployed to the production Firebase project. Is it `olbrain-studio/firestore.rules` at or near `1f05ca11`? | F-1 … F-5 |
| The code revisions deployed for each service (versus the audited `origin/main` commits) | All S-findings |
| Whether Firebase Auth allows open email/password sign-up, including `@olbrain.com` addresses | S-10; also who counts as "any signed-in user" everywhere |
| MCP deployments: the `MCP_REQUIRE_AUTH` value and Cloud Run ingress / `allow_unauthenticated` per project | S-9 |
| The runtime's public exposure, i.e. whether the email, directive and Meta webhook endpoints are reachable directly or behind a verifying proxy | S-5, S-7, S-8 |
| SendGrid Inbound Parse configuration and live payload format | S-5, S-6 |
| BigQuery dataset IAM and views behind Lumen | S-11 |
| The number of production `memberships_index` rows built from agent or project memberships | F-5 |
| Repositories not in the workspace: olbrain-noesis-os (browser queries), agent-directives (directive caller), the webhook service (share and Meta forwarding), analytics-service (rollup documents) | F-1 coverage, S-7, S-8, S-3/S-12 |
