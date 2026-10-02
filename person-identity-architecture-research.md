# Person Identity — Architecture Research

Research date: 2026-09-25. Read-only investigation.
Filename chosen by this pass (the task named none): `investigation/person-identity-architecture-research.md`.

**Evidence base.** All repositories were fetched immediately before this pass. Every citation is
pinned to an explicit commit, never to `origin/main`, which moves:

`olbrain-agent-runtime 8df0e02` · `olbrain-agent-design 51ffe3b` · `olbrain-agent-engine e43654e` ·
`olbrain-shared 8a0f0b5` · `olbrain-studio 8cee761c` · `olbrain-studio-backend ca9724a` ·
`olbrain-research-design e211584` · `olbrain-research-runtime 6b81691` ·
`olbrain-knowledge-vault 66b02e2` · `olbrain-workflow-runtime 1978f4a`

**Epistemic labels used throughout.** `[CONTRACT]` the normative contract requires it ·
`[CODE]` verified in source at a named commit · `[PRIOR]` an earlier investigation document
proposed it · `[INFERENCE]` reasoning of this pass · `[UNDECIDED]` genuinely open.
Inference is never promoted to architecture without the label.

**Not done here:** no production code, no schema, no migration, no contract change, no
modification to the State Semantics Explorer or any existing investigation artifact.

---

## 1. Executive finding

**D4 is the wrong question, and answering it as posed would entrench the actual problem.**

D4 asks whether person identity should move to an opaque surrogate id with the hash retained as
a lookup index. That is a primary-key question. It presumes there is one person-identity
mechanism whose key is up for revision. **There is not.** There are four independent
person-identity mechanisms in production, built on three mutually incompatible normalisation
regimes, and they disagree about who is the same human. `[CODE]`

| # | Mechanism | Key construction | Scope embedded | Mergeable | Store |
|---|---|---|---|---|---|
| 1 | `person_hash` | `sha256(strip+lower(user_key))[:32]` | **none — global** | no | `agent_datastores` entries |
| 2 | `memory_doc_id` | `{agent_id}__{sha256(strip+lower(user_key))[:32]}` | agent | no | `agent_user_memory` |
| 3 | `lead_contact_doc_id` | `{org_id}__{sha256(normalised_contact)[:32]}` | org | **yes**, by design | `lead_contacts` / `lead_profiles` |
| 4 | `agent_users` | composite `(agent_id, channel, channel_user_id)`, unhashed | agent + channel | n/a | `agent_users` |

Three findings make this a domain problem rather than an encoding problem:

1. **The input to the key is a different kind of thing on every channel.** `[CODE]` WhatsApp
   passes a phone number, email passes an email address, Instagram passes a per-app IGSID, and
   web chat passes `None`. One human reaching the same agent on two channels becomes two
   permanently unrelated persons, with no mechanism anywhere to relate them.
2. **A persisted merge-and-redirect mechanism exists in production — for organizations, never
   for persons.** `[CODE]` `organizations.merged_into` carries a redirect pointer with chain
   resolution, selective child re-pointing and JSONL rollback snapshots
   (`olbrain-studio-backend ca9724a:scripts/merge_organizations.py`,
   `merge_billing_aggregates.py:11-22`); research clients merge by survivor designation
   (`olbrain-research-design e211584`). **No person-keyed store has any such field.** The only
   person-merge capability is `lead_people`'s read-time union-find, which is never persisted.
   The doctrine exists; it was simply never extended to the entity that needs it most.
3. **The normative contract has no object class for a person.** `[CONTRACT]` It models state
   *about* a person (the `CUSTOMER` scope) and it models resolution between *mentions* of
   things a person talks about (`SAME_AS`, `RESOLVES_TO`). It assigns the establishment of
   identity to an `IDENTITY_SYSTEM` under authority domain `IDENTITY_SECURITY` — a system that
   does not exist in any repository. `[CODE]`

**The larger problem D4 represents:** person identity in OLBrain is *unowned*. Every subsystem
that needed a person invented one, each reasoning locally and correctly, and no layer is
responsible for the question "is this the same human?" The contract presumes that question was
already answered upstream. Nothing answers it.

**What follows.** The recommendation in §13 is that OLBrain needs a **resolution layer** — a
persisted, org-scoped, non-authorizing mapping from channel-local observed identifiers to a
stable internal subject — and that the contract's `CUSTOMER` scope is that subject. This is not
a key format change. The key format is downstream of it and comparatively unimportant. §13 also
attempts to falsify this and records where it does not hold.

---

## 2. Current identity reality

### 2.1 The four mechanisms, verified

**(1) `person_hash`** — `olbrain-shared 8a0f0b5:src/olbrain_shared/agent/datastore/columns.py:35`

```python
def person_hash(user_key: str) -> str:
    """Deterministic entry id for a person-keyed (fill="extract") row.
    Hashed so a raw phone or email never appears in a document path;
    normalised so one person is one row. The digest half of
    agent_memory_service.memory_doc_id ..."""
    return hashlib.sha256(user_key.strip().lower().encode("utf-8")).hexdigest()[:32]
```

Unsalted, unkeyed, no tenant, no channel, no type tag. Consumed by `agent-runtime`
(`services/extract_entry_writer.py:61`, `core/cs_packet_builder.py:1938`) and `agent-design`
(`app/services/datastore_service.py:384`, `app/services/datastore_import.py:147,206`).

**(2) `memory_doc_id`** — `olbrain-agent-runtime 8df0e02:services/agent_memory_service.py:92-97`

```python
def memory_doc_id(agent_id: str, user_key: str) -> str:
    digest = hashlib.sha256(user_key.strip().lower().encode("utf-8")).hexdigest()[:32]
    return f"{agent_id}__{digest}"
```

**This is a second, inline implementation of the same digest — not an import.** `[CODE]` The
`person_hash` docstring calls itself "the digest half of `agent_memory_service.memory_doc_id`",
but the dependency is documentary, not mechanical. Changing `person_hash` in `olbrain-shared`
would leave `memory_doc_id` silently divergent, breaking the intended correspondence between
`agent_datastores` and `agent_user_memory` for every existing row with no error anywhere.

> **Correction to an existing artifact.** `investigation/senior-review-reconciliation.md` states
> in C7 and §4.1 fact 6 that "none vendors a copy". That is false as written and materially
> understates D2's blast radius. Recorded here; that document should be corrected when next
> touched.

**(3) `lead_contact_doc_id`** — `olbrain-agent-runtime 8df0e02:core/lead_contacts.py:410-419`

```python
def lead_contact_doc_id(org_id: str, contact: str) -> str:
    """{org_id}__{sha256(contact)[:32]} — the lead_profiles convention.
    Org embedded in the id keeps two orgs' customers sharing an email from
    ever colliding in one doc, with every lookup still a direct get."""
```

Org-scoped **deliberately, with the reasoning stated in source.** This is an in-production,
documented rejection of exactly the global-digest choice that `person_hash` makes.

**(4) `agent_users`** — `olbrain-agent-runtime 8df0e02:services/firebase_service.py:274-295`.
Composite key `(agent_id, channel, channel_user_id)`, queried rather than hashed. **The only
mechanism that records which channel an identifier came from**, and therefore the only one that
does not implicitly assert that identifiers from different channels are comparable.

### 2.2 Three normalisation regimes, and they disagree

Normalisation *is* the identity decision — it defines which distinct inputs are one person.

| Regime | Phone handling | Email handling | Verdict on "+91 98765-43210" vs "919876543210" |
|---|---|---|---|
| `person_hash` / `memory_doc_id` | **none** — `strip().lower()` only | casing only | **two different people** |
| `lead_contacts` | digits-only extraction (`normalise_contact_phone`, `core/lead_contacts.py:180-202`) | `normalise_contact_email` | **one person** |
| `agent_users` | none — raw `channel_user_id` per channel | n/a | two, but honestly labelled by channel |

`lead_contacts` also deliberately *under*-merges, and says why —
`olbrain-agent-runtime 8df0e02:core/lead_contacts.py:181-188`:

