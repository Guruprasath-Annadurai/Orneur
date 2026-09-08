"""
Phase 15.9 -- real test-collection comparison via git worktree + pytest
--collect-only (spec section 4).
"""
from __future__ import annotations

import subprocess

import pytest

from orca.mission.test_collection_diff import collect_test_ids_at_revision, compare_collections


def _run(args, cwd):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _run(["init", "-q"], cwd=str(repo_dir))
    _run(["config", "user.email", "test@example.com"], cwd=str(repo_dir))
    _run(["config", "user.name", "Test"], cwd=str(repo_dir))
    return repo_dir


def _commit(repo_dir, files: dict, message: str) -> str:
    for path, content in files.items():
        full = repo_dir / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    _run(["add", "-A"], cwd=str(repo_dir))
    _run(["commit", "-q", "-m", message], cwd=str(repo_dir))
    return _run(["rev-parse", "HEAD"], cwd=str(repo_dir)).strip()


def test_real_collection_shrinks_when_a_test_is_removed(repo):
    baseline = _commit(repo, {
        "tests/test_a.py": "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n",
    }, "baseline: two tests")
    candidate = _commit(repo, {
        "tests/test_a.py": "def test_one():\n    assert True\n",
    }, "candidate: removed test_two")

    baseline_ids = collect_test_ids_at_revision(str(repo), baseline)
    candidate_ids = collect_test_ids_at_revision(str(repo), candidate)

    assert any("test_one" in i for i in baseline_ids)
    assert any("test_two" in i for i in baseline_ids)
    assert any("test_two" in i for i in candidate_ids) is False

    delta = compare_collections(baseline_ids, candidate_ids)
    assert delta.collection_shrank is True
    assert any("test_two" in i for i in delta.removed)


def test_real_collection_grows_when_a_test_is_added(repo):
    baseline = _commit(repo, {"tests/test_a.py": "def test_one():\n    assert True\n"}, "baseline")
    candidate = _commit(repo, {
        "tests/test_a.py": "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n",
    }, "candidate: added test_two")

    baseline_ids = collect_test_ids_at_revision(str(repo), baseline)
    candidate_ids = collect_test_ids_at_revision(str(repo), candidate)
    delta = compare_collections(baseline_ids, candidate_ids)

    assert delta.collection_shrank is False
    assert any("test_two" in i for i in delta.added)
