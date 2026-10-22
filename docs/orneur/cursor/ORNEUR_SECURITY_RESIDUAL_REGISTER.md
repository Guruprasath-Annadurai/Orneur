# Security residual register

This branch does not reopen the GENESIS checkpoint confinement fixes. Those files were not edited.

| Item | State after this branch | Residual |
|---|---|---|
| Checkpoint path confinement, cross-run migration off, local anti-rollback ledger | Unchanged on the base (`97582a94`) | Ledger is local. A party who can replace both the checkpoint and the ledger still needs the integrity key for the HMAC. External anchoring is not implemented. |
| External anti-rollback anchor | `FailClosedExternalAnchor` raises `AnchorUnavailable`. `SyntheticAnchorDouble.kind` is `SYNTHETIC_TEST_DOUBLE`. | No witness service exists. The double is not production. |
| Derived block-store cache | Keyed HMAC mode when the caller passes a 32-byte key. `CacheIntegrityKey` keeps the raw key out of `repr`, `str`, `format`, `bytes()`, pickle, and `json` default conversion. | Unkeyed mode is still the default and still loses to a writer who updates the store and the sidecar together. The key is still caller-supplied. This module does not mint one. |
| Corpus pathname substitution | Reproduced: a pre-planted `shard-*.jsonl` symlink was followed and corpus bytes were appended outside `output_dir`. Shard, lock, and input-leaf opens now use `O_NOFOLLOW` on a directory fd. A stored shard path whose leaf is outside the output directory is not opened. | With `allowed_root` unset, ancestor symlinks above the input leaf are still followed. SQLite reopens the progress database by its real path after the no-follow open. This is not a kernel sandbox. |
| Agent idempotency and task identity | A replay returns the existing task id only for the same agent and the same handler, payload, dependencies, parent, cost, and timeout. A new idempotency key cannot reuse an existing task id. `TaskIdentityConflict` does not name the current owner. | Any holder of the in-process `Orchestrator` can still read `tasks` and `idempotency`. This is not an OS privilege boundary. |
| Optimizer state on restore | Non-finite and wrong-shape moments fail closed. | Equal-shaped moment substitution is left to the checkpoint HMAC. |
| Same-uid worker | Unchanged. Labels in `isolated_worker.py` already say same-uid is not a privilege boundary. | Process separation is not a kernel sandbox. Distinct uid still requires a reviewed drop, and default CI does not run as root. |
| Training authorization | Untouched. | Still not granted. |
| Acceptance ledger | Untouched. | Numerator remains 0. |

No security check was removed or weakened to obtain a pass.
