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
from orneur.intelligence.ocl.canonical import _to_json_safe, parse_ocl_draft_json, to_canonical_json
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import SecretContentRejected
from orneur.intelligence.ocl.trust import UNTRUSTED, CompilationTrustContext


def _walk_strings(value, *, path: str):
    """Yields (path, string) for every string leaf reachable from `value`
    -- INCLUDING dict/mapping KEYS, not only values (a secret-shaped
    metadata key such as {"sk-...": "harmless"} must be caught just as
    reliably as a secret-shaped value; this was a real gap in the prior
    closure's walker, which only visited `value.items()`'s values)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                yield f"{path}.<key>", k
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


def create_checkpoint(draft: CognitiveArtifact, *, trust_context: CompilationTrustContext = UNTRUSTED) -> str:
    """Compiles `draft`, scans the ENTIRE compiled artifact for secret-
    shaped content (every string-bearing field AND every mapping key, not
    a hand-picked subset), and returns a canonical JSON checkpoint string.
    Raises `SecretContentRejected` rather than silently redacting and
    persisting -- matching the Phase 15 curriculum-candidate precedent
    (reject, don't silently admit). `trust_context` defaults to
    `UNTRUSTED_MODEL_OR_WIRE`, same as `compile_artifact()` itself; pass a
    stronger context only when the caller has independently established
    the draft's true origin."""
    compiled = compile_artifact(draft, trust_context=trust_context)
    _scan_for_secrets(compiled)
    return to_canonical_json(compiled)


def restore_checkpoint(checkpoint_json: str, *, trust_context: CompilationTrustContext = UNTRUSTED) -> CognitiveArtifact:
    """Parses and re-validates a checkpoint through the full parse-then-
    compile path -- restoring is not a trusted shortcut around
    compilation; a tampered or stale checkpoint must still fail the same
    way a fresh malformed artifact would.

    IMPORTANT: a checkpoint persists COGNITIVE STATE, never compilation
    TRUST. `trust_context` defaults to `UNTRUSTED_MODEL_OR_WIRE`, same as
    everywhere else -- a checkpoint created under
    `TRUSTED_DETERMINISTIC_SYSTEM` does NOT restore itself back into that
    trust level automatically; nothing inside the checkpoint JSON can
    supply it. The RESTORING runtime must independently re-establish trust
    (out-of-band, exactly as at creation time) and pass the matching
    `trust_context` explicitly if the checkpoint's privileged references
    are to compile successfully again. A trusted checkpoint restored in an
    untrusted context fails closed, by design."""
    draft = parse_ocl_draft_json(checkpoint_json)
    return compile_artifact(draft, trust_context=trust_context)
