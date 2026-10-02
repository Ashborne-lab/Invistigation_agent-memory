"""REFERENCE adapter: the B0 fixes as an executable specification (memory-lane-b-security-b0-v1.md §A.2).

This is not production code and is not meant to be copied verbatim: it pins the BEHAVIOUR the owning repository
must reproduce. Each function names the finding it specifies. Every refusal raises world.Denied (explicit).
"""
import base64
import hashlib
import hmac
import json
import sqlite3

from fastapi import HTTPException

from world import Denied

NAME = "reference"
SHARE_TTL = 900                     # seconds; short-lived exchanged share credential [UNMEASURED: owner sets]
SHARE_ROUTES = {"webhook", "upload_attachment", "feedback", "session_insights"}
ROUTE_SCOPE = {"webhook": "agents:invoke", "feedback": "agents:invoke", "leads.list": "leads:read",
               "leads.export": "leads:read", "leads.import": "leads:write", "leads.erase": "leads:write",
               "memory.read": "agents:read", "memory.delete": "agents:write"}
EDIT_ROLES = {"owner", "super_admin", "admin", "editor"}


# ------------------------------------------------------------------ B0-12 require_org_access + server-derived org
def require_org_access(w, p, org):
    if not org:
        raise Denied("no_org")
    if p.kind == "api_key":
        if p.org != org:
            raise Denied("api_key_org_mismatch")
        return
    if p.kind == "firebase":
        if (p.uid, org) not in w.index:
            raise Denied("not_a_member")
        return
    raise Denied("principal_not_allowed")


def resource_org(w, kind, rid):
    if kind == "agent":
        a = w.agents.get(rid)
        if a is None:
            raise Denied("unknown_agent")
        return a["org"]
    if kind == "project":
        if rid not in w.projects:
            raise Denied("unknown_project")
        return w.projects[rid]
    raise Denied("unknown_resource_kind")


def access_org_resource(w, p, kind, rid, body_org=None):
    org = resource_org(w, kind, rid)          # the body's org is never consulted
    require_org_access(w, p, org)
    return org


def _require_view(w, p, aid):
    a = w.agents.get(aid)
    if a is None:
        raise Denied("unknown_agent")
    if p.kind == "firebase" and a["owner"] == p.uid:
        return a
    require_org_access(w, p, a["org"])
    return a


def _require_edit(w, p, aid):
    a = _require_view(w, p, aid)
    if p.kind == "firebase" and a["owner"] != p.uid and w.roles.get((p.uid, a["org"])) not in EDIT_ROLES:
        raise Denied("not_an_editor")
    return a


# ------------------------------------------------------------------ B0-13 studio-backend create / fork
def create_agent(w, p, project_id, body_org=None):
    org = resource_org(w, "project", project_id)
    require_org_access(w, p, org)
    aid = "agent_new_%d" % (len(w.agents) + 1)
    w.agents[aid] = {"org": org, "owner": p.uid, "project": project_id}
    return aid


def list_forks(w, p, source):
    _require_view(w, p, source)
    return [a for a, d in w.agents.items() if d.get("fork_of") == source]


def fork_preflight(w, p, source, target_project=None):
    src = _require_view(w, p, source)
    target_org = resource_org(w, "project", target_project or src["project"])
    require_org_access(w, p, target_org)
    return {"source_state": "ok", "target_org": target_org}


def fork_agent(w, p, source, target_project=None):
    src = _require_view(w, p, source)
    proj = target_project or src["project"]
    target_org = resource_org(w, "project", proj)
    require_org_access(w, p, target_org)
    aid = "fork_%d" % (len(w.agents) + 1)
    w.agents[aid] = {"org": target_org, "owner": p.uid, "project": proj, "fork_of": source}
    for doc, allowed in w.knowledge.items():               # knowledge follows only a permitted source
        if source in allowed:
            allowed.add(aid)
    return aid


# ------------------------------------------------------------------ B0-14 agent-design
def get_agent(w, p, aid):
    return dict(_require_view(w, p, aid))


def list_agents(w, p, project_id=None, org=None):
    if project_id:
        org = resource_org(w, "project", project_id)
    require_org_access(w, p, org)
    return sorted(a for a, d in w.agents.items() if d["org"] == org and (not project_id or d["project"] == project_id))


def active_agents(w, p, org):
    require_org_access(w, p, org)
    return sorted(a for a, d in w.agents.items() if d["org"] == org)


def agent_user_read(w, p, aid, rid):
    _require_view(w, p, aid)
    row = w.agent_users.get(rid)
    if row is None or row["agent"] != aid:
        raise Denied("row_not_under_agent")
    return dict(row)


