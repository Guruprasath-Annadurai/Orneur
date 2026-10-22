# Cursor pre-training work register

Owner: Cursor. Base SHA: `97582a94efcb93dda6c4e8a8c89e457f446a5af2`. Branch: `cursor/orneur-pretraining-foundation-p0-4e55`.

Implementation commit: `4398150a41af424e1d04c7e83d314c6ef4b1ca17`. Formal acceptance is unchanged: `pretraining=95 numerator=0`.

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
| F09 CI | P0 | Workflow list extended. GitHub run follows the push. | `.github/workflows/test.yml` `torch-loss-tests` | torch job runs the three torch-dependent cursor files. The others collect in the deterministic job. | Exact-head CI URL is not known until the push. |
| F10 compute scenarios | P1 | Labels only. No measured throughput. | `orca/pretrain_foundation/compute_scenarios.py`. Existing `orca/genesis/model/scaling.py` unchanged. | `tests/test_cursor_compute_scenarios.py` | Hardware purchase is a founder decision. |
| F11 agent substrate | P1 | Tested with in-process handlers. | `orca/pretrain_foundation/agents.py` | `tests/test_cursor_agent_orchestration.py` | Not connected to C02. Not 100 model workers. |
| F12 fault injection | P1 | Tested for local atomic publish. | `orca/pretrain_foundation/faults.py` | `tests/test_cursor_fault_injection.py` | Does not replace checkpoint fault tests already on the base. |
| F13 acceptance evidence | P0 | Ledger not modified. | this directory | preflight | Founder and independent reviewers. |
| F14 developer preflight | P1 | Script runs. | `scripts/cursor/pretraining_preflight.py` | executed locally | None. |

Independent audit: required before any of this is treated as accepted. This register is not that audit.
