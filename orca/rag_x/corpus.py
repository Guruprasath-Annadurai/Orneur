"""Synthetic authorized corpus.

Documents are visible only when tenant, workspace, principal, revocation,
and expiry all match the scope. A document body cannot change that decision.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from orca.rag_x.contracts import AuthorizedRetrievalScope

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    kind: str
    chunk_id: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    version_id: str
    text: str
    context_prefix: str = ""
    authoritative: bool = True
    parent_chunk_ids: tuple[str, ...] = ()
    language: str = "en"
    modality: str = "text"


@dataclass(frozen=True)
class Document:
    document_id: str
    version_id: str
    tenant_id: str
    workspace_id: str
    principals: frozenset[str]
    title: str
    chunks: tuple[Chunk, ...]
    valid_from: str
    valid_to: str | None = None
    superseded_by: str | None = None
    revoked: bool = False
    language: str = "en"
    modality: str = "text"
    provider_status: str = "available"
    domain: str = "technical"
    source_uri: str = ""
    observed_at: str = ""
    entities: tuple[tuple[str, str], ...] = ()
    symbols: tuple[SymbolRecord, ...] = ()
    rows: tuple[dict[str, str], ...] = ()
    memory_owner: str | None = None
    session_id: str | None = None
    deleted: bool = False

    @property
    def digest(self) -> str:
        body = "\n".join(chunk.text for chunk in self.chunks)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    kind: str
    tenant_id: str


@dataclass
class Corpus:
    documents: dict[tuple[str, str], Document] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    _cache: dict[tuple, tuple] = field(default_factory=dict)
    _epoch: int = 0
    log: list[str] = field(default_factory=list)

    def add(self, document: Document) -> None:
        self.documents[(document.document_id, document.version_id)] = document
        self._epoch += 1
        self._cache.clear()

    def revoke(self, document_id: str, version_id: str) -> None:
        current = self.documents[(document_id, version_id)]
        self.documents[(document_id, version_id)] = _replace(current, revoked=True)
        self._epoch += 1
        self._cache.clear()

    def delete_memory(self, document_id: str, version_id: str) -> None:
        current = self.documents[(document_id, version_id)]
        self.documents[(document_id, version_id)] = _replace(current, deleted=True)
        self._epoch += 1
        self._cache.clear()

    def visible(self, scope: AuthorizedRetrievalScope) -> list[Document]:
        key = (self._epoch, scope.tenant_id, scope.principal_id, scope.workspace_id, scope.session_id, scope.as_of)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        chosen: dict[str, Document] = {}
        for document in self.documents.values():
            if not _authorized(document, scope):
                continue
            previous = chosen.get(document.document_id)
            if previous is None or document.version_id > previous.version_id:
                chosen[document.document_id] = document
        rows = list(chosen.values())
        self._cache[key] = tuple(rows)
        return rows

    def redact(self, text: str) -> str:
        return _EMAIL.sub("[redacted-email]", text)


def _authorized(document: Document, scope: AuthorizedRetrievalScope) -> bool:
    if document.deleted or document.revoked:
        return False
    if document.tenant_id != scope.tenant_id:
        return False
    if document.workspace_id != scope.workspace_id:
        return False
    if scope.principal_id not in document.principals:
        return False
    if document.memory_owner is not None and document.memory_owner != scope.principal_id:
        return False
    if document.session_id is not None and document.session_id != scope.session_id:
        return False
    if document.valid_from and scope.as_of < document.valid_from:
        return False
    if document.valid_to is not None and scope.as_of >= document.valid_to:
        return False
    return True


def _replace(document: Document, **changes) -> Document:
    data = document.__dict__.copy()
    data.update(changes)
    return Document(**data)
