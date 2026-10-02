# Lane B / B0: Acceptance Tests v1

**Date:** 2026-10-01.

**Scope:** investigation and test only. No production repository edited, nothing deployed, no production data, synthetic identities only.

**Sources:** `origin/main` at

| Repository | Commit |
|---|---|
| studio-backend | `5da93ae` |
| agent-design | `c56271d` |
| agent-engine | `dfc3a47` |
| agent-runtime | `daee3f9` |
| research-runtime | `6b81691` |
| mcp-deployer | `b75cc12` |
| studio (rules) | `1f05ca11` |

**Builds on:** [`memory-lane-b-security-b0-v1.md`](memory-lane-b-security-b0-v1.md).

## 1. What was built

### 1.1 Server-side acceptance tests (Track 1): `investigation/lane-b/acceptance/`

| File | Role |
|---|---|
| `extract.py` | Loads **real `origin/main` code** read-only (`git show`) into an isolated scratch tree, with labelled stubs for internal imports |
| `world.py` | Synthetic world: org A/B, users, editor and viewer roles, projects, agents, knowledge docs, end users, leads, share tokens, service accounts, MCP credentials |
| `current.py` | **Today's behaviour.** `[REAL]` entries call the actual functions. `[MODELLED]` entries reproduce traced handlers too heavy to import, each citing file:line |
| `reference.py` | **The fix as an executable specification.** It pins behaviour, not an implementation |
| `test_b0_12_to_14_org_access.py`, `test_b0_15_to_17_subject_selection.py`, `test_b0_18_to_24_services.py` | The tests |
| `conftest.py` | `B0_TARGET=current \| reference \| owner` |
| `results/current.txt`, `results/reference.txt` | Recorded runs |

**Real code exercised:**
- studio-backend `require_permission` and `verify_admin_user`;
- agent-design `require_permission`;
- agent-engine `require_permission`/`check_permission`, `require_olbrain_user`, Lumen `_enforce_agent_id_filter` + `validate_sql`;
- research-runtime `is_internal_user`;
- agent-runtime `memory_doc_id`;
- mcp-deployer `require_auth_enabled`.

**Modelled** (handlers depend on live Firestore/GCP clients): the studio-backend agent and activity routes, the agent-design routers, the runtime API-key middleware, leads, memory, email and directive routes, the MCP `tools/call` handler, and the share-token service.

### 1.2 Revocation (Track 2): `investigation/lane-b/rules-lab/probe_revocation.mjs`, `run_revocation.sh`

Results are in `results/b0-stage1-revocation.jsonl` and `results/before-revocation.jsonl`.

## 2. Results

| Target | Tests | GREEN | RED | Meaning |
|---|---|---|---|---|
| `reference` | 74 | **73** (+1 skipped: a current-only documentation test) | 0 | The specified fix satisfies every invariant |
| `current` | 74 | **12**: exactly the legitimate-access tests | **62**: every attack test | Today's code fails every security test, and keeps every legitimate behaviour the fix must preserve |

**Why the RED tests are red.** These are the actual failure messages from `results/current.txt`:
- `DID NOT RAISE Denied` (38): an unauthorised action succeeded.
- Lumen `assert not any("victim" …)`: four adversarial SQL forms read another tenant's rows **through the real production filter**.
- `cred-DEFAULT` returned for an agent without credentials: the default-credential fallback.
- `TypeError: check_permission() takes 3 positional arguments` (B0-24, real code).
- The admin gates return `True` for an **unverified** `@olbrain.com` password account (real studio-backend code; the engine and research gates likewise).

**INV-S13 (revocation):**

| Rules | Access before revocation | Denied after revocation (same token) |
|---|---|---|
| `firestore.current.rules` | 12/12 | **0/12**. Nothing depends on membership, so revocation changes nothing |
| `firestore.b0.rules` | 12/12 | **12/12** |

## 3. Coverage by finding

