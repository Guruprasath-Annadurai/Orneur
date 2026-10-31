# MASTER-04 — CI evidence

## Starting refs CI (pre-existing)
| Ref | Run | Result |
|---|---|---|
| MASTER-03 tip `b96cc32` | [41178651529](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41178651529) | all jobs PASS |
| L03 code `c8b0f54` | [41189270383](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41189270383) | success |
| L03 doc head `bfeaae2` | [41190351398](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41190351398) | success (docs-only delta vs code SHA) |

## Exact-head verified tip

| Item | Value |
|---|---|
| Tip SHA | `cadad0e525c5f84698af9945d048b9ba36aa4f0e` |
| Tip TREE | `d1742759c1ecf25629f7bca1376719a75bd52d71` |
| Run | [41196122676](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41196122676) |
| Result | **success — 10/10 jobs** |
| Deterministic | **9730 passed**, 0 failed, 425 skipped, 197 deselected, 6 xfailed |
| Journeys | all suites green; M04 suite **9/9**; L03 vector/lifecycle/failure/live green; B6 live green |

## Failing-before (disclosed)

### Tip `000ee2a` — run [41192500593](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41192500593)
**FAIL** — Deterministic (vector deletion/DocStore; false lock-refusal under slow start) + Journeys (`test_l02_b6_backup_live`: orphaned owner held serving lock after API stop).

### Tip `5ab87f3` — run [41194297136](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/41194297136)
**FAIL** — Deterministic 27 failed (sticky `enable_service_mode` after B6 `with TestClient` → owner `bad_root` when MEMORY_DIR outside ORCA_HOME) + Journeys ancestry only (shallow checkout missing objects; M04 B–F 8/9 green).

## Repairs that landed on `cadad0e`
1. Stop vector owner on API shutdown before releasing serving lock.
2. Lock-refusal detection scoped to owner.log bytes since latest spawn.
3. Lifespan clears sticky service mode + transport cache on exit.
4. Journeys checkout `fetch-depth: 0` for ancestry fail-closed on real history.

Local green after repairs: B6 serving-lock → deletion/doc/embedding/product_flows/M04/B6 backup = **84 passed**.
