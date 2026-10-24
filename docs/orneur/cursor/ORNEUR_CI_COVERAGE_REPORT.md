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

Verified head: `3185d0a4760d9cf43b66353e1bb2fd2e99108958`.

That commit records the implementation SHA. The code under test is `4398150a41af424e1d04c7e83d314c6ef4b1ca17`. A green badge on a different SHA, including base run `39759240669`, is not evidence for this diff.

Run: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39773008463

Event: push. Conclusion: success. Created 22 October 2026, 17:15 Asia/Calcutta. Completed 22 October 2026, 17:32 Asia/Calcutta. Nine jobs, all success.

| Job | Result |
|---|---|
| Deterministic Unit Tests (`119804937373`) | success. `8948 passed, 389 skipped, 43 deselected, 7 xfailed` in 1011.25s. |
| Dependency Vulnerability Scan (informational, base install only) | success |
| Genesis V2 Security (encryption tests must execute) | success |
| RSE dependency lock and vulnerability scan | success |
| SSE Diagnostics (browser-loaded module, zero payload leakage) | success |
| Genesis V2 Sandbox (containment tests must execute) | success |
| Training Math Unit Tests (Torch) (`119804937804`) | success. `549 passed, 3 deselected` in 263.84s. |
| Production Container Build + Boot Smoke | success |
| RSE Docker Synthetic Integration Lab (bounded, exit-code enforced) | success |

The three deselections in the torch job are the pre-existing audit #077 vulnerability demonstrations named in `.github/workflows/test.yml`. They are not cursor tests.

In that torch job, every case in `tests/test_cursor_training_math.py`, `tests/test_cursor_keyed_cache.py`, and `tests/test_cursor_tokenizer_multilingual.py` passed (27 cases).

In the deterministic job, the non-torch cursor files produced 53 `PASSED` lines: pipeline admission, tokenizer robustness, model family, eval integrity, external anchor, agent orchestration, fault injection, and compute scenarios. The three torch files did not appear as executed cases in that log. They run in the torch job.

No assertion was weakened to obtain this result. Acceptance remains `pretraining=95 numerator=0`.
