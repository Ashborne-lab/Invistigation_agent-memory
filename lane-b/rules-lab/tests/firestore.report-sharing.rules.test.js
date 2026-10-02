/**
 * Firestore rules unit tests for report sharing.
 *
 * Five contracts, one file:
 *   1. `research_runs` documents are not client-writable. They were, via the
 *      top-level catch-all — which is what RunMeta means by "research_runs is
 *      world-writable under current rules". `cancel_requested` lives there.
 *   2. `research_report_shares` is server-only in BOTH directions. It holds the
 *      share tokens; a readable token is a leaked public link.
 *   3. `report_versions` AND `steps` reads both consult the share document.
 *      Noesis subscribes to both subcollections directly from the client
 *      (subscribeReportVersions, subscribeRunSteps), and both carry the
 *      finished report body verbatim — report_versions via the review JSON,
 *      steps via the writer's `write_chunk` detail. Gating only one leaves
 *      `private` readable through the other.
 *   4. The org check backing #3 is `isOrgMember()` — a memberships_index
 *      lookup — not a token-claim comparison. The platform issues org claims
 *      under several names (org_id, tenant_id, organization_id,
 *      primaryOrganization — see
 *      olbrain-research-design/app/middleware/auth.py:84-108), and
 *      studio-backend's invitation_service sets only primaryOrganization on
 *      invited members. A claim comparison silently denies exactly those
 *      members; a membership lookup does not depend on which claim a token
 *      happens to carry.
 *   5. A share document missing `visibility` reads as `organization`, not as
 *      a denial. `get(...).data.visibility` on an absent field is a rules
 *      evaluation error, which fails the whole `allow` clause — including
 *      for the setter. `.data.get('visibility', 'organization')` matches the
 *      design's documented default instead.
 *   6. The gate holds for the read shape production uses: an ordered
 *      collection query (`list`), not the per-document `get` every other
 *      test here issues. A `list` denial never surfaces — the listener
 *      simply never populates.
 */
const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');

const PROJECT_ID = 'olbrain-report-sharing-rules-test';

const ORG = 'org-alpha';
const OWNER_UID = 'uid-owner';       // set the report private
const MATE_UID = 'uid-teammate';     // same org, not the setter
const OUTSIDER_UID = 'uid-outsider'; // different org
const INVITED_UID = 'uid-invited';          // token carries ONLY primaryOrganization; IS a member
const NO_MEMBERSHIP_UID = 'uid-no-member';  // token carries a matching org_id/tenant_id; is NOT a member

const OPEN_RUN = 'run-open';                   // no share doc at all
const ORG_RUN = 'run-org';                     // visibility: organization
const PRIVATE_RUN = 'run-private';             // visibility: private, set by OWNER_UID
const NO_VISIBILITY_RUN = 'run-no-visibility'; // share doc exists, `visibility` field absent

let env;

const ctxFor = (uid, org) =>
  env.authenticatedContext(uid, { org_id: org, tenant_id: org }).firestore();

// Studio-backend's invitation_service sets only this claim on invited
// members — never org_id, never tenant_id (auth.py:84-108). A token-claim
// comparison would deny this caller; isOrgMember() does not care.
const ctxWithPrimaryOrgOnly = (uid, org) =>
  env.authenticatedContext(uid, { primaryOrganization: org }).firestore();

