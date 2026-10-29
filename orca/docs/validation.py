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
MAX_DOCS_PER_USER = 200
MAX_BYTES_PER_USER = 1024 * 1024 * 1024        # per account, across conversations

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
    if ext == ".docx":
        if not head.startswith(b"PK\x03\x04"):
            raise UploadRejected("content_mismatch", "This file is not a valid DOCX document.")
        inspect_zip(data, filename)
    if ext in _TEXT_EXT:
        sample = data[:65536]
        if head.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise UploadRejected("unsupported_encoding", "This text file is UTF-16. Save it as UTF-8 and upload it again.")
        if b"\x00" in sample:
            raise UploadRejected("content_mismatch", "This file looks binary, not text.")
        if head.startswith((b"%PDF-", b"PK\x03\x04", b"\x7fELF", b"MZ")):
            raise UploadRejected("content_mismatch", "This file's contents do not match its type.")
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start < len(sample) - 4:                            # a multi-byte character cut by the sample boundary is not corruption
                raise UploadRejected("unsupported_encoding", "This text file is not UTF-8. Save it as UTF-8 and upload it again.")


MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ZIP_RATIO = 200


def inspect_zip(data: bytes, filename: str = "") -> None:
    """Pre-parse structure check for a ZIP-based container (DOCX): cheap, reads only the central directory. Refuses decompression bombs, path-traversal member
    names, encrypted members and anything that is not a real DOCX package. Nothing is decompressed here."""
    import io
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except Exception:
        raise UploadRejected("content_mismatch", "This file is not a valid DOCX document.")
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UploadRejected("container_unsafe", "This document contains too many parts.")
    total = 0
    for info in infos:
        total += info.file_size
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/") or (len(name) > 1 and name[1] == ":"):
            raise UploadRejected("container_unsafe", "This document contains an unsafe part name.")
        if info.flag_bits & 0x1:
            raise UploadRejected("container_unsafe", "Encrypted documents are not supported.")
        if info.file_size > 1024 * 1024 and info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO:
            raise UploadRejected("container_unsafe", "This document expands to an unsafe size.")
    if total > MAX_ZIP_UNCOMPRESSED:
        raise UploadRejected("container_unsafe", "This document expands to an unsafe size.")
    if filename.lower().endswith(".docx") and "word/document.xml" not in {i.filename for i in infos}:
        raise UploadRejected("content_mismatch", "This file is not a valid DOCX document.")


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
