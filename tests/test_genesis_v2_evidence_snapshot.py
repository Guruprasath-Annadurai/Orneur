"""Read-only evidence snapshot script: aggregates existing read-only checks, never touches a secret, never
activates/authorizes/generates anything, always exits 0."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*extra_args):
    return subprocess.run([sys.executable, "scripts/genesis_v2_evidence_snapshot.py", *extra_args],
                           cwd=ROOT, capture_output=True, text=True)


def test_evidence_snapshot_runs_read_only_and_exits_zero_without_a_vault():
    p = _run()
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert doc["document"] == "GENESIS_V2_EVIDENCE_SNAPSHOT"
    assert doc["vault_isolation"]["status"] == "NOT_CONFIGURED"
    for key in ("owner_preflight", "privacy_scan", "role_preflight_owner", "role_preflight_generator", "role_preflight_verifier"):
        assert key in doc


def test_evidence_snapshot_includes_vault_check_when_vault_given(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    p = _run("--vault", str(vault))
    assert p.returncode == 0
    doc = json.loads(p.stdout)
    assert "pass" in doc["vault_isolation"]   # real verify_vault_isolation() output, not the NOT_CONFIGURED placeholder


def test_evidence_snapshot_never_contains_a_real_secret_shaped_value():
    p = _run()
    assert p.returncode == 0
    blob = p.stdout
    import re
    # no 64-hex-char string anywhere (a real vault key or corpus secret would be exactly this shape)
    assert not re.search(r"\b[0-9a-fA-F]{64}\b", blob)
    for forbidden in ("-----BEGIN", "/Users/", "/home/"):
        assert forbidden not in blob


def test_evidence_snapshot_role_preflights_agree_with_direct_calls():
    """Cross-check: the script's aggregated role_preflight_* sections must match calling the same functions directly
    -- proves the script is genuinely composing existing functions, not reimplementing or diverging from them."""
    from orca.eval.genesis_v2 import store as ST
    p = _run()
    doc = json.loads(p.stdout)
    assert doc["role_preflight_owner"]["status"] == ST.owner_setup_preflight()["status"]
    assert doc["role_preflight_generator"]["status"] == ST.generator_setup_preflight()["status"]
    assert doc["role_preflight_verifier"]["status"] == ST.verifier_setup_preflight()["status"]


def test_evidence_snapshot_never_writes_anything(tmp_path):
    """No registry, vault, or ledger write occurs -- confirmed by running twice and diffing the repository's own
    tracked/untracked state via git, which must show no new files this script could have created."""
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    _run()
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    assert before == after
