"""A port of the current production write semantics, used as the benchmark baseline.

Source (read-only, ``origin/main``): olbrain-agent-runtime@daee3f9
- services/agent_memory_service.py:147-159   _clean_facts
- services/agent_memory_service.py:276-421   read → LLM → full-list replace, set(merge=True)
- services/agent_memory_service.py:498-529   delete (a get, then delete; no tombstone)
- core/llm_providers/anthropic_provider.py:~4677-4689  generate_json returns {} on parse failure;
  stop_reason is never checked
- config/settings.py:247  user_memory_max_facts = 30;  agent_memory_service.py:38  MAX_FACT_CHARS = 300

Only the semantics that matter to the benchmark are reproduced. The "model"
is whatever text the scenario scripts, because this workspace has no API key
for a real model.
"""
import json
from typing import Dict, List, Optional

MAX_FACTS = 30
MAX_FACT_CHARS = 300


def generate_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _clean_facts(raw, max_facts=MAX_FACTS) -> Optional[List[str]]:
    if not isinstance(raw, list):
        return None
    facts = []
    for item in raw:
        if not isinstance(item, str):
            continue
        t = item.strip()
        if t:
            facts.append(t[:MAX_FACT_CHARS])
    return facts[:max_facts]


class LegacyStore:
    def __init__(self):
        self.docs: Dict[str, dict] = {}

    def load(self, key):
        d = self.docs.get(key)
        return None if d is None else {"facts": list(d["facts"])}

    def delete(self, key):
        self.docs.pop(key, None)

    def write(self, key, existing, model_text) -> str:
        """``existing`` is the snapshot read before the model call, as in production."""
        result = generate_json(model_text)
        facts = _clean_facts(result.get("facts") if isinstance(result, dict) else None)
        if facts is None:
            return "extraction_failed_keep"            # includes truncated JSON → freeze
        existing_facts = (existing or {}).get("facts", [])
        if facts == existing_facts:
            return "unchanged"
        if not facts and existing is None:
            return "nothing_durable"
        self.docs[key] = {"facts": facts}             # blind set(merge=True): arrays are replaced whole
        return "written"
