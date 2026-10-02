"""OWNER adapter: olbrain-studio-backend (B0-12, 13, 18, 22, 23).

Every function runs the REAL committed code from branch b0/security (extract.OWNER_REF), loaded into the scratch
tree with only infrastructure stubbed (Firestore client/helpers, storage, activity sink, api-key service). The
World is mapped onto the repo's own dict-backed fake (tests/fake_firestore.py, also loaded from the branch).
Every 401/403 HTTPException is mapped to world.Denied; anything else propagates.

Not provided: share_use — credential ACCEPTANCE is agent-runtime's middleware (C4), not studio-backend code.
"""
import asyncio
import os
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import extract
from world import Denied

NAME = "owner:studio_backend"
REPO = "olbrain-studio-backend"
REF = extract.OWNER_REF

# --------------------------------------------------------------------------- stubs (infrastructure only)
_STUBS = {
    "middleware/request_state.py": "def populate_tenant_id_from_user(*a, **k):\n    return None\n",
    # Firestore helpers delegate to the per-call fake (DB is set by _bind()).
    "services/firestore_service.py": (
        "DB = None\n"
        "def get_firestore_client():\n    return DB\n"
        "def get_document(coll, doc_id):\n"
        "    s = DB.collection(coll).document(doc_id).get()\n"
        "    return s.to_dict() if s.exists else None\n"
        "def server_timestamp():\n    return 'TS'\n"
        "def query_documents_by_field(coll, field, value):\n"
        "    out = []\n"
        "    for s in DB.collection(coll).where(field, 'array_contains', value).stream():\n"
        "        d = s.to_dict(); d.setdefault('id', s.id); out.append(d)\n"
        "    return out\n"),
    "services/firebase_storage.py": "def get_storage_bucket(*a, **k):\n    raise RuntimeError('no storage in tests')\n",
    "services/workflow_storage.py": "def get_shared_workflow_bucket(*a, **k):\n    raise RuntimeError('no storage')\n",
    "services/activity_service.py": (
        "SINK = []\n"
        "async def log_activity(request, auth_user_id=None, **kw):\n"
        "    SINK.append((request, auth_user_id, kw)); return {'success': True, 'message': 'ok'}\n"
        "async def list_activities(**kw):\n"
        "    return {'success': True, 'data': [r for r, _, _ in SINK if r.organization_id == kw.get('organization_id')],"
        " 'total': 0}\n"),
    "services/activity_read_state_service.py": (
        "def mark_activity_read(*a, **k):\n    return None\n"
        "def mark_all_read_for_user(*a, **k):\n    return 0\n"),
    "services/agent_permissions.py": "async def check_edit_permission(*a, **k):\n    return False\n",
    "services/org_roles.py": "def is_org_member(*a, **k):\n    return False\n",
    "services/api_key_service.py": "api_key_service = None\n",
    "services/workflow_share_bundle.py": "def build_share_bundle(*a, **k):\n    return {}\n",
    "models/caller_channel_models.py": "VoiceConfig = dict\n",
}
_REAL = [  # (repo path, scratch path) — real b0/security source
    ("tests/fake_firestore.py", "sbtests/fake_firestore.py"),
    ("middleware/auth.py", "middleware/auth.py"),
    ("services/agent_runtime.py", "services/agent_runtime.py"),
    ("models/activity_models.py", "models/activity_models.py"),
    ("models/agent_models.py", "models/agent_models.py"),
    ("models/api_key_models.py", "models/api_key_models.py"),
    ("models/share_token_models.py", "models/share_token_models.py"),
]
_M = {}


def _mods():
    if not _M:
        for rel, text in _STUBS.items():
            extract._write(rel, text)
        for path, as_rel in _REAL:
            extract.materialise(REPO, path, as_rel, ref=REF)
        _M["fake"] = extract.load(REPO, "tests/fake_firestore.py", "sbtests/fake_firestore.py", ref=REF)
        _M["auth"] = extract.load(REPO, "middleware/auth.py", "middleware/auth.py", ref=REF)
        import importlib
        _M["fs"] = importlib.import_module("services.firestore_service")    # the stub above
        _M["agents"] = extract.load(REPO, "services/agent_service.py", "services/agent_service.py", ref=REF)
        _M["activity"] = extract.load(REPO, "routes/activity_routes.py", "routes/activity_routes.py", ref=REF)
        _M["share"] = extract.load(REPO, "services/share_token_service.py", "services/share_token_service.py",
                                   ref=REF)
        _M["models"] = __import__("models.agent_models", fromlist=["x"])
        _M["amodels"] = __import__("models.activity_models", fromlist=["x"])
    return _M


