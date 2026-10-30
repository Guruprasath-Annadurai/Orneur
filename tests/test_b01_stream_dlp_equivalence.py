"""LANDMARK-01 B-01 final integration (Wave E): the streaming redactor must be EQUIVALENT to redacting the finished text.

Two defects were found by the first live run of the default-path stream, both in ``StreamRedactor`` (the pre-existing tests only asserted that the *whole*
secret was absent, which a partial leak satisfies):

  1. Tail leak. ``sk-<20+ chars>`` counted as "complete" the moment 20 characters had arrived, so it was redacted then; the key's remaining 1-4
     characters arrived in the next delta and were released right after the ``[REDACTED-...]`` marker (e.g. ``[REDACTED-OPENAI_API_KEY]2``).
  2. Lost last letter. A bare ``s``/``A``/``B``/``g`` at the end of the text was treated as the start of ``sk-``/``AKIA``/``Bearer``/``ghp_`` and dropped at
     ``finish()`` - an answer ending in "keys" was stored and shown as "key".

The property asserted here is the strongest simple one: for ANY chunking, ``"".join(push(...)) + finish()`` equals ``scan_output(whole_text)["safe_text"]``,
and ``safe_text()`` (what is persisted) equals what was emitted (what the client saw). Evidence class: DETERMINISTIC.
"""
from __future__ import annotations

import random

import pytest

from orca.serve.dlp import scan_output
from orca.serve.stream_dlp import StreamRedactor

SECRET = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
AWS = "AKIAIOSFODNN7EXAMPLE"
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
BEARER = "Bearer " + "eyJhbGciOiJIUzI1NiJ9abcdefghijkl"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxyz0123456789\n-----END RSA PRIVATE KEY-----"

WORDS = [
    "keys", "this", "always", "is", "as", "bus", "Gas", "AB", "Be", "Bear", "Bearer", "beware", "ghost", "gh", "g", "A", "B", "s", "sk", "sky", "skate", "ask-me",
    "sk-short", "sk-", "AKIA", "AKIAshort", "ghp_", "ghp_short", "its", "Привет", "你好", "🌍", "naïve", "café", "x_sk-y", "pre_AKIAIOSFODNN7EXAMPLE",
]


def stream(text: str, cuts: list[int]) -> tuple[str, str, StreamRedactor]:
    r = StreamRedactor()
    pieces, last = [], 0
    for c in sorted(set(cuts)) + [len(text)]:
        pieces.append(r.push(text[last:c]))
        last = c
    pieces.append(r.finish())
    return "".join(pieces), r.safe_text(), r


def one_shot(text: str) -> str:
    return scan_output(text)["safe_text"]


@pytest.mark.parametrize("secret", [SECRET, AWS, GH, BEARER, PEM])
def test_every_two_way_split_of_every_secret_equals_one_shot_redaction(secret):
    text = f"before {secret} after the secret, and a last word keys"
    expected = one_shot(text)
    for i in range(len(text) + 1):
        emitted, stored, _ = stream(text, [i])
        assert emitted == expected, (i, emitted)
        assert stored == emitted


@pytest.mark.parametrize("secret", [SECRET, AWS, GH, BEARER, PEM])
def test_character_by_character_equals_one_shot_redaction(secret):
    text = f"x {secret} y keys"
    emitted, stored, _ = stream(text, list(range(1, len(text))))
    assert emitted == one_shot(text) and stored == emitted


@pytest.mark.parametrize("secret", [SECRET, AWS, GH, BEARER])
def test_no_partial_secret_follows_the_redaction_marker(secret):
    """The reproduced leak: a split just past the 20th character released the key's last characters after the marker."""
    body = secret.split("-", 1)[-1].split("_", 1)[-1].split(" ", 1)[-1]
    for i in range(1, len(secret)):
        emitted, _, _ = stream(f"k: {secret} .", [3 + i])
        assert "REDACTED" in emitted
        for n in (3, 4):
            assert body[-n:] not in emitted, (i, emitted)


@pytest.mark.parametrize("word", ["keys", "this", "bus", "Gas", "AB", "Be", "Bear", "Bearer", "g", "A", "B", "s", "sk", "gh", "AKI", "Привет", "🌍"])
def test_a_trailing_word_is_never_shortened(word):
    for text in (f"the {word}", f"{word}", f"a b {word}"):
        for cuts in ([], [len(text) - 1], list(range(1, len(text)))):
            emitted, stored, _ = stream(text, [c for c in cuts if 0 < c < len(text)])
            assert emitted == text == stored, (text, cuts, emitted)


