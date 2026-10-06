# Owner Decision Request: Third-Party Erasure in Customer Execution Memory v1

**Date:** 2026-10-06.

**Status:** **[OWNER DECISION REQUIRED].** No policy is selected or recommended. Nothing has been sent.

**Owner:** **[OWNER NOT IDENTIFIED IN CURRENT ARTIFACTS].**
- No record names an owner for this specific question.
- For context only, adjacent erasure questions are recorded as **Legal** (C-2 erasure reversal; `target-architecture-decision-closure-v1.md`) and **Jay** (R6b, erasure through a wrongly merged person; `final-identity-docket-2026-09-28.md`).
- Neither is assumed to own this one.

**Source:** the [CONTRACT_GAP] in `agent-execution-memory-foundation-v1.md` §I and `execution-episode-generator-contract-v1.md`.

---

## The question

> **If Customer X's execution episode contains personal or otherwise governed data about Third Party Y, and Y is erased under Y's applicable erasure rule, must Y's data embedded in X's execution episode and/or its member Evidence also become unavailable?**

## What the current architecture does (facts, not a decision)

- **Storage.** Execution memory is stored in **X's** CUSTOMER partition: member Evidence plus an `episode_summary` generation sealed under **X's** subject key (journal v1.1 + A1; owner decision CUSTOMER_SHARED).
- **Erasure scope.** Erasure today is **per subject partition**: an erasure entry (fence) plus destruction of that subject's key (journal §F, Part 3 erasure). **Y's erasure reaches Y's partition only.** Nothing in X's partition is keyed to Y.
- **Generations are recorded, not regenerated.** Replay serves the recorded text (A1, recorded-outcome replay). Changing a recorded generation's content is not an existing operation.
- **Available suppression mechanisms:**
  - a new generation over a changed usable member set (A1 key);
  - the dead-evidence filter at read.

  Both are per member record, not per datum inside a record.
- **Contract gap.** The contract does not say whether one subject's erasure must reach data about it held in another subject's partition. This is the same class of question as other cross-subject content.
- **Not in scope here:** E-5 (evidence durability), T-2 (security class values), B-3 (retention classes). They are separate owner items, not reopened.

## Options (no recommendation: no project evidence decides between them)

| | **A. Strict propagation** | **B. Customer-partition ownership** | **C. Governed data-class rule** |
|---|---|---|---|
| Rule | Y's erasure makes Y's data unavailable wherever it appears, including X's execution episodes and their member Evidence | X's execution memory follows X's lifecycle; Y's independent erasure does not rewrite X's history | Whether Y's erasure propagates depends on the data's security / privacy / retention classification |
| Semantic consequence | X's execution history can change after the fact (episodes suppressed or regenerated) | X's history is stable; Y's data may persist inside X's records until X's own erasure or retention ends | Mixed: some embedded data disappears, some persists, by class |
| Privacy consequence | Strongest for Y | Weakest for Y; Y's data outlives Y's erasure inside X's partition | As strong as the classification is accurate |
| Implementation consequence | Needs a way to **find** Y's data inside other partitions (an index of third-party mentions, or entity resolution over evidence and summaries), then suppress or regenerate the affected members. That is cross-partition work, which the architecture avoids today | None beyond today | Needs per-datum classification at write time, plus the Option A machinery for the classes that propagate |
| Audit / replay consequence | Recorded generations would be superseded by new ones (A1 allows a new generation; the old one stays a sealed fact unless shredded). Replay stays deterministic, but history at past positions changes for readers after the erasure | Unchanged | Option A's consequences, for the propagating classes |
| Impact on immutable journal / history | Facts cannot be edited. Unavailability needs either suppression (new generation plus a read filter) or cryptographic unreadability of the embedded datum | None | As A, for the propagating classes |
| Crypto-shred / content-rewrite machinery required? | **Yes, for true unreadability.** X-keyed sealing cannot shred Y's datum without per-datum (Y-keyed) envelopes or record rewriting. Suppression alone is not unrecoverability (C-5 v1 E-1: deletion leaves residue) | No | Yes, for the propagating classes |
| Input needed | Legal (the obligation); Security (mechanism); Product (history-change acceptability) | Legal (whether this meets the obligation) | Legal and Security (classification), Product |

## Exact approval request

Choose one, and state the legal basis your organisation relies on:

1. **Option A:** Y's erasure must make Y's embedded data unavailable in X's execution memory and member Evidence. Also state whether suppression suffices or cryptographic unreadability is required.
2. **Option B:** X's execution memory follows X's lifecycle only.
3. **Option C:** propagation by data class. Name the classes that propagate.

**Until decided:** the architecture behaves as Option B **by default of construction, not by decision**. This is recorded as an open gap, not as a choice.
