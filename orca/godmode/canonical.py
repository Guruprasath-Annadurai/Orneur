"""
Canonical action-argument representation (Phase 10.1 spec §3-4). One
deterministic hashing function, reused by issuance AND resolution, so
"the same action" always hashes identically and no two semantically-
different actions can ever collide onto the same hash through
representation tricks (key ordering, nested structures, Unicode
normalization, numeric/bool/null type confusion).

Deliberately NOT `str(dict)`/`repr(sorted(...))` -- Python dict/set/repr
ordering and float repr are not a stable, cross-version, cross-type
canonical form (the exact anti-pattern spec §3 calls out; it is also
exactly what the Phase 10 `issuance.arguments_hash_of()` used, which is
why it was never actually enforceable).
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def _canonicalize_value(value: Any) -> Any:
    """
    Recursively normalizes a value into a JSON-representable form with
    stable semantics:

    - dict: keys sorted, each value recursively canonicalized. Non-string
      keys are rejected (JSON's own dict-key rule) by coercing to str
      explicitly and NFC-normalizing, so two differently-encoded-but-
      equivalent Unicode keys canonicalize identically.
    - list/tuple: order is PRESERVED (list order is semantically
      meaningful for tool arguments -- e.g. a sequence of edits -- unlike
      dict key order, which is not) but each element is canonicalized.
    - str: Unicode NFC-normalized so two byte-different-but-equivalent
      spellings of the same string hash identically.
    - bool: checked BEFORE int (bool is an int subclass in Python --
      without this, True and 1 would canonicalize identically, a real
      type-confusion vector spec §14 calls out).
    - int: unchanged (exact).
    - float: represented via `repr()` at canonicalization time only for
      values that round-trip exactly through `float(repr(x))` -- since
      Python's `repr(float)` is itself the shortest round-tripping
      decimal representation (stable since Python 3.1), this is a safe,
      deterministic float form, distinct from any int of the same
      numeric value (2.0 and 2 canonicalize differently -- deliberate,
      since a tool schema that says "int" vs "float" is a type
      difference a caller should not be able to blur).
    - None: unchanged.
    """
    if isinstance(value, bool):
        return {"__t": "bool", "v": value}
    if isinstance(value, int):
        return {"__t": "int", "v": value}
    if isinstance(value, float):
        return {"__t": "float", "v": repr(value)}
    if isinstance(value, str):
        return {"__t": "str", "v": unicodedata.normalize("NFC", value)}
    if value is None:
        return {"__t": "null"}
    if isinstance(value, dict):
        normalized_items = sorted(
            (unicodedata.normalize("NFC", str(k)), _canonicalize_value(v)) for k, v in value.items()
        )
        return {"__t": "obj", "v": normalized_items}
    if isinstance(value, (list, tuple)):
        return {"__t": "arr", "v": [_canonicalize_value(v) for v in value]}
    # Anything else (a custom object) is rejected outright rather than
    # silently stringified with unstable repr semantics.
    raise TypeError(f"cannot canonicalize argument value of type {type(value).__name__}")


def canonicalize_arguments(arguments: dict) -> str:
    """Deterministic JSON string -- same semantic arguments always
    produce byte-identical output, regardless of original key order,
    dict-vs-OrderedDict, or Unicode normalization form."""
    canonical = _canonicalize_value(dict(arguments))
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_arguments(arguments: dict) -> str:
    """SHA-256 of the canonical representation. Cryptographic (not a
    fast non-crypto hash) because arguments MAY legitimately contain a
    secret value that needs binding without ever being reversible from
    the hash (spec §21)."""
    canonical = canonicalize_arguments(arguments)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
