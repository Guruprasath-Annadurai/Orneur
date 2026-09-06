"""
Orca Code Tool — sandboxed local code execution.
Runs Python and shell code in a subprocess with timeout and output capture.
No network calls to execute code. Fully local.

SECURITY: run_python() previously had ZERO restriction — it ran arbitrary
Python with the real interpreter and the real OS user's full permissions,
no AST checks, no import restrictions, nothing. Combined with the model's
own known jailbreak susceptibility (see docs/SECURITY_AUDIT.md), this was a
complete, real attack chain: a jailbroken model could call this tool to
read secrets, spawn processes, or reach the network. _check_code_safety()
below is a real fix, but an HONEST one: it's an AST-based denylist, not a
true sandbox. A sufficiently obfuscated payload (reconstructing a blocked
name via string concatenation + getattr, for example) can still bypass a
static check. It raises the bar significantly above zero restriction; it
is not a hardened sandbox. A real sandbox (container/microVM/gVisor) is
the correct long-term fix and is out of scope for this pass. Environment
variables are also stripped from the subprocess (see run_python) as
defense in depth — even if the AST check is bypassed, there is no secret
sitting in os.environ to steal.
"""
from __future__ import annotations

import ast
import shlex
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 30  # seconds
MAX_OUTPUT = 8000  # chars

# Import roots that grant file/process/network access or dynamic-code
# escape hatches — the actual capabilities that turn "run some Python" into
# "read any file / spawn any process / reach the network."
_BLOCKED_IMPORTS = {
    "os", "subprocess", "sys", "socket", "shutil", "ctypes", "multiprocessing",
    "importlib", "pty", "pdb", "code", "resource", "signal", "fcntl", "termios",
    "ftplib", "telnetlib", "smtplib", "http", "urllib", "requests",
    "socketserver", "asyncio", "webbrowser",
}
_BLOCKED_BUILTINS = {"eval", "exec", "compile", "open", "__import__", "input", "breakpoint"}


