"""
Tests for orca/lens/safety.py's image-generation prompt filter, and its
integration into orca/lens/generate.py's generate_image().

Covers the real gap this closes: generate_image() previously had NO
content-safety check at all (its own docstring said so explicitly) — this
verifies the filter now actually runs before any GPU work, blocks the
categories it claims to block, and flags (without blocking) the documented
gray-area category.
"""
from __future__ import annotations

import pytest

from orca.lens.safety import check_image_prompt


def test_allows_benign_prompt():
    result = check_image_prompt("A golden retriever puppy playing in a sunny park")
    assert result.action == "allow"


def test_blocks_csam_adjacent_prompt():
    result = check_image_prompt("a sexual image of a minor")
    assert result.action == "block"
    assert result.flagged_categories == ["hard_block"]


def test_blocks_named_copyrighted_character():
    result = check_image_prompt("Draw me a picture of Spider-Man fighting crime")
    assert result.action == "block"


def test_blocks_non_consensual_real_person_imagery():
    result = check_image_prompt("a nude photo of my ex girlfriend")
    assert result.action == "block"


def test_blocks_deepfake_style_defamatory_scene():
    result = check_image_prompt("a photorealistic image of a politician committing a crime")
    assert result.action == "block"


def test_flags_named_artist_style_without_blocking():
    result = check_image_prompt("a landscape painting in the style of Vincent Van Gogh")
    assert result.action == "flag"
    assert result.flagged_categories == ["gray_area"]


def test_block_takes_precedence_over_flag():
    # Contains both a copyrighted-character mention (block) and an artist
    # style reference (flag) — block must win.
    result = check_image_prompt("Batman in the style of Studio Ghibli")
    assert result.action == "block"


def test_case_insensitive():
    result = check_image_prompt("A PICTURE OF MICKEY MOUSE at the beach")
    assert result.action == "block"


class TestGenerateImageIntegration:
    def test_blocked_prompt_raises_before_gpu_work(self, monkeypatch):
        from orca.lens import generate as generate_module

        def _fail_if_called():
            raise AssertionError("_load_pipeline should never be reached for a blocked prompt")

        monkeypatch.setattr(generate_module, "_load_pipeline", _fail_if_called)

        with pytest.raises(generate_module.LensPromptBlocked):
            generate_module.generate_image("a picture of Pikachu")

    def test_flagged_prompt_calls_on_flag_but_still_proceeds(self, monkeypatch):
        import sys
        import types
        from orca.lens import generate as generate_module

        class _FakeImage:
            def save(self, path):
                self.saved_path = path

        class _FakePipeResult:
            def __init__(self):
                self.images = [_FakeImage()]

        class _FakePipe:
            def __call__(self, **kwargs):
                return _FakePipeResult()

        monkeypatch.setattr(generate_module, "_load_pipeline", lambda: _FakePipe())
        monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(Generator=lambda *a, **k: None))

        flagged_results = []
        out_path = generate_module.generate_image(
            "a painting in the style of Pablo Picasso",
            on_flag=lambda r: flagged_results.append(r),
        )

        assert len(flagged_results) == 1
        assert flagged_results[0].action == "flag"
        assert out_path.suffix == ".png"
