"""
Cross-document public semantic truth invariants (ORNEUR final public
semantic truth closure). Brand-string tests (test_brand_invariant.py) and
prose tests (test_readme_model_truth.py) are not enough on their own --
a document can use perfectly correct ORNEUR branding while still
asserting stale or self-contradictory FACTS about model state or feature
availability. These tests derive facts from `orca/registry/model_spec.py`
(the single source of truth) wherever practical, rather than encoding a
second, independently-maintained truth table that could itself drift.

CURRENT_CANONICAL / CURRENT_SUPPORTING documents (see
docs/orneur/brand/ORNEUR_PUBLIC_SURFACE_MANIFEST.md's classification
table) are held to these invariants. `docs/AETERNUM_TRAINING_PLAN.md` is
HISTORICAL_SUPERSEDED and explicitly banner-marked as such -- its
preserved historical body text is not scanned by these tests (that would
require rewriting real history, which this closure deliberately does
not do); only README's *treatment* of that document is checked.
"""
from __future__ import annotations

import re
from pathlib import Path

from orca.registry.model_spec import MODEL_SPECS

REPO_ROOT = Path(__file__).resolve().parent.parent

CURRENT_DOCS = {
    "README.md": (REPO_ROOT / "README.md").read_text(encoding="utf-8"),
    "docs/MODEL_CARDS.md": (REPO_ROOT / "docs/MODEL_CARDS.md").read_text(encoding="utf-8"),
    "docs/PERPLEXITY_DIFFERENTIATION_PLAN.md": (REPO_ROOT / "docs/PERPLEXITY_DIFFERENTIATION_PLAN.md").read_text(encoding="utf-8"),
}


# ── 1/2: canonical Genesis must never be described as an already-trained
#         checkpoint at a wrong (or any) parameter count ──────────────────

def test_genesis_parameter_class_is_3b_not_7b_in_model_spec():
    """Ground truth check: if this ever fails, MODEL_SPECS itself changed
    and every prose assertion below needs re-deriving, not just this test."""
    assert MODEL_SPECS["genesis"].parameter_class == "3B"
    assert MODEL_SPECS["genesis"].base_model_status == "SELECTED"


def test_no_current_doc_calls_genesis_a_trained_7b_or_8b_model():
    stale_patterns = [
        re.compile(r"Genesis[^.\n]{0,20}7[- ]?8B"),
        re.compile(r"Genesis[^.\n]{0,20}\b7B\b"),
        re.compile(r"Genesis \(7B\)"),
    ]
    for doc_name, text in CURRENT_DOCS.items():
        for pattern in stale_patterns:
            assert not pattern.search(text), f"{doc_name} still contains a stale Genesis-7B/8B claim: {pattern.pattern!r}"


def test_no_current_doc_claims_genesis_is_already_fine_tuned_or_trained():
    stale_patterns = [
        re.compile(r"Genesis[^.\n]{0,40}(already )?(fine-tuned|trained)\b(?!.*no canonical)", re.IGNORECASE),
    ]
    for doc_name, text in CURRENT_DOCS.items():
        for pattern in stale_patterns:
            for match in pattern.finditer(text):
                # Allow the README's own truthful disclosure sentence,
                # which pairs "trained" with the negation in the same
                # breath (e.g. "no canonical checkpoint has been trained").
                window = text[max(0, match.start() - 60):match.end() + 60]
                assert "no canonical" in window.lower() or "not been trained" in window.lower() or "no trained" in window.lower(), (
                    f"{doc_name} claims Genesis is fine-tuned/trained without the required disclosure nearby: {match.group()!r}"
                )


# ── 3: canonical Aeternum's base model must never be presented as selected ──

def test_aeternum_base_model_is_none_in_model_spec():
    assert MODEL_SPECS["aeternum"].base_model is None
    assert MODEL_SPECS["aeternum"].base_model_status == "UNSELECTED_PROVISIONAL"


def test_no_current_doc_presents_qwen_14b_as_aeternums_selected_base_model():
    stale = re.compile(r"Aeternum[^.\n]{0,60}Qwen2\.5-14B[^.\n]{0,40}\b(is|as) the\b", re.IGNORECASE)
    for doc_name, text in CURRENT_DOCS.items():
        assert not stale.search(text), f"{doc_name} presents Qwen2.5-14B as Aeternum's selected base model"


def test_no_current_doc_asserts_aeternum_has_a_trained_checkpoint():
    stale = re.compile(r"Aeternum[^.\n]{0,60}\bhas a trained\b", re.IGNORECASE)
    for doc_name, text in CURRENT_DOCS.items():
        assert not stale.search(text)


# ── 4: the historical Aeternum training doc must not be labeled current ────

