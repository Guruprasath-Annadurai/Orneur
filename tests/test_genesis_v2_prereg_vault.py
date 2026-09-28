"""Preregistration draft (not frozen) + owner vault verification + terminology/status preservation."""
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import prereg as PR
from orca.eval.genesis_v2 import spec
from orca.eval.genesis_v2 import vault_verify as VV

ROOT = Path(__file__).resolve().parents[1]
PH = ROOT / "docs/orneur/phase-21"
DRAFT = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json").read_text())


# ---------------------------------------------------------------- preregistration
def test_draft_is_valid_as_a_draft_and_binds_every_required_field():
    assert PR.validate_draft(DRAFT) == []
    assert set(DRAFT["bindings"]) == set(PR.BINDINGS) and len(PR.BINDINGS) == 23
    assert json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_SCHEMA.json").read_text()) == PR.schema()


def test_draft_is_not_frozen_has_no_results_and_defers_unknowns():
    assert DRAFT["status"] == "DRAFT_NOT_FROZEN" and DRAFT["frozen"] is False and DRAFT["frozen_at"] is None
    assert DRAFT["candidate_results"] == [] and DRAFT["first_candidate_run_at"] is None and DRAFT["floors_status"] == "PROPOSED_NOT_LOCKED"
    for k in PR.DEFERRED:
        assert DRAFT["bindings"][k] is None, k
    problems = PR.validate_for_freeze(DRAFT)
    assert problems and any("not FROZEN" in p for p in problems) and any("private_corpus_aggregate_commitment" in p for p in problems)


def test_bindings_reflect_the_v2_design():
    b = DRAFT["bindings"]
    assert b["eval_version"] == spec.EVAL_VERSION and b["corpus_version"] == spec.CORPUS_VERSION
    assert b["sandbox_policy_version"]["policy_version"] == "genesis-v2-coding-sandbox-policy/1"
    assert b["sandbox_policy_version"]["sandbox_ready"] is False and b["sandbox_policy_version"]["qualification_candidate_image_digest"]
    assert b["runner_identity"]["runner_id"] and b["storage_verification_digest"] and b["code_hashes"]
    assert b["resource_spend_limits"]["max_spend_usd_per_stage"]["STAGE_1"] == 0
    assert b["qualification_holdout_policy"]["write_once_per_candidate_lineage"] is True
    assert b["qualification_holdout_policy"]["adaptation_after_open_requires_fresh_holdout_version"] is True
    assert b["semantic_review_mechanism_version"]["operational_state"] == "CONFIGURED_LOCAL_ONLY"
    assert b["model_run_constraints"]["model_execution_requires"].startswith("signed authorization")
    assert set(b["stage_protocols"]) == {"STAGE_0", "STAGE_1", "STAGE_2", "STAGE_3"}
    assert b["category_counts"]["reasoning"]["QUALIFICATION_HOLDOUT"] == 180 and "latency" in b["gating_report_only_status"]


MUTATIONS = [
    (lambda d: d.__setitem__("frozen", True), True), (lambda d: d.__setitem__("status", "FROZEN"), True), (lambda d: d["candidate_results"].append({"m": 1}), True),
    (lambda d: d.__setitem__("first_candidate_run_at", "2026-09-27T00:00:00Z"), True),
    (lambda d: d["bindings"].__setitem__("private_corpus_aggregate_commitment", "sha256:fake"), True), (lambda d: d["bindings"].__setitem__("code_hashes", None), True),
    (lambda d: d["bindings"].__setitem__("runner_identity", None), True), (lambda d: d["bindings"].pop("floors"), True),
    (lambda d: d.__setitem__("floors_status", "LOCKED"), True), (lambda d: d["bindings"].__setitem__("eval_version", "genesis-capability-eval/1.0.0"), True),
    (lambda d: d.__setitem__("record_sha256", "0" * 64), False), (lambda d: d["bindings"]["floors"].__setitem__("reasoning", 0.01), False),
    (lambda d: d.__setitem__("schema_version", "x"), False)]


