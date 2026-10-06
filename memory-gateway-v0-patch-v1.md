# Memory Gateway v0.1 Patch v1 (GW-1, GW-2, GW-3; GW-G2 text)

**Date:** 2026-10-04.

**Classification:** TARGET ARCHITECTURE. A surgical Gateway patch plus verification. Test-only reference.

**Decisions implemented:** `memory-gateway-defect-decisions-v1.md` (GW-G1, GW-G3, GW-G2).

**Labels:** [PROVEN], [INFERENCE], [OWNER], [CONTRACT_GAP].

**FINAL VERDICT: GATEWAY V0.1 CONFORMANT.**

---

## 1. GW-1 fix: causal-token validation (GW-G3 hybrid)

**Order in every read** (`get_current_state`, `search_history`, `compile_context`):
1. bind and authorise the handle;
2. **validate `after`**;
3. only then close and serve.

**`after` is accepted only if it is one of:**
- `None`;
- a **finite** number (not a bool) with `after ≤ B = max(gateway clock, the latest durable commit time in the bound subject's partition)`; B comes from one read of durable facts, not a closure;
- a **Gateway-signed causal token**, verified by MAC with `org` and `subject` equal to the binding, carrying a finite position.

**Otherwise:** **INVALID_CAUSAL_TOKEN**, with `r = None` and **no core access at all** (a spy confirms zero journal reads or closures).

**Tokens:**
- `"ct." + base64(json{org, subject, pos}) + "." + HMAC-SHA256`;
- the key is `HMAC(handle_secret, "olbrain-gateway-causal-token-v1")`, so it is domain-separated and in the **same custody class** as the handle secret (C-1 [OWNER]; no new custody model);
- every `WriteResult` with a time (APPENDED or DUPLICATE) and every `ReadResult` carries `token`;
- `ContextPackage` keeps its pinned v0 shape (its field set is asserted by the unchanged G0 test), and its `r` is usable as a numeric token within B.

**The existing numeric v0 API stays compatible:** numbers within the bound work exactly as before (the G0 suite is unchanged and green).

## 2. GW-2 fix: content fingerprint on durable outcomes

- Every `commit_outcome` payload is `(status, at, reason, actual_version, fingerprint)`, where the fingerprint is the **gate's existing canonical `fingerprint(pr)`**. It covers subject, org, predicate, policy version, operation, writer, source, value, **sorted** anchors (order-insensitive), map key and validity. It is deterministic, process-independent, and no new command semantics are invented.
- **The lookup, before any time is assigned:**

  | Case | Result |
  |---|---|
  | Same `(org, subject, command_id)` and the same fingerprint | **DUPLICATE**, with the original outcome (and a token for its time) |
  | Same key, a **different** fingerprint | **COMMAND_ID_REUSED**. Not recorded; the original is unaffected |

- `expected_version` stays outside the fingerprint: it is a precondition. This keeps the G0 rule "the same id with a now-valid version replays the original outcome".

## 3. GW-3 fix: durable namespace only

- The namespace is `(org_id, subject_id, command_id)`. The authority is the bound subject's partition entry `"outcome:" + command_id`.
- **The gate is called with a fresh, empty ledger on every call**, so no in-process ledger can decide an outcome. `_gate_ledger` is kept, always empty, with a comment. The gate is unchanged.
- `_pending` is now keyed `(subject, command_id)` and remains an optimisation **for an unresolved transient attempt only**. After loss, the retry re-decides from durable facts.

## 4. GW-G2 contract correction (text only; semantics unchanged)

Gateway contract → **v0.1**.

**§2 now states:**
- the binding authority (org, merge root, member-set version) is the **identity-layer subject head**;
- **evidence is not the identity authority**;
- v0's mapping derived from ingestion is a **test/reference stub**;
- **reads and writes both** depend on the identity binding;
- its durability, availability and interface are **[OWNER]**;
- binding fails closed without it.

**§11 is retitled and corrected accordingly.**

**Also amended for the fixes:**
- §6: causal-token validity;
- §8: namespace, fingerprint, durable-only outcomes;
- §12: new codes;
- §13: "process state never decides" is now [PROVEN];
- §16: the conformance result.

## 5. Test results

| Suite | Tests | Explicit | Implied | Store-independent |
|---|---|---|---|---|
| G0 `test_memory_gateway_v0.py` | 38, **unchanged** | 19/19 | 19/19 | — |
| Adversarial `test_memory_gateway_adversarial_v0.py` | **109** (63 from the audit + 46 new) | pass | pass | pass |
| Both Gateway suites together | 147 | **72/72** | **72/72** | 3 |

