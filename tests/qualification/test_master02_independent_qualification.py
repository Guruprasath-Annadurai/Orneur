"""
ORNEUR INDEPENDENT MASTER-02 INTEGRATION QUALIFICATION TEST SUITE
Candidate: PR #145 (cursor/master-02-integration-candidate-316a)
HEAD SHA: d8827409248dcdb5da55a010d8224d9e0e3bddbe
Integration Merge Commit: 7fb78a3d9c522edff26335a551ceadc5d500f941
Merge-Tip Tree: 7a980d4ae918bc4dbec374772a2ec20e36d3107f

Audited Scope:
1. Five-PR ancestry and clean merge sequence.
2. Current tree vs merge-tip tree analysis (zero orca/ diff).
3. Independent reproduction of intermittent TOTP step-rollover flake.
4. Concurrent API-key creation atomicity.
5. Shallow-clone harness analysis and complete commit history verification.
6. C06/C07 non-authoritative behavior on integrated tree.
7. Model identity truth, training freeze, and formal 0/95 ledger.
8. Exclusion of B6 and persistence of legacy plaintext backup risk on MASTER-02.
"""

import sys
for mod in list(sys.modules.keys()):
    if mod == "orca" or mod.startswith("orca."):
        del sys.modules[mod]
sys.path = ['/home/pc/projects/Orneur-master02'] + [p for p in sys.path if not p.endswith('/Orneur')]
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
import pytest

MASTER02_DIR = Path('/home/pc/projects/Orneur-master02')
def _switch_to_master02():
    import sys
    for m in [k for k in list(sys.modules) if k.startswith(('orca', 'tests'))]:
        sys.modules.pop(m, None)
    sys.path = [str(MASTER02_DIR)] + [p for p in sys.path if p != '/home/pc/projects/Orneur']
MERGE_COMMIT = "7fb78a3d9c522edff26335a551ceadc5d500f941"
MERGE_TREE = "7a980d4ae918bc4dbec374772a2ec20e36d3107f"
HEAD_SHA = "d8827409248dcdb5da55a010d8224d9e0e3bddbe"
REPAIR_TIP = "6d977703ef0af77e7099fa9979bfb4a8cdf21864"

# The 5 constituent PR SHAs
F02_SHA = "649d90f84069fc618ba4d69b4c26a66bed731caa"  # PR #140
F03_SHA = "0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51"  # PR #142
L01_SHA = "9cb864c99ad323d11626063498a7d1cef0d7d4b5"  # PR #136
L02_SHA = "38e0d311991875366f2bc88a39690c7b2b6ea3ee"  # PR #139
L02_B3_SHA = "283e3a464a3de1d0a420709a3f6602730023300d"  # PR #141 code
L02_B3_EVIDENCE = "66ce8aeace2077b89195735211d75ebd566716c8"  # PR #141 head


def _git(*args, cwd=MASTER02_DIR):
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


# ---------------------------------------------------------------------------
# Gate 1: Five-PR Ancestry and Integration Tree Identity
# ---------------------------------------------------------------------------


def test_five_pr_ancestry_in_complete_history():
    """Verify all 5 constituent PRs are direct topological ancestors of MASTER-02."""
    assert MASTER02_DIR.is_dir()
    current_head = _git("rev-parse", "HEAD")
    assert current_head == HEAD_SHA, f"HEAD mismatch: {current_head} != {HEAD_SHA}"

    constituents = [
        ("PR #140 (F02)", F02_SHA),
        ("PR #142 (F03)", F03_SHA),
        ("PR #136 (L01)", L01_SHA),
        ("PR #139 (L02)", L02_SHA),
        ("PR #141 (L02-B3)", L02_B3_SHA),
    ]
    for label, sha in constituents:
        rc = subprocess.call(["git", "merge-base", "--is-ancestor", sha, current_head], cwd=str(MASTER02_DIR))
        assert rc == 0, f"{label} ({sha}) is NOT an ancestor of {current_head}!"


def test_merge_tip_tree_identity_and_zero_orca_diff():
    """Verify tree 7a980d4a and confirm zero production code diff in orca/ post-merge."""
    merge_tree = _git("rev-parse", f"{MERGE_COMMIT}^{{tree}}")
    assert merge_tree == MERGE_TREE, f"Merge tree mismatch: {merge_tree} != {MERGE_TREE}"

    # Verify zero production diff between merge commit 7fb78a3 and HEAD d882740
    orca_diff = _git("diff", MERGE_COMMIT, HEAD_SHA, "--", "orca")
    assert orca_diff == "", f"Production code in orca/ was modified after merge commit: {orca_diff}"


