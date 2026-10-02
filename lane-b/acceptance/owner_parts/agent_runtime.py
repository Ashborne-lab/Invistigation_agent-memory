"""OWNER adapter: olbrain-agent-runtime (B0-15, B0-16, B0-17, B0-19; B0-23 acceptance side).

Every entry calls REAL code loaded read-only from the committed `b0/security` branch (`extract.OWNER_REF`):
- core/route_scope.py, core/memory_subject.py, core/email_inbound.py, core/directive_auth.py,
  core/hotpath_cache.py and core/api_key_middleware.py are materialised whole under SCRATCH/b0_owner_runtime/
  (that root goes first on sys.path; `core.*` there is the b0/security copy, its package __init__ is empty);
- services/agent_memory_service.py is too heavy to import (Firestore SDK sentinels), so its pure read/write-key
  functions (memory_doc_id, load_memory_doc, load_user_memory, load_user_memory_any, resolve_write_key) are taken
  with `extract.function_source`.

The synthetic World is mapped onto a dict-backed Firestore stand-in (api_keys, agents, share_credentials,
agent_user_memory). The API-key middleware and its validator run for real (APIKeyMiddleware.__call__ ->
APIKeyValidator.validate_api_key_for_agent / load_share_credential); 401/403/503 become world.Denied.

What is NOT exercised here (heavy FastAPI handlers) is marked [WIRING-ONLY: proven by <repo test>]; each named
test exists in olbrain-agent-runtime@b0/security.

share_use consumes the credential issued by studio-backend's share_validate in the reference shape
`w.issued[credential] = {"agent", "session", "exp"}` (optional "share_token_id"), and stores it as the runtime
reads it: share_credentials/{sha256(credential)} = {agent_id, organization_id, session_id, share_token_id,
permissions: ["agents:invoke"], expires_at}.
"""
import asyncio
import hashlib
import importlib
import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import extract as X
from world import Denied

NAME = "owner:agent_runtime"
REPO = "olbrain-agent-runtime"
REF = X.OWNER_REF
_ROOT = "b0_owner_runtime"

__all__ = ["runtime_call", "memory_key", "webhook_memory_lookup", "channel_memory_lookup",
           "store_verified_memory", "email_webhook", "send_directive", "share_use"]

for _path in ("core/route_scope.py", "core/memory_subject.py", "core/email_inbound.py",
              "core/directive_auth.py", "core/hotpath_cache.py", "core/api_key_middleware.py"):
    X.materialise(REPO, _path, _ROOT + "/" + _path, ref=REF)
# `core` is a common top-level name: import ours in isolation, keep the module objects, put back whatever was there.
_owner_root = os.path.join(X.SCRATCH, _ROOT)
_saved = {m: sys.modules.pop(m) for m in [m for m in sys.modules if m == "core" or m.startswith("core.")]}
sys.path.insert(0, _owner_root)
_RS = importlib.import_module("core.route_scope")
_MS = importlib.import_module("core.memory_subject")
_EI = importlib.import_module("core.email_inbound")
_DA = importlib.import_module("core.directive_auth")
importlib.import_module("core.hotpath_cache")
_MW = importlib.import_module("core.api_key_middleware")
_MINE = {m: sys.modules.pop(m) for m in [m for m in sys.modules if m == "core" or m.startswith("core.")]}
sys.path.remove(_owner_root)
sys.modules.update(_saved)

_MEM: Dict[str, Any] = {"hashlib": hashlib, "Optional": Optional, "Dict": Dict, "Any": Any, "List": List,
                        "MEMORY_COLLECTION": "agent_user_memory"}
for _fn in ("memory_doc_id", "load_memory_doc", "load_user_memory", "load_user_memory_any", "resolve_write_key"):
    exec(X.function_source(REPO, "services/agent_memory_service.py", _fn, ref=REF), _MEM)


# ------------------------------------------------------------------ dict-backed Firestore stand-in
class _Snap:
    def __init__(self, doc_id, data):
        self.id, self._data, self.exists = doc_id, data, data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Coll:
    def __init__(self, docs, filters=()):
        self._docs, self._filters = docs, filters

    def where(self, field, op, value):
        return _Coll(self._docs, self._filters + ((field, value),))

    def limit(self, _n):
        return self

    def stream(self):
        return [_Snap(k, v) for k, v in self._docs.items() if all(v.get(f) == x for f, x in self._filters)]

    def document(self, doc_id):
        docs = self._docs
        return SimpleNamespace(get=lambda: _Snap(doc_id, docs.get(doc_id)))


class _DB:
    def __init__(self, **collections):
        self.c = collections

    def collection(self, name):
        return _Coll(self.c.setdefault(name, {}))


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _token(p):
    return "ak_" + p.key_id


def _world_db(w, principal=None, share_credentials=None):
    keys = {}
    if principal is not None and principal.kind == "api_key":
        meta = {}
        if principal.scoped_agent:
            meta["scoped_agent_id"] = principal.scoped_agent
        if principal.share_token:
            meta["share_token_id"] = principal.share_token
        keys[principal.key_id] = {"key_hash": _sha(_token(principal)), "status": "active",
                                  "organization_id": principal.org, "permissions": list(principal.perms),
                                  "is_system": bool(principal.share_token), "metadata": meta}
    return _DB(api_keys=keys,
               agents={a: {"organization_id": d["org"]} for a, d in w.agents.items()},
               share_credentials=share_credentials or {})


