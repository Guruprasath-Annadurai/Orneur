# Agent trust, adversarial security, and synthetic evaluation

Verdict: `ENGINEERING PARTIAL — SPECIFIC BLOCKERS`.

This note does not assert `PRETRAINING_READINESS_ACCEPTED`, `FOUNDER_AUTHORIZATION_GRANTED`, or `TRAINING_EXECUTION_ALLOWED`. It does not enroll a reviewer, mint a key, or edit the acceptance ledger.

## Commits an auditor can check out

| Branch | Commit | What it changes |
|---|---|---|
| `cursor/readiness-report-boundary-a8b0` | `4f82a6ee060c0e6a3d0ce78015ba1eae74c17ad2` | `report()` no longer treats caller ids as acceptance |
| `cursor/agent-trust-boundary-a8b0` | `8b36b2718ae01a422d2decd37fc3da47a9d2df82` | caller booleans, grants, symlinks, delegation, restart |
| `cursor/synthetic-agent-eval-a8b0` | parent of this file's commit is `8b36b2718ae01a422d2decd37fc3da47a9d2df82` | synthetic task collection, graph, genome |

The synthetic-eval commit is the commit that contains this file. Do not treat a branch name as a green CI result until GitHub has run that exact head.

## Reproduced vulnerability

On `eaa3eaceef79c78924f0b1d5b0eaea48a04f7c4d`, before the report boundary:

`readiness_gate.report()` with a cleared synthetic observation (`counted` 2) and `{"EXEC-1": "forged", "FINAL-2": "forged"}` returned `execution_allowed: true`, `founder_authorized: true`, and `readiness_reportable: true`. The gate label stayed `BLOCKERS_CLEAR_NOT_ACCEPTED`. `acceptance_engine.evaluate` was not called.

## Corrections

`report()` is the `SYNTHETIC_OBSERVATION` interface. Supplied ids are copied to `supplied_identifiers_ignored`. `formally_accepted` stays empty. The three authorization flags stay false. `production_report()` and `report_evaluated()` call `acceptance_engine.evaluate` and do not accept a caller map. Duplicate ids, ids outside the register, and a `git_sha` other than the subject are refused before that call. A non-empty in-memory ledger against the committed empty root is `missing_authority`. The engine's first code is `WRONG_ROOT_STATE_SHA` because the empty root has no 40-character subject SHA. No bootstrap key was created. The engine file was not edited.

`evidence_span(..., authorized=True)` raises. Every span it builds has `authorized=False`. `transition` to `VERIFIED` still fails closed because no external evidence authority is enrolled. `decide_authority` denies caller grant dictionaries. `isolate_memory` stays `allowed: false` for matching tenant strings. `select_team` can consult a `CapabilityGraph` and sets `advertisement_trusted: false`. `restore_snapshot` refuses a success without a stored result and refuses rewriting `CANCELLED` as `SUCCEEDED`.

## Adversarial tests

`tests/test_agent_adversarial_trust.py` on the trust commit:

- Caller boolean, forged grant, and same-actor verification.
- Producer and falsifier with the same id, and self-promotion.
- Cross-tenant delegation and delegation depth above 4.
- Symlink leaf and checkpoint byte substitution.
- Training-lock strings, including the string `"false"`, hidden-eval substring scan, tool-output markers, and one duplicate effect key.
- Cancel during defer, then a forged restart.
- Same-tenant memory strings and tool text that must not change authority.

`tests/test_synthetic_agent_eval.py` on the eval commit adds budget exhaustion, queue saturation, a child budget above the parent, a capability-graph block despite a qualified advertisement, and a failure genome that the producer cannot close.

## Remaining failures

These are still open. The tests above do not close them.

