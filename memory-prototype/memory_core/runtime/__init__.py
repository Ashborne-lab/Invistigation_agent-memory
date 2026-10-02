"""In-memory test harness: pure core plus an atomic in-memory store. This module is NOT pure.

It wires the pure modules together the way the implementation spec §10–§16
and the red-team review (R-1…R-25) describe, so benchmark scenarios can run
end to end. It models only what semantic testing needs. It is not a
Firestore or PostgreSQL simulator.

State is partitioned the way the hybrid architecture partitions it, so the
restore model (``restore.py``) can restore one store without the other:

- FS   (evidence store, Firestore): messages, bindings/index, subject keys,
        identity state (epochs, merged_into, merges, heads' identity fields),
        dedup, and the commit records kept with each message (LA-1);
- PG   (memory store): claims, suppressions, episodes, manifests, head slots,
        search projection, derived artifacts, knowledge, commitments;
- WORM (never restored): the PII-free erasure and identity ledger.

A transaction takes a snapshot on entry and restores it if anything
raises, which makes a commit all-or-nothing.
"""
import copy
import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from .. import commitments as CM
from .. import fence as F
from .. import handle as H
from .. import ids
from .. import knowledge as K
from ..config import DEFAULT, Decisions
from ..gate import Accepted, gate
from ..model import (ACCESS_DENIED, ACTIVE, AGENT, INVALIDATED, NEVER_TRUE, PENDING_ERASURE, QUARANTINED, RETRACTED,
                     SUPERSEDED, TOOL, UNAVAILABLE, USER, Claim, ClaimContent, ClaimState, Episode, ErasureRecord,
                     Evidence, SlotResult, SupportEdge, Suppression, Transition)
from ..normalise import fold, search_tokens, tokens
from ..policy import lookup, registry
from ..render import render_context, render_structured
from ..resolve import admissible, resolve
from ..temporal import asserted_interval, covers, effective_interval, eligible_at, status_at

EXTRACTOR_VERSION = "proto-x1"
HEAD_FS_FIELDS = ("subject_id", "org_id", "agent_id", "status", "content_closed", "merge_ids_in_force",
                  "member_set_version", "consent_memory", "do_not_contact", "erased_at", "sessions", "kind",
                  "assurance")
HEAD_PG_FIELDS = ("slots", "slot_at")


@dataclass
class Head:
    subject_id: str
    org_id: str
    agent_id: str
    status: str = "active"                  # active | pending_erasure | erased
    content_closed: bool = False
    merge_ids_in_force: List[str] = field(default_factory=list)
    member_set_version: int = 0
    consent_memory: bool = True
    do_not_contact: bool = False
    slots: Dict[str, SlotResult] = field(default_factory=dict)
    slot_at: Dict[str, float] = field(default_factory=dict)
    erased_at: Optional[float] = None
    sessions: Set[str] = field(default_factory=set)
    kind: str = "person"                    # person | account | endpoint
    assurance: str = "channel_verified"


@dataclass
class Job:
    subject_id: str
    evidence_ids: Tuple[str, ...]
    context_ids: Tuple[str, ...]
    q17_recovery_of: Optional[str] = None


@dataclass
class Report:
    created: List[str] = field(default_factory=list)
    supported: List[str] = field(default_factory=list)
    retracted: List[str] = field(default_factory=list)
    quarantined: List[str] = field(default_factory=list)
    invalidated: List[str] = field(default_factory=list)
    rejections: list = field(default_factory=list)
    fenced: List[Tuple[int, str]] = field(default_factory=list)
    deferred: List[Tuple[int, str]] = field(default_factory=list)
    anomalies: list = field(default_factory=list)


