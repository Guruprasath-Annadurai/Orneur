"""Measured pretraining facts. This module does not accept a requirement.

It does not write the acceptance ledger, the register graph, a trust root,
or a training authorization. A worksheet here is a recomputation, not a
readiness percentage.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

from orca.eval.genesis_harness import HoldoutPurposeViolation, open_split
from orca.rse.imp1.locks import (
    corpus_generation_authorized,
    gpu_authorized,
    model_selection_authorized,
    prove_authorization_locks,
    qualification_authorized,
    training_authorized,
)

_REPO = Path(__file__).resolve().parents[2]
_EXPECTED_CPU = "Ryzen 7 9700X"
_EXPECTED_GPU = "RTX 5060 Ti"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worksheet(root: Path | None = None) -> dict:
    """List every counted pretraining id and the status stored in the graph."""
    base = Path(root) if root is not None else _REPO
    graph_path = base / "docs" / "orneur" / "acceptance" / "register_graph.json"
    ledger_path = base / "docs" / "orneur" / "acceptance" / "acceptance_ledger.json"
    before = _sha256(ledger_path)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    counted = [
        node for node in graph["nodes"]
        if node.get("denominator") == "PRE_TRAINING" and node.get("counts") is True
    ]
    counted.sort(key=lambda node: node["id"])
    accepted = ledger if isinstance(ledger, dict) else {}
    after = _sha256(ledger_path)
    if before != after:
        raise RuntimeError("worksheet changed the acceptance ledger")
    return {
        "schema": "orneur-pretraining-worksheet/1",
        "counted": len(counted),
        "ledger_accepted_count": len(accepted) if isinstance(accepted, dict) else 0,
        "ledger_sha256": after,
        "rows": [{"id": node["id"], "status": node["status"], "owner": node.get("implementation_owner")} for node in counted],
        "accepted_by_this_module": False,
    }


def spend_decision(requested_usd: float, root: Path | None = None) -> dict:
    base = Path(root) if root is not None else _REPO
    document = json.loads((base / "docs" / "orneur" / "authorization" / "MODEL_EVAL_AUTHORIZATION.json").read_text(encoding="utf-8"))
    cap = document.get("max_spend_usd")
    numeric = isinstance(cap, (int, float)) and not isinstance(cap, bool) and isinstance(requested_usd, (int, float)) and not isinstance(requested_usd, bool)
    above = numeric and requested_usd > cap
    return {
        "requested_usd": requested_usd,
        "cap_usd": cap,
        "authorization_status": document.get("status"),
        "gpu_allowed": document.get("gpu_allowed"),
        "above_cap_refused": above or not numeric,
        "within_cap": bool(numeric and 0 <= requested_usd <= cap),
        "training_authorized": False,
        "code": "spend_refused" if above or not numeric else "within_cap_training_still_denied",
    }


def training_identity_holdout(root: Path) -> dict:
    """The training purpose cannot open the private holdout split."""
    try:
        open_split(root, "HOLDOUT", "TRAINING")
    except HoldoutPurposeViolation as exc:
        return {"opened": False, "code": "holdout_refused", "detail": str(exc)}
    return {"opened": True, "code": "holdout_exposed"}


def lock_probe(root: Path | None = None) -> dict:
    before = {
        "corpus": corpus_generation_authorized(),
        "qualification": qualification_authorized(),
        "model_selection": model_selection_authorized(),
        "gpu": gpu_authorized(),
        "training": training_authorized(),
    }
    result = prove_authorization_locks(root)
    after = {
        "corpus": corpus_generation_authorized(),
        "qualification": qualification_authorized(),
        "model_selection": model_selection_authorized(),
        "gpu": gpu_authorized(),
        "training": training_authorized(),
    }
    return {
        "proof_decision": result.decision,
        "proof_reason": result.reason,
        "proof_ok": result.ok,
        "executable": result.executable,
        "before": before,
        "after": after,
        "locks_flipped": before != after or any(after.values()),
    }


def egress_decision(root: Path, candidate: Path) -> dict:
    """Refuse a path that escapes the training root, including a symlink."""
    base = root.resolve()
    if candidate.is_symlink():
        return {"allowed": False, "code": "symlink_refused"}
    try:
        resolved = candidate.resolve()
    except OSError:
        return {"allowed": False, "code": "path_unreadable"}
    if resolved != base and base not in resolved.parents:
        return {"allowed": False, "code": "outside_root"}
    if resolved.name == "holdout.jsonl":
        return {"allowed": False, "code": "holdout_path_refused"}
    return {"allowed": True, "code": "inside_root"}


def infrastructure_record(repo_sha: str) -> dict:
    """Describe this process. An absent workstation id stays absent."""
    return {
        "schema": "orneur-training-infrastructure/1",
        "repo_sha": repo_sha,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "p2_environment_id": None,
        "dry_run_launches_training": False,
        "gpu_permission": "DENIED",
        "training_authorized": training_authorized(),
        "complete": False,
    }


def workstation_probe() -> dict:
    """Observe this machine. Do not treat a match as founder hardware acceptance."""
    cpu = ""
    try:
        cpu = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        cpu = platform.processor() or ""
    model = ""
    for line in cpu.splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[-1].strip()
            break
    mem_kib = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                mem_kib = int(line.split()[1])
    except OSError:
        mem_kib = None
    smi = shutil.which("nvidia-smi")
    gpu_text = ""
    smi_ok = False
    if smi:
        try:
            completed = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=5, check=False)
            gpu_text = (completed.stdout or completed.stderr or "").strip()
            smi_ok = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            smi_ok = False
    profile_match = _EXPECTED_CPU in model and _EXPECTED_GPU in gpu_text and smi_ok
    return {
        "cpu_model": model,
        "mem_kib": mem_kib,
        "nvidia_smi": smi_ok,
        "gpu_text": gpu_text,
        "profile_strings_match": profile_match,
        "validated": False,
        "reason": "hardware acceptance requires an observed founder workstation and is not self-certified",
    }