def agent_user_write(w, p, aid, rid, patch):
    _require_edit(w, p, aid)
    row = w.agent_users.get(rid)
    if row is not None and row["agent"] != aid:
        raise Denied("row_not_under_agent")
    w.agent_users.setdefault(rid, {"agent": aid, "org": w.agents[aid]["org"]}).update(patch)


def agent_user_delete(w, p, aid, rid):
    _require_edit(w, p, aid)
    row = w.agent_users.get(rid)
    if row is None or row["agent"] != aid:
        raise Denied("row_not_under_agent")
    del w.agent_users[rid]


def install_blueprint(w, p, project_id):
    org = resource_org(w, "project", project_id)
    require_org_access(w, p, org)
    return "installed:" + project_id


def store_admin_approve(w, p, submission):
    if not is_platform_admin(p):
        raise Denied("not_platform_admin")
    w.submissions[submission] = "approved"


# ------------------------------------------------------------------ B0-15 runtime API-key route scope
def runtime_call(w, key, route, org=None, path_agent=None, header_agent=None):
    if key.kind != "api_key":
        raise Denied("api_key_required")
    if key.share_token and route not in SHARE_ROUTES:
        raise Denied("share_key_route_not_allowed")
    if ROUTE_SCOPE.get(route) not in key.perms:
        raise Denied("missing_scope")
    if org is not None and org != key.org:
        raise Denied("org_mismatch")
    if path_agent is not None:
        if w.agents.get(path_agent, {}).get("org") != key.org:
            raise Denied("agent_not_in_key_org")
        if header_agent is not None and path_agent != header_agent:
            raise Denied("path_agent_header_mismatch")
        if key.scoped_agent and path_agent != key.scoped_agent:
            raise Denied("agent_outside_key_scope")
    if route.startswith("leads."):
        return list(w.leads.get(key.org, []))
    if route == "memory.delete":
        return "deleted"
    return "ok"


# ------------------------------------------------------------------ B0-16 memory subject selection
def memory_key(agent, channel, assurance, user_id):
    return "%s__%s" % (agent, hashlib.sha256(("%s|%s|%s" % (channel, assurance, user_id.strip().lower()))
                                              .encode()).hexdigest()[:32])


def webhook_memory_lookup(w, caller, agent, user_id, chat_id="c1"):
    """The webhook (API-key / share) path: the caller's asserted user_id is an ASSERTED identity."""
    if caller.share_token:
        user_id = "share_%s_%s" % (caller.share_token, chat_id)       # never caller-chosen
    key = memory_key(agent, "api:%s" % caller.key_id, "asserted", user_id)
    return w.memory.get(key)


def channel_memory_lookup(w, agent, channel, user_id):
    """A channel-verified path (e.g. WhatsApp sender verified by Meta)."""
    return w.memory.get(memory_key(agent, channel, "channel_verified", user_id))


def store_verified_memory(w, agent, channel, user_id, content):
    w.memory[memory_key(agent, channel, "channel_verified", user_id)] = content


# ------------------------------------------------------------------ B0-17 email webhook
def email_webhook(w, form, auth_secret, agent="agent_A1"):
    if not auth_secret or not hmac.compare_digest(auth_secret, w.email_parse_secret):
        raise Denied("email_webhook_unauthenticated")
    verified = form.get("SPF") == "pass" and str(form.get("dkim", "")).find("pass") >= 0
    sender = form["from"].strip().lower()
    if not verified:
        return {"accepted": True, "verified": False, "subject_key": None, "memory": None, "reply_to": [sender],
                "memory_in_reply": False}
    mem = channel_memory_lookup(w, agent, "email", sender)
    return {"accepted": True, "verified": True, "subject_key": memory_key(agent, "email", "channel_verified", sender),
            "memory": mem, "reply_to": [sender] + [c for c in form.get("cc", []) if c], "memory_in_reply": mem is not None}


# ------------------------------------------------------------------ B0-18 platform admin
def is_platform_admin(p):
    if p.kind != "firebase":
        return False
    if p.admin_claim:
        return True
    return bool(p.email and p.email.lower().endswith("@olbrain.com") and p.email_verified is True
                and p.provider == "google.com" and p.hd == "olbrain.com")


def require_platform_admin(p):
    if not is_platform_admin(p):
        raise Denied("not_platform_admin")


# ------------------------------------------------------------------ B0-19 send-directive
def send_directive(w, caller, agent, target_user_row, directive):
    if caller is None or caller.kind != "service" or caller.service_email not in w.services:
        raise Denied("service_identity_required")
    row = w.agent_users.get(target_user_row)
    if row is None or row["agent"] != agent:
        raise Denied("target_not_an_end_user_of_agent")
    if row.get("opted_out"):
        raise Denied("target_opted_out")
    w.sent.append((agent, target_user_row, directive))
    return "sent"


