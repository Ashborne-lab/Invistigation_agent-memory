"""Durable-journal STORAGE BOUNDARY (contract v1.1, Part 3). TEST/PROTOTYPE ONLY.

The boundary states WHAT must be true of storage, not how it is represented. "Closing" a source is an abstract
operation: one implementation records a frontier value, another needs no record at all.

Guarantees (each is exercised by ``tests/test_durable_storage_boundary.py`` against BOTH implementations):
S1 Conditional append. An entry becomes durable only if no consumed prefix of its partition has reached its time;
   otherwise the append is refused (READ_CLOSED) and nothing is written. A publication is likewise never placed at or
   before a consumed prefix of its predicate's log.
S2 Closure survives crashes. Once ``assign``/``close``/a served position has returned, every later entry or
   publication of those sources is placed strictly after it, also after ``crash()``.
S3 Durable before acknowledgement. A fact reported APPENDED is in every later ``facts()``, including after a crash.
S4 Reads follow closure. A read issued after a closure reflects every fact acknowledged before it, and no fact can
   later appear at or before the position it was served at.
S5 Single-partition group append is all-or-nothing. Storage-level idempotency: same idem and content -> DUPLICATE;
   same idem, different content -> refused.
Plus the v1 storage guards: known kinds, O1, O3 stamp consistency, the erasure fence and key destruction.

Reference implementations:
- ``ExplicitFrontierStore``: frontiers are durable values owned by the store.
- ``ImpliedFrontierStore``: no per-source frontier is stored in the data store. Closure is implied by the global
  order of a time service (``SerialClock``, timestamp-oracle form): every step draws its time from it inside the
  step, and an entry becomes durable only if the time service has not moved past the entry's time. The time
  service's single high-water IS state (global, crash-surviving); the implied form moves closure state out of the
  data store into the time service, it does not remove it. A memoryless variant (bounded-uncertainty time plus
  commit-wait, no state anywhere) would still need in-flight / safe-time tracking or locks [INFERENCE].

Not provided by either (and not required by the contract): a global order over partitions, transactions across
sources, a write per stale-tolerant read."""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..durable_journal import (KINDS, AppendRejected, Crash, DurableFacts, Entry, Publication, Sealed, Stored,
                               in_force)

NEG = -math.inf
DERIVED_REF = "ckpt:"          # sealed refs of derived checkpoint payloads (journal_compaction); never a fact's ref


def after(x: float) -> float:
    return math.nextafter(x, math.inf)


@dataclass(frozen=True)
class View:
    """A lagging, read-only copy: the facts it has fully incorporated, and the position through which they are
    closed (explicit frontier values, or an implied closed position)."""
    facts: DurableFacts
    f_part: Mapping[str, float]
    f_pol: Mapping[str, float]
    implied: Optional[float] = None


