"""Durable home for commitment events and episode generations. TEST/PROTOTYPE ONLY.

Amendment A1 to the durable-journal contract v1.1
(``investigation/durable-home-episodes-commitments-decision-v1.md``). Both are journal facts in the owning
CUSTOMER subject's partition, written through the unchanged ``TimedJournal`` (journal-assigned commit time, K1;
duplicate before time, K8) over either reference store:

- ``commitment_event``: one sealed ``commitments.Event`` (red-team M-2, C-E). ``idem = cevent:<event_id>``.
  Same id + same content: DUPLICATE. Same id + different content: EVENT_ID_REUSED, decided before anything is
  sealed. The head stays the unchanged pure projection ``commitments.project``.
- ``episode_summary``: one sealed ``EpisodeGeneration``: a recorded summarisation (the generator is
  nondeterministic, so it is replayed, never regenerated). ``idem`` is keyed on the INPUTS (episode, members,
  generator version): a retry with the same inputs returns the recorded generation even if its new text differs.
  The latest generation of an episode (partition order) is served. ``summary_status`` is derived, never stored.

Neither kind is consumed by the claim projection (contract §1: Narrative Memory and commitments establish no
Current State). Fingerprints and seal references are keyed by the subject key, so they become unlinkable after
crypto-shred (§F). Nothing here reads process state: every read is a function of the durable facts at r plus the
existing inputs retrieval already takes (evidence status, undone merges).
"""
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

from .. import commitments as CM
from ..durable_journal import AppendRejected, DurableFacts, Entry, Sealed
from ..ids import _h
from ..model import Episode

COMMITMENT_EVENT, EPISODE_SUMMARY = "commitment_event", "episode_summary"
SUPPRESSED = "context_suppressed"


@dataclass(frozen=True)
class EpisodeGeneration:
    """One recorded summarisation of one episode. Narrative Memory fields per contract §1."""
    episode_id: str
    subject_id: str
    agent_id: str
    tenant_id: str
    evidence_ids: Tuple[str, ...]            # membership (provenance)
    active_at_generation: Tuple[str, ...]    # members whose status was active when this generation was recorded
    started_at: float                        # observed / valid window
    ended_at: Optional[float]
    summary: Optional[str]
    generator_version: str
    merge_ids: Tuple[str, ...] = ()
    security_class: str = "TEST_ONLY_standard"      # T-2: derivation is ENG, the floor is Security [OWNER]
    retention_class: str = "TEST_ONLY_retention"    # B-3 [OWNER]


# ------------------------------------------------------------------------------------------------ identity
def event_idem(event_id: str) -> str:
    return "cevent:" + event_id


def event_ref(subject_key: bytes, e: CM.Event) -> str:
    """Keyed content fingerprint of an event, used as its seal reference."""
    return "ce_" + _h(subject_key, "cevent|v1|" + repr(e))


def generation_key(subject_key: bytes, g: EpisodeGeneration) -> str:
    """Keyed identity of a generation's INPUTS (never its output text): the members, the members that were usable
    (active) when it was generated, and the generator version. A forget_fact changes the usable set, so the
    regeneration it triggers is a new generation; a plain retry is not."""
    return _h(subject_key, "epgen|v1|%s|%s|%s|%s" % (g.episode_id, "|".join(sorted(g.evidence_ids)),
                                                     "|".join(sorted(g.active_at_generation)), g.generator_version))


def generation_idem(subject_key: bytes, g: EpisodeGeneration) -> str:
    return "episode:%s:%s" % (g.episode_id, generation_key(subject_key, g))


def generation_ref(subject_key: bytes, g: EpisodeGeneration) -> str:
    return "eg_" + _h(subject_key, "epgen-content|v1|" + repr(g))


# ------------------------------------------------------------------------------------------------ writes
def _prior(j, subject: str, idem: str) -> Optional[Entry]:
    return next((s.entry for s in j.store.entries(subject) if s.entry.idem == idem), None)


def _commit(j, subject: str, kind: str, idem: str, ref: str, content, clock: float):
    def build(at):
        return [(Entry(subject, kind, idem, at, None, None, None), (subject, ref, content))]
    try:
        return j.commit(subject, idem, None, None, clock, build)
    except AppendRejected as e:
        return ("REJECTED", str(e))                           # e.g. sealing under a destroyed key (§F)


