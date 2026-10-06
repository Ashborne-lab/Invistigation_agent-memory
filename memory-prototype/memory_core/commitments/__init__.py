"""Commitments (red-team M-2 / R-10). Pure.

Two models, so the defect and the fix can be compared:

- ``MutableRow``: v2 as written. A row with a ``state`` that typed commands
  and an expiry job overwrite in arrival order. Creation is not idempotent.
- ``project(events, now)``: the reviewed model. An append-only,
  evidence-backed event log, plus a projection that is a pure function of
  the event SET (sorted by (at, event_id)). Creation is idempotent on an
  action key, expiry is computed at read time from ``due_until``, terminal
  states accept only an operator ``reopened``, and an external system's
  status change is mirrored with freshness.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

PROPOSED, CONFIRMED, IN_PROGRESS, FULFILLED, CANCELLED, EXPIRED, BREACHED = (
    "proposed", "confirmed", "in_progress", "fulfilled", "cancelled", "expired", "breached")
TERMINAL = {FULFILLED, CANCELLED}

# event kinds -> (allowed from-states, to-state). None = any non-terminal state.
_T = {
    "create": ((), PROPOSED),
    "confirm_tool_success": ((PROPOSED,), CONFIRMED),
    "confirm_assent": ((PROPOSED,), CONFIRMED),
    "start": ((CONFIRMED,), IN_PROGRESS),
    "fulfil": ((CONFIRMED, IN_PROGRESS), FULFILLED),
    "cancel": (None, CANCELLED),
    "external_cancelled": (None, CANCELLED),
    "reopen_operator": ((FULFILLED, CANCELLED), CONFIRMED),
}
_AUTH = {"confirm_tool_success": {"tool"}, "confirm_assent": {"user"}, "reopen_operator": {"operator"},
         "external_cancelled": {"external"}, "create": {"agent", "tool", "operator"},
         "start": {"agent", "tool", "operator"}, "fulfil": {"tool", "operator", "external"},
         "cancel": {"user", "operator", "tool", "agent"}}


@dataclass(frozen=True)
class Event:
    event_id: str
    commitment_key: str          # idempotency key: hmac(relationship, kind, due window, action fingerprint)
    kind: str
    at: float
    actor: str                   # user | agent | tool | operator | external | clock
    evidence_id: str             # every event is backed by evidence (C-8: commands are evidence)
    due_until: Optional[float] = None
    external_ref: Optional[str] = None
    # C-E (target architecture): explicit identity. Whether a commitment is CUSTOMER- or relationship-scoped is
    # an open Product/Security decision; these fields make either enforceable without a second model.
    subject_id: str = ""
    agent_id: str = ""
    tenant_id: str = ""


@dataclass
class Head:
    commitment_key: str
    state: str
    due_until: Optional[float]
    external_ref: Optional[str]
    last_external_at: Optional[float]
    events: Tuple[str, ...]
    rejected: Tuple[Tuple[str, str], ...] = ()
    subject_id: str = ""
    agent_id: str = ""
    tenant_id: str = ""


def project(events: Iterable[Event], now: float, dead_evidence: frozenset = frozenset()) -> Dict[str, Head]:
    """Pure projection. Depends only on the SET of events (delivery order is irrelevant)."""
    by_key: Dict[str, List[Event]] = {}
    seen = set()
    for e in events:
        if e.event_id in seen:
            continue                                  # duplicate delivery
        seen.add(e.event_id)
        by_key.setdefault(e.commitment_key, []).append(e)
    out = {}
    for k, evs in by_key.items():
        evs.sort(key=lambda e: (e.at, e.event_id))
        h: Optional[Head] = None
        rej = []
        for e in evs:
            if e.evidence_id in dead_evidence:
                rej.append((e.event_id, "evidence_erased"))
                continue
            frm, to = _T.get(e.kind, (None, None))
            if to is None or e.actor not in _AUTH.get(e.kind, set()):
                rej.append((e.event_id, "unauthorised_or_unknown"))
                continue
            if e.kind == "create":
                if h is None:                         # idempotent: a second create is a no-op
                    h = Head(k, PROPOSED, e.due_until, e.external_ref, None, (e.event_id,),
                             subject_id=e.subject_id, agent_id=e.agent_id, tenant_id=e.tenant_id)
                continue
            if h is None:
                rej.append((e.event_id, "no_commitment"))
                continue
            if (e.subject_id, e.agent_id, e.tenant_id) != (h.subject_id, h.agent_id, h.tenant_id):
                rej.append((e.event_id, "identity_mismatch"))   # C-E: one commitment, one identity
                continue
            cur = h.state
            if cur in TERMINAL and e.kind != "reopen_operator":
                rej.append((e.event_id, "terminal"))
                continue
            if frm is not None and cur not in frm:
                rej.append((e.event_id, "illegal_from_" + cur))
                continue
            h.state = to
            h.events += (e.event_id,)
            if e.actor == "external" or e.kind == "confirm_tool_success":
                h.last_external_at = e.at
            if e.external_ref:
                h.external_ref = e.external_ref
        if h is not None:
            # read-time expiry: no job, no race (M-2 scenario c)
            if h.state in (PROPOSED, CONFIRMED, IN_PROGRESS) and h.due_until is not None and now >= h.due_until:
                h.state = EXPIRED
            h.rejected = tuple(rej)
            out[k] = h
    return out


@dataclass
class MutableRow:
    """v2 as written: one row per create, overwritten in arrival order (the defect model)."""
    rows: Dict[str, dict] = field(default_factory=dict)
    n: int = 0

    def apply(self, e: Event, now: float):
        if e.kind == "create":
            self.n += 1                                # not idempotent: duplicate assent -> second row
            self.rows["row%d" % self.n] = {"key": e.commitment_key, "state": PROPOSED, "due": e.due_until}
            return
        to = _T.get(e.kind, (None, None))[1]
        for r in self.rows.values():
            if r["key"] == e.commitment_key and to:
                r["state"] = to                        # last writer wins, no terminal rule

    def expire_job(self, now: float):
        for r in self.rows.values():
            if r["due"] is not None and now >= r["due"] and r["state"] in (PROPOSED, CONFIRMED, IN_PROGRESS):
                r["state"] = EXPIRED

    def states(self, key: str) -> List[str]:
        return sorted(r["state"] for r in self.rows.values() if r["key"] == key)
