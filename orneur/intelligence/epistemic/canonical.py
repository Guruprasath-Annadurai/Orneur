"""
Deterministic canonical serialization for Phase 18 objects. Mirrors
orneur.intelligence.ocl.canonical's chain exactly: sort every collection
deterministically -> recursively normalize dataclasses/enums/mappings to
JSON-safe primitives -> json.dumps(sort_keys=True, deterministic
separators, allow_nan=False) -> SHA-256 hex digest over the UTF-8 bytes.
Same semantic input must always produce the same canonical bytes/digest
-- no wall-clock reads, no object reprs, no memory addresses.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from types import MappingProxyType

from orneur.intelligence.epistemic import errors
from orneur.intelligence.epistemic.limits import MAX_OVERLAY_SERIALIZED_BYTES
from orneur.intelligence.epistemic.models import EpistemicOverlay


def canonicalize(overlay: EpistemicOverlay) -> EpistemicOverlay:
    """Returns a new EpistemicOverlay with every collection in stable,
    deterministic order. Never changes content, only ordering."""
    sorted_assessments = tuple(sorted(overlay.assessments, key=lambda a: a.atom_id))
    normalized_assessments = tuple(
        dataclasses.replace(
            a,
            direct_support_evidence_refs=tuple(sorted(a.direct_support_evidence_refs)),
            direct_refutation_evidence_refs=tuple(sorted(a.direct_refutation_evidence_refs)),
            derived_support_atom_refs=tuple(sorted(a.derived_support_atom_refs)),
            derived_refutation_atom_refs=tuple(sorted(a.derived_refutation_atom_refs)),
            unresolved_evidence_refs=tuple(sorted(a.unresolved_evidence_refs)),
            contradiction_atom_refs=tuple(sorted(a.contradiction_atom_refs)),
            verification_contract_refs=tuple(sorted(a.verification_contract_refs)),
            reason_codes=tuple(sorted(a.reason_codes, key=lambda r: r.value)),
        )
        for a in sorted_assessments
    )
    return dataclasses.replace(overlay, assessments=normalized_assessments)


def _to_json_safe(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_json_safe(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, (dict, MappingProxyType)):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise errors.EpistemicCanonicalizationError(f"cannot canonicalize value of type {type(value).__name__}")


def to_canonical_json(overlay: EpistemicOverlay) -> str:
    canonical = canonicalize(overlay)
    safe = _to_json_safe(canonical)
    try:
        text = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    except ValueError as exc:
        raise errors.EpistemicCanonicalizationError(f"non-finite value in overlay: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_OVERLAY_SERIALIZED_BYTES:
        raise errors.PayloadLimitExceeded("canonical overlay JSON exceeds MAX_OVERLAY_SERIALIZED_BYTES")
    return text


def digest(overlay: EpistemicOverlay) -> str:
    """Proves content identity only -- no cryptographic authentication
    claim, matching OCL's own digest() doctrine."""
    return hashlib.sha256(to_canonical_json(overlay).encode("utf-8")).hexdigest()
