# L03 — security and regression results

Engineering-owned evidence; nothing here is independent qualification. Local runs on the workstation (chromadb 1.5.9 installed — the `memory` extra); CI results (run 41189270383, 10/10 green, 54 L03 tests passed there) are in `L03_EXACT_HEAD_CI.md`.

## New tests (54 + evidence scripts)
| File | Tests | What it proves |
|---|---:|---|
| `tests/test_l03_vector_service.py` | 14 | real owner process: roundtrip, application never imports chromadb, exactly one owner under 6 simultaneous starters, token/path refusal, deadline release + unfrozen application under a held lock, frozen-owner replacement, bounded admission, per-collection isolation, `SIGKILL` mid-indexing, second-worker visibility, graceful stop, idle exit, memory-limit recycling, bounded stuck writes |
| `tests/test_l03_lifecycle.py` | 26 (13 × {embedded, service}) | the Phase D/E scenarios in `L03_DATA_LIFECYCLE_AND_ERASURE_EVIDENCE.md` |
| `tests/test_l03_failure_lab.py` | 8 | descriptor pressure (two ways), damaged binding database, legacy adoption, half-finished deletion with expired lease, missing embedding service, conflicting identifiers |
| `tests/journey/test_l03_vector_live.py` | 6 | two real `orca serve` workers (V1–V6) — added to the CI Journeys job |
| `docs/…/evidence/baseline/l03_baseline_lab.py` | E1–E12 | failing-before evidence against an exact `38e0d31` checkout |

## Existing suites re-run on the changed code (local, final)
`tests/test_l03_*`, `test_l02_*` (all), `test_memory_*` (incl. `test_memory_long_term_chroma_privacy.py`, `test_memory_store_metadata.py`), `test_deletion_end_to_end.py`, `test_account_delete.py`, `test_g006_tenant_isolation.py`, `test_b_conversations.py`, `test_b2_conversation_documents.py`, `test_serve_streaming.py`, `test_product_flows_fake_ollama.py`, `test_connector_document_store.py`, `test_temporary_chat_privacy.py`: **510 passed, 1 skipped, 2 xfailed, 0 failed** (the skip is the pre-existing ASGI-transport disconnect test, documented in its own text; the xfails are pre-existing in `test_g006`). Live: `tests/journey/test_l03_vector_live.py` 6 passed; the LANDMARK-01/02 live suites run in CI (see the CI document).

## Existing assertions or code paths changed, with reasons
* `tests/test_l02_operational.py`: the readiness test asserts the exact set of `maintenance_backlog` keys; two vector counters were added (`vector_deletions_unconfirmed`, `vector_reclamation_pending`).
* `orca/serve/api.py`: synchronous long-term-memory calls on async paths now run in `asyncio.to_thread`; `/api/memory/recall` and `/api/remember` return `503 server_busy` / `504 request_timeout` (or `404` for a refused ownership) when the vector layer fails, instead of an empty result or an unhandled error.
* `orca/gateway/reconcile.py`, `orca/serve/deletions.py`, `orca/docs/store.py`, `orca/brain/memory.py`: all chromadb access moved behind `orca/vectorstore`. `DocStore` and `LongTermMemory` no longer do I/O in their constructors.
* **Pre-existing order dependence (not caused by this change):** running `test_memory_long_term_chroma_privacy.py` (which `importlib.reload`s `orca.brain.memory` and does not restore it) before `test_l02_deletion_lifecycle.py` in one process makes 7 of the latter fail on the **unmodified baseline** as well (verified on `38e0d31`). CI's file order avoids it. Left as is and recorded.

## Security properties
| Property | Evidence |
|---|---|
| Tenant isolation at the vector layer | ownership binding (`mismatch` refuses read, write and delete); tombstoned conversations cannot open a collection; keyword-file collision cannot leak (registry authority) |
| Deleted content not retrievable through retry, restart, fallback, cached collection or partial cleanup | lifecycle tests (cached handles, stale writes, sweep, snapshot restore, repeated failure) |
| Physical erasure not over-claimed | `RECLAIMED` only after rewrite + orphan removal; per-document rebuild; `DEFERRED` visible; limits section above |
| No retrieval from a collection whose ownership cannot be verified | damaged binding database test (fails closed) |
| Service channel | private socket/directory, token, JSON only (no pickle), path confinement, bounded frames |
| No user content in counters/logs | counters carry names/counts only; errors carry exception type names, never messages (messages can quote content) |
| Quota / turn-commit semantics unchanged | `test_serve_streaming.py`, `test_product_flows_fake_ollama.py`, the L02 recovery and operations suites unchanged |
| Prompt-injected documents cannot grant tools | `test_l02_tool_authority.py`, `test_l02_judge_trust_boundary.py` unchanged and green |

## Not re-run for this change
Real-Ollama document journeys and real PDF/DOCX parser fixtures (workstation-only suites), the LANDMARK-02 customer journeys in Chromium (CI fixture variants run), the Postgres integration suite (unaffected modules), B6 backup suites on this branch (they live on PR #143; compared in an isolated worktree instead — see the blocker register).
