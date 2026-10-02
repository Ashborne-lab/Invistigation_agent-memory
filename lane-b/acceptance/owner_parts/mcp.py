"""OWNER adapter: olbrain-mcp-deployer, service side of B0-20 (contract C3).

REAL code loaded read-only from the committed `b0/security` branch (extract.OWNER_REF):
- runtime/agent_binding.py, runtime/agent_authz.py, runtime/auth_middleware.py are materialised whole under
  SCRATCH/b0_owner_mcp/ and imported as the top-level names main.py uses (`agent_binding`, `agent_authz`,
  `auth_middleware`), in isolation: whatever had those names in sys.modules is put back afterwards;
- runtime/main.py is too heavy to import (Firestore/KMS/managers), so `_get_credentials_for_server` (the credential
  tiers, incl. the B0-20 no-default/no-env rule for tenant-scoped servers) is taken with extract.function_source
  and run against fakes.
- The user edit check for credential management is studio-backend's REAL `require_agent_edit`
  (owner_parts/studio_backend.py loads it from olbrain-studio-backend@b0/security).

World mapping: w.secret = MCP_AGENT_BINDING_KEY, w.now = the verifier's clock, w.services = MCP_ALLOWED_INVOKERS,
studio-backend-sa@synthetic = MCP_CREDENTIAL_ADMIN_INVOKERS (and an allowed invoker), w.mcp_creds = the KMS
`credentials/{agent}:{server}` docs (("default", s) = credentials/default:{s}), w.agents[a]["org"] =
agents/{a}.organization_id. The `env` argument is applied as given: MCP_REQUIRE_AUTH is set or cleared, never
defaulted. Google's OIDC verifier is faked: a service principal's token verifies as that SA (aud = the expected
audience); any other principal sends no token.

MODELLING CHOICE: the real shopify definition is OAuth (tier 1 reads oauth_connections). To exercise the KMS tiers
2-3 for real, "shopify" is given a non-OAuth definition that requires one credential; is_tenant_scoped classifies
it tenant-scoped either way.

Not provided: workflow-runtime / research-runtime caller parts. workflow-runtime has no MCP call site of its own
(every call is in olbrain-shared); research-runtime calls MCP with no agent at all. Both BLOCKED, see the B0-20
report.
"""
import asyncio
import importlib
import logging
import os
import sys
from contextlib import contextmanager
from typing import Dict, Optional
from unittest.mock import patch

import extract as X
from world import Denied

NAME = "owner:mcp"
REPO = "olbrain-mcp-deployer"
REF = X.OWNER_REF
_ROOT = "b0_owner_mcp"
AUD = "https://mcp-synthetic.run.app"           # this service's OIDC audience (MCP_EXPECTED_AUDIENCE)
STUDIO_SA = "studio-backend-sa@synthetic"
CRED_SERVER = "shopify"                         # the server the credential-route test acts on
_DEFS = {"shopify": {"credentials": {"required": [{"name": "SHOPIFY_ACCESS_TOKEN"}]}}}

__all__ = ["mint_binding", "mcp_tools_call", "mcp_credentials_route"]

_NAMES = ("agent_binding", "agent_authz", "auth_middleware")
for _n in _NAMES:
    X.materialise(REPO, "runtime/%s.py" % _n, "%s/%s.py" % (_ROOT, _n), ref=REF)
_owner_root = os.path.join(X.SCRATCH, _ROOT)
_saved = {n: sys.modules.pop(n) for n in _NAMES if n in sys.modules}
sys.path.insert(0, _owner_root)
_AB = importlib.import_module("agent_binding")
_AZ = importlib.import_module("agent_authz")
_AM = importlib.import_module("auth_middleware")
for _n in _NAMES:
    sys.modules.pop(_n, None)
sys.path.remove(_owner_root)
sys.modules.update(_saved)

_MAIN = {"Optional": Optional, "Dict": Dict, "os": os, "logger": logging.getLogger("owner.mcp"), "agent_authz": _AZ,
         "_load_server_definition": lambda name: _DEFS.get(name)}
exec(X.function_source(REPO, "runtime/main.py", "_get_credentials_for_server", ref=REF), _MAIN)


class _Kms:
    def __init__(self, w):
        self.w = w

    async def retrieve_credentials(self, agent_id, server_name):
        cred = self.w.mcp_creds.get((agent_id, server_name))
        return {"SHOPIFY_ACCESS_TOKEN": cred} if cred else None


