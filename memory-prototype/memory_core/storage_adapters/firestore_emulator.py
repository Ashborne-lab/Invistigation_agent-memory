"""Firestore EMULATOR adapter for the technology-neutral ``DurableJournal`` interface. TEST ONLY.

Safety: refuses to start unless ``FIRESTORE_EMULATOR_HOST`` points at a loopback address; the project id is a
``demo-`` id (never a real project) and the credentials are anonymous. No production credentials, project, data,
schema or rules are touched.

Layout (one namespace per adapter instance, so tests sharing one emulator never see each other):
  dj_runs/{ns}/parts/{h(partition)}                 head: {name, n}       (read in every append: the lock)
  dj_runs/{ns}/parts/{h(partition)}/entries/{pos}   {pos, idem, at, kind, blob=pickle(Entry)}
  dj_runs/{ns}/meta/pubs                            head: {n}             (read by appends, written by publish)
  dj_runs/{ns}/pubs/{h(pred|ver)}                   {seq, predicate, version, at}
  dj_runs/{ns}/vault/{h(key|ref)}                   {key_id, ref, blob}   sealed content
  dj_runs/{ns}/keys/{h(key)}                        {destroyed: true}

The contract's append rules stay in ``DurableJournal.append`` / ``publish`` (not reimplemented); this adapter runs
them inside ONE Firestore transaction, so the store (not a client-side read-then-write race) serialises them."""
import hashlib
import os
import pickle
import uuid

from google.api_core.exceptions import AlreadyExists
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from ..durable_journal import AppendRejected, Crash, DurableFacts, DurableJournal, Publication, Sealed, Stored

PROJECT = "demo-olbrain-storage-eval"
_LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")
_client = None


def require_emulator():
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
    if not host or host.rsplit(":", 1)[0] not in _LOOPBACK:
        raise RuntimeError("Firestore adapter is emulator-only: FIRESTORE_EMULATOR_HOST must be a loopback address")
    return host


def client():
    global _client
    if _client is None:
        require_emulator()
        _client = firestore.Client(project=PROJECT, credentials=AnonymousCredentials())
    return _client


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:40]


