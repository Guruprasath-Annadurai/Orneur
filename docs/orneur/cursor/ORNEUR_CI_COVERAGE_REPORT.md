# CI coverage

## Local

Python 3.12. Torch 2.14.1+cpu. SentencePiece 0.2.2. Pytest 9.1.1.

`tests/test_cursor_*.py`: 80 collected, and after the workstation-note fix the compute scenario test passed inside a 137-passed regression run. The other cursor files passed in the preceding 79-passed run (one failure, the note assertion, was the only failure and was corrected).

Also passed locally after these edits:

- `tests/test_genesis_data_pipeline.py`
- `tests/test_genesis_training_primitives.py`
- `tests/test_genesis_learning_step.py`
- `tests/test_genesis_tokenizer.py`
- `tests/test_genesis_data_loader.py`
- `tests/test_genesis_resumable_checkpoint.py`
- `tests/test_genesis_synthetic_learning_proof.py`

## Workflow change

`.github/workflows/test.yml`, job `torch-loss-tests`, now also runs:

- `tests/test_cursor_training_math.py`
- `tests/test_cursor_keyed_cache.py`
- `tests/test_cursor_tokenizer_multilingual.py`

Those modules call `pytest.importorskip` before importing Torch or SentencePiece, so the deterministic job skips them when those packages are absent. The torch job installs both and executes them. Skipping them in the deterministic job is not a pass of the math or cache checks.

The other `tests/test_cursor_*.py` files do not import Torch. The deterministic job collects the whole `tests/` tree, so they run there.

## GitHub

The exact-head Actions URL is not available until this branch is pushed. It will be added to the handover when the run exists. A green badge on a different SHA is not evidence for this change.
