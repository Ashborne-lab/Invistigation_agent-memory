# Lane B / B0: Implementation Status v2

**Date:** 2026-10-03.

**Supersedes:** [`memory-lane-b-b0-implementation-status-v1.md`](memory-lane-b-b0-implementation-status-v1.md). v1 stays as the record of the first pass.

**Scope.** Local `b0/security` branches only:
- nothing was pushed, opened as a PR, deployed or migrated, and there were no shadow writes;
- no production data was read;
- push is disabled in all 13 workspace repositories;
- B1/B2 were not started.

**Contracts.** [`lane-b/b0-impl-contracts.md`](lane-b/b0-impl-contracts.md), C1–C10. Amendments A1–A12 still need owner or Security sign-off.

**Blockers.** [`memory-lane-b-b0-blockers-v1.md`](memory-lane-b-b0-blockers-v1.md). §5 below supersedes its §1 (session permission blocks), which is now resolved.

## 1. What is now GREEN

### Acceptance suite (74 tests). Re-run by the coordinator on 2026-10-03

| Target | Result |
|---|---|
| `current` (`origin/main`) | 62 RED / 12 GREEN (baseline, unchanged) |
| `reference` (spec) | 73 GREEN / 1 skipped |
| **`owner`** (real `b0/security` code, all six `owner_parts`) | **73 GREEN / 1 skipped**. The skip is the current-only gate test, by design |
| `owner` pointed at `origin/main` (control) | 73 errors: the GREEN results come from branch code |

**Every acceptance test for B0-12 … B0-24 is GREEN against real branch code.** Some route handlers are proven through repository tests rather than inside the adapter. These are marked WIRING-ONLY, and each names an existing repository test:

| `owner_parts` file | WIRING-ONLY entries |
|---|---|
| agent_design | 9 |
| agent_runtime | 9 |
| mcp | 3 |
| studio_backend | 1 |
| agent_engine | 0 |
| research | 0 |

### Firestore rules (repository `firestore.rules`, local emulator, from v1, unchanged this pass)

| Rules | Attack probes allowed | Legit twins denied | Revocation | Studio rules suite |
|---|---|---|---|---|
| Current production file | 51/51 | — | 0/12 | — |
| Stage 1 | 1/51 (V2-new-collection, by design) | 0 | 12/12 | 456/456 |
| Stage 2 (`firestore.stage2.rules`, held for Noesis) | 0/51 | 0 | 12/12 | 454/456 (2 intended flips) |

### Repository suites (reported by the implementing agents; not re-run by the coordinator)

| Repository | Before | After | New failures |
|---|---|---|---|
| studio-backend | 3574 passed / 6 failed | **3715 / 6** (same six) | 0 |
| agent-runtime | 5308 passed / 135 failed | **5478 / 135** (same) | 0 |
| agent-engine | 3962 passed / 20 failed | 4022 / 20 (same) | 0 |
| agent-design | 1921 passed / 38 failed | 2000 / 39 (see note) | 0 attributable |
| mcp-deployer | 962 passed / 40 failed / 64 errors | **1014 / 40 / 64** (identical set) | 0 |
| research-runtime | Chunked: same 66 pre-existing failures per chunk before and after | Same | 0 |
| studio (Jest) | 49 failed pre-existing | Touched files green | Full suite not re-run after `22b25b50` |

**agent-design note.** About 30 xdist workers crash per run on tests that try to reach real GCP. The 13 failures that appear only after the change fail identically with the change stashed. A targeted comparison over 59 relevant files gave 31 failed / 631 passed before and 31 / 643 after, with every failure in a hang-prone file.

### Local commits (`b0/security`)

| Repository (base) | Commits |
|---|---|
| olbrain-studio (`1f05ca11`) | `e16f2e48`, `eb018f0e`, `2ac0b906`, `53aa5da9`, `22b25b50`, `16c7747c` |
| olbrain-studio-backend (`5da93ae`) | `149e417`, `9838f54`, `07db37f`, `684b32a`, `2e47a29`, `33c5dc8`, **`0f8619e`** (B0-30/31/28c) |
| olbrain-agent-runtime (`daee3f9`) | `c745a85`, `4b20e9e`, **`8eecdd1`** (B0-26/27) |
| olbrain-agent-engine (`dfc3a47`) | `ac12593`, `0c75915`, `92e262b` |
| olbrain-agent-design (`c56271d`) | **`02aee8c`** (B0-12/14) |
| olbrain-mcp-deployer (`b75cc12`) | **`bfc4331`** (B0-20 service) |
| olbrain-research-runtime (`6b81691`) | **`61ff951`** (B0-18 gate, C2) |
| olbrain-workflow-runtime (`2356de0`) | none (no MCP call site in this repository; see §2) |

## 2. Per finding (this pass in bold; earlier rows summarised from v1)

