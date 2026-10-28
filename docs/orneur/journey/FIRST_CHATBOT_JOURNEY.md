# ORNEUR first real chatbot journey -- harness, status and frontend integration report

Base: Redis-qualified `e8e6ab105ef94ddc5ed729c54e2ec0d130951334`. Branch `claude/chatbot-journey-2026-10-28`.
Cursor PR #124 (`cursor/inference-session-isolation-ae9d`, head `78bfb3c`) was read, not merged: it adds
`orca/serve/inference.py` etc. and does **not** touch any blocker below (J-1, J-2 are in files #124 leaves alone).
No inference, Redis or container runtime was added here; the harness only *drives* what exists.

## 1. Canonical entry points (verified by running them)

| Thing | Where |
|---|---|
| Server | `orca serve` -> `orca/cli.py:serve` -> uvicorn over `orca.serve.api.create_app()` (Dockerfile `CMD`) |
| Approved chatbot UI | `GET /conversation` -> `orca/serve/web/conversation.html` (founder-approved shell, both themes) |
| Legacy UI (untouched) | `GET /app` -> `index.html`; `GET /` landing; `GET /trust` |
| What the approved UI calls | `POST /api/stream` (SSE) for sending -- **not** `/api/chat`; `/api/auth/{login,signup,me}`, `/api/sessions`, `/api/session/{id}/messages`, `.../edits`, `/api/sessions/temporary`, `.../temporary/close` |
| Canonical JSON chat API | `POST /api/chat` (kept in the journey; returns `context_freshness` from the Redis work) |

Both chat routes resolve a model through the cognitive kernel then `ModelGateway` -> Ollama.

## 2. Evidence classes (what each test actually proves)

| Class | Meaning | Where |
|---|---|---|
| **LIVE_API** | real `orca serve` subprocess + real Ollama + (E3) real Redis, driven over HTTP | `tests/journey/test_journey_api_live.py` |
| **BROWSER** | real Chromium driving `/conversation` against that same server/Ollama; screenshots in both themes | `tests/journey/test_journey_browser.py` + `browser_journey.py` |
| **MOCKED** (pre-existing, *not* journey evidence) | in-process `TestClient` + `FakeOllama`: `tests/test_b_conversations.py`, `test_b11_*`, `test_b13_temporary_chat.py`, `test_multiworker_*`, `test_redis_*` (the last two use real Redis but fake inference) | rest of `tests/` |
| **NODE-DOM** (pre-existing) | `node --test tests/frontend/*.mjs`, page logic without a browser or a server (CI job "Conversation Shell Frontend") | `tests/frontend/` |

Before this branch **no test in the repo exercised browser -> server -> Ollama**; `test_conversation_shell.py` says so itself.
The tap (`OllamaTap`) sits between the server and the real Ollama, forwards everything, and records each model request, so context
assertions are on *what the model was sent*, not on what a 1B model happens to answer. Side calls (knowledge-graph extraction quotes
earlier turns) are excluded by `answer_contexts()` -- an earlier version of these tests passed for exactly that wrong reason.

## 3. Journey status (latest full run: 32 tests, 20 passed, 12 failed -- the failures are the findings)

A step is **PASSED only if its LIVE_API and BROWSER halves both pass.** Nothing below is declared passed on one half.

| Step | LIVE_API | BROWSER | Verdict |
|---|---|---|---|
| A login | pass | pass (wrong password refused, login, shell usable) | **PASSED** |
| B new conversation, real Ollama, streaming | pass (incremental SSE, tap proves real call) | pass (answer grows 294->331->371->428->466 chars) | **PASSED** -- *but see B3/J-1: no memory of earlier turns* |
| B3 second turn sees first turn | **FAIL x4** (3 phrasings on /api/stream, 1 on /api/chat) | -- | **FAILED (J-1)** |
| C persistence + reload | pass (+ full server restart) | pass after reload; **C0 FAIL**: sidebar not updated without reload | **PARTIAL (FE-3)** |
| D isolation | pass (read/list/search/stream/edit) | pass (second user sees nothing) | **PASSED** |
| E edited-message context | **FAIL** (E1, E2, E3 two servers + Redis) | edit via reopen passes; **E0 FAIL** same-turn edit; context **FAIL** | **FAILED (J-1, FE-2)** |
| F temporary chat | pass | pass (hidden, close deletes, 409 afterwards) | **PASSED** |
| G logout + revocation | pass (API logout revokes, other device survives, logout-all) | **FAIL**: UI "Sign out" never calls the server | **FAILED (FE-1)** |
| Both themes | -- | light screenshots all steps; dark shell renders (T1) | partial |
| Colon-tag model (`llama3.2:1b`) | **FAIL** | -- | **FAILED (J-2)** |

## 4. Integration blockers, prioritised

**P0**
- **J-1 -- the model never receives conversation history (on any route).** `orca/cognitive/kernel.py:483`
  `direct_inference_binding()` builds `messages=[{"role":"user","content": objective}]`; the stream route
  (`api.py` ~2279) and `/api/chat` both go through it for every message observed (`substitution_reason=kernel_routing`).
  Consequences: no multi-turn memory at all, and the Redis/edit consistency work that is qualified for `sess.agent` history is
  not what feeds the model -- so "edited message reaches the model" cannot currently be true. Verified with the tap on 3 phrasings
  (`test_B3...`), `/api/chat` (`test_B4`), edit on one server and next turn on another with real Redis (`test_E3`), and the browser
  (`test_E3_browser...`). Owner: live inference (Cursor) -- *not* fixed here to avoid a competing path.
- **FE-1 -- UI Sign out does not revoke the server session.** `conversation.html:3715` `doLogout()` only clears local state;
  `POST /api/auth/logout` is never called, so the token stays valid after the user believes they signed out
  (browser test: `/api/auth/me` and `/api/sessions` return 200 with the old token). Server side is correct (LIVE_API G1/G2 pass).
  Fix is one fetch in `_clearAuthStateAndShowSignIn`'s logout path; no visual change.

**P1**
- **J-2 -- stock Ollama tags crash the stream.** `deployment_id = f"ollama-{model}"` (`orca/gateway/wiring.py:199`) hits
  `validate_id` which rejects `:`; `/api/stream` ends after the `model` event with no `chunk`/`done` and no error event
  (the UI then shows its generic "could not be completed"). The journey serves a colon-free alias
  (`ollama cp llama3.2:1b orneur-journey`, local copy, no download) and `test_blocker_colon_tags_stream` stays red until fixed.
- **FE-2 -- same-turn edit stays disabled.** The server already returns `user_message_id` on `done`
  (`api.py:2453`); the page ignores it (`conversation.html:2552` comment asks for exactly this). Edit works only after reopening.
- **FE-3 -- sidebar stale after the first turn.** `loadSessions()` is called on the `session` event, before the turn is persisted;
  the list says "No conversations yet" until a reload.

**P2 / observations**
- Conversations are titled `(untitled conversation)` -- no auto-title in the live path.
- Starting a temporary chat resets the model selection to "Choose model" (an unsent message is left in the composer).
- Server log attributes authenticated stream failures to `user=anonymous`.
- Signup issues a working token with no email verification (by current design; flagging for the launch checklist).
- Streaming `/api/stream` `done` has no `context_freshness` (only `/api/chat` does).

## 5. Compatibility
- **Redis (e8e6ab1)**: included unchanged; E3 runs two real servers sharing one home and Redis db 13 and asserts
  `context_freshness == "confirmed"` -- that part passes; the context assertion fails on J-1.
- **PR #124**: independent; no files overlap with this branch (`tests/journey/**`, `docs/orneur/journey/**`, one marker line in `pyproject.toml`).
- **Frozen UI/UX**: `conversation.html` and brand assets untouched.

## 6. Running it
Capabilities needed: Ollama with an alias model, Redis on `localhost:6379` (db 13/14/15), Chromium via Playwright in a tools venv.
```bash
ollama cp llama3.2:1b orneur-journey                      # local alias, no download
docker run -d --rm --name orneur-redis-test -p 6379:6379 redis:7-alpine
uv venv /home/pc/projects/.journey-tools/.venv && uv pip install --python /home/pc/projects/.journey-tools/.venv/bin/python playwright==1.49.1
/home/pc/projects/.journey-tools/.venv/bin/python -m playwright install chromium
# no sudo? extract libnss3 libnspr4 libasound2t64 (apt-get download + dpkg -x) into .journey-tools/libs
/home/pc/projects/Orneur/.venv/bin/python -m pytest tests/journey -m journey_live -p no:cacheprovider -v
```
A missing capability FAILS with `capability missing: ...` (never skips). The tests are opt-in (`-m journey_live`, `ORNEUR_JOURNEY=1`, or
naming `tests/journey`), and carry `live_ollama_smoke` so `scripts/ci/run_deterministic_tests.sh` excludes them. Screenshots go to
`$ORNEUR_JOURNEY_ARTIFACTS` (default `/tmp/orneur-journey-artifacts`).


---

## 7. Frontend remediation (branch `claude/frontend-journey-remediation-2026-10-28`)

Scope: `orca/serve/web/conversation.html` only (behaviour; no markup, copy-of-record, layout, logo or theme change) plus tests.
Untouched by design: `orca/cognitive/kernel.py`, gateway routing, the Redis session store, Cursor's inference PR, Docker isolation.

| Finding | Fix | Evidence |
|---|---|---|
| **FE-1 secure logout** | `doLogout()` issues `POST /api/auth/logout` with the live token *before* discarding it, clears all local state synchronously (epochs bumped, stream aborted, drafts/search/model cleared, localStorage token removed), then reports the server's answer: 200 "You have been signed out." / 401 "This session had already ended." / network or 5xx (retried once) "...did not confirm that this session was ended. It may remain valid until it expires." No "signed out everywhere" wording exists; logout-all is not offered. A late outcome never overwrites a newer sign-in. A `storage` listener signs this tab out when another tab removes the shared token. | node `test_logout_revocation.mjs` (10); browser G1 (old token -> 401 on `/api/auth/me`, `/api/sessions`, `/api/stream` by plain HTTP *and* in-page; another session of the same user stays 200) and G2 (route-aborted logout: honest message; the server still accepts the token, as the message says); API G1/G2 |
| **FE-2 same-turn edit** | `appendUserMessage()` exposes `bindServerMessageId(id)`; the `done` handler calls it with `ev.user_message_id` only. Never overwrites a known id; ignores non-strings; no content/position/last-message inference. | node `test_b11_inline_edit.mjs` (+3); browser E0 (immediate edit), E1 (after reopen), **E4 (two tabs: each edits its own message; server transcript `['alpha edited','beta edited']`)** |
| **FE-3 sidebar** | The `session` event no longer refreshes (it raced persistence). The `done` event refreshes once `user_message_id` confirms persistence, skipped for temporary chats. | browser C0, C2 (rows 3 -> 4 without reload), F1 (temporary chat adds no row); node `test_view_ownership_epoch.mjs` updated to the new call site |

Two pre-existing node assertions pinned the old sources (`function doLogout() {` and "session event calls loadSessions()"); they were updated
deliberately, with a comment naming this change, rather than loosened.

Residual limits: if the server is unreachable at sign-out the token is not revoked (disclosed to the user; the page cannot retry after the
token is discarded); `/api/stream` still lacks `context_freshness`; J-1 and J-2 remain red by instruction.
