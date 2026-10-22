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
