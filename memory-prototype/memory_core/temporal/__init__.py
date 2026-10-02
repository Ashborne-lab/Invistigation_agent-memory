"""Temporal primitives (implementation spec §9; contract §4; RECON E12). Pure.

Intervals are half-open: [valid_from, valid_until).
- A claim's lifecycle "as of" a knowledge cutoff is rebuilt from its transitions.
- A retraction with cause ``no_longer_true`` ends the claim at the retraction's
  evidence time. It bounds the claim's interval; it never removes the claim.
"""
from typing import Optional, Tuple

from ..config import Decisions
from ..model import (ACTIVE, INF, INVALIDATED, NEG_INF, NEVER_TRUE, NO_LONGER_TRUE, PENDING_ERASURE, QUARANTINED,
                     RETRACTED, SUPERSEDED, Claim)

EXCLUDED = {INVALIDATED, QUARANTINED, PENDING_ERASURE, "redacted", "pending"}


def status_at(c: Claim, cutoff: float) -> Tuple[str, Optional[str], Optional[float]]:
    """(status, retract_cause, effective_end_from_retraction) as known at ``cutoff``."""
    if c.content.committed_at > cutoff:
        return "not_yet", None, None
    status, cause, eff = ACTIVE, None, None
    for t in c.state.transitions:
        if t.at > cutoff:
            break
        status = t.to
        if t.to == RETRACTED:
            cause = t.cause
            eff = t.effective_at
        elif t.to == ACTIVE:
            cause, eff = None, None
    return status, cause, eff


def eligible_at(c: Claim, cutoff: float, mode: str) -> bool:
    s, cause, _ = status_at(c, cutoff)
    if s == "not_yet" or s in EXCLUDED:
        return False
    if s == RETRACTED and cause == NEVER_TRUE:
        return False
    if s == SUPERSEDED and mode != "persisted":
        return False
    return True


def asserted_interval(c: Claim, d: Decisions) -> Tuple[float, float]:
    vf = c.content.valid_from
    if vf is None:
        vf = NEG_INF if d.null_valid_from == "unbounded_start" else c.content.observed_at
    vu = c.content.valid_until if c.content.valid_until is not None else INF
    return vf, vu


def effective_interval(c: Claim, cutoff: float, d: Decisions, successor_vf: Optional[float] = None
                       ) -> Tuple[float, float]:
    vf, vu = asserted_interval(c, d)
    s, cause, eff = status_at(c, cutoff)
    if s == RETRACTED and cause == NO_LONGER_TRUE and eff is not None:
        vu = min(vu, eff)
    if s == SUPERSEDED and successor_vf is not None:
        vu = min(vu, successor_vf)
    return vf, vu


def covers(iv: Tuple[float, float], t: float) -> bool:
    return iv[0] <= t < iv[1]


def ended_by_retraction(c: Claim, cutoff: float) -> bool:
    s, cause, _ = status_at(c, cutoff)
    return s == RETRACTED and cause == NO_LONGER_TRUE


def freshness(last_confirmed: Optional[float], now: float, freshness_days: Optional[float]) -> str:
    if freshness_days is None or last_confirmed is None:
        return "FRESH"
    return "STALE" if now - last_confirmed > freshness_days else "FRESH"