> *"True E.164 needs a country context a voice transcript does not carry, so the key is simply
> every digit in order … '98765 43210' is a distinct national form and keys separately — **exact
> match beats clever match where a wrong merge reads a stranger's history to the caller.**"*

That sentence is the best statement of the real safety property anywhere in the codebase, and
`person_hash` does not implement it.

### 2.3 The identity ingress is channel-local and untyped

`[CODE]` What becomes `user_key`, and therefore `person_hash(user_key)`, per channel:

| Channel | Source of `user_id` | Site (`olbrain-agent-runtime 8df0e02`) |
|---|---|---|
| WhatsApp | `from_number` (phone) | `routers/meta_whatsapp.py:965` |
| Email | `from_email` | `routers/email.py:311` |
| Instagram | `sender_igsid` (Meta per-app scoped id) | `routers/meta_instagram.py:314` |
| Directives / voice | `phone_number or session_id` | `routers/directives.py:215, 342` |
| Web chat | **`None`** | `routers/chat.py:224` |
| Webhook | `request_data.user_id or session_id` | `routers/agent_webhook.py:2632` |

The key carries no discriminator for which of these it is. `user_key_kind` is stored on the
entry but records only `"identity"` vs `"session"` — not phone vs email vs IGSID.

### 2.4 The anonymous path, and a read/write asymmetry

`olbrain-agent-runtime 8df0e02:core/lightweight_processor.py:3885-3894`:

```python
# ... Key them by session_id instead:
# one row per conversation rather than one per person. user_key_kind
# records which, so the UI can label the row honestly and a later
# dedup pass can find these.
user_key = (getattr(user_message, "user_id", None) or "").strip()
user_key_kind = "identity"
if not user_key:
    user_key = (user_message.session_id or "").strip()
    user_key_kind = "session"
```

Two things follow, both verified:

1. **Every anonymous conversation creates a new person, permanently.** The "later dedup pass"
   the comment anticipates does not exist in any repository. `[CODE]`
2. **Session-keyed person rows are write-only.** All three prompt-read paths
   (`core/cs_packet_builder.py:1875`, `:1921`, `:2017`) begin `user_key = message.user_id` and
   `return ""` when it is absent. **None falls back to `session_id`.** A row written under a
   session key can never be read back by the agent that wrote it. `[CODE]`

This is a concrete defect, independent of any target architecture, and it is recorded in §12.

### 2.5 What does not exist — and what does

Search surface for this subsection, stated precisely: `git grep -nE` over **all ten repositories
at the commits listed in the header, all file types**, excluding tests, `node_modules` and
Markdown. An earlier draft of this report claimed a ten-repo verification it had not performed;
the searches below were re-run to match the claim.

**Absent everywhere** `[CODE]`:

- **Any `IDENTITY_SYSTEM` / `IDENTITY_SECURITY` / identity service.** Zero hits in ten
  repositories. The authority domain the contract names as the only permitted writer of identity
  **has no implementation anywhere.**
- **Any `CUSTOMER` scope class.** The term appears five times in ten repositories and every
  occurrence is prose — a comment in
  `olbrain-studio 8cee761c:src/components/research/Reports/ReportsList.js:29`, prompt text in
  `leadPersonalizationPrompt.js`, and two comments in
  `olbrain-research-runtime 6b81691:app/lifecycle/{driver.py:503, phases.py:1259}`. **No scope
  class, no enum member, no partition key.**
- The only real scope implementation is the agent-engine Context Service
  (`olbrain-agent-engine e43654e:alchemist/context/scope.py:9-17`), whose ladder is
  `GLOBAL → ORG → PROJECT → AGENT → SESSION`. **There is no person or customer level.**

**Present — and this corrects the earlier draft's headline claim** `[CODE]`:

A persisted merge-and-redirect mechanism **does** exist in production. It has simply never been
applied to persons.

- **Organizations merge.** `olbrain-studio-backend ca9724a:scripts/merge_organizations.py`
  writes a `merged_into` pointer on the archived organization;
  `scripts/merge_billing_aggregates.py:11-22` resolves those pointers **including chains**
  (*"Discovery is generic (scans `organizations.merged_into` and resolves chains)"*). The merge
  re-stamps `organization_id` on projects, agents, subscriptions and workflow definitions, but
  **"INTENTIONALLY leaves historical billing data under the source orgs."** It is dry-run by
  default and snapshots every document to JSONL before any delete, for rollback.
- **Research clients merge.**
  `olbrain-research-design e211584:app/routers/org_research_clients.py:297` writes
  `"merged_into": survivor` — a survivor-designation merge on a customer-adjacent entity.
- **Context facts supersede.** `olbrain-agent-engine e43654e:alchemist/context/facts.py:28` and
  `facts_store.py:43` carry a `superseded_by` chain, already noted in prior investigation as the
  closest structural analog to the contract's Claim.
- Research plans and chat proposals carry `superseded_by_plan_id` / `superseded_by_message_id`
  (`olbrain-shared 8a0f0b5:src/olbrain_shared/research/firestore/`).

**Absent specifically for persons** `[CODE]`: no `alias`, `canonical_id`, `merged_into`,
`primary_person` or `same_as` field on any person-keyed store — `agent_datastores`,
`agent_user_memory`, `lead_contacts`, `lead_profiles` or `agent_users`. The only person-merge
capability anywhere is `lead_people`'s read-time union-find, which is never persisted.

**This is a materially better finding than "no alias field exists anywhere."** OLBrain has a
working, audited, rollback-capable entity-merge doctrine — persisted redirect pointer, chain
resolution, selective child re-pointing, history deliberately left in place. It was built for
organizations and never extended to the entity that needs it most. §8 and §13 treat it as the
in-house precedent it is.

---

## 3. Domain meaning of "person"

The question "what is a person in OLBrain?" has, in the current system, four different answers
depending on which subsystem is asked. Reconstructing the implied domain model from behaviour:

- **To `agent_datastores` / `agent_user_memory`:** a person is *a normalised contact string*.
  Identity is a pure function of one identifier. Two identifiers are two people, always.
- **To `lead_contacts` / `lead_people`:** a person is *an equivalence class over contact keys*,
  discovered from evidence (a profile carrying both an email and a phone proves those keys are
  one human), and explicitly provisional. `core/lead_people.py:28-32` states it outright:

  > *"`person_key` is a `lead_contacts` document id, **subject to merge**. It is NOT a permanent
  > identifier for a human. Two keys that have never yet co-occurred are two people as far as
  > this module can prove, and the day a profile arrives carrying both, they become one and the
  > root may change. **Anything storing a `person_key` must therefore be re-pointable.**"*

- **To `agent_users`:** a person is *a channel endpoint* — an address the agent can reach.
- **To the contract:** a person is *a scope* (`CUSTOMER`), i.e. a container for state and a unit
  of deletion, whose establishment is somebody else's job. `[CONTRACT]`

**These are not four wrong answers. They are answers to four different questions**, and the
system has never distinguished them. Naming the distinction is the main analytic contribution
of this section:

| Concept | Question it answers | Stability | Who should own it |
|---|---|---|---|
| **Channel endpoint** | "Where do I reach them?" | stable per channel, meaningless across | channel layer |
| **Observed identifier** | "What did they present?" | immutable observation | Evidence plane |
| **Resolved subject** | "Which human is this?" | revisable as evidence accrues | a resolution layer |
| **State scope** | "Where does their state live?" | must be stable for the life of the state | contract / `scope_id` |
| **Authenticated principal** | "Who are they *allowed to be*?" | security-owned | `IDENTITY_SECURITY` |

**The current system collapses all five into one 32-hex digest.** `[INFERENCE]` That collapse is
the root cause of D2, D3 and D4 alike: each is a symptom of a different one of the five
escaping.

The final row matters most. `[CONTRACT]` The contract is explicit that a conversation
*"cannot modify identity, role, authorization, tenant membership, or security policy"*
(architecture-contract.md:1219) and that `account_role` is writable only by `IDENTITY_SYSTEM`.
**Resolved subject and authenticated principal must never be the same object.** §7 shows what
happens when they are.

---

## 4. Identity invariants

Invariants a canonical person identity must satisfy, derived from the contract where it speaks
and from the failure modes in §12 where it does not.

