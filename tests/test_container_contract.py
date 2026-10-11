"""Static checks of the non-root container contract (G-003). The behavioural checks need a Docker daemon and live in
scripts/container/verify_nonroot.sh, which the 'Production Container Build + Boot Smoke' CI job runs against the freshly built image."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "docker/entrypoint-nonroot.sh"


def test_entrypoint_is_valid_posix_sh_and_drops_privileges_for_good():
    assert subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True).returncode == 0
    text = ENTRYPOINT.read_text()
    assert "exec runuser -u" in text and 'exec "$@"' in text
    assert "set -eu" in text


def test_entrypoint_detects_a_foreign_entry_anywhere_not_just_at_the_top_level():
    """An interrupted re-own leaves the top directory ours and a subtree root-owned; checking only the top level would wave that through."""
    text = ENTRYPOINT.read_text()
    assert "find \"$DATA_DIR\" -xdev ! -uid" in text
    assert "stat -c %u" not in text
    assert not re.search(r"chown\s+-[A-Za-z]*[HL]", text), "chown must not follow symlinks while running as root"


def _k8s_init_command() -> str:
    text = (ROOT / "k8s/deployment.yaml").read_text()
    m = re.search(r"name: fix-data-ownership.*?command:\n\s+- sh\n\s+- -c\n\s+- \|\n((?:\s{10}.*\n)+)", text, re.S)
    assert m, "init container command not found"
    return "\n".join(line.strip() for line in m.group(1).splitlines())


def test_k8s_init_container_uses_the_same_whole_tree_check_and_least_capabilities():
    cmd = _k8s_init_command()
    assert "find /data -xdev ! -uid 10001 -print -quit" in cmd and "stat -c %u" not in cmd and "chmod 0700 /data" in cmd
    text = (ROOT / "k8s/deployment.yaml").read_text()
    assert 'add: ["CHOWN", "FOWNER", "DAC_OVERRIDE"]' in text            # without CHOWN a root process with all caps dropped cannot re-own (script C7d)
    for needle in ("runAsNonRoot: true", "runAsUser: 10001", "fsGroup: 10001", "type: RuntimeDefault", "allowPrivilegeEscalation: false"):
        assert needle in text


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.fly"])
def test_images_create_the_unprivileged_user_and_owned_0700_state_directory(name):
    text = (ROOT / name).read_text()
    assert "--uid 10001" in text and "install -d -o orneur -g orneur -m 0700" in text
    if name == "Dockerfile":
        assert re.search(r"^USER 10001:10001$", text, re.M)
    else:
        assert "entrypoint-nonroot.sh" in text and "ENTRYPOINT" in text


def test_ci_runs_the_behavioural_verification_against_the_built_image():
    wf = (ROOT / ".github/workflows/test.yml").read_text()
    assert "scripts/container/verify_nonroot.sh" in wf and "IMAGE=orneur-ci:${{ github.sha }}" in wf
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts/container/verify_nonroot.sh")], capture_output=True).returncode == 0
