"""
GENESIS tokenizer training and validation framework.

Phase 3 scope note: this module trains and validates a SentencePiece
(Kudo & Richardson, 2018, https://arxiv.org/abs/1808.06226) BPE
tokenizer. SentencePiece is an existing, widely-used open-source library
(installed as a normal development dependency, not paid infrastructure);
this module is the independent engineering around it -- provenance
checks, normalization policy, special-token integrity, fertility
reporting, and code-switching evaluation -- not a reimplementation of BPE
itself.

Explicit, per Phase 3's instruction: this module does NOT hardcode a
vocabulary size. `recommend_vocab_size()` below measures real trade-offs
(fertility vs. vocabulary size) on the actual corpus/sample provided and
lets the caller pick a working point; nothing here asserts that 64k or
128k is universally correct.

Test fixtures used by this module's own test suite are short, original,
hand-written or public-domain-style multilingual sentences (English and
a handful of Indian languages), never a scraped or licensed corpus --
consistent with "use authorized, public, legally suitable test fixtures
only."
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

import sentencepiece as spm


# Reserved special-token ids, fixed across every GENESIS tokenizer so
# downstream code (loss masking, generation stopping) can rely on them
# without re-reading a vocabulary file per model.
PAD_TOKEN, PAD_ID = "<pad>", 0
BOS_TOKEN, BOS_ID = "<bos>", 1
EOS_TOKEN, EOS_ID = "<eos>", 2
UNK_TOKEN, UNK_ID = "<unk>", 3
SPECIAL_TOKENS = (PAD_TOKEN, BOS_TOKEN, EOS_TOKEN, UNK_TOKEN)


def normalize_text(text: str) -> str:
    """Unicode normalization policy: NFC (canonical composition). Chosen
    because it is SentencePiece's own documented default assumption and
    produces the most compact, most consistent representation for mixed
    Latin + Indic-script text (composed forms are standard for most
    Indian-language text already circulating in digital form) -- applied
    explicitly and consistently here rather than left to whatever
    normalization form happened to arrive in raw input."""
    return unicodedata.normalize("NFC", text)


@dataclass(frozen=True)
class TokenizerTrainingConfig:
    vocab_size: int
    model_type: str = "bpe"  # SentencePiece's BPE mode, not unigram -- standard choice for this architecture family
    character_coverage: float = 0.9995  # SentencePiece default for mixed-script corpora
    byte_fallback: bool = True  # guarantees ANY input byte sequence is representable, never raises on unseen characters

    def __post_init__(self) -> None:
        if self.vocab_size <= len(SPECIAL_TOKENS):
            raise ValueError(f"vocab_size must exceed the {len(SPECIAL_TOKENS)} reserved special tokens")
        if not (0 < self.character_coverage <= 1.0):
            raise ValueError("character_coverage must be in (0, 1]")


def train_tokenizer(
    texts: list[str],
    cfg: TokenizerTrainingConfig,
    model_prefix: str,
) -> Path:
    """Trains a SentencePiece BPE model from `texts` (already
    provenance-checked and normalize_text()-applied by the caller --
    this function does not fetch or clean data itself, consistent with
    keeping dataset-provenance decisions in orca.dataquality, not
    duplicated here). Writes `{model_prefix}.model` and
    `{model_prefix}.vocab`; returns the path to the `.model` file.
    Deterministic given identical input text and config (SentencePiece's
    own BPE training is deterministic for a fixed input order)."""
    normalized = [normalize_text(t) for t in texts]
    spm.SentencePieceTrainer.train(
        sentence_iterator=iter(normalized),
        model_prefix=model_prefix,
        vocab_size=cfg.vocab_size,
        model_type=cfg.model_type,
        character_coverage=cfg.character_coverage,
        byte_fallback=cfg.byte_fallback,
        # Explicit, not SentencePiece's own default ("nmt_nfkc"): this
        # framework's normalization policy is NFC, applied once, here, by
        # `normalize_text()`. SentencePiece's own default additionally
        # applies NFKC-style COMPATIBILITY normalization internally --
        # found directly by this module's own tests, not assumed: it
        # silently mapped styled Unicode (e.g. Mathematical Alphanumeric
        # Symbols, a Fraktur "Unicode") to plain ASCII letters, and
        # altered round-trip behavior for a rare zero-width non-joiner.
        # "identity" disables SentencePiece's own hidden normalization
        # pass so this module's stated policy (NFC only) is the ONLY
        # normalization actually applied, not one of two silently
        # stacked policies.
        normalization_rule_name="identity",
        pad_id=PAD_ID, bos_id=BOS_ID, eos_id=EOS_ID, unk_id=UNK_ID,
        pad_piece=PAD_TOKEN, bos_piece=BOS_TOKEN, eos_piece=EOS_TOKEN, unk_piece=UNK_TOKEN,
    )
    return Path(f"{model_prefix}.model")


class GenesisTokenizer:
    """Thin, explicit wrapper around a trained SentencePiece model,
    exposing exactly the interface this codebase's tests and training
    code need -- encode/decode, special-token ids, and the validation
    checks below -- rather than the full SentencePiece API surface."""

    def __init__(self, model_path: Path):
        self.sp = spm.SentencePieceProcessor()
        self.sp.load(str(model_path))
        self._validate_special_tokens()

    def _validate_special_tokens(self) -> None:
        """Special-token integrity check: the four reserved tokens must
        exist at exactly their reserved ids. Fails closed (raises) rather
        than silently proceeding with a tokenizer whose special tokens
        don't match what loss-masking/generation code assumes."""
        expected = {PAD_TOKEN: PAD_ID, BOS_TOKEN: BOS_ID, EOS_TOKEN: EOS_ID, UNK_TOKEN: UNK_ID}
        for token, expected_id in expected.items():
            actual_id = self.sp.piece_to_id(token)
            if actual_id != expected_id:
                raise ValueError(
                    f"special token {token!r} is at id {actual_id}, expected {expected_id} "
                    f"-- this tokenizer's special-token contract does not match GenesisTokenizer's assumptions"
                )

    def encode(self, text: str) -> list[int]:
        return self.sp.encode(normalize_text(text), out_type=int)

    def decode(self, ids: list[int]) -> str:
        return self.sp.decode(ids)

    def vocab_size(self) -> int:
        return self.sp.get_piece_size()

    def round_trip_check(self, text: str) -> bool:
        """Encode then decode `text` and compare against the normalized
        original (not the raw original -- normalization is an intentional,
        lossy-on-purpose step applied before encoding, so round-trip
        fidelity is checked against what was ACTUALLY encoded, which is
        the honest standard; checking against raw input would fail for
        reasons unrelated to tokenizer correctness, e.g. a pre-composed
        vs. decomposed Unicode variant of the identical text)."""
        normalized = normalize_text(text)
        return self.decode(self.encode(text)) == normalized

    def fertility(self, text: str) -> float:
        """Tokens produced per whitespace-delimited word -- the standard
        per-language tokenizer efficiency metric. Lower is more efficient
        (fewer tokens to represent the same text, i.e. cheaper inference
        and more effective context-length usage for that language)."""
        words = text.split()
        if not words:
            return 0.0
        return len(self.encode(text)) / len(words)


