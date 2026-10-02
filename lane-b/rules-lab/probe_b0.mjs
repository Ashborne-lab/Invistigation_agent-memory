// Lane B / B0 security probe (extends Lane A's 15-probe set).
// Runs a rules file (argv[2]) in the local Firestore emulator (demo project, synthetic data only) and records,
// for every probe, the attacker result (a signed-in user of ANOTHER org) AND a legitimate twin (the owner /
// org member doing the same thing). G-SEC requires: every attack denied; every legitimate twin unchanged.
import { initializeTestEnvironment, assertSucceeds } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, updateDoc, deleteDoc, collection, collectionGroup, query, where, getDocs, limit } from "firebase/firestore";
import { readFileSync } from "node:fs";

const RULES = process.argv[2] || "firestore.rules";
const env = await initializeTestEnvironment({
  projectId: "demo-olbrain-b0",
  firestore: { rules: readFileSync(RULES, "utf8"), host: "127.0.0.1", port: Number(process.env.EMU_PORT || 8080) },
});

async function seed() {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    // [B0-29 / C10] memberships_index seeds carry scope: "organization" (new server contract: the index is built
    // from organization memberships only and stamped). Backward compatible: older rules ignore the field.
    await setDoc(doc(db, "memberships_index/victim_uid_victim_org"), { roles: ["owner"], scope: "organization" });
    await setDoc(doc(db, "memberships_index/mate_uid_victim_org"), { roles: ["member"], scope: "organization" });
    await setDoc(doc(db, "memberships_index/editor_uid_victim_org"), { roles: ["editor"], scope: "organization" });
    await setDoc(doc(db, "memberships_index/attacker_uid_attacker_org"), { roles: ["owner"], scope: "organization" });
    await setDoc(doc(db, "agents/victim_agent"), { owner_id: "victim_uid", userId: "victim_uid", organization_id: "victim_org" });
    await setDoc(doc(db, "agent_messages/m1"), { organization_id: "victim_org", agent_id: "victim_agent",
      session_id: "s1", role: "user", content: "synthetic message" });
    await setDoc(doc(db, "agent_sessions/s1"), { organization_id: "victim_org", agent_id: "victim_agent", summary: "x" });
    await setDoc(doc(db, "organizations/victim_org/members/victim_uid"), { email: "owner@victim.example" });
    await setDoc(doc(db, "organizations/victim_org/departments/d1"), { name: "Support" });
    await setDoc(doc(db, "agents/victim_agent/versions/v1"), { additional_context: "brain" });
    await setDoc(doc(db, "agents/victim_agent/documents/doc1"), { title: "kb" });
    await setDoc(doc(db, "tickets/t1"), { organization_id: "victim_org", customer: { email: "c@x.example" } });
    await setDoc(doc(db, "agent_users/u1"), { organization_id: "victim_org", agent_id: "victim_agent", phone_number: "+910000000000" });
    await setDoc(doc(db, "agent_analytics/victim_agent/days/2026-10-01"), { messages: 3, organization_id: "victim_org" });
    await setDoc(doc(db, "projects/victim_proj"), { organization_id: "victim_org" });
    await setDoc(doc(db, "organization_analytics/victim_org/months/2026-10"), { messages: 9, organization_id: "victim_org" });
    await setDoc(doc(db, "project_analytics/victim_proj/months/2026-10"), { messages: 5, organization_id: "victim_org", project_id: "victim_proj" });
    await setDoc(doc(db, "billing_aggregates/a1/orgs/victim_org/months/2026-10"), { inr: 100, organization_id: "victim_org" });
    await setDoc(doc(db, "organizations/victim_org"), { name: "Victim", wallet: { balance: 500 } });
    // [repo-stage1 additions] B0-23 share credentials (server-only)
    await setDoc(doc(db, "share_credentials/h1"), { agent_id: "victim_agent", organization_id: "victim_org", session_id: "s1", permissions: ["agents:invoke"] });
    await setDoc(doc(db, "share_credentials/h1/audit/a1"), { at: 1 });
    // [C10 additions] agent-only ADMIN collaborator with a LEGACY unscoped index row; legacy_uid: unscoped owner row only
    await setDoc(doc(db, "memberships_index/collab_uid_victim_org"), { roles: ["admin"] });
    await setDoc(doc(db, "memberships_index/legacy_uid_victim_org"), { roles: ["owner"] });
    await setDoc(doc(db, "agent_access/collab_uid_collab_agent"), { user_id: "collab_uid", agent_id: "collab_agent", organization_id: "victim_org", roles: ["admin"], scope: "agent" });
    await setDoc(doc(db, "agents/collab_agent"), { owner_id: "victim_uid", userId: "victim_uid", organization_id: "victim_org" });
    await setDoc(doc(db, "agent_messages/cm1"), { organization_id: "victim_org", agent_id: "collab_agent", session_id: "cs1", content: "x" });
    await setDoc(doc(db, "agent_sessions/cs1"), { organization_id: "victim_org", agent_id: "collab_agent" });
    await setDoc(doc(db, "billing_ledger/bl1"), { organization_id: "victim_org", amount: 10 });
  });
}

