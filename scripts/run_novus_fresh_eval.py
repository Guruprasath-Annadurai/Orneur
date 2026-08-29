"""
Runs the real redteam suite (jailbreak, bias, calibration) against a given
Ollama model and writes a report matching the existing
~/.orca/training/redteam/redteam_<model>.json format, so it can be directly
compared against prior checkpoints' recorded reports.

Usage: python3 scripts/run_novus_fresh_eval.py <ollama-model-name>
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from orca.train.redteam import RedTeamEvaluator

REDTEAM_DIR = Path.home() / ".orca" / "training" / "redteam"
REDTEAM_DIR.mkdir(parents=True, exist_ok=True)

model = sys.argv[1] if len(sys.argv) > 1 else "orca-core-combined-v2"


def main() -> None:
    ev = RedTeamEvaluator(model, on_log=print)

    # Low concurrency: this Mac runs Ollama CPU-only against an 8B Q4 model.
    # The first run at max_workers' default (6) produced widespread
    # [GENERATION_ERROR: timed out] results under CPU contention, which
    # silently poisoned the calibration/jailbreak scores with false misses
    # (a real, previously-documented failure mode for this exact eval code —
    # see orca/train/eval.py's own docstring about the same class of bug).
    # Serializing avoids CPU contention so each call gets its full 60s budget.
    jailbreak = ev.run_jailbreak_suite(trials=3, max_workers=2)
    bias = ev.run_bias_probes(trials=3, max_workers=2)
    calibration = ev.run_calibration_probes(max_workers=1)

    report = {
        "model": model,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "jailbreak": jailbreak,
        "bias": bias,
        "calibration": calibration,
    }

    out_path = REDTEAM_DIR / f"redteam_{model}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[done] wrote {out_path}")
    print(f"jailbreak block_rate={jailbreak.get('block_rate')} avg_block_rate={jailbreak.get('avg_block_rate')}")
    print(f"bias flag_rate={bias.get('flag_rate')}")
    print(f"calibration score={calibration.get('calibration_score')}")


if __name__ == "__main__":
    main()
