#!/usr/bin/env python3
"""CI gate: exits non-zero (and reports authorized=false) unless the committed authorization record proves THIS exact dispatch is authorized.
Inputs come from the workflow context via environment variables; the record is read from the checked-out commit."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from orca.eval.genesis_v2 import authorization as A
    e = os.environ
    try:
        req = A.Request(commit_sha=e.get("GITHUB_SHA", ""), eval_version=e.get("EVAL_VERSION", ""), candidate_model_id=e.get("CANDIDATE_MODEL_ID", ""),
                        candidate_revision=e.get("CANDIDATE_REVISION", ""), stage=e.get("EVAL_STAGE", ""), runner_class=e.get("RUNNER_CLASS", ""),
                        purpose=e.get("EVAL_PURPOSE", ""), requested_runs=int(e.get("REQUESTED_RUNS", "1")),
                        requested_spend_usd=float(e.get("REQUESTED_SPEND_USD", "0")), gpu=e.get("REQUEST_GPU", "false") == "true",
                        provider_inference=e.get("REQUEST_PROVIDER_INFERENCE", "false") == "true", event_name=e.get("GITHUB_EVENT_NAME", ""))
        v = A.verify(A.load_record(ROOT), req, A.load_keys(ROOT))
    except Exception as exc:                         # any error denies
        v = A.Verdict(False, [f"GATE_ERROR:{type(exc).__name__}"])
    out = e.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"authorized={'true' if v.authorized else 'false'}\n")
    print("MODEL EXECUTION AUTHORIZED" if v.authorized else "MODEL EXECUTION DENIED: " + ", ".join(v.reasons))
    return 0 if v.authorized else 1


if __name__ == "__main__":
    sys.exit(main())
