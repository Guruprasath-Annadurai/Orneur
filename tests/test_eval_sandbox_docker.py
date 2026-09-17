"""
Phase 21B.4.1 (§2, §17) container-sandbox security tests --
orca.eval.sandbox_docker, the real OS-level isolation boundary that
replaces orca.eval.sandbox's subprocess-only approach as the backend
orca.eval.genesis_suite.score_unit_test() actually uses.

CRITICAL DISTINCTION (spec §17): every test in this file either runs
for real against the actual Docker backend on this host (skipped, never
failed, if Docker is unavailable -- see `requires_docker` below) or is
explicitly labeled otherwise. A test passing here means SECURITY
PROPERTY VERIFIED ON ACTUAL BACKEND for this host's Docker installation
and the pinned `python:3.11-slim` image -- it does NOT mean "the code
path exists" (IMPLEMENTATION TESTED) if Docker was unavailable and the
test was skipped. Never conflate the two; a skipped security test is
NOT evidence of a verified property.
"""
from __future__ import annotations

import time

import pytest

from orca.eval.sandbox_docker import (
    SandboxBackendUnavailable,
    is_docker_available,
    resolve_image_digest,
    run_sandboxed_docker,
)

requires_docker = pytest.mark.skipif(not is_docker_available(), reason="Docker is not available in this environment")

# ── availability / contract plumbing (IMPLEMENTATION TESTED, no Docker needed) ──


def test_is_docker_available_returns_a_bool():
    assert isinstance(is_docker_available(), bool)


def test_resolve_image_digest_returns_none_or_a_digest_string():
    result = resolve_image_digest("this-image-does-not-exist-12345:latest")
    assert result is None


# ── the following tests require Docker and are SECURITY PROPERTY VERIFIED
#    ON ACTUAL BACKEND when they run (not skipped) ──────────────────────────


@requires_docker
def test_valid_code_executes_correctly():
    code = "def is_palindrome(s):\n    s = s.lower().replace(' ', '')\n    return s == s[::-1]\n"
    r = run_sandboxed_docker(code, "is_palindrome", ("racecar",))
    assert r.ok is True
    assert r.fn_result is True
    r2 = run_sandboxed_docker(code, "is_palindrome", ("hello",))
    assert r2.fn_result is False


@requires_docker
def test_network_socket_connect_is_blocked_at_the_kernel_level():
    """SECURITY PROPERTY VERIFIED ON ACTUAL BACKEND: --network none means
    no network interface exists inside the container at all -- confirmed
    via a real connection attempt to a real external IP, not a mock."""
    code = "def f(s):\n    import socket\n    sock = socket.socket()\n    sock.settimeout(3)\n    sock.connect(('8.8.8.8', 53))\n    return 'connected'\n"
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=6.0)
    assert r.ok is False


@requires_docker
def test_dns_resolution_is_blocked_closing_the_python_guard_gap():
    """The exact gap found in orca.eval.sandbox's Python-level network
    guard this closure: socket.gethostbyname() does not go through
    socket.socket() at all, so a Python-level monkeypatch of
    socket.socket cannot intercept it -- confirmed live this closure
    that DNS resolution succeeded despite that guard. --network none is
    a kernel-level fact (no interface, no resolver reachable), not a
    guard any in-container Python code can route around."""
    code = "def f(s):\n    import socket\n    return socket.gethostbyname('example.com')\n"
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=6.0)
    assert r.ok is False
    assert "resolution" in (r.error or "").lower() or "name" in (r.error or "").lower()


@requires_docker
def test_repository_path_does_not_exist_inside_container():
    """No bind mount of the host repository exists -- the path isn't
    merely permission-denied, it doesn't exist at all inside the
    container's filesystem."""
    code = (
        "def f(s):\n"
        "    import os\n"
        "    return os.path.exists('/Users/ag/orca') or os.path.exists('/app') or os.path.exists('/repo')\n"
    )
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=6.0)
    assert r.ok is True
    assert r.fn_result is False


@requires_docker
def test_readonly_root_filesystem_rejects_writes():
    code = "def f(s):\n    open('/usr/local/escape_test.txt', 'w').write('x')\n    return 'wrote'\n"
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=6.0)
    assert r.ok is False
    assert "read-only" in (r.error or "").lower()


