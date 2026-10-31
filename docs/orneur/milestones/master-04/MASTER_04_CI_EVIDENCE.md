# MASTER-04 — CI evidence

## Starting refs CI (pre-existing)
| Ref | Run | Result |
|---|---|---|
| MASTER-03 tip `b96cc32` | [41178651529](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41178651529) | all jobs PASS |
| L03 code `c8b0f54` | [41189270383](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41189270383) | success |
| L03 doc head `bfeaae2` | [41190351398](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41190351398) | success (docs-only delta vs code SHA) |

## MASTER-04 tip CI

### Failing-before (disclosed)
| Item | Value |
|---|---|
| Tip | `000ee2ae8f6f7e7b167df22bf615f186dff91cd4` |
| Run | [41192500593](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41192500593) |
| Result | **FAIL** — Deterministic (vector deletion/DocStore degraded; aggressive ensure_owner lock-refusal false-positive under slow start) + Journeys (`test_l02_b6_backup_live`: restore refused because vector owner still held serving lock after API stop) |
| Other jobs | 8/10 PASS (Torch, Container, Security, Sandbox, RSE×2, Dep scan, SSE) |

### Repair 1
1. `ensure_owner` treats only owner.log "vector owner refused to start" as lock-refusal (not slow chromadb start).
2. API lifespan shutdown stops the vector owner before releasing the API serving lock.

| Tip | `5ab87f3c567ead37210eac91b38d286b3d6bc429` |
|---|---|
| Run | [41194297136](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41194297136) |
| Result | **FAIL** — Deterministic 27 failed (same docs/LTM `PENDING` pattern) + Journeys ancestry only (`fetch-depth` shallow; M04 B–F 8/9 green; L03 54 + B6 live green) |

### Root cause (Deterministic contamination) — confirmed locally
`tests/test_l02_b6_corrective.py::test_the_application_takes_the_serving_lock_on_startup` uses `with TestClient(app)`, which runs lifespan → `enable_service_mode(True)`. Lifespan exit did **not** clear service mode, so every later Deterministic test inherited service mode without lifespan.

Those tests often keep `MEMORY_DIR`/`DOCS_DIR` outside the current `ORCA_HOME` (import-time binding or g006 monkeypatch). The owner rejects such roots as `bad_root` → deletion reports `PENDING`/`docs:failed` / DocStore degraded. Local reproduction: B6 serving-lock test then deletion/embedding/product_flows → same 4 failures as CI; after the fix → green.

Journeys ancestry failed closed correctly on missing objects under shallow checkout (not a silent bypass).

### Repair 2
1. Lifespan finally: `enable_service_mode(False)` + `reset_for_tests()` after stop_owner / lock release.
2. Journeys checkout `fetch-depth: 0` for ancestry objects.
3. Lock-refusal log probe scoped to bytes written since the latest spawn (no historical poison).

### Passing-after
_pending exact-head CI on repair-2 tip_

Local green after repair-2: B6 serving-lock → deletion lifecycle → doc-store → embedding → temporary-chat → product_flows account delete → M04 suite → B6 backup = **84 passed**.
