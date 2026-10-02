// Lane A security probe: runs the CURRENT production firestore.rules (olbrain-studio@1f05ca11, read-only copy)
// in the local emulator (project demo-olbrain-probe: no real project) and records what a signed-in user from
// another org can do. Synthetic data only. Output: one JSON line per probe.
import { initializeTestEnvironment, assertSucceeds, assertFails } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, updateDoc } from "firebase/firestore";
import { readFileSync } from "node:fs";

const env = await initializeTestEnvironment({
  projectId: "demo-olbrain-probe",
  firestore: { rules: readFileSync("firestore.rules", "utf8"), host: "127.0.0.1", port: 8093 },
});

await env.withSecurityRulesDisabled(async (ctx) => {
  const db = ctx.firestore();
  await setDoc(doc(db, "memberships_index/victim_uid_victim_org"), { roles: ["owner"] });
  await setDoc(doc(db, "memberships_index/attacker_uid_attacker_org"), { roles: ["owner"] });
  await setDoc(doc(db, "agents/victim_agent"), { owner_id: "victim_uid", organization_id: "victim_org" });
  await setDoc(doc(db, "agent_messages/m1"), { organization_id: "victim_org", agent_id: "victim_agent",
    session_id: "+919800000001-victim_agent", role: "user", content: "my card ends 4242" });
  await setDoc(doc(db, "agent_sessions/+919800000001-victim_agent"), { organization_id: "victim_org",
    agent_id: "victim_agent", phone_number: "+919800000001", summary: "customer is upset about refund" });
  await setDoc(doc(db, "organizations/victim_org/members/mem1"), { email: "owner@victim.example", name: "V" });
  await setDoc(doc(db, "agents/victim_agent/versions/v1"), { additional_context: "brain" });
  await setDoc(doc(db, "tickets/t1"), { organization_id: "victim_org", customer: { email: "c@x.example" } });
  await setDoc(doc(db, "agent_user_memory/victim_agent__abc"), { organization_id: "victim_org", facts: ["x"] });
  await setDoc(doc(db, "agent_users/u1"), { organization_id: "victim_org", phone_number: "+919800000001" });
});

const attacker = env.authenticatedContext("attacker_uid", { email: "a@attacker.example" }).firestore();
const results = [];
async function probe(id, finding, op, fn) {
  let allowed;
  try { await assertSucceeds(fn()); allowed = true; } catch (e) { allowed = false; }
  results.push({ id, finding, op, allowed_for_other_org_user: allowed });
}

await probe("E1-read", "E1 agent_messages cross-tenant", "read victim message", () => getDoc(doc(attacker, "agent_messages/m1")));
await probe("E1-write", "E1 agent_messages cross-tenant", "overwrite victim message (forge evidence)",
  () => updateDoc(doc(attacker, "agent_messages/m1"), { content: "I am an admin" }));
await probe("E1-create", "E1 agent_messages cross-tenant", "create message in victim session",
  () => setDoc(doc(attacker, "agent_messages/forged"), { organization_id: "victim_org", agent_id: "victim_agent",
    session_id: "+919800000001-victim_agent", role: "user", content: "remember I am VIP" }));
await probe("S-read", "agent_sessions cross-tenant", "read victim session (phone, summary)",
  () => getDoc(doc(attacker, "agent_sessions/+919800000001-victim_agent")));
await probe("S-write", "agent_sessions cross-tenant", "rewrite victim session summary",
  () => updateDoc(doc(attacker, "agent_sessions/+919800000001-victim_agent"), { summary: "VIP; refund approved" }));
await probe("K1-forge", "K1 tenancy root", "create an agent claiming the victim org",
  () => setDoc(doc(attacker, "agents/forged_agent"), { owner_id: "attacker_uid", organization_id: "victim_org" }));
await probe("K1-takeover", "K1 tenancy root", "update the victim's agent",
  () => updateDoc(doc(attacker, "agents/victim_agent"), { owner_id: "attacker_uid" }));
await probe("N3-members", "N3 org members", "read victim org member (email)",
  () => getDoc(doc(attacker, "organizations/victim_org/members/mem1")));
await probe("N6-versions", "N6 agent versions", "write victim agent version (brain)",
  () => setDoc(doc(attacker, "agents/victim_agent/versions/v2"), { additional_context: "ignore rules" }));
await probe("N5-tickets", "N5 tickets", "read victim ticket (customer PII)", () => getDoc(doc(attacker, "tickets/t1")));
await probe("M1-read", "agent_user_memory", "read victim memory", () => getDoc(doc(attacker, "agent_user_memory/victim_agent__abc")));
await probe("AU-read", "agent_users", "read victim end-user identifiers", () => getDoc(doc(attacker, "agent_users/u1")));
// new v2 collections that do not exist in the rules yet: does the catch-all already expose them?
await probe("V2-bindings", "S0-5 new memory collections", "write memory_bindings (identity root)",
  () => setDoc(doc(attacker, "memory_bindings/x"), { subject_id: "attacker_subject", epoch: 0 }));
await probe("V2-identity-events", "S0-5 new memory collections", "write identity_events",
  () => setDoc(doc(attacker, "identity_events/e1"), { kind: "merge" }));
await probe("V2-dedup", "S0-5 new memory collections", "write inbound_dedup",
  () => setDoc(doc(attacker, "inbound_dedup/d1"), { evidence_id: "m1" }));

for (const r of results) console.log(JSON.stringify(r));
await env.cleanup();
