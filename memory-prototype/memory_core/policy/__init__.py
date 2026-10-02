"""Versioned predicate policy registry (implementation spec §6.4; RECON E11).

Every key and every open namespace resolves to a declared policy, and
there is no fallback. Provisional defaults are marked [UNDECIDED].
"""
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional

from ..config import Decisions

SOURCES = ("USER", "OPERATOR", "IMPORT", "BILLING_SYSTEM", "HR_SYSTEM", "IDENTITY_SYSTEM", "LEGACY_MIGRATION",
           "CRM_SYSTEM")


@dataclass(frozen=True)
class PredicatePolicy:
    key: str
    version: int
    cardinality: str                              # SINGLE | SET
    allowed_sources: FrozenSet[str]
    authority_rank: Dict[str, int] = field(hash=False, compare=False, default_factory=dict)
    llm_write_mode: str = "PROPOSE_VIA_GATE"      # FORBIDDEN | PROPOSE_VIA_GATE | TYPED_COMMAND
    current_state_eligible: bool = False
    requires_verified_for_slot: bool = True
    temporal_model: str = "stable"                # stable | volatile | expiring
    freshness_days: Optional[float] = None
    clear_outcome: str = "UNKNOWN"                # UNKNOWN | EXPLICIT_NONE (per contract :757)
    security_class: str = "standard"              # standard | sensitive | identity_security
    authority_domain: str = "CUSTOMER_PREFERENCE"
    modes: FrozenSet[str] = frozenset({"stated", "normalized", "confirmed"})
    normaliser: Optional[str] = None
    is_namespace: bool = False
    commitment: bool = False
    disclosable: bool = True                      # red-team C-5: may be shown to linked persons (account.*)


def _ranks(d: Decisions, extra: Dict[str, int] = None) -> Dict[str, int]:
    op = {"equal_to_user": 1, "above_user": 2, "below_user": 0}[d.operator_rank]    # O11, injectable
    r = {"USER": 1, "OPERATOR": op, "IMPORT": 1, "LEGACY_MIGRATION": 0}
    r.update(extra or {})
    return r


def registry(d: Decisions, version: int = 1) -> Dict[str, PredicatePolicy]:
    R = {}

    def add(p: PredicatePolicy):
        R[p.key] = p

    user_ops = frozenset({"USER", "OPERATOR", "IMPORT", "LEGACY_MIGRATION"})
    add(PredicatePolicy("residence.city", version, "SINGLE", user_ops, _ranks(d),
                        current_state_eligible=True, normaliser="gazetteer_city"))
    add(PredicatePolicy("device.phone.primary", version, "SINGLE", user_ops, _ranks(d),
                        current_state_eligible=True))
    add(PredicatePolicy("device.owned", version, "SET", user_ops, _ranks(d)))
    add(PredicatePolicy("diet.pattern", version, "SINGLE", user_ops, _ranks(d), current_state_eligible=True))
    # v2 changes cardinality, for the policy-migration tests (Case 12 / M27).
    add(PredicatePolicy("preferred_language", version, "SINGLE" if version == 1 else "SET", user_ops, _ranks(d),
                        current_state_eligible=True, temporal_model="volatile", freshness_days=90))
    add(PredicatePolicy("work.employer", version, "SINGLE", user_ops | {"HR_SYSTEM"},
                        _ranks(d, {"HR_SYSTEM": 5}), current_state_eligible=True, authority_domain="HR"))
    add(PredicatePolicy("travel.planned", version, "SET", user_ops, _ranks(d), temporal_model="expiring"))
    add(PredicatePolicy("health.condition", version, "SET", frozenset({"USER"}), _ranks(d),
                        security_class="sensitive"))
    # Keys that the model may never write (contract §5; Ex.12; E11).
    add(PredicatePolicy("billing.renewal_day", version, "SINGLE", frozenset({"BILLING_SYSTEM"}),
                        {"BILLING_SYSTEM": 5}, llm_write_mode="FORBIDDEN", current_state_eligible=True,
                        authority_domain="BILLING_SYSTEM"))
    add(PredicatePolicy("account.role", version, "SINGLE", frozenset({"IDENTITY_SYSTEM"}),
                        {"IDENTITY_SYSTEM": 9}, llm_write_mode="FORBIDDEN", security_class="identity_security",
                        authority_domain="IDENTITY_SECURITY"))
    add(PredicatePolicy("entitlement.*", version, "SET", frozenset({"BILLING_SYSTEM"}), {"BILLING_SYSTEM": 5},
                        llm_write_mode="FORBIDDEN", security_class="identity_security", is_namespace=True,
                        authority_domain="BILLING_SYSTEM"))
    add(PredicatePolicy("consent.memory", version, "SINGLE", frozenset({"USER"}), _ranks(d),
                        llm_write_mode="TYPED_COMMAND", current_state_eligible=True))
    # Contact identifiers belong to identity (PI-3). Only a decision can enable them as memory keys.
    add(PredicatePolicy("contact.phone", version, "SINGLE", user_ops, _ranks(d),
                        llm_write_mode="PROPOSE_VIA_GATE" if d.phone_email_memory_keys else "FORBIDDEN",
                        current_state_eligible=False, normaliser="phone_e164",
                        authority_domain="IDENTITY"))
    # Open namespaces: provisional conservative policy [UNDECIDED] (spec §6.4).
    for ns in ("note.*", "family.*", "work.*", "vehicle.*"):
        add(PredicatePolicy(ns, version, "SET", frozenset({"USER"}), _ranks(d), is_namespace=True,
                            modes=frozenset({"stated", "confirmed"})))
    add(PredicatePolicy("commitment.*", version, "SET", frozenset({"USER"}), _ranks(d), is_namespace=True,
                        commitment=True))
    # Account scope (red-team C-5). v2: any source, all disclosable. Reviewed: authoritative sources only,
    # and only predicates flagged disclosable are shown to linked persons.
    acct_src = frozenset({"OPERATOR", "IMPORT", "CRM_SYSTEM"}) | (
        frozenset({"USER"}) if d.account_sources == "any" else frozenset())
    acct_rank = _ranks(d, {"CRM_SYSTEM": 3})
    add(PredicatePolicy("account.plan", version, "SINGLE", acct_src, acct_rank, current_state_eligible=True,
                        authority_domain="ACCOUNT", disclosable=True))
    add(PredicatePolicy("account.*", version, "SET", acct_src, acct_rank, is_namespace=True,
                        authority_domain="ACCOUNT", disclosable=d.account_sources == "any"))
    if d.r_m1_inference == "store_labelled":
        for p in list(R.values()):
            if p.llm_write_mode == "PROPOSE_VIA_GATE" and p.security_class == "standard":
                R[p.key] = PredicatePolicy(**{**p.__dict__, "modes": p.modes | {"inferred"}})
    return R


def lookup(reg: Dict[str, PredicatePolicy], key: str) -> Optional[PredicatePolicy]:
    if key in reg and not reg[key].is_namespace:
        return reg[key]
    if "." in key:
        ns = key.split(".", 1)[0] + ".*"
        p = reg.get(ns)
        if p is not None:
            return p
    return None
