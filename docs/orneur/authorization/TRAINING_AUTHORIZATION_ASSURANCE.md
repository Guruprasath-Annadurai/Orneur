# Training authorization — adversarial assurance (Task C, for independent review of PR #24)

Status: **IMPLEMENTED_TESTED, NOT_AUTHORIZED, NOT_INDEPENDENTLY_AUDITED.** The committed registry still has zero keys and the committed record is
`NOT_AUTHORIZED`: **no training is authorized, no key was provisioned, nothing was trained, no GPU or spend was used.** All tests use synthetic keys and
throw-away repositories (`tests/test_training_authorization_assurance.py`, building on the PR #24 `World` fixture). Frozen contracts are untouched.

## 1. Entry-point inventory (what can start training)

| Surface | Reaches a trainer? | Governed by the gate? |
|---|---|---|
| `orca.train.finetune.train()` | yes (`_train_impl`) | **yes** — `authorize_training()` first |
| `orca.train.finetune._train_impl()` | yes | **yes** — requires a `TrainingGrant`, re-verified |
| `orca.train.cloud.CloudTrainer.run()` (SSH rented GPU) | yes (remote) | **yes** — authorizes before any SSH/upload |
| `orneur train run | nano | core | ultra | cloud` (CLI) | via the two above | **yes**; denial = exit 2 |
| `_ssh_run`, `_rsync_up/_down` (module helpers) | would start remote work | not themselves gated → **tripwire**: no module outside `cloud.py` may use them |
| `orca/learning/training_experiment.py` | **no** — explicitly never invokes a trainer (its text names a non-existent `run_finetune`; stale wording only) | n/a |
| CI workflows, Dockerfiles, compose, k8s, shell scripts | **no** — scanned: none launches `orneur/orca train run|nano|core|ultra|cloud`, `python -m orca.train`, `torchrun`, `accelerate launch`, `deepspeed` (workflows only run `orca train prepare/eval/regression/redteam/card`) | tripwire test |
| 14 legacy Colab/Kaggle notebooks (`notebooks/*.ipynb`) | **yes, off-host** (they construct SFT/DPO trainers) | **no, by nature** — they run on third-party hosts and are not executed by any ORNEUR code (tripwire: nothing runs notebooks). The set is frozen in a test so a new one is a visible change. They are a policy/process control, not a code control |
| Any script an operator writes that never imports ORNEUR | yes | **no** — outside what repository code can stop (documented residual) |

## 2. Attack results

Against PR #24 head `ce3d58c` (`docs/orneur/status/taskc/BEFORE_pr24_head.txt`): **16 failed** (genuine gaps), 7 passed (controls that already held / tripwires), 1 documented residual.
After the fix (`AFTER_fixed.txt`): **0 failed**, 23 passed, 1 xfail (residual). The 92 pre-existing gate tests pass unchanged.

| # | Attack | Before | After |
|---|---|---|---|
| 1 | `dataclasses.replace(grant, max_wall_clock_minutes=10**6 / expires_at / train_sha256 / eval_sha256 / run_slot / environment_class / cfg_fingerprint / authorization_id)` — the seal is an init field, so the widened copy passed | **forged grant accepted** (8 variants) | `GRANT_TAMPERED` |
| 2 | `copy`, `deepcopy`, `pickle` round-trip of a grant | produced an unvalidated grant object | `TypeError` (grants cannot be copied or serialized) |
| 3 | grant built by `object.__new__` with a wrong seal / wrong tag / widened fields, passed to `require_grant`, `assert_valid_for`, `assert_files`, `wall_clock_callback` | **accepted** (no consumer re-checked the seal) | every consumer calls `verify_integrity()` → `GRANT_FORGED_OR_TAMPERED` |
| 4 | delete the run-slot directory to reset `max_runs` | **budget reset** | the audit chain is a second ledger → `RUN_BUDGET_EXHAUSTED` |
| 5 | edit a line of `events.jsonl` | log still appended to; nothing noticed | `AUDIT_LOG_TAMPERED` blocks new authorizations |
| 6 | append malformed JSON to the log | same | `AUDIT_LOG_TAMPERED` (a malformed log is tampered, never "fine") |
| 7 | 6 concurrent starts on a `max_runs=1` authorization | exactly one grant | unchanged |
| 8 | forged environment (`ORNEUR_TRAINING_AUTHORIZED`, `CI`, `FORCE`, …) + a hand-crafted `AUTHORIZED` file in the state directory, against the real repository | denied `NOT_AUTHORIZED` | unchanged (the record is read from the reviewed repository, never from state) |
| 9 | remote-GPU helpers reused outside `CloudTrainer.run()` | none do | tripwire |
| 10 | CI / container / script surface launching training | none do | tripwire |
| 11 | truncating the TAIL of the audit chain | undetected | **still undetected (strict xfail)** |

Already covered by PR #24 and unchanged: replayed/expired/revoked authorizations, wrong dataset or base-model revision, dirty tree / changed code / non-ancestor commit,
signature from another purpose domain, over-broad authority scope, spend and wall-clock limits, unreadable trust files, no env/flag/dry-run bypass, trainer-construction
AST guard.

## 3. Fix summary (`orca/train/authorization.py`)

* `TrainingGrant` carries an HMAC tag over its fields, keyed by a random per-process key that is never written anywhere; edits break it, `__reduce__` forbids copying/pickling,
  and every consumer (`require_grant`, `assert_valid_for`, `assert_files`, `wall_clock_callback`) verifies it first.
* `authorize_training()` verifies the audit hash-chain before doing anything else, and counts prior `TRAINING_AUTHORIZED` events for the authorization against `max_runs`
  in addition to the slot files.
* `verify_event_chain()` treats malformed / unreadable logs as tampered.

## 4. Residual risks (honest)

1. **Same-process attacker.** Code running in the training process can read `_SEAL`, `_PROCESS_KEY` and call internals. The gate controls ORNEUR's own entry points; it does not
   sandbox the process. Anyone who can edit this source file (and the pinned registry digest) changes the policy — mitigated only by review, the code-tree hash in the grant, and
   founder-held offline signing.
2. **Audit tail truncation** (attack 11) and deleting *both* the slot files and the events leave the budget resettable. Needs an anchor outside the operator's write access
   (remote append-only log / signed checkpoint). Not built.
3. **Notebooks and operator-written scripts** are outside the gate (§1).
4. **Remote script contents** run on a host ORNEUR does not control; the gate prevents launching, not the content.
5. **Environment class is declared by code path, not measured**; spend on the SSH path is an estimate.
6. No independent review of PR #24 or of this assurance change yet.

## 5. Reviewer handoff

Review `orca/train/authorization.py` (diff vs `ce3d58c`), `tests/test_training_authorization_assurance.py`, and the before/after files in `docs/orneur/status/taskc/`.
Reproduce: `pytest tests/test_training_authorization_assurance.py tests/test_training_authorization_gate.py` (Python 3.11). Exact commit SHA and CI results: see the PR.
