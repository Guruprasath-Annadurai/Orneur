# BACKEND_SECURITY_QUALIFICATION_MATRIX

Engineering evidence only. **G13 Independent qualification = Antigravity, not this matrix.**

Tip under test: `6d53c1ed03ca2d827083a7e7a91ac38ed9afb88c`

| Control | Gate | Engineering status | Evidence |
|---|---|---|---|
| Invalid/revoked credentials refused | G1 | PASS (unit) | `tests/test_foundation01_auth_optional.py`, `tests/test_b_logout_revocation.py` |
| User/session isolation | G2 | PASS (unit) | auth optional cross-user messages; session ownership suites |
| Atomic quota + replay | G3 | PASS (unit) | `tests/test_foundation01_quota_admission.py`, `tests/test_p0_reservation_ownership.py` |
| Streaming DLP | G4 | PASS (unit; ancestor) | `tests/test_p0_stream_dlp_closure.py`, `tests/test_critical_sse_dlp.py` |
| Transcript authority / fencing | G5 | PASS (unit) | `tests/test_p0_transcript_integrity.py`, `tests/test_p0_transcript_commit.py` |
| Multi-turn + edit context | G6 | PASS (unit) | `tests/test_conversation_context.py` |
| Temporary privacy | G7 | PARTIAL | temporary_chat finish/unlink; needs two-process soak |
| Redis concurrency | G8 | PARTIAL | lease/fence unit tests; full two-worker Redis soak outstanding |
| Model routing / Ollama IDs | G9 | PASS (unit) | `tests/test_ollama_deployment_id.py`; live Ollama TBD |
| API compatibility for Claude | G10 | DOCUMENTED | `BACKEND_FRONTEND_CONTRACT.md` |
| Crash / failure recovery | G11 | PARTIAL | transcript crash hooks in #130 tests; broader matrix TBD |
| Exact-head CI | G12 | PENDING | CI on this tip after push |
| Independent qualification | G13 | OPEN | Antigravity only |

## Route admission parity (engineering)

| Route | Identity | Ownership | Entitlement | Atomic quota | DLP | Commit auth |
|---|---|---|---|---|---|---|
| `/api/chat` | optional* | yes | yes | `admit_serving` | output scan | SQLite fencing |
| `/api/stream` | optional* | yes | yes | `admit_serving` | StreamRedactor | SQLite fencing |
| `/api/inference/*` | required | yes | yes | `reserve_quota` | StreamRedactor | SQLite fencing |
| `/api/ultra` | optional* | session | yes | `admit_serving` | output scan | best-effort |
| `/api/vision` | optional* | session | yes | `admit_serving` | output scan | n/a |
| `/api/cognitive/execute` | optional | n/a | partial | **check_quota (legacy)** | — | — |

\* Invalid credentials always 401; missing credentials follow route anonymous policy.
