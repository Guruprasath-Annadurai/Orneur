"""
Reusable field validators for Phase 18, mirroring
orneur.intelligence.ocl.typecheck's pattern: every validator raises a
typed errors.Invalid* exception (never a raw TypeError/AttributeError),
and never echoes a caller-supplied value's repr into the error detail
(only type names / bounded identifiers), so malformed input can't leak
secret-shaped content into logs.
"""
from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from orneur.intelligence.epistemic import errors
from orneur.intelligence.epistemic.limits import MAX_STRING_FIELD_LENGTH


def require_string(value: object, *, where: str) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise errors.InvalidObjectType(f"{where}: expected str, got {type(value).__name__}")
    if len(value) > MAX_STRING_FIELD_LENGTH:
        raise errors.InvalidStructuredValue(f"{where}: string exceeds max length")
    return value


def require_instance(value: object, expected_type: type, *, where: str) -> object:
    # isinstance() correctly rejects a bare str equal to a str-mixin
    # Enum member's .value -- this is the entire point of this helper.
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
