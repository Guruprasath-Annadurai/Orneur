"""Immutable, hash-chained, transactional access ledger + write-once holdout lifecycle.

A private-corpus grant is issued only AFTER its access record is durably committed (SQLite transaction, chained to the previous record).
Only pre-registered processes (id + code hash + allowed purposes/splits) may be granted access. The qualification holdout opens once per
holdout version: no re-run, no tuning, no adapted derivative against an opened holdout — that needs a fresh holdout version.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS records(
  seq INTEGER PRIMARY KEY,
  kind TEXT NOT NULL, run_id TEXT NOT NULL, eval_version TEXT, candidate_lineage TEXT, purpose TEXT, split TEXT,
  prev_hash TEXT NOT NULL UNIQUE, record_hash TEXT NOT NULL UNIQUE, body TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_run_access ON records(run_id) WHERE kind='ACCESS';
CREATE UNIQUE INDEX IF NOT EXISTS ux_run_result ON records(run_id) WHERE kind='RESULT';
CREATE UNIQUE INDEX IF NOT EXISTS ux_lineage_qualification ON records(eval_version, candidate_lineage)
  WHERE kind='ACCESS' AND purpose='QUALIFICATION_RUN';
CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'ledger records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'ledger records are immutable'); END;
"""
_REQUIRED_SCHEMA_OBJECTS = ("ux_run_access", "ux_run_result", "ux_lineage_qualification", "records_no_update", "records_no_delete")