def _run_middleware(db, method, path, headers, now=None):
    """REAL APIKeyMiddleware + APIKeyValidator over the stand-in. Returns (status, request.state)."""
    validator = _MW.APIKeyValidator.__new__(_MW.APIKeyValidator)
    validator.db, validator.rate_limit_cache = db, {}
    middleware = _MW.APIKeyMiddleware(validator, agent_id="unused")
    request = SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers=headers,
                              state=SimpleNamespace())

    async def _handler(_request):
        return SimpleNamespace(status_code=200)

    saved_core = {m: sys.modules.get(m) for m in _MINE}
    saved_time = _MW.time
    sys.modules.update(_MINE)                       # the validator's lazy `from core import hotpath_cache`
    if now is not None:
        _MW.time = SimpleNamespace(time=lambda: now)  # the World's clock for share-credential expiry
    try:
        response = asyncio.run(middleware(request, _handler))
    finally:
        _MW.time = saved_time
        for m, mod in saved_core.items():
            if mod is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = mod
    return response.status_code, request.state


def _check(status):
    if status in (401, 403, 503):
        raise Denied("http_%d" % status)
    if status != 200:
        raise AssertionError("unexpected status %d (not an authorization decision)" % status)


_ROUTES = {
    "leads.list": ("GET", "/organizations/{org}/lead-profiles"),
    "leads.export": ("POST", "/organizations/{org}/lead-exports"),
    "leads.import": ("POST", "/organizations/{org}/lead-profiles/import"),
    "leads.erase": ("DELETE", "/api/lead-contacts"),
    "memory.read": ("GET", "/api/agents/{agent}/user-memory/u1"),
    "memory.delete": ("DELETE", "/api/agents/{agent}/user-memory/u1"),
    "webhook": ("POST", "/api/agent/webhook"),
    "feedback": ("POST", "/api/agent/message-feedback"),
    "upload_attachment": ("POST", "/api/agent/upload-attachment"),
    "session_insights": ("GET", "/api/agent/session-insights/{session}"),
}


# ------------------------------------------------------------------ B0-15
def runtime_call(w, key, route, org=None, path_agent=None, header_agent=None):
    """REAL middleware decision (route_scope table + validator org/agent binding)."""
    method, template = _ROUTES[route]
    # A machine caller always sends X-Agent-ID (the middleware 400s without it): the named agent, else its own.
    agent_hdr = header_agent or path_agent or key.scoped_agent or \
        next((a for a, d in sorted(w.agents.items()) if d["org"] == key.org), "agent_none")
    path = template.format(org=org or key.org, agent=path_agent or agent_hdr, session="s1")
    headers = {"Authorization": "Bearer " + (_token(key) if key.kind == "api_key" else "firebase-token"),
               "X-Agent-ID": agent_hdr}
    status, _state = _run_middleware(_world_db(w, key), method, path, headers)
    _check(status)
    # [WIRING-ONLY: proven by tests/test_b0_route_scope_middleware.py::test_fully_scoped_key_keeps_access_in_own_org]
    # past the middleware the leads handlers read the caller's own org (`_leads_org_gate` re-checks it).
    if route.startswith("leads."):
        return list(w.leads.get(key.org, []))
    if route == "memory.delete":
        return "deleted"
    return "ok"


# ------------------------------------------------------------------ B0-16
def memory_key(agent, channel, assurance, user_id):
    return _MEM["memory_doc_id"](agent, _MS.subject_key(channel, assurance, user_id))


def _memory_db(w):
    return _DB(agent_user_memory={k: {"facts": [v]} for k, v in w.memory.items()})


def _read(w, agent, keys):
    doc = _MEM["load_user_memory_any"](_memory_db(w), agent, keys)      # REAL read over the subject keys
    return doc["facts"][0] if doc else None


def webhook_memory_lookup(w, caller, agent, user_id, chat_id="c1"):
    # [WIRING-ONLY: proven by tests/test_b0_route_scope_middleware.py::test_share_key_keeps_share_routes]
    # the middleware stamps auth_method/api_key_id/share_token_id from the key record.
    state = SimpleNamespace(auth_method="api_key", api_key_id=caller.key_id, share_token_id=caller.share_token)
    # [WIRING-ONLY: proven by tests/test_b0_webhook_memory_subject.py::test_legacy_share_key_user_id_is_forced_everywhere
    #  and ::test_api_key_caller_is_asserted_under_its_key_channel_even_claiming_whatsapp]
    # the webhook forces the share id and marks the turn ASSERTED under webhook_channel(...).
    if state.share_token_id:
        user_id = _RS.share_user_id(state.share_token_id, chat_id)
    channel = _MS.webhook_channel(state.auth_method, api_key_id=state.api_key_id,
                                  share_token_id=state.share_token_id)
    # [WIRING-ONLY: proven by tests/test_b0_memory_subject.py::test_asserted_turn_cannot_load_verified_or_legacy_memory]
    # the packet builder reads exactly lookup_keys(...) through load_user_memory_any.
    return _read(w, agent, _MS.lookup_keys(user_id, channel, _MS.ASSERTED))


