# Cursor pre-training work register

Owner: Cursor. Base SHA: `97582a94efcb93dda6c4e8a8c89e457f446a5af2`. Branch: `cursor/orneur-pretraining-foundation-p0-4e55`.

Implementation commit: `4398150a41af424e1d04c7e83d314c6ef4b1ca17`. The GitHub run that executed that code is on docs head `3185d0a4760d9cf43b66353e1bb2fd2e99108958`: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39773008463 (success, 9/9, completed 22 October 2026, 17:32 Asia/Calcutta). Formal acceptance is unchanged: `pretraining=95 numerator=0`.

| Task | Priority | Status | Source | Tests | Blocker |
|---|---|---|---|---|---|
| F01 repository baseline | P0 | Done for this inspection | `docs/orneur/cursor/ORNEUR_PRETRAINING_ENGINEERING_BASELINE.md` | `scripts/cursor/pretraining_preflight.py` | None for the map. Merge of the GENESIS line is still open. |
| F02 training mathematics | P0 | Tested locally. Not an authorized training run. | `orca/genesis/training/math_qualification.py`, `primitives.py` (`validate_optimizer_state`) | `tests/test_cursor_training_math.py` | Independent review. GPU not used. |
| F03 dataset admission and keyed cache | P0 | Tested locally. Unkeyed mode remains the default. | `orca/genesis/data/pipeline.py`, `loader.py` | `tests/test_cursor_pipeline_admission.py`, `tests/test_cursor_keyed_cache.py` | Caller must supply the cache key. No founder key was minted. |
| F04 tokenizer robustness | P0/P1 | Tested locally. Round-trip only. | `orca/genesis/tokenizer/specials.py`, `robustness.py` | `tests/test_cursor_tokenizer_robustness.py`, `tests/test_cursor_tokenizer_multilingual.py` | No new tokenizer was trained on an external corpus. |
| F05 eval integrity harness | P0 | Tested locally on synthetic items. | `orca/genesis/eval/integrity.py` | `tests/test_cursor_eval_integrity.py` | Private V2 corpus is not authorized. No score was produced for a model. |
| F06 model-family contracts | P1 | Tested locally. | `orca/genesis/model/family_registry.py` | `tests/test_cursor_model_family.py` | No checkpoint is registered as trained. |
| F07 security residuals | P0 | Keyed cache and fail-closed anchor added. Checkpoint remediation not reopened. | `loader.py`, `orca/genesis/training/external_anchor.py` | keyed-cache and external-anchor tests | Same-uid worker isolation was already implemented and was not edited. No external witness exists. |
| F08 reproducibility | P0 | Partial. Preflight prints git SHA and the register line. | `scripts/cursor/pretraining_preflight.py` | manual run recorded in the handover | No new hash-locked training extra. No second clean-room rebuild in this session. |
| F09 CI | P0 | Workflow list extended. Exact-head run succeeded. | `.github/workflows/test.yml` `torch-loss-tests` | Torch job `119804937804`: 27 cursor math/cache/multilingual cases passed inside `549 passed, 3 deselected`. Deterministic job: 53 non-torch cursor cases passed inside `8948 passed, 389 skipped, 43 deselected, 7 xfailed`. | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39773008463 on `3185d0a4760d9cf43b66353e1bb2fd2e99108958`. The 3 deselections are the existing audit #077 demonstrations. |
| F10 compute scenarios | P1 | Labels only. No measured throughput. | `orca/pretrain_foundation/compute_scenarios.py`. Existing `orca/genesis/model/scaling.py` unchanged. | `tests/test_cursor_compute_scenarios.py` | Hardware purchase is a founder decision. |
| F11 agent substrate | P1 | Tested with in-process handlers. | `orca/pretrain_foundation/agents.py` | `tests/test_cursor_agent_orchestration.py` | Not connected to C02. Not 100 model workers. |
| F12 fault injection | P1 | Tested for local atomic publish. | `orca/pretrain_foundation/faults.py` | `tests/test_cursor_fault_injection.py` | Does not replace checkpoint fault tests already on the base. |
| F13 acceptance evidence | P0 | Ledger not modified. | this directory | preflight | Founder and independent reviewers. |
| F14 developer preflight | P1 | Script runs. | `scripts/cursor/pretraining_preflight.py` | executed locally | None. |

## Security correction on PR #80

| Task | Priority | Status | Source | Tests | Blocker |
|---|---|---|---|---|---|
| HMAC key confidentiality | P0 | Local tests passed. Exact-head CI is the PR head after this commit. | `orca/genesis/data/loader.py` `CacheIntegrityKey` | `tests/test_cursor_keyed_cache.py::test_cache_integrity_key_is_absent_from_diagnostic_forms` | Keyed mode stays opt-in. No founder key was minted. |
| Idempotency authority binding | P0 | Local tests passed. | `orca/pretrain_foundation/agents.py` `Orchestrator.submit` | `tests/test_cursor_agent_orchestration.py` | In-process state is still readable by the orchestrator holder. |
| Task-id reuse | P0 | Reproduced on `7d66c72`, then rejected before any write. | `orca/pretrain_foundation/agents.py` `TaskIdentityConflict` | `tests/test_cursor_agent_orchestration.py::test_reused_task_id_with_a_new_key_does_not_overwrite` | The in-process maps remain readable by whoever holds the orchestrator. |
| Corpus pathname substitution | P0 | Reproduced, then rejected with `O_NOFOLLOW` opens. | `orca/genesis/data/pipeline.py` | `tests/test_cursor_pipeline_admission.py` plus `tests/test_genesis_data_pipeline.py` | Ancestor symlinks above an input leaf are still followed when `allowed_root` is unset. Checkpoint confinement was not reopened. |

Independent audit: required before any of this is treated as accepted. This register is not that audit. Handoff: `ORNEUR_ANTIGRAVITY_SECURITY_HANDOFF.md`.
