"""
Builds the orca-nano (Genesis) combined safety+calibration SFT dataset —
the same joint-training fix already validated on orca-core (Novus), but
with the ratio computed from what's actually on disk rather than copy-pasted.

Nano's data situation is the OPPOSITE of core's: core had only 3 real safety
examples and needed 4x oversampling to reach a workable ~1:5 (safety:
calibration) ratio. Nano has 39 real safety-refusal examples (38 from
nano_safety_dpo_20260719.jsonl + 1 probe-grounded) against only 31
calibration examples -- using all of them unmodified would give ~1.3:1,
which is close to the 1:2 ratio that caused core's calibration to collapse
to 0%. So here we SUBSAMPLE safety down to the same ~1:5 ratio instead of
oversampling.

Usage: python3 scripts/build_nano_combined_dataset.py [safety_count]
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from orca.data.formatter import to_llama3

ORCA_HOME = Path.home() / ".orca"
SAFETY_PATHS = [
    ORCA_HOME / "training" / "dpo" / "nano_safety_dpo_20260719.jsonl",
    ORCA_HOME / "training" / "dpo" / "nano-v7_probe_grounded_safety_dpo_20260724.jsonl",
]
CALIBRATION_PATH = ORCA_HOME / "training" / "raw" / "nano_distilled_20260829.jsonl"
OUT_DIR = Path(__file__).resolve().parent.parent / "notebooks" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
EVAL_FRACTION = 0.1
TARGET_RATIO = 5  # calibration:safety, matching core's validated fix

SYSTEM_PROMPT = (
    "You are Orca — a powerful, thoughtful AI assistant. You reason carefully before responding,\n"
    "give direct and accurate answers, and adapt your style to the complexity of each question.\n"
    "For simple questions, be concise. For complex ones, think step by step.\n"
    "You have persistent memory, can execute code, search the web, and manage files.\n"
)


def load_safety_examples() -> list[dict]:
    examples = []
    for path in SAFETY_PATHS:
        with open(path) as f:
            for line in f:
                d = json.loads(line)
                conv = {
                    "conversations": [
                        {"role": "system", "value": SYSTEM_PROMPT},
                        {"role": "human", "value": d["prompt"]},
                        {"role": "gpt", "value": d["chosen"]},
                    ]
                }
                examples.append({"text": to_llama3(conv), "kind": "safety"})
    return examples


def load_calibration_examples() -> list[dict]:
    examples = []
    with open(CALIBRATION_PATH) as f:
        for line in f:
            d = json.loads(line)
            examples.append({"text": to_llama3(d), "kind": "calibration"})
    return examples


def main() -> None:
    rng = random.Random(SEED)

    safety_all = load_safety_examples()
    calibration = load_calibration_examples()

    n_target_safety = int(len(sys.argv) > 1 and sys.argv[1] or max(1, round(len(calibration) / TARGET_RATIO)))
    rng.shuffle(safety_all)
    safety = safety_all[:n_target_safety]

    combined = safety + calibration
    rng.shuffle(combined)

    n_eval = max(1, int(len(combined) * EVAL_FRACTION))
    eval_set = combined[:n_eval]
    train_set = combined[n_eval:]

    train_path = OUT_DIR / "orca_nano_combined_train_v1.jsonl"
    eval_path = OUT_DIR / "orca_nano_combined_eval_v1.jsonl"

    with open(train_path, "w") as f:
        for ex in train_set:
            f.write(json.dumps({"text": ex["text"]}) + "\n")
    with open(eval_path, "w") as f:
        for ex in eval_set:
            f.write(json.dumps({"text": ex["text"]}) + "\n")

    n_safety_train = sum(1 for e in train_set if e["kind"] == "safety")
    n_calib_train = sum(1 for e in train_set if e["kind"] == "calibration")
    print(f"[build] safety available: {len(safety_all)}, subsampled to: {len(safety)}")
    print(f"[build] calibration examples: {len(calibration)}")
    print(f"[build] train: {len(train_set)} ({n_safety_train} safety : {n_calib_train} calibration, ratio 1:{n_calib_train / max(n_safety_train, 1):.1f})")
    print(f"[build] eval: {len(eval_set)}")
    print(f"[build] wrote {train_path}")
    print(f"[build] wrote {eval_path}")


if __name__ == "__main__":
    main()
