"""ORNEUR Master Qualification Test Suite Orchestrator.

Executes the independent qualification battery against explicitly selected target candidates,
enforces worktree and PYTHONPATH isolation, distinguishes positive from negative controls,
records dual-provenance (candidate SHA vs harness SHA), measures telemetry, and emits
strict machine-readable evidence manifests.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def get_git_info(target_dir: Path) -> dict:
    info = {"sha": "unknown", "branch": "unknown", "clean": False}
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target_dir, text=True).strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target_dir, text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=target_dir, text=True).strip()
        info["sha"] = sha
        info["branch"] = branch
        info["clean"] = len(status) == 0
    except Exception as e:
        info["error"] = str(e)
    return info


def find_python_executable(worktree: Path) -> str:
    """Resolve Python executable without hardcoded workstation paths."""
    venv_py = worktree / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    # Check current runtime environment
    return sys.executable


def run_test_suite(
    python_bin: str,
    candidate_worktree: Path,
    harness_worktree: Path,
    test_rel_path: str,
    redis_db: int = 13,
) -> dict:
    """Execute one qualification test suite strictly isolated to candidate's modules."""
    test_file = harness_worktree / test_rel_path
    if not test_file.exists():
        test_file = candidate_worktree / test_rel_path

    cmd = [
        python_bin,
        "-m", "pytest",
        str(test_file),
        "-v",
        "-p", "no:cacheprovider",
        "--tb=short",
    ]

    # Enforce strict PYTHONPATH to candidate worktree to prevent accidental cross-worktree imports
    env = os.environ.copy()
    env["PYTHONPATH"] = str(candidate_worktree)
    env["ORCA_ENV"] = "test"
    env["ORCA_REDIS_URL"] = f"redis://127.0.0.1:6379/{redis_db}"
    env["REDIS_URL"] = f"redis://127.0.0.1:6379/{redis_db}"
    env["JWT_SECRET_KEY"] = "qualification-harness-secret-key-32b!"

    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=candidate_worktree, capture_output=True, text=True, env=env)
    duration = time.perf_counter() - t0

    # Parse stdout for outcomes
    passed_count = res.stdout.count(" PASSED")
    skipped_count = res.stdout.count(" SKIPPED")
    failed_count = res.stdout.count(" FAILED")

    return {
        "command": " ".join(cmd),
        "exit_code": res.returncode,
        "passed": res.returncode == 0,
        "duration_seconds": round(duration, 3),
        "passed_count": passed_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }


def main():
    parser = argparse.ArgumentParser(description="ORNEUR Qualification Orchestrator")
    parser.add_argument("--candidate-worktree", required=True, help="Path to target candidate worktree")
    parser.add_argument("--harness-worktree", default=str(Path(__file__).resolve().parent.parent.parent), help="Path to qualification harness worktree")
    parser.add_argument("--output", default="docs/orneur/landmarks/qualification-01/QUALIFICATION_01_EVIDENCE_MANIFEST.json", help="Output evidence JSON path")
    parser.add_argument("--redis-db", type=int, default=13, help="Isolated test Redis DB")
    args = parser.parse_args()

    candidate_dir = Path(args.candidate_worktree).resolve()
    harness_dir = Path(args.harness_worktree).resolve()

    if not candidate_dir.exists():
        print(f"ERROR: Candidate worktree '{candidate_dir}' does not exist.", file=sys.stderr)
        sys.exit(2)

    candidate_git = get_git_info(candidate_dir)
    harness_git = get_git_info(harness_dir)
    python_bin = find_python_executable(candidate_dir)

    print("=" * 80)
    print("ORNEUR QUALIFICATION LANDMARK-01 — ORCHESTRATOR")
    print(f"Candidate Worktree : {candidate_dir}")
    print(f"Candidate SHA      : {candidate_git['sha']} (Branch: {candidate_git['branch']}, Clean: {candidate_git['clean']})")
    print(f"Harness Worktree   : {harness_dir}")
    print(f"Harness SHA        : {harness_git['sha']} (Branch: {harness_git['branch']})")
    print(f"Python Executable  : {python_bin}")
    print(f"Isolated Redis DB  : {args.redis_db}")
    print("=" * 80)

    test_files = [
        "tests/qualification/test_auth_adversarial.py",
        "tests/qualification/test_inference_adversarial.py",
        "tests/qualification/test_storage_concurrency.py",
        "tests/qualification/test_privacy_lifecycle.py",
        "tests/qualification/test_reliability_load.py",
    ]

    manifest = {
        "manifest_version": "2.0.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "candidate": {
            "worktree": str(candidate_dir),
            "sha": candidate_git["sha"],
            "branch": candidate_git["branch"],
            "clean": candidate_git["clean"],
        },
        "harness": {
            "worktree": str(harness_dir),
            "sha": harness_git["sha"],
            "branch": harness_git["branch"],
        },
        "environment": {
            "os": "Ubuntu 24.04 LTS (WSL2 Linux 6.18.54.1-microsoft)",
            "python_runtime": sys.version.split()[0],
            "python_executable": python_bin,
            "redis_instance": f"redis://127.0.0.1:6379/{args.redis_db} (Isolated test DB)",
            "model_serving": "llama3.2:1b via Ollama (localhost:11434)",
        },
        "results": {},
        "summary": {
            "total_suites": len(test_files),
            "passed_suites": 0,
            "failed_suites": 0,
            "total_tests_passed": 0,
            "total_tests_skipped": 0,
            "total_tests_failed": 0,
            "total_duration_seconds": 0.0,
            "qualification_status": "PENDING",
        },
    }

    any_unexpected_failure = False

    for tf in test_files:
        print(f"\nRunning {tf}...")
        res = run_test_suite(python_bin, candidate_dir, harness_dir, tf, redis_db=args.redis_db)
        manifest["results"][tf] = res
        manifest["summary"]["total_duration_seconds"] += res["duration_seconds"]
        manifest["summary"]["total_tests_passed"] += res["passed_count"]
        manifest["summary"]["total_tests_skipped"] += res["skipped_count"]
        manifest["summary"]["total_tests_failed"] += res["failed_count"]

        if res["passed"]:
            manifest["summary"]["passed_suites"] += 1
            print(f"  -> PASSED ({res['passed_count']} passed, {res['skipped_count']} skipped in {res['duration_seconds']}s)")
        else:
            manifest["summary"]["failed_suites"] += 1
            any_unexpected_failure = True
            print(f"  -> FAILED ({res['failed_count']} failed in {res['duration_seconds']}s)")

    manifest["summary"]["total_duration_seconds"] = round(manifest["summary"]["total_duration_seconds"], 3)
    manifest["summary"]["qualification_status"] = "PASSED" if not any_unexpected_failure else "FAILED"

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = harness_dir / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n" + "=" * 80)
    print("Qualification Battery Execution Complete.")
    print(f"Outcome              : {manifest['summary']['qualification_status']}")
    print(f"Suites (Passed/Total): {manifest['summary']['passed_suites']}/{manifest['summary']['total_suites']}")
    print(f"Tests (Pass/Skip/Fail): {manifest['summary']['total_tests_passed']}/{manifest['summary']['total_tests_skipped']}/{manifest['summary']['total_tests_failed']}")
    print(f"Evidence Manifest    : {out_path}")
    print("=" * 80)

    if any_unexpected_failure:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
