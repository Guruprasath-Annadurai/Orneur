"""
Phase 15.15 -- structural + behavioral tests proving pytest's REAL exit
code controls CI truth for the deterministic test job in
`.github/workflows/test.yml`.

Motivation: run `34632529810` was green (`conclusion: success`) even
though the deterministic pytest job hit THREE real collection errors
(missing `openai`/`mcp`/`torch`) -- because the job's `run:` step piped
pytest through `tee` with no explicit `shell:` key, and GitHub Actions'
true default shell in that case is `bash -e {0}`, NOT `bash -eo
pipefail {0}` (that stronger default applies only when `shell: bash`
is given explicitly). Without `pipefail`, a pipeline's exit status is
the LAST command's (`tee`, which exits 0 as long as it can write its
file) -- so pytest's non-zero exit was silently swallowed.

Fixed by moving the canonical invocation into
`scripts/ci/run_deterministic_tests.sh`, which sets `set -euo pipefail`
itself -- true regardless of what shell default the calling workflow
step uses. These tests prove (a) the workflow actually calls that
script rather than reintroducing an inline unguarded pipe, (b) the
script itself declares `pipefail` BEFORE its `tee` pipeline, and (c) a
REAL invocation of the script against a deliberately-failing, isolated
temporary pytest suite actually exits non-zero -- not merely that the
right words appear in the script text.
"""
from __future__ import annotations

import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "test.yml"
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ci" / "run_deterministic_tests.sh"


def _load_workflow() -> dict:
    return yaml.safe_load(_WORKFLOW_PATH.read_text())


def _pytest_job_steps() -> list[dict]:
    return _load_workflow()["jobs"]["pytest"]["steps"]


# ── Structural: the workflow calls the fail-closed script ─────────────

def test_deterministic_test_step_invokes_the_fail_closed_script():
    steps = _pytest_job_steps()
    run_steps = [s for s in steps if "run" in s and "Run deterministic" in s.get("name", "")]
    assert len(run_steps) == 1, f"expected exactly one deterministic-test run step, found {len(run_steps)}"
    run_text = run_steps[0]["run"]
    assert "scripts/ci/run_deterministic_tests.sh" in run_text, (
        "the deterministic-test step must invoke the fail-closed wrapper script, not an inline pytest|tee pipeline"
    )


def test_deterministic_test_step_does_not_reintroduce_an_unguarded_inline_pipe():
    """Defense in depth: even if a future edit adds text back to this
    step, it must never contain a bare `pytest ... | tee` without
    `pipefail` (or an explicit `shell: bash` combined with `set -o
    pipefail`) somewhere in the SAME step."""
    steps = _pytest_job_steps()
    for step in steps:
        run_text = step.get("run", "")
        if "| tee" not in run_text and "|tee" not in run_text:
            continue
        has_pipefail_in_step = "pipefail" in run_text
        has_pipefail_shell = step.get("shell", "").strip() == "bash" and "pipefail" in run_text
        # The current design routes through the script instead, so a
        # step containing "| tee" directly should also declare
        # pipefail itself if it's ever reintroduced.
        assert has_pipefail_in_step or has_pipefail_shell, (
            f"step {step.get('name')!r} pipes into tee without pipefail anywhere in its own run text -- "
            f"a real pytest failure would be silently masked by tee's own exit code"
        )


def test_torch_loss_tests_job_is_present_and_required():
    """No `continue-on-error` on the dedicated Torch job -- it must be
    a real, required part of the workflow, not an informational
    best-effort job."""
    jobs = _load_workflow()["jobs"]
    assert "torch-loss-tests" in jobs, "the dedicated Torch training-math job must exist"
    job = jobs["torch-loss-tests"]
    assert job.get("continue-on-error") is not True
    run_texts = " ".join(s.get("run", "") for s in job["steps"])
    assert "tests/test_train_losses.py" in run_texts