**From the contract** `[CONTRACT]`:

- **I1.** A mutable current-state predicate resolves within exactly one authoritative state
  scope (§2). Therefore a person's state scope must be **single-valued at resolution time** — a
  person cannot be two scopes at once for the same predicate.
- **I2.** Deletion containment uses `scope_generation(scope_id)` per deletable scope class,
  including `CUSTOMER` (§12). Therefore person identity must be a **deletion unit**.
- **I3.** Scope hierarchy for deletion **MUST NOT** imply authorization inheritance. Stated
  twice. Therefore person identity must be **non-authorizing**.
- **I4.** `RESOLVES_TO` is mention → canonical entity, **non-authorizing**; cross-customer
  `SAME_AS` is forbidden; *"the canonical entity is a semantic anchor, not a privacy bridge"*
  (line 1300). Therefore **no identity link may widen visibility**.
- **I5.** `scope_id` is the frozen MVP partition key (§615). Therefore whatever identifies a
  person in the target **is** a `scope_id`, not a separate key competing with it.

**From observed failure modes** `[INFERENCE]`:

- **I6 — Revisability.** Resolution must be revisable without rewriting history. Evidence
  accrues; a correct system learns that two subjects are one. `lead_people` already asserts this.
- **I7 — Non-destructiveness.** Revision must not destroy the prior state. The contract's own
  precedent: *"A1 RESOLVES_TO iphone_17_pro → REVOKED. A1 and its evidence are untouched."*
  (line 1096). Merge must be reversible because merges are sometimes wrong.
- **I8 — Provability.** Identity must never be minted where it is not provable. `lead_people`
  implements exactly this and says why: *"Minting identity where none is provable either
  collapses back to per-call granularity or risks a wrong merge."*
- **I9 — Typed inputs.** An identifier must carry its kind. A phone, an email and an IGSID are
  not interchangeable inputs to one function, and §2.3 shows the current system treats them as if
  they were.
- **I10 — Tenant containment.** Two organizations' customers must not become comparable through
  the identity mechanism. `lead_contacts` satisfies this in its path; §7 shows `person_hash` does
  not satisfy it in its value.

**I3/I4 and I6/I7 together are the crux.** Identity must be *revisable* and *non-authorizing* at
the same time. Most naive designs achieve one at the cost of the other: a mutable canonical id
that things point at tends to become an implicit authorization edge; an immutable key that never
merges is safe but cannot represent a person.

---

## 5. Identity lifecycle semantics

Each case below states what the architecture **must guarantee**, and what the current system
actually does. "Not traced" means no mechanism was found and none is inferred.

| # | Lifecycle case | Must guarantee | Current behaviour |
|---|---|---|---|
| 1 | **New person** | A subject is created only from a provable identifier, typed and tenant-scoped | `person_hash(user_key)` minted on first write, untyped, global `[CODE]` |
| 2 | **Repeated interaction** | Same human on the same channel resolves to the same subject | Holds, **provided the channel emits a byte-identical identifier**. Format drift (e.g. `+91 98765 43210` vs `919876543210`) silently forks the person under `person_hash` `[CODE]` |
| 3 | **Same person, different user keys** | Resolvable to one subject as evidence permits | **Impossible.** Different channels → different digests → different persons, no alias table `[CODE]` |
| 4 | **User key change** (phone/email change) | Old key remains addressable; new key resolves to the same subject | **No mechanism.** New key = new person; prior memory is orphaned and unreachable `[CODE]` |
| 5 | **Anonymous → identified** | Session-scoped observations attach to the identified subject | **No mechanism**, and the session-keyed row is write-only (§2.4). The code comment anticipates a dedup pass that does not exist `[CODE]` |
| 6 | **Duplicate detection** | Candidate duplicates surfaced, not auto-merged | Only `lead_people`, read-time, within one org, never persisted `[CODE]` |
| 7 | **Identity merge** | Non-destructive, reversible, auditable, non-authorizing | `lead_people` union-find only — derived per request, not persisted, not audited, not applicable to `agent_datastores` or `agent_user_memory` `[CODE]` |
| 8 | **Identity split** | Prior merge reversible without data loss | **Not traced — no mechanism found.** Union-find is not invertible once inputs change |
| 9 | **Mistaken merge** | Detectable and recoverable; no cross-person leakage in the interim | **Not traced.** `lead_contacts:181-188` prevents some merges by under-merging, which is mitigation, not recovery |
| 10 | **Organization transfer** | Person state follows the agent or is severed, deliberately | Agent transfer reassigns `organization_id` on `agents/{id}`; `agent_datastores` entries carry no org (tenancy is on the table header) so person rows **silently follow the agent into the new org** `[CODE]` — see §12 F4 |
| 11 | **Agent transfer** | As above | Same path; same consequence |
| 12 | **Account deletion** | All state in the person's scope removed or classified | `agent_user_memory` has a delete path (`agent_memory_service.py:512-527`). No mechanism deletes *across* the four stores by person `[CODE]` |
| 13 | **Memory deletion** | Derived objects invalidated synchronously, excluded until recomputed `[CONTRACT]` | Firestore stores have no derived-object graph; not applicable yet |
| 14 | **Historical / audit retention** | Identity references in history remain resolvable after merge or deletion | **Not traced.** No history plane exists for person identity |
| 15 | **Re-registration** | Returning under a previously-deleted key behaves predictably | **Not traced.** Deterministic hashing means a re-registered key resurrects the *same* document id — so a deleted person's id is reused by whoever next presents that phone number `[INFERENCE, from determinism]` |
| 16 | **External identity references** | Stable outward-facing reference that is not a raw identifier | **Not traced.** Instagram IGSID is itself an external per-app id; no outward identity reference found |
| 17 | **Concurrent writes** | Single-writer-wins or explicit conflict | Extract writer uses two non-atomic `set(..., merge=True)` calls with exceptions swallowed; live tool uses an atomic batch `[CODE]` — different durability contracts on the same row |
| 18 | **Retries / idempotency** | Same observation twice = one effect | Deterministic key makes the *write* idempotent, but `created_at` is guarded explicitly because `merge=True` would otherwise erase first-seen time (`extract_entry_writer.py:94-97`) `[CODE]` |
| 19 | **Firestore → PostgreSQL migration** | Identity preserved or explicitly re-keyed with a mapping | See §9 |

**The pattern across cases 3, 4, 5, 7, 8, 9, 14, 15:** every case that requires identity to
*change over time* has no mechanism. The current design assumes identity is a pure, total,
immutable function of one string. Six of the nineteen lifecycle cases falsify that assumption.

---

## 6. Current-system dependency map

Who produces, consumes, persists and exposes identity.

```
CHANNEL INGRESS  (produces an observed identifier, typed only by which router ran)
  meta_whatsapp:965  from_number ──┐
  email:311          from_email  ──┤
  meta_instagram:314 sender_igsid──┤
  directives:215     phone|session─┤
  chat:224           None         ─┤
  agent_webhook:2632 user_id|sess ─┘
                                   │  AbstractMessage.user_id
                                   ▼
            ┌──────────────────────┴───────────────────────┐
            │                                              │
   lightweight_processor:3890                    cs_packet_builder:1875/1921/2017
   (WRITE) user_id ?? session_id                 (READ) user_id only — no fallback
   user_key_kind = identity|session                       │
            │                                              │
            ▼                                              ▼
   person_hash(user_key)                          person_hash(user_key)
   extract_entry_writer:61                        cs_packet_builder:1938
            │                                              │
            ▼                                              ▼
   agent_datastores/{agent}/tables/{table}/entries/{person_hash}
     • entry: NO organization_id
     • table header: organization_id  (both writers)
     • rendered into the system prompt every packet build
       (core/packet/person_records.py)
            ▲
            │  operator CRUD — requires raw user_key
   agent-design datastore_service:384, datastore_import:147,206

   memory_doc_id(agent_id, user_key)  ← INLINE DUPLICATE of the digest
   agent_memory_service:92 ──────────► agent_user_memory/{agent}__{digest}

   lead_contact_doc_id(org_id, contact) ─► lead_contacts/{org}__{digest}
                                            ▲ union-find at read time
                                            └ lead_people (derived, not persisted)

   (agent_id, channel, channel_user_id) ─► agent_users   (queried, unhashed)
```