class StorageBoundary:
    """Shared durable fact store + the S-guarantees' common parts. Subclasses define closure."""

    def __init__(self, policy_history, *, atomic: bool = True):
        self.policy_history = policy_history
        self.atomic = atomic                  # False only in the break test "non-atomic group" (S5)
        self.parts: Dict[str, List[Stored]] = {}
        self.pubs: List[Publication] = []
        self.vault: Dict[Tuple[str, str], object] = {}
        self.destroyed: set = set()
        self.writes = 0                       # stored-frontier writes (cost accounting)

    # ---------------------------------------------------------------- reads of durable facts (S4)
    def entries(self, partition: str) -> List[Stored]:
        return list(self.parts.get(partition, []))

    def publications(self) -> List[Publication]:
        return list(self.pubs)

    _publications = publications              # name used by the v1 helpers and the X-1 tests
    _durable = entries

    def partitions(self) -> List[str]:
        return sorted(self.parts)

    def facts(self) -> DurableFacts:
        return DurableFacts({p: tuple(v) for p, v in self.parts.items()}, tuple(self.pubs), dict(self.vault),
                            self.policy_history)

    # ---------------------------------------------------------------- sealing / erasure (unchanged from v1)
    def seal(self, key_id: str, ref: str, content) -> Sealed:
        if key_id in self.destroyed:
            raise AppendRejected("key_destroyed")
        self.vault[(key_id, ref)] = content
        return Sealed(key_id, ref)

    def destroy_key(self, key_id: str) -> None:
        self.destroyed.add(key_id)
        for k in [k for k in self.vault if k[0] == key_id]:
            del self.vault[k]

    def drop_derived(self, key_id: str, ref: str) -> None:
        """Physically delete ONE derived payload (a retired or rejected checkpoint, or a staged one that failed
        verification). Only derived refs are accepted: a journal fact's sealed payload is never deleted here (only
        erasure removes those, via ``destroy_key``). Idempotent: an absent payload is a no-op."""
        if not ref.startswith(DERIVED_REF):
            raise AppendRejected("not_a_derived_payload")
        self.vault.pop((key_id, ref), None)

    # ---------------------------------------------------------------- closure (subclass)
    def assign(self, partition: str, predicate: Optional[str], reading: float) -> float:
        """A commit time for an entry of ``partition``: strictly after every consumed prefix of the partition and
        every publication of ``predicate``, not before the partition's last entry; on return the predicate's log
        is closed through it."""
        raise NotImplementedError

    def close(self, sources: Sequence[Tuple[str, str]], r: float) -> float:
        """Consume ``sources`` (("part", s) / ("pol", p)) through at least r. Returns the position actually closed
        (>= r). Irrevocable on return (S2)."""
        raise NotImplementedError

    def closed(self, partition: str, predicates: Sequence[str], reading: float) -> Optional[float]:
        """A position <= reading through which these sources are ALREADY closed, without a stored write; None if
        there is none."""
        raise NotImplementedError

    def snapshot(self) -> View:
        raise NotImplementedError

    def view_position(self, v: View, partition: str, predicates: Sequence[str], reading: float) -> Optional[float]:
        raise NotImplementedError

    def _overtaken(self, partition: str, at: float) -> bool:
        """S1: has a consumed prefix of ``partition`` reached ``at``?"""
        raise NotImplementedError

    def _log_overtaken(self, predicate: str, T: float) -> bool:
        raise NotImplementedError

    def _assign_publication(self, predicate: str, reading: float) -> float:
        raise NotImplementedError

    def crash(self) -> None:
        pass

    # ---------------------------------------------------------------- writes
    def append(self, partition: str, at: float, entries: Sequence[Entry], *, check: Optional[Callable] = None,
               conditional: bool = True, crash_after: Optional[int] = None):
        """S1 + S3 + S5, as ONE serialized step on ``partition``: closure check, O1, the journal's own check
        (``check(at)`` -> refusal or None: OCC and the O3 stamp at ``at``), then an all-or-nothing durable write."""
        if conditional and self._overtaken(partition, at):
            return ("READ_CLOSED", at)
        stored = self.parts.get(partition, [])
        if stored and at < stored[-1].entry.at:
            return ("COMMIT_TIME_REGRESSED", at)
        if check is not None:
            refusal = check(at)
            if refusal is not None:
                return refusal
        try:
            fresh = self._validate(partition, entries)
        except AppendRejected as e:
            return ("REJECTED", str(e))
        if not fresh:
            return ("DUPLICATE", at)
        lst = self.parts.setdefault(partition, [])
        if crash_after is not None:
            if not self.atomic:                              # WEAKENED: a prefix of the group becomes durable
                for e in fresh[:crash_after]:
                    lst.append(Stored(e, len(lst)))
            raise Crash()                                    # atomic: nothing of the group is durable
        for e in fresh:
            lst.append(Stored(e, len(lst)))
        return ("APPENDED", at)

    def _validate(self, partition, entries):
        if not entries or len({e.partition for e in entries}) != 1 or entries[0].partition != partition:
            raise AppendRejected("group_must_target_one_partition")
        stored = self.parts.get(partition, [])
        have = {s.entry.idem: s.entry for s in stored}
        fresh = []
        for e in entries:
            if e.kind not in KINDS:
                raise AppendRejected("unknown_kind")
            if e.idem in have:
                if have[e.idem] != e:
                    raise AppendRejected("idem_reused_with_different_content")
                continue
            fresh.append(e)
        if fresh and any(s.entry.kind == "erasure" for s in stored):
            raise AppendRejected("partition_erased")
        for e in fresh:
            if e.predicate is not None and e.policy_version != in_force(self.pubs, e.predicate, e.at):
                raise AppendRejected("stale_policy_stamp")
        return fresh

    def publish(self, predicate: str, version: int, reading: float) -> float:
        """Assign T (after every consumed prefix of the log) and append the publication, in one step."""
        T = self._assign_publication(predicate, reading)
        self._append_publication(Publication(predicate, version, T))
        return T

    def publish_at(self, pub: Publication, *, conditional: bool = True) -> str:
        """A publication with a caller-given time (replay, or the rejected interpretations). Still conditional."""
        if conditional and self._log_overtaken(pub.predicate, pub.at):
            raise AppendRejected("log_closed")
        return self._append_publication(pub)

    def _append_publication(self, pub: Publication) -> str:
        mine = [p for p in self.pubs if p.predicate == pub.predicate]
        if any(p.version == pub.version for p in mine):
            return "DUPLICATE"
        if mine and (pub.version <= max(p.version for p in mine) or pub.at < max(p.at for p in mine)):
            raise AppendRejected("publication_out_of_order")
        self.pubs.append(pub)
        return "APPENDED"

    def _last_at(self, partition):
        s = self.parts.get(partition)
        return s[-1].entry.at if s else NEG

    def _last_pub(self, predicate):
        ts = [p.at for p in self.pubs if p.predicate == predicate]
        return max(ts) if ts else NEG


