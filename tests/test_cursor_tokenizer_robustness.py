"""Unicode and chunking checks. No tokenizer training and no proficiency score."""
from __future__ import annotations

import pytest

from orca.genesis.tokenizer.robustness import (
    InvalidTextEncoding,
    chunk_text,
    decode_utf8,
    normalized_digest,
    normalize_nfc,
    reserved_special_surfaces,
)
from orca.genesis.tokenizer.specials import SPECIAL_TOKENS

SAMPLES = {
    "en": "The sky is clear today.",
    "ta": "இன்று வானம் தெளிவாக உள்ளது.",
    "hi": "आज आसमान साफ़ है।",
    "te": "ఈ రోజు ఆకాశం స్పష్టంగా ఉంది.",
    "kn": "ಇಂದು ಆಕಾಶ ಸ್ಪಷ್ಟವಾಗಿದೆ.",
    "ar": "السماء صافية اليوم.",
    "zh": "今天天气晴朗。",
}


@pytest.mark.parametrize("text", list(SAMPLES.values()))
def test_nfc_is_idempotent_for_representative_scripts(text):
    once = normalize_nfc(text)
    assert normalize_nfc(once) == once
    assert decode_utf8(once.encode("utf-8")) == once


def test_decomposed_latin_nfc_matches_precomposed():
    assert normalize_nfc("e\u0301") == normalize_nfc("é") == "é"


def test_invalid_utf8_is_rejected():
    with pytest.raises(InvalidTextEncoding):
        decode_utf8(b"\xff")


def test_reserved_special_token_surfaces_are_detected():
    assert reserved_special_surfaces("hello") == []
    found = reserved_special_surfaces("user typed <eos> in the middle")
    assert found == ["<eos>"]
    assert set(SPECIAL_TOKENS) == {"<pad>", "<bos>", "<eos>", "<unk>"}


def test_chunks_cover_the_normalized_text_without_splitting_codepoints():
    text = SAMPLES["ta"] + SAMPLES["zh"] + "e\u0301"
    chunks = chunk_text(text, 3)
    assert "".join(chunks) == normalize_nfc(text)
    assert all(len(chunk) <= 3 for chunk in chunks)
    assert normalized_digest(text) == normalized_digest(normalize_nfc(text))


def test_mixed_script_digest_changes_when_the_text_changes():
    mixed = " ".join(SAMPLES.values())
    assert normalized_digest(mixed) != normalized_digest(mixed + " ")