**Changes to the adversarial suite** (additive, plus the required marker removal):
- the **8 strict defect reproducers** now pass, and their `xfail` markers and the GW marker definitions are **removed**;
- **one decision-driven expectation change, flagged:** `test_stale_or_nan_tokens_do_not_move_the_read_and_two_conversations_agree` asserted v0's tolerance of `after=NaN`. GW-G3 makes NaN an **invalid** token, so the assertion now expects INVALID_CAUSAL_TOKEN. Its stale-token and two-conversation assertions are unchanged;
- **46 new tests**, each over both stores:

  | Area | Tests |
  |---|---|
  | INVALID_CAUSAL_TOKEN before closure, for 9 bad values (1e9, 1e300, ±inf, NaN, bool, str, list, dict) | 18 |
  | The numeric bound | 2 |
  | Signed tokens issued and accepted | 2 |
  | Token binding and forgery (another subject, wrong org, modified position, forged MAC, foreign key) | 2 |
  | Skewed-node monotonic read (a number refused, a signed token accepted) | 2 |
  | COMMAND_ID_REUSED for 6 material variants (value, predicate, policy version, valid_from, valid_until, anchor) | 12 |
  | Anchor-order insensitivity | 2 |
  | Two subjects with one id are independent | 2 |
  | Process state cleared between every call, plus a restart (DUPLICATE identical; different content refused; signed token survives the restart) | 2 |
  | Another org's namespace | 2 |

**No xfails remain anywhere** [PROVEN].

## 6. Mutation results

Each protection was removed in turn, both Gateway suites were run, and the code was restored byte-identical. **19 of 19 caught:**

| Protection removed | Failures |
|---|---|
| Handle authorisation | 16 |
| Subject binding | 10 |
| Org binding | 6 |
| Handle signature | 4 |
| **Causal-token validation skipped** | 34 |
| **Numeric bound** | 10 |
| **Finiteness** | 2 |
| **Token signature** | 2 |
| **Token org/subject binding** | 2 |
| Duplicate before time | 26 |
| **Command fingerprint comparison** | 16 |
| **Fresh gate ledger** | 6 |
| Stale policy stamp (gate) | 2 |
| Stale policy stamp (write) | 2 |
| In-flight conflict at write | 1 |
| Conflict at build | 2 |
| Transient retry | 9 |
| Transient not terminal | 4 |
| Scope validation | 4 |

**Note on "finiteness" (2):** `inf` and NaN are also rejected by the bound (`inf > B`; `NaN ≤ B` is false), so only `-inf` isolates this check. It is caught.

## 7. Regression results

| Run | Result |
|---|---|
| Full prototype suite | **1202 passed, 0 xfailed** |
| The pre-audit baseline (everything except the adversarial file) | **1093 passed**, identical to before |

**No foundational component changed:** Durable Journal v1.1, K1–K10, StorageBoundary, the gate, the commit layer, typed retrieval, the Context Compiler, the Pipeline and Lane A handles are all untouched. No existing G0 or core test was edited.

## 8. Files changed

| File | Change |
|---|---|
| `memory-prototype/memory_core/gateway/__init__.py` | GW-1, GW-2, GW-3 |
| `memory-prototype/tests/test_memory_gateway_adversarial_v0.py` | Markers removed, the flagged NaN expectation, 46 new tests |
| `investigation/memory-gateway-contract-v0.md` | Retitled **v0.1**; the §2, §6, §8, §11, §12, §13, §16 amendments |
| `investigation/memory-gateway-v0-patch-v1.md` | This report |
| `investigation/MASTER.md` | Entry |

## 9. Final verdict

**GATEWAY V0.1 CONFORMANT.**

- **GW-1, GW-2 and GW-3 are fixed:**
  - the former reproducers pass on both reference stores;
  - dedicated tests cover every case the decisions specify;
  - every protection is necessary per the mutation run;
  - the full suite is green with no xfails.
- **Still owner-held** (unchanged; none reopened):
  - the identity-layer binding interface and its guarantees (GW-G2 [OWNER]);
  - the evidence-store guarantees [CONTRACT_GAP];
  - signing and handle key custody (C-1);
  - the retry budget;
  - stale-tolerant read classes;
  - non-CUSTOMER grants;
  - C-5 (parked).
