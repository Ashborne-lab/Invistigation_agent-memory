"""PostgreSQL adapters for C-5 (``storage-technology-evaluation-v2-request.md``). TEST ONLY, not a production schema.

Two adapters over ONE disposable, loopback-only PostgreSQL cluster (``postgres_local``):
- ``PgFrontierStore``: the v1.1 ``StorageBoundary`` in the EXPLICIT closed-position form. Per-partition and
  per-predicate head rows hold the frontiers and are the serialization points (``SELECT ... FOR UPDATE``).
- ``PgJournal``: the v1 ``DurableJournal`` interface (for the unchanged storage-level replay conformance suite).

The contract rules are NOT reimplemented. Each operation runs the reference code (``ExplicitFrontierStore`` /
``DurableJournal``) inside ONE PostgreSQL transaction, on a working set loaded from the database after taking the
row locks, then writes the difference back and commits. Acknowledgement is the COMMIT returning
(``synchronous_commit = on``). Time comes from the caller's reading plus the stored frontiers, never ``now()``.

Isolation between journals: every row carries ``ns`` (one namespace = one tenant). Every transaction sets
``app.ns`` with ``set_config(..., is_local => true)`` (= ``SET LOCAL``) and row-level security admits only that
namespace. The connecting role owns nothing and has NOBYPASSRLS, so RLS applies to it.

Layout (schema ``c5``):
  heads(ns, partition, f_part)                    partition head: the S1 lock and frontier
  entries(ns, partition, pos, at, kind, idem, blob)
  polheads(ns, predicate, f_pol)                  policy-log head: the O4 lock and frontier
  pubs(ns, seq, predicate, version, at)
  keys(ns, key_id, destroyed)                     the seal / destroy serialization point
  vault(ns, key_id, ref, blob)                    sealed content (deleted on destroy: NOT crypto-shredding)
"""
import collections
import contextlib
import math
import os
import pickle
import uuid

import psycopg

from ..durable_journal import AppendRejected, Crash, DurableFacts, DurableJournal, Entry, Publication, Sealed, \
    Stored
from ..storage_boundary import DERIVED_REF, ExplicitFrontierStore, View

NEG = -math.inf
_LOOPBACK = ("127.0.0.1", "localhost", "::1")

DDL = """
CREATE SCHEMA IF NOT EXISTS c5;
CREATE TABLE IF NOT EXISTS c5.heads (ns text, partition text, f_part float8 NOT NULL DEFAULT '-Infinity',
                                     PRIMARY KEY (ns, partition));
CREATE TABLE IF NOT EXISTS c5.entries (ns text, partition text, pos int, at float8 NOT NULL, kind text, idem text,
                                       blob bytea NOT NULL, PRIMARY KEY (ns, partition, pos));
CREATE TABLE IF NOT EXISTS c5.polheads (ns text, predicate text, f_pol float8 NOT NULL DEFAULT '-Infinity',
                                        PRIMARY KEY (ns, predicate));
CREATE TABLE IF NOT EXISTS c5.pubs (ns text, seq bigserial, predicate text, version int, at float8 NOT NULL,
                                    PRIMARY KEY (ns, predicate, version));
CREATE TABLE IF NOT EXISTS c5.keys (ns text, key_id text, destroyed bool NOT NULL DEFAULT false,
                                    PRIMARY KEY (ns, key_id));
CREATE TABLE IF NOT EXISTS c5.vault (ns text, key_id text, ref text, blob bytea NOT NULL,
                                     PRIMARY KEY (ns, key_id, ref));
"""
TABLES = ("heads", "entries", "polheads", "pubs", "keys", "vault")


def require_loopback(dsn: str) -> str:
    """Refuse anything but the disposable local cluster (no production host can be reached by mistake)."""
    info = psycopg.conninfo.conninfo_to_dict(dsn)
    if info.get("host") not in _LOOPBACK or info.get("dbname") != "c5eval":
        raise RuntimeError("C-5 PostgreSQL adapter is disposable-cluster-only (loopback host, database c5eval)")
    return dsn


