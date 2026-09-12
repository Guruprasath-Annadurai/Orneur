"""
CognitiveCheckpoint (spec section 8.10). A checkpoint IS a compiled,
canonical `CognitiveArtifact` -- OCL structurally never carries raw hidden
chain-of-thought or execution credentials (no such field exists anywhere
in the type system), so the one real remaining risk is secret-SHAPED
CONTENT inside ANY string-bearing field anywhere in the artifact. Reuses
Phase 15's existing sanitization infrastructure
(`orca.learning.sanitize.sanitize_for_candidate`) rather than inventing a
second secrets mechanism, per this module's own charter -- and (Phase 17
closure) scans the WHOLE artifact via its own canonical JSON-safe
representation, not a hand-picked subset of fields.
"""
from __future__ import annotations

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.canonical import _to_json_safe, compile_ocl_json, to_canonical_json
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import SecretContentRejected


def _walk_strings(value, *, path: str):
    """Yields (path, string) for every string leaf reachable from `value`
    -- the same recursive shape `canonical._to_json_safe` already produces,
    reused here so no second traversal scheme has to be kept in sync."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _walk_strings(v, path=f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk_strings(v, path=f"{path}[{i}]")


def _scan_for_secrets(artifact: CognitiveArtifact) -> None:
    from orca.learning.sanitize import sanitize_for_candidate

    safe = _to_json_safe(artifact)
    for path, string_value in _walk_strings(safe, path="artifact"):
        if not string_value:
            continue
        result = sanitize_for_candidate(string_value)
        if result.rejected:
            raise SecretContentRejected(
                f"{path} matched a secret pattern -- refusing to persist it into a checkpoint. "
                "Reasons: " + "; ".join(result.reject_reasons)
            )


def create_checkpoint(draft: CognitiveArtifact) -> str:
    """Compiles `draft`, scans the ENTIRE compiled artifact for secret-
    shaped content (every string-bearing field, not a hand-picked subset),
    and returns a canonical JSON checkpoint string. Raises
    `SecretContentRejected` rather than silently redacting and persisting --
    matching the Phase 15 curriculum-candidate precedent (reject, don't
    silently admit)."""
    compiled = compile_artifact(draft)
    _scan_for_secrets(compiled)
    return to_canonical_json(compiled)


def restore_checkpoint(checkpoint_json: str) -> CognitiveArtifact:
    """Parses and re-validates a checkpoint through the full
    parse-then-compile path (`compile_ocl_json`) -- restoring is not a
    trusted shortcut around compilation; a tampered or stale checkpoint
    must still fail the same way a fresh malformed artifact would."""
    return compile_ocl_json(checkpoint_json)
