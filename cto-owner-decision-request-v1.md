# Owner Decision Request v1: checkpoint verification trust model and signature definition

**Date:** 2026-10-05.

**For:** the owner of the Durable Journal compaction contract (`durable-journal-compaction-contract-v1.md`), which defines the checkpoint's canonical identity. No named person or channel is assumed, and nothing has been sent.

**Status:** **[OWNER DECISION REQUIRED].** Engineering cannot make this choice, because it changes what a reader is entitled to trust.

**Evidence:**
- `incremental-checkpoint-signature-v1.md`;
- `tests/test_incremental_checkpoint_signature.py`;
- earlier checkpoint reports: compaction v1, consumers v1, fast path v1.2, maintenance v1, pruning v1.

---

## 1. The decision required

> **When may a checkpoint reader rely on an earlier verification instead of re-verifying the full canonical signature itself, and if so, may the canonical signature definition change to make that cheap?**

**Sub-question (only if the answer above changes anything):** should the canonical signature become a hierarchical, compositional digest instead of SHA-256 over one flat serialization?

## 2. Why engineering cannot decide it

- **The canonical signature is the checkpoint's identity** (compaction contract §1). Readers verify it on every use, and it is what catches a payload that decodes to a different fold than the one signed (a builder defect, or a payload and index rewritten together).
- **An exact incremental reproduction of the current signature is impossible.** The hashed input changes in its first 64-byte block on every advance (measured: offset 7–12 in 556 of 556 advances), and SHA-256 can be resumed only over an unchanged prefix.
- Any cheaper verification therefore requires **either** a new definition **or** a reader that trusts an earlier check. Both change the contract's integrity guarantee.

## 3. Current semantics, and why they cost what they cost

- **Integrity per use:** every reader decodes the payload and recomputes SHA-256 over the full canonical state, including all claim content.
- **Cost:** O(total claim content) per validation. Measured validations per operation:

  | Operation | Validations |
  |---|---|
  | Read | 3 |
  | Typed command | 4 |
  | Maintenance step | 5 |

- **A redefinition alone (for example a Merkle root) does not remove this.** A verifier that must detect a change anywhere still hashes every leaf. A compositional digest saves work only at **build** time, about one pass per checkpoint creation.

## 4. Options

| Option | Semantics | Verification cost | What changes |
|---|---|---|---|
| **A. Status quo** | Full verification on every use | O(content) per validation | Nothing |
| **B. Hash-shape change only** (a hierarchical signature v2) | Same guarantee | Build becomes O(changed leaves + tree height); staged and reader verification stay O(content) | Contract §1 identity definition; contract version bump |
| **C. Trust earlier verification** (verified at publication, readers check the integrity digest and metadata only, or verify once per process) | **Weaker reader guarantee.** A reader no longer independently detects a payload that decodes to a different fold than signed, if payload and index were rewritten together. The trust anchor becomes the publication-time verification plus the payload digest. A per-process memo must never become authoritative across a key destruction (decode is still attempted, so unreadability is still detected) | Readers O(payload bytes); no re-hash of content | Contract §4 validation rules; the threat model statement |
| **D. Lazy per-claim verification** of only what is read | **Gives up fail-fast whole-payload integrity.** Corruption of an unread claim is not detected until it is read | Proportional to what the read touches | Contract §4; a different failure model |

## 5. Recommendation (a recommendation, not a decision)

**Keep A for now, and first apply the engineering-only fix that needs no decision: validate a checkpoint once per operation and reuse the validated fold within that operation.**
- Measured effect: reads 3→1, commands 4→2, maintenance 5→3 validations.
- The canonical signature is preserved exactly.
- Re-open B or C only if measured per-operation verification is still a bottleneck after that.
- **Prefer B over C if a change is ever needed.** B keeps the integrity guarantee and changes only the hash shape. C and D weaken what a reader can detect.

## 6. Migration and compatibility implications (any option except A)

- **Contract version bump.** Readers reject checkpoints of the old contract version (`contract_version`), and each partition gets one full checkpoint rebuild.
- **No truth migration.** Checkpoints are derived acceleration structures; the journal is untouched. Losing every checkpoint is already proven harmless.
- Both payload encodings (`full`, `ref`) would carry the new signature. Mixed-version stores coexist safely, because old-version checkpoints are simply rejected and rebuilt.

## 7. What is blocked, and what is not

| Blocked until decided | Not blocked |
|---|---|
| Any change to how a checkpoint's identity is computed or verified | Per-operation validation reuse (engineering) |
| | Trace-size encoding |
| | The `idem` index |
| | Policy-log indexing |
| | Orphan-payload GC |
| | All other workstreams |

## 8. Exact approval requested

Choose one:
1. **Approve A** (status quo), with per-operation reuse as engineering work. *(recommended)*
2. **Approve B** (hierarchical signature v2), with a contract version bump.
3. **Approve C**, with an explicit statement of the reader's reduced guarantee and its trust anchor.
4. **Approve D**, with an explicit statement of the lazy failure model.
