"""Trusted retrieval sessions.

A caller-supplied tenant string is not a session. Only `SessionAuthority.issue`
mints a new `TrustedSession`, and only a session that this authority still
recognizes can pass `is_current`. `adopt` reopens one already-issued session
id for this process. It does not scan other sessions, does not clear a
revocation, and does not accept an id this authority did not format.
"""
from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass, field

_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")


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

    def adopt(self, session_id: str, tenant_id: str, principal_id: str) -> TrustedSession:
        """Reopen one existing session id in this process.

        A live matching record returns the session this process already holds.
        A revoked record stays revoked. A different tenant or principal is
        refused. An unknown id receives a new token for that id only — the
        caller must already have decided the id is the one bound to this
        conversation. This does not look at sibling directories.
        """
        if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
            raise AccessDenied("session id is not an issued identifier")
        if not isinstance(tenant_id, str) or not tenant_id or not isinstance(principal_id, str) or not principal_id:
            raise AccessDenied("tenant and principal are required to adopt a session")
        record = self._records.get(session_id)
        if record is not None:
            if record.revoked:
                raise AccessDenied("trusted session is revoked")
            if record.tenant_id != tenant_id or record.principal_id != principal_id:
                raise AccessDenied("trusted session belongs to a different principal")
            return TrustedSession(tenant_id, principal_id, session_id, record.token, _seal=_SEAL)
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
