// INV-S13: stale authorization must not survive membership revocation.
// For each resource: (1) the member has access, (2) the membership is revoked server-side (memberships_index row
// deleted with the Admin SDK, exactly as studio-backend sync_org_membership_index does), (3) the SAME user retries
// with the SAME token → must be denied. No client-side fallback is involved. Synthetic data, local emulator only.
import { initializeTestEnvironment, assertSucceeds } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, updateDoc, deleteDoc } from "firebase/firestore";
import { readFileSync } from "node:fs";

const env = await initializeTestEnvironment({
  projectId: "demo-olbrain-revoke",
  firestore: { rules: readFileSync(process.argv[2] || "firestore.rules", "utf8"), host: "127.0.0.1", port: 8080 },
});

async function seed() {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    // [B0-29 / C10] memberships_index seeds carry scope: "organization" (new server contract: the index is built
    // from organization memberships only and stamped). Backward compatible: older rules ignore the field.
    await setDoc(doc(db, "memberships_index/mate_uid_org_V"), { roles: ["editor"], scope: "organization" });
    await setDoc(doc(db, "memberships_index/admin_uid_org_V"), { roles: ["admin"], scope: "organization" });
    await setDoc(doc(db, "organizations/org_V"), { name: "V", runtime: {} });
    await setDoc(doc(db, "agents/agent_V"), { owner_id: "owner_uid", userId: "owner_uid", organization_id: "org_V" });
    await setDoc(doc(db, "agent_messages/m1"), { organization_id: "org_V", agent_id: "agent_V", session_id: "s1", content: "x" });
    await setDoc(doc(db, "agent_sessions/s1"), { organization_id: "org_V", agent_id: "agent_V" });
    await setDoc(doc(db, "agent_sessions/s1/messages/x"), { content: "x" });
    await setDoc(doc(db, "agent_users/u1"), { organization_id: "org_V", agent_id: "agent_V" });
    await setDoc(doc(db, "organizations/org_V/members/owner_uid"), { email: "o@v.example" });
    await setDoc(doc(db, "organizations/org_V/departments/d1"), { name: "Support" });
    await setDoc(doc(db, "agent_analytics/agent_V/days/2026-10-01"), { n: 1 });
    await setDoc(doc(db, "tickets/t1"), { organization_id: "org_V", user_id: "someone_else" });
  });
}
const revoke = (uid) => env.withSecurityRulesDisabled((ctx) => deleteDoc(doc(ctx.firestore(), `memberships_index/${uid}_org_V`)));
const as = (uid) => env.authenticatedContext(uid, { email: uid + "@v.example", email_verified: true }).firestore();

const CASES = [
  ["agent read (org member)", "mate_uid", (db) => getDoc(doc(db, "agents/agent_V"))],
  ["agent update non-tenancy field (org editor)", "mate_uid", (db) => updateDoc(doc(db, "agents/agent_V"), { basic_info: { name: "x" } })],
  ["agent subcollection write (org editor)", "mate_uid", (db) => setDoc(doc(db, "agents/agent_V/notes/n1"), { t: 1 })],
  ["agent_messages read", "mate_uid", (db) => getDoc(doc(db, "agent_messages/m1"))],
  ["agent_sessions read", "mate_uid", (db) => getDoc(doc(db, "agent_sessions/s1"))],
  ["agent_sessions/*/messages read", "mate_uid", (db) => getDoc(doc(db, "agent_sessions/s1/messages/x"))],
  ["agent_users read", "mate_uid", (db) => getDoc(doc(db, "agent_users/u1"))],
  ["org members read", "mate_uid", (db) => getDoc(doc(db, "organizations/org_V/members/owner_uid"))],
  ["org subcollection write (departments)", "mate_uid", (db) => setDoc(doc(db, "organizations/org_V/departments/d2"), { name: "x" })],
  ["agent analytics read", "mate_uid", (db) => getDoc(doc(db, "agent_analytics/agent_V/days/2026-10-01"))],
  ["ticket read (org member)", "mate_uid", (db) => getDoc(doc(db, "tickets/t1"))],
  ["org doc update (admin)", "admin_uid", (db) => updateDoc(doc(db, "organizations/org_V"), { auto_recharge: { on: true } })],
];

for (const [name, uid, op] of CASES) {
  await seed();
  const db = as(uid);
  let before, after;
  try { await assertSucceeds(op(db)); before = true; } catch { before = false; }
  await revoke(uid);
  try { await assertSucceeds(op(db)); after = true; } catch { after = false; }
  console.log(JSON.stringify({ resource: name, uid, allowed_before_revocation: before, allowed_after_revocation: after,
                               inv_s13_holds: before && !after }));
}
await env.cleanup();
