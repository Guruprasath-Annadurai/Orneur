"""
Completes Novus's missing eval_accuracy and domain_eval measurements
against orca-core-combined-v2, using the repository's real evaluation
methodology (orca.train.eval.OllamaEvaluator.accuracy_eval,
orca.train.novus_eval.NovusEvaluator.run) -- both are sequential (no
concurrency), so they avoid the CPU-contention timeout issue this same
local machine hit during the redteam eval earlier in this phase.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.train.eval import OllamaEvaluator
from orca.train.novus_eval import NovusEvaluator

EVAL_DIR = Path.home() / ".orca" / "training" / "eval"
EVAL_DIR.mkdir(parents=True, exist_ok=True)

model = "orca-core-combined-v2"

print(f"[eval] running accuracy_eval (50 golden prompts) against {model}...")
acc_evaluator = OllamaEvaluator(model, on_log=print)
accuracy_report = acc_evaluator.accuracy_eval()
acc_path = EVAL_DIR / f"eval_{model}.json"
with open(acc_path, "w") as f:
    json.dump({"model": model, "accuracy": accuracy_report}, f, indent=2)
print(f"[eval] wrote {acc_path}")

print(f"\n[eval] running Novus domain eval (24 probes) against {model}...")
domain_evaluator = NovusEvaluator(model, on_log=print)
domain_report = domain_evaluator.run()
domain_path = EVAL_DIR / f"novus_eval_{model}.json"
with open(domain_path, "w") as f:
    json.dump(domain_report, f, indent=2)
print(f"[eval] wrote {domain_path}")

print(f"\n[done] accuracy={accuracy_report['accuracy']*100:.1f}% "
      f"domain_eval overall={domain_report.get('overall_score', domain_report.get('overall'))}")
