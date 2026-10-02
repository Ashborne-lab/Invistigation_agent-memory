"""The logical model (implementation spec §4, §7, §11, §13, §15).

Time is a float number of days. The prototype tests semantics, not
calendars.

Claim content is immutable (``ClaimContent`` is frozen). A claim's
lifecycle is kept separately, in ``ClaimState``.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

INF = float("inf")
NEG_INF = float("-inf")

# Author roles for Evidence.
USER, AGENT, TOOL, OPERATOR_ROLE, IMPORT_ROLE, SYSTEM_ROLE = "user", "agent", "tool", "operator", "import", "system"

# Claim lifecycle statuses. "superseded" is persisted only in persisted mode.
ACTIVE, RETRACTED, INVALIDATED, QUARANTINED, PENDING_ERASURE, SUPERSEDED = (
    "active", "retracted", "invalidated", "quarantined", "pending_erasure", "superseded")
NO_LONGER_TRUE, NEVER_TRUE = "no_longer_true", "never_true"

# Resolution statuses (contract §4).
VALUE, EXPLICIT_NONE, UNKNOWN, CONFLICT, UNAVAILABLE, ACCESS_DENIED = (
    "VALUE", "EXPLICIT_NONE", "UNKNOWN", "CONFLICT", "UNAVAILABLE", "ACCESS_DENIED")


@dataclass
class Evidence:
    evidence_id: str
    org_id: str
    subject_id: str
    source_member_id: str
    agent_id: str
    session_id: str
    author_role: str
    text: str
    observed_at: float
    epochs: Dict[str, int]                      # {"org": n, "subject": n, "session": n}
    merge_ids_at_ingestion: Tuple[str, ...] = ()
    source_system: Optional[str] = None         # for tool evidence, e.g. "BILLING_SYSTEM"
    tool_args: str = ""                         # agent-supplied arguments (echo check)
    status: str = "active"                      # active | invalidated | context_suppressed | pending_erasure | erased
    extraction_state: str = "pending"
    # Red-team additions (R-1, R-2, R-3, R-14). Defaults keep the original atomic ingest() behaviour.
    channel: str = ""
    registered: bool = True                     # PG evidence_meta exists
    bound: bool = True                          # subject/epochs stamped (False = unbound until registration)
    user_key: str = ""                          # what the runtime knew at write time (to resolve late)
    receipt_seq: int = 0                        # evidence-store commit order (server-assigned)
    app_ts: Optional[float] = None              # caller/application clock (may be skewed)
    sealed_hash: Optional[str] = None
    seal_state: str = "sealed"                  # unsealed | sealed | withdrawn | tampered
    dedup_key: Optional[str] = None
    commit_records: List[tuple] = field(default_factory=list)   # LA-1: proposals + decisions kept with evidence


@dataclass(frozen=True)
class ClaimContent:
    """Immutable after commit (spec §7.3)."""
    claim_id: str
    subject_id: str
    source_member_id: str
    org_id: str
    learned_by_agent_id: str
    key: str
    value: Tuple[str, str]           # (kind, canonical value); kind in text|enum|none|number|bool
    source: str                      # USER | OPERATOR | IMPORT | <SYSTEM NAME> | LEGACY_MIGRATION
    assertion_mode: str              # stated | normalized | confirmed | operator | imported | legacy | inferred
    value_check: str                 # verified | unverified
    normaliser_id: Optional[str]
    anchor: Tuple[Tuple[str, str], ...]          # ((evidence_id, quote), ...)
    prompt_ref: Optional[Tuple[str, str]]
    valid_from: Optional[float]
    valid_until: Optional[float]     # the asserted end; None means open
    observed_at: float
    committed_at: float
    extractor_version: str
    policy_version: int
    derivation: str = "orig"         # "orig" | "recovery:<merge_id>"
    observed_seq: int = 0            # R-14 tie-break: evidence-store receipt order
    written_via: str = "llm"         # llm | command | import  (R-16 admission filter)


@dataclass
class Transition:
    at: float
    frm: str
    to: str
    cause: str
    cause_ref: str = ""
    effective_at: Optional[float] = None   # for no_longer_true: the evidence time when the value ended
    merge_ids: Tuple[str, ...] = ()        # set when merge-epoch evidence caused this transition (undo reverses it)


@dataclass
class SupportEdge:
    edge_id: str
    evidence_id: str
    source_class: str
    source_member_id: str
    observed_at: float
    merge_ids: Tuple[str, ...] = ()        # merge-epoch support; see finding F-4


@dataclass
class ClaimState:
    status: str = ACTIVE
    retract_cause: Optional[str] = None
    transitions: List[Transition] = field(default_factory=list)
    support: Dict[str, SupportEdge] = field(default_factory=dict)
    merge_ids: List[str] = field(default_factory=list)
    attributed: bool = True                 # False means quarantined, attributed to no member
    superseded_by: Optional[str] = None     # persisted mode only
    archive_reason: Optional[str] = None


@dataclass
class Claim:
    content: ClaimContent
    state: ClaimState

    @property
    def id(self):
        return self.content.claim_id


@dataclass
class Suppression:
    fingerprint: str
    created_at: float
    observed_before: float


@dataclass
class Episode:
    episode_id: str
    subject_id: str
    agent_id: str
    evidence_ids: List[str]
    started_at: float
    ended_at: Optional[float]
    summary: Optional[str] = None
    summary_status: str = "none"          # none | ok | regenerate_pending | quarantined | pending_erasure
    merge_ids: List[str] = field(default_factory=list)


@dataclass
class SlotResult:
    key: str
    status: str
    value: Optional[Tuple[str, str]] = None
    winning_claim_ids: Tuple[str, ...] = ()
    conflict_claim_ids: Tuple[str, ...] = ()
    freshness_status: str = "FRESH"
    authority_domain: str = ""
    valid_from: Optional[float] = None
    valid_until: Optional[float] = None
    source: Optional[str] = None
    policy_version: int = 0
    state_version: int = 0
    source_position: Optional[float] = None
    note: str = ""
    elements: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = ()   # SET keys: (value, element_status, claim_ids)

    def signature(self):
        """What counts as a 'change' for state_version (spec §13)."""
        return (self.status, self.value, self.winning_claim_ids, self.conflict_claim_ids)


@dataclass
class ErasureRecord:
    record_id: str
    scope: Tuple[str, ...]
    epochs_set: Dict[str, int]
    requested_at: float
    member_set_version: int
    kind: str                         # forget_me | forget_fact | undo | org
    stores_covered: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptManifest:
    manifest_id: str
    render_version: str
    policy_version: int
    member_set_version: int
    slots: Tuple[Tuple[str, int], ...]
    claims: Tuple[Tuple[str, str], ...]
    episodes: Tuple[str, ...]
    tiers_failed: Tuple[str, ...]
    block_hash: str = ""                          # R-22: hash of the rendered block (replay check)
    truncated: Tuple[Tuple[str, int], ...] = ()   # R-12: (tier, omitted count)
    render_mode: str = "quotes"
