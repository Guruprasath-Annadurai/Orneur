"""
CognitiveCheckpoint (spec section 8.10). A checkpoint IS a compiled,
canonical `CognitiveArtifact` -- OCL structurally never carries raw hidden
chain-of-thought or execution credentials (no such field exists anywhere
in the type system), so the one real remaining risk is secret-SHAPED
CONTENT inside an atom's `content` string or an evidence anchor's
reference/locator. Reuses Phase 15's existing sanitization infrastructure
(`orca.learning.sanitize.sanitize_for_candidate`) rather than inventing a
second secrets mechanism, per this module's own charter.
"""
from __future__ import annotations

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.canonical import artifact_from_canonical_json, to_canonical_json
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import SecretContentRejected


def _scan_for_secrets(artifact: CognitiveArtifact) -> None:
    from orca.learning.sanitize import sanitize_for_candidate

    for atom in artifact.atoms:
        result = sanitize_for_candidate(atom.content)
        if result.rejected:
            raise SecretContentRejected(
                f"atom {atom.atom_id!r} content matched a secret pattern -- refusing to persist "
                "it into a checkpoint. Reasons: " + "; ".join(result.reject_reasons)
            )
    for anchor in artifact.evidence:
        for field_value in (anchor.reference, anchor.locator or ""):
            result = sanitize_for_candidate(field_value)
            if result.rejected:
                raise SecretContentRejected(
                    f"evidence anchor {anchor.evidence_id!r} matched a secret pattern -- refusing to "
                    "persist it into a checkpoint. Reasons: " + "; ".join(result.reject_reasons)
                )


def create_checkpoint(draft: CognitiveArtifact) -> str:
    """Compiles `draft`, scans it for secret-shaped content, and returns a
    canonical JSON checkpoint string. Raises `SecretContentRejected` rather
    than silently redacting and persisting -- matching the Phase 15
    curriculum-candidate precedent (reject, don't silently admit)."""
    compiled = compile_artifact(draft)
    _scan_for_secrets(compiled)
    return to_canonical_json(compiled)


def restore_checkpoint(checkpoint_json: str) -> CognitiveArtifact:
    """Parses and re-validates a checkpoint -- restoring is not a trusted
    shortcut around compilation; a tampered or stale checkpoint must still
    fail the same way a fresh malformed artifact would."""
    draft = artifact_from_canonical_json(checkpoint_json)
    return compile_artifact(draft)
