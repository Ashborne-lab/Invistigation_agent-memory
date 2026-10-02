# olbrain-studio — Firestore Rules Review

**Repo:** `olbrain-studio` | **HEAD:** `252f7887a8183f2f82392668f5fcb7d912e15611` (short `252f788`), verified to match `origin/main` | **Review date:** 2026-09-19

**Scope note:** This is NOT a general repo survey. Scope is strictly: `firestore.rules`, `firestore.clix.rules`, `tests/firestore-rules/`, and the two config files (`firebase.json`, `.firebaserc`, `firebase.clix.json`, `scripts/deploy-clix-rules.sh`) needed to explain how the two rulesets map to deployment targets. No other file in this ~1,900-file frontend monolith was read or surveyed.

---

## How Firestore rule evaluation works in this file (read before the per-collection sections)

Firestore evaluates **every** `match` block whose path pattern matches the requested document path, for the requested operation, and grants the operation if **any** matching block's condition is true (blocks OR together — they never narrow each other). A generic wildcard match (e.g. `/{collection}/{docId}/{sub}/{rest=**}`) matches on **segment count**, so it applies to any collection whose exact path shape fits, unless that collection name is explicitly excluded inside that specific catch-all's own condition. A more specific, tighter rule written earlier in the file does **not** override a later, looser catch-all that also matches the same path — the reverse of what most engineers assume from "most specific wins" in other systems. `firestore.rules` itself is unusually candid about this: multiple of its own comments (lines 94–98, 348–349, 375, 477–480, 636–638, 832–839, 853–860, 875–880) document cases where a tighter rule was written but is currently **defeated** by a catch-all that was never taught to exclude that collection. This review treats those comments as source evidence, not as reassurance, and re-verifies each one against the actual exclusion lists.

`firestore.rules` (55,184 bytes / 974 lines) has three catch-alls, in order:
1. `/{collection}/{docId}` (line 704) — 2-segment top-level documents. Read exclusion list: lines 706–716. Write exclusion list: lines 718–743.
2. `/{collection}/{docId}/{sub}/{rest=**}` (line 881) — 4+-segment subcollection documents. Read exclusion: lines 883–884. Write exclusion: lines 897–900.
3. `/agents/{agentId}/{sub}/{rest=**}` (line 910) — subcollections specifically under `agents/`, open except `sub == 'owner_lessons'` for writes.

---

## Per-collection findings

### `agent_sessions/{id}`
No dedicated `match` block exists anywhere in `firestore.rules` (confirmed by grep across the whole file — zero hits for the literal string `agent_sessions`). It is a 2-segment top-level path, so it falls entirely to catch-all #1. `agent_sessions` is **not** in the read exclusion list (706–716) or the write exclusion list (718–743).
**Classification: VERIFIED CURRENT.** Effective rule: `allow read, write: if isAuthenticated()` — any signed-in platform user, any org.

### `agent_messages/{id}`
Same situation: zero hits for `agent_messages` in `firestore.rules`. Whether it is a genuine top-level collection or reached only via `agent_sessions/{id}/messages/{id}` cannot be settled from this repo (the shared `olbrain-shared` schema is out of scope here), but it doesn't change the outcome: a top-level 2-segment path falls to catch-all #1 (not excluded), and a 4-segment subcollection path falls to catch-all #2 (not excluded — `agent_messages`/`agent_sessions` absent from lines 883–884 and 897–900) either way.
**Classification: VERIFIED CURRENT.** Effective rule under either path shape: any signed-in user.

