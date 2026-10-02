"""CURRENT adapter: today's behaviour at origin/main, so every acceptance test is RED before the fix.

Two kinds of entry, labelled on each function:
- [REAL]      calls the actual origin/main function, loaded read-only by extract.py;
- [MODELLED]  reproduces a traced route handler too heavy to import (FastAPI apps with Firestore/GCP clients),
              with the exact file:line it models. Owners replace a MODELLED entry by pointing the test at their real
              handler (see conftest.py: B0_TARGET=owner).
"""
import asyncio
import sqlite3

from fastapi import HTTPException

import extract as X
from world import Denied

NAME = "current"
_SB = X.studio_backend_auth()           # studio-backend middleware/auth.py
_AD = X.agent_design_auth()             # agent-design app/middleware/auth.py
_ENG = X.engine_auth()                  # agent-engine alchemist/utils/auth.py
_LUMEN = X.engine_bigquery()            # agent-engine lumen bigquery.py + services/bigquery_service.py
_MEMORY_DOC_ID = X.runtime_memory_doc_id()
_GATES = X.engine_olbrain_gates()
_RR_INTERNAL = X.research_is_internal_user()


def _http_to_denied(fn, *a):
    try:
        return fn(*a)
    except HTTPException as e:
        raise Denied("http_%d" % e.status_code)


def _ctx(module, p):
    return module.UserContext(user_id=p.uid, email=p.email, email_verified=p.email_verified, organization_id=p.org,
                              auth_method="api_key" if p.kind == "api_key" else "firebase", permissions=list(p.perms))


# ------------------------------------------------------------------ B0-12
def require_org_access(w, p, org):
    """[REAL] there is no require_org_access today; the only shared check is require_permission (both services)."""
    _http_to_denied(_SB.require_permission, _ctx(_SB, p), "agents:read")
    _http_to_denied(_AD.require_permission, _ctx(_AD, p), "agents:read")


def resource_org(w, kind, rid):
    return (w.agents.get(rid) or {}).get("org") if kind == "agent" else w.projects.get(rid)


def access_org_resource(w, p, kind, rid, body_org=None):
    """[REAL require_permission] + [MODELLED] handlers marked "None" (e.g. agent-design agent.py:563 takes the
    org from the path/body)."""
    require_org_access(w, p, None)
    return body_org or resource_org(w, kind, rid)


# ------------------------------------------------------------------ B0-13 studio-backend
def create_agent(w, p, project_id, body_org=None):
    """[MODELLED] routes/agent_routes.py:65 → services/agent_service.py:115: only API keys are org-checked."""
    _http_to_denied(_SB.require_permission, _ctx(_SB, p), "agents:write")
    org = w.projects.get(project_id)
    if p.kind == "api_key" and p.org != org:
        raise Denied("api_key_project_org_mismatch")
    aid = "agent_new_%d" % (len(w.agents) + 1)
    w.agents[aid] = {"org": org, "owner": p.uid, "project": project_id}
    return aid


def list_forks(w, p, source):
    """[MODELLED] agent_routes.py:128 / agent_service.py:613: no check."""
    return [a for a, d in w.agents.items() if d.get("fork_of") == source]


def fork_preflight(w, p, source, target_project=None):
    """[MODELLED] agent_routes.py:191: no check; leaks source state and target org."""
    src = w.agents[source]
    return {"source_state": "ok", "target_org": w.projects.get(target_project or src["project"])}


def fork_agent(w, p, source, target_project=None):
    """[MODELLED] agent_routes.py:212 / agent_service.py:796-1040 + _extend_knowledge_access (:1255): no check."""
    src = w.agents[source]
    proj = target_project or src["project"]
    aid = "fork_%d" % (len(w.agents) + 1)
    w.agents[aid] = {"org": w.projects[proj], "owner": p.uid, "project": proj, "fork_of": source}
    for doc, allowed in w.knowledge.items():
        if source in allowed:
            allowed.add(aid)
    return aid


# ------------------------------------------------------------------ B0-14 agent-design
def get_agent(w, p, aid):
    """[REAL require_permission] + [MODELLED] services/agent_service.py:~834 `if owner_id != user_id: pass`."""
    _http_to_denied(_AD.require_permission, _ctx(_AD, p), "agents:read")
    return dict(w.agents[aid])


