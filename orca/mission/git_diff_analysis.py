"""
Phase 15.9 -- real, git-based baseline/candidate diff analysis (spec
section 3-4).

Every function here shells out to the real `git` binary against a
real repository -- no synthetic diff dictionaries, no guessing from
"only the current tree" (spec section 3's explicit instruction). Uses
`git diff --name-status -M` (rename detection) and `git show
<rev>:<path>` to reconstruct file content at a specific revision.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field


class GitDiffError(Exception):
    pass


def _run_git(args: list[str], *, cwd: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise GitDiffError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


@dataclass(frozen=True)
class RenamedFile:
    old_path: str
    new_path: str
    similarity_percent: int


@dataclass(frozen=True)
class DiffSummary:
    baseline_revision: str
    candidate_revision: str
    added_files: tuple[str, ...] = field(default_factory=tuple)
    deleted_files: tuple[str, ...] = field(default_factory=tuple)
    modified_files: tuple[str, ...] = field(default_factory=tuple)
    renamed_files: tuple[RenamedFile, ...] = field(default_factory=tuple)

    @property
    def all_changed_files(self) -> tuple[str, ...]:
        return (
            self.added_files + self.deleted_files + self.modified_files
            + tuple(r.new_path for r in self.renamed_files)
        )

    @property
    def test_files_changed(self) -> tuple[str, ...]:
        return tuple(f for f in self.all_changed_files if _is_test_path(f))


def _is_test_path(path: str) -> bool:
    return "/tests/" in f"/{path}" or path.startswith("tests/") or path.rsplit("/", 1)[-1].startswith("test_")


def get_diff_summary(repo_path: str, baseline_revision: str, candidate_revision: str) -> DiffSummary:
    """Uses `git diff --name-status -M` (rename detection threshold
    default) between two REAL revisions in a REAL repository."""
    output = _run_git(
        ["diff", "--name-status", "-M", f"{baseline_revision}..{candidate_revision}"],
        cwd=repo_path,
    )
    added, deleted, modified, renamed = [], [], [], []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            similarity = int(status[1:]) if len(status) > 1 and status[1:].isdigit() else 0
            renamed.append(RenamedFile(old_path=parts[1], new_path=parts[2], similarity_percent=similarity))
        elif status == "A":
            added.append(parts[1])
        elif status == "D":
            deleted.append(parts[1])
        elif status == "M":
            modified.append(parts[1])
        # C (copy) and others intentionally not specially handled this phase

    return DiffSummary(
        baseline_revision=baseline_revision, candidate_revision=candidate_revision,
        added_files=tuple(added), deleted_files=tuple(deleted), modified_files=tuple(modified),
        renamed_files=tuple(renamed),
    )


def read_file_at_revision(repo_path: str, revision: str, file_path: str) -> str | None:
    """Returns the real file content at `revision` via `git show`, or
    None if the file did not exist at that revision (never guesses
    content)."""
    result = subprocess.run(
        ["git", "show", f"{revision}:{file_path}"], cwd=repo_path,
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return None
    return result.stdout
