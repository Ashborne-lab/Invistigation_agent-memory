# Person Identity — Measurement Pass

Date: 2026-09-26. Read-only investigation.
Companion to `investigation/person-identity-architecture-research.md` (2026-09-25), whose
conditional recommendation this pass exists to test.

**Evidence base.** Same fetched commits as the research report, re-used unchanged:
`olbrain-agent-runtime 8df0e02` · `olbrain-agent-design 51ffe3b` · `olbrain-agent-engine e43654e` ·
`olbrain-shared 8a0f0b5` · `olbrain-studio 8cee761c` · `olbrain-studio-backend ca9724a` ·
`olbrain-research-design e211584` · `olbrain-research-runtime 6b81691` ·
`olbrain-knowledge-vault 66b02e2` · `olbrain-workflow-runtime 1978f4a`

**Labels.** `[CODE]` verified in source at a named commit · `[DATA]` measured against real data ·
`[CONTRACT]` the normative contract states it · `[INFERENCE]` reasoning of this pass ·
`[UNDECIDED]` genuinely open · **`[UNMEASURED]`** requires data access this workspace does not
have · **`[UNMEASURABLE]`** no ground truth exists in the current model, so no amount of access
would answer it as posed.

The last two are deliberately distinct. Conflating them would let a reader think every gap is
waiting on a credential. One of them is not.

**Not done here:** no production query, no data modification, no code change, no contract
change, no modification to the research report or any other existing artifact.

---

## 1. Executive measurement summary

### Finding 0 — this workspace has no production data access, so §§1–5 cannot be measured here

Established before any other work `[CODE]`:

- No credentials, service-account files, `.env`, exports, CSV or JSONL fixtures anywhere in the
  workspace outside `repos/`.
- `gcloud` is not installed. No `GOOGLE_APPLICATION_CREDENTIALS`, `FIREBASE_*`, `GCLOUD_*` or
  `FIRESTORE_*` environment variable is set.
- The `firebase` CLI is present and logged in as **`coderbash6@gmail.com`** — not the OLBrain
  account — and `firebase projects:list` **fails**. No OLBrain project is reachable.

Sections 1–5 of the task ask for counts, percentages and joins over live Firestore. **Those
numbers cannot be produced here, and this pass does not estimate them.** Per the standing
project rule, they are recorded as unresolved rather than invented.

**I did not attempt to reach production.** Even had an authenticated path existed, reading
customer phone numbers and email addresses out of production is not authorised by this task and
the workspace is explicitly an investigation copy. If such a route is wanted, it should be an
explicit decision, not a side effect of a measurement pass.

What this pass delivers instead, for §§1–5: the **structural bounds** derivable from code (which
materially narrow several of the questions), and **executable query specifications** — exact
collection paths, join keys, populations, limitations, and the threshold at which each result
would change the recommendation — so that whoever has access can produce the numbers in an
afternoon rather than re-deriving the method.

### What this pass did settle, from code and git history

| # | Question | Result |
|---|---|---|
| §6 | Have `person_hash` and `memory_doc_id` ever diverged? | **No, never.** Byte-identical since introduction. The risk is latent, not historical. `[CODE]` |
| §7 | Does identity feed an authorization decision (F8)? | **No.** Identity is addressing only; authorization is API key + org match, independent. **This falsifies a claim in my own prior report.** `[CODE]` |
| §5 | Is F4's stale tenancy measurable at all? | **Yes** — transfers are logged (`activities`, `activity_type='agent_transferred'`). And F4 is worse than stated: the cascade handles **16 collections including `agent_sessions`, and omits every person-keyed store.** `[CODE]` |
| §8 | Are there identity mechanisms the report missed? | **Two, and one is decisive** — `research_clients` is a complete alias + merge + redirect entity-resolution model already in production. `[CODE]` |
| §2 | Can fragmentation-per-human be measured? | **No — `[UNMEASURABLE]`.** There is no ground truth for "one human" anywhere in the system. The question is circular as posed. |

### The single most consequential discovery

`olbrain-research-design e211584:app/routers/org_research_clients.py` implements, in production,
at `organizations/{org_id}/research_clients/{client_key}`:

- an **`aliases`** array — many observed names resolving to one entity,
- a **`merged_into`** pointer plus `archived: true` on the non-surviving entity,
- **alias inheritance on merge** (`survivor.aliases |= loser.aliases | {loser}`),
- a bound (`_MAX_ALIASES`) and an `updated_by` audit field,
- all **org-scoped** by path.