**Systems that assume identity is immutable** `[CODE]`: `person_hash` and every caller;
`memory_doc_id`; the prompt-read path, which does a direct `get` by computed id; the operator
CRUD path; `datastore_import`'s dedup, which uses `person_hash` to detect duplicates.

**Systems that assume identity can change** `[CODE]`: `lead_people` alone — and it states the
requirement its neighbours violate: *"Anything storing a `person_key` must therefore be
re-pointable."* Nothing storing a `person_hash` is re-pointable.

**Where identity is implicitly an authorization boundary** `[CODE]`: possession of a raw
`user_key` is sufficient to write any person's row through the operator path
(`datastore_service.py:378-390`), and sufficient to compute any person's document id in every
store. The identifier is simultaneously the locator and, in effect, the capability. This is the
structure the contract forbids for canonical entities (I4) — see §7.

**Where identity and memory semantics couple** `[CODE]`: `person_records.py` renders a person's
datastore row into the system prompt unconditionally on every packet build. Identity resolution
therefore directly determines **what the model is told** — a wrong merge is not a reporting
error, it reads one person's attributes to another in-conversation. This is the highest-severity
coupling in the system and it is why `lead_contacts`' under-merging instinct is correct.

---

## 7. Security and privacy analysis

Claims below are traced to data flow, not asserted.

**7.1 The digest is cross-organization linkable.** `[CODE]` `person_hash` is
`sha256(strip+lower(key))` with no salt, no key and no tenant input. The *paths* are agent- or
org-scoped; the *value* is global. Two organizations holding a row for the same phone number hold
**the identical 32-hex string**. Anyone able to read both — a platform operator, an exported
dataset, a support dump, a future analytics join, or an attacker exploiting the `agents`
catch-all (§12 F5) — can join customer bases across tenants by equality alone. `lead_contacts`
avoids the *collision* problem by prefixing `org_id`, but its digest suffix is likewise
unsalted, so it does not avoid the *linkage* problem either.

**7.2 The input domain is enumerable, so the digest is testable.** `[CODE]` The inputs are phone
numbers and email addresses. Indian mobile numbers are roughly a 10^9 space; a full sweep is
minutes of commodity compute. `sha256` is deliberately fast. **A `person_hash` is therefore not
a pseudonym — it is an encoding of the phone number**, recoverable by anyone who obtains it.
The docstring's stated goal, *"so a raw phone or email never appears in a document path"*, is
achieved literally and not substantively.

**7.3 The shared digest is intentional, and that is the problem.** `[CODE]` `person_hash`'s
docstring names itself the digest half of `memory_doc_id`. The intent — one person, one identity,
across `agent_datastores` and `agent_user_memory` — is sound. The implementation makes the
digest a **global join key across every store and every tenant**, when what was wanted was a
join key *within one agent's data*.

**7.4 Hashing, HMAC, encryption and opaque ids solve different problems.** `[INFERENCE]`

| Mechanism | Prevents path PII | Resists guessing | Tenant-isolates | Rotatable | Reversible by owner |
|---|---|---|---|---|---|
| Plain `sha256` (current) | yes | **no** | **no** | **no** | no |
| HMAC, per-tenant key | yes | yes | yes | yes, with dual-read | no |
| Encryption (AEAD) | yes | yes | yes | yes | **yes** |
| Opaque random id + mapping | yes | yes | yes | **n/a — nothing to rotate** | via the mapping |

Deriving the identifier from the value — the shared property of rows 1–3 — is what forces the
rotation problem to exist at all. An opaque id has no rotation problem because it encodes
nothing. **This is the strongest single argument against every keyed-hash variant**, and it is
independent of the D4 framing.

**7.5 Rotation is currently impossible.** `[CODE]` Re-keying requires the original `user_key`.
The entry stores `user_key_kind` and never the raw key (`extract_entry_writer.py:87-93`). This
is D3, and it is a direct consequence of deriving the key from a value you then discard.

**7.6 Identity as an accidental authorization bridge.** `[CODE]` Three concrete routes:
(i) knowing a phone number yields the document id in every store, and the operator CRUD path
accepts a raw `user_key` to address any row; (ii) `person_records.py` renders a person's row into
the prompt by computed id, so anything that makes two humans share a digest makes the agent
disclose one to the other; (iii) `agents/{id}` remains readable and writable by any authenticated
platform user (`olbrain-studio 8cee761c:firestore.rules:836`, `agents` in neither exclusion
list), and org resolution flows through that document — so agent-document access is upstream of
person-data access.

**7.7 Identity references leak attributes.** `[CODE]` `user_key_kind` distinguishes
`"identity"` from `"session"`, and `channel` is stored on the entry. A reader who cannot read
values still learns that a person exists, which channel they used, and — by testing a guessed
phone number against the id — whether a *specific* human is a customer of a *specific* agent.
That is a membership disclosure independent of field-level protection.

**7.8 What is genuinely protected.** `[CODE]` `agent_datastores` is excluded from all four
Firestore catch-all lists — client access is fully denied. `agents/{id}/{sub}/**` excludes
`mcp_configs` from reads and `mcp_configs` + `owner_lessons` from writes
(`8cee761c:firestore.rules:1087-1090`). An org-level `pii_policy` gates every person-memory read
and write path (`cs_packet_builder.py:1878-1880` and siblings). The exposures above are not
browser-reachable; they are properties of the identifier itself and of server-side paths.

---

## 8. Merge and split analysis

**Does the target architecture need person-merge at all?** Taking the question seriously rather
than assuming yes.

**8.1 What the contract says.** `[CONTRACT]` The contract's resolution vocabulary operates on
**mentions**, not persons. Example 4 reads *"Customer A mentions: A1 'my 17 Pro', A2 'my
iPhone'"* — `A1` and `A2` are mention entities inside the `CUSTOMER:A` scope, resolving to a
`GLOBAL` product. `SAME_AS` is permitted within a scope and forbidden across. `RESOLVES_TO` is
non-authorizing. *"Entity destructive merges — Rejected in initial implementation."* Entity
resolution is listed as an **asynchronous** operation that *"improves future recall"* (line 719).

**8.2 The reading that matters.** Two readings are available and they differ materially:

- *Reading A — merge is forbidden.* If a person **is** a `CUSTOMER` scope, then "these two
  persons are one human" is a cross-scope `SAME_AS`, which is forbidden.
- *Reading B — merge is out of scope.* `SAME_AS` relates mentions, and persons are not mentions.
  The contract simply has no vocabulary for relating two customer scopes.

**Reading B is better supported.** `[INFERENCE]` The forbidden case in Example 4 is `A1 SAME_AS
B1` — two *mentions* owned by different customers, where the harm is explicitly privacy
(*"a semantic anchor, not a privacy bridge"*). Persons never appear as operands of `SAME_AS`
anywhere in the contract. And the contract assigns identity establishment to `IDENTITY_SYSTEM`
under `IDENTITY_SECURITY`, i.e. **outside** the state-semantics machinery entirely.

So: **the contract does not forbid person-merge. It declines to model it, because it assumes
identity is settled before state semantics begin.** `[UNDECIDED]` — this reading should be
confirmed by the contract owner, because Reading A would invalidate §13.

**8.3 Is merge desirable?** The strongest argument *against* is in the codebase:
*"exact match beats clever match where a wrong merge reads a stranger's history to the caller."*
Given §6's finding that person rows are rendered into the system prompt, a wrong merge is an
immediate in-conversation disclosure. Merge is not a reporting nicety; it is a privacy-critical
operation.

The argument *for* is that refusing merge does not make identity stable — it makes it **wrong in
the other direction**. §5 cases 3, 4 and 5 show the current system fragmenting one human into
arbitrarily many persons. Fragmentation is not safe; it is a different failure, in which the
agent forgets a returning customer and the memory investment is silently lost.