def default_dsn() -> str:
    return require_loopback(os.environ["C5_PG_DSN"])


def connect(dsn=None):
    return psycopg.connect(require_loopback(dsn or default_dsn()), autocommit=True)


STATS = collections.Counter()      # process-wide: transactions, rollbacks, refusals (the driver reports them)


class _Tx:
    """One transaction per operation, tenant-scoped with SET LOCAL. Nested calls (the in-step ``check`` reading
    facts) join the open transaction."""

    def __init__(self, ns, conn=None, dsn=None):
        self.ns, self.dsn = ns, dsn
        self.conn = conn or connect(dsn)
        self.cur = None

    @contextlib.contextmanager
    def tx(self, isolation=None):
        if self.cur is not None:
            yield self.cur
            return
        STATS["tx"] += 1
        try:
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    if isolation:
                        cur.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
                    cur.execute("SELECT set_config('app.ns', %s, true)", (self.ns,))
                    self.cur = cur
                    try:
                        yield cur
                    finally:
                        self.cur = None
        except BaseException:
            STATS["rollback"] += 1
            raise

    def reconnect(self):
        with contextlib.suppress(Exception):
            self.conn.close()
        self.conn, self.cur = connect(self.dsn), None


# ---------------------------------------------------------------------------------------------- shared reads
def _entries(cur, partition):
    cur.execute("SELECT pos, blob FROM c5.entries WHERE partition = %s ORDER BY pos", (partition,))
    return [Stored(pickle.loads(b), pos) for pos, b in cur.fetchall()]


def _pubs(cur):
    cur.execute("SELECT predicate, version, at FROM c5.pubs ORDER BY seq")
    return [Publication(p, v, a) for p, v, a in cur.fetchall()]


def _facts(cur, policy_history):
    cur.execute("SELECT partition, pos, blob FROM c5.entries ORDER BY partition, pos")
    parts = {}
    for p, pos, b in cur.fetchall():
        parts.setdefault(p, []).append(Stored(pickle.loads(b), pos))
    cur.execute("SELECT key_id, ref, blob FROM c5.vault")
    vault = {(k, r): pickle.loads(b) for k, r, b in cur.fetchall()}
    return DurableFacts({p: tuple(v) for p, v in parts.items()}, tuple(_pubs(cur)), vault, policy_history)


def _lock_key(cur, key_id, mode):
    cur.execute("INSERT INTO c5.keys (ns, key_id) VALUES (current_setting('app.ns'), %s) ON CONFLICT DO NOTHING",
                (key_id,))
    cur.execute("SELECT destroyed FROM c5.keys WHERE key_id = %s FOR " + mode, (key_id,))
    return cur.fetchone()[0]


def _seal(cur, key_id, ref, content):
    if _lock_key(cur, key_id, "SHARE"):                    # a concurrent destroy holds FOR UPDATE until it commits
        raise AppendRejected("key_destroyed")
    cur.execute("INSERT INTO c5.vault (ns, key_id, ref, blob) VALUES (current_setting('app.ns'), %s, %s, %s) "
                "ON CONFLICT (ns, key_id, ref) DO UPDATE SET blob = EXCLUDED.blob", (key_id, ref, pickle.dumps(content)))
    return Sealed(key_id, ref)


def _destroy(cur, key_id):
    """Deletes the sealed rows and fences the key. Row deletion, NOT cryptographic destruction (C-1 [OWNER]): the
    bytes remain in heap pages until VACUUM and in WAL / backups until they age out."""
    _lock_key(cur, key_id, "UPDATE")
    cur.execute("UPDATE c5.keys SET destroyed = true WHERE key_id = %s", (key_id,))
    cur.execute("DELETE FROM c5.vault WHERE key_id = %s", (key_id,))


