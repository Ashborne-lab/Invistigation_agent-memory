/**
 * Firestore rules unit tests for the two client-write exclusions that guard
 * the research approval surface in `firestore.rules` (the main olbrain rules
 * file): `research_plans`, and the `research_chat_sessions` DOCUMENT.
 *
 * Run with the Firebase emulator:
 *   npm i -D @firebase/rules-unit-testing firebase-tools
 *   firebase emulators:exec --only firestore "npx jest tests/firestore-rules"
 *
 * They are one contract with one attack behind it. Approving a plan starts a
 * run the org pays for, and the gate that authorises it reads two documents:
 * the plan (verbatim, into the run subject) and the session (`started_by` and
 * `org_id`). Both are top-level collections matched by the catch-all at
 * `match /{collection}/{docId}`, so both have to be excluded from its write
 * grant or any signed-in user can forge either one into another org.
 *
 * Only the runtime's Admin SDK writes them, and the Admin SDK bypasses rules,
 * so the exclusions cost the product nothing. Reads are a *deliberate*
 * exception — pinned here so a later change cannot silently revoke them
 * without this test turning red.
 */

const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-research-plans-rules-test';

const USER_UID = 'uid-authenticated-user';
const OTHER_ORG_UID = 'uid-other-org-user';

// The session owner, and the org whose money is at stake.
const OWNER_UID = 'uid-session-owner';
const OWNER_ORG = 'org-victim';

let env;

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      host: '127.0.0.1',
      port: 8080,
      rules: fs.readFileSync(path.join(__dirname, '../../firestore.rules'), 'utf8'),
    },
  });

  // Seed one plan doc and one session doc so the read/write-denial tests
  // exercise real documents, not missing ones. The session is owned by
  // OWNER_UID in OWNER_ORG — the victim in every cross-tenant case below.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc('research_plans/seeded').set({
      org_id: 'some-org',
      status: 'proposed',
    });
    await db.doc('research_chat_sessions/seeded').set({
      started_by: OWNER_UID,
      org_id: OWNER_ORG,
      template_id: 't1',
    });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('research_plans (client-write hole closed, read left open)', () => {
  test('authenticated client CANNOT write (create) research_plans', async () => {
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertFails(
      db.doc('research_plans/forged').set({ org_id: 'some-org', status: 'approved' })
    );
  });

  test('authenticated client CANNOT overwrite an existing plan (update)', async () => {
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertFails(
      db.doc('research_plans/seeded').update({ status: 'approved' })
    );
  });

  test('authenticated client from another org CANNOT write a forged plan either', async () => {
    const db = env.authenticatedContext(OTHER_ORG_UID).firestore();
    await assertFails(
      db.doc('research_plans/forged-cross-org').set({ org_id: 'some-org', status: 'approved' })
    );
  });

  test('unauthenticated client CANNOT write research_plans', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(
      db.doc('research_plans/forged-anon').set({ org_id: 'some-org', status: 'approved' })
    );
  });

  // Pinning the deliberate decision: read stays open via the catch-all
  // because org claims are issued under several names and an org-scoped
  // read rule would blank the Plan tab for tokens using a different claim.
  // If this test goes red, someone added `research_plans` to the read
  // exclusion list without the claims audit this brief calls for.
  test('authenticated client CAN read research_plans (deliberate, not a regression)', async () => {
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertSucceeds(db.doc('research_plans/seeded').get());
  });

  test('unauthenticated client CANNOT read research_plans', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(db.doc('research_plans/seeded').get());
  });
});
describe('research_chat_sessions document (the approve gate\'s own inputs)', () => {
  // The hole this closes: only the `messages` SUBCOLLECTION was excluded, and
  // it was excluded from the four-segment catch-all
  // (`match /{collection}/{docId}/{sub}/{rest=**}`). A session document is two
  // segments, so that exclusion never touched it and the top-level catch-all
  // granted every authenticated user write on every session in every org.
  //
  // What that buys an attacker: `_verify_session` in the research runtime
  // authorises a plan approval by comparing the session's `started_by` to the
  // caller's uid and its `org_id` to the caller's org. Rewrite those two
  // fields and the session — and the billed run it can start — is yours.

  test('a stranger CANNOT rewrite another org\'s session document', async () => {
    const db = env.authenticatedContext(USER_UID, { org_id: 'org-attacker' }).firestore();
    await assertFails(
      db.doc('research_chat_sessions/seeded').update({ started_by: USER_UID })
    );
  });

  test('a stranger CANNOT take a session over by org either', async () => {
    const db = env.authenticatedContext(USER_UID, { org_id: 'org-attacker' }).firestore();
    await assertFails(
      db.doc('research_chat_sessions/seeded').update({ org_id: 'org-attacker' })
    );
  });

  test('a stranger CANNOT delete another org\'s session document', async () => {
    const db = env.authenticatedContext(USER_UID, { org_id: 'org-attacker' }).firestore();
    await assertFails(db.doc('research_chat_sessions/seeded').delete());
  });

  test('an unauthenticated client CANNOT write a session document', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(
      db.doc('research_chat_sessions/forged-anon').set({ started_by: 'anyone' })
    );
  });

  // The explicit owner-scoped match block is now the only write grant, so it
  // has to still work. If this goes red the exclusion took a real grant with
  // it, not just the hole.
  test('the owner CAN still update their own session', async () => {
    const db = env.authenticatedContext(OWNER_UID, { org_id: OWNER_ORG }).firestore();
    await assertSucceeds(
      db.doc('research_chat_sessions/seeded').update({ title: 'renamed' })
    );
  });

  // Same deliberate decision as research_plans above, and for the same
  // reason: org claims are issued under several names on this platform, so an
  // org-scoped read rule would blank live chat history for tokens carrying a
  // different one. Pinned so the gap stays a decision rather than a surprise.
  test('an authenticated client CAN read a session document (deliberate, not a regression)', async () => {
    const db = env.authenticatedContext(USER_UID, { org_id: 'org-attacker' }).firestore();
    await assertSucceeds(db.doc('research_chat_sessions/seeded').get());
  });

  test('an unauthenticated client CANNOT read a session document', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(db.doc('research_chat_sessions/seeded').get());
  });
});
