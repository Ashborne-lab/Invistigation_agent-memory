"""Explicit, switchable architecture decisions (implementation spec §26).

Each field names either a decision that is still open or one Jay has
settled. The defaults are the spec's provisional choices. Tests run both
settings where practical, so the effect of each decision can be seen.
"""
from dataclasses import dataclass, replace
from typing import Optional

UNSET = None


@dataclass(frozen=True)
class Decisions:
    # M27 / spec §8.1: "read_time" (spec default) | "persisted" (the alternative).
    supersession_storage_mode: str = "read_time"
    # D15. Only "fail_closed" is implementable without a decision on moving evidence.
    transfer_policy: str = "fail_closed"
    # R6b is settled (Option B). This flag is kept so a test can show the
    # failure mode when it is switched off.
    pending_erasure_enabled: bool = True
    # Spec §26 conflict 3 / PI-3.
    phone_email_memory_keys: bool = False
    # R-M1: "reject" (no persisted inference) | "store_labelled".
    r_m1_inference: str = "reject"
    # R-M2: learned patterns are out of prototype scope. Recorded only.
    r_m2_learned_patterns: str = "UNSET"
    # R-M3. Physical deletion uses the archive window below.
    r_m3_retention: str = "UNSET"
    # R-M4: "org_members" (today's audience) | "named_role".
    r_m4_memory_read_roles: str = "org_members"
    # Legal / R-M3: ERASURE_ARCHIVE_WINDOW in days. UNSET means physical deletion never runs.
    erasure_archive_window_days: Optional[float] = UNSET
    # O11, injectable: "equal_to_user" | "above_user" | "below_user".
    operator_rank: str = "equal_to_user"
    # T4 / RECON §8.4 #4: "per_member" | "per_person".
    member_support_counting: str = "per_member"
    # §9.5: "unbounded_start" | "from_observed".
    null_valid_from: str = "unbounded_start"
    # Case 15: "evidence_before" (a suppression blocks older evidence only) | "forever".
    suppression_scope: str = "evidence_before"
    # Prototype finding F-1: which claims the soft value check may accept as unverified.
    # "any" = the spec as written; "cross_script_only" = the proposed amendment.
    unverified_scope: str = "any"
    # Prototype finding F-3: include the derivation context in the claim id
    # (the spec formula leaves it out).
    claim_id_derivation_tag: bool = False
    # Prototype finding F-2: which interval of the later claim supersedes.
    # "asserted" (a later claim's own asserted interval) | "effective_overlap" (literal E7 wording).
    supersession_interval: str = "asserted"
    # Findings F-4, F-6, F-7 and F-8. Defaults reproduce the spec as written; the "amended" config turns them on.
    dedup_scope: str = "any"                      # "any" (spec §6.1 step 10) | "same_source_group" (F-6)
    retract_observed_before: bool = False         # F-7: a retraction only reaches claims observed at or before it
    retract_same_group: bool = False              # F-8: a retraction only reaches the same source group (R2)
    undo_reverses_merge_support: bool = False     # F-4: undo removes support edges added by merge-epoch evidence

    # ---- Red-team resolutions (memory-architecture-v2-red-team.md). Defaults reproduce the defect. ----
    # C-1: when are subject/epoch/merge stamps taken? "registration" (v2 as written: PG step, possibly late)
    # | "write" (R-1: inside the evidence-store transaction, atomic with the message).
    stamp_at: str = "registration"
    # C-2 / R-2 / R-24: evidence must be sealed (keyed hash over role|author|channel|content) before extraction.
    require_seal: bool = False
    # C-3 / R-3: provider-message-id dedup inside the write transaction.
    inbound_dedup: bool = False
    # C-4 / R-4: "caller_org" (v2: any same-org caller may name any subject) | "handle" (conversation-bound).
    read_auth: str = "caller_org"
    # C-5 / R-5: who may write account.* claims. "any" (v2) | "authoritative" (operator/import/CRM only).
    account_sources: str = "any"
    # C-6 / R-6: derived writers (judges, dispositions, lead capture) go through the stamp fence + registry.
    derived_writes_fenced: bool = False
    # C-9 / R-9: re-extraction by a new extractor version supersedes the old derivation of the same evidence.
    reextract_supersede: bool = False
    # M-4 / R-12 / R-25: "quotes" (v2 + F-9 'said: <quote>') | "structured" (no quotes, sanitised, capped).
    render_mode: str = "quotes"
    narratives_in_prompt: bool = True             # R-25: off by default in customer prompts
    tier_caps: tuple = (0, 0)                      # (T0, T1) item caps; 0 = uncapped. [UNMEASURED]
    # M-6 / R-14: ordering source for knowledge time. "app_clock" (caller-supplied timestamp) | "receipt".
    order_by: str = "app_clock"
    # M-7 / R-15: reject current-state assertions with a future/intent marker and no future validity.
    future_marker_rule: bool = False
    # M-8 / R-16: apply the CURRENT policy's admission rules at read time.
    policy_admission_filter: bool = False
    # M-9 / R-17: "none" (search reads claims directly) | "projection_trusted" (stale index served as-is)
    # | "projection_revalidated" (index gives ids; every hit re-checked against the system of record).
    search_index: str = "none"
    # M-11 / R-19: search maps query tokens through the gate's normaliser (cross-script).
    search_normalised: bool = False
    # M-13 / R-21: "op_order" (each operation locks in its own order) | "ascending" (global order).
    lock_order: str = "op_order"
    # M-3 / R-11: Agent Knowledge.
    candidates_in_prompt: bool = True
    knowledge_min_contributors: int = 1            # k. [UNMEASURED]; owner-set per org
    knowledge_erasure_handler: bool = False
    # M-2 / R-10: commitments as "mutable_row" (v2) | "event_log" (evidence-backed events + projection).
    commitment_model: str = "mutable_row"
    # Lane A finding LA-1 (restore): replay of the gap re-decides identity ("redecide") or applies the
    # identity decision recorded at commit time ("recorded").
    replay_identity: str = "redecide"
    # Red-team M-5 / MAP N1: identity assurance. False = the memory key has no channel/assurance component
    # (an asserted id loads the verified person's memory). True = asserted ids bind to isolated endpoints.
    identity_assurance: bool = False
    # Red-team C-7: physical deletion also covers v2's own stores (search projection, manifests linkage,
    # derived artifacts, knowledge lineage, commitment events).
    registry_covers_v2_stores: bool = False
    # Lane A finding LA-3: which merges are "in force" for a subject at ingestion. "tree" (as implemented
    # from E3: every merge applied to the survivor's tree, kept incrementally) goes stale after a partial
    # undo of a chained merge and quarantines an independent subject's own claims. "path": the non-undone
    # merges on the subject's current path to its root, recomputed from the identity graph.
    merge_ids_basis: str = "tree"
    # Lane A finding LA-9: retractions as records applied to every matching claim of the same group observed at
    # or before them, independent of commit order (out-of-order extraction otherwise escapes a retraction).
    retraction_records: bool = False
    # Lane A finding LA-11: "support_folding" (spec §6.1 step 10: a re-assertion becomes a support edge of an
    # existing claim) makes history depend on commit order under out-of-order extraction. "per_evidence": a claim
    # is one evidence-anchored assertion; dedup and reconfirmation (freshness) are computed at read time.
    dedup_mode: str = "support_folding"
    # Lane A finding LA-13 (real-model run): models anchor retractions/re-assertions to OLD context messages,
    # which collapses history (a retraction anchored on the claim's own message ends it at its start).
    # True: assertion/retraction anchors must be evidence of the job being extracted (the new turn);
    # context evidence may only be a prompt_ref.
    anchor_pending_only: bool = False
    # Lane A finding LA-14 (real-model run): a cross-script value the deterministic normaliser cannot map (gazetteer
    # coverage) is downgraded to an UNVERIFIED claim (memory only, never current state) instead of being lost.
    normalized_fallback_unverified: bool = False
    # Finding F-9 (prototype) / v2 §E: unverified claims of current-state keys appear in the MEMORY tier,
    # labelled "unverified, not current" (never as current state).
    render_unverified_registered: bool = False
    # Lane A finding LA-16 (real-model run): models retract the old value of a single-value key in the same
    # message that asserts the new one. That explicit retraction defeats read-time supersession (a later
    # never_true of the new value cannot revive the old one). True: such replacement retractions are dropped.
    drop_replacement_retractions: bool = False
    # Lane A finding LA-18 (real-model run): stated values are canonicalised through the key's normaliser
    # ("Gurgaon" -> "Gurugram"), otherwise synonyms become different values (false CONFLICT, wrong supersession).
    canonicalise_values: bool = False


