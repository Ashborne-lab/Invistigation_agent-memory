# Lane B / B0: Studio Query Audit v1

**Date:** 2026-10-01.

**Scope:** read-only. olbrain-studio `src/` at `origin/main` `1f05ca11`. No code changed.

**Rules audited against:** `investigation/lane-b/rules-lab/firestore.b0.rules`, after the rollup correction in §1.

## 0. Why queries break

Firestore checks a query against the rules **before** running it, and refuses it if the rule could not hold for every possible result. Under B0:

| Rule | A query is provable only if it… |
|---|---|
| `agent_messages`, `agent_sessions`, `agent_users`: org member of `resource.organization_id` **or** `canUseAgent(resource.agent_id)` | …constrains `organization_id ==` (an org you belong to) or `agent_id ==` (an agent you own or whose org you belong to). `project_id` and `session_id` prove nothing. `canUseAgent` = owner or org member; project-only or team-only users do **not** pass |
| `agents`: owner, org member, project member, or team member | …constrains `owner_id == uid`, `organization_id ==`, `project_id ==` (**only** if `projects/{p}/members/{uid}` exists), or `team_access.team_member_ids array-contains uid`. `project_id in [...]` needs project membership of every value |
| Collection-group `months`/`days`/`hours` (rollups): `isOrgMember(resource.organization_id)` | …constrains `organization_id ==` an org you belong to |
| Path-scoped trees (`agents/{a}/**`, `agent_analytics/{a}/**`, `organization_analytics/{o}/**`, `project_analytics/{p}/**`, `organizations/{o}/**`, `agent_sessions/{s}/messages`) | Provable by path; no query change needed |

## 1. Correction to the B0 rules found by this audit

The first B0 draft removed the generic rollup readers. **Ten live collection-group call sites** in `usageService.js` would have returned empty, silently: they `.catch(() => null)`.

**Fix applied in the rules lab:**
- org-scoped collection-group readers;
- explicit blocks for `organization_analytics`, `project_analytics`, `workflow_analytics`, `billing_aggregates`, `agent_analytics/**`.

Before this, every one of those trees was readable across tenants through the 4-segment catch-all.

**Lab result:** the rollup probes RU-* deny another org and allow members, including an org-scoped group query, and Studio's suite stays 346/346.

**Assumption:** every rollup document carries `organization_id`. The org-filtered group queries at `usageService.js:700/:769/:1484` depend on it already. The writer (olbrain-analytics-service) is a **missing repository** `[UNRESOLVED]`.

## 2. Query table

**Legend:**
- **Live** = has a static caller in `src/`.
- **Dead** = no caller: delete it, or fix it if it is revived.
- **Index** = a new composite index is needed for the replacement.

### 2.1 Queries that MUST change before the rules deploy (live)

| File | Line | Collection | Current scope | Required constraint | Why the rule can't prove it | Safe replacement | Class | Index |
|---|---|---|---|---|---|---|---|---|
| src/services/analytics/usage/usageService.js | 4424 (getProjectSentimentDistribution) | agent_sessions | `project_id==`, `mode==production`, `limit 500` | `organization_id==` | `project_id` is not a tenant field for evidence | Add `where('organization_id','==',orgId)`. `orgId` is not in ProjectAnalyticsTab: pass it from UsageAnalyticsContent or read the project doc's `organization_id` | MUST ADD organization_id | No (equality + limit) |
| usageService.js | 4503 (getProjectFailedSessionsBySource) | agent_sessions | `project_id==`, `mode==production`, `limit 500` | `organization_id==` | same | same as :4424 | MUST ADD organization_id | No |
| usageService.js | 304 (getProjectAgentsUsage) | CG `months` | `project_id==` | `organization_id==` | The group reader needs the org constraint | Add `where('organization_id','==',orgId)` | MUST ADD organization_id | **Yes**: CG (organization_id, project_id) |
| usageService.js | 552 (getProjectPerAgentForRange) | CG `days`/tier | `project_id==` + key range | `organization_id==` | same | Add the org filter | MUST ADD organization_id | **Yes**: CG (organization_id, project_id, day) |
| usageService.js | 2360 (getProjectTopAgents, fallback) | CG `months` | `project_id==`, `month==` | `organization_id==` | same | Add the org filter | MUST ADD organization_id | **Yes**: CG (organization_id, project_id, month) |
| usageService.js | 2516, 2582, 2645, 2703 (getProjectAgentsBreakdown) | CG `days`/`months` | `project_id==` + `day` range / `month==` | `organization_id==` | same | Add the org filter | MUST ADD organization_id | **Yes** (as above) |
| src/components/dashboard/content/DashboardContent.js | 418 | agents | `project_id==`, `lifecycle_state in`, `orderBy created_at` | `organization_id==` (unless every viewer has a project-member doc) | `project_id` proves access only for project members | Add `where('organization_id','==',orgId)`; `orgId` is in scope at :407 | MUST ADD organization_id | **Yes**: (organization_id, project_id, lifecycle_state, created_at desc) |
| src/services/_infra/data/FirestoreDataAccess.js | 548 (getProjectAgents; callers projectService:422 → ProjectList:200, ProjectsContent:84, ProjectProfileContent) | agents | `project_id==` (+ optional status / team filters) | `organization_id==` | same | Add an `organizationId` parameter; callers have `currentOrganization` | MUST ADD organization_id (UNKNOWN if every org member is guaranteed a project-member doc) | No |

