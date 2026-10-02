"""Lane B / B0 (repo port): build olbrain-studio's firestore.rules (stage 1) and firestore.stage2.rules from the
audited blob (git show <ref>:firestore.rules == firestore.current.rules), by running make_b0_rules.py's named
substitutions UNCHANGED and then adding, as further named substitutions:

  [B0-25] organizations/{orgId} read -> isOrgMember(orgId); 'organizations' excluded from the top-level READ catch-all
          (it was already excluded from the write list and from the 4-segment lists).
  [B0-23] share_credentials server-only (read, write: false) and excluded from all four catch-all lists.

Usage: python make_repo_rules.py <studio-repo-dir> [<git-ref>]   (writes firestore.rules + firestore.stage2.rules
in the repo, plus firestore.repo-stage1.rules / firestore.repo-stage2.rules copies here for the lab runners).
make_b0_rules.py itself is not modified and its outputs in this directory are not touched.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = sys.argv[1]
REF = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
SRC_TEXT = subprocess.run(["git", "-C", REPO, "show", REF + ":firestore.rules"], capture_output=True, check=True,
                          ).stdout.decode("utf-8")
assert SRC_TEXT == open(os.path.join(HERE, "firestore.current.rules"), encoding="utf-8", newline="").read(), \
    "repo blob differs from firestore.current.rules: re-audit before porting"

GEN = open(os.path.join(HERE, "make_b0_rules.py"), encoding="utf-8").read()
GEN = GEN.replace('s = open(SRC, encoding="utf-8", newline="").read()', "s = SRC_TEXT")
GEN = GEN.replace('open(OUT, "w", encoding="utf-8", newline="").write(s)\nprint("wrote", OUT)\n', "")
assert "SRC_TEXT" in GEN and 'open(OUT, "w"' not in GEN


def sub(s, old, new, label, count=1):
    if s.count(old) < count:
        raise SystemExit("anchor not found: " + label)
    return s.replace(old, new, count)


def c10(s):
    """[B0-29 / contract C10] memberships_index rows count only when scope == 'organization'; agent-only
    collaborators are proved by agent_access/{uid}_{agentId} (server-only) for THAT agent only."""
    s = sub(s, '''    function orgRoles(orgId) {
      return get(orgIndexPath(orgId)).data.roles;
    }

    function isOrgMember(orgId) {
      return exists(orgIndexPath(orgId));
    }''', '''    // [B0-29 / C10] memberships_index used to union EVERY membership type (organization, project,
    // agent), so an agent-only collaborator granted 'admin' became an org admin here. Only rows that
    // studio-backend stamps scope == 'organization' (built from organization memberships only) count;
    // a legacy row without scope grants NOTHING (the backfill must run before this deploys).
    function orgIndexScoped(orgId) {
      return exists(orgIndexPath(orgId))
        && get(orgIndexPath(orgId)).data.get('scope', '') == 'organization';
    }

    function orgRoles(orgId) {
      return orgIndexScoped(orgId) ? get(orgIndexPath(orgId)).data.get('roles', []) : [];
    }

    function isOrgMember(orgId) {
      return orgIndexScoped(orgId);
    }

    // [B0-29 / C10] agent_access/{uid}_{agentId}: an agent-only collaborator's grant, for that agent
    // only (server-written by the same sync; clients can neither read nor write it).
    function agentAccessPath(agentId) {
      return /databases/$(database)/documents/agent_access/$(request.auth.uid + '_' + agentId);
    }

    function agentAccessRoles(agentId) {
      return exists(agentAccessPath(agentId)) ? get(agentAccessPath(agentId)).data.get('roles', []) : [];
    }''', "C10 org index scope")
    s = sub(s, '''    function canUseAgent(agentId) {
      return ownsAgent(agentId) || isOrgMember(agentOrg(agentId));
    }''', '''    function canUseAgent(agentId) {
      return ownsAgent(agentId) || isOrgMember(agentOrg(agentId))
        || exists(agentAccessPath(agentId)); // [B0-29 / C10] agent-only collaborator, this agent only
    }''', "C10 canUseAgent")
    s = sub(s, '''        || isOrgEditor(agentOrg(agentId)));
    }''', '''        || isOrgEditor(agentOrg(agentId))
        || agentAccessRoles(agentId).hasAny(['editor', 'admin'])); // [B0-29 / C10]
    }''', "C10 canEditAgent")
    s = sub(s, '''      allow read: if isAuthenticated() && agentReadable(resource.data);
      allow create, delete: if false;
      allow update: if isAuthenticated()
        && (resource.data.get('userId', '') == request.auth.uid
            || resource.data.get('owner_id', '') == request.auth.uid
            || isOrgEditor(resource.data.get('organization_id', '')))''', '''      allow read: if isAuthenticated()
        && (agentReadable(resource.data) || exists(agentAccessPath(agentId))); // [C10]
      allow create, delete: if false;
      allow update: if isAuthenticated()
        && (resource.data.get('userId', '') == request.auth.uid
            || resource.data.get('owner_id', '') == request.auth.uid
            || isOrgEditor(resource.data.get('organization_id', ''))
            || agentAccessRoles(agentId).hasAny(['editor', 'admin'])) // [C10]''', "C10 agents block")
    s = sub(s, "    match /share_credentials/{id=**} { allow read, write: if false; }\n",
            "    match /share_credentials/{id=**} { allow read, write: if false; }\n"
            "    // [B0-29 / C10] agent_access/{uid}_{agentId}: server-only authorization data.\n"
            "    match /agent_access/{id=**} { allow read, write: if false; }\n", "agent_access block")
    s = sub(s, "          'share_credentials',   // [B0-23] hashed share credentials: server-only\n",
            "          'share_credentials',   // [B0-23] hashed share credentials: server-only\n"
            "          'agent_access',        // [B0-29] agent-only collaborator grants: server-only\n", "top read list agent_access")
    s = sub(s, "          'share_credentials',      // [B0-23] hashed share credentials: server-only\n",
            "          'share_credentials',      // [B0-23] hashed share credentials: server-only\n"
            "          'agent_access',           // [B0-29] a client row would grant itself an agent\n", "top write list agent_access")
    s = sub(s, "        && !(collection in ['share_credentials', // [B0-23]\n",
            "        && !(collection in ['share_credentials', 'agent_access', // [B0-23] [B0-29]\n", "4-seg agent_access", count=2)
    return s


def build(stage2):
    ns = {"__file__": os.path.join(HERE, "make_b0_rules.py"), "__name__": "make_b0_rules_embedded",
          "SRC_TEXT": SRC_TEXT}
    argv = sys.argv
    sys.argv = ["make_b0_rules.py"] + (["--stage2"] if stage2 else [])
    try:
        exec(compile(GEN, "make_b0_rules.py", "exec"), ns)
    finally:
        sys.argv = argv
    s = ns["s"]

    # ---- [B0-25] org document: members only ----------------------------------------------------------------
    s = sub(s, '''    // Reads are deliberately UNCHANGED: still any authenticated user, as the
    // catch-all already allowed. Scoping reads to membership needs a predicate
    // that works, and there isn't one yet — membership lives in a separate
    // collection with random document ids, which rules cannot query. That is a
    // separate and larger change.''', '''    // [B0-25] Reads are MEMBERS ONLY (isOrgMember = memberships_index row,
    // server-maintained). Before B0 any signed-in user could read any org's
    // document (wallet, runtime config). Invitees who are not members yet read
    // the org's display name through studio-backend
    // GET /api/invitations/{invitation_token}; onboarding no longer lists orgs.''', "org doc comment")
    s = sub(s, '''    match /organizations/{orgId} {
      allow read: if isAuthenticated();''', '''    match /organizations/{orgId} {
      allow read: if isAuthenticated() && isOrgMember(orgId); // [B0-25]''', "org doc read")
    s = sub(s, '''          'research_report_shares', // holds the share tokens''', '''          'organizations',       // [B0-25] org doc read is members-only: its explicit block is the only grant
          'share_credentials',   // [B0-23] hashed share credentials: server-only
          'research_report_shares', // holds the share tokens''', "top-level read list (org, share_credentials)")
    s = sub(s, '''          'research_runs',          // cancel_requested''', '''          'share_credentials',      // [B0-23] hashed share credentials: server-only
          'research_runs',          // cancel_requested''', "top-level write list (share_credentials)")
    # both 4-segment lists (read and write) start with the same [B0] line
    s = sub(s, "        && !(collection in ['agent_sessions', 'agent_analytics', 'memory_bindings', 'identity_events', // [B0]",
            "        && !(collection in ['share_credentials', // [B0-23]\n"
            "                            'agent_sessions', 'agent_analytics', 'memory_bindings', 'identity_events', // [B0]",
            "4-seg lists (share_credentials)", count=2)
    s = sub(s, "    match /memory_control/{id=**} { allow read, write: if false; }\n",
            "    match /memory_control/{id=**} { allow read, write: if false; }\n"
            "    // [B0-23] share_credentials/{sha256(credential)}: written and read only by studio-backend and the\n"
            "    // agent-runtime API-key middleware (Admin SDK). A client read would leak a live credential's binding.\n"
            "    match /share_credentials/{id=**} { allow read, write: if false; }\n", "share_credentials block")

    s = c10(s)

    if stage2:
        s = sub(s, "rules_version = '2';", """// =====================================================================================================
// STAGE 2 of the B0 rules (top-level allow-list: unknown collections are denied by default).
// DO NOT DEPLOY until the Noesis client inventory is validated (olbrain-noesis-os is a missing
// repository; its browser reads are unaudited). firebase.json points at firestore.rules (stage 1), never
// at this file. Generated by investigation/lane-b/rules-lab/make_repo_rules.py.
// =====================================================================================================
rules_version = '2';""", "stage2 header")
    return s


for stage2, repo_name, lab_name in ((False, "firestore.rules", "firestore.repo-c10-stage1.rules"),
                                    (True, "firestore.stage2.rules", "firestore.repo-c10-stage2.rules")):
    out = build(stage2)
    for path in (os.path.join(REPO, repo_name), os.path.join(HERE, lab_name)):
        open(path, "w", encoding="utf-8", newline="").write(out)
        print("wrote", path)
