"""Model-execution authorization boundary: ordinary repo activity can never invoke a model; every authorization field must be exact."""
import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from orca.eval.genesis_v2 import authorization as A

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows"
SHA = "a" * 40
NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    else:
        pytest.importorskip("cryptography")


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def signer():
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    sk = Ed25519PrivateKey.generate()                          # ephemeral, in-test only
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "k-test", "public_key_hex": pub, "identity": "owner@example.invalid", "role": "OWNER"}]

    def make(**over):
        r = A.default_record()
        r.update({"authorization_id": "auth-" + "0f" * 8, "status": "AUTHORIZED", "commit_sha": SHA, "eval_version": "genesis-capability-eval/2.0.0",
                  "candidate": {"model_id": "cand-x", "revision": "rev-1"}, "permitted_stage": "STAGE_1", "permitted_runner_class": "SELF_HOSTED_CPU",
                  "permitted_purpose": "SCREENING", "max_runs": 2, "max_spend_usd": 0, "issued_at": ts(NOW - timedelta(hours=1)),
                  "expires_at": ts(NOW + timedelta(days=1)), "authorizing_authority": {"identity": "owner@example.invalid", "role": "OWNER", "key_id": "k-test"},
                  "gpu_allowed": False, "network_provider_inference_allowed": False})
        r.update(over)
        r["signature"] = sk.sign(A.canonical_signing_bytes(r)).hex()
        return r
    return make, keys


def req(**over):
    base = dict(commit_sha=SHA, eval_version="genesis-capability-eval/2.0.0", candidate_model_id="cand-x", candidate_revision="rev-1", stage="STAGE_1",
                runner_class="SELF_HOSTED_CPU", purpose="SCREENING", requested_runs=1, requested_spend_usd=0.0, gpu=False, provider_inference=False,
                event_name="workflow_dispatch")
    base.update(over)
    return A.Request(**base)


# ------------------------------------------------------------ committed state
def test_committed_record_is_not_authorized_and_no_key_is_registered():
    rec = json.loads((ROOT / A.RECORD_PATH).read_text())
    assert rec == A.default_record() and rec["status"] == "NOT_AUTHORIZED" and rec["signature"] is None
    assert rec["gpu_allowed"] is False and rec["network_provider_inference_allowed"] is False and rec["max_runs"] == 0
    assert set(rec) == A.RECORD_KEYS
    from orca.eval.genesis_v2 import authority_registry as AR
    assert json.loads((ROOT / AR.REGISTRY_PATH).read_text())["records"] == []
    v = A.verify(rec, req(), A.load_keys(ROOT))
    assert not v.authorized and "NOT_AUTHORIZED" in v.reasons


def test_gate_script_denies_for_every_event_type_including_dispatch():
    for event in ("push", "pull_request", "schedule", "workflow_dispatch", ""):
        env = {**os.environ, "GITHUB_EVENT_NAME": event, "GITHUB_SHA": SHA, "EVAL_VERSION": "genesis-capability-eval/2.0.0", "CANDIDATE_MODEL_ID": "m",
               "CANDIDATE_REVISION": "r", "EVAL_STAGE": "STAGE_1", "RUNNER_CLASS": "SELF_HOSTED_CPU", "EVAL_PURPOSE": "SCREENING"}
        out = ROOT / f"_gate_out_{event or 'none'}.txt"
        env["GITHUB_OUTPUT"] = str(out)
        p = subprocess.run([sys.executable, "scripts/ci/verify_model_eval_authorization.py"], cwd=ROOT, env=env, capture_output=True, text=True)
        assert p.returncode == 1 and "DENIED" in p.stdout, (event, p.stdout, p.stderr)
        assert out.read_text().strip() == "authorized=false"
        out.unlink()


