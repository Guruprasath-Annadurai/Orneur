"""
Phase 15.9 -- real test-collection comparison between two git
revisions (spec section 4).

Uses `git worktree` to materialize each revision into a real
temporary directory, then runs `pytest --collect-only -q` there to
get REAL collected test node ids -- never a guess from diff text
alone.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class CollectionDiffError(Exception):
    pass


@dataclass(frozen=True)
class CollectionDelta:
    baseline_ids: frozenset[str]
    candidate_ids: frozenset[str]

    @property
    def removed(self) -> frozenset[str]:
        return self.baseline_ids - self.candidate_ids

    @property
    def added(self) -> frozenset[str]:
        return self.candidate_ids - self.baseline_ids

    @property
    def unchanged(self) -> frozenset[str]:
        return self.baseline_ids & self.candidate_ids

    @property
    def collection_shrank(self) -> bool:
        return len(self.candidate_ids) < len(self.baseline_ids)


def collect_test_ids_at_revision(repo_path: str, revision: str, test_target: str = "tests") -> frozenset[str]:
    """Materializes `revision` into a real temporary worktree and runs
    `pytest --collect-only -q` there. Returns the empty set (not an
    error) if collection genuinely finds nothing -- callers combine
    this with other evidence rather than treating an empty set as
    automatically suspicious or automatically fine."""
    with tempfile.TemporaryDirectory(prefix="orneur-collection-diff-") as worktree_dir:
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", worktree_dir, revision],
            cwd=repo_path, capture_output=True, text=True, timeout=60,
        )
        if add.returncode != 0:
            raise CollectionDiffError(f"git worktree add failed for {revision}: {add.stderr.strip()}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_target, "--collect-only", "-q"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=120,
            )
            ids = set()
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and "::" in line and not line.startswith("="):
                    ids.add(line)
            return frozenset(ids)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", worktree_dir], cwd=repo_path,
                            capture_output=True, text=True, timeout=30)


def compare_collections(baseline_ids: frozenset[str], candidate_ids: frozenset[str]) -> CollectionDelta:
    return CollectionDelta(baseline_ids=baseline_ids, candidate_ids=candidate_ids)
