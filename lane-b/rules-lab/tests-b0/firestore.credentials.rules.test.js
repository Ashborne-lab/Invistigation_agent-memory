/**
 * Firestore rules unit tests for `credentials` and `mcp_tool_executions` —
 * the platform-side half of the Notion connector's cross-tenant fix (see
 * docs/superpowers/specs/2026-09-25-notion-connector-design.md §5c in
 * olbrain_lab).
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 * (needs a JDK >= 21 — see tests/firestore-rules/README.md.)
 *
 * WHAT WAS OPEN. `credentials` was in NO match block, so it fell through to
 * both catch-alls (`match /{collection}/{docId}` and the four-segment
 * `match /{collection}/{docId}/{sub}/{rest=**}`) and inherited
 * `allow read, write: if isAuthenticated()` for every signed-in user in any
 * org. The documents hold KMS-wrapped per-agent MCP server secrets, keyed
 * `{agentId}:{serverName}` (olbrain-mcp-deployer
 * runtime/services/kms_credential_service.py), or `default:{serverName}` for
 * the env-fallback tier every unconfigured agent tries
 * (`_get_credentials_for_server` tier 3). Because the *ciphertext* carried no
 * additional authenticated data until this same design's platform PR, a
 * stranger who could read one victim's `encrypted_credentials` and write it
 * into their own agent's document (or into `default:{server}`) got the same
 * KMS key to decrypt it for them — no org boundary was ever checked. AAD
 * binding is the other half of that fix and lives in olbrain-mcp-deployer;
 * this rule closes the platform side regardless of which half lands first.
 * No client reads or writes `credentials` — Studio's Configure flow
 * (`POST /api/v1/credentials`) and every tool call go through
 * studio-backend / agent-design HTTP routes, which use the Admin SDK.
 *
 * `mcp_tool_executions` was in no match block either, so a forged row could
 * plant a fake tool-call log in someone else's Execution Logs tab. This one
 * is WRITE-only: the tab still reads the collection with the client SDK
 * (src/services/analytics/executionLogs/executionLogsService.js) and the
 * documents carry no `organization_id`, so an org-scoped read isn't possible
 * yet — read stays on the catch-alls' blanket `isAuthenticated()` grant, the
 * same gap `knowledge_library` and `research_plans` already document above
 * it, not closed here.
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

const PROJECT_ID = 'olbrain-credentials-rules-test';
const ATTACKER_UID = 'uid-signed-in-stranger';

// Keyed by agentId:serverName, which is what a copied ciphertext would target.
const VICTIM_AGENT = 'victim-agent-id';
const CREDENTIAL_DOC = `${VICTIM_AGENT}:notion`;
const DEFAULT_TIER_DOC = 'default:notion'; // tier-3 fallback every unconfigured agent tries

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
    await db.doc(`credentials/${CREDENTIAL_DOC}`).set({
      encrypted_credentials: 'dGVzdC1jaXBoZXJ0ZXh0LWJhc2U2NA==',
      agent_id: VICTIM_AGENT,
      server_name: 'notion',
    });
    await db.doc(`credentials/${DEFAULT_TIER_DOC}`).set({
      encrypted_credentials: 'ZGVmYXVsdC10aWVyLWNpcGhlcnRleHQ=',
      agent_id: 'default',
      server_name: 'notion',
    });
    await db.doc('mcp_tool_executions/log-1').set({
      agent_id: VICTIM_AGENT,
      tool_name: 'notion_search',
      status: 'success',
      timestamp: Date.now(),
    });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('credentials — reads denied', () => {
  test('a signed-in stranger CANNOT read another agent\'s credential doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`credentials/${CREDENTIAL_DOC}`).get());
  });

  test('an unauthenticated client CANNOT read it either', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(db.doc(`credentials/${CREDENTIAL_DOC}`).get());
  });

  test('CANNOT list the collection to find which agents have credentials', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.collection('credentials').get());
  });

  test('CANNOT read the shared default-tier fallback doc either', async () => {
    // The design's tier-3 fallback: every agent with no token of its own
    // tries `default:{server}`, so it is as sensitive as any per-agent doc.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`credentials/${DEFAULT_TIER_DOC}`).get());
  });
});

describe('credentials — writes denied (a copied ciphertext is a decrypt-for-me primitive)', () => {
  test('CANNOT overwrite another agent\'s credential doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`credentials/${CREDENTIAL_DOC}`).update({
        encrypted_credentials: 'YXR0YWNrZXItc3Vic3RpdHV0ZWQ=',
      })
    );
  });

  test('CANNOT plant a victim\'s ciphertext under an attacker-owned agent id', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('credentials/attacker-agent-id:notion').set({
        encrypted_credentials: 'dGVzdC1jaXBoZXJ0ZXh0LWJhc2U2NA==',
        agent_id: 'attacker-agent-id',
        server_name: 'notion',
      })
    );
  });

  test('CANNOT overwrite the shared default-tier fallback doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`credentials/${DEFAULT_TIER_DOC}`).update({
        encrypted_credentials: 'YXR0YWNrZXItc3Vic3RpdHV0ZWQ=',
      })
    );
  });

  test('CANNOT delete a credential doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`credentials/${CREDENTIAL_DOC}`).delete());
  });
});

// The gap that shipped in the first version of the twilio_accounts fix: every
// case above is a TWO-segment path, and this suite's own edit adds
// `credentials` to both the two-segment AND four-segment lists at once, so a
// future subcollection (e.g. a rotation history) inherits the same fence.
describe('credentials — subcollections are fenced too', () => {
  test('CANNOT read a nested document under a credential', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`credentials/${CREDENTIAL_DOC}/history/h1`).get());
  });

  test('CANNOT write a nested document under a credential', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`credentials/${CREDENTIAL_DOC}/history/h1`).set({ x: 1 })
    );
  });
});

describe('mcp_tool_executions — writes denied (a forged row is a fabricated log)', () => {
  test('CANNOT plant a fake execution log entry', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('mcp_tool_executions/forged-log').set({
        agent_id: VICTIM_AGENT,
        tool_name: 'notion_get_page',
        status: 'success',
        timestamp: Date.now(),
      })
    );
  });

  test('CANNOT edit an existing execution log entry', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('mcp_tool_executions/log-1').update({ status: 'success' })
    );
  });

  test('CANNOT delete an execution log entry', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc('mcp_tool_executions/log-1').delete());
  });
});

describe('mcp_tool_executions — reads stay allowed (the Execution Logs tab needs it)', () => {
  test('a signed-in user CAN still read a single execution log doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertSucceeds(db.doc('mcp_tool_executions/log-1').get());
  });

  test('a signed-in user CAN still query/list execution logs', async () => {
    // Mirrors executionLogsService.js's collection query, which is how the
    // Execution Logs tab's client-SDK listener reads this collection.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertSucceeds(db.collection('mcp_tool_executions').get());
  });
});

// The Admin SDK is the only legitimate accessor for `credentials` and the only
// writer for `mcp_tool_executions`, and both bypass rules entirely. Pinned so
// that "we locked it down" cannot be confused with "we broke the writer".
describe('the Admin SDK still works, which is the only path that ever mattered', () => {
  test('a rules-disabled context can still read and write credentials', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      const snap = await db.doc(`credentials/${CREDENTIAL_DOC}`).get();
      expect(snap.exists).toBe(true);
      await db.doc(`credentials/${CREDENTIAL_DOC}`).update({ server_name: 'notion' });
    });
  });

  test('a rules-disabled context can still write mcp_tool_executions', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      await db.doc('mcp_tool_executions/log-2').set({
        agent_id: VICTIM_AGENT,
        tool_name: 'notion_search',
        status: 'success',
        timestamp: Date.now(),
      });
      const snap = await db.doc('mcp_tool_executions/log-2').get();
      expect(snap.exists).toBe(true);
    });
  });
});
