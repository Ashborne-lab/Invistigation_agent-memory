# S7 backfill — correction note (M1)

Date: 2026-09-26. Read-only. **The backfill script is not modified and no data is changed.**

**Audience:** the S7 / QF-4 owner. This is a procedure correction, not an objection to S7's goal.

---

## 1. The problem in one paragraph

`[CODE]` QF-4's answer schedules S7 as WB-006 with the sequence: **stamp `organization_id` on new
rows at every runtime write site → backfill india-prod → move the collections into an org-scoped
rules block with rules tests**, noting that tightening rules first would break live reads. That
ordering is correct. The defect is in an unstated assumption of step 2: that a missing
`organization_id` is the only wrong state. `[CODE]` It is not — **agent transfer leaves person
stores stamped with the origin organization**, so some values are already present and already
wrong. A backfill that fills only missing values preserves them, and step 3 then tightens rules
onto a field that mis-attributes exactly those tenants.

---

## 2. Evidence

### 2.1 The transfer cascade omits every person-keyed store

`[CODE]` `olbrain-studio-backend ca9724a`. Collections handled across
`services/agent_transfer_platform_ops.py` and `services/agent_transfer_service.py`:

`agents`, `projects`, `organizations`, `memberships`, `knowledge_library`, `agent_senders`,
`share_tokens`, `api_keys`, `mcp_configs`, `agent_subscriptions`, `agent_deployments`,
**`agent_sessions`**, `usage` / `usage_archive`, `analytics` / `analytics_archive`,
`agent_transfer_invites`, `user_profiles` — **sixteen.**

Omitted: `agent_datastores`, `agent_user_memory`, `lead_contacts`, `lead_profiles`, `agent_users`.
**`agent_datastores` returns zero hits in the entire studio-backend repository.**

`[INFERENCE]` The cascade is thorough about per-agent subcollections — it even archives usage and
analytics — and handles `agent_sessions`, the conversation record. It omits every store holding
*who the conversation was with*. This is not a general oversight about subcollections; it is
specific to the person plane.

### 2.2 Where the stale value lives

`[CODE]` `agent_datastores` entries carry **no** `organization_id`; tenancy is on the **table
header** `agent_datastores/{agent}/tables/{table}`, written by both writers
(`olbrain-agent-runtime 8df0e02:services/extract_entry_writer.py:83`,
`core/tools/datastore_executor.py:347-353`) from the live request context at table-creation and
on subsequent header merges.

`[INFERENCE]` After a transfer the agent belongs to the target org while the header still carries
the origin org. The agent keeps reading its rows — addressing is by `agent_id` path, not by org —
so nothing visibly breaks. The field is simply wrong, silently.

### 2.3 Both stores self-heal — but on different clocks

`[CODE]` Both durable write paths in `olbrain-agent-runtime 8df0e02:services/agent_memory_service.py`
(`:398-405`, `:467-475`) include `"organization_id": organization_id` in the payload on **every**
durable write, from the live request context. So a transferred agent's memory documents re-stamp
themselves on the next turn that records something.

`[CODE]` Both paths `return None` when there is nothing new (`:394-396`, `:462-465`), so the
re-stamp requires an actual content change, not merely a turn.

`[CODE]` **`agent_datastores` self-heals by the same mechanism.** Both writers write the table
header with `set(table_ref, {—, "organization_id": organization_id, —}, merge=True)` on **every**
write, from the live request context —
`olbrain-agent-runtime 8df0e02:services/extract_entry_writer.py:79-85` and
`core/tools/datastore_executor.py:347-353`. An earlier draft of this note said the residue was
*"every table of every transferred agent, indefinitely"*; **that was wrong and is withdrawn.**

`[INFERENCE]` Consequences for the procedure. Both stores self-heal, but on **different clocks**,
and the difference runs opposite to the intuition:

