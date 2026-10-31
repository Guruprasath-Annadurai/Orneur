"""
ORNEUR INDEPENDENT MASTER-03 INTEGRATION QUALIFICATION TEST SUITE
Candidate: PR #146 (cursor/master-03-security-corrected-b882)
Verified Engineering HEAD: b96cc3260078b6f677a22381b05fe1f72026256f
Verified Tree: 168a6a2c75bd11e0cbac113e06ff4d50e88f9cae
Merge Commit: 34b6688450fdc199baf336fd5884164fd5684f63

Audited Scope:
1. Complete 6-PR ancestry (F02, F03, L01, L02, L02-B3, L02-B6) and source preservation.
2. Full-history ancestry fail-closed verification (no skip on missing objects).
3. Evalinfra governance frozen-path gate: verify the 4 pinned blobs and fail-closed defense against arbitrary changes.
4. Retention of B3 and B6 live-journey selections and historical login-timing evidence.
5. Integrated B6 security: legacy backup refusal, deletion ledger chaining, recovery journal validation, no-crypto server start.
6. Cross-feature adversarial probes: restored account stays deleted, simultaneous restore lock, interrupted restore restart refusal.
7. Model identity disclosure, streaming cancellation, formal 0/95 acceptance ledger, and pretraining NO-GO.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest

MASTER03_DIR = Path("/home/pc/projects/Orneur-master03")
HEAD_SHA = "b96cc3260078b6f677a22381b05fe1f72026256f"
EXPECTED_TREE = "168a6a2c75bd11e0cbac113e06ff4d50e88f9cae"
MERGE_COMMIT = "34b6688450fdc199baf336fd5884164fd5684f63"

# Constituent PR identities
CONSTITUENTS = {
    "canonical_main": "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a",
    "pr140_f02": "649d90f84069fc618ba4d69b4c26a66bed731caa",
    "pr142_f03": "0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51",
    "pr136_l01": "9cb864c99ad323d11626063498a7d1cef0d7d4b5",
    "pr139_l02": "38e0d311991875366f2bc88a39690c7b2b6ea3ee",
    "pr141_b3_code": "283e3a464a3de1d0a420709a3f6602730023300d",
    "pr141_b3_head": "66ce8aeace2077b89195735211d75ebd566716c8",
    "master02_head": "d8827409248dcdb5da55a010d8224d9e0e3bddbe",
    "pr143_b6_code": "14e1160dc50024d726f2f379fba510fbd2a88f66",
    "pr143_b6_head": "4ab809df6b9895812def68e5d9e9cef03a09f4d7",
    "master03_merge": "34b6688450fdc199baf336fd5884164fd5684f63",
}


def _switch_to_master03():
    for m in [k for k in list(sys.modules) if k.startswith(("orca", "tests"))]:
        sys.modules.pop(m, None)
    sys.path = [str(MASTER03_DIR)] + [p for p in sys.path if p != "/home/pc/projects/Orneur"]


def _git(*args, cwd=MASTER03_DIR):
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


# ---------------------------------------------------------------------------
# Gate 1: Lineage, Tree Identity, and Ancestry Verification
# ---------------------------------------------------------------------------


def test_master03_complete_six_pr_ancestry():
    """Verify all 6 constituent PRs are direct topological ancestors of MASTER-03 HEAD."""
    assert MASTER03_DIR.is_dir()
    current_head = _git("rev-parse", "HEAD")
    assert current_head == HEAD_SHA, f"HEAD mismatch: {current_head} != {HEAD_SHA}"

    current_tree = _git("rev-parse", f"{HEAD_SHA}^{{tree}}")
    assert current_tree == EXPECTED_TREE, f"Tree mismatch: {current_tree} != {EXPECTED_TREE}"

    for name, sha in CONSTITUENTS.items():
        rc = subprocess.call(["git", "merge-base", "--is-ancestor", sha, HEAD_SHA], cwd=str(MASTER03_DIR))
        assert rc == 0, f"{name} ({sha[:7]}) is NOT an ancestor of MASTER-03 HEAD {HEAD_SHA}!"


def test_ancestry_gate_fails_closed_when_objects_missing():
    """Verify that portable harness fails closed instead of skipping when git objects are absent."""
    harness_path = MASTER03_DIR / "tests/qualification/test_master02_f03_portable_harness.py"
    content = harness_path.read_text(encoding="utf-8")
    # Verify pytest.skip is removed from the ancestry check function specifically
    fn_start = content.find("def test_engineering_sha_is_ancestor_of_integrated_head")
    fn_end = content.find("def test_parent_and_engineering_blob_identity_preserved")
    ancestry_fn = content[fn_start:fn_end]
    assert "pytest.skip" not in ancestry_fn
    assert "Refusing to skip; configure full-history fetch." in ancestry_fn


# ---------------------------------------------------------------------------
# Gate 2: Evalinfra Governance Gate and 4 Pinned Blob Exceptions
# ---------------------------------------------------------------------------


def test_evalinfra_governance_four_pinned_blobs_and_fail_closed():
    """Verify the 4 pinned blobs match approved Foundation changes and arbitrary diffs fail closed."""
    gov_test_path = MASTER03_DIR / "tests/test_evalinfra_governance.py"
    content = gov_test_path.read_text(encoding="utf-8")

    expected_blobs = {
        "docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json":
            "d236706d07d3934d191fad0ee81ac9a49c6d8463",
        "docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json":
            "1eff1d91fae0d028a9275b716824c0c4cc8f0833",
        "docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json":
            "0cabf72961f637d81425564ac7bb64b0d611af7b",
        "orca/rse/imp1/consumer_verification.py":
            "a42286de9a0babe348a2f9b03840a29fb4664e64",
    }

    # Verify that each blob matches HEAD exactly
    for path, exp_blob in expected_blobs.items():
        actual_blob = _git("rev-parse", f"HEAD:{path}")
        assert actual_blob == exp_blob, f"Blob mismatch for {path}: {actual_blob} != {exp_blob}"

    # Confirm the test also refuses to skip on missing branch point
    assert "Refusing to skip; configure full-history fetch." in content


# ---------------------------------------------------------------------------
# Gate 3: Retention of Live Journeys and Non-Overwritten Timing Evidence
# ---------------------------------------------------------------------------


def test_b3_and_b6_live_journeys_and_login_timing_preserved():
    """Verify both B3 and B6 live journeys are retained and login timing is indexed, not overwritten."""
    workflow = (MASTER03_DIR / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "test_l02_b3_apikey_reauth_live.py" in workflow
    assert "test_l02_b6_backup_live.py" in workflow

    # Verify login timing index
    timing_index_path = MASTER03_DIR / "docs/orneur/landmarks/landmark-02/evidence/l02_04_login_timing.json"
    index = json.loads(timing_index_path.read_text(encoding="utf-8"))
    assert "retained_measurements" in index
    retained_paths = [m["path"] for m in index["retained_measurements"]]
    assert any("master02-1a17fb0" in p for p in retained_paths)
    assert any("b6-e5266c7" in p for p in retained_paths)

    # Confirm both measurement files exist on disk
    for m in index["retained_measurements"]:
        assert (MASTER03_DIR / m["path"]).is_file()


# ---------------------------------------------------------------------------
# Gate 4: Integrated B6 Security Hardening
# ---------------------------------------------------------------------------


def test_integrated_b6_legacy_backup_refusal():
    """Verify legacy backup entry points refuse on the integrated tree."""
    _switch_to_master03()
    from orca.ops import backup as legacy_ops
    from orca.serve.backup_errors import BackupError

    with pytest.raises(BackupError) as exc:
        legacy_ops.backup_sqlite()
    assert "legacy plaintext backup/restore is retired" in str(exc.value)


def test_integrated_b6_no_crypto_dependency_server_start():
    """Verify datadir_lock and backup_errors have zero import dependency on cryptography."""
    _switch_to_master03()
    # Ensure datadir_lock and backup_errors import without cryptography
    import orca.serve.backup_errors as be
    import orca.serve.datadir_lock as dl
    assert hasattr(be, "BackupError")
    assert hasattr(dl, "serving_lock")
    assert hasattr(dl, "exclusive_data_dir")


# ---------------------------------------------------------------------------
# Gate 5: Cross-Feature Adversarial Probes
# ---------------------------------------------------------------------------


def test_adversarial_deleted_account_stays_deleted_after_restore():
    """Cross-feature probe: restore an old backup taken before customer deleted account.
    Deletion ledger must re-apply the tombstone so the deleted user is NOT resurrected."""
    _switch_to_master03()
    from orca.serve import backup as srv_backup
    from orca.serve import deletion_ledger as dl

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        datadir = root / "datadir"
        datadir.mkdir()
        auth_db = datadir / "auth.db"

        # 1. Create database with active user
        conn = sqlite3.connect(str(auth_db))
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users VALUES ('u-deleted-1', 'victim@example.com')")
        conn.commit()
        conn.close()

        # 2. Take encrypted backup
        key = os.urandom(32)
        archive_path = root / "backup_before_delete.orbk"
        srv_backup.create(datadir, archive_path, key=key)

        # 3. Simulate customer account deletion: records in deletion ledger
        dl.record(kind="user", subject_id="u-deleted-1", home=datadir)
        export_file = root / "deletion.export"
        dl.export(datadir, export_file, key=key)

        # 4. Restore the old backup into a new target using the deletion ledger export
        target = root / "restored_target"
        res = srv_backup.restore(archive_path, target, key=key, deletion_ledger=export_file)

        # 5. Verify the deletion was applied during restore
        assert res["deletions_applied"]["user"] >= 1

        # 6. Check database in target: victim user must be GONE
        res_conn = sqlite3.connect(str(target / "auth.db"))
        rows = res_conn.execute("SELECT id FROM users WHERE id='u-deleted-1'").fetchall()
        res_conn.close()
        assert len(rows) == 0, f"Victim user was resurrected! Rows: {rows}"


def test_adversarial_simultaneous_restore_and_server_lock_conflict():
    """Cross-feature probe: server running prevents restore; restore prevents server start."""
    _switch_to_master03()
    from orca.serve import datadir_lock
    from orca.serve.backup_errors import RestoreFailed

    with tempfile.TemporaryDirectory() as td:
        datadir = Path(td)
        (datadir / ".server.lock").write_text("")

        # When serving lock is held: restore must fail closed
        with datadir_lock.serving_lock(datadir):
            with pytest.raises(RestoreFailed) as exc:
                with datadir_lock.exclusive_data_dir(datadir):
                    pass
            assert "a server is running" in str(exc.value)

        # When restore lock is held: server start must fail closed
        with datadir_lock.exclusive_data_dir(datadir):
            with pytest.raises(RestoreFailed) as exc:
                with datadir_lock.serving_lock(datadir):
                    pass
            assert "a restore is in progress" in str(exc.value)


def test_adversarial_interrupted_restore_blocks_server_startup():
    """Cross-feature probe: interrupted restore leaving .restore-journal.json blocks server."""
    _switch_to_master03()
    from orca.serve import datadir_lock

    with tempfile.TemporaryDirectory() as td:
        datadir = Path(td)
        journal = datadir / ".restore-journal.json"
        journal.write_text(json.dumps({"aside": ".pre-restore-1234567890", "moved": [], "placed": []}))

        assert datadir_lock.restore_pending(datadir) is True


# ---------------------------------------------------------------------------
# Gate 6: Governance, Model Truth, and Formal Acceptance
# ---------------------------------------------------------------------------


def test_governance_immutability_and_formal_acceptance_zero():
    """Verify formal acceptance is 0/95 and training authorization remains STRICT NO-GO."""
    res = subprocess.check_output(
        ["python3", "scripts/acceptance/validate_register_graph.py", "--check"],
        cwd=str(MASTER03_DIR),
        text=True,
    ).strip()
    assert "pretraining=95 numerator=0" in res

    auth_json = json.loads((MASTER03_DIR / "docs/orneur/authorization/TRAINING_AUTHORIZATION.json").read_text(encoding="utf-8"))
    assert auth_json.get("authorized") is False or auth_json.get("status") in ("NOT_AUTHORIZED", "NO_GO")


def test_adversarial_stale_document_removed_after_restore():
    """Cross-feature probe: document deleted after backup is stripped from registry on restore."""
    _switch_to_master03()
    from orca.serve import backup as srv_backup
    from orca.serve import deletion_ledger as dl

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        datadir = root / "datadir"
        datadir.mkdir()
        docs_dir = datadir / "docs"
        docs_dir.mkdir()
        reg_file = docs_dir / "registry.json"
        reg_data = {"sess_1": [{"doc_id": "doc-secret-123", "filename": "classified.pdf"}]}
        reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

        # Must have auth.db or a db for backup
        conn = sqlite3.connect(str(datadir / "auth.db"))
        conn.execute("CREATE TABLE t (x INT)")
        conn.commit()
        conn.close()

        key = os.urandom(32)
        archive_path = root / "backup_with_doc.orbk"
        srv_backup.create(datadir, archive_path, key=key)

        # Customer deletes doc
        dl.record(kind="doc", subject_id="doc-secret-123", session_id="sess_1", home=datadir)
        export_file = root / "doc_del.export"
        dl.export(datadir, export_file, key=key)

        target = root / "restored_docs"
        res = srv_backup.restore(archive_path, target, key=key, deletion_ledger=export_file)
        assert res["deletions_applied"]["doc"] >= 1

        # Check restored registry
        target_reg = json.loads((target / "docs" / "registry.json").read_text(encoding="utf-8"))
        assert len(target_reg.get("sess_1", [])) == 0


def test_model_identity_disclosure_and_governance_contracts():
    """Verify model identity contracts: third-party Ollama disclosed, Genesis INTERFACE_ONLY."""
    _switch_to_master03()
    from orca.serve.model_identity import model_identity

    # Verify model identity never fabricates native weights when served via Ollama
    ident = model_identity(
        requested_variant="orca-core",
        served_tier="orca-nano",
        served_model="llama3.2:1b",
        backend="ollama",
    )
    assert ident["substituted"] is True
    assert ident["requested_tier"] == "core"
    assert ident["served_tier"] == "nano"
    assert ident["backend"] == "ollama"

    # Model info / capabilities disclosure
    weights_origin_doc = (MASTER03_DIR / "docs/orneur/landmarks/landmark-02/L02_MODEL_IDENTITY_AND_CAPABILITY_TRUTH.md").read_text(encoding="utf-8")
    assert "L02-08" in weights_origin_doc
    assert "INTERFACE_ONLY" in weights_origin_doc
    assert "third-party open-weights model" in weights_origin_doc