| Finding | State | Evidence |
|---|---|---|
| B0-01…11, B0-25 (rules) | DONE locally (stage 1; stage 2 held) | Emulator, above |
| B0-12 | DONE (studio-backend + **agent-design**) | AT 6/6 |
| B0-13 | DONE | AT 6/6 |
| **B0-14** | **DONE** (`02aee8c`): `get_agent` check, list-by-project org, active, model, `agent_users` writes bound to the row's own agent, install, C2 store admin | AT 8/8; 18 repository tests |
| B0-15, 16, 17, 19, 23 | DONE (runtime + backend + Studio). **B0-16 / INV-S8 is now closable on the direct Meta path:** signed only | AT 23/23 (runtime) + B0-23 5/5 |
| B0-18 | DONE in studio-backend, engine and **research-runtime** (`61ff951`, C2, no fallback) | AT 5/5 |
| **B0-20** | **Service DONE** (`bfc4331`): auth always on; agent only from a verified binding; no default or env credentials for tenant-scoped servers; credential routes allow-listed. **Callers PARTIAL:** agent-runtime done; research-runtime and workflow-runtime blocked (see below) | AT 8/8; 45 repository tests |
| B0-21 | DONE in code; BigQuery unproven | AT 6/6 (SQLite) |
| B0-22, 24, 28, 28b, 29 (C10) | DONE (v1) | AT / repository tests |
| **B0-26** | **DONE** (`8eecdd1`): `X-Hub-Signature-256` over the raw body on `/api/webhook/meta` and both bridge routes. No secret → 503; bad or missing signature → 401. Only the direct signed path is `channel_verified`; bridge = `asserted` | `tests/test_b0_meta_signature.py` (52/52 Meta tests) |
| **B0-27** | **DONE** (`8eecdd1`): session = (verified sender, thread root). A session is adopted only if its recorded `verified_sender` matches. Unverified mail never joins verified threads | `tests/test_b0_email_inbound.py` (27/27) |
| **B0-28c** | **DONE** (`0f8619e`): the 5 coordinator-verified routes, plus every sub-audit route confirmed and fixed per route (per-route table in the agent report: org owner/admin mutations, domains, project/user/template/share-run routes, personal routes). No global API-key policy was added. Two items not confirmed: project agent assign/unassign (reported broken at runtime, untouched) and the member invite/role/remove, join/access-request routes (rely on `require()`; not verified line by line) | 36 tests in `tests/test_b0_30_31_28c.py` (35/36 RED on the previous HEAD) |
| **B0-30** | **DONE**: whatsapp-config POST/DELETE need `ORG_SETTINGS_EDIT` (owner/admin per olbrain-shared matrix). `PUT /{org}` was already gated; only its misleading docstring was fixed | Same file |
| **B0-31** | **DONE**: org accept requires a Firebase principal with `email_verified is True` and body email == token email. Token accept also binds `user_id` to the caller (**B0-33**, below) | Same file |

## 3. Newly discovered issues (encountered directly during this pass)

| ID | Repository | Finding | Class | State |
|---|---|---|---|---|
| B0-32 | agent-runtime | Bridge-forwarded (asserted) WhatsApp messages still share the phone-based conversation session (`{phone}-{agent}`) with the signed direct path, so a forged bridge message reads that session's history | VERIFIED by implementing agent (not re-read by coordinator) | **OPEN** |
| B0-33 | studio-backend | `POST /api/invitations/{token}/accept` created the membership for the body `user_id`, so the invite could be granted to another account | VERIFIED CURRENT (agent) | **FIXED** in `0f8619e` |
| B0-34 | studio-backend | `PATCH /api/users/{uid}/verification` lets users self-mark email/phone as verified in `user_profiles`. No studio-backend check reads it | OPEN QUESTION: does any client or rule trust it? | **OPEN** |
| B0-35 | agent-design | `check_edit_permission`, `_check_capability`, `check_view_permission` and `check_org_govern_permission` read `memberships` without a `type` filter. This is the C10 over-breadth inside agent-design (datastore, documents, potions, brain, presence) | VERIFIED CURRENT (agent) | **OPEN.** Its fix is the C10 semantics awaiting sign-off |
| B0-36 | mcp-deployer | Shopify/WooCommerce OAuth routes take `agent_id` from the body under auth-exempt `/api/oauth/*` (`main.py:2660, 2896, 3027, 3306`); `/api/v1/template?agent_id=` reads any agent's tool config (`main.py:2492`); the private gateway chooses the customer config from the caller-supplied `X-MCP-Config-Id` | VERIFIED CURRENT (agent) | **OPEN** |
| B0-37 | mcp-deployer | The environment-credential tier would have handed a single-tenant BYOK wrapper's org-A credential to a bound org-B agent | VERIFIED CURRENT (agent) | **CLOSED** by `bfc4331`. Research paid connectors and BYOK wrappers will get 403 until an org-only binding exists (Security decision) |
| B0-38 | mcp-deployer config | cratio, ecommerce, olbrain-test and playwright-recorder are public-ingress **and** had no app-level auth: anyone on the internet could call `tools/call` with any agent (per config) | VERIFIED in config; DEPLOYMENT STATUS UNVERIFIED | Code fixed; ingress unchanged (ops) |

**Also reported:**
- The shared HMAC binding key lets any holder mint a binding for any agent, and `iss` is self-declared. This is part of the Security key-custody decision.
- Agentless tool discovery still starts a subprocess with default credentials. It lists names only, with no tool calls.