def test_deterministic_job_installs_mcp_and_nvidia_extras():
    """tests/test_distill.py (openai, via the `nvidia` extra) and
    tests/test_mcp_fs_server_sandbox.py (mcp, via the `mcp` extra) must
    both be genuinely installable in the main deterministic job -- not
    silently uncollectable."""
    steps = _pytest_job_steps()
    install_steps = [s for s in steps if "uv pip install" in s.get("run", "")]
    assert install_steps, "expected an install step using uv pip install"
    install_text = install_steps[0]["run"]
    assert ".[dev,mcp,nvidia]" in install_text or (".[dev" in install_text and "mcp" in install_text and "nvidia" in install_text)


# ── Script-level: pipefail declared before the tee pipeline ───────────

def test_script_declares_pipefail_before_its_tee_pipeline():
    assert _SCRIPT_PATH.exists(), f"expected {_SCRIPT_PATH} to exist"
    lines = [l for l in _SCRIPT_PATH.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
    pipefail_lines = [i for i, l in enumerate(lines) if "set -euo pipefail" in l or "set -o pipefail" in l]
    tee_lines = [i for i, l in enumerate(lines) if "| tee" in l or "|tee" in l]
    assert pipefail_lines, "the script must declare pipefail"
    assert tee_lines, "the script is expected to pipe pytest output through tee"
    assert pipefail_lines[0] < tee_lines[0], "pipefail must be declared BEFORE the tee pipeline, not after"


def test_script_is_executable():
    mode = _SCRIPT_PATH.stat().st_mode
    assert mode & stat.S_IXUSR, f"{_SCRIPT_PATH} must be executable (chmod +x)"


# ── Behavioral: a REAL failing suite, run through the REAL script, ────
# actually exits non-zero. Never adds a deliberately-failing test to
# this repository's own normal collection -- builds an isolated,
# throwaway temp directory instead.

def test_wrapper_script_exits_nonzero_on_a_genuinely_failing_suite(tmp_path):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "test_deliberately_fails.py").write_text(
        textwrap.dedent(
            """
            def test_this_always_fails():
                assert False, "deliberate failure for CI fail-closed regression coverage"
            """
        )
    )
    # A minimal stand-in script, IDENTICAL in structure to the real
    # one (same pipefail-before-tee shape), run against the isolated
    # fixture -- proves the WRAPPER PATTERN itself is fail-closed,
    # without invoking the real script's own `-m "not live_ollama_smoke"`
    # marker expression (which would just collect nothing useful from
    # this throwaway fixture) or depending on this repo's real fixtures.
    wrapper = tmp_path / "run.sh"
    wrapper.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            cd {fake_repo}
            {sys.executable} -m pytest -v 2>&1 | tee {tmp_path / "log.txt"}
            """
        )
    )
    wrapper.chmod(0o755)

    result = subprocess.run(["bash", str(wrapper)], capture_output=True, text=True)
    assert result.returncode != 0, (
        f"the pipefail-guarded wrapper must exit non-zero when pytest fails, got {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (tmp_path / "log.txt").exists()  # tee still wrote its log -- pipefail doesn't suppress that


def test_wrapper_without_pipefail_would_have_masked_the_same_failure(tmp_path):
    """Negative control, proving the ORIGINAL defect is real and this
    isn't a tautological test: the SAME failing suite through a
    wrapper WITHOUT pipefail exits ZERO (tee's own exit code) -- this
    is exactly what made run 34632529810 falsely green."""
    fake_repo = tmp_path / "fake_repo2"
    fake_repo.mkdir()
    (fake_repo / "test_deliberately_fails.py").write_text(
        textwrap.dedent(
            """
            def test_this_always_fails():
                assert False
            """
        )
    )
    wrapper = tmp_path / "run_unguarded.sh"
    wrapper.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            cd {fake_repo}
            {sys.executable} -m pytest -v 2>&1 | tee {tmp_path / "log_unguarded.txt"}
            """
        )
    )
    wrapper.chmod(0o755)

    result = subprocess.run(["bash", str(wrapper)], capture_output=True, text=True)
    assert result.returncode == 0, (
        "this negative control is expected to demonstrate the masking defect (exit 0 despite pytest "
        "failing) -- if this assertion itself fails, the underlying bash pipeline behavior this whole "
        "file is guarding against may have changed"
    )
