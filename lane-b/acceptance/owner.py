"""OWNER adapter: the B0 acceptance interface backed by the REAL code on each repository's `b0/security` branch.

Each repository contributes `owner_parts/<repo>.py`. Missing parts leave their functions undefined, so those tests
fail (honest: not implemented), never fall back to reference.py.
Run: B0_TARGET=owner B0_OWNER_ADAPTER=owner python -m pytest -q
"""
import importlib

NAME = "owner"
PARTS = ("studio_backend", "agent_design", "agent_runtime", "agent_engine", "mcp", "research")
LOADED, MISSING = [], []

for _part in PARTS:
    try:
        _m = importlib.import_module("owner_parts." + _part)
    except ModuleNotFoundError as e:
        if e.name != "owner_parts." + _part:
            raise
        MISSING.append(_part)
        continue
    LOADED.append(_part)
    for _k in getattr(_m, "__all__", [k for k in vars(_m) if not k.startswith("_")]):
        if callable(getattr(_m, _k)) and _k not in globals():   # first part to define a name wins
            globals()[_k] = getattr(_m, _k)