def record_commitment_event(j, subject_key: bytes, e: CM.Event, clock: float,
                            evidence_live: Optional[Callable[[str], bool]] = None):
    """Append one commitment event to its creating subject's partition. Returns the journal's result, or a
    refusal decided before any time is assigned or anything is sealed."""
    if not e.subject_id:
        return ("REJECTED", "identity_required")              # C-E: identity-less commitments never exist
    if evidence_live is not None and not evidence_live(e.evidence_id):
        return ("REJECTED", "evidence_not_live")              # Lane A: every event is backed by live evidence
    idem, ref = event_idem(e.event_id), event_ref(subject_key, e)
    prior = _prior(j, e.subject_id, idem)
    if prior is not None:
        if not isinstance(prior.payload, Sealed) or prior.payload.ref != ref:
            return ("EVENT_ID_REUSED", None)                  # the original fact is untouched
        return ("DUPLICATE", prior.at)
    return _commit(j, e.subject_id, COMMITMENT_EVENT, idem, ref, e, clock)


def record_episode_generation(j, subject_key: bytes, g: EpisodeGeneration, clock: float):
    """Append one generation. The same inputs return the RECORDED generation (DUPLICATE), whatever the new
    output text: recorded-outcome replay for a nondeterministic generator."""
    if not g.subject_id:
        return ("REJECTED", "identity_required")
    idem = generation_idem(subject_key, g)              # the journal decides DUPLICATE on it, before time (K8)
    return _commit(j, g.subject_id, EPISODE_SUMMARY, idem, generation_ref(subject_key, g), g, clock)


# ------------------------------------------------------------------------------------------------ reads at r
def _visible(facts: DurableFacts, subject: str, kind: str, r: float) -> Optional[List[object]]:
    """Readable payloads of ``kind`` committed at or before r, in partition order. None: the partition is erased."""
    stored = [s for s in facts.partitions.get(subject, ()) if s.entry.at <= r]
    if any(s.entry.kind == "erasure" for s in stored):
        return None
    out = []
    for s in stored:
        if s.entry.kind == kind and isinstance(s.entry.payload, Sealed):
            x = facts.vault.get((s.entry.payload.key_id, s.entry.payload.ref))
            if x is not None:                                 # destroyed key: contributes nothing
                out.append(x)
    return out


def commitment_events_at(facts: DurableFacts, subject: str, r: float) -> Tuple[CM.Event, ...]:
    return tuple(_visible(facts, subject, COMMITMENT_EVENT, r) or ())


def commitments_at(facts: DurableFacts, subject: str, r: float,
                   dead_evidence: FrozenSet[str] = frozenset()) -> Dict[str, CM.Head]:
    """The unchanged projection over the partition's events visible at r, with read-time expiry AT r."""
    heads = CM.project(commitment_events_at(facts, subject, r), r, dead_evidence)
    return {k: h for k, h in heads.items() if h.subject_id == subject}


def generations_at(facts: DurableFacts, subject: str, r: float) -> Dict[str, EpisodeGeneration]:
    """The latest generation of each episode visible at r (partition order)."""
    latest: Dict[str, EpisodeGeneration] = {}
    for g in _visible(facts, subject, EPISODE_SUMMARY, r) or ():
        latest[g.episode_id] = g
    return latest


def derive_status(g: EpisodeGeneration, evidence_status: Mapping[str, str],
                  merges_undone: FrozenSet[str] = frozenset()) -> str:
    """Lane A's episode statuses as a pure function of facts (never journaled)."""
    if set(g.merge_ids) & set(merges_undone):
        return "quarantined"                                  # merge undo (runtime: undo_merge)
    if any(evidence_status.get(e) == SUPPRESSED for e in g.active_at_generation):
        return "regenerate_pending"                           # forget_fact suppressed an input after generation
    return "ok" if g.summary else "none"


def episodes_at(facts: DurableFacts, subject: str, r: float, evidence_status: Mapping[str, str],
                merges_undone: FrozenSet[str] = frozenset()) -> Tuple[Episode, ...]:
    """``model.Episode`` objects for the unchanged ``search_memory`` (via ``MemorySource.episodes``)."""
    return tuple(Episode(g.episode_id, g.subject_id, g.agent_id, list(g.evidence_ids), g.started_at, g.ended_at,
                         g.summary, derive_status(g, evidence_status, merges_undone), list(g.merge_ids))
                 for _, g in sorted(generations_at(facts, subject, r).items()))
