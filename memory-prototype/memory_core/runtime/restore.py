"""Restore / disaster-recovery model (Lane A, A8). NOT pure: it operates on a ``Memory``.

The architecture has three stores with different restore behaviour:
- FS   (evidence store): restorable (Firestore PITR/backup);
- PG   (memory store): restorable (Cloud SQL PITR/backup);
- WORM (erasure + identity ledger, retention-locked GCS): never restored, always authoritative.

``snapshot`` captures FS and PG at a point (journal seq). ``restore`` replaces one or both partitions with a
snapshot. ``recover`` runs the restore protocol (memory-restore-protocol-v1.md):

  1. WORM replay, interleaved in journal order with the commit records kept with the evidence (FS):
     identity events and erasures are re-applied to whichever store regressed;
  2. identity reconciliation from the PG identity projection (covers WORM mirror lag when FS regressed);
  3. epoch high-water marks from the WORM ledger (epochs never go backwards);
  4. evidence lost by an FS restore: support edges to it are dropped; claims left without support become
     invalidated(lost_in_restore);
  5. projections rebuilt (heads, search index); invariants checked.

Store-assigned counters (message id allocation, receipt sequence) are NOT restored: real Firestore ids are
random, so a restore can never reissue an id that PG still references.
"""
import copy
from typing import Dict, List, Optional

from ..model import ACTIVE, INVALIDATED, Transition
from . import HEAD_FS_FIELDS, HEAD_PG_FIELDS, Head, Job, Memory

FS_ATTRS = ["org_keys", "keys", "index", "evidence", "ev_seq", "epoch", "epoch_log", "merged_into", "merges",
            "merges_undone", "org_erased_at", "session_erased_before", "inbound_dedup", "written_at", "links"]
PG_ATTRS = ["claims", "suppressions", "episodes", "manifests", "manifest_subject", "fts", "derived", "knowledge",
            "cevents", "crows", "identity_applied", "retractions", "replay_watermark"]


def snapshot(m: Memory) -> dict:
    return {
        "seq": m.seq,
        "fs": {a: copy.deepcopy(getattr(m, a)) for a in FS_ATTRS},
        "heads_fs": {s: {f: copy.deepcopy(getattr(h, f)) for f in HEAD_FS_FIELDS} for s, h in m.heads.items()},
        "pg": {a: copy.deepcopy(getattr(m, a)) for a in PG_ATTRS},
        "heads_pg": {s: {f: copy.deepcopy(getattr(h, f)) for f in HEAD_PG_FIELDS} for s, h in m.heads.items()},
        "extraction": {e: ev.extraction_state for e, ev in m.evidence.items()},   # PG-owned watermark
    }


def restore(m: Memory, store: str, snap: dict):
    """store: 'fs' | 'pg' | 'both'."""
    cur_extraction = {e: ev.extraction_state for e, ev in m.evidence.items()}
    cur_pg_heads = {s: {f: getattr(h, f) for f in HEAD_PG_FIELDS} for s, h in m.heads.items()}
    if store in ("fs", "both"):
        for a in FS_ATTRS:
            setattr(m, a, copy.deepcopy(snap["fs"][a]))
        heads = {}
        for s, fields in snap["heads_fs"].items():
            h = Head(s, fields["org_id"], fields["agent_id"])
            for f, v in fields.items():
                setattr(h, f, copy.deepcopy(v))
            for f, v in cur_pg_heads.get(s, {}).items():
                setattr(h, f, v)
            heads[s] = h
        m.heads = heads
        for e, ev in m.evidence.items():                  # the watermark lives in PG
            if store == "fs" and e in cur_extraction:
                ev.extraction_state = cur_extraction[e]
    if store in ("pg", "both"):
        for a in PG_ATTRS:
            setattr(m, a, copy.deepcopy(snap["pg"][a]))
        for s, h in m.heads.items():
            pg = snap["heads_pg"].get(s, {"slots": {}, "slot_at": {}})
            for f in HEAD_PG_FIELDS:
                setattr(h, f, copy.deepcopy(pg[f]))
        for e, ev in m.evidence.items():
            ev.extraction_state = snap["extraction"].get(e, "pending" if ev.author_role in ("user", "tool")
                                                         else "not_applicable")


def _subjects(m: Memory, refs) -> List[str]:
    out = []
    for s, h in m.heads.items():
        if h.org_id in m.org_keys and m.wref(s) in refs:
            out.append(s)
    return sorted(out)


def _apply_worm(m: Memory, rec: dict, fs: bool, pg: bool):
    k = rec["kind"]
    if k == "forget_me":
        ms = _subjects(m, set(rec["subjects"]))
        if fs:
            live = [s for s in ms if m.heads[s].status == "active"]
            if live:
                m._fs_forget_me(live, rec["t"])
            for s in ms:
                for ev in m.evidence.values():
                    if ev.subject_id == s and ev.status == "active":
                        ev.status = "pending_erasure"
        if pg and ms:
            m._pg_forget_me(set(ms), rec["t"])
    elif k in ("merge", "undo"):
        a = _subjects(m, {rec["absorbed"]})
        s = _subjects(m, {rec["survivor"]})
        if not a or not s:
            return                                           # subjects lost with an FS restore
        a, s = a[0], s[0]
        if fs:
            if k == "merge" and rec["mid"] not in m.merges:
                m._fs_merge(rec["mid"], a, s, rec["t"])
            if k == "undo" and rec["mid"] in m.merges and rec["mid"] not in m.merges_undone:
                m._fs_undo(rec["mid"], rec["t"])
        if pg:
            ev = {"kind": k, "mid": rec["mid"], "survivor": s, "absorbed": a}
            m._pg_identity_event(ev, rec["t"])
    elif k == "forget_fact":
        ms = _subjects(m, set(rec["subjects"]))
        if ms:
            m._pg_forget_fact(ms, rec["key"], rec["canon"], rec["t"])
    elif k in ("erase_evidence", "withdraw"):
        e = rec["evidence_id"]
        if fs and e in m.evidence:
            m.evidence[e].status = "erased" if k == "erase_evidence" else INVALIDATED
        if pg:
            m._pg_drop_support(e, rec["t"], "no_remaining_support" if k == "erase_evidence" else "evidence_withdrawn")


