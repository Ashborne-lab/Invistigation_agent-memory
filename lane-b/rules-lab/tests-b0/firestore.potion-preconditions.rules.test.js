// tests/firestore-rules/firestore.potion-preconditions.rules.test.js
/**
 * Potion program, Phase 0 precondition G12 (map §5).
 *
 * Four paths were reachable cross-tenant through the catch-alls:
 *   - organizations/{org}/connector_credentials/{id}  (org-subcollection catch-all, no rule at all)
 *   - lead_contacts / lead_activity / lead_exports      (top-level catch-all, no rule at all)
 *   - agents/{id}/mcp_configs/{srv}                     (agents-subcollection catch-all OR-ed away ownsAgent)
 *   - agent_learned_patterns/{id}/patterns/{p}          (generic subcollection catch-all OR-ed away the owner rule)
 *
 * Rules OR together. For connector_credentials and the three lead_*
 * collections, the explicit block is `allow read, write: if false` — that
 * documents intent but grants nothing on its own, so only the CATCH-ALL
 * EXCLUSION is load-bearing there; a test below would not notice if the
 * `if false` block were deleted, only if the exclusion were. For mcp_configs
 * and agent_learned_patterns, both halves matter: the explicit block is what
 * GRANTS owner/org-member access, and the catch-all exclusion is what stops
 * the catch-all granting broader access on top of it — remove either one and
 * a test below fails. The over-reach block at the end pins that in-org
 * collaborators keep the access Studio's Tools UI needs.
 */
const fs = require('fs');
const path = require('path');
const { initializeTestEnvironment, assertFails, assertSucceeds } = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-potion-preconditions-rules-test';
const ORG_A = 'org-a', ORG_B = 'org-b';
const AGENT_A = 'agent-a';
const AGENT_NULL_ORG = 'agent-null-org'; // owned by OWNER_A, organization_id explicitly null (personal workspace)
const OWNER_A = 'uid-owner-a';      // owns AGENT_A, member of ORG_A
const MEMBER_A = 'uid-member-a';    // member of ORG_A, not the owner
const STRANGER = 'uid-stranger-b';  // member of ORG_B only

let env;

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: { host: '127.0.0.1', port: 8080,
      rules: fs.readFileSync(path.join(__dirname, '../../firestore.rules'), 'utf8') },
  });
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`memberships_index/${OWNER_A}_${ORG_A}`).set({ roles: ['owner'] });
    await db.doc(`memberships_index/${MEMBER_A}_${ORG_A}`).set({ roles: ['editor'] });
    await db.doc(`memberships_index/${STRANGER}_${ORG_B}`).set({ roles: ['owner'] });
    await db.doc(`agents/${AGENT_A}`).set({ owner_id: OWNER_A, organization_id: ORG_A, basic_info: { name: 'A' } });
    await db.doc(`agents/${AGENT_A}/mcp_configs/shopify`).set({ enabled: true, is_private: true, mcp_runtime_url: 'https://x' });
    await db.doc(`agent_learned_patterns/${AGENT_A}/patterns/p1`).set({ status: 'active', intent_examples: ['verbatim end-user text'] });
    await db.doc(`organizations/${ORG_A}/connector_credentials/cred1`).set({ auth_config: 'kms-wrapped', provider: 'shopify' });
    await db.doc('lead_contacts/lc1').set({ organization_id: ORG_A, contact_hash: 'h' });
    await db.doc('lead_activity/la1').set({ organization_id: ORG_A, kind: 'call' });
    await db.doc('lead_exports/le1').set({ organization_id: ORG_A, status: 'done' });
    // Fix round 1: personal-workspace agent — Studio writes organization_id
    // explicitly null for these (FirestoreDataAccess.js), which must not
    // make agentOrg()/isOrgMember() error or open the agent to any org member.
    await db.doc(`agents/${AGENT_NULL_ORG}`).set({ owner_id: OWNER_A, organization_id: null, basic_info: { name: 'N' } });
    await db.doc(`agents/${AGENT_NULL_ORG}/mcp_configs/shopify`).set({ enabled: true, is_private: true, mcp_runtime_url: 'https://x' });
    // Fix round 1: a doc under the lead_contacts/lc1 subcollection, to prove
    // the four-segment generic catch-all fences lead_* too, not just the
    // two-segment top-level catch-all.
    await db.doc('lead_contacts/lc1/notes/n1').set({ note: 'internal' });
    // over-reach controls
    await db.doc(`organizations/${ORG_A}/activities/m1`).set({ ok: true });
    await db.doc('some_collection/doc1/sub/item1').set({ ok: true });
  });
});
afterAll(async () => { await env.cleanup(); });

