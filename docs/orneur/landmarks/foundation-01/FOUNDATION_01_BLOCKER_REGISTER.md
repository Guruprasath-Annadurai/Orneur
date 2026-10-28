# FOUNDATION_01_BLOCKER_REGISTER

Refreshed for functional tip `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8` on `cursor/foundation-landmark-01-backend-closure-1cdf`.  
Audit after evidence freeze: use GitHub PR #132 HEAD.

| ID | Severity | Status | File / function | Notes | Acceptance |
|---|---|---|---|---|---|
| B01 | P0 | **Resolved** | `get_current_user_optional` | Invalid bearer → 401 | `test_foundation01_auth_optional.py` |
| B02 | P0 | **Resolved** | Transcript SoT | SQLite fencing (#130); #131 rejected | storage decision + p0_transcript |
| B03 | P0 | **Resolved** | chat/stream quota race | `admit_serving` | `test_foundation01_quota_admission.py` |
| B04 | P0 | **Resolved** | Route admission divergence | shared `admission.py` | `test_a_serving_authorization.py` |
| B05 | P1 | **Resolved** | Multi-turn missing on fencing | #126 merged | conversation_context / ollama_deployment_id |
| B06 | P1 | **Resolved (unit)** | Temp-chat lock unlink | flock then unlink | `test_temporary_chat_privacy.py`; two-process soak still env |
| B07 | P1 | **Resolved** | `/api/cognitive/execute` | on `admit_serving` | serving_authorization AST |
| B08 | P1 | **Open — env** | Two-worker Redis soak | No Redis in Cursor closeout VM | DISTRIBUTED report; Antigravity |
| B09 | P1 | **Open — env** | Live Ollama `llama3.2:1b` | Ollama unavailable here | REAL_OLLAMA report; Antigravity |
| B10 | P2 | **Open — Claude** | Frontend integration | Cursor does not modify FE branch | BACKEND_FRONTEND_CONTRACT |
| B11 | P0 | **Open** | Independent qualification | Engineering ≠ G13 | Antigravity at frozen HEAD |
| B12 | P1 | **Documented risk** | Persist best-effort | Delivered text without fail-closed HTTP if SQLite commit fails; reload messages | Contract persistence § |
| B13 | P1 | **Resolved (CI)** | Exact-head Deterministic red | Obsolete G006/S2 vs 401 + HTTP JSON stream gates | fix `2b6b6de`; CI 40733516543 / 40733526194 |
| G-020 | P1 | **Open known** | Agent shell/file tools | Documented xfail; not FOUNDATION-01 CI scope | `test_g006` 11a/11b xfail |

## Closed by consolidation (do not re-implement)

- PR #125/#127 DLP, reservation ownership, catalog entitlement.
- PR #130 SQLite fencing SoT.
- PR #126 conversation context + colon-safe Ollama IDs.
- Explorer BB-AUTH/ADM/QUOTA/OWN/PRIV/DLP items closed on this tip.

## Still open for Antigravity / Claude

- Live Ollama + real Redis two-worker / outage / crash-restart.
- Browser contract implementation (Claude).
- G13 independent qualification.
- G-020 tool confinement (separate track).
