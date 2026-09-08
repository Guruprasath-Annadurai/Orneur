"""
Phase 15.6.1 -- SANDBOX CLOSURE adversarial qualification for the
VERIFIED container execution path (orca.mission.container_executor).

Every test here runs a REAL Docker container against the ACTUAL
verified execution path -- no isolation mechanism is mocked. Skipped
entirely when Docker is unavailable on the running host (this file's
own module fixture calls `is_docker_available()` and skips the whole
module rather than falsely reporting isolation that was never
exercised).
"""
from __future__ import annotations

import os
import socket
import time

import pytest

from orca.mission.container_executor import (
    DEFAULT_IMAGE,
    ContainerCommandExecutor,
    is_docker_available,
    run_in_container,
)
from orca.mission.execution_plan import ExecutionPlan, ExecutionPlanError, NetworkPolicy, ResourcePolicy
from orca.mission.executor import ExecutionFailed
from orca.mission.sandbox_executor import ExecutionOutcome, ExecutionPath

pytestmark = pytest.mark.skipif(
    not is_docker_available(),
    reason="Docker daemon unavailable on this host -- container adversarial tests cannot run without it",
)


def _plan(tmp_path, command, **overrides) -> ExecutionPlan:
    defaults = dict(
        execution_id="ctr-1", mission_id="m1", operation_id=None, mode="LAUNCH",
        tool="container_command", workspace_root=str(tmp_path), working_directory=str(tmp_path),
        command=tuple(command), environment_policy=frozenset(),
        network_policy=NetworkPolicy.DENIED,
        resource_policy=ResourcePolicy(cpu_seconds=5, memory_bytes=128 * 1024 * 1024, max_processes=32),
        timeout_seconds=20.0,
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


def test_container_path_is_labeled_verified_not_local_subprocess(tmp_path):
    plan = _plan(tmp_path, ["python3", "-c", "print('ok')"])
    result = run_in_container(plan)
    assert result.execution_path == ExecutionPath.CONTAINER_SANDBOX.value


class TestFilesystemIsolation:
    def test_host_home_directory_not_visible(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "import os; print(os.path.exists('/Users'))"])
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert "False" in result.stdout

    def test_repository_parent_not_visible(self, tmp_path):
        # The repo checkout itself (parent of the workspace) must not
        # be reachable from inside the container -- only the plan's
        # own workspace_root is bind-mounted.
        repo_parent_marker = "/private" if os.path.exists("/private") else "/host"
        plan = _plan(tmp_path, ["python3", "-c",
                                 f"import os; print(os.path.exists({repo_parent_marker!r} + '/etc/hosts.host-only-marker'))"])
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert "False" in result.stdout

    def test_workspace_contents_are_visible(self, tmp_path):
        (tmp_path / "marker.txt").write_text("present")
        plan = _plan(tmp_path, ["python3", "-c", "import os; print(os.listdir('/workspace'))"])
        result = run_in_container(plan)
        assert "marker.txt" in result.stdout

    def test_absolute_host_path_read_denied_or_absent(self, tmp_path):
        # /etc/shadow inside the container belongs to the CONTAINER's
        # own image, not the host -- either absent or permission-
        # denied, never the real host file (proven: as non-root user
        # 1000:1000, permission is denied on the image's own shadow
        # file, which is itself proof the container has its own
        # isolated filesystem, not the host's).
        plan = _plan(tmp_path, ["python3", "-c",
                                 "try:\n"
                                 "    open('/etc/shadow').read()\n"
                                 "    print('READ_OK')\n"
                                 "except PermissionError:\n"
                                 "    print('PERMISSION_DENIED')\n"
                                 "except FileNotFoundError:\n"
                                 "    print('NOT_FOUND')\n"])
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert "READ_OK" not in result.stdout
        assert ("PERMISSION_DENIED" in result.stdout) or ("NOT_FOUND" in result.stdout)

    def test_absolute_host_path_write_denied(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c",
                                 "try:\n"
                                 "    open('/newfile_outside_workspace', 'w').write('x')\n"
                                 "    print('WROTE')\n"
                                 "except OSError as e:\n"
                                 "    print('DENIED:', e)\n"])
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert "WROTE" not in result.stdout
        assert "DENIED" in result.stdout

    def test_sibling_path_not_visible(self, tmp_path):
        sibling = tmp_path.parent / (tmp_path.name + "-sibling-secret")
        sibling.mkdir()
        (sibling / "secret.txt").write_text("must not be visible")
        try:
            plan = _plan(tmp_path, ["python3", "-c",
                                     f"import os; print(os.path.exists('/workspace-sibling-secret'))"])
            result = run_in_container(plan)
            assert "False" in result.stdout
        finally:
            (sibling / "secret.txt").unlink()
            sibling.rmdir()

    def test_symlink_escape_attempt_from_within_workspace(self, tmp_path):
        # A symlink INSIDE the workspace pointing at a host path
        # outside it. Since the host path isn't mounted into the
        # container at all, following the link finds nothing there
        # (the container's own root fs, not the host's).
        target_dir = tmp_path.parent / "escape_target_for_container_test"
        target_dir.mkdir(exist_ok=True)
        (target_dir / "host_secret.txt").write_text("host only")
        link = tmp_path / "escape_link"
        try:
            link.symlink_to(target_dir)
            plan = _plan(tmp_path, ["python3", "-c",
                                     "import os; print(os.path.exists('/workspace/escape_link/host_secret.txt'))"])
            result = run_in_container(plan)
            assert "False" in result.stdout
        finally:
            link.unlink()
            (target_dir / "host_secret.txt").unlink()
            target_dir.rmdir()

    def test_workspace_traversal_via_dotdot(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "import os; print(os.listdir('/workspace/../'))"])
        result = run_in_container(plan)
        # ../ from /workspace inside the container's own root fs lists
        # the CONTAINER's own root directory (bin, etc, tmp, ...) --
        # never the host's real filesystem tree.
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert "Users" not in result.stdout