### `agent_learned_patterns/{agentId}/patterns/{patternId}`
Has an explicit, named, non-trivial rule (lines 269–273):
```
match /agent_learned_patterns/{agentId}/patterns/{patternId} {
  allow read: if isAuthenticated() && ownsAgent(agentId);
  allow update: if isAuthenticated() && ownsAgent(agentId)
                 && request.resource.data.diff(resource.data).affectedKeys().hasOnly(['status']);
}
```
But this path is 4 segments, so catch-all #2 (`/{collection}/{docId}/{sub}/{rest=**}`) also matches it, and `agent_learned_patterns` is **absent** from both that catch-all's read exclusion (883–884: `organizations`, `agents`, `agent_datastores`, `twilio_accounts`) and write exclusion (897–900: `organizations`, `agents`, `research_chat_sessions`, `research_runs`, `agent_datastores`, `outreach_campaigns`, `agent_users`, `twilio_accounts`). Rules OR together, so the catch-all's `allow read, write: if isAuthenticated()` **fully supersedes** the `ownsAgent`-gated rule — including granting `create` and `delete`, which the explicit block never even attempts to grant.
**Classification: VERIFIED CURRENT** (as an active exposure) / the `ownsAgent`-scoped block itself is best classified **CONTRADICTED BY SOURCE** as an effective control — it exists in source but is provably inert given the catch-all it sits inside. This is the exact mechanism the repo-and-soul-map's G12 finding describes (a catch-all "superseding the tighter `ownsAgent` rule"), independently re-derived here from the current file rather than assumed from that finding.

### `agent_datastores/{agentId}/{rest=**}`
```
match /agent_datastores/{agentId}/{rest=**} {
  allow read, write: if false;
}
```
(lines 535–537). This wildcard covers the agent-level doc and every table/entry beneath it. It is also explicitly excluded from **both** catch-alls: top-level read list (line 714) and write list (line 741), subcollection read list (line 883) and write list (line 899). No path to this collection is reachable from a client under any condition. `tests/firestore-rules/firestore.datastore.rules.test.js` (see Test Coverage below) exercises exactly this and passes.
**Classification: VERIFIED CURRENT.** This **directly contradicts** the senior review's inclusion of `agent_datastores` in the "reachable by any signed-in user" set — current source shows total lockdown, consistent with the extensive in-file comments (lines 511–537) describing this as a deliberate 2026-09 fix for a hole that existed "from the data store's first deploy" until closed (commit `9fdf819b`, `fix(rules): close the agent data store to every client (#2446)`).

### `agent_user_memory/{memoryId}`
```
match /agent_user_memory/{memoryId} {
  allow read: if isAuthenticated() && isOrgMember(resource.data.organization_id);
  allow write: if false;
}
```
(lines 543–546). Excluded from catch-all #1's read list (line 711) and write list (line 728) — no supersession risk since it's a 2-segment path only matched by catch-all #1.
**Classification: VERIFIED CURRENT — CONFIRMED ORG-SCOPED.** Read requires real org membership (via `isOrgMember`, which resolves against `memberships_index`, itself hard-denied to all clients, lines 199–201). Write is server-only (Admin SDK bypasses rules). This is the one PII-bearing collection in the review list that is actually locked down correctly today.

### `context_logs/{scopeKey}/events/{eventId}`
```
match /context_logs/{scopeKey}/events/{eventId} {
  allow read: if isAuthenticated() && resource.data.user_id == request.auth.uid;
  allow write: if false;
}
```
(lines 481–484), with an explicit comment (477–480) admitting: *"like the synapse rules above, the permissive catch-all below currently OR-grants authenticated access; this stricter rule documents the intended privacy model and fully takes effect once that catch-all is tightened."* This is a 4-segment path, so catch-all #2 applies, and `context_logs` is **absent** from both its read exclusion (883–884) and write exclusion (897–900).
**Classification: VERIFIED CURRENT** (as an active exposure). Effective rule: any signed-in user can read AND write any `context_logs` event on any scope (global, org, project, agent, or session), fully overriding the owner-only intent. The file's own comment confirms this was known and left unresolved at HEAD.

### `context_facts`
Zero hits for `context_facts` anywhere in `firestore.rules`. No dedicated rule, not present in any exclusion list of either catch-all, regardless of whether its actual path shape is 2-segment or 4-segment.
**Classification: VERIFIED CURRENT.** Any signed-in user can read and write, by omission rather than by explicit permissive rule — there is no evidence this was ever considered when the file's catch-all exclusion lists were built (unlike `context_logs`, which at least has a dead tighter rule sitting next to it).