`[INFERENCE]` **Both over-merge and under-merge are harms, and they are not symmetric.**
Over-merge discloses one person's data to another — acute, privacy-critical, possibly
unrecoverable. Under-merge loses continuity — chronic, recoverable, non-disclosing. **An
architecture should therefore be biased toward under-merge and must make merge an explicit,
evidenced, reversible act, never an inference.** This is exactly `lead_people`'s posture, and it
should be generalised rather than replaced.

**8.4 Mechanism, if merge is supported.** `[INFERENCE]` Two precedents point the same way. The
contract's revocation pattern — *"A1 RESOLVES_TO iphone_17_pro → REVOKED. A1 and its evidence are
untouched."* — and, more concretely, **OLBrain's own organization-merge implementation**
(§2.5): a persisted `merged_into` redirect, chain resolution, selective re-pointing of children,
history deliberately left under the source entity, and a rollback snapshot before any delete.
That is a working, audited merge doctrine already running in production. Applied to persons:

- Observed identifiers are **immutable** records — an observation, never revised.
- A `RESOLVES_TO`-shaped link maps an observed identifier to a subject. The link is the mutable
  object; the observation is not.
- Merge = **re-point links**, never rewrite rows. Split = **revoke links** and re-point.
- Nothing stores the subject id in a way that cannot be re-pointed — `lead_people`'s rule.
- Because nothing is destroyed, a mistaken merge is recoverable by revoking the link, and the
  audit trail shows who merged on what evidence.

**8.5 What breaks.** `[INFERENCE]` Under merge, a claim made about subject S1 before the merge
was made under different knowledge. If S1 and S2 merge, do S1's claims become claims about the
merged subject? The contract's bitemporality (`t_valid`/`knowledge_cutoff`) can express "we
believed this when we thought these were two people", but **the merged subject's current-state
resolution could now surface a `CONFLICT` that did not exist before** — two active claims on one
predicate from two formerly-separate subjects. §6 of the contract forbids resolving that by
recency. **This is a genuine unsolved interaction and it is listed in §20 as a new question.**

---

## 9. Migration constraints

Concrete against the current data model. No fields invented.

**9.1 What an `agent_datastores` extract entry actually contains** `[CODE]`
(`extract_entry_writer.py:87-99`): `entry_id` (= `person_hash`), `last_session_id`,
`user_key_kind`, `channel`, `values`, `updated_at`, and `created_at` on first write only.
The parent table header carries `organization_id`; the entry does not.

**9.2 Re-keyable vs not.**

| Row class | Raw key recoverable? | Re-keyable? |
|---|---|---|
| Extract rows, `user_key_kind = "identity"` | **No** — never stored | Only if the raw identifier is recoverable from another store |
| Extract rows, `user_key_kind = "session"` | **Yes** — the key *is* the session id, and `last_session_id` is on the row | Yes, mechanically — but they key a conversation, not a person |
| `agent_user_memory` docs | No — `{agent_id}__{digest}` | No |
| `lead_contacts` | **Partially** — `lead_profiles` hold contact values | Plausibly yes; not traced in detail |
| `agent_users` | **Yes** — `channel_user_id` stored in the clear | Yes |

**9.3 The recovery path nobody has costed.** `agent_users` stores
`(agent_id, channel, channel_user_id)` **unhashed** `[CODE]`. The join is valid because
`channel_user_id` and `user_id` take **the same source variable on every channel** — verified
pairwise at `olbrain-agent-runtime 8df0e02`: `meta_whatsapp.py:888/965` (`from_number`),
`email.py:290/311` (`from_email`), `meta_instagram.py:296/314` (`sender_igsid`),
`directives.py:502/215` (`phone_number or session_id`). So `person_hash(channel_user_id)`
reconstructs exactly the `agent_datastores` entry id for that person.

**Coverage, verified** `[CODE]`: `upsert_agent_user` is called from `agent_webhook.py:2637`,
`directives.py:343` and `:499`, `email.py:287`, `meta_instagram.py:293` and
`meta_whatsapp.py:885` — **every channel that carries a real identifier**. It is *not* called
from `routers/chat.py`, the web-chat path that passes `user_id=None` and has no identifier to
recover. **Recovery therefore covers precisely the rows for which recovery is possible**, which
is the best available outcome rather than a gap.

**This is the single most valuable unexploited fact in the migration picture** and it materially
changes D3's answer: the set of permanently unrecoverable rows is not "all of them" but
approximately "the session-keyed ones", which §17.4 argues were never persons at all. Sizing the
join is §19's second task and needs no senior input.

**9.4 What is permanently lost regardless.** `[CODE]` Extract rows carry no `session_id` (only
`last_session_id`, a last-touch marker overwritten every turn), no message id and no extraction
run id. **Evidence lineage for historical extract rows is not reconstructible.** This is why
D1(a) was answered "migrate as un-provenanced Memory" — that decision is correct and this pass
does not disturb it.

**9.5 Mapping table, dual-read, addressability.** `[INFERENCE]` A mapping table is **required**,
not optional, under any target that changes the identifier — because the prompt-read path does a
direct `get` by computed id and would silently return nothing for every unmigrated person, which
presents as an agent that has forgotten every customer. Dual-read is therefore mandatory for the
migration window, and old ids must remain addressable until the read path is cut over.

**9.6 Operator-authored data.** `[CODE]` The operator path computes `person_hash(user_key)` from
a raw key the operator supplies, so operators *hold* raw keys outside the system. Migration must
not assume the stored corpus is the only source of identifiers. D1(b)'s "operator wins" rule
means operator-touched rows carry the higher authority and **must not be silently re-keyed into a
merged subject** without the authority marker surviving.

**9.7 Identity freeze.** `[INFERENCE]` Because `person_hash` is deterministic, a migration that
runs while writes continue will have new rows appearing under old keys behind the migrator.
Either the write path emits both keys during the window, or a short freeze is required. **Not
decided here.**

**9.8 Deletion during migration.** `[CONTRACT]` §12 requires generation-based rejection of work
whose scope changed before commit. A person deleted mid-migration must not be re-materialised by
an in-flight migration worker. The current Firestore stores have no `scope_generation`, so this
protection **does not exist today** and must be built as part of migration rather than assumed.

---

## 10. Candidate architectures discovered

Not constrained to the two D4 names. Six were found; four are serious.

**A — Status quo: global unsalted digest.** Keep `person_hash`.
*Only merit:* zero migration. *Disqualifying:* §7.1/7.2 — the identifier is a recoverable
encoding of a phone number and a cross-tenant join key. It also cannot express §5's six
change-over-time cases. **Not viable.**

**B — Per-tenant keyed hash (HMAC).** `HMAC(tenant_key, normalised_identifier)`.
Fixes linkage and guessing. Rotation becomes possible but expensive (dual-key window; §9.2 shows
the raw key is mostly unrecoverable, so rotation may be *impossible* for much of the corpus).
Still derives identity from value, so it **still cannot merge** — two identifiers remain two
subjects forever. *Fixes privacy, leaves the domain problem untouched.*

**C — Opaque surrogate subject id + persisted identifier mapping.** A random `subject_id`;
a separate table mapping (tenant, identifier_type, normalised_identifier) → subject_id.
Merge = re-point mappings. Split = revoke. Nothing to rotate. Satisfies I1–I10.
*Costs:* an indirection on every read; a mapping table that becomes critical infrastructure;
migration needs §9.3's recovery join.

**D — Event-sourced identity: immutable observations + revisable resolution links.**
C, plus the observation itself is a first-class immutable record and the mapping is a
*claim* about it, with provenance, authority and revocation — exactly the contract's
Evidence → Claim → Current State shape applied to identity. Merge history is auditable by
construction; mistaken merges are revocable with lineage intact.
*Costs:* the most machinery; resolution becomes a query rather than a lookup.

**E — No canonical person at all: channel endpoints only.** Formalise `agent_users`' model;
memory is per-endpoint; never claim two endpoints are one human.
*Merit:* maximal privacy, zero merge risk, honest about what is provable, and it is nearly what
`person_hash` accidentally implements today. *Cost:* the product loses cross-channel continuity
permanently, which is very likely a business non-starter — but it deserves naming because it is
the only option with **no** wrong-merge failure mode.

