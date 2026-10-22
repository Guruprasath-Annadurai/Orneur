# Engineering handover

## 1. Executive verdict

PARTIAL.

Software for the gaps listed below is implemented and covered by local tests. The pre-training programme is not accepted, and training is not authorized. A PASS for the whole programme would be false while founder gates remain closed.

## 2. What changed

Added:

- `orca/genesis/training/math_qualification.py`
- `orca/genesis/training/external_anchor.py`
- `orca/genesis/model/family_registry.py`
- `orca/genesis/eval/integrity.py`
- `orca/genesis/tokenizer/specials.py`
- `orca/genesis/tokenizer/robustness.py`
- `orca/pretrain_foundation/` (`agents.py`, `faults.py`, `compute_scenarios.py`)
- `scripts/cursor/pretraining_preflight.py`
- `tests/test_cursor_*.py` (80 tests)
- this `docs/orneur/cursor/` set

Repaired:

- Corpus reader: invalid UTF-8, symlink input, optional license gate, optional max record size.
- Derived cache: optional HMAC mode, fail closed on a bad tag.
- `TrainingState.restore`: optimizer-state shape and finiteness check.

Not removed: audited security checks. Not changed: acceptance ledger, authorization JSON, isolated worker, checkpoint confinement, C02 mission code, frontend.

## 3. Verification

Base: `97582a94efcb93dda6c4e8a8c89e457f446a5af2`. Implementation commit: `4398150a41af424e1d04c7e83d314c6ef4b1ca17`.

Local commands (Asia/Calcutta date 22 October 2026, UTC machine clock):

```
python3 -m pytest tests/test_cursor_pipeline_admission.py tests/test_cursor_tokenizer_robustness.py tests/test_cursor_model_family.py tests/test_cursor_eval_integrity.py tests/test_cursor_external_anchor.py tests/test_cursor_agent_orchestration.py tests/test_cursor_fault_injection.py tests/test_cursor_compute_scenarios.py tests/test_cursor_training_math.py tests/test_cursor_keyed_cache.py tests/test_cursor_tokenizer_multilingual.py
```

80 collected. The compute-scenario assertion failed once on a note that omitted the rupee figure; the note was corrected. The corrected scenario file then passed inside:

```
python3 -m pytest tests/test_cursor_compute_scenarios.py tests/test_genesis_data_pipeline.py tests/test_genesis_training_primitives.py tests/test_genesis_learning_step.py tests/test_genesis_tokenizer.py tests/test_genesis_data_loader.py
```

137 passed.

```
python3 -m pytest tests/test_genesis_resumable_checkpoint.py tests/test_genesis_synthetic_learning_proof.py tests/test_cursor_training_math.py
```

46 passed.

No skip was required in those local runs because Torch and SentencePiece were installed. In GitHub's deterministic job, the three Torch files skip via `importorskip` and are listed on `torch-loss-tests` so they still execute. No xfail was added.

Exact-head CI for `3185d0a4760d9cf43b66353e1bb2fd2e99108958`: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39773008463

Push event. Conclusion success. Created 22 October 2026, 17:15 Asia/Calcutta. Completed 22 October 2026, 17:32 Asia/Calcutta. All 9 jobs succeeded. Do not cite run `39759240669`; that run is the base branch, not this diff.

Torch job `119804937804`: `549 passed, 3 deselected` in 263.84s. The 3 deselections are the pre-existing audit #077 demonstrations. All 27 cursor math, keyed-cache, and multilingual cases in that job passed.

Deterministic job `119804937373`: `8948 passed, 389 skipped, 43 deselected, 7 xfailed` in 1011.25s. The 53 non-torch cursor cases passed there. The three torch cursor files were not executed in that job; they executed in the torch job.

No xfail was added. No assertion was weakened. Known intermittent failures: none observed on this run.

## 4. Readiness, kept separate

| Question | Assessment |
|---|---|
| Software implementation | Partial. The gaps in the work register are coded. Large parts of the 95-row register are hardware, custody, or review. |
| Test qualification | Local pass on the suites above. GitHub run `39773008463` on `3185d0a` succeeded, including the torch job that executed the math, cache, and multilingual cases. |
| Independent security qualification | Not done. Cursor is the author. |
| Dataset provenance | Machinery only. No authorized corpus. |
| Evaluation readiness | Synthetic harness only. Private holdout not created. |
| Hardware readiness | Not provisioned. Workstation class is not frontier capacity. |
| Formal acceptance | 0 / 95. |
| Training authorization | Not granted. |
| Global product readiness | Not claimed. |

## 5. Remaining work

| Owner | Work |
|---|---|
| Cursor, still open | A second clean environment rebuild was not done. Supply-chain lock refresh was not attempted. Exact-head CI for the implementation docs head `3185d0a` is recorded above. |
| Claude | C02 mission API and the founder-approved frontend. Do not duplicate. |
| Independent auditor | Review of this diff and of the still-unmerged GENESIS line. |
| Founder | Acceptance signatures, training grant, corpus custody, hardware decision, any external anchor. |
| External | GPUs, witness service, private eval storage. Not purchased. |

## 6. Next engineering batch

1. The GitHub log for `3185d0a` was read. The run succeeded. Do not weaken an assertion if a later run fails.
2. If a cache key custody path is specified by the founder, require keyed mode for any future authorized run. Do not invent the key.
3. Leave checkpoint confinement and C02 alone unless a new, reproduced defect appears.
