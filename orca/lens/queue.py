"""
Orca Lens — async job queue for image generation.

Real gap this closes: `generate_image()` (orca/lens/generate.py) is
synchronous and blocking — a single Flux [schnell] generation takes real
wall-clock time even at 4 inference steps, and a future `/api/lens/generate`
endpoint calling it directly would tie up a request thread for the whole
duration, per user, with no way to poll status or handle concurrent
requests sanely.

HONEST SCOPE:
  - This is a single-machine, diskcache-backed queue (same diskcache
    dependency already used by orca/brain/memory.py) — jobs persist across
    a process restart, but there is no distributed worker coordination
    (no Redis/Celery/SQS). Sufficient for "the API doesn't block on
    generation and a user can poll for a result," not sufficient for
    horizontally scaling generation across multiple machines. That's a
    real, separate scaling problem for whenever Lens actually has GPU
    hosting provisioned (RunPod Serverless was the leading option, never
    provisioned — see generate.py's own honest-scope note).
  - `process_next()` runs generation synchronously in whatever process/
    thread calls it — a real deployment needs a dedicated worker process
    (or a thread pool) calling this in a loop; this module provides the
    queue primitives, not the worker process itself.
  - No job expiry/cleanup policy yet — jobs and their generated images
    accumulate under ~/.orca/lens/queue and ~/.orca/lens/generated
    indefinitely. Fine for early testing, needs a retention policy before
    real user volume.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import diskcache

from orca.config import ORCA_HOME

QUEUE_DIR = ORCA_HOME / "lens" / "queue"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

# Valid job lifecycle: pending -> running -> (done | failed | blocked)
_VALID_STATUSES = {"pending", "running", "done", "failed", "blocked"}


@dataclass
class LensJob:
    id: str
    prompt: str
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result_path: Optional[str] = None
    error: Optional[str] = None
    width: int = 1024
    height: int = 1024
    num_inference_steps: int = 4
    seed: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


class LensJobQueue:
    """
    diskcache-backed FIFO-ish job queue. Not strictly FIFO under concurrent
    submission (diskcache doesn't guarantee insertion-order iteration), but
    close enough for the expected low-concurrency early-stage volume — a
    real distributed queue (SQS/Redis streams) would be the fix if that
    ever matters at scale.
    """

    def __init__(self, cache_dir: Path | None = None):
        self._cache = diskcache.Cache(str(cache_dir or QUEUE_DIR))

    def submit(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 4,
        seed: Optional[int] = None,
    ) -> str:
        """Enqueues a job and returns its id immediately — does NOT run
        generation. Content-safety moderation runs at process_next() time
        (right before the actual GPU work), not here, so a blocked prompt
        still shows up in status history rather than vanishing silently."""
        job = LensJob(
            id=str(uuid.uuid4()), prompt=prompt, width=width, height=height,
            num_inference_steps=num_inference_steps, seed=seed,
        )
        self._cache.set(job.id, job.to_dict())
        self._cache.set("_pending_ids", self._pending_ids() + [job.id])
        return job.id

    def get_status(self, job_id: str) -> Optional[LensJob]:
        data = self._cache.get(job_id)
        return LensJob(**data) if data else None

    def _pending_ids(self) -> list[str]:
        return self._cache.get("_pending_ids", [])

    def _set_status(self, job_id: str, **updates) -> None:
        data = self._cache.get(job_id)
        if not data:
            return
        data.update(updates, updated_at=time.time())
        self._cache.set(job_id, data)

    def process_next(self) -> Optional[LensJob]:
        """
        Pops and processes the next pending job SYNCHRONOUSLY in the calling
        thread/process. Returns the completed (or failed/blocked) job, or
        None if the queue is empty. A real worker calls this in a loop.
        """
        pending = self._pending_ids()
        if not pending:
            return None

        job_id = pending[0]
        self._cache.set("_pending_ids", pending[1:])

        self._set_status(job_id, status="running")
        job = self.get_status(job_id)
        if job is None:
            return None

        from orca.lens.generate import generate_image, LensPromptBlocked

        try:
            out_path = generate_image(
                job.prompt, width=job.width, height=job.height,
                num_inference_steps=job.num_inference_steps, seed=job.seed,
            )
            self._set_status(job_id, status="done", result_path=str(out_path))
        except LensPromptBlocked as e:
            self._set_status(job_id, status="blocked", error=str(e))
        except Exception as e:
            self._set_status(job_id, status="failed", error=str(e))

        return self.get_status(job_id)

    def pending_count(self) -> int:
        return len(self._pending_ids())