def list_agents(w, p, project_id=None, org=None):
    """[MODELLED] routers/agent.py:172-177 + service 1978-1983: project_id is applied before the key's org."""
    _http_to_denied(_AD.require_permission, _ctx(_AD, p), "agents:read")
    if p.kind == "api_key" and org is None:
        org = p.org
    if project_id:
        return sorted(a for a, d in w.agents.items() if d["project"] == project_id)
    return sorted(a for a, d in w.agents.items() if d["org"] == org)


def active_agents(w, p, org):
    """[MODELLED] routers/agent.py:563-565: only API keys are org-checked."""
    _http_to_denied(_AD.require_permission, _ctx(_AD, p), "agents:read")
    if p.kind == "api_key" and p.org != org:
        raise Denied("api_key_org_mismatch")
    return sorted(a for a, d in w.agents.items() if d["org"] == org)


def agent_user_read(w, p, aid, rid):
    """[MODELLED] routers/agent_user.py:44-161 / services/agent_user_service.py:32-110: no agent/org check."""
    return dict(w.agent_users[rid])


def agent_user_write(w, p, aid, rid, patch):
    w.agent_users.setdefault(rid, {"agent": aid}).update(patch)


def agent_user_delete(w, p, aid, rid):
    del w.agent_users[rid]


def install_blueprint(w, p, project_id):
    """[MODELLED] routers/store.py:95 / store_service.py:124-155: only checks the project exists."""
    if project_id not in w.projects:
        raise Denied("unknown_project")
    return "installed:" + project_id


def store_admin_approve(w, p, submission):
    """[MODELLED] routers/store.py:231-275: `# TODO: Add proper admin role check`."""
    w.submissions[submission] = "approved"


# ------------------------------------------------------------------ B0-15 runtime
def runtime_call(w, key, route, org=None, path_agent=None, header_agent=None):
    """[MODELLED] core/api_key_middleware.py ~515-627 (no scope check); leads guard :479-485 (key_org == org);
    routers/agent_memory.py:48-109 (org compared, path agent not matched to X-Agent-ID / scoped agent)."""
    if org is not None and org != key.org:
        raise Denied("org_mismatch")
    if path_agent is not None and w.agents.get(path_agent, {}).get("org") != key.org:
        raise Denied("agent_not_in_key_org")
    if route.startswith("leads."):
        return list(w.leads.get(key.org, []))
    if route == "memory.delete":
        return "deleted"
    return "ok"


# ------------------------------------------------------------------ B0-16 memory subject
def memory_key(agent, channel, assurance, user_id):
    return _MEMORY_DOC_ID(agent, user_id)              # [REAL] no channel, no assurance


def webhook_memory_lookup(w, caller, agent, user_id, chat_id="c1"):
    """[REAL memory_doc_id] + [MODELLED] agent_webhook.py:2746 / cs_packet_builder.py:1972: user_key = user_id."""
    return w.memory.get(_MEMORY_DOC_ID(agent, user_id))


def channel_memory_lookup(w, agent, channel, user_id):
    return w.memory.get(_MEMORY_DOC_ID(agent, user_id))


def store_verified_memory(w, agent, channel, user_id, content):
    w.memory[_MEMORY_DOC_ID(agent, user_id)] = content


# ------------------------------------------------------------------ B0-17 email
def email_webhook(w, form, auth_secret, agent="agent_A1"):
    """[MODELLED] routers/email.py:67-138: public, no secret, no SPF/DKIM, from_email is the memory key (:311),
    reply-all includes cc (:56-63, :107)."""
    sender = form["from"].strip().lower()
    mem = w.memory.get(_MEMORY_DOC_ID(agent, sender))
    return {"accepted": True, "verified": True, "subject_key": _MEMORY_DOC_ID(agent, sender), "memory": mem,
            "reply_to": [sender] + list(form.get("cc", [])), "memory_in_reply": mem is not None}


# ------------------------------------------------------------------ B0-18 admin
def is_platform_admin(p):
    """[REAL] studio-backend verify_admin_user, with the Firebase verifier replaced by the synthetic principal."""
    async def fake_verify(**kw):
        return _ctx(_SB, p)
    orig = _SB.verify_firebase_token
    _SB.verify_firebase_token = fake_verify
    try:
        asyncio.run(_SB.verify_admin_user(request=None, authorization="Bearer synthetic", x_user_authorization=None))
        return True
    except HTTPException:
        return False
    finally:
        _SB.verify_firebase_token = orig


def engine_admin(p):
    """[REAL] agent-engine routes.py require_olbrain_user with the token verifier injected."""
    _GATES["_verify_firebase_token"] = lambda a, b: {"uid": p.uid, "email": p.email,
                                                     "email_verified": p.email_verified}
    try:
        asyncio.run(_GATES["require_olbrain_user"](authorization="Bearer x", x_user_authorization=None))
        return True
    except HTTPException:
        return False


