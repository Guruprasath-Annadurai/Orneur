# Training mathematics qualification

Scope: tiny CPU tensors. No corpus, no GPU, no checkpoint that would be used for serving.

## What was added

`orca/genesis/training/math_qualification.py`

- Central finite-difference check against `backward()` on the manual attention path. Absolute tolerance `2e-3` at epsilon `1e-3`. A pass is not bit-exact.
- `reference_adamw_step`: decoupled AdamW, weight decay applied before the Adam update. Compared to `torch.optim.AdamW` at `atol=1e-6`, `rtol=1e-6`.
- `supervised_token_count`: positions that survive the causal shift and are not `ignore_index`.

`validate_optimizer_state` in `orca/genesis/training/primitives.py` runs at the start of `TrainingState.restore`. It rejects a partial slot map, a moment whose shape disagrees with the parameter, a non-finite moment, and a negative step. An empty AdamW state (no step yet) is valid. An equal-shaped swap of two moments is not detected here; the existing checkpoint HMAC covers content binding.

## Tests

`tests/test_cursor_training_math.py` covers finite difference, one AdamW step, weight decay on matrices only, cleared gradients, clipping, NaN loss before `optimizer.step`, token counts, accumulation of equal microbatches versus the mean of per-microbatch losses, optimizer corruption, three save/restore cycles (`atol=1e-6`, `rtol=1e-5`), and the engine learning rate at the pre-increment global step.

Accumulation assumption, stated in the test: equal microbatch sizes and mean-reduced loss divided by the accumulation count. That is the engine's update. It is not the gradient of one concatenated batch.

## Already covered on the base, not re-implemented

Dataset-identity mismatch, config-fingerprint mismatch, and single-interrupt resume equivalence already have tests in `tests/test_genesis_resumable_checkpoint.py`. Those tests passed again after the restore check was added (`tests/test_genesis_resumable_checkpoint.py` and `tests/test_genesis_synthetic_learning_proof.py` in the same local run as the math tests: 46 passed, which also included `tests/test_cursor_training_math.py`).

## Not claimed

Bit-exact resume on every CPU. A measured maximum absolute difference of zero on one machine is an observation, not a portability guarantee. The repeated-interruption test uses `torch.allclose`.
