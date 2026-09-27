"""Sandbox POLICY tests (pure: no Docker needed). Containment itself is proven in test_genesis_v2_sandbox_containment.py (mandatory sandbox CI job)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import sandbox as SB

ROOT = Path(__file__).resolve().parents[1]
POL = SB.SandboxPolicy()
JOB = SB.SandboxJob("gce2-" + "a" * 24, "rev-1", {"main.py": b"print(1)"}, ("python3", "-I", "/job/main.py"))


def args(policy=POL, job=JOB, d=Path("/tmp/jobdir")):
    return SB.build_docker_args(policy, job, d, "gce2-sbx-test")


def pairs(a):
    return {a[i]: a[i + 1] for i in range(len(a) - 1)}


def test_docker_args_carry_every_hardening_flag():
    a = args()
    s = " ".join(a)
    p = pairs(a)
    assert a[:2] == ["docker", "run"] and p["--network"] == "none" and "--read-only" in a and p["--cap-drop"] == "ALL"
    assert p["--security-opt"] == "no-new-privileges" and p["--user"] == "65534:65534" and p["--pull"] == "never" and p["--ipc"] == "private"
    assert p["--pids-limit"] == "32" and p["--memory"] == "256m" and p["--memory-swap"] == "256m" and p["--cpus"] == "1"
    for u in ("nofile=64:64", "nproc=32:32", "fsize=4194304:4194304", "cpu=8:8", "core=0:0"):
        assert f"--ulimit {u}" in s, u
    assert f"--mount type=bind,source=/tmp/jobdir,target=/job,readonly" in s
    assert "--tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m" in s and "--tmpfs /work:rw,noexec,nosuid,nodev,size=16m" in s
    assert p["--workdir"] == "/work" and p["--label"] == SB.LABEL
    i = a.index("python:3.11-slim")
    assert a[i + 1:i + 3] == ["/usr/bin/env", "-i"] and a[-3:] == ["python3", "-I", "/job/main.py"]
    assert "--env" not in a and "--env-file" not in a                                   # environment is set only via `env -i` inside the container


def test_docker_args_never_contain_forbidden_capabilities():
    s = " ".join(args())
    for bad in ("--privileged", "--pid host", "--pid=host", "--network host", "--network=host", "--net host", "--ipc host", "docker.sock", "--cap-add",
                "--device", "--security-opt seccomp=unconfined", "--security-opt apparmor=unconfined", "--userns host", "--volumes-from", "-v ", "--publish",
                "-p ", "--env-file", "--group-add", "--user root", "--user 0", "--mount type=bind,source=/,", "/var/run", "--add-host"):
        assert bad not in s, bad
    mounts = [x for x in args() if x.startswith("type=bind")]
    assert len(mounts) == 1 and mounts[0].endswith("readonly")                     # the ONLY host path, read-only


def test_environment_is_an_explicit_allow_list_and_never_inherited(monkeypatch):
    monkeypatch.setenv("ORNEUR_TEST_SECRET_TOKEN", "sekrit-value")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-fake")
    a = args()
    i = a.index("-i", a.index("/usr/bin/env"))
    envs = {x.split("=", 1)[0] for x in a[i + 1:] if "=" in x and not x.startswith("/")}
    assert envs == {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "PYTHONNOUSERSITE"}
    assert "sekrit-value" not in " ".join(a) and "ghp_fake" not in " ".join(a) and "aws-fake" not in " ".join(a)
    he = SB._host_env()
    assert "ORNEUR_TEST_SECRET_TOKEN" not in he and "GITHUB_TOKEN" not in he and "AWS_SECRET_ACCESS_KEY" not in he
    assert "TZ=UTC" in " ".join(a) and "LANG=C.UTF-8" in " ".join(a) and "PYTHONHASHSEED=0" in " ".join(a)


@pytest.mark.parametrize("key", ["AWS_SECRET", "GITHUB_TOKEN", "ORNEUR_X", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DOCKER_HOST", "PATH", "bad-key", "A B"])
def test_illegal_extra_env_rejected(key):
    job = SB.SandboxJob("i", "r", {"a": b"x"}, ("python3", "-c", "pass"), {key: "v"})
    with pytest.raises(SB.SandboxPolicyViolation):
        args(job=job)


@pytest.mark.parametrize("bad", ["../evil", "a/../../evil", "/abs/path", "", "a//b", "./a", "a/./b", "a\\b", "x\x00y", "a/", "a" * 300, "../", ".."])
def test_path_traversal_and_illegal_paths_are_refused(tmp_path, bad):
    root = tmp_path / "jobroot"
    root.mkdir()
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.stage_files({bad: b"x"}, root)
    assert list(root.iterdir()) == []
    assert not (tmp_path / "evil").exists() and not Path("/abs/path").exists()


def test_staging_limits_and_types(tmp_path):
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.stage_files({f"f{i}": b"x" for i in range(SB.MAX_FILES + 1)}, tmp_path)
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.stage_files({"big": b"x" * (SB.MAX_FILE_BYTES + 1)}, tmp_path)
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.stage_files({f"f{i}": b"x" * SB.MAX_FILE_BYTES for i in range(3)}, tmp_path)
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.stage_files({"s": "not-bytes"}, tmp_path)
    SB.stage_files({"a/b/c.py": b"print(1)", "d.txt": b"x"}, tmp_path)
    assert (tmp_path / "a/b/c.py").read_bytes() == b"print(1)" and oct((tmp_path / "a/b/c.py").stat().st_mode & 0o777) == "0o444"
    assert not any(p.is_symlink() for p in tmp_path.rglob("*"))


def test_staging_refuses_existing_symlinked_directory(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(victim, root / "link")
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.stage_files({"link/x.py": b"x"}, root)
    assert list(victim.iterdir()) == []                                              # nothing escaped through the symlink


def test_symlink_hardlink_and_escape_in_fixture_trees_refused(tmp_path):
    secret = tmp_path / "host_secret.txt"
    secret.write_text("host secret")
    tree = tmp_path / "fx"
    tree.mkdir()
    (tree / "ok.txt").write_text("fine")
    assert SB.load_fixture_tree(tree) == {"ok.txt": b"fine"}
    os.symlink(secret, tree / "link.txt")
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.load_fixture_tree(tree)
    os.unlink(tree / "link.txt")
    os.symlink(tmp_path, tree / "dirlink")
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.load_fixture_tree(tree)
    os.unlink(tree / "dirlink")
    os.link(secret, tree / "hard.txt")
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.load_fixture_tree(tree)
    os.unlink(tree / "hard.txt")
    (tmp_path / "rootlink").symlink_to(tree)
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.load_fixture_tree(tmp_path / "rootlink")                                   # the root itself may not be a symlink
    os.mkfifo(tree / "fifo")
    with pytest.raises(SB.SandboxPolicyViolation):
        SB.load_fixture_tree(tree)


@pytest.mark.parametrize("over", [dict(network="bridge"), dict(network="host"), dict(user="0:0"), dict(user="root"), dict(runtime="python2"), dict(pids=0),
                                  dict(pids=100000), dict(wall_seconds=0), dict(wall_seconds=3600), dict(max_output_bytes=10 ** 9),
                                  dict(allow_dependencies=("numpy",)), dict(cpus="0"), dict(require_pinned_digest=True)])
def test_weak_policies_are_rejected(over):
    with pytest.raises(SB.SandboxPolicyViolation):
        args(policy=SB.SandboxPolicy(**over))


def test_qualification_mode_requires_a_digest_pinned_image():
    pinned = SB.SandboxPolicy(image="python@sha256:" + "a" * 64, require_pinned_digest=True)
    assert not pinned.problems()
    assert SB.SandboxPolicy(require_pinned_digest=True).problems()


def test_command_must_be_a_nonempty_string_argv():
    for bad in ((), ("",), ("python3", 1)):
        with pytest.raises(SB.SandboxPolicyViolation):
            args(job=SB.SandboxJob("i", "r", {"a": b"x"}, bad))


def test_execution_record_schema_is_content_free_and_complete():
    fields = set(SB.ExecutionRecord.__dataclass_fields__)
    assert fields == {"item_id", "candidate_revision", "sandbox_image_digest", "command", "exit_status", "timed_out", "resource_limit_status", "stdout_sha256",
                      "stderr_sha256", "stdout_bytes", "stderr_bytes", "test_result_digest", "duration_seconds", "sandbox_policy_version"}
    assert not fields & {"stdout", "stderr", "code", "prompt", "answer", "files"}
    m = SB.policy_manifest()
    assert m["network"] == "none" and m["policy_version"] == SB.POLICY_VERSION and "docker socket" in m["forbidden"]


def test_run_job_refuses_without_docker_instead_of_falling_back(monkeypatch):
    monkeypatch.setattr(SB, "is_docker_available", lambda: False)
    with pytest.raises(SB.SandboxUnavailable):
        SB.run_job(JOB)


def test_sandbox_ready_is_not_claimed_by_interfaces_alone():
    st = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["freeze_prerequisites"]["sandbox_ready"] is False
    assert st["component_states"]["coding_sandbox"] in ("IMPLEMENTED", "IMPLEMENTED_TESTED")
    assert st["sandbox_readiness"]["sandbox_ready"] is False and "digest" in st["sandbox_readiness"]["why_not_ready"]
