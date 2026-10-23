"""Authenticated product-path retrieval through AuthorizedIndex.

Canonical local retrieval for signed-in application requests is
`orca.truth.indexed_query.run_authorized_retrieval` on a session-bound
`AuthorizedIndex`. This module does not call `orca.rag_x.execute`, does
not treat `orneur.rag_x.synthetic_hash_v1` as a neural encoder, and does
not authorize native-model training.

Anonymous DocStore traffic is unchanged and is not an authorized index.
Retrieved text never grants tool execution (`tool_grant` stays false).

Binding contract
----------------
One product conversation has one binding record:

    ORCA_HOME/authorized_index/<user_id>/bindings/<product_session_id>.json

The record names exactly one index session directory under that user's
root. The user-id directory is a storage prefix, not an isolation
boundary: a caller who can read sibling directories can see other
conversations of the same user. This module never scans siblings and
never opens an index directory that the conversation's own record does
not name.

The record is written only after `AuthorizedIndex` has opened that
directory, under an exclusive lock. A crash before the record exists
leaves an orphan directory that no conversation opens. Revocation is the
`revoked: true` flag on that record plus the in-process session revoke.
A restart or another worker adopts the same index session id; it does
not mint a broader one. A missing record is `absent` (no document
grounding). A revoked record is `revoked` (refuse). Neither case falls
through to the legacy store.

Prompt contract: a passage enters model context only when this
conversation's index still replays it and the product registry lists
that document. Disagreement between the index and the legacy store
drops the passage. It does not widen authority.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from orca.docs.authorized_index import AuthorizedIndex
from orca.truth.access import AccessDenied, SessionAuthority, TrustedSession
from orca.truth.indexed_query import AuthorizedAnswer, fact_conflicts, run_authorized_retrieval

_DOCUMENT_REFERENCE = re.compile(
    r"\b(documents?|uploaded|upload|attachments?|files?|pdfs?|summarize|summarise|summary)\b",
    re.I,
)

_LOCK = threading.RLock()
_AUTHORITY = SessionAuthority()
_BINDINGS: dict[tuple[str, str], "_Binding"] = {}
_DOC_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_RECORD_LIMIT = 8192


class ProductRetrievalDenied(PermissionError):
    """Authenticated product retrieval was refused by the authorized index."""

    def __init__(self, reason: str, *, code: str = "denied"):
        self.reason = reason
        self.code = code
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


def _passage_identity(stored_name: str) -> tuple[str | None, str]:
    match = _DOC_ID.match(stored_name or "")
    if match is None:
        return None, stored_name or ""
    doc_id = match.group(0)
    rest = stored_name[len(doc_id):]
    if rest.startswith("-") and len(rest) > 1:
        return doc_id, rest[1:]
    return doc_id, stored_name


@contextmanager
def _binding_lock(user_id: str, product_session_id: str):
    from orca.config import _mkdir_owner_only

    directory = _mkdir_owner_only(_root_for_user(user_id) / "bindings")
    name = _safe_component(product_session_id)
    fd = os.open(directory / f"{name}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield directory / f"{name}.json"
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _read_record(path: Path, key: tuple[str, str]) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProductRetrievalDenied("binding record cannot be opened", code="denied") from exc
    try:
        raw = os.read(fd, _RECORD_LIMIT + 1)
    finally:
        os.close(fd)
    if len(raw) > _RECORD_LIMIT:
        raise ProductRetrievalDenied("binding record is too large", code="denied")
    try:
        payload = json.loads(raw.decode())
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductRetrievalDenied("binding record is not valid", code="denied") from exc
    if not isinstance(payload, dict):
        raise ProductRetrievalDenied("binding record is not valid", code="denied")
    if payload.get("user_id") != key[0] or payload.get("product_session_id") != key[1]:
        raise ProductRetrievalDenied("binding record does not match this conversation", code="denied")
    session_id = payload.get("index_session_id")
    if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise ProductRetrievalDenied("binding record has no index session", code="denied")
    revoked = payload.get("revoked")
    if revoked not in (True, False):
        raise ProductRetrievalDenied("binding record revocation flag is not boolean", code="denied")
    return {
        "user_id": key[0],
        "product_session_id": key[1],
        "index_session_id": session_id,
        "revoked": revoked,
    }


def _write_record(path: Path, payload: dict) -> None:
    if path.is_symlink():
        raise ProductRetrievalDenied("binding record is a symlink", code="denied")
    raw = json.dumps(payload, separators=(",", ":")).encode()
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _close_quietly(index: AuthorizedIndex | None) -> None:
    if index is None:
        return
    try:
        index.close()
    except Exception:
        pass


def _load_binding(user_id: str, product_session_id: str, *, create: bool) -> _Binding:
    key = (_safe_component(user_id), _safe_component(product_session_id))
    with _LOCK:
        with _binding_lock(key[0], key[1]) as record_path:
            existing = _BINDINGS.get(key)
            if existing is not None and _AUTHORITY.is_current(existing.trusted) and existing.index.permits(existing.trusted):
                return existing
            if existing is not None:
                _close_quietly(existing.index)
                _BINDINGS.pop(key, None)
            record = _read_record(record_path, key)
            if record is not None and record["revoked"]:
                raise ProductRetrievalDenied("authorized session is revoked", code="revoked")
            if record is not None:
                trusted = _AUTHORITY.adopt(record["index_session_id"], f"user:{key[0]}", key[0])
                index = AuthorizedIndex(_AUTHORITY, trusted, _root_for_user(key[0]))
                binding = _Binding(trusted=trusted, index=index, user_id=key[0], product_session_id=key[1])
                _BINDINGS[key] = binding
                return binding
            if not create:
                raise ProductRetrievalDenied(
                    "no authorized index is bound for this authenticated session",
                    code="absent",
                )
            trusted = _AUTHORITY.issue(f"user:{key[0]}", key[0])
            index = None
            try:
                index = AuthorizedIndex(_AUTHORITY, trusted, _root_for_user(key[0]))
                _write_record(record_path, {
                    "version": 1,
                    "user_id": key[0],
                    "product_session_id": key[1],
                    "index_session_id": trusted.session_id,
                    "revoked": False,
                })
            except Exception:
                _close_quietly(index)
                _AUTHORITY.revoke(trusted)
                raise
            binding = _Binding(trusted=trusted, index=index, user_id=key[0], product_session_id=key[1])
            _BINDINGS[key] = binding
            return binding


def bind(user_id: str, product_session_id: str) -> _Binding:
    """Open or create the trusted session bound to this one conversation."""
    return _load_binding(user_id, product_session_id, create=True)


def admit_uploaded_document(user_id: str, product_session_id: str, *, filename: str, text: str, doc_id: str) -> str:
    binding = bind(user_id, product_session_id)
    try:
        return binding.index.admit(binding.trusted, _admissible_filename(filename, doc_id), text)
    except AccessDenied as exc:
        raise ProductRetrievalDenied(getattr(exc, "reason", str(exc)), code="denied") from exc


def delete_uploaded_document(user_id: str, product_session_id: str, *, filename: str, doc_id: str) -> int:
    try:
        binding = _load_binding(user_id, product_session_id, create=False)
    except ProductRetrievalDenied as exc:
        if exc.code == "absent":
            return 0
        raise
    try:
        return binding.index.delete(binding.trusted, _admissible_filename(filename, doc_id))
    except AccessDenied as exc:
        raise ProductRetrievalDenied(getattr(exc, "reason", str(exc)), code="denied") from exc


def retrieve_authorized(user_id: str, product_session_id: str, query: str) -> AuthorizedAnswer:
    binding = _load_binding(user_id, product_session_id, create=False)
    try:
        answer = run_authorized_retrieval(binding.trusted, binding.index, query)
    except AccessDenied as exc:
        raise ProductRetrievalDenied(getattr(exc, "reason", str(exc)), code="denied") from exc
    if answer.hits or not _DOCUMENT_REFERENCE.search(query or ""):
        return answer
    try:
        passages = binding.index.listed_passages(binding.trusted, limit=5)
    except AccessDenied as exc:
        raise ProductRetrievalDenied(getattr(exc, "reason", str(exc)), code="denied") from exc
    if not passages:
        return answer
    conflicts = fact_conflicts([hit.text for hit in passages])
    return AuthorizedAnswer(
        query=answer.query,
        tenant_id=answer.tenant_id,
        principal_id=answer.principal_id,
        hits=tuple(passages),
        evidence=(),
        sources=(),
        abstained=bool(conflicts),
        contradictions=tuple(conflicts),
        claim_support=None,
        tool_grant=False,
        partial_reasons=tuple(answer.partial_reasons) + ("lexical miss; enumerated this conversation's authorized passages",),
        method="authorized-enumeration",
        dense_backend=answer.dense_backend,
        production_neural=False,
        judge_consulted=False,
        ignored_claims=answer.ignored_claims,
    )


def model_context_from_authorized(user_id: str, product_session_id: str, answer: AuthorizedAnswer | None):
    """Passages that may enter a model prompt for this conversation.

    Returns None when there is nothing to ground on: no answer, no hits,
    a contradiction, a passage the index will not replay, or a passage
    whose document was never committed to this conversation's registry.
    None means an ordinary ungrounded answer, not a legacy-store fallback.
    """
    if answer is None or answer.abstained or not answer.hits:
        return None
    from orca.docs.pipeline import RAGResult
    from orca.docs.store import list_docs

    binding = _load_binding(user_id, product_session_id, create=False)
    if not binding.index.permits(binding.trusted):
        raise ProductRetrievalDenied("authorized session is revoked", code="revoked")
    registered = {row.get("doc_id") for row in list_docs(product_session_id)}
    dna: dict = {}
    lines: list[str] = []
    names: list[str] = []
    for hit in answer.hits:
        if not binding.index.replay(binding.trusted, hit.content_sha256, hit.text):
            continue
        doc_id, filename = _passage_identity(hit.filename)
        if not doc_id or doc_id not in registered:
            continue
        ref = f"D{len(dna) + 1}"
        dna[ref] = {
            "text": hit.text,
            "chunk_idx": hit.chunk_idx,
            "filename": filename,
            "doc_id": doc_id,
            "content_sha256": hit.content_sha256,
        }
        names.append(filename)
        lines.append(
            f"[{ref}] filename={filename} chunk={hit.chunk_idx} sha256={hit.content_sha256} doc_id={doc_id}\n{hit.text}"
        )
    if not dna:
        return None
    result = RAGResult(
        context_block="\n\n".join(lines),
        citation_dna=dna,
        sources=names,
        contradictions=list(answer.contradictions),
        sufficiency_confidence=0.0,
        retrieval_rounds=1,
        used_fallback=False,
    )
    result.authorized_method = answer.method
    result.production_neural = bool(answer.production_neural)
    result.tool_grant = False
    return result


def revoke(user_id: str, product_session_id: str) -> None:
    """Revoke this conversation's trusted session on disk and in this process.

    The durable flag is written first. A crash after that write still
    fails closed on the next open. This does not revoke any other
    conversation, and it does not grant a replacement session.
    """
    key = (_safe_component(user_id), _safe_component(product_session_id))
    with _LOCK:
        with _binding_lock(key[0], key[1]) as record_path:
            record = _read_record(record_path, key)
            binding = _BINDINGS.get(key)
            if record is None and binding is None:
                return
            if record is not None:
                record = {**record, "version": 1, "revoked": True}
                _write_record(record_path, record)
            elif binding is not None:
                _write_record(record_path, {
                    "version": 1,
                    "user_id": key[0],
                    "product_session_id": key[1],
                    "index_session_id": binding.trusted.session_id,
                    "revoked": True,
                })
            if binding is not None:
                _AUTHORITY.revoke(binding.trusted)


def drop_process_state_for_tests() -> None:
    """Drop in-process sessions without deleting index directories or binding files.

    The next open rehydrates from the binding record. Use this to simulate
    a restart or a second worker. `reset_for_tests` is the same memory
    drop; neither helper deletes authority on disk.
    """
    with _LOCK:
        for binding in _BINDINGS.values():
            _close_quietly(binding.index)
        _BINDINGS.clear()
        _AUTHORITY._records.clear()


def reset_for_tests() -> None:
    drop_process_state_for_tests()
