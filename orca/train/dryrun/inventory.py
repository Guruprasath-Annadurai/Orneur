"""Off-host / out-of-gate training inventory (Workstream G #13).

`scan_repo()` discovers every artifact in the repository that can train (or move model weights) OUTSIDE orca.train.authorization's control:
notebooks, Kaggle kernel-launch metadata, any Python file that constructs a trainer outside the two gated modules, launcher commands in
scripts/CI/containers, and off-host GPU runner scripts. `build_inventory()` joins that with the curated, reviewed facts below.
The committed inventory is docs/orneur/status/trainprep/OFFHOST_NOTEBOOK_INVENTORY.json; tests/test_trainprep_inventory.py fails when the
repo and the inventory disagree (a NEW training artifact, a changed hash, or a removed file), so adding one is always a visible, reviewed change.

Nothing here executes, imports or edits any notebook or script. It only reads text.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path

SCHEMA = "orneur-offhost-training-inventory/1"
INVENTORY_REL = "docs/orneur/status/trainprep/OFFHOST_NOTEBOOK_INVENTORY.json"
GATED_IN_REPO = {"orca/train/finetune.py", "orca/train/cloud.py"}       # construct trainers, but only after authorize_training()/require_grant()
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build", ".claude"}
_TRAINER_NAMES = {"SFTTrainer", "DPOTrainer", "ORPOTrainer", "KTOTrainer", "GRPOTrainer", "PPOTrainer", "RewardTrainer", "Trainer"}
_TRAINER_RE = re.compile(r"SFTTrainer|DPOTrainer|GRPOTrainer|ORPOTrainer|KTOTrainer|PPOTrainer|RewardTrainer|transformers\.Trainer|\btrainer\.train\(")
_EMBEDDED_RE = re.compile(r"\b(SFTTrainer|DPOTrainer|GRPOTrainer|ORPOTrainer|KTOTrainer|PPOTrainer|RewardTrainer)\(|\btrainer\.train\(\)")
_WEIGHT_RE =re.compile(r"FastLanguageModel|get_peft_model|save_pretrained_merged|save_pretrained_gguf|push_to_hub")
_LAUNCHER_RE = re.compile(r"\b(?:orneur|orca)\s+train\s+(?:run|nano|core|ultra|cloud)\b|python3?\s+-m\s+orca\.train\b|\btorchrun\b|\baccelerate\s+launch\b|\bdeepspeed\b")
_OFFHOST_GPU_RE = re.compile(r"^\s*(?:import|from)\s+(?:modal|lightning_sdk|runpod|vastai)\b", re.M)
_MODEL_RE = re.compile(r"[\"'](unsloth/[A-Za-z0-9._-]+|Qwen/[A-Za-z0-9._-]+|meta-llama/[A-Za-z0-9._-]+)[\"']")
_INPUT_RE = re.compile(r"[\"'](/kaggle/input/[^\"']+|/content/drive[^\"']*)[\"']")
_OUTPUT_RE = re.compile(r"[\"'](/kaggle/working/[^\"']+|/content/[A-Za-z0-9_./-]+\.(?:gguf|zip))[\"']")

_GENERIC_BYPASS = ("Runs on a third-party host (%s) with its own GPU quota and internet access. It imports the trainer stack directly and never imports "
                   "orca.train.authorization, so no TrainingGrant, signed authorization record, code-tree/dataset hash binding, run budget or audit event "
                   "applies. Anyone holding the notebook and a %s account can start it; ORNEUR code does not execute or observe it.")

# Curated, reviewed facts. `proposed_action` vocabulary: retire (superseded; remove from active tree after owner sign-off) | freeze (keep, hash-pinned,
# never run without an out-of-band equivalent of the gate) | gate (the lineage head: its next use must be re-expressed as `orneur train run`, which IS gated).
CURATED = {
    "notebooks/orca_core_calibration_sft_kaggle_v1.ipynb": ("core-calibration", "SFT calibration-fix adapter on top of the DPO adapter (Llama-3.1-8B-Instruct, plain PEFT).", "gate", "Only notebook for this stage; re-implement through the gated finetune path before any rerun."),
    "notebooks/orca_core_combined_sft_kaggle_v1.ipynb": ("core-combined", "Joint safety+calibration SFT pass on top of v2 (Llama-3.1-8B-Instruct, plain PEFT).", "gate", "Only notebook for this stage; re-implement through the gated finetune path before any rerun."),
    "notebooks/orca_core_dpo_kaggle_v1.ipynb": ("core-dpo", "Probe-grounded safety DPO on top of v2 (Llama-3.1-8B-Instruct), with merged + GGUF export.", "gate", "DPO has no gated in-repo path yet; a gated DPO entry point must exist before this is reused."),
    "notebooks/orca_core_dpo_merge_export_v1.ipynb": ("core-dpo", "No trainer: merges the DPO adapter into the base model and exports Q4_K_M GGUF off-host.", "freeze", "Loads and rewrites model weights off-host without any provenance record; keep frozen, require manual provenance if ever used."),
    "notebooks/orca_core_finetune_kaggle_v1.ipynb": ("core-finetune", "QLoRA SFT, Llama-3.1-8B-Instruct, orca_core_llama3 train/eval v1 data.", "retire", "Superseded by v2 of the same notebook (different data revision); keep only if the owner needs the history."),
    "notebooks/orca_core_finetune_kaggle_v2.ipynb": ("core-finetune", "QLoRA SFT, Llama-3.1-8B-Instruct, orca_core_llama3 train/eval v2 data, merged + GGUF export.", "gate", "Lineage head for core SFT; the gated path (orca.train.finetune) is its in-repo replacement."),
    "notebooks/orca_nano_dpo_kaggle_v1.ipynb": ("nano-dpo", "DPO safety + honesty fix on top of Nano v4 (Qwen2.5-7B-Instruct), merged + GGUF export.", "gate", "DPO has no gated in-repo path yet; a gated DPO entry point must exist before this is reused."),
    "notebooks/orca_nano_dpo_merge_fix_v2.ipynb": ("nano-dpo", "No trainer: merge/export repair for the Nano DPO adapter (GGUF + merged weights) off-host.", "freeze", "Rewrites model weights off-host without any provenance record; keep frozen."),
    "notebooks/orca_nano_finetune_colab.ipynb": ("nano-finetune-colab", "QLoRA SFT, Qwen2.5-7B-Instruct, Colab free T4, merged + GGUF export.", "retire", "Oldest Colab revision; superseded by v2-v4 and by the Kaggle lineage."),
    "notebooks/orca_nano_finetune_colab_v2.ipynb": ("nano-finetune-colab", "QLoRA SFT, Qwen2.5-7B-Instruct, Colab free T4 (Drive-backed outputs).", "retire", "Superseded by v3/v4."),
    "notebooks/orca_nano_finetune_colab_v3.ipynb": ("nano-finetune-colab", "QLoRA SFT, Qwen2.5-7B-Instruct, Colab free T4 (Drive-backed outputs).", "retire", "Superseded by v4."),
    "notebooks/orca_nano_finetune_colab_v4.ipynb": ("nano-finetune-colab", "QLoRA SFT, Qwen2.5-7B-Instruct, Colab free T4 (Drive-backed outputs). Latest Colab revision.", "freeze", "Latest on Colab; the owner decides whether the Kaggle lineage head makes it retirable. Frozen meanwhile."),
    "notebooks/orca_nano_finetune_kaggle.ipynb": ("nano-finetune-kaggle", "QLoRA SFT, Qwen2.5-7B-Instruct, Kaggle free T4/P100.", "retire", "Oldest Kaggle revision; superseded by v2-v4_safety."),
    "notebooks/orca_nano_finetune_kaggle_v2.ipynb": ("nano-finetune-kaggle", "QLoRA SFT, Qwen2.5-7B-Instruct, Kaggle T4x2/P100.", "retire", "Superseded by v3/v4_safety."),
    "notebooks/orca_nano_finetune_kaggle_v3.ipynb": ("nano-finetune-kaggle", "QLoRA SFT, Qwen2.5-7B-Instruct, oversampled train file, Kaggle.", "retire", "Superseded by v4_safety."),
    "notebooks/orca_nano_finetune_kaggle_v4_safety.ipynb": ("nano-finetune-kaggle", "QLoRA SFT, Qwen2.5-7B-Instruct, v3_safety train file, Kaggle. Latest Nano SFT revision.", "gate", "Lineage head for Nano SFT; re-express through the gated finetune path before any rerun."),
    "notebooks/orca_core_combined_sft_kaggle_v1-kernel-metadata.json": ("core-combined", "Kaggle kernel-push configuration for the combined SFT notebook (private kernel, GPU T4, internet ON, two input datasets).", "freeze", "This file is what `kaggle kernels push` consumes; it launches the notebook with GPU and internet. Keep frozen; the owner should confirm the remote kernel and datasets are private."),
    "notebooks/orca_core_calibration_sft_kaggle_v1-kernel-metadata.json": ("core-calibration", "Kaggle kernel-push configuration for the calibration SFT notebook.", "freeze", "Same as above."),
}
CURATED_WATCHLIST = {
    "scripts/phase21b_4_20_modal_h100_control.py": "Off-host H100 control INFERENCE on Modal (trusted inference, hard function timeout). Not a trainer.",
    "scripts/phase21b_4_20_lightning_control.py": "Off-host control INFERENCE orchestration on Lightning. Not a trainer.",
    "scripts/phase21b_4_20_lightning_runner.py": "Runs on the Lightning host: control INFERENCE only. Not a trainer.",
    "orca/eval/sandbox_modal.py": "Modal sandbox for evaluation code execution. Not a trainer.",
    "scripts/phase21b_4_13_glm_cpu_preflight.py": "Modal CPU-ONLY image/config preflight (no gpu= parameter, no weight download, no inference). Not a trainer.",
    "scripts/phase21b_4_15_1_qwen38_27b_cpu_preflight.py": "Modal CPU-ONLY metadata/CLI-parse preflight against a vLLM image (no weights, no CUDA init). Not a trainer.",
    "scripts/phase21b_4_20_control_runtime_qualification.py": "Modal GPU serving-path qualification of three control models as trusted INFERENCE only (smoke prompts). Not a trainer.",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for f in sorted(filenames):
            yield Path(dirpath) / f


def _notebook_source(path: Path) -> str:
    try:
        nb = json.loads(path.read_text())
        return "\n".join("".join(c.get("source", [])) for c in nb.get("cells", []) if c.get("cell_type") == "code")
    except (OSError, ValueError, AttributeError):
        return path.read_text(errors="replace")


def _py_trainer_constructs(text: str) -> list:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ["UNPARSEABLE"]
    hits = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in _TRAINER_NAMES:
            hits.add(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in _TRAINER_NAMES:
            hits.add(n.attr)
        elif isinstance(n, ast.ImportFrom):
            hits.update(a.name for a in n.names if a.name in _TRAINER_NAMES)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            hits.update("EMBEDDED_SCRIPT:" + m.group(0) for m in _EMBEDDED_RE.finditer(n.value))    # e.g. the remote script template inside cloud.py
    return sorted(hits)


def scan_repo(root) -> dict:
    """{'artifacts': {relpath: facts}, 'watchlist': {relpath: facts}}. Deterministic (sorted)."""
    root = Path(root)
    artifacts: dict = {}
    watch: dict = {}
    for p in _walk(root):
        rel = p.relative_to(root).as_posix()
        top = rel.split("/")[0]
        if p.suffix == ".ipynb":
            src = _notebook_source(p)
            artifacts[rel] = {
                "kind": "NOTEBOOK", "sha256": _sha256(p),
                "platform": "COLAB" if ("google.colab" in src or "/content/" in src) else ("KAGGLE" if "/kaggle/" in src else "UNKNOWN"),
                "trainer_constructs": sorted(set(_TRAINER_RE.findall(src))), "moves_model_weights": bool(_WEIGHT_RE.search(src)),
                "base_models": sorted(set(_MODEL_RE.findall(src))), "data_inputs": sorted(set(_INPUT_RE.findall(src)))[:6],
                "outputs": sorted(set(_OUTPUT_RE.findall(src)))[:6],
            }
        elif p.name.endswith("-kernel-metadata.json"):
            try:
                meta = json.loads(p.read_text())
            except ValueError:
                meta = {}
            artifacts[rel] = {"kind": "KAGGLE_KERNEL_METADATA", "sha256": _sha256(p), "platform": "KAGGLE", "trainer_constructs": [], "moves_model_weights": False,
                              "base_models": [], "data_inputs": sorted(meta.get("dataset_sources", [])), "outputs": [],
                              "launch_config": {"enable_gpu": meta.get("enable_gpu"), "enable_internet": meta.get("enable_internet"), "is_private": meta.get("is_private"),
                                                "machine_shape": meta.get("machine_shape"), "code_file": meta.get("code_file")}}
        elif p.suffix == ".py" and top not in ("tests", "docs"):
            text = p.read_text(errors="replace")
            hits = _py_trainer_constructs(text)
            if hits and rel != "orca/train/dryrun/inventory.py":
                artifacts[rel] = {"kind": "GATED_IN_REPO" if rel in GATED_IN_REPO else "PYTHON_TRAINER_OUTSIDE_GATE", "sha256": _sha256(p), "platform": "ON_HOST_OR_SSH",
                                  "trainer_constructs": hits, "moves_model_weights": True, "base_models": [], "data_inputs": [], "outputs": []}
            if _OFFHOST_GPU_RE.search(text):
                watch[rel] = {"kind": "OFFHOST_GPU_RUNNER", "sha256": _sha256(p), "trains": bool(hits)}
        elif p.suffix in (".sh", ".yml", ".yaml", ".toml") or p.name.startswith(("Dockerfile", "Makefile")):
            if top in ("tests", "docs"):
                continue
            m = _LAUNCHER_RE.search(p.read_text(errors="replace"))
            if m:
                artifacts[rel] = {"kind": "LAUNCHER_COMMAND", "sha256": _sha256(p), "platform": "CI_OR_CONTAINER", "trainer_constructs": [m.group(0)],
                                  "moves_model_weights": True, "base_models": [], "data_inputs": [], "outputs": []}
    return {"artifacts": dict(sorted(artifacts.items())), "watchlist": dict(sorted(watch.items()))}


def _bypass_text(facts: dict) -> str:
    if facts["kind"] == "GATED_IN_REPO":
        return "None known: this module calls authorize_training()/require_grant() before any trainer or SSH use (covered by tests/test_training_authorization_gate.py)."
    if facts["kind"] == "KAGGLE_KERNEL_METADATA":
        return "`kaggle kernels push` with this file starts a GPU, internet-enabled kernel entirely outside ORNEUR; nothing in the repository gates it."
    if facts["kind"] != "NOTEBOOK":
        return "Not governed by the gate; must be added to the gated allowlist or removed."
    plat = {"KAGGLE": "Kaggle", "COLAB": "Google Colab"}.get(facts["platform"], "an unknown host")
    text = _GENERIC_BYPASS % (plat, plat)
    if not facts["trainer_constructs"]:
        text += " (This notebook has no trainer but loads/merges/exports model weights, an unrecorded provenance path.)"
    return text


def build_inventory(root) -> dict:
    scan = scan_repo(root)
    entries = []
    missing = [p for p, f in scan["artifacts"].items() if p not in CURATED and f["kind"] not in ("GATED_IN_REPO",)]
    if missing:
        raise KeyError(f"uncurated training artifact(s) -- review and add to CURATED: {missing}")
    for i, (rel, facts) in enumerate(scan["artifacts"].items(), 1):
        if facts["kind"] == "GATED_IN_REPO":
            lineage, what, action, why = ("in-repo", "The repository's own gated trainers (orca.train.finetune local/GPU; orca.train.cloud SSH rented GPU).", "gate", "Already gated; listed for completeness.")
        else:
            lineage, what, action, why = CURATED[rel]
        entries.append({"id": f"OH-{i:02d}", "path": rel, "kind": facts["kind"], "sha256": facts["sha256"], "platform": facts["platform"], "lineage": lineage,
                        "what_it_trains": what, "trainer_constructs": facts["trainer_constructs"], "moves_model_weights": facts["moves_model_weights"],
                        "base_models": facts["base_models"], "data_inputs": facts["data_inputs"], "outputs": facts["outputs"],
                        **({"launch_config": facts["launch_config"]} if "launch_config" in facts else {}),
                        "how_it_bypasses_the_gate": _bypass_text(facts), "proposed_action": action, "rationale": why})
    watch = [{"path": rel, "kind": f["kind"], "sha256": f["sha256"], "trains": f["trains"], "note": CURATED_WATCHLIST.get(rel, "UNREVIEWED")}
             for rel, f in scan["watchlist"].items()]
    counts: dict = {}
    for e in entries:
        counts[e["proposed_action"]] = counts.get(e["proposed_action"], 0) + 1
    return {"schema": SCHEMA, "status": "INVENTORY_ONLY__NO_ACTION_TAKEN", "generated_by": "scripts/trainprep/offhost_inventory.py --write",
            "note": "Nothing was retired, frozen, edited or executed. proposed_action is a proposal for the owner; see RETIREMENT_PLAN.md.",
            "summary": {"entries": len(entries), "by_action": dict(sorted(counts.items())),
                        "training_notebooks": sum(1 for e in entries if e["kind"] == "NOTEBOOK" and e["trainer_constructs"])},
            "entries": entries, "offhost_gpu_runners_not_training": watch}


def compare(root, inventory: dict) -> list:
    """Problem list (empty == repo and committed inventory agree). Never raises for 'new artifact', reports it."""
    problems = []
    scan = scan_repo(root)
    listed = {e["path"]: e for e in inventory.get("entries", [])}
    for rel, facts in scan["artifacts"].items():
        if rel not in listed:
            problems.append(f"NEW_UNINVENTORIED_TRAINING_ARTIFACT:{rel}")
        elif listed[rel]["sha256"] != facts["sha256"]:
            problems.append(f"INVENTORIED_ARTIFACT_CHANGED:{rel}")
        elif listed[rel]["kind"] != facts["kind"]:
            problems.append(f"KIND_CHANGED:{rel}")
        elif rel not in CURATED and facts["kind"] != "GATED_IN_REPO":
            problems.append(f"NOT_CURATED:{rel}")
    for rel in listed:
        if rel not in scan["artifacts"]:
            problems.append(f"INVENTORIED_ARTIFACT_MISSING_OR_NO_LONGER_DETECTED:{rel}")
    wl = {w["path"]: w for w in inventory.get("offhost_gpu_runners_not_training", [])}
    for rel, facts in scan["watchlist"].items():
        if rel not in wl:
            problems.append(f"NEW_OFFHOST_GPU_RUNNER:{rel}")
        elif wl[rel]["sha256"] != facts["sha256"]:
            problems.append(f"OFFHOST_GPU_RUNNER_CHANGED:{rel}")
        elif facts["trains"]:
            problems.append(f"OFFHOST_GPU_RUNNER_NOW_CONSTRUCTS_A_TRAINER:{rel}")
    for rel in wl:
        if rel not in scan["watchlist"]:
            problems.append(f"WATCHLIST_ENTRY_MISSING:{rel}")
    return problems


def inventory_bytes(inv: dict) -> bytes:
    return (json.dumps(inv, indent=2, sort_keys=True) + "\n").encode()
