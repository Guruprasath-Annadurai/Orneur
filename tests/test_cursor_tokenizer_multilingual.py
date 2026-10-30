"""SentencePiece round-trip on short original sentences.

Kannada, Arabic, and Chinese are included alongside the scripts already
covered by the earlier tokenizer tests. No proficiency number is reported.
"""
from __future__ import annotations

import pytest

pytest.importorskip("sentencepiece")

from orca.genesis.tokenizer.framework import (  # noqa: E402
    GenesisTokenizer,
    TokenizerTrainingConfig,
    train_tokenizer,
)
from orca.genesis.tokenizer.robustness import normalize_nfc  # noqa: E402

SENTENCES = [
    "The sky is clear today and the wind is calm.",
    "இன்று வானம் தெளிவாக உள்ளது, காற்று அமைதியாக உள்ளது.",
    "आज आसमान साफ़ है और हवा शांत है।",
    "ఈ రోజు ఆకాశం స్పష్టంగా ఉంది మరియు గాలి ప్రశాంతంగా ఉంది.",
    "ಇಂದು ಆಕಾಶ ಸ್ಪಷ್ಟವಾಗಿದೆ ಮತ್ತು ಗಾಳಿ ಶಾಂತವಾಗಿದೆ.",
    "السماء صافية اليوم والريح هادئة.",
    "今天天气晴朗，风也很平静。",
    "I think ரயில் is late, आज, and 今天.",
]


@pytest.fixture(scope="module")
def tokenizer(tmp_path_factory):
    directory = tmp_path_factory.mktemp("cursor_tok")
    path = train_tokenizer(SENTENCES, TokenizerTrainingConfig(vocab_size=800), str(directory / "tok"))
    return GenesisTokenizer(path)


@pytest.mark.parametrize("text", SENTENCES)
def test_round_trip_across_the_listed_scripts(tokenizer, text):
    assert tokenizer.decode(tokenizer.encode(text)) == normalize_nfc(text)


def test_encoding_is_deterministic(tokenizer):
    text = SENTENCES[-1]
    assert tokenizer.encode(text) == tokenizer.encode(text)
