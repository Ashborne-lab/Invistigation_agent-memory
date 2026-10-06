"""pytest plugin: run the UNCHANGED X-1 tests with the implied-frontier store as the journal's default storage.

    python -m pytest -p memory_core.storage_boundary.pytest_x1_on_implied tests/test_x1_commit_time.py

Used to classify which X-1 assertions are guarantees (must hold on any conformant storage) and which assert the
explicit-frontier mechanism or a skewed-clock regime that an implied frontier excludes by its precondition."""
import memory_core.commit_time as ct

from . import ImpliedFrontierStore


def pytest_configure(config):
    ct.default_storage = lambda policy_history, durable_frontiers=True: ImpliedFrontierStore(policy_history)