- `agent_user_memory` heals **per person** — one document per person, re-stamped only when *that*
  person returns **and** records something durable (both paths `return None` when there is nothing
  new). A dormant person never heals.
- `agent_datastores` heals **per table** — one header shared by every person in the table,
  re-stamped by **any** write to it. A table with any activity at all corrects itself for all its
  rows at once.
- **So `agent_datastores`' residue is the narrower one** (wholly quiet tables), and
  `agent_user_memory`'s is likely the larger population, since dormant persons are common on any
  conversational platform. `[UNMEASURED]` — Phase 0 measures both rather than assuming either.
- The two stores still need **different** treatment, because one heals per-table and the other
  per-person; a uniform backfill would misjudge both residues.

### 2.4 Transfers are enumerable

`[CODE]` `olbrain-studio-backend ca9724a:constants/activity_types.py:94-95` defines
`agent_transferred` and `agent_transfer_received`; `:132` marks the former
`ActivitySeverity.WARNING`. Activities are written to the **`activities`** collection
(`services/activity_service.py:505`) and emitted at `services/agent_transfer_service.py:2326` and
`:3173`. Transfer intent is separately persisted in **`agent_transfer_invites`** with `status` in
`pending | accepted | cancelled | expired` (`models/agent_transfer_models.py:69`).

`[INFERENCE]` The affected population is therefore directly queryable. This is what makes the
correction actionable rather than merely cautionary.

### 2.5 The finance family is outside S7 entirely

`[CODE]` `olbrain-finance-engine 109a838` scopes by **path** — `organizations/{org_id}/…`, with
`require_org_role(org_id, …)` at `app/auth.py:63`. `[INFERENCE]` Path-scoped collections need no
stamping and no backfill; the org is structural. **This narrows S7's scope** and removes an
~18-collection family that earlier scoping discussions assumed was in play.

---

## 3. The authoritative source for current organization

`[INFERENCE]` `agents/{agent_id}.organization_id` is the authoritative current owner. Reasons:

1. `[CODE]` It is what the transfer cascade re-stamps.
2. `[CODE]` It is what org resolution already flows through — `knowledge_library`,
   `_get_knowledge_base` and `skill_binding_service` all resolve organization via this document.
3. QF-1's answer makes `agent-design` the owner-of-record for `agents/{id}`, so it has a named
   owner.

**Caveat, recorded rather than resolved.** `[CODE]` `agents/{id}` is in neither catch-all exclusion
list at `olbrain-studio 8cee761c` (S1), so any authenticated user can write it. `[INFERENCE]` The
authoritative source for a tenancy backfill is itself client-writable. This does not invalidate
using it — there is no better source — but the invariant in §6 should be checked *after* the
rules tightening that QF-1's answer attaches to the ownership move, not only before.

---

## 4. Proposed verification procedure

`[INFERENCE]` Presented as a specification for the S7 owner to accept, amend or reject. **No step
is executed here and none writes.**

### Phase 0 — measure before changing anything

1. From `activities` where `activity_type == 'agent_transferred'`, build the set of transferred
   agent ids with origin and target org and the transfer timestamp.
2. Reconcile against `agent_transfer_invites` where `status == 'accepted'`. A discrepancy either
   way is itself a finding.
3. For each transferred agent, read `agents/{id}.organization_id` (current truth).
4. Compare against every `agent_datastores/{agent_id}/tables/*.organization_id`.
5. Repeat for `agent_user_memory` (document field), `lead_profiles`, `lead_contacts`,
   `agent_users` — noting `[CODE]` that `agent_users` has no `organization_id` at all, being keyed
   `(agent_id, channel, channel_user_id)`, so it is a *derivation* case, not a *correction* case.
6. **Output: three disjoint counts per collection** — `missing`, `present-and-correct`,
   `present-and-wrong`. The third is the population the current procedure would miss.

### Phase 1 — reconciliation rules

`[INFERENCE]`

