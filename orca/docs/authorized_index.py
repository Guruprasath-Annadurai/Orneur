"""Session-bound local document index.

Sparse ranking uses `orca.docs.sparse.bm25_scores`. Hybrid ranking uses
`orca.docs.reranker.reciprocal_rank_fusion` only when a neural encoder
actually runs. `orneur.rag_x.synthetic_hash_v1` is refused and is never
reported as neural retrieval.

The index does not accept a tenant id from the query. Scope is the
`TrustedSession` that admitted the documents.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from orca.docs.chunker import chunk_text
from orca.docs.reranker import reciprocal_rank_fusion
from orca.docs.sparse import bm25_scores
from orca.truth.access import AccessDenied, SessionAuthority, TrustedSession

# Must stay identical to orca.rag_x.rank.HASH_EMBEDDING_ID. docs does not
# import the research kernel.
SYNTHETIC_HASH_EMBEDDING_ID = "orneur.rag_x.synthetic_hash_v1"
PRODUCTION_ENCODER_ID = "nomic-embed-text"


@dataclass(frozen=True)
class LocalEncoder:
    """A caller-supplied embedding function.

    `kind="neural"` is necessary but not sufficient for a production label.
    `production_neural` on a search report is true only when this identity
    is `nomic-embed-text` and `probe_ollama` succeeded in this process.
    """

    kind: str
    identity: str
    embed: Callable[[str], tuple[float, ...] | list[float]]
    research_only: bool = False


@dataclass(frozen=True)
class IndexHit:
    text: str
    filename: str
    chunk_idx: int
    score: float
    version: int
    content_sha256: str
    doc_id: str


@dataclass(frozen=True)
class IndexSearchReport:
    hits: tuple[IndexHit, ...]
    method: str
    dense_backend: str
    production_neural: bool
    partial_reasons: tuple[str, ...]
    cache_hit: bool
    ignored_claims: tuple[str, ...] = field(default_factory=tuple)


class AuthorizedIndex:
    """One session, one directory, one authorization decision."""

    requires_trusted_session = True

    def __init__(
        self,
        authority: SessionAuthority,
        session: TrustedSession,
        root: Path | str,
        encoder: LocalEncoder | None = None,
        *,
        max_scored: int = 256,
        max_top_k: int = 24,
    ):
        if not authority.is_current(session):
            raise AccessDenied("index requires a current trusted session")
        if max_scored < 1 or max_top_k < 1:
            raise AccessDenied("retrieval budgets must be positive")
        self._authority = authority
        self._session = session
        self._session_id = session.session_id
        self._token = session.token
        self._tenant_id = session.tenant_id
        self._principal_id = session.principal_id
        self._encoder = encoder
        self._max_scored = max_scored
        self._max_top_k = max_top_k
        self._epoch = 0
        self._cache_key: tuple | None = None
        self._cache_report: IndexSearchReport | None = None
        self._ollama_probe: bool | None = None
        self._root = Path(root) / session.session_id
        self._root.mkdir(parents=True, exist_ok=True)
        self._jsonl = self._root / "chunks.jsonl"
        self._revoked_path = self._root / "revoked.txt"
        self._ensure_leaf(self._jsonl)
        self._ensure_leaf(self._revoked_path)
        self._revoked = self._read_revoked()

    def permits(self, access: object) -> bool:
        if not self._authority.is_current(access):
            return False
        if not isinstance(access, TrustedSession):
            return False
        if access.session_id != self._session_id:
            return False
        if access.tenant_id != self._tenant_id or access.principal_id != self._principal_id:
            return False
        try:
            return hmac.compare_digest(access.token, self._token)
        except (TypeError, ValueError):
            return False

    def probe_ollama(self) -> bool:
        """Record whether a local nomic encoder responds. Does not install one."""
        try:
            from orca.docs.store import _ollama_embed

            vectors = _ollama_embed(["orneur-encoder-probe"])
            self._ollama_probe = bool(vectors) and bool(vectors[0]) and len(vectors[0]) > 8
        except Exception:
            self._ollama_probe = False
        return self._ollama_probe

    def admit(self, session: TrustedSession, filename: str, text: str) -> str:
        self._require(session)
        if not isinstance(filename, str) or not filename or "/" in filename or "\x00" in filename:
            raise AccessDenied("document filename is not admissible")
        if not isinstance(text, str) or not text.strip():
            raise AccessDenied("document text is empty")
        chunks = chunk_text(text, doc_id=filename, filename=filename)
        if not chunks:
            raise AccessDenied("document produced no chunks")
        rows, _partial = self._load_rows()
        version = max((int(row["version"]) for row in rows if row["filename"] == filename), default=0) + 1
        kept = [row for row in rows if row["filename"] != filename]
        written: list[dict] = []
        for chunk in chunks:
            digest = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            if digest in self._revoked:
                raise AccessDenied("revoked document digest cannot be admitted")
            written.append({
                "doc_id": filename,
                "filename": filename,
                "chunk_idx": chunk.chunk_idx,
                "text": chunk.text,
                "version": version,
                "content_sha256": digest,
            })
        self._write_rows(kept + written)
        self._bump()
        return written[0]["content_sha256"]

    def delete(self, session: TrustedSession, filename: str) -> int:
        """Remove a document and revoke the digests that were stored."""
        self._require(session)
        rows, _partial = self._load_rows()
        removed = [row for row in rows if row["filename"] == filename]
        if not removed:
            return 0
        for row in removed:
            self._revoked.add(row["content_sha256"])
        self._write_revoked()
        self._write_rows([row for row in rows if row["filename"] != filename])
        self._bump()
        return len(removed)

    def search(
        self,
        session: TrustedSession,
        query: str,
        *,
        top_k: int = 5,
        deadline_s: float | None = None,
        claimed_tenant: str | None = None,
    ) -> IndexSearchReport:
        self._require(session)
        ignored: list[str] = []
        if claimed_tenant is not None and claimed_tenant != self._tenant_id:
            ignored.append("ignored caller tenant claim")
        if deadline_s is not None and deadline_s <= 0:
            return IndexSearchReport(
                hits=(), method="none", dense_backend=self._dense_backend_label(),
                production_neural=False, partial_reasons=("deadline",), cache_hit=False,
                ignored_claims=tuple(ignored),
            )
        limit = min(int(top_k), self._max_top_k)
        partial: list[str] = []
        if int(top_k) > self._max_top_k:
            partial.append("retrieval budget clamped")
        if limit < 1:
            partial.append("retrieval budget")
            return IndexSearchReport(
                hits=(), method="none", dense_backend=self._dense_backend_label(),
                production_neural=False, partial_reasons=tuple(partial), cache_hit=False,
                ignored_claims=tuple(ignored),
            )
        stamp = self._leaf_stamp(self._jsonl)
        cache_key = (self._epoch, stamp, query, limit, tuple(ignored))
        if self._cache_key == cache_key and self._cache_report is not None:
            cached = self._cache_report
            return IndexSearchReport(
                hits=cached.hits, method=cached.method, dense_backend=cached.dense_backend,
                production_neural=cached.production_neural, partial_reasons=cached.partial_reasons,
                cache_hit=True, ignored_claims=cached.ignored_claims,
            )
        rows, load_partial = self._load_rows()
        partial.extend(load_partial)
        if len(rows) > self._max_scored:
            rows = rows[: self._max_scored]
            partial.append("scoring budget")
        texts = [row["text"] for row in rows]
        sparse = bm25_scores(query, texts)
        sparse_order = sorted(
            range(len(rows)),
            key=lambda index: (-sparse[index], rows[index]["filename"], rows[index]["chunk_idx"]),
        )
        sparse_hits = [self._hit(rows[index], sparse[index]) for index in sparse_order if sparse[index] > 0]
        method = "sparse"
        dense_backend = self._dense_backend_label()
        fused_hits = sparse_hits
        encoder_ran = False
        if self._encoder_runs():
            assert self._encoder is not None
            try:
                query_vector = self._encoder.embed(query)
                dense_scores = [self._cosine(query_vector, self._encoder.embed(row["text"])) for row in rows]
            except Exception:
                partial.append("dense encoder failed")
                dense_backend = "unavailable:encoder-failed"
            else:
                encoder_ran = True
                method = "hybrid-rrf"
                dense_backend = self._encoder.identity
                dense_order = sorted(
                    range(len(rows)),
                    key=lambda index: (-dense_scores[index], rows[index]["filename"], rows[index]["chunk_idx"]),
                )
                dense_hits = [
                    self._hit(rows[index], dense_scores[index]) for index in dense_order if dense_scores[index] > 0
                ]
                fused = reciprocal_rank_fusion([
                    [self._as_dict(hit) for hit in sparse_hits],
                    [self._as_dict(hit) for hit in dense_hits],
                ])
                by_key = {(hit.filename, hit.chunk_idx): hit for hit in sparse_hits + dense_hits}
                fused_hits = []
                for item in fused:
                    key = (item.get("filename", ""), item.get("chunk_idx", -1))
                    hit = by_key.get(key)
                    if hit is not None:
                        fused_hits.append(IndexHit(
                            text=hit.text, filename=hit.filename, chunk_idx=hit.chunk_idx,
                            score=float(item.get("_rrf", 0.0)), version=hit.version,
                            content_sha256=hit.content_sha256, doc_id=hit.doc_id,
                        ))
        if len(fused_hits) > limit:
            fused_hits = fused_hits[:limit]
            partial.append("retrieval budget")
        report = IndexSearchReport(
            hits=tuple(fused_hits),
            method=method,
            dense_backend=dense_backend,
            production_neural=self._production_neural(encoder_ran),
            partial_reasons=tuple(partial),
            cache_hit=False,
            ignored_claims=tuple(ignored),
        )
        self._cache_key = cache_key
        self._cache_report = report
        return report

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Truth Fabric calls this after `permits`. Shape matches DocStore."""
        if not self.permits(self._session):
            raise AccessDenied("document store requires a current trusted session")
        report = self.search(self._session, query, top_k=top_k)
        return [
            {
                "text": hit.text,
                "filename": hit.filename,
                "chunk_idx": hit.chunk_idx,
                "score": hit.score,
                "version": hit.version,
                "content_sha256": hit.content_sha256,
                "doc_id": hit.doc_id,
            }
            for hit in report.hits
        ]

    def count(self) -> int:
        if not self.permits(self._session):
            raise AccessDenied("document store requires a current trusted session")
        rows, _partial = self._load_rows()
        return len(rows)

    def replay(self, session: TrustedSession, content_sha256: str, text: str) -> bool:
        if not self.permits(session):
            return False
        try:
            rows, _partial = self._load_rows()
        except AccessDenied:
            return False
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != content_sha256 or digest in self._revoked:
            return False
        return any(row["content_sha256"] == content_sha256 and row["text"] == text for row in rows)

    def _require(self, session: TrustedSession) -> None:
        if not self.permits(session):
            raise AccessDenied("trusted session does not permit this index")

    def _bump(self) -> None:
        self._epoch += 1
        self._cache_key = None
        self._cache_report = None

    def _encoder_runs(self) -> bool:
        encoder = self._encoder
        if encoder is None:
            return False
        if encoder.research_only or encoder.kind != "neural":
            return False
        if encoder.identity == SYNTHETIC_HASH_EMBEDDING_ID:
            return False
        return True

    def _dense_backend_label(self) -> str:
        encoder = self._encoder
        if encoder is None:
            return "unavailable"
        if encoder.research_only or encoder.identity == SYNTHETIC_HASH_EMBEDDING_ID:
            return "refused:synthetic-hash-research-only"
        if encoder.kind != "neural":
            return "refused:encoder-kind"
        return "unavailable"

    def _production_neural(self, encoder_ran: bool) -> bool:
        encoder = self._encoder
        return bool(
            encoder_ran
            and encoder is not None
            and encoder.identity == PRODUCTION_ENCODER_ID
            and encoder.kind == "neural"
            and not encoder.research_only
            and self._ollama_probe is True
        )

    def _load_rows(self) -> tuple[list[dict], list[str]]:
        partial: list[str] = []
        raw = self._read_leaf(self._jsonl)
        rows: list[dict] = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                partial.append(f"corrupt line {line_number}")
                continue
            if not isinstance(row, dict):
                partial.append(f"corrupt line {line_number}")
                continue
            text = row.get("text")
            digest = row.get("content_sha256")
            if not isinstance(text, str) or not isinstance(digest, str):
                partial.append(f"corrupt line {line_number}")
                continue
            actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual != digest:
                partial.append(f"digest mismatch line {line_number}")
                continue
            if digest in self._revoked:
                partial.append(f"revoked digest line {line_number}")
                continue
            rows.append(row)
        return rows, partial

    def _write_rows(self, rows: list[dict]) -> None:
        payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")
        self._replace_leaf(self._jsonl, payload)

    def _read_revoked(self) -> set[str]:
        raw = self._read_leaf(self._revoked_path)
        return {line.strip() for line in raw.splitlines() if line.strip()}

    def _write_revoked(self) -> None:
        payload = (("\n".join(sorted(self._revoked)) + "\n").encode("utf-8")) if self._revoked else b""
        self._replace_leaf(self._revoked_path, payload)

    def _ensure_leaf(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            return
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)

    def _leaf_stamp(self, path: Path) -> str:
        """Content stamp. A same-length substitution or a symlink does not reuse a cached ranking."""
        return hashlib.sha256(self._read_leaf(path).encode("utf-8")).hexdigest()

    def _read_leaf(self, path: Path) -> str:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise AccessDenied("index leaf refused") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise AccessDenied("index leaf is not a regular file")
            chunks: list[bytes] = []
            while True:
                block = os.read(fd, 65536)
                if not block:
                    break
                chunks.append(block)
        finally:
            os.close(fd)
        return b"".join(chunks).decode("utf-8")

    def _replace_leaf(self, path: Path, payload: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        os.replace(temporary, path)

    @staticmethod
    def _hit(row: dict, score: float) -> IndexHit:
        return IndexHit(
            text=row["text"], filename=row["filename"], chunk_idx=int(row["chunk_idx"]),
            score=score, version=int(row["version"]), content_sha256=row["content_sha256"],
            doc_id=row.get("doc_id", row["filename"]),
        )

    @staticmethod
    def _as_dict(hit: IndexHit) -> dict:
        return {"text": hit.text, "filename": hit.filename, "chunk_idx": hit.chunk_idx, "doc_id": hit.doc_id}

    @staticmethod
    def _cosine(left, right) -> float:
        pairs = list(zip(left, right))
        if not pairs:
            return 0.0
        return sum(a * b for a, b in pairs)

