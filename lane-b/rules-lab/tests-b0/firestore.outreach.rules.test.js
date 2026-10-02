/**
 * Firestore rules unit tests for the Outreach collections — client writes
 * denied, reads deliberately still open.
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 * (needs a JDK >= 21 — see tests/firestore-rules/README.md.)
 *
 * TWO exclusion-list edits stand behind this suite and it only passes with
 * BOTH, for the reason `research_chat_sessions` documents in the rules file:
 * `match /{collection}/{docId}` matches a TWO-segment path and
 * `match /{collection}/{docId}/{sub}/{rest=**}` matches FOUR or more, so
 * neither list can stand in for the other. Remove either line and half the
 * cases below go red.
 *
 * This is the class of defect that has already bitten this file twice —
 * `app_subscriptions` was wide open because a `**` wildcard matched ZERO
 * segments and OR-ed a blanket grant over the exclusion above it, and
 * `research_golden_templates`' own `allow write: if false` restricted nothing
 * for the same reason. Rules OR together, so an explicit deny is worth exactly
 * nothing until every catch-all that reaches the path also excludes it. That
 * is invisible to inspection, which is why these run against a real emulator.
 *
 * WHAT WAS OPEN. Any authenticated user, in any org, could write
 * `outreach_campaigns/{anyAgent}/runs/{anyRun}`. `paused` and
 * `cancel_requested` are read by olbrain-agent-directives' campaign runner as
 * control flags, so a signed-in stranger could pause or cancel another
 * tenant's live send — or flip a finished run back to running. `agent_users`
 * holds end-user names and PHONE NUMBERS; it is the sibling of
 * `agent_user_memory`, already excluded as "end-user PII", and was missed.
 *
 * NOTHING LEGITIMATE LOSES A WRITE. Both are read from the browser by
 * client-SDK listeners, but every mutation already goes over HTTP —
 * campaignService's create/run/pause/resume/cancel/retry through
 * `directivesApi`, agentUserService's CRUD and directive CRUD through
 * `agentDesignApi`. The runtime and agent-directives use the Admin SDK, which
 * bypasses rules entirely.
 *
 * READS STAY OPEN, and that gap is real and pinned below rather than hidden:
 * an authenticated user can still read another org's campaign progress and
 * end-user phone numbers. Closing it needs org-scoped reads, and these
 * documents carry no `organization_id` (campaign_store.create_run writes
 * none), so the rule used elsewhere denies everyone when the field is absent.
 * That is S7 of the Outreach migration.
 *
 * The compat surface (`db.doc(path).set(…)`) is deliberate:
 * @firebase/rules-unit-testing@4.0.1 imports firebase/compat/firestore, so
 * `ctx.firestore()` is a compat handle and modular setDoc/getDoc will not take
 * it.
 */

const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-outreach-rules-test';
const ATTACKER_UID = 'uid-signed-in-stranger';

