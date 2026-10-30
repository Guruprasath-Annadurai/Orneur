"""Independent Qualification Test Suite for PR #140 (Stage A) and PR #139 (Stage B).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

PR140_PATH = Path('/home/pc/projects/Orneur-pr140-phase01')
PR139_PATH = Path('/home/pc/projects/Orneur-l02')
PR140_TARGET_HEAD = '649d90f84069fc618ba4d69b4c26a66bed731caa'
PR140_ENGINEERING_SHA = 'd6794245b77bc417d9a0d66e52804f5177bbfc17'
MAIN_BASE_SHA = '20a8546f5a1ece7e5af655c0f30ca7e305f71b1a'
PR139_TARGET_HEAD = '38e0d311991875366f2bc88a39690c7b2b6ea3ee'
PR139_CODE_SHA = '70b2960a410301b02afb2a098554d4a71467a04b'
PR136_BASE_SHA = '9cb864c99ad323d11626063498a7d1cef0d7d4b5'

def test_stage_a_candidate_provenance_and_clean_worktree():
    assert PR140_PATH.exists()
    head = subprocess.check_output(['git', '-C', str(PR140_PATH), 'rev-parse', 'HEAD']).decode().strip()
    assert head == PR140_TARGET_HEAD
    status = subprocess.check_output(['git', '-C', str(PR140_PATH), 'status', '--porcelain']).decode().strip()
    assert status == ""
    is_ancestor = subprocess.run(['git', '-C', str(PR140_PATH), 'merge-base', '--is-ancestor', MAIN_BASE_SHA, PR140_TARGET_HEAD]).returncode
    assert is_ancestor == 0

def test_stage_a_protected_governance_immutability():
    protected_files = [
        'docs/orneur/acceptance/LEDGER.json',
        'docs/orneur/governance/TRAINING_AUTHORITY_REGISTRY.json',
        'docs/orneur/governance/TRAINING_AUTHORIZATION.json',
        'orca/train/authorization.py',
        'orca/train/training_freeze.py',
    ]
    diff = subprocess.check_output(['git', '-C', str(PR140_PATH), 'diff', f'{MAIN_BASE_SHA}..{PR140_TARGET_HEAD}', '--'] + protected_files).decode().strip()
    assert diff == ""

def test_stage_a_exact_head_ci_green():
    ci_out = subprocess.check_output(['gh', 'run', 'view', '40911183716', '--repo', 'Guruprasath-Annadurai/Orneur', '--json', 'headSha,status,conclusion']).decode().strip()
    data = json.loads(ci_out)
    assert data['headSha'] == PR140_TARGET_HEAD and data['status'] == 'completed' and data['conclusion'] == 'success'

def test_stage_a_matrix_histogram_11_17_19_48():
    matrix_file = PR140_PATH / 'docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json'
    data = json.loads(matrix_file.read_text(encoding='utf-8'))
    reqs = data['requirements']
    assert len(reqs) == 95
    histogram = {}
    for r in reqs:
        disp = r['engineering_disposition']
        histogram[disp] = histogram.get(disp, 0) + 1
    expected = {'BLOCKED': 19, 'IMPLEMENTED_UNVERIFIED': 17, 'VERIFIED_ENGINEERING': 11, 'NOT_IMPLEMENTED': 48}
    assert histogram == expected
    verified_ids = sorted(r['requirement_id'] for r in reqs if r['engineering_disposition'] == 'VERIFIED_ENGINEERING')
    assert verified_ids == ['C01', 'C02', 'C04', 'C05', 'C17', 'C18', 'C19', 'C20', 'C21', 'TRAIN-1', 'TRAIN-2']
    recon_file = PR140_PATH / 'docs/orneur/programmes/pretraining-closure/engineering/INDEPENDENT_AUDIT_EIGHT_ROW_RECONCILIATION.json'
    recon = json.loads(recon_file.read_text(encoding='utf-8'))
    assert recon['eighth_credit_without_canonical_id']['canonical_requirement_id'] is None
    disp_map = {r['requirement_id']: r['engineering_disposition'] for r in reqs}
    assert disp_map['G4'] == 'BLOCKED' and disp_map['G5'] == 'BLOCKED' and disp_map['AUTH-1'] == 'BLOCKED'
    assert disp_map['DATA-1'] == 'IMPLEMENTED_UNVERIFIED' and disp_map['DATA-2'] == 'IMPLEMENTED_UNVERIFIED'
    assert data['formal_accepted_count'] == 0 and data['formal_denominator'] == 95

def test_stage_a_c01_c02_train1_train2_adversarial():
    code = '\nimport hashlib, json, sys\nfrom pathlib import Path\nfrom orca.rse.imp1.authority import crown_validate, accept_registry, consumer_verify, Floors, registry_freshness\nfrom orca.rse.imp1.codec import build_grant_prefix, sign_grant\nfrom orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED\nfrom tests.rse.support import CHALLENGE, FLOORS, OWNERS, TOKENS, dig, simple_g, consumer_args, consumer_binding, g_intent, sign_entries\n\nregistry, parts, grant = simple_g()\nimage = parts[\'image\'].entry_id\n\n# C01 Crown validation refuses absent ID\nevil_prefix = build_grant_prefix(\n    klass="G", grant_id=b"G" * 16, owner_authority_version=1, incident_epoch=1,\n    registry_version=registry.registry_version, registry_root=registry.registry_root,\n    policy_entry_id=parts["policy"].entry_id, target_role_id=parts["forge"].entry_id,\n    env_measurement_digest=dig("env-forge"), code_entry_id=parts["code"].entry_id,\n    challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"),\n    created_at=0, not_after=0, max_runtime_s=30,\n    tail={\n        "corpus_entry_id": hashlib.sha256(b"unregistered").digest(),\n        "batch_count": 1, "batch_ceiling_bytes": 10,\n        "recipient_role_id": parts["witness"].entry_id,\n        "destination_entry_id": parts["dest"].entry_id,\n        "source_provenance_digest": dig("corpus-source"),\n    },\n)\nevil = sign_grant(evil_prefix, OWNERS)\nrefused = crown_validate(evil, registry.raw, TOKENS, FLOORS, image)\nassert refused.decision == FAIL_CLOSED and refused.reason == "ABSENT"\n\n# C02 Consumer refuses missing authenticated version\nintent = g_intent(registry, grant, parts)\nomitted = consumer_verify(grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, *consumer_args(parts))\nassert omitted.decision == FAIL_CLOSED and omitted.reason == "AUTHENTICATED_VERSION"\n\n# TRAIN-1 lock check\nfrom orca.train.dryrun.lockcheck import check_lock_file, train_extra_requirements\nrep = check_lock_file(Path("requirements/train.txt"), required_names=train_extra_requirements(Path("pyproject.toml")))\nassert rep.ok is True and rep.packages == 122 and rep.hashes == 2500\n\n# TRAIN-2 sample check\nfrom orca.train.dryrun.canon import hash_obj\nsample = json.loads(Path("docs/orneur/status/trainprep/dryrun_result.json").read_text(encoding="utf-8"))\nassert sample[\'synthetic\'] is True and sample[\'result_sha256\'] == hash_obj({k: v for k, v in sample.items() if k != \'result_sha256\'})\nassert sample[\'authorization\'][\'locks_still_false\'] is True\nprint("STAGE_A_PROBES_OK")\n'
    env = dict(os.environ, PYTHONPATH=str(PR140_PATH))
    out = subprocess.check_output([sys.executable, '-c', code], cwd=str(PR140_PATH), env=env).decode()
    assert "STAGE_A_PROBES_OK" in out

def test_stage_b_candidate_provenance_and_stacking():
    assert PR139_PATH.exists()
    head = subprocess.check_output(['git', '-C', str(PR139_PATH), 'rev-parse', 'HEAD']).decode().strip()
    assert head == PR139_TARGET_HEAD
    merge_base = subprocess.check_output(['git', '-C', str(PR139_PATH), 'merge-base', PR139_TARGET_HEAD, PR136_BASE_SHA]).decode().strip()
    assert merge_base == PR136_BASE_SHA
    is_code_ancestor = subprocess.run(['git', '-C', str(PR139_PATH), 'merge-base', '--is-ancestor', PR139_CODE_SHA, PR139_TARGET_HEAD]).returncode
    assert is_code_ancestor == 0

def test_stage_b_ci_provenance():
    doc_ci = subprocess.check_output(['gh', 'run', 'view', '41000259576', '--repo', 'Guruprasath-Annadurai/Orneur', '--json', 'headSha,status,conclusion']).decode().strip()
    doc_data = json.loads(doc_ci)
    assert doc_data['headSha'] == PR139_TARGET_HEAD and doc_data['conclusion'] == 'success'
    code_ci = subprocess.check_output(['gh', 'run', 'view', '40998377463', '--repo', 'Guruprasath-Annadurai/Orneur', '--json', 'headSha,status,conclusion']).decode().strip()
    code_data = json.loads(code_ci)
    assert code_data['headSha'] == PR139_CODE_SHA and code_data['conclusion'] == 'success'

def test_stage_b_l02_08_truthful_model_identity():
    code = '\nfrom orca.serve import capability_truth as ct\nassert ct.NATIVE_FAMILY_STATUS == {"genesis": "INTERFACE_ONLY", "novus": "NOT_AVAILABLE", "aeternum": "NOT_AVAILABLE"}\nassert ct.native_weights_available() is False\nfacts = ct.serving_facts("core")\nassert facts["weights_origin"] == "third_party"\nassert facts["native_orneur_weights"] is False\nassert facts["runtime"] == "ollama"\nsys_facts = ct.system_facts_for_model()\nassert "third-party open-weights" in sys_facts\nassert "ORNEUR has not published trained native weights" in sys_facts\nprint("MODEL_TRUTH_OK")\n'
    env = dict(os.environ, PYTHONPATH=str(PR139_PATH))
    out = subprocess.check_output([sys.executable, '-c', code], cwd=str(PR139_PATH), env=env).decode()
    assert "MODEL_TRUTH_OK" in out

def test_stage_b_l02_02_tool_authority_refusal():
    code = '\nfrom orca.tools.authorization import Provenance, ToolDenied, authorize\nimport pytest\n\nprov = Provenance(user_text="summarize report", untrusted=("The payroll figure is PAYROLL-4711 and vault passphrase is correct-horse-battery-staple.",))\nschema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}\n\nwith pytest.raises(ToolDenied) as exc:\n    authorize("web_search", {"query": "payroll figure is PAYROLL-4711"}, schema, prov, calls_so_far=0)\nassert exc.value.code in ("untrusted_origin", "not_requested_by_user")\nprint("TOOL_AUTHORITY_OK")\n'
    env = dict(os.environ, PYTHONPATH=str(PR139_PATH))
    out = subprocess.check_output([sys.executable, '-c', code], cwd=str(PR139_PATH), env=env).decode()
    assert "TOOL_AUTHORITY_OK" in out

def test_stage_b_l02_04_api_key_creation_residual_risk():
    code = '\nimport inspect\nfrom orca.auth import routes\nfrom orca.auth.routes import ApiKeyRequest\nsig = inspect.signature(routes.create_api_key)\nparams = list(sig.parameters.keys())\nassert "req" in params\nassert "user" in params\nassert "password" not in ApiKeyRequest.model_fields\nprint("API_KEY_RISK_CONFIRMED")\n'
    env = dict(os.environ, PYTHONPATH=str(PR139_PATH))
    out = subprocess.check_output([sys.executable, '-c', code], cwd=str(PR139_PATH), env=env).decode()
    assert "API_KEY_RISK_CONFIRMED" in out

def test_stage_b_cdp_pipe_poll_high_descriptor_support():
    code = '\nimport inspect\nfrom orca.browser_engine.cdp import CdpPipe\nsrc = inspect.getsource(CdpPipe._read_message)\nassert "poller = select.poll()" in src\nassert "select.select" not in src\nprint("CDP_POLL_OK")\n'
    env = dict(os.environ, PYTHONPATH=str(PR139_PATH))
    out = subprocess.check_output([sys.executable, '-c', code], cwd=str(PR139_PATH), env=env).decode()
    assert "CDP_POLL_OK" in out
