"""Exceptions for the backup / restore / deletion-ledger tooling. Standard library only: the server imports this (and ``datadir_lock``) at start-up, and the production image does
not install ``cryptography``."""
from __future__ import annotations


class BackupError(Exception):
    """Base class: every refusal in the backup tooling is one of these (never a raw library exception)."""


class BackupKeyError(BackupError):
    """The key is missing, malformed, or stored unsafely."""


class BackupAuthError(BackupError):
    """The archive failed authentication: wrong key, modified, truncated or not an ORNEUR backup."""


class BackupIncompleteError(BackupError):
    """The archive authenticated but is not a complete, consistent backup."""


class DeletionHistoryUnavailable(BackupError):
    """No authoritative record of later deletions is available, so restoring could silently bring deleted customer data back."""


class RestoreFailed(BackupError):
    """Restore stopped; the target directory is unchanged (or was rolled back)."""


class LedgerIntegrityError(BackupError):
    """The ledger file does not form a valid chain (removed/edited/reordered/forged/empty): it cannot be trusted as deletion history."""


class BackupDependencyMissing(BackupError):
    """The optional ``cryptography`` package is not installed, so encrypted backup / restore cannot run."""