### `context_guardrails`
Same as `context_facts`: zero hits, not referenced anywhere, not excluded from either catch-all.
**Classification: VERIFIED CURRENT.** Any signed-in user, any org, read and write.

### `vibe_sessions/{id}`
Zero hits for `vibe_sessions`. Not excluded from catch-all #1 (2-segment path).
**Classification: VERIFIED CURRENT.** Any signed-in user, any org, read and write — including `organization_id`/`user_id`/`title` fields per store-inventory's description of this doc.

### `research_templates/{id}`
Zero hits for `research_templates` (the only `research_*` collections with dedicated rules are `research_chat_sessions`, `research_runs/{runId}/steps`, and `research_runs/{runId}/report_versions` — none of which is the template collection itself). Not excluded from catch-all #1.
**Classification: VERIFIED CURRENT.** Any signed-in user, any org, read and write on template metadata/config.

### `research_runs/{id}` (top-level document only — distinct from its `steps`/`report_versions` subcollections)
The two dedicated rules at lines 447–456 and 462–471 only govern `research_runs/{runId}/steps/{stepId}` and `research_runs/{runId}/report_versions/{versionId}` — both are 4-segment paths, correctly excluded from catch-all #2's write list (line 899, `research_runs` is present) and left readable only via the parent-run org check inside their own blocks (no catch-all #2 read exclusion needed since read isn't excluded there either — but wait, `research_runs` **is absent** from catch-all #2's read exclusion list at 883–884, so even these subcollections' reads also fall through the catch-all; the dedicated rule's condition is looser (org-claim match) than "any authenticated user" so it doesn't matter for read — catch-all read is still the more permissive of the two either way for `research_runs`'s subcollections).

Crucially, the **top-level `research_runs/{runId}` document itself** (2 segments: `RunMeta` — org_id, status, cost rollup, billing, claim review) has **no dedicated rule at all**, and `research_runs` is **absent** from catch-all #1's read exclusion (706–716) **and** write exclusion (718–743) — only `research_plans` and `research_chat_sessions` are excluded there, not `research_runs` itself.
**Classification: VERIFIED CURRENT — and worse than the senior review's read-only framing.** Any signed-in user can both **read and write** the top-level `research_runs` document for any org's run (org, cost, billing, status fields included), while the `steps`/`report_versions` subcollections are properly write-protected. This asymmetry (child protected, parent not) appears to be an oversight distinct from the deliberately-scoped protections nearby (`research_plans`, `research_chat_sessions` — see the extensive comment at lines 654–683 explaining exactly why those two were added) — `research_runs` itself was never added to that list.

### `workflow_definitions/{id}`
Zero hits for `workflow_definitions`. Not excluded from catch-all #1.
**Classification: VERIFIED CURRENT.** Any signed-in user, any org, read and write on the workflow definition doc (draft/published pointers, org_id, trigger config).

### `workflow_agent_memory/{agentId}`
Zero hits for `workflow_agent_memory`. Not excluded from catch-all #1. Given store-inventory already found **zero app-layer auth** on this store's REST routes (`olbrain-workflow-runtime`, Security Finding D), this compounds: it is also open at the Firestore layer to any signed-in platform user directly, bypassing the (nonexistent) REST auth entirely.
**Classification: VERIFIED CURRENT.** Any signed-in user, any org, read and write — including `original_data` verbatim business/document fields (per store-inventory).

