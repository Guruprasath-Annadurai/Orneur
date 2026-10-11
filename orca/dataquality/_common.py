"""Shared deterministic helpers: canonical JSON, hashing, JSONL loading, text extraction and normalisation."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def canonical_json(obj) -> str:
    """Stable serialisation: sorted keys, compact separators, ASCII-safe. Used for every digest."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def pretty_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False) + "\n"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_of(obj) -> str:
    return sha256_text(canonical_json(obj))


@dataclass
class Line:
    """One physical JSONL line. ``obj`` is None when the line did not parse; ``error`` then holds a content-free reason."""
    line: int
    obj: object
    error: str | None = None
    raw_sha256: str = ""


def load_jsonl(path) -> list:
    """Parse a JSONL file into Line records (1-based line numbers). Never raises on bad content; bad lines carry ``error``."""
    data = Path(path).read_bytes()
    parts = data.split(b"\n")
    if parts and parts[-1] == b"":
        parts = parts[:-1]   # trailing newline
    out = []
    for i, raw in enumerate(parts, start=1):
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        digest = sha256_bytes(raw)
        if not raw.strip():
            out.append(Line(i, None, "blank_line", digest))
            continue
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            out.append(Line(i, None, "invalid_utf8", digest))
            continue
        try:
            out.append(Line(i, json.loads(txt), None, digest))
        except (ValueError, RecursionError):
            out.append(Line(i, None, "invalid_json", digest))
    return out


def parsed(lines: list) -> list:
    """Only the lines that parsed to JSON objects."""
    return [l for l in lines if l.error is None and isinstance(l.obj, dict)]


# ---------------------------------------------------------------- text extraction
_LLAMA_SYS = re.compile(r"<\|start_header_id\|>system<\|end_header_id\|>.*?<\|eot_id\|>", re.S)
_CHATML_SYS = re.compile(r"<\|im_start\|>system.*?<\|im_end\|>", re.S)
_LLAMA_HDR = re.compile(r"<\|start_header_id\|>\w+<\|end_header_id\|>")
_CHATML_HDR = re.compile(r"<\|im_start\|>\w+")
_CTRL = re.compile(r"<\|[^|>]{1,40}\|>")


def strip_system_block(text: str) -> str:
    """Remove the (shared) system-prompt block of a Llama-3 or ChatML string; anything else is returned unchanged."""
    t = _LLAMA_SYS.sub("", text, count=1)
    return _CHATML_SYS.sub("", t, count=1)


def strip_control_tokens(text: str) -> str:
    t = _LLAMA_HDR.sub("\n", text)
    t = _CHATML_HDR.sub("\n", t)
    return _CTRL.sub("\n", t)


def message_texts(msgs) -> list:
    out = []
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                out.append((str(m.get("role", "")), m["content"]))
    return out


def body_text(obj: dict) -> str:
    """Content-bearing text of a record with the system prompt and template control tokens excluded (shared boilerplate must not inflate similarity)."""
    if not isinstance(obj, dict):
        return ""
    if isinstance(obj.get("text"), str):
        return strip_control_tokens(strip_system_block(obj["text"])).strip()
    if "messages" in obj:
        return "\n".join(c for r, c in message_texts(obj["messages"]) if r != "system")
    if "chosen" in obj or "rejected" in obj:
        parts = [obj.get("prompt")]
        for k in ("chosen", "rejected"):
            v = obj.get(k)
            parts.append(v if isinstance(v, str) else "\n".join(c for _, c in message_texts(v)))
        return "\n".join(p for p in parts if isinstance(p, str))
    parts = [obj.get(k) for k in ("instruction", "prompt", "input", "response", "completion", "output")]
    return "\n".join(p for p in parts if isinstance(p, str))


def legacy_body_text(obj: dict) -> str:
    """Everything after the first Llama-3 ``<|eot_id|>`` (system block excluded, special tokens kept). This exact slicing reproduces the
    192/666 figure of docs/orneur/phase-0/GENESIS_DATASET_BASELINE.md."""
    t = obj.get("text", "") if isinstance(obj, dict) else ""
    return t.split("<|eot_id|>", 1)[1] if "<|eot_id|>" in t else t


def string_leaves(o, out=None) -> list:
    out = [] if out is None else out
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, dict):
        for k in sorted(o):
            string_leaves(o[k], out)
    elif isinstance(o, (list, tuple)):
        for v in o:
            string_leaves(v, out)
    return out


# ---------------------------------------------------------------- normalisation
# Partial, documented confusables table (Cyrillic / Greek letters that render like Latin ones). Applied after casefold.
_HOMOGLYPHS = {
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x",
    "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ϲ": "c",
}
_HOMO_TABLE = {ord(k): v for k, v in _HOMOGLYPHS.items()}
_TOKEN = re.compile(r"\w+", re.U)


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text)).casefold()
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")   # zero-width joiners / spaces, bidi marks
    return t.translate(_HOMO_TABLE)


def tokens(text: str) -> list:
    return _TOKEN.findall(fold(text))


def normalize(text: str) -> str:
    return " ".join(tokens(text))


def mask_numbers(norm: str) -> str:
    return re.sub(r"\d+", "#", norm)
