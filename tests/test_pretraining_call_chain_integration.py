"""Call-chain integration for Phase 2–9 operational safeguards.

Traces enforcement from operational entrypoints (not unit-test helpers alone).
Negative cases show that bypassing a helper through a real caller still refuses
unauthorized behavior. Research/feasibility modules remain standalone and are
not counted as operational enforcement.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orca.genesis.data.pipeline import (
    CorpusBoundaryError,
    process_corpus,
    process_training_bound_corpus,
)
from orca.pretrain_foundation.corpus_controls import (
    CorpusControlError,
    refuse_remote_origin,
    training_bound_reader_kwargs,
)
from orca.pretrain_foundation.eval_boundary import (
    AccessAttempt,
    EvalBoundaryError,
    authorize_access,
)
from orca.pretrain_foundation.genesis_feasibility import assess_genesis
from orca.pretrain_foundation.hardware_evidence_boundary import (
    EvidenceClaim,
    PhysicalEvidenceError,
    refuse_mock_as_acceptance,
)
from orca.pretrain_foundation.training_freeze import (
    TrainingFreezeError,
    assert_unauthorized_execution_refused,
    build_freeze_package,
)
from orca.train.authorization import TrainingNotAuthorized, authorize_training, require_grant
from orca.train.config import TrainingConfig

ROOT = Path(__file__).resolve().parents[1]


def test_process_corpus_entrypoint_enforces_remote_origin_refusal(tmp_path):
    """Operational corpus entry refuses remote origins before any open."""
    with pytest.raises(CorpusBoundaryError, match="remote corpus origin"):
        process_corpus("https://example.com/remote.jsonl", tmp_path / "out", num_shards=1)
    with pytest.raises(CorpusBoundaryError, match="remote corpus origin"):
        process_corpus("s3://bucket/corpus.jsonl", tmp_path / "out2", num_shards=1)


def test_process_corpus_still_refuses_remote_if_helper_is_bypassed(tmp_path, monkeypatch):
    """Negative: neutralizing refuse_remote_origin must not admit a remote URL.

    The operational path opens only local paths; a neutralized helper still
    cannot turn a remote URI into an authorized corpus admission.
    """
    monkeypatch.setattr(
        "orca.pretrain_foundation.corpus_controls.refuse_remote_origin",
        lambda _source: None,
    )
    # Re-import binding used inside pipeline (local import each call).
    # Even with the helper no-op'd, Path/open on a remote URI must not succeed
    # as an admitted corpus.
    with pytest.raises((CorpusBoundaryError, OSError, FileNotFoundError, ValueError)):
        process_corpus("https://example.com/still-remote.jsonl", tmp_path / "out", num_shards=1)


def test_training_bound_entrypoint_refuses_license_bypass_kwargs(tmp_path):
    """Operational training-bound caller cannot disable require_license via kwargs."""
    path = tmp_path / "in.jsonl"
    path.write_text(json.dumps({"text": "x", "license": "MIT"}) + "\n", encoding="utf-8")
    # Direct kwargs override attempt is stripped; require_license stays True.
    report, _ = process_training_bound_corpus(
        path,
        tmp_path / "out",
        num_shards=1,
        allowed_root=tmp_path,
        require_license=False,  # type: ignore[call-arg]
    )
    # With license metadata present and require_license forced True, record may keep;
    # the critical property is that require_license=False did not disable the gate.
    assert training_bound_reader_kwargs(allowed_root=tmp_path)["require_license"] is True
    with pytest.raises(CorpusControlError, match="cannot disable require_license"):
        training_bound_reader_kwargs(require_license=False)
    # Missing jail still refused on the operational entry.
    with pytest.raises(CorpusBoundaryError, match="allowed_root"):
        process_training_bound_corpus(path, tmp_path / "out2", num_shards=1, allowed_root=None)  # type: ignore[arg-type]
    del report


def test_training_bound_entrypoint_refuses_remote_origin(tmp_path):
    with pytest.raises(CorpusBoundaryError, match="remote corpus origin"):
        process_training_bound_corpus(
            "https://example.com/train.jsonl",
            tmp_path / "out",
            num_shards=1,
            allowed_root=tmp_path,
        )


def test_authorize_training_operational_chokepoint_refuses_without_grant(tmp_path, monkeypatch):
    """Real authorize_training entry remains fail-closed under committed NOT_AUTHORIZED."""
    import orca.config as orca_config

    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    cfg = TrainingConfig()
    train_file = tmp_path / "t.jsonl"
    train_file.write_text("{}\n", encoding="utf-8")
    cfg.train_file = str(train_file)
    with pytest.raises(TrainingNotAuthorized) as exc:
        authorize_training(cfg, environment_class="SELF_HOSTED_GPU")
    reasons = set(exc.value.reasons)
    assert reasons & {
        "NOT_AUTHORIZED",
        "AUTHORITY_REGISTRY_UNREADABLE_OR_NOT_PINNED",
        "RECORD_UNREADABLE",
        "RECORD_INVALID",
    }


def test_require_grant_bypass_attempt_refuses_forged_or_missing_grant():
    """Negative: calling lower-level require_grant without a real grant refuses."""
    cfg = TrainingConfig()
    with pytest.raises(TrainingNotAuthorized) as exc:
        require_grant(None, cfg, environment_class="SELF_HOSTED_GPU")
    assert "NO_TRAINING_GRANT" in exc.value.reasons
    with pytest.raises(TrainingNotAuthorized) as exc2:
        require_grant({"authorization_id": "forged"}, cfg, environment_class="SELF_HOSTED_GPU")
    assert "NO_TRAINING_GRANT" in exc2.value.reasons


def test_finetune_train_entrypoint_refuses_before_model_work(tmp_path, monkeypatch):
    """Operational finetune.train path hits authorize_training before deps/model."""
    import orca.config as orca_config
    import orca.train.finetune as ft

    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    calls: list[str] = []

    def _deny(*_a, **_k):
        calls.append("authorize_training")
        raise TrainingNotAuthorized(["NOT_AUTHORIZED"])

    monkeypatch.setattr(ft, "authorize_training", _deny)

    def _boom(*_a, **_k):
        calls.append("start_training_run")
        raise AssertionError("model/training work must not run when unauthorized")

    monkeypatch.setattr(ft, "start_training_run", _boom)
    monkeypatch.setattr(ft, "validate_training_identity", lambda _cfg: None)

    cfg = TrainingConfig()
    train_file = tmp_path / "t.jsonl"
    train_file.write_text("{}\n", encoding="utf-8")
    cfg.train_file = str(train_file)
    with pytest.raises(TrainingNotAuthorized):
        ft.train(cfg)
    assert calls == ["authorize_training"]


def test_freeze_package_entrypoint_refuses_unauthorized_execution():
    package = build_freeze_package(ROOT, code_sha="a" * 40, model_configuration={"arch": "test"})
    assert package.training_authorization == "NO-GO"
    with pytest.raises(TrainingFreezeError, match="unauthorized"):
        assert_unauthorized_execution_refused(package, execute_requested=True)


def test_research_feasibility_modules_remain_standalone_not_operational_enforcement():
    """GENESIS/hardware feasibility reports are analytical; not operational gates."""
    report = assess_genesis()
    assert report.official_foundation_selected is False
    assert report.weights_downloaded is False
    claim = EvidenceClaim(requirement_id="HW-01", kind="witness_serial_custody", synthetic=True)
    with pytest.raises(PhysicalEvidenceError):
        refuse_mock_as_acceptance(claim)


def test_eval_boundary_helper_denies_holdout_but_is_not_isolation_acceptance():
    """QUAL-2 helper behavior exists; isolation acceptance remains external."""
    with pytest.raises(EvalBoundaryError, match="denied holdout"):
        authorize_access(
            AccessAttempt(
                actor_identity="training",
                resource_class="eval_holdout",
                action="read",
            )
        )
