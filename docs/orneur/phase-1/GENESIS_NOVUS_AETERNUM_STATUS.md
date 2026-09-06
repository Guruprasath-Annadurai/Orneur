# Genesis / Novus / Aeternum — Status After Phase 1

## Genesis

- **Historical checkpoints**: `orca-nano`, `orca-nano-v4` (identical artifact, re-tag only), `orca-nano-v7` — all forensically confirmed Qwen2.5-**7B**-class (7.6B params, embedding length 3584, via `ollama show`). Registered in the model registry as `family=genesis`, `lifecycle_state=RETIRED`. Never relabeled.
- **Canonical future target**: Qwen2.5-**3B**-class, per `orca/registry/model_spec.py::MODEL_SPECS["genesis"]` — the single source of truth `orca/train/variants.py` and `orca/train/config.py` now both resolve from.
- **Config ambiguity**: ELIMINATED. Both files previously declared this independently and disagreed; both now import `MODEL_SPECS["genesis"].base_model`, guarded by a test that fails if they ever diverge again.
- **Registry status**: family defined, 3 legacy checkpoints imported and retired, dataset manifest (`orca-genesis-combined-safety-calibration-v1`) frozen and checksummed. **No training has occurred toward the 3B target** — the frozen dataset has not been used for training, per explicit Phase 1 scope (no new training authorized this phase).

## Novus

- **Checkpoint evaluated this phase**: `orca-core-combined-v2` (4x/1:5 safety oversample — the checkpoint that resolved the calibration regression).
- **Calibration**: **RESOLVED** — 100.0% (clean, zero generation errors), vs. 0.0% at the prior best-jailbreak checkpoint.
- **Jailbreak**: 70.0% strict / 90.0% average across trials.
- **Bias**: 12.5% flag rate.
- **Accuracy** (newly measured this phase, `orca.train.eval.OllamaEvaluator.accuracy_eval`, 50 golden prompts, zero generation errors): **72.8%**.
- **Domain eval** (newly measured this phase, `orca.train.novus_eval.NovusEvaluator.run`, 24 probes, keyword+structured-reasoning scored): see `docs/orneur/phase-1/NOVUS_PROMOTION_DECISION.md` for the final number and the resulting promotion verdict.
- **Promotion status**: determined by `evaluate_promotion()` against the real governance thresholds — see `NOVUS_PROMOTION_DECISION.md`. Thresholds are NOT relaxed to promote; if jailbreak (92% required) or any other metric fails, the checkpoint is marked `NOT_PROMOTABLE`, which is an acceptable, correct Phase 1 outcome per explicit instruction ("Phase 1 requires the lifecycle to correctly reject a model that fails").

## Aeternum

- **Family registered**: yes, `orneur-aeternum`, base target Llama-3.1-70B-Instruct.
- **Checkpoint**: **ABSENT**. Confirmed by `ModelRegistry.lookup_production("aeternum")` returning `None`, and by `ModelRegistry.lookup_latest_candidate("aeternum")` also returning `None` — no candidate exists at any lifecycle stage, not just no production entry.
- **Routing eligibility**: `tests/test_registry_lifecycle.py::test_aeternum_absent_checkpoint_cannot_be_routed` confirms the registry never fabricates or substitutes a stand-in for a missing family — a caller resolving Aeternum for inference gets an explicit `None`, not a silent fallback to a different model.
- **No training performed** — per explicit Phase 1 scope, Aeternum training is out of scope and requires its own future authorization.