const as = (uid) => env.authenticatedContext(uid).firestore();

describe('connector_credentials is unreachable from any client', () => {
  const p = `organizations/${ORG_A}/connector_credentials/cred1`;
  test('org member cannot read', async () => { await assertFails(as(MEMBER_A).doc(p).get()); });
  test('org owner cannot read', async () => { await assertFails(as(OWNER_A).doc(p).get()); });
  test('stranger cannot write', async () => { await assertFails(as(STRANGER).doc(p).set({ auth_config: 'forged' })); });
  test('org member cannot write', async () => { await assertFails(as(MEMBER_A).doc(p).update({ provider: 'x' })); });
  test('nobody can list', async () => { await assertFails(as(OWNER_A).collection(`organizations/${ORG_A}/connector_credentials`).get()); });
});

describe.each([['lead_contacts', 'lc1'], ['lead_activity', 'la1'], ['lead_exports', 'le1']])(
  '%s is unreachable from any client', (col, id) => {
    test('org member cannot read', async () => { await assertFails(as(MEMBER_A).doc(`${col}/${id}`).get()); });
    test('stranger cannot write', async () => { await assertFails(as(STRANGER).doc(`${col}/${id}`).set({ forged: true })); });
    test('org member cannot delete', async () => { await assertFails(as(MEMBER_A).doc(`${col}/${id}`).delete()); });
    test('nobody can list', async () => { await assertFails(as(OWNER_A).collection(col).get()); });
  });

describe('agents/{id}/mcp_configs is org-scoped', () => {
  const p = `agents/${AGENT_A}/mcp_configs/shopify`;
  test('stranger cannot read', async () => { await assertFails(as(STRANGER).doc(p).get()); });
  test('stranger cannot write a binding', async () => { await assertFails(as(STRANGER).doc(p).set({ mcp_runtime_url: 'https://evil', is_private: false })); });
  test('stranger cannot list', async () => { await assertFails(as(STRANGER).collection(`agents/${AGENT_A}/mcp_configs`).get()); });
  test('owner can read and write', async () => {
    await assertSucceeds(as(OWNER_A).doc(p).get());
    await assertSucceeds(as(OWNER_A).doc(p).update({ enabled: false }));
  });
  test('in-org collaborator can read and write (Studio Tools UI)', async () => {
    await assertSucceeds(as(MEMBER_A).doc(p).get());
    await assertSucceeds(as(MEMBER_A).doc(p).update({ enabled: true }));
  });
});

describe('agent_learned_patterns is org-scoped and status-only', () => {
  const p = `agent_learned_patterns/${AGENT_A}/patterns/p1`;
  test('stranger cannot read verbatim end-user examples', async () => { await assertFails(as(STRANGER).doc(p).get()); });
  test('stranger cannot write', async () => { await assertFails(as(STRANGER).doc(p).update({ status: 'deactivated' })); });
  test('owner can read and flip status', async () => {
    await assertSucceeds(as(OWNER_A).doc(p).get());
    await assertSucceeds(as(OWNER_A).doc(p).update({ status: 'deactivated' }));
  });
  test('in-org collaborator can flip status but not rewrite the pattern', async () => {
    await assertSucceeds(as(MEMBER_A).doc(p).update({ status: 'active' }));
    await assertFails(as(MEMBER_A).doc(p).update({ intent_examples: ['tampered'] }));
  });
  test('nobody can create or delete a pattern from a client', async () => {
    await assertFails(as(OWNER_A).doc(`agent_learned_patterns/${AGENT_A}/patterns/p2`).set({ status: 'active' }));
    await assertFails(as(OWNER_A).doc(p).delete());
  });
});