def test_a_stream_that_ends_while_a_fragment_is_still_short_is_released_like_the_one_shot_route():
    """Nothing can grow after the end of the stream, so a fragment shorter than the DLP's own 20-char definition of a secret is plain text. This is
    what keeps "... use a Bearer token" from losing its last words; a COMPLETE secret at the end is still redacted (see the split tests above)."""
    for tail in ("sk-a1B2c3", "AKIAIOSFODNN", "Bearer abcdef", "ghp_abc", "Bearer token", "Bearer s."):
        text = f"leading text {tail}"
        emitted, stored, _ = stream(text, [5])
        assert emitted == one_shot(text) == text and stored == emitted
    for secret in (SECRET, AWS, GH, BEARER):
        emitted, _, _ = stream(f"ends with a secret {secret}", [7])
        assert secret not in emitted and "REDACTED" in emitted


def test_prose_that_merely_resembles_a_prefix_is_not_withheld():
    text = "ask-me about skate and ghost stories, Bearers beware, it's all good"
    for cuts in ([], list(range(1, len(text)))):
        emitted, stored, _ = stream(text, cuts)
        assert emitted == text == stored


def test_randomised_chunking_always_equals_one_shot_redaction():
    rnd = random.Random(20261029)
    secrets = [SECRET, AWS, GH, BEARER, PEM]
    for _ in range(600):
        parts = []
        for _ in range(rnd.randint(1, 9)):
            parts.append(rnd.choice(secrets) if rnd.random() < 0.35 else rnd.choice(WORDS))
        text = rnd.choice([" ", "\n", " and ", ", "]).join(parts)
        cuts = [rnd.randrange(1, len(text)) for _ in range(rnd.randint(0, 12))] if len(text) > 1 else []
        emitted, stored, _ = stream(text, cuts)
        assert emitted == one_shot(text), (text, cuts, emitted)
        assert stored == emitted, "what is persisted must be exactly what the client was shown"


def test_overflow_is_reported_once_and_the_stored_text_matches_what_was_sent():
    r = StreamRedactor()
    out = r.push("sk-" + "a" * 400) + r.finish()
    assert out.count("[REDACTED-OVERFLOW]") == 1
    assert r.safe_text() == out
    assert "a" * 20 not in out


def test_no_chunking_ever_shows_more_of_a_secret_than_the_one_shot_redaction_does():
    """Adversarial separators (glued text, dashes, punctuation): the streamed output may be STRICTER than the one-shot scan on text that has no word
    boundaries, but it must never reveal a secret body the one-shot scan hides. Before the B-01 fixes ~1.2% of these chunkings leaked a whole PEM body
    (``key.-----BEGIN ...`` split after the first dash) and many leaked a key's last characters."""
    rnd = random.Random(7)
    bodies = [SECRET, AWS, GH, "eyJhbGciOiJIUzI1NiJ9abcdefghijkl", "MIIEowIBAAKCAQEAxyz0123456789"]
    secrets = [SECRET, AWS, GH, BEARER, PEM]
    for _ in range(2500):
        parts = [rnd.choice(secrets) if rnd.random() < 0.4 else rnd.choice(WORDS) for _ in range(rnd.randint(1, 10))]
        text = rnd.choice([" ", "\n", " and ", ", ", "", ".", "\t", "-", "--", "x"]).join(parts)
        cuts = [rnd.randrange(1, len(text)) for _ in range(rnd.randint(0, 25))] if len(text) > 1 else []
        emitted, stored, _ = stream(text, cuts)
        reference = one_shot(text)
        assert stored == emitted
        for body in bodies:
            assert not (body in emitted and body not in reference), (text, sorted(set(cuts)), emitted)


@pytest.mark.parametrize("glue", ["key.", "word", "x-", "(", '"', "`", ":"])
def test_a_pem_header_glued_to_preceding_text_is_still_recognised_at_every_split(glue):
    text = f"{glue}{PEM}\nafter"
    expected = one_shot(text)
    assert "MIIEowIBAAKCAQEAxyz0123456789" not in expected
    for i in range(1, len(text)):
        emitted, _, _ = stream(text, [i])
        assert "MIIEowIBAAKCAQEAxyz0123456789" not in emitted, (glue, i, emitted)
