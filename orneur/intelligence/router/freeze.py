"""
Deep, recursive validation + freezing of structured metadata values for
Phase 20, mirroring orneur.intelligence.integrity.freeze's logic
exactly (same-algorithm duplication, Phase-20-namespaced errors -- see
errors.py's module docstring)."""
from __future__ import annotations

import math
from types import MappingProxyType

from orneur.intelligence.router import errors
from orneur.intelligence.router.limits import MAX_METADATA_DEPTH, MAX_METADATA_KEYS, MAX_STRING_FIELD_LENGTH


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


def require_mapping_root(value: object, *, where: str) -> object:
    """Metadata is a mapping contract at the ROOT -- a scalar must never
    silently pass just because validate_and_freeze() correctly accepts
    scalars as valid NESTED values."""
    if not isinstance(value, (dict, MappingProxyType)):
        raise errors.InvalidObjectType(f"{where}: expected a mapping, got {type(value).__name__}")
    return value