def test_gate_script_errors_deny(tmp_path):
    env = {**os.environ, "GITHUB_EVENT_NAME": "workflow_dispatch", "REQUESTED_RUNS": "not-an-int", "GITHUB_OUTPUT": str(tmp_path / "o")}
    p = subprocess.run([sys.executable, "scripts/ci/verify_model_eval_authorization.py"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert p.returncode == 1 and (tmp_path / "o").read_text().strip() == "authorized=false" and "GATE_ERROR" in p.stdout


# ------------------------------------------------------------ verification: positive path + every denial
def test_a_fully_exact_signed_record_authorizes(signer):
    make, keys = signer
    v = A.verify(make(), req(), keys, NOW)
    assert v.authorized and v.reasons == []


DENIALS = {
    "missing_record": (lambda make: None, {}, "RECORD_NOT_AN_OBJECT"),
    "string_record": (lambda make: "UNREADABLE", {}, "RECORD_NOT_AN_OBJECT"),
    "malformed_extra_key": (lambda make: {**make(), "extra": 1}, {}, "RECORD_SCHEMA_MISMATCH"),
    "malformed_missing_key": (lambda make: {k: v for k, v in make().items() if k != "max_runs"}, {}, "RECORD_SCHEMA_MISMATCH"),
    "status_not_authorized": (lambda make: make(status="NOT_AUTHORIZED"), {}, "NOT_AUTHORIZED"),
    "status_garbage": (lambda make: make(status="yes"), {}, "STATUS_INVALID"),
    "wrong_sha": (lambda make: make(), {"commit_sha": "b" * 40}, "WRONG_COMMIT_SHA"),
    "short_sha_in_record": (lambda make: make(commit_sha="aaaa"), {"commit_sha": "aaaa"}, "WRONG_COMMIT_SHA"),
    "wrong_eval_version": (lambda make: make(), {"eval_version": "genesis-capability-eval/1.0.0"}, "WRONG_EVAL_VERSION"),
    "wrong_candidate_model": (lambda make: make(), {"candidate_model_id": "other"}, "WRONG_CANDIDATE"),
    "wrong_candidate_revision": (lambda make: make(), {"candidate_revision": "rev-2"}, "WRONG_CANDIDATE"),
    "wrong_stage": (lambda make: make(), {"stage": "STAGE_2"}, "WRONG_STAGE"),
    "wrong_runner": (lambda make: make(), {"runner_class": "GITHUB_HOSTED_CPU"}, "WRONG_RUNNER_CLASS"),
    "wrong_purpose": (lambda make: make(), {"purpose": "QUALIFICATION"}, "WRONG_PURPOSE"),
    "too_many_runs": (lambda make: make(), {"requested_runs": 3}, "RUN_COUNT_NOT_AUTHORIZED"),
    "zero_runs_authorized": (lambda make: make(max_runs=0), {}, "RUN_COUNT_NOT_AUTHORIZED"),
    "bool_as_runs": (lambda make: make(max_runs=True), {}, "RUN_COUNT_NOT_AUTHORIZED"),
    "spend_exceeds": (lambda make: make(), {"requested_spend_usd": 1.0}, "SPEND_NOT_AUTHORIZED"),
    "expired": (lambda make: make(issued_at=ts(NOW - timedelta(days=3)), expires_at=ts(NOW - timedelta(days=1))), {}, "AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"),
    "not_yet_valid": (lambda make: make(issued_at=ts(NOW + timedelta(hours=1)), expires_at=ts(NOW + timedelta(days=1))), {}, "AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID"),
    "window_too_long": (lambda make: make(expires_at=ts(NOW + timedelta(days=90))), {}, "VALIDITY_WINDOW_TOO_LONG"),
    "bad_timestamp": (lambda make: make(issued_at="yesterday"), {}, "TIMESTAMP_INVALID"),
    "gpu_not_allowed": (lambda make: make(), {"gpu": True}, "GPU_NOT_AUTHORIZED"),
    "gpu_flag_but_cpu_runner": (lambda make: make(gpu_allowed=True), {"gpu": True}, "GPU_NOT_AUTHORIZED"),
    "gpu_runner_without_permission": (lambda make: make(permitted_runner_class="SELF_HOSTED_GPU"), {"runner_class": "SELF_HOSTED_GPU"}, "GPU_RUNNER_WITHOUT_GPU_PERMISSION"),
    "provider_inference_not_allowed": (lambda make: make(), {"provider_inference": True}, "PROVIDER_INFERENCE_NOT_AUTHORIZED"),
    "flags_not_bool": (lambda make: make(gpu_allowed="true"), {}, "PERMISSION_FLAGS_INVALID"),
    "bad_authority_role": (lambda make: make(authorizing_authority={"identity": "owner@example.invalid", "role": "CLAUDE", "key_id": "k-test"}), {}, "AUTHORITY_INVALID"),
    "bad_authorization_id": (lambda make: make(authorization_id="whatever"), {}, "AUTHORIZATION_ID_INVALID"),
    "push_event": (lambda make: make(), {"event_name": "push"}, "EVENT_NOT_EXPLICIT_DISPATCH"),
    "pull_request_event": (lambda make: make(), {"event_name": "pull_request"}, "EVENT_NOT_EXPLICIT_DISPATCH"),
    "schedule_event": (lambda make: make(), {"event_name": "schedule"}, "EVENT_NOT_EXPLICIT_DISPATCH"),
}


@pytest.mark.parametrize("name", sorted(DENIALS))
def test_every_deviation_denies_with_its_reason(signer, name):
    make, keys = signer
    build, over, reason = DENIALS[name]
    v = A.verify(build(make), req(**over), keys, NOW)
    assert not v.authorized and reason in v.reasons, (name, v.reasons)


def test_signature_and_key_registry_are_enforced(signer):
    make, keys = signer
    good = make()
    assert not A.verify({**good, "signature": "00" * 64}, req(), keys, NOW).authorized                       # forged signature
    assert "SIGNATURE_INVALID" in A.verify({**good, "signature": "zz"}, req(), keys, NOW).reasons
    tampered = {**good, "max_runs": 5}                                                                       # edited after signing
    assert "SIGNATURE_INVALID" in A.verify(tampered, req(), keys, NOW).reasons
    assert "NO_TRUSTED_AUTHORITY_KEY_REGISTERED" in A.verify(good, req(), [], NOW).reasons                  # empty registry => nothing authorized
    assert "AUTHORITY_KEY_NOT_REGISTERED" in A.verify(good, req(), [{**keys[0], "key_id": "other"}], NOW).reasons
    assert "AUTHORITY_IDENTITY_MISMATCH" in A.verify(good, req(), [{**keys[0], "identity": "someone@else.invalid"}], NOW).reasons
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    other = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    assert "SIGNATURE_INVALID" in A.verify(good, req(), [{**keys[0], "public_key_hex": other}], NOW).reasons  # signed by a different key


def test_unreadable_key_registry_means_no_authority(tmp_path):
    from orca.eval.genesis_v2 import authority_registry as AR
    assert A.load_keys(tmp_path) == []
    (tmp_path / "docs/orneur/authorization").mkdir(parents=True)
    (tmp_path / AR.REGISTRY_PATH).write_text("not json")
    assert A.load_keys(tmp_path) == []
    (tmp_path / AR.REGISTRY_PATH).write_text('{"schema_version": "genesis-v2-authority-registry/1", "records": "nope"}')
    assert A.load_keys(tmp_path) == []
    assert A.load_record(tmp_path) == "UNREADABLE"


# ------------------------------------------------------------ workflow boundary
def _wf(p):
    d = yaml.safe_load(p.read_text())
    return d, (d.get(True) or d.get("on") or {})


FORBIDDEN_IN_STATIC = re.compile(r"ollama|orca\s+train\s+(eval|redteam|regression|card|run|cloud)|orca\s+data\s+(seed|distill)|\bdistill\b|self-hosted", re.I)


def _exec_text(job) -> str:
    """Only what a job EXECUTES or runs on (commands, actions, runner labels) — not names, comments or descriptions."""
    parts = [str(job.get("runs-on"))]
    for s in job.get("steps", []):
        parts += [str(s.get("run", "")), str(s.get("uses", "")), str(s.get("with", "")), str(s.get("env", ""))]
    return "\n".join(parts)


def test_no_workflow_runs_a_model_on_push_pull_request_or_schedule():
    for p in sorted(WF.glob("*.yml")):
        d, on = _wf(p)
        triggers = set(on) if isinstance(on, dict) else {on}
        auto = triggers & {"push", "pull_request", "pull_request_target", "schedule", "workflow_run", "release", "create", "issue_comment"}
        if auto:
            for name, j in d["jobs"].items():
                assert not FORBIDDEN_IN_STATIC.search(_exec_text(j)), f"{p.name}:{name}: auto-triggered job contains model-invocation or self-hosted references"


def test_eval_workflow_is_dispatch_only_and_the_model_job_is_gated():
    d, on = _wf(WF / "eval.yml")
    assert set(on) == {"workflow_dispatch"}
    jobs = d["jobs"]
    assert jobs["authorize"]["runs-on"] == "ubuntu-latest" and "self-hosted" not in str(jobs["authorize"])
    ev = jobs["eval"]
    assert ev["needs"] == "authorize" and "needs.authorize.outputs.authorized == 'true'" in ev["if"] and "workflow_dispatch" in ev["if"]
    assert "verify_model_eval_authorization.py" in (WF / "eval.yml").read_text()
    assert not {"push", "pull_request", "pull_request_target", "schedule"} & set(on)                          # no automatic trigger keys at all


def test_seed_workflow_has_the_same_gate():
    d, on = _wf(WF / "seed.yml")
    assert set(on) == {"workflow_dispatch"} and d["jobs"]["seed"]["needs"] == "authorize"
    assert "authorized == 'true'" in d["jobs"]["seed"]["if"] and d["jobs"]["authorize"]["runs-on"] == "ubuntu-latest"


def test_every_ollama_or_self_hosted_job_anywhere_needs_the_gate():
    for p in sorted(WF.glob("*.yml")):
        d, on = _wf(p)
        for name, j in d["jobs"].items():
            if "self-hosted" in str(j.get("runs-on")) or re.search(r"ollama", _exec_text(j), re.I):
                assert set(on) == {"workflow_dispatch"}, (p.name, name)
                assert j.get("needs") == "authorize" and "authorized == 'true'" in str(j.get("if")), (p.name, name)


def test_static_checks_workflow_is_cpu_only_and_functional():
    d, on = _wf(WF / "eval-static-checks.yml")
    assert set(on) == {"push", "pull_request"}
    job = d["jobs"]["static-data-check"]
    assert job["runs-on"] == "ubuntu-latest"
    assert not FORBIDDEN_IN_STATIC.search(_exec_text(job))
    runs = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert "pytest -q tests/test_genesis_v2_authorization.py" in runs and "orca train prepare" in runs
    # the static command itself is genuinely model-free and still works: it reads local files only
    from orca.train import prepare
    import ast
    tree = ast.parse(Path(prepare.__file__).read_text())
    imported = {n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert not imported & {"requests", "httpx", "urllib", "openai", "subprocess", "ollama", "socket", "aiohttp", "anthropic"}, imported


def test_model_executing_cli_commands_are_only_reachable_from_the_gated_workflows():
    hits = {}
    for p in sorted(WF.glob("*.yml")):
        t = p.read_text()
        if re.search(r"orca\s+train\s+(eval|redteam|regression)|orca\s+data\s+seed|ollama\s+pull", t):
            hits[p.name] = True
    assert set(hits) == {"eval.yml", "seed.yml"}
