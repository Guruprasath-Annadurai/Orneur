# Security residual register

This branch does not reopen the GENESIS checkpoint confinement fixes. Those files were not edited.

| Item | State after this branch | Residual |
|---|---|---|
| Checkpoint path confinement, cross-run migration off, local anti-rollback ledger | Unchanged on the base (`97582a94`) | Ledger is local. A party who can replace both the checkpoint and the ledger still needs the integrity key for the HMAC. External anchoring is not implemented. |
| External anti-rollback anchor | `FailClosedExternalAnchor` raises `AnchorUnavailable`. `SyntheticAnchorDouble.kind` is `SYNTHETIC_TEST_DOUBLE`. | No witness service exists. The double is not production. |
| Derived block-store cache | Keyed HMAC mode when the caller passes a 32-byte key. | Unkeyed mode is still the default and still loses to a writer who updates the store and the sidecar together. |
| UTF-8 and symlink corpus input | Rejected or counted, as documented in the data note. | Ancestor-symlink confinement is only applied when `allowed_root` is set. The check is not a kernel sandbox. |
| Optimizer state on restore | Non-finite and wrong-shape moments fail closed. | Equal-shaped moment substitution is left to the checkpoint HMAC. |
| Same-uid worker | Unchanged. Labels in `isolated_worker.py` already say same-uid is not a privilege boundary. | Process separation is not a kernel sandbox. Distinct uid still requires a reviewed drop, and default CI does not run as root. |
| Training authorization | Untouched. | Still not granted. |
| Acceptance ledger | Untouched. | Numerator remains 0. |

No security check was removed or weakened to obtain a pass.