**F — Derived resolution, never persisted.** Generalise `lead_people`'s union-find across stores;
compute the equivalence class at read time.
*Merit:* no migration of identity, no stale merge state. *Disqualifying at scale:* union-find
over a full corpus per request is not a bounded operation, the result is unstable between reads
(the same query can return different groupings as data arrives), and §6's prompt coupling means
an unstable grouping is an unstable disclosure boundary. **Viable only at `lead_people`'s current
scale, which is one org's list endpoint.**

---

## 11. Tradeoff analysis

Conditions under which each option is or is not valid. No scorecard.

**B is valid if and only if** the product accepts that a person is permanently one identifier.
That is a *domain* commitment, not a technical one: it means WhatsApp-you and email-you are two
customers forever, by policy. If the business can say that plainly, B is cheap, safe and
defensible — and the current fragmentation stops being a bug and becomes the specification.
**B is invalid the moment anyone wants cross-channel continuity**, because no amount of key
cleverness merges derived keys.

**C is valid if** merge is needed and the mapping table can be made a first-class, tenant-scoped,
audited store. **C becomes dangerous if** the mapping is treated as a convenience rather than
security-critical: a table that says "these identifiers are one person" is precisely the
authorization bridge I4 forbids if anything consults it for visibility. The mitigation is
structural — the mapping resolves *addressing* only and must never appear in an authorization
decision — and it must be enforced, not documented.

**D is valid if** OLBrain expects merges to be contested, audited or regulator-visible, and if
the team is already building the Evidence/Claim machinery for everything else — in which case
identity is one more predicate family and D costs less than it appears. **D is over-built if**
identity changes are rare and operator-driven; then C's mapping with an audit log is
indistinguishable in practice at a fraction of the cost.

**E is valid if** the product's value does not depend on recognising a returning human across
channels. **Not traced:** whether it does. This is a product question, not an architecture one,
and §18 asks it — because if the answer is "it does not", options C and D are unnecessary and the
correct move is to make B's fragmentation explicit and honest.

**F is valid only** as a read-time convenience inside a bounded list view, which is what it is.

**On performance and interoperability** `[INFERENCE]`: C and D add an indirection to the person
read path, which today is a single direct `get` computed in-process. Under PostgreSQL this
becomes a join on an indexed unique key — not a concern at any plausible scale. Cross-service
interoperability *improves* under C and D, because services exchange an opaque `subject_id`
rather than each recomputing a digest from a raw identifier they must therefore possess. Under
A and B, every consuming service must hold the raw phone number to address the person — which is
itself the privacy problem.

**On the five-object target model** `[INFERENCE]`: A, B and E leave identity outside the model
entirely. C places it beside the model as infrastructure. **D places it inside** — identity
becomes Evidence (the observation), Claim (the resolution assertion, with authority and
provenance) and Current State (the resolved subject). D is the only option that does not require
a second, parallel truth mechanism for identity. That is a strong argument, and it is the main
reason §13 lands where it does.

---

## 12. Failure modes

Verified defects and structural failure modes. F1–F4 are `[CODE]`; F6–F8 are `[INFERENCE]`.

**F1 — Session-keyed person rows are write-only.** The write path falls back to `session_id`;
all three read paths require `user_id` and return `""` without it. Every anonymous conversation
writes a person row the agent can never read. `core/lightweight_processor.py:3890-3894` vs
`core/cs_packet_builder.py:1875, 1921, 2017`. **Severity: silent, permanent data
accumulation with zero product value.**

**F2 — The digest has two independent implementations.** `person_hash`
(`olbrain-shared 8a0f0b5:columns.py:35`) and `memory_doc_id`
(`agent-runtime 8df0e02:agent_memory_service.py:92-97`). Changing one silently desynchronises
the two stores for every existing person. **Severity: a latent trap directly in D2's path.**

**F3 — Format drift forks a person.** `person_hash` applies no phone normalisation. Any channel
or operator supplying the same number in a different format creates a second person.
`lead_contacts` normalises; `person_hash` does not. **Severity: silent memory loss.**

**F4 — An organization transfer leaves person data stamped with the wrong tenant.**
**Resolved this pass** `[CODE]`. `agent_datastores` entries carry no `organization_id`; tenancy
lives on the table header, written by both writers. The transfer/relocation cascade lives in
`olbrain-studio-backend ca9724a` (`services/agent_relocation_service.py`,
`services/agent_transfer_platform_ops.py`) and re-stamps `organization_id` across agents,
projects, memberships and knowledge. **`agent_datastores` does not appear anywhere in
studio-backend at `ca9724a` — zero hits in the entire repository.**

So the cascade cannot and does not touch person data. After a transfer the agent belongs to the
target organization while **its person rows' table headers still carry the origin organization's
id**. This is not a cross-tenant *leak* — the data does not move into the new tenant — it is a
tenancy *inconsistency*: the agent still reads the rows (it addresses them by `agent_id` path,
not by org), while any organization-scoped query attributes them to an organization that no
longer owns the agent.

**Severity: the `organization_id` on person data is not a reliable tenancy predicate**, which
bears directly on QF-4 / S7, whose whole purpose is to make org-scoped rules enforceable. A
backfill that stamps and then tightens rules on the basis of this field will mis-scope every
transferred agent's person data.

**F5 — Agent-document access is upstream of person-data access.** `agents` is in neither
exclusion list of the top-level catch-all (`olbrain-studio 8cee761c:firestore.rules:836`), and
organization resolution flows through that document.

**F6 — Deterministic ids resurrect deleted people.** Delete a person, then let the same phone
number present again: the id is recomputed identically and the new row inherits the deleted
person's address. If any downstream reference survived deletion, it now points at a different
human.

**F7 — Merge creates conflicts that did not exist.** Two formerly-separate subjects each with an
active claim on one predicate produce a `CONFLICT` on merge, which §6 of the contract forbids
resolving by recency. Unaddressed in every candidate. See §20.

**F8 — The mapping table becomes an authorization oracle.** Under C or D, a table asserting that
two identifiers are one person is a disclosure primitive. If any code path consults it to widen
visibility, I4 is violated and the "semantic anchor, not a privacy bridge" rule is broken by
infrastructure rather than by a claim.

---

## 13. Recommended target model — and an attempt to falsify it

### 13.1 The recommendation

`[INFERENCE]` — this is a research recommendation, not an architecture decision, and §18 lists
what must be decided by a human before it becomes one.

**Person identity should mean: a tenant-scoped, opaque, non-authorizing *subject* that
observed identifiers resolve to, where the resolution is revisable evidence and the subject is
the contract's `CUSTOMER` scope.**

Concretely — **option C as the MVP shape, structured so that it is the first increment of D**:

1. **Observed identifier** — an immutable record of what a channel presented: `(tenant, channel,
   identifier_type, raw_or_protected_value, observed_at)`. `identifier_type` is mandatory,
   fixing I9 and §2.3.
2. **Subject** — an opaque, random id. It encodes nothing, so it never needs rotation (§7.4).
   **The subject id is the `CUSTOMER` scope_id**, which the contract already froze as the
   partition key (I5). Identity does not compete with `scope_id`; it *is* `scope_id`.
3. **Resolution link** — observed identifier → subject. Mutable, versioned, with provenance and
   an authority domain. Merge re-points links; split revokes them. Nothing else stores anything
   re-pointable, satisfying `lead_people`'s rule.
4. **Resolution is evidenced, never inferred.** Automatic merge only on co-occurrence proof of
   the kind `lead_people` already requires; everything weaker is a *candidate* surfaced for human
   confirmation. Bias to under-merge (§8.3).
5. **Non-authorizing, structurally.** The resolution table answers addressing questions only.
   Authorization continues to derive from grants, per I3/I4.
6. **Normalisation is `lead_contacts`', not `person_hash`'s** — typed per identifier kind,
   deliberately conservative, with the rationale already written in source.

**Why this rather than the alternatives.** It is the only shape that satisfies I1–I10
simultaneously; it makes rotation a non-problem rather than a hard problem; and it is the only
option that does not require a second truth mechanism beside the five-object model. It is also
**the least novel option available**: it generalises `lead_contacts`/`lead_people`'s identity
doctrine and reuses the merge mechanics OLBrain already runs for organizations (§2.5) —
persisted redirect, chain resolution, history left in place, rollback snapshot. Very little here
has to be invented; it has to be applied to persons.

