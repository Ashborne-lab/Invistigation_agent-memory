# CTO Latest Code: Reconciliation v1

**Date:** 2026-10-03.

**Scope:** source synchronisation and reconciliation only.
- No source file changed. Nothing implemented, merged, reset, pushed or deployed.
- `b0/security` branches untouched.
- No new vulnerability audit: only the known B0 findings were checked.

## 1. Synchronisation

`git fetch --all --prune` was run in each repository. This updates remote-tracking refs only; working trees and local branches were unchanged. Every repository is still on `b0/security`, with a clean tree and push disabled.

| Repository | Audited commit | Old local `origin/main` | **New `origin/main`** (fetched 2026-10-03) | New commits | Our `b0/security` |
|---|---|---|---|---|---|
| olbrain-studio | `1f05ca11` | `1f05ca11` | **`9509fc1c`** | 39 | `16c7747c` |
| olbrain-studio-backend | `5da93ae` | `5da93ae` | **`3e8dff4`** | 38 | `0f8619e` |
| olbrain-agent-design | `c56271d` | `c56271d` | **`e8d03a2`** | 4 | `02aee8c` |
| olbrain-agent-runtime | `daee3f9` | `daee3f9` | **`abf052d`** | 71 | `8eecdd1` |
| olbrain-agent-engine | `dfc3a47` | `dfc3a47` | **`76e9d6a`** | 3 | `92e262b` |
| olbrain-mcp-deployer | `b75cc12` | `b75cc12` | **`069208c`** | 6 | `bfc4331` |
| olbrain-research-runtime | `6b81691` | `6b81691` | **`7a327b1`** | 27 | `61ff951` |
| olbrain-workflow-runtime | `2356de0` | `2356de0` | **`7a6b07b`** | 4 | `2356de0` (no B0 commit) |

**Where the CTO's fixes live.** Every security fix found is merged into `origin/main`.
- The remote fix branches dated 2026-10-01 or later in olbrain-studio (`fix/rules-default-deny`, `fix/rules-org-scope-*`, `fix/rules-server-only-*`, `fix/profiles-via-directory`) are the PR branches of commits already on `origin/main`.
- No other security-related unmerged remote branch exists in the eight repositories.
- No tags are relevant.

**`origin/main` is therefore the newest reachable CTO code.** Whether it is **deployed** is not verifiable from here.

## 2. Method (reusing existing tests; no new audit)

1. **Commit log** since each audited commit, filtered for security subjects. Each relevant commit was opened and its message and diff checked.
2. **File-change check** on every file implicated by a B0 finding: `git log <audited>..origin/main -- <file>`.
3. **Acceptance suite, `current` target.** Its `[REAL]` entries load code from `origin/main`, so they now execute the CTO's code. Result: **61 RED / 13 GREEN**, against 62 / 12 at audit. The single flip is `test_B0_18_unverified_olbrain_address_gets_no_admin`. The `[MODELLED]` entries cannot reflect upstream changes, so those findings rely on steps 1–2.
4. **Rules probes**, unchanged `probe_b0.mjs` and `probe_revocation.mjs`, run against the CTO's `firestore.rules` at `9509fc1c` in the local emulator. Results are in `lane-b/rules-lab/results/cto-main-9509fc1c-*`.
   - **Attacks allowed: 7 of 51.**
   - **Legitimate twins denied: 4.** The CTO's rules are stricter on client agent and org-document edits; this is a behaviour difference, not a vulnerability.
   - **Revocation:** 8 of 8 applicable cases denied after revocation. The other 4 were already denied before revocation.
   - **Studio's old 346-test suite:** 20 failures. It no longer matches the CTO's rules, so this is not meaningful.

## 3. Per finding

**Commit key:** O = original audited commit; N = newest `origin/main`.