DEFAULT = Decisions()
_F = dict(unverified_scope="cross_script_only", claim_id_derivation_tag=True, dedup_scope="same_source_group",
          retract_observed_before=True, retract_same_group=True, undo_reverses_merge_support=True)
# The reviewed architecture: prototype findings F-* plus red-team resolutions R-*.
AMENDED = Decisions(**_F, stamp_at="write", require_seal=True, inbound_dedup=True, read_auth="handle",
                    account_sources="authoritative", derived_writes_fenced=True, reextract_supersede=True,
                    render_mode="structured", narratives_in_prompt=False, tier_caps=(20, 30), order_by="receipt",
                    future_marker_rule=True, policy_admission_filter=True, search_index="projection_revalidated",
                    search_normalised=True, lock_order="ascending", candidates_in_prompt=False,
                    knowledge_min_contributors=3, knowledge_erasure_handler=True, commitment_model="event_log",
                    replay_identity="recorded", identity_assurance=True, registry_covers_v2_stores=True,
                    merge_ids_basis="path", retraction_records=True, dedup_mode="per_evidence",
                    anchor_pending_only=True, normalized_fallback_unverified=True,
                    render_unverified_registered=True, drop_replacement_retractions=True,
                    canonicalise_values=True, null_valid_from="from_observed")   # LA-19 (spec §9.5)
# F-* only (the previous "amended" config), kept so older benchmark results stay comparable.
F_ONLY = Decisions(**_F)


def with_(d: Decisions, **kw) -> Decisions:
    return replace(d, **kw)