# --------------------------------------------------------------------------- World <-> fake Firestore
def _db(w):
    docs = {}
    for uid, org in w.index:
        docs["memberships_index/%s_%s" % (uid, org)] = {"user_id": uid, "organization_id": org,
                                                        "roles": [w.roles.get((uid, org), "member")],
                                                        "scope": "organization"}
    for pid, org in w.projects.items():
        docs["projects/" + pid] = {"project_info": {"organization_id": org}}
    for aid, a in w.agents.items():
        d = {"organization_id": a["org"], "owner_id": a["owner"], "project_id": a["project"],
             "lifecycle_state": "active", "basic_info": {"name": aid, "runtime": "conversational"}}
        if a.get("fork_of"):
            d.update(forked_from=a["fork_of"], forked_at="TS")
        docs["agents/" + aid] = d
    for doc, allowed in w.knowledge.items():
        docs["knowledge_library/" + doc] = {"id": doc, "allowed_agents": sorted(allowed)}
    return _mods()["fake"].FakeFirestore(docs)


def _sync_back(w, db):
    for path, d in db.docs.items():
        kind, _, rid = path.partition("/")
        if kind == "agents" and "/" not in rid and rid not in w.agents:
            w.agents[rid] = {"org": d["organization_id"], "owner": d["owner_id"], "project": d["project_id"]}
            if d.get("forked_from"):
                w.agents[rid]["fork_of"] = d["forked_from"]
        if kind == "knowledge_library":
            w.knowledge[rid] = set(d.get("allowed_agents") or [])


@contextmanager
def _bind(w):
    m = _mods()
    db = _db(w)
    m["fs"].DB = db
    with patch.object(m["auth"], "_firestore_db", lambda: db):
        try:
            yield db
        except HTTPException as e:
            if e.status_code in (401, 403):
                raise Denied(str(e.detail))
            raise
        finally:
            _sync_back(w, db)


def _user(p):
    UC = _mods()["auth"].UserContext
    if p.kind == "firebase":
        return UC(p.uid, email=p.email, email_verified=p.email_verified, auth_method="firebase")
    if p.kind == "api_key":
        return UC(p.uid, organization_id=p.org, auth_method="api_key", permissions=list(p.perms))
    return UC(p.uid or "", auth_method=p.kind)          # anonymous / service: not a studio principal


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- B0-12
def require_org_access(w, p, org):
    with _bind(w):
        _mods()["auth"].require_org_access(_user(p), org)


def resource_org(w, kind, rid):
    # [WIRING-ONLY: proven by olbrain-studio-backend tests/test_b0_org_access.py::test_create_agent_in_another_orgs_project_denied]
    # studio-backend resolves the org inline from the server record (agent_service.create_agent / fork_*):
    # project_info.organization_id or organization_id of the project doc; organization_id of the agent doc.
    with _bind(w) as db:
        snap = db.collection({"agent": "agents", "project": "projects"}.get(kind, "?")).document(rid).get()
        if not snap.exists:
            raise Denied("unknown_" + kind)
        d = snap.to_dict()
        return (d.get("project_info") or {}).get("organization_id") or d.get("organization_id")


def access_org_resource(w, p, kind, rid, body_org=None):
    org = resource_org(w, kind, rid)                   # body_org is never consulted
    require_org_access(w, p, org)
    return org


# --------------------------------------------------------------------------- B0-13 (real AgentService)
def _service(db):
    svc = _mods()["agents"].AgentService.__new__(_mods()["agents"].AgentService)
    svc.db = db

    async def _none(*a, **k):
        return []
    # Copy helpers (storage / prompt templates / inbox) are side effects unrelated to authorization;
    # _extend_knowledge_access stays REAL so knowledge inheritance is exercised.
    svc._copy_subcollections = svc._copy_prompt_template = svc._fork_workflow = _none
    svc._provision_agent_email = _none
    return svc


def create_agent(w, p, project_id, body_org=None):
    with _bind(w) as db:
        req = _mods()["models"].AgentCreateRequest(name="new", project_id=project_id)
        return _run(_service(db).create_agent(req, p.uid, user_context=_user(p)))["agent_id"]


def list_forks(w, p, source):
    with _bind(w) as db:
        return [d["id"] for d in _run(_service(db).list_forks(source, user_context=_user(p)))]


