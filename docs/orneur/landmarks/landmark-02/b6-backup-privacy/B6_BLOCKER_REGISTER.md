# L02-B6 — blocker and limitation register (after the corrective pass)

States: `FIXED` = engineering-verified here; `BLOCKED` = needs a founder-controlled decision or external infrastructure, nothing simulated; `OPEN` = known, accepted, documented. Nothing is independently qualified.

## Defects found and closed
| ID | Sev | Finding | State |
|---|---|---|---|
| B6-1 | P1 | backups readable in plaintext; loose file modes | FIXED (encrypted archive, 0600) |
| B6-2 | P1 | older backup resurrected later-deleted data | FIXED (deletion ledger + export; refuses without history) |
| B6-3 | P1 | interrupted restore left a mixed directory | FIXED (staged, journalled, rolled back, readiness gate) |
| B6-4 | P2 | unauthenticated manifest; no completeness check; raw errors; unlisted files | FIXED |
| B6-5 | P2 | deleted text left in freed database pages after restore | FIXED (secure_delete + VACUUM on staged copies) |
| **B6-6** | **P1** | **legacy bypass: `orca/ops/backup.py`, `orca backup`, `orca restore` still wrote plaintext accounts backups and restored them without deletion history** (missed in the first B6 delivery, which overstated closure) | **FIXED** — all entry points refuse; offline `import-legacy`; 4/4 reproduced then closed |
| B6-7 | P2 | ledger accepted when removed/re-created, truncated to empty, with forged lines | FIXED (chain + genesis lineage + manifest/export comparison) |
| B6-8 | P2 | recovery journal trusted blindly (path escape → arbitrary delete/move) | FIXED (validation; symlink not followed) |
| B6-9 | P2 | restored files inherited loose permissions | FIXED (0700/0600) |
| B6-10 | P2 | two restores, or a restore under a running server (and the reverse) could overlap | FIXED (flock; advisory, local filesystem) |

| B6-11 | P1 | the server (lifespan, `/readyz`) and every deletion path imported `cryptography`, which the production image does not install: server would not start, deletions would fail (found by CI on `e5266c7`) | FIXED (stdlib-only error/lock/ledger modules; lazy KDF import; clear CLI message) |

## BLOCKED — founder / external decisions
| ID | Item | Why it cannot be closed in code |
|---|---|---|
| **B6-B1** | **Key custody** (where keys live, copies, rotation, escrow, who may restore) | a custody policy, not an engineering choice; loss of the key makes every archive unrecoverable by design |
| **B6-B2** | **Retention and destruction of historical backups; immutable / off-host storage** | an offline copy cannot be altered by a live deletion; only the holder can destroy it. No erasure of offline copies is claimed |
| **B6-B3** | **Off-host anchoring of the deletion ledger** (WORM storage, second host, signed external log) | the only way to make *completeness* of deletion history verifiable. Without it a consistent rewrite of the ledger, or deletions after the newest copy kept elsewhere, are undetectable. Nothing was simulated |
| B6-B5 | Whether the production image should include the `backup` extra (`cryptography`) so encrypted backups can run inside the container | changes the image's dependency surface and supply-chain review; not done. Until decided, backups run from a separate environment with `pip install 'orneur[backup]'`; the container cannot create or restore one |
| B6-B4 | Postgres plaintext dumps (`*.pgdump`) | no automated, verifiable migration; manual offline procedure and retention decision (see `B6_LEGACY_MIGRATION.md`) |

## OPEN — accepted limitations
| ID | Sev | Limitation |
|---|---|---|
| B6-L1 | P2 | the live ledger is an editable file: hash-chained and compared with copies elsewhere, **not** tamper-proof, **not** authenticated, **not** independently authoritative; restore reports `completeness_verified: false` always |
| B6-L2 | P2 | restoring onto a new machine honours deletions only up to the newest export's time |
| B6-L3 | P3 | a forged but correctly chained ledger entry (someone with write access who knows the format) is accepted; its effect is limited to deleting data that the backup contains, and the previous contents are kept in `.pre-restore-*` for rollback |
| B6-L4 | P3 | opaque ids stay in the ledger after the data is deleted (no content, no email) |
| B6-L5 | P3 | the `flock` guard is advisory and local-filesystem only; a server started by a version without the lock is not detected |
| B6-L6 | P3 | vector-store files are consistent with the databases only if the server was stopped; documents' chunks and per-conversation memory of deleted items are removed by the existing sweeps/reconciler after start, not during restore |
| B6-L7 | P3 | `.pre-restore-*` rollback copies and the one-time `auth.db.pre-migration-*.bak` are plaintext on disk until the operator removes them; backup creation writes one database snapshot to a private scratch directory (removed, not wiped) |
| B6-L8 | P3 | not tested: very large data directories, a real KMS/HSM, NFS, two hosts |
