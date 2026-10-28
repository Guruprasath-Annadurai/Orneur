# Antigravity handoff — PR #125 P0 security closure

**Branch:** `cursor/inference-p0-security-closure-c12b`  
**Base:** `cursor/inference-qualification-p0-ae9d` @ `9298b157fe22c95c897d7afbcc9f2e21a99d256e` (PR #125 head; do not treat green CI alone as qualification)  
**Failed qualification SHA (prior):** `db15161b2ba487ff57ccedf3130d7f56bcea2fa0`

## Closure claims (re-verify; do not inherit)

| ID | Defect | Closure mechanism | Primary evidence |
| --- | --- | --- | --- |
| P0-1 | SSE DLP PEM / split-secret leakage | `StreamRedactor` state machine (`NORMAL` / `PEM_HEADER` / `PEM_BODY` / fail / cancel); hold incomplete headers & bodies; never flush hold on cancel; fail-closed on incomplete PEM at finish | `tests/test_p0_stream_dlp_closure.py`, `tests/test_critical_sse_dlp.py` |
| P0-2 | Reservation replay / cross-user theft | Reservations bind `user_id` + fingerprint; `consumed` / `in_progress` never re-admit; optional idempotent replay of stored response without provider dispatch | `tests/test_p0_reservation_ownership.py`, `tests/test_serving_policy_adversarial.py`, `tests/test_redis_integration_gap.py` (cross-process quota) |
| P0-3 | Transcript write ignoring Redis CAS | `claim_turn_commit` (lease+revision) → `conversations.commit_turn` (SQLite SoT + single JSONL export of both messages) → Redis stamp; stale fence writes nothing | `tests/test_p0_transcript_commit.py` |
| P0-4 | Regressions | Existing isolation / catalog / atomic admit / native refusal / Redis fencing / temp-chat paths preserved | `tests/test_inference_gateway.py`, `tests/test_variant_misrepresentation.py`, `tests/test_inference_http.py` |
| P0-5 | Frontend journey | **OPEN** — see `P0_INFERENCE_API_STREAM_COMPATIBILITY.md`. `/api/stream` now uses `StreamRedactor` for upstream chunks, but quota admission + turn claim protocol are still inference-primary. J-1 / J-2 remain open. | Compatibility doc |

## Failing-before (at `9298b15`) vs passing-after (this branch)

Reproducers (run against checked-out SHA):

1. **PEM incomplete header:** char-by-char / almost-complete `-----BEGIN … KEY----` then body → prior redactor emitted header/body; now holds and redacts.
2. **Consumed replay at 50/50:** `reserve`→`consume` then `reserve` same `request_id` returned `ok=True`; now `ok=False` / replay-only; cross-user raises `reservation_forbidden`.
3. **Stale fence persist:** append JSONL then Redis CAS refuse left transcript dirty; now `_persist` raises `stale_worker` with empty transcript; new fence commits atomically.

## Environment notes for this run

- Real Redis: `redis://localhost:6379/14` — ping OK; lease/CAS/multi-process tests executed.
- Live Ollama: **not available** in this agent environment (no daemon on `:11434`). Provider paths exercised via synthetic fixture transports + gateway fixture server.
- No protected merges, staging/production deploy, paid infra, or native training performed.

## Remaining security limits (disclose)

- Pattern DLP is floor-not-ceiling (unrecognized secret shapes can miss).
- `/api/stream` quota still check-then-increment (not reservation-fenced).
- `/api/stream` transcript path still `_persist_turn` append pairs (not `claim_turn_commit`).
- When Redis is down, turn fencing falls back to process lock + SQLite revision; cross-process stale writers are not fenced without Redis.
- Idempotent consumed replay requires a stored response JSON; consumed-without-response rejects redispatch but cannot reconstruct the answer.

## Independent qualification checklist

1. Check out this branch tip SHA (record exact commit).
2. Run P0 test modules above against real Redis.
3. Re-run Antigravity PEM split / reservation theft / lease-expiry transcript attacks against `/api/inference/*`.
4. Separately attack `/api/stream` for J-1 / J-2; do not close journeys on inference-only green.
5. Confirm CI on the exact tip SHA.
