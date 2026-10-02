/**
 * Firestore rules unit tests for BRD share records (`brd_shares`).
 *
 * brd_shares/{brd_id} holds each shared BRD's token and audience. It is
 * server-only in BOTH directions: a readable token is a leaked link, and the
 * audience IS the access decision, so a client write would let the writer
 * publish anyone's BRD. agent-engine's Admin SDK is the only reader and
 * writer (alchemist/services/brd_share_service.py).
 */
const fs = require('fs');
const path = require('path');
const { initializeTestEnvironment, assertFails } = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-brd-shares-rules-test';
const ORG = 'org-alpha';
const OWNER_UID = 'uid-owner';
const MATE_UID = 'uid-teammate';
const OUTSIDER_UID = 'uid-outsider';
const SHARE = 'brd_shares/brd-1';

let env;
const as = (uid) => env.authenticatedContext(uid).firestore();

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      host: '127.0.0.1',
      port: 8080,
      rules: fs.readFileSync(path.join(__dirname, '../../firestore.rules'), 'utf8'),
    },
  });
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`memberships_index/${OWNER_UID}_${ORG}`).set({ roles: ['owner'] });
    await db.doc(`memberships_index/${MATE_UID}_${ORG}`).set({ roles: ['member'] });
    await db.doc(SHARE).set({
      token: 'tok-secret', audience: 'organization', session_id: 'sess-1',
      brd_id: 'brd-1', org_id: ORG, set_by: OWNER_UID,
    });
  });
});

afterAll(async () => { await env.cleanup(); });

describe('brd_shares is server-only', () => {
  test.each([OWNER_UID, MATE_UID, OUTSIDER_UID])('%s cannot read a share record', async (uid) => {
    await assertFails(as(uid).doc(SHARE).get());
  });

  test('nobody can list share records to harvest tokens', async () => {
    await assertFails(as(OUTSIDER_UID).collection('brd_shares').get());
  });

  test('the owner cannot widen their own share from the client', async () => {
    await assertFails(as(OWNER_UID).doc(SHARE).update({ audience: 'public' }));
  });

  test('an outsider cannot mint a share for someone else\'s BRD', async () => {
    await assertFails(as(OUTSIDER_UID).doc('brd_shares/brd-2').set({ token: 't', audience: 'public' }));
  });

  test('nothing can nest under a share record either', async () => {
    await assertFails(as(OWNER_UID).doc(`${SHARE}/notes/n1`).set({ x: 1 }));
    await assertFails(as(OWNER_UID).doc(`${SHARE}/notes/n1`).get());
  });
});