| State | Action |
|---|---|
| `organization_id` absent | Stamp from `agents/{id}.organization_id` — the original S7 intent |
| present **and equal** to the agent's current org | Leave |
| present **and different**, agent **has** a transfer record | **Overwrite** from the agent's current org. This is the corrected case |
| present **and different**, agent has **no** transfer record | **Do not write. Escalate.** A mismatch without a transfer is unexplained and could indicate a different defect, a legitimate multi-org arrangement, or bad data |

`[INFERENCE]` The fourth row is the important one: the correction must not become a blanket
"overwrite whatever disagrees", because that would silently repair states nobody has diagnosed.

### Phase 2 — dry-run requirements

`[INFERENCE]` The in-house precedent is explicit and should be followed:
`olbrain-studio-backend ca9724a:scripts/merge_billing_aggregates.py` is **dry-run by default,
writes only with `--apply --yes`, and snapshots every affected document to JSONL before any
destructive step, for rollback.** The same three properties should be required here, plus:

- per-collection and per-org counts printed before and after;
- an explicit count of the `present-and-wrong` class, so the correction's effect is visible rather
  than absorbed into a total;
- the escalation list (Phase 1 row 4) emitted as data, not as log noise.

### Phase 3 — the invariant that must hold before rules tighten

`[INFERENCE]` **For every collection moving into an org-scoped rules block: zero documents whose
`organization_id` differs from the authoritative current organization of their owning agent, and
zero documents where it is absent.**

This must be asserted *immediately before* the rules change and re-asserted after, because
`agent_datastores` headers are written from live request context and an in-flight transfer during
the window would reintroduce a mismatch. `[INFERENCE]` A transfer freeze for the duration of the
rules change is the simplest way to make the invariant hold, and it is cheap — transfers are rare
enough to be individually logged.

---

## 5. Does `agent_user_memory` self-healing change the procedure?

`[INFERENCE]` **Yes, in two specific ways** — and so does `agent_datastores`' (§2.3). Neither
removes the need for the backfill.

1. **Ordering, corrected.** Both self-heal on write, but `agent_datastores` heals **per table**
   (any writer fixes the header for every row in it) while `agent_user_memory` heals **per person**
   (only that person's return, with durable new content, fixes their document). On that difference
   **`agent_user_memory` is likely to hold the larger stale residue**, not the smaller — the
   opposite of what an earlier draft of this note said. `[UNMEASURED]` Phase 0 measures both
   rather than sequencing on an assumption.
2. **Verification must be point-in-time.** Because both heal continuously, a count taken before a
   busy period differs from one taken after through no action of the backfill. The Phase 3
   invariant must be asserted in the same window as the rules change, not inferred from an earlier
   measurement.

`[INFERENCE]` Self-healing justifies skipping **neither** store. Dormant persons and quiet tables
never heal; for `agent_user_memory` the failure direction is a 404 to the rightful owner — a
correctness bug, privacy-safe but real.

---

## 6. What this note does not do

- It does not modify `backfill-clix-organization-id.js` or any script.
- It does not execute any query — `[UNMEASURED]`, no data access in this workspace.
- It does not decide whether S7 proceeds, or in what order. That is the programme owner's call.
- It does not classify any collection legally — G5/QF-2 are parked.

---

## 7. Limitations

1. `[UNMEASURED]` The size of the `present-and-wrong` population is unknown. It may be zero if no
   agent has ever been transferred — Phase 0 step 1 settles that cheaply and should run first.
2. `[CODE]` The transfer collection list was derived from `.collection("…")` references in two
   service files; a dynamically-named collection would have been missed.
3. `[INFERENCE]` Whether `lead_profiles` / `lead_contacts` carry a stale org after transfer was not
   traced to the same depth as `agent_datastores` and `agent_user_memory`; they are included in
   Phase 0 to be measured rather than assumed.
4. The §3 caveat — that the authoritative source is itself client-writable — is recorded as an
   interaction with S1/QF-1, not resolved here.