beforeAll(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      host: '127.0.0.1',
      port: 8080,
      rules: fs.readFileSync(path.join(__dirname, '../../firestore.rules'), 'utf8'),
    },
  });

  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    for (const runId of [OPEN_RUN, ORG_RUN, PRIVATE_RUN, NO_VISIBILITY_RUN]) {
      await db.doc(`research_runs/${runId}`).set({ org_id: ORG, status: 'completed' });
      await db.doc(`research_runs/${runId}/report_versions/001`).set({
        version: 1, review: { overall_score: 7.1 },
      });
      // steps carries the finished report body too (writer `write_chunk`
      // detail) — same seeding shape as report_versions so the mirror tests
      // below exercise a real document, not a missing one.
      await db.doc(`research_runs/${runId}/steps/001`).set({
        step_type: 'write_chunk', detail: { heading: 'Summary' },
      });
    }

    // Membership rows back isOrgMember(), which report_versions/steps reads
    // now gate on instead of a token-claim comparison. OUTSIDER_UID and
    // NO_MEMBERSHIP_UID deliberately get none — their absence is what the
    // last two tests below pin.
    await db.doc(`memberships_index/${OWNER_UID}_${ORG}`).set({ roles: ['owner'] });
    await db.doc(`memberships_index/${MATE_UID}_${ORG}`).set({ roles: ['member'] });
    await db.doc(`memberships_index/${INVITED_UID}_${ORG}`).set({ roles: ['member'] });

    await db.doc(`research_report_shares/${ORG_RUN}`).set({
      token: 'tok-org', visibility: 'organization',
      visibility_set_by: OWNER_UID, org_id: ORG,
    });
    await db.doc(`research_report_shares/${PRIVATE_RUN}`).set({
      token: 'tok-private', visibility: 'private',
      visibility_set_by: OWNER_UID, org_id: ORG,
    });
    // Deliberately no `visibility` field — pins that a share row missing one
    // (an in-progress write, or a future field rename) does not deny
    // everyone, including the setter.
    await db.doc(`research_report_shares/${NO_VISIBILITY_RUN}`).set({
      token: 'tok-no-vis', visibility_set_by: OWNER_UID, org_id: ORG,
    });
  });
});

afterAll(async () => { await env.cleanup(); });

describe('research_runs is not client-writable', () => {
  test('a signed-in org member cannot write a run document', async () => {
    await assertFails(
      ctxFor(MATE_UID, ORG).doc(`research_runs/${OPEN_RUN}`).update({ cancel_requested: true }),
    );
  });

  test('a signed-in outsider cannot write another org run document', async () => {
    await assertFails(
      ctxFor(OUTSIDER_UID, 'org-beta').doc(`research_runs/${OPEN_RUN}`).update({ cancel_requested: true }),
    );
  });

  test('reads are unchanged — an org member still reads the run', async () => {
    await assertSucceeds(ctxFor(MATE_UID, ORG).doc(`research_runs/${OPEN_RUN}`).get());
  });
});

describe('research_report_shares is server-only', () => {
  test('an org member cannot read a share document', async () => {
    await assertFails(ctxFor(MATE_UID, ORG).doc(`research_report_shares/${ORG_RUN}`).get());
  });

  test('the setter cannot read their own share document either', async () => {
    await assertFails(ctxFor(OWNER_UID, ORG).doc(`research_report_shares/${ORG_RUN}`).get());
  });

  test('nobody can write a share document', async () => {
    await assertFails(
      ctxFor(OWNER_UID, ORG).doc(`research_report_shares/${ORG_RUN}`).update({ visibility: 'public' }),
    );
  });
});

describe('report_versions reads consult the share document', () => {
  test('no share document — an org member reads, exactly as before', async () => {
    await assertSucceeds(
      ctxFor(MATE_UID, ORG).doc(`research_runs/${OPEN_RUN}/report_versions/001`).get(),
    );
  });

  test('organization visibility — an org member reads', async () => {
    await assertSucceeds(
      ctxFor(MATE_UID, ORG).doc(`research_runs/${ORG_RUN}/report_versions/001`).get(),
    );
  });

  test('private — the setter reads', async () => {
    await assertSucceeds(
      ctxFor(OWNER_UID, ORG).doc(`research_runs/${PRIVATE_RUN}/report_versions/001`).get(),
    );
  });

  test('private — a teammate is denied', async () => {
    await assertFails(
      ctxFor(MATE_UID, ORG).doc(`research_runs/${PRIVATE_RUN}/report_versions/001`).get(),
    );
  });

  test('another org is denied regardless of visibility', async () => {
    await assertFails(
      ctxFor(OUTSIDER_UID, 'org-beta').doc(`research_runs/${ORG_RUN}/report_versions/001`).get(),
    );
  });

  // Every test above reads ONE document. Production never does:
  // subscribeReportVersions (noesis src/services/research/runService.js) is
  // query(ref, orderBy('version', 'desc')) — an ordered collection query, a
  // `list` operation, not a `get`. The two are separate operations in the
  // rules engine: `allow get` satisfies every assertion above and denies the
  // read the app actually makes, and a listener denial is silent — the view
  // just never populates. This is the shape that has to work.
  //
  // Namespaced rather than getDocs/query/orderBy because
  // @firebase/rules-unit-testing hands back a firebase/compat Firestore; the
  // request on the wire is the same RunQuery either way, which is all the
  // rules engine sees.
  test('the ordered collection query the client actually issues succeeds', async () => {
    const snap = await assertSucceeds(
      ctxFor(MATE_UID, ORG)
        .collection(`research_runs/${ORG_RUN}/report_versions`)
        .orderBy('version', 'desc')
        .get(),
    );
    // Resolving is not enough — the documents have to come back.
    expect(snap.docs.map((d) => d.id)).toEqual(['001']);
  });
});

