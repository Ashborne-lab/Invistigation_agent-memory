"""OWNER adapter: olbrain-agent-design (B0-12 agent-design half, B0-14).

Every decision runs REAL code loaded read-only from the committed `b0/security` branch (`extract.OWNER_REF`):
- app/middleware/auth.py (require_org_access, require_agent_view, require_agent_edit, resolve_project_org,
  is_platform_admin, require_platform_admin, verify_firebase_token) and app/services/agent_user_service.py (+ its
  pydantic models) are materialised whole under SCRATCH/b0_owner_agent_design/. `app` is a common top-level name, so
  ours is imported in isolation and whatever was in sys.modules is put back.
- app/services/firestore_service.py is replaced by a stub (the service's db is set per call to the dict fake below).

The World is mapped onto a dict-backed Firestore stand-in: memberships_index/{uid}_{org} rows with
scope "organization" and roles [role]; projects/{p}.project_info.organization_id; agents/{a} with organization_id,
owner_id, project_id; agent_users/{rid} with agent_id. Firebase principals go through the real verify_firebase_token
(firebase_admin.auth.verify_id_token patched to return synthetic claims), so UserContext.claims is the decoded token
C2 sees. API-key principals are built as verify_api_key would build them (org from the key record).
401/403 HTTPException -> world.Denied; anything else propagates.

Heavy handlers (agent_service listing queries, store_service writes) are not imported: their route wiring is marked
[WIRING-ONLY: proven by <repo test>] and each named test exists in olbrain-agent-design@b0/security
(tests/test_b0_org_access.py).
"""
import asyncio
import importlib
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException

import extract as X
from world import Denied

NAME = "owner:agent_design"
REPO = "olbrain-agent-design"
REF = X.OWNER_REF
_ROOT = "b0_owner_agent_design"
_T = "tests/test_b0_org_access.py"

__all__ = ["require_org_access", "access_org_resource", "get_agent", "list_agents", "active_agents",
           "agent_user_read", "agent_user_write", "agent_user_delete", "install_blueprint", "store_admin_approve"]

for _path in ("app/middleware/auth.py", "app/services/agent_user_service.py", "app/models/agent_user_models.py"):
    X.materialise(REPO, _path, _ROOT + "/" + _path, ref=REF)
X._write(_ROOT + "/app/services/firestore_service.py",
         "# STUB: the real module builds a Firestore client; the adapter sets service.db per call.\n"
         "def get_firestore_client():\n    return None\n")
_owner_root = os.path.join(X.SCRATCH, _ROOT)
_saved = {m: sys.modules.pop(m) for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]}
sys.path.insert(0, _owner_root)
_AUTH = importlib.import_module("app.middleware.auth")
_AUS = importlib.import_module("app.services.agent_user_service")
_MODELS = importlib.import_module("app.models.agent_user_models")
_MINE = {m: sys.modules.pop(m) for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]}
sys.path.remove(_owner_root)
sys.modules.update(_saved)
assert _AUS.require_agent_edit is _AUTH.require_agent_edit       # one auth module: the patch below reaches both


# ------------------------------------------------------------------ dict-backed Firestore stand-in
class _Snap:
    def __init__(self, doc_id, data):
        self.id, self._data, self.exists = doc_id, data, data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Doc:
    def __init__(self, db, path):
        self._db, self._path = db, path
        self.id = path.rsplit("/", 1)[1]

    def get(self):
        return _Snap(self.id, self._db.docs.get(self._path))

    def set(self, data):
        self._db.docs[self._path] = dict(data)

    def update(self, data):
        if self._path not in self._db.docs:
            raise KeyError(self._path)
        self._db.docs[self._path].update(data)

    def delete(self):
        self._db.docs.pop(self._path, None)


class _Coll:
    def __init__(self, db, name):
        self._db, self._name = db, name

    def document(self, doc_id=None):
        self._db.n += 1
        return _Doc(self._db, "%s/%s" % (self._name, doc_id or "auto_%d" % self._db.n))


