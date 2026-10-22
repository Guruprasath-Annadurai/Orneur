# Independent audit handoff

This note is not an audit.

Review branch: `cursor/foundation-x-rag-x-4e55`, based on `fc1eb1dd098377e8506485dbcd82d6ed148b52b3`.

The progress-database correction is on PR #80 at that base commit. Exact-head Linux CI: https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39840961482 (9/9 success). Darwin `F_GETPATH` was not executed and remains a qualification blocker. SQLite 3.45 on Linux still resolves the directory-descriptor URI to a real path for WAL siblings; the code checks the inode and refuses symlink sidecars.

Canonical retrieval added after the research kernel: `orca/truth/access.py`, `orca/docs/authorized_index.py`, `orca/docs/sparse.py`, `orca/truth/indexed_query.py`, and the `access` argument on `TruthFabric.assess_evidence`. `orca/rag_x` remains a research kernel. Its previous head `81e4e31` is green at https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39843423059 and does not cover the integration commit. Local commands include `python3 -m pytest tests/test_truth_authorized_index.py tests/test_rag_x_foundation.py`. The capability classes in `orca/rag_x/matrix.py` still describe the research kernel, not a production certification of all 38 techniques.

Please challenge, at the exact head SHA of the draft pull request:

- Tenant, workspace, principal, revocation, and connector filtering.
- Raw SQL rejection and row tenant filters.
- Claim span checks, summary authority, and contradiction handling.
- The X2 fixture size and the decision not to generalize it.
- Whether any prototype is described as a production method.
- Whether a `FOUNDER_GRANT` string can still complete the lifecycle. It must not.
- Whether hash embeddings are described as neural retrieval. They must not.
- Lifecycle fail-closed behavior and the refusal to start training.
- The absence of an application-path test through PR #79 or PR #81.
- Acceptance numerator remaining 0.

A pass, conditional pass, partial, or fail from the reviewer is acceptable. This author report's own verdict is partial.
