# Senior answers to the Identity Decision Docket (2026-09-28)

Source: the answers collection of the Identity Decision Docket artifact (https://claude.ai/artifact/9w8zAyNMNx5zkrVNK5BSem). All answers came from one answerer id, between 07:43 and 07:56 UTC.
18 of the 19 questions were answered. **G1 has no answer.**
Classification: every item below is a **TARGET ARCHITECTURE** policy input. None of them is a verified current-state fact.

"Council" means Jay's request for an independent verdict from at least three Opus 5.5 reviewers (stated in the Q3 note).

| Q | Choice | Note (verbatim) | Status |
|---|---|---|---|
| Q1 shared/recycled identifier auto-merge | none | "yes merge it, but keep a note of what is merged... the context that is pointing towards the numbers being shared access is invaluable" | DECIDED: merge, and record provenance plus shared-access signals |
| Q2 which identifiers count as exact | none | "both are viable, you can keep a confidence score or if needed keep a judge model (jev) or models which are good at deciding things (try to stray away from LLMs for cost overflow)" | DECIDED: both count, weighted by confidence. The scoring mechanism is open (cheap non-LLM scorer first, JEV as fallback) |
| Q3 what undo restores | none | "i would lean towards a proper undo, must restore the content... but you can refer to the council of opus 5.5 s for this (atleast 3)" | LEAN: full content restore. COUNCIL |
| Q4 undo stops re-merge | Allow a stored undo as the one human identity action | "but make sure if you make the undo persistent, have ways to clear it aswell" | DECIDED: a stored "not same person" record, which must be clearable. Narrows J3 |
| Q5 cross-agent visibility | Yes, they share what they know | none | DECIDED |
| Q6 transfer, shared person | Split; don't merge on arrival | "but you can also chat with the council to implement ways to edit this setting at the time of moving the agent" | DECIDED default. COUNCIL on a per-transfer override |
| Q7 anonymous web chat / Instagram-only | Both are persons | "in future we might implement chat behavior and try to match 2 persons who are anonymous based on their mannerisms" | DECIDED. Behavioural matching is FUTURE and not scoped |
| Q8 P(A)+E(B) on one record | Weak: only above the threshold | "council verdict needed" | LEAN: weak. COUNCIL |
| Q9 interim resolver | Rebuild it to run on every write | none | DECIDED |
| Q10 MEMORY vs Claims | none | "council verdict needed" | COUNCIL |
| Q11 Memory Gateway = IDENTITY_SYSTEM | No, person resolution is a separate authority | none | DECIDED |
| Q12 separate person-merge rule | none | "council verdict needed" | COUNCIL |
| Q13 J3 replaces human-merge design | Confirmed, J3 replaces it | "we need to remove the human intervention as requirement wherever possible" | DECIDED |
| Q14 opt-out / forget-me scope | Follow the person | none | DECIDED. Touches parked legal work (G5) |
| D4 person key form | none | "id lean towards opaque id, council verdict needed" | LEAN: opaque id. COUNCIL |
| G5 + QF-2 parking | none | "council verdict needed" | COUNCIL |
| D2 hash form | Keyed hash (HMAC) per org | "council verdict might help" | DECIDED, with council review optional |
| G8 rejected-work disposition | Split by kind of work | "council verdict needed, id lean towards " (note truncated) | LEAN: split by kind. COUNCIL |
| G1 capability caching | no answer | none | UNANSWERED |

## Tensions raised by these answers

- **Q1 vs Q4 vs J3.** Q1 auto-merges shared numbers, so wrong merges will happen. Q4 is then the only correction, and it is a human action, which J3 excluded. Q4 explicitly makes that one exception, and Q13 asks to keep human involvement to a minimum.
- **Q3 vs the feasibility finding.** Full content restore is impossible while the LLM regenerates the fact list in place. This is established in the resolution spec §8. A proper undo therefore needs content versioning at write time.
- **Q5 raises the stakes of Q1.** Once memory is shared across agents, one wrong merge exposes facts to every agent in the org.
- **Q14 "follow the person" lives with G5 parked.** Erasure that follows a merged person depends on the legal classification that is still parked.
- **Q7 behavioural matching** would be inferred identity from behaviour, which is a privacy and legal question. It is recorded as FUTURE only.
