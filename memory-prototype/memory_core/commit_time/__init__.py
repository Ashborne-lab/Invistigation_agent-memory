"""X-1 decision model: who assigns commit time, and where O4 / R-READ are enforced. TEST/PROTOTYPE ONLY.

Decision (``investigation/durable-journal-x1-decision-v1.md``):
- the JOURNAL layer assigns commit time (``at`` for entries, ``T`` for publications) inside the commit step. A
  caller never supplies it. Callers supply observation and valid times as payload only;
- every source of evaluation points (each subject partition, each predicate's policy log) has a durable, monotone
  CLOSED FRONTIER. A consumer may use a prefix of a source only once that source is closed through it, and every
  fact acknowledged from that source afterwards is placed strictly after it.

Consumers, and the prefix each one consumes:
- a served read at r: its partition through r (inclusive), and the policy logs of the predicates it evaluates
  through r (inclusive). A CURRENT read uses r = max(clock, the caller's causal token) and closes the partition
  BEFORE it reads; a STALE-TOLERANT read is served at an already-closed frontier, with no write;
- an acknowledged entry at t: the policy log of its predicate strictly before t (its O3 stamp), and its own
  partition up to itself (its commit-time OCC check).
Not consumers: gate reads (the commit step re-validates), publication reports, publications.

Storage is any ``storage_boundary.StorageBoundary`` (contract v1.1, Part 3): it holds the facts AND owns closure
(explicit frontier values, or a frontier implied by a serialization-consistent time source). This layer holds NO
correctness state of its own: it decides when to assign, close and check, and the storage makes it durable.
``mode`` exists only so the break tests can run the REJECTED interpretations:
- ``writer``: the caller supplies ``at`` / ``T``, with no closure (what the v1 interface does);
- ``writer+read_watermark``: as ``writer``, plus a per-partition read watermark only;
- ``store_local``: the store assigns times from a monotone clock PER SOURCE, with no closure between sources."""
import math
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..durable_journal import (AppendRejected, Crash, DurableFacts, Entry, Publication, in_force, reconstruct)
from ..journal_compaction import checkpoint_fold
from ..storage_boundary import ExplicitFrontierStore, StorageBoundary, View

JOURNAL, WRITER, WRITER_READ_WATERMARK, STORE_LOCAL = "journal", "writer", "writer+read_watermark", "store_local"
NEG = -math.inf


def after(x: float) -> float:
    return math.nextafter(x, math.inf)


@dataclass(frozen=True)
class Served:
    """A read result as it was handed out. ``r`` is returned to the caller (the as-of token)."""
    subject: str
    r: float
    trace: Mapping[str, Tuple[tuple, ...]]


@dataclass
class Prepared:
    subject: str
    cmd: str
    predicate: Optional[str]
    stamp: Optional[int]
    at: float
    entries: List[Tuple[Entry, Optional[tuple]]]
    expected_version: Optional[int] = None


def default_storage(policy_history, *, durable_frontiers: bool = True) -> StorageBoundary:
    """The storage used when none is given (the X-1 tests' default): explicit frontiers."""
    return ExplicitFrontierStore(policy_history, volatile_frontiers=not durable_frontiers)


