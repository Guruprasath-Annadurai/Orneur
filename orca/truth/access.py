"""Trusted retrieval sessions.

A caller-supplied tenant string is not a session. Only `SessionAuthority.issue`
mints a `TrustedSession`, and only a session that this authority still
recognizes can pass `is_current`.
"""
from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field


class AccessDenied(PermissionError):
    """The caller has no current trusted session for this store."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


_SEAL = object()


@dataclass(frozen=True)
class TrustedSession:
    tenant_id: str
    principal_id: str
    session_id: str
    token: str = field(repr=False)
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise AccessDenied("session was not issued by SessionAuthority")

    def __reduce__(self):
        raise TypeError("a TrustedSession cannot be copied or serialized")


@dataclass
class _Record:
    tenant_id: str
    principal_id: str
    token: str
    revoked: bool = False


class SessionAuthority:
    """In-process issuer. This is not an enterprise identity provider."""

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}

    def issue(self, tenant_id: str, principal_id: str) -> TrustedSession:
        if not isinstance(tenant_id, str) or not tenant_id or not isinstance(principal_id, str) or not principal_id:
            raise AccessDenied("tenant and principal are required to issue a session")
        session_id = secrets.token_hex(16)
        token = secrets.token_hex(32)
        self._records[session_id] = _Record(tenant_id, principal_id, token)
        return TrustedSession(tenant_id, principal_id, session_id, token, _seal=_SEAL)

    def revoke(self, session: TrustedSession) -> None:
        record = self._records.get(getattr(session, "session_id", ""))
        token = getattr(session, "token", "")
        if record is None or not isinstance(token, str):
            return
        try:
            matches = hmac.compare_digest(record.token, token)
        except (TypeError, ValueError):
            return
        if matches:
            record.revoked = True

    def is_current(self, candidate: object) -> bool:
        if not isinstance(candidate, TrustedSession):
            return False
        if candidate._seal is not _SEAL:
            return False
        record = self._records.get(candidate.session_id)
        if record is None or record.revoked:
            return False
        if record.tenant_id != candidate.tenant_id or record.principal_id != candidate.principal_id:
            return False
        try:
            return hmac.compare_digest(record.token, candidate.token)
        except (TypeError, ValueError):
            return False
