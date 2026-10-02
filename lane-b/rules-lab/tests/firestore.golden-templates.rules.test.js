/**
 * Firestore rules unit tests for `research_golden_templates` — the global
 * catalogue of golden research templates Olbrain authors and publishes.
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 * (needs a JDK >= 21 — see tests/firestore-rules/README.md, and note that
 * `java_home -v 23` silently returns Java 17 unless the brew JDK is symlinked.)
 *
 * TWO edits in `firestore.rules` stand behind this suite, and it only passes
 * with BOTH. The explicit `match /research_golden_templates/{goldenId}` block
 * says `allow write: if false` — but rules OR together, and the top-level
 * catch-all at `match /{collection}/{docId}` grants
 * `allow write: if isAuthenticated()` to every collection NOT named in its
 * exclusion array. So that `if false` restricts nothing on its own. It is
 * exactly how `capability_types` and `step_types` have been
 * authenticated-writable since the day they were written, and the defect
 * class fixed in 201e08c1. The two write-denial cases below go red the moment
 * the exclusion-array line is removed.
 *
 * Why this collection is worth a rule: a row is a GCS pointer.
 * `storage_path` is read server-side by
 * POST /api/golden-templates/{slug}/instantiate and turned into a bucket
 * read, and `load_body` accepts any path in the bucket — so a forged row is a
 * cross-org read of another org's template body.
 *
 * Reads stay open on purpose: card copy and a `golden_templates/` path, no
 * PII, nothing org-scoped — the same posture capability_types chose. The only
 * writer is the Admin SDK in olbrain-research-design's
 * scripts/seed_golden_templates.py, which bypasses rules, and Studio reads
 * the list over HTTP. So the exclusion costs the product nothing.
 *
 * The compat surface (`db.doc(path).set(…)`) is deliberate and not a
 * modernisation candidate: @firebase/rules-unit-testing@4.0.1 imports
 * firebase/compat/firestore, so `ctx.firestore()` is a compat handle and
 * modular setDoc/getDoc will not take it.
 */

const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-golden-templates-rules-test';
const USER_UID = 'uid-authenticated-user';

// The path a forged row would aim instantiate at: another org's template body.
const VICTIM_PATH = 'research/templates/victim-template/v1.json';

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

  // One seeded row so the update and read cases exercise a real document, not
  // a missing one. Shape mirrors what seed_golden_templates.py upserts.
  await env.withSecurityRulesDisabled(async (ctx) => {
    await ctx.firestore().doc('research_golden_templates/decision-research-brief').set({
      name: 'Decision Research Brief',
      status: 'active',
      current_version: 1,
      storage_path: 'golden_templates/decision-research-brief/v1.json',
    });
  });
});

afterAll(async () => {
  await env.cleanup();
});

describe('research_golden_templates (Olbrain-owned catalogue: reads open, client writes denied)', () => {
  test('authenticated client CANNOT create a catalogue row', async () => {
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertFails(
      db.doc('research_golden_templates/forged').set({
        name: 'Forged',
        status: 'active',
        current_version: 1,
        storage_path: VICTIM_PATH,
      })
    );
  });

  test('authenticated client CANNOT repoint an existing row at another org\'s body', async () => {
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertFails(
      db.doc('research_golden_templates/decision-research-brief').update({
        storage_path: VICTIM_PATH,
      })
    );
  });

  test('unauthenticated client CANNOT write a catalogue row', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(
      db.doc('research_golden_templates/forged-anon').set({ name: 'Forged', status: 'active' })
    );
  });

  // Deliberate, and pinned: the page reads this catalogue over HTTP, but the
  // client read grant is left open to match capability_types. If this goes red
  // someone tightened a read that leaks nothing.
  test('authenticated client CAN read a catalogue row (deliberate, not a regression)', async () => {
    const db = env.authenticatedContext(USER_UID).firestore();
    await assertSucceeds(db.doc('research_golden_templates/decision-research-brief').get());
  });

  test('unauthenticated client CANNOT read a catalogue row', async () => {
    const db = env.unauthenticatedContext().firestore();
    await assertFails(db.doc('research_golden_templates/decision-research-brief').get());
  });
});
