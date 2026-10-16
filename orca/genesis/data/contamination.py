"""
GENESIS Foundation Sprint 2, Workstream A, Mission A3: benchmark
contamination controls for native pretraining corpora.

Reuses the EXISTING, already-sanctioned protected-benchmark screening
mechanism rather than touching the protected holdout directly:
`orca.eval.genesis_contamination.screen_training_texts()` against the
Genesis Capability Eval V1 corpus's own committed `holdout_fingerprints.json`
(8-gram hashes only -- no holdout TEXT is ever read or exposed by this
module). `orca.eval.genesis_harness.open_split()` is explicitly documented
as "the only sanctioned way to read a split," and HOLDOUT may only be
opened for the `QUALIFICATION` purpose -- this module never calls it and
never reads the raw HOLDOUT split file; it reads only the pre-committed
fingerprint file, exactly the same way `orca.eval.genesis_prereg` and
`tests/test_genesis_eval_v1.py` already do.

This module adds exact-match and normalized-match corpus-vs-corpus
checks (for comparing a candidate pretraining shard against a SEPARATE,
explicitly-provided protected set -- e.g. a benchmark eval set other than
the Genesis Capability Eval V1 corpus) on top of that reuse.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from orca.eval.genesis_contamination import normalize_text, screen_training_texts
from orca.eval.genesis_corpus import CORPUS_DIR, FINGERPRINT_FILE


class ContaminationCheckIncomplete(Exception):
    """Raised when a contamination check could not actually be performed
    (e.g. the fingerprint file is missing or unreadable) -- Mission A3's
    explicit requirement: 'a dataset cannot be marked clean merely
    because no scanner error was reported.' Any caller catching this
    exception must treat the dataset as NOT verified clean, never as
    clean-by-default."""


@dataclass(frozen=True)
class ContaminationReport:
    """Every field is a count of something ACTUALLY CHECKED, not an
    absence-of-evidence claim. `checks_performed` lists which checks ran;
    a caller must check that the specific check they care about is in
    this list before trusting the corresponding count being zero."""
    checks_performed: tuple[str, ...]
    exact_matches: int
    normalized_matches: int
    holdout_overlap_flagged: int
    flagged_samples: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        """True only if every check that ran found zero flags. A report
        with an empty `checks_performed` is never `clean` -- see
        `is_fully_verified_clean()`."""
        return self.exact_matches == 0 and self.normalized_matches == 0 and self.holdout_overlap_flagged == 0

    def is_fully_verified_clean(self, *, required_checks: Sequence[str]) -> bool:
        """The honest gate: clean AND every check the caller actually
        requires was performed. Prevents the exact failure mode Mission
        A3 names -- a dataset silently treated as clean because one
        scanner was skipped, not because it was actually checked and
        passed."""
        return self.clean and set(required_checks) <= set(self.checks_performed)


def find_exact_matches(candidate_texts: Sequence[str], protected_texts: Sequence[str]) -> list[tuple[int, int]]:
    """Exact matches after normalization (NFC + casefold + whitespace
    collapse, via `normalize_text`) -- catches byte-identical and
    whitespace/case-variant duplicates alike."""
    protected_keys = {normalize_text(t): i for i, t in enumerate(protected_texts)}
    out = []
    for ci, ct in enumerate(candidate_texts):
        key = normalize_text(ct)
        if key in protected_keys:
            out.append((ci, protected_keys[key]))
    return out


def find_normalized_substring_matches(candidate_texts: Sequence[str], protected_texts: Sequence[str], *, min_len: int = 40) -> list[tuple[int, int]]:
    """Catches a protected text appearing as a SUBSTRING of a (typically
    longer) candidate record -- e.g. a benchmark question embedded inside
    a scraped web page -- which an exact whole-string match would miss.
    `min_len` guards against trivial short-string false positives."""
    out = []
    for pi, pt in enumerate(protected_texts):
        norm_p = normalize_text(pt)
        if len(norm_p) < min_len:
            continue
        for ci, ct in enumerate(candidate_texts):
            if norm_p in normalize_text(ct):
                out.append((ci, pi))
    return out


def load_genesis_eval_v1_fingerprints(repo_root: Path) -> Mapping[str, Sequence[int]]:
    """Reads the committed, non-text fingerprint file directly -- the
    exact pattern `orca.eval.genesis_prereg` and the existing Genesis
    Capability Eval V1 test suite already use. Raises
    `ContaminationCheckIncomplete` (never returns an empty-but-apparently-valid
    mapping) if the file is missing or malformed, so a caller cannot
    silently proceed as if holdout screening had happened when it did
    not."""
    path = Path(repo_root) / CORPUS_DIR / FINGERPRINT_FILE
    if not path.exists():
        raise ContaminationCheckIncomplete(f"Genesis Capability Eval V1 fingerprint file not found at {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ContaminationCheckIncomplete(f"fingerprint file at {path} is not valid JSON: {e!r}") from e


def run_contamination_checks(
    candidate_texts: Sequence[str], *, holdout_fingerprints: Mapping[str, Sequence[int]] | None = None,
    protected_texts: Sequence[str] | None = None,
) -> ContaminationReport:
    """Runs whichever checks the caller supplied inputs for, and records
    exactly which ones ran in `checks_performed` -- never claims a check
    happened when its required input was absent."""
    checks: list[str] = []
    exact_matches = 0
    normalized_matches = 0
    holdout_flagged = 0
    samples: list[dict] = []

    if protected_texts is not None:
        checks.append("exact_match")
        checks.append("normalized_substring_match")
        exact = find_exact_matches(candidate_texts, protected_texts)
        exact_matches = len(exact)
        samples.extend({"kind": "exact_match", "candidate_index": c, "protected_index": p} for c, p in exact[:20])
        substr = find_normalized_substring_matches(candidate_texts, protected_texts)
        normalized_matches = len(substr)
        samples.extend({"kind": "normalized_substring_match", "candidate_index": c, "protected_index": p} for c, p in substr[:20])

    if holdout_fingerprints is not None:
        checks.append("genesis_eval_v1_holdout_overlap")
        flagged = screen_training_texts(candidate_texts, holdout_fingerprints)
        holdout_flagged = len(flagged)
        samples.extend({"kind": "holdout_ngram_overlap", **f} for f in flagged[:20])

    return ContaminationReport(
        checks_performed=tuple(checks), exact_matches=exact_matches, normalized_matches=normalized_matches,
        holdout_overlap_flagged=holdout_flagged, flagged_samples=tuple(samples),
    )