class AccessLedger:
    """SQLite-backed ledger. Every grant is decided AND appended inside one BEGIN IMMEDIATE transaction (a database-wide writer lock), so concurrent
    workers/processes are serialized: exactly one contiguous sequence number per record, a run id can be granted once, a qualification lineage can be
    granted once per eval version (enforced by unique indexes as well as by the checks), and records are immutable (triggers). A crash before COMMIT
    leaves no record (rollback); after COMMIT the record is durable (synchronous=FULL). A retried request is a NEW request with the same run id and is
    denied — an interrupted grant consumes its single run; adapting afterwards needs a fresh holdout version.
    Truncation (dropping the newest records) cannot be detected from the database alone: publish head_anchor() externally and pass it to verify_chain.
    """

    _fault = None   # test hook: callable invoked after INSERT and before COMMIT to simulate a crash

    def __init__(self, directory: Path, registry: dict[str, RegisteredProcess], *, freeze: dict | None = None):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "ledger.sqlite3"
        self._registry = dict(registry)
        self._freeze = freeze or spec.freeze_status()
        c = self._connect()
        try:
            c.executescript(_SCHEMA)   # idempotent (IF NOT EXISTS); serialized by SQLite's database lock
        finally:
            c.close()
        try:
            os.chmod(self._db, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db, timeout=60, isolation_level=None)
        c.execute("PRAGMA synchronous=FULL")
        c.execute("PRAGMA journal_mode=DELETE")
        return c

    # -- reading / verification ------------------------------------------------------------------------------------------------------
    def records(self) -> list:
        c = self._connect()
        try:
            return [{**json.loads(b), "record_hash": h} for b, h in c.execute("SELECT body, record_hash FROM records ORDER BY seq")]
        finally:
            c.close()

    def head_anchor(self) -> dict:
        r = self.records()
        return {"seq": len(r) - 1, "record_hash": r[-1]["record_hash"]} if r else {"seq": -1, "record_hash": GENESIS_HASH}

    def verify_chain(self, expected_head: dict | None = None) -> int:
        c = self._connect()
        try:
            names = {n for (n,) in c.execute("SELECT name FROM sqlite_master")}
            if not set(_REQUIRED_SCHEMA_OBJECTS) <= names:
                raise LedgerCorrupt("immutability triggers / uniqueness indexes are missing")
            rows = list(c.execute("SELECT seq, prev_hash, record_hash, body FROM records ORDER BY seq"))
        finally:
            c.close()
        prev = GENESIS_HASH
        for i, (seq, prev_hash, rec_hash, body) in enumerate(rows):
            d = json.loads(body)
            if seq != i or d.get("seq") != i:
                raise LedgerCorrupt(f"gap or reorder at position {i}")
            if prev_hash != prev or d.get("prev_hash") != prev or not _HEX.match(rec_hash) or _h(d) != rec_hash:
                raise LedgerCorrupt(f"broken chain at {i}")
            prev = rec_hash
        if expected_head is not None and (len(rows) - 1, prev) != (expected_head["seq"], expected_head["record_hash"]):
            raise LedgerCorrupt("head does not match the externally anchored head (truncation or fork)")
        return len(rows)

    def get_grant(self, run_id: str) -> dict | None:
        return next((r for r in self.records() if r.get("kind") == "ACCESS" and r["run_id"] == run_id), None)

    # -- derived lifecycle -----------------------------------------------------------------------------------------------------------
    @staticmethod
    def _state_from(recs: list, eval_version: str) -> dict:
        opened_by, retired = None, False
        lineages: list = []
        for r in recs:
            if r.get("split") != "QUALIFICATION_HOLDOUT" or r.get("eval_version") != eval_version or r.get("kind") != "ACCESS":
                continue
            if r["purpose"] == spec.PURPOSE_QUALIFICATION:
                opened_by = opened_by or r
                lineages.append(r["candidate_lineage"])
            if r["purpose"] == spec.PURPOSE_RETIREMENT:
                retired = True
        return {"state": spec.STATE_RETIRED if retired else (spec.STATE_OPENED if opened_by else spec.STATE_SEALED), "opened_by": opened_by, "lineages": lineages}

    def holdout_state(self, eval_version: str) -> dict:
        return self._state_from(self.records(), eval_version)

    def _append_tx(self, c: sqlite3.Connection, body: dict) -> dict:
        row = c.execute("SELECT seq, record_hash FROM records ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (row[0] + 1, row[1]) if row else (0, GENESIS_HASH)
        body = {**body, "seq": seq, "prev_hash": prev}
        rec = {**body, "record_hash": _h(body)}
        try:
            c.execute("INSERT INTO records(seq, kind, run_id, eval_version, candidate_lineage, purpose, split, prev_hash, record_hash, body) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (seq, body["kind"], body["run_id"], body.get("eval_version"), body.get("candidate_lineage"), body.get("purpose"), body.get("split"),
                       prev, rec["record_hash"], _canon(body)))
        except sqlite3.IntegrityError as e:
            raise AccessDenied("DUPLICATE_GRANT", "uniqueness constraint (run id / lineage) rejected the record") from e
        if self._fault:
            self._fault()
        return rec

    def _locked(self, fn):
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                out = fn(c)
                c.execute("COMMIT")
                return out
            except BaseException:
                c.execute("ROLLBACK")
                raise
        finally:
            c.close()

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
        if req.purpose in (spec.PURPOSE_QUALIFICATION, spec.PURPOSE_STAGE1) and not self._freeze.get("frozen"):
            raise AccessDenied("EVAL_NOT_FROZEN", "private-split access requires GENESIS_CAPABILITY_EVAL_V2_FROZEN")

        def txn(c):
            recs = [{**json.loads(b), "record_hash": h} for b, h in c.execute("SELECT body, record_hash FROM records ORDER BY seq")]
            if any(r.get("kind") == "ACCESS" and r["run_id"] == req.run_id for r in recs):
                raise AccessDenied("RUN_ALREADY_GRANTED", "a run id yields at most one grant; a retry is not a second authorization")
            if req.split == "QUALIFICATION_HOLDOUT":
                st = self._state_from(recs, req.eval_version)
                if req.purpose == spec.PURPOSE_QUALIFICATION:
                    if st["state"] == spec.STATE_RETIRED:
                        raise AccessDenied("HOLDOUT_RETIRED", "a retired holdout can no longer qualify anything")
                    if req.candidate_lineage in st["lineages"]:
                        raise AccessDenied("HOLDOUT_ALREADY_OPENED", "write-once per candidate lineage: no re-run, tuning or retry; a fresh holdout version is required")
                    if any(l in st["lineages"] for l in req.derived_from_lineages):
                        raise AccessDenied("FRESH_HOLDOUT_VERSION_REQUIRED", "adapted from a lineage that already opened this holdout")
                elif req.purpose == spec.PURPOSE_RETIREMENT and st["state"] != spec.STATE_OPENED:
                    raise AccessDenied("NOT_OPENED", "disclosure is only allowed after the holdout was used and formally retired")
            return self._append_tx(c, {
                "kind": "ACCESS", "who": req.process_id, "process_code_sha256": req.code_sha256, "purpose": req.purpose, "split": req.split,
                "eval_version": req.eval_version, "timestamp_utc": req.timestamp_utc, "corpus_digest": req.corpus_digest, "run_id": req.run_id,
                "candidate_revision": req.candidate_revision, "candidate_lineage": req.candidate_lineage,
                "derived_from_lineages": list(req.derived_from_lineages)})
        return self._locked(txn)

    def record_result(self, run_id: str, result_digest: str, timestamp_utc: str) -> dict:
        """Write-once, idempotent result binding: the same digest again returns the existing record; a different digest is refused."""
        if not _HEX.match(result_digest):
            raise AccessDenied("BAD_RESULT_DIGEST")

        def txn(c):
            recs = [{**json.loads(b), "record_hash": h} for b, h in c.execute("SELECT body, record_hash FROM records ORDER BY seq")]
            prior = next((r for r in recs if r.get("kind") == "RESULT" and r["run_id"] == run_id), None)
            if prior is not None:
                if prior["result_digest"] == result_digest:
                    return prior
                raise AccessDenied("RESULT_CONFLICT", "a different result is already recorded for this run")
            if not any(r.get("kind") == "ACCESS" and r["run_id"] == run_id for r in recs):
                raise AccessDenied("UNKNOWN_RUN", run_id)
            return self._append_tx(c, {"kind": "RESULT", "run_id": run_id, "result_digest": result_digest, "timestamp_utc": timestamp_utc})
        return self._locked(txn)


def reject_v1_evidence(record: dict) -> None:
    """V1 holdout results were computed on a publicly exposed corpus; they may never support a V2 private qualification."""
    ev = str(record.get("eval_version", ""))
    if ev.startswith("genesis-capability-eval/1") or record.get("split") == "HOLDOUT" or str(record.get("item_id", "")).startswith("gce1-"):
        raise AccessDenied("V1_EVIDENCE_REFUSED", "V1 is a public/development benchmark only")