**Why not D outright.** D is better, and it is where this should end up. It is not the right
*first* increment: it requires the Evidence/Claim machinery to exist first, and identity would
become the riskiest possible pilot for it. C's tables are D's tables with a thinner claim model,
so C does not have to be unbuilt to reach D.

### 13.2 Falsification attempts

**Attempt 1 — "Merge is forbidden, so this is illegal."** If §8.2's Reading A is right — persons
are `CUSTOMER` scopes, person-merge is a cross-scope `SAME_AS`, forbidden — the recommendation is
dead as written. *Defence:* `SAME_AS` demonstrably relates mentions; persons never appear as its
operands; the forbidden case's stated harm is cross-customer privacy, which re-pointing links
within one tenant does not create. *This defence is not conclusive.* **Recorded as the single
question most likely to overturn §13, and asked in §18.**

**Attempt 2 — "The mapping table is the authorization bridge you warned about."** F8 is a real
objection to my own recommendation. *Defence:* it is a containable one — the table is
tenant-partitioned and never consulted in an authorization path. *But that is a discipline, not a
structure*, and disciplines decay. A structural enforcement mechanism is **not designed here**
and is a genuine weakness of the recommendation.

**Attempt 3 — "Under-merge bias makes it useless."** If the bar for merging is co-occurrence
proof, and channels rarely produce co-occurrence, the system merges almost nothing and delivers
little more than option B at much higher cost. *This objection largely holds.* Its force depends
entirely on how often real traffic yields co-occurrence — **unmeasured**, and §19 proposes
measuring it before committing. If co-occurrence is rare, **option B plus an explicit product
statement that identity is per-channel is the better architecture**, and I would recommend it.

**Attempt 4 — "Deletion breaks it."** A person deletes their account; the subject is deleted; the
observed identifiers remain and the same human returns. *Defence:* observations are tenant-scoped
records subject to the same deletion; F6's resurrection problem is *better* here than under A/B
because a new random subject is minted rather than the old address being silently reused.
**Holds.**

**Attempt 5 — "Organization transfer breaks it."** If subjects are tenant-scoped and an agent
moves between organizations, its person data belongs to subjects in the origin tenant. Either the
data is severed or subjects are re-parented — and re-parenting a subject into another tenant is
exactly the cross-tenant identity event that I10 exists to prevent. **This is not solved by the
recommendation, and F4 shows it is not solved today either.** Listed in §20.

**Attempt 6 — "It makes the prompt path slower and more fragile."** Today it is one computed
`get`; under C it is a lookup then a fetch, and a resolution-table outage means the agent forgets
everyone. *Defence:* the join is trivial in PostgreSQL and cacheable. *But* the failure mode is
real and new: identity becomes a runtime dependency of every packet build. Mitigations exist and
are **not designed here**.

**Net.** The recommendation survives attempts 1, 4 and 6 with caveats; is materially weakened by
attempt 2 (needs structural enforcement) and attempt 5 (unsolved); and is **conditionally
defeated by attempt 3** if co-occurrence proves rare. The recommendation is therefore **conditional
on the §19 measurement**, and that condition is stated rather than hidden.

---

## 14. Consequences for the PostgreSQL schema

`[INFERENCE]` Shape only. **No schema is written here**, per the standing instruction.

- The person's identifier in person-keyed tables becomes the **subject id, which is the
  `CUSTOMER` `scope_id`** — the contract's already-frozen partition key. There is no separate
  "person primary key" decision to take; D4's premise dissolves.
- Two new table families are implied: observed identifiers (immutable) and resolution links
  (mutable, versioned, provenanced). Under option D these are Evidence and Claim rather than
  bespoke tables.
- Uniqueness belongs on `(tenant, identifier_type, normalised_value)` in the resolution layer —
  **not** on the person row, which must tolerate many identifiers per subject.
- **D1(b)'s per-field authority marker** (writer + timestamp, from the answered D1) is orthogonal
  to identity and must be carried on the value row regardless of which identity option is chosen.
- Nothing may store a subject id in a form that cannot be re-pointed. Foreign keys to the subject
  are fine; **denormalised copies of it into wide rows are not**, and that is a schema-review rule
  rather than a constraint.
- `scope_generation` must exist per `CUSTOMER` scope for §12 deletion protection. It does not
  exist today in any form (§9.8).

---

## 15. Consequences for Memory / Claim / Evidence / Current State

`[INFERENCE]`, bounded by `[CONTRACT]` where noted.

- **Evidence.** An observed identifier is an observation and belongs in the Evidence plane under
  option D. `[CONTRACT]` Evidence is append-only and is not evicted, which matches an
  observation's semantics exactly.
- **Claim.** "Identifier X belongs to subject S" is a claim with an authority domain. The
  contract already names the right one: `IDENTITY_SECURITY`, writable only by `IDENTITY_SYSTEM`,
  with `LLM_WRITE = FORBIDDEN` and `USER_WRITE = FORBIDDEN` (architecture-contract.md:1212-1213).
  **This is the most important single alignment in the report:** the contract already forbids the
  LLM or the user from asserting identity, and the current extract pipeline — an LLM writing
  person rows keyed by an identifier the LLM did not verify — sits uncomfortably against it.
  Whether extract-mode writes constitute an identity assertion is `[UNDECIDED]` and asked in §18.
- **Current State.** The resolved subject for an identifier is a materialized projection, exactly
  as the contract requires of Current State — not a second source of truth.
- **Memory.** `[CONTRACT]` D1(a) already decided that historical extract rows migrate as
  un-provenanced Memory. **Memory keyed by subject inherits the merge problem**: merging two
  subjects merges their Memory, and Memory is non-assertive, so there is no conflict machinery to
  catch a bad merge — it simply becomes recall. This makes the under-merge bias more important,
  not less.
- **Narrative Memory.** Session summaries reference a person implicitly. **Not traced** — no
  mechanism found linking narrative memory to a person key; it is session-scoped today.
- **Provenance.** Under D, a merge is itself provenanced: who merged, on what evidence, when, and
  revocably. Under A and B there is no merge and therefore no provenance question. Under C the
  provenance is an audit log rather than a first-class lineage.

---

## 16. Consequences for authorization and tenancy

`[CONTRACT]` + `[INFERENCE]`:

- **Identity must never widen visibility.** I3/I4. The resolution layer answers "which subject is
  this?" and must be structurally incapable of answering "may this caller see it?" F8 is the
  standing risk.
- **Subjects are tenant-scoped.** A subject belongs to exactly one organization. No subject spans
  tenants; no identifier resolves across tenants. This is `lead_contacts`' rule, generalised, and
  it fixes §7.1 at the structural level rather than by adding a salt.
- **Possession of an identifier must stop being an addressing capability.** Under the
  recommendation, knowing a phone number no longer computes a document id anywhere — it resolves
  only through a tenant-scoped table the caller must already be authorized to query. This is the
  single largest security improvement available, and it is unavailable under A and B by
  construction.
- **`CUSTOMER` scope becomes real.** Today it exists only in the contract; the one implemented
  scope ladder has no person level (`agent-engine e43654e:alchemist/context/scope.py:9-17`).
  Deletion containment per person (I2) requires it.
- **Deletion containment ≠ authorization inheritance** must be preserved as the contract states
  twice. A subject that contains state must not thereby grant access to it.

---

## 17. Consequences for migration

`[INFERENCE]`, constrained by §9's verified facts.

1. **Recover what is recoverable first.** §9.3 — `agent_users` holds raw `channel_user_id`.
   Compute `person_hash(channel_user_id)` and join to orphaned `agent_datastores` rows. This
   converts an unknown-sized "permanently lost" set into a measured one and is the highest-value
   migration step available. It needs no decision.
2. **Mint subjects, do not re-key rows.** Create a subject per recovered identifier; write
   resolution links; leave the existing rows addressable by their current id during the window.
3. **Dual-read is mandatory** (§9.5), because the prompt path's direct `get` fails silently.
4. **Session-keyed rows are not persons.** `user_key_kind = "session"` rows should migrate as
   conversation-scoped Memory, not as subjects. They were never people, and F1 shows the agent
   never read them.