def channel_memory_lookup(w, agent, channel, user_id):
    return _read(w, agent, _MS.lookup_keys(user_id, channel, _MS.CHANNEL_VERIFIED))


def store_verified_memory(w, agent, channel, user_id, content):
    keys = _MS.lookup_keys(user_id, channel, _MS.CHANNEL_VERIFIED)
    key = _MEM["resolve_write_key"](_memory_db(w), agent, keys)          # REAL write-key choice
    w.memory[_MEM["memory_doc_id"](agent, key)] = content


# ------------------------------------------------------------------ B0-17
def email_webhook(w, form, auth_secret, agent="agent_A1"):
    # [WIRING-ONLY: proven by tests/test_b0_email_inbound.py::test_route_rejects_missing_or_wrong_secret_before_parsing
    #  and ::test_route_fails_closed_when_secret_unconfigured] the route runs this check before reading the form.
    _check(_EI.parse_secret_status(_EI.presented_secret(auth_secret, None), w.email_parse_secret))
    parsed = _EI.parse_inbound(form, "inbound.synthetic")
    user, channel, assurance = _EI.memory_identity(parsed)
    keys = _MS.lookup_keys(user, channel, assurance)
    memory = _read(w, agent, keys) if keys else None
    # [WIRING-ONLY: proven by tests/test_b0_email_inbound.py::test_unverified_mail_is_processed_without_memory_and_without_cc
    #  and ::test_verified_mail_keeps_memory_subject_and_reply_all] _process_single_email sends to the sender with
    # reply_recipients(parsed) as cc and memory_identity(parsed) as the AbstractMessage subject.
    return {"accepted": True, "verified": parsed["verified"],
            "subject_key": _MEM["memory_doc_id"](agent, keys[0]) if keys else None,
            "memory": memory, "reply_to": [parsed["from_email"].lower()] + _EI.reply_recipients(parsed),
            "memory_in_reply": memory is not None}


# ------------------------------------------------------------------ B0-19
def send_directive(w, caller, agent, target_user_row, directive):
    """REAL middleware directive gate; the Google signature check itself is the World's verdict on `caller`."""
    claims = ({"email": caller.service_email, "email_verified": True}
              if caller is not None and caller.kind == "service" else None)
    env = {"DIRECTIVES_ALLOWED_SERVICE_ACCOUNTS": ",".join(sorted(w.services)),
           "DIRECTIVES_AUDIENCE": "https://runtime.synthetic"}
    saved_env = {k: os.environ.get(k) for k in env}
    saved_verify = _DA.verify_service_token
    os.environ.update(env)
    _DA.verify_service_token = lambda token: claims
    try:
        headers = {"Authorization": "Bearer synthetic-oidc"} if caller is not None else {}
        status, state = _run_middleware(_DB(), "POST", _DA.DIRECTIVE_PATH, headers)
    finally:
        _DA.verify_service_token = saved_verify
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    _check(status)
    # [WIRING-ONLY: proven by tests/test_b0_directives_auth.py::test_target_must_be_an_end_user_of_that_agent]
    # resolve_directive_target finds the agent_users row of THIS agent and applies target_denial to it.
    row = w.agent_users.get(target_user_row)
    prod_row = None if row is None else {"agent_id": row["agent"], "channel_user_id": target_user_row,
                                         "opted_out_at": "2026-01-01T00:00:00Z" if row.get("opted_out") else None}
    if _DA.target_denial(prod_row, agent):
        raise Denied(_DA.target_denial(prod_row, agent))
    w.sent.append((agent, target_user_row, directive))
    return "sent"


# ------------------------------------------------------------------ B0-23 (acceptance side)
def share_use(w, credential, agent, session, route):
    issued = w.issued.get(credential)
    store = {}
    if issued is not None:
        store[_sha(credential)] = {"agent_id": issued["agent"],
                                   "organization_id": w.agents.get(issued["agent"], {}).get("org"),
                                   "session_id": issued["session"],
                                   "share_token_id": issued.get("share_token_id", "tok_issued"),
                                   "permissions": ["agents:invoke"], "expires_at": issued["exp"]}
    method, template = _ROUTES[route]
    path = template.format(org=w.agents.get(agent, {}).get("org", "org_none"), agent=agent, session=session)
    status, state = _run_middleware(_world_db(w, share_credentials=store), method, path,
                                    {"Authorization": "Bearer " + credential, "X-Agent-ID": agent}, now=w.now)
    _check(status)
    # [WIRING-ONLY: proven by tests/test_b0_webhook_memory_subject.py::test_share_credential_cannot_name_another_session]
    # each share handler calls share_bound_session(request, <its session id>) -> share_session_denial.
    if _RS.share_session_denial(state.share_session_id, session):
        raise Denied("out_of_scope")
    return "ok"