class FirestoreEmulatorJournal(DurableJournal):
    instances = 0          # how many journals were built (the connector reports which tests touched the emulator)
    tx_attempts = 0        # transaction bodies run, including contention retries
    tx_commits = 0
    position_conflicts = 0 # a concurrent writer took the same partition position first (create precondition)
    MAX_ATTEMPTS = 20

    def __init__(self, policy_history, *, namespace=None, **kw):
        super().__init__(policy_history, **kw)
        type(self).instances += 1
        self.db = client()
        self.ns = namespace or uuid.uuid4().hex
        self.root = self.db.collection("dj_runs").document(self.ns)
        self._tx = None
        self._len, self._head = {}, {}
        self._pub_n = 0

    # ------------------------------------------------------------------ transactions
    def _in_tx(self, fn, read_only=False):
        @firestore.transactional
        def run(tx):
            type(self).tx_attempts += 1
            self._tx = tx
            try:
                return fn()
            finally:
                self._tx = None
        out = run(self.db.transaction(read_only=read_only, max_attempts=self.MAX_ATTEMPTS))
        type(self).tx_commits += 1
        return out

    def _get(self, ref_or_query):
        return ref_or_query.get(transaction=self._tx) if self._tx else ref_or_query.get()

    def _part(self, p):
        return self.root.collection("parts").document(_h(p))

    # ------------------------------------------------------------------ hooks
    def _durable(self, partition):
        head = self._part(partition)
        snap = self._get(head)                                        # lock the partition head
        self._head[partition] = (snap.to_dict() or {}) if snap.exists else {}
        docs = self._get(head.collection("entries").order_by("pos"))
        out = [Stored(pickle.loads(d.get("blob")), d.get("pos")) for d in docs]
        self._len[partition] = len(out)
        return out

    def _publications(self):
        head = self._get(self.root.collection("meta").document("pubs"))
        self._pub_n = head.get("n") if head.exists else 0
        docs = self._get(self.root.collection("pubs").order_by("seq"))
        return [Publication(d.get("predicate"), d.get("version"), d.get("at")) for d in docs]

    def partitions(self):
        return sorted(d.get("name") for d in self._get(self.root.collection("parts")))

    def _write(self, partition, entries, crash_after):
        n = self._len[partition]
        head = self._part(partition)

        def put(w, i, e):
            w.create(head.collection("entries").document(f"{n + i:010d}"),
                     {"pos": n + i, "idem": e.idem, "at": e.at, "kind": e.kind, "blob": pickle.dumps(e)})
            w.set(head, {"name": partition, "n": n + i + 1}, merge=True)

        if crash_after is not None:
            if not self.atomic:                                       # weakened: a prefix leaks (separate writes)
                for i, e in enumerate(entries[:crash_after]):
                    b = self.db.batch()
                    put(b, i, e)
                    b.commit()
            raise Crash()                                             # atomic: the transaction rolls back
        w = self._tx or self.db.batch()
        for i, e in enumerate(entries):
            put(w, i, e)
        if w is not self._tx:
            w.commit()

    def _write_publication(self, pub):
        w = self._tx or self.db.batch()
        w.create(self.root.collection("pubs").document(_h(f"{pub.predicate}|{pub.version}")),
                 {"seq": self._pub_n, "predicate": pub.predicate, "version": pub.version, "at": pub.at})
        w.set(self.root.collection("meta").document("pubs"), {"n": self._pub_n + 1})
        if w is not self._tx:
            w.commit()

    def crash(self):
        self._tx, self._len, self._head = None, {}, {}                                # no other process state exists

    # ------------------------------------------------------------------ contract operations
    def append(self, entries, crash_after=None):
        if not self.atomic:                                           # the break path deliberately has no transaction
            return super().append(entries, crash_after)
        for _ in range(self.MAX_ATTEMPTS):
            try:
                return self._in_tx(lambda: super(FirestoreEmulatorJournal, self).append(entries, crash_after))
            except AlreadyExists:
                # Another writer committed this position after our read. Nothing of ours was written; re-run the
                # whole append (its idempotency check makes the retry exactly-once).
                type(self).position_conflicts += 1
        raise AppendRejected("contention")

    def publish(self, pub):
        return self._in_tx(lambda: super(FirestoreEmulatorJournal, self).publish(pub))

    def seal(self, key_id, ref, content):
        def body():
            if self._get(self.root.collection("keys").document(_h(key_id))).exists:
                raise AppendRejected("key_destroyed")
            self._tx.set(self.root.collection("vault").document(_h(key_id + "|" + ref)),
                         {"key_id": key_id, "ref": ref, "blob": pickle.dumps(content)})
            return Sealed(key_id, ref)
        return self._in_tx(body)

    def destroy_key(self, key_id):
        """Deletes the sealed documents. NOTE: this is document deletion, not cryptographic key destruction; the
        evaluation records what it does and does not establish."""
        def body():
            docs = list(self._get(self.root.collection("vault").where("key_id", "==", key_id)))
            self._tx.set(self.root.collection("keys").document(_h(key_id)), {"destroyed": True})
            for d in docs:
                self._tx.delete(d.reference)
        self._in_tx(body)

    def facts(self):
        def body():
            parts = {p: tuple(self._durable(p)) for p in self.partitions()}
            pubs = tuple(self._publications())
            vault = {(d.get("key_id"), d.get("ref")): pickle.loads(d.get("blob"))
                     for d in self._get(self.root.collection("vault"))}
            return DurableFacts(parts, pubs, vault, self.policy_history)
        return self._in_tx(body, read_only=True)                      # one consistent snapshot
