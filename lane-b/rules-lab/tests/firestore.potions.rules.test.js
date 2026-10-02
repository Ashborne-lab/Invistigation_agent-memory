// tests/firestore-rules/firestore.potions.rules.test.js
/**
 * Potion program, Phase 2. `potions/{agentId}` (pointer doc) and
 * `potions/{agentId}/versions/{n}` are written only by olbrain-agent-design's
 * Admin SDK. Rules OR together, so the load-bearing lines are the four
 * catch-all EXCLUSIONS; the explicit `if false` block documents intent.
 */
const fs = require('fs');
const path = require('path');
const { initializeTestEnvironment, assertFails, assertSucceeds } = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-potions-rules-test';
const ORG_A = 'org-a';
const AGENT_A = 'agent-a';
const OWNER_A = 'uid-owner-a';
const MEMBER_A = 'uid-member-a';
const STRANGER = 'uid-stranger-b';

let env;

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: { host: '127.0.0.1', port: 8080,
      rules: fs.readFileSync(path.join(__dirname, '../../firestore.rules'), 'utf8') },
  });
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    // memberships_index and agents/{AGENT_A} are inert for potions: every
    // potions path below is an unconditional `if false` deny, with no
    // ownership or org-membership check to satisfy. Seeded only for parity
    // with the sibling suite (firestore.potion-preconditions.rules.test.js).
    await db.doc(`memberships_index/${OWNER_A}_${ORG_A}`).set({ roles: ['owner'] });
    await db.doc(`memberships_index/${MEMBER_A}_${ORG_A}`).set({ roles: ['editor'] });
    await db.doc(`memberships_index/${STRANGER}_org-b`).set({ roles: ['owner'] });
    await db.doc(`agents/${AGENT_A}`).set({ owner_id: OWNER_A, organization_id: ORG_A, basic_info: { name: 'A' } });
    await db.doc(`potions/${AGENT_A}`).set({ agent_id: AGENT_A, organization_id: ORG_A, current_version: 1 });
    await db.doc(`potions/${AGENT_A}/versions/1`).set({ version: 1, content_hash: 'h' });
    await db.doc('some_collection/doc1').set({ ok: true }); // over-reach control (two-segment READ list)
    await db.doc('some_collection/doc1/sub/item1').set({ ok: true }); // over-reach control (four-segment lists)
  });
});
afterAll(async () => { await env.cleanup(); });

const as = (uid) => env.authenticatedContext(uid).firestore();

describe('potions/{agentId} is unreachable from any client', () => {
  const p = `potions/${AGENT_A}`;
  test('agent owner cannot read', async () => { await assertFails(as(OWNER_A).doc(p).get()); });
  test('org member cannot read', async () => { await assertFails(as(MEMBER_A).doc(p).get()); });
  test('stranger cannot read', async () => { await assertFails(as(STRANGER).doc(p).get()); });
  test('owner cannot write', async () => { await assertFails(as(OWNER_A).doc(p).set({ current_version: 99 })); });
  test('stranger cannot create another agent\'s pointer', async () => { await assertFails(as(STRANGER).doc('potions/agent-z').set({ agent_id: 'agent-z' })); });
  test('nobody can list', async () => { await assertFails(as(OWNER_A).collection('potions').get()); });
});

describe('potions/{agentId}/versions/{n} is unreachable from any client', () => {
  const p = `potions/${AGENT_A}/versions/1`;
  test('owner cannot read', async () => { await assertFails(as(OWNER_A).doc(p).get()); });
  test('member cannot write', async () => { await assertFails(as(MEMBER_A).doc(p).set({ content_hash: 'forged' })); });
  test('stranger cannot delete', async () => { await assertFails(as(STRANGER).doc(p).delete()); });
  test('nobody can list versions', async () => { await assertFails(as(OWNER_A).collection(`potions/${AGENT_A}/versions`).get()); });
});

describe('over-reach control', () => {
  test('an unrelated generic subcollection is still reachable', async () => {
    await assertSucceeds(as(MEMBER_A).doc('some_collection/doc1/sub/item1').get());
  });
  test('the four-segment catch-all still grants write on an unrelated subcollection', async () => {
    await assertSucceeds(as(MEMBER_A).doc('some_collection/doc1/sub/item1').set({ ok: true, touched: true }));
  });
  test('the two-segment catch-all still grants read on an unrelated top-level doc', async () => {
    await assertSucceeds(as(MEMBER_A).doc('some_collection/doc1').get());
  });
});
