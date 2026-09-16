"""
Builds the canonical `orneur-genesis` v2 SFT dataset -- Phase 21B's
expansion of the v1 (37-record, safety+calibration-only) dataset with
genuinely diverse, hand-authored examples covering the domains Genesis's
own cognitive identity (Builder/Executor -- Executable Intelligence)
requires and v1 never touched at all: requirement interpretation,
implementation planning, debugging/root-cause analysis, test creation,
security-aware implementation, evidence-aware completion (refusing
fabricated verification claims), authority-boundary awareness (propose,
never self-execute governed actions), tool-use planning, consequence
awareness, and uncertainty handling.

Formatted via ChatML (`orca.data.formatter.to_chatml`), NOT Llama-3
format -- Qwen2.5 (Genesis's canonical base) uses ChatML natively
(`<|im_start|>`/`<|im_end|>`), unlike v1's build script
(`build_nano_combined_dataset.py`), which formatted nano's data as
Llama-3, a template mismatch against the actual base model's chat
template. Not fixed retroactively in v1 (out of Phase 21B's audit-only
scope for legacy data); v2 is built correctly from the start.

HONEST SCOPE, per Phase 21B's own "do not manufacture scale" instruction:
this is 20 new hand-authored records, not thousands of templated
variants -- real task/domain/structural diversity over volume. This is
still far short of a production SFT corpus; see
docs/orneur/phase-21/PHASE21_GENESIS_BUILD_PREPARATION.md's dataset
section for the honest current-size assessment.

Usage: python3 scripts/build_genesis_v2_dataset.py
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
from pathlib import Path

from orca.data.formatter import to_chatml

ORCA_HOME = Path.home() / ".orca"
V2_SEED_PATH = ORCA_HOME / "training" / "raw" / "genesis_v2_seed_20260916.jsonl"
OUT_DIR = Path(__file__).resolve().parent.parent / "notebooks" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
EVAL_FRACTION = 0.15  # smaller corpus -> a slightly larger eval fraction keeps eval non-trivial

SYSTEM_PROMPT = (
    "You are Orneur Genesis, ORNEUR's Builder / Executor model. You propose and implement "
    "software, but you never claim work is verified unless it genuinely has been, and you "
    "never execute governed/authority-bearing actions yourself -- you propose them for a "
    "human or ORNEUR's deterministic governance layer to authorize."
)

REQUIRED_SCHEMA_KEYS = {"domain", "prompt", "response"}


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def load_seed_examples() -> list[dict]:
    """Fail-closed schema validation: every record must have exactly the
    required keys with non-empty string values, and no duplicate
    (domain, prompt) pair -- a malformed or duplicate record aborts the
    build rather than silently producing a corrupt dataset."""
    if not V2_SEED_PATH.exists():
        raise FileNotFoundError(
            f"Genesis v2 seed file not found: {V2_SEED_PATH}\n"
            "This file is a local, untracked training-data source (matching the "
            "project's existing convention -- see ~/.orca/ in .gitignore), not "
            "committed to the repository."
        )

    examples: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    with open(V2_SEED_PATH) as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)  # raises json.JSONDecodeError on malformed lines -- fail closed
            missing = REQUIRED_SCHEMA_KEYS - record.keys()
            if missing:
                raise ValueError(f"{V2_SEED_PATH}:{line_no}: record missing required keys {missing}")
            for key in REQUIRED_SCHEMA_KEYS:
                if not isinstance(record[key], str) or not record[key].strip():
                    raise ValueError(f"{V2_SEED_PATH}:{line_no}: field {key!r} must be a non-empty string")
            dedup_key = (record["domain"], record["prompt"])
            if dedup_key in seen_keys:
                raise ValueError(f"{V2_SEED_PATH}:{line_no}: duplicate (domain, prompt) pair {dedup_key!r}")
            seen_keys.add(dedup_key)
            examples.append(record)

    if not examples:
        raise ValueError(f"{V2_SEED_PATH} contains no records -- refusing to build an empty dataset")
    return examples


def to_conversation_text(record: dict) -> str:
    conv = {
        "conversations": [
            {"role": "system", "value": SYSTEM_PROMPT},
            {"role": "human", "value": record["prompt"]},
            {"role": "gpt", "value": record["response"]},
        ]
    }
    return to_chatml(conv)


def build() -> dict:
    examples = load_seed_examples()
    formatted = [{"text": to_conversation_text(r), "domain": r["domain"]} for r in examples]

    rng = random.Random(SEED)
    indices = list(range(len(formatted)))
    rng.shuffle(indices)
    eval_count = max(1, round(len(formatted) * EVAL_FRACTION))
    eval_indices = set(indices[:eval_count])

    train_records = [formatted[i] for i in range(len(formatted)) if i not in eval_indices]
    eval_records = [formatted[i] for i in eval_indices]

    # Exact train/eval leakage check (fail closed, not just reported).
    train_texts = {r["text"] for r in train_records}
    eval_texts = {r["text"] for r in eval_records}
    leakage = train_texts & eval_texts
    if leakage:
        raise ValueError(f"Train/eval leakage detected in {len(leakage)} record(s) -- refusing to write output")

    train_path = OUT_DIR / "orneur_genesis_v2_train.jsonl"
    eval_path = OUT_DIR / "orneur_genesis_v2_eval.jsonl"
    with open(train_path, "w") as f:
        for r in train_records:
            f.write(json.dumps({"text": r["text"]}) + "\n")
    with open(eval_path, "w") as f:
        for r in eval_records:
            f.write(json.dumps({"text": r["text"]}) + "\n")

    train_checksum = _sha256_of_text(train_path.read_text())
    eval_checksum = _sha256_of_text(eval_path.read_text())

    domain_counts: dict[str, int] = {}
    for r in formatted:
        domain_counts[r["domain"]] = domain_counts.get(r["domain"], 0) + 1

    summary = {
        "dataset_id": "orneur-genesis-v2",
        "version": "v1",
        "record_count": len(formatted),
        "train_count": len(train_records),
        "eval_count": len(eval_records),
        "domains": domain_counts,
        "train_path": str(train_path),
        "eval_path": str(eval_path),
        "train_checksum": f"sha256:{train_checksum}",
        "eval_checksum": f"sha256:{eval_checksum}",
        "creation_code_sha": _current_git_sha(),
        "seed": SEED,
    }
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    build()
