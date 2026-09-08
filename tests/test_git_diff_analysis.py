"""Phase 15.9 -- real git diff analysis tests."""
from __future__ import annotations

import subprocess

import pytest

from orca.mission.git_diff_analysis import GitDiffError, get_diff_summary, read_file_at_revision


def _run(args, cwd):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
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


def test_added_deleted_modified_classified_correctly(repo):
    # b.py and c.py are given genuinely DIFFERENT content -- if they
    # were identical, git's own -M rename detection would (correctly)
    # treat "b.py deleted, c.py added with the same content" as a
    # rename rather than an unrelated add+delete, which would make
    # this test's own fixture, not the code under test, wrong.
    baseline = _commit(repo, {"a.py": "1", "b.py": "content-only-in-b\n" * 5}, "baseline")
    (repo / "b.py").unlink()
    candidate = _commit(repo, {"a.py": "2", "c.py": "totally-different-content-in-c\n" * 5}, "candidate")

    summary = get_diff_summary(str(repo), baseline, candidate)
    assert summary.added_files == ("c.py",)
    assert summary.deleted_files == ("b.py",)
    assert summary.modified_files == ("a.py",)


def test_rename_detected_not_deletion(repo):
    baseline = _commit(repo, {"old.py": "def f():\n    return 1\n"}, "baseline")
    _run(["mv", "old.py", "new.py"], cwd=str(repo))
    candidate = _commit(repo, {}, "rename")

    summary = get_diff_summary(str(repo), baseline, candidate)
    assert len(summary.renamed_files) == 1
    assert summary.renamed_files[0].old_path == "old.py"
    assert summary.renamed_files[0].new_path == "new.py"
    assert "old.py" not in summary.deleted_files


def test_read_file_at_revision_returns_real_content(repo):
    baseline = _commit(repo, {"a.py": "VERSION = 1\n"}, "baseline")
    candidate = _commit(repo, {"a.py": "VERSION = 2\n"}, "candidate")

    assert read_file_at_revision(str(repo), baseline, "a.py") == "VERSION = 1\n"
    assert read_file_at_revision(str(repo), candidate, "a.py") == "VERSION = 2\n"


def test_read_file_at_revision_returns_none_for_nonexistent_file(repo):
    baseline = _commit(repo, {"a.py": "1"}, "baseline")
    assert read_file_at_revision(str(repo), baseline, "nonexistent.py") is None


def test_test_files_changed_property(repo):
    baseline = _commit(repo, {"tests/test_a.py": "1", "orca/app.py": "1"}, "baseline")
    candidate = _commit(repo, {"tests/test_a.py": "2", "orca/app.py": "2"}, "candidate")
    summary = get_diff_summary(str(repo), baseline, candidate)
    assert summary.test_files_changed == ("tests/test_a.py",)


def test_invalid_revision_raises(repo):
    _commit(repo, {"a.py": "1"}, "baseline")
    with pytest.raises(GitDiffError):
        get_diff_summary(str(repo), "nonexistent-rev-a", "nonexistent-rev-b")
