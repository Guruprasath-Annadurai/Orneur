#!/usr/bin/env python3
"""Build the Pretraining Foundation Final Master Engineering Report.

Does not write the acceptance ledger. Does not authorize training.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from orca.pretrain_foundation.c27_feasibility import investigate_c27
from orca.pretrain_foundation.genesis_feasibility import assess_genesis, family_status_snapshot
from orca.pretrain_foundation.hardware_evidence_boundary import PHYSICAL_REQUIREMENT_IDS
from orca.pretrain_foundation.independent_codec import c16_engineering_status
from orca.pretrain_foundation.infra_record import build_infra_record
from orca.pretrain_foundation.readiness_gate import blocker_codes, production_observation
from orca.pretrain_foundation.training_freeze import build_freeze_package, write_freeze_manifest

MATRIX = ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json"
GRAPH = ROOT / "docs/orneur/acceptance/register_graph.json"
LEDGER = ROOT / "docs/orneur/acceptance/acceptance_ledger.json"
ENG = ROOT / "docs/orneur/programmes/pretraining-closure/engineering"
OUT_MD = ENG / "ORNEUR_PRETRAINING_FOUNDATION_FINAL_MASTER_ENGINEERING_REPORT.md"
OUT_JSON = ENG / "ORNEUR_PRETRAINING_FOUNDATION_FINAL_MASTER_ENGINEERING_REPORT.json"
FREEZE = ENG / "TRAINING_FREEZE_MANIFEST.json"
EVIDENCE_MANIFEST = ENG / "FINAL_EVIDENCE_MANIFEST.json"


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    sha = _git_sha()
    obs = production_observation()
    blockers = blocker_codes(obs)
    genesis = assess_genesis()
    c27 = investigate_c27()
    infra = build_infra_record(ROOT, code_sha=sha, dry_run_log_pointer="synthetic://cpu-dry-run")
    freeze = build_freeze_package(
        ROOT,
        sha,
        model_configuration={
            "architecture_version": genesis.architecture_version,
            "candidate_tier": genesis.candidate_tier,
            "parameter_count": genesis.parameter_count,
        },
        tokenizer_digest=None,
        dataset_digest=None,
        evaluation_identity=None,
    )
    write_freeze_manifest(FREEZE, freeze)

    rows = []
    for req in matrix["requirements"]:
        rid = req["requirement_id"]
        node = nodes.get(rid, {})
        rows.append({
            "requirement_id": rid,
            "exact_acceptance_condition": req.get("exact_acceptance_condition") or node.get("evidence_required") or "",
            "engineering_disposition": req["engineering_disposition"],
            "independent_review_status": "NOT_CLAIMED",
            "formal_acceptance": False,
            "register_status": req.get("register_status") or node.get("status"),
            "missing_evidence": req.get("remaining_engineering_work") or node.get("escalation") or "",
            "executed_test_result": req.get("executed_test_result"),
            "candidate_sha": req.get("candidate_sha"),
            "founder_controlled_dependency": req.get("founder_controlled_dependency"),
            "physical_gate": rid in PHYSICAL_REQUIREMENT_IDS,
        })

    hist = matrix["disposition_histogram"]
    doc = {
        "schema": "orneur-pretraining-foundation-final-master-engineering-report/1",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "training_authorization": "NO-GO",
        "formal_acceptance": {"numerator": len(ledger), "denominator": 95},
        "starting_main_sha": matrix.get("main_base_sha"),
        "prior_qualified_code_sha": matrix.get("prior_qualified_code_sha"),
        "honesty_probe_tip": "cd1e557a685b529c57bf4bf2f594b088cbeb5172",
        "final_engineering_sha": sha,
        "pr_lineage": ["#138 FOUNDATION-02", "#140 Phase 0/1 honesty + Phases 2-9 closure"],
        "disposition_histogram": hist,
        "verified_engineering_ids": matrix.get("verified_engineering_ids"),
        "readiness_blockers": blockers,
        "genesis": genesis.to_dict(),
        "family_statuses": family_status_snapshot(),
        "c27": c27.to_dict(),
        "c16_status": c16_engineering_status(secondary_present=False),
        "infra_record": infra.to_dict(),
        "freeze_package": freeze.to_dict(),
        "requirements": rows,
        "artifact_digests": {
            "matrix": _file_digest(MATRIX),
            "probes": _file_digest(ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_VERIFICATION_PROBES.json"),
            "register_graph": _file_digest(GRAPH),
            "ledger": _file_digest(LEDGER),
            "freeze_manifest": _file_digest(FREEZE),
        },
        "honest_final_disposition": {
            "engineering_completed": (
                "Phase 0/1 evidence honesty; RSE software probes for C04-C15/C17-C21/C45; "
                "QUAL-2 holdout denial; Phase 2-9 boundary modules; freeze package NO-GO"
            ),
            "engineering_incomplete": (
                "Physical/custody HW gates; independent second codec (C16); mainline merge (G2/G3); "
                "formal acceptance process"
            ),
            "founder_controlled_blockers": [
                "G1", "G8", "G10", "DEC-K", "C08", "C44", "C27", "R65", "DATA-3", "DATA-5",
                "MODEL-1", "MODEL-2R", "QUAL-1", "FINAL-2",
            ],
            "external_blockers": sorted(PHYSICAL_REQUIREMENT_IDS),
            "independent_qualification_pending": True,
            "formal_acceptance_count": f"{len(ledger)}/95",
            "training_authorization_status": "NO-GO",
        },
    }
    return doc


def render_md(doc: dict) -> str:
    lines = [
        "# ORNEUR — PRETRAINING FOUNDATION FINAL MASTER ENGINEERING REPORT",
        "",
        f"**Generated (UTC):** {doc['generated_at_utc']}  ",
        f"**Final engineering SHA:** `{doc['final_engineering_sha']}`  ",
        f"**Prior qualified code SHA:** `{doc['prior_qualified_code_sha']}`  ",
        f"**Training authorization:** **{doc['training_authorization']}**  ",
        f"**Formal acceptance:** **{doc['formal_acceptance']['numerator']} / {doc['formal_acceptance']['denominator']}**  ",
        "",
        "## A. Programme summary",
        "",
        f"- Starting main SHA: `{doc['starting_main_sha']}`",
        f"- PR lineage: {', '.join(doc['pr_lineage'])}",
        f"- Honesty probe tip: `{doc['honesty_probe_tip']}`",
        f"- Disposition histogram: `{json.dumps(doc['disposition_histogram'], sort_keys=True)}`",
        f"- VERIFIED_ENGINEERING IDs: {', '.join(doc['verified_engineering_ids'] or []) or '(none)'}",
        f"- Readiness blockers: {', '.join(doc['readiness_blockers'])}",
        "",
        "## B. Phase-by-phase results",
        "",
        "| Phase | Focus | Disposition |",
        "|---:|---|---|",
        "| 0 | Technical baseline | ENGINEERING_COMPLETE — AWAITING_INDEPENDENT_REVIEW |",
        "| 1 | Evidence honesty / foundation software | ENGINEERING_COMPLETE — AWAITING_INDEPENDENT_REVIEW |",
        "| 2 | RSE/security software (+ C27 investigation) | PARTIAL_ENGINEERING — physical/class-K blocked |",
        "| 3 | GENESIS feasibility (analytical) | PARTIAL_ENGINEERING — DEC-K/MODEL blocked |",
        "| 4 | Data pipeline (synthetic only) | PARTIAL_ENGINEERING — G8/DATA-3 blocked |",
        "| 5 | Eval harness + holdout denial | PARTIAL_ENGINEERING — QUAL-1/private custody blocked |",
        "| 6 | Hardware-trust boundary software | BLOCKED_BY_PROTECTED_DECISION (physical) |",
        "| 7 | Training infra identity (CPU) | PARTIAL_ENGINEERING — GPU/P2 blocked |",
        "| 8 | Integration preparation | BLOCKED_BY_PROTECTED_DECISION (mainline merge) |",
        "| 9 | Freeze package NO-GO | ENGINEERING_COMPLETE package / NOT_FROZEN |",
        "| 10 | Training execution | PROHIBITED |",
        "",
        "### C27 feasibility",
        "",
        f"- {doc['c27']['summary']}",
        f"- Disposition: `{doc['c27']['engineering_disposition']}`",
        "",
        "### C16 codec",
        "",
        f"- `{doc['c16_status']}`",
        "",
        "## C. Complete requirement accounting",
        "",
        "| ID | Engineering | Formal | Independent | Physical | Missing / next action |",
        "|---|---|---|---|---|---|",
    ]
    for row in doc["requirements"]:
        missing = (row.get("missing_evidence") or "").replace("|", "/")[:120]
        lines.append(
            f"| {row['requirement_id']} | `{row['engineering_disposition']}` | "
            f"{row['formal_acceptance']} | {row['independent_review_status']} | "
            f"{row['physical_gate']} | {missing} |"
        )
    g = doc["genesis"]
    lines += [
        "",
        "## D. Native model status",
        "",
        f"- GENESIS: `{doc['family_statuses']['GENESIS']}` — arch `{g['architecture_version']}`, "
        f"tier `{g['candidate_tier']}`, params `{g['parameter_count']}`",
        f"- NOVUS: `{doc['family_statuses']['NOVUS']}`",
        f"- AETERNUM: `{doc['family_statuses']['AETERNUM']}`",
        f"- Official foundation selected: **{g['official_foundation_selected']}**",
        f"- Weights downloaded: **{g['weights_downloaded']}**",
        f"- Frontier pretraining available: **{g['frontier_pretraining_available']}**",
        f"- Available compute: {g['available_compute']}",
        "",
        "## E. Security and governance",
        "",
        "- Authorization remains fail-closed / NOT_AUTHORIZED / empty registry.",
        "- Audit-tail truncation residual remains P2 (strict xfail ≠ PASS).",
        "- Trust anchors / founder signatures not fabricated.",
        "- Physical HW gates refuse mock-as-acceptance.",
        f"- Freeze package status: `{doc['freeze_package']['status']}` / "
        f"`{doc['freeze_package']['training_authorization']}`",
        "",
        "## F. Final qualification evidence",
        "",
        f"- Candidate SHA: `{doc['final_engineering_sha']}`",
        f"- Artifact digests: `{json.dumps(doc['artifact_digests'], sort_keys=True)}`",
        "- Reproduction:",
        "  - `python scripts/acceptance/validate_register_graph.py --check`",
        "  - `python -m pytest tests/test_foundation02_probe_honesty.py tests/test_pretraining_phase_closure.py -q`",
        "  - `python scripts/foundation02/build_requirement_matrix.py`",
        "  - `python scripts/foundation02/build_final_master_report.py`",
        "",
        "## G. Honest final disposition",
        "",
    ]
    for key, value in doc["honest_final_disposition"].items():
        if isinstance(value, list):
            lines.append(f"- **{key}:** {', '.join(value)}")
        else:
            lines.append(f"- **{key}:** {value}")
    lines += [
        "",
        "This report is engineering evidence for CTO review and Antigravity audit. "
        "It is **not** formal acceptance and **not** training authorization.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ENG.mkdir(parents=True, exist_ok=True)
    doc = build()
    OUT_JSON.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(doc), encoding="utf-8")
    EVIDENCE_MANIFEST.write_text(
        json.dumps(
            {
                "schema": "orneur-pretraining-closure-final-evidence-manifest/1",
                "final_engineering_sha": doc["final_engineering_sha"],
                "training_authorization": "NO-GO",
                "formal_acceptance": "0/95",
                "primary_report_md": str(OUT_MD.relative_to(ROOT)),
                "primary_report_json": str(OUT_JSON.relative_to(ROOT)),
                "freeze_manifest": str(FREEZE.relative_to(ROOT)),
                "matrix": str(MATRIX.relative_to(ROOT)),
                "antigravity_handoff": "docs/orneur/programmes/pretraining-closure/engineering/ANTIGRAVITY_HANDOFF.md",
                "artifact_digests": doc["artifact_digests"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"wrote {FREEZE.relative_to(ROOT)}")
    print(f"wrote {EVIDENCE_MANIFEST.relative_to(ROOT)}")
    print("training_authorization NO-GO formal", doc["formal_acceptance"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