// A different tenant's agent. The attacker is authenticated but has no
// relationship to it whatsoever — which is the whole point: before this
// change, none was needed.
const VICTIM_AGENT = 'victim-agent-id';
const VICTIM_RUN = 'victim-run-id';

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

  // Seeded with the Admin SDK, the way agent-directives and the runtime
  // actually write these — so the update cases exercise real documents.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`outreach_campaigns/${VICTIM_AGENT}/runs/${VICTIM_RUN}`).set({
      agent_id: VICTIM_AGENT,
      name: 'Weekly re-engagement',
      status: 'running',
      paused: false,
      cancel_requested: false,
      progress: { total: 4000, sent: 1200 },
    });
    await db
      .doc(`outreach_campaigns/${VICTIM_AGENT}/runs/${VICTIM_RUN}/targets/tg1`)
      .set({ phone: '+919876543210', display_name: 'Asha R', status: 'queued' });
    await db.doc('agent_users/victim-user-id').set({
      agent_id: VICTIM_AGENT,
      phone: '+919876543210',
      display_name: 'Asha R',
      channel: 'whatsapp',
    });
    await db.doc('agent_users/victim-user-id/directives/d1').set({ text: 'call back' });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('outreach_campaigns — a stranger cannot steer another tenant\'s send', () => {
  test('CANNOT pause a live run', async () => {
    // `paused` is a control flag the campaign runner reads every tick.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`outreach_campaigns/${VICTIM_AGENT}/runs/${VICTIM_RUN}`).update({ paused: true })
    );
  });

  test('CANNOT cancel a live run', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db
        .doc(`outreach_campaigns/${VICTIM_AGENT}/runs/${VICTIM_RUN}`)
        .update({ cancel_requested: true })
    );
  });

  test('CANNOT forge a run under someone else\'s agent', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`outreach_campaigns/${VICTIM_AGENT}/runs/forged`).set({
        agent_id: VICTIM_AGENT,
        status: 'running',
      })
    );
  });

  test('CANNOT rewrite a per-recipient target row', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db
        .doc(`outreach_campaigns/${VICTIM_AGENT}/runs/${VICTIM_RUN}/targets/tg1`)
        .update({ phone: '+910000000000' })
    );
  });

  // The two-segment parent. It is a different match block from the four-segment
  // one above, so it needs its own exclusion AND its own case.
  test('CANNOT write the campaign parent document', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`outreach_campaigns/${VICTIM_AGENT}`).set({ hijacked: true })
    );
  });

  test('unauthenticated client CANNOT write either', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(
      db.doc(`outreach_campaigns/${VICTIM_AGENT}/runs/${VICTIM_RUN}`).update({ paused: true })
    );
  });
});

describe('agent_users — end-user PII, the sibling of agent_user_memory', () => {
  test('CANNOT create an end-user row', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('agent_users/forged-user').set({
        agent_id: VICTIM_AGENT,
        phone: '+910000000000',
        channel: 'whatsapp',
      })
    );
  });

  test('CANNOT repoint an existing row\'s phone number', async () => {
    // A write here redirects where the next campaign message is delivered.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('agent_users/victim-user-id').update({ phone: '+910000000000' })
    );
  });

  test('CANNOT write a directive subcollection row', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('agent_users/victim-user-id/directives/forged').set({ text: 'exfiltrate' })
    );
  });

  test('CANNOT delete an end-user row', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc('agent_users/victim-user-id').delete());
  });
});

// These are NOT aspirational — they pin the deliberate half of the decision.
// If a later change closes reads, these go red and whoever did it has to
// confirm Studio's listeners and the Noesis console still work, rather than
// discovering it in production.
describe('reads stay open, deliberately — the gap S7 closes', () => {
  test('an authenticated stranger CAN still read a campaign run', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertSucceeds(
      db.doc(`outreach_campaigns/${VICTIM_AGENT}/runs/${VICTIM_RUN}`).get()
    );
  });

  test('[B0] an authenticated stranger can NO LONGER read end-user rows', async () => {
    // Closed by B0: agent_users reads require canUseAgent(resource.data.agent_id) or org membership.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc('agent_users/victim-user-id').get());
  });
});

// Studio's Brain Builder still writes these three from the BROWSER through the
// client SDK, so they cannot close until the Studio tile is retired at S7.
// Pinned so the split is a recorded decision rather than an oversight — and so
// that whoever closes them at S7 sees these flip and knows to check Studio.
describe('[B0] agents/{id}/outreach_* — the OWNER writes, a stranger cannot', () => {
  test.each(['outreach_templates', 'outreach_audiences', 'outreach_configs'])(
    '%s: stranger write denied, owner write allowed',
    async (sub) => {
      await env.withSecurityRulesDisabled(async (ctx) => {
        await ctx.firestore().doc(`agents/${VICTIM_AGENT}`).set({ owner_id: 'uid-b0-owner', userId: 'uid-b0-owner',
                                                                   organization_id: 'org-b0' });
      });
      const attacker = env.authenticatedContext(ATTACKER_UID).firestore();
      await assertFails(attacker.doc(`agents/${VICTIM_AGENT}/${sub}/some-doc`).set({ name: 'x' }));
      const owner = env.authenticatedContext('uid-b0-owner').firestore();
      await assertSucceeds(owner.doc(`agents/${VICTIM_AGENT}/${sub}/some-doc`).set({ name: 'x' }));
    }
  );
});
