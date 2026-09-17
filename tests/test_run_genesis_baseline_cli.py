"""
Phase 21B.4.1 (§10-12, §18) CLI tests for
orca.eval.run_genesis_baseline -- confirms preflight is machine-readable
(never a subjective log message), that unpinned revisions and
unavailable devices are reported as explicit blockers, and that real
execution is refused (never silently attempted) when preflight is not
ready. No test in this file performs real model inference.
"""
from __future__ import annotations

import argparse

from orca.eval.run_genesis_baseline import _build_arg_parser, main, run_preflight


def _args(**overrides):
    defaults = dict(
        candidate="test-candidate", upstream_model="test/model", artifact_repo="test/model-artifact",
        exact_revision="a" * 40, tokenizer_revision=None, backend="transformers", quantization="none",
        device="cpu", suite_id="genesis-eval", suite_version="v1", max_new_tokens=64, temperature=0.0,
        top_p=1.0, seed=42, system_instruction="test system instruction", run_id=None,
        preflight=True, json=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_arg_parser_requires_core_fields():
    parser = _build_arg_parser()
    import pytest

    with pytest.raises(SystemExit):
        parser.parse_args(["--preflight"])  # missing required --candidate etc


def test_arg_parser_accepts_full_valid_invocation():
    parser = _build_arg_parser()
    args = parser.parse_args([
        "--candidate", "qwen3-8b", "--upstream-model", "Qwen/Qwen3-8B",
        "--artifact-repo", "unsloth/Qwen3-8B", "--exact-revision", "a" * 40,
        "--backend", "transformers", "--preflight",
    ])
    assert args.candidate == "qwen3-8b"
    assert args.exact_revision == "a" * 40


def test_preflight_returns_a_dict_with_ready_and_blockers_keys():
    report = run_preflight(_args())
    assert isinstance(report, dict)
    assert "ready" in report and isinstance(report["ready"], bool)
    assert "blockers" in report and isinstance(report["blockers"], list)


def test_preflight_rejects_unpinned_revision_as_explicit_blocker():
    report = run_preflight(_args(exact_revision="main"))
    assert report["ready"] is False
    assert any("revision" in b.lower() for b in report["blockers"])


def test_preflight_rejects_empty_candidate():
    report = run_preflight(_args(candidate=""))
    assert report["ready"] is False
    assert any("candidate" in b.lower() for b in report["blockers"])


def test_preflight_flags_unavailable_cuda_device():
    report = run_preflight(_args(device="cuda:0"))
    if not report["checks"].get("cuda_available", False):
        assert report["ready"] is False
        assert any("cuda" in b.lower() for b in report["blockers"])


def test_preflight_reports_suite_digests_when_computable():
    report = run_preflight(_args())
    assert "suite_content_digest" in report["checks"]
    assert "suite_scoring_contract_digest" in report["checks"]
    assert report["checks"]["suite_task_count"] == 90


def test_preflight_reports_docker_and_sandbox_contract_when_available():
    report = run_preflight(_args())
    assert "docker_available" in report["checks"]
    if report["checks"]["docker_available"]:
        assert "sandbox_contract" in report["checks"]


def test_main_preflight_exit_code_matches_readiness(capsys):
    ready_code = main([
        "--candidate", "test", "--upstream-model", "test/model", "--artifact-repo", "test/model",
        "--exact-revision", "a" * 40, "--backend", "transformers", "--device", "cpu", "--preflight",
    ])
    not_ready_code = main([
        "--candidate", "test", "--upstream-model", "test/model", "--artifact-repo", "test/model",
        "--exact-revision", "main", "--backend", "transformers", "--device", "cpu", "--preflight",
    ])
    assert not_ready_code == 1
    # ready_code is 0 only if this host is fully ready (Docker + writable dirs
    # etc) -- assert it's a valid exit code either way, not a crash.
    assert ready_code in (0, 1)


def test_main_refuses_real_execution_when_preflight_not_ready(capsys):
    exit_code = main([
        "--candidate", "test", "--upstream-model", "test/model", "--artifact-repo", "test/model",
        "--exact-revision", "main",  # unpinned -- guarantees NOT READY
        "--backend", "transformers", "--device", "cpu",
    ])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "NOT READY" in captured.err


def test_main_preflight_json_output_is_valid_json(capsys):
    main([
        "--candidate", "test", "--upstream-model", "test/model", "--artifact-repo", "test/model",
        "--exact-revision", "a" * 40, "--backend", "transformers", "--device", "cpu", "--preflight", "--json",
    ])
    import json

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "ready" in parsed
