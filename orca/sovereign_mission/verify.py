"""Independent re-verification of sovereign evidence records.

This process recomputes digests from the bytes it is given. It does not
witness authorship: a writer who replaces record, hash, and aggregate
together still matches. An external immutable witness is not claimed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orca.sovereign_mission.store import canonical, digest


class VerifyError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify_record(record: dict, claimed_sha256: str) -> dict:
    if not isinstance(record, dict) or not isinstance(claimed_sha256, str):
        raise VerifyError("record_refused")
    computed = digest(record)
    match = computed == claimed_sha256
    return {
        "match": match,
        "computed_sha256": computed,
        "claimed_sha256": claimed_sha256,
        "status": "intact" if match else "mismatch",
    }


def verify_aggregate(records: list[dict], claimed_aggregate: str) -> dict:
    hashes = []
    details = []
    for item in records:
        result = verify_record(item["record"], item["record_sha256"])
        details.append(result)
        hashes.append(item["record_sha256"])
        if not result["match"]:
            return {
                "status": "mismatch",
                "aggregate_match": False,
                "records": details,
                "witness": "local_recompute",
            }
    computed = digest({"evidence": hashes})
    match = computed == claimed_aggregate
    return {
        "status": "intact" if match else "mismatch",
        "aggregate_match": match,
        "computed_aggregate": computed,
        "claimed_aggregate": claimed_aggregate,
        "records": details,
        "witness": "local_recompute",
    }


def verify_marker_receipt(path: Path, expected_text: str, claimed_sha256: str | None = None) -> dict:
    if not path.is_file() or path.is_symlink():
        return {"status": "missing", "path": str(path), "match": False}
    body = path.read_bytes()
    text_ok = body.decode("utf-8", "replace") == expected_text
    computed = sha256_bytes(body)
    hash_ok = claimed_sha256 is None or computed == claimed_sha256
    return {
        "status": "verified" if text_ok and hash_ok else "mismatch",
        "match": text_ok and hash_ok,
        "computed_sha256": computed,
        "claimed_sha256": claimed_sha256,
        "witness": "local_filesystem",
    }


def verify_jsonl(path: Path) -> dict:
    if not path.is_file():
        raise VerifyError("evidence_missing")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        record = payload.get("record") or payload
        claimed = payload.get("record_sha256") or payload.get("content_sha256")
        if claimed is None:
            claimed = digest(record) if isinstance(record, dict) else sha256_bytes(line.encode())
            rows.append({"status": "unhashed", "match": False, "claimed_sha256": None})
            continue
        if isinstance(record, dict):
            rows.append(verify_record(record, claimed))
        else:
            computed = sha256_bytes(canonical(payload).encode() if isinstance(payload, dict) else line.encode())
            rows.append({"status": "intact" if computed == claimed else "mismatch", "match": computed == claimed})
    intact = all(row.get("match") for row in rows) and bool(rows)
    return {"status": "intact" if intact else "mismatch", "records": rows, "witness": "local_recompute"}