That is the architecture the research report recommends for persons — observed identifiers →
resolution → surviving canonical subject, tenant-scoped, non-destructive, audited. **It is the
third independent in-house implementation of this pattern** (after `organizations.merged_into`
and `lead_people`'s union-find), and the closest structurally, because it is the only one with
an explicit alias set.

`[INFERENCE]` The resolution-layer model is therefore not an architectural invention. OLBrain has
built it three times, for three different entity classes, and never for the entity the product
actually converses with. That materially weakens the "this is over-engineering" objection and
shifts the open question from *"is this the right shape?"* to *"is cross-channel recognition
worth having?"* — which remains J1 and remains a product decision.

---

## 2. Co-occurrence results

**Status: `[UNMEASURED]` — requires data access. Structurally bounded here.**

### 2.1 What the code proves about where co-occurrence can exist

`[CODE]` Co-occurrence evidence — one record proving two identifier types belong to one human —
can be produced by **exactly one store**, and cannot be produced by the person-memory pipeline at
all:

- **`lead_profiles` / `lead_contacts` can.** A single lead profile is populated from fields
  captured during a conversation and may carry both an email and a phone. `lead_people`'s
  union-find exists precisely to exploit that: *"Any single profile carrying BOTH values is proof
  that those two keys are one human"* (`olbrain-agent-runtime 8df0e02:core/lead_people.py:14-17`).
- **`agent_datastores` cannot, by construction.** The extract pipeline takes **one** `user_key`
  per turn, derived from `AbstractMessage.user_id`, which is a single channel-local identifier
  (`core/lightweight_processor.py:3890`). A row records one person as known through one
  identifier. Nothing in that path ever observes two identifier types together.
- **`agent_users` cannot.** Its key is `(agent_id, channel, channel_user_id)` — one row per
  endpoint, with no field relating one endpoint to another
  (`services/firebase_service.py:274-295`).
- **`agent_user_memory` cannot.** Keyed `{agent_id}__{digest}` from the same single `user_key`.

`[INFERENCE]` **Therefore `lead_profiles` is the only valid population for measuring
co-occurrence**, and any measurement taken elsewhere would be measuring nothing. This also means
the co-occurrence *rate* is a property of the lead-capture product surface, not of the platform
as a whole — a bias that must be stated with any number produced (§2.3).

### 2.2 Executable specification

| Element | Specification |
|---|---|
| **Population** | `lead_profiles` documents, grouped by `organization_id` |
| **Numerator A** | profiles where `normalise_contact_email(fields)` **and** `normalise_contact_phone(fields)` both return non-`None` |
| **Numerator B** | profiles yielding ≥2 distinct usable contact keys of any type |
| **Denominator** | profiles yielding ≥1 usable contact key (profiles with none are excluded — `lead_people` counts but never merges them) |
| **Normalisation** | must use `core/lead_contacts.py:normalise_contact_email` / `normalise_contact_phone` verbatim, **not** a reimplementation — the digits-only phone rule is the identity decision (`:180-202`) |
| **Per-org split** | required; report median and spread, not a pooled mean |
| **Exclusions** | `_WITHHELD_CONTACT_KEYS` (`office_number`, `home_number`, `alternate_number`, `reachable_at`) are unreachable by definition and must not count (`:291-293`) |

### 2.3 Known biases to state alongside any result

`[INFERENCE]`

1. **Survivorship toward voice/lead-capture.** Lead profiles arise where an agent is configured
   to capture contacts. The rate says little about text channels.
2. **Capture-prompt dependence.** An agent that asks for both an email and a phone manufactures
   co-occurrence; one that asks for either suppresses it. The measured rate is partly a
   measurement of agent design, not of human behaviour.
3. **Under-counting by design.** Digits-only phone normalisation deliberately keys national and
   country-code forms separately (`:181-188`), so genuine co-occurrence can be missed. Any
   number is a **lower bound**.
4. **It is not the same question as J1.** Co-occurrence measures *how often the system could
   prove two identifiers are one human within one org's lead data*. J1 asks whether the product
   needs cross-channel recognition. A low rate does not prove low need — it may equally prove the
   current capture surface has no way to express it (§11).

### 2.4 The threshold that would change the recommendation

`[INFERENCE]` The research report's falsification attempt 3 says a resolution layer is not worth
building if co-occurrence is rare. Making that operational:

- **Below ~5% of contactable profiles**: the resolution layer would merge almost nothing.
  Option B (per-tenant keyed hash) plus an explicit product statement that identity is
  per-channel is the better architecture, and the report's recommendation should be withdrawn.
- **Above ~20%**: fragmentation is affecting a large minority of known contacts and the
  resolution layer is justified on the measured evidence alone.
- **Between**: not decidable by this number, and J1 must be answered directly.

These thresholds are this pass's proposal, not a decided policy. `[UNDECIDED]`

---

## 3. Fragmentation results

**Status: partly `[UNMEASURABLE]`, partly `[UNMEASURED]`.**

### 3.1 The central metric is unmeasurable as posed, and that is itself the finding

The task asks for the *"average number of `person_hash` values associated with one observed
human"*. `[INFERENCE]` **That number cannot be computed, and not because of missing access.**

Computing it requires knowing which `person_hash` values belong to the same human. That is
precisely the mapping that does not exist — it is the research report's central finding and the
thing a resolution layer would create. The question asks to measure fragmentation against an
identity resolution whose absence *is* the fragmentation.

The circularity is worth stating plainly because it is a stronger argument than any number would
have been: **OLBrain cannot currently measure how fragmented its person data is, because
measuring that requires the very mechanism it lacks.** Nothing in the system can answer "how many
records describe this human?"

The only escape is a proxy with its own bias — `lead_profiles` co-occurrence (§2), which measures
fragmentation only where the lead-capture surface happened to record two identifiers. That proxy
cannot see the WhatsApp/email split that §3.2 shows is structurally guaranteed.

### 3.2 What *is* provable without data: fragmentation is structural, not incidental

`[CODE]` Fragmentation does not depend on user behaviour or data quality. It is forced by the
ingress design. One human reaching **the same agent** on two channels produces two unrelated
`person_hash` values, because `user_id` is a different kind of identifier per channel:

| Channel | `user_id` | Site (`olbrain-agent-runtime 8df0e02`) |
|---|---|---|
| WhatsApp | `from_number` | `routers/meta_whatsapp.py:965` |
| Email | `from_email` | `routers/email.py:311` |
| Instagram | `sender_igsid` | `routers/meta_instagram.py:314` |
| Directives/voice | `phone_number or session_id` | `routers/directives.py:215, 342` |
| Web chat | `None` → session id | `routers/chat.py:224` + `lightweight_processor.py:3890-3894` |

`[INFERENCE]` So the fragmentation *ceiling* is known without any data: **a human using N
distinct channel identifier types with one agent has exactly N person records**, plus one more
for every anonymous web-chat session. No measurement is needed to establish that; only its
frequency is unknown.

### 3.3 Normalisation-induced fragmentation — a worked example

`[CODE]` Two of the three regimes disagree on the same phone number:

| Input | `person_hash` (`strip+lower` only) | `lead_contacts` (digits-only) |
|---|---|---|
| `+91 98765-43210` | `sha256("+91 98765-43210")` | `919876543210` |
| `919876543210` | `sha256("919876543210")` | `919876543210` |
| `98765 43210` | `sha256("98765 43210")` | `9876543210` |

Under `person_hash` these are **three people**. Under `lead_contacts` they are **two** (the
national form keys separately on purpose). `[INFERENCE]` A single agent whose WhatsApp webhook
supplies E.164 and whose voice directive supplies a national form will therefore hold two person
rows for one caller, permanently, with no code path capable of relating them.

### 3.4 Executable specification for the measurable part

| Metric | Method | Limitation |
|---|---|---|
| Channel-overlap rate | Group `agent_users` by `(agent_id, channel_user_id)`; count identifiers appearing under **>1 `channel`** | Only catches the *same string* on two channels; a phone on WhatsApp and an email on email are invisible |
| Normalisation collisions | For all `agent_users.channel_user_id` in one agent, compare `normalise_contact_phone(x)` equality against `person_hash` inequality | Proves §3.3 empirically; needs the real normaliser |
| Session-row share | Ratio of `user_key_kind="session"` to `"identity"` rows in `agent_datastores` | See §5 |

### 3.5 Operational significance

`[UNMEASURED]`. `[INFERENCE]` The *mechanism* by which fragmentation becomes visible to a
customer is established: `core/packet/person_records.py` renders a person's extract rows into the
system prompt on every packet build. A fragmented person is therefore an agent that greets a
returning customer as a stranger on their second channel. Whether that is happening often enough
to matter is exactly J1, and is not answerable here.

---

## 4. agent_datastores recovery results

**Status: `[UNMEASURED]` for all counts. Join validity and cardinality settled from code.**

### 4.1 The join is valid — verified pairwise

`[CODE]` The research report's proposed recovery join works because `channel_user_id` and
`user_id` are assigned from the **same source variable** at every call site:

| Channel | `channel_user_id=` | `user_id=` | Same expression? |
|---|---|---|---|
| WhatsApp | `from_number` (`meta_whatsapp.py:888`) | `from_number` (`:965`) | yes |
| Email | `from_email` (`email.py:290`) | `from_email` (`:311`) | yes |
| Instagram | `sender_igsid` (`meta_instagram.py:296`) | `sender_igsid` (`:314`) | yes |
| Directives | `phone_number or session_id` (`directives.py:502`) | `phone_number or session_id` (`:215`) | yes |

So `person_hash(agent_users.channel_user_id)` reconstructs the `agent_datastores` entry id
exactly. `[CODE]`

### 4.2 Coverage is bounded, and the gap is benign

`[CODE]` `upsert_agent_user` is called from `agent_webhook.py:2637`, `directives.py:343` and
`:499`, `email.py:287`, `meta_instagram.py:293`, `meta_whatsapp.py:885` — **every channel
carrying a real identifier**. It is *not* called from `routers/chat.py`, which is the web-chat
path that has no identifier to recover. Recovery covers precisely the rows where recovery is
possible.

### 4.3 The join is not 1:1 — a structural ambiguity the report did not state

`[CODE]` `agent_users` is keyed `(agent_id, channel, channel_user_id)`, so the **same identifier
observed on two channels produces two `agent_users` records** — for example a phone number
arriving via both `meta_whatsapp` and `directives`. Both yield the identical
`person_hash(phone)`, hence the identical single `agent_datastores` entry.

`[INFERENCE]` So the join's cardinality is **many `agent_users` → one `agent_datastores` row**,
not one-to-one. This is not a defect: it is the one place in the current system where two channel
observations are *already* known to concern the same person, because they share an identifier
string. **It is a second, previously unnoticed source of co-occurrence evidence** — weaker than
`lead_profiles` (same identifier, not two identifier types) but real, and it would be free to
exploit during migration. The task's "rows that map to multiple `agent_users` records" is
therefore expected, and counting it is a measurement of channel overlap (§3.4), not of error.

### 4.4 Executable specification

| Quantity | Method | Notes |
|---|---|---|
| Total extract identity rows | `agent_datastores/*/tables/*/entries` where `user_key_kind == "identity"` | `[UNMEASURED]` |
| Session rows | same, `user_key_kind == "session"` | §5 |
| Recoverable | entry ids matching `person_hash(cu)` for some `agent_users` row with the same `agent_id` | join per agent, never across agents |
| Unrecoverable | identity rows with no match | the true residue of D3 |
| Ambiguous / multi-map | recoverable rows matching ≥2 `agent_users` records | §4.3 — a channel-overlap signal, not an error |
| Cross-org anomalies | table-header `organization_id` ≠ the agent's current `organization_id` | **this is the F4 probe — see §6** |

**Population limit.** Only agents whose channels call `upsert_agent_user`. Web-chat-only agents
will show 0% recoverable and must be reported separately rather than dragging the aggregate down.

---

## 5. Session-row blast radius

**Status: counts `[UNMEASURED]`. Behaviour fully settled `[CODE]`.**

### 5.1 Confirmed: written by one path, read by none

`[CODE]` Re-verified at `8df0e02`:

- **Write** — `core/lightweight_processor.py:3890-3894` falls back to `session_id` with
  `user_key_kind = "session"` when `user_id` is absent.
- **Read** — all three prompt-read paths (`core/cs_packet_builder.py:1875`, `:1921`, `:2017`)
  open with `user_key = message.user_id` and `return ""` when absent. **None falls back to
  `session_id`.**

So a session-keyed row is unreachable by the agent that wrote it. The write path's own comment
anticipates *"a later dedup pass"* that exists nowhere in any repository.

### 5.2 Is any session row read by anything?

`[CODE]` The HTTP datastore surface (`routers/datastore.py`, and the entry endpoints referenced
from `routers/agent_memory.py:60-67`) serves entries **by table**, not by person key, so an
operator browsing a table in Studio **does** see session-keyed rows. They are invisible to the
agent, not to humans.

`[INFERENCE]` That is consistent with the write-path comment that `user_key_kind` exists *"so the
UI can label the row honestly"*. The rows are therefore not dead in the product sense — they are
operator-visible lead capture — but they are dead in the **memory** sense, which is the sense
that matters for the target architecture.

### 5.3 What they should become

`[INFERENCE]` The research report's §17.4 position holds and is strengthened: session-keyed rows
are **conversation-scoped records, not persons**. They were never read as person memory, so
migrating them as Memory keyed by a subject would invent a person the system never believed in.
They should migrate as session-scoped data, retaining operator visibility.

### 5.4 Executable specification

Count `entries` by `user_key_kind`, grouped by `agent_id` and `table_id`; cross-reference the
agent's configured channels. `[INFERENCE]` The expected shape is that session rows concentrate
almost entirely in agents whose traffic is web chat (`routers/chat.py`, `user_id=None`) — if they
appear materially on identifier-bearing channels, something else is wrong and that would be a new
finding.

---

## 6. Transfer / stale-tenancy results

**Status: counts `[UNMEASURED]` but fully answerable with access. F4 sharpened materially.**

### 6.1 Transfers are recorded — so the question is measurable

`[CODE]` Contrary to a worry that transfers might leave no trace:

- `olbrain-studio-backend ca9724a:constants/activity_types.py:94-95` defines
  `agent_transferred` and `agent_transfer_received`; `:132` marks `agent_transferred` as
  `ActivitySeverity.WARNING`.
- Activities are written to the **`activities`** collection
  (`services/activity_service.py:505`), and emitted at
  `services/agent_transfer_service.py:2326` and `:3173`.
- Transfer intent is separately persisted in **`agent_transfer_invites`**
  (`services/agent_transfer_service.py`), with `status` in `pending | accepted | cancelled |
  expired` (`models/agent_transfer_models.py:69`).

So the population of transferred agents is directly queryable.

### 6.2 F4 is worse than the research report stated

`[CODE]` The report said the cascade "cannot touch person data". The sharper fact is that the
cascade is **thorough about per-agent subcollections and still omits every person-keyed store.**
Collections handled across `agent_transfer_platform_ops.py` and `agent_transfer_service.py`:

`agents`, `projects`, `organizations`, `memberships`, `knowledge_library`, `agent_senders`,
`share_tokens`, `api_keys`, `mcp_configs`, `agent_subscriptions`, `agent_deployments`,
**`agent_sessions`**, `usage` / `usage_archive`, `analytics` / `analytics_archive`,
`agent_transfer_invites`, `user_profiles` — **16 collections.**

Omitted: **`agent_datastores`**, **`agent_user_memory`**, **`lead_contacts`**, **`lead_profiles`**,
**`agent_users`**. `agent_datastores` returns **zero hits in the entire studio-backend repository**.

`[INFERENCE]` The cascade handles `agent_sessions` — conversation data — while omitting every
store that holds who the conversation was *with*. This is not an oversight about subcollections
in general; it is specifically the person plane that no transfer author considered. That is the
signature of the report's core thesis: person identity is unowned, so it is absent from the
checklists of people who thought carefully about everything else.

### 6.3 Consequence for QF-4 / S7

`[INFERENCE]` After a transfer, an agent belongs to the target organization while its person
rows' table headers still carry the **origin** organization's id. The agent still reads them
(addressing is by `agent_id` path, not by org), but any org-scoped query mis-attributes them.

This matters beyond identity: **QF-4 / S7 plans to stamp `organization_id`, backfill, then tighten
rules on that field.** For transferred agents the field is already present and already wrong, so a
backfill that skips non-null values would preserve the error and the subsequent rules tightening
would mis-scope exactly those tenants. **This should be raised with the S7 owner** — it is a
concrete, testable interaction between two otherwise unrelated workstreams.

### 6.4 Executable specification

1. `activities` where `activity_type == 'agent_transferred'` → set of transferred `agent_id`s,
   with origin and target org from the activity payload.
2. For each, read `agents/{id}.organization_id` (current) and compare with every
   `agent_datastores/{agent_id}/tables/*.organization_id` (header).
3. **Mismatch count is the stale-tenancy population.** Repeat for `agent_user_memory`
   (`organization_id` is on the document — `routers/agent_memory.py:73` relies on it) and
   `lead_profiles`.
4. Cross-check: `agent_transfer_invites` with `status == 'accepted'` should reconcile with (1).

**The `agent_user_memory` case largely self-heals — verified** `[CODE]`. Its `organization_id`
is load-bearing for **authorization** (§8), not merely for reporting, so a stale value would deny
the current owner their own data with a 404. But both durable write paths
(`services/agent_memory_service.py:398-405` and `:467-475`) include
`"organization_id": organization_id` in the payload written **on every durable write**, taken
from the live request context — not only at creation. So the first turn after a transfer that
produces a memory change re-stamps the field correctly.

`[INFERENCE]` The residue is therefore narrower than first thought, and precisely shaped: the
stale stamp persists only for **persons who never interact with the agent again**, whose memory
becomes permanently unreadable to the new owning organization. It also persists for persons who
do return but say nothing new, since both paths `return None` when there is no durable change
(`:394-396`, `:462-465`). Failure direction remains privacy-safe — it denies rather than leaks.
`agent_datastores` has no equivalent self-healing, because its `organization_id` lives on the
table header rather than on the row, and nothing re-derives it from the agent's current org.

---

## 7. Hash-divergence history (N7)

**Status: `[CODE]` — fully answered. The hypothesis is false.**

### 7.1 Complete history of both implementations

| Implementation | Commits touching the digest | Date | Expression |
|---|---|---|---|
| `memory_doc_id` (`agent-runtime`) | `7481c61` — *"feat(memory): agent_memory_service — doc id, load, prompt block"* | **2026-06-13** | `hashlib.sha256(user_key.strip().lower().encode("utf-8")).hexdigest()[:32]` |
| `person_hash` (born in `agent-runtime`) | `5641e59` — *"feat(extract): the extractor writes data store entries, not a per-person document (#518)"* | **2026-09-12** | `hashlib.sha256(user_key.strip().lower().encode("utf-8")).hexdigest()[:32]` |
| `person_hash` (moved to shared) | `5d63d5c` (#520, agent-runtime side) / `5bcd688` (#119, olbrain-shared side) | **2026-09-12** | unchanged |

Method: `git log -S` pickaxe on the digest expression across all refs in both repositories, plus
`git log --follow` on both files. `[CODE]`

### 7.2 Result

- `git log -S "hexdigest()[:32]" --follow -- services/agent_memory_service.py` returns **exactly
  one commit** — the digest line has never been modified since 2026-06-13.
- `git log --follow -- src/olbrain_shared/agent/datastore/columns.py` in `olbrain-shared` returns
  **exactly one commit** (`5bcd688`, 2026-09-12) — `person_hash` has never been modified since
  landing there.
- The expression at `person_hash`'s first appearance (`5641e59`) is **byte-identical** to
  `memory_doc_id`'s, including argument order (`.strip().lower()`), encoding and truncation.
- The shared move happened the **same day** as the local introduction, so no window exists in
  which two *different* `person_hash` bodies were deployed.

**Conclusion `[CODE]`: the two implementations have never diverged. No deployment window could
have produced unreachable `agent_user_memory` documents by this mechanism. N7's hypothesised
divergence did not occur.**

### 7.3 What remains true

`[INFERENCE]` The risk is **latent, not historical**. The two remain textually independent — one
in a versioned shared library, one inline — with nothing (no test, no import, no shared constant)
that would fail if a future change touched one only. N7 should be reworded from *"may already
have diverged"* to *"is unguarded against diverging"*, and the cheap mitigation is a single test
asserting `memory_doc_id(a, k).endswith(person_hash(k))`. That is a code change and is **not made
here**.

### 7.4 Residual `[UNMEASURED]`

Whether any *data* anomaly exists that a divergence would have caused — orphaned
`agent_user_memory` documents whose digest half matches no `agent_datastores` entry — is not
checkable without access. Given 7.2 it should be empty; a non-empty result would indicate a
different cause and would be a genuine new finding.

---

## 8. Identity → authorization coupling (F8)

**Status: `[CODE]` — F8's present-day analogue does not exist. This corrects my prior report.**

### 8.1 Broad search

`[CODE]` Across all ten repositories at the pinned commits, no occurrence of `person_hash`,
`user_key` or `memory_doc_id` appears on a line also involving `auth`, `permission`, `allow`,
`denied`, `forbid`, `can_`, `is_owner`, `member`, `visib` or `scope_owner`. Zero hits.

**This is a measured zero, not a broken pipeline.** The same command with the authorization
filter removed returns **52** identity hits in `olbrain-agent-runtime 8df0e02` alone, and the
authorization vocabulary itself returns **364** hits in that repository's Python. Both halves of
the intersection are well populated; the intersection is empty. (A silently-empty search is the
error this investigation already made once, in the research report's §2.5, so the control was run
deliberately.)

### 8.2 Targeted inspection of the person-data HTTP surface

The broad search only proves absence of textual co-location, so the actual gate was read.
`olbrain-agent-runtime 8df0e02:routers/agent_memory.py`:

```python
@router.get("/agents/{agent_id}/user-memory/{channel_user_id}")
async def get_user_memory(agent_id, channel_user_id, request,
                          api_key_id: str = Depends(get_api_key_id)):
    if not api_key_id:
        raise HTTPException(status_code=401, detail="API key required")
    caller_org = _caller_org(request)
    memory = agent_memory_service.load_memory_doc(_get_db(), agent_id, channel_user_id)
    if memory is None or memory.get("organization_id") != caller_org:
        raise HTTPException(status_code=404, detail="No memory for this user")
```

and `_caller_org` (`:33-46`):

```python
org = getattr(request.state, "organization_id", None)
if not org:
    raise HTTPException(status_code=404, detail="No memory for this user")
```

**Three independent gates**, none of which is the identity value: an API key must be present; the
key must carry an org context; and the document's `organization_id` must equal that org. The
person identifier is the **addressing** input only.

The docstring states the design intent explicitly: *"a caller without an org context … or whose
org doesn't match the doc's gets 404 — never 403 — so existence is not confirmed across
tenants."* `[CODE]` The same posture is applied to the lead-profile and lead-contact routes
(`:197-280`, each passing `expected_organization_id=_caller_org(request)`).

### 8.3 Classification, as the task asks

| Use of identity | Where | Verdict |
|---|---|---|
| **Direct authorization** | none found | **F8 not realized** `[CODE]` |
| **Indirect addressing** | `person_hash` / `memory_doc_id` computing a document id | pervasive, and benign given 8.2 `[CODE]` |
| **Merely retrieving data** | prompt-read path (`cs_packet_builder`), `person_records.py` | in-process, after the agent is already authorized `[CODE]` |
| **Operator/admin tools** | agent-design `datastore_service.py:384` (operator supplies raw `user_key`) | operator is separately authenticated; identity is the row address, not the permission `[CODE]` |

### 8.4 Correction to the research report

`[CODE]` `person-identity-architecture-research.md` §6, under *"Where identity is implicitly an
authorization boundary"*, concludes that *"the identifier is simultaneously the locator and, in
effect, the capability."* **It is the capability framing that is withdrawn.**

To be precise about what was and was not wrong. That paragraph did **not** claim the operator
path is unauthenticated, and this pass's §8.3 classifies it the same way the original evidence
does — `datastore_service.py:378-390` is an authenticated admin surface where the identifier is
the row address, not the permission. What the paragraph got wrong is the inference drawn from
that: it treated "the identifier locates the row in every store" as equivalent to "the identifier
grants access to the row". §8.2 shows it does not. Possession of a `user_key` computes an
address; every reachable surface additionally requires an authenticated principal and an org
match.

§7.6 of that report should be read as describing a *structural* hazard — that a value derived from
a guessable secret is used as a locator — rather than a present-day authorization bypass. The
correction does not remove the privacy findings in §7.1/§7.2 of that report (cross-tenant
linkability and guessability of the digest), which are independent of authorization and still
stand.

`[INFERENCE]` It does, however, weaken falsification attempt 2 in that report's §13.2 in a
*favourable* direction: OLBrain already demonstrates, three times in one file, the discipline of
keeping tenancy checks independent of the addressing key. F8 remains a real risk for a future
mapping table, but the codebase's existing habit is the right one rather than the feared one.

---

## 9. Additional identity mechanisms

Each assessed for whether it carries genuine identity semantics, not counted by string match.

### 9.1 `research_clients` — a complete entity-resolution model **(new, decisive)**

`[CODE]` `olbrain-research-design e211584:app/routers/org_research_clients.py`, at
`organizations/{org_id}/research_clients/{client_key}`:

```python
inherited = set(loser_doc.get("aliases") or []) | {loser}
merged = sorted(set((survivor_snap.to_dict() or {}).get("aliases") or []) | inherited)
if len(merged) > _MAX_ALIASES: raise HTTPException(400, ...)
survivor_ref.update({"aliases": merged, "updated_at": now, "updated_by": user.user_id})
loser_ref.update({"archived": True, "merged_into": survivor,
                  "updated_at": now, "updated_by": user.user_id})
```

**Identity semantics: yes, fully.** Many observed names (`aliases`) resolve to one canonical
entity (`client_key`); merge is operator-initiated and audited (`updated_by`); the non-survivor is
**archived, not deleted**, and carries a `merged_into` redirect; aliases are inherited so prior
references remain resolvable; the whole thing is org-scoped by path.

`[INFERENCE]` This is the research report's recommended shape, implemented. Its subject class is a
consulting firm's *client* (an organization), not an individual human, so it does not solve the
person problem — but it removes any doubt that the shape is viable or foreign to the codebase.
Notably, it chose **operator-initiated merge**, which is directly relevant to J5.

### 9.2 `member_identity` — the authenticated-principal axis

`[CODE]` `olbrain-research-runtime 6b81691:app/lifecycle/member_identity.py` resolves a Firebase
`uid` to a display name via `user_profiles/{uid}`, with a documented four-step fallback, recorded
onto a chat session at creation (`started_by_name` / `started_by_email`).

**Identity semantics: yes — but for a different subject class.** This is the *operator/member*
identity, not the end-user person. `[INFERENCE]` It confirms the research report's five-concept
separation (§3 of that report): OLBrain already keeps **authenticated principal** distinct from
**resolved subject**, and does so correctly. Nothing here needs changing; it matters because it
shows the platform can hold two identity axes without confusing them — which is the discipline the
person plane lacks.

### 9.3 Mechanisms assessed and found *not* to carry person-identity semantics

`[CODE]`

| Mechanism | Assessment |
|---|---|
| **Workflow memory** (`olbrain-workflow-runtime 1978f4a`) | Hits in `app/core/orchestrator.py`, `app/routers/exceptions.py` only. No person key; workflow state is run-scoped. **No person identity.** |
| **Knowledge-vault** (`66b02e2:services/tables/*`) | `normalize.py`, `ambiguity.py`, `verify.py` concern *table/column* entity disambiguation in extracted documents — entity resolution over document content, not people. **No person identity.** |
| **Research learned overlays** | Keyed by template/profile, not by person. **No person identity.** |
| **Session summaries** | Session-scoped; reference a person only implicitly through the session. **No independent person key** (consistent with the research report's "not traced" note, now confirmed). |
| **Context facts** (`agent-engine e43654e:alchemist/context/facts.py:28`) | Carries `superseded_by`; scoped by the `GLOBAL→ORG→PROJECT→AGENT→SESSION` ladder, which has **no person level**. Supersession of *facts*, not of identities. |

### 9.4 Revised inventory

`[CODE]` **Six identity mechanisms** now known, across two subject classes:

*End-user person (four, mutually unlinked):* `person_hash` · `memory_doc_id` ·
`lead_contact_doc_id` + `lead_people` · `agent_users`.

*Other subject classes (three, each with working resolution):* `organizations.merged_into` ·
`research_clients` aliases+merge · `member_identity` (principals).

`[INFERENCE]` The asymmetry is the finding. **Every entity class OLBrain models deliberately has
a working identity story. The one it converses with does not.**

---

## 10. Falsification of the proposed resolution-layer model

Using only evidence found in this pass. The research report's own §13.2 attempts are not repeated.

**Attempt A — "The shape is speculative over-engineering."**
**Falsified.** `[CODE]` Three in-house implementations exist (`organizations.merged_into`,
`research_clients` aliases+merge, `lead_people` union-find). `research_clients` matches the
proposal almost feature-for-feature. The proposal is the *least* novel option available.

**Attempt B — "Identity already leaks into authorization, so a mapping table will too."**
**Falsified as a present-day claim.** `[CODE]` §8 shows three independent gates that never consult
the identity value, and a documented 404-not-403 cross-tenant posture applied consistently across
four routes. The codebase's existing habit is the one the proposal requires. F8 remains a
*prospective* risk requiring structural enforcement — unchanged, but no longer evidenced by
current practice.

**Attempt C — "Merge would be built on evidence that doesn't exist."**
**Partly survives, and narrows.** `[CODE]` Co-occurrence evidence exists in exactly one store
(`lead_profiles`, §2.1) plus a weaker second source discovered here (same identifier on two
channels via `agent_users`, §4.3). The *rate* is `[UNMEASURED]`. If it is near zero the proposal
is defeated (§2.4) — this remains the live falsification and the reason the recommendation is
conditional.

**Attempt D — "Tenant-scoped identity cannot survive organization transfer."**
**Survives and is now empirically grounded.** `[CODE]` §6 shows the transfer cascade already
omits every person-keyed store, so transfer *already* breaks person tenancy today. A tenant-scoped
subject does not introduce this problem; it would make it **explicit and therefore fixable**,
because a transfer would have to decide what happens to subjects rather than silently leaving a
stale stamp. This inverts the objection: the current model hides the problem, the proposal surfaces
it. The *policy* (sever vs re-parent) remains J6.

**Attempt E — "Merge breaks Current State and Memory."**
**Unfalsified — and the strongest remaining objection.** `[CONTRACT]` Two active claims on one
predicate from formerly-separate subjects produce a `CONFLICT` the contract forbids resolving by
recency. Nothing found this pass addresses it. For Memory the problem is worse: Memory is
non-assertive, so a bad merge surfaces as confident recall of a stranger's details with no
conflict machinery to catch it. `[INFERENCE]` **`research_clients` does not help here** — merging
client *names* has no current-state semantics, so the one close precedent is silent on precisely
the hardest part.

**Attempt F — "Identity becomes an unavoidable runtime dependency."**
**Survives, cost now visible.** `[CODE]` `person_records.py` renders person rows into the system
prompt on every packet build via a direct computed `get`. Interposing resolution puts a lookup on
the hot path of every turn. `[INFERENCE]` Mitigable by caching — the resolution link is
low-cardinality and rarely changes — but it is a new availability coupling and the research
report's attempt 6 stands.

**Attempt G — "A simpler model satisfies the observed requirements."**
**Open, and sharpened.** `[INFERENCE]` If §2's measurement shows rare co-occurrence, then the
simpler model is: per-tenant keyed hash (privacy fixed), typed identifiers (§3.2's structural
fragmentation made honest), and **`agent_users` promoted to the person model** — since it is
already channel-typed, already stores raw identifiers, and already tolerates many endpoints per
agent. That is closer to a rename than a migration. **It deserves to be a named candidate rather
than a footnote**, and it is the main thing this pass would add to the research report's option
list.

**Net.** The proposal is more credible after this pass on shape (A), authorization (B) and
transfer (D); unchanged on runtime cost (F); and still conditional on co-occurrence (C). The
unresolved core is **E — merge versus Current State and Memory** — which no precedent addresses
and which is now the deepest open problem in the identity work.

---

## 11. What the evidence now says about J1

**J1 — does OLBrain need to recognise one human across channels? `[UNDECIDED]`. Not answered
here, and not answerable from code.**

What this pass establishes that bears on it:

1. `[CODE]` **The product currently cannot do it, by construction** — not by policy, not by
   accident of data quality. §3.2's ingress table forces one person per channel identifier type.
2. `[CODE]` **Nobody has decided it should not.** The write path's own comment anticipates *"a
   later dedup pass"*; `lead_people` was built specifically to defragment within one org. Both are
   evidence of felt need, from two independent authors.
3. `[CODE]` **Every other entity class got the capability.** Organizations, research clients and
   principals each have a working identity story. The omission for persons looks like an
   oversight, not a decision.
4. `[UNMEASURABLE]` **The cost of *not* doing it cannot currently be measured** (§3.1), because
   measuring fragmentation requires the resolution that is missing.
5. `[UNMEASURED]` **The opportunity is bounded by a rate nobody has computed** (§2).

`[INFERENCE]` Points 2 and 3 are the substantive new input: the question has never been *decided
against* — it has never been posed. Point 4 is the trap: a decision deferred for want of evidence
cannot be resolved by more investigation, because the evidence the system would need to produce is
exactly what it lacks. **J1 must be answered as a product question, and §2's measurement can only
size it, not settle it.**

**What would make J1 answerable with evidence rather than judgment:** the §2 co-occurrence rate
(sizes the addressable population), plus one thing not available anywhere in the platform — whether
customers *do* switch channels within one relationship. `[INFERENCE]` The nearest proxy is §3.4's
channel-overlap count in `agent_users`, which sees only identical identifiers across channels and
so undercounts. Nothing measures the WhatsApp-then-email customer. That is the real evidential gap
behind J1, and it is a gap in **instrumentation**, not in analysis.

---

## 12. What remains genuinely a human or product decision

Unchanged from the research report's J1–J6; this pass moves none of them and answers none on
Jay's behalf. Status after measurement:

| ID | Decision | Moved by this pass? |
|---|---|---|
| **J1** | Cross-channel recognition needed? | **Sharpened, not answered** (§11). Never posed, never declined. |
| **J2** | Contract: person-merge forbidden or unmodelled? | **No.** Pure contract reading. Still the likeliest way to overturn the proposal. |
| **J3** | Who owns person identity? | **Strengthened** — §9.4 shows every *other* entity class has an owner and a working model. |
| **J4** | Is an LLM-extracted person row an identity assertion? | **No movement.** `[CONTRACT]` still forbids `LLM_WRITE` on `IDENTITY_SECURITY`. |
| **J5** | Merge: operator-confirmed, automatic, or both? | **Informed** — `research_clients` chose **operator-initiated + audited** (§9.1). A live in-house precedent to accept or reject. |
| **J6** | Organization transfer: follow, sever, or block? | **Escalated** — §6.2 shows person data is already stranded on transfer, so this is a present bug, not only a future design question. |

---

## 13. Updated list of architecture questions

Carried forward from the research report, with this pass's status. **N-numbers match that
report; M-numbers are new here.**

| ID | Question | Status after this pass |
|---|---|---|
| N1 | Merge produces Current State conflicts | **Open, now the deepest problem** (§10 attempt E). No precedent addresses it. |
| N2 | Identity has no place in the five-object model | Open, unchanged `[CONTRACT]` |
| N3 | Subject/tenant lifecycle interaction | **Escalated to a present-tense bug** (§6.2) |
| N4 | Under-merge cost is unmeasured | **Reclassified `[UNMEASURABLE]`** as posed (§3.1) |
| N5 | Memory merge has no conflict machinery | **Open, and sharpened** — `research_clients` is silent here (§10 E) |
| N6 | Resolution as runtime dependency | Open; cost now located at `person_records.py` (§10 F) |
| N7 | Digest implementations may have diverged | **CLOSED — they never have** (§7). Reword to "unguarded against diverging" |
| **M1** | **S7 backfill will mis-scope transferred agents** | New (§6.3). A non-null-but-wrong `organization_id` survives a skip-if-present backfill. **Raise with the S7 owner.** |
| **M2** | **`agent_users` is a latent person model** | New (§10 G). Channel-typed, raw identifiers, many-per-agent. Promoting it may be the simpler architecture. |
| **M3** | **Nothing instruments channel switching** | New (§11). The evidence J1 needs is not collected anywhere. An instrumentation gap, not an analysis gap. |
| **M4** | **Stale `organization_id` on `agent_user_memory` denies access — but self-heals** | New (§6.4), **severity reduced on verification.** The field is load-bearing for authorization, but it is re-stamped on every durable write, so the residue is dormant persons only — those who never return, or return with nothing new to record. `agent_datastores` has no such self-healing. |

---

## 14. Should D4 remain reframed?

**Yes. `[INFERENCE]` The reframing is strengthened, and one of its supporting arguments is
withdrawn.**

Strengthened:

- `[CODE]` The count of identity mechanisms rose from four to six across two subject classes
  (§9.4), and the asymmetry — every entity class but the person has a working identity model — is
  a sharper statement of the problem than "four mechanisms disagree".
- `[CODE]` §3.1 establishes something stronger than "D4 asks the wrong question": OLBrain
  **cannot measure the problem D4 is a symptom of**, because measuring it requires the mechanism
  D4 declines to discuss. A primary-key choice cannot fix an unobservable system.
- `[CODE]` The proposal's shape is proven in-house three times (§9.1, §10 A).

Withdrawn:

- `[CODE]` §8.4 retracts the research report's claim that the identity value functions as a
  capability. It does not. That argument should no longer be used to justify the reframing; the
  privacy arguments (cross-tenant linkability, guessability) are independent and still stand.

Added:

- `[INFERENCE]` A candidate the research report did not name: **promote `agent_users`** (§10 G,
  M2). If co-occurrence proves rare, this may satisfy the observed requirements at far lower cost
  than a resolution layer, and it is closer to a rename than a migration. **D4's reframed question
  should explicitly include it** rather than presenting resolution-layer-vs-keyed-hash as the
  field.

**D4 should remain reframed as:** *what is a person in OLBrain, who owns that definition, and does
the product need to recognise one human across channels?* — with the addition that the answer
space now includes formalising the per-channel model honestly, not only building resolution.

---

## Compact status table

| Question | Evidence status | Answerable without Jay? | Why it matters |
|---|---|---|---|
| **§1 Co-occurrence rate** | `[UNMEASURED]` — needs Firestore; population and method fixed (§2.2) | **Yes, with data access** | The single threshold that confirms or defeats the resolution layer (§2.4) |
| **§2 Fragmentation per human** | `[UNMEASURABLE]` as posed — no ground truth for "one human" | **No — not by anyone** | The circularity *is* the finding: the problem is currently unobservable |
| **§2b Structural fragmentation** | `[CODE]` — proven, ceiling known | **Already answered** | One human = N channel identifier types, forced by ingress |
| **§3 Recovery join** | `[UNMEASURED]` counts; `[CODE]` validity + cardinality | **Yes, with data access** | Turns D3 from "all lost" into a measured residue |
| **§4 Session-row radius** | `[UNMEASURED]` counts; `[CODE]` never read as memory | **Yes, with data access** | Decides whether they migrate as conversation data (§5.3) |
| **§5 Transfer / stale tenancy** | `[UNMEASURED]` counts; `[CODE]` transfers are logged, 16 collections handled, all person stores omitted | **Yes, with data access** | Present-tense bug; collides with S7 (M1) |
| **§6 Hash divergence (N7)** | `[CODE]` — **CLOSED, never diverged** | **Already answered** | Removes a feared data-corruption class; leaves an unguarded seam |
| **§7 Identity→authorization (F8)** | `[CODE]` — **not realized**; three independent gates | **Already answered** | Corrects my prior report; shows the right discipline already exists |
| **§8 Additional mechanisms** | `[CODE]` — six mechanisms, two subject classes | **Already answered** | `research_clients` proves the proposed shape in-house |
| **§9 Merge vs Current State (N1/N5)** | `[CONTRACT]` + `[INFERENCE]` — unresolved | **No — contract + design** | Deepest open problem; no precedent addresses it |
| **J1 Cross-channel recognition** | `[UNDECIDED]` — never posed, never declined | **No — product decision** | Everything else hangs on it (§11) |
| **J2 Contract reading on merge** | `[UNDECIDED]` | **No — contract owner** | Reading A would invalidate the proposal |
| **J6 Transfer policy** | `[UNDECIDED]`; `[CODE]` shows a present bug | **No — tenancy policy** | Person data is stranded on transfer today |
| **M2 Promote `agent_users`?** | `[INFERENCE]` — new candidate | **Partly** — viability from code; desirability is J1 | May satisfy requirements far more cheaply |
| **M3 Channel-switch instrumentation** | `[CODE]` — nothing collects it | **Yes, to specify** | The evidence J1 needs is not being gathered |

---

**No implementation is recommended.** This pass produced no schema, no migration, no code change
and no decision. It closed two open questions from the research report (N7, F8), corrected one
claim in it (§8.4), escalated one to a present-tense bug (N3/§6.2), reclassified one as
unmeasurable (N4/§3.1), surfaced four new questions (M1–M4), and converted the five unmeasured
sections into runnable specifications with stated thresholds.

**The one thing to do next that needs no decision:** run §2.2's co-occurrence query. It is the
condition on which the research report's recommendation explicitly depends, the population and
method are fixed, and the thresholds are stated in advance so the result cannot be argued after
the fact.
