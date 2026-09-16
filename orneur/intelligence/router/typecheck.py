"""
Reusable field validators for Phase 20, mirroring
orneur.intelligence.integrity.typecheck's logic exactly (small,
deliberate, same-algorithm duplication -- see errors.py's module
docstring for why each phase keeps its own copy)."""
from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from orneur.intelligence.router import errors
from orneur.intelligence.router.limits import MAX_STRING_FIELD_LENGTH


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
    if not isinstance(value, (list, tuple, frozenset, set)):
        raise errors.InvalidObjectType(
            f"{where}: expected list/tuple/set/frozenset, got {type(value).__name__}"
        )
    return value


def require_enum_member(value: object, enum_cls: type[Enum], *, where: str) -> Enum:
    if not isinstance(value, enum_cls):
        raise errors.InvalidObjectType(
            f"{where}: expected {enum_cls.__name__} member, got {type(value).__name__}"
        )
    return value
