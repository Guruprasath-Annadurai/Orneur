"""Synthetic byte tokenizer. No corpus download and no trained vocabulary."""

from __future__ import annotations


class TokenizerError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SyntheticByteTokenizer:
    name = "orneur.synthetic_bytes/1"

    def encode(self, text: str) -> list[int]:
        if not isinstance(text, str):
            raise TokenizerError("text_refused")
        return list(text.encode("utf-8"))

    def decode(self, ids: list[int]) -> str:
        if any(not isinstance(i, int) or i < 0 or i > 255 for i in ids):
            raise TokenizerError("id_refused")
        return bytes(ids).decode("utf-8")


def family_foundation_status() -> dict:
    return {
        "genesis": "INTERFACE_ONLY",
        "novus": "NOT_AVAILABLE",
        "aeternum": "NOT_AVAILABLE",
        "official_scores": None,
        "trained_checkpoint": False,
        "tokenizer": SyntheticByteTokenizer.name,
    }
