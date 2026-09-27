"""Shared identity-registry machinery for authority and reviewer registries: schema, validation, expiry/revocation, and derivation of the minimal
public key-list a signature verifier needs. Private signing keys are never handled here — only public keys ever enter these structures."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEX32 = re.compile(r"^[0-9a-f]{64}$")   # a raw Ed25519 public key is 32 bytes = 64 hex chars

BASE_FIELDS = ("id", "role", "public_key_hex", "activation_timestamp", "expiry", "revoked")


def _ts_ok(s) -> bool:
    return isinstance(s, str) and bool(_TS.match(s))


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def validate_base(r) -> list:
    p = []
    if not isinstance(r, dict):
        return ["record is not an object"]
    if not isinstance(r.get("id"), str) or not r["id"]:
        p.append("id must be a non-empty string")
    if not isinstance(r.get("public_key_hex"), str) or not _HEX32.match(r.get("public_key_hex", "")):
        p.append("public_key_hex must be 64 lowercase hex characters (a raw 32-byte Ed25519 public key)")
    if not _ts_ok(r.get("activation_timestamp")):
        p.append("activation_timestamp invalid")
    if r.get("expiry") is not None and not _ts_ok(r.get("expiry")):
        p.append("expiry must be null or a valid timestamp")
    if not isinstance(r.get("revoked"), bool):
        p.append("revoked must be a boolean")
    return p


def is_active(r: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not isinstance(r, dict) or r.get("revoked") is not False and r.get("revoked") is not True:
        return False
    if r.get("revoked") is True:
        return False
    try:
        if _parse(r["activation_timestamp"]) > now:
            return False
        if r.get("expiry") and _parse(r["expiry"]) <= now:
            return False
    except (KeyError, ValueError, TypeError):
        return False
    return True


def active_keys(doc: dict) -> list:
    """The minimal {key_id, public_key_hex, identity, role} shape the signature verifiers in authorization.py / review.py consume."""
    return [{"key_id": r["id"], "public_key_hex": r["public_key_hex"], "identity": r["id"], "role": r["role"]}
            for r in doc.get("records", []) if is_active(r)]


def empty_registry(schema_version: str) -> dict:
    return {"schema_version": schema_version, "records": []}


def load(path: Path, schema_version: str, validator) -> tuple:
    """Returns (doc_or_None, problems). Any read/parse/schema error => (None, [...]) — never a silent empty-but-valid registry."""
    try:
        doc = json.loads(Path(path).read_text())
    except Exception as e:
        return None, [f"unreadable: {type(e).__name__}"]
    problems = validator(doc)
    return (doc, []) if not problems else (None, problems)