## 4. Remaining RED / not done

| Item | Why |
|---|---|
| B0-20 callers in research-runtime (`app/tools/mcp_client.py:154, :198`) | Research runs carry an org but **no agent**. A binding needs an org-only binding form: **Security decision** |
| B0-20 callers in olbrain-shared (`workflow/mcp_client.py`, used by workflow-runtime; `_agentic_loop.py`) | The fix belongs in olbrain-shared (per-request mint). That repository was outside this pass, and it needs a release plus version bumps |
| B0-20 other callers: agent-design `routers/mcp.py:195`, `mcp_service.py:508, :1615`, `config_generator_service.py:1592`; studio-backend `private_mcp_service.py:442` | Not wired. The credential-admin caller decision (A10) comes first |
| B0-32, B0-34, B0-35, B0-36 | Open (above) |
| Project agent assign/unassign route; member/join/access-request routes | Not verified line by line (B0-28c residue) |
| Studio full Jest suite after `22b25b50` | Not re-run |

## 5. Decisions still blocking (unchanged policy; code waits behind config and fails closed)

| Decision | Owner | Code state |
|---|---|---|
| MCP signing scheme, KMS, key custody, rotation; org-only binding for research/BYOK; credential-admin caller (A10) | Security | HMAC behind one `_sign` function; no key → deny |
| Google SSO / staff admin identity policy (C2). **No backend sets an `admin` claim today**, so staff are locked out if the `hd` claim is absent | Security | C2 enforced in 4 repositories; no fallback |
| Trusted end-user id assertion by an org's server | Product / Security | Default no; no opt-in built |
| Share credential TTL, and channel-link max age | Product | Required env vars; missing → 503 |
| C10 authorization semantics (agent-only collaborators lose org-wide reads; `agent_access`). This also gates B0-35 | Security + owners | Implemented in studio-backend + rules; agent-design partly |
| Legal / privacy treatment of possibly misattributed legacy memory | Legal | No rekey, no migration |
| Contract amendments A1–A12 | Respective owners | Recorded in contracts |

## 6. Exact remaining requirements for G-SEC

**1. Local code gate**
- The acceptance suite is GREEN (73/73 applicable).
- **Still required:**
  - fix or formally accept B0-32, B0-34, B0-35, B0-36;
  - wire the remaining B0-20 callers once the Security binding decision lands (research-runtime, olbrain-shared/workflow, agent-design, studio-backend);
  - verify the two unconfirmed B0-28c route groups;
  - re-run the Studio full Jest suite.

**2. Staging rules gate**, in this order:
1. Build the 6 composite indexes additively (never `firebase deploy --only firestore:indexes`).
2. Run the `memberships_index` C10 backfill as a staging dry run. Untyped memberships must count 0. Then apply.
3. Deploy the services in this order: runtime → studio-backend → agent-design → Studio.
4. Deploy the stage-1 rules to the staging project.
5. Run on staging: probes (all denied except V2-new-collection), twins, revocation 12/12, Studio smoke tests, and Noesis smoke tests.

Stage 2 only after the Noesis inventory.

**3. Infrastructure gate.** Provision and verify:
- `META_APP_SECRET`;
- `EMAIL_INBOUND_PARSE_SECRET` and the Parse URL;
- `DIRECTIVES_ALLOWED_SERVICE_ACCOUNTS` / `DIRECTIVES_AUDIENCE`;
- `MCP_AGENT_BINDING_KEY`, `MCP_EXPECTED_AUDIENCE` (base URL) and `MCP_CREDENTIAL_ADMIN_INVOKERS`, per project;
- `SHARE_CREDENTIAL_TTL_SECONDS` and `SHARE_CHANNEL_TOKEN_MAX_AGE_DAYS`;
- `LUMEN_BQ_AGENT_LOG_VIEW`, plus the BigQuery authorised view and IAM;
- MCP ingress review (public projects first).

Also:
- inventory `default:*` credentials and BYOK wrappers;
- confirm Firebase sign-up providers and the `hd` claim;
- confirm the deployed ruleset and the deployed service revisions.

**4. Missing repositories** (resolved, or formally accepted by their owner):
- olbrain-noesis-os: stage 2, and its browser queries;
- agent-directives: must send OIDC;
- the webhook service: must forward `shc_`;
- olbrain-agent-bridge: must sign the forwarded Meta body;
- analytics-service: rollup `organization_id`;
- olbrain-shared: the MCP caller fix.

**5. Staging proof of real route behaviour** for every server finding: the owner adapters prove decision code plus repository wiring tests, not deployed behaviour.

## 7. Gate states

| Gate | State |
|---|---|
| 1. Local code gate | **NOT PASSED.** The acceptance suite is fully GREEN, but B0-32/34/35/36 are open and B0-20 callers are partial |
| 2. Staging rules gate | **NOT PASSED** (not run) |
| 3. Infrastructure gate | **NOT PASSED** (nothing provisioned) |
| **4. G-SEC overall** | **NOT PASSED** |

**Stop.** B1/B2, the Memory Gateway, the PG schema, migration and shadow writes were not started.