### 2.2 Live queries that are SAFE AS-IS

**agent_messages:**
- conversationService.js:1927 (`session_id` + `agent_id`);
- DeploymentTestDrawer.js:115 (`session_id` + `agent_id`).

**Collection-group rollups (org-scoped; safe only after the §1 rule correction):** usageService.js:516 (getOrgPerAgentForPeriod), :1484 (getOrganizationTopProjects fallback), :2085 (getOrganizationTopAgents fallback).

**agent_sessions:**
- usageService.js:5911 (org);
- analyticsService.js:662/672 (`agent_id`).

**agent_users:** agentUserService.js:22 (`agent_id`).

**agents:**
- FirestoreDataAccess.js:621, :637 (org);
- DashboardContent.js:410 (org), :427/:434 (`owner_id`);
- ProjectList.js:108, :270 (org);
- UnifiedSendersManager.js:439, :763 (org);
- billingApiClient.js:689 (org);
- usageService.js:1566, :1729 (org).

**Members:**
- organizationService.js:1529 (path-scoped; member only);
- Onboarding.js:898/:911 (own member doc; the org list read stays open, see §3).

**tickets:** supportService.js:160 (`user_id == uid`).

**Path-scoped reads:** agents subcollections, `agent_analytics/{a}/{tier}/{k}` getDocs (usageService.js:1163, :1355, :3183, :3926 …), `project_analytics/{p}/months` (usageService.js:258, now member-scoped).

### 2.3 Dead code that would fail (delete, or fix if revived)

| File:line | Collection | Problem | Class |
|---|---|---|---|
| usageService.js:910, :3347 | agent_messages | `session_id` only | MUST ADD agent_id (`agentId` is in scope) |
| usageService.js:3506; messagesService.js:156/173 | agent_messages | `project_id` only | MUST ADD organization_id |
| usageService.js:4364 | agent_sessions | `project_id` only | MUST ADD organization_id |
| usageService.js:4235, :5376 | agent_sessions | Field chosen by argument | UNKNOWN (depends on the argument) |
| handoffService.js:235 | agent_sessions | Unscoped cross-tenant sweep | MUST BE SERVER-SIDE |
| FirestoreDataAccess.js:586, :909 | agents | Possibly unfiltered | MUST ADD organization_id |
| FirestoreDataAccess.js:698; DataCacheContext.js:204, :264 | agents | `project_id` / `project_id in` | MUST ADD organization_id |
| usageService.js:392, :700, :769, :3125, :3598, :3675; billingQueryService.js:87 | CG rollups | Project-scoped, or org-scoped (fine after §1) | MUST ADD organization_id (project-scoped ones) |
| analyticsService.js:873, :992 | `agent_analytics/{agent}` 2-segment doc listener | No rule at that depth | MUST BE SERVER-SIDE / delete |
| organizationService.js:1088 | members across all orgs, filtered by `user_id` | Cross-org loop | MUST BE SERVER-SIDE (or a doc-id get) |

### 2.4 Unknown (missing repository)

**olbrain-noesis-os** (operator console) reads `agent_messages`, `agent_sessions`, `agentify_sessions`, `research_chat_sessions` and more from the browser (studio rules comments). **None of its queries could be audited.** The staging rollout (handoff §2) must run Noesis against the B0 rules and capture denials before production.

## 3. Residual finding raised by this audit

**B0-25: top-level `organizations/{org}` documents are readable by every signed-in user.**
- Rule: studio rules L418 `allow read: if isAuthenticated()`.
- They hold the org's wallet and runtime configuration.
- The probe `ORG-doc-read` shows another org's user can read them. This is **still allowed under B0 stage 1.**
- It was not closed blind because two flows depend on it:
  - Studio's invitation flow (invitationService.js:394) reads the org doc for an invitee who is not yet a member;
  - the onboarding fallback (Onboarding.js:898) lists orgs.
- **Fix to hand off:** restrict org-doc read to members, and serve invitees through an API endpoint (invitation token → org display name only). Alternatively, move wallet and runtime to a member-only subcollection.
- Owner: Studio + studio-backend. Added to the handoff matrix.

## 4. Summary for the Studio owner

- **Must change before the rules deploy:** 2 live `agent_sessions` queries, 7 live project-scoped collection-group rollup call sites, and 2 live `agents` queries. That's **11 live call sites in 3 files**; FirestoreDataAccess.js:548 is conditional on project-member docs, plus 3 new collection-group composite indexes and 1 new agents index.
- **Everything else live is SAFE AS-IS.** About 25 dead functions should be deleted, or fixed when revived.
- **Caveat:** users who reach an agent **only** through project or team membership, without org membership, lose reads of that agent's sessions, messages and end users under B0 (`canUseAgent`). Whether such users exist is a product question; Studio's data model suggests projects live inside orgs `[INFERENCE]`. If they do exist, `evidenceReadable` must be extended with the project-member clause.