| Finding | O | N | CTO fix found? | Evidence | Our local B0 fix vs CTO fix | Status |
|---|---|---|---|---|---|---|
| B0-01 agent takeover/forge (rules) | studio `1f05ca11` | `9509fc1c` | **Yes** | All K1 attack probes denied | Both deny. The CTO's rules also deny the owner/editor client update that our twin expects | **CTO FIX VERIFIED** (emulator) |
| B0-02/03 messages, sessions | same | same | **Yes** | E1-*, S-* denied | Equivalent | **CTO FIX VERIFIED** (emulator) |
| B0-04…08 members, org subcollections, agent subcollections, tickets, `agent_users` | same | same | **Yes** | N3, N4, N5, N6, AU probes denied | Equivalent | **CTO FIX VERIFIED** (emulator) |
| B0-09 analytics rollups | same | same | **Mostly** | AN, RU-org/project/billing/group denied. **RU-group-project-only still allowed**: a stranger's `project_id`-only `months` collection-group query (cause not analysed: no new audit) | Ours denies it | **CTO FIX PRESENT BUT DIFFERENT** (one probe still allowed) |
| B0-10 org doc update by any user | same | same | **Yes** | Org-doc update attack denied (the admin twin is also denied) | Ours allows admins | **CTO FIX VERIFIED** (emulator) |
| B0-11 new collections client-writable | same | same | **Yes** | `d9be212d` "default deny – remove the catch-alls"; V2-*, SC-* denied (incl. V2-new-collection, which our stage 1 left to stage 2) | The CTO's approach equals our stage 2 (default deny) | **CTO FIX VERIFIED** (emulator) |
| B0-25 org doc readable by any user | same | same | **Yes** | `0835fca3` (rules), `40bbb6a7` (invites and profiles via the backend). ORG-doc-read and list denied | Same approach as ours | **CTO FIX VERIFIED** (emulator) |
| B0-29 (C10) agent/project grants → org roles | studio-backend `5da93ae` + rules | `3e8dff4` / `9509fc1c` | **No** | `membership_service.py` unchanged. The C10-collab-* and legacy-row probes are still allowed (6 attacks) | Ours fixes it (pending C10 sign-off) | **NOT PRESENT IN AVAILABLE REFS** |
| B0-12 `require_org_access` | studio-backend `5da93ae`, agent-design `c56271d` | `3e8dff4`, `e8d03a2` | **No** | `require_permission` unchanged in both (studio-backend `auth.py` changed only in `verify_admin_user`); B0-12 tests still RED | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-13 create/fork | `5da93ae` | `3e8dff4` | **No** | `agent_routes.py` unchanged; the `agent_service.py` change (`7ec75a9`) is unrelated (bridge auth) | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-14 agent-design | `c56271d` | `e8d03a2` | **Partly** | `f6e612f` (WB-010): read gate on `get_agent` and model override; membership check on `/organization/{org}/active`. **Not touched:** list-by-project (`agent.py` hunk list), `agent_user.py`, `agent_user_service.py`, `store.py` (install, store admin) | Ours covers all 8 sub-cases | **CTO FIX PRESENT BUT DIFFERENT** (partial) |
| B0-15 share-key scope | runtime `daee3f9` | `abf052d` | **No** | `api_key_middleware.py`, `agent_memory.py` unchanged | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-16 caller-chosen memory subject | `daee3f9` | `abf052d` | **No** | `agent_memory_service.py` unchanged; the `agent_webhook.py` / `cs_packet_builder.py` changes are unrelated features | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-17 email webhook | `daee3f9` | `abf052d` | **No** | `routers/email.py` unchanged | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-18 platform admin | studio-backend, engine, research | `3e8dff4`, `76e9d6a`, `7a327b1` | **Partly** | studio-backend `968da75` (2026-10-03): `verify_admin_user` now requires `email_verified` (acceptance flip confirms it in real code). It does **not** require a Google provider or `hd`, so a verified password account on `@olbrain.com` still passes (`test_B0_18_password_account…` still RED). Engine `require_olbrain_user` and research `is_internal_user` are unchanged (the current-only gate test is still RED) | Ours applies C2 in 4 repositories; the policy is pending Security | **CTO FIX PRESENT BUT DIFFERENT** (studio-backend only; weaker than C2) |
| B0-19 directives | `daee3f9` | `abf052d` | **No** | `directives.py` unchanged | Ours fixes the receiver | **NOT PRESENT IN AVAILABLE REFS** |
| B0-20 MCP | mcp `b75cc12` | `069208c` | **No** | `auth_middleware.py` and `main.py` unchanged (only calendly commits) | Ours fixes the service | **NOT PRESENT IN AVAILABLE REFS** |
| B0-21 Lumen | engine `dfc3a47` | `76e9d6a` | **No** | `bigquery.py` unchanged. (`76e9d6a` WB-025 changes the Lumen *ticket* org, not SQL isolation) | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-22 activities | `5da93ae` | `3e8dff4` | **No** | `activity_routes.py` unchanged | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-23 share token live key | `5da93ae` | `3e8dff4` | **No** | `share_token_service.py` unchanged | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-24 engine permission helper | `dfc3a47` | `76e9d6a` | **No** | `alchemist/utils/auth.py` unchanged | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-26 Meta signature | `daee3f9` | `abf052d` | **No** | `meta_whatsapp.py`, `meta_instagram.py` unchanged | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-27 email thread join | `daee3f9` | `abf052d` | **No** | `email.py` unchanged | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-28/28b API key via creator uid | `5da93ae` | `3e8dff4` | **No** | `access_control.py`, `analytics_authorization.py` unchanged; `_require_org_member` not touched | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-28c `resolved-notify` | `5da93ae` | `3e8dff4` | **Yes** | `432092b` (WB-023): only agent-engine's internal identity is accepted; everyone else gets 404 | Ours allows internal **or** a C2 admin; the CTO's is stricter (internal only) | **CTO FIX PRESENT BUT DIFFERENT** (stricter) |
| B0-28c `power-users`, `log-event`, `deleted`, `whatsapp-config` GET | `5da93ae` | `3e8dff4` | **No** | `analytics_routes.py` changed only by `32c4fa8` (recording playback); the `power-users` dependency is still only `verify_firebase_token`; `api_key_routes.py` and `delete_proxy_routes.py` unchanged | Ours fixes them | **NOT PRESENT IN AVAILABLE REFS** |
| B0-30 any user updates any org | `5da93ae` | `3e8dff4` | **No** | `organization_service.py:263` still says "Permission check removed"; whatsapp-config POST/DELETE still depend only on `verify_firebase_token` | Ours fixes it | **NOT PRESENT IN AVAILABLE REFS** |
| B0-31 invite takeover (+ B0-33 token accept for a body `user_id`) | `5da93ae` | `3e8dff4` | **Yes** | `1fb1a00` (WB-012): the org-route accept requires the token email to equal the invite email and be verified; the token-route accept writes for the caller's uid and refuses a different body `user_id` | Same semantics as ours (`0f8619e`) | **OUR FIX ALREADY MATCHES** (CTO fix verified) |
| B0-32 bridge session sharing | — | `abf052d` | **No** | Runtime Meta files unchanged | Not fixed by either | **NOT PRESENT IN AVAILABLE REFS** |
| B0-34 self-marked verification | — | `3e8dff4` | **No** | `user_routes.py` changed only by `5b54b1c` (directory endpoint) | Not fixed by either | **NOT PRESENT IN AVAILABLE REFS** |
| B0-35 C10 over-breadth in agent-design | — | `e8d03a2` | **No** | `agent_service.py` unchanged | Not fixed by either | **NOT PRESENT IN AVAILABLE REFS** |
| B0-36 MCP OAuth/template/gateway agent ids | — | `069208c` | **No** | `main.py` unchanged | Not fixed by either | **NOT PRESENT IN AVAILABLE REFS** |