class Memory:
    def __init__(self, d: Decisions = DEFAULT, policy_version: int = 1, seed: int = 0):
        self.d = d
        self.policy_version = policy_version
        self.reg = registry(d, policy_version)
        self._rng = random.Random(seed)                # deterministic keys: restore/replay can reproduce ids
        # ---- FS
        self.org_keys: Dict[str, bytes] = {}
        self.heads: Dict[str, Head] = {}
        self.keys: Dict[str, Optional[bytes]] = {}
        self.index: Dict[str, str] = {}
        self.evidence: Dict[str, Evidence] = {}
        self.ev_seq: List[str] = []
        self.epoch: Dict[str, int] = {}
        self.epoch_log: Dict[str, List[Tuple[int, str, float]]] = {}
        self.merged_into: Dict[str, Tuple[str, str]] = {}
        self.merges: Dict[str, dict] = {}
        self.merges_undone: Set[str] = set()
        self.org_erased_at: Dict[str, float] = {}
        self.session_erased_before: Dict[str, float] = {}
        self.inbound_dedup: Dict[str, str] = {}
        self.written_at: Dict[str, float] = {}
        self.links: Dict[str, Set[str]] = {}            # person root -> linked accounts (authoritative links)
        # ---- PG
        self.claims: Dict[str, Claim] = {}
        self.suppressions: Dict[str, List[Suppression]] = {}
        self.episodes: Dict[str, Episode] = {}
        self.manifests: List[Tuple[float, object]] = []
        self.manifest_subject: Dict[str, str] = {}
        self.fts: Dict[str, dict] = {}                  # search projection (claim id -> indexed row)
        self.derived: Dict[Tuple[str, str], dict] = {}  # (kind, subject) -> derived artifact (judges, leads…)
        self.knowledge: Dict[str, K.Item] = {}
        self.cevents: List[CM.Event] = []
        self.crows = CM.MutableRow()
        self.identity_applied: List[dict] = []          # PG projection of identity events (C-1a)
        self.retractions: List[dict] = []               # LA-9 retraction records
        self.replay_watermark = 0                       # LA-10 recovery watermark (PG)
        # ---- WORM (never restored)
        self.erasure_log: List[ErasureRecord] = []
        self.worm: List[dict] = []
        # ---- harness
        self.anomalies: list = []
        self.purpose: Dict[str, frozenset] = {}
        self.unavailable: Set[str] = set()      # evidence ids transiently unreadable (fault injection)
        self.handle_secret = bytes(self._rng.getrandbits(8) for _ in range(32))
        self._n = 0
        self._rseq = 0                           # evidence-store receipt sequence
        self.seq = 0                             # global operation sequence (journal order)

    # ------------------------------------------------------------------ util
    def _id(self, p):
        self._n += 1
        return "%s%d" % (p, self._n)

    def _newkey(self) -> bytes:
        return bytes(self._rng.getrandbits(8) for _ in range(32))

    def _tick(self) -> int:
        self.seq += 1
        return self.seq

    @contextmanager
    def txn(self):
        snap = copy.deepcopy(self.__dict__)
        try:
            yield
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(snap)
            raise

    def _bump(self, scope: str, cause: str, t: float):
        self.epoch[scope] = self.epoch.get(scope, 0) + 1
        self.epoch_log.setdefault(scope, []).append((self.epoch[scope], cause, t))

    def root(self, s: str) -> str:
        seen = set()
        while s in self.merged_into and s not in seen:
            seen.add(s)
            s = self.merged_into[s][0]
        return s

    def members(self, s: str) -> List[str]:
        r = self.root(s)
        return sorted(x for x in self.heads if self.root(x) == r)

    def set_purpose(self, agent_id: str, keys):
        self.purpose[agent_id] = frozenset(keys)

    def wref(self, subject: str) -> str:
        return ids.worm_ref(self.org_keys[self.heads[subject].org_id], subject)

    # ---------------------------------------------------------------- binding (FS)
    def _index_key(self, org, agent, channel, user_key, assurance, api_key):
        ok = self.org_keys.setdefault(org, self._newkey())
        if not self.d.identity_assurance:
            return ids.index_key(ok, agent, "*", user_key)            # MAP N1: no channel component
        if assurance == "asserted":
            return ids.index_key(ok, agent, "asserted:%s:%s" % (channel, api_key or ""), user_key)
        return ids.index_key(ok, agent, channel, user_key)

    def _bind(self, org, agent, channel, user_key, session, assurance="channel_verified", api_key=None) -> str:
        ix = self._index_key(org, agent, channel, user_key, assurance, api_key)
        sid = self.index.get(ix)
        if sid is None or self.heads[sid].status != "active":
            sid = self._id("sub_")                    # opaque, never derived from the identifier
            kind = "endpoint" if (self.d.identity_assurance and assurance == "asserted") else "person"
            self.heads[sid] = Head(sid, org, agent, kind=kind, assurance=assurance)
            self.keys[sid] = self._newkey()
            self.index[ix] = sid
        self.heads[sid].sessions.add(session)
        return sid

    def _stamp(self, ev: Evidence, sid: str):
        ev.subject_id = ev.source_member_id = sid
        ev.epochs = {"org": self.epoch.get("org:" + ev.org_id, 0), "subject": self.epoch.get("subject:" + sid, 0),
                     "session": self.epoch.get("session:" + ev.session_id, 0)}
        ev.merge_ids_at_ingestion = self._merges_in_force(sid)
        ev.bound = True

    def _merges_in_force(self, sid: str) -> Tuple[str, ...]:
        if self.d.merge_ids_basis == "path":                      # LA-3
            out, cur, seen = [], sid, set()
            while cur in self.merged_into and cur not in seen:
                seen.add(cur)
                nxt, mid = self.merged_into[cur]
                out.append(mid)
                cur = nxt
            return tuple(sorted(out))
        return tuple(sorted(self.heads[self.root(sid)].merge_ids_in_force + self.heads[sid].merge_ids_in_force))

    # ---------------------------------------------------------------- ingest
    def write_message(self, org: str, agent: str, channel: str, user_key: str, session: str, role: str, text: str,
                      t: float, app_ts: Optional[float] = None, provider_msg_id: Optional[str] = None,
                      source_system: Optional[str] = None, tool_args: str = "", assurance: str = "channel_verified",
                      api_key: Optional[str] = None) -> Evidence:
        """The evidence-store transaction (Firestore). R-1: stamps are taken HERE when stamp_at == 'write'."""
        ok = self.org_keys.setdefault(org, self._newkey())
        if self.d.inbound_dedup and provider_msg_id:
            dk = ids.dedup_key(ok, channel, provider_msg_id)
            if dk in self.inbound_dedup and self.inbound_dedup[dk] in self.evidence:
                return self.evidence[self.inbound_dedup[dk]]          # redelivery: same evidence
        self._rseq += 1
        eid = self._id("ev_")
        observed = t if self.d.order_by == "receipt" or app_ts is None else app_ts
        ev = Evidence(eid, org, "", "", agent, session, role, text, observed, epochs={},
                      source_system=source_system, tool_args=tool_args,
                      extraction_state="pending" if role in (USER, TOOL, "operator") else "not_applicable",
                      channel=channel, registered=False, bound=False, user_key=user_key, receipt_seq=self._rseq,
                      app_ts=app_ts, seal_state="unsealed")
        ev._assurance, ev._api_key = assurance, api_key
        if self.d.stamp_at == "write":
            self._stamp(ev, self._bind(org, agent, channel, user_key, session, assurance, api_key))
        if self.d.inbound_dedup and provider_msg_id:
            ev.dedup_key = ids.dedup_key(ok, channel, provider_msg_id)
            self.inbound_dedup[ev.dedup_key] = eid
        self.evidence[eid] = ev
        self.ev_seq.append(eid)
        self.written_at[eid] = t
        self._tick()
        return ev

    def register(self, eid: str, t: float) -> Evidence:
        """The PG registration step (evidence_meta + outbox). Late binding is the C-1 defect."""
        ev = self.evidence[eid]
        if not ev.bound:
            # v2 as written: the subject and epochs are resolved NOW, from today's binding
            self._stamp(ev, self._bind(ev.org_id, ev.agent_id, ev.channel, ev.user_key, ev.session_id,
                                       getattr(ev, "_assurance", "channel_verified"), getattr(ev, "_api_key", None)))
        h = self.heads[ev.subject_id]
        if h.status != "active" and ev.status == "active":
            ev.status = PENDING_ERASURE                 # registered after its subject was erased
            ev.extraction_state = "fenced"
        ev.registered = True
        self._tick()
        return ev

    def seal(self, eid: str, t: float):
        ev = self.evidence.get(eid)
        if ev is None or ev.seal_state != "unsealed":
            return
        ev.sealed_hash = ids.sealed_hash(self.org_keys[ev.org_id], ev.author_role, ev.author_role, ev.channel,
                                         ev.text)
        ev.seal_state = "sealed"

    def seal_sweep(self, now: float, window: float) -> List[str]:
        """R-24: seal anything the runtime failed to seal (crash between save and seal)."""
        out = []
        for eid in list(self.ev_seq):
            ev = self.evidence[eid]
            if ev.seal_state == "unsealed" and ev.status == "active" and now - self.written_at.get(eid, now) >= window:
                self.seal(eid, now)
                out.append(eid)
        return out

    def ingest(self, org: str, agent: str, channel: str, user_key: str, session: str, role: str, text: str,
               t: float, source_system: Optional[str] = None, tool_args: str = "", **kw) -> Evidence:
        """Write + register + seal in one step (the settled-turn path)."""
        ev = self.write_message(org, agent, channel, user_key, session, role, text, t, source_system=source_system,
                                tool_args=tool_args, **kw)
        if ev.registered:
            return ev                                   # dedup hit
        self.register(ev.evidence_id, t)
        self.seal(ev.evidence_id, t)
        return ev

    def mutate_message(self, eid: str, t: float, text: Optional[str] = None, role: Optional[str] = None,
                       delete: bool = False):
        """In-place edits and deletes by runtime paths (aborted turns, close-turn rewrites) or clients."""
        ev = self.evidence.get(eid)
        if ev is None:
            return
        sealed = ev.seal_state == "sealed"
        if delete:
            if self.d.require_seal and sealed:
                with self.txn():                         # withdrawn: lineage re-evaluation (R-2)
                    ev.status, ev.seal_state = INVALIDATED, "withdrawn"
                    self._pg_drop_support(eid, t, "evidence_withdrawn")
                    self._worm({"kind": "withdraw", "evidence_id": eid, "t": t})
            else:
                del self.evidence[eid]                   # the runtime's physical delete; claims are not told
                self.ev_seq = [e for e in self.ev_seq if e != eid]
            return
        if text is not None:
            ev.text = text
        if role is not None:
            ev.author_role = role
        if self.d.require_seal and sealed:
            self._tampered(ev, t)

    def _tampered(self, ev: Evidence, t: float):
        ev.seal_state = "tampered"
        self.anomalies.append(("evidence_tampered", ev.evidence_id))
        for c in self.claims.values():
            if any(e.evidence_id == ev.evidence_id for e in c.state.support.values()) and c.state.status == ACTIVE:
                c.state.transitions.append(Transition(t, ACTIVE, QUARANTINED, "evidence_tampered", ev.evidence_id))
                c.state.status, c.state.attributed = QUARANTINED, False
        for s in list(self.heads):
            if self.heads[s].status == "active":
                self.refresh_all(s, t)

    def _verify_seals(self, eids: Sequence[str], t: float):
        for e in eids:
            ev = self.evidence.get(e)
            if ev is not None and ev.seal_state == "sealed":
                hh = ids.sealed_hash(self.org_keys[ev.org_id], ev.author_role, ev.author_role, ev.channel, ev.text)
                if hh != ev.sealed_hash:
                    self._tampered(ev, t)                # e.g. a client wrote the document directly

    # ------------------------------------------------------------ extraction
    def _extractable(self, ev: Evidence) -> bool:
        return ev.registered and (not self.d.require_seal or ev.seal_state == "sealed")

    def prepare(self, subject: str, only: Optional[Sequence[str]] = None) -> Job:
        pend = [e for e in self.ev_seq if self.evidence[e].subject_id == subject and self._extractable(self.evidence[e])
                and self.evidence[e].extraction_state == "pending" and (only is None or e in only)]
        sessions = {self.evidence[e].session_id for e in pend}
        ctx = [e for e in self.ev_seq if self.evidence[e].session_id in sessions and self.evidence[e].registered]
        return Job(subject, tuple(pend), tuple(ctx))

    def reextract_job(self, eids: Sequence[str]) -> Job:
        for e in eids:
            if e in self.evidence and self.evidence[e].extraction_state in ("done",):
                self.evidence[e].extraction_state = "pending"
        subj = self.evidence[eids[0]].subject_id
        return self.prepare(subj, list(eids))

    def _stamps(self, eids: Sequence[str]) -> List[F.Stamp]:
        out = []
        for e in eids:
            ev = self.evidence.get(e)
            if ev is None or not ev.bound:
                out.append(F.Stamp(e, False, "missing", {}, {}, (), "", 0.0))
                continue
            out.append(F.Stamp(e, True, ev.status, dict(ev.epochs),
                               {"org": "org:" + ev.org_id, "subject": "subject:" + ev.subject_id,
                                "session": "session:" + ev.session_id},
                               tuple(ev.merge_ids_at_ingestion), ev.subject_id, ev.observed_at,
                               transient_unavailable=e in self.unavailable))
        return out

    def _fctx(self, q17=False) -> F.Context:
        return F.Context(self.epoch_log, dict(self.merged_into), set(self.merges_undone),
                         {s: h.erased_at for s, h in self.heads.items() if h.erased_at is not None},
                         dict(self.org_erased_at), {s: h.org_id for s, h in self.heads.items()},
                         set(self.heads), q17_recovery=q17)

    def _is_suppressed_fn(self, subjects: Sequence[str]):
        def f(key, canon, observed_at):
            for s in subjects:
                k = self.keys.get(s)
                if not k:
                    continue
                fp = ids.suppression_fp(k, key, canon)
                for sp in self.suppressions.get(s, []):
                    if sp.fingerprint == fp and (self.d.suppression_scope == "forever"
                                                 or observed_at <= sp.observed_before):
                        return True
            return False
        return f

    def commit(self, job: Job, proposals: Sequence[dict], t: float, extractor_version: str = EXTRACTOR_VERSION,
               reextract: bool = False, recorded: Optional[Dict[int, tuple]] = None, _record: bool = True) -> Report:
        rep = Report()
        with self.txn():
            src_head = self.heads[job.subject_id]
            job = Job(job.subject_id, tuple(e for e in job.evidence_ids if e in self.evidence),
                      tuple(e for e in job.context_ids if e in self.evidence), job.q17_recovery_of)
            # (evidence deleted between prepare and commit, e.g. an aborted turn, simply drops out)
            if src_head.status != "active" and job.q17_recovery_of is None:
                for e in job.evidence_ids:
                    self.evidence[e].extraction_state = "fenced"
                rep.fenced.append((-1, "subject_" + src_head.status))
                return rep
            target_members = self.members(job.subject_id)
            if not all(self.heads[m].consent_memory for m in target_members) and job.evidence_ids:
                for e in job.evidence_ids:
                    self.evidence[e].extraction_state = "skipped_consent"
                return rep
            if self.d.require_seal:
                self._verify_seals(job.context_ids, t)
            batch = {e: self.evidence[e] for e in job.context_ids if e in self.evidence}
            cand = [c for c in self.claims.values() if c.content.subject_id in target_members
                    and c.state.attributed]
            cand += [c for a in self._accounts_of(job.subject_id) for c in self.claims.values()
                     if c.content.subject_id == a]
            purpose = self.purpose.get(src_head.agent_id, frozenset())
            g = gate(proposals, batch, list(job.context_ids), cand, self.reg, self.d,
                     self._is_suppressed_fn(target_members + [job.subject_id]), purpose,
                     pending=frozenset(job.evidence_ids))
            rep.rejections = g.rejections
            rep.anomalies = g.anomalies
            self.anomalies += g.anomalies
            if job.q17_recovery_of:
                g.accepted = [a for a in g.accepted if a.mode != "confirmed"]    # confirmed claims are not recovered
            if reextract and self.d.reextract_supersede:
                self._supersede_by_lineage(job, g.accepted, extractor_version, t, rep)
            touched = set()
            fenced_ev, applied_ev, deferred_ev = set(), set(), set()
            decisions = {}
            applied_log = []
            batch_new: Dict[tuple, str] = {}
            for a in sorted(g.accepted, key=lambda a: (self.evidence[a.anchor[0][0]].receipt_seq, a.index)):
                fr = F.fence(self._stamps(a.input_evidence_ids), self._fctx(q17=job.q17_recovery_of is not None))
                if recorded is not None and self.d.replay_identity == "recorded" and fr.action != F.REJECT \
                        and a.index in recorded:
                    act, tgt, mr, attr = recorded[a.index]               # LA-1: the identity decision taken then
                    if act == F.REJECT:
                        fr = F.Result(F.REJECT, "recorded_reject")
                    elif tgt in self.heads:
                        fr = F.Result(act, "recorded", target_subject=tgt, merges_recorded=tuple(mr), attributed=attr)
                decisions[a.index] = (fr.action, fr.target_subject, tuple(fr.merges_recorded), fr.attributed)
                if fr.action == F.REJECT:
                    rep.fenced.append((a.index, fr.reason))
                    fenced_ev.update(a.input_evidence_ids)
                    continue
                if fr.action == F.DEFER:
                    rep.deferred.append((a.index, fr.reason))
                    deferred_ev.update(a.input_evidence_ids)
                    continue
                if a.kind in ("new_claim", "support") and self.d.require_seal:
                    # LA-4: commit must be a pure function of (proposals, pre-state). (1) A proposal whose own
                    # derivation already exists was processed before: no-op, whatever dedup would now say.
                    # (2) Two proposals of one fact in one batch share one claim (deterministic intra-batch dedup).
                    tgt0 = fr.target_subject
                    if a.key.startswith("account.") and self._accounts_of(tgt0):
                        tgt0 = self._accounts_of(tgt0)[0]
                    deriv = "recovery:" + job.q17_recovery_of if job.q17_recovery_of else "orig"
                    own = ids.claim_id(self.keys[tgt0], a.anchor[0][0], a.key, a.value[1], deriv,
                                       self.d.claim_id_derivation_tag)
                    if own in self.claims and own != a.target_claim_id:
                        applied_ev.update(a.input_evidence_ids)
                        continue
                    gk = (tgt0, a.key, a.value, a.source, a.source_member_id)
                    if self.d.dedup_mode == "per_evidence":
                        pass                         # LA-11 + LA-4: one claim per evidence; own-id check suffices
                    elif a.kind == "new_claim" and gk in batch_new:
                        a.kind, a.target_claim_id = "support", batch_new[gk]
                    elif a.kind == "new_claim":
                        batch_new[gk] = own
                applied_log.append((copy.deepcopy(a), fr.action, fr.target_subject, tuple(fr.merges_recorded),
                                    fr.attributed))
                tgt = self._apply(a, fr, t, rep, job, extractor_version)
                applied_ev.update(a.input_evidence_ids)
                touched.add((tgt, a.key))
            for e in job.evidence_ids:
                ev = self.evidence[e]
                if e in deferred_ev:
                    ev.extraction_state = "pending"          # the watermark does not pass deferred evidence
                elif e in fenced_ev and e not in applied_ev:
                    ev.extraction_state = "fenced"
                else:
                    ev.extraction_state = "done"
            if _record:
                rec = {"seq": self._tick(), "subject": job.subject_id, "evidence_ids": job.evidence_ids,
                       "context_ids": job.context_ids, "q17": job.q17_recovery_of, "proposals": list(proposals),
                       "t": t, "version": extractor_version, "reextract": reextract, "decisions": decisions,
                       "applied": applied_log, "superseded": list(rep.invalidated),
                       "states": {e: self.evidence[e].extraction_state for e in job.evidence_ids}}
                for e in job.evidence_ids:
                    self.evidence[e].commit_records.append(rec)      # LA-1: kept with the evidence (FS)
            for subj, key in touched:
                self._refresh(self.root(subj), key, t)
                self._index_claims_of(subj)
        return rep

    def replay_record(self, rec: dict) -> Report:
        """LA-1 (generalised): roll forward a commit by applying its RECORDED outcome (gate + identity), never by
        re-deciding against the current evidence and identity state. Later journal entries re-apply in order."""
        rep = Report()
        t = rec["t"]
        job = Job(rec["subject"], tuple(rec["evidence_ids"]), tuple(rec["context_ids"]), rec["q17"])
        with self.txn():
            for cid in rec.get("superseded", ()):
                c = self.claims.get(cid)
                if c is not None and c.state.status == ACTIVE:
                    c.state.transitions.append(Transition(t, ACTIVE, INVALIDATED, "re_extracted", rec["version"]))
                    c.state.status = INVALIDATED
            touched = set()
            for a, act, tgt, mr, attr in rec.get("applied", ()):
                if tgt not in self.heads or any(e not in self.evidence for e, _ in a.anchor):
                    continue                           # the subject or the evidence is gone (erasure wins)
                if a.kind in ("support", "retract") and a.target_claim_id not in self.claims:
                    continue
                fr = F.Result(act, "replay", target_subject=tgt, merges_recorded=tuple(mr), attributed=attr)
                touched.add((self._apply(copy.deepcopy(a), fr, t, rep, job, rec["version"]), a.key))
            for e, st in rec.get("states", {}).items():
                if e in self.evidence:
                    self.evidence[e].extraction_state = st
            for subj, key in touched:
                if subj in self.heads:
                    self._refresh(self.root(subj), key, t)
                    self._index_claims_of(subj)
        return rep

    def _supersede_by_lineage(self, job: Job, accepted: List[Accepted], version: str, t: float, rep: Report):
        """C-9 / R-9: claims derived ONLY from this evidence by an older version, and not re-proposed, end."""
        keep = {(a.key, a.value) for a in accepted if a.kind in ("new_claim", "support")}
        evs = set(job.evidence_ids)
        for c in self.claims.values():
            if c.state.status != ACTIVE or c.content.extractor_version == version or c.content.committed_at > t:
                continue                    # LA-8: bounded by the re-extraction's own knowledge time
            sup = {e.evidence_id for e in c.state.support.values()}
            if not sup or not sup <= evs:
                continue
            if (c.content.key, c.content.value) in keep:
                continue
            c.state.transitions.append(Transition(t, ACTIVE, INVALIDATED, "re_extracted", version))
            c.state.status = INVALIDATED
            rep.invalidated.append(c.id)

    def _accounts_of(self, subject: str) -> List[str]:
        return sorted(self.links.get(self.root(subject), set())) if subject in self.heads else []

    def _apply(self, a: Accepted, fr: F.Result, t: float, rep: Report, job: Job, version: str) -> str:
        target = fr.target_subject
        if a.key.startswith("account.") and self._accounts_of(target):
            target = self._accounts_of(target)[0]       # account-scope claims live on the linked account
        if a.kind == "new_claim":
            k = self.keys[target]
            deriv = "recovery:" + job.q17_recovery_of if job.q17_recovery_of else "orig"
            cid = ids.claim_id(k, a.anchor[0][0], a.key, a.value[1], deriv, self.d.claim_id_derivation_tag)
            if cid in self.claims:
                rep.supported.append(cid)       # idempotent re-commit of the same derivation
                return target
            ev0 = self.evidence[a.anchor[0][0]]
            content = ClaimContent(cid, target, a.source_member_id, ev0.org_id, ev0.agent_id, a.key, a.value,
                                   a.source, a.mode, a.value_check, a.normaliser_id, a.anchor, a.prompt_ref,
                                   a.valid_from, a.valid_until, a.observed_at, t, version,
                                   self.policy_version, deriv, observed_seq=ev0.receipt_seq,
                                   written_via="command" if ev0.author_role == "operator" else "llm")
            st = ClaimState(merge_ids=list(fr.merges_recorded))
            if fr.action == F.QUARANTINE:
                st.status, st.attributed = QUARANTINED, False
                st.transitions.append(Transition(t, "new", QUARANTINED, "recorded_merge_undone", fr.reason))
                rep.quarantined.append(cid)
            for eid, _q in a.anchor:
                e = self.evidence[eid]
                st.support[ids.edge_id(k, cid, eid)] = SupportEdge(ids.edge_id(k, cid, eid), eid, a.source,
                                                                   e.source_member_id, e.observed_at,
                                                                   tuple(fr.merges_recorded))
            c = Claim(content, st)
            self.claims[cid] = c
            if fr.action != F.QUARANTINE:
                rep.created.append(cid)
                for r in self.retractions:
                    self._apply_retraction_record(r, c, t, rep)
                if self.d.supersession_storage_mode == "persisted":
                    self._persist_supersession(c, t)
        elif a.kind == "support":
            c = self.claims[a.target_claim_id]
            if fr.action == F.QUARANTINE:
                return target
            k = self.keys[c.content.subject_id]
            for eid, _q in a.anchor:
                e = self.evidence[eid]
                eg = ids.edge_id(k, c.id, eid)
                c.state.support.setdefault(eg, SupportEdge(eg, eid, a.source, e.source_member_id, e.observed_at,
                                                           tuple(fr.merges_recorded)))
            rep.supported.append(c.id)
        elif a.kind in ("retract", "retract_record"):
            if fr.action == F.QUARANTINE:
                return target
            ev0 = self.evidence[a.anchor[0][0]]
            if a.kind == "retract":
                c = self.claims[a.target_claim_id]
                c.state.transitions.append(Transition(t, c.state.status, RETRACTED, a.cause, a.anchor[0][0],
                                                      effective_at=a.observed_at, merge_ids=tuple(fr.merges_recorded)))
                c.state.status, c.state.retract_cause = RETRACTED, a.cause
                rep.retracted.append(c.id)
            if self.d.retraction_records:
                r = {"key": a.key, "value": a.value, "source": a.source, "member": a.source_member_id,
                     "cause": a.cause, "observed_at": a.observed_at, "observed_seq": ev0.receipt_seq,
                     "evidence_id": ev0.evidence_id, "t": t, "merge_ids": tuple(fr.merges_recorded)}
                if r not in self.retractions:
                    self.retractions.append(r)
                for c in list(self.claims.values()):
                    self._apply_retraction_record(r, c, t, rep)
        return target

    def _apply_retraction_record(self, r: dict, c: Claim, t: float, rep: Optional[Report] = None):
        """LA-9: a recorded retraction ends every matching claim of its group observed at or before it."""
        if c.state.status not in (ACTIVE, RETRACTED) or c.content.key != r["key"] or c.content.value != r["value"]:
            return
        if (c.content.source, c.content.source_member_id) != (r["source"], r["member"]):
            return
        if (c.content.observed_at, c.content.observed_seq) > (r["observed_at"], r["observed_seq"]):
            return
        if c.state.status == RETRACTED:
            # converge to the same end whatever the commit order: never_true dominates; otherwise the EARLIEST
            # applicable no_longer_true end wins
            cur_eff = next((x.effective_at for x in reversed(c.state.transitions) if x.to == RETRACTED), None)
            if c.state.retract_cause == NEVER_TRUE:
                return
            if r["cause"] != NEVER_TRUE and cur_eff is not None and cur_eff <= r["observed_at"]:
                return
        c.state.transitions.append(Transition(t, c.state.status, RETRACTED, r["cause"], r["evidence_id"],
                                              effective_at=r["observed_at"], merge_ids=tuple(r["merge_ids"])))
        c.state.status, c.state.retract_cause = RETRACTED, r["cause"]
        if rep is not None:
            rep.retracted.append(c.id)

    def _persist_supersession(self, new: Claim, t: float):
        nvf, nvu = asserted_interval(new, self.d)
        for o in self.claims.values():
            if o is new or o.content.key != new.content.key or o.state.status != ACTIVE:
                continue
            if (o.content.source, o.content.source_member_id) != (new.content.source, new.content.source_member_id):
                continue
            if lookup(self.reg, o.content.key).cardinality != "SINGLE":
                continue
            if o.content.observed_at < new.content.observed_at:
                ovf, ovu = asserted_interval(o, self.d)
                if ovf < nvu and nvf < ovu:
                    o.state.transitions.append(Transition(t, ACTIVE, SUPERSEDED, "superseded_by", new.id))
                    o.state.status, o.state.superseded_by = SUPERSEDED, new.id

    # ---------------------------------------------------------- search projection (M-9)
    def _index_claims_of(self, subject: str):
        if self.d.search_index == "none":
            return
        ms = set(self.members(subject)) | set(self._accounts_of(subject))
        for c in self.claims.values():
            if c.content.subject_id in ms:
                self._index_one(c)

    def _index_one(self, c: Claim):
        self.fts[c.id] = {"subject": c.content.subject_id, "key": c.content.key, "value": c.content.value[1],
                          "tokens": sorted(search_tokens(c.content.key.replace(".", " ") + " " + c.content.value[1])),
                          "status": c.state.status, "claim": copy.deepcopy(c)}

    def reindex_all(self):
        """The async projection job (rebuild from the system of record)."""
        self.fts = {}
        if self.d.search_index != "none":
            for c in self.claims.values():
                self._index_one(c)

    # ------------------------------------------------------------ projection
    def _member_claims(self, s: str) -> List[Claim]:
        ms = set(self.members(s))
        return [c for c in self.claims.values() if c.content.subject_id in ms and c.state.attributed]

    def resolve_now(self, s: str, key: str, as_of: float, cutoff: float) -> SlotResult:
        p = lookup(self.reg, key)
        return resolve(p, self._member_claims(s), as_of, cutoff, self.d, key=key)

    def _refresh(self, s: str, key: str, t: float):
        p = lookup(self.reg, key)
        if p is None or not p.current_state_eligible:
            return
        h = self.heads[s]
        new = self.resolve_now(s, key, t, t)
        old = h.slots.get(key)
        new.state_version = (old.state_version if old else 0) + (0 if old and old.signature() == new.signature() else 1)
        h.slots[key] = new
        h.slot_at[key] = t

    def refresh_all(self, s: str, t: float):
        for key, p in self.reg.items():
            if p.current_state_eligible and not p.is_namespace:
                self._refresh(self.root(s), key, t)

    def rebuild_head(self, s: str, t: float) -> Dict[str, tuple]:
        out = {}
        for key, p in self.reg.items():
            if p.current_state_eligible and not p.is_namespace:
                out[key] = self.resolve_now(self.root(s), key, t, t).signature()
        return out

    # --------------------------------------------------------------- deletion
    def _worm(self, rec: dict):
        rec = dict(rec)
        rec["seq"] = self._tick()
        self.worm.append(rec)

    def _pg_drop_support(self, eid: str, t: float, cause: str):
        for c in self.claims.values():
            gone = [k for k, e in c.state.support.items() if e.evidence_id == eid]
            for k in gone:
                del c.state.support[k]
            if gone and not c.state.support and c.state.status in (ACTIVE, RETRACTED, SUPERSEDED):
                c.state.transitions.append(Transition(t, c.state.status, INVALIDATED, cause, eid))
                c.state.status = INVALIDATED
        for s in list(self.heads):
            if self.heads[s].status == "active":
                self.refresh_all(s, t)

    def erase_evidence(self, eid: str, t: float):
        """Erasure of one evidence record (e.g. part of a conversation)."""
        with self.txn():
            self.evidence[eid].status = "erased"
            self._pg_drop_support(eid, t, "no_remaining_support")
            self._worm({"kind": "erase_evidence", "evidence_id": eid, "t": t})

    def forget_fact(self, subject: str, key: str, value_text: str, t: float) -> List[str]:
        canon = fold(value_text)
        with self.txn():
            ms = self.members(subject)
            hit = self._pg_forget_fact(ms, key, canon, t)
            # agent turns echoing the fact (M19) and anchors: FS side
            sessions = {s for m in ms for s in self.heads[m].sessions}
            for ev in self.evidence.values():
                if ev.session_id in sessions and ev.author_role == AGENT and canon and canon in fold(ev.text):
                    ev.status = "context_suppressed"
            self.erasure_log.append(ErasureRecord(self._id("er_"), tuple(ms), {}, t, 0, "forget_fact"))
            self._worm({"kind": "forget_fact", "subjects": [self.wref(m) for m in ms], "key": key, "canon": canon,
                        "t": t})
        return hit

    def _pg_forget_fact(self, ms, key, canon, t) -> List[str]:
        hit = []
        for c in self.claims.values():
            if c.content.key == key and c.content.value[1] == canon and (
                    c.content.subject_id in ms or c.content.source_member_id in ms):
                if self.d.suppression_scope == "evidence_before" and c.content.observed_at > t:
                    continue                # LA-8: a forget is bounded by its knowledge time (replay-safe)
                if c.state.status != PENDING_ERASURE:
                    c.state.transitions.append(Transition(t, c.state.status, PENDING_ERASURE, "forget_fact"))
                    c.state.status, c.state.archive_reason = PENDING_ERASURE, "forget_fact"
                hit.append(c.id)
                for eid, _ in c.content.anchor:
                    if eid in self.evidence:
                        self.evidence[eid].status = "context_suppressed"
        for m in ms:
            if self.keys.get(m):
                fp = ids.suppression_fp(self.keys[m], key, canon)
                if not any(sp.fingerprint == fp for sp in self.suppressions.get(m, [])):
                    self.suppressions.setdefault(m, []).append(Suppression(fp, t, t))
        for ep in self.episodes.values():
            if ep.subject_id in ms and any(self.evidence[e].status == "context_suppressed"
                                           for e in ep.evidence_ids if e in self.evidence):
                ep.summary_status = "regenerate_pending"
        for m in ms:
            self.refresh_all(m, t)
        return hit

    def stop_remembering(self, subject: str):
        for m in self.members(subject):
            self.heads[m].consent_memory = False

    def forget_me(self, subject: str, t: float) -> ErasureRecord:
        """R6b Option B: erase the whole merged subject; binding (FS) first, then PG archive."""
        with self.txn():
            ms = self.members(subject)
            epochs = self._fs_forget_me(ms, t)
            rec = ErasureRecord(self._id("er_"), tuple(ms), epochs, t,
                                max(self.heads[m].member_set_version for m in ms), "forget_me")
            self.erasure_log.append(rec)
            self._worm({"kind": "forget_me", "subjects": [self.wref(m) for m in ms],
                        "epochs": {self.wref(m): epochs["subject:" + m] for m in ms}, "t": t})
            self._pg_forget_me(set(ms), t)
            if not self.d.pending_erasure_enabled:
                self._physical_delete(set(ms))
        return rec

    def _fs_forget_me(self, ms, t) -> Dict[str, int]:
        epochs = {}
        for m in ms:
            h = self.heads[m]
            self._bump("subject:" + m, "erasure", t)
            epochs["subject:" + m] = self.epoch["subject:" + m]
            h.status, h.erased_at = PENDING_ERASURE, t
            h.consent_memory, h.do_not_contact = False, True
            for sess in h.sessions:
                self._bump("session:" + sess, "erasure", t)
                self.session_erased_before[sess] = t
        for ix in [ix for ix, s in self.index.items() if s in ms]:
            del self.index[ix]                              # retire; next contact makes a new subject
        for ev in self.evidence.values():
            if ev.subject_id in ms:
                ev.status = PENDING_ERASURE
        return epochs

    def _pg_forget_me(self, ms: Set[str], t: float):
        self._archive_sweep(ms, t)
        if self.d.knowledge_erasure_handler:
            K.on_erase(self.knowledge.values(), set(ms), self.d.knowledge_min_contributors)
        if self.d.derived_writes_fenced:
            for k in [k for k in self.derived if k[1] in ms]:
                del self.derived[k]

    def _archive_sweep(self, ms: Set[str], t: float):
        for c in self.claims.values():
            if c.content.subject_id in ms or c.content.source_member_id in ms:
                if c.state.status != PENDING_ERASURE:
                    c.state.transitions.append(Transition(t, c.state.status, PENDING_ERASURE, "forget_me"))
                    c.state.status, c.state.archive_reason = PENDING_ERASURE, "forget_me"
            else:
                for k in [k for k, e in c.state.support.items() if e.source_member_id in ms]:
                    del c.state.support[k]
                if not c.state.support and c.state.status == ACTIVE:
                    c.state.transitions.append(Transition(t, ACTIVE, INVALIDATED, "support_erased"))
                    c.state.status = INVALIDATED
        for ep in self.episodes.values():
            if ep.subject_id in ms:
                ep.summary_status = PENDING_ERASURE

    def physical_deletion_job(self, now: float) -> dict:
        w = self.d.erasure_archive_window_days
        if w is None:
            return {"ran": False, "reason": "ERASURE_ARCHIVE_WINDOW unset", "deleted": 0}
        due = {s for s, h in self.heads.items() if h.status == PENDING_ERASURE and h.erased_at is not None
               and now - h.erased_at >= w}
        n = self._physical_delete(due)
        return {"ran": True, "deleted": n}

    def _physical_delete(self, ms: Set[str]) -> int:
        n = 0
        gone_claims = set()
        for cid in [c for c, v in self.claims.items() if v.content.subject_id in ms or v.content.source_member_id in ms]:
            del self.claims[cid]
            gone_claims.add(cid)
            n += 1
        gone_ev = {e for e, v in self.evidence.items() if v.subject_id in ms}
        for eid in gone_ev:
            del self.evidence[eid]
        self.ev_seq = [e for e in self.ev_seq if e in self.evidence]
        for eid in [e for e, ep in self.episodes.items() if ep.subject_id in ms]:
            del self.episodes[eid]
        self.retractions = [r for r in self.retractions if r["member"] not in ms]
        for s in ms:
            self.keys[s] = None                # crypto-shred
            self.suppressions.pop(s, None)
            self.heads[s].status = "erased"
            self.heads[s].slots = {}
        if self.d.registry_covers_v2_stores:   # red-team C-7: v2's own stores are registered too
            for cid in [c for c, r in self.fts.items() if r["subject"] in ms or c in gone_claims]:
                del self.fts[cid]
            for mid, s in list(self.manifest_subject.items()):
                if s in ms:
                    self.manifest_subject[mid] = "erased"          # rekey: aggregate survives, linkage does not
            for k in [k for k in self.derived if k[1] in ms]:
                del self.derived[k]
            self.cevents = [e for e in self.cevents if e.evidence_id not in gone_ev]
            for dk in [dk for dk, e in self.inbound_dedup.items() if e in gone_ev]:
                del self.inbound_dedup[dk]
        return n

    # --------------------------------------------------------------- identity
    def merge(self, absorbed: str, survivor: str, t: float) -> str:
        # LA-12: the identity authority refuses merges involving a non-active subject (erase-then-merge would
        # either pull archived content into a live person or make a live person's memory unwritable) and
        # merges between subjects already sharing a root (a second merge id would make undo ambiguous).
        if self.d.merge_ids_basis == "path":
            for s in (absorbed, survivor):
                if s not in self.heads or self.heads[s].status != "active":
                    raise ValueError("merge_refused:subject_not_active:" + s)
            if self.root(absorbed) == self.root(survivor):
                raise ValueError("merge_refused:already_same_subject")
        mid = self._id("m_")
        with self.txn():
            self._fs_merge(mid, absorbed, survivor, t)
            self._worm({"kind": "merge", "mid": mid, "absorbed": self.wref(absorbed),
                        "survivor": self.wref(survivor), "t": t})
            self._pg_identity_event({"kind": "merge", "mid": mid, "survivor": survivor, "absorbed": absorbed}, t)
        return mid

    def _fs_merge(self, mid, absorbed, survivor, t):
        self.merged_into[absorbed] = (survivor, mid)
        self.merges[mid] = {"absorbed": absorbed, "survivor": survivor, "at": t}
        for s in self.members(survivor):
            self.heads[s].merge_ids_in_force.append(mid)
        self.heads[absorbed].content_closed = True
        self._bump("subject:" + absorbed, "merge", t)
        self.heads[survivor].member_set_version += 1

    def _pg_identity_event(self, ev: dict, t: float):
        if any(x["mid"] == ev["mid"] and x["kind"] == ev["kind"] for x in self.identity_applied):
            return                                     # idempotent (C-1a projection)
        self.identity_applied.append(dict(ev, t=t))
        if ev["kind"] == "merge":
            self.refresh_all(ev["survivor"], t)
        elif ev["kind"] == "undo":
            self._pg_undo(ev["mid"], t)

    def undo_merge(self, mid: str, t: float):
        with self.txn():
            self._fs_undo(mid, t)
            m = self.merges[mid]
            self._worm({"kind": "undo", "mid": mid, "absorbed": self.wref(m["absorbed"]),
                        "survivor": self.wref(m["survivor"]), "t": t})
            self._pg_identity_event({"kind": "undo", "mid": mid, "survivor": m["survivor"],
                                     "absorbed": m["absorbed"]}, t)

    def _fs_undo(self, mid, t):
        m = self.merges[mid]
        self.merges_undone.add(mid)
        a, b = m["absorbed"], m["survivor"]
        if self.merged_into.get(a, (None, None))[1] == mid:
            del self.merged_into[a]
        for h in self.heads.values():
            if mid in h.merge_ids_in_force:
                h.merge_ids_in_force.remove(mid)
        self.heads[a].content_closed = False
        self.heads[b].member_set_version += 1
        self.heads[a].member_set_version += 1

    def _pg_undo(self, mid, t):
        m = self.merges[mid]
        a, b = m["absorbed"], m["survivor"]
        self.retractions = [r for r in self.retractions if mid not in r["merge_ids"]]
        for c in self.claims.values():
            if c.state.status == PENDING_ERASURE:
                continue                    # LA-6: erasure dominates; an undo never moves an erased claim
            if mid in c.state.merge_ids and c.state.status != QUARANTINED:
                c.state.transitions.append(Transition(t, c.state.status, QUARANTINED, "merge_undone", mid))
                c.state.status, c.state.attributed = QUARANTINED, False
            # M17: reverse lifecycle transitions caused by merge-epoch evidence
            for tr in list(c.state.transitions):
                if mid in tr.merge_ids and c.state.status == tr.to and tr.to != QUARANTINED:
                    c.state.transitions.append(Transition(t, tr.to, tr.frm, "undo_reversal", mid))
                    c.state.status = tr.frm
                    if tr.to == RETRACTED:
                        c.state.retract_cause = None
            # F-4: support edges contributed by merge-epoch evidence are removed
            gone = [k for k, e in c.state.support.items() if mid in e.merge_ids] \
                if self.d.undo_reverses_merge_support else []
            for k in gone:
                del c.state.support[k]
            if gone and not c.state.support and c.state.status == ACTIVE:
                c.state.transitions.append(Transition(t, ACTIVE, INVALIDATED, "support_was_merge_epoch", mid))
                c.state.status = INVALIDATED
        for ep in self.episodes.values():
            if mid in ep.merge_ids:
                ep.summary_status = QUARANTINED
        if self.d.knowledge_erasure_handler:
            K.on_undo(self.knowledge.values(), mid, self.d.knowledge_min_contributors)
        # refresh every root whose claims may have changed (not only the two merge parties)
        for s in {self.root(c.content.subject_id) for c in self.claims.values()} | {self.root(a), self.root(b)}:
            if s in self.heads and self.heads[s].status == "active":
                self.refresh_all(s, t)

    def transfer(self, subject: str, t: float):
        if self.d.transfer_policy != "fail_closed":
            raise NotImplementedError("D15 undecided: copying memory on transfer needs the evidence-move decision")
        self._bump("subject:" + subject, "transfer", t)
        self._worm({"kind": "transfer", "subject": self.wref(subject), "t": t})

    def recovery_job(self, mid: str, subject: str) -> Job:
        eids = tuple(e for e in self.ev_seq if self.evidence[e].subject_id == subject
                     and mid in self.evidence[e].merge_ids_at_ingestion and self.evidence[e].author_role == USER)
        sessions = {self.evidence[e].session_id for e in eids}
        ctx = tuple(e for e in self.ev_seq if self.evidence[e].session_id in sessions)
        return Job(subject, eids, ctx, q17_recovery_of=mid)

    # ---------------------------------------------------------------- accounts (C-5)
    def create_account(self, org: str, name: str) -> str:
        self.org_keys.setdefault(org, self._newkey())
        sid = self._id("acct_")
        self.heads[sid] = Head(sid, org, "*", kind="account")
        self.keys[sid] = self._newkey()
        return sid

    def link_account(self, person: str, account: str, source: str) -> bool:
        if self.d.account_sources == "authoritative" and source not in ("OPERATOR", "IMPORT", "CRM_SYSTEM"):
            return False                                # e.g. a free-mail domain match never links
        self.links.setdefault(self.root(person), set()).add(account)
        return True

    def operator_assert(self, subject: str, key: str, value: str, t: float, session: str = "op") -> Report:
        """An operator command: recorded as evidence (C-8.4), then committed through the gate."""
        h = self.heads[subject]
        eid = self._id("ev_")
        self._rseq += 1
        ev = Evidence(eid, h.org_id, subject, subject, h.agent_id, session, "operator", "%s = %s" % (key, value), t,
                      epochs={"org": self.epoch.get("org:" + h.org_id, 0), "subject": self.epoch.get("subject:" + subject, 0),
                              "session": 0}, channel="operator", receipt_seq=self._rseq)
        self.evidence[eid] = ev
        self.ev_seq.append(eid)
        self.written_at[eid] = t
        self.seal(eid, t) if ev.seal_state == "unsealed" else None
        ev.sealed_hash = ids.sealed_hash(self.org_keys[ev.org_id], ev.author_role, ev.author_role, ev.channel, ev.text)
        ev.seal_state = "sealed"
        job = Job(subject, (eid,), (eid,))
        return self.commit(job, [{"op": "assert", "key": key, "mode": "stated", "value": {"kind": "text", "v": value},
                                  "anchor": [{"evidence_id": eid, "quote": value}]}], t)

    # ------------------------------------------------------------ derived writers (C-6)
    def derived_write(self, kind: str, eids: Sequence[str], payload: dict, t: float) -> bool:
        """Judges, dispositions, lead capture, titles: person-derived artifacts outside the Gateway."""
        if self.d.derived_writes_fenced:
            fr = F.fence(self._stamps(eids), self._fctx())
            if fr.action != F.COMMIT:
                return False
            subj = fr.target_subject
        else:
            ev = self.evidence.get(eids[0])
            subj = ev.subject_id if ev else "?"
        self.derived[(kind, subj)] = dict(payload, evidence_ids=list(eids), t=t)
        return True

    # ------------------------------------------------------------ agent knowledge (M-3)
    def learn(self, agent: str, statement: str, eids: Sequence[str], t: float) -> str:
        iid = "ak_" + str(abs(hash((agent, fold(statement)))) % 10 ** 10)
        it = self.knowledge.setdefault(iid, K.Item(iid, agent, statement))
        for e in eids:
            ev = self.evidence.get(e)
            if ev is None:
                continue
            if self.d.derived_writes_fenced and F.fence(self._stamps([e]), self._fctx()).action != F.COMMIT:
                continue
            K.contribute(it, ev.subject_id, ev.merge_ids_at_ingestion)
        return iid

    def approve_knowledge(self, iid: str) -> Tuple[bool, str]:
        it = self.knowledge[iid]
        vals = [c.content.value[1] for c in self.claims.values() if c.content.subject_id in it.contributors]
        return K.approve(it, self.d.knowledge_min_contributors, vals)

    def _knowledge_for(self, agent: str) -> List[K.Item]:
        return sorted((it for it in self.knowledge.values() if it.agent_id == agent
                       and K.visible(it, self.d.knowledge_min_contributors, self.d.candidates_in_prompt)),
                      key=lambda i: i.item_id)

    # ------------------------------------------------------------ commitments (M-2)
    def commitment_event(self, e: CM.Event, now: float) -> bool:
        if self.d.commitment_model == "event_log":
            ev = self.evidence.get(e.evidence_id)
            if ev is None or ev.status != "active":
                return False                            # every event is backed by live evidence
            self.cevents.append(e)
        else:
            self.crows.apply(e, now)
        return True

    def commitments(self, now: float) -> dict:
        if self.d.commitment_model == "event_log":
            dead = frozenset(e for e, v in self.evidence.items() if v.status != "active")
            return {k: h.state for k, h in CM.project(self.cevents, now, dead).items()}
        self.crows.expire_job(now)
        return {r["key"]: self.crows.states(r["key"]) for r in self.crows.rows.values()}

    # -------------------------------------------------------------- retrieval
    def issue_handle(self, eid: str, t: float, ttl: float = 1.0) -> str:
        ev = self.evidence[eid]
        r = self.root(ev.subject_id)
        h = self.heads[r]
        return H.issue(self.handle_secret, H.Handle(ev.org_id, ev.agent_id, ev.session_id, r, h.assurance,
                                                    tuple(sorted(self.links.get(r, set()))), h.member_set_version,
                                                    t + ttl))

    def handle_for_subject(self, subject: str, t: float, agent: Optional[str] = None) -> str:
        r = self.root(subject)
        h = self.heads[r]
        sess = sorted(h.sessions)[0] if h.sessions else "s"
        return H.issue(self.handle_secret, H.Handle(h.org_id, agent or h.agent_id, sess, r, h.assurance,
                                                    tuple(sorted(self.links.get(r, set()))), h.member_set_version,
                                                    t + 1e9))

    def _authorize(self, caller: dict, subject: str, now: float = 0.0) -> Optional[SlotResult]:
        h = self.heads.get(subject)
        if h is None or h.status != "active":
            return SlotResult(key="*", status=UNAVAILABLE, note="subject erased or unknown")
        if self.d.read_auth == "handle" and caller.get("kind") != "operator":
            tok = caller.get("handle")
            if callable(tok):
                tok = tok(subject)                       # test harness: handle for the served conversation
            if not tok:
                return SlotResult(key="*", status=ACCESS_DENIED, note="handle_required")
            try:
                hd = H.verify(self.handle_secret, tok, now)
                r = self.root(subject)
                H.authorize(hd, subject_root=r, subject_org=h.org_id,
                            current_msv=self.heads[r].member_set_version, scope="person")
            except H.HandleError as e:
                return SlotResult(key="*", status=ACCESS_DENIED, note=e.code)
            return None
        if caller.get("org") != h.org_id:
            return SlotResult(key="*", status=ACCESS_DENIED)
        if caller.get("kind") == "operator" and self.d.r_m4_memory_read_roles == "named_role" and \
                "memory_read" not in caller.get("roles", ()):
            return SlotResult(key="*", status=ACCESS_DENIED, note="R-M4 named role required")
        return None

    def _org_of(self, subject: str) -> str:
        return self.heads[subject].org_id

    def get_current_state(self, caller: dict, subject: str, key: str, as_of: Optional[float] = None,
                          cutoff: Optional[float] = None, now: Optional[float] = None) -> SlotResult:
        now = now if now is not None else (cutoff if cutoff is not None else 1e9)
        deny = self._authorize(caller, subject, now)
        if deny:
            deny.key = key
            return deny
        p = lookup(self.reg, key)
        if p is None or not p.current_state_eligible:
            return SlotResult(key=key, status=UNAVAILABLE, note="not a current-state predicate")
        org = self._org_of(subject)
        claims = [c for c in self._member_claims(subject) if c.content.org_id == org]   # per-row org check
        r = resolve(p, claims, as_of if as_of is not None else now, cutoff if cutoff is not None else now,
                    self.d, now=now, key=key)
        h = self.heads[self.root(subject)]
        if key in h.slots and h.slots[key].signature() == r.signature():
            r.state_version = h.slots[key].state_version
        return r

    def _row(self, c: Claim, now: float, status: str) -> dict:
        vf, vu = effective_interval(c, now, self.d)
        return dict(claim_id=c.id, key=c.content.key, value=c.content.value[1], status=status,
                    valid_from=vf, valid_until=vu, source=c.content.source,
                    scope="subject:%s/org:%s" % (c.content.subject_id, c.content.org_id),
                    observed_at=c.content.observed_at, assertion_mode=c.content.assertion_mode,
                    value_check=c.content.value_check, quote=" ".join(q for _, q in c.content.anchor))

    def search_history(self, caller: dict, subject: str, key: str, now: float, include_retracted=False):
        deny = self._authorize(caller, subject, now)
        if deny:
            return deny
        rows = []
        org = self._org_of(subject)
        p = lookup(self.reg, key)
        for c in self._member_claims(subject):
            if c.content.key != key or c.content.org_id != org or (p is not None and not admissible(p, c, self.d)):
                continue
            st, cause, _ = status_at(c, now)
            if st in (QUARANTINED, PENDING_ERASURE, INVALIDATED):
                continue
            if st == RETRACTED and cause == NEVER_TRUE and not include_retracted:
                continue
            label = st if st != RETRACTED else "retracted:" + (cause or "")
            if st == ACTIVE:
                cur = self.resolve_now(subject, key, now, now)
                if p.cardinality == "SINGLE" and c.id not in cur.winning_claim_ids and c.id not in cur.conflict_claim_ids:
                    label = "superseded"
            rows.append(self._row(c, now, label))
        return sorted(rows, key=lambda r: (r["observed_at"], r["claim_id"]))

    def _search_candidates(self, subject: str) -> List[Claim]:
        ms = set(self.members(subject))
        if self.d.search_index == "none":
            return self._member_claims(subject)
        out = []
        for cid, row in sorted(self.fts.items()):
            if row["subject"] not in ms:
                continue
            if self.d.search_index == "projection_trusted":
                out.append(row["claim"])                        # the index copy, served as-is (M-9 defect)
            else:
                c = self.claims.get(cid)                        # re-validate against the system of record
                if c is not None and c.state.attributed and c.content.subject_id in ms:
                    out.append(c)
        return out

    def search_memory(self, caller: dict, subject: str, query: str, now: float, limit=10):
        deny = self._authorize(caller, subject, now)
        if deny:
            return deny
        q = search_tokens(query) if self.d.search_normalised else set(tokens(query))
        rows = []
        org = self._org_of(subject)
        for c in self._search_candidates(subject):
            p = lookup(self.reg, c.content.key)
            if c.content.org_id != org or p is None or not admissible(p, c, self.d):
                continue
            if p.current_state_eligible and not (self.d.render_unverified_registered
                                                 and c.content.value_check == "unverified"):
                continue                                   # current-state values only via get_current_state (F-9)
            if not eligible_at(c, now, self.d.supersession_storage_mode) or \
                    not covers(effective_interval(c, now, self.d), now):
                continue
            src = c.content.key.replace(".", " ") + " " + c.content.value[1]
            text = search_tokens(src) if self.d.search_normalised else set(tokens(src))
            score = len(q & text)
            if score or not q:
                rows.append((score, self._row(c, now, status_at(c, now)[0])))
        if self.d.narratives_in_prompt or self.d.render_mode == "quotes":
            for ep in self.episodes.values():
                if ep.subject_id in self.members(subject) and ep.summary_status == "ok" and ep.summary:
                    score = len(q & set(tokens(ep.summary)))
                    if score:
                        rows.append((score, dict(claim_id=ep.episode_id, key="narrative", value=ep.summary,
                                                 status="narrative-non-assertive", valid_from=ep.started_at,
                                                 valid_until=ep.ended_at, source="EPISODE_SUMMARY",
                                                 scope="subject:" + ep.subject_id, observed_at=ep.started_at,
                                                 assertion_mode="narrative", value_check="n/a", quote="")))
        if self.d.dedup_mode == "per_evidence":            # LA-11: read-time dedup, latest observation wins
            best = {}
            for sc, row in rows:
                k = (row["key"], row["value"], row["source"])
                if k not in best or (row["observed_at"], row["claim_id"]) > (best[k][1]["observed_at"],
                                                                              best[k][1]["claim_id"]):
                    best[k] = (sc, row)
            rows = list(best.values())
        rows.sort(key=lambda x: (-x[0], x[1]["claim_id"]))
        return [r for _, r in rows[:limit]]

    def _account_rows(self, subject: str, now: float) -> List[dict]:
        rows = []
        for a in self._accounts_of(subject):
            for c in self.claims.values():
                if c.content.subject_id != a or not eligible_at(c, now, self.d.supersession_storage_mode):
                    continue
                if not covers(effective_interval(c, now, self.d), now):
                    continue
                p = lookup(self.reg, c.content.key)
                if p is None or not admissible(p, c, self.d):
                    continue
                if self.d.account_sources == "authoritative" and not p.disclosable:
                    continue                                # C-5: only disclosable predicates reach persons
                rows.append(self._row(c, now, status_at(c, now)[0]))
        return rows

    def build_context(self, caller: dict, subject: str, now: float, fail_tiers=()):
        deny = self._authorize(caller, subject, now)
        if deny:
            return None, None
        slots = []
        for key, p in sorted(self.reg.items()):
            if p.current_state_eligible and not p.is_namespace and "t0" not in fail_tiers and not key.startswith("account."):
                r = self.get_current_state(caller, subject, key, now=now)
                if r.status != "UNKNOWN":
                    slots.append(r)
        rows = [] if "t1" in fail_tiers else self.search_memory(caller, subject, "", now, limit=50)
        mem_rows = [r for r in rows if r["key"] != "narrative"] + self._account_rows(subject, now)
        eps = [dict(episode_id=e.episode_id, summary=e.summary) for e in self.episodes.values()
               if e.subject_id in self.members(subject) and e.summary_status == "ok"]
        agent = self.heads[self.root(subject)].agent_id
        kn = self._knowledge_for(agent)
        msv = self.heads[self.root(subject)].member_set_version
        if self.d.render_mode == "structured":
            extra = [("t4_guidance_not_facts", [{"ref": it.item_id, "guidance": it.statement[:200]} for it in kn])] \
                if kn else []
            text, man = render_structured(slots, mem_rows, eps, fail_tiers, self.policy_version, msv,
                                          self.d.narratives_in_prompt, self.d.tier_caps, extra)
        else:
            text, man = render_context(slots, mem_rows, eps, fail_tiers, self.policy_version, msv)
            if kn:
                text = text.replace("<</MEMORY>>", "[Agent guidance]\n" + "\n".join(
                    "- " + it.statement for it in kn) + "\n<</MEMORY>>")
        self.manifests.append((now, man))
        self.manifest_subject[man.manifest_id] = self.root(subject)
        return text, man

    # --------------------------------------------------------------- episodes
    def assign_episodes(self, subject: str, gap_days: float = 1.0,
                        summarizer: Callable[[List[str]], str] = lambda texts: " / ".join(t[:40] for t in texts)):
        evs = [self.evidence[e] for e in self.ev_seq if self.evidence[e].subject_id == subject]
        groups, cur = [], []
        for ev in evs:
            if cur and ev.observed_at - cur[-1].observed_at > gap_days:
                groups.append(cur)
                cur = []
            cur.append(ev)
        if cur:
            groups.append(cur)
        k = self.keys[subject]
        for g in groups:
            eid = ids.episode_id(k, g[0].agent_id, g[0].evidence_id)
            usable = [e.text for e in g if e.author_role == USER and e.status == "active"]
            ep = self.episodes.get(eid) or Episode(eid, subject, g[0].agent_id, [], g[0].observed_at, None)
            ep.evidence_ids = [e.evidence_id for e in g]
            ep.ended_at = g[-1].observed_at
            ep.merge_ids = sorted({m for e in g for m in e.merge_ids_at_ingestion})
            if ep.summary_status in ("none", "regenerate_pending", "ok"):
                ep.summary = summarizer(usable) if usable else None     # from evidence only, never from summaries
                ep.summary_status = "ok" if ep.summary else "none"
            self.episodes[eid] = ep

    # ------------------------------------------------------------ invariants
    def invariants(self, now: float) -> List[str]:
        v = []
        for c in self.claims.values():
            if c.state.status == ACTIVE and c.state.attributed:
                live = [e for e in c.state.support.values()
                        if e.evidence_id in self.evidence and self.evidence[e.evidence_id].status in (
                            "active", "context_suppressed")]
                if not live:
                    v.append("active claim without live support: " + c.id)
                if self.d.require_seal and not any(self.evidence[e.evidence_id].seal_state == "sealed" for e in live):
                    v.append("active claim without sealed support: " + c.id)
                h = self.heads.get(c.content.subject_id)
                if h and h.status != "active":
                    v.append("active claim under erased subject: " + c.id)
        for s, h in self.heads.items():
            if h.status == "active" and self.root(s) == s:
                for k, r in h.slots.items():
                    at = h.slot_at.get(k, now)
                    if self.resolve_now(s, k, at, at).signature() != r.signature():
                        v.append("head/rebuild mismatch %s %s" % (s, k))
        return v
