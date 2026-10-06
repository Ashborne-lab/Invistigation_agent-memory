"""pytest plugin (connector): runs the UNCHANGED conformance suite with implementation B = the Firestore emulator.

    firebase emulators:exec --only firestore --project demo-olbrain-storage-eval \
      "python -m pytest -p memory_core.storage_adapters.pytest_firestore_conformance tests/test_durable_journal_conformance.py"

It replaces ``memory_core.durable_journal.PartitionedJournal`` before the suite is imported, so every test that
builds "B_partitioned" (directly or through IMPLS / journal_for) gets the emulator adapter. A_global stays the
in-memory reference. At the end it reports which tests actually reached the emulator."""
import pytest

import memory_core.durable_journal as dj

from .firestore_emulator import FirestoreEmulatorJournal, require_emulator

_touched, _all = set(), []


def pytest_configure(config):
    require_emulator()
    dj.PartitionedJournal = FirestoreEmulatorJournal


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    before = FirestoreEmulatorJournal.instances
    yield
    _all.append(item.nodeid)
    if FirestoreEmulatorJournal.instances > before:
        _touched.add(item.nodeid)


def pytest_terminal_summary(terminalreporter):
    tr = terminalreporter
    tr.section("firestore emulator coverage")
    tr.write_line(f"tests run: {len(_all)}; reached the emulator adapter: {len(_touched)}; "
                  f"adapter instances: {FirestoreEmulatorJournal.instances}; "
                  f"transactions committed: {FirestoreEmulatorJournal.tx_commits}; "
                  f"transaction bodies run (incl. contention retries and rolled-back rejects or crashes): {FirestoreEmulatorJournal.tx_attempts}")
    for n in _all:
        if n not in _touched:
            tr.write_line(f"  not on emulator: {n}")
