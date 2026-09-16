"""
Deterministic canonical serialization for Phase 20's RoutingDecision.
Mirrors orneur.intelligence.integrity.canonical's chain exactly (which
itself mirrors Phase 18/OCL): sort every collection deterministically ->
recursively normalize dataclasses/enums/mappings to JSON-safe
primitives -> json.dumps(sort_keys=True, deterministic separators,
allow_nan=False) -> SHA-256 hex digest. No wall-clock reads, object
reprs, or memory addresses ever enter this chain.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from types import MappingProxyType

from orneur.intelligence.router import errors
from orneur.intelligence.router.contracts import RoutingDecision
from orneur.intelligence.router.limits import MAX_DECISION_SERIALIZED_BYTES


def canonicalize(decision: RoutingDecision) -> RoutingDecision:
    """Returns a new RoutingDecision with every collection in stable,
    deterministic order. Never changes content, only ordering."""
    sorted_candidates = tuple(
        dataclasses.replace(c, rejection_reasons=tuple(sorted(c.rejection_reasons, key=lambda r: r.value)))
        for c in sorted(decision.candidate_evaluations, key=lambda c: c.family.value)
    )
    sorted_factors = tuple(sorted(decision.material_epistemic_factors, key=lambda f: f.atom_id))
    sorted_reasons = tuple(sorted(decision.reason_codes, key=lambda r: r.value))
    return dataclasses.replace(
        decision,
        candidate_evaluations=sorted_candidates,
        material_epistemic_factors=sorted_factors,
        reason_codes=sorted_reasons,
    )


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
    raise errors.RouterCanonicalizationError(f"cannot canonicalize value of type {type(value).__name__}")


def to_canonical_json(decision: RoutingDecision) -> str:
    canonical = canonicalize(decision)
    safe = _to_json_safe(canonical)
    try:
        text = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    except ValueError as exc:
        raise errors.RouterCanonicalizationError(f"non-finite value in decision: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_DECISION_SERIALIZED_BYTES:
        raise errors.PayloadLimitExceeded("canonical decision JSON exceeds MAX_DECISION_SERIALIZED_BYTES")
    return text


def digest(decision: RoutingDecision) -> str:
    """Proves content identity only -- no cryptographic authentication
    claim, matching OCL/Phase-18/19's own digest() doctrine."""
    return hashlib.sha256(to_canonical_json(decision).encode("utf-8")).hexdigest()