| Finding | Tests | Current | Reference | Real or modelled current | Fully covered? |
|---|---|---|---|---|---|
| B0-12 `require_org_access` | 6 | 4 RED, 2 legit green | 6 GREEN | **REAL** `require_permission` (both services) | **Yes**: A→B denied (user, key); A→A allowed (user, key); body org never overrides; anonymous denied |
| B0-13 studio-backend create/fork | 6 | 5 RED | GREEN | MODELLED (agent_routes.py:65/128/191/212, agent_service.py:115/613/796-1040/1255) | Yes |
| B0-14 agent-design | 8 | 7 RED | GREEN | REAL `require_permission` + MODELLED handlers | Yes, including viewer read but no write, and store admin |
| B0-15 share/API-key scope | 10 | 8 RED | GREEN | MODELLED (api_key_middleware ~515-627, leads :479-879, agent_memory :48-109) | Yes |
| B0-16 caller-controlled `user_id` | 4 | 3 RED | GREEN | **REAL** `memory_doc_id` + MODELLED lookup | Yes |
| B0-17 email webhook | 5 | 4 RED | GREEN | MODELLED (email.py:56-138, :311) | Yes. SPF/DKIM parsing is modelled on SendGrid's `SPF`/`dkim` fields `[UNVERIFIED against live SendGrid payloads]` |
| B0-18 platform admin | 5 + 1 | 4 RED (incl. the current-only gate test), 2 legit green | GREEN | **REAL** studio-backend `verify_admin_user`; **REAL** engine `require_olbrain_user` and research `is_internal_user` (current-only test) | Yes, for the 3 gates traced. **Not** for the engine's `get_metrics_scope` and `require_olbrain_identity` (same pattern, same fix) |
| B0-19 send-directive | 4 | 3 RED | GREEN | MODELLED (directives.py:66) | Yes, for the endpoint. The caller (agent-directives) is a **missing repository** |
| B0-20 MCP | 8 | 8 RED | GREEN | REAL `require_auth_enabled` semantics + MODELLED main.py:2107-2149, :494-720, :1558-1632 | Yes, for the service contract. The binding-token format is a reference choice; owners may use another signed format that satisfies the same tests |
| B0-21 Lumen | 6 | 5 RED, 1 legit green | GREEN | **REAL** filter + validator, SQLite stand-in for BigQuery | Yes, for the query-isolation property. BigQuery authorised views and row-access policies themselves need a staging probe |
| B0-22 activities | 3 | 3 RED | GREEN | MODELLED (activity_routes.py:55, ~95) | Yes |
| B0-23 share tokens | 5 | 5 RED | GREEN | MODELLED (share_token_service.py:143-242, validate) | Yes |
| B0-24 engine helper | 3 | 3 RED (real TypeError) | GREEN | **REAL** `alchemist/utils/auth.py` | Yes. Note: even after fixing the signature, the real `get_user_permissions` returns `[]` for every user (a TODO), so a pure signature fix would deny everyone. The reference maps roles from `memberships_index` |
| INV-S13 revocation (rules) | 12 resources | 0/12 hold | 12/12 hold | Real rules in the emulator | Yes, for the rules. Server routes need the same online check, covered by B0-12's membership source |

**Total: 74 server acceptance tests, plus 12 revocation cases, plus 32 rules probes with 16 legitimate twins.** The probes extend `memory-lane-b-security-b0-v1.md` §C by six: RU-org-analytics, RU-project-analytics, RU-billing-aggregates, RU-group-query, RU-group-unscoped and ORG-doc-read, plus the K1 editor cases.

**Rules-probe results** (`rules-lab/results/*-probe.jsonl`):

| Rules | Attacks allowed | Legitimate twins denied | Studio suite |
|---|---|---|---|
| current | 32/32 | 0 | 346/346 |
| B0 stage 1 | 2/32: ORG-doc-read = **B0-25 residual**, V2-new-collection = closed only by stage 2 | 0 | 346/346 |
| B0 stage 2 | 1/32: ORG-doc-read (B0-25) | 0 | 345/346 (`tests-b0`); the one failure is the intended flip `over-reach control › two-segment catch-all still grants read` |

