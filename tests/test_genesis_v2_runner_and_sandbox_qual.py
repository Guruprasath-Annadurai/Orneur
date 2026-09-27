"""Qualification runner registry + sandbox qualification-candidate record."""
import hashlib
import json
from pathlib import Path

from orca.eval.genesis_v2 import ledger as L
from orca.eval.genesis_v2 import runner_registry as RN
from orca.eval.genesis_v2 import sandbox as SB
from orca.eval.genesis_v2 import sandbox_qualification as SQ

ROOT = Path(__file__).resolve().parents[1]


def _rec(**over):
    r = {"runner_id": "r1", "runner_class": "SELF_HOSTED_CPU", "os_runtime": "linux", "code_sha256": "a" * 64, "allowed_purposes": ["STAGE1_SCREEN"],
         "allowed_splits": ["SCREEN"], "sandbox_image_digest": "sha256:" + "b" * 64, "semantic_engine_digest": None,
         "storage_backend_verification_digest": "c" * 64, "ledger_database_identity_digest": "d" * 64, "network_policy": "none",
         "credential_scope": {"private_store_read": True, "public_repo_write": False, "training_credentials": False, "unrelated_cloud_credentials": False, "developer_tokens": False},
         "state": "REGISTERED_NOT_AUTHORIZED"}
    r.update(over)
    return r


def test_committed_runner_registry_is_valid_and_registered_not_authorized():
    doc = json.loads((ROOT / RN.REGISTRY_PATH).read_text())
    assert RN.validate(doc) == [] and len(doc["records"]) == 1
    r = doc["records"][0]
    assert r["state"] == "REGISTERED_NOT_AUTHORIZED" and r["credential_scope"]["public_repo_write"] is False
    assert RN.to_ledger_registered_processes(doc) == {}                                    # registration grants nothing


def test_authorized_state_produces_a_ledger_registered_process():
    doc = {"schema_version": RN.SCHEMA_VERSION, "records": [_rec(state="AUTHORIZED")]}
    procs = RN.to_ledger_registered_processes(doc)
    assert set(procs) == {"r1"} and isinstance(procs["r1"], L.RegisteredProcess) and procs["r1"].splits == ("SCREEN",)


def test_runner_record_schema_violations():
    for over in (dict(state="MAYBE"), dict(network_policy="bridge"), dict(allowed_purposes=[]), dict(code_sha256="short"),
                 dict(credential_scope={"private_store_read": True}), dict(credential_scope={**_rec()["credential_scope"], "training_credentials": True})):
        assert RN.validate_record(_rec(**over))
    assert RN.validate_record({**_rec(), "extra": 1})
    doc = {"schema_version": RN.SCHEMA_VERSION, "records": [_rec(), _rec()]}
    assert any("duplicate" in p for p in RN.validate(doc))


def test_code_sha256_of_is_deterministic_over_the_real_package(tmp_path):
    files = sorted(Path(ROOT / "orca/eval/genesis_v2").glob("*.py"))
    assert RN.code_sha256_of(files) == RN.code_sha256_of(files)
    assert len(RN.code_sha256_of(files)) == 64


# ---------------------------------------------------------------- sandbox qualification-candidate record
def test_committed_sandbox_qualification_candidate_record_matches_the_pinned_image():
    rec = json.loads((ROOT / SQ.RECORD_PATH).read_text())
    assert rec["schema_version"] == SQ.SCHEMA_VERSION and rec["sandbox_ready"] is False
    assert rec["image_reference"] == SB.SUPPORTED_RUNTIMES[SQ.RUNTIME_KEY]
    assert rec["image_digest"] == rec["image_reference"].split("@", 1)[1]
    assert rec["dockerfile_sha256"] == hashlib.sha256((ROOT / SQ.DOCKERFILE_PATH).read_bytes()).hexdigest()
    assert rec["containment_test_result_digest"] and rec["runtime_versions"]["python_in_container"].startswith("3.11")


def test_dockerfile_pins_by_digest_not_a_mutable_tag():
    text = (ROOT / SQ.DOCKERFILE_PATH).read_text()
    assert "FROM python@sha256:" in text and "FROM python:3.11-slim\n" not in text and "latest" not in text.lower()


def test_qualification_candidate_image_is_addressable_and_matches_registry_entries():
    rec = json.loads((ROOT / SQ.RECORD_PATH).read_text())
    runner_reg = json.loads((ROOT / RN.REGISTRY_PATH).read_text())
    assert runner_reg["records"][0]["sandbox_image_digest"] == rec["image_digest"]
    draft = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json").read_text())
    assert draft["bindings"]["sandbox_policy_version"]["qualification_candidate_image_digest"] == rec["image_digest"]
