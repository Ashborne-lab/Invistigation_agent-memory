/**
 * Firestore rules unit tests for `firestore.clix.rules`.
 *
 * Run with the Firebase emulator:
 *   npm i -D @firebase/rules-unit-testing firebase-tools
 *   firebase emulators:exec --only firestore "npx jest tests/firestore-rules"
 *
 * These tests verify the contract that auditors care about most:
 *   - Cross-tenant reads are denied (org A cannot read org B's data).
 *   - PII collections (whatsapp phones, conversations) are not client-readable
 *     across tenants.
 *   - Backend-only collections cannot be touched by any client.
 *   - `organization_id` cannot be mutated on update.
 */

const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'clix-capital-prod-rules-test';

const ORG_A = 'clix-capital';
const ORG_B = 'other-tenant';

const USER_A_UID = 'uid-clix-user';
const USER_B_UID = 'uid-other-user';
const ADMIN_A_UID = 'uid-clix-admin';

let env;

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      host: '127.0.0.1',
      port: 8080,
      rules: fs.readFileSync(path.join(__dirname, '../../firestore.clix.rules'), 'utf8'),
    },
  });

  // Seed memberships using the admin context (rules bypassed).
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`memberships/${USER_A_UID}_${ORG_A}`).set({
      user_id: USER_A_UID,
      organization_id: ORG_A,
      role: 'viewer',
      status: 'active',
    });
    await db.doc(`memberships/${ADMIN_A_UID}_${ORG_A}`).set({
      user_id: ADMIN_A_UID,
      organization_id: ORG_A,
      role: 'admin',
      status: 'active',
    });
    await db.doc(`memberships/${USER_B_UID}_${ORG_B}`).set({
      user_id: USER_B_UID,
      organization_id: ORG_B,
      role: 'viewer',
      status: 'active',
    });
    // Pre-existing docs in each org used for read-isolation tests.
    await db.doc(`conversations/conv-a`).set({
      organization_id: ORG_A,
      message_content: 'hello from clix',
    });
    await db.doc(`conversations/conv-b`).set({
      organization_id: ORG_B,
      message_content: 'hello from other tenant',
    });
    await db.doc(`agents/agent-a`).set({
      organization_id: ORG_A,
      owner_id: USER_A_UID,
      name: 'Clix agent',
    });
    await db.doc(`whatsapp_user_phones/phone-1`).set({
      organization_id: ORG_A,
      phone: '+910000000000',
    });
    await db.doc(`secrets/api-key-1`).set({ value: 'sk-secret' });
    await db.doc(`organizations/${ORG_A}/secrets/internal`).set({ value: 'internal' });
  });
});

afterAll(async () => {
  if (env) await env.cleanup();
});

beforeEach(async () => {
  // Don't clear — we rely on seed data above. Tests only create test-specific docs.
});

const ctxFor = (uid) =>
  uid
    ? env.authenticatedContext(uid).firestore()
    : env.unauthenticatedContext().firestore();

describe('default deny', () => {
  test('unauthenticated reads denied on every enumerated collection', async () => {
    const db = ctxFor(null);
    await assertFails(db.doc('agents/agent-a').get());
    await assertFails(db.doc('conversations/conv-a').get());
    await assertFails(db.doc('memberships/anything').get());
  });

  test('reads against unenumerated collection denied', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc('completely_made_up/x').get());
    await assertFails(db.doc('debug/x').get());
  });
});

describe('cross-tenant isolation', () => {
  test('org-A user CAN read own org conversation', async () => {
    const db = ctxFor(USER_A_UID);
    await assertSucceeds(db.doc('conversations/conv-a').get());
  });

  test('org-A user CANNOT read org-B conversation', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc('conversations/conv-b').get());
  });

  test('org-B user CANNOT read org-A conversation', async () => {
    const db = ctxFor(USER_B_UID);
    await assertFails(db.doc('conversations/conv-a').get());
  });

  test('org-A user CAN read own agent', async () => {
    const db = ctxFor(USER_A_UID);
    await assertSucceeds(db.doc('agents/agent-a').get());
  });

  test('org-B user CANNOT read org-A agent', async () => {
    const db = ctxFor(USER_B_UID);
    await assertFails(db.doc('agents/agent-a').get());
  });
});

describe('PII (whatsapp phones, secrets) blocked from all clients', () => {
  test('phone PII not client-readable even by same-org member', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc('whatsapp_user_phones/phone-1').get());
  });

  test('phone PII not writable by admin either', async () => {
    const db = ctxFor(ADMIN_A_UID);
    await assertFails(
      db.doc('whatsapp_user_phones/phone-2').set({
        organization_id: ORG_A,
        phone: '+910000000001',
      })
    );
  });

  test('secrets collection blocked', async () => {
    const db = ctxFor(ADMIN_A_UID);
    await assertFails(db.doc('secrets/api-key-1').get());
    await assertFails(db.doc('secrets/api-key-1').set({ value: 'x' }));
  });

  test('org sub-secrets blocked even from owner', async () => {
    const db = ctxFor(ADMIN_A_UID);
    await assertFails(db.doc(`organizations/${ORG_A}/secrets/internal`).get());
  });
});

