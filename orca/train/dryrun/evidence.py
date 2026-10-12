"""Run-evidence integrity and recovery accounting for the synthetic dry-run (resilience #2, #3, #4, #5, #8). Read-only over a run directory,
except publish_content_addressed which writes one new immutable file. No trainer, no network, no gate: this module cannot start or authorize a run.

  * content-addressed manifests: a sealed manifest can be published under `sha256-<hash of its bytes>.manifest.json` (exclusive, read-only);
    verify_content_addressed() detects an edited or renamed file because name and content must agree;
  * effective_timeline(): the committed-step history a ledger implies once every resume rewinds to its verified checkpoint. A step that
    appears twice without a rewind is DOUBLE-COUNTED, a gap is SKIPPED -- recovery must produce neither;
  * verify_checkpoint_set(): every ledger-recorded checkpoint exists, verifies for THIS run id/plan/step/digest, is recorded in step order, and
    nothing unlisted sits beside them; returns a deterministic hash chain over (run, step, name, digest);
  * verify_run_evidence(): ledger chain + anchor, timeline, checkpoint set and every sealed manifest in one call (empty list == intact);
  * final_evidence_bytes(): canonical bytes of what a finished run proves, so a resumed run can be compared byte for byte with an
    uninterrupted one.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from orca.registry.checkpoint import CorruptCheckpointError
from orca.train.dryrun.canon import ZERO_HASH, canonical_bytes, hash_obj, sha256_hex
from orca.train.dryrun.ckpt import list_checkpoint_names, load_state, verify_checkpoint
from orca.train.dryrun.ledger import RunLedger, verify_sealed_manifest

EVIDENCE_SCHEMA = "orneur-dryrun-final-evidence/1"
_ADDR = re.compile(r"^sha256-([0-9a-f]{64})\.manifest\.json$")


class EvidenceError(RuntimeError):
    pass


# ─── content-addressed manifests ─────────────────────────────────────────────────────────────────────────────────────────────

def manifest_content_id(data: bytes) -> str:
    return sha256_hex(data)


def publish_content_addressed(manifest_path, store_dir) -> Path:
    data = Path(manifest_path).read_bytes()
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    dest = store / f"sha256-{manifest_content_id(data)}.manifest.json"
    if dest.exists():
        if dest.read_bytes() != data:
            raise EvidenceError("content address already holds different bytes (store tampered)")
        return dest
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return dest


def verify_content_addressed(path) -> list:
    p = Path(path)
    m = _ADDR.match(p.name)
    if not m:
        return ["NOT_A_CONTENT_ADDRESSED_NAME"]
    try:
        data = p.read_bytes()
    except OSError:
        return ["MANIFEST_UNREADABLE"]
    return [] if manifest_content_id(data) == m.group(1) else ["CONTENT_ADDRESS_MISMATCH"]


# ─── effective committed-step history ────────────────────────────────────────────────────────────────────────────────────────

def effective_timeline(ledger: RunLedger) -> tuple:
    """(timeline, problems). timeline[i] is the surviving commit of step i+1."""
    res = ledger.verify()
    if not res.ok:
        return [], ["LEDGER_NOT_INTACT:" + ",".join(res.problems)]
    tl, problems = [], []
    for rec in res.records:
        b = rec["body"]
        if b["type"] == "step_committed":
            s = b["step"]
            if s == len(tl) + 1:
                tl.append({"step": s, "state_sha256": b["state_sha256"], "tokens_seen": b["tokens_seen"], "spend_micro_usd": b["spend_micro_usd"]})
            elif s <= len(tl):
                problems.append(f"STEP_DOUBLE_COUNTED_AT_{s}")
            else:
                problems.append(f"STEP_SKIPPED_AT_{s}")
        elif b["type"] == "run_resumed":
            if b["from_step"] > len(tl):
                problems.append(f"RESUME_FROM_UNCOMMITTED_STEP_{b['from_step']}")
            else:
                del tl[b["from_step"]:]                          # everything after the verified checkpoint is rolled back and will be redone
    return tl, sorted(set(problems))


# ─── checkpoint set ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckpointSetReport:
    problems: list = field(default_factory=list)
    chain_head: str = ZERO_HASH
    names: list = field(default_factory=list)


def verify_checkpoint_set(root, plan, run_id: str) -> CheckpointSetReport:
    root = Path(root)
    ck = root / "checkpoints"
    rep = CheckpointSetReport()
    res = RunLedger(root / "ledger.jsonl").verify()
    if not res.ok:
        rep.problems.append("LEDGER_NOT_INTACT:" + ",".join(res.problems))
        return rep
    eff = {}
    for r in res.records:
        b = r["body"]
        if b["type"] == "checkpoint_saved":
            eff[b["step"]] = (r["seq"], b["name"], b["digest"])          # a later record for the same step supersedes a quarantined one
    ordered = sorted(eff.items())
    if [v[0] for _, v in ordered] != sorted(v[0] for _, v in ordered):
        rep.problems.append("CHECKPOINT_ORDER")
    on_disk = set(list_checkpoint_names(ck))
    head = ZERO_HASH
    for step, (_seq, name, digest) in ordered:
        rep.names.append(name)
        if name not in on_disk:
            rep.problems.append(f"CHECKPOINT_MISSING_{name}")
            continue
        try:
            vc = verify_checkpoint(ck, name, expected_plan_sha256=plan.sha256, expected_digest=digest, expected_step=step, expected_run_id=run_id)
            load_state(vc, plan)
        except CorruptCheckpointError as e:
            rep.problems.append(f"CHECKPOINT_UNVERIFIED_{name}:{e}")
            continue
        head = hash_obj({"prev": head, "run_id": run_id, "step": step, "name": name, "digest": digest})
    for name in sorted(on_disk - {n for _, (_s, n, _d) in ordered}):
        rep.problems.append(f"CHECKPOINT_UNLISTED_{name}")
    rep.chain_head = head
    rep.problems = sorted(set(rep.problems))
    return rep


# ─── one-call verification and the comparable final evidence ────────────────────────────────────────────────────────────────

def verify_run_evidence(root, plan, run_id: str) -> list:
    root = Path(root)
    ledger = RunLedger(root / "ledger.jsonl")
    res = ledger.verify()
    if not res.ok:
        return ["LEDGER_NOT_INTACT:" + ",".join(res.problems)]
    problems = []
    problems += effective_timeline(ledger)[1]
    problems += verify_checkpoint_set(root, plan, run_id).problems
    mdir = root / "manifests"
    files = sorted(p for p in mdir.iterdir() if p.is_file()) if mdir.is_dir() else []
    have = {}
    for p in files:
        have[sha256_hex(p.read_bytes())] = p
        problems += verify_sealed_manifest(p, ledger)
    for r in res.records:
        if r["body"]["type"] == "manifest_sealed" and r["body"]["manifest_sha256"] not in have:
            problems.append("SEALED_MANIFEST_FILE_MISSING")
    return sorted(set(problems))


def final_evidence(root, plan) -> dict:
    root = Path(root)
    ledger = RunLedger(root / "ledger.jsonl")
    tl, problems = effective_timeline(ledger)
    if problems:
        raise EvidenceError("run evidence is not intact: " + ",".join(problems))
    cps = {}
    for name in list_checkpoint_names(root / "checkpoints"):
        step = int(name.split("-")[1])
        if step % plan.checkpoint_every and step != plan.total_steps:
            continue                    # a checkpoint written at a stop/abort point is operational, not part of the plan-determined set
        cps[name] = json.loads((root / "checkpoints" / f"{name}.manifest.json").read_bytes())["artifact_checksum"]
    return {"schema": EVIDENCE_SCHEMA, "plan_sha256": plan.sha256, "steps": len(tl), "timeline_sha256": hash_obj(tl),
            "final_state_sha256": tl[-1]["state_sha256"] if tl else None, "checkpoints": cps}


def final_evidence_bytes(root, plan) -> bytes:
    return canonical_bytes(final_evidence(root, plan)) + b"\n"


__all__ = ["CheckpointSetReport", "EvidenceError", "effective_timeline", "final_evidence", "final_evidence_bytes", "manifest_content_id",
           "publish_content_addressed", "verify_checkpoint_set", "verify_content_addressed", "verify_run_evidence"]
