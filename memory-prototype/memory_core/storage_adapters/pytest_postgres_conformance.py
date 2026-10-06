"""pytest plugin (connector): the UNCHANGED suites against the disposable PostgreSQL cluster. TEST ONLY.

    C5_PG_DSN="host=127.0.0.1 port=54329 dbname=c5eval user=c5app" \\
      python -m pytest -p memory_core.storage_adapters.pytest_postgres_conformance \\
        tests/test_durable_storage_boundary.py tests/test_x1_commit_time.py tests/test_durable_journal_conformance.py

Before any test module is imported it rebinds, for the session only:
- ``storage_boundary.ExplicitFrontierStore`` -> ``PgFrontierStore`` (the boundary suite's ``explicit`` kind;
  PostgreSQL uses the explicit closed-position form). The ``implied`` kind stays the in-memory reference and is
  deselected: it is not PostgreSQL evidence;
- ``commit_time.default_storage`` -> ``PgFrontierStore`` (the X-1 suite's default storage);
- ``durable_journal.PartitionedJournal`` -> ``PgJournal`` (the conformance suite's ``B_partitioned``; ``A_global``
  stays the in-memory reference it is compared with).
At the end it reports which tests reached PostgreSQL."""
import pytest

import memory_core.commit_time as ct
import memory_core.durable_journal as dj
import memory_core.storage_boundary as sb

from .postgres_boundary import STATS, PgFrontierStore, PgJournal, default_dsn

_touched, _all, _deselected = set(), [], []


def _instances():
    return PgFrontierStore.instances + PgJournal.instances


def pytest_configure(config):
    default_dsn()                                            # refuses anything but the loopback c5eval cluster
    sb.ExplicitFrontierStore = PgFrontierStore
    dj.PartitionedJournal = PgJournal
    ct.default_storage = lambda ph, *, durable_frontiers=True: PgFrontierStore(
        ph, volatile_frontiers=not durable_frontiers)


def pytest_collection_modifyitems(config, items):
    keep = []
    for it in items:
        cs = getattr(it, "callspec", None)
        if cs is not None and cs.params.get("kind") == "implied":
            _deselected.append(it)
        else:
            keep.append(it)
    config.hook.pytest_deselected(items=_deselected)
    items[:] = keep


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    before = _instances()
    yield
    _all.append(item.nodeid)
    if _instances() > before:
        _touched.add(item.nodeid)


def pytest_terminal_summary(terminalreporter):
    tr = terminalreporter
    tr.section("postgresql coverage")
    tr.write_line(f"tests run: {len(_all)}; reached PostgreSQL: {len(_touched)}; deselected (implied kind): "
                  f"{len(_deselected)}; PgFrontierStore instances: {PgFrontierStore.instances}; PgJournal instances: "
                  f"{PgJournal.instances}; transactions: {STATS['tx']}; rolled back: {STATS['rollback']}")
    for n in _all:
        if n not in _touched:
            tr.write_line(f"  not on PostgreSQL: {n}")
