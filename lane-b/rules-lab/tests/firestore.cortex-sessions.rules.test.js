/**
 * Firestore rules unit tests for Cortex sessions (`agentify_sessions`).
 *
 * A Cortex session holds a whole conversation and every BRD built in it, and
 * each BRD carries its PDF as a Firebase download-token URL that works signed
 * out. Until this suite, all of it was readable AND writable by every
 * signed-in user in every org: the owner-only block for agentify_sessions was
 * decorative, because the collection sat in neither catch-all's exclusion
 * list and rules OR together. Contracts:
 *   1. The owner reads their own session and BRDs.
 *   2. A member of the session's org reads them too. Studio and Noesis both
 *      open a teammate's session read-only, and their useActiveBrd hooks read
 *      the session doc and the active BRD straight from the client.
 *   3. Everyone else is denied, including members of other orgs and signed-in
 *      users with no membership at all.
 *   4. Nothing under agentify_sessions is client-writable. agent-engine's
 *      Admin SDK is the only writer. A client write could repoint owner_id
 *      past the engine's owner checks, or plant messages that Cortex reads
 *      back as history on the owner's next turn.
 *   5. `messages` and `brd_revisions` are server-only. Studio fetches
 *      messages over HTTP (GET /api/agentify/sessions/{sid}/messages).
 *   6. The dashboard's recommendations listener still works, in the
 *      owner-filtered shape it now issues. An unfiltered listing is denied.
 *   7. `organizations/{org}/brd_documents` (BRD PDFs uploaded to an org) is
 *      server-only. No frontend reads it; agent-engine serves it over HTTP.
 */
const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-cortex-sessions-rules-test';

const ORG = 'org-alpha';
const OTHER_ORG = 'org-beta';
const OWNER_UID = 'uid-owner';       // created the session, owns the BRD
const MATE_UID = 'uid-teammate';     // member of ORG, not the owner
const OUTSIDER_UID = 'uid-outsider'; // member of OTHER_ORG only
const STRANGER_UID = 'uid-stranger'; // signed in, member of nothing

const SESSION = 'agentify_sessions/sess-1';
const BRD = `${SESSION}/recommendations/brd-1`;
const MESSAGE = `${SESSION}/messages/msg-1`;
const REVISION = `${BRD}/brd_revisions/rev-1`;
// Written before sessions carried organization_id: only the owner can be
// established, so only the owner may read.
const LEGACY_SESSION = 'agentify_sessions/sess-legacy';
const LEGACY_BRD = `${LEGACY_SESSION}/recommendations/brd-legacy`;
// The org-keyed session the dashboard listener reads (session id == org id).
const ORG_KEYED_RECS = `agentify_sessions/${ORG}/recommendations`;
const ORG_UPLOAD = `organizations/${ORG}/brd_documents/doc-1`;

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
    await db.doc(`memberships_index/${OUTSIDER_UID}_${OTHER_ORG}`).set({ roles: ['owner'] });

    await db.doc(SESSION).set({
      user_id: OWNER_UID, organization_id: ORG, project_id: 'proj-1', title: 'Support bot',
    });
    await db.doc(BRD).set({
      owner_id: OWNER_UID,
      organization_id: ORG,
      basic_info: { name: 'Support bot' },
      recommendation_metadata: {
        business_requirements_document: { executive_summary: 'Answer tickets.' },
        brd_documents: [{ url: 'https://firebasestorage.googleapis.com/v0/b/x/o/y?alt=media&token=t' }],
      },
    });
    await db.doc(MESSAGE).set({ role: 'user', content: 'We run a support desk.' });
    await db.doc(REVISION).set({ section_key: 'executive_summary', op: 'set_section' });

    await db.doc(LEGACY_SESSION).set({ user_id: OWNER_UID, title: 'Old session' });
    await db.doc(LEGACY_BRD).set({ owner_id: OWNER_UID, basic_info: { name: 'Old BRD' } });

    await db.doc(`${ORG_KEYED_RECS}/brd-owner`).set({ owner_id: OWNER_UID, organization_id: ORG });
    await db.doc(`${ORG_KEYED_RECS}/brd-mate`).set({ owner_id: MATE_UID, organization_id: ORG });

    await db.doc(ORG_UPLOAD).set({ filename: 'Plan.pdf', url: 'https://firebasestorage.googleapis.com/v0/b/x/o/z?alt=media&token=u' });
  });
});

afterAll(async () => { await env.cleanup(); });

describe('the owner reads their own Cortex data', () => {
  test('session doc', async () => {
    await assertSucceeds(as(OWNER_UID).doc(SESSION).get());
  });

  test('BRD', async () => {
    await assertSucceeds(as(OWNER_UID).doc(BRD).get());
  });

  test('a legacy session and BRD with no organization_id', async () => {
    await assertSucceeds(as(OWNER_UID).doc(LEGACY_SESSION).get());
    await assertSucceeds(as(OWNER_UID).doc(LEGACY_BRD).get());
  });
});

