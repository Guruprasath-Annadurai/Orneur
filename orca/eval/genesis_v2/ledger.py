"""Immutable, hash-chained access ledger + write-once holdout lifecycle.

A private-corpus grant is issued only AFTER its access record is durably created (create-exclusive file, chained to the previous record).
Only pre-registered processes (id + code hash + allowed purposes/splits) may be granted access. The qualification holdout opens once per
holdout version: no re-run, no tuning, no adapted derivative against an opened holdout — that needs a fresh holdout version.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from orca.eval.genesis_v2 import spec

GENESIS_HASH = "0" * 64
_HEX = re.compile(r"^[0-9a-f]{64}$")


class AccessDenied(PermissionError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class LedgerCorrupt(ValueError):
    pass


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _h(o) -> str:
    return hashlib.sha256(_canon(o).encode()).hexdigest()


@dataclass(frozen=True)
class RegisteredProcess:
    """Pre-registered (in the frozen public preregistration) process allowed to touch private splits."""
    process_id: str
    code_sha256: str
    purposes: tuple
    splits: tuple


@dataclass(frozen=True)
class AccessRequest:
    process_id: str
    code_sha256: str
    purpose: str
    split: str
    eval_version: str
    corpus_digest: str
    run_id: str
    candidate_revision: str
    candidate_lineage: str
    derived_from_lineages: tuple = ()
    timestamp_utc: str = ""


REQUIRED_FIELDS = ("who", "purpose", "eval_version", "timestamp_utc", "corpus_digest", "run_id", "candidate_revision")


class AccessLedger:
    def __init__(self, directory: Path, registry: dict[str, RegisteredProcess], *, freeze: dict | None = None):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._registry = dict(registry)
        self._freeze = freeze or spec.freeze_status()

    # -- reading / verification ------------------------------------------------------------------------------------------------------
    def records(self) -> list:
        out = []
        for p in sorted(self._dir.glob("[0-9]" * 8 + ".json")):
            out.append(json.loads(p.read_text()))
        return out

    def verify_chain(self) -> int:
        prev, n = GENESIS_HASH, 0
        files = sorted(self._dir.glob("*.json"))
        for i, p in enumerate(files):
            if p.name != f"{i:08d}.json":
                raise LedgerCorrupt(f"gap or foreign file at {p.name}")
            rec = json.loads(p.read_text())
            body = {k: v for k, v in rec.items() if k != "record_hash"}
            if rec.get("prev_hash") != prev or not _HEX.match(str(rec.get("record_hash", ""))) or _h(body) != rec["record_hash"]:
                raise LedgerCorrupt(f"broken chain at {p.name}")
            prev, n = rec["record_hash"], n + 1
        return n

    # -- derived lifecycle -----------------------------------------------------------------------------------------------------------
    def holdout_state(self, eval_version: str) -> dict:
        opened_by, retired = None, False
        lineages: list = []
        for r in self.records():
            if r.get("split") != "QUALIFICATION_HOLDOUT" or r.get("eval_version") != eval_version or r.get("kind") != "ACCESS":
                continue
            if r["purpose"] == spec.PURPOSE_QUALIFICATION:
                opened_by = opened_by or r
                lineages.append(r["candidate_lineage"])
            if r["purpose"] == spec.PURPOSE_RETIREMENT:
                retired = True
        state = spec.STATE_RETIRED if retired else (spec.STATE_OPENED if opened_by else spec.STATE_SEALED)
        return {"state": state, "opened_by": opened_by, "lineages": lineages}

    def _append(self, body: dict) -> dict:
        recs = self.records()
        prev = recs[-1]["record_hash"] if recs else GENESIS_HASH
        body = {**body, "seq": len(recs), "prev_hash": prev}
        rec = {**body, "record_hash": _h(body)}
        path = self._dir / f"{len(recs):08d}.json"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)   # create-exclusive, read-only: a record is never overwritten
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False, indent=1))
        return rec

    # -- the gate --------------------------------------------------------------------------------------------------------------------
    def request_access(self, req: AccessRequest) -> dict:
        proc = self._registry.get(req.process_id)
        if proc is None:
            raise AccessDenied("PROCESS_NOT_PREREGISTERED", req.process_id)
        if req.code_sha256 != proc.code_sha256:
            raise AccessDenied("CODE_HASH_MISMATCH", "running code differs from the pre-registered process")
        if req.split not in spec.PRIVATE_SPLITS:
            raise AccessDenied("NOT_A_PRIVATE_SPLIT", req.split)
        if req.purpose in spec.FORBIDDEN_PURPOSES:
            raise AccessDenied("FORBIDDEN_PURPOSE", req.purpose)
        if req.purpose not in spec.ALLOWED_PURPOSES[req.split] or req.purpose not in proc.purposes or req.split not in proc.splits:
            raise AccessDenied("PURPOSE_NOT_PERMITTED", f"{req.purpose} on {req.split}")
        if req.eval_version != spec.EVAL_VERSION:
            raise AccessDenied("WRONG_EVAL_VERSION", "V1 runs can never qualify against V2" if req.eval_version.startswith("genesis-capability-eval/1") else req.eval_version)
        for f in ("run_id", "candidate_revision", "candidate_lineage", "corpus_digest"):
            if not getattr(req, f):
                raise AccessDenied("MISSING_FIELD", f)
        if not _HEX.match(req.corpus_digest):
            raise AccessDenied("BAD_CORPUS_DIGEST", "must be a sha256 hex digest")
        if not req.timestamp_utc:
            raise AccessDenied("MISSING_FIELD", "timestamp_utc")
        if req.split == "QUALIFICATION_HOLDOUT":
            st = self.holdout_state(req.eval_version)
            if req.purpose == spec.PURPOSE_QUALIFICATION:
                if not self._freeze.get("frozen"):
                    raise AccessDenied("EVAL_NOT_FROZEN", "qualification holdout access requires GENESIS_CAPABILITY_EVAL_V2_FROZEN")
                if st["state"] == spec.STATE_RETIRED:
                    raise AccessDenied("HOLDOUT_RETIRED", "a retired holdout can no longer qualify anything")
                if req.candidate_lineage in st["lineages"]:
                    raise AccessDenied("HOLDOUT_ALREADY_OPENED", "write-once per candidate lineage: no re-run, tuning or retry; a fresh holdout version is required")
                if any(l in st["lineages"] for l in req.derived_from_lineages):
                    raise AccessDenied("FRESH_HOLDOUT_VERSION_REQUIRED", "adapted from a lineage that already opened this holdout")
            elif req.purpose == spec.PURPOSE_RETIREMENT and st["state"] != spec.STATE_OPENED:
                raise AccessDenied("NOT_OPENED", "disclosure is only allowed after the holdout was used and formally retired")
        if req.split == "SCREEN" and not self._freeze.get("frozen"):
            raise AccessDenied("EVAL_NOT_FROZEN", "screen access requires the frozen preregistration")
        return self._append({
            "kind": "ACCESS", "who": req.process_id, "process_code_sha256": req.code_sha256, "purpose": req.purpose, "split": req.split,
            "eval_version": req.eval_version, "timestamp_utc": req.timestamp_utc, "corpus_digest": req.corpus_digest, "run_id": req.run_id,
            "candidate_revision": req.candidate_revision, "candidate_lineage": req.candidate_lineage,
            "derived_from_lineages": list(req.derived_from_lineages)})

    def record_result(self, run_id: str, result_digest: str, timestamp_utc: str) -> dict:
        """Write-once result binding for a qualification run; a second result for the same run id is refused."""
        if not _HEX.match(result_digest):
            raise AccessDenied("BAD_RESULT_DIGEST")
        if any(r.get("kind") == "RESULT" and r["run_id"] == run_id for r in self.records()):
            raise AccessDenied("RESULT_ALREADY_RECORDED", run_id)
        if not any(r.get("kind") == "ACCESS" and r["run_id"] == run_id for r in self.records()):
            raise AccessDenied("UNKNOWN_RUN", run_id)
        return self._append({"kind": "RESULT", "run_id": run_id, "result_digest": result_digest, "timestamp_utc": timestamp_utc})


def reject_v1_evidence(record: dict) -> None:
    """V1 holdout results were computed on a publicly exposed corpus; they may never support a V2 private qualification."""
    ev = str(record.get("eval_version", ""))
    if ev.startswith("genesis-capability-eval/1") or record.get("split") == "HOLDOUT" or str(record.get("item_id", "")).startswith("gce1-"):
        raise AccessDenied("V1_EVIDENCE_REFUSED", "V1 is a public/development benchmark only")
