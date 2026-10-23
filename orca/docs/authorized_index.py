"""Session-bound local document index.

Sparse ranking uses `orca.docs.sparse.bm25_scores`. Hybrid ranking uses
`orca.docs.reranker.reciprocal_rank_fusion` only when a neural encoder
actually runs. `orneur.rag_x.synthetic_hash_v1` is refused and is never
reported as neural retrieval.

The index does not accept a tenant id from the query. Scope is the
`TrustedSession` that admitted the documents. Every filesystem step is
bound to a directory descriptor opened with no-follow semantics.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import threading
import urllib.request
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
_INDEX_LOCK_NAME = ".index.lock"
_KEY_NAME = ".mac.key"
_JSONL_NAME = "chunks.jsonl"
_REVOKED_NAME = "revoked.txt"
_TMP_NAME = re.compile(r"^\.(chunks\.jsonl|revoked\.txt)\.[0-9]+\.[0-9]+\.[0-9a-f]{32}\.tmp$")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_WRITE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class LocalEncoder:
    """A caller-supplied embedding function.

    `kind="neural"` is necessary but not sufficient for a production label.
    Declaring `identity="nomic-embed-text"` does not qualify this callable.
    `production_neural` is true only when a `TrustedOllamaEncoder` actually
    ran and verified the backend model identity.
    """

    kind: str
    identity: str
    embed: Callable[[str], tuple[float, ...] | list[float]]
    research_only: bool = False


class TrustedOllamaEncoder:
    """Production adapter. Availability is not qualification."""

    kind = "neural"
    identity = PRODUCTION_ENCODER_ID
    research_only = False

    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host.rstrip("/")
        self._verified_model: str | None = None
        self._dimension: int | None = None
        self._available = False

    def probe(self) -> bool:
        """HTTP availability only. Does not set production qualification."""
        try:
            vector, _model = self._request("orneur-encoder-probe")
        except Exception:
            self._available = False
            return False
        self._available = bool(vector)
        return self._available

    def embed(self, text: str) -> tuple[float, ...]:
        vector, model = self._request(text)
        if model:
            if model.split(":")[0] != PRODUCTION_ENCODER_ID:
                raise AccessDenied("ollama model identity is not nomic-embed-text")
            self._verified_model = model.split(":")[0]
        self._check_vector(vector)
        return vector

    def qualified(self) -> bool:
        return self._verified_model == PRODUCTION_ENCODER_ID and self._dimension is not None

    def _check_vector(self, vector: tuple[float, ...]) -> None:
        if not vector:
            raise AccessDenied("embedding is empty")
        if any(not math.isfinite(value) for value in vector):
            raise AccessDenied("embedding is not finite")
        if self._dimension is None:
            self._dimension = len(vector)
        elif len(vector) != self._dimension:
            raise AccessDenied("embedding dimension is inconsistent")

    def _request(self, text: str) -> tuple[tuple[float, ...], str | None]:
        payload = json.dumps({"model": PRODUCTION_ENCODER_ID, "prompt": text}).encode()
        request = urllib.request.Request(
            f"{self.host}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise AccessDenied("embedding response is not an object")
        model = data.get("model")
        model_name = model if isinstance(model, str) and model else None
        raw = data.get("embedding")
        if not isinstance(raw, list) or not raw:
            raise AccessDenied("embedding response has no vector")
        vector = tuple(float(value) for value in raw)
        return vector, model_name


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


def _is_symlink_errno(exc: OSError) -> bool:
    return exc.errno in {errno.ELOOP, getattr(errno, "EMLINK", -1), errno.EPERM}


class AuthorizedIndex:
    """One session, one directory, one authorization decision."""

    requires_trusted_session = True

    def __init__(
        self,
        authority: SessionAuthority,
        session: TrustedSession,
        root: Path | str,
        encoder: LocalEncoder | TrustedOllamaEncoder | None = None,
        *,
        max_scored: int = 256,
        max_top_k: int = 24,
    ):
        if not authority.is_current(session):
            raise AccessDenied("index requires a current trusted session")
        if max_scored < 1 or max_top_k < 1:
            raise AccessDenied("retrieval budgets must be positive")
        if "/" in session.session_id or session.session_id in {".", ".."} or "\x00" in session.session_id:
            raise AccessDenied("session id is not a single directory component")
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
        self._io_lock = threading.RLock()
        self._dir_fd = _open_session_directory(Path(root), session.session_id)
        try:
            self._lock_fd = os.open(_INDEX_LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._dir_fd)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
            try:
                self._mac_key = self._load_or_create_key()
                self._sweep_temporary()
                self._ensure_leaf(_JSONL_NAME)
                self._ensure_leaf(_REVOKED_NAME)
                self._revoked = self._read_revoked()
            finally:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        except Exception:
            lock_fd = getattr(self, "_lock_fd", None)
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except OSError:
                    pass
            os.close(self._dir_fd)
            raise

    def close(self) -> None:
        try:
            os.close(self._lock_fd)
        except OSError:
            pass
        try:
            os.close(self._dir_fd)
        except OSError:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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
        """Record whether a local nomic HTTP endpoint responds. Not qualification."""
        try:
            adapter = self._encoder if isinstance(self._encoder, TrustedOllamaEncoder) else TrustedOllamaEncoder()
            self._ollama_probe = adapter.probe()
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
        with self._serialized():
            rows, _partial = self._load_rows()
            version = max((int(row["version"]) for row in rows if row["filename"] == filename), default=0) + 1
            kept = [row for row in rows if row["filename"] != filename]
            written: list[dict] = []
            for chunk in chunks:
                digest = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
                if digest in self._revoked:
                    raise AccessDenied("revoked document digest cannot be admitted")
                row = {
                    "doc_id": filename,
                    "filename": filename,
                    "chunk_idx": chunk.chunk_idx,
                    "text": chunk.text,
                    "version": version,
                    "content_sha256": digest,
                    "tenant_id": self._tenant_id,
                    "session_id": self._session_id,
                }
                row["mac"] = self._mac(row)
                written.append(row)
            self._write_rows(kept + written)
            self._bump()
            return written[0]["content_sha256"]

    def delete(self, session: TrustedSession, filename: str) -> int:
        """Remove a document and revoke the digests that were stored."""
        self._require(session)
        with self._serialized():
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
                hits=(), method="none", dense_backend=self._dense_backend_label(False),
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
                hits=(), method="none", dense_backend=self._dense_backend_label(False),
                production_neural=False, partial_reasons=tuple(partial), cache_hit=False,
                ignored_claims=tuple(ignored),
            )
        stamp = self._leaf_stamp(_JSONL_NAME)
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
        dense_backend = self._dense_backend_label(False)
        fused_hits = sparse_hits
        encoder_ran = False
        if self._encoder_runs():
            try:
                query_vector = self._embed(query)
                dense_scores = [self._cosine(query_vector, self._embed(row["text"])) for row in rows]
            except Exception:
                partial.append("dense encoder failed")
                dense_backend = "unavailable:encoder-failed"
            else:
                encoder_ran = True
                method = "hybrid-rrf"
                dense_backend = self._dense_backend_label(True)
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

    def rotate_integrity_key(self, session: TrustedSession) -> None:
        self._require(session)
        with self._serialized():
            rows, partial = self._load_rows()
            if any(reason.startswith("integrity") for reason in partial):
                raise AccessDenied("refusing to rotate over an unrecoverable index")
            self._mac_key = secrets.token_bytes(32)
            self._replace_leaf(_KEY_NAME, self._mac_key)
            for row in rows:
                row["mac"] = self._mac(row)
            self._write_rows(rows)
            self._bump()

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
        if getattr(encoder, "research_only", False) or getattr(encoder, "kind", None) != "neural":
            return False
        if getattr(encoder, "identity", None) == SYNTHETIC_HASH_EMBEDDING_ID:
            return False
        return True

    def _embed(self, text: str):
        encoder = self._encoder
        assert encoder is not None
        if isinstance(encoder, TrustedOllamaEncoder):
            return encoder.embed(text)
        return encoder.embed(text)

    def _dense_backend_label(self, encoder_ran: bool) -> str:
        encoder = self._encoder
        if encoder is None:
            return "unavailable"
        identity = getattr(encoder, "identity", "")
        if getattr(encoder, "research_only", False) or identity == SYNTHETIC_HASH_EMBEDDING_ID:
            return "refused:synthetic-hash-research-only"
        if getattr(encoder, "kind", None) != "neural":
            return "refused:encoder-kind"
        if identity == PRODUCTION_ENCODER_ID and not isinstance(encoder, TrustedOllamaEncoder):
            return "unqualified"
        if isinstance(encoder, TrustedOllamaEncoder) and not encoder.qualified():
            return "unqualified"
        if encoder_ran:
            return identity
        return "unavailable"

    def _production_neural(self, encoder_ran: bool) -> bool:
        encoder = self._encoder
        return bool(
            encoder_ran
            and isinstance(encoder, TrustedOllamaEncoder)
            and encoder.qualified()
        )

    def _mac(self, row: dict) -> str:
        payload = {
            "tenant_id": self._tenant_id,
            "session_id": self._session_id,
            "doc_id": row.get("doc_id", row.get("filename")),
            "filename": row["filename"],
            "chunk_idx": row["chunk_idx"],
            "version": row["version"],
            "content_sha256": row["content_sha256"],
            "text": row["text"],
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._mac_key, body, hashlib.sha256).hexdigest()

    def _load_rows(self) -> tuple[list[dict], list[str]]:
        partial: list[str] = []
        raw = self._read_leaf(_JSONL_NAME)
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
            mac = row.get("mac")
            if not isinstance(text, str) or not isinstance(digest, str):
                partial.append(f"corrupt line {line_number}")
                continue
            actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual != digest:
                partial.append(f"digest mismatch line {line_number}")
                continue
            if not isinstance(mac, str) or not hmac.compare_digest(mac, self._mac(row)):
                partial.append(f"integrity mismatch line {line_number}")
                continue
            if row.get("tenant_id") not in {None, self._tenant_id} or row.get("session_id") not in {None, self._session_id}:
                partial.append(f"scope mismatch line {line_number}")
                continue
            if digest in self._revoked:
                partial.append(f"revoked digest line {line_number}")
                continue
            rows.append(row)
        return rows, partial

    def _write_rows(self, rows: list[dict]) -> None:
        payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")
        self._replace_leaf(_JSONL_NAME, payload)

    def _read_revoked(self) -> set[str]:
        raw = self._read_leaf(_REVOKED_NAME)
        return {line.strip() for line in raw.splitlines() if line.strip()}

    def _write_revoked(self) -> None:
        payload = (("\n".join(sorted(self._revoked)) + "\n").encode("utf-8")) if self._revoked else b""
        self._replace_leaf(_REVOKED_NAME, payload)

    def _ensure_leaf(self, name: str) -> None:
        try:
            fd = os.open(name, _FILE_WRITE, 0o600, dir_fd=self._dir_fd)
        except FileExistsError:
            self._require_regular(name)
            return
        os.close(fd)

    def _require_regular(self, name: str) -> None:
        try:
            info = os.stat(name, dir_fd=self._dir_fd, follow_symlinks=False)
        except OSError as exc:
            raise AccessDenied("index leaf refused") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AccessDenied("index leaf is not a regular file")

    def _leaf_stamp(self, name: str) -> str:
        return hashlib.sha256(self._read_leaf(name).encode("utf-8")).hexdigest()

    def _read_leaf(self, name: str) -> str:
        try:
            fd = os.open(name, _FILE_READ, dir_fd=self._dir_fd)
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

    def _replace_leaf(self, name: str, payload: bytes) -> None:
        temporary = f".{name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(16)}.tmp"
        fd = os.open(temporary, _FILE_WRITE, 0o600, dir_fd=self._dir_fd)
        try:
            view = memoryview(payload)
            offset = 0
            while offset < len(payload):
                written = os.write(fd, view[offset:])
                if written <= 0:
                    raise AccessDenied("index write was truncated")
                offset += written
            os.fsync(fd)
        except Exception:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self._dir_fd)
            except OSError:
                pass
            raise
        os.close(fd)
        os.rename(temporary, name, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd)
        os.fsync(self._dir_fd)

    def _load_or_create_key(self) -> bytes:
        try:
            fd = os.open(_KEY_NAME, _FILE_WRITE, 0o600, dir_fd=self._dir_fd)
        except FileExistsError:
            fd = os.open(_KEY_NAME, _FILE_READ, dir_fd=self._dir_fd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise AccessDenied("integrity key is not a regular file")
                key = os.read(fd, 64)
            finally:
                os.close(fd)
            if len(key) < 32:
                raise AccessDenied("integrity key is unusable")
            return key
        try:
            key = secrets.token_bytes(32)
            os.write(fd, key)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self._dir_fd)
        return key

    def _sweep_temporary(self) -> None:
        names = _listdir_fd(self._dir_fd)
        for name in names:
            if _TMP_NAME.match(name):
                try:
                    os.unlink(name, dir_fd=self._dir_fd)
                except OSError:
                    continue

    def _serialized(self):
        return _DirectoryLock(self._io_lock, self._lock_fd)

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
        if len(left) != len(right):
            raise ValueError("embedding dimension mismatch")
        pairs = list(zip(left, right))
        if not pairs:
            return 0.0
        if any(not math.isfinite(a) or not math.isfinite(b) for a, b in pairs):
            raise ValueError("embedding is not finite")
        return sum(a * b for a, b in pairs)


class _DirectoryLock:
    def __init__(self, mutex: threading.RLock, lock_fd: int):
        self._mutex = mutex
        self._lock_fd = lock_fd

    def __enter__(self):
        self._mutex.acquire()
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_exc):
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        self._mutex.release()
        return False


def _listdir_fd(dir_fd: int) -> list[str]:
    try:
        return os.listdir(dir_fd)
    except TypeError:
        proc = f"/proc/self/fd/{dir_fd}"
        if os.path.exists(proc):
            return os.listdir(proc)
        raise AccessDenied("cannot list the index directory without a descriptor listdir")


def _open_session_directory(root: Path, session_id: str) -> int:
    absolute = Path(root)
    if not absolute.is_absolute():
        absolute = Path.cwd() / absolute
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        parts = list(absolute.parts[1:]) + [session_id]
        for index, part in enumerate(parts):
            if part in {"", ".", ".."} or "/" in part or "\x00" in part:
                raise AccessDenied("index path component is not admissible")
            create = index >= len(parts) - 2
            next_fd = _open_component(fd, part, create=create)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_component(parent_fd: int, name: str, *, create: bool) -> int:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    try:
        child = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        if _is_symlink_errno(exc) or exc.errno in {errno.ENOTDIR, errno.EEXIST}:
            raise AccessDenied("index path component is a symlink or not a directory") from exc
        raise
    try:
        info = os.fstat(child)
        if not stat.S_ISDIR(info.st_mode):
            raise AccessDenied("index path component is not a directory")
        mode = stat.S_IMODE(info.st_mode)
        world_or_group_write = bool(mode & 0o022)
        sticky = bool(mode & stat.S_ISVTX)
        if world_or_group_write and not sticky:
            raise AccessDenied("index path permissions are not a confinement boundary")
        if create and not sticky and info.st_uid != os.geteuid():
            raise AccessDenied("index directory is not owned by this process")
        return child
    except Exception:
        os.close(child)
        raise
