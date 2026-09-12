"""
Reusable field-type validators (Phase 17 final closure section 3). The
compiler must not depend on the wire parser having already enforced
Python types -- a direct programmatic caller can construct a dataclass
with a value that violates its own type annotation (Python does not
enforce them at runtime), e.g. `ModelIdentityRef(family=[])`. Every
scalar/sequence field the compiler reads is validated through one of
these before use, so no raw `TypeError`/`AttributeError`/`KeyError` can
ever escape `compile_artifact()`.
"""
from __future__ import annotations

from orneur.intelligence.ocl import limits
from orneur.intelligence.ocl.errors import InvalidStructuredValue


def require_string(value, *, where: str) -> str:
    if not isinstance(value, str):
        raise InvalidStructuredValue(f"{where}: expected a string, got {type(value).__name__}")
    if len(value) > limits.MAX_STRING_FIELD_LENGTH:
        raise InvalidStructuredValue(f"{where}: string exceeds {limits.MAX_STRING_FIELD_LENGTH} chars")
    return value


def require_optional_string(value, *, where: str):
    if value is None:
        return None
    return require_string(value, where=where)


def require_string_sequence(value, *, where: str) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise InvalidStructuredValue(f"{where}: expected a sequence, got {type(value).__name__}")
    if len(value) > limits.MAX_METADATA_KEYS:
        raise InvalidStructuredValue(f"{where}: sequence exceeds {limits.MAX_METADATA_KEYS} elements")
    return tuple(require_string(v, where=f"{where}[]") for v in value)


def require_optional_int(value, *, where: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidStructuredValue(f"{where}: expected an int, got {type(value).__name__}")
    return value
