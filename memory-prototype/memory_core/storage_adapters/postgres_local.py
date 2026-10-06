"""A DISPOSABLE local PostgreSQL 16 cluster for C-5. TEST ONLY.

Binaries: the ``pgserver`` wheel's bundled PostgreSQL (no system install). Data directory: a throwaway directory
given by the caller (the session scratchpad). Listens on 127.0.0.1 only. Never a production host, project or
credential.

Roles: ``c5admin`` (bootstrap superuser, owns the schema; used only for setup and inspection) and ``c5app`` (LOGIN,
NOSUPERUSER, NOBYPASSRLS, owns nothing: every adapter connection uses it, so row-level security applies).
Durability settings are left at their defaults and asserted: ``fsync = on``, ``synchronous_commit = on``,
``full_page_writes = on``.

    python -m memory_core.storage_adapters.postgres_local init|start|stop|crash|status DATADIR [PORT]
"""
import os
import subprocess
import sys

import psycopg

from .postgres_boundary import DDL, TABLES

PORT = 54329


def bindir():
    import pgserver
    return os.path.join(os.path.dirname(pgserver.__file__), "pginstall", "bin")


def _run(*args, check=True):
    return subprocess.run([os.path.join(bindir(), args[0])] + list(args[1:]), capture_output=True, text=True,
                          check=check)


def dsn(port=PORT, user="c5app", db="c5eval"):
    return f"host=127.0.0.1 port={port} dbname={db} user={user}"


def init(datadir, port=PORT):
    _run("initdb", "-D", datadir, "-U", "c5admin", "--auth=trust", "-E", "UTF8", "--no-locale")
    with open(os.path.join(datadir, "postgresql.conf"), "a") as f:
        f.write(f"\nlisten_addresses = '127.0.0.1'\nport = {port}\nmax_connections = 200\n"
                "wal_level = replica\nmax_wal_senders = 4\nhot_standby = on\n")
    with open(os.path.join(datadir, "pg_hba.conf"), "w") as f:      # loopback only
        f.write("host all all 127.0.0.1/32 trust\nhost replication all 127.0.0.1/32 trust\n")
    start(datadir)
    setup(port)


def setup(port=PORT):
    with psycopg.connect(dsn(port, "c5admin", "postgres"), autocommit=True) as c:
        c.execute("CREATE DATABASE c5eval")
    with psycopg.connect(dsn(port, "c5admin"), autocommit=True) as c:
        c.execute("CREATE ROLE c5app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")
        c.execute(DDL)
        c.execute("GRANT USAGE ON SCHEMA c5 TO c5app")
        for t in TABLES:
            c.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON c5.{t} TO c5app")
            c.execute(f"ALTER TABLE c5.{t} ENABLE ROW LEVEL SECURITY")
            c.execute(f"CREATE POLICY tenant ON c5.{t} USING (ns = current_setting('app.ns', true)) "
                      f"WITH CHECK (ns = current_setting('app.ns', true))")
        c.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA c5 TO c5app")