describe('steps reads mirror report_versions — same org check, same share gate', () => {
  // steps carries the finished report body, not just progress metadata
  // (writer `write_chunk` steps embed section markdown, and
  // useRunSections.js/LiveReportView.js reassemble the whole artifact from
  // exactly these documents). noesis subscribes to it directly from the
  // client (subscribeRunSteps) with no error callback on the listener, so a
  // rules denial here doesn't degrade gracefully like report_versions does
  // — it just never populates. It needs the same isOrgMember() +
  // _shareAllows() gate as report_versions, not org membership alone.
  test('an org member reads a non-private run', async () => {
    await assertSucceeds(
      ctxFor(MATE_UID, ORG).doc(`research_runs/${ORG_RUN}/steps/001`).get(),
    );
  });

  test('a matching org claim without a membership row is denied', async () => {
    await assertFails(
      ctxFor(NO_MEMBERSHIP_UID, ORG).doc(`research_runs/${ORG_RUN}/steps/001`).get(),
    );
  });

  test('private — the setter reads', async () => {
    await assertSucceeds(
      ctxFor(OWNER_UID, ORG).doc(`research_runs/${PRIVATE_RUN}/steps/001`).get(),
    );
  });

  test('private — a teammate is denied', async () => {
    await assertFails(
      ctxFor(MATE_UID, ORG).doc(`research_runs/${PRIVATE_RUN}/steps/001`).get(),
    );
  });
});

describe('a share document missing visibility defaults to organization', () => {
  // get(...).data.visibility on an absent field is a rules evaluation
  // error, which fails the whole allow clause outright rather than denying
  // gracefully — the round-1 RED evidence for the primaryOrganization case
  // documents exactly that failure mode ("Property org_id is undefined on
  // object"). research-design (a sibling repo, a separate task) owns this
  // document's writes, so a two-phase write or a future field rename must
  // not silently blank the owner's own access. .data.get('visibility',
  // 'organization') is what makes that true, and matches the design's
  // documented default for a run with no share document at all.
  test('a same-org member still reads report_versions', async () => {
    await assertSucceeds(
      ctxFor(MATE_UID, ORG).doc(`research_runs/${NO_VISIBILITY_RUN}/report_versions/001`).get(),
    );
  });
});

describe('the org check is membership, not a token claim', () => {
  // This is the whole point of the isOrgMember() gate: a caller invited via
  // studio-backend's invitation_service carries only `primaryOrganization`,
  // never `org_id` or `tenant_id`. An `org_id || tenant_id` comparison would
  // deny this exact caller. Fails on the token-claim comparison this file
  // used to have; passes once the gate is a membership lookup.
  test('a token carrying only primaryOrganization reads, given a membership row', async () => {
    await assertSucceeds(
      ctxWithPrimaryOrgOnly(INVITED_UID, ORG).doc(`research_runs/${ORG_RUN}/report_versions/001`).get(),
    );
  });

  // The other half of the same contract: a matching org claim is not enough
  // on its own. Pins that the switch to isOrgMember() tightened the check to
  // an actual membership row rather than just widening it.
  test('a matching org claim without a membership row is denied', async () => {
    await assertFails(
      ctxFor(NO_MEMBERSHIP_UID, ORG).doc(`research_runs/${ORG_RUN}/report_versions/001`).get(),
    );
  });
});
