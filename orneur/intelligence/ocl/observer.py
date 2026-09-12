"""
Safe observation / OCL Observer (spec section 19). Deterministic
projections of one CognitiveArtifact for different consumers. A view is a
DATA PROJECTION, never a permission grant, and it never invents content --
every field in a projection comes directly from the source artifact.
Projection never mutates the source artifact (which is frozen already).
"""
from __future__ import annotations

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.canonical import _to_json_safe, canonicalize
from orneur.intelligence.ocl.enums import AtomKind, ObserverView


def _atoms_of_kind(artifact: CognitiveArtifact, *kinds: AtomKind) -> list[dict]:
    return [_to_json_safe(a) for a in artifact.atoms if a.kind in kinds]


def project(artifact: CognitiveArtifact, view: ObserverView) -> dict:
    canonical = canonicalize(artifact)

    if view == ObserverView.MODEL_VIEW:
        return {
            "artifact_id": canonical.artifact_id,
            "atoms": [_to_json_safe(a) for a in canonical.atoms],
            "relations": [_to_json_safe(r) for r in canonical.relations],
            "evidence": [_to_json_safe(e) for e in canonical.evidence],
            "causal_hypotheses": [_to_json_safe(c) for c in canonical.causal_hypotheses],
            "counterfactual_branches": [_to_json_safe(c) for c in canonical.counterfactual_branches],
        }

    if view == ObserverView.VERIFIER_VIEW:
        return {
            "artifact_id": canonical.artifact_id,
            "verification_contracts": [_to_json_safe(v) for v in canonical.verification_contracts],
            "evidence": [_to_json_safe(e) for e in canonical.evidence],
            "assertions_and_hypotheses": _atoms_of_kind(canonical, AtomKind.ASSERTION, AtomKind.HYPOTHESIS),
            "conflicts": _atoms_of_kind(canonical, AtomKind.CONFLICT),
            "limitations": _atoms_of_kind(canonical, AtomKind.LIMITATION),
        }

    if view == ObserverView.COURT_VIEW:
        return {
            "artifact_id": canonical.artifact_id,
            "action_intents": [_to_json_safe(x) for x in canonical.action_intents],
            "evidence": [_to_json_safe(e) for e in canonical.evidence],
            "conflicts": _atoms_of_kind(canonical, AtomKind.CONFLICT),
            "limitations": _atoms_of_kind(canonical, AtomKind.LIMITATION),
        }

    if view == ObserverView.HUMAN_SUMMARY_VIEW:
        return {
            "artifact_id": canonical.artifact_id,
            "claims": _atoms_of_kind(canonical, AtomKind.ASSERTION),
            "unknowns": _atoms_of_kind(canonical, AtomKind.UNKNOWN),
            "proposed_next_steps": _atoms_of_kind(canonical, AtomKind.ACTION_PROPOSAL, AtomKind.TEST_PROPOSAL),
            "limitations": _atoms_of_kind(canonical, AtomKind.LIMITATION),
            "evidence_ids": [e.evidence_id for e in canonical.evidence],
        }

    if view == ObserverView.AUDIT_VIEW:
        return _to_json_safe(canonical)

    if view == ObserverView.LEARNING_REFERENCE_VIEW:
        return {
            "artifact_id": canonical.artifact_id,
            "atoms": [_to_json_safe(a) for a in canonical.atoms],
            "relations": [_to_json_safe(r) for r in canonical.relations],
            "causal_hypotheses": [_to_json_safe(c) for c in canonical.causal_hypotheses],
        }

    raise ValueError(f"unknown ObserverView {view!r}")
