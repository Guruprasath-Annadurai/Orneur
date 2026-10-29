# LANDMARK-01 — Blocker Register

Every item that remains after this milestone. Severity: **P0** unsafe to proceed · **P1** blocks "first public chatbot" quality · **P2** should be fixed before wide exposure · **P3** polish / known limitation.
No P0 is known to remain. "Owner" is the engineering owner proposed for the fix, not an assignment.

| ID | Sev | Title |
|---|---|---|
| B-01 | P1 | Plain-chat answers are delivered as one *labelled replay*, not token-by-token |
| B-02 | P1 | Nothing in this milestone is independently qualified |
| B-03 | CLOSED | `/api/inference/*` authority heartbeat (was: generations > 45 s failed to commit) |
| B-04 | P2 | Real-Ollama journeys are workstation-only, not in CI |
| B-05 | P2 | Physical reclamation of deleted vector/graph data is best-effort |
| B-06 | P2 | When a session has documents but no evidence plan, the Kernel's direct answer is discarded and the model is called again (≥ 2 answering calls per turn) |
| B-07 | P3 | After a severed connection the page cannot know whether the server committed the turn |
| B-08 | P3 | `/api/cognitive/execute` surfaces a kernel failure as an unhandled 500 |
| B-09 | P3 | Sign-up has no email verification; anonymous callers have IP rate limits but no per-user quota |
| B-10 | P3 | Persisted deployment records under old ids are orphaned after the family-aware id change |
| B-11 | P3 | DLP is a pattern floor |

---

## B-01 — P1 — plain-chat answers are not streamed token-by-token

* **File / function:** `orca/cognitive/kernel.py::CognitiveKernel._answer_directly` and `orca/serve/api.py::_event_stream` (`use_kernel_direct` branch).
* **Reproduction:** sign in, send any plain message in `/conversation` with real Ollama (`llama3.2:1b`). `window.__sseLog` (browser journey `B1`) shows `stream {delivery:"replayed", cancellable:false}`, exactly one `chunk {replayed:true}`, then `done`.
* **Expected:** several `chunk` events as Ollama produces tokens, `delivery:"upstream"`, Stop works.
* **Observed (pre-remediation):** the whole answer arrives in one labelled chunk after the model finishes.
* **Cursor Kernel half (this corrective wave):** optional `CognitiveRequest.on_raw_delta` + `ModelGateway.stream()` in `_answer_directly`; `RawDeltaChannel`; tests in `tests/test_kernel_streaming.py`. Evidence under `docs/orneur/landmarks/landmark-01/b01-remediation/`. **API still awaits Kernel before SSE** until Claude integrates the handoff — end-to-end B-01 remains open.
* **Owner:** Kernel owner (Cursor) + Claude for the API/UI half.
* **Claude remaining:** run Kernel as a task; drain raw deltas through `StreamRedactor`; emit `delivery:"upstream"` / `cancellable:true`. See `b01-remediation/B01_CLAUDE_API_INTEGRATION_HANDOFF.md`.
* **Acceptance test:** journey `B1` (real Ollama) asserts `delivery == "upstream"` and ≥ 2 chunks with a measurable arrival spread for a ≥ 400-character answer; `test_canonical_route_dlp.py` must still pass; quota must be consumed at the first chunk.

## B-02 — P1 — independent qualification has not happened

* **Scope:** the whole candidate. Antigravity qualified #125/#126 baselines and *failed* #127 on P0-3; neither #130 nor #131 has a qualification result, and the integration of #129 + #130 + this branch's changes is new.
* **Impact:** nothing here may be called `INDEPENDENTLY_QUALIFIED`, deployed, or merged to a protected branch.
* **Owner:** Antigravity (qualification), CTO/founder (decision).
* **Fix:** freeze the SHA in the draft PR, run Antigravity's consolidated qualification, including the earlier vulnerabilities (stale-writer, JSONL phantom turns, prompt contamination, DLP chunk split, reservation theft, replay).
* **Acceptance:** an Antigravity report naming the exact SHA.

## B-03 — CLOSED in this milestone — `/api/inference/*` authority heartbeat

* Was: `orca/serve/inference.py::_persist` renewed authority once, immediately before the commit, on a 45 s TTL — a healthy generation that outlived the TTL lost the right to commit (`stale_worker`).
* Fix: `_authority_heartbeat` keeps the Redis lease and SQLite authority alive for the duration of `complete`, `stream_complete` and `stream_via_gateway`; renewal only succeeds for the same fence + epoch, so a superseded worker still fails.
* Evidence: `tests/test_landmark_integration_fixes.py::test_a_generation_longer_than_the_authority_ttl_still_commits_on_the_inference_routes` (**fails with `stale_worker` when the heartbeat is disabled**) and `…::test_a_superseded_inference_worker_still_cannot_commit_despite_the_heartbeat`.

