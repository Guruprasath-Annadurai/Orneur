"""
GENESIS Foundation Sprint 2, Workstream A, Mission A4/A6: multilingual
tokenizer-evaluation integration tests.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
spm = pytest.importorskip("sentencepiece")

from orca.genesis.data.multilingual import (  # noqa: E402
    REPRESENTATIVE_CODE_SWITCHED_FIXTURES,
    REPRESENTATIVE_FIXTURES,
    check_byte_fallback,
    evaluate_multilingual_tokenizer,
)
from orca.genesis.tokenizer.framework import GenesisTokenizer, TokenizerTrainingConfig, train_tokenizer  # noqa: E402


@pytest.fixture(scope="module")
def tokenizer(tmp_path_factory):
    texts = [s for samples in REPRESENTATIVE_FIXTURES.values() for s in samples] + REPRESENTATIVE_CODE_SWITCHED_FIXTURES
    tmp_dir = tmp_path_factory.mktemp("multilingual_tok")
    path = train_tokenizer(texts, TokenizerTrainingConfig(vocab_size=600), model_prefix=str(tmp_dir / "tok"))
    return GenesisTokenizer(path)


def test_fixtures_cover_english_and_multiple_indian_languages():
    assert "en" in REPRESENTATIVE_FIXTURES
    indic = {lang for lang in REPRESENTATIVE_FIXTURES if lang != "en"}
    assert len(indic) >= 2


def test_evaluate_multilingual_tokenizer_reports_every_fixture_language(tokenizer):
    report = evaluate_multilingual_tokenizer(tokenizer)
    assert set(report.fertility_by_language) == set(REPRESENTATIVE_FIXTURES)
    assert set(report.round_trip_pass_rate_by_language) == set(REPRESENTATIVE_FIXTURES)
    assert set(report.sequence_length_expansion_by_language) == set(REPRESENTATIVE_FIXTURES)


def test_fertility_values_are_positive_and_finite(tokenizer):
    report = evaluate_multilingual_tokenizer(tokenizer)
    for lang, fertility in report.fertility_by_language.items():
        assert fertility > 0 and fertility < float("inf")


def test_round_trip_pass_rate_is_measured_not_assumed(tokenizer):
    report = evaluate_multilingual_tokenizer(tokenizer)
    for lang, rate in report.round_trip_pass_rate_by_language.items():
        assert 0.0 <= rate <= 1.0


def test_byte_fallback_handles_a_genuinely_unseen_character(tokenizer):
    round_trips, token_count = check_byte_fallback(tokenizer)
    assert round_trips is True
    assert token_count > 0


def test_code_switching_fertility_is_measured_against_mixed_samples(tokenizer):
    report = evaluate_multilingual_tokenizer(tokenizer)
    assert report.code_switching_fertility > 0


def test_sequence_length_expansion_is_bounded_and_positive(tokenizer):
    report = evaluate_multilingual_tokenizer(tokenizer)
    for lang, ratio in report.sequence_length_expansion_by_language.items():
        assert 0 < ratio < 10  # a sane tokens-per-character range for any real tokenizer


def test_custom_fixtures_can_be_supplied_instead_of_the_default_set(tokenizer):
    custom = {"en": ["A short custom English sentence for this specific test."]}
    report = evaluate_multilingual_tokenizer(tokenizer, fixtures=custom)
    assert set(report.fertility_by_language) == {"en"}


def test_this_module_never_claims_a_reasoning_or_fluency_score():
    """Structural guard against scope creep: this module's own source
    must never compute or name anything resembling a reasoning/fluency/
    translation-quality score -- only tokenizer-behavior measurements."""
    import orca.genesis.data.multilingual as mod
    from pathlib import Path
    source = Path(mod.__file__).read_text().lower()
    for forbidden in ("reasoning_score", "fluency_score", "translation_quality", "comprehension_score"):
        assert forbidden not in source
