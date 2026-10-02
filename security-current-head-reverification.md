# Security findings — re-verification at current HEAD

Date: 2026-09-26. Read-only. **Awareness only; no remediation is proposed.**

**Why this exists.** Earlier investigation passes cited `olbrain-studio` at `252f7887`, which was a
stale remote-tracking ref (the workspace had never been fetched since clone). Every security
finding derived from it needed re-checking. Re-verified here against
**`olbrain-studio 8cee761c`** and the other current commits.

---

## 1. Headline: the security posture has materially improved since the stale checkout

`[CODE]` The two-segment catch-all `match /{collection}/{docId}` at `8cee761c` now carries:

| List | Stale `252f7887` | Current `8cee761c` |
|---|---|---|
| **read** exclusions | 9 | **17** |
| **write** exclusions | 24 | **33** |

`[INFERENCE]` Eight collections gained read protection and nine gained write protection between
the two commits. Several are person-keyed stores central to the identity investigation. **Any
statement in an earlier investigation document about catch-all exposure should be re-read against
this list rather than trusted.**

**Current read exclusions (17):** `research_report_shares`, `agentify_sessions`, `brd_shares`,
`memberships_index`, `billing_ledger`, `wallet_grants`, `wallet_recharges`, `agent_user_memory`,
`lead_profiles`, `twilio_accounts`, `agent_datastores`, `superagent_threads`, `lead_contacts`,
`lead_activity`, `lead_exports`, `agent_learned_patterns`, `potions`.

**Current write exclusions (33):** the 17 above plus `research_runs`, `human_agents`,
`app_subscriptions`, `agent_subscriptions`, `organization_subscriptions`, `organizations`,
`outreach_campaigns`, `agent_users`, `research_plans`, `superagent_definitions`,
`superagent_runs`, `superagent_delegations`, `research_chat_sessions`, `knowledge_library`,
`research_golden_templates`, `agent_senders`.

---

## 2. Finding-by-finding

### S1 — `agents/{id}` effective access is broader than intended

**Status: CONFIRMED, unchanged.** `[CODE]` at `olbrain-studio 8cee761c:firestore.rules`.

`agents` appears in **neither** the 17-entry read exclusion list **nor** the 33-entry write
exclusion list of the two-segment catch-all (verified by direct match count: read=0, write=0). The
precise owner rule is therefore OR-superseded, and any authenticated user can read or write any
agent document, including fields that carry `owner_id` / `organization_id`.

`[INFERENCE]` This is now the **most conspicuous remaining gap**, because the collections around it
were tightened while it was not. The rules file documents the exposure itself and explains the
reason — scoping `agents` reads is a much larger change. QF-1's answer attaches the fix to the
ownership move (*"add `agents` to both exclusion lists"*), so the remedy is already routed.

### S2 — Collections readable cross-org because they lack `organization_id`

**Status: PARTIALLY SUPERSEDED — the count and the framing have both moved.** `[CODE]`

