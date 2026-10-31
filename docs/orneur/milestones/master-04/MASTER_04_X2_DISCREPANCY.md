# MASTER-04 — X2 discrepancy investigation

## Claims under test
1. L03 `cross_workstream_b6_comparison.json` X2: `"restore_error": "RestoreFailed"`.
2. L03 blocker register L03-B1: restore **proceeded** while the vector owner was running; owner kept a stale view.

## Method
Isolated worktree from exact #146 HEAD `b96cc32…`, genuine `--no-ff` merge of complete L03 history (`bfeaae2…`). Instrumented X2 reproduction **before** owner serving-lock integration (merge tip without the MASTER-04 lock fix path exercised via the pre-fix behaviour of owner not holding `.server.lock`).

## Observed failing-before (this tree)
See `evidence/x2_failing_before.json` and `evidence/x2_failing_before_restore_proceeds.log`.

| Field | Observed |
|---|---|
| restore outcome | **succeeded** (`verified: true`) |
| `restore_error` | `null` (not `RestoreFailed`) |
| owner alive after | **true** |
| owner view keep | 1 |
| deleted collection count via live owner | **1** (stale / resurrected view under live owner) |
| `.server.lock` held by owner before restore | **false** |

## Verdict on the discrepancy
- **Blocker-register claim reproduced** (restore proceeds while owner active; stale owner view).
- **Comparison-JSON `RestoreFailed` NOT reproduced** on this merge tip. That field is **unconfirmed** for MASTER-04’s integrated tree; do not treat it as the failing-before for lock closure.
- Likely cause of JSON `RestoreFailed` in the original L03 isolated merge run: environment-specific (e.g. another holder of the B6 lock, or a different failure mode), not the owner lock contract itself.

## After MASTER-04 lock fix
`tests/qualification/test_master04_integration.py::test_B_restore_refuses_while_owner_holds_serving_lock` — restore raises `RestoreFailed` with `server is running` while owner holds the shared serving lock.