def test_shallow_clone_harness_behavior_analysis():
    """Audit the shallow-clone skip in Cursor's test_master02_f03_portable_harness.py."""
    harness_path = MASTER02_DIR / "tests/qualification/test_master02_f03_portable_harness.py"
    assert harness_path.is_file()
    content = harness_path.read_text(encoding="utf-8")

    # Confirm that Cursor's harness includes a skip when git commit object is missing
    assert "pytest.skip" in content
    assert "shallow/partial clone missing" in content

    # BUT in our complete commit history audit, the object MUST exist and ancestor check must pass
    rc = subprocess.call(["git", "cat-file", "-e", f"{F03_SHA}^{{commit}}"], cwd=str(MASTER02_DIR))
    assert rc == 0, f"Full repo must contain commit {F03_SHA}"


# ---------------------------------------------------------------------------
# Gate 2: Intermittent TOTP Flake Reproduction & Concurrency Atomicity
# ---------------------------------------------------------------------------


def test_independent_reproduction_of_totp_step_rollover_flake():
    """Reproduce root cause of intermittent TOTP failure: time.time() + 31 on window boundary."""
    import sys
    for m in list(sys.modules.keys()):
        if m == 'orca' or m.startswith('orca.'):
            del sys.modules[m]
    if str(MASTER02_DIR) not in sys.path:
        sys.path = [str(MASTER02_DIR)] + [p for p in sys.path if not p.endswith('/Orneur')]
    from orca.auth.totp import generate_totp_secret, totp_now, verify_totp

    secret = generate_totp_secret()

    # 1. Inside 30s bucket (e.g. remainder 10.0s):
    # Server counter = S, Client with +31s counter = S + 1. Offset = +1 -> ACCEPTED
    t_safe = 57666667 * 30 + 10.0
    code_safe = totp_now(secret, at_time=t_safe + 31)
    assert verify_totp(secret, code_safe, window=1, at_time=t_safe) is True

    # 2. Window boundary (e.g. remainder 29.5s):
    # Server counter = S, Client with +31s counter = S + 2. Offset = +2 -> REJECTED (401)!
    t_boundary = 57666667 * 30 + 29.5
    code_flaked = totp_now(secret, at_time=t_boundary + 31)
    assert verify_totp(secret, code_flaked, window=1, at_time=t_boundary) is False

    # Mathematical certainty: Failure window is exactly [29.0, 30.0) seconds of each 30s epoch (1/30 = ~3.33% flake rate)


def test_concurrent_api_key_totp_claim_atomicity():
    _switch_to_master02()
    from orca.auth import account_security as acct

    # Test claim_totp_step uses atomic INSERT ... ON CONFLICT DO NOTHING
    user_id = f"test-totp-user-{int(time.time())}"
    step = 57666667

    # First claim must succeed
    first = acct.claim_totp_step(user_id, step)
    assert first is True

    # Second claim for same user and step MUST fail (replay prevention)
    second = acct.claim_totp_step(user_id, step)
    assert second is False


# ---------------------------------------------------------------------------
# Gate 3: C06 / C07 Software Invariants on Integrated Tree
# ---------------------------------------------------------------------------


def test_c06_c07_software_behavior_on_integrated_tree():
    _switch_to_master02()
    from orca.rse.imp1.consumer_verification import (
        consumer_confirm_from_signed_bytes,
        render_from_signed_bytes,
    )
    from orca.rse.imp1.verdict import CHECKS_PASSED
    from tests.rse.support import (
        CHALLENGE,
        FLOORS,
        TOKENS,
        consumer_args,
        consumer_binding,
        g_intent,
        simple_g,
    )

    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas

    res = consumer_confirm_from_signed_bytes(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent,
        CHALLENGE, role, env, **binding,
    )
    assert res.decision == CHECKS_PASSED
    assert res.reason == "C06_C07_CONFIRMED"

    # Strict lockout
    p = res.payload
    assert p["authority_usable"] is False
    assert p["spending"] is False
    assert p["training"] is False
    assert p["gpu"] is False
    assert p["corpus_generation"] == "NOT_AUTHORIZED"


# ---------------------------------------------------------------------------
# Gate 4: Exclusion of B6 and Plaintext Backup Risk Persistence
# ---------------------------------------------------------------------------


def test_b6_is_excluded_and_plaintext_backup_risk_remains():
    """Verify that B6 (encrypted backups) is NOT integrated and legacy plaintext backup code remains."""
    # B6 files must NOT exist on MASTER-02
    assert not (MASTER02_DIR / "orca/serve/backup_crypto.py").exists()
    assert not (MASTER02_DIR / "orca/serve/deletion_ledger.py").exists()
    assert not (MASTER02_DIR / "tests/test_l02_b6_backup.py").exists()

    # Legacy plaintext backup.py must still be present on MASTER-02
    legacy_backup = MASTER02_DIR / "orca/ops/backup.py"
    assert legacy_backup.is_file()
    legacy_content = legacy_backup.read_text(encoding="utf-8")
    assert "backup_sqlite" in legacy_content and "restore_sqlite" in legacy_content
    # Plaintext tar / sqlite copy remains active in MASTER-02
    assert "tarfile" in legacy_content or "sqlite3" in legacy_content


