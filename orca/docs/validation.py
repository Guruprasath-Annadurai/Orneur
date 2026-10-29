"""L02-02: upload validation. Everything here runs BEFORE a file is parsed or indexed, and none of it trusts the client.

* ``safe_filename`` - the display name that will appear in citations and prompts. It is metadata only (no upload is ever written to disk under this name),
  but it is rendered to users and to the model, so it is reduced to a bounded, printable basename.
* ``validate_content`` - the extension is only a claim; the bytes must agree with it (a PDF/DOCX must carry its container magic, a text type must be text).
* limits - bytes read, extracted characters, chunks per document, documents per conversation.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

MAX_FILENAME_CHARS = 120
MAX_EXTRACTED_CHARS = 2_000_000          # ~2 MB of text per document
MAX_CHUNKS_PER_DOC = 2_000
MAX_DOCS_PER_SESSION = 20

_CTRL = re.compile(r"[\x00-\x1f\x7f​-‏ -‮⁦-⁩]")
_UNSAFE = re.compile(r"[<>\"'`\\|?*:;{}\[\]$]")

_TEXT_EXT = {".txt", ".md", ".rst", ".log", ".yaml", ".yml", ".toml", ".ini", ".csv", ".json",
             ".py", ".js", ".ts", ".java", ".cpp", ".c", ".go", ".rb", ".rs", ".sh"}


class UploadRejected(ValueError):
    """Caller-fixable input problem; ``code`` is a stable public category and ``str(self)`` is safe to show."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


def safe_filename(name: str | None, default: str = "upload.txt") -> str:
    raw = (name or "").replace("\x00", "")
    base = PureWindowsPath(PurePosixPath(raw).name).name           # drop any directory part written for either OS ("../../etc/x.txt" -> "x.txt")
    base = _UNSAFE.sub("_", _CTRL.sub("", base)).strip(" .")
    if not base or set(base) <= {"_"}:
        return default
    if len(base) > MAX_FILENAME_CHARS:
        stem, dot, ext = base.rpartition(".")
        ext = ext[:12] if dot else ""
        base = (stem[: MAX_FILENAME_CHARS - len(ext) - 1] + "." + ext) if ext else base[:MAX_FILENAME_CHARS]
    return base


def validate_content(filename: str, data: bytes) -> None:
    ext = PurePosixPath(filename).suffix.lower()
    if not data:
        raise UploadRejected("empty_file", "This file is empty.")
    head = data[:8]
    if ext == ".pdf" and not data[:1024].lstrip().startswith(b"%PDF-"):
        raise UploadRejected("content_mismatch", "This file is not a valid PDF.")
    if ext == ".docx" and not head.startswith(b"PK\x03\x04"):
        raise UploadRejected("content_mismatch", "This file is not a valid DOCX document.")
    if ext in _TEXT_EXT:
        sample = data[:65536]
        if b"\x00" in sample:
            raise UploadRejected("content_mismatch", "This file looks binary, not text.")
        if head.startswith((b"%PDF-", b"PK\x03\x04", b"\x7fELF", b"MZ")):
            raise UploadRejected("content_mismatch", "This file's contents do not match its type.")
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start < len(sample) - 4:                            # a multi-byte character cut by the sample boundary is not corruption
                raise UploadRejected("content_mismatch", "This file is not valid UTF-8 text.")


async def read_bounded(upload, limit: int) -> bytes:
    """Read an UploadFile without ever holding more than ``limit`` + one block in memory. Raises UploadRejected(413) the moment the limit is crossed."""
    buf = bytearray()
    while True:
        block = await upload.read(1024 * 1024)
        if not block:
            return bytes(buf)
        buf += block
        if len(buf) > limit:
            raise UploadRejected("file_too_large", f"File too large. Max: {limit // 1024 // 1024}MB", 413)
