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

from orca.eval.genesis_contamination import jaccard, normalize_text, screen_training_texts, word_ngrams
from orca.eval.genesis_corpus import CORPUS_DIR, FINGERPRINT_FILE

NEAR_DUP_WORD_NGRAM = 5
NEAR_DUP_JACCARD_THRESHOLD = 0.85


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
    cross_split_near_duplicates: int = 0
    flagged_samples: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        """True only if every check that ran found zero flags. A report
        with an empty `checks_performed` is never `clean` -- see
        `is_fully_verified_clean()`."""
        return (
            self.exact_matches == 0 and self.normalized_matches == 0
            and self.holdout_overlap_flagged == 0 and self.cross_split_near_duplicates == 0
        )

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


class CrossSplitScreeningTooLargeError(Exception):
    """P1-02 fix: raised by `find_near_duplicates_across_splits()` when
    the total record count exceeds `max_total_records`. This function
    is a CPU-testable reference implementation (pairwise O(n^2)
    comparison, the same honest trade-off `orca.genesis.data.pipeline`'s
    own bounded `NEAR_DUP_WINDOW` sliding-window already documents for
    within-corpus near-dup detection) -- independently reproduced as
    having NO explicit scalability limit at all before this fix: it
    would simply run slower and slower, with no boundary past which a
    caller is told "this input is too large for this implementation."
    Raising a clear, explicit error past a documented size is the
    directive's own explicitly-permitted alternative to actually
    building a MinHash/LSH-indexed implementation (out of scope for
    this hardening pass, exactly as `pipeline.py`'s own near-duplicate
    detection already documents for the analogous within-corpus case) --
    a caller with a genuinely large corpus must shard the cross-split
    check itself (e.g. per-shard, or via an external indexed near-dup
    tool) rather than this function silently taking an unbounded amount
    of time."""


def find_near_duplicates_across_splits(
    split_to_records: Mapping[str, Sequence[str]], *, max_total_records: int = 5000,
) -> list[tuple[str, int, str, int]]:
    """A-11 (Workstream A hardening): `deterministic_split()`
    (`orca.genesis.data.pipeline`) guarantees a given record's split
    assignment is reproducible and that record is never duplicated
    across splits -- but it does NOT, and cannot, guarantee two
    DIFFERENT but near-identical records (e.g. one phrased slightly
    differently from the other) land in the same split; each is hashed
    and bucketed independently of the other. A validation/test record
    that is a near-duplicate of a training record is a real train/eval
    leakage risk this module did not previously check for at all.
    Returns `(split_a, index_a, split_b, index_b)` tuples for every
    cross-split pair exceeding `NEAR_DUP_JACCARD_THRESHOLD` -- empty
    means none found, which a caller must still treat as "checked and
    clean," never implicitly assumed without calling this.

    P1-02 fix: this is an O(n^2) pairwise comparison -- explicitly
    bounded by `max_total_records` (default 5000, ~12.5M comparisons,
    the same order of magnitude this module's own test suite exercises
    comfortably on CPU). Raises `CrossSplitScreeningTooLargeError`
    rather than silently taking an unbounded amount of time past that
    size -- an EXPLICIT scalability limit, the directive's own stated
    alternative to a full indexed (MinHash/LSH) implementation, which
    remains a documented, out-of-scope future upgrade."""
    total = sum(len(records) for records in split_to_records.values())
    if total > max_total_records:
        raise CrossSplitScreeningTooLargeError(
            f"find_near_duplicates_across_splits() received {total} total records, exceeding "
            f"max_total_records={max_total_records} -- this O(n^2) pairwise comparison has no indexed "
            f"implementation; shard the cross-split check yourself or raise max_total_records explicitly "
            f"if you have confirmed the runtime cost is acceptable"
        )
    bucketed: list[tuple[str, int, frozenset]] = []
    for split_name, records in split_to_records.items():
        for idx, text in enumerate(records):
            bucketed.append((split_name, idx, frozenset(word_ngrams(normalize_text(text), NEAR_DUP_WORD_NGRAM))))

    flagged: list[tuple[str, int, str, int]] = []
    for i in range(len(bucketed)):
        split_a, idx_a, shingles_a = bucketed[i]
        for j in range(i + 1, len(bucketed)):
            split_b, idx_b, shingles_b = bucketed[j]
            if split_a == split_b:
                continue  # within-split near-dups are pipeline.py's own concern, not a leakage risk
            if jaccard(shingles_a, shingles_b) >= NEAR_DUP_JACCARD_THRESHOLD:
                flagged.append((split_a, idx_a, split_b, idx_b))
    return flagged


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
    protected_texts: Sequence[str] | None = None, split_to_records: Mapping[str, Sequence[str]] | None = None,
) -> ContaminationReport:
    """Runs whichever checks the caller supplied inputs for, and records
    exactly which ones ran in `checks_performed` -- never claims a check
    happened when its required input was absent. `split_to_records`
    (A-11 hardening) enables the cross-split near-duplicate check --
    pass the pipeline's actual per-split record sets (e.g. from
    `read_kept_records_by_split()`) to screen for train/eval leakage via
    near-duplicate content, not merely exact duplication."""
    checks: list[str] = []
    exact_matches = 0
    normalized_matches = 0
    holdout_flagged = 0
    cross_split_flagged = 0
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

    if split_to_records is not None:
        checks.append("cross_split_near_duplicate")
        cross_split = find_near_duplicates_across_splits(split_to_records)
        cross_split_flagged = len(cross_split)
        samples.extend(
            {"kind": "cross_split_near_duplicate", "split_a": sa, "index_a": ia, "split_b": sb, "index_b": ib}
            for sa, ia, sb, ib in cross_split[:20]
        )

    return ContaminationReport(
        checks_performed=tuple(checks), exact_matches=exact_matches, normalized_matches=normalized_matches,
        holdout_overlap_flagged=holdout_flagged, cross_split_near_duplicates=cross_split_flagged, flagged_samples=tuple(samples),
    )
