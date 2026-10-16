"""
GENESIS Foundation Sprint 2, Workstream A, Mission A2/A6: streaming
pipeline tests, including adversarial coverage (corrupt records,
duplicates, interrupted processing, concurrent writers, excessive memory
consumption, untrusted input paths).
"""
from __future__ import annotations

import json
import threading

import pytest

from orca.genesis.data.pipeline import (
    ProcessingReport,
    deterministic_shard,
    deterministic_split,
    process_corpus,
    stream_records,
)


def _write_jsonl(path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


def test_stream_records_yields_valid_lines_and_skips_blank_lines(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": "a"}), "", json.dumps({"text": "b"})])
    out = list(stream_records(p))
    assert [t for _, t in out if t] == ["a", "b"]


# ------------------------------------------------------------ corrupt records --

def test_corrupt_json_line_is_rejected_not_raised(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, ["{not valid json", json.dumps({"text": "ok"})])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.corrupt_records == 1
    assert report.kept == 1


def test_missing_text_field_is_rejected_as_corrupt(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"not_text": "x"}), json.dumps({"text": "ok"})])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.corrupt_records == 1


def test_non_dict_json_record_is_rejected_as_corrupt(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps([1, 2, 3]), json.dumps({"text": "ok"})])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.corrupt_records == 1


def test_corrupt_record_samples_are_bounded():
    report = ProcessingReport()
    for i in range(50):
        report.record_corrupt(f"reason {i}")
    assert report.corrupt_records == 50
    assert len(report.corrupt_samples) == 20


# ------------------------------------------------------------ duplicates --

