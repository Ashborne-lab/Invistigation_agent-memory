"""B0 acceptance tests: adapter selection.

  B0_TARGET=current    → today's origin/main behaviour (REAL extracted code + MODELLED handlers). Must be RED.
  B0_TARGET=reference  → the executable specification of the fix. Must be GREEN.
  B0_TARGET=owner      → the owning repository's implementation: set B0_OWNER_ADAPTER=<module> exposing the same
                         functions (see reference.py for the interface). This is the RED → GREEN gate for owners.
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from world import standard_world  # noqa: E402

TARGET = os.environ.get("B0_TARGET", "reference")


@pytest.fixture(scope="session")
def impl():
    if TARGET == "owner":
        return importlib.import_module(os.environ["B0_OWNER_ADAPTER"])
    return importlib.import_module(TARGET)


@pytest.fixture
def w():
    return standard_world()