@pytest.mark.parametrize("i", range(len(MUTATIONS)))
def test_draft_mutations_are_rejected(i):
    mut, rehash = MUTATIONS[i]
    d = copy.deepcopy(DRAFT)
    mut(d)
    if rehash:
        d["record_sha256"] = PR.record_hash(d)          # even a self-consistent forged record must be rejected on substance
    assert PR.validate_draft(d), "mutation not detected"


def test_a_fully_bound_locked_record_can_be_frozen_and_floors_become_immutable():
    d = copy.deepcopy(DRAFT)
    for k in PR.DEFERRED:
        d["bindings"][k] = {"bound": k}
    d.update({"status": "FROZEN", "frozen": True, "frozen_at": "2026-10-01T00:00:00Z", "floors_status": "LOCKED"})
    d["record_sha256"] = PR.record_hash(d)
    assert PR.validate_for_freeze(d) == []
    later = copy.deepcopy(d)
    later["bindings"]["floors"]["reasoning"] = 0.05                                    # lowering a floor after freeze
    with pytest.raises(ValueError):
        PR.assert_floors_unchanged(d, later)
    PR.assert_floors_unchanged(d, copy.deepcopy(d))
    started = copy.deepcopy(DRAFT)
    started["first_candidate_run_at"] = "2026-10-02T00:00:00Z"
    moved = copy.deepcopy(started)
    moved["bindings"]["floors"]["coding"] = 0.01
    with pytest.raises(ValueError):
        PR.assert_floors_unchanged(started, moved)                                     # also immutable once a candidate has run


def test_v2_remains_unfrozen_everywhere():
    assert spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN is False
    st = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["GENESIS_CAPABILITY_EVAL_V2_FROZEN"] is False and st["preregistration"]["state"] == "DRAFT_NOT_FROZEN"


# ---------------------------------------------------------------- vault verification
def _repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    return r


def _vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir(mode=0o700)
    os.chmod(v, 0o700)
    f = v / "SEAL.enc"
    f.write_bytes(b"x")
    os.chmod(f, 0o400)
    return v


def test_isolated_vault_passes(tmp_path):
    r = VV.verify_vault_isolation(_vault(tmp_path), _repo(tmp_path))
    assert r["pass"], r


def test_vault_inside_repo_fails(tmp_path):
    repo = _repo(tmp_path)
    v = repo / "vault"
    v.mkdir(mode=0o700)
    (v / "SEAL.enc").write_bytes(b"x")
    os.chmod(v / "SEAL.enc", 0o400)
    r = VV.verify_vault_isolation(v, repo)
    assert not r["pass"] and r["checks"]["vault_outside_repository_tree"] is False and r["checks"]["vault_not_inside_any_git_work_tree"] is False


def test_vault_inside_another_git_work_tree_fails(tmp_path):
    other = tmp_path / "otherrepo"
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=other, check=True)
    v = other / "v"
    v.mkdir(mode=0o700)
    r = VV.verify_vault_isolation(v, _repo(tmp_path))
    assert not r["pass"] and r["checks"]["vault_not_inside_any_git_work_tree"] is False


def test_symlinked_vault_and_tracked_symlink_into_vault_fail(tmp_path):
    repo, v = _repo(tmp_path), _vault(tmp_path)
    link = tmp_path / "vaultlink"
    link.symlink_to(v)
    assert VV.verify_vault_isolation(link, repo)["checks"]["vault_is_not_a_symlink"] is False
    os.symlink(v, repo / "sneaky")
    subprocess.run(["git", "add", "sneaky"], cwd=repo, check=True)
    r = VV.verify_vault_isolation(v, repo)
    assert not r["pass"] and r["checks"]["no_tracked_symlink_points_into_vault"] is False


def test_enc_artifact_in_repo_and_bad_permissions_and_plaintext_fail(tmp_path):
    repo, v = _repo(tmp_path), _vault(tmp_path)
    (repo / "x.enc").write_bytes(b"x")
    assert not VV.verify_vault_isolation(v, repo)["checks"]["no_tracked_or_untracked_enc_artifacts_in_repo"]
    (repo / "x.enc").unlink()
    os.chmod(v / "SEAL.enc", 0o644)
    assert not VV.verify_vault_isolation(v, repo)["pass"]
    os.chmod(v / "SEAL.enc", 0o400)
    (v / "corpus.jsonl").write_text("{}")
    assert not VV.verify_vault_isolation(v, repo)["checks"]["vault_permissions_and_no_plaintext_siblings"]


