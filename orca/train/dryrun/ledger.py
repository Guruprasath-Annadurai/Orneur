"""Training-artifact provenance: an append-only, hash-chained RUN LEDGER plus an immutable sealed run manifest that is a normal
orca.registry.training_run.TrainingRunManifest (so existing registry tooling can read it) bound to the ledger head.

Why both: TrainingRunManifest.save() overwrites its file and the registry has no tamper evidence, so a run's story could be rewritten after
the fact. Here every event (start/binding, each committed step with its state hash, each checkpoint with its digest, stops, aborts, resume,
finish) is chained; the manifest records the ledger head at seal time and the ledger records the manifest's hash. Editing any one of the
three (ledger, manifest, checkpoint) breaks a cross-check. Nothing in orca/registry/training_run.py is modified.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from orca.registry.training_run import TrainingRunManifest
from orca.train.dryrun.canon import canonical_bytes, hash_obj, sha256_hex
from orca.train.dryrun.chainlog import ChainError, HashChainFile, VerifyResult

LEDGER_SCHEMA = "orneur-dryrun-run-ledger/1"
_REQUIRED = {
    "run_started": {"plan_sha256", "binding", "synthetic", "grant", "env_manifest_sha256", "budget"},
    "run_refused": {"reasons"},
    "run_resumed": {"from_step", "from_digest", "binding", "restore", "rejected_checkpoints"},
    "step_committed": {"step", "state_sha256", "tokens_seen", "spend_micro_usd"},
    "step_aborted": {"step", "reason"},
    "checkpoint_saved": {"step", "name", "digest"},
    "run_stopped": {"reason", "step", "state_sha256"},
    "run_finished": {"step", "state_sha256"},
    "manifest_sealed": {"manifest_sha256", "ledger_head_seq", "ledger_head_hash"},
}


def _semantic_problems(records: list) -> list:
    """State machine over the ordered events. Pure."""
    problems: list = []
    phase = "NEW"           # NEW -> RUNNING -> STOPPED|FINISHED|REFUSED -> SEALED
    for r in records:
        b, seq = r["body"], r["seq"]
        t = b.get("type")
        if t not in _REQUIRED:
            problems.append(f"UNKNOWN_EVENT_TYPE_AT_{seq}")
            continue
        if set(b) - {"type"} != _REQUIRED[t]:
            problems.append(f"EVENT_FIELDS_AT_{seq}")
            continue
        if phase == "NEW":
            if seq != 1 or t not in ("run_started", "run_refused"):
                problems.append(f"FIRST_EVENT_MUST_BE_START_OR_REFUSAL_AT_{seq}")
            phase = "RUNNING" if t == "run_started" else "REFUSED"
        elif phase == "RUNNING":
            # run_resumed IS allowed here: a process that crashed never wrote run_stopped, and recovering from that is the point of resume.
            if t in ("run_started", "run_refused", "manifest_sealed"):
                problems.append(f"EVENT_{t}_NOT_ALLOWED_WHILE_RUNNING_AT_{seq}")
            elif t == "run_stopped":
                phase = "STOPPED"
            elif t == "run_finished":
                phase = "FINISHED"
        elif phase == "STOPPED":
            if t == "run_resumed":
                phase = "RUNNING"
            elif t == "manifest_sealed":
                phase = "SEALED_STOPPED"
            else:
                problems.append(f"EVENT_{t}_AFTER_STOP_AT_{seq}")
        elif phase in ("FINISHED", "REFUSED"):
            if t == "manifest_sealed":
                phase = "SEALED"
            else:
                problems.append(f"EVENT_{t}_AFTER_TERMINAL_AT_{seq}")
        elif phase == "SEALED_STOPPED":
            if t == "run_resumed":
                phase = "RUNNING"
            else:
                problems.append(f"EVENT_{t}_AFTER_SEAL_AT_{seq}")
        else:
            problems.append(f"EVENT_{t}_AFTER_SEAL_AT_{seq}")
    return problems


class RunLedger:
    def __init__(self, path, *, anchor_key: bytes | None = None):
        self.chain = HashChainFile(path, anchor=True, anchor_key=anchor_key)
        self.path = self.chain.path

    def verify(self) -> VerifyResult:
        res = self.chain.verify(require_anchor=True)
        if res.ok:
            problems = _semantic_problems(res.records)
            if problems:
                res.ok = False
                res.problems.extend(problems)
        return res

    def append(self, type_: str, **fields) -> dict:
        if type_ not in _REQUIRED or set(fields) != _REQUIRED[type_]:
            raise ValueError(f"bad ledger event {type_!r}")
        body = {"type": type_, **fields}
        canonical_bytes(body)                                   # must be canonically serializable (no NaN)
        res = self.chain.verify(require_anchor=True)
        if not res.ok:
            raise ChainError("refusing to append to a tampered ledger: " + ",".join(res.problems))
        trial = _semantic_problems(res.records + [{"seq": res.last_seq + 1, "body": body}])
        if trial:
            raise ChainError("ledger state machine refuses event: " + ",".join(trial))
        return self.chain.append(body)

    def records(self) -> list:
        return self.verify().records

    def checkpoint_digests(self) -> dict:
        """step -> digest for every checkpoint the (verified) ledger recorded; empty if the ledger is not intact."""
        res = self.verify()
        if not res.ok:
            return {}
        return {r["body"]["step"]: r["body"]["digest"] for r in res.records if r["body"]["type"] == "checkpoint_saved"}

    def run_started_body(self) -> dict | None:
        res = self.verify()
        if not res.ok or not res.records or res.records[0]["body"].get("type") != "run_started":
            return None
        return res.records[0]["body"]


# ─── sealed manifest (a real TrainingRunManifest) ─────────────────────────────────────────────────────────────────────────────

def build_run_manifest(*, run_id: str, plan, binding: dict, ledger: RunLedger, checkpoint_names: list, failure_state: str | None,
                       final_state_sha256: str | None, env_manifest_sha256: str, start_time: str, end_time: str) -> TrainingRunManifest:
    seq, head = ledger.chain.head()
    dataset_id = "synthetic-regression-" + hash_obj({"data_seed": plan.data_seed, "n": plan.n_examples, "d": plan.n_features})[:8]
    cfg = {**plan.as_dict(), "dryrun_ledger": {"schema": LEDGER_SCHEMA, "head_seq": seq, "head_hash": head},
           "env_manifest_sha256": env_manifest_sha256, "binding": binding, "final_state_sha256": final_state_sha256, "synthetic": True}
    return TrainingRunManifest(
        run_id=run_id, model_id="synthetic-toy-linear", base_model="synthetic/toy-linear-v1", dataset_manifest_ids=[dataset_id],
        training_config=cfg, hyperparameters={"optimizer": plan.optimizer, "lr": plan.lr, "grad_accum": plan.grad_accum,
                                              "micro_batch": plan.micro_batch, "total_steps": plan.total_steps},
        seed=plan.seed, precision="float64-pure-python", hardware_info="CPU-only pure-Python; no GPU; SYNTHETIC",
        git_sha=binding.get("git_sha", "UNKNOWN"), start_time=start_time, end_time=end_time, checkpoint_outputs=list(checkpoint_names),
        failure_state=failure_state, compute_provider="synthetic-dryrun", dataset_content_digests={dataset_id: plan.sha256},
        dataset_split_digests={"train": plan.sha256}, dataset_bundle_id=None)


def seal_run_manifest(ledger: RunLedger, manifest: TrainingRunManifest, directory, filename: str | None = None) -> Path:
    """Write the manifest EXCLUSIVELY (never overwriting) and chain its hash into the ledger. Refuses if the manifest's embedded ledger head is
    not the current head (i.e. events happened after the manifest was built)."""
    seq, head = ledger.chain.head()
    emb = (manifest.training_config or {}).get("dryrun_ledger", {})
    if emb.get("head_seq") != seq or emb.get("head_hash") != head:
        raise ChainError("manifest does not bind the current ledger head")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename or f"{manifest.run_id}.manifest.json")
    data = (json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)      # O_EXCL: a sealed manifest can never be replaced
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    ledger.append("manifest_sealed", manifest_sha256=sha256_hex(data), ledger_head_seq=seq, ledger_head_hash=head)
    return path


def verify_sealed_manifest(path, ledger: RunLedger) -> list:
    """Cross-checks manifest <-> ledger. Returns a list of problem codes (empty == consistent)."""
    res = ledger.verify()
    if not res.ok:
        return ["LEDGER_NOT_INTACT:" + ",".join(res.problems)]
    sealed = [r for r in res.records if r["body"]["type"] == "manifest_sealed"]
    if not sealed:
        return ["MANIFEST_NOT_SEALED_IN_LEDGER"]
    try:
        data = Path(path).read_bytes()
        doc = json.loads(data)
        TrainingRunManifest(**doc)               # still a valid registry manifest
    except (OSError, ValueError, TypeError):
        return ["MANIFEST_UNREADABLE_OR_NOT_A_TRAININGRUNMANIFEST"]
    ev = next((r["body"] for r in sealed if r["body"]["manifest_sha256"] == sha256_hex(data)), None)
    if ev is None:                                # no sealed event carries this file's hash: the file was edited, replaced or never sealed
        return ["MANIFEST_HASH_MISMATCH"]
    problems = []
    emb = (doc.get("training_config") or {}).get("dryrun_ledger", {})
    at = next((r for r in res.records if r["seq"] == emb.get("head_seq")), None)
    if at is None or at["hash"] != emb.get("head_hash") or emb.get("head_seq") != ev["ledger_head_seq"] or emb.get("head_hash") != ev["ledger_head_hash"]:
        problems.append("MANIFEST_LEDGER_HEAD_MISMATCH")
    return problems
