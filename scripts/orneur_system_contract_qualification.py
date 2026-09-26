"""Generate docs/orneur/phase-21/evidence/ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json from the REAL contract engine (no model, GPU or provider call). Never fabricates a verdict."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval.system_contract_qualification import build_artifact  # noqa: E402

EVIDENCE = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE / "ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json"

if __name__ == "__main__":
    art = build_artifact(EVIDENCE)
    OUT.write_text(json.dumps(art, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"verdict": art["verdict"], "model_calls": art["model_calls"], "gpu_calls": art["gpu_calls"], "provider_calls": art["provider_calls"],
                      "cases": {k: (v["detected_contract_type"], v["final_output"], v["passed"]) for k, v in art["cases"].items()}}, indent=2, ensure_ascii=False))
    raise SystemExit(0 if art["all_contracts_satisfied"] else 1)
