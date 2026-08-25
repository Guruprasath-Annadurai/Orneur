"""
Tests for orca/lens/queue.py's async job queue.

Covers the real gap this closes: generate_image() is synchronous/blocking,
with no way for a future API endpoint to accept a request, return
immediately, and let the caller poll for a result. Also covers that a
blocked prompt (content-safety filter) surfaces as a real "blocked" status
in the job's history, rather than vanishing without a trace.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orca.lens.queue import LensJobQueue


@pytest.fixture
def queue(tmp_path):
    return LensJobQueue(cache_dir=tmp_path / "queue")


def test_submit_returns_job_id_and_status_is_pending(queue):
    job_id = queue.submit("a golden retriever puppy")
    job = queue.get_status(job_id)

    assert job is not None
    assert job.status == "pending"
    assert job.prompt == "a golden retriever puppy"


def test_get_status_returns_none_for_unknown_job(queue):
    assert queue.get_status("nonexistent-id") is None


def test_process_next_returns_none_when_queue_empty(queue):
    assert queue.process_next() is None


def test_process_next_marks_job_done_on_success(queue, monkeypatch):
    from orca.lens import queue as queue_module

    fake_path = Path("/tmp/fake-generated.png")
    monkeypatch.setattr(queue_module, "generate_image", lambda *a, **k: fake_path, raising=False)
    # generate_image is imported inside process_next (deferred import) —
    # patch it at the source module so that import resolves to our fake.
    import orca.lens.generate as generate_module
    monkeypatch.setattr(generate_module, "generate_image", lambda *a, **k: fake_path)

    job_id = queue.submit("a golden retriever puppy")
    result = queue.process_next()

    assert result.id == job_id
    assert result.status == "done"
    assert result.result_path == str(fake_path)


def test_process_next_marks_job_blocked_on_moderation_block(queue, monkeypatch):
    import orca.lens.generate as generate_module

    def _raise_blocked(*a, **k):
        raise generate_module.LensPromptBlocked("mickey mouse", ["hard_block"])

    monkeypatch.setattr(generate_module, "generate_image", _raise_blocked)

    job_id = queue.submit("a picture of Mickey Mouse")
    result = queue.process_next()

    assert result.status == "blocked"
    assert "hard_block" in result.error


def test_process_next_marks_job_failed_on_unexpected_exception(queue, monkeypatch):
    import orca.lens.generate as generate_module

    def _raise_error(*a, **k):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(generate_module, "generate_image", _raise_error)

    job_id = queue.submit("a golden retriever puppy")
    result = queue.process_next()

    assert result.status == "failed"
    assert "CUDA out of memory" in result.error


def test_pending_count_tracks_queue_size(queue, monkeypatch):
    import orca.lens.generate as generate_module
    monkeypatch.setattr(generate_module, "generate_image", lambda *a, **k: Path("/tmp/x.png"))

    assert queue.pending_count() == 0
    queue.submit("prompt 1")
    queue.submit("prompt 2")
    assert queue.pending_count() == 2

    queue.process_next()
    assert queue.pending_count() == 1


def test_jobs_processed_in_submission_order(queue, monkeypatch):
    import orca.lens.generate as generate_module
    monkeypatch.setattr(generate_module, "generate_image", lambda *a, **k: Path("/tmp/x.png"))

    first_id = queue.submit("first")
    second_id = queue.submit("second")

    first_result = queue.process_next()
    second_result = queue.process_next()

    assert first_result.id == first_id
    assert second_result.id == second_id
