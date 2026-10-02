"""Load REAL origin/main source from the workspace repositories into an isolated scratch tree, so acceptance tests
can exercise current production logic without editing any repository. Read-only: `git show origin/main:<path>`.

Only small, dependency-light modules are extracted. Internal imports are satisfied by stub modules written next to
them (each stub states what it replaces). Nothing is executed against any service.
"""
import importlib
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "repos"))
SCRATCH = os.path.join(tempfile.gettempdir(), "olbrain_b0_extract")
_COMMITS = {}


OWNER_REF = os.environ.get("B0_OWNER_REF", "b0/security")   # the owner adapter loads the B0 branch, not origin/main


def commit(repo, ref="origin/main"):
    if (repo, ref) not in _COMMITS:
        _COMMITS[(repo, ref)] = subprocess.check_output(["git", "-C", os.path.join(ROOT, repo), "rev-parse",
                                                         "--short", ref], text=True).strip()
    return _COMMITS[(repo, ref)]


def source(repo, path, ref="origin/main"):
    return subprocess.check_output(["git", "-C", os.path.join(ROOT, repo), "show", ref + ":" + path],
                                   text=True, encoding="utf-8")


def _write(rel, text):
    p = os.path.join(SCRATCH, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def materialise(repo, path, as_rel, stubs=None, ref="origin/main"):
    """Write <ref>:<path> to SCRATCH/<as_rel> plus stub files; return the import name."""
    _write(as_rel, source(repo, path, ref))
    for rel, text in (stubs or {}).items():
        _write(rel, text)
    parts = as_rel[:-3].split("/")
    for i in range(1, len(parts)):                  # package __init__ files
        init = os.path.join(SCRATCH, *parts[:i], "__init__.py")
        if not os.path.exists(init):
            _write("/".join(parts[:i]) + "/__init__.py", "")
    if SCRATCH not in sys.path:
        sys.path.insert(0, SCRATCH)
    return ".".join(parts)


def load(repo, path, as_rel, stubs=None, ref="origin/main"):
    name = materialise(repo, path, as_rel, stubs, ref)
    for m in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[m]
    return importlib.import_module(name)


def function_source(repo, path, func_name, ref="origin/main"):
    """The text of one top-level (async) def from a large module, for modules too heavy to import whole."""
    lines = source(repo, path, ref).splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(("def " + func_name + "(", "async def " + func_name + "(")))
    end = start + 1
    while end < len(lines) and (not lines[end] or lines[end][0] in " \t)" or lines[end].startswith("#")):
        end += 1
    return "\n".join(lines[start:end]) + "\n"


# --------------------------------------------------------------------------- the extracted modules
def studio_backend_auth():
    return load("olbrain-studio-backend", "middleware/auth.py", "sb/middleware/auth.py", {
        "middleware/request_state.py": "def populate_tenant_id_from_user(*a, **k):\n    return None\n"})


def agent_design_auth():
    return load("olbrain-agent-design", "app/middleware/auth.py", "ad/app/middleware/auth.py")


def engine_auth():
    return load("olbrain-agent-engine", "alchemist/utils/auth.py", "alchemist/utils/auth.py", {
        "alchemist/constants/collections.py": "class Collections:\n    def __getattr__(self, k):\n        return k\n"
                                              "Collections = Collections()\n"})


def engine_bigquery():
    load("olbrain-agent-engine", "alchemist/services/bigquery_service.py", "alchemist/services/bigquery_service.py",
         {"alchemist/config/firebase_config.py": "def get_bigquery_client():\n    raise RuntimeError('no BigQuery in tests')\n"})
    return load("olbrain-agent-engine", "alchemist/agents/lumen/evidence/bigquery.py",
                "alchemist/agents/lumen/evidence/bigquery.py")


def runtime_memory_doc_id():
    ns = {}
    exec("import hashlib\n" + function_source("olbrain-agent-runtime", "services/agent_memory_service.py",
                                              "memory_doc_id"), ns)
    return ns["memory_doc_id"]


def engine_olbrain_gates():
    """require_olbrain_user / get_metrics_scope / require_olbrain_identity from routes.py, with the token verifier
    injected (routes.py itself is too heavy to import)."""
    from typing import Dict, Optional, Tuple
    ns = {"Optional": Optional, "Tuple": Tuple, "Dict": Dict, "Header": lambda *a, **k: None}
    import logging
    from fastapi import HTTPException
    ns.update(logger=logging.getLogger("engine"), HTTPException=HTTPException)
    for fn in ("require_olbrain_user", "get_metrics_scope", "require_olbrain_identity"):
        exec(function_source("olbrain-agent-engine", "routes.py", fn), ns)
    return ns


def research_is_internal_user():
    ns = {}
    src = source("olbrain-research-runtime", "app/middleware/firebase_auth.py")
    exec("from __future__ import annotations\n" + function_source("olbrain-research-runtime",
                                                                  "app/middleware/firebase_auth.py", "_domain_of") +
         function_source("olbrain-research-runtime", "app/middleware/firebase_auth.py", "is_internal_user"), ns)
    return ns["is_internal_user"]


def mcp_auth_middleware():
    return load("olbrain-mcp-deployer", "runtime/auth_middleware.py", "mcp/runtime/auth_middleware.py")
