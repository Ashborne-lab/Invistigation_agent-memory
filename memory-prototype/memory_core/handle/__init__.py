"""Conversation-bound memory handles (red-team C-4 / R-4). Pure.

A handle is the only thing an agent runtime may present to read person
memory. It binds one conversation: org, agent, session, subject (the
merge root at issue time), the assurance of the binding, the scopes the
Gateway computed from grants, and the member-set version. A handle is a
capability for exactly that conversation, never for "a subject id".

Format: base64(json payload) + "." + HMAC-SHA256(secret, payload).
"""
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import FrozenSet, Optional, Tuple

ASSURANCE_ORDER = {"anonymous": 0, "asserted": 1, "org_signed": 2, "channel_verified": 3}


class HandleError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Handle:
    org: str
    agent: str
    session: str
    subject: str                       # merge root at issue
    assurance: str
    accounts: Tuple[str, ...]          # linked accounts (grant-computed)
    member_set_version: int
    exp: float


def _sign(secret: bytes, body: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def issue(secret: bytes, h: Handle) -> str:
    body = json.dumps(h.__dict__, sort_keys=True).encode()
    return base64.urlsafe_b64encode(body).decode() + "." + _sign(secret, body)


def verify(secret: bytes, token: str, now: float) -> Handle:
    try:
        b64, sig = token.rsplit(".", 1)
        body = base64.urlsafe_b64decode(b64.encode())
    except Exception:
        raise HandleError("malformed")
    if not hmac.compare_digest(_sign(secret, body), sig):
        raise HandleError("bad_signature")
    d = json.loads(body)
    d["accounts"] = tuple(d["accounts"])
    h = Handle(**d)
    if now > h.exp:
        raise HandleError("expired")
    return h


def authorize(h: Handle, *, subject_root: str, subject_org: str, current_msv: int, scope: str,
              target_agent: Optional[str] = None, target_account: Optional[str] = None,
              required_assurance: str = "anonymous") -> None:
    """Raise HandleError unless the handle may read ``scope`` of this target. Pure.

    scope: "person" | "relationship" | "account".
    """
    if subject_org != h.org:
        raise HandleError("cross_org")
    if subject_root != h.subject:
        raise HandleError("wrong_subject")
    if current_msv != h.member_set_version:
        raise HandleError("stale_handle")                 # merge/undo since issue: re-issue per turn
    if ASSURANCE_ORDER[h.assurance] < ASSURANCE_ORDER[required_assurance]:
        raise HandleError("assurance_too_low")
    if scope == "relationship" and target_agent != h.agent:
        raise HandleError("other_agent_relationship")
    if scope == "account" and target_account not in h.accounts:
        raise HandleError("account_not_linked")
