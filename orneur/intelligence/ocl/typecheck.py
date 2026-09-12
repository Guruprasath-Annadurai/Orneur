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

from types import MappingProxyType

from orneur.intelligence.ocl import limits
from orneur.intelligence.ocl.errors import InvalidObjectType, InvalidStructuredValue


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


def require_instance(value, expected_type, *, where: str):
    """Phase 17 type-parity closure: the compiler must not assume a
    collection element or object-valued field is the expected OCL
    dataclass/enum type merely because Python's type annotations say so --
    a direct programmatic caller can pass anything. Used for both plain
    dataclasses (CognitiveAtom, Provenance, ModelIdentityRef, ...) and
    Enum classes (AtomKind, SourceClass, EvidenceKind, RelationKind,
    ProducerKind, ...) -- `isinstance` against a str-mixin Enum class
    correctly rejects a plain string that merely equals a member's
    `.value` (the same doctrine already applied to CompilationTrustContext
    in trust.is_valid_trust_context())."""
    if not isinstance(value, expected_type):
        raise InvalidObjectType(f"{where}: expected {expected_type.__name__}, got {type(value).__name__}")
    return value


def require_sequence_container(value, *, where: str):
    """Phase 17 container-typing closure: a top-level draft sequence field
    (`artifact.atoms`, `.relations`, `.evidence`, ...) must be a `list` or
    `tuple` -- nothing else. A `dict`/`str` iterates to something silently
    wrong (an empty dict/string iterates to ZERO elements and would
    silently "compile as an empty collection" with no error at all); a
    generator/iterator/set is consumed exactly once, so a validator that
    iterates it during type-checking would find it exhausted on a later
    pass that needs to iterate it again (e.g. `len()` or a second loop) --
    this must be rejected outright, not merely tolerated. Checked BEFORE
    any iteration of the value, never after a generator has already been
    partially consumed."""
    if not isinstance(value, (list, tuple)):
        raise InvalidStructuredValue(f"{where}: expected a list or tuple, got {type(value).__name__}")
    return value


def require_structured_mapping(value, *, where: str):
    """The wire schema requires every metadata-shaped field to be a JSON
    OBJECT at its root (a bare JSON array/string/number is never a valid
    `metadata`), and programmatic construction must enforce the identical
    rule -- `validate_structured_value()` alone is insufficient here
    because it deliberately allows a list/tuple value (needed for nested
    JSON arrays *inside* a mapping), which would let a root-level list
    slip through as if it were a metadata object. This checks only the
    root container's shape; recursive content validation is a separate
    step via `validate_structured_value()`."""
    if not isinstance(value, (dict, MappingProxyType)):
        raise InvalidStructuredValue(f"{where}: expected a mapping (JSON object), got {type(value).__name__}")
    return value
