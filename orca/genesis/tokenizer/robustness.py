"""Tokenizer-adjacent robustness checks that do not train a tokenizer.

Unicode normalization, UTF-8 rejection, reserved-token surfaces, and
code-point chunking. No proficiency score is computed.
"""
from __future__ import annotations

import hashlib
import unicodedata

from orca.genesis.tokenizer.specials import SPECIAL_TOKENS


class InvalidTextEncoding(Exception):
    """The bytes are not well-formed UTF-8, or they contain a surrogate."""


def normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def decode_utf8(data: bytes) -> str:
    """Decode UTF-8 strictly. Invalid bytes and surrogates are rejected."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidTextEncoding("input is not valid UTF-8") from exc
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        raise InvalidTextEncoding("input contains a surrogate code point")
    return text


def reserved_special_surfaces(text: str) -> list[str]:
    """Reserved token spellings that appear literally in `text`.

    Finding one means the text should be rejected or escaped before it is
    encoded. This function does not encode.
    """
    return [token for token in SPECIAL_TOKENS if token in text]


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split into code-point chunks of at most `max_chars`.

    The chunks concatenate back to the NFC form of `text`. Python string
    slices do not cut a code point in half.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    normalized = normalize_nfc(text)
    if not normalized:
        return []
    return [normalized[index:index + max_chars] for index in range(0, len(normalized), max_chars)]


def normalized_digest(text: str) -> str:
    """SHA-256 of the NFC UTF-8 bytes. A binding input, not a signature."""
    return hashlib.sha256(normalize_nfc(text).encode("utf-8")).hexdigest()
