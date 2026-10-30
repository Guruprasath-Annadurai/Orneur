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