describe('backend-only collections client-denied', () => {
  test('agent_sessions write denied', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(
      db.doc('agent_sessions/x').set({
        organization_id: ORG_A,
        agent_id: 'agent-a',
      })
    );
  });

  test('billing_records read denied to non-admin', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      await ctx
        .firestore()
        .doc('billing_records/r1')
        .set({ organization_id: ORG_A, user_id: USER_A_UID });
    });
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc('billing_records/r1').get());
  });

  test('billing_records read allowed to org admin', async () => {
    const db = ctxFor(ADMIN_A_UID);
    await assertSucceeds(db.doc('billing_records/r1').get());
  });

  test('billing_records writes denied even to admin', async () => {
    const db = ctxFor(ADMIN_A_UID);
    await assertFails(
      db.doc('billing_records/r2').set({ organization_id: ORG_A, amount: 100 })
    );
  });
});

describe('organization_id mutation blocked on update', () => {
  test('cannot mutate organization_id on agent', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(
      db.doc('agents/agent-a').update({
        organization_id: ORG_B, // privilege escalation attempt
      })
    );
  });

  test('benign updates still pass', async () => {
    const db = ctxFor(USER_A_UID);
    await assertSucceeds(
      db.doc('agents/agent-a').update({
        name: 'renamed Clix agent',
      })
    );
  });
});

describe('memberships visibility', () => {
  test('user can read own membership', async () => {
    const db = ctxFor(USER_A_UID);
    await assertSucceeds(db.doc(`memberships/${USER_A_UID}_${ORG_A}`).get());
  });

  test('user cannot read another user’s membership', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc(`memberships/${USER_B_UID}_${ORG_B}`).get());
  });

  test('user cannot self-elevate by writing memberships', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(
      db.doc(`memberships/${USER_A_UID}_${ORG_B}`).set({
        user_id: USER_A_UID,
        organization_id: ORG_B,
        role: 'admin',
        status: 'active',
      })
    );
  });
});

describe('alchemist conversations are user-scoped', () => {
  test('user can write to own message path', async () => {
    const db = ctxFor(USER_A_UID);
    await assertSucceeds(
      db
        .doc(`alchemist_conversations/${USER_A_UID}/messages/m1`)
        .set({ content: 'hi' })
    );
  });

  test('user cannot write to another user’s message path', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(
      db
        .doc(`alchemist_conversations/${USER_B_UID}/messages/m1`)
        .set({ content: 'snoop' })
    );
  });
});

describe('beta_signups (unauthenticated form)', () => {
  test('anonymous create allowed', async () => {
    const db = ctxFor(null);
    await assertSucceeds(
      db.doc('beta_signups/sample').set({ email: 'test@example.com' })
    );
  });

  test('anonymous read denied', async () => {
    const db = ctxFor(null);
    await assertFails(db.doc('beta_signups/sample').get());
  });
});

describe('workflow_runs (org-scoped reads, backend writes)', () => {
  beforeAll(async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      await db.doc('workflow_runs/run-a').set({
        run_id: 'run-a',
        agent_id: 'agent-a',
        organization_id: ORG_A,
        status: 'completed',
        started_at: new Date(),
      });
      await db.doc('workflow_runs/run-b').set({
        run_id: 'run-b',
        agent_id: 'agent-b',
        organization_id: ORG_B,
        status: 'completed',
        started_at: new Date(),
      });
      await db.doc('workflow_runs/run-legacy').set({
        run_id: 'run-legacy',
        agent_id: 'agent-x',
        // intentionally NO organization_id
        status: 'completed',
      });
    });
  });

  test('same-org member can read own run', async () => {
    const db = ctxFor(USER_A_UID);
    await assertSucceeds(db.doc('workflow_runs/run-a').get());
  });

  test('cross-org member cannot read other org run', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc('workflow_runs/run-b').get());
  });

  test('legacy run without organization_id is unreadable', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc('workflow_runs/run-legacy').get());
  });

  test('client write denied even from org admin', async () => {
    const db = ctxFor(ADMIN_A_UID);
    await assertFails(
      db.doc('workflow_runs/run-c').set({
        run_id: 'run-c',
        agent_id: 'agent-a',
        organization_id: ORG_A,
        status: 'pending',
      })
    );
  });
});

describe('workflow_items (org-scoped reads, backend writes)', () => {
  beforeAll(async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      await db.doc('workflow_items/item-a').set({
        item_id: 'item-a',
        run_id: 'run-a',
        agent_id: 'agent-a',
        organization_id: ORG_A,
        status: 'completed',
        created_at: new Date(),
      });
      await db.doc('workflow_items/item-b').set({
        item_id: 'item-b',
        run_id: 'run-b',
        agent_id: 'agent-b',
        organization_id: ORG_B,
        status: 'completed',
        created_at: new Date(),
      });
    });
  });

  test('same-org member can read own item', async () => {
    const db = ctxFor(USER_A_UID);
    await assertSucceeds(db.doc('workflow_items/item-a').get());
  });

  test('cross-org member cannot read other org item', async () => {
    const db = ctxFor(USER_A_UID);
    await assertFails(db.doc('workflow_items/item-b').get());
  });

  test('client write denied even from org admin', async () => {
    const db = ctxFor(ADMIN_A_UID);
    await assertFails(
      db.doc('workflow_items/item-c').set({
        item_id: 'item-c',
        run_id: 'run-a',
        agent_id: 'agent-a',
        organization_id: ORG_A,
        status: 'completed',
      })
    );
  });
});
