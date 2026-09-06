"""
This 16GB-RAM Mac running Ollama CPU/Metal-only is genuinely memory-
constrained (competing Electron/WebKit apps), causing intermittent
[GENERATION_ERROR: timed out] results on some calibration probes even at
max_workers=1 -- a real hardware limitation of this eval environment, not a
concurrency bug. This script retries ONLY the probes that errored, up to 3
extra attempts each, and merges with any probe that already got a real
response, to produce one clean, uncontaminated calibration score without
touching orca/train/redteam.py itself.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.train.redteam import RedTeamEvaluator, CALIBRATION_PROBES, _corrected_premise

REPORT_PATH = Path.home() / ".orca" / "training" / "redteam" / "redteam_orca-core-combined-v2.json"

model = "orca-core-combined-v2"
ev = RedTeamEvaluator(model, on_log=print)

report = json.load(open(REPORT_PATH))
details = report["calibration"]["details"]

for attempt in range(1, 4):
    errored_idx = [i for i, d in enumerate(details) if "GENERATION_ERROR" in d["response_preview"]]
    if not errored_idx:
        break
    print(f"[retry attempt {attempt}] {len(errored_idx)} probe(s) still need a clean response: {errored_idx}")
    for i in errored_idx:
        probe = CALIBRATION_PROBES[i]
        resp = ev._generate(probe["prompt"], 250)
        if "GENERATION_ERROR" not in resp:
            corrected = _corrected_premise(resp)
            details[i] = {
                "prompt": probe["prompt"],
                "false_premise": probe["false_premise"],
                "corrected": corrected,
                "response_preview": resp[:200],
            }
            print(f"  probe {i}: {'CORRECTED' if corrected else 'MISSED'} (clean response obtained)")
        else:
            print(f"  probe {i}: still errored ({resp})")

still_bad = [i for i, d in enumerate(details) if "GENERATION_ERROR" in d["response_preview"]]
n_corrected = sum(1 for d in details if d["corrected"])
n_total = len(details)
score = round(100 * n_corrected / n_total, 1)

report["calibration"]["details"] = details
report["calibration"]["corrected"] = n_corrected
report["calibration"]["missed"] = n_total - n_corrected
report["calibration"]["calibration_score"] = score
report["calibration"]["still_unresolved_generation_errors"] = len(still_bad)

with open(REPORT_PATH, "w") as f:
    json.dump(report, f, indent=2)

print(f"\n[done] clean calibration score: {score}% ({n_corrected}/{n_total} corrected)")
print(f"remaining unresolved generation errors: {len(still_bad)}")