@contextmanager
def _deployment(w, env, extra_invokers=()):
    keys = ("MCP_REQUIRE_AUTH", "MCP_ALLOWED_INVOKERS", "MCP_EXPECTED_AUDIENCE", "MCP_AGENT_BINDING_KEY",
            "MCP_CREDENTIAL_ADMIN_INVOKERS")
    saved = {k: os.environ.get(k) for k in keys}
    conf = {"MCP_ALLOWED_INVOKERS": ";".join(sorted(set(w.services) | set(extra_invokers))),
            "MCP_EXPECTED_AUDIENCE": AUD, "MCP_AGENT_BINDING_KEY": w.secret.decode(),
            "MCP_CREDENTIAL_ADMIN_INVOKERS": STUDIO_SA}
    if "MCP_REQUIRE_AUTH" in env:
        conf["MCP_REQUIRE_AUTH"] = env["MCP_REQUIRE_AUTH"]
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(conf)

    def verify(token, _request):
        return {"email": token, "email_verified": True, "aud": AUD}
    try:
        with patch.object(_AM.id_token, "verify_oauth2_token", verify):
            yield
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def _caller_auth(caller, path):
    """REAL CallerAuthMiddleware.dispatch. Returns the request (its state carries the verified claims)."""
    from starlette.requests import Request
    headers = []
    if caller is not None and caller.kind == "service" and caller.service_email:
        headers.append((b"authorization", ("Bearer " + caller.service_email).encode()))
    request = Request({"type": "http", "method": "POST", "path": path, "headers": headers, "query_string": b"",
                       "scheme": "https", "server": ("mcp-synthetic", 443)})

    async def _next(_request):
        return "passed"
    out = asyncio.run(_AM.CallerAuthMiddleware(app=None).dispatch(request, _next))
    if out != "passed":
        raise Denied("caller_auth_%d" % out.status_code)
    return request


def _agent_org(w):
    async def lookup(agent_id):
        return (w.agents.get(agent_id) or {}).get("org")
    return lookup


def _authz(coro):
    try:
        return asyncio.run(coro)
    except _AZ.AgentAuthzError as e:
        raise Denied("%d:%s" % (e.status, e.detail))


# ------------------------------------------------------------------ B0-20
def mint_binding(w, agent, server, exp_delta=60, org=None):
    """The shared C3 algorithm (agent_binding.mint_agent_binding; identical code in agent-runtime)."""
    org = org or w.agents[agent]["org"]
    iat = int(w.now)
    if 0 < exp_delta <= _AB.MAX_TTL:
        return _AB.mint_agent_binding(agent, org, server, ttl=exp_delta, now=iat, key=w.secret)
    # mint refuses ttl <= 0; an already-expired binding is the same format with exp in the past.
    exp = iat + exp_delta
    return _AB.encode({"agent_id": agent, "org_id": org, "aud": server, "iss": _AB.ISSUER,
                       "iat": exp - 60, "exp": exp}, w.secret)


def mcp_tools_call(w, env, caller, server, body_agent=None, query_agent=None, binding=None):
    with _deployment(w, env):
        _caller_auth(caller, "/api/v1/tools/call")
        # [WIRING-ONLY: proven by olbrain-mcp-deployer tests/runtime/test_b0_20_agent_binding_routes.py
        #  ::test_spoofed_agent_with_a_binding_for_another_agent_is_rejected] main.call_tool hands the header,
        # server_name and body/query agent_id to agent_authz.authorize_agent (via main._authorize_agent).
        claims = _authz(_AZ.authorize_agent(binding, server, agent_org=_agent_org(w),
                                            claimed=(body_agent, query_agent),
                                            tenant_scoped=_AZ.is_tenant_scoped(server, _DEFS.get(server)),
                                            now=w.now))
        agent = claims["agent_id"] if claims else ""
        _MAIN["kms_credential_service"] = _Kms(w)
        creds, _source = asyncio.run(_MAIN["_get_credentials_for_server"](agent, server))
        if creds is None:
            raise Denied("no_tenant_credentials")      # main.call_tool: HTTP 400, nothing is called
        return {"agent": agent, "credential": creds.get("SHOPIFY_ACCESS_TOKEN")}


def mcp_credentials_route(w, service_caller, user, op, agent):
    from owner_parts import studio_backend as SB
    caller_email = getattr(service_caller, "service_email", None)
    if caller_email == STUDIO_SA:
        # studio-backend's own user check (REAL require_agent_edit) before it would mint a binding.
        with SB._bind(w) as db:
            snap = db.collection("agents").document(agent).get()
            if not snap.exists:
                raise Denied("unknown_agent")
            SB._mods()["auth"].require_agent_edit(SB._user(user), snap.to_dict(), agent)
    # [WIRING-ONLY: caller side BLOCKED - olbrain-studio-backend does not mint X-OLBrain-Agent-Binding for
    #  /api/v1/credentials yet (not in this lane).] The binding is minted here with the shared algorithm, for
    #  EVERY caller (strongest attacker: a non-studio caller that also holds a valid binding).
    binding = mint_binding(w, agent, CRED_SERVER) if agent in w.agents else None
    with _deployment(w, {}, extra_invokers=(STUDIO_SA,)):
        request = _caller_auth(service_caller, "/api/v1/credentials")
        # [WIRING-ONLY: proven by olbrain-mcp-deployer tests/runtime/test_b0_20_agent_binding_routes.py
        #  ::test_credential_routes_need_studio_backend_sa_and_a_binding_for_the_target] store/delete_credentials
        # call agent_authz.authorize_credential_admin with request.state.caller_claims["email"].
        _authz(_AZ.authorize_credential_admin(request.state.caller_claims.get("email"), binding, CRED_SERVER,
                                              agent, agent_org=_agent_org(w), now=w.now))
    return op + ":" + agent
