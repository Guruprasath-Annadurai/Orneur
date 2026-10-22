# Independent audit handoff

This note is not an audit.

Review branch: `cursor/foundation-x-rag-x-4e55`, based on `fc1eb1dd098377e8506485dbcd82d6ed148b52b3`.

The progress-database correction is on PR #80 at that base commit. Its local command was `python3 -m pytest tests/test_cursor_progress_db_portability.py tests/test_cursor_pipeline_admission.py tests/test_genesis_data_pipeline.py tests/test_audit_genesis_hardening_remediation.py` (69 passed). Darwin `F_GETPATH` was not executed. SQLite 3.45 on Linux still resolves the directory-descriptor URI to a real path for WAL siblings; the code checks the inode and refuses symlink sidecars.

The new kernel and lifecycle code are `orca/rag_x/` and `orca/foundation_x/`. Local command: `python3 -m pytest tests/test_rag_x_foundation.py` (16 passed). The capability classes are `orca/rag_x/matrix.py`.

Please challenge, at the exact head SHA of the draft pull request:

- Tenant, workspace, principal, revocation, and connector filtering.
- Raw SQL rejection and row tenant filters.
- Claim span checks, summary authority, and contradiction handling.
- The X2 fixture size and the decision not to generalize it.
- Whether any prototype is described as a production method.
- Lifecycle fail-closed behavior and the refusal to start training.
- The absence of an application-path test through PR #79 or PR #81.
- Acceptance numerator remaining 0.

A pass, conditional pass, partial, or fail from the reviewer is acceptable. This author report's own verdict is partial.
