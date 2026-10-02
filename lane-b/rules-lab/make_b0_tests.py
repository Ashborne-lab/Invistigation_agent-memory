"""Lane B / B0: the studio rules suites, adjusted ONLY where they pinned a now-closed cross-tenant gap or relied on a
fixture that is not how production proves membership. Every change is listed here with its reason; the originals
in tests/ stay untouched (the before-record). Output: tests-b0/.

1. org-members: the fixture seeded membership only as organizations/{org}/members/{uid}; the rules have always
   proved membership with memberships_index/{uid}_{org} (maintained by studio-backend). The member is seeded there too.
2. finance: "client-used subcollection stays readable" asserted ANY signed-in user can read another org's
   members/metrics/workflow_usage (exposure N3/N4). B0 version: a member of the org reads it; a stranger is denied.
3. outreach: "still writable … until S7" asserted a STRANGER can write another org's outreach_* (pinned known gap);
   "a stranger CAN still read end-user rows" pinned agent_users read for strangers. Both now assert denial, and an
   owner-positive test proves Studio's owner writes still work.
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC, DST = os.path.join(HERE, "tests"), os.path.join(HERE, "tests-b0")
shutil.rmtree(DST, ignore_errors=True)
shutil.copytree(SRC, DST)


def sub(name, old, new):
    p = os.path.join(DST, name)
    s = open(p, encoding="utf-8", newline="").read()
    assert old in s, (name, old[:70])
    open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))


sub("firestore.org-members.rules.test.js", """    await db.doc(`organizations/${VICTIM_ORG}/members/${MEMBER_UID}`).set({""",
    """    await db.doc(`memberships_index/${MEMBER_UID}_${VICTIM_ORG}`).set({ roles: ['viewer'] }); // [B0] fixture
    await db.doc(`organizations/${VICTIM_ORG}/members/${MEMBER_UID}`).set({""")

sub("firestore.finance.rules.test.js", """    'client-used subcollection organizations/{org}/%s stays readable',
    async (sub) => {
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertSucceeds(db.doc(`organizations/${ORG}/${sub}/seeded`).get());
    }""", """    'client-used subcollection organizations/{org}/%s stays readable FOR A MEMBER, and not for a stranger [B0]',
    async (sub) => {
      await env.withSecurityRulesDisabled(async (ctx) => {
        await ctx.firestore().doc(`memberships_index/${USER_UID}_${ORG}`).set({ roles: ['member'] });
      });
      const db = env.authenticatedContext(USER_UID).firestore();
      await assertSucceeds(db.doc(`organizations/${ORG}/${sub}/seeded`).get());
      const stranger = env.authenticatedContext('uid-b0-stranger').firestore();
      await assertFails(stranger.doc(`organizations/${ORG}/${sub}/seeded`).get());
    }""")

sub("firestore.outreach.rules.test.js", """  test('an authenticated stranger CAN still read end-user rows', async () => {
    // The confidentiality gap, stated out loud. Org-scoped reads need an
    // organization_id these documents do not carry yet.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertSucceeds(db.doc('agent_users/victim-user-id').get());
  });""", """  test('[B0] an authenticated stranger can NO LONGER read end-user rows', async () => {
    // Closed by B0: agent_users reads require canUseAgent(resource.data.agent_id) or org membership.
    const db = env.authenticatedContext(ATTACKER_UID).firestore();
    await assertFails(db.doc('agent_users/victim-user-id').get());
  });""")

sub("firestore.outreach.rules.test.js", """describe('agents/{id}/outreach_* — still writable, until S7 retires Studio\\'s tile', () => {
  test.each(['outreach_templates', 'outreach_audiences', 'outreach_configs'])(
    '%s is still client-writable (Studio authors it directly)',
    async (sub) => {
      const db = env.authenticatedContext(ATTACKER_UID).firestore();
      await assertSucceeds(
        db.doc(`agents/${VICTIM_AGENT}/${sub}/some-doc`).set({ name: 'x' })
      );
    }
  );
});""", """describe('[B0] agents/{id}/outreach_* — the OWNER writes, a stranger cannot', () => {
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
});""")
print("tests-b0 written")