describe('a member of the session org reads it (the read-only teammate view)', () => {
  test('session doc', async () => {
    await assertSucceeds(as(MATE_UID).doc(SESSION).get());
  });

  test('BRD', async () => {
    await assertSucceeds(as(MATE_UID).doc(BRD).get());
  });

  test('but not a legacy session or BRD whose org cannot be established', async () => {
    await assertFails(as(MATE_UID).doc(LEGACY_SESSION).get());
    await assertFails(as(MATE_UID).doc(LEGACY_BRD).get());
  });
});

describe('everyone else is denied', () => {
  test('a member of another org cannot read the session doc', async () => {
    await assertFails(as(OUTSIDER_UID).doc(SESSION).get());
  });

  test('a member of another org cannot read the BRD', async () => {
    await assertFails(as(OUTSIDER_UID).doc(BRD).get());
  });

  test('a signed-in user with no membership cannot read either', async () => {
    await assertFails(as(STRANGER_UID).doc(SESSION).get());
    await assertFails(as(STRANGER_UID).doc(BRD).get());
  });

  test('a member of another org cannot list the org-keyed recommendations', async () => {
    await assertFails(as(OUTSIDER_UID).collection(ORG_KEYED_RECS).get());
  });

  test('signed out is denied', async () => {
    await assertFails(env.unauthenticatedContext().firestore().doc(SESSION).get());
  });
});

describe('nothing under agentify_sessions is client-writable', () => {
  test('the owner cannot update their own session doc', async () => {
    await assertFails(as(OWNER_UID).doc(SESSION).update({ title: 'Renamed' }));
  });

  test('the owner cannot edit their own BRD', async () => {
    await assertFails(as(OWNER_UID).doc(BRD).update({ 'basic_info.name': 'Edited' }));
  });

  test('an outsider cannot repoint owner_id on a BRD', async () => {
    await assertFails(as(OUTSIDER_UID).doc(BRD).update({ owner_id: OUTSIDER_UID }));
  });

  test('an outsider cannot plant a message in someone else\'s session', async () => {
    await assertFails(
      as(OUTSIDER_UID).collection(`${SESSION}/messages`).add({ role: 'assistant', content: 'planted' }),
    );
  });

  test('nobody can create a session doc', async () => {
    await assertFails(
      as(STRANGER_UID).doc('agentify_sessions/sess-new').set({ user_id: STRANGER_UID }),
    );
  });

  test('the owner cannot write a BRD revision', async () => {
    await assertFails(as(OWNER_UID).doc(`${BRD}/brd_revisions/rev-2`).set({ op: 'revert' }));
  });
});

describe('messages and BRD revisions are server-only', () => {
  test('the owner cannot read their session messages from the client', async () => {
    await assertFails(as(OWNER_UID).doc(MESSAGE).get());
  });

  test('a teammate cannot read them either', async () => {
    await assertFails(as(MATE_UID).collection(`${SESSION}/messages`).get());
  });

  test('the owner cannot read BRD revisions from the client', async () => {
    await assertFails(as(OWNER_UID).doc(REVISION).get());
  });
});

describe('the dashboard recommendations listener', () => {
  // DashboardContent.js subscribes to the org-keyed session's
  // recommendations filtered to the viewer's own rows: a listing the rules
  // can prove, where an unfiltered one is denied outright. A denied listener
  // never errors visibly, it just never populates, so the allowed shape is
  // pinned here.
  test('the owner-filtered query succeeds and returns only the viewer\'s rows', async () => {
    const snap = await assertSucceeds(
      as(OWNER_UID).collection(ORG_KEYED_RECS).where('owner_id', '==', OWNER_UID).get(),
    );
    expect(snap.docs.map((d) => d.id)).toEqual(['brd-owner']);
  });

  test('an unfiltered listing is denied even to an org member', async () => {
    await assertFails(as(MATE_UID).collection(ORG_KEYED_RECS).get());
  });
});

describe('organizations/{org}/brd_documents is server-only', () => {
  test('an org member cannot read an org BRD upload', async () => {
    await assertFails(as(MATE_UID).doc(ORG_UPLOAD).get());
  });

  test('an outsider cannot read it', async () => {
    await assertFails(as(OUTSIDER_UID).doc(ORG_UPLOAD).get());
  });

  test('an org member cannot write one', async () => {
    await assertFails(
      as(MATE_UID).doc(`organizations/${ORG}/brd_documents/doc-2`).set({ filename: 'Forged.pdf' }),
    );
  });
});