# ------------------------------------------------------------------ B0-20 MCP
def mint_binding(w, agent, server, exp_delta=60, org=None):
    org = org or w.agents[agent]["org"]
    body = json.dumps({"agent": agent, "org": org, "aud": server, "exp": w.now + exp_delta}, sort_keys=True).encode()
    return base64.urlsafe_b64encode(body).decode() + "." + hmac.new(w.secret, body, hashlib.sha256).hexdigest()


def _verify_binding(w, token, server):
    try:
        b64, sig = token.rsplit(".", 1)
        body = base64.urlsafe_b64decode(b64.encode())
    except Exception:
        raise Denied("binding_malformed")
    if not hmac.compare_digest(hmac.new(w.secret, body, hashlib.sha256).hexdigest(), sig):
        raise Denied("binding_bad_signature")
    d = json.loads(body)
    if d["exp"] < w.now:
        raise Denied("binding_expired")
    if d["aud"] != server:
        raise Denied("binding_wrong_server")
    if w.agents.get(d["agent"], {}).get("org") != d["org"]:
        raise Denied("binding_wrong_tenant")
    return d


def mcp_tools_call(w, env, caller, server, body_agent=None, query_agent=None, binding=None):
    # auth is ALWAYS required: a missing or "false" MCP_REQUIRE_AUTH does not open the service (fail closed)
    if caller is None or caller.kind != "service" or caller.service_email not in w.services:
        raise Denied("caller_not_allowlisted")
    if not binding:
        raise Denied("binding_required")
    b = _verify_binding(w, binding, server)
    for claimed in (body_agent, query_agent):
        if claimed is not None and claimed != b["agent"]:
            raise Denied("claimed_agent_differs_from_binding")
    cred = w.mcp_creds.get((b["agent"], server))
    if cred is None:
        raise Denied("no_tenant_credentials")            # never ('default', server)
    return {"agent": b["agent"], "credential": cred}


def mcp_credentials_route(w, service_caller, user, op, agent):
    if service_caller is None or service_caller.service_email != "studio-backend-sa@synthetic":
        raise Denied("credential_routes_require_studio_backend")
    _require_edit(w, user, agent)
    return op + ":" + agent


# ------------------------------------------------------------------ B0-21 Lumen
def lumen_query(w, agent, sql, rows):
    """Structural isolation: the model's SQL runs against a database that only contains this agent's rows."""
    iso = sqlite3.connect(":memory:")
    iso.execute("create table service_logs(agent_id text, msg text)")
    iso.executemany("insert into service_logs values(?,?)", [r for r in rows if r[0] == agent])
    return [r[0] for r in iso.execute(sql)]


# ------------------------------------------------------------------ B0-22 activities
def activity_log(w, p, body_org, actor_id=None, kind="note"):
    require_org_access(w, p, body_org)
    actor = p.uid if p.kind == "firebase" else (actor_id or p.uid)
    w.activities.append({"org": body_org, "actor": actor, "kind": kind})


def activity_list(w, p, org):
    require_org_access(w, p, org)
    return [a for a in w.activities if a["org"] == org]


# ------------------------------------------------------------------ B0-23 share tokens
def share_validate(w, token, session):
    t = w.share_tokens.get(token) or next((v for v in w.share_tokens.values() if v["short_id"] == token), None)
    if t is None:
        raise Denied("unknown_share_token")
    cid = "shc_%d" % (len(w.issued) + 1)
    w.issued[cid] = {"agent": t["agent"], "session": session, "exp": w.now + SHARE_TTL}
    return {"credential": cid, "agent": t["agent"], "expires_at": w.now + SHARE_TTL}


def share_use(w, credential, agent, session, route):
    c = w.issued.get(credential)
    if c is None:
        raise Denied("unknown_credential")
    if w.now > c["exp"]:
        raise Denied("expired")
    if c["agent"] != agent or c["session"] != session:
        raise Denied("out_of_scope")
    if route not in SHARE_ROUTES:
        raise Denied("route_not_allowed")
    return "ok"


# ------------------------------------------------------------------ B0-24 engine permission helper
ROLE_PERMS = {"owner": {"agents:read", "agents:write"}, "editor": {"agents:read", "agents:write"},
              "viewer": {"agents:read"}}


async def engine_require_permission(w, user_id, organization_id, permission):
    perms = ROLE_PERMS.get(w.roles.get((user_id, organization_id)), set()) if (user_id, organization_id) in w.index \
        else set()
    if permission not in perms:
        raise HTTPException(status_code=403, detail="Permission denied: " + permission)
