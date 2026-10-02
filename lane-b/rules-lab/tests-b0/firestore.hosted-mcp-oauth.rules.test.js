/**
 * Firestore rules unit tests for the hosted-MCP OAuth data model (spec §4
 * Studio, §5 Data model; docs/superpowers/specs/2026-09-26-hosted-mcp-connect-design.md
 * in olbrain_lab). Task 8 part A (Studio S8).
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 * (needs a JDK >= 21 — see tests/firestore-rules/README.md.)
 *
 * WHAT WAS OPEN (before this suite's rule changes).
 *
 * `agents/{agentId}/oauth_tokens/{provider}` fell through to the
 * `/agents/{agentId}/{sub}/{rest=**}` catch-all (only `owner_lessons` and
 * `mcp_configs` were excluded), so it inherited
 * `allow read, write: if isAuthenticated() && sub != 'owner_lessons' && sub != 'mcp_configs'`
 * — any signed-in user, in any org, including a stranger to the agent's org,
 * could read or overwrite another agent's KMS-wrapped Notion access/refresh
 * tokens. This is a total client-side deny: only the deployer's Admin SDK
 * (token_store.py) reads or writes these documents; even the agent's own
 * owner has no legitimate client-SDK reason to touch them.
 *
 * `oauth_states/{sha256(state)}` and `oauth_clients/{provider}:{hash}}` were
 * in NO match block, so they fell through to the top-level two-segment
 * catch-all (`match /{collection}/{docId}`) and inherited
 * `allow read, write: if isAuthenticated()`. `oauth_states` holds a
 * KMS-encrypted PKCE code_verifier plus the `uid`/`agent_id`/`provider` the
 * `complete` step checks — a stranger overwriting or reading a state doc
 * could hijack another user's in-flight OAuth handshake. `oauth_clients` is
 * the DCR-fallback client registration record; a forged doc could substitute
 * a different `client_id`. Both are server-only: the deployer's Admin SDK
 * (hosted_oauth/flow.py, registration.py) is the only reader/writer.
 *
 * `agents/{agentId}/mcp_configs/{configId}` already required
 * `canUseAgent(agentId)` (owner or org member) for BOTH read and write, but
 * write was unrestricted on WHICH fields — any editor could set or change
 * `tool_access` directly through the client SDK, bypassing agent-design's
 * `set_tool_access` (mcp_service.py:689), which is the only place the
 * `hosted_mcp` "allowlist-only" rule (contract.md) is enforced. A client
 * write straight to Firestore could restore a blocklist/`all` mode, or
 * silently re-enable a tool the panel shows as off. This closes the FIELD,
 * not the collection: every other `mcp_configs` field (`enabled`, `config`,
 * ...) keeps working exactly as before for the owner/org-member write the
 * product already relies on (McpConfigDialog Save, configureAndEnableMcpServer).
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

const PROJECT_ID = 'olbrain-hosted-mcp-oauth-rules-test';
const OWNER_UID = 'uid-agent-owner';
const ATTACKER_UID = 'uid-signed-in-stranger';

const AGENT_ID = 'agent-victim-1';
const PROVIDER = 'notion-hosted';

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

  // Seeded the way the platform actually writes these: Admin SDK, rules
  // bypassed. `canUseAgent` (used by the mcp_configs block) needs the agent
  // document itself to resolve ownership.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`agents/${AGENT_ID}`).set({
      userId: OWNER_UID,
      owner_id: OWNER_UID,
      name: 'Victim Agent',
    });
    await db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).set({
      encrypted_token: 'ZmFrZS1jaXBoZXJ0ZXh0LWJhc2U2NA==',
      grant_id: 'grant-1',
      token_version: 1,
      status: 'connected',
      connected_by: OWNER_UID,
    });
    await db.doc('oauth_states/deadbeef00112233').set({
      provider: PROVIDER,
      server_id: PROVIDER,
      agent_id: AGENT_ID,
      uid: OWNER_UID,
      redirect_uri: 'https://studio.olbrain.com/auth/mcp/callback',
      code_verifier_ct: 'ZmFrZS12ZXJpZmllcg==',
    });
    await db.doc(`oauth_clients/${PROVIDER}:abcd1234abcd1234`).set({
      client_id: 'dcr-client-1',
      token_endpoint_auth_method: 'none',
      registered_at: '2026-09-26T00:00:00Z',
    });
    await db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).set({
      enabled: true,
    });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('agents/{agentId}/oauth_tokens/{provider} — deny-all client access', () => {
  test('a stranger CANNOT read another agent\'s oauth token doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).get());
  });

  test('the agent OWNER cannot read the oauth token doc either — deny-all, not owner-scoped', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertFails(db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).get());
  });

  test('CANNOT list the oauth_tokens subcollection', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertFails(db.collection(`agents/${AGENT_ID}/oauth_tokens`).get());
  });

  test('a stranger CANNOT overwrite another agent\'s oauth token doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).update({ status: 'connected' })
    );
  });

  test('the agent OWNER cannot write the oauth token doc either', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertFails(
      db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).update({ status: 'connected' })
    );
  });

  test('CANNOT create a new oauth token doc under a different (attacker-owned) agent', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`agents/attacker-agent/oauth_tokens/${PROVIDER}`).set({ status: 'connected' })
    );
  });

  test('CANNOT delete an oauth token doc', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertFails(db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).delete());
  });
});

describe('oauth_states/{hash} — deny-all client access (single-use PKCE state)', () => {
  test('CANNOT read a state doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc('oauth_states/deadbeef00112233').get());
  });

  test('CANNOT list oauth_states', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.collection('oauth_states').get());
  });

  test('CANNOT overwrite a state doc (hijack another user\'s in-flight handshake)', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('oauth_states/deadbeef00112233').update({ uid: ATTACKER_UID })
    );
  });

  test('CANNOT create a new state doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('oauth_states/forgedstatehash01').set({ provider: PROVIDER, uid: ATTACKER_UID })
    );
  });

  test('CANNOT delete a state doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc('oauth_states/deadbeef00112233').delete());
  });
});

describe('oauth_clients/{provider}:{hash} — deny-all client access (DCR fallback registration)', () => {
  test('CANNOT read a client registration doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`oauth_clients/${PROVIDER}:abcd1234abcd1234`).get());
  });

  test('CANNOT list oauth_clients', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.collection('oauth_clients').get());
  });

  test('CANNOT overwrite a client registration doc (substitute a different client_id)', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`oauth_clients/${PROVIDER}:abcd1234abcd1234`).update({ client_id: 'attacker-client' })
    );
  });

  test('CANNOT create a new client registration doc', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`oauth_clients/${PROVIDER}:ffffffffffffffff`).set({ client_id: 'attacker-client' })
    );
  });
});

describe('agents/{agentId}/mcp_configs/{configId}.tool_access — write guard (the mutation check)', () => {
  test('an editor CANNOT create a config doc that sets tool_access directly', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertFails(
      db.doc(`agents/${AGENT_ID}/mcp_configs/other-server`).set({
        enabled: true,
        tool_access: { mode: 'allowlist', tools: { search: true } },
      })
    );
  });

  test('THE MUTATION CHECK: an editor CANNOT update tool_access on an existing config doc', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertFails(
      db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).update({
        tool_access: { mode: 'allowlist', tools: { search: true } },
      })
    );
  });

  test('an editor CANNOT set tool_access via a dotted sub-field path either', async () => {
    // affectedKeys() collapses a dotted update path to its top-level field,
    // so `tool_access.mode` must be caught by the same guard as a full
    // `tool_access` object replace.
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertFails(
      db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).update({
        'tool_access.mode': 'allowlist',
      })
    );
  });

  test('a stranger (not owner/org member) still cannot write tool_access either — belt and suspenders', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).update({
        tool_access: { mode: 'allowlist', tools: {} },
      })
    );
  });

  test('the SAME editor CAN still update a non-tool_access field — the guard is field-scoped, not a blanket deny', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertSucceeds(
      db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).update({ enabled: false })
    );
    // Restore for the tests below / test order independence.
    await assertSucceeds(
      db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).update({ enabled: true })
    );
  });

  test('the owner CAN still create a NEW config doc that carries no tool_access', async () => {
    const db = env.authenticatedContext(OWNER_UID).firestore();
    await assertSucceeds(
      db.doc(`agents/${AGENT_ID}/mcp_configs/some-other-server`).set({ enabled: true, config: { x: 1 } })
    );
  });
});

// The Admin SDK is the only legitimate accessor for oauth_tokens/oauth_states/
// oauth_clients, and the only writer of mcp_configs.tool_access. Pinned so
// that "we locked it down" cannot be confused with "we broke the backend".
describe('the Admin SDK still works, which is the only path that ever mattered', () => {
  test('a rules-disabled context can still read/write oauth_tokens', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      await db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).update({ token_version: 2 });
      const snap = await db.doc(`agents/${AGENT_ID}/oauth_tokens/${PROVIDER}`).get();
      expect(snap.data().token_version).toBe(2);
    });
  });

  test('a rules-disabled context can still write oauth_states and oauth_clients', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      await db.doc('oauth_states/deadbeef00112233').update({ redirect_uri: 'https://studio.olbrain.com/auth/mcp/callback' });
      await db.doc(`oauth_clients/${PROVIDER}:abcd1234abcd1234`).update({ registered_at: '2026-09-26T01:00:00Z' });
    });
  });

  test('a rules-disabled context (agent-design) can still write mcp_configs.tool_access', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      await db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).update({
        tool_access: { mode: 'allowlist', tools: { search: true } },
      });
      const snap = await db.doc(`agents/${AGENT_ID}/mcp_configs/${PROVIDER}`).get();
      expect(snap.data().tool_access.mode).toBe('allowlist');
    });
  });
});