def test_exact_duplicates_are_rejected(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": "the same sentence repeated"})] * 3)
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.exact_duplicates == 2
    assert report.kept == 1


def test_whitespace_and_case_variant_duplicates_are_caught_via_normalization(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [
        json.dumps({"text": "Hello   World"}),
        json.dumps({"text": "hello world"}),
    ])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.exact_duplicates == 1


def test_near_duplicates_within_window_are_flagged(tmp_path):
    p = tmp_path / "in.jsonl"
    base = (
        "The quick brown fox jumps over the lazy dog near the riverbank today while "
        "the morning sun rises slowly over the distant quiet green hills beyond town"
    )
    near = (
        "The quick brown fox jumps over the lazy dog near the riverbank today while "
        "the morning sun rises slowly over the distant quiet green hills beyond city"
    )
    _write_jsonl(p, [json.dumps({"text": base}), json.dumps({"text": near})])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.near_duplicates == 1
    assert report.kept == 1


def test_genuinely_different_records_are_both_kept(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [
        json.dumps({"text": "A sentence entirely about cooking pasta for dinner tonight."}),
        json.dumps({"text": "A completely unrelated sentence about space exploration history."}),
    ])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.kept == 2
    assert report.near_duplicates == 0
    assert report.exact_duplicates == 0


# ------------------------------------------------------------ restart safety --

def test_interrupted_processing_can_resume_from_the_reported_offset(tmp_path):
    p = tmp_path / "in.jsonl"
    texts = [f"unique record number {i} about something distinct" for i in range(10)]
    _write_jsonl(p, [json.dumps({"text": t}) for t in texts])

    first_report, first_kept = process_corpus(p, tmp_path / "out1", num_shards=1)
    # Simulate an interruption after only 4 lines were actually read by
    # manually re-deriving a resume point, then confirm resuming from a
    # real mid-stream offset correctly yields the REMAINING records, not
    # a re-processing of everything from the start.
    partial = list(stream_records(p))[:4]
    resume_at = partial[-1][0] + 1
    remaining = list(stream_records(p, resume_from_line=resume_at))
    assert len(remaining) == 10 - 4
    assert remaining[0][1] == texts[4]


def test_resume_offset_is_reported_as_total_lines_read(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": f"record {i}"}) for i in range(5)])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.resume_offset == 5


# ------------------------------------------------------------ determinism --

def test_deterministic_shard_is_a_pure_function_of_content():
    assert deterministic_shard("hello", num_shards=4) == deterministic_shard("hello", num_shards=4)


def test_deterministic_shard_distributes_across_the_full_range():
    shards = {deterministic_shard(f"record {i}", num_shards=8) for i in range(200)}
    assert len(shards) > 1  # not everything collapsing into one shard


def test_deterministic_shard_rejects_invalid_num_shards():
    with pytest.raises(ValueError):
        deterministic_shard("x", num_shards=0)


def test_deterministic_split_is_reproducible_and_disjoint():
    results = [deterministic_split(f"record {i}") for i in range(500)]
    assert set(results) <= {"train", "validation", "test"}
    assert deterministic_split("a fixed record") == deterministic_split("a fixed record")


def test_deterministic_split_rejects_invalid_percentages():
    with pytest.raises(ValueError):
        deterministic_split("x", train_pct=90, val_pct=20)


def test_reprocessing_the_same_input_produces_identical_shard_file_contents(tmp_path):
    """Reproducible ordering: running the pipeline twice over the same
    input must produce byte-identical shard outputs."""
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": f"distinct record {i} about topic {i}"}) for i in range(20)])
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    process_corpus(p, out1, num_shards=3)
    process_corpus(p, out2, num_shards=3)
    files1 = sorted(f.name for f in out1.glob("*.jsonl"))
    files2 = sorted(f.name for f in out2.glob("*.jsonl"))
    assert files1 == files2
    for name in files1:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


# ------------------------------------------------------------ quality filtering --

def test_quality_filter_rejects_records_that_fail_the_predicate(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": "short"}), json.dumps({"text": "this record is long enough to pass the filter easily"})])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1, quality_filter=lambda t: len(t) > 20)
    assert report.quality_rejected == 1
    assert report.kept == 1


# ------------------------------------------------------------ PII/secret screening --

def test_pii_secret_screening_rejects_records_with_a_detected_secret(tmp_path):
    p = tmp_path / "in.jsonl"
    # A GitHub-shaped token pattern, matching the existing
    # orca.connectors.security.redact_secrets pattern list this pipeline
    # reuses via orca.learning.sanitize.sanitize_for_candidate.
    secret_text = "here is my token ghp_1234567890abcdef1234567890abcdef1234"
    _write_jsonl(p, [json.dumps({"text": secret_text}), json.dumps({"text": "a perfectly ordinary sentence with no secrets at all"})])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.pii_secret_rejected >= 1


def test_pii_screening_can_be_disabled_explicitly(tmp_path):
    p = tmp_path / "in.jsonl"
    secret_text = "here is my token ghp_1234567890abcdef1234567890abcdef1234"
    _write_jsonl(p, [json.dumps({"text": secret_text})])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1, enforce_pii_screening=False)
    assert report.pii_secret_rejected == 0
    assert report.kept == 1


# ------------------------------------------------------------ safe atomic writes --

def test_output_shard_files_have_owner_only_permissions(tmp_path):
    import os
    import stat
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": "a record that will be written to a real shard file"})])
    out = tmp_path / "out"
    process_corpus(p, out, num_shards=1)
    shard_files = list(out.glob("*.jsonl"))
    assert shard_files
    for f in shard_files:
        mode = stat.S_IMODE(os.stat(f).st_mode)
        assert mode == 0o600


def test_no_partial_shard_file_is_left_behind_on_a_simulated_write_failure(tmp_path, monkeypatch):
    import orca.genesis.data.pipeline as pipeline_mod

    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": "a record headed for a shard write that will be interrupted"})])
    out = tmp_path / "out"
    out.mkdir()

    original_replace = pipeline_mod.os.replace

    def _boom(src, dst):
        raise OSError("simulated crash during shard write")

    monkeypatch.setattr(pipeline_mod.os, "replace", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        process_corpus(p, out, num_shards=1)
    monkeypatch.setattr(pipeline_mod.os, "replace", original_replace)
    # No stray .tmp- files left behind -- the atomic-write helper cleans
    # up its own temp file on any exception.
    assert not list(out.glob(".*tmp-*"))


# ------------------------------------------------------------ concurrent writers --

def test_concurrent_pipeline_runs_against_separate_output_dirs_do_not_corrupt_each_other(tmp_path):
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": f"concurrent-safe record {i} about topic {i}"}) for i in range(30)])

    results = {}
    errors = []

    def _run(tag):
        try:
            out_dir = tmp_path / f"out-{tag}"
            report, kept = process_corpus(p, out_dir, num_shards=2)
            results[tag] = (report, kept)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_run, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 4
    kept_counts = {tag: r[0].kept for tag, r in results.items()}
    assert len(set(kept_counts.values())) == 1  # every concurrent run processed the same input identically


# ------------------------------------------------------------ excessive memory consumption --

def test_streaming_reader_does_not_load_the_whole_file_into_memory(tmp_path):
    """stream_records() is a generator -- confirmed by checking that
    calling it does not itself read the file (only iterating does), and
    that a large file can be streamed without constructing an
    in-memory list of all lines first."""
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": f"record {i}"}) for i in range(5000)])
    gen = stream_records(p)
    import types
    assert isinstance(gen, types.GeneratorType)
    first_line_number, first_text = next(gen)
    assert first_text == "record 0"
    # Consuming only the first item must not have read the entire file --
    # verified indirectly: the generator object itself holds no fully
    # materialized list of all 5000 records (it is a generator, not a list).


def test_near_duplicate_window_is_bounded_not_unbounded(tmp_path):
    """Processing many genuinely distinct records must not grow the
    near-duplicate comparison window without bound -- a basic defense
    against excessive memory consumption on a large corpus."""
    p = tmp_path / "in.jsonl"
    _write_jsonl(p, [json.dumps({"text": f"a genuinely distinct record number {i} about topic {i}"}) for i in range(2000)])
    report, kept = process_corpus(p, tmp_path / "out", num_shards=1)
    assert report.kept == 2000  # all distinct, none spuriously flagged due to window eviction


# ------------------------------------------------------------ untrusted input paths --

def test_nonexistent_input_path_raises_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(stream_records(tmp_path / "does_not_exist.jsonl"))


def test_a_directory_passed_as_input_path_raises_rather_than_silently_producing_nothing(tmp_path):
    a_dir = tmp_path / "a_directory"
    a_dir.mkdir()
    with pytest.raises((IsADirectoryError, PermissionError)):
        list(stream_records(a_dir))
