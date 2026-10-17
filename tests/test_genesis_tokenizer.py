"""
GENESIS Foundation Sprint 1, Phase 5: non-training verification of the
tokenizer framework. Trains small SentencePiece models on short,
original, hand-written multilingual sentences (English + a handful of
Indian languages, Hindi/Tamil/Telugu scripts) -- never a scraped or
licensed corpus, consistent with "authorized, public, legally suitable
test fixtures only." No model training (in the neural-network sense)
occurs anywhere in this file; SentencePiece's own BPE-merge training is
classical, non-gradient-based tokenizer construction, a different thing
entirely from training a language model.
"""
from __future__ import annotations

import pytest

# sentencepiece is deliberately NOT installed in the main deterministic
# CI job, same reasoning as torch (see tests/test_train_losses.py) --
# kept out of every regular test run, installed only in the dedicated
# `torch-loss-tests` job (also updated to install it), which this file
# runs under for real.
pytest.importorskip("sentencepiece")

from orca.genesis.tokenizer.framework import (  # noqa: E402
    BOS_ID,
    BOS_TOKEN,
    EOS_ID,
    EOS_TOKEN,
    PAD_ID,
    PAD_TOKEN,
    UNK_ID,
    UNK_TOKEN,
    GenesisTokenizer,
    TokenizerTrainingConfig,
    code_switching_fertility,
    normalize_text,
    per_language_fertility_report,
    train_tokenizer,
)

# Short, original, hand-written sentences -- not sourced from any
# licensed or scraped corpus. English plus Hindi (Devanagari), Tamil, and
# Telugu, each a plain, unremarkable sentence about the weather or a meal,
# written directly for this test file.
ENGLISH = [
    "The sky is clear today and the wind is calm.",
    "She finished her homework before dinner.",
    "The train arrives at the station every morning.",
]
HINDI = [
    "आज आसमान साफ़ है और हवा शांत है।",
    "उसने खाने से पहले अपना काम पूरा किया।",
    "ट्रेन हर सुबह स्टेशन पर आती है।",
]
TAMIL = [
    "இன்று வானம் தெளிவாக உள்ளது, காற்று அமைதியாக உள்ளது.",
    "அவள் இரவு உணவிற்கு முன் வீட்டுப் பாடத்தை முடித்தாள்.",
    "ரயில் ஒவ்வொரு காலையும் நிலையத்தை வந்தடைகிறது.",
]
TELUGU = [
    "ఈ రోజు ఆకాశం స్పష్టంగా ఉంది మరియు గాలి ప్రశాంతంగా ఉంది.",
    "ఆమె రాత్రి భోజనానికి ముందు తన ఇంటి పని పూర్తి చేసింది.",
    "రైలు ప్రతి ఉదయం స్టేషన్‌కు వస్తుంది.",
]
CODE_SWITCHED = [
    "I think ट्रेन is late today, let's check the schedule.",
    "She said आज వాతావరణం is nice, let's go for a walk.",
]

ALL_TEXTS = ENGLISH + HINDI + TAMIL + TELUGU


@pytest.fixture(scope="module")
def trained_tokenizer_path(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("genesis_tokenizer_test")
    # 500, not 300: SentencePiece itself rejected 300 here with a precise,
    # informative error -- 4 scripts (Latin + Devanagari + Tamil + Telugu)
    # in this fixture require 375 unique characters just for required_chars
    # coverage, before any BPE merging can begin. A real, small-scale
    # demonstration of exactly the measured character-coverage vs.
    # vocab-size trade-off Phase 3 asks this framework to surface, not a
    # bug to route around.
    cfg = TokenizerTrainingConfig(vocab_size=500)
    return train_tokenizer(ALL_TEXTS, cfg, model_prefix=str(tmp_dir / "test_tok"))


@pytest.fixture(scope="module")
def tokenizer(trained_tokenizer_path):
    return GenesisTokenizer(trained_tokenizer_path)


# -------------------------------------------------------- normalization --

def test_normalize_text_applies_nfc():
    # 'é' as a combining sequence (e + combining acute accent) vs. the
    # single precomposed codepoint -- NFC must produce the same result
    # for both.
    decomposed = "é"
    precomposed = "é"
    assert normalize_text(decomposed) == normalize_text(precomposed) == precomposed


# -------------------------------------------------------- special tokens --

def test_special_tokens_at_reserved_ids(tokenizer):
    assert tokenizer.sp.piece_to_id(PAD_TOKEN) == PAD_ID
    assert tokenizer.sp.piece_to_id(BOS_TOKEN) == BOS_ID
    assert tokenizer.sp.piece_to_id(EOS_TOKEN) == EOS_ID
    assert tokenizer.sp.piece_to_id(UNK_TOKEN) == UNK_ID


def test_config_rejects_vocab_size_too_small_for_special_tokens():
    with pytest.raises(ValueError, match="reserved special tokens"):
        TokenizerTrainingConfig(vocab_size=2)


# ---------------------------------------------------------- round trip --

@pytest.mark.parametrize("text", ENGLISH + HINDI + TAMIL + TELUGU + CODE_SWITCHED)
def test_round_trip_encoding_decoding(tokenizer, text):
    assert tokenizer.round_trip_check(text)


def test_byte_fallback_handles_unseen_characters(tokenizer):
    """A character that appears in NONE of the training text (byte
    fallback's whole purpose) must still encode and decode without
    raising -- this is what `byte_fallback=True` is for."""
    unseen = "🦄𝔘𝔫𝔦𝔠𝔬𝔡𝔢"  # emoji + mathematical alphanumeric symbols, absent from training data
    ids = tokenizer.encode(unseen)
    assert len(ids) > 0
    decoded = tokenizer.decode(ids)
    assert decoded == normalize_text(unseen)


# ----------------------------------------------------- fertility metrics --

def test_fertility_is_positive_and_finite(tokenizer):
    for text in ENGLISH + HINDI + TAMIL + TELUGU:
        f = tokenizer.fertility(text)
        assert f > 0
        assert f == f  # not NaN


def test_per_language_fertility_report_covers_all_languages(tokenizer):
    report = per_language_fertility_report(tokenizer, {
        "en": ENGLISH, "hi": HINDI, "ta": TAMIL, "te": TELUGU,
    })
    assert set(report.keys()) == {"en", "hi", "ta", "te"}
    assert all(v > 0 for v in report.values())


def test_code_switching_fertility_is_measured_separately(tokenizer):
    mixed_fertility = code_switching_fertility(tokenizer, CODE_SWITCHED)
    assert mixed_fertility > 0


def test_code_switching_fertility_rejects_empty_input(tokenizer):
    with pytest.raises(ValueError, match="non-empty"):
        code_switching_fertility(tokenizer, [])