# ============================================================================================ v1.1 boundary
class PgFrontierStore(ExplicitFrontierStore):
    """Explicit frontiers in head rows. Weakening switches of the reference (``volatile_frontiers``, ``close_logs``,
    ``atomic``) are kept with the same meaning so the boundary suite's break tests apply unchanged."""

    instances = 0

    def __init__(self, policy_history, *, ns=None, conn=None, dsn=None, **kw):
        self._ws_part, self._ws_pol, self._in_op = {}, {}, False
        super().__init__(policy_history, **kw)
        type(self).instances += 1
        self.db = _Tx(ns or uuid.uuid4().hex, conn, dsn)

    @property
    def ns(self):
        return self.db.ns

    # frontiers: the working set inside an operation, the database outside one (never a process cache)
    @property
    def f_part(self):
        if self._in_op:
            return self._ws_part
        with self.db.tx() as cur:
            cur.execute("SELECT partition, f_part FROM c5.heads")
            return {p: f for p, f in cur.fetchall() if f != NEG}

    @f_part.setter
    def f_part(self, v):
        self._ws_part = v

    @property
    def f_pol(self):
        if self._in_op:
            return self._ws_pol
        with self.db.tx() as cur:
            cur.execute("SELECT predicate, f_pol FROM c5.polheads")
            return {p: f for p, f in cur.fetchall() if f != NEG}

    @f_pol.setter
    def f_pol(self, v):
        self._ws_pol = v

    # ------------------------------------------------------------------ the one-transaction operation
    def _op(self, fn, parts=(), preds=()):
        """Lock ``parts`` then ``preds`` (sorted, one global order: no deadlock), load the working set, run the
        reference logic, write the difference back, commit. A Crash inside rolls back (atomic) unless the store is
        deliberately non-atomic (break test), where the prefix the reference wrote is committed first."""
        crashed = None
        with self.db.tx() as cur:
            fp, fq = {}, {}
            for p in sorted(set(parts)):
                cur.execute("INSERT INTO c5.heads (ns, partition) VALUES (current_setting('app.ns'), %s) "
                            "ON CONFLICT DO NOTHING", (p,))
                cur.execute("SELECT f_part FROM c5.heads WHERE partition = %s FOR UPDATE", (p,))
                fp[p] = cur.fetchone()[0]
            for q in sorted(set(preds)):
                cur.execute("INSERT INTO c5.polheads (ns, predicate) VALUES (current_setting('app.ns'), %s) "
                            "ON CONFLICT DO NOTHING", (q,))
                cur.execute("SELECT f_pol FROM c5.polheads WHERE predicate = %s FOR UPDATE", (q,))
                fq[q] = cur.fetchone()[0]
            cur.execute("SELECT predicate, f_pol FROM c5.polheads")
            allq = dict(cur.fetchall())
            self._ws_part = {p: f for p, f in fp.items() if f != NEG}
            self._ws_pol = {q: f for q, f in allq.items() if f != NEG}
            self.parts = {p: _entries(cur, p) for p in set(parts)}
            self.pubs = _pubs(cur)
            n_parts = {p: len(v) for p, v in self.parts.items()}
            n_pubs = len(self.pubs)
            before_part, before_pol = dict(self._ws_part), dict(self._ws_pol)
            self._in_op = True
            try:
                try:
                    out = fn()
                except Crash as e:
                    if self.atomic:
                        raise
                    crashed = e                                  # WEAKENED: persist the leaked prefix
                    out = None
                for p, lst in self.parts.items():
                    for s in lst[n_parts.get(p, 0):]:
                        if p not in fp:
                            raise AssertionError("append to an unlocked partition")
                        cur.execute("INSERT INTO c5.entries (ns, partition, pos, at, kind, idem, blob) VALUES "
                                    "(current_setting('app.ns'), %s, %s, %s, %s, %s, %s)",
                                    (p, s.pos, s.entry.at, s.entry.kind, s.entry.idem, pickle.dumps(s.entry)))
                for pub in self.pubs[n_pubs:]:
                    if pub.predicate not in fq:
                        raise AssertionError("publication to an unlocked log")
                    cur.execute("INSERT INTO c5.pubs (ns, predicate, version, at) VALUES "
                                "(current_setting('app.ns'), %s, %s, %s)", (pub.predicate, pub.version, pub.at))
                for p, f in self._ws_part.items():
                    if f != before_part.get(p):
                        assert p in fp, "frontier raised without its lock"
                        cur.execute("UPDATE c5.heads SET f_part = %s WHERE partition = %s", (f, p))
                for q, f in self._ws_pol.items():
                    if f != before_pol.get(q):
                        assert q in fq, "frontier raised without its lock"
                        cur.execute("UPDATE c5.polheads SET f_pol = %s WHERE predicate = %s", (f, q))
            finally:
                self._in_op = False
        if crashed is not None:
            raise crashed
        return out

    # ------------------------------------------------------------------ durable facts (S4): always the database
    def entries(self, partition):
        with self.db.tx() as cur:
            return _entries(cur, partition)

    def publications(self):
        with self.db.tx() as cur:
            return _pubs(cur)

    _publications = publications
    _durable = entries

    def partitions(self):
        with self.db.tx() as cur:
            cur.execute("SELECT DISTINCT partition FROM c5.entries ORDER BY 1")
            return [r[0] for r in cur.fetchall()]

    def facts(self):
        with self.db.tx("REPEATABLE READ" if self.db.cur is None else None) as cur:
            return _facts(cur, self.policy_history)

    def seal(self, key_id, ref, content):
        with self.db.tx() as cur:
            return _seal(cur, key_id, ref, content)

    def destroy_key(self, key_id):
        with self.db.tx() as cur:
            _destroy(cur, key_id)

    def drop_derived(self, key_id, ref):
        """Delete one derived (checkpoint) payload row. Tenant-scoped by RLS (SET LOCAL app.ns); fact refs refused."""
        if not ref.startswith(DERIVED_REF):
            raise AppendRejected("not_a_derived_payload")
        with self.db.tx() as cur:
            cur.execute("DELETE FROM c5.vault WHERE key_id = %s AND ref = %s", (key_id, ref))

    # ------------------------------------------------------------------ closure and writes: reference logic
    def assign(self, partition, predicate, reading):
        return self._op(lambda: ExplicitFrontierStore.assign(self, partition, predicate, reading),
                        parts=[partition], preds=[predicate] if predicate else [])

    def close(self, sources, r):
        return self._op(lambda: ExplicitFrontierStore.close(self, sources, r),
                        parts=[k for t, k in sources if t == "part"], preds=[k for t, k in sources if t != "part"])

    def closed(self, partition, predicates, reading):
        with self.db.tx() as cur:
            cur.execute("SELECT f_part FROM c5.heads WHERE partition = %s", (partition,))
            row = cur.fetchone()
            cur.execute("SELECT predicate, f_pol FROM c5.polheads WHERE predicate = ANY(%s)", (list(predicates),))
            pol = dict(cur.fetchall())
        r = min([reading, row[0] if row else NEG] + [pol.get(p, NEG) for p in predicates])
        return None if r == NEG else r

    def snapshot(self):
        with self.db.tx("REPEATABLE READ") as cur:                  # one consistent snapshot of facts + frontiers
            facts = _facts(cur, self.policy_history)
            cur.execute("SELECT partition, f_part FROM c5.heads")
            fp = {p: f for p, f in cur.fetchall() if f != NEG}
            cur.execute("SELECT predicate, f_pol FROM c5.polheads")
            fq = {p: f for p, f in cur.fetchall() if f != NEG}
        return View(facts, fp, fq)

    def append(self, partition, at, entries, *, check=None, conditional=True, crash_after=None):
        res = self._op(lambda: ExplicitFrontierStore.append(self, partition, at, entries, check=check,
                                                           conditional=conditional, crash_after=crash_after),
                       parts=[partition])
        STATS["append:" + res[0]] += 1
        return res

    def publish(self, predicate, version, reading):
        return self._op(lambda: ExplicitFrontierStore.publish(self, predicate, version, reading), preds=[predicate])

    def publish_at(self, pub, *, conditional=True):
        return self._op(lambda: ExplicitFrontierStore.publish_at(self, pub, conditional=conditional),
                        preds=[pub.predicate])

    def crash(self):
        """The process (its connection, any open transaction) is lost. Nothing else exists to lose."""
        self.db.reconnect()
        if self.volatile_frontiers:                                  # WEAKENED: frontiers were process state
            with self.db.tx() as cur:
                cur.execute("UPDATE c5.heads SET f_part = '-Infinity'")
                cur.execute("UPDATE c5.polheads SET f_pol = '-Infinity'")


