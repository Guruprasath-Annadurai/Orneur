"""
The ONE canonical definition of the Phase 21B.4.20 locked runtime smoke protocol.

Single source of truth for: smoke ids, the exact user-message bytes, the request mode, and the exact acceptance semantics. Every
execution path (the shared runner, the Modal harnesses, the record builder, the validator, the Qwen configuration analysis) and every
test consumes THIS file; nothing may hand-write a smoke string of its own. The module is standard-library only so it can be shipped
next to the runner into a container or Studio that has no `orca` package.

Fail-closed: `PINNED_PROTOCOL_SHA256` is the fingerprint of the complete protocol. Importing this module verifies it, so a one-character
change to a prompt, an expected value, the request mode or the acceptance kind stops every consumer until the change is made
deliberately (new pinned hash, new owner lock) -- it can never drift silently.

Permitted normalization for acceptance is exactly one thing: Python `str.strip()` of the response content, applied identically to all
smokes. There is no "contains", "mentions", "starts with", HTTP-status-only or non-empty-only acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import json

PROTOCOL_ID = "GENESIS_CONTROL_RUNTIME_LOCKED_SMOKE_PROTOCOL"
NORMALIZATION = "str.strip() (surrounding whitespace only), identical for every smoke"

# (smoke_id, purpose, exact user-message text, request mode, acceptance). `expected` is the acceptance target, never a prompt.
SMOKE_DEFINITIONS: tuple[dict, ...] = (
    {"smoke_id": "A", "purpose": "deterministic readiness", "user": "Reply exactly:\nREADY", "stream": True,
     "acceptance": {"kind": "exact_text", "expected": "READY"}},
    {"smoke_id": "B", "purpose": "trivial instruction following", "user": "2 + 3", "stream": False,
     "acceptance": {"kind": "exact_text", "expected": "5"}},
    {"smoke_id": "C", "purpose": "short structured response", "user": 'Return valid JSON:\n{"status":"ready"}', "stream": False,
     "acceptance": {"kind": "json_equal", "expected": {"status": "ready"}}},
)

# Fingerprint of the complete protocol (see protocol_sha256). Changing ANY protocol byte requires a deliberate re-pin.
PINNED_PROTOCOL_SHA256 = "d462103b607e9741786ef86afc0b1769d5857d6e7feef36de516dac87a2b25c1"


def _defs(definitions=None):
    return SMOKE_DEFINITIONS if definitions is None else definitions


def smoke_ids(definitions=None) -> tuple[str, ...]:
    return tuple(d["smoke_id"] for d in _defs(definitions))


def _definition(smoke_id: str, definitions=None) -> dict:
    for d in _defs(definitions):
        if d["smoke_id"] == smoke_id:
            return d
    raise KeyError(f"unknown locked smoke {smoke_id!r}")


def messages(smoke_id: str, definitions=None) -> list[dict]:
    """The exact chat messages sent for this smoke (a single user message; no system message)."""
    return [{"role": "user", "content": _definition(smoke_id, definitions)["user"]}]


def prompt_utf8(smoke_id: str, definitions=None) -> bytes:
    return _definition(smoke_id, definitions)["user"].encode("utf-8")


def prompt_sha256(smoke_id: str, definitions=None) -> str:
    return hashlib.sha256(prompt_utf8(smoke_id, definitions)).hexdigest()


def _canonical_document(definitions=None) -> dict:
    return {"protocol_id": PROTOCOL_ID, "normalization": NORMALIZATION,
            "smokes": [{"smoke_id": d["smoke_id"], "messages": messages(d["smoke_id"], definitions), "stream": d["stream"],
                        "acceptance": d["acceptance"]} for d in _defs(definitions)]}


def canonical_protocol_bytes(definitions=None) -> bytes:
    """Canonical JSON (sorted keys, no insignificant whitespace, UTF-8, no ASCII escaping) of the complete protocol."""
    return json.dumps(_canonical_document(definitions), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def protocol_sha256(definitions=None) -> str:
    return hashlib.sha256(canonical_protocol_bytes(definitions)).hexdigest()


def verify_protocol_integrity(definitions=None) -> None:
    got = protocol_sha256(definitions)
    if got != PINNED_PROTOCOL_SHA256:
        raise RuntimeError(f"locked smoke protocol drift: fingerprint {got} != pinned {PINNED_PROTOCOL_SHA256}")


def protocol_document(definitions=None) -> dict:
    """Everything worth persisting: exact messages, UTF-8 bytes (hex), per-prompt sha256, acceptance, and the protocol sha256."""
    doc = _canonical_document(definitions)
    doc["prompts"] = [{"smoke_id": d["smoke_id"], "messages": messages(d["smoke_id"], definitions), "utf8_hex": prompt_utf8(d["smoke_id"], definitions).hex(),
                       "sha256": prompt_sha256(d["smoke_id"], definitions), "stream": d["stream"], "acceptance": d["acceptance"]} for d in _defs(definitions)]
    doc["canonical_json_utf8_sha256"] = protocol_sha256(definitions)
    doc["protocol_sha256"] = doc["canonical_json_utf8_sha256"]
    return doc


def runner_smokes(definitions=None) -> list[dict]:
    """The plain-data list the runner/harnesses iterate: smoke_id, purpose, user, expected (display), stream, acceptance."""
    return [{"smoke_id": d["smoke_id"], "purpose": d["purpose"], "user": d["user"],
             "expected": d["acceptance"]["expected"] if d["acceptance"]["kind"] == "exact_text"
             else json.dumps(d["acceptance"]["expected"], separators=(",", ":")),
             "stream": d["stream"], "acceptance": copy.deepcopy(d["acceptance"])} for d in _defs(definitions)]


def acceptance(smoke_id: str, content, definitions=None) -> tuple[bool, str]:
    """Pure. Does `content` satisfy the locked requirement EXACTLY? (whitespace-strip only; generated text is data, never executed)"""
    try:
        rule = _definition(smoke_id, definitions)["acceptance"]
    except KeyError:
        return False, f"unknown smoke {smoke_id!r}"
    if not isinstance(content, str):
        return False, "no string content"
    text = content.strip()
    want = rule["expected"]
    if rule["kind"] == "exact_text":
        return (text == want, "exact match" if text == want else f"content is not exactly {want!r}")
    try:
        parsed = json.loads(text)
    except ValueError:
        return False, "content is not valid JSON"
    ok = isinstance(parsed, dict) and parsed == want
    return ok, ("parsed JSON equals the exact object" if ok else f"parsed JSON is not exactly {json.dumps(want, separators=(',', ':'))}")


verify_protocol_integrity()