**B0-25 (new, found by the query audit):** the top-level `organizations/{org}` document (wallet, runtime) is readable by any signed-in user. It is not covered by a server test: it is a rules and flow change for the Studio owner. See `memory-lane-b-b0-query-audit-v1.md` §3.

## 4. How an owner turns RED to GREEN

1. In the owning repository, write a thin adapter module exposing the functions used by the tests, with the same names and signatures as `reference.py`. Each function calls the real handler, for example via FastAPI `TestClient` against the app with Firestore faked or pointed at the emulator, and maps a 401/403 to `world.Denied`.
2. Run `B0_TARGET=owner B0_OWNER_ADAPTER=<module> python -m pytest investigation/lane-b/acceptance -q`.
3. Before the fix, the security tests are RED, as with `current`. After the fix, everything must be GREEN, **including the 12 legitimate-access tests**. A fix that denies everything fails those.
4. Port the tests into the repository's own suite once green. The synthetic world is self-contained.

## 5. Dependencies of the rules on `memberships_index` (INV-S13), and propagation assumptions

**Which rules read the index.** `isOrgMember`, `isOrgAdmin`, `isOrgOwner`, `isOrgEditor` (new) and `orgRoles`. These cover:
- agents read and update;
- every agent subcollection (through `canUseAgent`/`canEditAgent`);
- `agent_messages`, `agent_sessions` (+ messages), `agent_users`, `agent_analytics`, `tickets` (org path);
- `organizations/*/members` and every other org subcollection;
- org document updates;
- plus the pre-existing blocks (mcp_configs, learned patterns, research, synapse …).

**Project membership.** The agent read rule also accepts `projects/{project_id}/members/{uid}`. **Revoking an org membership does not remove project membership documents.** studio-backend must delete them in the same revocation path. This is not covered by the probe and is an owner action (added to the handoff).

**`team_access.team_member_ids`** on the agent doc also grants read. Revocation must remove the uid from those arrays. Owner action.

**Propagation.**
- Rules evaluate the index **on every request**; there is no token caching in rules. So revocation is effective as soon as studio-backend's `sync_org_membership_index()` deletes the row.
- The emulator shows an immediate effect. In production, Firestore reads are strongly consistent, so the delay is the latency of the backend sync job `[UNMEASURED]`.
- **Custom claims** (`tenant_id`, `roles` minted by the claim-setter function) are **not** used by these rules. They would persist until token refresh (≤ 1 h). They must not be added as an access shortcut.

## 6. Untested areas (stated, not hidden)

| Area | Why untested here | Where it gets tested |
|---|---|---|
| The real FastAPI route handlers for B0-13/14/15/17/19/20/22/23 | Too heavy to import without live clients; modelled with citations | The owner adapter (§4) against the real app plus the emulator |
| BigQuery authorised views / row-access policies | No BigQuery here | Staging probe running the same 5 adversarial SQL forms |
| SendGrid Inbound Parse field formats (`SPF`, `dkim`) | No live payloads | Staging, with SendGrid test mails |
| Firebase Auth sign-up providers and the `hd` claim | Project configuration not in the workspace | Security owner checks the Firebase console configuration |
| agent-directives, webhook service, Noesis callers | **Missing repositories** | After the repositories are provided |
| Per-project MCP ingress / IAM (`allow_unauthenticated`) | GCP configuration | Ops checklist in the handoff |
| Revocation against the stage-2 rules | Run against stage 1 only; stage 2 is a strict superset (an allow-list on top) | Re-run `run_revocation.sh firestore.b0-stage2.rules` in staging |
| Project-member and team-member removal on revocation | Studio-backend code path not traced end to end | Owner test (handoff) |