class _DB:
    def __init__(self, docs):
        self.docs, self.n = docs, 0

    def collection(self, name):
        return _Coll(self, name)


def _db(w):
    docs = {}
    for uid, org in w.index:
        docs["memberships_index/%s_%s" % (uid, org)] = {"user_id": uid, "organization_id": org,
                                                        "roles": [w.roles.get((uid, org), "member")],
                                                        "scope": "organization"}
    for pid, org in w.projects.items():
        docs["projects/" + pid] = {"project_info": {"organization_id": org}}
    for aid, a in w.agents.items():
        docs["agents/" + aid] = {"organization_id": a["org"], "owner_id": a["owner"], "project_id": a["project"]}
    for rid, r in w.agent_users.items():
        docs["agent_users/" + rid] = {k: v for k, v in r.items() if k not in ("agent", "org")} | {"agent_id": r["agent"]}
    return _DB(docs)


def _sync_back(w, db):
    rows = {p.split("/", 1)[1]: d for p, d in db.docs.items() if p.startswith("agent_users/")}
    for rid in list(w.agent_users):
        if rid not in rows:
            del w.agent_users[rid]
    for rid, d in rows.items():
        aid = d["agent_id"]
        row = {k: v for k, v in d.items() if k != "agent_id"}
        w.agent_users[rid] = {**row, "agent": aid, "org": w.agents.get(aid, {}).get("org")}


@contextmanager
def _bind(w):
    db = _db(w)
    with patch.object(_AUTH, "_firestore_db", lambda: db):
        try:
            yield db
        except HTTPException as e:
            if e.status_code in (401, 403):
                raise Denied(str(e.detail))
            raise
        finally:
            _sync_back(w, db)


def _claims(p):
    c = {"uid": p.uid, "email": p.email, "email_verified": p.email_verified,
         "firebase": {"sign_in_provider": p.provider}}
    if p.hd is not None:
        c["hd"] = p.hd
    if p.admin_claim:
        c["admin"] = True
    return c


def _user(p):
    if p.kind == "firebase":       # the REAL token path, so UserContext.claims is what C2 receives
        with patch.object(_AUTH.auth, "verify_id_token", return_value=_claims(p)):
            return asyncio.run(_AUTH.verify_firebase_token(authorization="Bearer synthetic", x_user_authorization=None))
    if p.kind == "api_key":        # as verify_api_key builds it: org from the server-side key record
        return _AUTH.UserContext(p.uid, email_verified=True, organization_id=p.org, auth_method="api_key",
                                 permissions=list(p.perms))
    return _AUTH.UserContext(p.uid or "", auth_method=p.kind)     # anonymous / service: not a design principal


def _agent_doc(db, aid):
    snap = db.collection("agents").document(aid).get()
    if not snap.exists:
        raise Denied("unknown_agent")      # the route answers 404 (_load_agent_or_404) before any check
    return snap.to_dict()


def _svc(db):
    s = _AUS.AgentUserService.__new__(_AUS.AgentUserService)
    s.db = db
    return s


# ------------------------------------------------------------------ B0-12 (agent-design copy)
def require_org_access(w, p, org):
    with _bind(w):
        _AUTH.require_org_access(_user(p), org)


def access_org_resource(w, p, kind, rid, body_org=None):
    with _bind(w) as db:                   # body_org is never consulted: the org comes from the server record
        if kind == "project":
            org = _AUTH.resolve_project_org(rid)
        elif kind == "agent":
            org = _agent_doc(db, rid).get("organization_id")
        else:
            raise Denied("unknown_resource_kind")
        _AUTH.require_org_access(_user(p), org)
        return org


# ------------------------------------------------------------------ B0-14
def get_agent(w, p, aid):
    # [WIRING-ONLY: proven by olbrain-agent-design tests/test_b0_org_access.py::test_get_agent_cross_org_denied_firebase_and_key]
    # GET /api/agents/{id}: _load_agent_or_404 then the REAL require_agent_view below; agent_service.get_agent
    # (workflow-status enrichment) runs only after it passes.
    with _bind(w) as db:
        agent = _agent_doc(db, aid)
        _AUTH.require_agent_view(_user(p), agent, aid)
    return dict(w.agents[aid])