def fork_preflight(w, p, source, target_project=None):
    with _bind(w) as db:
        r = _run(_service(db).fork_preflight(source, p.uid, target_project_id=target_project,
                                             user_context=_user(p)))
        return {"source_state": "ok" if r["source_active"] else "inactive", "target_org": r["target_organization_id"]}


def fork_agent(w, p, source, target_project=None):
    with _bind(w) as db:
        req = _mods()["models"].AgentForkRequest(name="fork", target_project_id=target_project)
        return _run(_service(db).fork_agent(source, req, p.uid, user_context=_user(p)))["agent_id"]


# --------------------------------------------------------------------------- B0-18 (real C2 + real verify_admin_user)
def _claims(p):
    c = {"uid": p.uid, "email": p.email, "email_verified": p.email_verified,
         "firebase": {"sign_in_provider": p.provider}}
    if p.hd is not None:
        c["hd"] = p.hd
    if p.admin_claim:
        c["admin"] = True
    return c


def is_platform_admin(p):
    return p.kind == "firebase" and _mods()["auth"].is_platform_admin(_claims(p))


def require_platform_admin(p):
    auth = _mods()["auth"]
    if p.kind != "firebase":
        raise Denied("not_a_firebase_user")
    with patch.object(auth.auth, "verify_id_token", return_value=_claims(p)):
        try:
            _run(auth.verify_admin_user(request=None, authorization="Bearer synthetic", x_user_authorization=None))
        except HTTPException as e:
            if e.status_code in (401, 403):
                raise Denied(str(e.detail))
            raise


# --------------------------------------------------------------------------- B0-22 (real route handlers)
def activity_log(w, p, body_org, actor_id=None, kind="note"):
    m = _mods()
    sink = __import__("services.activity_service", fromlist=["x"]).SINK
    sink.clear()
    body = m["amodels"].LogActivityRequest(activity_type=kind, resource_type="org", organization_id=body_org,
                                           actor_id=actor_id)
    req = SimpleNamespace(headers={}, client=None)
    with _bind(w):
        _run(m["activity"].log_activity(body, req, _user(p)))
    for r, auth_user_id, _ in sink:   # the service records actor_id or the authenticated uid
        w.activities.append({"org": r.organization_id, "actor": r.actor_id or auth_user_id, "kind": kind})


def activity_list(w, p, org):
    with _bind(w):
        _run(_mods()["activity"].list_activities_route(organization_id=org, actor_id=None, resource_type=None,
                                                      resource_id=None, limit=50, offset=0, user=_user(p)))
    return [a for a in w.activities if a["org"] == org]


# --------------------------------------------------------------------------- B0-23 (real ShareTokenService.validate)
def share_validate(w, token, session):
    os.environ.setdefault("SHARE_CREDENTIAL_TTL_SECONDS", "900")       # test configuration (Product decides)
    os.environ.setdefault("SHARE_CHANNEL_TOKEN_MAX_AGE_DAYS", "90")
    from datetime import datetime, timezone
    m = _mods()
    with _bind(w) as db:
        for tid, t in w.share_tokens.items():
            db.collection("share_tokens").document(tid).set({
                "agent_id": t["agent"], "organization_id": t["org"], "token": "st_" + tid,
                "short_id": t["short_id"], "status": "active", "api_key": t["stored_api_key"],
                "created_at": datetime.now(timezone.utc), "expires_at": None})
        svc = m["share"].ShareTokenService.__new__(m["share"].ShareTokenService)
        svc.db = db
        arg = "st_" + token if token in w.share_tokens else token
        real_now = time.time()
        r = _run(svc.validate_share_token(arg, session_id=session))
    if not r.get("valid"):
        raise Denied(r.get("error", "invalid"))
    exp = w.now + (r["expires_at"] - real_now)        # credential expiry mapped onto the World clock
    # The real service mints its own session id (shs_…) and ignores a client-invented one (stricter than C4).
    # The World names sessions by label ("sess_1"); record label <-> server id as a bijective renaming, the same way
    # synthetic uids map onto fake documents. The runtime then compares labels exactly as it would compare ids.
    if not str(r.get("session_id", "")).startswith("shs_"):
        raise Denied("server_did_not_mint_session")
    w.issued[r["credential"]] = {"agent": r["agent_id"], "session": session, "server_session": r["session_id"],
                                 "exp": exp}
    return {"credential": r["credential"], "agent": r["agent_id"], "expires_at": exp}
