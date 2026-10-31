# MASTER-04 — red-to-green evidence

## Red (failing-before)
1. X2 on merge tip without owner serving lock: restore **succeeds** over live owner; owner keeps stale counts (`evidence/x2_failing_before.json`).
2. Claude comparison-only patch (`proposed_owner_serving_lock.patch`) that `except Exception: lock=None` then `owner.serve()` — **prohibited**; not applied.

## Green (after fix on `d3afecc`)
Local: `pytest tests/qualification/test_master04_integration.py` — **9 passed** (`evidence/master04_suite_green.log`).

Deterministic CI red→green lever: lifespan must clear service mode on exit (B6 `with TestClient` was contaminating later L02 deletion/DocStore tests via sticky service mode + MEMORY_DIR outside ORCA_HOME → owner `bad_root`). Journeys red→green for ancestry: `fetch-depth: 0`.

Exact-head green: tip `cadad0e` — Deterministic 9730 passed / 0 failed; Journeys M04 9/9; run [41196122676](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41196122676).

| Test | Proves |
|---|---|
| A ancestry | M03 + L03 SHAs are ancestors; missing objects would fail closed |
| B restore while owner | RestoreFailed "server is running" |
| B owner under exclusive | ensure_owner raises; pid None |
| C active owner backup | `consistent=false` + owner_active marker |
| C quiesced backup | `consistent=true` after quiesce |
| D lifecycle | tombstones + sweep; deleted bytes gone; physical medium erasure unproven |
| E multiprocess race | 4 restores all RestoreFailed while owner alive |
| F packaging | Dockerfile does not install memory/backup/chromadb |
| F fail-closed patch | catch-and-continue absent; exit 2 present |

## Preservation (local)
- B3 apikey reauth unit: 22 passed
- B6 backup + corrective: 69 passed
- B6 no-crypto dependency: 3 passed
- acceptance register graph: 1 passed
- pretraining readiness gate: 4 passed
