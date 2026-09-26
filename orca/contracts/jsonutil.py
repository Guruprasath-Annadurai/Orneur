"""Strict JSON helpers shared by detection, validation and serialization (no repair, no leniency)."""
from __future__ import annotations

import json

MAX_JSON_CHARS = 4096
MAX_JSON_DEPTH = 20


class StrictJSONError(ValueError):
    pass


def _reject_constant(name):
    raise StrictJSONError(f"non-standard JSON constant {name!r} is not allowed")


def _no_duplicates(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise StrictJSONError(f"duplicate object key {k!r}")
        seen[k] = v
    return seen


def depth_of(value, _d=1) -> int:
    if isinstance(value, dict):
        return max([_d] + [depth_of(v, _d + 1) for v in value.values()])
    if isinstance(value, list):
        return max([_d] + [depth_of(v, _d + 1) for v in value])
    return _d


def strict_loads(text: str):
    """Parse the ENTIRE text as one JSON value. Rejects trailing data, NaN/Infinity, duplicate keys, oversize and over-deep documents."""
    if not isinstance(text, str):
        raise StrictJSONError("JSON text must be a string")
    if len(text) > MAX_JSON_CHARS:
        raise StrictJSONError("JSON text too long")
    try:
        value = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_no_duplicates)
    except RecursionError as e:
        raise StrictJSONError("JSON nesting too deep") from e
    except json.JSONDecodeError as e:
        raise StrictJSONError(f"not valid JSON: {e.msg}") from e
    if depth_of(value) > MAX_JSON_DEPTH:
        raise StrictJSONError("JSON nesting too deep")
    return value


def canonical_dumps(value) -> str:
    """The deterministic serialization ORNEUR emits (key order preserved; no whitespace; non-ASCII kept)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def strict_equal(a, b) -> bool:
    """Strict JSON value equality: True != 1, 1 != 1.0, key sets and list order must match exactly."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a.keys()).__len__() == len(b) and set(a) == set(b) and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b))
    return a == b
