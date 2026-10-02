# QF-5 — Current session / configuration path (research)

Date: 2026-09-26. Read-only. **No decision is made about removing `FirestoreConfigService`.**

Commit: `olbrain-agent-runtime 8df0e02` (current `origin/main` at the time of the pre-investigation
fetch). All line references are at that commit.

---

## 1. What is live on current `origin/main`

`[CODE]` Two configuration sources coexist, serving different things, with **no flag selecting
between them**.

| Path | Source | Reached by |
|---|---|---|
| `FirestoreConfigService` | Firestore | `Agent.__init__(..., use_firestore_config: bool = True)` (`core/agent.py:40`), taken via `dependencies.py` → `factory.create_agent(agent_id)` |
| GCS `active_config.json` | `gs://{project}-deployment-configs/configs/{agent_id}/active_config.json` | `core/utils/agent_config_resolver.py:5,24,59`; imported by `routers/chat.py:34`; documented as the source in `routers/agent_memory.py:119` and `routers/handoff.py:235` |

`[CODE]` `core/agent.py:91-92` — `if self._use_firestore_config: self.config_service = FirestoreConfigService(self.agent_id)`.

---

## 2. Which methods are undefined — exhaustively established

`[CODE]` The `Agent` class at `core/agent.py` defines exactly these public/private methods:

`__init__`, `initialize`, `_initialize_essential_services`, `_get_enabled_tools_config`,
`_load_agent_whatsapp_number`, `_initialize_session_authentication`,
`_initialize_universal_llm_interface`, `_build_system_prompt`, `create_session`,
`find_or_create_session_for_phone`, `get_session`, `update_session`, `archive_session`,
`get_agent_info`, `get_token_usage`, `get_memory_stats`, `cleanup`.

**Neither `process_message_universal` nor `stream_response` is among them**, and
`git grep -E "def (process_message_universal|stream_response)"` returns nothing anywhere in the
repository.

`[INFERENCE]` The surviving `Agent` object is a **session-management and introspection object** —
create/get/update/archive a session, report info, token usage and memory stats. It has no
message-processing capability of any kind. That is the structural fact behind QF-5, and it is
stronger than "the config path is legacy": the object the Firestore config path configures cannot
process a message at all.

### 2.1 Nothing supplies them dynamically

`[CODE]` Searched and found absent: any `setattr` on an `Agent` providing either method; any mixin,
subclass, adapter or generated code defining them; any test mock (the apparent test hits in
`tests/test_tenant_router.py` are the unrelated local variable `upstream_response`). The only
`getattr` on an agent is `routers/monitoring.py:156`, reading `agent_config`.

---

## 3. Which branches can reach them

`[CODE]` Exactly two call sites, both in one router:

- `routers/sessions.py:462` — `response_data = await agent.process_message_universal(abstract_message)`
- `routers/sessions.py:568` — `async for chunk in agent.stream_response(`

`[INFERENCE]` Both are reachable code paths on the non-stream and stream branches of the session
message endpoint. If either is executed, Python raises `AttributeError` at the call. There is no
guard, fallback or `hasattr` check preceding either.

### 3.1 How long they have been undefined

`[CODE]` `git log -S "async def process_message_universal" -- core/agent.py` shows the method
removed in **`7a51069` / `4cbed37`, both dated 2026-04-01**, commit subject
*"chore: remove deprecated MessageProcessor pipeline"*. The method existed from the initial commit
(`d9f1a51`, 2026-01-29) until then.

`[INFERENCE]` **The two branches have called an undefined method for approximately six months**
(2026-04-01 → 2026-09-26). This materially changes what the QF-5 log query needs to establish.
Two readings are consistent with six months of silence:

- **(a) Dead traffic.** The endpoint is not called; nobody has noticed because nothing reaches it.
- **(b) Erroring traffic tolerated.** The endpoint is called and fails, and the resulting 500s are
  either unmonitored or attributed elsewhere.

`[INFERENCE]` (a) is the more probable reading — a continuously-500ing message endpoint on a
conversational platform would be unlikely to survive six months unreported — but **(b) cannot be
excluded from source alone**, and distinguishing them is precisely what Jay's *"investigate first"*
answer asks for.

### 3.2 Documentation still advertises them

`[CODE]` `README.md:340,348,355,385`, `WEBHOOK_ARCHITECTURE.md:21`
(*"Processes messages through `agent.process_message_universal()`"*) and
`OUTREACH_EXECUTION_GUIDE.md:294` all document the removed API. `[INFERENCE]` The documentation
was not updated when the pipeline was removed, which is a plausible reason the call sites survived.

---

## 4. Construction-time only, or message-processing critical?

`[INFERENCE]` **Construction-time and session-CRUD only**, on the evidence:

