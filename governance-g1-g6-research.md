# G1 + G6 — Capability caching and online authorization (research)

Date: 2026-09-26. Read-only. **No TTL is assigned and no operation set is chosen here.**
`[CONTRACT]` requires G1 and G6 to be answered together; this report prepares both.

Commits: `olbrain-agent-runtime 8df0e02` · `olbrain-agent-engine e43654e` ·
`olbrain-studio 8cee761c` · `olbrain-shared 8a0f0b5`.

---

## 1. The paired question

`[CONTRACT]` §16 rows 1 and 6. G1: is *"60s general, tighter for sensitive operations"* approved,
and what is the tighter value? G6: which operations require online authorization rather than a
cached capability? The contract's own note explains the coupling: *"Zero revocation lag and
auth-outage tolerance are mutually exclusive… The TTL in item 1 is the accepted lag. Item 6 names
the operations for which that lag is unacceptable."*

---

## 2. The decisive existing precedent

`[CODE]` **OLBrain has already made this exact decision once**, for API-key authentication, and
the shape of its answer is directly transferable.

`olbrain-agent-runtime 8df0e02:core/hotpath_cache.py`:

```
"""R4 (perf/prelim-hotpath-surgery): tiny TTL cache for rarely-changing ...
  HOTPATH_DOC_CACHE_TTL_SECONDS  entry TTL when enabled (default 30)
  ... an agent can be served from cache for at most TTL seconds."""
```

- `doc_cache_enabled()` reads `HOTPATH_DOC_CACHE_ENABLED`, **default `"false"`** (`:38-42`).
- `doc_cache_ttl_seconds()` reads `HOTPATH_DOC_CACHE_TTL_SECONDS`, **default `30`** (`:44-45`).
- `TTLDocCache` is a minimal thread-safe `key -> (value, expires_at)` store (`:52-85`).

And the split that matters, at `core/api_key_middleware.py:288-293`:

> *"R4 (flag-gated, default OFF): TTL cache for the api-key doc **FETCH**. **Only the fetch is
> cached — every check below (hash re-compare, status, expiry, org membership, scoped-agent pin,
> rate limit) still runs per request.** Copy on hit so the caller's `doc_data['id'] = ...` stamp
> can't poison the cached entry."*

`[INFERENCE]` This is precisely the G1/G6 architecture in miniature, and it answers the paired
question in a way the contract's framing does not anticipate:

**It is not "which operations are cached vs online". It is "which *part of the authorization
computation* may be cached".** The credential *lookup* is cached; every *predicate* — status,
expiry, org membership, scope pin, rate limit — is evaluated per request against fresh inputs.
Revocation that flips `status` takes effect on the next request regardless of TTL, because status
is re-checked, not cached.

That decomposition materially shrinks G6's scope: under it, most operations need no "online
authorization" exception, because the parts that must be fresh already are.

---

## 3. What the architecture already implies

`[CONTRACT]`