def list_agents(w, p, project_id=None, org=None):
    # [WIRING-ONLY: proven by olbrain-agent-design tests/test_b0_org_access.py::test_list_agents_by_project_cross_org_denied]
    # GET /api/agents?project_id=: the REAL resolve_project_org + require_org_access run before
    # agent_service.list_agents, whose Firestore query (project_id / organization_id filter) is mirrored here.
    with _bind(w):
        if project_id:
            org = _AUTH.resolve_project_org(project_id)
        _AUTH.require_org_access(_user(p), org)
    return sorted(a for a, d in w.agents.items() if d["org"] == org and (not project_id or d["project"] == project_id))


def active_agents(w, p, org):
    # [WIRING-ONLY: proven by olbrain-agent-design tests/test_b0_org_access.py::test_active_agents_requires_org_membership]
    # GET /api/agents/organization/{org}/active: REAL require_org_access, then agent_service.get_active_agents (the
    # org-filtered query is mirrored here).
    with _bind(w):
        _AUTH.require_org_access(_user(p), org)
    return sorted(a for a, d in w.agents.items() if d["org"] == org)


def agent_user_read(w, p, aid, rid):
    # agent-design has NO agent_users read route; the REAL row gate (agent from the row, then view) is used.
    # The (aid, row) pairing is checked here because no agent-design route carries an agent id with a row id.
    with _bind(w) as db:
        row = asyncio.run(_svc(db).authorize_row(_user(p), rid, edit=False))
    if row.get("agent_id") != aid:
        raise Denied("row_not_under_agent")
    return {**{k: v for k, v in row.items() if k != "agent_id"}, "agent": row["agent_id"],
            "org": w.agents[row["agent_id"]]["org"]}


def agent_user_write(w, p, aid, rid, patch_):
    with _bind(w) as db:
        svc, user = _svc(db), _user(p)
        if rid in w.agent_users:           # REAL update_user (agent derived from the row, edit check inside)
            if w.agent_users[rid]["agent"] != aid:
                raise Denied("row_not_under_agent")
            asyncio.run(svc.update_user(rid, _MODELS.AgentUserUpdateRequest(**patch_), user))
        else:                              # REAL create_user (agent from the body, edit check inside)
            req = _MODELS.AgentUserCreateRequest(agent_id=aid, channel=patch_.get("channel", "web"))
            asyncio.run(svc.create_user(req, user))


def agent_user_delete(w, p, aid, rid):
    with _bind(w) as db:
        if w.agent_users.get(rid, {}).get("agent") not in (None, aid):
            raise Denied("row_not_under_agent")
        asyncio.run(_svc(db).delete_user(rid, _user(p)))


def install_blueprint(w, p, project_id):
    # [WIRING-ONLY: proven by olbrain-agent-design tests/test_b0_org_access.py::test_install_blueprint_into_other_org_project_denied]
    # store_service.install_blueprint resolves the project's org from projects/{id} and calls the REAL
    # require_org_access below before any write.
    with _bind(w):
        _AUTH.require_org_access(_user(p), _AUTH.resolve_project_org(project_id))
    return "installed:" + project_id


def store_admin_approve(w, p, submission):
    # [WIRING-ONLY: proven by olbrain-agent-design tests/test_b0_org_access.py::test_store_admin_routes_require_platform_admin]
    # POST /api/v1/store/admin/submissions/{id}/approve calls the REAL require_platform_admin (C2) on the
    # verified token's claims before store_service.approve_submission.
    try:
        _AUTH.require_platform_admin(_user(p))
    except HTTPException as e:
        if e.status_code in (401, 403):
            raise Denied(str(e.detail))
        raise
    w.submissions[submission] = "approved"
