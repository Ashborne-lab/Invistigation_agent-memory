"""Keyed deterministic ids (implementation spec §7.2).

Every id is an HMAC-SHA256 under a random key per subject. Without that
key, an id reveals nothing about the value it was computed from.
Destroying the key (crypto-shredding at physical erasure) makes any
leftover id impossible to link back to the subject.
"""
import base64
import hashlib
import hmac
import os


def new_subject_key() -> bytes:
    return os.urandom(32)


def _h(key: bytes, msg: str) -> str:
    d = hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    return base64.b32encode(d).decode("ascii").rstrip("=").lower()[:26]


def claim_id(subject_key: bytes, evidence_id: str, key: str, canonical_value: str,
             derivation: str = "orig", include_derivation: bool = False) -> str:
    """The spec formula is HMAC(subject_key, evidence|key|value).

    ``include_derivation`` is the prototype's amendment for finding F-3.
    """
    tag = ("|" + derivation) if include_derivation else ""
    return "clm_" + _h(subject_key, "claim|v1|%s|%s|%s%s" % (evidence_id, key, canonical_value, tag))


def edge_id(subject_key: bytes, claim: str, evidence_id: str) -> str:
    return "sup_" + _h(subject_key, "edge|v1|%s|%s" % (claim, evidence_id))


def suppression_fp(subject_key: bytes, key: str, canonical_value: str) -> str:
    return "sfp_" + _h(subject_key, "supp|v1|%s|%s" % (key, canonical_value))


def index_key(org_key: bytes, agent_id: str, channel: str, user_key: str) -> str:
    return "idx_" + _h(org_key, "v1|%s|%s|%s" % (agent_id, channel, user_key.strip().lower()))


def sealed_hash(org_key: bytes, role: str, author_role: str, channel: str, text: str) -> str:
    """Red-team R-2/R-24: keyed hash over role|author|channel|content (a role flip changes it)."""
    return "seal_" + _h(org_key, "seal|v1|%s|%s|%s|%s" % (role, author_role, channel, text or ""))


def dedup_key(org_key: bytes, channel: str, provider_msg_id: str) -> str:
    return "dd_" + _h(org_key, "dedup|v1|%s|%s" % (channel, provider_msg_id))


def worm_ref(org_key: bytes, subject_id: str) -> str:
    """PII-free reference used in the WORM ledger (red-team C-8): matches a subject without naming it."""
    return "wr_" + _h(org_key, "worm|v1|%s" % subject_id)


def episode_id(subject_key: bytes, agent_id: str, first_evidence_id: str) -> str:
    return "ep_" + _h(subject_key, "ep|v1|%s|%s" % (agent_id, first_evidence_id))
