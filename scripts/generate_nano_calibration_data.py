"""
Generates the Genesis (nano) calibration/premise-correction dataset, mirroring
how core's 60-example calibration set (core_distilled_20260826.jsonl) was
built: same teacher (llama3.1:8b via Ollama), same PREMISE_CORRECTION seed
domain, distilled through orca's own seed-prompt pipeline.

Usage: python3 scripts/generate_nano_calibration_data.py [n_examples]
"""
from __future__ import annotations

import sys

from orca.data.seeds import PREMISE_CORRECTION
from orca.train.distill import distill_from_seeds

N_EXAMPLES = int(sys.argv[1]) if len(sys.argv) > 1 else 60


def main() -> None:
    result = distill_from_seeds(
        teacher_model="llama3.1:8b",
        n_examples=N_EXAMPLES,
        variant="nano",
        domains=[PREMISE_CORRECTION],
        on_log=print,
    )
    print(f"[done] written={result['written']} failed={result['failed']} -> {result['output_file']}")


if __name__ == "__main__":
    main()