def recover(m: Memory, store: str, snap: dict, t: float, worm_visible: Optional[int] = None) -> dict:
    """Run the restore protocol. ``worm_visible`` simulates WORM mirror lag (only the first N entries exist)."""
    worm = m.worm if worm_visible is None else m.worm[:worm_visible]
    fs, pg = store in ("fs", "both"), store in ("pg", "both")
    report = {"worm_applied": 0, "commits_replayed": 0, "lost_in_restore": 0, "identity_from_pg": 0}
    # 1. interleaved replay: WORM entries + (PG regressed) commit records kept with the evidence
    # LA-10: resumable, not "commutative": a transactional watermark (in PG) records the last journal entry
    # applied; a re-run or crash-resume skips everything at or below it.
    floor = max(snap["seq"], m.replay_watermark)
    items = [(r["seq"], 0, r) for r in worm if r["seq"] > floor]
    if pg:
        seen = set()
        for ev in m.evidence.values():
            for r in ev.commit_records:
                if r["seq"] > floor and r["seq"] not in seen:
                    seen.add(r["seq"])
                    items.append((r["seq"], 1, r))
    for _seq, kind, r in sorted(items, key=lambda x: (x[0], x[1])):
        m.replay_watermark = max(m.replay_watermark, _seq)          # same transaction as the entry (model)
        if kind == 0:
            _apply_worm(m, r, fs=fs, pg=True)                # PG side always (idempotent)
            report["worm_applied"] += 1
        else:
            if m.d.replay_identity == "recorded":
                m.replay_record(r)                       # LA-1: apply recorded outcomes
            else:
                evs = tuple(e for e in r["evidence_ids"] if e in m.evidence)
                if not evs or r["subject"] not in m.heads:
                    continue
                for e in evs:
                    m.evidence[e].extraction_state = "pending"
                job = Job(r["subject"], evs, tuple(e for e in r["context_ids"] if e in m.evidence), r["q17"])
                m.commit(job, r["proposals"], r["t"], r["version"], r["reextract"], _record=False)   # re-decide
            report["commits_replayed"] += 1
    # 2. identity reconciliation from the PG projection (WORM mirror lag + FS regression)
    if fs:
        for ev in sorted(m.identity_applied, key=lambda x: x["t"]):
            a, s = ev.get("absorbed"), ev.get("survivor")
            if ev["kind"] == "merge" and ev["mid"] not in m.merges and a in m.heads and s in m.heads:
                m._fs_merge(ev["mid"], a, s, ev["t"])
                report["identity_from_pg"] += 1
            if ev["kind"] == "undo" and ev["mid"] in m.merges and ev["mid"] not in m.merges_undone:
                m._fs_undo(ev["mid"], ev["t"])
                report["identity_from_pg"] += 1
    # 3. epoch high-water marks
    for r in worm:
        if r["kind"] == "forget_me":
            for s in _subjects(m, set(r["subjects"])):
                hw = r["epochs"][m.wref(s)]
                if m.epoch.get("subject:" + s, 0) < hw:
                    m.epoch["subject:" + s] = hw
                    m.epoch_log.setdefault("subject:" + s, []).append((hw, "erasure", r["t"]))
    # 4a. seal re-verification over support-referenced evidence (LA-7): a PG restore loses tamper quarantines
    #     taken after the snapshot; an FS restore rolls seals back to "unsealed". Re-derive both from content.
    from ..normalise import fold
    referenced = {e.evidence_id for c in m.claims.values() if c.state.status == ACTIVE
                  for e in c.state.support.values()}
    for eid in sorted(referenced):
        ev = m.evidence.get(eid)
        if ev is None:
            continue
        if ev.seal_state == "unsealed" and ev.status == "active":
            m.seal(eid, t)
        if ev.seal_state == "sealed":
            m._verify_seals([eid], t)
        if ev.seal_state == "tampered":
            m._tampered(ev, t)
            report["tamper_requarantined"] = report.get("tamper_requarantined", 0) + 1
    for c in m.claims.values():                       # the quote must still be in the (restored) evidence
        for k, e in list(c.state.support.items()):
            ev = m.evidence.get(e.evidence_id)
            quotes = [q for (aid, q) in c.content.anchor if aid == e.evidence_id]
            if ev is not None and quotes and not all(fold(q) in fold(ev.text) for q in quotes):
                del c.state.support[k]
    # 4b. evidence lost by an FS restore
    for c in m.claims.values():
        gone = [k for k, e in c.state.support.items() if e.evidence_id not in m.evidence]
        for k in gone:
            del c.state.support[k]
        if not c.state.support and c.state.status == ACTIVE:
            c.state.transitions.append(Transition(t, ACTIVE, INVALIDATED, "lost_in_restore"))
            c.state.status = INVALIDATED
            report["lost_in_restore"] += 1
    # 5. projections
    for s, h in m.heads.items():
        if h.status == "active" and m.root(s) == s:
            m.refresh_all(s, t)
    m.reindex_all()
    report["invariants"] = m.invariants(t)
    return report
