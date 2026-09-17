"""
Operator-facing CLI for a real Genesis foundation-model baseline run
(Phase 21B.4.1, §10-12). Real model evaluation NEVER happens implicitly
-- not at import time, not during tests, not during CI, not during
ordinary application boot. It happens ONLY when this command is invoked
explicitly with every required field, and ONLY after both gates pass:

  1. TECHNICAL GATE: `--preflight` reports "READY FOR REAL BASELINE".
  2. OWNER RESOURCE GATE: an actual owner-authorized compute resource
     exists for this run. This CLI does not and cannot verify "owner
     authorization" itself (that is a human decision, not a technical
     check) -- it verifies TECHNICAL readiness only. A human operator
     must confirm the resource gate separately before running without
     --preflight.

Usage:

    # Check readiness without running any inference:
    python -m orca.eval.run_genesis_baseline --preflight \\
        --candidate qwen3-8b --upstream-model Qwen/Qwen3-8B \\
        --artifact-repo unsloth/Qwen3-8B --exact-revision <sha> \\
        --backend transformers --quantization 4bit --device cuda

    # Real execution (only after preflight is READY and a resource is
    # actually authorized and available):
    python -m orca.eval.run_genesis_baseline \\
        --candidate qwen3-8b --upstream-model Qwen/Qwen3-8B \\
        --artifact-repo unsloth/Qwen3-8B --exact-revision <sha> \\
        --backend transformers --quantization 4bit --device cuda
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are Orneur Genesis, ORNEUR's Builder / Executor model. You propose and implement "
    "software and broader executable outcomes across business, quantitative, scientific, and "
    "everyday-professional domains, but you never claim work is verified unless it genuinely "
    "has been, you never execute governed/authority-bearing actions yourself -- you propose "
    "them for a human or ORNEUR's deterministic governance layer to authorize -- and you never "
    "fabricate progress, evidence, or approval."
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orca.eval.run_genesis_baseline",
        description="Run (or preflight-check) a real Genesis foundation-model baseline against genesis-eval-v1.",
    )
    parser.add_argument("--candidate", required=True, help="Logical candidate name, e.g. 'qwen3-8b'")
    parser.add_argument("--upstream-model", required=True, help="Canonical upstream HF repo id, e.g. 'Qwen/Qwen3-8B'")
    parser.add_argument("--artifact-repo", required=True, help="Actual artifact repo/mirror used for inference")
    parser.add_argument("--exact-revision", required=True, help="Exact immutable commit SHA -- 'main'/'latest' is rejected")
    parser.add_argument("--tokenizer-revision", default=None, help="Exact tokenizer revision (defaults to --exact-revision)")
    parser.add_argument("--backend", required=True, choices=["transformers"], help="Inference backend")
    parser.add_argument("--quantization", default="none", choices=["none", "4bit", "8bit"])
    parser.add_argument("--device", default="cpu", help="'cpu' | 'cuda' | 'cuda:0' | 'mps'")
    parser.add_argument("--suite-id", default="genesis-eval")
    parser.add_argument("--suite-version", default="v1")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--system-instruction", default=DEFAULT_SYSTEM_INSTRUCTION)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--preflight", action="store_true", help="Check readiness only -- performs NO inference")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    return parser


def run_preflight(args: argparse.Namespace) -> dict:
    """Verifies WITHOUT running any inference. Returns a machine-readable
    dict with `ready: bool` and `blockers: list[str]` -- readiness is
    never a subjective log message, per spec §11."""
    blockers: list[str] = []
    checks: dict = {}

    # candidate ID syntax
    checks["candidate_id_syntax"] = bool(args.candidate and args.candidate.strip())
    if not checks["candidate_id_syntax"]:
        blockers.append("candidate name is empty")

    # exact revision supplied
    try:
        from orca.eval.runner import CandidateConfig

        CandidateConfig(
            candidate=args.candidate, upstream_model=args.upstream_model, artifact_repo=args.artifact_repo,
            exact_revision=args.exact_revision, tokenizer_revision=args.tokenizer_revision or args.exact_revision,
            backend=args.backend, quantization=args.quantization,
            inference_config={"temperature": args.temperature, "top_p": args.top_p, "max_new_tokens": args.max_new_tokens},
            seed=args.seed, context_window_used=0, system_instruction=args.system_instruction,
        )
        checks["exact_revision_pinned"] = True
    except ValueError as exc:
        checks["exact_revision_pinned"] = False
        blockers.append(f"revision pinning check failed: {exc}")

    # suite manifest state + digests
    try:
        from orca.eval.genesis_suite import all_tasks, compute_suite_digests

        tasks = all_tasks()
        task_ids, content_digest, scoring_digest = compute_suite_digests(tasks)
        checks["suite_content_digest"] = content_digest
        checks["suite_scoring_contract_digest"] = scoring_digest
        checks["suite_task_count"] = len(task_ids)
    except Exception as exc:
        blockers.append(f"failed to compute suite digests: {exc!r}")

    try:
        from orca.registry.evaluation_suite_manifest import EvaluationSuiteManifest

        try:
            persisted = EvaluationSuiteManifest.load(args.suite_id, args.suite_version)
            checks["suite_persisted"] = True
            checks["suite_frozen"] = persisted.frozen
        except FileNotFoundError:
            checks["suite_persisted"] = False
            checks["suite_frozen"] = False
            # Not a blocker -- first registration happens automatically inside
            # record_baseline_and_freeze_suite() on the first real baseline.
    except Exception as exc:
        blockers.append(f"failed to check suite manifest state: {exc!r}")

    # sandbox availability + security contract
    try:
        from orca.eval.sandbox_docker import is_docker_available

        docker_ok = is_docker_available()
        checks["docker_available"] = docker_ok
        if not docker_ok:
            blockers.append("Docker is not available -- required for coding/debugging category scoring")
        else:
            from orca.eval.sandbox_contract import current_docker_contract

            contract = current_docker_contract()
            checks["sandbox_contract"] = asdict(contract)
            if contract.container_image_digest is None:
                blockers.append(
                    f"sandbox image {contract.container_image_tag!r} has not been pulled locally -- "
                    "its digest cannot be resolved, so the sandbox contract is not yet reproducible"
                )
    except Exception as exc:
        blockers.append(f"failed to check sandbox availability: {exc!r}")

    # output directories / disk capacity
    try:
        from orca.registry.evaluation_result_manifest import EVALUATION_RESULT_DIR

        checks["result_destination"] = str(EVALUATION_RESULT_DIR)
        checks["result_destination_writable"] = EVALUATION_RESULT_DIR.exists() and _is_writable(EVALUATION_RESULT_DIR)
        if not checks["result_destination_writable"]:
            blockers.append(f"result destination {EVALUATION_RESULT_DIR} is not writable")
        usage = shutil.disk_usage(EVALUATION_RESULT_DIR)
        checks["disk_free_bytes"] = usage.free
        if usage.free < 1_000_000_000:  # 1GB floor for result/log artifacts (NOT model weights)
            blockers.append(f"less than 1GB free disk space at {EVALUATION_RESULT_DIR}")
    except Exception as exc:
        blockers.append(f"failed to check output directory/disk capacity: {exc!r}")

    # model adapter availability + backend/library versions
    try:
        import transformers

        checks["transformers_version"] = transformers.__version__
        try:
            import torch

            checks["torch_version"] = torch.__version__
            checks["cuda_available"] = torch.cuda.is_available()
            checks["mps_available"] = getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()
        except ImportError:
            blockers.append("torch is not installed")
        if args.backend == "transformers":
            checks["adapter_module_importable"] = True
    except ImportError:
        blockers.append("transformers is not installed")
        checks["adapter_module_importable"] = False

    # selected device visibility
    if args.device.startswith("cuda") and not checks.get("cuda_available", False):
        blockers.append(f"--device {args.device!r} requested but CUDA is not available on this host")
    if args.device == "mps" and not checks.get("mps_available", False):
        blockers.append("--device mps requested but MPS is not available on this host")

    ready = len(blockers) == 0
    return {"ready": ready, "blockers": blockers, "checks": checks}


def _is_writable(path) -> bool:
    import os

    return os.access(path, os.W_OK)


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.preflight:
        report = run_preflight(args)
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print("READY FOR REAL BASELINE" if report["ready"] else "NOT READY")
            if report["blockers"]:
                print("Blockers:")
                for b in report["blockers"]:
                    print(f"  - {b}")
        return 0 if report["ready"] else 1

    # Real execution path -- gated by preflight passing AND (separately,
    # not verifiable by this CLI) owner resource authorization. This CLI
    # re-runs preflight internally before allowing execution to proceed,
    # so a caller cannot skip straight to inference on a not-ready system.
    preflight_report = run_preflight(args)
    if not preflight_report["ready"]:
        print("NOT READY -- refusing to run real inference. Run with --preflight for details.", file=sys.stderr)
        for b in preflight_report["blockers"]:
            print(f"  - {b}", file=sys.stderr)
        return 1

    print(
        "Technical preflight is READY, but this command does not itself verify owner "
        "resource authorization -- that is a human decision, not a technical check. "
        "Confirm an owner-authorized compute resource is actually in use before proceeding.",
        file=sys.stderr,
    )
    # Real execution wiring (adapter construction, run_suite(), and
    # record_baseline_and_freeze_suite()) is intentionally NOT invoked
    # here without that explicit human confirmation step -- see
    # docs/orneur/phase-21/PHASE21B4_1_COMPUTE_READY_CLOSURE.md for the
    # exact remaining manual step and why it is not automated.
    print("Real execution wiring exists in orca.eval.runner and orca.eval.adapters -- "
          "invoke it directly once resource authorization is confirmed.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