## B-04 — P2 — real-Ollama journeys are not in CI

* **Where:** `tests/journey/test_journey_api_live.py`, `test_journey_browser.py` need a real Ollama model; CI has none. The fixture-provider journeys (`test_journey_browser_fixture.py`, `test_journey_concurrency_live.py`) **are** in CI as job *Journeys (real servers + real Redis + real Chromium, fixture provider)*.
* **Impact:** the real-model evidence in the handoff was produced on the workstation (Windows 11 / WSL2 / `llama3.2:1b`) and must be re-run by Antigravity on the frozen SHA.
* **Owner:** Claude / CTO (a self-hosted runner or a pinned tiny model in CI).
* **Acceptance:** a CI job that pulls a pinned small model and runs the two real-Ollama modules.

## B-05 — P2 — deleted data: physical reclamation is best-effort

* SQLite: `secure_delete=ON` + WAL truncate (verified at byte level). JSONL: unlinked (not shredded). Chroma / knowledge graph: logical deletion verified; physical reclamation may be `DEFERRED` per `docs/orneur/status/P1_DELETION_ASSURANCE_DESIGN.md`.
* **Owner:** deletion-assurance workstream. **Acceptance:** byte-level scan of the whole `ORNEUR_HOME` after a temp-chat closure finds no content (the multi-process test already does this for the files it creates; extend to the vector store).

## B-06 — P2 — discarded Kernel answer when a session has documents

* **File / function:** `orca/serve/api.py` (`use_kernel_direct = cognitive_result.output is not None and (sess.doc_store.count() == 0 or cognitive_result.evidence_state is not None)`).
* **Observed (measured with the fixture provider):** with a document loaded the provider receives the Kernel's answering call, then the Deep-RAG call, then the streamed AgentLoop call (plus knowledge-graph extraction). The Kernel's output is dropped. One quota unit is charged, but compute is multiplied.
* **Minimal fix:** pass "documents present" into the Kernel request so it skips `_answer_directly`. **Acceptance:** one provider dispatch per turn for a document session.

## B-07 — P3 — outcome unknown after a severed connection

* **Where:** `conversation.html` stream error handling (`markMessageInterrupted`).
* **Observed:** when the connection vanishes mid-stream the page shows "Response interrupted"; whether the server went on to commit the turn depends on whether it noticed the disconnect first. The browser journey (`S4`) accepts either outcome and asserts the invariants that matter — no partial assistant message is ever committed, and the conversation is immediately usable — but the page does not poll to tell the user which happened. A reload shows the authoritative transcript.
* **Fix:** on an interrupted stream, re-read `/messages` once and reconcile the DOM (or show "this reply was saved / not saved"). **Acceptance:** extend `S4` to assert the badge text matches the server state.

## B-08 — P3 — `/api/cognitive/execute`

* Internal/experimental route; a kernel failure propagates as an unhandled exception (500). Quota is refunded (verified). **Fix:** wrap with `public_error`.

## B-09 — P3 — sign-up / anonymous

* No email verification; per-IP sign-up limit (5/h) is intentionally left on. Anonymous callers are limited by IP only. Not a regression; out of this milestone.

## B-10 — P3 — orphaned deployment records

* `ModelDeployment.save()` persisted records under the old tag-only id; after the family-aware id change they are not read again. **Fix:** a one-shot cleanup of `…/deployments/ollama-*` records whose id is not in the current set.

## B-11 — P3 — DLP is a floor

* Pattern based (OpenAI/Anthropic/AWS/GitHub/Bearer/PEM). Unknown secret shapes pass. Acknowledged in #127/#130 handoffs; unchanged.

---

## Closed during this milestone (kept for the audit trail)

Authentication anonymous-fallback · racy quota on canonical and secondary routes · authority acquired after generation · stream kernel-direct DLP bypass · raw secrets in long-term memory / live window · reads stranding turn authority · authority row seeded at revision 0 · temporary-chat crash-mid-closure, racing commit, lock race, byte-level residue · single-tag multi-tier deployment collision · stream duplicate delivery · store-down handling · flush of non-ORNEUR Redis data in tests. Details: `LANDMARK_01_INTEGRATION_PROVENANCE.md` §5.