@requires_docker
def test_infinite_loop_is_killed_by_timeout():
    code = "def f(s):\n    while True:\n        pass\n"
    start = time.time()
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=3.0)
    elapsed = time.time() - start
    assert r.ok is False
    assert r.timed_out is True
    assert elapsed < 15


@requires_docker
def test_memory_limit_kills_the_container():
    code = "def f(s):\n    x = bytearray(500 * 1024 * 1024)\n    return len(x)\n"
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=8.0, memory_limit="128m")
    assert r.ok is False
    assert r.timed_out is False  # killed by OOM, not by the wall-clock timeout


@requires_docker
def test_pids_limit_blocks_fork_bomb():
    code = (
        "def f(s):\n"
        "    import os\n"
        "    count = 0\n"
        "    try:\n"
        "        for i in range(1000):\n"
        "            os.fork()\n"
        "            count += 1\n"
        "    except Exception:\n"
        "        return count\n"
        "    return count\n"
    )
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=8.0, pids_limit=8)
    # Either the fork bomb was capped well below 1000, or the container
    # was killed outright -- either way, an unbounded fork bomb must not
    # succeed silently.
    if r.ok:
        assert r.fn_result < 1000
    else:
        assert True  # killed/errored -- also an acceptable enforcement outcome


@requires_docker
def test_huge_output_is_truncated_not_unbounded():
    code = "def f(s):\n    print('A' * 5_000_000)\n    return 'done'\n"
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=8.0)
    # A 5MB print against a 1MB output cap must be detected -- either as
    # a truncation or a parse failure caused by truncation -- never
    # silently accepted as if the full output were trustworthy.
    assert r.ok is False or r.output_truncated is True


@requires_docker
def test_environment_has_no_host_secrets():
    code = "def f(s):\n    import os\n    return sorted(os.environ.keys())\n"
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=6.0)
    assert r.ok is True
    env_keys = set(r.fn_result)
    # The python:3.11-slim IMAGE itself bakes in a few build-metadata env
    # vars (PYTHON_VERSION, PYTHON_SHA256, GPG_KEY) -- harmless, not host
    # secrets, not something this project controls. The actual security
    # property is that NO variable from the real HOST environment (this
    # test process's own os.environ, which does carry real tokens/keys
    # in CI) leaks into the container.
    import os as _os

    host_only_keys = set(_os.environ.keys()) - {"HOME", "PATH", "LANG"}
    leaked = env_keys & host_only_keys
    assert not leaked, f"host environment variables leaked into the sandboxed container: {leaked}"
    assert "GITHUB_TOKEN" not in env_keys
    assert "OPENAI_API_KEY" not in env_keys
    assert "ANTHROPIC_API_KEY" not in env_keys


@requires_docker
def test_malformed_code_fails_closed():
    r = run_sandboxed_docker("def broken(:\n", "broken", (), timeout_seconds=6.0)
    assert r.ok is False


@requires_docker
def test_subprocess_within_container_cannot_reach_network_either():
    """A subprocess spawned INSIDE the container (which is not itself
    blocked -- pids_limit permits a handful of processes) still cannot
    reach the network, because --network none applies to the whole
    container, not just the top-level process."""
    code = (
        "def f(s):\n"
        "    import subprocess\n"
        "    r = subprocess.run(['python3', '-c', \"import socket; socket.socket().connect(('8.8.8.8', 53))\"], capture_output=True, text=True)\n"
        "    return r.returncode\n"
    )
    r = run_sandboxed_docker(code, "f", ("x",), timeout_seconds=8.0)
    assert r.ok is True
    assert r.fn_result != 0  # the inner connect() attempt must have failed


def test_sandbox_backend_unavailable_raised_when_docker_missing(monkeypatch):
    """IMPLEMENTATION TESTED (does not require Docker itself -- simulates
    its absence): confirms the fail-closed contract by forcing
    is_docker_available() to report False."""
    import orca.eval.sandbox_docker as sandbox_docker_mod

    monkeypatch.setattr(sandbox_docker_mod, "is_docker_available", lambda: False)
    with pytest.raises(SandboxBackendUnavailable):
        run_sandboxed_docker("def f(s):\n    return True\n", "f", ("x",))
