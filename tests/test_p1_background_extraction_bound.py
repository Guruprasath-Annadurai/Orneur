"""LANDMARK-04 P1 -- post-turn knowledge extraction is a bounded, best-effort background job.

Finding (P2, reproduced with the live fixture-provider journey: every served turn made one extra non-streamed model call): each committed turn spawned an unconditional
``asyncio.create_task(to_thread(extract_and_add))`` -- unbounded in count, and a hidden extra provider call per turn. It is now admitted through a small slot pool; when the pool
is full the extraction is skipped (it is derived data and can be rebuilt), never queued without limit.
"""
from __future__ import annotations

import asyncio
import threading


def test_extraction_concurrency_is_bounded_and_overflow_is_skipped():
    from orca.serve import api

    started, gate, lock = [], threading.Event(), threading.Lock()

    class KG:
        def extract_and_add(self, text, source, brain):
            with lock:
                started.append(text)
            gate.wait(5)

    class Sess:
        knowledge_graph = KG()
        brain = object()

    async def run():
        tasks = [api._spawn_kg_extraction(Sess(), f"turn {i}") for i in range(20)]
        await asyncio.sleep(0.3)
        concurrent = len(started)
        gate.set()
        await asyncio.gather(*[t for t in tasks if t is not None])
        return concurrent, sum(1 for t in tasks if t is None)

    concurrent, skipped = asyncio.run(run())
    assert concurrent <= api._KG_EXTRACT_SLOTS_N, f"{concurrent} extraction jobs ran at once"
    assert skipped >= 20 - api._KG_EXTRACT_SLOTS_N, "overflow was queued instead of skipped"
    # slots are released: a later turn is admitted again
    gate.set()
    async def later():
        t = api._spawn_kg_extraction(Sess(), "later")
        assert t is not None
        await t
    asyncio.run(later())