def research_internal(p):
    """[REAL] research-runtime app/middleware/firebase_auth.py is_internal_user."""
    class U:
        email = p.email
        email_verified = p.email_verified
    return bool(_RR_INTERNAL(U()))


def require_platform_admin(p):
    if not is_platform_admin(p):
        raise Denied("not_platform_admin")


# ------------------------------------------------------------------ B0-19 directives
def send_directive(w, caller, agent, target_user_row, directive):
    """[MODELLED] routers/directives.py:66: in public_endpoints, no auth; any target."""
    w.sent.append((agent, target_user_row, directive))
    return "sent"


# ------------------------------------------------------------------ B0-20 MCP
def mint_binding(w, agent, server, exp_delta=60, org=None):
    return "ignored-by-current-mcp"


def mcp_tools_call(w, env, caller, server, body_agent=None, query_agent=None, binding=None):
    """[REAL] runtime/auth_middleware.py require_auth_enabled/verify_caller semantics + [MODELLED] main.py:2107-2149
    (agent_id from body/query) and _get_credentials_for_server :494-720 (agent KMS, then 'default')."""
    if env.get("MCP_REQUIRE_AUTH", "false").lower() == "true":
        if caller is None or caller.kind != "service" or caller.service_email not in w.services:
            raise Denied("caller_not_allowlisted")
    agent = body_agent if body_agent is not None else (query_agent or "")
    cred = w.mcp_creds.get((agent, server)) if agent else None
    if cred is None:
        cred = w.mcp_creds.get(("default", server))
    return {"agent": agent, "credential": cred}


def mcp_credentials_route(w, service_caller, user, op, agent):
    """[MODELLED] main.py:1558-1577, 1617-1632: agent_id from body/path, no user check."""
    return op + ":" + agent


# ------------------------------------------------------------------ B0-21 Lumen
def lumen_query(w, agent, sql, rows):
    """[REAL] _enforce_agent_id_filter + validate_sql, then the SQL runs over the full (multi-tenant) table."""
    try:
        _LUMEN._enforce_agent_id_filter(sql, agent_id=agent)
        _LUMEN_SVC_VALIDATE(sql)
    except Exception as e:
        raise Denied("rejected:" + type(e).__name__)
    db = sqlite3.connect(":memory:")
    db.execute("create table service_logs(agent_id text, msg text)")
    db.executemany("insert into service_logs values(?,?)", rows)
    return [r[0] for r in db.execute(sql)]


import alchemist.services.bigquery_service as _BQS  # noqa: E402  (loaded by extract.engine_bigquery)
_LUMEN_SVC_VALIDATE = _BQS.validate_sql


# ------------------------------------------------------------------ B0-22 activities
def activity_log(w, p, body_org, actor_id=None, kind="note"):
    """[MODELLED] studio-backend routes/activity_routes.py:55 / activity_service log_activity: org and actor from body."""
    w.activities.append({"org": body_org, "actor": actor_id or p.uid, "kind": kind})


def activity_list(w, p, org):
    """[MODELLED] activity_routes.py ~95 / list_activities: no membership check."""
    return [a for a in w.activities if a["org"] == org]


# ------------------------------------------------------------------ B0-23 share tokens
def share_validate(w, token, session):
    """[MODELLED] share_token_service.validate_share_token: returns the STORED live key; no expiry in channel mode."""
    t = w.share_tokens.get(token) or next((v for v in w.share_tokens.values() if v["short_id"] == token), None)
    if t is None:
        raise Denied("unknown_share_token")
    return {"credential": t["stored_api_key"], "agent": t["agent"], "expires_at": None}


def share_use(w, credential, agent, session, route):
    """[MODELLED] the stored key is an org-bound live key (scoped_agent only): no session binding, no expiry."""
    tok = next((t for t in w.share_tokens.values() if t["stored_api_key"] == credential), None)
    if tok is None:
        raise Denied("unknown_credential")
    if tok["org"] != w.agents.get(agent, {}).get("org"):
        raise Denied("org_mismatch")
    return "ok"


# ------------------------------------------------------------------ B0-24 engine helper
async def engine_require_permission(w, user_id, organization_id, permission):
    """[REAL] alchemist/utils/auth.py require_permission (calls check_permission with 4 args; it takes 3)."""
    await _ENG.require_permission(None, user_id, organization_id, permission)
