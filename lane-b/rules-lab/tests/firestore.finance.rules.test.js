/**
 * Firestore rules unit tests for the finance-engine server-only closure in
 * `firestore.rules` (the main olbrain rules file).
 *
 * Run with the Firebase emulator:
 *   npm i -D @firebase/rules-unit-testing firebase-tools
 *   firebase emulators:exec --only firestore "npx jest tests/firestore-rules"
 *
 * Contract under test: every org subcollection the finance engine writes is
 * unreachable from the client SDK — reads and writes both — for ANY
 * authenticated user, while the client-used subcollections stay granted.
 * Client P&L data (statements, the confirmed model, registers, projection
 * runs, uploaded input files, deck templates/runs) must be impossible to
 * read or forge from a browser.
 */

const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-finance-rules-test';

const ORG = 'some-org';
const USER_UID = 'uid-authenticated-user';

// The full server-only exclusion list from firestore.rules — if a collection
// is added there, add it here; this suite is the auditor evidence.
const ENGINE_ONLY = [
  'secrets',
  'pnl_statements',
  'pnl_drivers',
  'finance_profile',
  'pnl_exports',
  'finance_policy',
  'finance_rm',
  'pnl_rm_projections',
  'rm_proposals',
  'finance_lines',
  'pnl_line_projections',
  // Added 2026-08-14 — the closure completion:
  'finance_model',
  'pnl_projections',
  'pnl_inputs',
  'pnl_bridges',
  'pnl_deck_templates',
  'pnl_deck_runs',
];

// Named client-used subcollections from the rules comment — these must keep
// working or the exclusion broke real screens.
const CLIENT_GRANTED = ['members', 'metrics', 'workflow_usage'];

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

  // Seed one doc per engine-only collection so the read-denial tests exercise
  // a real document, not a missing one.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    for (const sub of ENGINE_ONLY) {
      await db.doc(`organizations/${ORG}/${sub}/seeded`).set({
        org_id: ORG,
        note: 'server-written finance data',
      });
    }
    for (const sub of CLIENT_GRANTED) {
      await db.doc(`organizations/${ORG}/${sub}/seeded`).set({ org_id: ORG });
    }
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('finance engine server-only closure', () => {
  test.each(ENGINE_ONLY)(
    'authenticated client cannot READ organizations/{org}/%s',
    async (sub) => {
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertFails(db.doc(`organizations/${ORG}/${sub}/seeded`).get());
    }
  );

  test.each(ENGINE_ONLY)(
    'authenticated client cannot WRITE organizations/{org}/%s',
    async (sub) => {
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertFails(
        db.doc(`organizations/${ORG}/${sub}/forged`).set({ forged: true })
      );
    }
  );

  test.each(ENGINE_ONLY)(
    'unauthenticated client cannot READ organizations/{org}/%s',
    async (sub) => {
      const db = env.unauthenticatedContext().firestore();
      await assertFails(db.doc(`organizations/${ORG}/${sub}/seeded`).get());
    }
  );

  test.each(ENGINE_ONLY)(
    'nested paths under organizations/{org}/%s are also unreachable',
    async (sub) => {
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertFails(
        db.doc(`organizations/${ORG}/${sub}/seeded/versions/v1`).get()
      );
    }
  );

  test.each(CLIENT_GRANTED)(
    'client-used subcollection organizations/{org}/%s stays readable',
    async (sub) => {
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertSucceeds(db.doc(`organizations/${ORG}/${sub}/seeded`).get());
    }
  );
});