def start(datadir):
    # no captured pipes: on Windows the server inherits them and pg_ctl would never return
    subprocess.run([os.path.join(bindir(), "pg_ctl"), "-D", datadir, "-l", os.path.join(datadir, "server.log"), "-w",
                    "start"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True)


def stop(datadir, mode="fast"):
    """``immediate`` = a crash: no shutdown checkpoint; the next start replays WAL (crash recovery)."""
    return _run("pg_ctl", "-D", datadir, "-m", mode, "-w", "stop", check=False)


def status(port=PORT):
    with psycopg.connect(dsn(port, "c5admin"), autocommit=True) as c:
        out = {k: c.execute(f"SHOW {k}").fetchone()[0] for k in
               ("server_version", "fsync", "synchronous_commit", "full_page_writes", "wal_sync_method",
                "default_transaction_isolation", "max_connections")}
        out["c5app"] = c.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='c5app'").fetchone()
        out["owner"] = c.execute("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname='c5'").fetchall()
        out["rls"] = c.execute("SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace='c5'::regnamespace "
                               "AND relkind='r' ORDER BY 1").fetchall()
    return out


def wait_ready(port, timeout=60.0):
    import time
    t = time.time() + timeout
    while time.time() < t:
        try:
            with psycopg.connect(dsn(port, "c5admin"), autocommit=True, connect_timeout=2) as c:
                if c.execute("SELECT 1").fetchone():
                    return True
        except psycopg.OperationalError:
            time.sleep(0.25)
    raise RuntimeError("server not ready on port %d" % port)


class Env:
    """The C-5 driver's backend hooks for PostgreSQL (the driver itself is technology-neutral). Picklable."""
    name = "postgresql"

    def __init__(self, datadir, port=PORT, replica_dir=None, replica_port=PORT + 1):
        self.datadir, self.port, self.replica_dir, self.replica_port = datadir, port, replica_dir, replica_port

    def make_store(self, policy_history, ns, replica=False, **kw):
        from .postgres_boundary import PgFrontierStore
        return PgFrontierStore(policy_history, ns=ns, dsn=dsn(self.replica_port if replica else self.port), **kw)

    def admin(self, replica=False):
        return psycopg.connect(dsn(self.replica_port if replica else self.port, "c5admin"), autocommit=True)

    def crash_backend(self):
        """An immediate stop: every server process is terminated without a shutdown checkpoint (crash-equivalent
        for PostgreSQL; the next start runs WAL crash recovery). NOT an OS or power failure."""
        return stop(self.datadir, "immediate").stdout

    def restart_backend(self):
        start(self.datadir)
        wait_ready(self.port)

    def ensure_replica(self):
        if self.replica_dir is None:
            return False
        if not os.path.exists(os.path.join(self.replica_dir, "PG_VERSION")):
            _run("pg_basebackup", "-h", "127.0.0.1", "-p", str(self.port), "-U", "c5admin", "-D", self.replica_dir,
                 "-R", "-X", "stream")
            with open(os.path.join(self.replica_dir, "postgresql.auto.conf"), "a") as f:
                f.write(f"\nport = {self.replica_port}\n")
        try:
            wait_ready(self.replica_port, timeout=1.0)
        except RuntimeError:
            start(self.replica_dir)
            wait_ready(self.replica_port)
        return True

    def replica_lag_bytes(self):
        with self.admin() as c:
            row = c.execute("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) FROM pg_stat_replication"
                            ).fetchone()
        return None if row is None else int(row[0] or 0)

    def describe(self):
        return status(self.port)

    def set_conf(self, name, value):
        with self.admin() as c:
            if value is None:
                c.execute(f"ALTER SYSTEM RESET {name}")
            else:
                c.execute(f"ALTER SYSTEM SET {name} = '{value}'")
            c.execute("SELECT pg_reload_conf()")

    def promote_replica(self):
        """Failover: the standby becomes a primary (pg_ctl promote). The old primary must not be restarted as a
        primary afterwards (split brain); the driver discards one side explicitly."""
        _run("pg_ctl", "-D", self.replica_dir, "-w", "promote", check=False)
        wait_ready(self.replica_port)
        with self.admin(replica=True) as c:
            for _ in range(100):
                if not c.execute("SELECT pg_is_in_recovery()").fetchone()[0]:
                    return True
                import time
                time.sleep(0.1)
        return False

    def drop_replica(self):
        import shutil
        stop(self.replica_dir, "immediate")
        shutil.rmtree(self.replica_dir, ignore_errors=True)


if __name__ == "__main__":
    cmd, d = sys.argv[1], sys.argv[2]
    if cmd == "init":
        init(d)
    elif cmd == "setup":
        setup()
    elif cmd == "start":
        start(d)
    elif cmd == "stop":
        print(stop(d).stdout)
    elif cmd == "crash":
        print(stop(d, "immediate").stdout)
    print(status() if cmd != "stop" and cmd != "crash" else "")