# ============================================================================================ v1 journal
class PgJournal(DurableJournal):
    """The v1 ``DurableJournal`` rules (unchanged) run inside one transaction per append / publish, serialized by the
    partition head row (appends) and one publication-log head row (publish)."""

    instances = 0

    def __init__(self, policy_history, *, ns=None, conn=None, dsn=None, **kw):
        super().__init__(policy_history, **kw)
        type(self).instances += 1
        self.db = _Tx(ns or uuid.uuid4().hex, conn, dsn)

    def _lock(self, cur, partition=None, pubs=False):
        if partition is not None:
            cur.execute("INSERT INTO c5.heads (ns, partition) VALUES (current_setting('app.ns'), %s) "
                        "ON CONFLICT DO NOTHING", (partition,))
            cur.execute("SELECT 1 FROM c5.heads WHERE partition = %s FOR UPDATE", (partition,))
        if pubs:
            cur.execute("INSERT INTO c5.polheads (ns, predicate) VALUES (current_setting('app.ns'), '*') "
                        "ON CONFLICT DO NOTHING")
            cur.execute("SELECT 1 FROM c5.polheads WHERE predicate = '*' FOR UPDATE")

    def _durable(self, partition):
        with self.db.tx() as cur:
            return _entries(cur, partition)

    def _publications(self):
        with self.db.tx() as cur:
            return _pubs(cur)

    def partitions(self):
        with self.db.tx() as cur:
            cur.execute("SELECT DISTINCT partition FROM c5.entries ORDER BY 1")
            return [r[0] for r in cur.fetchall()]

    def _insert(self, cur, partition, pos, e):
        cur.execute("INSERT INTO c5.entries (ns, partition, pos, at, kind, idem, blob) VALUES "
                    "(current_setting('app.ns'), %s, %s, %s, %s, %s, %s)",
                    (partition, pos, e.at, e.kind, e.idem, pickle.dumps(e)))

    def _write(self, partition, entries, crash_after):
        leak = crash_after is not None and not self.atomic          # WEAKENED: the prefix is committed separately
        with self.db.tx() as cur:
            cur.execute("SELECT count(*) FROM c5.entries WHERE partition = %s", (partition,))
            n = cur.fetchone()[0]
            for i, e in enumerate(entries[:crash_after] if leak else () if crash_after is not None else entries):
                self._insert(cur, partition, n + i, e)
            if crash_after is not None and not leak:
                raise Crash()                                        # atomic: the transaction rolls back
        if leak:
            raise Crash()

    def _write_publication(self, pub):
        with self.db.tx() as cur:
            cur.execute("INSERT INTO c5.pubs (ns, predicate, version, at) VALUES (current_setting('app.ns'), %s, %s, %s)",
                        (pub.predicate, pub.version, pub.at))

    def append(self, entries, crash_after=None):
        if not self.atomic:                                          # the break path deliberately has no transaction
            return super().append(entries, crash_after)
        with self.db.tx() as cur:
            self._lock(cur, entries[0].partition if entries else None)
            return super().append(entries, crash_after)

    def publish(self, pub):
        with self.db.tx() as cur:
            self._lock(cur, pubs=True)
            return super().publish(pub)

    def seal(self, key_id, ref, content):
        with self.db.tx() as cur:
            return _seal(cur, key_id, ref, content)

    def destroy_key(self, key_id):
        with self.db.tx() as cur:
            _destroy(cur, key_id)

    def facts(self):
        with self.db.tx("REPEATABLE READ" if self.db.cur is None else None) as cur:
            return _facts(cur, self.policy_history)

    def crash(self):
        self.db.reconnect()
