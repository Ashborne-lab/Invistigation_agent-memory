"""C-5 PostgreSQL probe P-RLS: row-level security and ``SET LOCAL`` tenant scoping under connection pooling.
TEST ONLY (disposable loopback cluster, synthetic data).

    python -m memory_core.storage_adapters.postgres_probes OUT.json
"""
import json
import sys
import uuid

import psycopg

from .postgres_boundary import PgFrontierStore, connect
from .postgres_local import dsn


def probe():
    sys.path.insert(0, "tests")
    from test_durable_storage_boundary import sync_entry
    from test_integration import ALL
    from test_x1_commit_time import Writer
    ph = Writer().w.p.registry._v
    out = {}
    with psycopg.connect(dsn(user="c5admin"), autocommit=True) as adm:
        out["role_c5app"] = dict(zip(("rolsuper", "rolbypassrls"), adm.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'c5app'").fetchone()))
        out["table_owners"] = sorted({r[0] for r in adm.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname = 'c5'").fetchall()})
        out["rls_enabled_all_tables"] = all(r[0] for r in adm.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relnamespace = 'c5'::regnamespace AND relkind = 'r'"))
    pooled = connect()                                            # ONE connection shared by two tenants
    a, b = (PgFrontierStore(ph, ns="rlsA" + uuid.uuid4().hex[:8], conn=pooled),
            PgFrontierStore(ph, ns="rlsB" + uuid.uuid4().hex[:8], conn=pooled))
    for s in (a, b):
        for p in ALL:
            s.publish(p.predicate, 1, 0.0)
    at = a.assign("s1", None, 1.0)
    out["tenant_a_append"] = a.append("s1", at, [sync_entry("s1", "a-secret", at)])[0]
    a.seal("key:s1", "c:a", {"text": "TENANT_A_ONLY"})
    out["tenant_b_sees_a_entries"] = len(b.facts().partitions.get("s1", ()))
    out["tenant_b_sees_a_vault"] = len(b.facts().vault)
    out["tenant_a_sees_own"] = len(a.facts().partitions.get("s1", ()))
    out["setting_after_tx_on_pooled_conn"] = pooled.execute("SELECT current_setting('app.ns', true)").fetchone()[0]
    out["unscoped_query_rows"] = pooled.execute("SELECT count(*) FROM c5.entries").fetchone()[0]
    try:
        with pooled.transaction():
            pooled.execute("SELECT set_config('app.ns', %s, true)", (a.ns,))
            pooled.execute("INSERT INTO c5.entries (ns, partition, pos, at, kind, idem, blob) "
                           "VALUES (%s, 's1', 99, 1.0, 'sync', 'x', '\\x00')", (b.ns,))
        out["write_into_other_tenant"] = "ACCEPTED"
    except psycopg.errors.InsufficientPrivilege as e:
        out["write_into_other_tenant"] = "refused: " + str(e).splitlines()[0][:90]
    # the hazard SET LOCAL avoids: a SESSION-level setting survives the transaction on a pooled connection
    leak = connect()
    leak.execute("SELECT set_config('app.ns', %s, false)", (a.ns,))   # session-scoped (what the adapter never does)
    with leak.transaction():
        leak.execute("SELECT set_config('app.ns', %s, true)", (b.ns,))
    out["session_set_hazard_rows_visible_after_tx"] = leak.execute("SELECT count(*) FROM c5.entries").fetchone()[0]
    leak.close()
    with psycopg.connect(dsn(user="c5admin"), autocommit=True) as adm:
        out["superuser_sees_rows_without_setting"] = adm.execute(
            "SELECT count(*) > 0 FROM c5.entries WHERE ns = %s", (a.ns,)).fetchone()[0]
    out["result"] = "PASS" if (out["tenant_b_sees_a_entries"] == 0 and out["tenant_b_sees_a_vault"] == 0 and
                               out["unscoped_query_rows"] == 0 and out["setting_after_tx_on_pooled_conn"] in ("", None)
                               and out["write_into_other_tenant"].startswith("refused") and
                               not out["role_c5app"]["rolbypassrls"] and "c5app" not in out["table_owners"]) else "FAIL"
    return out


def probe_checkpoints():
    """P-CKPT: a checkpoint (derived, sealed under the subject key) over PostgreSQL through erasure. The prototype's
    ``CheckpointStore`` is NOT part of ``StorageBoundary``; this records how it behaves on a real store."""
    sys.path.insert(0, "tests")
    from memory_core import journal_compaction as JC
    from memory_core.commit_time import JOURNAL, TimedJournal
    from test_integration import ALL, CITY
    from test_journal_compaction import erase
    from test_x1_commit_time import Writer, put
    wr = Writer()
    ph = wr.w.p.registry._v
    st = PgFrontierStore(ph, ns="ckpt" + uuid.uuid4().hex[:8])
    j = TimedJournal(ph, JOURNAL, storage=st)
    for p in ALL:
        j.publish(p.predicate, 1, 0.0)
    put(j, wr, "c1", CITY, "pune", 1.0)
    out = {}
    for enc in ("full", "ref"):
        cps = JC.CheckpointStore(st, encoding=enc)
        status, cp = JC.create(j, cps, "s1", 2.0 if enc == "full" else 2.5)
        out[enc] = {"create": status, "valid_before_erasure": JC.validate(cp, st.facts())}
        out[enc]["cp"] = cp
    put(j, wr, "c2", CITY, "goa", 3.0)
    rows = lambda: sum(1 for k in st.facts().vault if k[1].startswith("ckpt:"))   # noqa: E731
    out["payload_rows_before_discard"] = rows()
    full = JC.CheckpointStore(st)
    full.index["s1"] = [out["full"]["cp"]]
    full.discard(out["full"]["cp"], "superseded")                    # calls storage.vault.pop(...)
    out["payload_rows_after_discard"] = rows()                       # a DB-backed store keeps the row: orphan
    erase(j, "s1", 4.0, destroy=True)
    f = st.facts()
    for enc in ("full", "ref"):
        cp = out[enc].pop("cp")
        out[enc]["after_key_destruction"] = JC.validate(cp, f)
    out["payload_rows_after_key_destruction"] = rows()
    out["reconstruct_erased"] = __import__("memory_core.durable_journal", fromlist=["reconstruct"]).reconstruct(
        f, "s1", 5.0).erased
    out["result"] = "PASS" if (out["full"]["after_key_destruction"] == out["ref"]["after_key_destruction"] ==
                               "unreadable" and out["payload_rows_after_key_destruction"] == 0) else "FAIL"
    out["code_gap"] = ("CheckpointStore.discard/drop_staged delete payloads through storage.vault (an in-memory "
                       "attribute), not a StorageBoundary operation: on PostgreSQL a retired payload row stays until "
                       "key destruction" if out["payload_rows_after_discard"] == out["payload_rows_before_discard"]
                       else "none")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "checkpoints":
        res = probe_checkpoints()
        with open(sys.argv[1], "w") as f:
            json.dump(res, f, indent=1, default=str)
        print(json.dumps(res, indent=1, default=str))
        sys.exit(0)
    res = probe()
    with open(sys.argv[1], "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))
