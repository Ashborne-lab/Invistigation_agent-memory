/**
 * Firestore rules unit tests for Olbrain's two org-membership stores —
 * `organizations/{orgId}/members/{uid}` and top-level `memberships` — which
 * several servers treat as PROOF of membership.
 *
 * Run with the Firebase emulator:
 *   npm run test:rules
 * (needs a JDK >= 21 — see tests/firestore-rules/README.md.)
 *
 * WHAT WAS OPEN. `members` had no match block of its own, so it fell through
 * to `match /organizations/{orgId}/{sub}/{rest=**}`, which grants any
 * signed-in user read AND write on every org subcollection it does not name.
 * The servers read this exact doc to decide membership:
 *   - agent-engine alchemist/utils/organization.py is_active_org_member (the
 *     doc DECIDES when it exists), behind tenant_access_error — the Synapse
 *     and Cortex turn gates and the billing org check;
 *   - studio-backend is_org_member / org_role;
 *   - superagent-design app/authz.py org_roles and skills-design
 *     is_active_org_member (Synapse fix plans C and F).
 * So one client write — `{membership_status: {status: 'active'}, role:
 * 'owner'}` at organizations/<victim>/members/<own uid> — made a stranger an
 * owner of any org to every one of those checks, and the claim-setter-member
 * Cloud Function then minted `tenant_id=<victim>` / `roles` custom claims on
 * the writer's own token.
 *
 * `memberships` had the same hole. Its own block says `allow write: if
 * false`, but rules OR together and the top-level catch-all
 * `match /{collection}/{docId}` granted write on every collection not in
 * its exclusion list — which named `memberships_index` but not
 * `memberships`. studio-backend's org_roles reads `memberships` as the
 * canonical store and agent-engine falls back to it whenever the members
 * doc is absent, so a forged `{user_id, organization_id, type:
 * 'organization', status: 'active', role: 'owner'}` row did the same.
 *
 * NOTHING LEGITIMATE LOSES ACCESS. Every member mutation goes through
 * studio-backend's /api/organizations/{org}/members routes (Admin SDK, rules
 * bypassed), and no client writes `memberships` (every Studio / Noesis touch
 * is a query or onSnapshot). The client-side writers in organizationService.js
 * (syncUserProfileToMemberships, populateOrganizationMemberUserInfo,
 * migrateToUserIdDocIds, migrateProfilePicturesToMemberships) have no
 * callers in Studio or Noesis. The two client READS keep today's shape:
 * Onboarding's slow path (getDoc of your own member doc in each org) and
 * subscribeToOrganizationMembers (onSnapshot of an org's member list).
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

const PROJECT_ID = 'olbrain-org-members-rules-test';
const VICTIM_ORG = 'org-victim';
const MEMBER_UID = 'uid-member';
const STRANGER_UID = 'uid-signed-in-stranger';

const ACTIVE_OWNER = {
  user_id: STRANGER_UID,
  role: 'owner',
  membership_status: { status: 'active' },
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
});

beforeEach(async () => {
  await env.clearFirestore();
  // Seeded the way studio-backend writes it: Admin SDK, rules bypassed.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.doc(`organizations/${VICTIM_ORG}`).set({ name: 'Victim org' });
    await db.doc(`organizations/${VICTIM_ORG}/members/${MEMBER_UID}`).set({
      user_id: MEMBER_UID,
      role: 'viewer',
      membership_status: { status: 'active' },
    });
    await db.doc('memberships/m-real').set({
      user_id: MEMBER_UID,
      organization_id: VICTIM_ORG,
      type: 'organization',
      status: 'active',
      role: 'viewer',
    });
  });
});

afterAll(async () => {
  await env.cleanup();
});

const as = (uid) => env.authenticatedContext(uid).firestore();

describe('nobody writes an org membership doc from a client', () => {
  test('a stranger cannot make themselves an active owner of another org', async () => {
    await assertFails(
      as(STRANGER_UID).doc(`organizations/${VICTIM_ORG}/members/${STRANGER_UID}`).set(ACTIVE_OWNER),
    );
  });

  test('a member cannot promote themselves', async () => {
    await assertFails(
      as(MEMBER_UID)
        .doc(`organizations/${VICTIM_ORG}/members/${MEMBER_UID}`)
        .update({ role: 'owner' }),
    );
  });

  test("a stranger cannot overwrite or remove someone else's membership", async () => {
    const ref = as(STRANGER_UID).doc(`organizations/${VICTIM_ORG}/members/${MEMBER_UID}`);
    await assertFails(ref.set({ membership_status: { status: 'removed' } }));
    await assertFails(ref.delete());
  });
});

describe("Studio's client reads keep working", () => {
  test("onboarding's slow path reads your own member doc in any org", async () => {
    await assertSucceeds(
      as(MEMBER_UID).doc(`organizations/${VICTIM_ORG}/members/${MEMBER_UID}`).get(),
    );
    await assertSucceeds(
      as(STRANGER_UID).doc(`organizations/${VICTIM_ORG}/members/${STRANGER_UID}`).get(),
    );
  });

  test('the Settings member list reads an org\'s members', async () => {
    await assertSucceeds(as(MEMBER_UID).collection(`organizations/${VICTIM_ORG}/members`).get());
  });

  test('the other org subcollections clients use are still writable', async () => {
    await assertSucceeds(
      as(MEMBER_UID).doc(`organizations/${VICTIM_ORG}/activities/a1`).set({ kind: 'note' }),
    );
  });
});

describe('nobody writes a top-level memberships row from a client', () => {
  // `memberships` is the OTHER membership store: studio-backend's org_roles
  // treats it as canonical, and agent-engine's is_active_org_member falls
  // back to it whenever the members doc is absent (every stranger's case).
  test('a stranger cannot forge an active owner row for another org', async () => {
    await assertFails(
      as(STRANGER_UID).doc('memberships/forged').set({
        user_id: STRANGER_UID,
        organization_id: VICTIM_ORG,
        type: 'organization',
        status: 'active',
        role: 'owner',
        roles: ['owner'],
      }),
    );
  });

  test("a stranger cannot remove someone else's membership row", async () => {
    await assertFails(as(STRANGER_UID).doc('memberships/m-real').update({ status: 'removed' }));
  });

  test("a member still reads their own rows (AuthContext's listener)", async () => {
    await assertSucceeds(
      as(MEMBER_UID).collection('memberships').where('user_id', '==', MEMBER_UID).get(),
    );
  });
});
