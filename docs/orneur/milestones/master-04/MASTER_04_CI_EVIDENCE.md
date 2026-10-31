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

### Repair
1. `ensure_owner` treats only owner.log "vector owner refused to start" as lock-refusal (not slow chromadb start).
2. API lifespan shutdown stops the vector owner before releasing the API serving lock.

### Passing-after
_pending push of repair tip_

Local green evidence: `evidence/master04_suite_green.log` (9/9) and post-repair local B6+deletion checks.
