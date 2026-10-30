# L02-B6 — handoff to Antigravity for independent re-test

Status `VERIFIED_ENGINEERING` for the independently testable part; **not** independently qualified. Draft PR (this branch), base = PR #139 head `38e0d31`. Not merged, not deployed. PR #141, #139, #136, #140 untouched. Key custody, backup retention policy and immutable storage are founder decisions and are marked BLOCKED in `B6_BACKUP_PRIVACY_REPORT.md` §6.

## Try to break
| Attack | Expected |
|---|---|
| read customer data from an archive without the key (strings, SQLite header, emails) | nothing |
| flip any byte; truncate at any offset (incl. frame boundary); append; swap frames; empty / foreign file | `verify` ok=false; `restore` raises `BackupAuthError`; target unchanged |
| wrong key; no key; key mode 644; key inside the data dir or beside the archive | refused (`BackupKeyError` / `BackupAuthError`), CLI exit 2/1, nothing created |
| archive built with the right key but missing core DB / listing a missing file / extra file / bad hash / `../` path / reserved names | refused |
| delete a conversation, document, account after a backup; restore the older archive over live data | still deleted; other tenants intact; no deleted text in raw DB bytes |
| restore to a new directory with no ledger and no export | `DeletionHistoryUnavailable`; nothing created |
| old export / edited export (e.g. entries removed) / export under another key | refused |
| kill the process (or inject failures) at each swap step | previous bytes restored exactly, or journal left: `/readyz` 503 until `data-backup recover` |
| file changes while being backed up | flagged `consistent: false`; restore refuses without `--allow-inconsistent` |
Not tried by us: a forged ledger line appended on the live system by someone with write access to the data directory (that actor can already read the data); racing two restores; restoring while the server runs; clock changes affecting the export freshness check; tampering with the journal file between crash and recover.

## Reproduce
```
cp docs/orneur/landmarks/landmark-02/b6-backup-privacy/evidence/b6_baseline_repro.py tests/ && git checkout 38e0d31 -- orca/serve/backup.py   # baseline: 8 failed
pytest tests/test_l02_b6_backup.py tests/test_l02_operational.py -p no:cacheprovider                                                      # 46 + 13 passed
pytest tests/journey/test_l02_b6_backup_live.py -p no:cacheprovider                                                                         # real server + CLI
```
Review first: `orca/serve/backup.py` (`restore`, `_extract`, `_apply_deletions`, journal), `backup_crypto.py`, `deletion_ledger.py`, the three hook sites (`deletions.begin`, `account_delete.delete_account`, `docs/store.mark_doc_deleting`), the `/readyz` restore check in `orca/serve/api.py`, `orca/cli.py` (`data-backup`). Please record your verdict against the exact SHA in your own PR.

## Corrective pass — additional things to attack
| Attack | Expected |
|---|---|
| `orca backup`, `orca backup --keep 3`, `orca restore <file> --yes`, `orca.ops.backup.{backup_sqlite,backup_postgres,run_backup,restore_sqlite}` | refuse (exit 1 / `BackupError` naming `data-backup`); no file written, live database unchanged |
| find any other code path that writes a plaintext copy of accounts/conversations or restores one | none intended; known plaintext artefacts are listed in `B6_LEGACY_MIGRATION.md` (pre-migration `.bak`, `.pre-restore-*`) |
| `import-legacy` with source/output inside the live directory, while a server runs, with a non-SQLite or non-accounts file | refused; live directory untouched; original never deleted |
| restore a migrated legacy archive without a live ledger / export, or with an export older than the import | refused |
| remove the ledger, truncate it (empty, garbage, valid prefix), edit/reorder/forge lines, replace it with another system's | refused (chain / lineage / "behind the export") |
| a consistent rewrite of the whole ledger by someone who knows the format | accepted — **by design undetectable**; result reports `completeness_verified: false` (please confirm the claim is honest, and tell us if any message overstates) |
| tamper with `.restore-journal.json` (`../`, absolute, nested, wrong types, symlinked holding dir, loose mode) | `RestoreFailed`, directory stays flagged, nothing outside the data directory touched |
| restored modes; two simultaneous restores; restore while a server runs; start a server during a restore | 0700/0600; "another restore is in progress"; "a server is running"; "a restore is in progress" |
Not tried by us: NFS or other filesystems where `flock` is unreliable; processes started by an older version (no lock); racing the lock acquisition from many processes at the millisecond level; huge data directories.
Reproduce: `pytest tests/test_l02_b6_corrective.py tests/test_l02_b6_backup.py tests/test_ops_backup.py tests/test_l02_operational.py`; live: `pytest tests/journey/test_l02_b6_backup_live.py`; red evidence: `evidence/b6c_*`. Legacy repro: copy `evidence/b6c_legacy_bypass_repro.py` into `tests/` and run it against `b1c56b9` (4 fail) and against the new head (it is expected to pass the same assertions).
