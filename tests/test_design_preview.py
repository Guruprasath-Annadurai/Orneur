"""The committed design preview must be exactly what the generator produces from the tested tokens, and must stay private, static and accessible."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "docs/orneur/design/preview/index.html"


def _generator():
    spec = importlib.util.spec_from_file_location("build_design_preview", ROOT / "scripts/design/build_design_preview.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_preview_is_exactly_what_the_generator_produces_from_the_tokens():
    assert PREVIEW.read_text(encoding="utf-8") == _generator().build()


def test_preview_is_static_and_makes_no_network_requests():
    html = PREVIEW.read_text(encoding="utf-8")
    assert "<script" not in html.lower()
    assert not re.findall(r'(?:src|href)\s*=\s*"https?://', html)
    assert not re.findall(r"url\(\s*['\"]?https?://", html) and "@import" not in html


def test_preview_uses_the_locked_greeting_and_both_official_themes():
    html = PREVIEW.read_text(encoding="utf-8")
    assert "Hello chief, what's the plan today." in html
    tokens = json.loads((ROOT / "docs/orneur/design/tokens.json").read_text())
    assert "theme-light" in html and "theme-dark" in html
    for theme in tokens["themes"].values():
        for colour in theme.values():
            assert colour in html


def test_preview_basic_accessibility_structure():
    html = PREVIEW.read_text(encoding="utf-8")
    assert '<html lang="en"' in html and 'name="viewport"' in html
    assert "prefers-reduced-motion" in html and ":focus-visible" in html
    for icon_button in re.findall(r'<button type="button" class="icon-btn"[^>]*>', html):
        assert "aria-label=" in icon_button
    assert html.count('aria-label="Message composer"') >= 6
    assert 'role="alert"' in html and 'role="status"' in html
    assert not re.findall(r"<img(?![^>]*\balt=)", html)


def test_the_screens_never_present_an_unqualified_model_as_qualified():
    html = re.sub(r"\s+", " ", PREVIEW.read_text(encoding="utf-8"))
    assert "experimental · not yet qualified" in html
    assert "no model shown is qualified for production" in html
    assert "production-ready" not in html.lower() and "qualified model" not in html.lower()
