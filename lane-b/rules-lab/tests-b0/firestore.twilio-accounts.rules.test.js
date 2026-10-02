/**
 * Firestore rules unit tests for `twilio_accounts` — plaintext Twilio
 * credentials that were readable by every signed-in user on the platform.
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 * (needs a JDK >= 21 — see tests/firestore-rules/README.md.)
 *
 * WHAT WAS OPEN. `twilio_accounts` appeared in NO match block, so it fell
 * through to `match /{collection}/{docId}` and inherited
 * `allow read: if isAuthenticated()`. The documents are keyed BY AGENT ID
 * (olbrain-studio-backend services/whatsapp_service.py:534) and hold
 * `account_sid` and `auth_token` as bare strings (models/whatsapp_models.py
 * :153-154 — no SecretStr, no KMS). `agents` is not in that read exclusion
 * list either, so the whole attack is: list `agents`, take every id, read
 * `twilio_accounts/{id}`. No org boundary is crossed because none is checked.
 *
 * READ is the load-bearing half here, which makes this suite different from
 * the outreach one next to it: that closed tampering and deliberately left
 * reads open, whereas this is a confidentiality leak and read is the whole
 * point. Write is closed too — a forged row repoints an agent at an
 * attacker's Twilio account, which is a credential SWAP rather than a leak.
 *
 * NOTHING LEGITIMATE LOSES ACCESS. The Twilio path is dead in production:
 * zero calls to api.twilio.com, zero whatsapp_service invocations, and zero
 * hits to any /api/whatsapp/twilio* route across studio-backend and
 * agent-bridge in a 30-day log window. WhatsApp runs entirely on the Meta/WABA
 * path now (agent-bridge + `agent_senders`). The only reader was ever
 * studio-backend's Admin SDK, which bypasses rules — and the suite proves that
 * by seeding through withSecurityRulesDisabled.
 *
 * THIS RULE DOES NOT UNDO PAST EXPOSURE. Anything already stored here was
 * readable by every authenticated user for as long as the collection has
 * existed, so it needs ROTATING in Twilio, not just fencing.
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

const PROJECT_ID = 'olbrain-twilio-rules-test';
const ATTACKER_UID = 'uid-signed-in-stranger';

// Keyed by agent id, which is what makes the enumeration step trivial.
const VICTIM_AGENT = 'victim-agent-id';

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

  // Seeded the way studio-backend writes it: Admin SDK, rules bypassed.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`twilio_accounts/${VICTIM_AGENT}`).set({
      account_sid: 'ACtestsidtestsidtestsidtestsid00',
      auth_token: 'testauthtokentestauthtoken000000',
      agent_id: VICTIM_AGENT,
    });
    // The enumeration source. Present so the first test describes the real
    // attack rather than assuming the attacker already knows an agent id.
    await db.doc(`agents/${VICTIM_AGENT}`).set({ name: 'Victim agent' });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('twilio_accounts — plaintext credentials, reads denied', () => {
  test('a signed-in stranger CANNOT read an agent\'s Twilio credentials', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`twilio_accounts/${VICTIM_AGENT}`).get());
  });

  test('an unauthenticated client CANNOT read them either', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(db.doc(`twilio_accounts/${VICTIM_AGENT}`).get());
  });

  test('the credential is closed even when the attacker knows the agent id', async () => {
    // Deliberately does NOT assert that `agents` is readable. An earlier draft
    // did, which pinned a known hole as a REQUIREMENT: the moment someone
    // scopes agent reads, this Twilio suite would go red for a reason that has
    // nothing to do with Twilio. The attack starts from a known agent id, so
    // model that directly instead.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`twilio_accounts/${VICTIM_AGENT}`).get());
  });

  test('CANNOT list the collection to find which agents have credentials', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.collection('twilio_accounts').get());
  });
});

// The gap that shipped in the first version of this PR: every case above is a
// TWO-segment path, and `twilio_accounts` was added to the two-segment lists
// only. Nothing nests under the collection today, so no test could have caught
// it by accident — it has to be probed deliberately, the way the sibling
// firestore.datastore suite probes each depth.
describe('twilio_accounts — subcollections are fenced at every depth', () => {
  test('CANNOT read a nested document under a credential', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`twilio_accounts/${VICTIM_AGENT}/rotations/r1`).get());
  });

  test('CANNOT create a nested document under a credential', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`twilio_accounts/${VICTIM_AGENT}/rotations/r1`).set({ auth_token: 'x' })
    );
  });

  test('CANNOT reach deeper still', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`twilio_accounts/${VICTIM_AGENT}/rotations/r1/audit/a1`).set({ x: 1 })
    );
  });
});

describe('twilio_accounts — writes denied too (a forged row is a credential swap)', () => {
  test('CANNOT repoint an agent at an attacker-controlled Twilio account', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc(`twilio_accounts/${VICTIM_AGENT}`).update({
        account_sid: 'ACattackerattackerattackerattack',
        auth_token: 'attackertokenattackertoken000000',
      })
    );
  });

  test('CANNOT create credentials for an agent that has none', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(
      db.doc('twilio_accounts/some-other-agent').set({
        account_sid: 'ACattackerattackerattackerattack',
        auth_token: 'attackertokenattackertoken000000',
      })
    );
  });

  test('CANNOT delete an agent\'s credentials', async () => {
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc(`twilio_accounts/${VICTIM_AGENT}`).delete());
  });
});

// The Admin SDK is the only legitimate accessor and bypasses rules entirely.
// Pinned so that "we locked it" cannot be confused with "we broke the writer".
describe('the Admin SDK still works, which is the only path that ever mattered', () => {
  test('a rules-disabled context can still read and write', async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const db = ctx.firestore();
      const snap = await db.doc(`twilio_accounts/${VICTIM_AGENT}`).get();
      expect(snap.exists).toBe(true);
      await db.doc(`twilio_accounts/${VICTIM_AGENT}`).update({ agent_id: VICTIM_AGENT });
    });
  });
});
