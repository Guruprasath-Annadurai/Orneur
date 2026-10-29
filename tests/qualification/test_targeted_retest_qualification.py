"""Independent Targeted Retest Qualification Suite for PR #140.

Authority: ORNEUR CTO
Candidate: PR #140
Target Engineering SHA: 54bb272d4329b59c4694ff5ab41605a7dc6539c7
Target Evidence HEAD: 961caaa39548c911cfec2610c06d1940551cbc6a
CI Reference Run: 40903308415
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

CANDIDATE_PATH = Path('/home/pc/projects/Orneur-pr140-phase01')
TARGET_ENGINEERING_SHA = '54bb272d4329b59c4694ff5ab41605a7dc6539c7'
TARGET_EVIDENCE_HEAD = '961caaa39548c911cfec2610c06d1940551cbc6a'
MAIN_BASE_SHA = '20a8546f5a1ece7e5af655c0f30ca7e305f71b1a'


def test_gate1_candidate_provenance_and_clean_worktree():
    assert CANDIDATE_PATH.exists(), f'{CANDIDATE_PATH} must exist'
    head = subprocess.check_output(['git', '-C', str(CANDIDATE_PATH), 'rev-parse', 'HEAD']).decode().strip()
    assert head == TARGET_EVIDENCE_HEAD, f'Candidate HEAD must match {TARGET_EVIDENCE_HEAD}'

    status = subprocess.check_output(['git', '-C', str(CANDIDATE_PATH), 'status', '--porcelain']).decode().strip()
    assert status == '', 'Candidate worktree must be 100% clean'

    is_ancestor = subprocess.run(
        ['git', '-C', str(CANDIDATE_PATH), 'merge-base', '--is-ancestor', TARGET_ENGINEERING_SHA, TARGET_EVIDENCE_HEAD]
    ).returncode
    assert is_ancestor == 0, 'Engineering SHA must be ancestor of Evidence HEAD'


def test_gate1_protected_governance_files_untouched():
    protected_files = [
        'docs/orneur/acceptance/LEDGER.json',
        'docs/orneur/governance/TRAINING_AUTHORITY_REGISTRY.json',
        'docs/orneur/governance/TRAINING_AUTHORIZATION.json',
        'orca/train/authorization.py',
        'orca/train/training_freeze.py',
    ]
    diff = subprocess.check_output(
        ['git', '-C', str(CANDIDATE_PATH), 'diff', f'{MAIN_BASE_SHA}..{TARGET_EVIDENCE_HEAD}', '--'] + protected_files
    ).decode().strip()
    assert diff == '', 'Protected governance and authorization files must have 0 diff against main'


def test_gate1_evidence_manifest_synchronization():
    matrix_file = CANDIDATE_PATH / 'docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json'
    probes_file = CANDIDATE_PATH / 'docs/orneur/milestones/foundation-02/FOUNDATION_02_VERIFICATION_PROBES.json'
    final_manifest = CANDIDATE_PATH / 'docs/orneur/programmes/pretraining-closure/engineering/FINAL_EVIDENCE_MANIFEST.json'

    m = json.loads(matrix_file.read_text(encoding='utf-8'))
    p = json.loads(probes_file.read_text(encoding='utf-8'))
    f = json.loads(final_manifest.read_text(encoding='utf-8'))

    assert m['candidate_sha'] == TARGET_ENGINEERING_SHA
    assert p['candidate_sha'] == TARGET_ENGINEERING_SHA
    assert f['final_engineering_sha'] == TARGET_ENGINEERING_SHA


def test_gate2_c01_signed_registry_path_refuses_unregistered_id():
    sys.path.insert(0, str(CANDIDATE_PATH))
    from orca.rse.imp1.authority import crown_validate
    from orca.rse.imp1.codec import build_grant_prefix, sign_grant
    from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED
    from tests.rse.support import CHALLENGE, FLOORS, OWNERS, TOKENS, dig, simple_g

    registry, parts, grant = simple_g()
    image = parts['image'].entry_id
    assert crown_validate(grant, registry.raw, TOKENS, FLOORS, image).decision == CHECKS_PASSED

    evil_prefix = build_grant_prefix(
        klass='G',
        grant_id=b'G' * 16,
        owner_authority_version=1,
        incident_epoch=1,
        registry_version=registry.registry_version,
        registry_root=registry.registry_root,
        policy_entry_id=parts['policy'].entry_id,
        target_role_id=parts['forge'].entry_id,
        env_measurement_digest=dig('env-forge'),
        code_entry_id=parts['code'].entry_id,
        challenge=CHALLENGE,
        prev_role_checkpoint=dig('prev-checkpoint'),
        created_at=0,
        not_after=0,
        max_runtime_s=30,
        tail={
            'corpus_entry_id': hashlib.sha256(b'unregistered-id-test').digest(),
            'batch_count': 1,
            'batch_ceiling_bytes': 10,
            'recipient_role_id': parts['witness'].entry_id,
            'destination_entry_id': parts['dest'].entry_id,
            'source_provenance_digest': dig('corpus-source'),
        },
    )
    evil = sign_grant(evil_prefix, OWNERS)
    refused = crown_validate(evil, registry.raw, TOKENS, FLOORS, image)
    assert refused.decision == FAIL_CLOSED
    assert refused.reason == 'ABSENT'


def test_gate2_c02_consumer_refuses_stale_or_unknown_registry():
    sys.path.insert(0, str(CANDIDATE_PATH))
    from orca.rse.imp1.authority import accept_registry, consumer_verify, Floors, registry_freshness
    from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED
    from tests.rse.support import (
        CHALLENGE, FLOORS, TOKENS, consumer_args, consumer_binding, g_intent, sign_entries, simple_g
    )

    registry, parts, grant = simple_g()
    image = parts['image'].entry_id
    intent = g_intent(registry, grant, parts)

    # Valid consumer verification
    ok = consumer_verify(
        grant,
        registry.raw,
        TOKENS,
        FLOORS,
        image,
        intent,
        CHALLENGE,
        *consumer_args(parts),
        **consumer_binding(registry),
    )
    assert ok.decision == CHECKS_PASSED

    # Stale / missing authenticated-version ledger -> FAIL_CLOSED
    omitted = consumer_verify(
        grant,
        registry.raw,
        TOKENS,
        FLOORS,
        image,
        intent,
        CHALLENGE,
        *consumer_args(parts),
    )
    assert omitted.decision == FAIL_CLOSED
    assert omitted.reason == 'AUTHENTICATED_VERSION'

    # Accept unknown / forked successor -> FAIL_CLOSED
    old = sign_entries(list(parts.values()), version=1)
    raised = Floors(2, 1, 1, 1)
    assert registry_freshness(old, raised, None).decision == FAIL_CLOSED
    assert registry_freshness(old, raised, None).reason == 'REGISTRY_FLOOR'

    linked = sign_entries(list(parts.values()), version=2, previous=old.registry_root)
    assert accept_registry(linked.raw, TOKENS, raised, old).decision == CHECKS_PASSED
    forked = bytearray(linked.raw)
    forked[9] ^= 0x01
    assert accept_registry(bytes(forked), TOKENS, raised, old).decision == FAIL_CLOSED


def test_gate3_train1_hash_lock_structure_and_coverage():
    sys.path.insert(0, str(CANDIDATE_PATH))
    from orca.train.dryrun.lockcheck import check_lock_file, train_extra_requirements

    lock_file = CANDIDATE_PATH / 'requirements/train.txt'
    pyproject_file = CANDIDATE_PATH / 'pyproject.toml'

    required = train_extra_requirements(pyproject_file)
    assert set(required) == {
        'accelerate', 'bitsandbytes', 'datasets', 'peft', 'scipy',
        'sentencepiece', 'transformers', 'trl', 'unsloth', 'wandb'
    }

    rep = check_lock_file(lock_file, required_names=required)
    assert rep.ok is True
    assert rep.problems == []
    assert rep.packages == 122
    assert rep.hashes == 2500
    assert rep.sha256 == '5330ae5c5bd3ca4bf35a1a3e9e8dc871dbc344a03bd3dce88a854536551f3733'


def test_gate4_train2_committed_sample_integrity_and_denied_locks():
    sys.path.insert(0, str(CANDIDATE_PATH))
    from orca.train.dryrun.canon import hash_obj

    sample_file = CANDIDATE_PATH / 'docs/orneur/status/trainprep/dryrun_result.json'
    doc = json.loads(sample_file.read_text(encoding='utf-8'))

    assert doc['synthetic'] is True
    assert doc['status'] == 'OK'
    assert doc['git_sha'] == 'cc39fb40c6805d6f1912d129d177d405f2c5f288'
    assert doc['result_sha256'] == hash_obj({k: v for k, v in doc.items() if k != 'result_sha256'})

    auth = doc['authorization']
    assert auth['authorization_files_byte_identical'] is True
    assert auth['locks_still_false'] is True

    funcs = auth['locks_after']['functions']
    for fn in [
        'corpus_generation_authorized', 'qualification_authorized', 'model_selection_authorized',
        'gpu_authorized', 'provider_authorized', 'spending_authorized', 'training_authorized'
    ]:
        assert funcs[fn] is False, f'{fn} must remain False'

    assert doc['gate_probe'] == {'authorized': False, 'reasons': ['NOT_AUTHORIZED']}


def test_gate4_train2_reproduce_synthetic_guard_preflight_failure():
    """Independently reproduce why test_train2_inprocess_dryrun_does_not_flip_locks failed in CI.

    SyntheticOnlyGuard checks sys.modules during _preflight. If a forbidden module
    (such as tokenizers, loaded by previous tests in the runner) is present, it fails closed.
    """
    sys.path.insert(0, str(CANDIDATE_PATH))
    from orca.train.dryrun.sentinel import SyntheticOnlyGuard, SyntheticGuaranteeUnavailable

    guard = SyntheticOnlyGuard(CANDIDATE_PATH / 'tmp_sandbox')
    import tokenizers
    with pytest.raises(SyntheticGuaranteeUnavailable, match='forbidden package.*already imported'):
        guard._preflight()


def test_gate5_full_matrix_integrity_and_counts():
    matrix_file = CANDIDATE_PATH / 'docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json'
    data = json.loads(matrix_file.read_text(encoding='utf-8'))

    requirements = data['requirements']
    assert len(requirements) == 95

    histogram = {}
    for r in requirements:
        c = r['engineering_disposition']
        histogram[c] = histogram.get(c, 0) + 1

    expected_histogram = {
        'BLOCKED': 19,
        'IMPLEMENTED_UNVERIFIED': 17,
        'VERIFIED_ENGINEERING': 11,
        'NOT_IMPLEMENTED': 48,
    }
    assert histogram == expected_histogram, f'Matrix histogram mismatch: {histogram}'

    verified_ids = sorted(r['requirement_id'] for r in requirements if r['engineering_disposition'] == 'VERIFIED_ENGINEERING')
    expected_verified_ids = ['C01', 'C02', 'C04', 'C05', 'C17', 'C18', 'C19', 'C20', 'C21', 'TRAIN-1', 'TRAIN-2']
    assert verified_ids == expected_verified_ids, f'Verified IDs mismatch: {verified_ids}'
    assert data['verified_engineering_ids'] == expected_verified_ids

    assert data['formal_accepted_count'] == 0
    assert data['formal_denominator'] == 95
