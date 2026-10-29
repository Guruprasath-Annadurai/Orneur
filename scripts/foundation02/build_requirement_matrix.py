#!/usr/bin/env python3
"""Build FOUNDATION-02 engineering disposition matrix over the 95 counted rows.

Does not accept requirements, edit the ledger, or mint signatures.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "docs/orneur/acceptance/register_graph.json"
LEDGER = ROOT / "docs/orneur/acceptance/acceptance_ledger.json"
OUT_JSON = ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json"
OUT_MD = ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.md"

# Engineering probes (code + tests). Formal acceptance stays separate.
ENGINEERING_MAP = {
    # Authorization / fail-closed
    "AUTH-1": ("VERIFIED_ENGINEERING", "orca/train/authorization.py; orca/genesis/governance/authorization.py", "tests/test_training_authorization_gate.py; tests/test_genesis_governance_authorization.py"),
    "G4": ("VERIFIED_ENGINEERING", "orca/train/authorization.py (NOT_AUTHORIZED default)", "tests/test_training_authorization_assurance.py"),
    "G5": ("VERIFIED_ENGINEERING", "TRAINING_AUTHORITY_REGISTRY empty + pinned digest", "tests/test_training_authorization_gate.py"),
    "G8": ("BLOCKED", "Founder corpus-generation grant absent", "orca/pretrain_foundation/readiness_gate.py"),
    "G10": ("BLOCKED", "Founder training permission absent", "docs/orneur/authorization/TRAINING_AUTHORIZATION.json"),
    "MODEL-1": ("BLOCKED", "No authorized native training identity", "orca/genesis/model/family_registry.py"),
    "MODEL-2R": ("BLOCKED", "No authorized model revision for training", "orca/genesis/model/family_registry.py"),
    "QUAL-1": ("BLOCKED", "No authorized qualification run", "orca/pretrain_foundation/readiness_gate.py"),
    "TRAIN-1": ("VERIFIED_ENGINEERING", "Synthetic training math + orchestration fail-closed", "tests/test_cursor_training_math.py; tests/test_genesis_training_primitives.py"),
    "TRAIN-2": ("VERIFIED_ENGINEERING", "Checkpoint/resume integrity synthetic", "tests/test_genesis_checkpoint_integrity.py; tests/test_genesis_resumable_checkpoint.py"),
    "C08": ("BLOCKED", "Founder-controlled compute authorization", "orca/pretrain_foundation/compute_scenarios.py"),
    "C44": ("BLOCKED", "Founder-controlled spend/GPU permission", "docs/orneur/authorization/TRAINING_AUTHORIZATION.json"),
    "DEC-K": ("BLOCKED", "Foundation selection decision not accepted", "docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md"),
    # Architecture / tokenizer / families
    "G2": ("IMPLEMENTED_UNVERIFIED", "Architecture artefacts present on main lineage", "docs/orneur/ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md"),
    "C01": ("VERIFIED_ENGINEERING", "Genesis model config + architecture tests (unmerged lineage recovered)", "tests/test_genesis_model_architecture.py"),
    "C02": ("VERIFIED_ENGINEERING", "Tokenizer framework + robustness", "tests/test_genesis_tokenizer.py; tests/test_cursor_tokenizer_robustness.py"),
    # Data provenance
    "DATA-1": ("VERIFIED_ENGINEERING", "Dataset manifest validation (synthetic); not formal provenance acceptance", "tests/test_genesis_data_manifest.py; tests/test_cursor_pipeline_admission.py"),
    "DATA-2": ("VERIFIED_ENGINEERING", "Contamination checks synthetic", "tests/test_genesis_data_contamination.py"),
    "DATA-3": ("BLOCKED", "Protected corpus creation requires founder grant", "orca/pretrain_foundation/readiness_gate.py"),
    "DATA-5": ("BLOCKED", "Independent custody evidence absent", "orca/pretrain_foundation/readiness_gate.py"),
    # Evaluation
    "QUAL-2": ("IMPLEMENTED_UNVERIFIED", "Eval adapter + integrity harness exist; no accepted private holdout", "tests/test_genesis_eval_adapter.py; tests/test_cursor_eval_integrity.py"),
    "QUAL-3": ("NOT_IMPLEMENTED", "Material-regression thresholds not frozen before candidate results", "docs/orneur/phase-21/GENESIS_PRETRAINING_QUALIFICATION.md"),
    # Supply / environment
    "SUP-1": ("IMPLEMENTED_UNVERIFIED", "CI/image digests cited historically; not two independent training-image digests for this tip", "docs/orneur/acceptance/register_graph.json"),
    "SUP-3": ("IMPLEMENTED_UNVERIFIED", "Dependency/lock evidence on foundation lineage", ".github/workflows/test.yml"),
    # Final worksheet
    "FINAL-1": ("VERIFIED_ENGINEERING", "Engineering matrix worksheet over 95 ids (this artifact); formal acceptance still 0", "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json"),
    "R65": ("BLOCKED", "Unmapped placeholder; cannot be signed", "docs/orneur/acceptance/register_graph.json"),
    "G1": ("BLOCKED", "Independent architecture review file not found", "docs/orneur/acceptance/register_graph.json"),
}


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _disposition(node: dict) -> tuple[str, str, str]:
    rid = node["id"]
    if rid in ENGINEERING_MAP:
        return ENGINEERING_MAP[rid]
    status = node.get("status") or ""
    founder = node.get("founder_approval") not in (None, "NOT_REQUIRED", "", "none")
    if status == "NOT_AUTHORIZED" or founder:
        return ("BLOCKED", "Founder-controlled or not authorized; engineering cannot accept", node.get("evidence_required") or "")
    if status == "NOT_VERIFIABLE":
        return ("BLOCKED", "Not independently verifiable in this pass", node.get("current_evidence") or "")
    if status in {"NOT_STARTED", "DESIGNED_ONLY"}:
        return ("NOT_IMPLEMENTED", "No verified engineering closure for this counted row yet", node.get("evidence_required") or "")
    if status in {"UNMERGED_NOT_ACCEPTED", "PRESENT_ON_MAIN", "NOT_ACCEPTED"}:
        return ("IMPLEMENTED_UNVERIFIED", "Artefacts/PRs exist but formal acceptance and/or independent qualification incomplete", node.get("current_evidence") or "")
    return ("NOT_IMPLEMENTED", f"Unhandled register status {status}", node.get("evidence_required") or "")


def build() -> dict:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    ids = list(graph["denominator_pretraining_ids"])
    sha = _git_sha()
    rows = []
    hist: dict[str, int] = {}
    for rid in ids:
        node = nodes[rid]
        disp, impl, tests = _disposition(node)
        hist[disp] = hist.get(disp, 0) + 1
        rows.append({
            "requirement_id": rid,
            "exact_acceptance_condition": node.get("evidence_required") or node.get("pass_rule") or "",
            "actual_implementation": impl,
            "evidence_path": node.get("current_evidence") or "",
            "source_sha": sha,
            "relevant_test": tests,
            "executed_test_result": "SEE_FOUNDATION_02_EXACT_HEAD_CI",
            "independent_evidence": "NOT_CLAIMED",
            "founder_controlled_dependency": node.get("founder_approval") not in (None, "NOT_REQUIRED", "", "none"),
            "register_status": node.get("status"),
            "engineering_disposition": disp,
            "remaining_engineering_work": node.get("escalation") or node.get("exit") or "",
            "depends_on": node.get("depends_on") or [],
            "formal_acceptance": False,
        })
    assert len(rows) == 95, len(rows)
    assert len(ledger) == 0, "ledger must remain empty"
    return {
        "schema": "orneur-foundation-02-requirement-matrix/1",
        "validator_check": "pretraining=95 numerator=0",
        "formal_accepted_count": 0,
        "formal_denominator": 95,
        "source_sha": sha,
        "register_graph_sha256": hashlib.sha256(GRAPH.read_bytes()).hexdigest(),
        "ledger_sha256": hashlib.sha256(LEDGER.read_bytes()).hexdigest(),
        "disposition_histogram": hist,
        "note": (
            "engineering_disposition is not formal acceptance. "
            "FORMALLY_ACCEPTED is never assigned by this script."
        ),
        "requirements": rows,
    }


def render_md(doc: dict) -> str:
    lines = [
        "# FOUNDATION-02 Requirement Matrix",
        "",
        f"**Source SHA:** `{doc['source_sha']}`  ",
        f"**Formal acceptance:** {doc['formal_accepted_count']} / {doc['formal_denominator']}  ",
        f"**Validator:** `{doc['validator_check']}`  ",
        "",
        "## Disposition histogram (engineering only)",
        "",
        "| Disposition | Count |",
        "|---|---:|",
    ]
    for k, v in sorted(doc["disposition_histogram"].items()):
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "## Rows",
        "",
        "| ID | Register status | Engineering disposition | Founder-controlled |",
        "|---|---|---|---|",
    ]
    for row in doc["requirements"]:
        lines.append(
            f"| {row['requirement_id']} | {row['register_status']} | "
            f"`{row['engineering_disposition']}` | {row['founder_controlled_dependency']} |"
        )
    lines += [
        "",
        "## Policy",
        "",
        "- This matrix does **not** modify `acceptance_ledger.json`.",
        "- A passed engineering test does not become `FORMALLY_ACCEPTED`.",
        "- Training authorization remains **NO-GO**.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    doc = build()
    OUT_JSON.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(doc), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} ({len(doc['requirements'])} rows)")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    print("histogram", doc["disposition_histogram"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
