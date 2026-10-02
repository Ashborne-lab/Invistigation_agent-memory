/**
 * Firestore rules unit tests for the agent data store's server-only closure
 * in `firestore.rules`.
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 *
 * What this pins, and why it exists. The data store holds the rows an agent
 * records mid-conversation into a builder-declared table — in practice
 * end-user PII, since that is what builders ask agents to collect. It shipped
 * with NO rule of its own, and the subcollection catch-all at the bottom of
 * the rules file matches any path four segments deep or more:
 *
 *   match /{collection}/{docId}/{sub}/{rest=**} {
 *     allow read:  if isAuthenticated() && !(collection in [...]);
 *     allow write: if isAuthenticated() && !(collection in [...]);
 *   }
 *
 * `agent_datastores` was in neither exclusion list, so every entry document
 * was readable AND writable by any signed-in user on the platform, across
 * tenants. Production held zero entries for the whole window, which is the
 * only reason it cost nothing.
 *
 * The fix is the pair the rules file's own `lead_profiles` comment describes:
 * an explicit `if false` block AND the collection named in both catch-alls.
 * Rules OR together, so either half alone is powerless. These tests fail if
 * either half is removed.
 */

const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-datastore-rules-test';

const ORG = 'some-org';
const AGENT = 'agent-abc';
const TABLE = 'tbl1';
const USER_UID = 'uid-authenticated-user';

// Every depth the data store occupies, because each is matched by a DIFFERENT
// rule: the agent document by the top-level catch-all, the table header and
// the entries by the subcollection catch-all.
const PATHS = {
  'the agent document': `agent_datastores/${AGENT}`,
  'the tables collection': `agent_datastores/${AGENT}/tables/${TABLE}`,
  'an entry': `agent_datastores/${AGENT}/tables/${TABLE}/entries/e1`,
};

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

  // Seed real documents so the read denials exercise an existing document
  // rather than a missing one — Firestore denies both, and a test that cannot
  // tell them apart proves less than it appears to.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(PATHS['the agent document']).set({ organization_id: ORG });
    await db.doc(PATHS['the tables collection']).set({
      name: 'Bookings',
      slug: 'bookings',
      organization_id: ORG,
      columns: [{ key: 'full_name', label: 'Full name', type: 'string' }],
    });
    await db.doc(PATHS['an entry']).set({
      entry_id: 'e1',
      session_id: 's1',
      values: { full_name: 'Someone Real' },
    });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('agent data store is unreachable from any client', () => {
  test.each(Object.entries(PATHS))(
    'an authenticated user cannot READ %s',
    async (_label, docPath) => {
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertFails(db.doc(docPath).get());
    }
  );

  test.each(Object.entries(PATHS))(
    'an authenticated user cannot WRITE %s',
    async (_label, docPath) => {
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertFails(db.doc(docPath).set({ forged: true }));
    }
  );

  test.each(Object.entries(PATHS))(
    'an unauthenticated client cannot READ %s',
    async (_label, docPath) => {
      const db = env.unauthenticatedContext().firestore();
      await assertFails(db.doc(docPath).get());
    }
  );

  test('an authenticated user cannot LIST a table\'s entries', async () => {
    // The operator's rows view is a list, not a get, and a rule that denied
    // only single-document reads would leave the whole table enumerable.
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertFails(
      db.collection(`agent_datastores/${AGENT}/tables/${TABLE}/entries`).get()
    );
  });

  test('an authenticated user cannot DELETE an entry', async () => {
    // Deletion is the destructive half of write and is worth its own case:
    // the operator's delete goes through the REST API, never the client SDK.
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertFails(db.doc(PATHS['an entry']).delete());
  });
});

describe('the closure did not over-reach', () => {
  // A neighbouring five-segment path that the subcollection catch-all should
  // still grant. If this starts failing, the exclusion was written too wide
  // and took unrelated screens down with it.
  test('an unrelated subcollection is still readable', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      await ctx.firestore().doc('some_collection/doc1/sub/item1').set({ ok: true });
    });
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertSucceeds(db.doc('some_collection/doc1/sub/item1').get());
  });
});
