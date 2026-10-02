"""OWNER adapter: olbrain-agent-engine (B0-18, B0-21, B0-24).

Every entry calls REAL code loaded read-only from the committed `b0/security` branch (`extract.OWNER_REF`) via
`extract.materialise` / `extract.function_source`; nothing is re-implemented here. The synthetic World is mapped onto:
- a dict-backed Firestore stand-in exposing only `memberships_index/{uid}_{org}` (B0-24);
- SQLite as the SQL dialect stand-in for BigQuery (B0-21): the REAL builder's output text and bound parameters run
  unchanged against a table holding EVERY tenant's rows. This proves the CTE + parameter filtering, not BigQuery
  semantics; BigQuery verification is the staging procedure in the repo (docs/security/lumen-isolation-staging.md).
- a Firebase decoded-token dict built from the synthetic Principal (B0-18).

Files are materialised under SCRATCH/b0_owner_engine/ (not SCRATCH/alchemist/, which current.py uses for origin/main)
and that root is put first on sys.path, so `alchemist.*` here is the b0/security copy.
"""
import importlib
import os
import sqlite3
import sys
import logging
from typing import Dict, Optional, Tuple

from fastapi import HTTPException

import extract as X
from world import Denied

NAME = "owner:agent_engine"
REPO = "olbrain-agent-engine"
REF = X.OWNER_REF
_ROOT = "b0_owner_engine"

for _path, _stubs in (
        ("alchemist/constants/collections.py", None),
        ("alchemist/utils/auth.py", None),
        ("alchemist/services/bigquery_service.py",
         # stub: the BigQuery client factory (no BigQuery in tests; run_safe_query is never called here)
         {_ROOT + "/alchemist/config/firebase_config.py":
          "def get_bigquery_client():\n    raise RuntimeError('no BigQuery in tests')\n"}),
        ("alchemist/agents/lumen/evidence/bigquery.py", None)):
    X.materialise(REPO, _path, _ROOT + "/" + _path, _stubs, ref=REF)
_owner_root = os.path.join(X.SCRATCH, _ROOT)
if sys.path[0] != _owner_root:
    sys.path.insert(0, _owner_root)
for _m in [m for m in sys.modules if m == "alchemist" or m.startswith("alchemist.")]:
    del sys.modules[_m]
_AUTH = importlib.import_module("alchemist.utils.auth")
_LUMEN = importlib.import_module("alchemist.agents.lumen.evidence.bigquery")

# routes.py is too heavy to import whole: take the three REAL gate functions from b0/security and give them the REAL
# is_platform_admin; only the Firebase signature check (_verify_firebase_token) is replaced by the synthetic token.
_GATES = {"Optional": Optional, "Tuple": Tuple, "Dict": Dict, "Header": lambda *a, **k: None,
          "HTTPException": HTTPException, "logger": logging.getLogger("engine"),
          "is_platform_admin": _AUTH.is_platform_admin}
for _fn in ("require_olbrain_user", "get_metrics_scope", "require_olbrain_identity"):
    exec(X.function_source(REPO, "routes.py", _fn, ref=REF), _GATES)


# ------------------------------------------------------------------ B0-18
def _decoded_token(p):
    """The Firebase decoded ID token a verified principal would present."""
    t = {"uid": p.uid, "email": p.email, "email_verified": p.email_verified,
         "firebase": {"sign_in_provider": p.provider}}
    if p.hd is not None:
        t["hd"] = p.hd
    if p.admin_claim:
        t["admin"] = True
    return t


def is_platform_admin(p):
    """[REAL] alchemist/utils/auth.py is_platform_admin (C2)."""
    if p.kind != "firebase":
        return False                     # only Firebase principals carry a decoded ID token
    return _AUTH.is_platform_admin(_decoded_token(p))


def require_platform_admin(p):
    if not is_platform_admin(p):
        raise Denied("not_platform_admin")


def engine_admin(p):
    """[REAL] routes.py require_olbrain_user (b0/security) with the token verifier injected."""
    import asyncio
    _GATES["_verify_firebase_token"] = lambda a, b: _decoded_token(p)
    try:
        asyncio.run(_GATES["require_olbrain_user"](authorization="Bearer x", x_user_authorization=None))
        return True
    except HTTPException:
        return False


# ------------------------------------------------------------------ B0-21
_VIEW = "synthetic-proj.lumen_isolated.agent_service_logs"


def lumen_query(w, agent, sql, rows):
    """[REAL] build_isolated_query (the function query_service_logs uses), executed on SQLite with all rows."""
    try:
        query, params = _LUMEN.build_isolated_query(sql, agent_id=agent, view=_VIEW)
    except _LUMEN.QueryRejected as e:
        raise Denied("rejected:" + e.code)
    db = sqlite3.connect(":memory:")
    db.execute("create table `%s` (agent_id text, msg text)" % _VIEW)
    db.executemany("insert into `%s` values (?, ?)" % _VIEW, rows)
    return [r[0] for r in db.execute(query, params)]


# ------------------------------------------------------------------ B0-24
class _Snap:
    def __init__(self, data):
        self.exists = data is not None
        self._data = data

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _MembershipsIndexDB:
    """Firestore stand-in: memberships_index/{uid}_{org} = {user_id, organization_id, roles} from World.index/roles."""

    def __init__(self, w):
        self._docs = {"%s_%s" % (u, o): {"user_id": u, "organization_id": o,
                                         "roles": [r for r in [w.roles.get((u, o))] if r]}
                      for (u, o) in w.index}

    def collection(self, name):
        db = self

        class _Coll:
            def document(self, doc_id):
                class _Doc:
                    def get(self):
                        return _Snap(db._docs.get(doc_id) if name == "memberships_index" else None)
                return _Doc()
        return _Coll()


# The acceptance spec names permissions agents:read / agents:write; the repo's vocabulary is agent:view / agent:edit
# (alchemist/utils/auth.py Permissions). Translated here; anything else passes through unchanged (and is denied
# unless the repo's role map grants it).
_PERM = {"agents:read": "agent:view", "agents:write": "agent:edit"}


async def engine_require_permission(w, user_id, organization_id, permission):
    """[REAL] alchemist/utils/auth.py require_permission (b0/security) over the memberships_index stand-in."""
    await _AUTH.require_permission(_MembershipsIndexDB(w), user_id, organization_id,
                                   _PERM.get(permission, permission))
