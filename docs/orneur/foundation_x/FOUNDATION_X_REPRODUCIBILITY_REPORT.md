# Reproducibility

This session did not re-run the torch training-math job. Those tests remain on the foundation branch and were last green in CI for `b5230a0960d4686b1e5982f20a79208dec365088` at https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39802379378. That run is not evidence for later commits.

What this session executed:

- Progress-database portability on Linux, including WAL and `synchronous=FULL`, in `tests/test_cursor_progress_db_portability.py`. Darwin `F_GETPATH` was not executed.
- `tests/test_rag_x_foundation.py`: 16 passed. Hash embeddings and BM25 are deterministic for the same text.
- Acceptance register: `pretraining=95 numerator=0 application=3 execution=2 post=1`.

Numerical tolerance for the new lifecycle and digest checks is exact string or digest equality. No GPU parity number was measured. `GPU_REQUIRED_NOT_RUN` in `orca/foundation_x/scaling.py` lists the accelerator checks that were not run.
