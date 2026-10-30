# B-01 — DLP / quota / SQLite / auth / privacy regression matrix

Evidence state: **VERIFIED_ENGINEERING** (engineering-owned tests). Class legend: `DET` deterministic in-process · `LIVE+FIX` real `orca serve` process(es) + fixture provider · `LIVE+REAL` real Ollama behind the recording tap · `BROWSER` real Chromium on the approved page. "Pre-existing" suites were re-run unchanged against the candidate unless §3 says otherwise.

## 1. Invariant → proof

| Invariant (directive §10 / Wave E–G) | Proof | Class | Result |
|---|---|---|---|
| Invalid / expired / revoked credential → refusal, **zero** model dispatch | `test_auth_invalid_bearer_refused.py` (12), `test_b01_refusal_protocol.py::…invalid_bearer…`, browser J12 (provider `requests` counter unchanged) | DET, BROWSER | pass |
| Atomic quota (`_QuotaTicket`, reservation, heartbeat, replay) | `test_canonical_quota_admission.py` (12) incl. 49/50 race **on the stream route**; `test_S7_*`, `test_S8_*`, `test_duplicate_delivery_*`; cancel race (quota delta == 1 per round, 36 rounds) | DET, LIVE+FIX | pass |
| Refund before output / consume at first output / no double consumption | refusal matrix (provider failure before vs after output); `test_S7_stop_before_any_output_refunds_the_unit`; browser J3 (`usage` +1) and J10 (outage: unchanged) | DET, LIVE+FIX, BROWSER | pass |
| One plain-chat request = one answering dispatch = one unit | `test_S8_one_plain_chat_request_is_one_answering_dispatch_and_one_unit`; real Ollama: tap shows exactly one answering request, `stream:true` | LIVE+FIX, LIVE+REAL | pass |
| SQLite fencing / epochs / commit-first / authoritative transcript | `test_canonical_turn_authority.py` (12); `test_S12_worker_stalled_MID_STREAM_…` (SIGSTOP a streaming worker, successor commits, resume → `turn_superseded`, transcript = successor only, next prompt excludes the stale turn); H1–H6 | DET, LIVE+FIX (real Redis DB 12, two processes) | pass |
| Redis advisory only (outage never bypasses SQLite fencing) | H4 (Redis restart mid-conversation), H5 (Redis down → SQLite authority, honest) — pre-existing, re-run | LIVE+FIX | pass |
| No stale writer commits after losing its epoch | S12 above; `test_superseded_stream_worker_cannot_persist_after_a_successor_took_authority` | LIVE+FIX, DET | pass |
| Stop / disconnect → no phantom turn; no contamination of later context | `test_S4_S5_S6_S7_…` (next prompt contains neither the abandoned prompt nor partial reply), real Ollama `test_S4_S5_S6_real_stop_…`, browser J3/J4/J7 | LIVE+FIX, LIVE+REAL, BROWSER | pass |
| Cancellation racing the commit → one coherent state, reported as stored | `test_stop_racing_the_commit_leaves_only_coherent_states` | LIVE+FIX | pass (commit won 10 / cancel won 26 of 36; no partial) |
| DLP: every external delta passes `StreamRedactor`; emitted == persisted == later context | `test_S3_secrets_split_across_chunk_sizes_*` (sizes 1,2,3,5,8,13; OpenAI/AWS/GitHub/Bearer/PEM; wire, transcript, export, next prompt **to every later provider call incl. side calls**, and a byte scan of **every file under `ORNEUR_HOME`**); `test_canonical_route_dlp.py` (8) | LIVE+FIX, DET | pass |
| DLP streaming ≡ one-shot redaction | `test_b01_stream_dlp_equivalence.py` (43; two-way splits of every secret, char-by-char, 600 + 2 500 randomized chunkings incl. adversarial separators, PEM glued to preceding text at every split); `evidence/redactor_differential.output.txt` (36 000 chunkings: original 655 leaks / 8 675 truncated → candidate 0 / 0) | DET | pass |
| DLP: Unicode intact | `test_unicode_split_across_chunks_is_delivered_intact` (Cyrillic, CJK, emoji, 2-char chunks) | LIVE+FIX | pass |
| Truth-Fabric draft never streamed | `test_truth_fabric_draft_tokens_never_reach_the_raw_delta_hook` | DET | pass |
| Multi-turn memory: only authorized, committed, effective history | `test_context_window_bounds.py` (3); live E1/E2/E5 canary (pineapple/peach/mango on the recorded outbound request, **real Ollama**); browser J7/J8 | DET, LIVE+REAL, BROWSER | pass |
| Editing invalidates the correct tail | browser J8 (provider's next request has the edited text and not the original); live E1/E3 | BROWSER, LIVE+REAL | pass |
| Temporary chat privacy & deletion | `test_temporary_chat_privacy.py` (4), `test_temporary_chat_multiprocess.py` (5, real processes + failure injection), live F1, browser J11 | DET, LIVE+FIX, BROWSER | pass |
| Multi-tab behaviour | browser J9 (two tabs stream two conversations: no cross-talk, each transcript exactly its own), existing E4 / G-series logout across tabs | BROWSER | pass |
| Cross-user isolation | `test_session_ownership_isolation.py` (4), `test_g006_tenant_isolation.py` (41), refusal matrix (404 JSON, no model call), live D1 / browser D1 | DET, LIVE+REAL | pass |
| Documents / Truth Fabric / RAG path not broken | `test_B1c_document_session_is_still_streamed_upstream_through_the_agent_loop`; `test_serve_streaming.py` (18; agent-loop stream paths, saturation, real-socket disconnect); `test_live_grounding_truth_closure.py` | LIVE+FIX, DET | pass |
| Non-streaming `/api/chat` unchanged | `test_S11_the_non_streaming_chat_route_is_unchanged` (provider receives `stream:false`); `test_chat_kernel_direct_redacts_everywhere`; canonical suites | LIVE+FIX, DET | pass |
| Idempotent replay: no second dispatch / charge / turn | `test_duplicate_delivery_replays_once_…`; H3 (across workers) | LIVE+FIX | pass |
| Anonymous caller | `test_an_anonymous_caller_is_streamed_without_persistence_or_quota` | DET | pass |

## 2. What the first live DLP run found (and why the old assertions did not)

The pre-existing redactor tests asserted only that the **whole** secret was absent from the output — which a partial release satisfies. The first run of the new live test (secret split at several sizes) showed `[REDACTED-OPENAI_API_KEY]2`, `…TOKEN]M3`, `…TOKEN]fghijkl`, and an answer ending `end of key` (the `s` lost). Fixes, each pinned by the equivalence tests:

1. A secret whose body has an unbounded length (`sk-…{20,}`, `Bearer …`, `ghp_…`) is now held until a character that ends it arrives; before, it was redacted the instant 20 characters were present and the remainder streamed out after the marker.
2. A bare `s`/`A`/`B`/`g`/`Bear`… at a word boundary is held only until the next delta and is released at the end of the stream; before, it was dropped at `finish()` (answers ending in "s" lost a letter). A candidate must now start at a word boundary (`(?<![A-Za-z0-9_])`).
3. A trailing run of `-` is always held (previously only after whitespace): `key.-----BEGIN RSA PRIVATE KEY-----` split after the first dash was never recognised and the whole private-key body streamed out.
4. (A pitfall of the first draft of fix 1, caught by the randomized differential test before it shipped.) The open-tail pattern is anchored with `\Z`, not `$`: `$` also matches before a trailing newline, which would have held a *closed* token and then scanned it in the wrong context.
5. End of stream releases what is held exactly as the one-shot scan would (a fragment shorter than the DLP's own 20-character definition is plain text; a complete secret is still redacted); an incomplete PEM or an oversized hold still fails closed. The overflow marker is recorded and returned exactly once (it used to be appended twice, so the stored text could differ from what was shown).

DLP remains **pattern-based**: it recognises the patterns in `orca/serve/dlp.py` (OpenAI/Anthropic keys, AWS access keys, bearer tokens, GitHub tokens, PEM private keys). It does not recognise every possible secret format and PII is flagged, not redacted — unchanged and still documented as limitation B-11.

## 3. Existing tests whose content was changed (nothing weakened)

| File | Change | Reason |
|---|---|---|
| `tests/test_product_flows_fake_ollama.py::test_stream_emits_session_chunk_done_with_a_message_id` | asserts the provider's two pieces, no `replayed`, `stream` = upstream/cancellable, `done.delivery == "upstream"` | it pinned the old replay contract B-01 removes |
| same file, `test_simple_answers_are_generated_with_streaming_upstream` | `xfail(strict=True)` → passing test (answering request has `stream:true`, one dispatch) | it was the strict xfail documenting B-01 itself |
| `tests/test_serve_streaming.py` (4 stubs) | stub signature gains `**_internal_stream_hooks` | `_run_cognitive_kernel` gained two optional keyword-only hooks; assertions untouched |
| `tests/test_inference_gateway.py::test_stream_chunks_and_cooperative_cancel` | chunk partition `["pong-","ok"]` → "two chunks, joined text `pong-ok`" | trailing dash is held one delta (item 3); text identical |
| `tests/journey/test_journey_api_live.py`, `browser_journey.py` | B1 no longer accepts a `replayed` fallback (requires upstream, ≥3 chunks, spread); B1b is plain chat; B1c keeps the document-session variant | the fallback existed only to tolerate B-01 |
| `tests/journey/test_journey_concurrency_live.py` | provider default follows `reply`; per-test `_reset_provider` | streamed pieces now come from the provider, not the kernel's non-streaming call |
| `tests/fake_ollama.py`, `tests/journey/harness.py` | additive: `/__stats /__requests /__config`, `chunk_times`, abort counters; tap records client hang-ups | measurement only |

## 4. Suites run for this document (local, workstation; CI results are in `B01_FINAL_EXACT_HEAD_CI_REPORT.md`)

See `B01_FINAL_INTEGRATION_ENGINEERING_REPORT.md` §5 for the exact commands, counts and logs.
