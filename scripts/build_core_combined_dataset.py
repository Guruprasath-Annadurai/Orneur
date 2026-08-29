"""
Builds the orca-core combined safety+calibration SFT dataset.

History: 3 safety examples : 60 calibration (~1:20) preserved jailbreak
resistance but calibration didn't move (16.7%, unchanged). Oversampling
safety 10x (~1:2) fixed jailbreak further (70/90% held-out) but calibration
collapsed to 0% -- the oversampled safety signal dominated training so
completely it crowded out the calibration signal entirely.

This version uses a moderate oversampling factor (tunable via
SAFETY_OVERSAMPLE, default 4x -> ~12:60, ~1:5) as a middle ground between
those two failed extremes, and shuffles with a fixed seed so both prior runs
and this one are reproducible for comparison.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from orca.data.formatter import to_llama3

ORCA_HOME = Path.home() / ".orca"
SAFETY_PATH = ORCA_HOME / "training" / "dpo" / "core_probe_grounded_safety_dpo_20260724.jsonl"
CALIBRATION_PATH = ORCA_HOME / "training" / "raw" / "core_distilled_20260826.jsonl"
OUT_DIR = Path(__file__).resolve().parent.parent / "notebooks" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAFETY_OVERSAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 4
SEED = 42
EVAL_FRACTION = 0.1

SYSTEM_PROMPT = (
    "You are Orca — a powerful, thoughtful AI assistant. You reason carefully before responding,\n"
    "give direct and accurate answers, and adapt your style to the complexity of each question.\n"
    "For simple questions, be concise. For complex ones, think step by step.\n"
    "You have persistent memory, can execute code, search the web, and manage files.\n"
)


def load_safety_examples() -> list[dict]:
    examples = []
    with open(SAFETY_PATH) as f:
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
    safety = load_safety_examples()
    calibration = load_calibration_examples()

    oversampled_safety = safety * SAFETY_OVERSAMPLE
    combined = oversampled_safety + calibration

    rng = random.Random(SEED)
    rng.shuffle(combined)

    n_eval = max(1, int(len(combined) * EVAL_FRACTION))
    eval_set = combined[:n_eval]
    train_set = combined[n_eval:]

    train_path = OUT_DIR / "orca_core_combined_train_v2.jsonl"
    eval_path = OUT_DIR / "orca_core_combined_eval_v2.jsonl"

    with open(train_path, "w") as f:
        for ex in train_set:
            f.write(json.dumps({"text": ex["text"]}) + "\n")
    with open(eval_path, "w") as f:
        for ex in eval_set:
            f.write(json.dumps({"text": ex["text"]}) + "\n")

    n_safety_train = sum(1 for e in train_set if e["kind"] == "safety")
    n_calib_train = sum(1 for e in train_set if e["kind"] == "calibration")
    print(f"[build] safety examples: {len(safety)} x{SAFETY_OVERSAMPLE} oversample = {len(oversampled_safety)}")
    print(f"[build] calibration examples: {len(calibration)}")
    print(f"[build] train: {len(train_set)} ({n_safety_train} safety : {n_calib_train} calibration, ratio 1:{n_calib_train / max(n_safety_train, 1):.1f})")
    print(f"[build] eval: {len(eval_set)}")
    print(f"[build] wrote {train_path}")
    print(f"[build] wrote {eval_path}")


if __name__ == "__main__":
    main()
