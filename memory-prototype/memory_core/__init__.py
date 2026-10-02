"""OLBrain memory prototype: the pure memory core plus an in-memory harness.

Every package here is pure: no I/O, no network and no Firestore:
policy, gate, resolve, temporal, fence, ids, normalise and render.

``memory_core.runtime`` is different. It is a test harness that combines
the pure core with an in-memory store, so scenarios can run end to end.

``memory_core.legacy_sim`` ports the current production write semantics
(``olbrain-agent-runtime@daee3f9:services/agent_memory_service.py``), so
the benchmark can measure a baseline.
"""
