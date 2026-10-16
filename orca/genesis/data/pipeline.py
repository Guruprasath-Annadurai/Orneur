"""
GENESIS Foundation Sprint 2, Workstream A, Mission A2: a real, executable,
CPU-testable streaming data-processing pipeline for native pretraining
text records.

Reuses existing, already-tested infrastructure rather than duplicating it:
`orca.eval.genesis_contamination.normalize_text`/`word_ngrams`/`jaccard`
for near-duplicate detection (the same algorithmic approach the Genesis
Capability Eval V1 corpus's own contamination control already uses, here
applied to raw pretraining records rather than eval-corpus items), and
`orca.learning.sanitize.sanitize_for_candidate` for PII/secret screening
(the same DLP path `orca.learning.pipeline`'s curriculum pipeline already
uses, reused rather than reimplemented). The atomic-write discipline below
(`tempfile.mkstemp` + `fsync` + `os.replace`) matches the pattern
established in `orca.genesis.training.primitives.save_training_state`
(Sprint 1) -- re-implemented here rather than imported, since that
specific helper is private to the training-primitives module and this is
a genuinely different artifact (a processed shard file, not a checkpoint).

Deliberately O(n^2) near-duplicate detection within a bounded window: this
is a CPU-testable reference implementation proving the mechanism and
contract correctness, not a production-scale pipeline. A real multi-GB
corpus would need MinHash/LSH-based near-duplicate detection; that
algorithmic upgrade is a drop-in replacement for `_find_near_duplicates`
below, not a change to this module's public contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from orca.eval.genesis_contamination import jaccard, normalize_text, word_ngrams
from orca.genesis.data.manifest import normalize_record_text
from orca.learning.sanitize import sanitize_for_candidate

NEAR_DUP_WORD_NGRAM = 5
NEAR_DUP_JACCARD_THRESHOLD = 0.85
NEAR_DUP_WINDOW = 500  # bounded pairwise comparison window -- see module docstring


class CorruptRecordError(Exception):
    """Raised internally per-line; always caught by `stream_records()` and
    converted into a `ProcessingReport.corrupt_records` entry -- never
    propagates out and never halts the stream."""


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """The established mkstemp + fsync + os.replace discipline (Sprint 1 /
    Audit #016's `save_training_state` pattern), reimplemented here for a
    plain artifact file rather than a torch checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@dataclass
class ProcessingReport:
    """Explicit, structured failure reporting -- every record is
    accounted for in exactly one bucket; nothing is silently dropped
    without being counted somewhere."""
    lines_read: int = 0
    corrupt_records: int = 0
    corrupt_samples: list[str] = field(default_factory=list)  # bounded sample of reasons, not unbounded
    exact_duplicates: int = 0
    near_duplicates: int = 0
    quality_rejected: int = 0
    pii_secret_rejected: int = 0
    kept: int = 0
    resume_offset: int = 0  # line number to resume from on restart

    def record_corrupt(self, reason: str) -> None:
        self.corrupt_records += 1
        if len(self.corrupt_samples) < 20:
            self.corrupt_samples.append(reason)


def stream_records(path: Path, *, resume_from_line: int = 0) -> Iterator[tuple[int, str]]:
    """Memory-bounded streaming reader: yields (line_number, text) one
    line at a time, never loading the whole file into memory.
    `resume_from_line` skips already-processed lines (restart safety) --
    a caller resuming a prior run passes the `resume_offset` their last
    `ProcessingReport` recorded. Malformed JSON lines are skipped with a
    recorded reason, never raised past this function."""
    with open(path, encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f):
            if line_number < resume_from_line:
                continue
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                rec = json.loads(raw_line)
            except json.JSONDecodeError:
                yield line_number, ""  # caller distinguishes via a sentinel check below
                continue
            text = rec.get("text") if isinstance(rec, dict) else None
            if not isinstance(text, str) or not text.strip():
                yield line_number, ""
                continue
            yield line_number, text


def deterministic_shard(normalized_text: str, *, num_shards: int) -> int:
    """A pure function of the record's own normalized content -- the same
    record always lands in the same shard, regardless of input file
    order, run count, or process. Not a function of position/index, which
    would make shard assignment depend on upstream ordering."""
    if num_shards < 1:
        raise ValueError(f"num_shards must be >= 1, got {num_shards}")
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % num_shards


def deterministic_split(normalized_text: str, *, train_pct: int = 90, val_pct: int = 5) -> str:
    """Deterministic train/validation/test assignment, purely a function
    of record content -- reproducible across re-runs, and (since it does
    not depend on any other record) incapable of leaking a record across
    splits no matter how many times the pipeline is re-run or re-ordered."""
    if train_pct + val_pct > 100 or train_pct < 0 or val_pct < 0:
        raise ValueError(f"train_pct+val_pct must be <= 100 and both >= 0, got {train_pct}/{val_pct}")
    digest = hashlib.sha256(("split:" + normalized_text).encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < train_pct:
        return "train"
    if bucket < train_pct + val_pct:
        return "validation"
    return "test"


def process_corpus(
    input_path: Path, output_dir: Path, *, num_shards: int, resume_from_line: int = 0,
    quality_filter: Callable[[str], bool] | None = None, enforce_pii_screening: bool = True,
) -> tuple[ProcessingReport, list[str]]:
    """The full pipeline stage: stream -> corrupt-record rejection ->
    normalize -> exact + bounded-window near-duplicate rejection ->
    quality filter -> PII/secret screening -> deterministic shard+split
    assignment -> safe atomic write. Returns (report, normalized_kept_records)
    -- the latter is what `GenesisDatasetManifest.build()` consumes for its
    content digest, so the manifest's digest is derived from the SAME
    records this function actually kept and wrote, not a separate,
    possibly-divergent recomputation."""
    report = ProcessingReport()
    seen_exact: set[str] = set()
    near_dup_window: list[tuple[int, str, frozenset]] = []
    shard_writers: dict[int, dict[str, list[str]]] = {i: {"train": [], "validation": [], "test": []} for i in range(num_shards)}
    kept_records: list[str] = []

    for line_number, raw_text in stream_records(input_path, resume_from_line=resume_from_line):
        report.lines_read += 1
        report.resume_offset = line_number + 1
        if not raw_text:
            report.record_corrupt(f"line {line_number}: malformed JSON or missing/empty 'text' field")
            continue

        normalized = normalize_record_text(raw_text)
        exact_key = hashlib.sha256(normalize_text(normalized).encode("utf-8")).hexdigest()
        if exact_key in seen_exact:
            report.exact_duplicates += 1
            continue
        seen_exact.add(exact_key)

        shingles = frozenset(word_ngrams(normalized, NEAR_DUP_WORD_NGRAM))
        near_dup_window.append((line_number, normalized, shingles))
        if len(near_dup_window) > NEAR_DUP_WINDOW:
            near_dup_window.pop(0)

        is_near_dup = False
        for _, _, other_shingles in near_dup_window[:-1]:
            if jaccard(shingles, other_shingles) >= NEAR_DUP_JACCARD_THRESHOLD:
                is_near_dup = True
                break
        if is_near_dup:
            report.near_duplicates += 1
            near_dup_window.pop()
            continue

        if quality_filter is not None and not quality_filter(normalized):
            report.quality_rejected += 1
            continue

        if enforce_pii_screening:
            sanitized = sanitize_for_candidate(normalized)
            if sanitized.rejected:
                report.pii_secret_rejected += 1
                continue
            normalized = sanitized.clean_text

        shard = deterministic_shard(normalized, num_shards=num_shards)
        split = deterministic_split(normalized)
        shard_writers[shard][split].append(normalized)
        kept_records.append(normalized)
        report.kept += 1

    for shard_idx, splits in shard_writers.items():
        for split_name, records in splits.items():
            if not records:
                continue
            out_path = output_dir / f"shard-{shard_idx:04d}-{split_name}.jsonl"
            payload = "\n".join(json.dumps({"text": r}, ensure_ascii=False) for r in records) + "\n"
            _atomic_write_bytes(out_path, payload.encode("utf-8"))

    return report, kept_records
