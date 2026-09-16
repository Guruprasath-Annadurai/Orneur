"""
Reusable field validators for Phase 19, mirroring
orneur.intelligence.epistemic.typecheck's logic exactly. Deliberately
NOT imported from orneur.intelligence.epistemic.typecheck: the
underlying isinstance-based logic is identical, but the raised
exceptions must be Phase-19's OWN errors.IntegrityError subclasses, not
epistemic.errors.* -- reusing the epistemic module directly would leak
a foreign exception type across Phase 19's own public boundary,
violating "every invalid public input must raise a typed IntegrityError
subclass." This small, intentional duplication exists only to keep each
phase's error taxonomy self-contained; the validation logic itself is
not novel.
"""
from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.limits import MAX_STRING_FIELD_LENGTH


def require_string(value: object, *, where: str) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise errors.InvalidObjectType(f"{where}: expected str, got {type(value).__name__}")
    if len(value) > MAX_STRING_FIELD_LENGTH:
        raise errors.InvalidStructuredValue(f"{where}: string exceeds max length")
    return value


def require_instance(value: object, expected_type: type, *, where: str) -> object:
    if not isinstance(value, expected_type):
        raise errors.InvalidObjectType(
            f"{where}: expected {expected_type.__name__}, got {type(value).__name__}"
        )
    return value


def require_sequence_container(value: object, *, where: str) -> Sequence:
    if not isinstance(value, (list, tuple)):
        raise errors.InvalidObjectType(
            f"{where}: expected list or tuple, got {type(value).__name__}"
        )
    return value


def require_enum_member(value: object, enum_cls: type[Enum], *, where: str) -> Enum:
    if not isinstance(value, enum_cls):
        raise errors.InvalidObjectType(
            f"{where}: expected {enum_cls.__name__} member, got {type(value).__name__}"
        )
    return value
