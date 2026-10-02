"""The legacy extractor, for the A3 baseline.

The prompt is copied verbatim from olbrain-agent-runtime@daee3f9 services/agent_memory_service.py:71-90
(LEGACY_EXTRACTION_SYSTEM_PROMPT, the frozen "fields" path), and the user payload mirrors :287-304 (CURRENT FACTS,
WANTED FIELDS, LATEST TURN with the assistant text included, which is the documented contamination path).
Production uses claude-haiku-4-5-20251001 (:246). Read-only copy for evaluation; nothing here touches production.
"""
import json
import re

MAX_FACTS = 30

LEGACY_EXTRACTION_SYSTEM_PROMPT = """You maintain a long-term memory profile of one end-user on behalf of a customer-service agent.

You receive the currently remembered facts, the fields this agent wants to know about the user, and the latest conversation turn. Return the UPDATED COMPLETE list of facts, plus any wanted field the turn revealed.

Rules for "facts":
- Facts must be durable and user-specific: identity, preferences, constraints, commitments, recurring issues, important history.
- Do NOT store: small talk, one-off transactional details already resolved, facts about the agent or the company, speculation.
- Update or remove facts the new turn contradicts or resolves; keep still-true facts verbatim.
- Each fact is one short sentence (max 25 words) about "the user".
- At most {max_facts} facts. Prefer dropping the least useful old fact over exceeding the cap.
- If the turn adds nothing durable, return the existing facts unchanged.

Rules for "fields":
- Use ONLY the names given under WANTED FIELDS. Never invent a key.
- Each value is what the user actually said, as a short literal string — not a paraphrase, not a sentence.
- Omit a field rather than guess. An omitted field keeps its stored value; a wrong one replaces it.
- Return {{}} when the turn reveals none of them.

Output ONLY JSON: {{"facts": ["...", "..."], "fields": {{"<field name>": "<value>"}}}}"""

SYSTEM = LEGACY_EXTRACTION_SYSTEM_PROMPT.format(max_facts=MAX_FACTS)


def build_request(facts, user_text, assistant_text, wanted_fields=()):
    user = (f"CURRENT FACTS:\n{json.dumps(facts, ensure_ascii=False)}\n\n"
            f"WANTED FIELDS:\n{json.dumps(list(wanted_fields), ensure_ascii=False)}\n\n"
            f"LATEST TURN:\nUser: {user_text[:4000]}\nAssistant: {assistant_text[:4000]}")
    return SYSTEM, user


def parse(text):
    if not text:
        return None, "empty"
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    i, j = t.find("{"), t.rfind("}")
    try:
        obj = json.loads(t[i:j + 1])
    except Exception:
        return None, "invalid_json"
    facts = obj.get("facts")
    if not isinstance(facts, list):
        return None, "no_facts_list"
    return [str(f)[:300] for f in facts if isinstance(f, (str, int, float))][:MAX_FACTS], ""
