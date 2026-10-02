import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from memory_core.config import DEFAULT, with_  # noqa: E402
from memory_core.runtime import Memory  # noqa: E402

ORG = "org1"


class World:
    """Small scenario helper. ``say`` ingests evidence; ``extract`` runs one job with scripted proposals."""

    def __init__(self, d=DEFAULT, policy_version=1):
        self.m = Memory(d, policy_version)
        # Harness convenience: in handle mode the caller presents a handle for the conversation it is
        # serving. Tests that probe isolation pass explicit tokens instead (tests/test_redteam_*.py).
        self.caller = {"org": ORG, "agent": "agentA", "kind": "agent",
                       "handle": lambda s: self.m.handle_for_subject(s, 0)}

    def say(self, user, text, t, role="user", org=ORG, agent="agentA", channel="wa", session=None, **kw):
        return self.m.ingest(org, agent, channel, user, session or ("s-" + user), role, text, t, **kw)

    def subj(self, ev):
        return ev.subject_id

    def extract(self, subject, proposals, t, only=None):
        job = self.m.prepare(subject, only)
        return self.m.commit(job, proposals, t)

    def cur(self, subject, key, now=1e6, **kw):
        return self.m.get_current_state(self.caller, subject, key, now=now, **kw)


def P(key, v, ev, quote=None, mode="stated", kind="text", op="assert", expr=None, cause=None, prompt=None,
      pquote=None, extra_anchor=None):
    anchor = [{"evidence_id": ev.evidence_id, "quote": quote if quote is not None else ev.text}]
    if extra_anchor:
        anchor += extra_anchor
    pr = {"op": op, "key": key, "mode": mode, "anchor": anchor}
    if op == "assert" or v is not None:
        pr["value"] = {"kind": kind, "v": v} if kind != "none" else {"kind": "none"}
    if expr:
        pr["valid_time"] = {"expression": expr}
    if cause:
        pr["cause"] = cause
    if prompt is not None:
        pr["prompt_ref"] = {"evidence_id": prompt.evidence_id, "quote": pquote or prompt.text}
    return pr


@pytest.fixture
def w():
    return World()


@pytest.fixture
def mk():
    return lambda **kw: World(with_(DEFAULT, **kw))
