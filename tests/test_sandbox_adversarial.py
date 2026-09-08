"""
Phase 15.6 -- adversarial sandbox boundary tests (spec section 25).

Records exactly what IS enforced (path-controlled write/delete tool
actions, cwd containment, argv-safety, output bounds, timeout,
cancellation) and exactly what is a disclosed LIMITATION of this V1
subprocess-level boundary (an arbitrary command's own use of absolute
paths, real network egress, resource limits on macOS specifically).
Nothing here is marked PASS for a control that was not actually
observed to hold.
"""
from __future__ import annotations

import os
import socket
import sys

import pytest

from orca.mission.execution_plan import ExecutionPlan, NetworkPolicy, ResourcePolicy
from orca.mission.sandbox_executor import (
    ExecutionOutcome,
    WorkspaceEscapeError,
    delete_file_in_workspace,
    run_command,
    write_file_in_workspace,
)


def _plan(tmp_path, command, **overrides) -> ExecutionPlan:
    defaults = dict(
        execution_id="adv-1", mission_id="m1", operation_id=None, mode="PROTOTYPE",
        tool="sandbox_command", workspace_root=str(tmp_path), working_directory=str(tmp_path),
        command=tuple(command), environment_policy=frozenset(),
        network_policy=NetworkPolicy.DENIED,
        resource_policy=ResourcePolicy(cpu_seconds=5, memory_bytes=256 * 1024 * 1024, max_processes=None),
        timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


# ── ENFORCED: path-controlled write/delete tool actions ────────────

def test_enforced_write_file_traversal_rejected(tmp_path):
    with pytest.raises(WorkspaceEscapeError):
        write_file_in_workspace(str(tmp_path), "../escaped.txt", b"pwned")
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_enforced_write_file_absolute_outside_rejected(tmp_path):
    with pytest.raises(WorkspaceEscapeError):
        write_file_in_workspace(str(tmp_path), "/tmp/orneur_adversarial_should_not_exist.txt", b"pwned")


def test_enforced_delete_file_traversal_rejected(tmp_path):
    victim = tmp_path.parent / "must_survive.txt"
    victim.write_text("safe")
    try:
        with pytest.raises(WorkspaceEscapeError):
            delete_file_in_workspace(str(tmp_path), "../must_survive.txt")
        assert victim.exists()
    finally:
        victim.unlink()


def test_enforced_write_file_inside_workspace_succeeds(tmp_path):
    target = write_file_in_workspace(str(tmp_path), "ok.txt", b"fine")
    assert target.read_bytes() == b"fine"


# ── ENFORCED: cwd containment for command execution ─────────────────

def test_enforced_cwd_traversal_rejected(tmp_path):
    plan = _plan(tmp_path, [sys.executable, "-c", "print('x')"], working_directory="../")
    result = run_command(plan)
    assert result.status is ExecutionOutcome.FAILED
    assert "outside workspace root" in result.stderr


# ── ENFORCED: argv safety ───────────────────────────────────────────

def test_enforced_shell_metacharacters_do_not_execute(tmp_path):
    marker = tmp_path / "pwned"
    plan = _plan(tmp_path, ["echo", f"$(touch {marker})", f"; touch {marker}", f"| touch {marker}"])
    result = run_command(plan)
    assert result.status is ExecutionOutcome.SUCCEEDED
    assert not marker.exists()


# ── ENFORCED: bounded output ─────────────────────────────────────────

def test_enforced_large_stdout_bounded(tmp_path):
    plan = _plan(tmp_path, [sys.executable, "-c", "import sys; sys.stdout.write('a' * (500*1024))"])
    result = run_command(plan)
    assert result.stdout_truncated is True
    assert len(result.stdout.encode()) <= 64 * 1024


# ── ENFORCED: long-running process is bounded by timeout ────────────

def test_enforced_long_running_process_times_out(tmp_path):
    plan = _plan(tmp_path, [sys.executable, "-c", "import time; time.sleep(60)"], timeout_seconds=0.5)
    result = run_command(plan)
    assert result.status is ExecutionOutcome.TIMED_OUT


# ── ENFORCED: child-process cleanup (no orphan survives timeout) ────

@pytest.mark.skipif(os.name != "posix", reason="process-group cleanup is POSIX-specific")
def test_enforced_child_process_group_is_killed_on_timeout(tmp_path):
    # Parent spawns a grandchild via `sh -c`; on timeout the whole
    # process group must die, not just the immediate child.
    marker = tmp_path / "grandchild_alive"
    script = (
        f"import subprocess, time, sys; "
        f"subprocess.Popen(['sh', '-c', 'sleep 30; touch {marker}']); "
        f"time.sleep(30)"
    )
    plan = _plan(tmp_path, [sys.executable, "-c", script], timeout_seconds=0.5)
    result = run_command(plan)
    assert result.status is ExecutionOutcome.TIMED_OUT
    import time as _time
    _time.sleep(1.0)  # give the (should-be-dead) grandchild a moment it does NOT get to use
    assert not marker.exists(), "grandchild survived timeout -- orphan process leaked"


# ── ENFORCED: environment dump does not include unlisted secrets ────

def test_enforced_environment_dump_excludes_unlisted_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("ORNEUR_ADVERSARIAL_SECRET", "sk-adversarial-000")
    plan = _plan(tmp_path, [sys.executable, "-c", "import os; [print(k) for k in os.environ]"],
                 environment_policy=frozenset())
    result = run_command(plan)
    assert "ORNEUR_ADVERSARIAL_SECRET" not in result.stdout


# ── DISCLOSED LIMITATION: arbitrary command can use absolute paths ──

def test_limitation_arbitrary_command_can_write_outside_workspace_via_absolute_path(tmp_path):
    """
    HONEST LIMITATION (see orca/mission/sandbox_executor.py module
    docstring): this V1 boundary validates the ExecutionPlan's OWN
    working_directory and the path-controlled write/delete tool
    actions above. It does NOT namespace-isolate the filesystem for
    an arbitrary subprocess that itself issues an absolute-path
    syscall -- that requires container/chroot-level isolation, which
    this phase does not implement (spec section 5 explicitly permits
    disclosing this rather than claiming an unenforced control). This
    test PROVES the limitation exists on this host rather than
    asserting it from confidence.
    """
    outside_file = tmp_path.parent / "orneur_adversarial_absolute_write.txt"
    plan = _plan(tmp_path, [sys.executable, "-c", f"open({str(outside_file)!r}, 'w').write('escaped')"])
    try:
        result = run_command(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert outside_file.exists(), (
            "expected-limitation write outside workspace did NOT occur -- "
            "if this assertion fails, the documented limitation claim is stale and must be corrected"
        )
    finally:
        if outside_file.exists():
            outside_file.unlink()


# ── DISCLOSED LIMITATION / truthful network semantics ────────────────

def test_network_policy_denied_is_not_kernel_enforced_on_this_v1_path(tmp_path):
    """
    HONEST NETWORK SEMANTICS (spec section 8): NetworkPolicy.DENIED on
    this V1 subprocess boundary means "no credentials/proxy config are
    provided and this adapter does not itself make outbound requests"
    -- it is NOT a kernel-level network-namespace denial. This test
    proves that on this host, a subprocess CAN still open a raw local
    socket connection, so the DENIED label is never mis-sold as an
    enforced kernel boundary. A real listener on localhost is used
    (harmless, no external network egress) so this test is
    deterministic and does not depend on internet access.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        script = (
            f"import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); "
            f"s.settimeout(2); s.connect(('127.0.0.1', {port})); print('CONNECTED')"
        )
        plan = _plan(tmp_path, [sys.executable, "-c", script], network_policy=NetworkPolicy.DENIED)
        result = run_command(plan)
        assert result.status is ExecutionOutcome.SUCCEEDED
        assert "CONNECTED" in result.stdout, (
            "expected-limitation network connection did NOT succeed -- "
            "if this assertion fails, the documented limitation claim is stale and must be corrected"
        )
    finally:
        srv.close()


# ── DISCLOSED LIMITATION: RLIMIT_AS reliability on this host ────────

@pytest.mark.skipif(os.name != "posix", reason="resource limits are POSIX-specific")
def test_resource_limits_observed_behavior_on_this_host(tmp_path):
    """
    Empirically observes (does not assume) whether RLIMIT_CPU actually
    terminates a CPU-bound loop on this host within a bounded wall
    -clock window. Records the observed outcome; the evidence
    checkpoint quotes this test's actual result rather than an
    assumed guarantee, per the module docstring's disclosed
    uncertainty about RLIMIT_AS specifically on macOS.
    """
    script = "i = 0\nwhile True:\n    i += 1\n"
    plan = _plan(
        tmp_path, [sys.executable, "-c", script],
        resource_policy=ResourcePolicy(cpu_seconds=1, memory_bytes=None, max_processes=None),
        timeout_seconds=5.0,  # generous wall-clock backstop independent of RLIMIT_CPU
    )
    result = run_command(plan)
    # Whichever mechanism actually stopped it (RLIMIT_CPU killing the
    # process -> FAILED with a negative/SIGXCPU-derived exit code, or
    # the wall-clock timeout backstop -> TIMED_OUT), it must NOT be
    # SUCCEEDED, since the loop never exits on its own.
    assert result.status is not ExecutionOutcome.SUCCEEDED
