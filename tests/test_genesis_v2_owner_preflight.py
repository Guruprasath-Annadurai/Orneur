"""Owner preflight aggregator: one deterministic command, READY only when every hard requirement holds AND inventory/semantic/sandbox are genuinely
ready — never automatically true, never generates anything."""
import json
import subprocess
import sys
from pathlib import Path

from orca.eval.genesis_v2 import owner_preflight as OP

ROOT = Path(__file__).resolve().parents[1]


def test_real_repository_preflight_is_structurally_sound_but_not_ready():
    r = OP.run(ROOT)
    assert r["schema_version"] == OP.SCHEMA_VERSION and r["current_main_sha"]
    assert r["result"] == "NOT_READY"
    assert set(r["outstanding_for_ready"]) == {"corpus_inventory_attested_pass", "semantic_engine_configured", "sandbox_ready"}
    for k in ("vault_verification_record_present_and_pass", "secret_manager_policy_valid", "authority_registry_valid", "reviewer_registry_valid",
              "separation_of_duties_clean", "sandbox_image_pinned_by_digest", "sandbox_containment_evidence_present", "runner_identity_registered",
              "runner_not_authorized_for_holdout_yet", "ledger_operational_ready", "preregistration_draft_consistent", "preregistration_not_frozen",
              "v2_not_frozen", "no_private_corpus_exists", "model_authorization_not_authorized"):
        assert r["checks"][k] is True, k


def test_hard_requirement_failure_forces_not_ready(tmp_path):
    import shutil
    shutil.copytree(ROOT, tmp_path / "repo", ignore=shutil.ignore_patterns(".git"))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path / "repo", check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path / "repo", check=True)
    subprocess.run(["git", "commit", "-q", "-m", "snapshot"], cwd=tmp_path / "repo", check=True)
    rec_path = tmp_path / "repo/docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json"
    d = json.loads(rec_path.read_text())
    d["status"] = "AUTHORIZED"        # would-be authorized: must force NOT_READY regardless of everything else
    rec_path.write_text(json.dumps(d))
    r = OP.run(tmp_path / "repo")
    assert r["result"] == "NOT_READY" and r["checks"]["model_authorization_not_authorized"] is False


def test_script_exit_codes_and_no_secret_generation():
    p = subprocess.run([sys.executable, "scripts/genesis_v2_owner_preflight.py"], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 2 and "NOT_READY" in p.stdout
    for forbidden in ("ORNEUR_GENESIS_V2_CORPUS_SECRET=", "ORNEUR_GENESIS_V2_ENCRYPTION_KEY=", "-----BEGIN"):
        assert forbidden not in p.stdout


def test_preflight_never_writes_anything():
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    OP.run(ROOT)
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    assert before == after
