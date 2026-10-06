# Target Architecture: C-5 Evaluation Issuance v1

**Classification:** TARGET ARCHITECTURE. Issuance record only. **C-5 remains undecided.**

| Item | Value |
|---|---|
| Authorisation | The owner's instruction "Issue the v2 storage technology evaluation request for both Firestore and PostgreSQL", 2026-10-04 |
| Issuance date | 2026-10-04 |
| Request issued | `investigation/storage-technology-evaluation-v2-request.md`, **v2.0**, SHA-256 `920623994cb8c2716d6c80142c1ec62e54464cab4fbba88fbdbc06c0c1dc38bd` |
| Candidates | **Firestore** and **PostgreSQL** (no others) |
| Contract | Durable Journal and Rebuild Contract **v1.1** (`durable-journal-rebuild-contract-v1.md`) |
| Boundary suite | **86** tests (86/86 on both reference stores at issue) |
| X-1 | 64/64 explicit; 53/64 implied. The 11 differences are mechanism-specific evidence, not semantic failures (v4 §3, v5) |
| Baseline | **1055/1055** (re-run at issue) |
| Environment tests | E1–E9, unchanged: concurrent conditional append versus closure; publish versus append; durability before acknowledgement; crash and recovery of closure; current-read closure cost; lagging and as-of reads; contention and retry; group-size limits; erasure under concurrency |

## 1. Pre-issue consistency check (bounded)

| # | Check | Result |
|---|---|---|
| 1 | Written against contract v1.1 | ✔ |
| 2 | Boundary suite count is 86 | ✔ (re-run: 86 passed) |
| 3 | X-1 64/64 explicit, 53/64 implied; the 11 classified as mechanism-specific | ✔ (re-run; **counts added to the request**) |
| 4 | K9 in flight proven for both forms | ✔ (the common test, both stores; the request names it) |
| 5 | The same E1–E9 | ✔ (nine rows, text unchanged) |
| 6 | Only Firestore and PostgreSQL | ✔ (**the "Other" row removed**) |
| 7 | No benchmark target, score, ranking, preference or implied winner | ✔ ("likely explicit form" softened to "possible … [INFERENCE]; the choice stays the adapter's") |
| 8 | Explicit/implied choice open per candidate | ✔ |
| 9 | One shared, technology-neutral concurrency driver for both | ✔ |
| 10 | No prototype mechanism turned into a requirement | ✔ (**one wording fixed:** "the entry durable only if **the time service** has not passed its time"; results must state the mechanism as a separate dimension, never as a requirement) |
| 11 | No owner decision silently made | ✔ (**"C-5 stays Infrastructure's decision" restated:** C-5 is a separate decision taken on the returned evidence; this evaluation does not make it. Owner parameters are listed as out of scope) |
| 12 | No production credential, data, deployment, migration, shadow write or Gateway requested | ✔ (**production deployment and shadow writes added** to the out-of-scope list) |

**Scope additions made to match the authorisation:**
- PostgreSQL: an explicit requirement for a `StorageBoundary` journal adapter (test-only), and RLS and `SET LOCAL` under pooling where the adapter uses them.
- Firestore: an explicit `StorageBoundary` adapter, and a scoped test identity.
- Results must keep five dimensions separate:
  - semantic conformance;
  - operational behaviour;
  - measured cost;
  - availability and durability;
  - implementation mechanism.
- A per-candidate return package (§5a of the request).

No semantic content of the request changed.

**Known metadata lag, not changed (forbidden):** the v1.1 contract's header still lists 78 boundary tests and a 1047-test suite. The authoritative counts at issue are 86 and 1055 (this record).

## 2. Evidence Infrastructure must return (request §5a), per candidate

1. The adapter, the connector, and the closed-position form chosen (explicit or implied, with the time service named if implied).
2. Results of the three suites run unchanged, with each failure classified.
3. The shared concurrency driver (source and configuration), identical for both candidates.
4. For each of E1–E9: the classification (PROVEN_EXECUTABLE with the environment named, PROVEN_DOCUMENTATION, INFERENCE, NEEDS_ENVIRONMENT, FAILS, CONTRACT_GAP), the recorded measurements and the raw logs.
5. Every CONTRACT_GAP, stated as scenario, rule and behaviour, without a workaround.
6. Environment description, and confirmation that only synthetic data and test identities were used.

Results are reported along the five dimensions above. A cost or availability figure is never a conformance result. **No storage choice is to be derived from the results except by a separate C-5 decision.**

## 3. Transmission limitation

**The request is issued as a final, hashed artifact in this repository. It has not been delivered to Infrastructure by this session:**
- no Infrastructure recipient or channel is known here;
- the Slack and Atlassian connectors are not authorised in this session;
- sending email to an unconfirmed address would be an unverified outward act.

**Delivery is the owner's step:** send the v2.0 file (verify its SHA-256 above) through the normal Infrastructure channel. Until delivery is confirmed, no environment is provisioned and nothing is awaited.

## 4. Status

- **C-5: UNDECIDED.**
- No store selected, nothing provisioned, no production touched.
- No journal implementation, Gateway, Pipeline/K9 change, contract change or owner decision.
- **Next architectural step:** begins when Infrastructure returns the evidence in §2.
- **The next decision after that:** C-5, select the durable storage architecture based on that evidence.

---

**Correction (2026-10-04).** "Through the normal Infrastructure channel" (§3) was an unsupported assumption: no Infrastructure destination is documented. The destination is **not established**; see `target-architecture-infrastructure-delivery-v1.md`. Everything else in this record stands.
