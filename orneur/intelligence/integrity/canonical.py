"""
Deterministic canonical serialization for Phase 19's IntegrityReceipt.
Mirrors orneur.intelligence.epistemic.canonical's chain exactly (which
itself mirrors orneur.intelligence.ocl.canonical): sort every collection
deterministically -> recursively normalize dataclasses/enums/mappings to
JSON-safe primitives -> json.dumps(sort_keys=True, deterministic
separators, allow_nan=False) -> SHA-256 hex digest. No wall-clock reads,
object reprs, or memory addresses ever enter this chain.

IntegrityReceipt intentionally has no self-referential "canonical_digest"
field (avoiding the chicken-and-egg problem of a structure digesting its
own digest) -- callers compute digest(receipt) externally, exactly as
Phase 18 callers compute epistemic.canonical.digest(overlay) rather than
reading a stored field.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from types import MappingProxyType

from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityReceipt
from orneur.intelligence.integrity.limits import MAX_RECEIPT_SERIALIZED_BYTES


def canonicalize(receipt: IntegrityReceipt) -> IntegrityReceipt:
    """Returns a new IntegrityReceipt with every collection in stable,
    deterministic order. Never changes content, only ordering."""
    sorted_assessments = tuple(sorted(receipt.assertion_assessments, key=lambda a: a.assertion_id))
    normalized_assessments = tuple(
        dataclasses.replace(
            a,
            obligations=tuple(sorted(a.obligations, key=lambda o: o.value)),
            violation_reasons=tuple(sorted(a.violation_reasons, key=lambda r: r.value)),
        )
        for a in sorted_assessments
    )
    sorted_disclosures = tuple(
        sorted(receipt.required_disclosures, key=lambda d: (d.assertion_id, d.obligation.value))
    )
    sorted_violations = tuple(
        sorted(
            receipt.violations,
            key=lambda v: (v.reason.value, v.assertion_id or "", v.source_atom_id or ""),
        )
    )
    return dataclasses.replace(
        receipt,
        assertion_assessments=normalized_assessments,
        required_disclosures=sorted_disclosures,
        violations=sorted_violations,
        material_scope_coverage=tuple(sorted(receipt.material_scope_coverage)),
        omitted_scope_atom_ids=tuple(sorted(receipt.omitted_scope_atom_ids)),
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
    raise errors.IntegrityCanonicalizationError(f"cannot canonicalize value of type {type(value).__name__}")


def to_canonical_json(receipt: IntegrityReceipt) -> str:
    canonical = canonicalize(receipt)
    safe = _to_json_safe(canonical)
    try:
        text = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    except ValueError as exc:
        raise errors.IntegrityCanonicalizationError(f"non-finite value in receipt: {exc}") from exc
    if len(text.encode("utf-8")) > MAX_RECEIPT_SERIALIZED_BYTES:
        raise errors.PayloadLimitExceeded("canonical receipt JSON exceeds MAX_RECEIPT_SERIALIZED_BYTES")
    return text


def digest(receipt: IntegrityReceipt) -> str:
    """Proves content identity only -- no cryptographic authentication
    claim, matching OCL/Phase-18's own digest() doctrine."""
    return hashlib.sha256(to_canonical_json(receipt).encode("utf-8")).hexdigest()