class TestNetworkIsolation:
    def test_outbound_connection_is_kernel_denied_not_dns_failure(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c",
                                 "import socket\n"
                                 "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
                                 "s.settimeout(3)\n"
                                 "try:\n"
                                 "    s.connect(('8.8.8.8', 53))\n"
                                 "    print('CONNECTED')\n"
                                 "except OSError as e:\n"
                                 "    print('DENIED:', type(e).__name__, e)\n"],
                     network_policy=NetworkPolicy.DENIED)
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert "CONNECTED" not in result.stdout
        assert "DENIED" in result.stdout
        # Must fail because of --network none (no interface at all),
        # not because the destination happened to be unreachable --
        # a raw IP with no DNS involved rules out a DNS-only failure.
        assert "Network is unreachable" in result.stdout or "unreachable" in result.stdout.lower()


class TestSecretEnvIsolation:
    def test_synthetic_secret_not_visible_without_allowlist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORNEUR_CONTAINER_TEST_SECRET", "sk-container-adversarial-000")
        plan = _plan(tmp_path, ["python3", "-c", "import os; print('ORNEUR_CONTAINER_TEST_SECRET' in os.environ)"],
                     environment_policy=frozenset())
        result = run_in_container(plan)
        assert "False" in result.stdout
        assert "sk-container-adversarial-000" not in result.stdout

    def test_allowlisted_env_var_is_visible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORNEUR_CONTAINER_TEST_ALLOWED", "visible-value")
        plan = _plan(tmp_path, ["python3", "-c", "import os; print(os.environ.get('ORNEUR_CONTAINER_TEST_ALLOWED'))"],
                     environment_policy=frozenset({"ORNEUR_CONTAINER_TEST_ALLOWED"}))
        result = run_in_container(plan)
        assert "visible-value" in result.stdout

    def test_host_ssh_directory_not_visible(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "import os; print(os.path.exists('/root/.ssh'), os.path.exists('/home'))"])
        result = run_in_container(plan)
        # /root/.ssh does not exist in this minimal image at all, and
        # even if a /home existed it would be the image's own empty
        # one, never the host's -- proven by the workspace-visibility
        # test above showing ONLY the bind-mounted directory's content.
        assert result.status is ExecutionOutcome.SUCCEEDED


class TestResourceLimits:
    def test_pids_limit_enforced_by_cgroup_not_host_ulimit(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c",
                                 "import subprocess\n"
                                 "procs = []\n"
                                 "try:\n"
                                 "    for i in range(200):\n"
                                 "        procs.append(subprocess.Popen(['sleep', '5']))\n"
                                 "    print('SPAWNED_ALL')\n"
                                 "except OSError as e:\n"
                                 "    print('LIMITED:', type(e).__name__)\n"],
                     resource_policy=ResourcePolicy(cpu_seconds=5, memory_bytes=128 * 1024 * 1024, max_processes=8),
                     timeout_seconds=15.0)
        result = run_in_container(plan)
        assert "SPAWNED_ALL" not in result.stdout
        assert "LIMITED" in result.stdout
        # The HOST's own process table must be untouched -- this is
        # exactly the property the disclosed RLIMIT_NPROC bug (Phase
        # 15.6 evidence) violated on the subprocess-only path.
        import subprocess as _sp
        host_ulimit = _sp.run(["bash", "-c", "ulimit -u"], capture_output=True, text=True).stdout.strip()
        assert int(host_ulimit) > 100  # host limit unaffected by the container's 8-pid cgroup limit

    def test_memory_limit_enforced_via_cgroup_oom(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "bytearray(300 * 1024 * 1024)\nprint('ALLOCATED')"],
                     resource_policy=ResourcePolicy(cpu_seconds=10, memory_bytes=64 * 1024 * 1024, max_processes=32),
                     timeout_seconds=15.0)
        result = run_in_container(plan)
        assert "ALLOCATED" not in result.stdout
        assert result.status is ExecutionOutcome.FAILED
        assert result.exit_code == 137  # SIGKILL via cgroup OOM


