/**
 * Firestore rules unit tests for `public_mcp_servers` — the MCP catalog.
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 * (needs a JDK >= 21 — see tests/firestore-rules/README.md.)
 *
 * WHAT WAS OPEN. `public_mcp_servers` (doc id = server id; fields include
 * `service_url` / `pre_deployed_url`) was in NO match block, so it fell
 * through to both catch-alls (`match /{collection}/{docId}` and the
 * four-segment `match /{collection}/{docId}/{sub}/{rest=**}`) and inherited
 * `allow read, write: if isAuthenticated()` for every signed-in user in any
 * org. agent-design's configure-and-enable flow reads `service_url` /
 * `pre_deployed_url` off a catalog doc and POSTs the user's PASTED MCP keys
 * there (mcp_service.py:439-442, 1474-1530), and Studio's OAuth popups use
 * `service_url` too — so a forged/repointed catalog doc exfiltrates other
 * users' API keys and TRACES credentials to an attacker-controlled endpoint,
 * no org boundary required.
 *
 * All client code only READS this collection — Studio
 * (src/services/_infra/data/FirestoreDataAccess.js:~1535 getDocs,
 * src/services/api-integration/mcpDeployment/mcpDeploymentService.js:~91
 * getDoc) and Noesis (FirestoreDataAccess.js:~1553 getDocs). The only writer
 * is the deployer CI via the Admin SDK, which bypasses rules. So this suite
 * asserts: reads stay open, every client-SDK write shape is denied (create,
 * update — including just `service_url` — and delete), and a subcollection
 * path is denied too (the four-segment catch-all is a separate list; rules
 * OR together, so both must exclude it).
 *
 * The compat surface (`db.doc(path).get()`) is deliberate:
 * @firebase/rules-unit-testing@4.0.1 imports firebase/compat/firestore, so
 * `ctx.firestore()` is a compat handle and modular getDoc will not take it.
 */

const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-public-mcp-servers-rules-test';
const ATTACKER_UID = 'uid-signed-in-stranger';

const SERVER_DOC = 'notion'; // doc id = server id, e.g. public_mcp_servers/notion

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

  // Seeded the way the deployer writes it: Admin SDK, rules bypassed.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`public_mcp_servers/${SERVER_DOC}`).set({
      name: 'Notion',
      service_url: 'https://mcp-notion.olbrain-legit.example/run',
      pre_deployed_url: 'https://mcp-notion.olbrain-legit.example/run',
      status: 'active',
    });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('public_mcp_servers — reads stay allowed (Studio/Noesis read the catalog client-side)', () => {
  test('a signed-in user CAN get a single catalog doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertSucceeds(db.doc(`public_mcp_servers/${SERVER_DOC}`).get());
  });

  test('a signed-in user CAN list the catalog', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertSucceeds(db.collection('public_mcp_servers').get());
  });
});

describe('public_mcp_servers — writes denied (a forged doc exfiltrates pasted MCP keys)', () => {
  test('CANNOT create a new catalog doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('public_mcp_servers/attacker-server').set({
        name: 'Attacker Server',
        service_url: 'https://attacker.example/collect',
        pre_deployed_url: 'https://attacker.example/collect',
        status: 'active',
      })
    );
  });

  test('CANNOT update an existing catalog doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`public_mcp_servers/${SERVER_DOC}`).update({ status: 'disabled' })
    );
  });

  test('CANNOT repoint service_url on an existing catalog doc', async () => {
    // This is the actual attack: repoint the URL agent-design POSTs pasted
    // keys to, without touching anything else about the doc.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`public_mcp_servers/${SERVER_DOC}`).update({
        service_url: 'https://attacker.example/collect',
      })
    );
  });

  test('CANNOT delete a catalog doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`public_mcp_servers/${SERVER_DOC}`).delete());
  });
});

// The gap the credentials/mcp_tool_executions fix documented: a two-segment
// exclusion alone leaves the four-segment catch-all wide open for anything
// nested under the collection. Rules OR together, so both lists must exclude
// `public_mcp_servers` for this to actually be denied.
describe('public_mcp_servers — subcollection paths are fenced too', () => {
  test('CANNOT write a nested document under a catalog doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`public_mcp_servers/${SERVER_DOC}/versions/v1`).set({ x: 1 })
    );
  });
});

// The Admin SDK is the only legitimate writer, and it bypasses rules
// entirely. Pinned so that "we locked it down" cannot be confused with
// "we broke the deployer".
describe('the Admin SDK still works, which is the only path that ever mattered', () => {
  test('a rules-disabled context can still write public_mcp_servers', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      // set(), not update(): independent of whether earlier tests left the seeded doc in place.
      await db.doc(`public_mcp_servers/${SERVER_DOC}`).set({ status: 'active' }, { merge: true });
      const snap = await db.doc(`public_mcp_servers/${SERVER_DOC}`).get();
      expect(snap.exists).toBe(true);
      expect(snap.data().status).toBe('active');
    });
  });
});
