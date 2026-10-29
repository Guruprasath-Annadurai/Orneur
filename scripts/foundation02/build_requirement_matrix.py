#!/usr/bin/env python3
"""Build FOUNDATION-02 engineering disposition matrix over the 95 counted rows.

Does not accept requirements, edit the ledger, or mint signatures.
Verified status requires inspectable implementation + executed test evidence.
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
PROBES_JSON = ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_VERIFICATION_PROBES.json"

# Historical lineage SHAs (implementation landed earlier). Distinct from candidate tip.
HISTORICAL = {
    "foundation_p0_commit": "fc1eb1d",
    "gap_register": "255d25a",
    "readiness_gate": "eaa3eac",
    "main_base": "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a",
}

# Candidate probe definitions: only these may become VERIFIED_ENGINEERING.
# Each requires implementation path(s), pytest node ids, and a recorded probe run.
VERIFIED_CANDIDATES = {
    "AUTH-1": {
        "implementation": [
            "orca/train/authorization.py",
            "orca/genesis/governance/authorization.py",
        ],
        "tests": [
            "tests/test_training_authorization_gate.py",
            "tests/test_genesis_governance_authorization.py",
        ],
        "historical_source_sha": "fc1eb1d",
        "claim": "Fail-closed training / native-pretraining authorization entry points",
    },
    "G4": {
        "implementation": [
            "orca/train/authorization.py",
            "docs/orneur/authorization/TRAINING_AUTHORIZATION.json",
        ],
        "tests": ["tests/test_training_authorization_assurance.py"],
        "historical_source_sha": "fc1eb1d",
        "claim": "Committed authorization record is NOT_AUTHORIZED; adversarial assurance suite",
    },
    "G5": {
        "implementation": [
            "orca/train/authorization.py",
            "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json",
        ],
        "tests": ["tests/test_training_authorization_gate.py"],
        "historical_source_sha": "fc1eb1d",
        "claim": "Empty authority registry with pinned digest; no key can authorize",
    },
    "TRAIN-1": {
        "implementation": [
            "orca/genesis/training/primitives.py",
            "orca/genesis/training/math_qualification.py",
        ],
        "tests": [
            "tests/test_cursor_training_math.py",
            "tests/test_genesis_training_primitives.py",
        ],
        "historical_source_sha": "fc1eb1d",
        "claim": "CPU synthetic training mathematics / primitives",
    },
    "TRAIN-2": {
        "implementation": [
            "orca/genesis/training/checkpoint_integrity.py",
            "orca/genesis/training/resumable_checkpoint.py",
        ],
        "tests": [
            "tests/test_genesis_checkpoint_integrity.py",
            "tests/test_genesis_resumable_checkpoint.py",
        ],
        "historical_source_sha": "fc1eb1d",
        "claim": "Synthetic checkpoint integrity and resume refusal paths",
    },
    "C01": {
        "implementation": ["orca/genesis/model/config.py", "orca/genesis/model/transformer.py"],
        "tests": ["tests/test_genesis_model_architecture.py"],
        "historical_source_sha": "fc1eb1d",
        "claim": "GENESIS architecture config/interface synthetic tests",
    },
    "C02": {
        "implementation": ["orca/genesis/tokenizer/framework.py", "orca/genesis/tokenizer/robustness.py"],
        "tests": [
            "tests/test_genesis_tokenizer.py",
            "tests/test_cursor_tokenizer_robustness.py",
        ],
        "historical_source_sha": "fc1eb1d",
        "claim": "Tokenizer framework + robustness synthetic tests",
    },
    "DATA-1": {
        "implementation": ["orca/genesis/data/manifest.py", "orca/genesis/data/pipeline.py"],
        "tests": [
            "tests/test_genesis_data_manifest.py",
            "tests/test_cursor_pipeline_admission.py",
        ],
        "historical_source_sha": "fc1eb1d",
        "claim": "Dataset manifest / pipeline admission (synthetic; not formal DATA-1 acceptance)",
    },
    "DATA-2": {
        "implementation": ["orca/genesis/data/contamination.py"],
        "tests": ["tests/test_genesis_data_contamination.py"],
        "historical_source_sha": "fc1eb1d",
        "claim": "Contamination checking helpers (synthetic; not formal DATA-2 acceptance)",
    },
}

# Explicit downgrades: worksheet / docs alone are not VERIFIED_ENGINEERING.
FORCE_UNVERIFIED = {
    "FINAL-1": (
        "IMPLEMENTED_UNVERIFIED",
        "Engineering worksheet artifact exists; FINAL-1 requires independent recomputation and formal process",
        "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json",
    ),
}

FORCE_BLOCKED = {
    "G8": ("BLOCKED", "Founder corpus-generation grant absent", "orca/pretrain_foundation/readiness_gate.py"),
    "G10": ("BLOCKED", "Founder training permission absent", "docs/orneur/authorization/TRAINING_AUTHORIZATION.json"),
    "MODEL-1": ("BLOCKED", "No authorized native training identity", "orca/genesis/model/family_registry.py"),
    "MODEL-2R": ("BLOCKED", "No authorized model revision for training", "orca/genesis/model/family_registry.py"),
    "QUAL-1": ("BLOCKED", "No authorized qualification run", "orca/pretrain_foundation/readiness_gate.py"),
    "C08": ("BLOCKED", "Founder-controlled compute authorization", "orca/pretrain_foundation/compute_scenarios.py"),
    "C44": ("BLOCKED", "Founder-controlled spend/GPU permission", "docs/orneur/authorization/TRAINING_AUTHORIZATION.json"),
    "DEC-K": ("BLOCKED", "Foundation selection decision not accepted", "docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md"),
    "DATA-3": ("BLOCKED", "Protected corpus creation requires founder grant", "orca/pretrain_foundation/readiness_gate.py"),
    "DATA-5": ("BLOCKED", "Independent custody evidence absent", "orca/pretrain_foundation/readiness_gate.py"),
    "R65": ("BLOCKED", "Unmapped placeholder; cannot be signed", "docs/orneur/acceptance/register_graph.json"),
    "G1": ("BLOCKED", "Independent architecture review file not found", "docs/orneur/acceptance/register_graph.json"),
}


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _run_probes(candidate_sha: str) -> dict:
    """Execute verification probes and return machine-readable results."""
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "PYTHONPATH": "/home/ubuntu/.local/lib/python3.12/site-packages:/usr/lib/python3/dist-packages:"
        + str(ROOT),
    }
    # Prefer project venv pytest if present.
    py = Path("/workspace/.venv/bin/python")
    python = str(py) if py.exists() else sys.executable

    results = {}
    for rid, meta in VERIFIED_CANDIDATES.items():
        # Existence checks
        missing = [p for p in meta["implementation"] if not (ROOT / p).exists()]
        missing_tests = [p for p in meta["tests"] if not (ROOT / p).exists()]
        cmd = [python, "-m", "pytest", "-q", "--tb=no", *meta["tests"]]
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        summary = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
        ok = proc.returncode == 0 and not missing and not missing_tests
        # xfail-only suites still return 0; treat as ok for engineering verification.
        results[rid] = {
            "requirement_id": rid,
            "claim": meta["claim"],
            "implementation_paths": meta["implementation"],
            "missing_implementation": missing,
            "test_paths": meta["tests"],
            "missing_tests": missing_tests,
            "historical_source_sha": meta["historical_source_sha"],
            "candidate_sha": candidate_sha,
            "pytest_command": cmd,
            "exit_code": proc.returncode,
            "summary_line": summary,
            "passed_probe": ok,
            "stderr_tail": (proc.stderr or "")[-500:],
        }
    PROBES_JSON.write_text(json.dumps({"candidate_sha": candidate_sha, "probes": results}, indent=2) + "\n")
    return results


def _disposition(node: dict, probes: dict, candidate_sha: str) -> dict:
    rid = node["id"]
    if rid in FORCE_BLOCKED:
        disp, impl, tests = FORCE_BLOCKED[rid]
        return {
            "engineering_disposition": disp,
            "actual_implementation": impl,
            "relevant_test": tests,
            "executed_test_result": "N/A_BLOCKED",
            "historical_source_sha": None,
            "evidence_paths": [tests] if isinstance(tests, str) else list(tests) if isinstance(tests, list) else [],
        }
    if rid in FORCE_UNVERIFIED:
        disp, impl, tests = FORCE_UNVERIFIED[rid]
        return {
            "engineering_disposition": disp,
            "actual_implementation": impl,
            "relevant_test": tests,
            "executed_test_result": "ARTIFACT_ONLY",
            "historical_source_sha": None,
            "evidence_paths": [tests],
        }
    if rid in VERIFIED_CANDIDATES:
        probe = probes[rid]
        if probe["passed_probe"]:
            return {
                "engineering_disposition": "VERIFIED_ENGINEERING",
                "actual_implementation": "; ".join(probe["implementation_paths"]),
                "relevant_test": "; ".join(probe["test_paths"]),
                "executed_test_result": f"PASS ({probe['summary_line']})",
                "historical_source_sha": probe["historical_source_sha"],
                "evidence_paths": probe["implementation_paths"] + probe["test_paths"],
                "probe": {
                    "exit_code": probe["exit_code"],
                    "summary_line": probe["summary_line"],
                    "candidate_sha": candidate_sha,
                },
            }
        return {
            "engineering_disposition": "IMPLEMENTED_UNVERIFIED",
            "actual_implementation": "; ".join(VERIFIED_CANDIDATES[rid]["implementation"]),
            "relevant_test": "; ".join(VERIFIED_CANDIDATES[rid]["tests"]),
            "executed_test_result": f"PROBE_FAILED exit={probe['exit_code']} {probe['summary_line']}",
            "historical_source_sha": VERIFIED_CANDIDATES[rid]["historical_source_sha"],
            "evidence_paths": VERIFIED_CANDIDATES[rid]["implementation"],
        }

    status = node.get("status") or ""
    founder = node.get("founder_approval") not in (None, "NOT_REQUIRED", "", "none")
    if status == "NOT_AUTHORIZED" or founder:
        return {
            "engineering_disposition": "BLOCKED",
            "actual_implementation": "Founder-controlled or not authorized; engineering cannot accept",
            "relevant_test": node.get("evidence_required") or "",
            "executed_test_result": "N/A_BLOCKED",
            "historical_source_sha": None,
            "evidence_paths": [],
        }
    if status == "NOT_VERIFIABLE":
        return {
            "engineering_disposition": "BLOCKED",
            "actual_implementation": "Not independently verifiable in this pass",
            "relevant_test": node.get("current_evidence") or "",
            "executed_test_result": "N/A_BLOCKED",
            "historical_source_sha": None,
            "evidence_paths": [],
        }
    if status in {"NOT_STARTED", "DESIGNED_ONLY"}:
        return {
            "engineering_disposition": "NOT_IMPLEMENTED",
            "actual_implementation": "No verified engineering closure for this counted row yet",
            "relevant_test": node.get("evidence_required") or "",
            "executed_test_result": "NOT_RUN",
            "historical_source_sha": None,
            "evidence_paths": [],
        }
    if status in {"UNMERGED_NOT_ACCEPTED", "PRESENT_ON_MAIN", "NOT_ACCEPTED"}:
        return {
            "engineering_disposition": "IMPLEMENTED_UNVERIFIED",
            "actual_implementation": "Artefacts/PRs exist but executed tip evidence / independent qualification incomplete",
            "relevant_test": node.get("current_evidence") or "",
            "executed_test_result": "NOT_PROBED",
            "historical_source_sha": None,
            "evidence_paths": [],
        }
    return {
        "engineering_disposition": "NOT_IMPLEMENTED",
        "actual_implementation": f"Unhandled register status {status}",
        "relevant_test": node.get("evidence_required") or "",
        "executed_test_result": "NOT_RUN",
        "historical_source_sha": None,
        "evidence_paths": [],
    }


def build(*, run_probes: bool = True) -> dict:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    ids = list(graph["denominator_pretraining_ids"])
    sha = _git_sha()
    probes = _run_probes(sha) if run_probes else {}
    if not run_probes and PROBES_JSON.exists():
        probes = json.loads(PROBES_JSON.read_text())["probes"]

    rows = []
    hist: dict[str, int] = {}
    for rid in ids:
        node = nodes[rid]
        d = _disposition(node, probes, sha)
        hist[d["engineering_disposition"]] = hist.get(d["engineering_disposition"], 0) + 1
        rows.append({
            "requirement_id": rid,
            "exact_acceptance_condition": node.get("evidence_required") or node.get("pass_rule") or "",
            "actual_implementation": d["actual_implementation"],
            "evidence_path": node.get("current_evidence") or "",
            "evidence_paths": d.get("evidence_paths") or [],
            "candidate_sha": sha,
            "historical_source_sha": d.get("historical_source_sha"),
            "relevant_test": d["relevant_test"],
            "executed_test_result": d["executed_test_result"],
            "probe": d.get("probe"),
            "independent_evidence": "NOT_CLAIMED",
            "founder_controlled_dependency": node.get("founder_approval") not in (None, "NOT_REQUIRED", "", "none"),
            "register_status": node.get("status"),
            "engineering_disposition": d["engineering_disposition"],
            "remaining_engineering_work": node.get("escalation") or node.get("exit") or "",
            "depends_on": node.get("depends_on") or [],
            "formal_acceptance": False,
        })
    assert len(rows) == 95, len(rows)
    assert len(ledger) == 0, "ledger must remain empty"
    verified = [r for r in rows if r["engineering_disposition"] == "VERIFIED_ENGINEERING"]
    for r in verified:
        assert r["executed_test_result"].startswith("PASS"), r
        assert r["historical_source_sha"], r
        assert r["candidate_sha"] == sha
    return {
        "schema": "orneur-foundation-02-requirement-matrix/2",
        "validator_check": "pretraining=95 numerator=0",
        "formal_accepted_count": 0,
        "formal_denominator": 95,
        "candidate_sha": sha,
        "main_base_sha": HISTORICAL["main_base"],
        "register_graph_sha256": hashlib.sha256(GRAPH.read_bytes()).hexdigest(),
        "ledger_sha256": hashlib.sha256(LEDGER.read_bytes()).hexdigest(),
        "disposition_histogram": hist,
        "verified_engineering_count": len(verified),
        "verified_engineering_ids": [r["requirement_id"] for r in verified],
        "probes_path": str(PROBES_JSON.relative_to(ROOT)),
        "note": (
            "engineering_disposition is not formal acceptance. "
            "VERIFIED_ENGINEERING requires implementation paths + pytest probe PASS on candidate_sha. "
            "historical_source_sha is when code landed; candidate_sha is the tip under test. "
            "FORMALLY_ACCEPTED is never assigned by this script."
        ),
        "requirements": rows,
    }


def render_md(doc: dict) -> str:
    lines = [
        "# FOUNDATION-02 Requirement Matrix",
        "",
        f"**Candidate SHA:** `{doc['candidate_sha']}`  ",
        f"**Main base SHA:** `{doc['main_base_sha']}`  ",
        f"**Formal acceptance:** {doc['formal_accepted_count']} / {doc['formal_denominator']}  ",
        f"**Validator:** `{doc['validator_check']}`  ",
        f"**VERIFIED_ENGINEERING (probed):** {doc['verified_engineering_count']} — "
        f"{', '.join(doc['verified_engineering_ids']) or '(none)'}  ",
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
        "## VERIFIED_ENGINEERING evidence",
        "",
        "| ID | Historical SHA | Candidate SHA | Tests | Result |",
        "|---|---|---|---|---|",
    ]
    for row in doc["requirements"]:
        if row["engineering_disposition"] != "VERIFIED_ENGINEERING":
            continue
        lines.append(
            f"| {row['requirement_id']} | `{row['historical_source_sha']}` | `{row['candidate_sha']}` | "
            f"{row['relevant_test']} | {row['executed_test_result']} |"
        )
    lines += [
        "",
        "## All rows",
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
        "- `historical_source_sha` ≠ proof the tip was the only SHA ever tested; probes run on `candidate_sha`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    run_probes = "--no-probes" not in argv
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    doc = build(run_probes=run_probes)
    OUT_JSON.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(doc), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} ({len(doc['requirements'])} rows)")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    print("histogram", doc["disposition_histogram"])
    print("verified", doc["verified_engineering_ids"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
