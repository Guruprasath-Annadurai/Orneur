"""
Phase 21B.4.20 -- persist the canonical LOCKED smoke protocol (exact messages, UTF-8 bytes, per-prompt sha256, protocol sha256) and the
documented drift of the earlier runner wording. CPU-only; reads the canonical module and the already-persisted Qwen attempt-4 record;
never modifies any existing evidence; no Modal, no GPU, no generation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from orca.eval import locked_smoke_protocol as lp  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
OUT = EVIDENCE_DIR / "GENESIS_LOCKED_SMOKE_PROTOCOL_2026-09-25.json"
QWEN_RECORD = EVIDENCE_DIR / "GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_2026-09-24.json"


def drifted_definitions_from(record: dict) -> tuple:
    """Rebuild a definitions tuple from the prompts attempt 4 actually sent, under the SAME canonical acceptance/stream fields."""
    defs = copy.deepcopy(lp.SMOKE_DEFINITIONS)
    sent = {p["smoke_id"]: p["messages"][0]["content"] for p in record["smoke_prompts"]}
    return tuple(dict(d, user=sent[d["smoke_id"]]) for d in defs)


def main() -> int:
    record = json.loads(QWEN_RECORD.read_text())
    ran = drifted_definitions_from(record)
    doc = lp.protocol_document()
    artifact = {
        "evidence_type": "LOCKED_SMOKE_PROTOCOL_CANONICAL", "phase": "21B.4.20", "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_of_truth": "orca/eval/locked_smoke_protocol.py (stdlib only; verifies PINNED_PROTOCOL_SHA256 on import; consumed by the runner, both Modal harnesses, the record builder, the validator, the Qwen analysis tooling and the tests)",
        "protocol": doc, "protocol_sha256": doc["protocol_sha256"], "pinned_in_module": lp.PINNED_PROTOCOL_SHA256,
        "acceptance_normalization": lp.NORMALIZATION,
        "wording_history": {
            "earlier_runner_wording_drift": {
                "used_by": ["Qwen3-8B attempt 4 (raw evidence, unchanged)", "planned (never sent) prompts of the Mistral-Nemo and Phi-4 NOT_TESTED records (canonicalized 2026-09-25 with the originals preserved)"],
                "messages": {d["smoke_id"]: d["user"] for d in ran},
                "prompt_sha256": {d["smoke_id"]: hashlib.sha256(d["user"].encode("utf-8")).hexdigest() for d in ran},
                "protocol_sha256_as_run": lp.protocol_sha256(ran),
                "status": "HISTORICAL. Not the canonical protocol; a record produced with it cannot be RUNTIME_QUALIFIED (validator rejects non-canonical prompts)."},
            "provenance_note": "The Phase 21B.4.20 spec first gave these smokes as examples in the longer wording the runner used. The owner's later 'SMOKES ONLY' lock and the 2026-09-25 canonicalization directive fix the short wording recorded here as canonical."},
        "consumers": ["scripts/phase21b_4_20_lightning_runner.py", "scripts/phase21b_4_20_modal_h100_control.py (ships the file beside the runner and verifies the fingerprint proven from inside the container)",
                      "scripts/phase21b_4_20_control_runtime_qualification.py (legacy)", "scripts/phase21b_4_20_lightning_control.py (record builder)",
                      "orca/eval/control_runtime_qualification.py (validator)", "scripts/phase21b_4_20_qwen_config_analysis.py", "tests/test_genesis_control_runtime_qualification.py"],
        "qwen3_8b_attempt_4": "raw evidence untouched; status FAILED unchanged",
        "no_gpu_used": True, "generated_output_executed": False,
    }
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"artifact": OUT.name, "protocol_sha256": artifact["protocol_sha256"], "as_run_sha256": artifact["wording_history"]["earlier_runner_wording_drift"]["protocol_sha256_as_run"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
