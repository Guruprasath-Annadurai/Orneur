# B-01 — Real Ollama streaming evidence

Evidence state: **VERIFIED_ENGINEERING** (workstation run; not independently qualified). Class: `LIVE+REAL` / `BROWSER` against the workstation's Ollama at `http://localhost:11434`.

**Model honesty.** The model is the third-party **`llama3.2:1b`** weights served by Ollama (lifecycle `EXPERIMENTAL`, disclosure "Experimental model -- not qualified."). It is not GENESIS, NOVUS or AETERNUM and nothing here claims it is. The product's own identity record for the run (below) says `served_model: llama3.2:1b`, `substituted: true, reason kernel_routing`, `data_left_infrastructure: false`. The literal tag was selected with `ORNEUR_JOURNEY_MODEL=llama3.2:1b`; the default `orneur-journey` is a local alias of the same weights (`ollama cp`), and results for both are recorded below.

All provider-side numbers come from the recording pass-through **tap** (`tests/journey/harness.py::OllamaTap`), which forwards bytes unchanged and records what ORNEUR sent and when ORNEUR hung up. Nothing is inferred and no timestamp is invented; raw JSON is in `evidence/`.

## S10 — progressive tokens from the real model (`test_S10_real_model_tokens_reach_the_client_progressively`)

Literal `llama3.2:1b`, long prompt ("at least 400 words about the history of the lighthouse"), `evidence/real_ollama_llama3.2_1b_progressive_streaming.json`:

| Measure | Value |
|---|---|
| SSE `chunk` events | **916** |
| distinct arrival instants (1 ms) | 865 |
| first chunk / last chunk / `done` | 0.838 s / 5.338 s / 5.723 s |
| answer length | 4 651 characters |
| `stream` event | `{"delivery":"upstream","cancellable":true}`; no `replayed` anywhere |
| answering dispatches seen by the tap | **1**, with `stream: true` |
| saved transcript | exactly the streamed text (once) |
| identity | `model` event == `done.model_identity` (`served_model: llama3.2:1b`) |

The same test on the alias gave 804 chunks over 0.779 s → 4.705 s (earlier run; file overwritten by the literal run).

## S4 — Stop hangs up on the real model (`test_S4_S5_S6_real_stop_hangs_up_on_the_model_and_leaves_no_phantom_turn`)

`evidence/real_ollama_llama3.2_1b_stop_cancellation.json`: the client left after 6 chunks; the tap recorded ORNEUR closing its connection **0.05 s later**; 926 lines had been relayed at that instant, 929 two seconds later (three already in flight) and none after; `open_streams == 0`; the transcript was empty; the next turn on the same conversation was persisted; the next prompt's model context contained nothing from the abandoned prompt or partial reply. (Whether Ollama then frees its own compute is Ollama's behaviour once its HTTP connection closes; what is proven here is that ORNEUR closes it, promptly.)

## Browser (real Chromium → real ORNEUR → real Ollama)

`tests/journey/test_b01_browser_streaming.py` real variant (10 steps + the Stop hang-up check) — long prompt rendered in ≥3 distinct DOM states spread over ≥0.8 s; Stop offered mid-stream, click → interrupted badge + "model connection was closed … not saved"; tap hang-up counted; no phantom turn; next prompt works; full response saved exactly once and equal to the DOM; refresh recovers; history probe; inline edit; temporary chat; revoked token. All pass.

## Full journey suites on the literal tag

`ORNEUR_JOURNEY_MODEL=llama3.2:1b pytest tests/journey -p no:cacheprovider` → **106 passed** (final code, 5 m 13 s; `evidence/journeys_all_literal_llama3.2-1b_final.txt`). Class split of those 106, by each file's own docstring (counts from `pytest --collect-only`): **real Ollama = 52** (`test_journey_api_live.py` 20, `test_journey_browser.py` 19, `test_b01_real_ollama_live.py` 2, `test_b01_browser_streaming.py` real variant 11); **fixture provider = 54** (`test_journey_browser_fixture.py` 10, `test_journey_concurrency_live.py` 11, `test_b01_streaming_live.py` 17, `test_b01_cancel_race_live.py` 1, `test_b01_browser_streaming.py` fixture variant 15). Do not read the 106 as "all real model".

Timing numbers are single-workstation measurements (WSL2, one GPU/CPU box) and are **not benchmarks**.
