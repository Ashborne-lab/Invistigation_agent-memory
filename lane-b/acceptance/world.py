"""Synthetic world for the B0 acceptance tests: two orgs, users, agents, keys, share tokens, memory, leads.
No real identifiers, no production data. Every id is obviously synthetic."""
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple


class Denied(Exception):
    """An explicit authorization refusal (the only acceptable failure mode for a security check)."""


@dataclass
class Principal:
    kind: str                         # firebase | api_key | service | anonymous
    uid: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool = False
    provider: Optional[str] = None    # firebase sign_in_provider: password | google.com
    hd: Optional[str] = None          # Google hosted domain claim
    admin_claim: bool = False         # backend-set custom claim
    org: Optional[str] = None         # API key's org (server-derived from the key record)
    perms: Tuple[str, ...] = ()
    scoped_agent: Optional[str] = None
    share_token: Optional[str] = None
    service_email: Optional[str] = None
    key_id: Optional[str] = None


@dataclass
class World:
    index: Set[Tuple[str, str]] = field(default_factory=set)                 # memberships_index (uid, org)
    roles: Dict[Tuple[str, str], str] = field(default_factory=dict)
    projects: Dict[str, str] = field(default_factory=dict)                   # project -> org
    agents: Dict[str, dict] = field(default_factory=dict)
    knowledge: Dict[str, Set[str]] = field(default_factory=dict)            # doc -> allowed_agents
    agent_users: Dict[str, dict] = field(default_factory=dict)
    leads: Dict[str, list] = field(default_factory=dict)                     # org -> lead rows
    memory: Dict[str, str] = field(default_factory=dict)                     # memory key -> content
    activities: list = field(default_factory=list)
    submissions: Dict[str, str] = field(default_factory=dict)                # blueprint submission -> status
    share_tokens: Dict[str, dict] = field(default_factory=dict)
    issued: Dict[str, dict] = field(default_factory=dict)                    # exchanged share credentials
    services: Set[str] = field(default_factory=set)                          # allow-listed service SAs
    mcp_creds: Dict[Tuple[str, str], str] = field(default_factory=dict)
    sent: list = field(default_factory=list)                                 # directives / email replies
    now: float = 1000.0
    secret: bytes = b"synthetic-binding-secret"
    email_parse_secret: str = "synthetic-parse-secret"


def standard_world() -> World:
    w = World()
    for org, uid in (("org_A", "uid_alice"), ("org_B", "uid_bob")):
        w.index.add((uid, org))
        w.roles[(uid, org)] = "editor"
    w.index.add(("uid_viewer_A", "org_A"))
    w.roles[("uid_viewer_A", "org_A")] = "viewer"
    w.projects.update(proj_A="org_A", proj_B="org_B")
    w.agents["agent_A1"] = {"org": "org_A", "owner": "uid_alice", "project": "proj_A"}
    w.agents["agent_B1"] = {"org": "org_B", "owner": "uid_bob", "project": "proj_B"}
    w.knowledge["kb_B"] = {"agent_B1"}
    w.agent_users["eu_B1"] = {"agent": "agent_B1", "org": "org_B", "phone": "+910000000001", "opted_out": True}
    w.agent_users["eu_A1"] = {"agent": "agent_A1", "org": "org_A", "phone": "+910000000002", "opted_out": False}
    w.leads["org_A"] = [{"id": "lead_a1"}]
    w.leads["org_B"] = [{"id": "lead_b1"}, {"id": "lead_b2"}]
    w.submissions["sub_1"] = "pending"
    w.services.update({"directives-sa@synthetic", "runtime-sa@synthetic"})
    w.mcp_creds[("agent_A1", "shopify")] = "cred-A1"
    w.mcp_creds[("agent_B1", "shopify")] = "cred-B1"
    w.mcp_creds[("default", "shopify")] = "cred-DEFAULT"
    w.share_tokens["tok_A1"] = {"agent": "agent_A1", "org": "org_A", "stored_api_key": "ak_live_org_A_scoped_A1",
                                "short_id": "abc123"}
    return w


ALICE = Principal("firebase", uid="uid_alice", email="alice@a.example", email_verified=True, provider="password")
BOB = Principal("firebase", uid="uid_bob", email="bob@b.example", email_verified=True, provider="password")
VIEWER_A = Principal("firebase", uid="uid_viewer_A", email="viewer@a.example", email_verified=True)
KEY_A = Principal("api_key", uid="uid_alice", org="org_A", key_id="key_A",
                  perms=("agents:read", "agents:write", "projects:read", "leads:read", "leads:write"))
SHARE_A1 = Principal("api_key", uid="uid_alice", org="org_A", key_id="key_share_A1", perms=("agents:invoke",),
                     scoped_agent="agent_A1", share_token="tok_A1")