# ==================================================================================== A: explicit frontiers
class ExplicitFrontierStore(StorageBoundary):
    """Frontiers are durable values owned by the store (never by the process).

    Weakening switches exist only for the break tests: ``conditional_append`` (S1), ``volatile_frontiers`` (S2),
    ``close_logs`` (log closure: O4)."""

    def __init__(self, policy_history, *, volatile_frontiers: bool = False, close_logs: bool = True, **kw):
        super().__init__(policy_history, **kw)
        self.f_part: Dict[str, float] = {}
        self.f_pol: Dict[str, float] = {}
        self.volatile_frontiers = volatile_frontiers
        self.close_logs = close_logs

    def _raise(self, table, key, x):
        if x > table.get(key, NEG):
            table[key] = x
            self.writes += 1

    def assign(self, partition, predicate, reading):
        at = max(reading, self._last_at(partition), after(self.f_part.get(partition, NEG)),
                 after(self._last_pub(predicate)) if predicate else NEG)
        if predicate and self.close_logs:
            self._raise(self.f_pol, predicate, at)
        return at

    def close(self, sources, r):
        for kind, key in sources:
            if kind == "part":
                self._raise(self.f_part, key, r)
            elif self.close_logs:
                self._raise(self.f_pol, key, r)
        return r

    def closed(self, partition, predicates, reading):
        r = min([reading, self.f_part.get(partition, NEG)] + [self.f_pol.get(p, NEG) for p in predicates])
        return None if r == NEG else r

    def snapshot(self):
        return View(self.facts(), dict(self.f_part), dict(self.f_pol))

    def view_position(self, v, partition, predicates, reading):
        r = min([reading, v.f_part.get(partition, NEG)] + [v.f_pol.get(p, NEG) for p in predicates])
        return None if r == NEG else r

    def _overtaken(self, partition, at):
        return at <= self.f_part.get(partition, NEG)

    def _log_overtaken(self, predicate, T):
        return T <= self.f_pol.get(predicate, NEG)

    def _assign_publication(self, predicate, reading):
        return max(reading, after(self.f_pol.get(predicate, NEG)), after(self._last_pub(predicate)))

    def publish(self, predicate, version, reading):
        T = super().publish(predicate, version, reading)
        self._raise(self.f_pol, predicate, T)                # reads at r >= T consume it; later ones follow it
        return T

    def crash(self):
        if self.volatile_frontiers:                          # WEAKENED: closure was process state
            self.f_part, self.f_pol = {}, {}


# ==================================================================================== B: implied frontiers
class SerialClock:
    """The time service of an implied-frontier store, in timestamp-oracle form: ONE global, strictly increasing
    sequence of times (each draw is later than every earlier draw, across all sources), whose high-water ``t`` is
    the service's own state and survives store crashes (a real oracle persists it). A node's reading is a lower
    bound only. Every step that consumes or commits DRAWS (``draws`` counts them: the implied form's per-read cost).

    Weakening switch for the break tests: ``per_node`` (no shared sequence: each draw is the caller's raw reading)."""

    def __init__(self, per_node: bool = False):
        self.t = NEG
        self.per_node = per_node
        self.draws = 0

    def draw(self, reading: float, strict: bool = True) -> float:
        self.draws += 1
        if self.per_node:
            return reading
        self.t = max(reading, after(self.t) if strict else self.t)
        return self.t

    def now(self) -> float:
        return self.t


class ImpliedFrontierStore(StorageBoundary):
    """No per-source frontier in the data store (its state is the durable facts only). A source is closed through x
    as soon as the time service's sequence has passed x: every later step draws a later time (assign, publish,
    reads), and an entry becomes durable only if the time service has not moved past the entry's time since it was
    drawn (so a consumer can never be overtaken by an in-flight entry). The store only READS the time service's
    position; it never sets it.

    Weakening switches for the break tests: ``refuse_overtaken`` (S1), ``clock_resets_on_crash`` (S2: a time source
    rebuilt from the durable log instead of surviving the crash)."""

    def __init__(self, policy_history, *, clock: Optional[SerialClock] = None, refuse_overtaken: bool = True,
                 clock_resets_on_crash: bool = False, **kw):
        super().__init__(policy_history, **kw)
        self.clock = clock or SerialClock()
        self.refuse_overtaken = refuse_overtaken
        self.clock_resets_on_crash = clock_resets_on_crash

    def assign(self, partition, predicate, reading):
        return self.clock.draw(max(reading, self._last_at(partition)))

    def close(self, sources, r):
        return self.clock.draw(r)                            # the position is closed because time has passed it

    def closed(self, partition, predicates, reading):
        t = self.clock.draw(reading)                         # time passes any in-flight entry; nothing is stored
        return min(reading, t)

    def snapshot(self):
        t = self.clock.draw(NEG)
        return View(self.facts(), {}, {}, implied=t)

    def view_position(self, v, partition, predicates, reading):
        return None if v.implied is None else min(reading, v.implied)

    def _overtaken(self, partition, at):
        return self.refuse_overtaken and self.clock.now() > at

    def _log_overtaken(self, predicate, T):
        return self.refuse_overtaken and self.clock.now() > T

    def _assign_publication(self, predicate, reading):
        return self.clock.draw(max(reading, self._last_pub(predicate)))

    def crash(self):
        if self.clock_resets_on_crash:                       # WEAKENED: time rebuilt from the durable log
            ts = [s.entry.at for v in self.parts.values() for s in v] + [p.at for p in self.pubs]
            self.clock.t = max(ts) if ts else NEG
