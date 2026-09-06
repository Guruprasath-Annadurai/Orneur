from __future__ import annotations

import pytest

from orca.learning.eval_harness import run_all


@pytest.fixture(autouse=True)
def _isolate_learning_registry_dirs(tmp_path, monkeypatch):
    """File-scoped registry isolation -- see test_learning_phase12.py's
    fixture of the same name for why this is not in tests/conftest.py."""
    from tests._learning_registry_isolation import isolate_registry_dirs
    isolate_registry_dirs(tmp_path, monkeypatch)


def test_learning_eval_harness_all_scenarios_pass():
    passed, total = run_all()
    assert total >= 20
    assert passed == total