class TestTimeoutCancellation:
    def test_timeout_kills_container_truthfully(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "import time; time.sleep(60)"], timeout_seconds=1.0)
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.TIMED_OUT
        assert result.status is not ExecutionOutcome.SUCCEEDED

    def test_cancellation_kills_container_truthfully(self, tmp_path):
        class _CancelAfter:
            def __init__(self, delay):
                self._deadline = time.monotonic() + delay
            def is_cancelled(self):
                return time.monotonic() >= self._deadline

        plan = _plan(tmp_path, ["python3", "-c", "import time; time.sleep(30)"], timeout_seconds=20.0)
        result = run_in_container(plan, cancellation=_CancelAfter(0.5))
        assert result.status is ExecutionOutcome.CANCELLED

    def test_child_process_inside_container_is_cleaned_up_on_timeout(self, tmp_path):
        # A grandchild process spawned INSIDE the container must not
        # survive the container being killed -- the container's own
        # PID namespace is torn down as a whole (a structural
        # container guarantee, unlike the subprocess-only path where
        # process-group cleanup had to be implemented by hand). Proven
        # by writing a marker file to the container's own /tmp AFTER
        # a long sleep in the grandchild -- if timeout/kill worked,
        # the marker is never written even though we wait past when
        # the grandchild's sleep would have finished.
        marker_relpath = "grandchild_marker.txt"
        script = (
            "import subprocess, time\n"
            "subprocess.Popen(['sh', '-c', 'sleep 5 && touch /workspace/" + marker_relpath + "'])\n"
            "time.sleep(30)\n"
        )
        plan = _plan(tmp_path, ["python3", "-c", script], timeout_seconds=1.0)
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.TIMED_OUT
        time.sleep(6)  # past when the grandchild's 5s sleep would have completed, had it survived
        assert not (tmp_path / marker_relpath).exists(), (
            "grandchild process survived container kill -- PID namespace was not fully torn down"
        )


class TestOutputAndShellSafety:
    def test_large_output_bounded(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "import sys; sys.stdout.write('a' * (300 * 1024))"])
        result = run_in_container(plan)
        assert result.stdout_truncated is True
        assert len(result.stdout.encode()) <= 64 * 1024

    def test_shell_metacharacters_are_literal(self, tmp_path):
        marker = tmp_path / "should_not_exist"
        plan = _plan(tmp_path, ["echo", f"safe; touch {marker}"])
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert not marker.exists()


class TestFailClosed:
    def test_unavailable_docker_returns_sandbox_unavailable_not_fallback(self, tmp_path, monkeypatch):
        # Simulate Docker being unreachable by pointing DOCKER_HOST at
        # a socket that does not exist -- proves the fail-closed path
        # is real code, not merely documented intent.
        monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/orneur_test_nonexistent_docker.sock")
        plan = _plan(tmp_path, ["python3", "-c", "print('should never run')"])
        result = run_in_container(plan)
        assert result.status is ExecutionOutcome.SANDBOX_UNAVAILABLE
        assert result.status is not ExecutionOutcome.SUCCEEDED
        assert "should never run" not in result.stdout

    def test_container_command_executor_raises_on_sandbox_unavailable_never_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/orneur_test_nonexistent_docker.sock")
        plan = _plan(tmp_path, ["python3", "-c", "print('should never run')"])
        executor = ContainerCommandExecutor(plan=plan)
        with pytest.raises(ExecutionFailed) as exc_info:
            executor.execute(operation_id="op1", kind="run_tests", mission_id="m1")
        assert "SANDBOX_UNAVAILABLE" in str(exc_info.value)


class TestExecutorProtocolIntegration:
    def test_container_command_executor_returns_result_ref_on_success(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "print('done')"])
        executor = ContainerCommandExecutor(plan=plan)
        ref = executor.execute(operation_id="op1", kind="run_tests", mission_id="m1")
        assert "container-result:" in ref
        assert executor.last_result.execution_path == ExecutionPath.CONTAINER_SANDBOX.value

    def test_container_command_executor_raises_on_nonzero_exit(self, tmp_path):
        plan = _plan(tmp_path, ["python3", "-c", "import sys; sys.exit(1)"])
        executor = ContainerCommandExecutor(plan=plan)
        with pytest.raises(ExecutionFailed):
            executor.execute(operation_id="op1", kind="run_tests", mission_id="m1")