def test_missing_relative_or_erroring_vault_paths_fail(tmp_path):
    repo = _repo(tmp_path)
    assert not VV.verify_vault_isolation(tmp_path / "does-not-exist", repo)["pass"]
    assert not VV.verify_vault_isolation(Path("relative/vault"), repo)["pass"]


def test_vault_script_exit_codes(tmp_path):
    import sys
    p = subprocess.run([sys.executable, "scripts/genesis_v2_vault_verify.py", "--vault", str(tmp_path / "nope")], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 2 and "VAULT ISOLATION FAIL" in p.stdout
    p = subprocess.run([sys.executable, "scripts/genesis_v2_preflight.py"], cwd=ROOT, capture_output=True, text=True, env={k: v for k, v in os.environ.items() if not k.startswith("ORNEUR_GENESIS")})
    assert p.returncode == 2 and "PRIVATE_STORAGE_NOT_CONFIGURED" in p.stdout


def test_owner_procedure_is_placeholder_only_and_complete():
    t = (PH / "GENESIS_CAPABILITY_EVAL_V2_OWNER_VAULT_PROCEDURE.md").read_text()
    for s in ("NOT ACTIVATED", "<VAULT_DIR>", "<SECRET_MANAGER_CLI>", "0700", "0400", "two custodians", "openssl rand -hex 32", "VAULT ISOLATION PASS", "Emergency revocation",
              "privacy incident", "Incident response", "Destruction", "Rotation", "runner", "Backup", "not inside any git work tree"):
        assert s.lower() in t.lower(), s
    import re
    assert not re.search(r"\b[0-9a-f]{64}\b", t) and "/Users/" not in t and "/home/" not in t


# ---------------------------------------------------------------- terminology
def test_status_terminology_is_strict():
    st = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    allowed = {"DESIGNED", "IMPLEMENTED", "TESTED", "QUALIFIED", "FROZEN", "PRODUCTION_READY"}
    for name, state in st["component_states"].items():
        core = state.replace("NOT_FROZEN", "").replace("NOT_QUALIFIED", "").replace("QUALIFICATION_CANDIDATE", "").replace("REQUALIFY", "")
        assert state.startswith(("DESIGNED", "IMPLEMENTED", "NOT_", "ACTIVATED", "CONFIGURED", "REGISTERED")) and "QUALIFIED" not in core and "FROZEN" not in core and "PRODUCTION" not in core, (name, state)
    assert st["terminology"]["levels"] == sorted(allowed, key=lambda x: ["DESIGNED", "IMPLEMENTED", "TESTED", "QUALIFIED", "FROZEN", "PRODUCTION_READY"].index(x))
    assert "unit-tested" in st["terminology"]["rule"]
    exp = {"model_eval_authorization_gate": "IMPLEMENTED_TESTED", "corpus_inventory": "IMPLEMENTED_POPULATED_REVIEWED_SIGNED_ATTESTATION",
           "semantic_manual_review_framework": "IMPLEMENTED_TESTED_CONFIGURED_LOCAL_ONLY", "coding_sandbox": "IMPLEMENTED_TESTED", "private_storage": "ACTIVATED_VERIFIED_TEST_ONLY",
           "v2_corpus": "NOT_GENERATED", "v2_freeze": "NOT_FROZEN", "preregistration": "DESIGNED_DRAFT_NOT_FROZEN_MOSTLY_BOUND",
           "authority_registry": "CONFIGURED_ONE_OWNER_KEY_REGISTERED", "reviewer_registry": "CONFIGURED_ZERO_KEYS_REGISTERED", "runner_identity": "REGISTERED_NOT_AUTHORIZED",
           "ledger_deployment": "IMPLEMENTED_OPERATIONAL_READY", "owner_preflight": "IMPLEMENTED_TESTED_RESULT_READY_FOR_PRIVATE_CORPUS_AUTHORIZATION"}
    assert {k: st["component_states"][k] for k in exp} == exp
    assert st["freeze_prerequisites"]["sandbox_ready"] is False and st["freeze_prerequisites"]["private_storage_genuinely_configured"] is False