The S7 commentary survives at `8cee761c:firestore.rules:831` (*"Sequence: stamp organization_id on
new rows, backfill existing…"*), `:921-922` (*"That is S7 of the Outreach migration"*) and `:930`.
So the underlying mechanism — a rule cannot be org-scoped when the documents carry no
`organization_id` — is unchanged and still documented in-file.

`[INFERENCE]` But the earlier *"~15 collections readable cross-org"* figure was derived from the
stale file and **should not be carried forward**. Eight collections gained read exclusions since,
several of them precisely the PII-bearing ones (`lead_profiles`, `lead_contacts`, `lead_activity`,
`lead_exports`, `agent_learned_patterns`). The residual population is smaller and was **not
recounted here**, because doing so properly requires enumerating every collection reachable by the
catch-all, not just those named in prior documents. `[UNMEASURED]` — recorded as open work.

### S3 — Agents subcollection catch-all

**Status: WITHDRAWN (already corrected in the previous pass).** `[CODE]`
`8cee761c:firestore.rules:1087-1090`:

```
match /agents/{agentId}/{sub}/{rest=**} {
  allow read: if isAuthenticated() && sub != 'mcp_configs';
  allow write: if isAuthenticated() && sub != 'owner_lessons' && sub != 'mcp_configs';
}
```

`mcp_configs` is excluded from reads and writes; `owner_lessons` from writes. The original finding
(*"no exclusion list, covering `mcp_configs`"*) came from the stale commit and is false at HEAD.

### S4 — The secure pattern: explicit deny **plus** catch-all exclusion

**Status: CONFIRMED, and more load-bearing than before.** `[CODE]` Explicit blocks exist at
`8cee761c:firestore.rules:244` (`match /memberships_index/{entryId}`) and `:295`
(`match /organizations/{orgId}/secrets/{document=**}`), and both collections also appear in the
catch-all exclusion lists — the pattern working as designed.

`[INFERENCE]` It remains the correct lens: it is exactly why S1 is still a real exposure (an
explicit rule exists but `agents` is not excluded) and why S3 was false (the exclusion is present).

### S5 — `secrets`, `memberships_index`, `agent_datastores`, `agent_user_memory` protections

**Status: CONFIRMED for all four, with better evidence than before.** `[CODE]`

- `agent_datastores` — in **both** read and write exclusion lists of the two-segment catch-all,
  **and** in both lists of the four-segment catch-all. Client access fully denied.
- `agent_user_memory` — in both read and write exclusion lists.
- `memberships_index` — in both, plus the explicit block at `:244`.
- `organizations/{orgId}/secrets` — explicit block at `:295`, and `organizations` is
  write-excluded from the catch-all.

`[INFERENCE]` Earlier line citations for these (e.g. `:712`, `:745`) were from the stale file and
are wrong; the *conclusions* were right.

### QF-4 / S7 assumptions

**Status: MECHANISM CONFIRMED; the assumption behind the backfill needs correcting.** `[CODE]` The
S7 sequence is still documented in-file at `:831` and `:921-922`: stamp `organization_id` on new
rows, backfill, then move collections into an org-scoped block.

`[INFERENCE]` `person-identity-measurement-pass.md` M1 identified a defect in that sequence: agent
transfer does not re-stamp person-store tenancy, so some `organization_id` values are **already
present and already wrong**. A "fill only missing values" backfill would preserve them and the
subsequent rules tightening would mis-scope those tenants.

`[CODE]` **Severity is bounded by self-healing in both affected stores** — `agent_datastores`
table headers and `agent_user_memory` documents are each re-stamped from live request context on
every durable write. The residue is therefore *quiet tables* and *dormant persons*, not the whole
transferred population. The procedure correction still stands, because those residues never heal
and a skip-if-present backfill would not touch them. Developed in
`s7-backfill-correction-note.md` §2.3 and §5; it corrects the *procedure*, not the S7 goal.

---

## 3. New finding this pass

### S6 (new) — `agent_users` is write-excluded but **not** read-excluded

`[CODE]` `agent_users` appears in the 33-entry **write** exclusion list and **not** in the 17-entry
**read** list at `8cee761c`.

`[INFERENCE]` This matters more than it appears. `agent_users` holds
`(agent_id, channel, channel_user_id)` with the channel identifier **unhashed** — raw phone
numbers, email addresses and Instagram IGSIDs
(`olbrain-agent-runtime 8df0e02:services/firebase_service.py:274-295`). It is the one person-keyed
store that keeps identifiers in the clear, and it is the store
`person-identity-measurement-pass.md` §4 identifies as the migration recovery source *because* it
does so.

Every sibling PII store — `agent_user_memory`, `lead_profiles`, `lead_contacts`, `lead_activity`,
`lead_exports`, `agent_datastores` — is read-excluded. `agent_users` is not. The rules file's own
outreach comment describes `agent_users` as *"end-user names and PHONE NUMBERS … the sibling of
`agent_user_memory`, which is already excluded here as 'end-user PII'"* — written when it was
added to the **write** list.

`[INFERENCE]` The read-side asymmetry looks like the same omission repeating: the collection was
recognised as PII, added to one list, and missed in the other. **This is an awareness finding for
the security owner, not a remediation**, and it should be verified against any client-SDK reader
before action — the earlier S3 episode is a caution against acting on a rules reading without
checking what legitimately depends on it.

---

## 4. Summary table

| ID | Prior status | Status at current HEAD | Verdict |
|---|---|---|---|
| S1 | `agents` in neither exclusion list | Same — read=0, write=0 matches | **Confirmed** |
| S2 | ~15 collections cross-org readable | Mechanism intact; population smaller and uncounted | **Changed — figure withdrawn, `[UNMEASURED]`** |
| S3 | Subcollection catch-all has no exclusions | `mcp_configs` read+write excluded, `owner_lessons` write excluded | **Withdrawn (false)** |
| S4 | Explicit deny + catch-all exclusion | Confirmed at `:244`, `:295` | **Confirmed** |
| S5 | Four collections protected | All four confirmed; line cites corrected | **Confirmed** |
| QF-4/S7 | Stamp → backfill → tighten | Mechanism confirmed; procedure needs M1 correction | **Confirmed with a caveat** |
| **S6** | — | `agent_users` read-exposed while its siblings are not | **New** |

---

## 5. Limitations

1. `[UNMEASURED]` S2's residual population was not recounted. Doing so requires enumerating every
   collection reachable by the catch-all at `8cee761c`, which was out of scope for a
   re-verification pass.
2. `[CODE]` Rules were read statically. No emulator run, no rules-test execution, and no check
   against the repository's own `firestore.*.rules.test.js` suites — which exist
   (`:343` references `firestore.outreach.rules.test.js`) and would be the authoritative check.
3. Findings from other repositories' security posture (e.g. the `olbrain-workflow-runtime`
   override endpoints noted in `d5-authority-research.md` §4.1) are not part of the S-series and
   are recorded there.
4. The three newly cloned repositories were not security-reviewed this pass beyond collection
   inventory; see `new-repo-inventory-closure.md`.
