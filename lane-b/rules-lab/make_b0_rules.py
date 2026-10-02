"""Lane B / B0: derive the hardened rules from the CURRENT production rules (olbrain-studio@1f05ca11).

Every change is a named, reviewable substitution against the current file, so the diff is auditable and the
transform can be re-run when the upstream file moves. Nothing here touches the production repository: the
output is investigation/lane-b/rules-lab/firestore.b0.rules, tested only in the local emulator.

Design (memory-lane-b-security-b0-v1.md §B):
- explicit, server-derived grants for every probed path, keyed on memberships_index (server-maintained) and on the
  agent document's organization (which clients can no longer change);
- client writes to tenancy roots, evidence, sessions, versions, identity and memory collections are denied
  (Admin SDK writers are unaffected: the Admin SDK bypasses rules);
- default-deny for UNKNOWN top-level collections is stage 2 (needs the Noesis client inventory), but the known
  future memory collections are denied now.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "firestore.current.rules")
OUT = os.path.join(HERE, "firestore.b0.rules")
STAGE2 = "--stage2" in sys.argv


def sub(s, old, new, label):
    if old not in s:
        raise SystemExit("anchor not found: " + label)
    return s.replace(old, new, 1)


s = open(SRC, encoding="utf-8", newline="").read()

# --- B0-K1: agents/{agentId} -------------------------------------------------------------------------------
s = sub(s, '''    match /agents/{agentId} {
      allow read, write: if isAuthenticated() &&
        (resource == null
          || resource.data.userId == request.auth.uid
          || resource.data.owner_id == request.auth.uid) &&
        (request.resource == null
          || request.resource.data.userId == request.auth.uid
          || request.resource.data.owner_id == request.auth.uid);
    }''', '''    // [B0-K1] agents/{agentId} is the tenancy root of trust (API-key org match, canUseAgent, DCI/KV placement).
    // Before B0 the top-level catch-all ORed over this block: any signed-in user could create an agent claiming
    // any org and take over any agent. Now: agents is excluded from both catch-alls; clients never create or
    // delete agents (studio uses POST /api/agents); owner, org members, project members and team members may
    // read; the owner or an org editor may update ONLY non-tenancy fields.
    function agentReadable(d) {
      return d.get('userId', '') == request.auth.uid
        || d.get('owner_id', '') == request.auth.uid
        || (d.get('organization_id', '') is string && d.get('organization_id', '') != ''
            && isOrgMember(d.get('organization_id', '')))
        || (d.get('project_id', '') is string && d.get('project_id', '') != ''
            && exists(/databases/$(database)/documents/projects/$(d.get('project_id', ''))/members/$(request.auth.uid)))
        || request.auth.uid in d.get('team_access', {}).get('team_member_ids', []);
    }
    function isOrgEditor(orgId) {
      return orgId is string && orgId != '' && exists(orgIndexPath(orgId))
        && orgRoles(orgId).hasAny(['owner', 'super_admin', 'admin', 'editor']);
    }
    function canEditAgent(agentId) {
      return exists(agentPath(agentId)) && (
        agentDoc(agentId).data.get('userId', '') == request.auth.uid
        || agentDoc(agentId).data.get('owner_id', '') == request.auth.uid
        || isOrgEditor(agentOrg(agentId)));
    }
    match /agents/{agentId} {
      allow read: if isAuthenticated() && agentReadable(resource.data);
      allow create, delete: if false;
      allow update: if isAuthenticated()
        && (resource.data.get('userId', '') == request.auth.uid
            || resource.data.get('owner_id', '') == request.auth.uid
            || isOrgEditor(resource.data.get('organization_id', '')))
        && !request.resource.data.diff(resource.data).affectedKeys()
              .hasAny(['organization_id', 'owner_id', 'userId', 'project_id', 'runtime', 'billing_config',
                       'lifecycle_state', 'team_access', 'api_keys']);
    }''', "agents block")

# --- B0-E1 / B0-AU / B0-N5 / B0-S0-5 / B0-AN: new explicit blocks, inserted before the catch-alls -------------
NEW_BLOCKS = '''
    // [B0-E1] Evidence and sessions. Clients never write them (studio inventory: reads only); the runtime's
    // Admin SDK is the only writer. Read: org member of the row's organization, OR may use the row's agent
    // (covers legacy rows without organization_id; queries must constrain organization_id or agent_id).
    function evidenceReadable(d) {
      return (d.get('organization_id', '') is string && d.get('organization_id', '') != ''
              && isOrgMember(d.get('organization_id', '')))
        || (d.get('agent_id', '') is string && d.get('agent_id', '') != '' && canUseAgent(d.get('agent_id', '')));
    }
    match /agent_messages/{messageId} {
      allow read: if isAuthenticated() && evidenceReadable(resource.data);
      allow write: if false;
    }
    match /agent_sessions/{sessionId} {
      allow read: if isAuthenticated() && evidenceReadable(resource.data);
      allow write: if false;
      match /messages/{messageId} {
        allow read: if isAuthenticated()
          && evidenceReadable(get(/databases/$(database)/documents/agent_sessions/$(sessionId)).data);
        allow write: if false;
      }
    }
    // [B0-AU] End-user identifiers: read for people who may use the agent; server-only writes.
    match /agent_users/{userId} {
      allow read: if isAuthenticated() && evidenceReadable(resource.data);
      allow write: if false;
    }
    // [B0-N5] Support tickets hold customer PII: the filer reads their own tickets and may set CSAT only;
    // org members of the ticket's org may read. The engine (Admin SDK) creates and updates everything else.
    match /tickets/{ticketId} {
      allow read: if isAuthenticated() && (resource.data.get('user_id', '') == request.auth.uid
        || (resource.data.get('organization_id', '') is string && resource.data.get('organization_id', '') != ''
            && isOrgMember(resource.data.get('organization_id', ''))));
      allow update: if isAuthenticated() && resource.data.get('user_id', '') == request.auth.uid
        && request.resource.data.diff(resource.data).affectedKeys().hasOnly(['csat', 'csat_at']);
      allow create, delete: if false;
    }
    // [B0-AN] Analytics / billing rollup trees. Before B0 every tree was readable by every signed-in user (the
    // 4-segment catch-all for doc reads, the generic {path=**}/months|days|hours rules for group queries).
    // Path reads are scoped to the tree's owner; writes are server-only (analytics-service, billing functions).
    match /agent_analytics/{agentId}/{rest=**} {
      allow read: if isAuthenticated() && canUseAgent(agentId);
      allow write: if false;
    }
    match /organization_analytics/{orgId}/{rest=**} {
      allow read: if isAuthenticated() && isOrgMember(orgId);
      allow write: if false;
    }
    match /project_analytics/{projectId}/{rest=**} {
      allow read: if isAuthenticated()
        && (exists(/databases/$(database)/documents/projects/$(projectId)/members/$(request.auth.uid))
            || isOrgMember(get(/databases/$(database)/documents/projects/$(projectId)).data.get('organization_id', '')));
      allow write: if false;
    }
    match /workflow_analytics/{workflowId}/{rest=**} {
      allow read: if isAuthenticated() && isOrgMember(resource.data.get('organization_id', ''));
      allow write: if false;
    }
    match /billing_aggregates/{a}/orgs/{orgId}/{rest=**} {
      allow read: if isAuthenticated() && isOrgMember(orgId);
      allow write: if false;
    }
    match /billing_aggregates/{rest=**} {
      allow read: if isAuthenticated() && isOrgMember(resource.data.get('organization_id', ''));
      allow write: if false;
    }
    // [B0-S0-5] Memory Gateway / identity-authority collections (Lane A R-1, C-1a). Server-only, always:
    // a client-writable binding would let any user re-point a customer's identity.
    match /memory_bindings/{id=**} { allow read, write: if false; }
    match /identity_events/{id=**} { allow read, write: if false; }
    match /inbound_dedup/{id=**} { allow read, write: if false; }
    match /evidence_meta/{id=**} { allow read, write: if false; }
    match /memory_control/{id=**} { allow read, write: if false; }

'''
s = sub(s, "    // ---- Catch-alls ----", NEW_BLOCKS + "    // ---- Catch-alls ----", "catch-all marker")

# --- exclude the now-explicit collections from the catch-alls (rules OR together) ---------------------------
B0_EXCL = ("'agents', 'agent_messages', 'agent_sessions', 'agent_users', 'tickets', 'agent_analytics', "
           "'organization_analytics', 'project_analytics', 'workflow_analytics', 'billing_aggregates', "
           "'memory_bindings', 'identity_events', 'inbound_dedup', 'evidence_meta', 'memory_control', 'departments', ")
s = sub(s, '''      allow read: if isAuthenticated()
        && !(collection in [
          'research_report_shares',''', '''      allow read: if isAuthenticated()
        && !(collection in [
          ''' + B0_EXCL + '''// [B0] explicit blocks above are now the only grants
          'research_report_shares',''', "top-level read list")
s = sub(s, '''      allow write: if isAuthenticated()
        && !(collection in [
          'research_runs',          // cancel_requested''', '''      allow write: if isAuthenticated()
        && !(collection in [
          ''' + B0_EXCL + '''// [B0] explicit blocks above are now the only grants
          'research_runs',          // cancel_requested''', "top-level write list")
s = sub(s, '''    match /{collection}/{docId}/{sub}/{rest=**} {
      allow read: if isAuthenticated()
        && !(collection in ['organizations', 'agents', 'agent_datastores',''', '''    match /{collection}/{docId}/{sub}/{rest=**} {
      allow read: if isAuthenticated()
        && !(collection in ['agent_sessions', 'agent_analytics', 'memory_bindings', 'identity_events', // [B0]
                            'organization_analytics', 'project_analytics', 'workflow_analytics', 'billing_aggregates',
                            'organizations', 'agents', 'agent_datastores',''', "4-seg read list")
s = sub(s, '''      allow write: if isAuthenticated()
        && !(collection in ['organizations', 'agents', 'research_chat_sessions',''', '''      allow write: if isAuthenticated()
        && !(collection in ['agent_sessions', 'agent_analytics', 'memory_bindings', 'identity_events', // [B0]
                            'organization_analytics', 'project_analytics', 'workflow_analytics', 'billing_aggregates',
                            'organizations', 'agents', 'research_chat_sessions',''', "4-seg write list")

# --- B0-N6: agent subcollections ----------------------------------------------------------------------------
s = sub(s, '''    match /agents/{agentId}/{sub}/{rest=**} {
      allow read: if isAuthenticated() && sub != 'mcp_configs' && sub != 'oauth_tokens';
      allow write: if isAuthenticated() && sub != 'owner_lessons' && sub != 'mcp_configs' && sub != 'oauth_tokens';
    }''', '''    // [B0-N6] Agent subcollections: read for people who may use the agent; writes only for the owner or an
    // org editor, and never for versions/owner_lessons/documents (server-written: publish, Dendrite, KV).
    match /agents/{agentId}/{sub}/{rest=**} {
      allow read: if isAuthenticated() && sub != 'mcp_configs' && sub != 'oauth_tokens' && canUseAgent(agentId);
      allow write: if isAuthenticated()
        && !(sub in ['owner_lessons', 'mcp_configs', 'oauth_tokens', 'versions', 'documents'])
        && canEditAgent(agentId);
    }''', "agent subcollections")

# --- B0-N3 / B0-N4: organization subcollections -------------------------------------------------------------
s = sub(s, '''    match /organizations/{orgId}/members/{memberId} {
      allow read: if isAuthenticated();
      allow write: if false;
    }''', '''    // [B0-N3] Member rows (names, emails) are visible to members of that org only, plus your OWN row in any org
    // (Studio onboarding's slow path checks it to discover a pending membership).
    match /organizations/{orgId}/members/{memberId} {
      allow read: if isAuthenticated() && (isOrgMember(orgId) || memberId == request.auth.uid);
      allow write: if false;
    }''', "members")
s = sub(s, '''    match /organizations/{orgId}/{sub}/{rest=**} {
      allow read, write: if isAuthenticated()
        && !(sub in [''', '''    // [B0-N4] Every other org subcollection (departments, private_mcp_servers, activities, ...) requires
    // membership of THAT org. Before B0 any signed-in user could read and write them across tenants.
    match /organizations/{orgId}/{sub}/{rest=**} {
      allow read, write: if isAuthenticated() && isOrgMember(orgId)
        && !(sub in [''', "org subcollections")

# --- B0-AN: generic months/days/hours readers are cross-tenant; analytics has its own block now -------------
s = sub(s, '''    match /{path=**}/months/{docId} {
      allow read: if isAuthenticated();
    }
    match /{path=**}/days/{docId} {
      allow read: if isAuthenticated();
    }
    match /{path=**}/hours/{docId} {
      allow read: if isAuthenticated();
    }''', '''    // [B0-AN] Collection-group rollup reads (Studio usageService: 11 live call sites) stay possible but are
    // org-scoped: a group query must constrain organization_id == an org the caller belongs to. Assumes every
    // rollup doc carries organization_id (analytics writer is in a missing repository: [UNRESOLVED]).
    match /{path=**}/months/{docId} {
      allow read: if isAuthenticated() && isOrgMember(resource.data.get('organization_id', ''));
    }
    match /{path=**}/days/{docId} {
      allow read: if isAuthenticated() && isOrgMember(resource.data.get('organization_id', ''));
    }
    match /{path=**}/hours/{docId} {
      allow read: if isAuthenticated() && isOrgMember(resource.data.get('organization_id', ''));
    }''', "rollups")

# --- B0-ORG: org document runtime config may only be set by org admins/owners -------------------------------
s = sub(s, '''        && (!writesAgentBudgets() || isOrgAdmin(orgId) || isOrgOwner(orgId));
    }''', '''        && (!writesAgentBudgets() || isOrgAdmin(orgId) || isOrgOwner(orgId))
        // [B0-ORG] any update (runtime.firebase_web_config, auto_recharge) requires an admin/owner of THIS org
        && (isOrgAdmin(orgId) || isOrgOwner(orgId));
    }''', "org doc update")

if STAGE2:
    # --- Stage 2: default-deny for unknown top-level collections (allow-list). Gated on the Noesis inventory.
    s = sub(s, '''    match /{collection}/{docId} {
      allow read: if isAuthenticated()
        && !(collection in [''', '''    function b0KnownClientCollection(c) {
      return c in ['users', 'user_profiles', 'projects', 'support_sessions', 'myelin_sessions', 'alchemist_sessions',
                   'workflow_definitions', 'conversations', 'alchemist_conversations', 'public_mcp_servers',
                   'mcp_tool_executions', 'research_templates', 'research_runs', 'workflows', 'workflow_runs',
                   'workflow_items', 'agent_traces', 'usage_events', 'billing_records', 'notifications',
                   'research_plans', 'research_chat_sessions', 'research_golden_templates'];
    }
    match /{collection}/{docId} {
      allow read: if isAuthenticated() && b0KnownClientCollection(collection)
        && !(collection in [''', "stage2 allowlist")
    s = sub(s, '''      allow write: if isAuthenticated()
        && !(collection in [
          ''' + B0_EXCL, '''      allow write: if isAuthenticated() && b0KnownClientCollection(collection)
        && !(collection in [
          ''' + B0_EXCL, "stage2 write")
    OUT = OUT.replace(".b0.rules", ".b0-stage2.rules")

open(OUT, "w", encoding="utf-8", newline="").write(s)
print("wrote", OUT)
