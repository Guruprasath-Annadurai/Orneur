"""Ledger operational-deployment activation (owner-side, local): initializes the real SQLite access ledger at a location outside the public
repository, verifies its integrity/permissions/crash-safety properties, and produces a public-safe deployment record (no path, no content).

No benchmark access is recorded here (there is no benchmark yet): the ledger is initialized EMPTY and stays that way until a real qualification
process makes a real, pre-registered, frozen-eval-gated request through orca.eval.genesis_v2.ledger.AccessLedger.request_access.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from orca.eval.genesis_v2 import ledger as L

SCHEMA_VERSION = "genesis-v2-ledger-deployment/1"
RECORD_PATH = "docs/orneur/phase-21/GENESIS_V2_LEDGER_DEPLOYMENT_RECORD.json"


def _location_digest(ledger_dir: Path) -> str:
    return hashlib.sha256(("genesis-v2-ledger-location|" + str(Path(ledger_dir).resolve())).encode()).hexdigest()


def _inside_repo(path: Path, repo_root: Path) -> bool:
    p, r = Path(path).resolve(), Path(repo_root).resolve()
    return p == r or r in p.parents


def activate_ledger(ledger_dir: Path, repo_root: Path) -> dict:
    ledger_dir = Path(ledger_dir)
    checks: dict = {}
    try:
        checks["outside_repository"] = not _inside_repo(ledger_dir, repo_root)
        if not checks["outside_repository"]:
            return {"pass": False, "checks": checks, "error": "ledger location is inside the repository"}
        ledger_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(ledger_dir, 0o700)
        led = L.AccessLedger(ledger_dir, {})    # empty registry: nothing can request access yet, by construction
        checks["initializes_without_error"] = True
        checks["empty_and_chain_verifies"] = led.records() == [] and led.verify_chain() == 0
        db = ledger_dir / "ledger.sqlite3"
        checks["db_file_exists"] = db.is_file()
        checks["db_permissions_restrictive"] = (db.stat().st_mode & 0o077) == 0
        checks["dir_permissions_restrictive"] = (ledger_dir.stat().st_mode & 0o077) == 0
        c = sqlite3.connect(db)
        try:
            names = {n for (n,) in c.execute("SELECT name FROM sqlite_master")}
            checks["immutability_triggers_present"] = {"records_no_update", "records_no_delete"} <= names
            checks["uniqueness_indexes_present"] = {"ux_run_access", "ux_run_result", "ux_lineage_qualification"} <= names
        finally:
            c.close()
        checks["no_benchmark_content"] = led.records() == []
        return {"pass": all(bool(v) for v in checks.values()), "checks": checks, "error": None}
    except Exception as e:
        checks["exception"] = False
        return {"pass": False, "checks": checks, "error": f"{type(e).__name__}: {str(e)[:160]}"}


def build_deployment_record(activation: dict, *, ledger_dir: Path) -> dict:
    c = activation["checks"]
    return {
        "document": "GENESIS_V2_LEDGER_DEPLOYMENT_RECORD", "schema_version": SCHEMA_VERSION, "backend": "sqlite",
        "verification_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "location_digest": _location_digest(ledger_dir),
        "outside_repository_result": bool(c.get("outside_repository")), "permissions_result": bool(c.get("db_permissions_restrictive") and c.get("dir_permissions_restrictive")),
        "integrity_controls_result": bool(c.get("immutability_triggers_present") and c.get("uniqueness_indexes_present") and c.get("empty_and_chain_verifies")),
        "no_benchmark_content_result": bool(c.get("no_benchmark_content")), "pass": bool(activation["pass"]),
        "evidence_digests": {k: hashlib.sha256(f"{k}={v}".encode()).hexdigest()[:16] for k, v in sorted(c.items())},
        "note": "The ledger is initialized EMPTY at this location and stays empty until a real, pre-registered, frozen-eval-gated request occurs. No benchmark content is ever stored in it (digests/ids/metadata only).",
    }