const ctxOf = (uid) => env.authenticatedContext(uid, { email: uid + "@example.test", email_verified: true }).firestore();
const A = ctxOf("attacker_uid"), V = ctxOf("victim_uid"), MATE = ctxOf("mate_uid"), ED = ctxOf("editor_uid");
const COLLAB = ctxOf("collab_uid"), LEGACY = ctxOf("legacy_uid");

const PROBES = [
  // id, finding, op, attack(fn on attacker db), legit twin (fn) or null, expectLegitAfterB0 ("allow"|"deny"|null)
  ["E1-read", "E1", "read another org's message", () => getDoc(doc(A, "agent_messages/m1")), () => getDoc(doc(MATE, "agent_messages/m1"))],
  ["E1-write", "E1", "overwrite another org's message", () => updateDoc(doc(A, "agent_messages/m1"), { content: "forged" }), null],
  ["E1-create", "E1", "create a message in another org's session", () => setDoc(doc(A, "agent_messages/f1"), { organization_id: "victim_org", agent_id: "victim_agent", session_id: "s1", role: "user", content: "VIP" }), null],
  ["E1-list", "E1", "list another org's messages by agent", () => getDocs(query(collection(A, "agent_messages"), where("agent_id", "==", "victim_agent"))), () => getDocs(query(collection(MATE, "agent_messages"), where("organization_id", "==", "victim_org")))],
  ["S-read", "E1", "read another org's session", () => getDoc(doc(A, "agent_sessions/s1")), () => getDoc(doc(MATE, "agent_sessions/s1"))],
  ["S-write", "E1", "rewrite another org's session", () => updateDoc(doc(A, "agent_sessions/s1"), { summary: "refund approved" }), null],
  ["K1-forge", "K1", "create an agent claiming another org", () => setDoc(doc(A, "agents/forged"), { owner_id: "attacker_uid", userId: "attacker_uid", organization_id: "victim_org" }), null],  // clients never create agents (studio: POST /api/agents); denied for everyone by design
  ["K1-editor-update", "K1", "stranger edits another org's agent config", () => updateDoc(doc(A, "agents/victim_agent"), { basic_info: { name: "x" } }), () => updateDoc(doc(ED, "agents/victim_agent"), { basic_info: { name: "edited by org editor" } })],
  ["K1-editor-repoint", "K1", "org editor moves the agent to another org", () => updateDoc(doc(ED, "agents/victim_agent"), { organization_id: "attacker_org" }), null],
  ["K1-takeover", "K1", "take over another org's agent", () => updateDoc(doc(A, "agents/victim_agent"), { owner_id: "attacker_uid", userId: "attacker_uid" }), () => updateDoc(doc(V, "agents/victim_agent"), { "basic_info": { name: "renamed" } })],
  ["K1-repoint", "K1", "owner moves own agent into a foreign org", () => updateDoc(doc(V, "agents/victim_agent"), { organization_id: "attacker_org" }), null],
  ["K1-read", "K1", "read another org's agent config", () => getDoc(doc(A, "agents/victim_agent")), () => getDoc(doc(MATE, "agents/victim_agent"))],
  ["K1-delete", "K1", "delete another org's agent", () => deleteDoc(doc(A, "agents/victim_agent")), null],
  ["N3-members", "N3", "read another org's member", () => getDoc(doc(A, "organizations/victim_org/members/victim_uid")), () => getDoc(doc(MATE, "organizations/victim_org/members/victim_uid"))],
  ["N4-departments", "N4", "write another org's department", () => setDoc(doc(A, "organizations/victim_org/departments/d2"), { name: "x" }), null],
  ["N4-dept-read", "N4", "read another org's department", () => getDoc(doc(A, "organizations/victim_org/departments/d1")), () => getDoc(doc(MATE, "organizations/victim_org/departments/d1"))],
  ["N6-versions", "N6", "write another org's agent version", () => setDoc(doc(A, "agents/victim_agent/versions/v2"), { additional_context: "evil" }), null],
  ["N6-documents", "N6", "write another org's agent document", () => setDoc(doc(A, "agents/victim_agent/documents/doc2"), { title: "evil" }), null],
  ["N5-tickets", "N5", "read another org's ticket", () => getDoc(doc(A, "tickets/t1")), () => getDoc(doc(MATE, "tickets/t1"))],
  ["AU-read", "AU", "read another org's end-user identifiers", () => getDoc(doc(A, "agent_users/u1")), () => getDoc(doc(MATE, "agent_users/u1"))],
  ["AN-read", "AN", "read another org's agent analytics", () => getDoc(doc(A, "agent_analytics/victim_agent/days/2026-10-01")), () => getDoc(doc(MATE, "agent_analytics/victim_agent/days/2026-10-01"))],
  ["RU-org-analytics", "B0-AN", "read another org's organization_analytics", () => getDoc(doc(A, "organization_analytics/victim_org/months/2026-10")), () => getDoc(doc(MATE, "organization_analytics/victim_org/months/2026-10"))],
  ["RU-project-analytics", "B0-AN", "read another org's project_analytics", () => getDoc(doc(A, "project_analytics/victim_proj/months/2026-10")), () => getDoc(doc(MATE, "project_analytics/victim_proj/months/2026-10"))],
  ["RU-billing-aggregates", "B0-AN", "read another org's billing aggregate", () => getDoc(doc(A, "billing_aggregates/a1/orgs/victim_org/months/2026-10")), () => getDoc(doc(MATE, "billing_aggregates/a1/orgs/victim_org/months/2026-10"))],
  ["RU-group-query", "B0-AN", "collection-group months query for another org", () => getDocs(query(collectionGroup(A, "months"), where("organization_id", "==", "victim_org"))), () => getDocs(query(collectionGroup(MATE, "months"), where("organization_id", "==", "victim_org")))],
  ["RU-group-unscoped", "B0-AN", "unscoped collection-group months query", () => getDocs(collectionGroup(A, "months")), null],
  ["ORG-doc-read", "B0-25 (residual)", "read another org's organization doc (wallet)", () => getDoc(doc(A, "organizations/victim_org")), () => getDoc(doc(MATE, "organizations/victim_org"))],
  ["V2-bindings", "S0-5", "write memory_bindings", () => setDoc(doc(A, "memory_bindings/x"), { subject_id: "x" }), null],
  ["V2-identity-events", "S0-5", "write identity_events", () => setDoc(doc(A, "identity_events/e1"), { kind: "merge" }), null],
  ["V2-dedup", "S0-5", "write inbound_dedup", () => setDoc(doc(A, "inbound_dedup/d1"), { evidence_id: "m1" }), null],
  ["V2-own-org-binding", "S0-5", "member writes a binding even in its own org", () => setDoc(doc(MATE, "memory_bindings/y"), { subject_id: "y", organization_id: "victim_org" }), null],
  ["V2-new-collection", "S0-5", "write an arbitrary new top-level collection", () => setDoc(doc(A, "future_memory_store/z"), { v: 1 }), null],
  // [repo-stage1 additions] B0-23 share_credentials, B0-25 org listing, project-scoped rollup shapes
  ["SC-read", "B0-23", "read another org's share credential", () => getDoc(doc(A, "share_credentials/h1")), null],
  ["SC-member-read", "B0-23", "org member reads a share credential (server-only)", () => getDoc(doc(MATE, "share_credentials/h1")), null],
  ["SC-list", "B0-23", "list share credentials by agent", () => getDocs(query(collection(A, "share_credentials"), where("agent_id", "==", "victim_agent"))), null],
  ["SC-forge", "B0-23", "forge a share credential", () => setDoc(doc(A, "share_credentials/forged"), { agent_id: "victim_agent", session_id: "any", expires_at: 4102444800 }), null],
  ["SC-sub-read", "B0-23", "read under a share credential (4-segment)", () => getDoc(doc(A, "share_credentials/h1/audit/a1")), null],
  ["SC-sub-write", "B0-23", "write under a share credential (4-segment)", () => setDoc(doc(A, "share_credentials/h1/audit/a2"), { at: 2 }), null],
  ["ORG-doc-list", "B0-25", "list organization docs (old onboarding fallback)", () => getDocs(query(collection(A, "organizations"), limit(100))), null],
  ["RU-group-project-only", "B0-AN", "project_id-only months group query (pre-B0 Studio shape)", () => getDocs(query(collectionGroup(MATE, "months"), where("project_id", "==", "victim_proj"))), null],
  ["RU-group-project-scoped", "B0-AN", "org+project months group query for another org", () => getDocs(query(collectionGroup(A, "months"), where("organization_id", "==", "victim_org"), where("project_id", "==", "victim_proj"))), () => getDocs(query(collectionGroup(MATE, "months"), where("organization_id", "==", "victim_org"), where("project_id", "==", "victim_proj")))],
  // [C10 additions] B0-29 membership index scope
  ["C10-collab-other-agent-messages", "B0-29", "agent-only collaborator reads another agent's messages", () => getDoc(doc(COLLAB, "agent_messages/m1")), () => getDoc(doc(COLLAB, "agent_messages/cm1"))],
  ["C10-collab-other-agent-sessions", "B0-29", "agent-only collaborator reads another agent's session", () => getDoc(doc(COLLAB, "agent_sessions/s1")), () => getDoc(doc(COLLAB, "agent_sessions/cs1"))],
  ["C10-collab-other-agent-update", "B0-29", "agent-only collaborator edits another agent", () => updateDoc(doc(COLLAB, "agents/victim_agent"), { basic_info: { name: "x" } }), () => updateDoc(doc(COLLAB, "agents/collab_agent"), { basic_info: { name: "collab edit" } })],
  ["C10-collab-billing-ledger", "B0-29", "agent-only admin reads the org billing ledger", () => getDoc(doc(COLLAB, "billing_ledger/bl1")), () => getDoc(doc(V, "billing_ledger/bl1"))],
  ["C10-collab-private-mcp-write", "B0-29", "agent-only admin writes org private_mcp_servers", () => setDoc(doc(COLLAB, "organizations/victim_org/private_mcp_servers/p2"), { name: "evil" }), () => setDoc(doc(V, "organizations/victim_org/private_mcp_servers/p2"), { name: "ok" })],
  ["C10-collab-org-doc-update", "B0-29", "agent-only admin updates the org doc", () => updateDoc(doc(COLLAB, "organizations/victim_org"), { auto_recharge: { on: true } }), () => updateDoc(doc(V, "organizations/victim_org"), { auto_recharge: { on: true } })],
  ["C10-legacy-agent-read", "B0-29", "legacy unscoped owner row reads an org agent", () => getDoc(doc(LEGACY, "agents/victim_agent")), null],
  ["C10-legacy-org-doc", "B0-29", "legacy unscoped owner row reads the org doc", () => getDoc(doc(LEGACY, "organizations/victim_org")), null],
  ["C10-agent-access-read", "B0-29", "client reads its own agent_access row", () => getDoc(doc(COLLAB, "agent_access/collab_uid_collab_agent")), null],
  ["C10-agent-access-forge", "B0-29", "client forges an agent_access row", () => setDoc(doc(A, "agent_access/attacker_uid_victim_agent"), { roles: ["admin"], agent_id: "victim_agent" }), null],
];

const out = [];
for (const [id, finding, op, attack, legit] of PROBES) {
  await seed();
  let allowed;
  try { await assertSucceeds(attack()); allowed = true; } catch { allowed = false; }
  let legitAllowed = null;
  if (legit) {
    await seed();
    try { await assertSucceeds(legit()); legitAllowed = true; } catch { legitAllowed = false; }
  }
  out.push({ id, finding, op, attacker_allowed: allowed, legitimate_allowed: legitAllowed });
}
for (const r of out) console.log(JSON.stringify(r));
await env.cleanup();
