"""
GENESIS Foundation Sprint 2, Workstream A, Mission A4: multilingual
tokenizer-evaluation integration.

Reuses the EXISTING tokenizer framework (Sprint 1,
`orca.genesis.tokenizer.framework`) directly rather than reimplementing
fertility/round-trip measurement -- `GenesisTokenizer.fertility()`/
`round_trip_check()` and `per_language_fertility_report()`/
`code_switching_fertility()` already exist and are already tested
(`tests/test_genesis_tokenizer.py`). This module adds exactly the two
measurements that framework does not yet expose (byte-fallback behavior
on genuinely unseen characters, and sequence-length expansion), and wires
all four into one structured report over a representative fixture set.

**This measures tokenizer BEHAVIOR only.** Nothing here claims, implies,
or could be mistaken for a reasoning-capability, fluency, or translation-
quality score -- fertility and round-trip correctness are properties of
the TOKENIZER, not of any model's understanding of the language. The
fixture sentences below are short, hand-authored, deliberately mundane
statements (weather, daily routine, arithmetic) chosen specifically to
avoid needing any external, rights-encumbered corpus -- not curated for
linguistic sophistication.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.genesis.tokenizer.framework import GenesisTokenizer, code_switching_fertility, per_language_fertility_report

# Short, hand-authored, rights-cleared fixture sentences -- mundane
# statements only, no external corpus, no copyrighted text. One Latin
# (English) set and three Indian-language sets spanning distinct scripts
# (Devanagari, Tamil, Telugu) to exercise genuinely different Unicode
# ranges, matching the language set `tests/test_genesis_tokenizer.py`
# already uses for round-trip testing.
REPRESENTATIVE_FIXTURES: dict[str, list[str]] = {
    "en": [
        "The weather is clear today and the wind is calm.",
        "She finished her homework before dinner.",
        "The train arrives at the station every morning.",
    ],
    "hi": [
        "आज आसमान साफ़ है और हवा शांत है।",
        "उसने खाने से पहले अपना काम पूरा किया।",
        "ट्रेन हर सुबह स्टेशन पर आती है।",
    ],
    "ta": [
        "இன்று வானம் தெளிவாக உள்ளது, காற்று அமைதியாக உள்ளது.",
        "அவள் இரவு உணவிற்கு முன் வீட்டுப் பாடத்தை முடித்தாள்.",
        "ரயில் ஒவ்வொரு காலையும் நிலையத்தை வந்தடைகிறது.",
    ],
    "te": [
        "ఈ రోజు ఆకాశం స్పష్టంగా ఉంది మరియు గాలి ప్రశాంతంగా ఉంది.",
        "ఆమె రాత్రి భోజనానికి ముందు తన ఇంటి పని పూర్తి చేసింది.",
        "రైలు ప్రతి ఉదయం స్టేషన్‌కు వస్తుంది.",
    ],
}

REPRESENTATIVE_CODE_SWITCHED_FIXTURES: list[str] = [
    "I think ट्रेन is late today, let's check the schedule.",
    "She said आज వాతావరణం is nice, let's go for a walk.",
]

# A character guaranteed absent from any trained SentencePiece vocabulary
# built from the fixtures above -- chosen specifically to exercise
# byte-fallback (SentencePiece's own `byte_fallback=True` training
# option), not because it has any linguistic significance.
_BYTE_FALLBACK_PROBE_CHAR = "\U0001F984"  # U+1F984 UNICORN FACE


@dataclass(frozen=True)
class MultilingualTokenizerReport:
    """Every field is a measured number from a real tokenizer call against
    the fixtures above -- none of this is a claim about reasoning,
    fluency, or translation quality. See module docstring."""
    fertility_by_language: dict[str, float]
    code_switching_fertility: float
    round_trip_pass_rate_by_language: dict[str, float]
    sequence_length_expansion_by_language: dict[str, float]  # mean tokens-per-character
    byte_fallback_round_trips: bool
    byte_fallback_token_count: int


def _round_trip_pass_rate(tokenizer: GenesisTokenizer, samples: list[str]) -> float:
    if not samples:
        return 0.0
    return sum(1 for s in samples if tokenizer.round_trip_check(s)) / len(samples)


def _sequence_length_expansion(tokenizer: GenesisTokenizer, samples: list[str]) -> float:
    """Mean tokens-per-character -- a second, complementary efficiency
    measurement to fertility's tokens-per-word (meaningful for languages
    where word-boundary whitespace is sparse or absent, where
    tokens-per-word can be a misleading efficiency signal on its own)."""
    if not samples:
        return 0.0
    ratios = [len(tokenizer.encode(s)) / len(s) for s in samples if len(s) > 0]
    return sum(ratios) / len(ratios) if ratios else 0.0


def check_byte_fallback(tokenizer: GenesisTokenizer) -> tuple[bool, int]:
    """Verifies the tokenizer can still round-trip a genuinely unseen
    character via byte-fallback, rather than silently dropping or
    corrupting it. Returns (round_trips_correctly, token_count_used)."""
    probe = f"test {_BYTE_FALLBACK_PROBE_CHAR} probe"
    ids = tokenizer.encode(probe)
    decoded = tokenizer.decode(ids)
    from orca.genesis.tokenizer.framework import normalize_text
    return decoded == normalize_text(probe), len(ids)


def evaluate_multilingual_tokenizer(
    tokenizer: GenesisTokenizer, *, fixtures: dict[str, list[str]] | None = None,
    code_switched_fixtures: list[str] | None = None,
) -> MultilingualTokenizerReport:
    """Runs the full battery against `fixtures` (defaults to
    `REPRESENTATIVE_FIXTURES`) and returns a structured report. Every
    number here is directly reproducible by re-running this function
    against the same tokenizer -- nothing is estimated or interpolated."""
    fixtures = fixtures if fixtures is not None else REPRESENTATIVE_FIXTURES
    code_switched = code_switched_fixtures if code_switched_fixtures is not None else REPRESENTATIVE_CODE_SWITCHED_FIXTURES

    fertility = per_language_fertility_report(tokenizer, fixtures)
    round_trip = {lang: _round_trip_pass_rate(tokenizer, samples) for lang, samples in fixtures.items()}
    seq_expansion = {lang: _sequence_length_expansion(tokenizer, samples) for lang, samples in fixtures.items()}
    cs_fertility = code_switching_fertility(tokenizer, code_switched) if code_switched else 0.0
    byte_fallback_ok, byte_fallback_tokens = check_byte_fallback(tokenizer)

    return MultilingualTokenizerReport(
        fertility_by_language=fertility, code_switching_fertility=cs_fertility,
        round_trip_pass_rate_by_language=round_trip, sequence_length_expansion_by_language=seq_expansion,
        byte_fallback_round_trips=byte_fallback_ok, byte_fallback_token_count=byte_fallback_tokens,
    )
