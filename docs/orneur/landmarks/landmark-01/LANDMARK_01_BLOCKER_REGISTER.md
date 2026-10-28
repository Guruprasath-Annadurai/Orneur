# LANDMARK-01 — Blocker Register

Every item that remains after this milestone. Severity: **P0** unsafe to proceed · **P1** blocks "first public chatbot" quality · **P2** should be fixed before wide exposure · **P3** polish / known limitation.
No P0 is known to remain. "Owner" is the engineering owner proposed for the fix, not an assignment.

| ID | Sev | Title |
|---|---|---|
| B-01 | P1 | Plain-chat answers are delivered as one *labelled replay*, not token-by-token |
| B-02 | P1 | Nothing in this milestone is independently qualified |
| B-03 | P2 | `/api/inference/*` routes have no authority heartbeat (generations > 45 s fail to commit) |
| B-04 | P2 | Real-Ollama journeys are workstation-only, not in CI |
| B-05 | P2 | Physical reclamation of deleted vector/graph data is best-effort |
| B-06 | P2 | When a session has documents but no evidence plan, the Kernel's direct answer is discarded and the model is called a second time |
| B-07 | P2 | In-process session cache can be stale across workers while Redis is down |
| B-08 | P3 | `/api/cognitive/execute` surfaces a kernel failure as an unhandled 500 |
| B-09 | P3 | Sign-up has no email verification; anonymous callers have IP rate limits but no per-user quota |
| B-10 | P3 | Persisted deployment records under old ids are orphaned after the family-aware id change |
| B-11 | P3 | DLP is a pattern floor |

---

## B-01 — P1 — plain-chat answers are not streamed token-by-token

* **File / function:** `orca/cognitive/kernel.py::CognitiveKernel._answer_directly` (calls non-streaming `ModelGateway.generate`) and `orca/serve/api.py::_event_stream` (`use_kernel_direct` branch).
* **Reproduction:** sign in, send any plain message in `/conversation` with real Ollama (`llama3.2:1b`). `window.__sseLog` (browser journey `B1`) shows `stream {delivery:"replayed", cancellable:false}`, exactly one `chunk {replayed:true}`, then `done`.
* **Expected:** several `chunk` events as Ollama produces tokens, `delivery:"upstream"`, Stop works.
* **Observed:** the whole answer arrives in one labelled chunk after the model finishes. The UI is honest about it (no typing animation, no Stop control for a replay — verified), but the experience is not that of a streaming chatbot.
* **What *is* verified:** when the AgentLoop/document path runs, chunks are forwarded as the provider emits them (fixture provider: 6 chunks 0.5 s apart ⇒ ≥ 1.2 s wire spread **and** ≥ 4 distinct DOM states measured by an in-page `MutationObserver`; Stop; refresh mid-stream; severed connection).
* **Impact:** perceived latency on every plain turn (≈ 1–3 s for a 1B model); no mid-answer cancellation for the default path.
* **Owner:** Kernel owner (Cursor) + Claude for the API/UI half.
* **Minimal fix:** add an optional `on_chunk` hook to `CognitiveRequest`; `_answer_directly` iterates `gateway.stream(...)` when it is set, forwarding each delta and still returning the complete output. `_stream_dispatch` runs the Kernel as a task, forwards queued deltas through the existing `StreamRedactor`, and emits the `model` identity event as soon as the tier is known. Gate it to ollama + no-document sessions (otherwise the Kernel's answer is discarded — see B-06).
* **Acceptance test:** journey `B1` (real Ollama) asserts `delivery == "upstream"` and ≥ 2 chunks with a measurable arrival spread for a ≥ 400-character answer; `test_canonical_route_dlp.py` must still pass; quota must be consumed at the first chunk.

## B-02 — P1 — independent qualification has not happened

* **Scope:** the whole candidate. Antigravity qualified #125/#126 baselines and *failed* #127 on P0-3; neither #130 nor #131 has a qualification result, and the integration of #129 + #130 + this branch's changes is new.
* **Impact:** nothing here may be called `INDEPENDENTLY_QUALIFIED`, deployed, or merged to a protected branch.
* **Owner:** Antigravity (qualification), CTO/founder (decision).
* **Fix:** freeze the SHA in the draft PR, run Antigravity's consolidated qualification, including the earlier vulnerabilities (stale-writer, JSONL phantom turns, prompt contamination, DLP chunk split, reservation theft, replay).
* **Acceptance:** an Antigravity report naming the exact SHA.

## B-03 — P2 — `/api/inference/*` has no authority heartbeat

* **File / function:** `orca/serve/inference.py::_persist` (one best-effort `renew_authority` immediately before the commit) and `_acquire_turn` (45 s TTL).
* **Reproduction:** a generation on `/api/inference/complete|stream` that takes longer than 45 s: `commit_turn` returns `authority_expired` ⇒ `InferenceError("stale_worker")`; the answer is lost.
* **Expected:** same behaviour as the canonical routes (`_TurnAuthority` heartbeat).
* **Impact:** only long generations on the secondary inference API. The browser does not use these routes.
* **Owner:** Cursor (PR #125/#127 lineage).
* **Minimal fix:** share `_TurnAuthority` (or a thread-based heartbeat) with `inference.py`.
* **Acceptance test:** like `test_canonical_turn_authority.py` with `ORNEUR_TURN_AUTHORITY_TTL_S=2` and a 5 s fixture generation: the turn commits.

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
* **Observed:** with documents loaded and no evidence state, the Kernel has already called the model, its output is dropped, and the AgentLoop calls the model again. One quota unit is charged, but the compute is doubled.
* **Minimal fix:** pass "documents present" into the Kernel request so it skips `_answer_directly`. **Acceptance:** one provider dispatch per turn for a document session.

## B-07 — P2 — stale in-process session cache while Redis is down

* `_sessions` (live agent window) is revalidated against Redis revisions; with Redis unreachable, a user session is rebuilt from the authoritative transcript (`context_freshness: rebuilt_authoritative`) and **model prompts are built from SQLite**, so the answer is not stale — but the AgentLoop's own window on another worker can lag until its next rebuild. Verified honest by `test_H5`. **Owner:** Cursor/Claude. **Fix:** drop the cache entry when `lease_state` is `None`.

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
