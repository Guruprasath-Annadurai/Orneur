"""Historical-integrity + mainline-reconciliation checks for the V2 privacy-hardening phase. Nothing historical may change semantically."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from orca.eval import genesis_prereg as PR
from orca.eval.system_contract_qualification import historical_control_state
from orca.intelligence import freeze_record as FRZ

ROOT = Path(__file__).resolve().parents[1]
PH = ROOT / "docs/orneur/phase-21"
CONTROL_EVIDENCE_AGGREGATE_SHA256 = "125db85c9abbbe2af9671c688a4335169162d8483c3f35bf763bf87688c2d358"
SYSTEM_QUAL_ARTIFACT_SHA256 = "9b14c4cf90d1022cfd76467d73d82202177698e6c4c16d98a39988938111ca19"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


def blob_sha1(p):
    d = Path(p).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(d) + d).hexdigest()


# ---------------------------------------------------------------- V1 historical integrity
def test_v1_files_manifests_and_harness_are_byte_identical_to_the_recorded_history():
    rec = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json").read_text())
    assert rec["GENESIS_CAPABILITY_EVAL_V1_FROZEN"] is False and rec["GENESIS_CAPABILITY_EVAL_V1_PRIVATE_HOLDOUT_VALID"] is False
    assert rec["reason"] == "PUBLIC_REPOSITORY_EXPOSURE"
    for rel, digest in rec["exposed_files_sha256"].items():
        assert sha(ROOT / rel) == digest, rel
    h = rec["v1_hashes_unmodified"]
    assert h["preregistration_file_sha256"] == sha(PH / "GENESIS_CAPABILITY_EVAL_V1_PREREGISTRATION.json")
    assert h["dataset_manifest_file_sha256"] == sha(PH / "GENESIS_CAPABILITY_EVAL_V1_MANIFEST.json")
    assert h["holdout_manifest_file_sha256"] == sha(PH / "GENESIS_CAPABILITY_EVAL_V1_HOLDOUT_MANIFEST.json")
    assert h["training_exclusion_manifest_file_sha256"] == sha(PH / "GENESIS_CAPABILITY_EVAL_V1_TRAINING_EXCLUSION_MANIFEST.json")
    pre = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V1_PREREGISTRATION.json").read_text())
    assert PR.harness_sha256(ROOT) == pre["harness_sha"] == "01a6b3b0b69bfba23053261b010de11ca91b2529cdc31259c82e777b600ea880"   # includes the Stage-2 family-order/incomplete fixes (genesis_funnel.py)
    assert pre["dataset_manifest_sha"] == "c8dfba1b3c479f197081fa4d374a2da71d0732c70ef7511f2512b45ccf2dda4d"
    ex = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V1_TRAINING_EXCLUSION_MANIFEST.json").read_text())
    assert ex["semantic_overlap"]["status"] == "HOOK_NOT_CONFIGURED"              # V1 contamination record untouched


# ---------------------------------------------------------------- architecture / core / contract engine / control evidence
@pytest.mark.parametrize("artifact", sorted(FRZ.ARTIFACTS))
def test_eternal_architecture_and_core_protocol_freeze_records_still_verify(artifact):
    a = FRZ.ARTIFACTS[artifact]
    rec = FRZ.verify_freeze_record(ROOT, ROOT / FRZ.FREEZE_DIR / a["file"])
    assert rec["status"] == "FROZEN"


def test_contract_engine_qualification_and_78_control_evidence_files_unchanged():
    ev = PH / "evidence"
    assert sha(ev / "ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json") == SYSTEM_QUAL_ARTIFACT_SHA256
    state = historical_control_state(ev)
    assert state["control_evidence_aggregate_sha256"] == CONTROL_EVIDENCE_AGGREGATE_SHA256 and state["file_count"] == 78
    d = json.loads((ev / "ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json").read_text())
    assert d["verdict"] == "SYSTEM_CONTRACT_QUALIFIED" and d["model_calls"] == 0 and d["gpu_calls"] == 0


def test_no_selection_and_all_authorizations_remain_false():
    st = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["GENESIS_CAPABILITY_EVAL_V2_FROZEN"] is False and st["foundation_selected"] is None
    assert st["authorizations"] == {"gpu": False, "training": False, "provider_inference": False, "spending": False, "foundation_selection": False, "phase_21c": False}
    assert st["private_corpus_generated"] is False and st["secret_available"] is False
    assert st["freeze_prerequisites"]["new_secret_corpus_generated"] is False
    assert not any(st["freeze_prerequisites"].values())          # infrastructure subchecks never flip a freeze prerequisite
    assert st["infrastructure_subchecks"]["note"].startswith("Infrastructure subchecks are NOT freeze prerequisites")


# ---------------------------------------------------------------- V2 code survives integration + reconciliation record
def test_v2_privacy_modules_are_present_importable_and_tracked():
    import importlib
    for m in ("spec", "secret", "store", "ledger", "manifest", "privacy_scan", "similarity", "contamination", "isolation"):
        importlib.import_module(f"orca.eval.genesis_v2.{m}")
    tracked = git("ls-files", "orca/eval/genesis_v2").stdout.split()
    if git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true":
        assert len([t for t in tracked if t.endswith(".py")]) >= 10


def test_mainline_reconciliation_record_is_consistent_and_verified_against_history_when_available():
    d = json.loads((PH / "GENESIS_V2_MAINLINE_RECONCILIATION.json").read_text())
    assert d["main_head_before"] == "b78a903185b3abe5fa6d7c748083bce288d4db71" and d["audited_v2_branch_head"] == "d7d5032a8b878b848d836cf654536dffc8ead7b6"
    assert d["tree_identical_after_merge"] is True and d["tree_before_merge"] == d["tree_after_merge"]
    assert d["overlap_with_v2_privacy_files"] == [] and "force" in d["strategy"] and "no force-push" in d["strategy"]
    wf = ROOT / ".github/workflows/phase14b-distributed-qualification.yml"
    assert blob_sha1(wf) == d["conflict"]["branch_blob_sha1"]                      # resolution kept the branch (descendant) version
    shallow = git("rev-parse", "--is-shallow-repository").stdout.strip()
    have = git("cat-file", "-e", d["merge_commit"]).returncode == 0
    if not have:
        assert shallow == "true"                                                    # only a shallow checkout may lack the history; a full clone must have it
        return
    parents = git("rev-list", "--parents", "-n", "1", d["merge_commit"]).stdout.split()[1:]
    assert parents == d["merge_commit_parents"]
    assert git("rev-parse", d["merge_commit"] + "^{tree}").stdout.strip() == d["tree_after_merge"]
    assert git("merge-base", "--is-ancestor", d["main_head_before"], "HEAD").returncode == 0     # canonical main history is contained
    assert git("merge-base", "--is-ancestor", d["audited_v2_branch_head"], "HEAD").returncode == 0  # audited V2 SHA is contained
    if git("cat-file", "-e", d["main_head_before"]).returncode == 0:
        assert git("rev-parse", d["main_head_before"] + ":.github/workflows/phase14b-distributed-qualification.yml").stdout.strip() == d["conflict"]["main_blob_sha1"]


def test_v2_design_docs_state_new_contracts():
    t = (PH / "GENESIS_CAPABILITY_EVAL_V2_DESIGN.md").read_text()
    for s in ("Contamination controls", "CONTAMINATION_DATASET_UNAVAILABLE", "NOT_CONFIGURED", "separation policy", "SQLite", "AES-256-GCM", "qualification",
              "PUBLIC_SFT", "genesis_sft_v2_public"):
        assert s in t, s
