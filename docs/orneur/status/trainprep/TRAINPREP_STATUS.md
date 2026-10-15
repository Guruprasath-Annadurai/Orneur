# Training infrastructure preparation (Workstream G): status

**Nothing was trained.** No GPU, model, tokenizer, weight download, provider/network inference, protected data or real key was used or created. `docs/orneur/authorization/TRAINING_AUTHORIZATION.json` and every other authorization/registry JSON are byte-identical to the base commit (`NOT_AUTHORIZED`; the sample result records before/after SHA-256 of all 14 files and the seven lock functions). `orca/train/authorization.py`, `docs/orneur/acceptance/**`, `docs/orneur/phase-21/rse/**`, `orca/rse/**` and `register_graph.json` are untouched. Nothing here changes whether training is authorized; it only prepares and tests the machinery around a future authorization.

## What exists

| # | Deliverable | Where | Tests |
|---|---|---|---|
| 1 | Hash-locked `train` extra (122 pinned packages, 2500 sha256 hashes; CPython 3.11, linux x86_64 manylinux_2_28) + structural verifier | `requirements/train.txt`, `orca/train/dryrun/lockcheck.py`, `scripts/trainprep/verify_train_lock.py` | `tests/test_trainprep_lock_env.py` |
| 2 | Deterministic environment manifest (python, platform, lock hash, container `null`/`NOT_BUILT`, injected code SHA and dataset bundle hash, seeds, self-hash) | `orca/train/dryrun/envmanifest.py`, `scripts/trainprep/env_manifest.py` | `tests/test_trainprep_lock_env.py` |
| 3 | Pure-Python toy model with Adam / SGD-momentum, warmup+decay scheduler, gradient accumulation, dropout RNG, data-order cursor | `orca/train/dryrun/toy.py`, `harness.py` | `tests/test_trainprep_resume.py` |
| 4 | Atomic, verify-before-load checkpoints on `orca.registry.checkpoint` | `orca/train/dryrun/ckpt.py` | `tests/test_trainprep_checkpoint.py` |
| 5, 6 | Resume byte-identity from any step; optimizer/scheduler/RNG/cursor preservation with negative controls | `harness.py` | `tests/test_trainprep_resume.py` |
| 7 | Hash-chained run ledger + immutable sealed `TrainingRunManifest` (registry code unmodified) | `chainlog.py`, `ledger.py` | `tests/test_trainprep_ledger.py` |
| 8 | Step/token/spend/wall-clock caps, kill switch, default 0 = nothing runs, rollback of the in-flight step | `budget.py` | `tests/test_trainprep_budget.py` |
| 9 | GPU allocation + failure-mode specification (DESIGN) | `GPU_ALLOCATION_AND_FAILURE_MODES.md` | n/a (docs) |
| 10 | Authorization enforcement against the real gate with in-test ephemeral keys | `harness.py::rehearse_with_grant`, `authorize_and_rehearse` | `tests/test_trainprep_authorization.py` |
| 11 | Git SHA (clean tree) + dataset manifest hash + config hash binding, re-checked on resume | `binding.py` | `tests/test_trainprep_binding.py` |
| 12 | Synthetic-only sentinel (imports, sockets, GPU libs, subprocess, out-of-sandbox paths), fails closed | `sentinel.py` | `tests/test_trainprep_sentinel.py` (subprocess) |
| 13 | Off-host training inventory (20 entries) + retirement plan + CI tripwire | `OFFHOST_NOTEBOOK_INVENTORY.json`, `RETIREMENT_PLAN.md`, `inventory.py`, `scripts/trainprep/offhost_inventory.py` | `tests/test_trainprep_inventory.py` |
| 14 | Rotating, chained, anchored local audit log + anchor for the gate's own `events.jsonl`; architecture doc | `auditlog.py`, `AUDIT_LOG_RETENTION_ARCHITECTURE.md` | `tests/test_trainprep_auditlog.py` |
| 15 | `python -m orca.train.dryrun` and the committed SYNTHETIC result | `cli.py`, `__main__.py`, `dryrun_result.json` | `tests/test_trainprep_cli.py` |

## Register rows (evidence prepared, not accepted)

| Row | What this change contributes | What it does NOT do |
|---|---|---|
| TRAIN-1 (hash lock + one dry-run command pinned to a SHA) | `requirements/train.txt` + verifier; `python -m orca.train.dryrun` records `git_sha` and the lock SHA-256 in one result | The lock was generated, not installed. Whether every hash matches the index at install time is only proven by `uv pip install --require-hashes -r requirements/train.txt`, which was deliberately not run. One platform/Python only. |
| TRAIN-2 (synthetic dry-run log with the locks still false) | `dryrun_result.json` (before/after SHA-256 of all authorization JSON, seven lock functions, `prove_authorization_locks()`, the gate's pure verdict `NOT_AUTHORIZED`) | The seven lock functions in `orca/rse/imp1/locks.py` are constants that return false; the evidence that matters is the on-disk JSON hashes and the gate verdict, and the result reports all of them. It is a toy run, not a full-trainer dry run. |
| G12 (infrastructure record) | Pinned software identity (lock), dry-run log pointer (sample result) | No P2 environment id exists; no container image exists. |
| P2-4 (spend above cap is refused; cap may remain 0) | `tests/test_trainprep_budget.py::test_spend_above_the_configured_cap_is_refused_including_cap_zero`, plus the grant-level `SPEND_NOT_AUTHORIZED` tests | The spend is simulated; real billing telemetry does not exist. |
| SUP-1 (two independent build digests of the training image) | The manifest carries `image_digest: null, status: NOT_BUILT` so nobody can mistake the placeholder for a digest | No image was built. Not started. |

## Reproduce

```
python -m pytest tests/test_trainprep_*.py
python scripts/trainprep/verify_train_lock.py
python scripts/trainprep/offhost_inventory.py --check
python -m orca.train.dryrun --out /tmp/result.json     # needs a clean git tree; exits 3 (fail closed) otherwise
```

## Known limitations

- The toy run proves control flow (caps, rollback, checkpoint, resume, ledger, guard), not numerical behaviour of a real trainer, CUDA, mixed precision or distributed code.
- The sentinel is a tripwire for ORNEUR code, not a sandbox against hostile code in the same process; PEP 578 audit hooks cannot be removed once installed (they stay inert when no guard is active).
- Wall-clock caps are per process invocation (step/token/spend caps are cumulative across resumes).
- The audit-log anchors raise the cost of truncation but a host operator holding the key and write access to log and anchors can still forge a history. Off-host anchoring is design only.
- The off-host notebook controls are a repository tripwire and a plan; remote Kaggle/Colab state and a person running a copy are outside what any repository test can see.
- Adding files under `orca/train` changes the gate's code-tree hash (`CODE_PATHS = orca/train, orca/registry`). This is intended (any future authorization is signed over the reviewed tree) and cannot affect the present `NOT_AUTHORIZED` state.
