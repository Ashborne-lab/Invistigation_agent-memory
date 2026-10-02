"""OWNER adapter: olbrain-research-runtime admin gate (B0-18, contract C2).

REAL code from the committed `b0/security` branch (extract.OWNER_REF): `is_platform_admin` and `is_internal_user`
from app/middleware/firebase_auth.py, taken with extract.function_source (the module imports firebase_admin).
The synthetic Principal is mapped onto the decoded Firebase token the gate reads (FirebaseUser.raw_claims):
email, email_verified, firebase.sign_in_provider = provider, hd, admin = admin_claim.
"""
from types import SimpleNamespace

import extract as X

NAME = "owner:research"
REPO = "olbrain-research-runtime"
REF = X.OWNER_REF
_PATH = "app/middleware/firebase_auth.py"

__all__ = ["research_internal", "is_platform_admin"]

_NS = {}
exec("from __future__ import annotations\nfrom typing import Any\n"
     + X.function_source(REPO, _PATH, "is_platform_admin", ref=REF)
     + X.function_source(REPO, _PATH, "is_internal_user", ref=REF), _NS)


def _decoded_token(p):
    claims = {"email": p.email, "email_verified": p.email_verified,
              "firebase": {"sign_in_provider": p.provider}, "hd": p.hd}
    if p.admin_claim:
        claims["admin"] = True
    return claims


def research_internal(p):
    """REAL is_internal_user on a FirebaseUser-shaped object (uid, org_id, email, raw_claims)."""
    user = SimpleNamespace(uid=p.uid, org_id="org", email=p.email, raw_claims=_decoded_token(p))
    return _NS["is_internal_user"](user)


def is_platform_admin(p):
    return _NS["is_platform_admin"](_decoded_token(p))
