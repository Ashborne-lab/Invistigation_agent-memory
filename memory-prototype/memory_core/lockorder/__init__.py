"""Lock-order model (red-team M-13 / R-21). Pure.

Every operation locks subject rows. "op_order" locks in the order the
operation names them (v2: unspecified). "ascending" locks the full member
set of every touched root, after following merged_into, in ascending
subject id. Two concurrent operations can deadlock iff some pair of rows
is acquired in opposite orders.
"""
from typing import Dict, List, Sequence, Tuple


def _root(s: str, merged_into: Dict[str, str]) -> str:
    seen = set()
    while s in merged_into and s not in seen:
        seen.add(s)
        s = merged_into[s]
    return s


def _members(s: str, merged_into: Dict[str, str], universe: Sequence[str]) -> List[str]:
    r = _root(s, merged_into)
    return [x for x in universe if _root(x, merged_into) == r]


def locks_for(op: str, args: Tuple[str, ...], merged_into: Dict[str, str], universe: Sequence[str],
              mode: str) -> List[str]:
    if mode == "op_order":
        if op == "merge":                      # (absorbed, survivor)
            return [args[0], args[1]]
        if op == "erase":                      # erase locks the root first, then members as discovered
            r = _root(args[0], merged_into)
            return [r] + [m for m in _members(args[0], merged_into, universe) if m != r]
        if op == "commit":
            return [args[0], _root(args[0], merged_into)] if _root(args[0], merged_into) != args[0] else [args[0]]
        if op == "undo":
            return [args[1], args[0]]          # (absorbed, survivor) -> survivor first
        raise ValueError(op)
    out = set()
    for a in args:
        out.update(_members(a, merged_into, universe))
        out.add(a)
    return sorted(out)


def can_deadlock(a: Sequence[str], b: Sequence[str]) -> bool:
    pa = {x: i for i, x in enumerate(a)}
    pb = {x: i for i, x in enumerate(b)}
    common = [x for x in pa if x in pb]
    for i, x in enumerate(common):
        for y in common[i + 1:]:
            if (pa[x] < pa[y]) != (pb[x] < pb[y]):
                return True
    return False
