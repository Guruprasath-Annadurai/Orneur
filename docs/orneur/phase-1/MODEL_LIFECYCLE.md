# Orneur Model Lifecycle (Phase 1)

Implemented in `orca/registry/`. This is the production foundation the project lacked entirely before Phase 1 — see `docs/orneur/phase-0/MODEL_TRAINING_STATUS.md` for the gaps this closes (no dataset versioning, no experiment tracking, no model registry with promotion/rollback).

## Model family (single source of truth)

`orca/registry/model_spec.py`'s `MODEL_SPECS` dict is now the ONLY place Genesis/Novus/Aeternum's canonical identity is declared. `orca/train/variants.py` and `orca/train/config.py` — the two files that previously duplicated this and silently disagreed on Genesis's parameter class — now both resolve `base_model` from `MODEL_SPECS`, guarded by `tests/test_registry_model_spec.py::test_variants_and_config_agree_with_model_spec`.

| Family | model_id | Canonical base | Parameter class | Legacy Ollama artifacts |
|---|---|---|---|---|
| Genesis | `orneur-genesis` | Qwen2.5-3B-Instruct | 3B (future target) | `orca-nano`, `orca-nano-v4`, `orca-nano-v7` — all forensically confirmed **7.6B**, legacy only |
| Novus | `orneur-novus` | Llama-3.1-8B-Instruct | 8B | `orca-core`, `orca-core-dpo`, `orca-core-combined` |
| Aeternum | `orneur-aeternum` | Llama-3.1-70B-Instruct | 70B (planned) | `orca-ultra` — **never trained**, no checkpoint exists |

## Lifecycle states

`orca/registry/model_spec.py`'s `LifecycleState` enum: `EXPERIMENTAL → TRAINED → EVALUATING → CANDIDATE → APPROVED → PRODUCTION`, with `REJECTED` and `RETIRED` as terminal/demoted states. A checkpoint only reaches `PRODUCTION` through `ModelRegistry.promote()`, which requires a `PROMOTABLE` evaluation decision — there is no code path that sets this by editing a string.

## Manifests

- **Dataset manifest** (`orca/registry/dataset_manifest.py`): `dataset_id`, `version`, `purpose`, `source_paths`, `record_count`, `schema`, `train_checksum`/`eval_checksum` (SHA-256), `creation_code_sha`, `filters_applied`, `deduplication_result`, `known_limitations`. `verify_against_files()` re-hashes the actual files and confirms they still match — catches tampering or accidental overwrite.
- **Checkpoint record** (`orca/registry/checkpoint.py`): identity (model, run, base model, dataset manifests, tokenizer), artifact location + checksum, `verify_integrity()` (raises `CorruptCheckpointError` rather than silently loading a bad artifact), lineage (`lineage_parent`).
- **Training run manifest** (`orca/registry/training_run.py`): run_id, model_id, base_model, dataset manifest IDs, hyperparameters, seed, precision, hardware info, git SHA (auto-captured), start/end time, checkpoint outputs, failure state, resume lineage.
- **Evaluation report** (`orca/registry/evaluation_registry.py`): metrics dict where a missing value is the literal sentinel `UNMEASURED` — never zero, never silently treated as passing.

## Promotion gates

`evaluate_promotion()` reuses the project's EXISTING governance thresholds — `orca/governance/model_cards.py`'s `PERSONA_CLAIM_THRESHOLDS` — rather than inventing new ones. Per family (mapped nano→genesis, core→novus, ultra→aeternum): `eval_accuracy`, `jailbreak_block_rate`, `bias_flag_rate_max`, `domain_eval_min`. Any `UNMEASURED` metric fails the gate outright. See `docs/orneur/phase-1/NOVUS_PROMOTION_DECISION.md` for the real, current Novus verdict.

## Model registry

`orca/registry/model_registry.py`'s `ModelRegistry`: `register`, `lookup`, `lookup_latest_candidate`, `lookup_production` (returns `None` for a family with nothing promoted — Aeternum today — never a fabricated or substituted entry), `promote` (raises `PromotionDenied` if the evaluation isn't `PROMOTABLE`), `reject`, `retire`, `rollback_target` (the most recently-superseded former-production entry). Persistence is a JSON file under `ORCA_HOME/registry/registry_state.json` — deliberately simple, per instruction, with a swappable interface for a future remote registry.

## Security

Every registry ID (`checkpoint_id`, `dataset_id`, `run_id`, `evaluation_id`) is validated by `orca/registry/_ids.py::validate_id()` before being used to build a file path — rejects path separators, absolute paths, and `..` traversal (including the character-class-regex gap where `".."` alone would otherwise pass; caught by `tests/test_registry_id_sanitization.py` and fixed before merge). This is the same bug class as the `orca/mcp/fs_server.py` fix earlier this phase, applied proactively here rather than found later.

## What this does NOT do (by design, per Phase 1 scope)

- Does not touch `orca/serve/registry.py` (the existing "resolve whichever Ollama model is currently installed" serving-time resolver) — that remains the inference-path fallback logic, untouched.
- Does not implement a remote/networked registry backend — the JSON-file store is deliberately swappable later, not built now.
- Does not attempt bit-for-bit training reproducibility — provenance is complete enough to reproduce the recipe (config, data, code SHA, seed), which is what was asked for; the underlying GPU/quantization stack can't guarantee determinism anyway.