def test_readme_does_not_call_aeternum_training_plan_the_current_plan():
    readme = CURRENT_DOCS["README.md"]
    assert "the real, current plan" not in readme
    # Must be labeled historical/superseded within a short window of each
    # link to the doc (markdown link + label frequently wraps onto its
    # own line, so a per-line check is too strict).
    for match in re.finditer(r"AETERNUM_TRAINING_PLAN\.md", readme):
        window = readme[max(0, match.start() - 80):match.end() + 120].lower()
        assert "historical" in window or "superseded" in window, (
            f"a link to AETERNUM_TRAINING_PLAN.md is not labeled historical/superseded nearby: {window!r}"
        )


def test_aeternum_training_plan_is_banner_marked_legacy():
    text = (REPO_ROOT / "docs/AETERNUM_TRAINING_PLAN.md").read_text(encoding="utf-8")
    assert "STATUS: LEGACY / HISTORICAL" in text
    assert "SUPERSEDED" in text
    assert "NOT CANONICAL" in text


def test_public_surface_manifest_classifies_aeternum_plan_as_historical_superseded():
    manifest = (REPO_ROOT / "docs/orneur/brand/ORNEUR_PUBLIC_SURFACE_MANIFEST.md").read_text(encoding="utf-8")
    # Find the classification table row for the Aeternum training plan.
    match = re.search(r"docs/AETERNUM_TRAINING_PLAN\.md`?\s*\|\s*\*\*(\w+)\*\*", manifest)
    assert match, "AETERNUM_TRAINING_PLAN.md not found in the manifest's classification table"
    assert match.group(1) == "HISTORICAL_SUPERSEDED"


# ── 5: README and the differentiation doc must agree on live web grounding ──

def test_readme_and_differentiation_doc_agree_live_grounding_is_wired():
    readme = CURRENT_DOCS["README.md"]
    diff_doc = CURRENT_DOCS["docs/PERPLEXITY_DIFFERENTIATION_PLAN.md"]

    assert "live web-search grounding" in readme.lower()
    # The differentiation doc must not assert zero/no live grounding as a
    # PRESENT-TENSE current-state claim anywhere outside of its own
    # explicitly-dated historical framing (which itself must now disclose
    # the gap is closed).
    assert "orneur has zero live" not in diff_doc.lower() or "at the time this plan was originally written" in diff_doc.lower()
    assert "that gap is now closed" in diff_doc.lower()
    # The doc may still QUOTE its own prior stale claim while explaining
    # the correction (same pattern as SECURITY_AUDIT.md's historical
    # eval-output quote) -- but only if immediately flagged as corrected.
    for match in re.finditer(r"not yet called from", diff_doc, re.IGNORECASE):
        window = diff_doc[max(0, match.start() - 100):match.end() + 200].lower()
        assert "stale" in window or "corrected" in window, (
            "the differentiation doc repeats the stale 'not yet called from' "
            "wiring claim without disclosing it was corrected"
        )


def test_web_search_tool_actually_registered_backing_the_readme_claim():
    """Ties the doc claim to the same runtime fact
    test_search_grounding_live_wiring.py verifies in depth -- kept here
    too as a cheap, always-run tripwire independent of that file."""
    from orca.tools import build_registry

    assert "web_search" in build_registry().all_names()


# ── 6: model-card docs must not claim every native family ships a card ────

def test_model_cards_doc_does_not_claim_every_variant_ships_a_card():
    text = CURRENT_DOCS["docs/MODEL_CARDS.md"]
    assert "Every Orneur model variant ships a signed model card" not in text
    assert "supports signed model cards for trained/evaluated checkpoints" in text.lower() or \
           "supports signed model cards" in text


def test_model_cards_doc_discloses_genesis_and_aeternum_have_no_checkpoint():
    text = CURRENT_DOCS["docs/MODEL_CARDS.md"].lower()
    assert "genesis has no trained checkpoint" in text
    assert "aeternum has no trained checkpoint" in text


# ── 8: model size must not be presented as the product hierarchy ──────────

def test_no_current_doc_says_aeternum_must_be_larger_because_flagship():
    stale = re.compile(r"must be larger\b.{0,30}flagship", re.IGNORECASE)
    for doc_name, text in CURRENT_DOCS.items():
        assert not stale.search(text), f"{doc_name} implies Aeternum must be larger because it is flagship"


def test_model_families_are_described_by_cognitive_role_not_size_tier():
    for family, expected_role_fragment in [
        ("genesis", "Executor"),
        ("novus", "Investigator"),
        ("aeternum", "Discoverer"),
    ]:
        assert expected_role_fragment in MODEL_SPECS[family].role