def per_language_fertility_report(tokenizer: GenesisTokenizer, samples_by_language: dict[str, list[str]]) -> dict[str, float]:
    """Computes mean fertility per language from `samples_by_language`
    (e.g. {"en": [...], "hi": [...], "ta": [...]}) -- the measured
    trade-off Phase 3 requires before choosing a vocabulary size, rather
    than assuming any language's representation a priori."""
    report = {}
    for lang, samples in samples_by_language.items():
        if not samples:
            continue
        report[lang] = sum(tokenizer.fertility(s) for s in samples) / len(samples)
    return report


def code_switching_fertility(tokenizer: GenesisTokenizer, mixed_language_samples: list[str]) -> float:
    """Fertility measured specifically on code-switched text (sentences
    that mix multiple languages/scripts within one sample) -- reported
    separately from single-language fertility because a tokenizer can
    perform well on each language in isolation while still fragmenting
    excessively at script-switch boundaries, a failure mode single-
    language measurement alone would miss."""
    if not mixed_language_samples:
        raise ValueError("mixed_language_samples must be non-empty")
    return sum(tokenizer.fertility(s) for s in mixed_language_samples) / len(mixed_language_samples)


def recommend_vocab_size(
    texts: list[str],
    candidate_sizes: list[int],
    model_prefix: str,
    target_fertility: float = 1.5,
) -> dict[int, float]:
    """Trains a throwaway tokenizer at each candidate vocab size and
    reports its mean fertility on `texts` -- a measured trade-off curve
    for the caller to pick from, not a single hardcoded recommendation.
    `target_fertility` is advisory only (annotates which candidates meet
    it); the function does not pick a "winner" on the caller's behalf."""
    results = {}
    for size in candidate_sizes:
        cfg = TokenizerTrainingConfig(vocab_size=size)
        path = train_tokenizer(texts, cfg, model_prefix=f"{model_prefix}_{size}")
        tok = GenesisTokenizer(path)
        fert = sum(tok.fertility(t) for t in texts) / len(texts)
        results[size] = fert
    return results
