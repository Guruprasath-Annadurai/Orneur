from __future__ import annotations

import pytest

from orca.society.eval_harness import run_all


class _FakeCheckpointRecord:
    def is_routable(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _hermetic_checkpoint_availability(monkeypatch):
    """Phase 15.15 CI truthfulness closure: orca/society/eval_harness.py
    imports `_default_checkpoint_lookup` directly by name (a distinct
    binding from orca.society.router's own module attribute), and
    deliberately uses the REAL default (not a fake) for its deployment/
    circuit-breaker lookups' sibling -- but that real default reads a
    CheckpointRecord from ORCA_HOME/registry/checkpoints/, present on a
    development machine (real historical checkpoint imports) but
    genuinely absent on a fresh CI checkout. This harness's own stated
    purpose (`run_all()`'s scenario matrix) is validating the
    DETERMINISTIC ROUTING/SCORING LOGIC across scenarios, not real
    production model artifact presence (that is `live_ollama_smoke`
    territory, covered separately) -- patched here so the harness
    genuinely runs and validates its logic in CI, matching the
    hermeticity discipline established in tests/test_society_router.py."""
    import orca.society.eval_harness as harness_mod

    monkeypatch.setattr(harness_mod, "_default_checkpoint_lookup", lambda checkpoint_id: _FakeCheckpointRecord())


def test_harness_runs_all_scenarios_deterministically():
    result = run_all()
    assert result.total >= 10
    assert result.pass_rate == 1.0, [r for r in result.results if not r.passed]


def test_harness_names_scenarios_covered_elsewhere_rather_than_faking_them():
    result = run_all()
    assert result.covered_elsewhere  # non-empty: explicit disclosure, not silent omission
