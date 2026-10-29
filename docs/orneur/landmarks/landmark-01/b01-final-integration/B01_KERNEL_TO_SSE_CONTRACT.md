# B-01 — Kernel → SSE contract (as implemented)

Evidence state of this document: **VERIFIED_ENGINEERING** (engineering-owned tests; not independently qualified).
Code: `orca/serve/api.py` (`_stream_dispatch`, `_event_stream`), `orca/cognitive/streaming.py`, `orca/cognitive/kernel.py`, `orca/serve/stream_dlp.py`.

## 1. When a turn is streamed from the Kernel

`POST /api/stream` streams the Kernel's own gateway deltas **iff all of these hold**; otherwise the pre-existing path runs unchanged.

| Condition | Why |
|---|---|
| the resolved backend for the tier is the local **Ollama** backend | frontier backends are synchronous passthroughs (`Backend.generate()`); nothing to stream |
| the session has **no loaded documents** (`sess.doc_store.count() == 0`) | a document session may discard the Kernel's draft for the RAG pipeline (known limitation B-06, untouched here) |
| the Kernel's plan is a **direct answer** | decided by the Kernel, not by the API; if it abstains, refuses or defers to tools/RAG, the API reports/continues exactly as before |

Truth-Fabric-routed answers (plans containing `RETRIEVE/SEARCH/VERIFY` operations) are **never streamed**: their text is only a draft until `verify_answer()` accepts it (and an AUDIT-grade failure abstains *after* generation). The Kernel therefore withholds `on_raw_delta` / `on_served` for that call (`dataclasses.replace(request, on_raw_delta=None, on_served=None)`), and the API delivers the verified answer whole, labelled `replayed` — the honest, pre-existing behaviour. Regression test: `test_truth_fabric_draft_tokens_never_reach_the_raw_delta_hook`.

## 2. Order of operations (everything before the model call is unchanged and happens first)

```
 1  auth           get_current_user_optional: no credential -> anonymous; an INVALID/expired/revoked credential -> HTTP 401 (zero model dispatch)
 2  rate limit     HTTP 429
 3  intent / plan  image/video intent -> SSE error;  model_access_allowed -> SSE error;  input moderation -> SSE error
 4  quota          _admit_message_quota: ATOMIC reservation (store reachable first, else history_unavailable)
 5  ownership      _check_session_ownership (HTTP 404);  _temporary_block (HTTP 409)
 6  authority      _hold_turn: Redis lease (advisory) + SQLite fencing epoch      <- BEFORE the Kernel assembles any context
 7  routing        backend resolution; _get_session; _temporary_block; eligibility (section 1)
 8  response       StreamingResponse becomes active; `session`, `generation` events are sent
 9  authority      (new session id only) _hold_turn inside the generator, before the Kernel starts
10  model          KernelRun starts the Kernel as a SUPERVISED task with on_raw_delta/on_served hooks
11  deltas         every raw delta -> consume quota (first output) -> StreamRedactor.push -> SSE `chunk` (safe text only)
12  completion     Kernel result validated: status, output == the concatenation of the raw deltas received, StreamRedactor.finish()
13  commit         still_authoritative() -> _persist_turn: existing SQLite-authoritative transaction (fence, epoch, expiry, owner re-validated INSIDE it)
14  derived state  live window, long-term memory, graph, Redis history: only for an ACCEPTED commit
15  done           truthful `persisted` ("saved" | "failed" | "not_applicable")
```

Steps 4 and 6 are the guarantee behind the directive's "admission and turn authority before model dispatch": nothing in steps 8–15 can run for a request that failed steps 1–7, and the producer task does not exist until step 10.

## 3. Events

| Event | When | Notes |
|---|---|---|
| `session` | first | `session_id` |
| `generation` | second | unchanged (`generation_id`, `session_id`) |
| `model` | immediately before `stream` (after the first real delta has arrived) | identity built from what the gateway **resolved for this call** (`on_served`: tier, `chunk.resolved_version`, deployment, runtime, entitlement downgrade) — not guessed. The `done` event repeats the identity computed from the completed `CognitiveResult`; if the two ever differed, a corrected `model` event (`"corrected": true`) is sent and audited. Tests assert equality. |
| `stream` | immediately before the first chunk, only after a real gateway delta arrived | `{"type":"stream","delivery":"upstream","cancellable":true}` — emitted only when an actual cancellable upstream stream is active (never earlier, when the Kernel may still defer or abstain). Order is the established `model`, `stream`, `chunk…`. |
| `chunk` | per safe delta | `{"type":"chunk","text":...}`; no `replayed` key |
| `error` | any failure/refusal | `PublicError.as_sse()`; no `done` follows |
| `done` | after the commit | `delivery:"upstream"`, `persisted`, `message_id`, `user_message_id`, `model_identity`, sources… The answer text is **not** repeated. |

Non-streamed turns (documents, Truth Fabric, frontier backends, idempotent replays) keep their existing events: `stream` `{delivery:"replayed",cancellable:false}` + one `chunk` with `replayed:true`.

The ASGI/browser contract is otherwise **unchanged** (additive: nothing was removed or renamed).

## 4. Raw-output boundary

