#!/usr/bin/env python3
"""Build FOUNDATION-02 engineering disposition matrix over the 95 counted rows.

Does not accept requirements, edit the ledger, or mint signatures.
Verified status requires inspectable implementation + honest pytest evidence:
actual passes, not exit-0 alone, not skip-only, not xfail-only, not zero-collected.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from orca.pretrain_foundation.probe_honesty import (  # noqa: E402
    assert_command_portable,
    build_probe_env,
    classify_probe,
    implementation_digests,
    lockfile_digest,
    resolve_python,
)

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
    # Prior independently tested code-bearing tip (Antigravity handoff).
    "prior_qualified_code_sha": "4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4",
}

# Candidate probe definitions: only these may become VERIFIED_ENGINEERING.
# Mappings MUST match register_graph.json evidence_required (not convenient filenames).
# Independently qualified by Antigravity (limited scope): C04, C05, C17–C21.
VERIFIED_CANDIDATES = {
    # C01: Refusal log from the signed registry path showing an unregistered id refused.
    "C01": {
        "implementation": ["orca/rse/imp1/authority.py", "orca/rse/imp1/codec.py"],
        "tests": ["tests/rse/test_c01_c02_registry_refusal.py"],
        "historical_source_sha": "b384348",
        "claim": "Signed-registry Crown path refuses unregistered entry id (ABSENT)",
    },
    # C02: Consumer refusal record for a stale or unknown registry.
    "C02": {
        "implementation": ["orca/rse/imp1/authority.py", "orca/rse/imp1/codec.py"],
        "tests": ["tests/rse/test_c01_c02_registry_refusal.py", "tests/rse/test_imp1r_final.py"],
        "historical_source_sha": "b384348",
        "claim": "Consumer / accept_registry refuse stale or unknown registry binding",
    },
    # C04: Refusal record for a ceiling above the policy cap.
    "C04": {
        "implementation": ["orca/rse/imp1/authority.py", "orca/rse/imp1/codec.py"],
        "tests": ["tests/rse/test_imp1_registry_crown.py"],
        "historical_source_sha": "b384348",
        "claim": "Policy ceiling / RESOURCE_CAP refusal (independently qualified)",
    },
    # C05: Validator output refusing a confusable name.
    "C05": {
        "implementation": ["orca/rse/imp1/codec.py"],
        "tests": ["tests/rse/test_imp1_registry_crown.py"],
        "historical_source_sha": "b384348",
        "claim": "Confusable registry name refusal (independently qualified)",
    },
    # C17–C21: OCR1 vector / frame / sender / origin acceptance conditions.
    "C17": {
        "implementation": ["orca/rse/imp4/ocr1.py"],
        "tests": ["tests/rse/test_imp4_ocr1.py"],
        "historical_source_sha": "b384348",
        "claim": "OCR1 enc validity / zero-shared-secret abort (independently qualified)",
    },
    "C18": {
        "implementation": ["orca/rse/imp4/ocr1.py"],
        "tests": ["tests/rse/test_imp4_ocr1.py"],
        "historical_source_sha": "b384348",
        "claim": "RFC 9180 profile vectors used by OCR1 (independently qualified)",
    },
    "C19": {
        "implementation": ["orca/rse/imp4/ocr1.py"],
        "tests": ["tests/rse/test_imp4_ocr1.py"],
        "historical_source_sha": "b384348",
        "claim": "Missing/duplicate/reordered/extra/truncated/foreign frame verdicts (independently qualified)",
    },
    "C20": {
        "implementation": ["orca/rse/imp4/ocr1.py"],
        "tests": ["tests/rse/test_imp4_ocr1.py"],
        "historical_source_sha": "b384348",
        "claim": "Unknown or revoked sender refusal (independently qualified)",
    },
    "C21": {
        "implementation": ["orca/rse/imp4/ocr1.py"],
        "tests": ["tests/rse/test_imp4_ocr1.py"],
        "historical_source_sha": "b384348",
        "claim": "Bad origin signature rejected before key use (independently qualified)",
    },
    # TRAIN-1: A hash lock of the train extra and one dry-run command pinned to a SHA.
    "TRAIN-1": {
        "implementation": [
            "orca/train/dryrun/lockcheck.py",
            "requirements/train.txt",
            "orca/train/dryrun/cli.py",
        ],
        "tests": ["tests/test_trainprep_lock_env.py"],
        "historical_source_sha": "fc1eb1d",
        "claim": "Hash-locked train extra (requirements/train.txt) + SHA-bound dry-run command surface",
    },
    # TRAIN-2: Synthetic dry-run log showing corpus/qual/model/GPU/training locks still false.
    "TRAIN-2": {
        "implementation": [
            "orca/train/dryrun/cli.py",
            "orca/rse/imp1/locks.py",
            "docs/orneur/status/trainprep/dryrun_result.json",
        ],
        "tests": ["tests/test_train2_dryrun_locks_evidence.py"],
        "historical_source_sha": "fc1eb1d",
        "claim": "Synthetic dry-run proves authorization locks remain false; no training",
    },
}

# Explicit classifications from register_graph acceptance conditions.
# Software tests must not substitute founder / physical / private-corpus artifacts.
FORCE_UNVERIFIED = {
    "FINAL-1": (
        "IMPLEMENTED_UNVERIFIED",
        "Engineering worksheet artifact exists; FINAL-1 requires independent recomputation and formal process",
        "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json",
    ),
    "C16": (
        "IMPLEMENTED_UNVERIFIED",
        "Primary OCR1 codec present; independent second implementation agreement not supplied (Cursor cannot self-certify)",
        "orca/pretrain_foundation/independent_codec.py",
    ),
    "C03": (
        "IMPLEMENTED_UNVERIFIED",
        "Canonical registry update dual-owner evidence software exists in RSE; dual distinct owner-token acceptance record not independently qualified",
        "orca/rse/imp1/codec.py",
    ),
    "C09": (
        "IMPLEMENTED_UNVERIFIED",
        "IMP-3 challenge-reuse software exists; original acceptance requires journal/freshness evidence, not software-test substitution",
        "orca/rse/imp3/freshness.py",
    ),
    "C10": (
        "IMPLEMENTED_UNVERIFIED",
        "IMP-3 freshness helpers exist; original acceptance requires freshness/journal artifact, not unit-probe substitution",
        "orca/rse/imp3/freshness.py",
    ),
    "C11": (
        "IMPLEMENTED_UNVERIFIED",
        "IMP-2 machine semantics exist; original acceptance requires witnessed checkpoint evidence on the operational path",
        "orca/rse/imp2/machine.py",
    ),
    "C12": (
        "IMPLEMENTED_UNVERIFIED",
        "Witness cosignature software exists; original acceptance requires witness cosignature / forged-ack refusal artifacts",
        "orca/rse/imp3/ledger.py",
    ),
    "C13": (
        "IMPLEMENTED_UNVERIFIED",
        "Synthetic fence is not the required witness-log fork/smaller-tree refusal artifact",
        "orca/rse/imp3/ledger.py",
    ),
    "C14": (
        "IMPLEMENTED_UNVERIFIED",
        "Unwitnessed-bundle refusal helpers exist; original acceptance requires witnessed-result usability evidence",
        "orca/rse/imp3/ledger.py",
    ),
    "C15": (
        "IMPLEMENTED_UNVERIFIED",
        "Software crash/journal recovery is not C26 power-cut / journal-replay acceptance evidence",
        "orca/rse/imp3/ledger.py",
    ),
    "C45": (
        "IMPLEMENTED_UNVERIFIED",
        "Lifecycle-edge software refusals exist; class-K / impossible-edge acceptance remains a separate decision record",
        "orca/rse/imp2/machine.py",
    ),
    "QUAL-2": (
        "IMPLEMENTED_UNVERIFIED",
        "Eval-boundary helpers deny training-identity holdout reads in unit tests; original QUAL-2 requires accepted failed-read isolation evidence (depends on QUAL-1/P2-2)",
        "orca/pretrain_foundation/eval_boundary.py",
    ),
    "DATA-1": (
        "IMPLEMENTED_UNVERIFIED",
        "Synthetic manifest/admission helpers exist; acceptance requires a provenance manifest bound to the DATA-3 creation digest (no protected corpus)",
        "orca/genesis/data/manifest.py",
    ),
    "DATA-2": (
        "IMPLEMENTED_UNVERIFIED",
        "Contamination helpers exist; acceptance requires holdout-separation bound to creation digest and holdout fingerprints (no protected corpus)",
        "orca/genesis/data/contamination.py",
    ),
    "SUP-3": (
        "IMPLEMENTED_UNVERIFIED",
        "RSE hash-lock / audit software exists; acceptance requires the lock on the SHA merged to main",
        "requirements/rse.txt",
    ),
}

FORCE_BLOCKED = {
    "G4": (
        "BLOCKED",
        "Founder purchase authorization and named hardware selection absent (register NOT_AUTHORIZED)",
        "docs/orneur/authorization/TRAINING_AUTHORIZATION.json",
    ),
    "G5": (
        "BLOCKED",
        "Provisioning / key-creation ceremony record absent (register NOT_AUTHORIZED)",
        "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json",
    ),
    "AUTH-1": (
        "BLOCKED",
        "Signed founder budget record (number, currency, signature) absent (register NOT_VERIFIABLE)",
        "docs/orneur/authorization/TRAINING_AUTHORIZATION.json",
    ),
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

# Independently qualified engineering IDs (Antigravity LIMITED TO TESTED SCOPE).
INDEPENDENTLY_QUALIFIED_ENGINEERING_IDS = ("C04", "C05", "C17", "C18", "C19", "C20", "C21")
# Data admission controls are qualified software but do not satisfy a counted DATA-* acceptance row.
QUALIFIED_UNCOUNTED_SOFTWARE = {
    "capability_id": "DATA_ADMISSION_CONTROLS",
    "canonical_requirement_id": None,
    "reason": (
        "Remote-origin refusal and training-bound license/jail admission are independently "
        "exercised software controls; they do not satisfy DATA-1 (provenance manifest bound to "
        "DATA-3 creation digest) or DATA-2 (contamination/holdout separation on a protected corpus)."
    ),
    "implementation": [
        "orca/pretrain_foundation/corpus_controls.py",
        "orca/genesis/data/pipeline.py",
    ],
    "tests": [
        "tests/test_pretraining_phase_closure.py",
        "tests/test_pretraining_call_chain_integration.py",
        "tests/test_cursor_pipeline_admission.py",
    ],
}


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _assert_clean_worktree() -> None:
    """Refuse probe runs against a dirty worktree (digests must match the tip)."""
    status = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
    ).strip()
    if status:
        raise RuntimeError(
            "refusing to run acceptance-producing probes on a dirty worktree; "
            "commit or stash changes so digests bind to an exact candidate SHA:\n"
            f"{status}"
        )


def _run_probes(candidate_sha: str) -> dict:
    """Execute verification probes and return machine-readable honest results."""
    _assert_clean_worktree()
    env = build_probe_env(ROOT)
    python = resolve_python(ROOT)

    results: dict[str, dict] = {}
    for rid, meta in VERIFIED_CANDIDATES.items():
        missing = [p for p in meta["implementation"] if not (ROOT / p).exists()]
        missing_tests = [p for p in meta["tests"] if not (ROOT / p).exists()]
        # Portable argv: interpreter path may resolve under the repo; never inject
        # /home/ubuntu site-packages. Record argv with a portable python token.
        cmd = [python, "-m", "pytest", "-q", "--tb=no", *meta["tests"]]
        portable_cmd = ["python", "-m", "pytest", "-q", "--tb=no", *meta["tests"]]
        assert_command_portable(portable_cmd)

        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        verdict = classify_probe(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            missing_implementation=missing,
            missing_tests=missing_tests,
            expected_candidate_sha=candidate_sha,
            recorded_candidate_sha=candidate_sha,
        )
        digests = implementation_digests(ROOT, meta["implementation"])
        results[rid] = {
            "requirement_id": rid,
            "claim": meta["claim"],
            "implementation_paths": meta["implementation"],
            "implementation_sha256": digests,
            "missing_implementation": missing,
            "test_paths": meta["tests"],
            "missing_tests": missing_tests,
            "historical_source_sha": meta["historical_source_sha"],
            "candidate_sha": candidate_sha,
            "pytest_command": portable_cmd,
            "python_resolved": python,
            "pythonpath": env.get("PYTHONPATH", ""),
            "exit_code": proc.returncode,
            "summary_line": verdict.counts.summary_line or "",
            "counts": verdict.counts.to_dict(),
            "passed_probe": verdict.passed_probe,
            "verdict_reason": verdict.reason,
            "refusal_codes": list(verdict.refusal_codes),
            "stderr_tail": (proc.stderr or "")[-500:],
        }
    payload = {
        "schema": "orneur-foundation-02-verification-probes/3",
        "candidate_sha": candidate_sha,
        "prior_qualified_code_sha": HISTORICAL["prior_qualified_code_sha"],
        "lockfile_sha256": lockfile_digest(ROOT),
        "honesty_rules": [
            "require_exit_code_0",
            "require_at_least_one_passed",
            "reject_zero_collected",
            "reject_skip_only",
            "reject_skips_present_including_mixed_pass_skip",
            "reject_xfail_only",
            "distinguish_xfailed_from_passed",
            "require_complete_expected_and_recorded_candidate_sha",
            "reject_absent_empty_malformed_or_mismatched_candidate_sha",
            "no_inherited_pythonpath_or_pytest_addopts",
            "portable_pytest_command_argv",
            "refuse_dirty_worktree_probe_runs",
        ],
        "training_authorization": "NO-GO",
        "probes": results,
    }
    PROBES_JSON.write_text(json.dumps(payload, indent=2) + "\n")
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
        probe = probes.get(rid)
        if probe is None:
            return {
                "engineering_disposition": "IMPLEMENTED_UNVERIFIED",
                "actual_implementation": "; ".join(VERIFIED_CANDIDATES[rid]["implementation"]),
                "relevant_test": "; ".join(VERIFIED_CANDIDATES[rid]["tests"]),
                "executed_test_result": "PROBE_MISSING",
                "historical_source_sha": VERIFIED_CANDIDATES[rid]["historical_source_sha"],
                "evidence_paths": VERIFIED_CANDIDATES[rid]["implementation"],
            }
        # Refuse stale --no-probes payloads from another tip.
        if probe.get("candidate_sha") != candidate_sha:
            return {
                "engineering_disposition": "IMPLEMENTED_UNVERIFIED",
                "actual_implementation": "; ".join(probe["implementation_paths"]),
                "relevant_test": "; ".join(probe["test_paths"]),
                "executed_test_result": (
                    f"PROBE_SHA_MISMATCH probe={probe.get('candidate_sha')} "
                    f"candidate={candidate_sha}"
                ),
                "historical_source_sha": probe["historical_source_sha"],
                "evidence_paths": probe["implementation_paths"],
            }
        if probe.get("passed_probe"):
            counts = probe.get("counts") or {}
            if (counts.get("skipped") or 0) > 0:
                return {
                    "engineering_disposition": "IMPLEMENTED_UNVERIFIED",
                    "actual_implementation": "; ".join(VERIFIED_CANDIDATES[rid]["implementation"]),
                    "relevant_test": "; ".join(VERIFIED_CANDIDATES[rid]["tests"]),
                    "executed_test_result": (
                        f"PROBE_REFUSED_SKIPS_PRESENT skipped={counts.get('skipped')} "
                        f"{probe.get('summary_line')}"
                    ),
                    "historical_source_sha": VERIFIED_CANDIDATES[rid]["historical_source_sha"],
                    "evidence_paths": VERIFIED_CANDIDATES[rid]["implementation"],
                }
            return {
                "engineering_disposition": "VERIFIED_ENGINEERING",
                "actual_implementation": "; ".join(probe["implementation_paths"]),
                "relevant_test": "; ".join(probe["test_paths"]),
                "executed_test_result": (
                    f"PASS ({probe.get('summary_line')}) "
                    f"passed={counts.get('passed')} "
                    f"xfailed={counts.get('xfailed') or 0} "
                    f"skipped={counts.get('skipped') or 0}"
                ),
                "historical_source_sha": probe["historical_source_sha"],
                "evidence_paths": probe["implementation_paths"] + probe["test_paths"],
                "probe": {
                    "exit_code": probe["exit_code"],
                    "summary_line": probe.get("summary_line"),
                    "counts": counts,
                    "candidate_sha": candidate_sha,
                    "implementation_sha256": probe.get("implementation_sha256") or {},
                    "refusal_codes": probe.get("refusal_codes") or [],
                    "verdict_reason": probe.get("verdict_reason"),
                },
            }
        return {
            "engineering_disposition": "IMPLEMENTED_UNVERIFIED",
            "actual_implementation": "; ".join(VERIFIED_CANDIDATES[rid]["implementation"]),
            "relevant_test": "; ".join(VERIFIED_CANDIDATES[rid]["tests"]),
            "executed_test_result": (
                f"PROBE_REFUSED exit={probe.get('exit_code')} "
                f"reason={probe.get('verdict_reason')} "
                f"{probe.get('summary_line')}"
            ),
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
        stored = json.loads(PROBES_JSON.read_text())
        probes = stored.get("probes") or {}
        # Stale tip: keep probes but disposition refuses VERIFIED on SHA mismatch.

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
        assert r["probe"] and (r["probe"].get("counts") or {}).get("passed", 0) >= 1
        assert (r["probe"].get("counts") or {}).get("skipped") in (None, 0)
    return {
        "schema": "orneur-foundation-02-requirement-matrix/3",
        "validator_check": "pretraining=95 numerator=0",
        "formal_accepted_count": 0,
        "formal_denominator": 95,
        "candidate_sha": sha,
        "main_base_sha": HISTORICAL["main_base"],
        "prior_qualified_code_sha": HISTORICAL["prior_qualified_code_sha"],
        "register_graph_sha256": hashlib.sha256(GRAPH.read_bytes()).hexdigest(),
        "ledger_sha256": hashlib.sha256(LEDGER.read_bytes()).hexdigest(),
        "lockfile_sha256": lockfile_digest(ROOT),
        "disposition_histogram": hist,
        "verified_engineering_count": len(verified),
        "verified_engineering_ids": [r["requirement_id"] for r in verified],
        "antigravity_remediation_downgrades": [
            "C09", "C10", "C11", "C12", "C13", "C14", "C15", "C45", "QUAL-2",
        ],
        "independently_qualified_engineering_ids": list(INDEPENDENTLY_QUALIFIED_ENGINEERING_IDS),
        "qualified_uncounted_software": QUALIFIED_UNCOUNTED_SOFTWARE,
        "probes_path": str(PROBES_JSON.relative_to(ROOT)),
        "training_authorization": "NO-GO",
        "note": (
            "engineering_disposition is not formal acceptance. "
            "Mappings are derived from register_graph.json evidence_required only. "
            "VERIFIED_ENGINEERING requires implementation paths + honest pytest evidence "
            "(>=1 passed; reject zero-collected / skip-only / mixed skips / xfail-only) "
            "on a complete matching candidate_sha. "
            "Independently qualified engineering (Antigravity LIMITED TO TESTED SCOPE): "
            "C04, C05, C17–C21. Data admission controls are qualified uncounted software "
            "(no eighth fabricated requirement ID). "
            "G4/G5/AUTH-1 remain BLOCKED (founder artifacts). "
            "DATA-1/DATA-2 remain IMPLEMENTED_UNVERIFIED (no protected corpus). "
            "FORMALLY_ACCEPTED is never assigned by this script. Training remains NO-GO."
        ),
        "requirements": rows,
    }


def render_md(doc: dict) -> str:
    lines = [
        "# FOUNDATION-02 Requirement Matrix",
        "",
        f"**Candidate SHA:** `{doc['candidate_sha']}`  ",
        f"**Prior qualified code SHA:** `{doc.get('prior_qualified_code_sha')}`  ",
        f"**Main base SHA:** `{doc['main_base_sha']}`  ",
        f"**Formal acceptance:** {doc['formal_accepted_count']} / {doc['formal_denominator']}  ",
        f"**Validator:** `{doc['validator_check']}`  ",
        f"**Training authorization:** **{doc.get('training_authorization', 'NO-GO')}**  ",
        f"**VERIFIED_ENGINEERING (honest probes):** {doc['verified_engineering_count']} — "
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
        "- Exit code 0 with zero collected / skip-only / mixed pass-skip / xfail-only is **not** VERIFIED_ENGINEERING.",
        "- `xfailed` residuals are distinguished from `passed`; an xfail is not a PASS.",
        "- Acceptance probes require complete expected and recorded 40-hex candidate SHAs.",
        "- Probe commands must not embed machine-specific interpreter or site-package paths.",
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
    print("training_authorization", doc.get("training_authorization"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
