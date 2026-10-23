"""Authenticated product-path retrieval through AuthorizedIndex.

Canonical local retrieval for signed-in application requests is
`orca.truth.indexed_query.run_authorized_retrieval` on a session-bound
`AuthorizedIndex`. This module does not call `orca.rag_x.execute`, does
not treat `orneur.rag_x.synthetic_hash_v1` as a neural encoder, and does
not authorize native-model training.

Anonymous DocStore traffic is unchanged and is not an authorized index.
TrustedSession tokens are in-process only and are not serializable; a
process restart requires a fresh bind. That limitation is recorded, not
papered over.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from orca.docs.authorized_index import AuthorizedIndex
from orca.truth.access import AccessDenied, SessionAuthority, TrustedSession
from orca.truth.indexed_query import AuthorizedAnswer, run_authorized_retrieval

_LOCK = threading.RLock()
_AUTHORITY = SessionAuthority()
_BINDINGS: dict[tuple[str, str], "_Binding"] = {}


class ProductRetrievalDenied(PermissionError):
    """Authenticated product retrieval was refused by the authorized index."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class _Binding:
    trusted: TrustedSession
    index: AuthorizedIndex
    user_id: str
    product_session_id: str


def _safe_component(value: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or value in {".", ".."} or "\x00" in value:
        raise ProductRetrievalDenied("identity is not a single directory component")
    return value


def _root_for_user(user_id: str) -> Path:
    import orca.config as orca_config
    from orca.config import _mkdir_owner_only
    root = orca_config.ORCA_HOME / "authorized_index" / _safe_component(user_id)
    return _mkdir_owner_only(root, parents=True)


def _admissible_filename(filename: str, doc_id: str) -> str:
    base = Path(filename).name if isinstance(filename, str) else ""
    if not base or "/" in base or "\x00" in base:
        return f"{_safe_component(doc_id)}.txt"
    return f"{_safe_component(doc_id)}-{base}"


def bind(user_id: str, product_session_id: str) -> _Binding:
    """Issue or reuse the in-process trusted session for this product session."""
    key = (_safe_component(user_id), _safe_component(product_session_id))
    with _LOCK:
        existing = _BINDINGS.get(key)
        if existing is not None and _AUTHORITY.is_current(existing.trusted) and existing.index.permits(existing.trusted):
            return existing
        trusted = _AUTHORITY.issue(f"user:{key[0]}", key[0])
        index = AuthorizedIndex(_AUTHORITY, trusted, _root_for_user(key[0]))
        binding = _Binding(trusted=trusted, index=index, user_id=key[0], product_session_id=key[1])
        _BINDINGS[key] = binding
        return binding


def admit_uploaded_document(user_id: str, product_session_id: str, *, filename: str, text: str, doc_id: str) -> str:
    binding = bind(user_id, product_session_id)
    try:
        return binding.index.admit(binding.trusted, _admissible_filename(filename, doc_id), text)
    except AccessDenied as exc:
        raise ProductRetrievalDenied(getattr(exc, "reason", str(exc))) from exc


def delete_uploaded_document(user_id: str, product_session_id: str, *, filename: str, doc_id: str) -> int:
    key = (_safe_component(user_id), _safe_component(product_session_id))
    with _LOCK:
        binding = _BINDINGS.get(key)
    if binding is None:
        return 0
    try:
        return binding.index.delete(binding.trusted, _admissible_filename(filename, doc_id))
    except AccessDenied as exc:
        raise ProductRetrievalDenied(getattr(exc, "reason", str(exc))) from exc


def retrieve_authorized(user_id: str, product_session_id: str, query: str) -> AuthorizedAnswer:
    key = (_safe_component(user_id), _safe_component(product_session_id))
    with _LOCK:
        binding = _BINDINGS.get(key)
    if binding is None:
        raise ProductRetrievalDenied("no authorized index is bound for this authenticated session")
    try:
        return run_authorized_retrieval(binding.trusted, binding.index, query)
    except AccessDenied as exc:
        raise ProductRetrievalDenied(getattr(exc, "reason", str(exc))) from exc


def revoke(user_id: str, product_session_id: str) -> None:
    """Test and incident-response helper: revoke the trusted session in-process."""
    key = (_safe_component(user_id), _safe_component(product_session_id))
    with _LOCK:
        binding = _BINDINGS.get(key)
        if binding is None:
            return
        _AUTHORITY.revoke(binding.trusted)


def reset_for_tests() -> None:
    with _LOCK:
        for binding in _BINDINGS.values():
            try:
                binding.index.close()
            except Exception:
                pass
        _BINDINGS.clear()
        _AUTHORITY._records.clear()
