"""Canonical JSON + hashing shared by every evalinfra module (same convention as orca.eval.genesis_v2: sorted keys, compact separators)."""
from __future__ import annotations

import hashlib
import json
import re

GENESIS_HASH = "0" * 64
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def canonical(o) -> str:
    """Deterministic JSON. NaN/Infinity are refused (they have no canonical form)."""
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_hex(data) -> str:
    return hashlib.sha256(data if isinstance(data, (bytes, bytearray)) else str(data).encode()).hexdigest()


def obj_hash(o) -> str:
    return sha256_hex(canonical(o))


def is_hex64(v) -> bool:
    return isinstance(v, str) and bool(HEX64.match(v))


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))