**CTO security commits that address no B0 finding** (recorded only so they are not mistaken for B0 fixes):

| Repository | Commit | What it fixes |
|---|---|---|
| agent-engine | `6844808` | WB-024: Nexus chat org membership |
| agent-engine | `76e9d6a` | WB-025: Vibe session tenancy per turn; Lumen ticket org |
| studio-backend | `7ec75a9` | WB-021: studio-backend → agent-bridge auth |
| studio | `ffdb7c1b` | WB-020: `agent_senders` query scope |
| studio | `325c293a`, `b965328e`, `3447d024`, `5b080d69`, `e7373a78`, `fa1a4145`, `70497c4f` | Server-only and org-scoping rule batches; these underlie the rule results above |

## 4. Exact CTO commit SHAs per verified fix

| Fix | Repository | Commits |
|---|---|---|
| Rules default deny and org scoping (B0-01…11, B0-25) | olbrain-studio | `d9be212d`, `e7373a78`, `5b080d69`, `0835fca3`, `40bbb6a7`, `fa1a4145`, `325c293a`, `3447d024`, `b965328e` (on `origin/main` `9509fc1c`) |
| Admin `email_verified` (B0-18, partial) | olbrain-studio-backend | `968da75` |
| Invitation accept bound to the caller (B0-31, B0-33) | olbrain-studio-backend | `1fb1a00` |
| `resolved-notify` internal-only (B0-28c, one route) | olbrain-studio-backend | `432092b` |
| agent-design read gates (B0-14, partial) | olbrain-agent-design | `f6e612f` |

## 5. Not verifiable from here

- **Deployment.** The `d9be212d` commit message states that an emulator probe of 184 production collections gave "identical results under the deployed rules and this change". That is the CTO's statement about the deployed ruleset. It is **not independently verified** here.
- **Fixes the CTO made today that are not on any reachable ref.** Cannot verify CTO fix from the available repository state; need commit SHA/branch/PR from CTO. This applies to any fix not listed in §4. In particular, nothing reachable touches B0-12/13/15/16/17/19/20/21/22/23/24/26/27/28/28b/29/30.

## 6. Baseline for the next security validation

**Use each repository's newest `origin/main`** (table in §1).
- Studio rules: `9509fc1c`.
- Server repositories:

| Repository | Commit |
|---|---|
| studio-backend | `3e8dff4` |
| agent-design | `e8d03a2` |
| agent-runtime | `abf052d` |
| agent-engine | `76e9d6a` |
| mcp-deployer | `069208c` |
| research-runtime | `7a327b1` |
| workflow-runtime | `7a6b07b` |

**Our `b0/security` branches are based on the old audited commits and have not been rebased.** Re-applying them onto these baselines is a separate, explicitly authorised step. For the rules, the CTO's default-deny file should replace our stage-1/stage-2 port as the base; our remaining rule-level deltas would then be B0-29 (C10) and the RU-group-project-only probe.