class TimedJournal:
    def __init__(self, policy_history, mode: str = JOURNAL, *, durable_frontiers: bool = True,
                 partition_lease: float = 0.0, recheck_at_write: bool = True, occ_at_write: bool = True,
                 snapshot_first: bool = False, storage: Optional[StorageBoundary] = None,
                 duplicate_check_first: bool = True):
        self.store = storage if storage is not None else \
            default_storage(policy_history, durable_frontiers=durable_frontiers)
        self.mode = mode
        self.served: List[Served] = []            # what was handed out (the invariant's evidence, not state)
        self.partition_lease = partition_lease    # > 0 only in the break test "frontier ahead of the clock"
        self.recheck_at_write = recheck_at_write  # False only in the break test "no write-time closure check"
        self.occ_at_write = occ_at_write          # False only in the break test "OCC outside the serialized write"
        self.snapshot_first = snapshot_first      # True only in the break test "snapshot taken before closure"
        self.duplicate_check_first = duplicate_check_first   # False only in the break test "duplicate after time"
        # v1.2 fast path (durable-journal-read-version-fastpath-v1.md): an optional journal_compaction.CheckpointStore.
        # Derived acceleration only. Closure, time assignment and the in-write K9 check are unchanged; a VALIDATED
        # checkpoint advanced through the durable suffix replaces the full replay inside them, and anything else
        # falls back to the v1.1 full replay.
        self.checkpoints = None

    # frontiers live in storage; these are read-only views of it (empty when the frontier is implied)
    @property
    def f_part(self) -> Dict[str, float]:
        return dict(getattr(self.store, "f_part", {}))

    @property
    def f_pol(self) -> Dict[str, float]:
        return dict(getattr(self.store, "f_pol", {}))

    @property
    def writes(self) -> int:
        return self.store.writes

    # ------------------------------------------------------------------ helpers
    def _entries(self, s):
        return self.store.entries(s)

    def _last_at(self, s):
        e = self._entries(s)
        return e[-1].entry.at if e else NEG

    def _last_pub(self, p):
        ts = [x.at for x in self.store.publications() if x.predicate == p]
        return max(ts) if ts else NEG

    def _checkpoint(self, facts, s, r, advance: bool = True, op=None):
        """A validated checkpoint fold of ``s`` (advanced through the durable suffix (c, r] when ``advance``), or
        None: the caller then uses the v1.1 full replay. ``op``: the calling operation's validations."""
        if self.checkpoints is None:
            return None
        hit = checkpoint_fold(facts, s, r, self.checkpoints, advance=advance, op=op)
        return None if hit is None else hit[1]

    def _version(self, s, predicate, at, op=None) -> int:
        facts = self.store.facts()
        f = self._checkpoint(facts, s, at, op=op)
        if f is not None:
            return len(f.trace.get(predicate, ()))                 # an erased fold has no trace: 0, as below
        return len(reconstruct(facts, s, at).trace.get(predicate, ()))

    # ------------------------------------------------------------------ publications
    def publish(self, predicate: str, version: int, clock: float) -> float:
        if self.mode == JOURNAL:
            return self.store.publish(predicate, version, clock)         # storage assigns T after closure
        T = max(clock, self._last_pub(predicate)) if self.mode == STORE_LOCAL else clock
        self.store.publish_at(Publication(predicate, version, T))
        return T

    # ------------------------------------------------------------------ appends (two steps, so reads can interleave)
    def prepare(self, subject: str, cmd: str, predicate: Optional[str], stamp: Optional[int], clock: float,
                build, expected_version: Optional[int] = None):
        """Time assignment. Idempotency is decided FIRST, on the logical command id, before any time exists: a
        duplicate returns the ORIGINAL commit time."""
        prior = next((x.entry for x in self._entries(subject) if x.entry.idem == cmd), None)
        if prior is not None and self.duplicate_check_first:
            return ("DUPLICATE", prior.at)
        if self.mode == JOURNAL:
            at = self.store.assign(subject, predicate, clock)    # O4: the predicate's log is now closed through at
        elif self.mode == STORE_LOCAL:
            at = max(clock, self._last_at(subject))
        else:
            at = clock
        if predicate and stamp != in_force(self.store.publications(), predicate, at):
            return ("STALE_POLICY_STAMP", at)                # the writer re-runs the gate; nothing was built
        # The record is built here, inside the commit step, from the assigned time (committed_at == at).
        p = Prepared(subject, cmd, predicate, stamp, at, build(at), expected_version)
        if not self.occ_at_write and expected_version is not None:
            actual = self._version(subject, predicate, at)          # WEAKENED: checked outside the write
            if actual != expected_version:
                return ("STATE_CONFLICT", actual)
            p.expected_version = None
        return ("PREPARED", p)

    def finish(self, p: Prepared, crash_after_durable: bool = False):
        """The serialized per-partition write, performed by storage: closure check (S1), O1, then this layer's
        checks at `at` (OCC, O3 stamp), then the all-or-nothing durable append."""
        s, at = p.subject, p.at

        def check(at_):
            if p.expected_version is not None:            # K9: its own validation, never an operation's
                actual = self._version(s, p.predicate, at_)
                if actual != p.expected_version:
                    return ("STATE_CONFLICT", actual)        # semantic: returned to the agent, never retried
            if p.predicate and p.stamp != in_force(self.store.publications(), p.predicate, at_):
                return ("STALE_POLICY_STAMP", at_)           # the writer re-runs the gate
            return None

        out = []
        for i, (e, seal) in enumerate(p.entries):
            if seal is not None:
                subj, ref, content = seal
                e = replace(e, payload=self.store.seal("key:" + subj, ref, content))
            out.append(replace(e, idem=p.cmd) if i == 0 else e)
        res = self.store.append(s, at, out, check=check,
                                conditional=self.recheck_at_write and self.mode in (JOURNAL, WRITER_READ_WATERMARK))
        if res[0] == "DUPLICATE":
            res = ("APPENDED", at)
        if res[0] == "APPENDED" and crash_after_durable:
            raise Crash()                                    # durable, acknowledgement lost
        return res

    def commit(self, subject, cmd, predicate, stamp, clock, build, expected_version=None, crash_after_durable=False):
        status, x = self.prepare(subject, cmd, predicate, stamp, clock, build, expected_version)
        if status != "PREPARED":
            return status, x
        return self.finish(x, crash_after_durable)

    # ------------------------------------------------------------------ reads
    def _read_preds(self, facts, s, r, op=None):
        """The predicates a read at r evaluates (whose policy logs it must close): every entry's predicate at or
        before r. Fast path: the checkpoint's covered set plus the suffix entries' metadata (no evaluation)."""
        f = self._checkpoint(facts, s, r, advance=False, op=op)
        if f is not None:
            return sorted(set(f.predicates) | {x.entry.predicate for x in facts.partitions.get(s, ())[f.position:]
                                          if x.entry.predicate and x.entry.at <= r})
        return sorted({x.entry.predicate for x in facts.partitions.get(s, ())
                       if x.entry.predicate and x.entry.at <= r})

    def begin_read(self, subject: str, clock: float, after: Optional[float] = None):
        """Step 1 of a CURRENT read: r = max(clock, causal token) and the partition is closed through r BEFORE
        anything is read, so no append can land at or before r once the snapshot exists."""
        r = max(clock, NEG if after is None else after) + self.partition_lease
        pre = None
        if self.snapshot_first:
            pre = self.store.facts()                         # WEAKENED: read first, close later
        elif self.mode in (JOURNAL, WRITER_READ_WATERMARK):
            r = self.store.close([("part", subject)], r)
        return subject, r, pre

    def end_read(self, token, op=None) -> Served:
        """Step 2: close the policy logs of the predicates evaluated, THEN read publications, then serve."""
        subject, r, pre = token
        if pre is not None and self.mode in (JOURNAL, WRITER_READ_WATERMARK):
            r = self.store.close([("part", subject)], r)
        facts = self.store.facts()
        if self.mode == JOURNAL:
            self.store.close([("pol", p) for p in self._read_preds(facts, subject, r, op)], r)
            facts = self.store.facts()
        return self._serve(pre if pre is not None else facts, subject, r, op)

    def read(self, subject: str, clock: float, closing: bool = True, after: Optional[float] = None, op=None
             ) -> Optional[Served]:
        """``closing`` (a CURRENT or OCC-base read): served at r = max(clock, ``after``), the caller's causal token
        (the time of its last acknowledged write or served read), after closing the sources through r.
        Otherwise (a STALE-TOLERANT read): served at a position storage has ALREADY closed, with no stored write.
        Returns None if there is none. ``op``: the calling operation's checkpoint validations."""
        if closing or self.mode != JOURNAL:
            return self.end_read(self.begin_read(subject, clock, after), op)
        facts = self.store.facts()
        r = self.store.closed(subject, self._read_preds(facts, subject, clock, op), clock)
        return None if r is None else self._serve(self.store.facts(), subject, r, op)

    def snapshot(self) -> View:
        return self.store.snapshot()

    def read_view(self, v: View, subject: str, clock: float) -> Optional[Served]:
        """A lagging view serves only at the position it has fully incorporated (never at the time of its last
        replicated entry: the next entry may carry the same time). Other modes serve at the caller's clock."""
        if self.mode == JOURNAL:
            r = self.store.view_position(v, subject, self._read_preds(v.facts, subject, clock), clock)
            if r is None:
                return None
        else:
            r = clock
        return self._serve(v.facts, subject, r)

    def served_trace(self, facts, subject, r, op=None) -> Mapping:
        """The served trace at r: the checkpoint fold's (validated, advanced to r), else the v1.1 full replay."""
        f = self._checkpoint(facts, subject, r, op=op)
        if f is not None:
            return {} if f.erased else {k: tuple(v) for k, v in f.trace.items()}
        rb = reconstruct(facts, subject, r)
        return {} if rb.erased else rb.trace

    def _serve(self, facts, subject, r, op=None):
        sv = Served(subject, r, self.served_trace(facts, subject, r, op))
        self.served.append(sv)
        return sv

    # ------------------------------------------------------------------ crash
    def crash(self):
        self.store.crash()                                   # the journal itself holds nothing to lose


# --------------------------------------------------------------------------- the invariant, as checks
def served_prefixes_are_immutable(j: TimedJournal) -> None:
    """THE invariant: every read ever served is reproduced exactly by the final facts (no fact was placed into
    a served prefix). Implies history stability and state_version monotonicity across served reads."""
    final = j.store.facts()
    for sv in j.served:
        rb = reconstruct(final, sv.subject, sv.r)
        assert ({} if rb.erased else rb.trace) == sv.trace, (sv.subject, sv.r)


def acknowledged_stamps_hold(j: TimedJournal) -> None:
    """O3/O4 in the final facts: every acknowledged entry is evaluated under the version it was admitted under."""
    f = j.store.facts()
    for part, stored in f.partitions.items():
        for x in stored:
            e = x.entry
            if e.predicate is not None:
                assert e.policy_version == in_force(f.publications, e.predicate, e.at), (part, e.kind, e.at)
