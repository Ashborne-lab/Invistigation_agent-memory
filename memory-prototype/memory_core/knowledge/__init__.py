"""Agent Knowledge (red-team M-3 / R-11). Pure.

An item is agent-scoped guidance learned from many conversations. It keeps
contributor lineage: subject -> the merge ids in force when each
contribution was made. Rules (reviewed config):
- an item is ACTIVE in prompts only when approved AND it has >= k distinct
  live contributors; candidates never reach production prompts;
- approval is refused when the statement contains a quasi-identifier
  drawn from contributors' own claim values (names, places, employers,
  numbers);
- erasing a contributor removes the contribution; an undone merge removes
  contributions made under that merge; then the k check is repeated.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set, Tuple

from ..normalise import fold, tokens

CANDIDATE, APPROVED, RETIRED = "candidate", "approved", "retired"


@dataclass
class Item:
    item_id: str
    agent_id: str
    statement: str
    status: str = CANDIDATE
    contributors: Dict[str, Set[str]] = field(default_factory=dict)   # subject -> merge ids in force

    def live_contributors(self) -> int:
        return len(self.contributors)


def contribute(it: Item, subject: str, merge_ids: Iterable[str] = ()):
    it.contributors.setdefault(subject, set()).update(merge_ids)


_NUM = re.compile(r"\d")


def quasi_identifiers(statement: str, contributor_values: Iterable[str]) -> List[str]:
    """Deterministic check: tokens of contributors' own claim values (len>=3) or any digit run."""
    st = set(tokens(statement))
    hits = sorted({t for v in contributor_values for t in tokens(v) if len(t) >= 3 and t in st})
    if _NUM.search(statement):
        hits.append("<number>")
    return hits


def approve(it: Item, k: int, contributor_values: Iterable[str]) -> Tuple[bool, str]:
    if it.live_contributors() < k:
        return False, "below_k"
    q = quasi_identifiers(it.statement, contributor_values)
    if q:
        return False, "quasi_identifier:" + ",".join(q)
    it.status = APPROVED
    return True, "approved"


def visible(it: Item, k: int, candidates_in_prompt: bool) -> bool:
    if it.status == RETIRED:
        return False
    if it.status == CANDIDATE:
        return candidates_in_prompt
    return it.live_contributors() >= k


def on_erase(items: Iterable[Item], subjects: Set[str], k: int):
    for it in items:
        for s in subjects:
            it.contributors.pop(s, None)
        if it.live_contributors() < k and it.status == APPROVED:
            it.status = RETIRED                        # never re-derived from fewer than k
        if not it.contributors:
            it.status = RETIRED


def on_undo(items: Iterable[Item], merge_id: str, k: int):
    for it in items:
        for s in [s for s, ms in it.contributors.items() if merge_id in ms]:
            del it.contributors[s]
        if it.live_contributors() < k and it.status == APPROVED:
            it.status = RETIRED