### `knowledge_library/{id}`
No dedicated `match` block (confirmed — appears only inside comments at lines 683, 700, 738, 748, 771, never as an actual `match` statement). It is explicitly named in catch-all #1's **write** exclusion list (line 738) but **not** in the read exclusion list (706–716). The surrounding comment (lines 683–703) is explicit and matches this finding exactly: *"an authenticated user can read another org's knowledge metadata here, which is the pre-existing exposure — narrowed, not yet closed."*
**Classification: VERIFIED CURRENT.** Read: any signed-in user, any org (confirmed, and the file's own comment agrees). Write: correctly denied to all clients (server-only), because it's excluded from the write catch-all and no other rule grants a client write.

### `organizations/{org}/connector_credentials/{id}`
Zero hits for `connector_credentials` anywhere in `firestore.rules`. This is a 4-segment path under `/organizations/{orgId}/{sub}/{rest=**}` (catch-all at lines 955–958):
```
match /organizations/{orgId}/{sub}/{rest=**} {
  allow read, write: if isAuthenticated()
    && !(sub in ['secrets', 'pnl_statements', 'pnl_drivers', 'finance_profile',
                 'pnl_exports', 'finance_policy', 'finance_rm', 'pnl_rm_projections',
                 'rm_proposals', 'finance_lines', 'pnl_line_projections',
                 'finance_model', 'pnl_projections', 'pnl_inputs', 'pnl_bridges',
                 'pnl_deck_templates', 'pnl_deck_runs', 'research_clients']);
}
```
`connector_credentials` is **absent** from this exclusion list, and — critically — this rule checks only `isAuthenticated()`, never `isOrgMember(orgId)`.
**Classification: VERIFIED CURRENT — full confirmation of repo-and-soul-map G12's specific claim.** Any signed-in user on the platform can read and write **any organization's** `connector_credentials` subcollection, with **zero org-membership check of any kind** (not even the weaker "any signed-in user" — there genuinely is no `orgId` predicate at all in the matching rule). Per the soul inventory (repo-and-soul-map §06), this collection holds KMS-wrapped credential *references*; the wrapping means a raw secret isn't handed over directly, but the credential-pointer document (and whatever metadata it carries) is fully exposed and, per the store's own architecture, mutable — which is a credential-swap risk, not just a leak.

### `agents/{id}` itself
Has a real, specific, non-trivial ownership rule at lines 23–31:
```
match /agents/{agentId} {
  allow read, write: if isAuthenticated() &&
    (resource == null || resource.data.userId == request.auth.uid || resource.data.owner_id == request.auth.uid) &&
    (request.resource == null || request.resource.data.userId == request.auth.uid || request.resource.data.owner_id == request.auth.uid);
}
```
This is a 2-segment path, so catch-all #1 also matches it, and `agents` is **absent** from catch-all #1's read exclusion (706–716) and write exclusion (718–743) — note this is a *different* catch-all from the one that correctly excludes `agents` at lines 883 and 898 (that one only governs `agents/{id}/{sub}/{rest=**}` subcollections, not the `agents/{id}` document itself). The file's own comment, describing a related but separate change, confirms this precisely (lines 793–805): closing the `agent_senders` enumeration gap *"means scoping `agents` reads, which is a much larger change (it would also **activate the owner-only block at line 23**...)"* — i.e., the code's own author documents that the line-23 ownership block is currently **dormant**.
**Classification: VERIFIED CURRENT — and the single most severe finding in this review.** Any signed-in platform user can both read AND write **any** agent document (any org), including `owner_id`, `organization_id`, `status`, and version pointers, completely independent of the `ownsAgent`-style check that looks, from the code, like it should be gating this. This is broader than every other finding above: it is not merely a PII read, it is an unauthenticated-by-org read/write on the platform's central resource-ownership document.

---

## `firestore.clix.rules` and deployment-target mapping

`firestore.clix.rules` (26,132 bytes / 609 lines) is a **structurally different, genuinely default-deny** ruleset — confirmed, not merely asserted:
- Its final block (lines 604–606) is `match /{document=**} { allow read, write: if false; }` with **no other catch-all anywhere in the file** — every one of its ~60 `match` blocks is a specific, named collection or subcollection path.
- Its own header comment (lines 3–22) states the design principles explicitly: "No wildcard `allow read, write: if isAuthenticated()` catch-all," "Every client-readable collection is explicitly enumerated," "Default-deny at the end."
- `isOrgMember` here (lines 46–50) checks a real `memberships/{uid}_{orgId}` document with `status == 'active'`, distinct from the shared ruleset's `memberships_index`-based helper — a separately maintained authorization data path for this tenant.
- Confirmed dedicated rules exist here (and only here) for: `agent_sessions/{id}` (org-scoped read, write false — lines 223–228), `agent_sessions/{id}/messages/{id}` (org-scoped via parent lookup — 229–237), `agent_messages/{id}` (org-scoped read, write false — 238–243), `agent_learned_patterns/…/patterns/{id}` (ownsAgent OR org-editor — 191–197, and here there is **no** enveloping catch-all to supersede it, so this rule is actually load-bearing, unlike its identically-worded counterpart in the shared file), `workflow_definitions/{id}` and `workflow_runs`/`workflow_items` (org-scoped — 466–488), `knowledge_library/{id}` (org-scoped CRUD — 430–435).
- Confirmed **absent** here (thus unreachable — default-deny): `agent_datastores`, `agent_user_memory`, `context_logs`, `context_facts`, `context_guardrails`, `vibe_sessions`, `research_templates`, `research_runs`, `workflow_agent_memory`, `connector_credentials` (in fact `organizations/{orgId}/{sub}` has no generic subcollection catch-all here at all — only `members`, `private_mcp_servers`, `secrets`, `usage` are named). None of these are reachable by any client on this tenant.

**Deployment-target mapping — confirmed via config, not inferred:**
- `.firebaserc` (repo root): `{"projects": {"default": "olbrain-india-prod", "prod": "olbrain-india-prod", "clix": "clix-capital-prod"}}` — two distinct **Firebase/GCP projects**, not two rulesets on one project.
- `firebase.json` (repo root): `"firestore": {"rules": "firestore.rules"}` — this is the config used for the default/`prod` alias, i.e. `olbrain-india-prod` and (per the clix file's own comment, line 11) other shared projects such as `vibeclone-prod`.
- `firebase.clix.json` (repo root, separate file, not referenced by the default `firebase.json`): `{"_comment": "Firebase config for the clix-capital-prod project ONLY. Deploys the locked-down firestore.clix.rules without affecting the shared firestore.rules used by other Firebase projects. Use with: firebase deploy --config firebase.clix.json --project clix-capital-prod --only firestore:rules", "firestore": {"rules": "firestore.clix.rules"}, ...}`.
- `scripts/deploy-clix-rules.sh` runs exactly that command (`firebase deploy --config firebase.clix.json --project clix-capital-prod --only firestore:rules[,storage]`).

So: **same codebase, two entirely separate Firebase projects**, each with its own Firestore database, deployed by two independent, manually-invoked commands (no single `firebase deploy` deploys both; the default command only ever touches `firestore.rules`, never `firestore.clix.rules`, unless someone explicitly runs the clix script). There is nothing in this repo indicating an automated CI/CD gate that deploys `firestore.clix.rules` on push — `scripts/deploy-clix-rules.sh` reads as a manual/ops-run script. Which document a request's data lives in (and therefore which ruleset governs it) is decided by which GCP project the requesting Studio/Noesis instance is pointed at for that tenant (i.e., "clix-capital-prod" is a dedicated single-tenant deployment of the whole platform, not a flag inside the shared one) — this is inferred from the project-separation evidence above; the actual tenant-routing mechanism (how a browser session picks which Firebase project/config to initialize against) lives outside `firestore.rules`/`firestore.clix.rules` and was not traced further, per scope.

## Test coverage findings

`tests/firestore-rules/` exists and is **real and runnable** (Firebase emulator + Jest, `npm run test:rules`), but its own `README.md` states plainly: **"CI: Not wired yet... nothing gates a merge on it."** Files present: `firestore.clix.rules.test.js`, `firestore.datastore.rules.test.js`, `firestore.finance.rules.test.js`, `firestore.golden-templates.rules.test.js`, `firestore.outreach.rules.test.js`, `firestore.research-plans.rules.test.js`, `firestore.twilio-accounts.rules.test.js`.

- **`firestore.datastore.rules.test.js`** exercises the shared `firestore.rules`' `agent_datastores` lockdown directly (`describe('agent data store is unreachable from any client', ...)`) — confirms that specific fix is intentional and tested, consistent with the VERIFIED CURRENT / total-lockdown finding above.
- **`firestore.clix.rules.test.js`** exercises `firestore.clix.rules` only — cross-tenant isolation, `agent_sessions` write-denial, `workflow_runs`/`workflow_items` org-scoping, default-deny on unenumerated collections, `organization_id`-immutability. It does **not** touch the shared `firestore.rules` file at all.
- `firestore.research-plans.rules.test.js` and `firestore.outreach.rules.test.js` cover the specific, narrow fixes named in their own commit history (`research_plans`/`research_chat_sessions`, `outreach_campaigns`/`agent_users`) in the shared ruleset.
- **No test file anywhere in this directory exercises**, on the shared `firestore.rules`: `agent_sessions`, `agent_messages`, `agent_learned_patterns`, `context_logs`, `context_facts`, `context_guardrails`, `vibe_sessions`, `research_templates`, `research_runs` (top-level doc), `workflow_definitions`, `workflow_agent_memory`, `connector_credentials`, or the `agents/{id}` catch-all-supersedes-ownership issue. (Grepped for each name across the whole `tests/firestore-rules/` directory; only `firestore.clix.rules.test.js` — which tests the *other* file — contains any of these strings.)

**Conclusion: every exposure found above on the shared `firestore.rules` is untested.** The README's own words apply directly: *"a rule nobody tests is a rule nobody notices regressing."* This is evidence the platform's rules-testing discipline is real (recently built, deliberately used for `agent_datastores`, `research_plans`, outreach, Twilio) but has not yet been extended to the collections this task was asked to check — those gaps are accidental-and-unverified in the CI sense, not intentional-and-tested, even where (as with `context_logs`) the author clearly *knew* about the gap and wrote a comment saying so.

## Git history signal

`git log --oneline -8 -- firestore.rules` (most recent first) shows a burst of very recent, deliberate tightening commits, all with explicit, security-motivated messages:
```
33242710 feat(rules): report_versions is readable by its org and writable by nobody (#2461)
907d23c8 chore(rules): superagent_threads is server-only, read and write (#2459)
95ba8a4c fix(rules): superagent_delegations is server-written (#2458)
7ab77317 fix(rules): close the subcollection gap and correct two false claims
e2ba6ca0 fix(rules): plaintext Twilio credentials were readable by every signed-in user
9c7adc12 style(rules): hoist the outreach note out of the array literal
d33d5b80 fix(rules): deny client writes to outreach_campaigns and agent_users (S2)
9fdf819b fix(rules): close the agent data store to every client (#2446)
```
This is an active, ongoing security-hardening effort on the shared ruleset — but every commit above closes a **different, specific** collection (Twilio credentials, outreach, agent_datastores, superagent_*, report_versions). None of the eight most recent commits touches `agent_sessions`, `agent_messages`, `agent_learned_patterns`'s catch-all supersession, `context_logs`, `research_templates`, `research_runs` (top-level), `workflow_definitions`, `workflow_agent_memory`, `connector_credentials`, or the `agents/{id}` catch-all supersession. The pattern reads as: the team is finding and closing these holes one at a time, by inspection, and has not yet reached the collections in this task's scope.

`git log --oneline -8 -- firestore.clix.rules` shows separate, tenant-specific work (Myelin/Aegis security-scan tab, `agent_sessions`/`agent_messages` org-scoped reads added for Clix at commit `87ae43fb`, `workflow_runs`/`workflow_items` org-scoping at `869a4c7c`), confirming the clix ruleset has its own independent hardening history and reached `agent_sessions`/`agent_messages` for that one tenant well before the shared ruleset did (the shared ruleset still has no rule for them at all, per above).

---

## Verdict on Security Finding E (drop-in for `store-inventory.md`)

| Collection | Verdict |
|---|---|
| `agent_sessions` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — no dedicated rule in `firestore.rules`; falls to unexcluded catch-all. (Clix tenant only: org-scoped, read-only.) |
| `agent_messages` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — same reasoning, both possible path shapes lead to the same unexcluded catch-all. (Clix tenant only: org-scoped, read-only.) |
| `agent_learned_patterns` | **CONFIRMED READABLE (and WRITABLE, including create/delete) BY ANY SIGNED-IN USER** — a real `ownsAgent`-scoped rule exists but is provably superseded by an unexcluded catch-all. |
| `agent_datastores` | **CONFIRMED ORG-SCOPED — actually confirmed FULLY DENIED to all clients**, not merely org-scoped. This directly contradicts the senior review's inclusion of this collection in the exposed set; current source is a deliberate, tested, complete lockdown (2026-09 fix). |
| `agent_user_memory` | **CONFIRMED ORG-SCOPED** — real `isOrgMember` gate on read, server-only write. Correctly locked down. |
| `context_logs` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — a real owner-scoped rule exists but is provably superseded by an unexcluded catch-all; the file's own comment admits this. |
| `context_facts` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — no rule at all, no exclusion. |
| `context_guardrails` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — no rule at all, no exclusion. |
| `vibe_sessions` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — no rule at all, no exclusion. |
| `research_templates` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — no rule at all, no exclusion. |
| `research_runs` (top-level doc) | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — worse than expected: even write is open on the parent run doc, though its `steps`/`report_versions` children are properly write-protected. |
| `workflow_definitions` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — no rule at all, no exclusion. (Clix tenant only: org-scoped.) |
| `workflow_agent_memory` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — no rule at all, no exclusion; compounds the already-confirmed absence of REST-layer auth found in `olbrain-workflow-runtime`. |
| `organizations/{org}/connector_credentials` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER, WITH NO ORG CHECK AT ALL** (not even `isOrgMember`) — full, precise confirmation of repo-and-soul-map G12's specific claim about this path. |
| `agents/{id}` | **CONFIRMED READABLE (and WRITABLE) BY ANY SIGNED-IN USER** — the platform's central ownership document. A real `ownsAgent`-style rule exists at line 23 but is dormant, per the file's own comment admitting as much elsewhere. This is the single broadest and most severe finding: it is not org-scoped, not owner-scoped, and governs every agent on the platform. |
| `knowledge_library` | **CONFIRMED READ: ANY SIGNED-IN USER / WRITE: SERVER-ONLY (correctly denied)** — asymmetric by design per the file's own comment; matches store-inventory's existing framing exactly. |

**Bottom line on the senior review's headline claim (senior-feedback.md item 3):** substantially **CONFIRMED**, and worse than stated in two ways — (1) it is not just `agent_sessions`/`agent_messages`, the same catch-all mechanism reaches at least ten more collections including the central `agents/{id}` document itself, and (2) several of these are writable, not merely readable, by any signed-in user, including the `agents/{id}` document and the top-level `research_runs` document. It is **weaker** than stated in one specific place: `agent_datastores` (explicitly named by the senior review as exposed "by the same logic") is in fact the one collection in this list that is fully and deliberately locked down — CONTRADICTED BY SOURCE for that one collection only.

## Open Questions

- Exact wire path shape of `agent_messages` (top-level with its own `organization_id`, vs. purely a subcollection of `agent_sessions`) cannot be settled from `firestore.rules` alone — the shared ruleset has no rule of either shape, so it doesn't affect this review's conclusion, but it would matter for anyone writing a fix. The `firestore.clix.rules` file has explicit rules for *both* shapes (`agent_messages/{id}` at line 238 AND `agent_sessions/{id}/messages/{messageId}` at line 229), suggesting both may genuinely exist in production, or that the clix rules were written defensively for both possibilities — unresolved from this repo.
- The exact mechanism by which a browser Studio/Noesis session decides which Firebase project (and therefore which ruleset) to initialize against for a given tenant/org (e.g., how "this org is clix-capital" gets resolved to project `clix-capital-prod` at runtime) is out of scope for this file-only review and was not traced.
- Whether `scripts/deploy-clix-rules.sh` is invoked by any CI/CD pipeline (vs. purely a manual ops script) could not be confirmed from `firestore.rules`/`firestore.clix.rules`/`firebase.json` alone; no `.github/workflows/*.yml` was read (out of the stated scope for this pass).
- Whether other dedicated-tenant Firebase projects besides `clix-capital-prod` exist and, if so, whether they use `firestore.clix.rules` or `firestore.rules` or a third file, is unknown — `.firebaserc` only lists `default`/`prod`/`clix`.
