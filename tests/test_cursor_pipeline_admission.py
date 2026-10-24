"""Admission checks for the streaming corpus reader.

Synthetic records only. No external corpus is downloaded.
"""
from __future__ import annotations

import json
import os

import pytest

from orca.genesis.data.pipeline import (
    CorpusBoundaryError,
    iter_classified_records,
    process_corpus,
)


def _write(path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n")


def test_invalid_utf8_is_a_counted_rejection_not_an_exception(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b'{"text": "ok"}\n{"text": "\xff"}\n')
    report, kept = process_corpus(path, tmp_path / "out", num_shards=1)
    assert report.corrupt_records == 1
    assert any("UTF-8" in sample for sample in report.corrupt_samples)
    assert report.kept == 1
    assert kept == ["ok"]


def test_symlink_input_is_refused(tmp_path):
    target = tmp_path / "real.jsonl"
    _write(target, [json.dumps({"text": "hello"})])
    link = tmp_path / "link.jsonl"
    os.symlink(target, link)
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        list(iter_classified_records(link))


def test_allowed_root_rejects_a_path_outside_it(tmp_path):
    jail = tmp_path / "jail"
    jail.mkdir()
    outside = tmp_path / "outside.jsonl"
    _write(outside, [json.dumps({"text": "hello"})])
    with pytest.raises(CorpusBoundaryError, match="outside allowed root"):
        process_corpus(outside, tmp_path / "out", num_shards=1, allowed_root=jail)


def test_license_omission_is_rejected_only_when_required(tmp_path):
    path = tmp_path / "in.jsonl"
    _write(path, [json.dumps({"text": "a public sentence about rain"})])
    plain, _kept = process_corpus(path, tmp_path / "plain", num_shards=1)
    assert plain.kept == 1
    licensed, _kept = process_corpus(path, tmp_path / "licensed", num_shards=1, require_license=True)
    assert licensed.kept == 0
    assert licensed.corrupt_records == 1
    assert any("license" in sample for sample in licensed.corrupt_samples)


def test_license_and_usage_metadata_are_accepted_when_required(tmp_path):
    path = tmp_path / "in.jsonl"
    _write(path, [json.dumps({
        "text": "a public sentence about rain",
        "license": "CC0-1.0",
        "usage_restrictions": "synthetic test fixture; not a training grant",
    })])
    report, kept = process_corpus(path, tmp_path / "out", num_shards=1, require_license=True)
    assert report.kept == 1
    assert kept == ["a public sentence about rain"]


def test_oversized_record_is_rejected_without_reading_it_as_json(tmp_path):
    path = tmp_path / "in.jsonl"
    huge = b'{"text": "' + (b"A" * 1000) + b'"}\n'
    small = b'{"text": "short"}\n'
    path.write_bytes(huge + small)
    report, kept = process_corpus(path, tmp_path / "out", num_shards=1, max_record_bytes=64)
    assert report.corrupt_records == 1
    assert any("max_record_bytes" in sample for sample in report.corrupt_samples)
    assert kept == ["short"]


def test_truncated_json_still_counts_as_corrupt(tmp_path):
    path = tmp_path / "in.jsonl"
    path.write_bytes(b'{"text": "no-end"')
    report, kept = process_corpus(path, tmp_path / "out", num_shards=1, max_record_bytes=1024)
    assert report.corrupt_records == 1
    assert kept == []


def test_preplanted_shard_symlink_is_not_followed(tmp_path):
    """Reproduced before the descriptor-anchored open: appending a shard
    followed a symlink and wrote corpus bytes into a file outside output_dir."""
    from orca.genesis.data.manifest import normalize_record_text
    from orca.genesis.data.pipeline import PROGRESS_DB_NAME, _shard_path, deterministic_split

    text = "a short synthetic sentence about rain"
    sensitive = tmp_path / "sensitive.txt"
    sensitive.write_bytes(b"ORIGINAL")
    out = tmp_path / "out"
    out.mkdir()
    link = _shard_path(out, 0, deterministic_split(normalize_record_text(text)))
    link.symlink_to(sensitive)
    source = tmp_path / "in.jsonl"
    _write(source, [json.dumps({"text": text})])
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        process_corpus(source, out, num_shards=1)
    assert sensitive.read_bytes() == b"ORIGINAL"
    assert link.is_symlink()

    link.unlink()
    report, kept = process_corpus(source, out, num_shards=1)
    assert report.kept == 1
    assert kept == [text]
    written = _shard_path(out, 0, deterministic_split(normalize_record_text(text)))
    written.unlink()
    written.symlink_to(sensitive)
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        process_corpus(source, out, num_shards=1)
    assert sensitive.read_bytes() == b"ORIGINAL"

    db = out / PROGRESS_DB_NAME
    import sqlite3
    conn = sqlite3.connect(db)
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    outside = outside_dir / written.name
    outside.write_bytes(b"OUTSIDE-BYTES-THAT-MUST-REMAIN")
    conn.execute(
        "UPDATE shard_file_safe_offsets SET path = ?, safe_byte_offset = 0",
        (str(outside),),
    )
    conn.commit()
    conn.close()
    with pytest.raises(CorpusBoundaryError, match="not under the output directory"):
        process_corpus(source, out, num_shards=1)
    assert outside.read_bytes() == b"OUTSIDE-BYTES-THAT-MUST-REMAIN"


def test_output_directory_symlink_is_not_followed(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    marker = real / "marker.txt"
    marker.write_text("keep")
    out = tmp_path / "out"
    os.symlink(real, out)
    source = tmp_path / "in.jsonl"
    _write(source, [json.dumps({"text": "a short synthetic sentence about rain"})])
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        process_corpus(source, out, num_shards=1)
    assert marker.read_text() == "keep"
    assert list(real.glob("shard-*.jsonl")) == []


def test_allowed_root_rejects_a_symlink_component(tmp_path):
    jail = tmp_path / "jail"
    jail.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.jsonl"
    _write(secret, [json.dumps({"text": "secret sentence"})])
    link = jail / "via"
    os.symlink(outside, link)
    with pytest.raises(CorpusBoundaryError, match="symlink"):
        list(iter_classified_records(link / "secret.jsonl", allowed_root=jail))
    assert secret.read_text().startswith('{"text"')
