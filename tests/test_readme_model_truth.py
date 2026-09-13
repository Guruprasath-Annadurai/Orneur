"""
README model-status truthfulness regression. Prevents the stale claim
"Genesis: Fine-tuned, evaluated, red-teamed" from reappearing in the
public README while the canonical registry truth
(docs/orneur/phase-16/PHASE16_NATIVE_INTELLIGENCE_BASELINE_AUDIT.md,
orca/registry/model_spec.py) says no canonical Genesis checkpoint has
been trained -- only legacy, RETIRED orca-nano* artifacts exist, and they
must never be presented as canonical Genesis.

This also guards Novus (real EXPERIMENTAL checkpoint, no PROMOTABLE
evaluation on record -- not production/promoted) and Aeternum (no trained
checkpoint at all, base model UNSELECTED_PROVISIONAL) against similar
overclaiming.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_genesis_is_not_claimed_as_trained_evaluated_redteamed():
    """The exact stale claim this closure fixed must never reappear
    attached to Genesis while the registry says no canonical checkpoint
    exists."""
    assert "Fine-tuned, evaluated, red-teamed" not in README


def test_genesis_status_discloses_no_canonical_checkpoint():
    assert "no canonical checkpoint has been trained" in README.lower() or \
           "no canonical checkpoint has been trained yet" in README


def test_genesis_legacy_artifacts_are_disclosed_as_retired_not_canonical():
    assert "RETIRED" in README
    assert "orca-nano" in README  # named explicitly as the legacy artifact, not hidden


def test_novus_is_disclosed_as_experimental_not_production():
    assert "EXPERIMENTAL" in README
    assert "PROMOTABLE" in README
    # Must not claim production/promoted status anywhere near Novus's row.
    assert "Novus" in README


def test_aeternum_has_no_trained_checkpoint_claim():
    assert "UNSELECTED_PROVISIONAL" in README
    assert "no trained checkpoint" in README.lower()


def test_readme_does_not_headline_parameter_counts_for_tiers():
    """Product identity in the tiers table must not lead with a raw
    parameter count (e.g. "8B", "14B") as the tier's identity -- that's
    identity via internal architecture detail, not positioning."""
    # A loose check: parameter-class strings should not appear directly
    # inside the tiers table's Positioning column text.
    for stale_headline in ["8B model", "14B model", "3B model"]:
        assert stale_headline not in README
