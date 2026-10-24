"""Failing-before behavior is closed here. No trusted identity is enrolled."""
from __future__ import annotations

import pytest

from orca.pretrain_foundation.agents import AgentIdentity, Orchestrator, ResultRejected, TaskSpec
from orca.pretrain_foundation.artifact_guard import ArtifactBoundaryError, read_regular_nofollow
from orca.pretrain_foundation.containment import EffectLedger, EffectLedgerError


def _orch() -> Orchestrator:
    orch = Orchestrator(max_concurrent=1, queue_bound=4)
    orch.register_agent(AgentIdentity("root", None, frozenset({"governed"}), 5))
    orch.register_handler("noop", lambda _payload, _ctx: {"ok": True}, "governed")
    orch.submit(TaskSpec("keep", "root", "noop", {}, "keep-key", cost_units=1))
    orch.submit(TaskSpec("bad", "root", "noop", {}, "bad-key", cost_units=1))
    return orch


def test_rejected_snapshot_does_not_mutate_earlier_tasks():
    orch = _orch()
    snap = orch.snapshot()
    snap["tasks"]["keep"]["status"] = "FAILED"
    snap["tasks"]["keep"]["error"] = "mutated"
    snap["tasks"]["bad"]["status"] = "SUCCEEDED"
    snap["tasks"]["bad"]["result"] = "not-a-dict"
    with pytest.raises(ResultRejected, match="stored result"):
        orch.restore_snapshot(snap)
    assert orch.tasks["keep"].status == "QUEUED"
    assert orch.tasks["keep"].error is None
    assert orch.tasks["bad"].status == "QUEUED"


def test_ancestor_symlink_and_dotdot_are_refused(tmp_path):
    real = tmp_path / "real"
    nested = real / "nested"
    nested.mkdir(parents=True)
    target = nested / "file.bin"
    target.write_bytes(b"checkpoint-v1")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert read_regular_nofollow(target) == b"checkpoint-v1"
    with pytest.raises(ArtifactBoundaryError, match="symlink"):
        read_regular_nofollow(link / "nested" / "file.bin")
    parent = tmp_path / "parent-real"
    parent.mkdir()
    (parent / "leaf.bin").write_bytes(b"leaf")
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(parent, target_is_directory=True)
    with pytest.raises(ArtifactBoundaryError, match="symlink"):
        read_regular_nofollow(parent_link / "leaf.bin")
    with pytest.raises(ArtifactBoundaryError, match="non-canonical"):
        read_regular_nofollow(tmp_path / ".." / "file.bin")


def test_durable_effect_ledger_survives_a_new_instance_and_refuses_a_symlink(tmp_path):
    path = tmp_path / "effects.json"
    first = EffectLedger(path)
    assert first.apply("irreversible-1", "sent")["applied"] is True
    second = EffectLedger(path)
    replay = second.apply("irreversible-1", "sent-again")
    assert replay["applied"] is False
    assert replay["duplicate"] is True
    assert replay["effect"] == "sent"
    memory = EffectLedger()
    assert memory.durable is False
    assert memory.apply("irreversible-1", "sent")["durable"] is False
    link = tmp_path / "effects-link.json"
    link.symlink_to(path)
    with pytest.raises(EffectLedgerError, match="regular file"):
        EffectLedger(link)
    path.write_text("{")
    with pytest.raises(EffectLedgerError, match="unreadable"):
        EffectLedger(path)


def test_in_memory_ledger_still_deduplicates_inside_one_process():
    ledger = EffectLedger()
    assert ledger.apply("irreversible-1", "sent")["applied"] is True
    replay = ledger.apply("irreversible-1", "sent-again")
    assert replay["applied"] is False
    assert replay["effect"] == "sent"
