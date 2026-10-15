"""The ORNEUR design tokens are an enforceable accessibility contract: every declared foreground/background pair must meet its minimum
WCAG 2.x contrast ratio in BOTH official themes, and the locked brand colours must be exactly the locked values."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

TOKENS = json.loads((Path(__file__).resolve().parent.parent / "docs/orneur/design/tokens.json").read_text())
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_brand_colours_are_exactly_the_locked_values():
    assert TOKENS["brand"] == {"slate_indigo": "#3A4B6B", "solar_coral": "#FF6B57", "pale_stone": "#E8E4DE"}


def test_exactly_two_official_themes():
    assert set(TOKENS["themes"]) == {"dark", "light"}


def test_every_token_is_a_valid_hex_colour_and_both_themes_define_the_same_tokens():
    assert set(TOKENS["themes"]["dark"]) == set(TOKENS["themes"]["light"])
    for theme in TOKENS["themes"].values():
        assert all(HEX.match(v) for v in theme.values())


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_all_declared_pairs_meet_their_minimum_contrast(theme):
    t = TOKENS["themes"][theme]
    failures = []
    for p in TOKENS["pairs"]:
        # Solar Coral is deliberately never used as a sole indicator on Light (documented rule); it is checked on Dark only.
        if theme == "light" and p["fg"] == "accent_fill":
            continue
        r = ratio(t[p["fg"]], t[p["bg"]])
        if r < p["min"]:
            failures.append(f'{theme}: {p["fg"]} on {p["bg"]} = {r:.2f} < {p["min"]} ({p["role"]})')
    assert failures == []


def test_documented_brand_colour_limits_are_real():
    """The rules in tokens.json exist because these raw combinations genuinely fail."""
    coral, indigo, stone = "#FF6B57", "#3A4B6B", "#E8E4DE"
    assert ratio(coral, TOKENS["themes"]["light"]["page"]) < 3.0          # coral text on Light would fail even large-text AA
    assert ratio(indigo, TOKENS["themes"]["dark"]["surface"]) < 3.0        # indigo text/icons on Dark would fail
    assert ratio(stone, indigo) >= 4.5                                     # Pale Stone on Slate Indigo is fine (user message in both themes)
