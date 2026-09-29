"""The single operational entry point every future corpus-generation code path MUST call before writing a single byte of
PILOT_TRAIN/DEV/SCREEN/QUALIFICATION_HOLDOUT content. Composes three independently fail-closed gates so that no single
compromised or stale record is sufficient on its own:

  1. corpus_generation_authorization.verify() against the REAL execution context (current git HEAD, the REAL current
     corpus-inventory digest, the REAL current preregistration record hash, the REAL event name) — never a
     caller-supplied context, so a caller cannot simply lie about what commit/evidence it is running against.
  2. The qualification-runner registry (runner_registry.py) must show `state == "AUTHORIZED"` for the running
     identity — `REGISTERED_NOT_AUTHORIZED` (the committed state throughout this whole program to date) still blocks
     generation even if a valid CORPUS_GENERATION_AUTHORIZATION record exists.
  3. Private-split reads/writes (SCREEN, QUALIFICATION_HOLDOUT) additionally go through
     `orca.eval.genesis_v2.ledger.AccessLedger`, which independently requires the process to be pre-registered,
     V2 to be FROZEN, and enforces the write-once-per-lineage holdout rule — this module never bypasses or replaces
     that ledger check, it is an ADDITIONAL gate before generation code would even reach the ledger.

Nothing in this module ever authorizes generation by itself — every check must independently pass.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
from orca.eval.genesis_v2 import inventory as INV
from orca.eval.genesis_v2 import prereg as PR
from orca.eval.genesis_v2 import runner_registry as RN


class CorpusGenerationNotAuthorized(PermissionError):
    """Raised by `require_authorization()`. Never caught-and-ignored by design — the caller is expected to abort."""


@dataclass
class BoundaryResult:
    authorized: bool
    reasons: list = field(default_factory=list)          # from corpus_generation_authorization.verify()
    runner_authorized: bool = False
    runner_state: str | None = None


def _current_commit_sha(root: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else ""


def _real_context(root: Path) -> tuple:
    """(commit_sha, inventory_digest, prereg_record_sha256) — always computed fresh from disk/git, never trusted from a caller."""
    inv = json.loads((root / INV.INVENTORY_PATH).read_text())
    inventory_digest = INV.inventory_digest(inv)
    draft = json.loads((root / PR.DRAFT_PATH).read_text())
    prereg_sha = draft.get("record_sha256", "")
    return _current_commit_sha(root), inventory_digest, prereg_sha


def _runner_authorized(root: Path, runner_id: str | None) -> tuple:
    """(authorized: bool, state: str|None). A runner identity not found in the registry, or found but not
    state==AUTHORIZED, is never treated as authorized."""
    reg_path = root / RN.REGISTRY_PATH
    if not reg_path.is_file():
        return False, None
    doc = json.loads(reg_path.read_text())
    if RN.validate(doc):
        return False, None
    records = doc.get("records", [])
    rec = next((r for r in records if r.get("runner_id") == runner_id), None) if runner_id else (records[0] if len(records) == 1 else None)
    if rec is None:
        return False, None
    return rec.get("state") == "AUTHORIZED", rec.get("state")


def check_authorization(root: Path, *, requested_scope: tuple, event_name: str = "", runner_id: str | None = None,
                         now=None) -> BoundaryResult:
    """Read-only: builds the real execution context, loads the real committed records, and returns a BoundaryResult.
    Never raises on a denial — only `require_authorization()` (below) turns a denial into an exception, so callers
    that just want to inspect the reasons (tests, dashboards, owner_preflight-style reporting) can call this safely."""
    root = Path(root)
    commit_sha, inv_digest, prereg_sha = _real_context(root)
    req = CGA.Request(commit_sha=commit_sha, requested_scope=tuple(requested_scope), current_inventory_digest=inv_digest,
                       current_prereg_record_sha256=prereg_sha, event_name=event_name)
    cga_path = root / CGA.RECORD_PATH
    record = json.loads(cga_path.read_text()) if cga_path.is_file() else CGA.default_record()
    keys = CGA.load_keys(root)
    verdict = CGA.verify(record, req, keys, now=now)
    runner_ok, runner_state = _runner_authorized(root, runner_id)
    authorized = verdict.authorized and runner_ok
    reasons = list(verdict.reasons)
    if not runner_ok:
        reasons.append(f"RUNNER_NOT_AUTHORIZED:{runner_state or 'NOT_REGISTERED'}")
    return BoundaryResult(authorized=authorized, reasons=reasons, runner_authorized=runner_ok, runner_state=runner_state)


def require_authorization(root: Path, *, requested_scope: tuple, event_name: str = "", runner_id: str | None = None, now=None) -> BoundaryResult:
    """The actual call site every future corpus-generation entry point must make. Raises CorpusGenerationNotAuthorized
    with the full reason list on any denial; returns the (authorized=True) BoundaryResult only when every gate passed."""
    result = check_authorization(root, requested_scope=requested_scope, event_name=event_name, runner_id=runner_id, now=now)
    if not result.authorized:
        raise CorpusGenerationNotAuthorized(f"corpus generation denied: {result.reasons}")
    return result