1. The `Agent` object has no message-processing method (§2), so it cannot be message-processing
   critical by construction.
2. Every channel router — WhatsApp, email, Instagram, directives, chat — obtains configuration
   from GCS `active_config.json` via `agent_config_resolver`, not from `FirestoreConfigService`.
3. `FirestoreConfigService` is instantiated inside `Agent.__init__`, so it is reached only when an
   `Agent` is constructed, which `dependencies.py` does per request for the routes that take that
   dependency.

`[CODE]` `create_agent_with_settings()` (`core/agent_factory.py:72`) — the settings-based
alternative — has no non-documentation callers, confirming the Firestore default is the only live
construction path.

`[INFERENCE]` This corroborates Jay's QF-5 correction exactly: `FirestoreConfigService` serves
session CRUD and `/agent/info`; message processing is GCS-backed. It should not be described as
the active message-processing configuration path.

---

## 5. What evidence would settle QF-5 — executable log specification

`[UNMEASURED]` Production logs are not accessible from this workspace (no credentials, no
`gcloud`, `firebase` CLI on an unrelated account). **No attempt was made to obtain access.** The
specification below is what someone with access should run.

### 5.1 Primary query

| Element | Specification |
|---|---|
| **Service** | `olbrain-agent-runtime` (Cloud Run), all revisions |
| **Window** | **2026-04-01 → present** — the removal date. A shorter window cannot distinguish readings (a) and (b) |
| **Endpoints** | `POST /sessions/{session_id}/messages` — both the non-stream branch (`sessions.py:462`) and the stream branch (`:568`) |
| **Group by** | HTTP status, revision, calling client/user-agent, org |
| **Decisive counters** | (i) total requests; (ii) count of **2xx**; (iii) count of **5xx**; (iv) count of log entries containing `AttributeError` and `process_message_universal` or `stream_response` |

### 5.2 How to read the result

`[INFERENCE]` Stated in advance so the outcome is not argued after the fact:

- **Total requests ≈ 0 since 2026-04-01** → reading (a). The endpoint is dead; QF-5's *"expected
  outcome"* branch applies (GCS canonical; the Firestore path, the two dead branches and
  `create_agent_with_settings` become removable). **The decision is still Jay's.**
- **Requests > 0 and effectively all 5xx** → also reading (a) in substance — the endpoint is
  reached but has never worked — but it means a live caller exists whose failure is being absorbed
  somewhere, and that caller must be identified before anything is removed.
- **Any 2xx on these two branches** → falsifies §2's analysis and would be a significant finding:
  it would mean the methods are supplied by a mechanism this pass did not find, and the source
  analysis must be redone before any decision.

### 5.3 Secondary queries

`[INFERENCE]`

- Which routes actually construct an `Agent` (i.e. take the `dependencies.py` dependency), by
  request volume — this sizes what `FirestoreConfigService` genuinely serves today.
- Whether `/agent/info` and the session CRUD routes carry meaningful traffic, which is the
  positive case for **retaining** the Firestore path rather than the negative case for removing it.
- `HOTPATH_DOC_CACHE_ENABLED` per environment — unrelated to QF-5 but noted in
  `governance-g1-g6-research.md` §7 and obtainable from the same deployment inspection.

---

## 6. What QF-5 is, and is not

`[INFERENCE]`

- **It is not** a choice between two configuration systems. Message processing is already GCS-only;
  there is no contest.
- **It is** two separable questions that the card phrases as one:
  1. *Is the `Agent` + `FirestoreConfigService` construction path retained for session CRUD and
     `/agent/info`?* — a product/runtime-owner decision, informed by §5.3.
  2. *What happens to the two branches that call undefined methods?* — **a defect, independent of
     (1) and true whichever way (1) goes.** It stands even if the Firestore path is retained
     forever.

`[INFERENCE]` Separating them is the most useful thing this report offers: (2) needs no decision
from Jay to be *recorded* as a defect, though fixing it is a code change and is out of scope here.

---

## 7. Limitations

1. `[UNMEASURED]` No production log access; §5 is a specification, not a result.
2. `[CODE]` statements about absence rest on source search at one commit; a mechanism outside the
   repository (a sidecar, a proxy rewriting the route, an alternative deployment of a different
   revision) would not have been found.
3. `[UNMEASURED]` Which Cloud Run revision is actually serving traffic was not determined; if a
   pre-2026-04-01 revision is still live, the methods exist there and §3.1's reasoning does not
   apply to it. **This is the most important caveat in the report** and the log query in §5 should
   group by revision for exactly that reason.
4. No assessment is offered of whether `FirestoreConfigService` *should* be retired — that is
   explicitly Jay's/the runtime owner's decision.
