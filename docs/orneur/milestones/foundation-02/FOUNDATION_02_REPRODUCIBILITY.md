# FOUNDATION-02 Reproducibility

## CPU-only foundation verification procedure

```bash
python scripts/acceptance/validate_register_graph.py --check
# expect: pretraining=95 numerator=0 ...

python -m pytest \
  tests/test_training_authorization_gate.py \
  tests/test_training_authorization_assurance.py \
  tests/test_genesis_governance_authorization.py \
  tests/test_cursor_training_math.py \
  tests/test_genesis_checkpoint_integrity.py \
  tests/test_genesis_resumable_checkpoint.py \
  tests/test_cursor_pipeline_admission.py \
  tests/test_foundation02_serving_contract.py \
  tests/test_pretraining_gap_register.py \
  tests/test_pretraining_readiness_gate.py \
  -q
```

Torch CPU + numpy + sentencepiece required for genesis tensor/tokenizer suites.

## Guarantees

- Deterministic unit CI must not launch real training (tripwires in auth tests).
- No hardcoded workstation paths introduced by FOUNDATION-02 deliverables.
- Temporary directories used by tests; no protected ledger mutation.
