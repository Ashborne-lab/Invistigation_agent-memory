# J1–J6 — Derived contract changes, implementation impact, unresolved questions

Date: 2026-09-28. Read-only. **Input:** Jay's answers to J1–J6, dated 2026-09-26, as relayed by
Shivam. **Output:** what those answers require, derived strictly from their wording plus verified
code and contract text.

**Rule for this document.** No new policy. Every requirement below traces either to Jay's words or
to a verified fact. Where Jay's wording is silent, ambiguous, or conflicts with the code it names,
the item is recorded as **UNRESOLVED — requires Jay's (or the contract owner's) confirmation**,
never filled in. Contract changes are **drafted, not applied** — `architecture-contract.md` is
unmodified (md5 `97c1fa3bcea1d71210c0429b1d113d07`).

Labels: `[JAY]` stated in the J1–J6 answers · `[CODE]` verified at a named commit ·
`[CONTRACT]` normative text · `[DERIVED]` follows necessarily from the above ·
`[UNRESOLVED]` needs a human answer.

**Evidence base, fetched 2026-09-28.** Most repositories moved in the two days since the last pass;
every citation here is at the new commit:
`olbrain-agent-runtime daee3f9` · `olbrain-shared d0e0d2b` · `olbrain-studio-backend 5da93ae`
(and Jay's cited `b2d39ff`, confirmed present) · `olbrain-research-design e218f10` ·
`olbrain-studio 1f05ca11` · `olbrain-agent-design c56271d`.

---

## 1. Verification of the premises Jay's answers rest on

Jay could not read the contract text and relied on summaries, so his factual premises were checked
independently before anything was derived from them.

| # | Jay's premise | Verdict | Evidence |
|---|---|---|---|
| V1 | J1: `lead_people` already union-finds normalised email + phone into an org-scoped `person_key` | **CONFIRMED, with a material qualification** | `[CODE]` `core/lead_people.py` `build_people()`; `person_key` is a `lead_contacts` doc id `{org_id}__{sha256}`. **But see V5.** |
| V2 | J1: `agent_user_memory` and `agent_datastores` are keyed per agent + unsalted hash, so the same phone is a different person per agent | **CONFIRMED** | `[CODE]` `memory_doc_id` = `{agent_id}__{sha256(strip+lower)[:32]}` (`agent_memory_service.py`, `daee3f9`); `person_hash` identical digest (`olbrain-shared d0e0d2b:columns.py`); `agent_datastores` path is `/{agent}/tables/…` |
| V3 | J5: reuse `research_clients` mechanics — `merged_into`, alias inheritance, archival | **CONFIRMED for the record shape. Two gaps.** | `[CODE]` `org_research_clients.py` (`e218f10`): routes are only `GET`, `PUT`, `DELETE`, `POST /merge`. **(a) There is no undo/unmerge route.** **(b) The key is `slugify(display_name)` — value-derived, not opaque.** |
| V4 | J6: the transfer cascade references none of the five person stores (studio-backend `b2d39ff`) | **CONFIRMED at `b2d39ff` and at current `5da93ae`** | `[CODE]` `agent_datastores`, `agent_user_memory`, `lead_contacts`, `lead_profiles`: zero references anywhere in the repository. `agent_users`: referenced only by outreach services; **zero** references in the three transfer/relocation service files. |
| V5 | J3: the org-scoped `person_key` fold is usable as the **named interim resolver**, "evaluated on every person-keyed write" | **CONFLICTS WITH THE CODE** | `[CODE]` The fold is invoked from exactly one place — `routers/agent_memory.py` `list_lead_people_endpoint` (`daee3f9`). It is **read-time only**, **never evaluated on any write**, runs over **lead profiles only**, and is **page-scoped**: its own docstring says *"A page boundary can split one person's calls across two pages, so `people` here means 'people as far as the loaded calls show'."* It does not persist anything. |

**V5 is the most consequential finding in this document** and is developed as U1 below. It does
not contradict Jay's *policy* — it means the mechanism he named does not yet do what his
requirement says the interim resolver must do.

---

## 2. What the answers decide — restated without addition

| ID | Decided `[JAY]` | Explicitly left to the spec `[JAY]` |
|---|---|---|
| **J1** | Recognise one human across channels **within an organisation and across that org's agents**. **Never across organisations.** | — |
| **J2** | The contract must **permit** person merges within an org and **forbid** them across orgs. Two `CUSTOMER` subjects in one org may resolve to one human. Merge semantics must be written into the contract explicitly. | The drafting |
| **J3** | Identity authority = **the Memory Gateway**; Shivam specs and builds it. Until then, agent-runtime's org-scoped `person_key` fold is the **named interim resolver**, and the contract should say so. Identity establishment and resolution are **purely code, evaluated on every person-keyed write**. **No human routes, approves or merges records by hand.** "Owner" means accountability for spec and code only. | — |
| **J4** | An LLM-extracted person-keyed row is **not** an identity assertion. The key is system-asserted (channel-supplied phone or email, hashed); the LLM supplies only field values. Classify the write as **MEMORY, not `IDENTITY_SECURITY`**, so the `LLM_WRITE` ban does not apply and extraction keeps working. | — |
| **J5** | Merges are **automatic**, with an **audit record** and an **undo**. **No operator approval gate.** An **exact normalised phone or email match within an org merges immediately** in code. Every merge writes **`merged_into` plus an audit record**. An operator **can undo but never has to approve**. Reuse `research_clients`' record shape, **not its operator-initiated trigger**. | **The weaker-evidence threshold** — "the spec must state" it |
| **J6** | Person data **follows the agent** on org transfer. Add `agent_datastores`, `agent_user_memory`, `lead_contacts`, `lead_profiles` and `agent_users` to the studio-backend transfer cascade and **re-stamp `organization_id` automatically**. | — |

---

## 3. Contract changes — drafted, not applied

Numbering is left to the contract owner: Patch 19 (D7) is itself undecided, so these are labelled
**P-A … P-E**. Each is written to encode Jay's answer and nothing more. Where encoding it exposes a
conflict with existing text, the conflict is stated beside the draft rather than resolved inside it.

### P-A — Person-subject resolution and the tenant boundary *(J1, J2)*

**Existing text that constrains it** `[CONTRACT]`, §14 Architecture decision matrix:

| Decision | Outcome |
|---|---|
| Canonical global entities | Allowed |
| Global entity as authorization bridge | Forbidden |
| **Cross-customer `SAME_AS`** | **Forbidden** |
| `RESOLVES_TO` | Mention → canonical entity, non-authorizing |
| Entity destructive merges | Rejected in initial implementation |

**The conflict.** `[DERIVED]` J2 says two `CUSTOMER` subjects in one org may resolve to one human.
Read literally, that is a relation between two customers — which the existing row forbids. **The
answer cannot simply be added; it collides with a live row.**

Two drafting routes encode Jay's policy, and **only one stays within it**:

- *Route 1 — reword the existing row* (e.g. "cross-customer" → "cross-tenant"). **This exceeds
  J2.** The row also governs *mention*-level `SAME_AS` (Example 4 forbids `A1 SAME_AS B1` between two
  customers' mentions). Rewording it would permit mention-level linking across customers within a
  tenant — something Jay did not decide.
- *Route 2 — leave the mention row untouched and add a distinct row for persons.* **This encodes J2
  exactly.**

**Draft (Route 2):**

> | Person-subject resolution within one tenant | **Allowed**, under §[merge semantics] |
> | Person-subject resolution across tenants | **Forbidden** |
>
> *Person-subject resolution relates two `CUSTOMER` scopes that are determined to be the same human.
> It is distinct from `SAME_AS`, which relates mentions, and does not alter the `SAME_AS` rows
> above. It never crosses a tenant boundary.*

`[UNRESOLVED]` **U16** — the contract owner must confirm Route 2 matches Jay's intent, since Jay's
decision rests on a summary of §14 rather than its text.

### P-B — Merge semantics *(J2, J5)*

**Draft:**

> **Person-subject merge.**
> 1. Merges are performed automatically by the identity authority (P-C). No human approval is
>    required or permitted as a precondition.
> 2. An **exact match of a normalised phone number or email address** within one tenant causes an
>    immediate merge. *[Normalisation: UNRESOLVED — U2.]*
> 3. Weaker evidence causes a merge only above a threshold stated in the identity specification.
>    *[Threshold: UNRESOLVED — U3.]*
> 4. Every merge records a `merged_into` reference on the non-surviving subject and writes an audit
>    record.
> 5. Every merge is **undoable**. An operator may undo a merge; an operator is never required to
>    approve one.
> 6. A merge is non-destructive: the non-surviving subject is archived, not deleted, and remains
>    resolvable through `merged_into`.

**Constraints that follow necessarily** `[DERIVED]` — not new policy, but consequences of J5's undo
requirement combined with the existing *"Entity destructive merges — Rejected"* row:

- **Any model that rewrites history is excluded**, because it cannot be undone. From the earlier
  Track E analysis, this excludes *re-subjecting Claims* (C-M1) and *unioning Memory sets* (Mem-M1).
  Both destroy the pre-merge boundary, so there is nothing to restore.
- The surviving models share the property that **only the resolution changes, never the underlying
  records**. The contract's existing revocation precedent is exactly this shape: *"A1 RESOLVES_TO
  iphone_17_pro → REVOKED. A1 and its evidence are untouched."*
- `[CONTRACT]` A merge that produces two authoritative values for one predicate yields `CONFLICT`,
  which §6 already defines as recoverable through the policy's declared `RESOLVE_CONFLICT`
  operation. **No new contract machinery is needed for that case.**

**What P-B cannot specify from Jay's answers:** what undo restores when evidence has accrued to the
merged subject *after* the merge — see U11.

### P-C — Identity authority *(J3)*

**Draft:**

> **Identity authority.** Person-subject establishment and resolution are performed by the Memory
> Gateway. Until the Memory Gateway exists, the org-scoped `person_key` fold in agent-runtime is the
> **named interim resolver**. Resolution is performed in code and is evaluated on every person-keyed
> write. No human routes, approves or performs a resolution. Ownership of the identity authority
> denotes accountability for its specification and code only.

**Two conflicts exposed by drafting it:**

1. **U1 — the named interim resolver does not do what the draft says it does.** V5: it is read-time,
   page-scoped, lead-only, and never evaluated on a write. The draft sentence *"evaluated on every
   person-keyed write"* is **false of the named mechanism today**. The contract cannot truthfully
   say both things without either changing the mechanism or changing the sentence.
2. **U6 — the contract already names an identity authority.** `[CONTRACT]` `IDENTITY_SECURITY` is an
   authority domain whose only permitted writer is `IDENTITY_SYSTEM`, and it governs
   **`account_role`** — platform roles and permissions (`:1212-1213`). `[CODE]` Neither exists in any
   repository. Jay's *"identity authority = the Memory Gateway"* does not say whether the Gateway
   becomes `IDENTITY_SYSTEM` (and therefore also authoritative for roles), or whether end-customer
   person resolution is a **separate** authority. These are different architectures: one puts
   authorization data inside the memory system.

### P-D — Classification of the extraction write *(J4)*

**Draft:**

> **Extraction-mode person-keyed writes.** The person key on an extraction-mode write is
> system-asserted from the channel-supplied identifier. The LLM supplies field values only. Such a
> write is classified under the **Memory** authority domain, not `IDENTITY_SECURITY`; the
> `LLM_WRITE = FORBIDDEN` restriction on `IDENTITY_SECURITY` does not apply to it.

**Conflict exposed** — **U5.** D1(a), already answered by Jay on the decision dashboard, reads:
*"Existing extract-mode rows migrate as un-provenanced Memory, not Claims. **Future extractions build
real Claims going forward.**"* J4 says to classify the write as **MEMORY**. Two readings:

- (i) J4 names the **authority domain** (Memory, not `IDENTITY_SECURITY`) and is silent on the object
  class — future extractions still produce Claims per D1(a). Consistent.
- (ii) J4 names the **object class** — extraction writes are Memory, not Claims. This **reverses
  D1(a)'s second sentence**.

The draft above is written under reading (i), because that is the reading that does not overturn a
prior answer. **It needs Jay's confirmation**, because the two readings produce different schemas.

### P-E — Tenant transfer *(J6)*

Mostly implementation (§4). One contract consequence `[DERIVED]`: J1 lets a subject span several of
one org's agents; J2 forbids a subject from spanning orgs; J6 moves one agent's person data to
another org. So a transfer **must split** any subject shared between the moving agent and an agent
that stays. The contract needs a sentence on what a transfer does to subjects — see U8. No draft is
offered, because Jay's answer does not say what the split produces.

---

## 4. Implementation impact

`[CODE]` locations at the commits in the header. **Nothing below is authorised to start**; this
maps where Jay's answers land.

### 4.1 The transfer cascade (J6) — the five stores do **not** behave alike

J6 says "re-stamp `organization_id` automatically" for all five. Verified per store:

| Store | Where the org lives | Self-heals on write? | What J6 actually requires |
|---|---|---|---|
| `agent_datastores` | Field on the **table header** | **Yes** — both writers merge the header, including `organization_id`, on every write | Re-stamp headers. Only quiet tables are stale today |
| `agent_user_memory` | Field on the **document** | **Yes** — both durable write paths include it on every write | Re-stamp documents. Only dormant persons are stale today |
| `agent_users` | Field on the document | **No.** `upsert_agent_user` writes `organization_id` **only on create**; the update branch touches `last_seen_at` and counters only | Re-stamp. **Every transferred agent's `agent_users` rows are stale today, and stay stale** |
| `lead_profiles` | Field; doc id = `lead_profile_doc_id(agent_id, session_id)` | Not traced | Re-stamp |
| `lead_contacts` | **Inside the document id** — `{org_id}__{sha256(contact)[:32]}` | n/a | **Re-stamping is impossible.** See below |

**`lead_contacts` needs re-keying, not re-stamping** `[CODE]` + `[DERIVED]`. The org is part of the
document id. And one contact document is **shared across all of an org's agents**: it holds a list
of `refs`, each carrying `agent_id` and `profile_doc_id`. Moving one agent therefore means
**extracting that agent's refs** out of the origin org's contact documents and writing them into
contact documents under the **target org's** id. If the target org already has a document for that
contact, that is an exact normalised match within one org — which **J5 says merges immediately**. So
**a transfer can trigger automatic merges in the receiving org.** J6's wording does not cover this.

**Additional finding — the interim resolver's evidence is silently capped.** `[CODE]`
`MAX_REFS_PER_CONTACT = 20` (`core/lead_contacts.py:52`); on append the list is trimmed to the last
20 and older refs are dropped. For a contact with more than 20 calls, the evidence the resolver
folds over is incomplete, with no record of what was dropped.

**Correction to an earlier artifact.** `s7-backfill-correction-note.md` §4 Phase 0 step 5 states that
`agent_users` *"has no `organization_id` at all"*. **That is wrong.** It carries the field, written
on create only. The practical consequence runs the other way from what that note implied:
`agent_users` needs the correction *most*, because it is the one store that never self-heals. That
note has not been edited here.

### 4.2 Where each answer lands in code

| Answer | Repository | Location | Impact |
|---|---|---|---|
| J1, J5 | `olbrain-shared d0e0d2b` | `person_hash` (`agent/datastore/columns.py`) | The digest is global and carries no tenant. Cross-agent recognition within an org needs either a resolver in front of it or a change to the key — **the choice is D4, still open** |
| J1, J5 | `olbrain-agent-runtime daee3f9` | `memory_doc_id` (`services/agent_memory_service.py`) | Key embeds `agent_id`, so the same human is a different document per agent — directly contrary to J1 |
| J1, J3 | `olbrain-agent-runtime daee3f9` | `core/lead_people.py` `build_people`; `routers/agent_memory.py` `list_lead_people_endpoint` | The named interim resolver. To meet J3 it must become **write-time, org-wide and persisted**; today it is none of the three (U1) |
| J3 | `olbrain-agent-runtime daee3f9` | Extraction writer, live datastore tool, the three prompt-read paths in `core/cs_packet_builder.py` | "Evaluated on every person-keyed write" puts resolution on the write path of all three writers |
| J3 | `olbrain-agent-design` | Operator CRUD — `datastore_service.py` computes `person_hash(user_key)` from an operator-supplied key | Operators currently choose the key. Under J3 ("no human routes… records by hand"), key assignment must move behind the resolver. *Verified at `51ffe3b`; not re-verified at `c56271d`.* |
| J4 | `olbrain-agent-runtime daee3f9` | Extraction write path | No code change implied by J4 itself — it preserves current behaviour. U5 decides whether the *object class* changes |
| J5 | `olbrain-research-design e218f10` | `org_research_clients.py` | Record shape to reuse. **No undo exists in the precedent** — undo is new work |
| J6 | `olbrain-studio-backend 5da93ae` | `services/agent_transfer_service.py`, `agent_transfer_platform_ops.py`, `agent_relocation_service.py` | Add five stores, with per-store mechanics per §4.1 |
| All | — | Memory Gateway | Does not exist. It is part of the target PostgreSQL design, which remains gated (§6) |

### 4.3 A consequence of J3 + J5 worth stating explicitly

`[DERIVED]` J3 forbids humans from merging by hand; J5 lets humans only *undo*. Together: **a missed
merge (two records that are the same human but were not joined) can only be fixed by changing code
or the threshold — never by an operator.** Under-merge becomes an engineering defect; over-merge
becomes an operator-reversible event. This is not new policy; it is what the two answers imply
together, and the spec will need to accommodate it.

---

## 5. Unresolved technical questions

Only questions Jay's answers genuinely leave open. None is answered here.

| ID | Question | Why it matters | Who |
|---|---|---|---|
| **U1** | **The named interim resolver is read-time, page-scoped, lead-only and never runs on a write.** Is "the `person_key` fold" meant *as-is* (in which case the "every person-keyed write" requirement cannot hold during the interim), or as a *specification* for a write-time, org-wide, persisted resolver to be built before the Gateway? | Decides whether the interim period needs new code at all. As written, P-C would state something false | **Jay** |
| **U2** | **Which normalisation defines "exact normalised phone or email"?** Three regimes exist. `lead_contacts` is digits-only and deliberately keys national and international forms of one number separately; `person_hash` does only `strip+lower`. `+91 98765 43210` vs `98765 43210` is a merge under neither today | J5's "merges immediately" depends entirely on what "exact" means | **Shivam** (spec) |
| **U3** | **The weaker-evidence threshold** — Jay says the spec must state it; nothing states it. `[CONTRACT]` §6 forbids selecting *authoritative values* by confidence; whether a confidence threshold for *identity* merge is compatible with that stance is a contract reading | Automatic merges below exact-match are where wrong merges happen, and a wrong merge renders one person's data into another's conversation. Undo restores the records, not what the agent already said (N12) | **Shivam** (value); **contract owner** (compatibility) |
| **U4** | **Identifiers that are neither phone nor email.** Instagram sends a per-app IGSID; web chat sends none (rows keyed by session id); webhooks send an arbitrary `user_id`. J5 names only phone and email | Undefined whether IGSID-keyed or session-keyed rows are persons at all, and whether they can ever merge | **Jay** / Shivam |
| **U5** | **J4 vs D1(a).** "Classify as MEMORY" vs "future extractions build real Claims". Authority domain or object class? | Produces different schemas | **Jay** |
| **U6** | **Is the Memory Gateway the contract's `IDENTITY_SYSTEM`?** That authority also governs `account_role` (platform permissions) | If yes, authorization data becomes part of the memory system | **Jay** + contract owner |
| **U7** | **Recognition across agents vs visibility across agents.** J1 decides that one human is one subject across an org's agents. It does not decide whether agent B may *see* what agent A recorded. Tables are per-agent with per-agent column schemas | "Same subject" and "shared memory" are different decisions; the first is made, the second is not | **Jay** |
| **U8** | **Transfer splits shared subjects.** A subject shared by agents A and B in org X; A moves to org Y. The subject must split (J2), A's data joins or creates a subject in Y, and an exact match in Y merges immediately (J5). Can a pre-transfer merge still be undone after the split? | J6 + J1 + J2 + J5 interact, and no answer covers the combination | **Jay** |
| **U9** | **`lead_contacts` transfer mechanics.** Re-keying, ref extraction, and merges-on-arrival (§4.1). J6's "re-stamp" wording does not cover it | Largest single implementation item in J6 | Shivam / studio-backend owner |
| **U10** | **Existing `agent_users` rows are stale for every past transfer** and will not self-heal | Needs a correction procedure, not just a cascade change for future transfers | S7 owner |
| **U11** | **What does undo restore?** `research_clients` has no undo to copy. If evidence accrued to the merged subject after the merge, which pre-merge subject does it return to? | Without this, "undo" is not implementable as stated | **Shivam** (spec) |
| **U12** | **Merge and `scope_generation`.** Is a merge a deletion of the retired scope (N10)? In-flight writes against it need fencing, and their disposition is G8 | Couples merge to two other open decisions | Contract owner; Operations (G8) |
| **U13** | **"Never across organisations" is policy; the key does not enforce it.** The digest is identical across orgs for the same phone — `lead_contacts` prefixes the org in the id but the suffix is the same unsalted hash | J1's boundary currently depends on every piece of code remembering it, not on the key. D2 (keyed or salted hash) is untouched by J1–J6 | **D2 — still open** |
| **U14** | **Key form.** `research_clients` uses a slug; `lead_contacts` a hash declared "subject to merge"; J5 reuses the *record shape*, not the key. Opaque surrogate or derived key? | Sets the primary key of every person-keyed table | **D4 — still open** |
| **U15** | **Resolution on the write hot path.** J3 requires resolution on every person-keyed write. The extraction writer currently swallows exceptions. If resolution is unavailable, does the write fail, queue, or proceed unresolved? | A new availability dependency on every write (N6) | **Shivam** (spec) |
| **U16** | **P-A drafting route** (§3) — confirm Route 2 matches Jay's intent, since his decision rests on a §14 summary rather than its text | Route 1 would also loosen mention-level `SAME_AS`, which Jay did not decide | **Contract owner** |

---

## 6. Effect on the open-decision board

**Closed by J1–J6** `[JAY]`: J1, J2, J3, J4, J5, J6 as decisions.

**Not closed, and not addressed by the answers:**

- **D4** — key form (U14).
- **D2** — keyed/salted hash; the privacy findings (cross-org linkability, guessability) are untouched
  (U13).
- **D3** — rows whose original key is unrecoverable.
- **N8** — becomes U7 (visibility, not recognition).
- **N10 / G8 coupling** — U12.
- **N11** — narrative re-registration.
- **N12** — disclosure is not rollback-able. `[DERIVED]` This now bears directly on J5: automatic
  merges above a weaker-evidence threshold (U3) are exactly the case where an agent can say something
  that undo cannot retract.

**PostgreSQL gate.** `[DERIVED]` Narrower again — identity *semantics* are now decided (scope,
permitted merges, authority, classification, transfer behaviour). Still blocked on: **D4** (key
form), and the **parked G5/QF-2** pair, which remains the binding constraint. J1–J6 do not touch
either.

---

## 7. What to take back to Jay

Short list — only where his answer cannot be implemented as written, or two answers pull in
different directions:

1. **U1** — The interim resolver he named runs on reads, per page, over leads only. His requirement
   says it runs on every write. Which does he mean?
2. **U5** — Does "classify as MEMORY" override D1(a)'s "future extractions build Claims"?
3. **U6** — Is the Memory Gateway meant to be the contract's `IDENTITY_SYSTEM`, which also owns
   platform roles?
4. **U7** — Does recognising one human across agents mean agents share what they know about that
   human?
5. **U8** — On transfer, a subject shared with an agent that stays must split. What happens to it?
6. **U4** — Are Instagram-only and anonymous web-chat contacts persons?

Everything else in §5 is spec work for Shivam or a reading for the contract owner, and does not need
Jay.
