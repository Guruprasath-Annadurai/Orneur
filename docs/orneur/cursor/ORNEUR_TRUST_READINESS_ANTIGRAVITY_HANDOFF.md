# Antigravity handoff for the trust and readiness corrections

This note covers PRs #105, #106, and #107 only. It does not merge them. It does not change the acceptance ledger.

Verdict for the programme remains `ENGINEERING PARTIAL — SPECIFIC BLOCKERS`.

## Exact heads and CI

Checked against GitHub Actions on 24 October 2026. Each run's `headSha` matches the PR head. All 9 checks succeeded. That is not a production authorization.

| PR | Branch | Head | Base | Actions run | headSha |
|---|---|---|---|---|---|
| #105 | `cursor/agent-trust-boundary-a8b0` | `8b36b2718ae01a422d2decd37fc3da47a9d2df82` | `cursor/measurement-gaps-a8b0` | `40085517242` | same head |
| #106 | `cursor/readiness-report-boundary-a8b0` | `4f82a6ee060c0e6a3d0ce78015ba1eae74c17ad2` | `cursor/pretraining-readiness-gate-a8b0` | `40085020975` | same head |
| #107 | `cursor/synthetic-agent-eval-a8b0` | `15972e185321fbc9459bc9e45783969e7c15ceb3` | `cursor/agent-trust-boundary-a8b0` | `40085517995` | same head |

## Ancestry

`8b36b2718ae01a422d2decd37fc3da47a9d2df82` is an ancestor of `15972e185321fbc9459bc9e45783969e7c15ceb3`. PR #107 contains PR #105.

`4f82a6ee060c0e6a3d0ce78015ba1eae74c17ad2` is not an ancestor of PR #107 and not an ancestor of PR #105. The merge base of #106 and #107 is `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` (`main`). Integrating the synthetic-eval branch does not include the readiness-report fix. Review #106 on its own base.

## What #106 changes

On parent `eaa3eaceef79c78924f0b1d5b0eaea48a04f7c4d`, `readiness_gate.report()` accepted caller ids `EXEC-1` and `FINAL-2` and returned `execution_allowed: true` without calling the acceptance engine.

`report()` is now the `SYNTHETIC_OBSERVATION` interface. Those flags stay false. `production_report()` and `report_evaluated()` call `acceptance_engine.evaluate` and take no caller acceptance map. The engine file and the ledger bytes were not modified.

## What #105 changes

Caller booleans, grant dictionaries, tenant strings, and evidence text do not authorize. Symlink leaves and a mismatched checkpoint digest are refused. Cross-tenant delegation and depth above 4 are refused. `restore_snapshot` refuses a cancellation rewritten as success. No signing key was minted. `VERIFIED` stays unreachable because no external evidence authority is enrolled.

## What #107 changes

Suite `synthetic-agent-eval-v1` selects size 2 only for the unsupported equation and a two-text dispute. Coding and retrieval select no team. The shadow tournament does not promote a winner. Counts at that head: 100 declared roles, 12 synthetic handlers, 17 `IMPLEMENTED_SYNTHETIC` capabilities, 0 qualified, 0 production authorized, 0/95 accepted.

## Ledger

`docs/orneur/acceptance/acceptance_ledger.json` bytes `[]\n`.

sha256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`.

## What an auditor should re-run

On each head, `git rev-parse HEAD` must match the table.

- #106 worktree: `PYTHONPATH=<worktree> python3 -m pytest -q tests/test_pretraining_readiness_gate.py`
- #105: `python3 -m pytest -q tests/test_agent_adversarial_trust.py tests/test_agent_role_registry.py tests/test_cursor_agent_orchestration.py`
- #107: `python3 -m pytest -q tests/test_synthetic_agent_eval.py tests/test_agent_role_registry.py tests/test_agent_adversarial_trust.py tests/test_cursor_agent_orchestration.py`

Refuse a reading that treats either branch as included in the other, or that treats a green check as permission to train.
