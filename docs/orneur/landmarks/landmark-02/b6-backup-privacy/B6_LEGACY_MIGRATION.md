# L02-B6 — offline migration of pre-existing plaintext backups

Applies to files written by the retired `orca backup` (`ORNEUR_HOME/backups/auth_backup_*.db`, SQLite) and `pg_dump` files (`auth_backup_*.pgdump`). The tools that wrote them
are retired: they refuse to run (`orca backup`, `orca restore`, `orca.ops.backup.backup_sqlite|backup_postgres|run_backup|restore_sqlite`). **Nothing imports a plaintext
backup into a live user-data directory, silently or otherwise.** A legacy file is an unencrypted copy of every account (emails, password hashes, API-key hashes, audit log) as
of its date; treat each one as sensitive until it has been migrated and destroyed.

## SQLite files (`auth_backup_*.db`) — supported, offline only
1. **Stop the server** on the data directory. `import-legacy` refuses while a server holds it.
2. **Copy** the legacy file(s) to a working location *outside* the data directory (e.g. an encrypted volume or a temporary directory you control). The command refuses a source or
   output inside the live directory.
3. Provision the backup key as for any backup (`orca data-backup keygen`, operator custody; see the report's BLOCKED items). Test-only keys for rehearsals.
4. `orca data-backup import-legacy <copy-of-legacy.db> <out>.orbk --key-file <key>` — the file is opened read-only, must pass `integrity_check` and contain a `users` table, and is
   written into a new encrypted, authenticated archive (`origin: legacy_plaintext_import`, accounts database only). The live directory is neither read nor written.
5. `orca data-backup verify <out>.orbk --key-file <key>`.
6. **Destroy the plaintext original and every copy** (including the one from step 2), on every medium you control. The tool never deletes it for you. `orca backups` lists any
   remaining legacy files in `ORNEUR_HOME/backups`; `orca.ops.backup.prune_old_backups` can remove them from that directory. Deletion from a filesystem is not secure erasure;
   snapshots, replicas and off-host copies of the plaintext are outside anything this tool can reach.

## How a migrated archive behaves on restore
It goes through the **normal** `orca data-backup restore`, with every protection: authentication, staging, deletion-history requirement (a live ledger in the target or an
authenticated export), re-application of deletions (deleted accounts are removed from the restored accounts database), health check, journalled swap, rollback.
Differences, all conservative: its creation time is the **import** time, so a deletion-history export generated *before* the import is refused; it records **no ledger lineage**
(nothing proves how a years-old accounts file relates to today's ledger), so the lineage/continuity check cannot run and the restore result states that completeness is not
verified; it contains only the accounts database, so conversations/documents are not restored from it.

## Postgres dumps (`auth_backup_*.pgdump`) — NOT migrated by this tool (BLOCKED / manual)
No automated path exists, deliberately: restoring a dump needs a PostgreSQL server and cannot be verified here. If you must keep one: restore it only into a **scratch, offline**
database that is not the production database, export what you need, create an encrypted archive from that export yourself, then destroy the dump, the scratch database and its
storage. Do not `pg_restore` over production: it would bring back deleted accounts. Choosing to keep such dumps at all is a founder retention decision.

## Other plaintext copies you may find
`auth.db.pre-migration-<time>-<pid>.bak` (mode 0600) is written beside `auth.db` once, by the schema upgrade, as a safety copy; it is a plaintext copy of the accounts database
that no deletion touches. It is not produced by the backup tools and was not changed here. Verify the upgrade, then destroy it. It *is* included (encrypted) in a new backup.