`on_raw_delta` receives **unredacted** provider text. It is wired only here, only to `KernelRun`'s channel, and the only consumer is the loop in `_event_stream`, which passes every delta through `StreamRedactor` before anything leaves the process or is stored. `/api/chat` never sets the hooks. The Kernel itself redacts (`dlp.scan_output`) the text it hands to working-memory ingestion (`_finalize_working_memory`), which previously received the raw text for *every* Kernel-direct answer on both routes.

## 5. Quota, authority, cancellation (billing policy unchanged)

* **Quota** — reserved atomically at step 4; consumed at the **first model output** (`_consume_message_quota` on the first delta; idempotent afterwards); released on every exit before any output (provider failure, Stop/disconnect before the first token, abstention, refusal). After output has arrived the unit stays spent (the established policy, asserted by `test_S7_*` and the browser step J3).
* **Authority** — `_TurnAuthority` (heartbeat renews the SQLite authority during the whole generation) is released in `_event_stream`'s `finally` and by `stream_chat`'s wrapper. A stale writer cannot commit: `commit_turn` re-validates fence/epoch/expiry/owner inside the transaction (`test_S12_worker_stalled_MID_STREAM_…`).
* **Stop / disconnect** — the browser aborts the fetch; the server cancels the `KernelRun` producer, which closes the gateway iterator (`contextlib.aclosing` in the Kernel), which closes the Ollama connection. `finally: await kernel_run.aclose()` waits for the producer to finish, so no task survives the request. Measured at the provider boundary against **real Ollama**: the recording tap saw ORNEUR hang up 0.05 s after the client left; relayed lines stopped (see `B01_REAL_OLLAMA_STREAMING_EVIDENCE.md`).
* **No phantom turn** — the commit happens only after a validated, complete answer; cancellation or failure before it writes nothing. Where Stop races the commit itself, exactly one of two coherent states results and is reported by what is stored (`test_stop_racing_the_commit_leaves_only_coherent_states`: 36 rounds, commit won 10 / cancel won 26, never a partial or duplicated turn, quota spent exactly once).

## 6. Refusal protocol — measured, and different from the Cursor handoff's claim

The Cursor handoff states that all pre-admission refusals are HTTP JSON statuses. **That is not what the route does.** `tests/test_b01_refusal_protocol.py` drives every refusal path and writes the measured table (`evidence/refusal_protocol.json`):

| Path | HTTP | Body | Public code | Where it happens |
|---|---|---|---|---|
| invalid / expired / revoked bearer | **401** | JSON | `auth_required` | dependency, before the route body |
| rate limit (60/min/IP) | **429** | JSON | `rate_limited` | first line of the route |
| conversation owned by another account | **404** | JSON | `session_not_found` | after quota admission (quota is released) |
| temporary chat closed / expired | **409** | JSON | `temporary_closed` / `temporary_expired` | after quota admission (quota is released) |
| model not allowed on the plan | 200 | **SSE** `error` | `model_access_denied` | before quota |
| input moderation block | 200 | **SSE** `error` | `content_refused` | before quota |
| image/video generation intent | 200 | **SSE** `error` | `lens_not_available` | before quota |
| daily quota exhausted | 200 | **SSE** `error` | `quota_exceeded` | quota admission |
| durable store unavailable | 200 | **SSE** `error` | `history_unavailable` | quota admission (nothing generated, nothing charged) |
| conversation busy (another live turn) | 200 | **SSE** `error` | `session_busy` | authority acquisition (quota released) |
| Kernel abstains | 200 | **SSE** `error` | `request_abstained` | in-stream (was pre-stream; same event) |
| provider failure **before** any output | 200 | **SSE** `error` | `backend_error` | in-stream; quota refunded |
| provider failure **after** output (truncated) | 200 | **SSE** `error` | `backend_error` | in-stream; no turn stored; unit stays spent (policy) |

For **every** row the test asserts: no unit spent unless output had been produced, no model call for pre-admission refusals, and that the very next request on the same conversation is admitted and answered (nothing left reserved or held). The frontend handles `401` (re-login), `409` (temporary-chat notice), other non-2xx (generic notice) and the SSE `error` event (interrupted badge + the server's message) — unchanged. **No client-visible contract was changed**; the only difference is that Kernel abstention/failure is now reported from inside the already-open event stream (as an `error` event, the same event the pre-stream path used).

## 7. Minimal changes to Cursor's Kernel (documented, tested)

| Change | Why | Test |
|---|---|---|
| `RawDeltaChannel` rewritten (terminal state is an attribute; no queued sentinel; no `create_task`); `KernelRun` added | the handoff lifecycle could hang and spawned an untracked task | `test_b01_raw_delta_lifecycle.py` |
| `CognitiveRequest.on_served` + `route_info` | announce the served deployment from fact, not a guess | `test_on_served_is_announced_once_…` |
| Truth-Fabric call strips the hooks | unverified draft tokens must not reach a client | `test_truth_fabric_draft_tokens_never_reach_the_raw_delta_hook` |
| `_finalize_working_memory` redacts before ingestion | raw secrets were remembered by the Kernel on both routes | `test_working_memory_ingestion_receives_the_redacted_answer_not_the_raw_one`, whole-`ORNEUR_HOME` byte scan in `test_S3_*` |