- Two distinct ids can still agree on a false string. That is not cryptographic collusion detection.
- No signature scheme is enrolled, so forged signatures are refused only by the absence of a verifier.
- `EffectLedger` is in-memory. Other irreversible effects are not covered.
- Private-evaluation leakage is a casefold substring scan, not a held-out corpus audit.
- In-flight handler bodies are not preempted.
- `fcntl` locking in the parent stack is per-process.
- Coding and retrieval tasks have no handler that can pass them.
- Size 16 was not run. Only 12 handlers exist.
- R65, acceptance-register C27 / class K, G1, trust enrollment, corpus custody, foundation selection, private evaluation, rights clearance, and qualified compute are unchanged.
- Uncertainty calibration was not added. There is no probability model to calibrate.
- Proof-carrying results remain the existing evidence span. `VERIFIED` is unreachable without an enrolled authority.
- 0 agents are independently qualified. 0 are production authorized.

## Performance comparison

Suite `synthetic-agent-eval-v1`. Five trials. Handlers are deterministic. `model_inference` is false. This is not a real-model gain.

| Task | Selected size | Why |
|---|---|---|
| reasoning-unsupported | 2 | size 1 stays OBSERVED; size 2 is REFUTED; size 10 matches size 2 and costs more calls |
| reasoning-supported | 1 | OBSERVED and not verified |
| coding-return-value | none | no `tests_passed` |
| retrieval-span | none | no `retrieved` |
| contradiction | 2 | size 1 has no dispute resolution; size 2 is DISPUTED |
| abstention | 1 | UNKNOWN, not VERIFIED |
| authority-refusal | 1 | DENIED and not executed |
| workflow-incomplete | 1 | INCOMPLETE, completion not fabricated |

`false_verification` was 0 on every measured size. Variance of the boolean success flag was 0. Latency is `process_perf_counter_seconds` and is not a service objective. `shadow_tournament` copies the selected size and sets `qualified` and `production_authorized` false. A larger team is recorded only for the unsupported equation and the contradiction task.

## Counts

| Count | Value |
|---|---|
| Declared roles | 100 |
| Implemented synthetic handlers | 12 |
| Independently qualified agents | 0 |
| Production-authorized agents | 0 |
| Capabilities at IMPLEMENTED_SYNTHETIC | 17 |
| Capabilities at DESIGNED | 18 |
| Capabilities qualified or production authorized | 0 |
| Counted pretraining requirements accepted | 0 / 95 |

The earlier measurement snapshot remains in `ORNEUR_100_AGENT_INDEPENDENT_QUALIFICATION_HANDOFF.md` and recorded 13 synthetic capabilities. B12, B16, C25, and D29 moved because the graph, the genome, restart refusal, and the tournament now have tests. Capability C27 in that list is still `record_denial`, not acceptance-register C27.

## Acceptance ledger

File: `docs/orneur/acceptance/acceptance_ledger.json`.

Bytes: `[]\n`.

sha256: `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`.

## Antigravity audit

1. Check out each commit above. Confirm `git rev-parse HEAD` matches the table, and for the eval branch confirm this file is in that commit and the parent is `8b36b2718ae01a422d2decd37fc3da47a9d2df82`.
2. On the readiness branch, from that worktree: `PYTHONPATH=<worktree> python3 -m pytest -q tests/test_pretraining_readiness_gate.py`. Expect the forged `EXEC-1` case to keep `execution_allowed` false.
3. On the trust commit: `python3 -m pytest -q tests/test_agent_adversarial_trust.py tests/test_agent_role_registry.py tests/test_cursor_agent_orchestration.py`.
4. On the eval commit: `python3 -m pytest -q tests/test_synthetic_agent_eval.py tests/test_agent_role_registry.py tests/test_agent_adversarial_trust.py tests/test_cursor_agent_orchestration.py`.
5. Recompute the ledger hash. Refuse the run if it differs from the hash above or if the file is not `[]\n`.
6. Refuse any reading that treats 12 handlers, 17 synthetic capabilities, or a selected team size as an independently qualified agent or as permission to train.

No protected merge, production deployment, spending, GPU job, or ledger edit is requested.
