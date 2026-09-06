"""Registers the two frozen dataset manifests produced during Phase 0/0.5."""
from __future__ import annotations

import subprocess
from pathlib import Path

from orca.registry.dataset_manifest import DatasetManifest, sha256_of_file

DATA_DIR = Path("notebooks/data")


def git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


novus_manifest = DatasetManifest(
    dataset_id="orca-novus-combined-safety-calibration",
    version="v2",
    purpose="joint safety+calibration SFT -- fixes the calibration regression from 1:2 oversample",
    source_paths=[
        "~/.orca/training/dpo/core_probe_grounded_safety_dpo_20260724.jsonl (3 examples, 4x oversampled)",
        "~/.orca/training/raw/core_distilled_20260826.jsonl (60 calibration examples)",
    ],
    record_count=65 + 7,  # 65 train + 7 eval, from scripts/build_core_combined_dataset.py's own logged output
    schema='{"text": str}',
    train_checksum=sha256_of_file(DATA_DIR / "orca_core_combined_train_v2.jsonl"),
    eval_checksum=sha256_of_file(DATA_DIR / "orca_core_combined_eval_v2.jsonl"),
    creation_code_sha=git_sha(),
    filters_applied="4x oversample of 3 safety examples, seeded shuffle (seed=42), 10% eval split",
    deduplication_result="not re-verified in this pass (built directly by scripts/build_core_combined_dataset.py)",
    known_limitations=[
        "Only 3 distinct safety-refusal source examples exist for Novus -- oversampling introduces exact duplicate safety examples in-corpus by design",
    ],
)
novus_manifest.save()
print(f"[register] {novus_manifest.dataset_id}-{novus_manifest.version} saved: {novus_manifest.manifest_path()}")

genesis_manifest = DatasetManifest(
    dataset_id="orca-genesis-combined-safety-calibration",
    version="v1",
    purpose="joint safety+calibration SFT for Genesis -- first attempt, not yet used for training",
    source_paths=[
        "~/.orca/training/dpo/nano_safety_dpo_20260719.jsonl (38 examples, subsampled)",
        "~/.orca/training/dpo/nano-v7_probe_grounded_safety_dpo_20260724.jsonl (1 example, subsampled)",
        "~/.orca/training/raw/nano_distilled_20260829.jsonl (31 calibration examples)",
    ],
    record_count=34 + 3,
    schema='{"text": str}',
    train_checksum=sha256_of_file(DATA_DIR / "orca_nano_combined_train_v1.jsonl"),
    eval_checksum=sha256_of_file(DATA_DIR / "orca_nano_combined_eval_v1.jsonl"),
    creation_code_sha=git_sha(),
    filters_applied="subsampled to 5-6 safety examples (~1:5 ratio), seeded shuffle (seed=42), 10% eval split",
    deduplication_result="0 exact duplicates, 0 train/eval leakage (verified in docs/orneur/phase-0/GENESIS_DATASET_BASELINE.md)",
    known_limitations=[
        "Calibration source capped at 31/60 requested examples by finite seed-template pool (2 templates x 18 subtopics)",
        "29% of pairs exceed 0.85 character-level similarity due to limited template diversity (not exact duplication)",
        "Ratio (1:5.8) chosen by analogy to Novus's fix, not yet validated by an actual Genesis training run",
    ],
)
genesis_manifest.save()
print(f"[register] {genesis_manifest.dataset_id}-{genesis_manifest.version} saved: {genesis_manifest.manifest_path()}")