def _check_code_safety(code: str) -> tuple[bool, str]:
    """Returns (is_safe, reason). reason is a plain-language explanation
    suitable for showing the caller, not a raw AST/syntax error dump."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_IMPORTS:
                    return False, f"`{alias.name}` isn't available in the sandbox — this keeps code execution safe."
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _BLOCKED_IMPORTS:
                return False, f"`{node.module}` isn't available in the sandbox — this keeps code execution safe."
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
            if name in _BLOCKED_BUILTINS:
                return False, f"`{name}` isn't available in the sandbox — this keeps code execution safe."

    return True, ""


@dataclass
class RunResult:
    code: str
    language: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def format(self) -> str:
        lines = []
        if self.timed_out:
            lines.append(f"[TIMEOUT after {TIMEOUT}s]")
        if self.stdout:
            lines.append(self.stdout[:MAX_OUTPUT])
        if self.stderr:
            lines.append(f"[stderr]\n{self.stderr[:2000]}")
        if not lines:
            lines.append(f"[exit {self.exit_code}]")
        return "\n".join(lines)


def run_python(code: str) -> RunResult:
    """Execute Python code in a subprocess — see module docstring for the
    real, honest scope of the safety check applied before execution."""
    code = textwrap.dedent(code)

    safe, reason = _check_code_safety(code)
    if not safe:
        return RunResult(code=code, language="python", stdout="", stderr=reason, exit_code=1)

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        proc = subprocess.run(
            [sys.executable, tmp],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            # Defense in depth: even if the AST check above is bypassed,
            # there should be no secret sitting in os.environ to steal.
            # PATH is kept so the interpreter itself can still resolve
            # standard-library behavior that shells out internally.
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        return RunResult(
            code=code,
            language="python",
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return RunResult(code=code, language="python", stdout="", stderr="", exit_code=-1, timed_out=True)
    finally:
        Path(tmp).unlink(missing_ok=True)


# SECURITY: the allowlist below deliberately EXCLUDES every general-purpose
# code interpreter (python/python3/node/npm/pip/perl/ruby/php/bash/sh/zsh/
# awk/perl) — allowing any of these here would let a caller bypass
# run_python()'s AST safety check entirely (e.g. `python3 -c "os.system(...)"`
# via this shell path instead of the sandboxed one). This tool exists for
# inert, read-oriented utilities, not a second, unsandboxed code-execution
# route.
_ALLOWED_SHELL_COMMANDS = {
    "ls", "cat", "pwd", "echo", "grep", "find", "wc", "head", "tail", "diff",
    "du", "df", "whoami", "date", "uname", "which", "env", "git",
}

_BLOCKED_SUBSTRINGS = [
    "rm -rf", "dd if=", "mkfs", ":(){:|:&};:", "shutdown", "reboot", "sudo rm", "sudo ",
]


def run_shell(command: str) -> RunResult:
    """
    Execute a single command from a fixed allowlist — NOT arbitrary shell
    execution.

    SECURITY: this previously ran ANY command via `shell=True` with only a
    6-item substring denylist blocking a handful of destructive patterns —
    real arbitrary command execution (data exfiltration via curl, reading
    secrets via unrestricted commands, network reconnaissance, and
    everything else) passed straight through. Unlike fetch_page's SSRF gap
    (confirmed dead code), this tool IS live and reachable via the agent's
    `shell` tool — combined with the model's known jailbreak
    susceptibility, this was a real, currently-exploitable gap, not a
    preventive one.

    Two structural changes, not just a bigger denylist:
      1. shell=False with shlex-parsed arguments — shell metacharacters
         (`;`, `&&`, `|`, backticks, `$()`, redirection) are NOT
         interpreted at all; there is no shell present to interpret them.
         This eliminates command-chaining/injection as a whole category,
         not just specific patterns of it.
      2. The command itself (the first token) must be in a fixed
         allowlist of safe, mostly-read-only utilities. Anything else —
         including every general-purpose interpreter — is refused
         outright, not pattern-matched against a denylist.

    HONEST SCOPE: a real, structural improvement, not a full sandbox.
      - An allowed command can still be misused within its own
        capability — the destructive-pattern check below remains as
        defense in depth for that case.
      - Path restriction is NOT part of this fix: `cat`/`find`/`head`/
        `tail`/`git` etc. can still read any file the OS user can read
        (e.g. `cat ~/.ssh/id_rsa` still succeeds) — unlike the dedicated,
        workspace-sandboxed read_file tool (orca/tools/__init__.py). A
        future pass restricting these commands' path arguments to the
        same workspace directory is the natural next step, not done here.
      - Real usability trade-off, deliberate: pipelines (`ls | grep x`) no
        longer work, since there's no shell to interpret the pipe — this
        is the direct, necessary cost of eliminating shell-metacharacter
        injection, not an oversight.
    """
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return RunResult(code=command, language="shell", stdout="", stderr=f"Could not parse command: {e}", exit_code=1)

    if not parts:
        return RunResult(code=command, language="shell", stdout="", stderr="Empty command.", exit_code=1)

    binary = parts[0]
    if binary not in _ALLOWED_SHELL_COMMANDS:
        return RunResult(
            code=command, language="shell", stdout="",
            stderr=(
                f"'{binary}' isn't in the sandbox's allowed command list — this keeps shell "
                f"execution safe. Allowed: {', '.join(sorted(_ALLOWED_SHELL_COMMANDS))}"
            ),
            exit_code=1,
        )

    lowered = command.lower()
    for b in _BLOCKED_SUBSTRINGS:
        if b in lowered:
            return RunResult(
                code=command, language="shell", stdout="",
                stderr=f"BLOCKED: '{b}' is a destructive pattern. Orca won't run it.",
                exit_code=1,
            )

    try:
        proc = subprocess.run(
            parts,
            shell=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            # Defense in depth, same as run_python: no secret should be
            # readable via an allowed command's environment even though
            # none of the allowlisted commands are expected to need one.
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        return RunResult(
            code=command,
            language="shell",
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return RunResult(code=command, language="shell", stdout="", stderr="", exit_code=-1, timed_out=True)
    except FileNotFoundError:
        return RunResult(code=command, language="shell", stdout="", stderr=f"Command not found: {binary}", exit_code=1)


def run_code(code: str, language: str = "python") -> RunResult:
    """Dispatch to the right executor."""
    lang = language.lower().strip()
    if lang in ("python", "python3", "py"):
        return run_python(code)
    elif lang in ("shell", "bash", "sh", "zsh"):
        return run_shell(code)
    else:
        return RunResult(
            code=code,
            language=lang,
            stdout="",
            stderr=f"Language '{lang}' not supported. Supported: python, shell/bash.",
            exit_code=1,
        )
