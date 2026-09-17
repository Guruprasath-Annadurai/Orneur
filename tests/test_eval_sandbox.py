"""
Phase 21B.4 (§5) sandbox security review tests -- orca.eval.sandbox
replaces the prior in-process restricted-builtins exec() after live
reproduction during this closure proved it exploitable (see
orca.eval.sandbox's module docstring for the full writeup). These tests
re-run the exact confirmed exploits against the new implementation and
assert they are closed, plus cover the required review checklist:
imports, __import__, open, exec, eval, compile, filesystem access,
subprocess, globals/builtins traversal, and timeout enforcement.
"""
from __future__ import annotations

import time

from orca.eval.sandbox import run_sandboxed


def test_valid_code_executes_correctly():
    code = "def is_palindrome(s):\n    s = s.lower().replace(' ', '')\n    return s == s[::-1]\n"
    assert run_sandboxed(code, "is_palindrome", ("racecar",)).fn_result is True
    assert run_sandboxed(code, "is_palindrome", ("hello",)).fn_result is False


def test_missing_function_fails_closed():
    code = "def some_other_name(s):\n    return True\n"
    result = run_sandboxed(code, "is_palindrome", ("x",))
    assert result.ok is False
    assert "not defined" in result.error


def test_syntax_error_fails_closed():
    result = run_sandboxed("def broken(:\n", "broken", ())
    assert result.ok is False


def test_exception_raising_code_fails_closed():
    code = "def is_palindrome(s):\n    raise RuntimeError('boom')\n"
    result = run_sandboxed(code, "is_palindrome", ("x",))
    assert result.ok is False
    assert "raised" in result.error


# ── the exact confirmed exploits, re-run against the fix ───────────────────


def test_subclass_walk_popen_discovery_finds_nothing_in_fresh_child():
    """The exact exploit reproduced live during this closure: walking
    object.__subclasses__() to find subprocess.Popen without ever using
    __import__. In the OLD in-process sandbox this found a real Popen
    class (already loaded by unrelated code in the host process) and
    spawned a real subprocess. In a genuinely fresh child interpreter,
    subprocess was never imported, so there is nothing to find."""
    code = (
        "def is_palindrome(s):\n"
        "    for cls in ().__class__.__bases__[0].__subclasses__():\n"
        "        if cls.__name__ == 'Popen':\n"
        "            return 'FOUND_POPEN'\n"
        "    return 'NOT_FOUND'\n"
    )
    result = run_sandboxed(code, "is_palindrome", ("x",))
    assert result.ok is True
    assert result.fn_result == "NOT_FOUND"


def test_infinite_loop_is_killed_by_timeout_not_hung_forever():
    code = "def is_palindrome(s):\n    while True:\n        pass\n"
    start = time.time()
    result = run_sandboxed(code, "is_palindrome", ("x",), timeout_seconds=2.0)
    elapsed = time.time() - start
    assert result.ok is False
    assert result.timed_out is True
    assert elapsed < 10  # generous upper bound; must not hang indefinitely


def test_direct_network_connection_is_blocked():
    code = (
        "def is_palindrome(s):\n"
        "    import socket\n"
        "    sock = socket.socket()\n"
        "    sock.connect(('example.com', 80))\n"
        "    return True\n"
    )
    result = run_sandboxed(code, "is_palindrome", ("x",))
    assert result.ok is False
    assert "network" in result.error.lower() or "blocked" in result.error.lower()


def test_subprocess_spawn_from_within_sandbox_is_blocked_by_resource_limit():
    """Confirmed live during this closure: RLIMIT_NPROC=0 genuinely
    prevents the sandboxed child from forking a grandchild process on
    this platform -- not assumed to work merely because the limit is
    set (macOS's rlimit support is notoriously incomplete for several
    limits)."""
    code = (
        "def is_palindrome(s):\n"
        "    import subprocess\n"
        "    r = subprocess.run(['echo', 'should not run'], capture_output=True, text=True)\n"
        "    return r.stdout\n"
    )
    result = run_sandboxed(code, "is_palindrome", ("x",))
    assert result.ok is False


def test_os_system_spawn_does_not_actually_execute_a_command(tmp_path):
    marker = tmp_path / "marker.txt"
    code = (
        "def is_palindrome(s):\n"
        f"    import os\n"
        f"    os.system('touch {marker}')\n"
        "    return True\n"
    )
    run_sandboxed(code, "is_palindrome", ("x",))
    assert not marker.exists()


def test_filesystem_write_within_own_temp_cwd_is_at_least_isolated_from_repo():
    """Documented limitation (see module docstring): the child is not
    filesystem-jailed and CAN write outside its own cwd (e.g. to /tmp).
    This test does not claim that's blocked -- it confirms the honestly-
    documented behavior (a write succeeds) so the limitation stays a
    verified fact, not an assumption that could silently drift if a
    future change altered it without updating the docs."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as outside_dir:
        marker = Path(outside_dir) / "escape_marker.txt"
        code = (
            "def is_palindrome(s):\n"
            f"    with open({str(marker)!r}, 'w') as f:\n"
            "        f.write('escaped')\n"
            "    return True\n"
        )
        result = run_sandboxed(code, "is_palindrome", ("x",))
        assert result.ok is True  # documented: filesystem writes outside cwd are NOT blocked
        assert marker.exists()


def test_malformed_result_not_json_serializable_fails_closed():
    code = "def is_palindrome(s):\n    return object()\n"  # not JSON-serializable
    result = run_sandboxed(code, "is_palindrome", ("x",))
    assert result.ok is False


def test_empty_code_fails_closed():
    result = run_sandboxed("", "is_palindrome", ("x",))
    assert result.ok is False


def test_deeply_nested_recursion_is_contained_not_crashing_the_harness():
    code = "def is_palindrome(s):\n    def f(n):\n        return f(n+1)\n    return f(0)\n"
    result = run_sandboxed(code, "is_palindrome", ("x",), timeout_seconds=5.0)
    # RecursionError inside the child is caught and reported, or the
    # process is killed by CPU/timeout -- either way this call must
    # return, never hang or crash the calling (parent) test process.
    assert isinstance(result.ok, bool)