5. **Operator-touched rows carry authority** (D1(b)) and must not be absorbed into a merged
   subject without the per-field authority marker surviving.
6. **No merges during migration.** Migrate the fragmentation as-is, then merge deliberately under
   the new machinery. A migration that also merges cannot distinguish a migration bug from a bad
   merge.
7. **Deletion during migration** requires `scope_generation`, which does not exist yet (§9.8) —
   so either it is built first or deletions are frozen for the window. **Not decided here.**

---

## 18. Decisions that genuinely need Jay

Six. Ordered by how much else depends on them.

**J1 — Does OLBrain need to recognise one human across channels?**
The product question everything else hangs on. If **no**, option B plus an explicit statement
that identity is per-channel is correct, cheap and honest, and most of this report is
unnecessary. If **yes**, a resolution layer is unavoidable. *No amount of code reading answers
this.*

**J2 — Contract reading: is person-merge forbidden, or merely unmodelled?** (§8.2)
Reading A kills §13. Reading B makes it available. The contract owner must say which.
**Most likely single point of failure in this report.**

**J3 — Who owns person identity?** The contract names `IDENTITY_SYSTEM` under
`IDENTITY_SECURITY`; no such system exists. Until someone owns it, four subsystems will keep
inventing their own — which is how the present state arose.

**J4 — Is an LLM-extracted person row an identity assertion?** (§15)
The contract forbids `LLM_WRITE` on `IDENTITY_SECURITY` predicates. The extract pipeline writes
person-keyed rows from LLM output. If those constitute identity assertions, the current pipeline
contradicts the contract and the fix is not a schema change.

**J5 — Is merge operator-confirmed, automatic on proof, or both?** Determines whether option C
suffices or D is required (§11), and sets the under-merge bias in policy rather than in code.

**J6 — Organization transfer: does person data follow the agent, sever, or block the transfer?**
Unanswered today (F4), unanswered by the recommendation (falsification attempt 5), and a tenancy
question rather than a technical one.

---

## 19. Questions answerable without Jay

All are code or data questions and can proceed under the read-only rule.

1. **Measure co-occurrence.** How often does one human present two identifier types to one org?
   `lead_profiles` carrying both an email and a phone is the existing proxy, and `lead_people`
   already computes it. **This is the condition on which §13 depends** (falsification attempt 3),
   and it is measurable now.
2. **Size the `agent_users` recovery join** (§9.3). How many orphaned `agent_datastores` rows
   become re-keyable? Directly answers D3's real scope.
3. ~~Trace F4.~~ **Resolved during this pass** (F4): `agent_datastores` appears nowhere in
   studio-backend at `ca9724a`, so the transfer cascade cannot touch person data, and a
   transferred agent's person rows retain the origin organization's id. The follow-on question
   — how many agents have actually been transferred, and therefore how much person data now
   carries a stale org stamp — is a data question and remains open.
4. **Count fragmentation.** How many distinct `person_hash` values per real human, estimable via
   `agent_users` channel overlap? Quantifies what the current model costs.
5. **Confirm F1's blast radius.** How many `user_key_kind = "session"` rows exist?
6. **Check the other person-keyed stores** — `lead_profiles` internals, session summaries,
   `research` learned overlays — for identity mechanisms this pass did not reach.
7. **Verify whether any code path consults identity in an authorization decision** (F8's
   present-day analogue).

---

## 20. New architectural questions discovered

Not present in D2, D3 or D4, and not in any prior artifact.

**N1 — Merge produces conflicts that did not exist.** (F7) Two subjects with active claims on one
predicate merge into a `CONFLICT` the contract forbids resolving by recency. No candidate
architecture addresses it. **Probably the deepest unsolved problem in this report.**

**N2 — Identity has no place in the five-object model.** The contract models state about a
person and resolution between mentions, but the person is a scope with no object class. Either
identity is Evidence/Claim/Current State (option D), or the model needs an explicit statement
that identity is out of scope and owned elsewhere. Currently it is neither.

**N3 — Subjects and tenants have a lifecycle interaction.** (Attempt 5, F4, J6) A tenant-scoped
subject and an agent that changes tenant are incompatible without an explicit rule.

**N4 — Under-merge is unmeasured and treated as free.** Every design here biases toward
under-merge on safety grounds, but nobody has measured what fragmentation costs the product.
The bias may be right and is currently an assumption.

**N5 — Memory merge has no conflict machinery.** (§15) Memory is non-assertive, so a bad merge
does not surface as a conflict — it surfaces as the agent confidently recalling a stranger's
details. Memory may need a merge-provenance marker that Claims get for free.

**N6 — Identity resolution becomes a runtime dependency of every packet build.** (Attempt 6) A
new availability coupling that does not exist today.

**N7 — `person_hash`'s two implementations may already have diverged in production.** (F2) Not
checked. If `olbrain-shared` ever shipped a change to `person_hash` that `memory_doc_id` did not
receive, some `agent_user_memory` documents are already unreachable from their
`agent_datastores` counterparts. **Checkable from git history and worth doing.**

---

## Concise closing statement

**What person identity should mean in OLBrain.** `[INFERENCE]` A person is not a hash of a phone
number, and not a row. A person is a **tenant-scoped, opaque subject that observed identifiers
resolve to** — where the observation is immutable evidence, the resolution is a revisable and
provenanced claim, and the subject is the contract's `CUSTOMER` scope. Identity is a *resolution
problem*, not an *encoding problem*.

**What architecture follows.** An explicit resolution layer (option C as the first increment of
option D): typed immutable observed identifiers; opaque subjects that encode nothing and so never
need rotation; mutable, auditable resolution links that make merge a re-pointing and split a
revocation; conservative normalisation generalised from `lead_contacts`; and a structural
guarantee that none of it participates in authorization.

**Evidence supporting it.** The contract already froze `scope_id` as the partition key and
already names `CUSTOMER` a scope, so the subject needs no new key concept. `lead_people` and
`lead_contacts` already implement this doctrine — provisional, re-pointable, org-scoped,
conservatively normalised — and document their reasoning in source. The contract's
`RESOLVES_TO`/revocation pattern is precisely the non-destructive link model required. And the
contract already assigns identity to `IDENTITY_SECURITY`, writable only by `IDENTITY_SYSTEM`.

**Evidence contradicting or limiting it.** The contract forbids cross-scope `SAME_AS` and rejects
destructive entity merges; if persons are scopes, person-merge may be forbidden outright (J2).
The mapping table is an authorization bridge if discipline slips (F8). Merge creates conflicts
the contract cannot resolve (N1). Organization transfer is unsolved (N3). And if co-occurrence
proves rare, the whole resolution layer under-delivers and simple per-tenant keyed hashing plus
an honest product statement is the better architecture.

**What remains unknown.** Whether cross-channel recognition is a product requirement (J1); how
often co-occurrence occurs (§19.1); how many rows are recoverable via `agent_users` (§19.2);
whether person data crosses tenants on agent transfer (§19.3); whether the two digest
implementations have already diverged (N7); and what merge means for Current State resolution
(N1).

**What truly requires Jay.** J1 (cross-channel recognition — the product question), J2 (the
contract reading), J3 (who owns identity), J4 (whether LLM-extracted person rows are identity
assertions), J5 (merge policy), J6 (organization transfer).

**On D4 itself.** D4 asks whether to adopt an opaque surrogate id. The honest answer is that the
surrogate id is the *least* important part of the change and adopting it alone would fix almost
nothing: it would replace one immutable un-mergeable key with another while leaving four
mechanisms, three normalisation regimes, no resolution layer and no owner. **D4 should be
reframed** — from "what is the primary key of person-keyed tables?" to "**what is a person in
OLBrain, who owns that definition, and does the product need to recognise one human across
channels?**" The first question has no correct answer until the last one is answered.

---

**This document decides nothing.** It is research. Every recommendation is labelled
`[INFERENCE]`, every contract statement `[CONTRACT]`, every source fact `[CODE]` with a pinned
commit. No production code, schema, migration, contract or existing artifact was modified.
