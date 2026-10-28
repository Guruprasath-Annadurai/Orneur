# P0-5 — `/api/stream` vs `/api/inference/*` compatibility assessment

**Status:** open for journey qualification (J-1 / J-2)  
**Assessed against:** corrective branch closing PR #125 P0-1..P0-3  
**Canonical frontend route:** `POST /api/stream`  
**Inference programme routes:** `POST /api/inference/complete`, `POST /api/inference/stream`, `GET /api/inference/history`

## Verdict

The chatbot journey must **not** be marked complete based on `/api/inference/*` alone.
The approved ORNEUR frontend speaks `/api/stream`. Security closures proven only on the
inference programme are necessary but not sufficient for J-1 / J-2.

## What now aligns

| Control | `/api/inference/*` | `/api/stream` |
| --- | --- | --- |
| Streaming DLP (stateful, PEM-aware) | Yes (`StreamRedactor`) | Yes (wired into upstream chunk loop; disconnect cancels hold) |
| Final persisted text DLP | Yes (`scan_output` in `_persist`) | Partial (frontier path scans; Ollama path persists redactor `safe_text`) |
| Same-user session isolation | Yes (`claim_session`) | Yes (existing session ownership) |
| Server catalog / entitlement | Yes (`authorize_model`) | Uses `model_access_allowed` on `model_variant` (different gate) |
| Atomic quota reservation | Yes (`reserve_quota` + fingerprint) | Still check-then-`increment_usage` (not reservation-based) |
| Durable SQLite fencing + SoT commit | Yes (`acquire_authority` + `commit_turn`) | Yes (`_persist_turn` → same acquire/commit/release; JSONL derived post-commit) |
| Advisory Redis lease / revision claim | Yes (`acquire_session_lease` + `claim_turn_commit`) | Lease not required on chat/stream path; SQLite fence is authoritative |
| Temporary-chat / retention / edits | Preserved via shared conversations + settings | Same modules |

## Remaining journey gaps (J-1 / J-2 stay open)

1. **Quota admission model differs.** `/api/stream` still uses `check_quota` + post-success `increment_usage`. A user at 50/50 can race concurrent `/api/stream` requests the way Antigravity originally demonstrated on the pre-reservation path. Inference reservations do not protect the frontend route.
2. **Transcript path now shares SQLite SoT** with inference (`_persist_turn` uses fencing). Journey qualification should still re-attack `/api/stream` end-to-end; do not inherit inference-only evidence.
3. **Model entitlement input differs.** Inference uses the server catalog keyed by model name. `/api/stream` still gates on client `model_variant` via `model_access_allowed`.
4. **Response shape / session bootstrap differ.** Frontend SSE event types (`session`, `model`, `thinking`, `chunk`, `done`, tools, citations, explainability) are not produced by `/api/inference/stream`.
5. **No end-to-end qualification of the frozen frontend against this corrective SHA.** J-1 / J-2 require live verification on `/api/stream` with the approved client, not synthetic inference transports.

## Recommendation for Antigravity

Qualify P0-1..P0-3 on `/api/inference/*` first (this branch). Keep J-1 / J-2 **FAILED / OPEN** until the same controls are demonstrated on `/api/stream` with the canonical frontend, or until `/api/stream` is explicitly cut over onto the inference admission + commit protocol without breaking the approved SSE contract.