- Authorization is **never** part of state resolution (§6, *"Authorization is not part of state
  resolution"*). So a capability cache cannot be justified or excused by resolution semantics; it
  is a separate plane.
- Scope hierarchy for deletion **MUST NOT** imply authorization inheritance — stated twice. A
  cached capability must therefore not be widened by any scope relationship.
- `account_role` is writable only by `IDENTITY_SYSTEM` under `IDENTITY_SECURITY`, with
  `LLM_WRITE = FORBIDDEN` and `USER_WRITE = FORBIDDEN` (`architecture-contract.md:1212-1213`).
  `[INFERENCE]` Any capability derived from `account_role` inherits that write-authority
  restriction, which is an argument for treating role-derived capabilities as *less* cacheable
  than key-derived ones — a role change is a security event, a key fetch is not.

`[CODE]` **Fail-closed is already the house pattern.** `_caller_org` raises rather than defaulting
(`routers/agent_memory.py:33-46`), and the cross-tenant posture is 404-not-403 so existence is not
confirmed. A capability cache must not convert a fail-closed path into a fail-open one on cache
hit — the `hotpath_cache` design avoids this by caching only the fetch.

---

## 4. Existing cached-auth patterns, inventoried

`[CODE]`

| Pattern | Location | What is cached | TTL | Default |
|---|---|---|---|---|
| API-key doc fetch | `agent-runtime 8df0e02:core/api_key_middleware.py:288-308` | the credential document only | `HOTPATH_DOC_CACHE_TTL_SECONDS`, 30s | **OFF** |
| Rate-limit counters | `core/api_key_middleware.py:83` | in-memory rate state | n/a | on |
| Agent config (GCS) | `core/utils/agent_config_resolver.py`, `cs_packet_builder.py:731` | `active_config.json` | `CONFIG_CACHE_TTL` | on |
| Context summary freshness | `agent-engine e43654e:alchemist/services/context_broker.py:185` | `summary_freshness: timedelta` | varies | on |

`[INFERENCE]` Only the first is an *authorization* cache. The others are configuration/content
caches and are not evidence about revocation tolerance. Note the config cache is the one
`artifacts/senior-feedback.md §2` flags as *never invalidated on publish* — a cautionary precedent
for any cache without an invalidation path.

---

## 5. What can safely operate online-only today

`[CODE]` Everything. `HOTPATH_DOC_CACHE_ENABLED` defaults to `false`, so **production is currently
online-only for authorization** unless the flag is set per environment (`[UNMEASURED]` — which
environments enable it was not determined; it is an env var, not in source).

`[INFERENCE]` This is the strongest practical input for G1: the platform runs online-only today.
The decision is therefore *whether to permit a cache*, not *how to safely remove one*. Nothing
breaks if the answer is "no caching in MVP" — that is the current state, and the dashboard already
records online-only as the safe interim.

---

## 6. What must remain online-authorized regardless of the TTL

`[INFERENCE]` Derivable from the contract without deciding G6's list:

1. **Anything writing `IDENTITY_SECURITY`-domain predicates.** `[CONTRACT]` Only `IDENTITY_SYSTEM`
   may; a cached capability that permitted it would let a stale grant write identity.
2. **Revocation itself, and any grant-management operation.** Caching the authorization for
   changing authorization is circular.
3. **Cross-tenant-visible operations** — anything whose failure mode is disclosure rather than
   denial. `[CODE]` The existing 404-not-403 pattern shows the house treats tenancy checks as
   non-negotiable; caching one would be the first exception.
4. **Bulk deletion** — interacts with G8 and `scope_generation`; a stale capability could authorize
   work against a scope whose generation has moved.

`[UNDECIDED]` Whether "sensitive" extends beyond these four is exactly G6 and is not decided here.

---

## 7. What information Jay and Security need for the paired decision

`[INFERENCE]` Ordered by how much it changes the answer:

1. **Is the 30s precedent acceptable as the general TTL, or is 60s intended?** The contract
   *proposes* 60s; the codebase *implemented* 30s for the analogous case. These differ and nobody
   has reconciled them. **This is the single cheapest input to the G1 decision** and it is a
   factual discrepancy, not an opinion.
2. **Is the fetch/check decomposition (§2) adopted as the model?** If yes, G6's list shrinks to
   operations where even a stale *credential document* is unacceptable — a much smaller set than
   "operations requiring online authorization" implies.
3. **What is the revocation path, and does it have an invalidation hook?** `[CODE]` `TTLDocCache`
   has `clear()` but no targeted invalidation, and no caller invokes it on a revocation event.
   Without that, TTL *is* the revocation lag. With it, the TTL matters far less.
4. **Which environments enable `HOTPATH_DOC_CACHE_ENABLED` today?** `[UNMEASURED]`. If production
   already runs with it on, the accepted lag is already 30s de facto and G1 would be ratifying
   rather than choosing.

---

## 8. Consequences of the plausible answers

`[INFERENCE]` Stated conditionally, per the standing rule.

- **If Jay/Security keep online-only for MVP:** nothing changes, nothing is blocked, and the
  capability-cache design can be deferred entirely. The cost is latency, already borne today.
- **If they adopt the fetch/check split with a 30s TTL:** the existing implementation is the
  reference; G6's list reduces to §6's four categories plus anything Security adds; an
  invalidation hook on revocation becomes the one new requirement.
- **If they adopt a 60s TTL for whole capabilities (not the split):** revocation lag becomes a real
  60s window on every check including org membership, and G6's list must then be exhaustive rather
  than indicative, because anything omitted from it inherits the full lag.

---

## 9. Limitations

1. Whether `HOTPATH_DOC_CACHE_ENABLED` is set in any deployed environment is `[UNMEASURED]` —
   it is an environment variable and deployment configuration was not inspected.
2. `[CODE]` statements about "no invalidation caller" reflect a source search for `doc_cache.clear`
   usage; a dynamically-dispatched caller would not have been found.
3. No capability object exists in any repository today — `[CODE]` there is no `capability` type,
   so §2's precedent is *analogous* (API-key authentication) rather than the mechanism G1/G6
   governs.
