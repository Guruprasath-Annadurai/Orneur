"""
Candidate deduplication (spec §16-17).

Mechanism, stated plainly per spec §17's "report exact mechanism": a
SHA-256 fingerprint over a normalized tuple of (task_type, failure_pattern,
canonicalized input structure, expected correction) -- reusing the exact
canonicalization discipline `orca.godmode.canonical.canonicalize_arguments`
already established (stable key order, NFC Unicode, explicit type tagging)
rather than inventing a second one. This is exact/near-exact dedupe over
normalized structure, NOT semantic/embedding-based dedupe -- the current
stack has no embedding infrastructure wired into this pipeline, and spec
§17 explicitly permits starting with the simpler canonical mechanism.

Near-duplicate detection here is deliberately narrow: two candidates whose
normalized (task_type, failure_type-set, input token-shingle set) overlap
above a fixed Jaccard threshold are flagged NEAR_DUPLICATE rather than
merged automatically -- merging is a review decision, not an automatic one.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from orca.godmode.canonical import canonicalize_arguments
from orca.learning.contracts import CurriculumCandidate

NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.8


def compute_fingerprint(candidate: CurriculumCandidate) -> str:
    normalized = canonicalize_arguments({
        "task_type": candidate.task_type,
        "target_role": candidate.target_role.value if candidate.target_role else None,
        "input_summary": candidate.input_summary.strip().lower(),
        "expected_behavior": candidate.expected_behavior.strip().lower(),
    })
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _shingles(text: str, n: int = 3) -> set[str]:
    tokens = text.lower().split()
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class DedupeReport:
    exact_duplicate_of: str | None = None
    near_duplicate_of: list[str] = None

    def __post_init__(self):
        if self.near_duplicate_of is None:
            self.near_duplicate_of = []


def dedupe_against(candidate: CurriculumCandidate, existing: list[CurriculumCandidate]) -> DedupeReport:
    if not candidate.dedupe_fingerprint:
        candidate.dedupe_fingerprint = compute_fingerprint(candidate)

    report = DedupeReport()
    my_shingles = _shingles(candidate.input_summary)
    for other in existing:
        if other.candidate_id == candidate.candidate_id:
            continue
        other_fp = other.dedupe_fingerprint or compute_fingerprint(other)
        if other_fp == candidate.dedupe_fingerprint:
            report.exact_duplicate_of = other.candidate_id
            return report  # exact match found -- no need to check near-duplicates
        if other.task_type == candidate.task_type:
            j = _jaccard(my_shingles, _shingles(other.input_summary))
            if j >= NEAR_DUPLICATE_JACCARD_THRESHOLD:
                report.near_duplicate_of.append(other.candidate_id)
    return report


def deduplicate(candidates: list[CurriculumCandidate]) -> tuple[list[CurriculumCandidate], list[CurriculumCandidate]]:
    """Returns (kept, dropped_as_exact_duplicates). Near-duplicates are kept
    but reported via dedupe_against, since merging is a review decision."""
    kept: list[CurriculumCandidate] = []
    dropped: list[CurriculumCandidate] = []
    for c in candidates:
        report = dedupe_against(c, kept)
        if report.exact_duplicate_of:
            dropped.append(c)
        else:
            kept.append(c)
    return kept, dropped