// Fix round 1, item 1: widen the update rule to the exact fields Studio's
// learnedPatternsService.js writes (deactivatePattern sets status +
// deactivation_reason + deactivated_at together; setPatternTrusted sets
// trusted_override alone), not just `status`.
describe('agent_learned_patterns update allows the exact fields Studio writes', () => {
  const p = `agent_learned_patterns/${AGENT_A}/patterns/p1`;
  test('owner can deactivate with status + deactivation_reason + deactivated_at', async () => {
    await assertSucceeds(as(OWNER_A).doc(p).update({
      status: 'deactivated', deactivation_reason: 'operator', deactivated_at: new Date(),
    }));
  });
  test('in-org collaborator can deactivate with the same three fields', async () => {
    await assertSucceeds(as(MEMBER_A).doc(p).update({
      status: 'deactivated', deactivation_reason: 'operator', deactivated_at: new Date(),
    }));
  });
  test('owner can set trusted_override', async () => {
    await assertSucceeds(as(OWNER_A).doc(p).update({ trusted_override: true }));
  });
  test('in-org collaborator can set trusted_override', async () => {
    await assertSucceeds(as(MEMBER_A).doc(p).update({ trusted_override: true }));
  });
  test('stranger still cannot write any of the allowed fields', async () => {
    await assertFails(as(STRANGER).doc(p).update({
      status: 'deactivated', deactivation_reason: 'operator', deactivated_at: new Date(),
    }));
    await assertFails(as(STRANGER).doc(p).update({ trusted_override: true }));
  });
  test('the must-not-fire case still fails: a disallowed field alongside an allowed one', async () => {
    await assertFails(as(OWNER_A).doc(p).update({ status: 'deactivated', intent_examples: ['tampered'] }));
  });
});

// Fix round 1, item 2: the parent doc agent_learned_patterns/{agentId} and
// the lead_* subcollections are reachable through catch-alls the first pass
// missed — the two-segment top-level catch-all didn't exclude
// agent_learned_patterns (only its patterns subcollection was fenced), and
// the four-segment generic subcollection catch-all didn't exclude lead_*
// (only its two-segment top-level docs were fenced). Same lesson the file's
// own twilio_accounts comment states: a fence must appear in both catch-alls.
describe('agent_learned_patterns parent doc is fenced at the top-level catch-all too', () => {
  test('stranger cannot create the parent doc', async () => {
    await assertFails(as(STRANGER).doc(`agent_learned_patterns/${AGENT_A}`).set({ hijacked: true }));
  });
  test('nobody can list the agent_learned_patterns collection', async () => {
    await assertFails(as(OWNER_A).collection('agent_learned_patterns').get());
  });
});

describe('lead_* subcollections are fenced at the generic four-segment catch-all too', () => {
  test('stranger cannot write a doc under lead_contacts', async () => {
    await assertFails(as(STRANGER).doc('lead_contacts/lc1/notes/n1').set({ forged: true }));
  });
  test('stranger cannot read a doc under lead_contacts', async () => {
    await assertFails(as(STRANGER).doc('lead_contacts/lc1/notes/n1').get());
  });
});

// Fix round 1, item 3: Studio writes organization_id: null for
// personal-workspace agents. agentOrg() must normalise that to '' rather
// than handing null to isOrgMember(), which would error.
describe('agentOrg normalises a null organization_id (personal-workspace agents)', () => {
  const p = `agents/${AGENT_NULL_ORG}/mcp_configs/shopify`;
  test('owner can still read and write', async () => {
    await assertSucceeds(as(OWNER_A).doc(p).get());
    await assertSucceeds(as(OWNER_A).doc(p).update({ enabled: false }));
  });
  test('an org member of any org cannot read or write', async () => {
    await assertFails(as(MEMBER_A).doc(p).get());
    await assertFails(as(MEMBER_A).doc(p).update({ enabled: true }));
    await assertFails(as(STRANGER).doc(p).get());
  });
});

describe('the closure did not over-reach', () => {
  test('an unrelated org subcollection is still readable and writable by an authenticated user', async () => {
    // Not `members`: that one is authorization data and server-written
    // (firestore.org-members.rules.test.js).
    await assertSucceeds(as(MEMBER_A).doc(`organizations/${ORG_A}/activities/m1`).get());
    await assertSucceeds(as(MEMBER_A).doc(`organizations/${ORG_A}/activities/m1`).update({ ok: false }));
  });
  test('an unrelated generic subcollection is still readable', async () => {
    await assertSucceeds(as(STRANGER).doc('some_collection/doc1/sub/item1').get());
  });
  test('an unrelated agents subcollection is still readable and writable', async () => {
    await assertSucceeds(as(MEMBER_A).doc(`agents/${AGENT_A}/notes/n1`).set({ ok: true }));
  });
});
