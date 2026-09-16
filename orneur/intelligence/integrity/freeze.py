"""
Deep, recursive validation + freezing of structured metadata values for
Phase 19, mirroring orneur.intelligence.epistemic.freeze's logic
exactly (which itself mirrors the Phase 17 OCL precedent). Deliberately
NOT imported directly from orneur.intelligence.epistemic.freeze for the
same reason as typecheck.py: the algorithm is identical, but malformed
Phase-19 metadata must raise Phase-19's own errors.IntegrityError
subclasses, keeping each phase's public error boundary self-contained.
"""
from __future__ import annotations

import math
from types import MappingProxyType

from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.limits import MAX_METADATA_DEPTH, MAX_METADATA_KEYS, MAX_STRING_FIELD_LENGTH


def validate_and_freeze(value: object, *, where: str, _depth: int = 0) -> object:
    if _depth > MAX_METADATA_DEPTH:
        raise errors.PayloadLimitExceeded(f"{where}: structured value nesting exceeds {MAX_METADATA_DEPTH}")

    if isinstance(value, (dict, MappingProxyType)):
        if len(value) > MAX_METADATA_KEYS:
            raise errors.PayloadLimitExceeded(f"{where}: mapping has more than {MAX_METADATA_KEYS} keys")
        frozen: dict[str, object] = {}
        for key, val in value.items():
            if not isinstance(key, str):
                raise errors.InvalidStructuredValue(f"{where}: mapping key is not a string (got {type(key).__name__})")
            if len(key) > MAX_STRING_FIELD_LENGTH:
                raise errors.InvalidStructuredValue(f"{where}: mapping key exceeds max string length")
            frozen[key] = validate_and_freeze(val, where=f"{where}.{key}", _depth=_depth + 1)
        return MappingProxyType(frozen)

    if isinstance(value, (list, tuple)):
        return tuple(
            validate_and_freeze(item, where=f"{where}[{i}]", _depth=_depth + 1) for i, item in enumerate(value)
        )

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise errors.InvalidStructuredValue(f"{where}: non-finite float (NaN/Infinity) is not allowed")
        return value

    if isinstance(value, str):
        if len(value) > MAX_STRING_FIELD_LENGTH:
            raise errors.InvalidStructuredValue(f"{where}: string exceeds max length")
        return value

    if value is None:
        return None

    raise errors.InvalidStructuredValue(f"{where}: unsupported metadata value type {type(value).__name__}")
