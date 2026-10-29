"""Reproduces the two producer/consumer defects in the PR #135 handoff (orca/cognitive/streaming.py at 15befec) and shows the corrected bridge on the same inputs.

Run from the repository root:  PYTHONPATH=. python docs/orneur/landmarks/landmark-01/b01-final-integration/evidence/lifecycle_defect_repro.py
It loads the ORIGINAL module straight from git (``git show 15befec:orca/cognitive/streaming.py``); nothing is mocked.
"""
import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ORIGINAL_SHA = "15befec7191a1992286d7fa027236002f7d385db"


def load_original():
    src = subprocess.run(["git", "show", f"{ORIGINAL_SHA}:orca/cognitive/streaming.py"], capture_output=True, text=True, check=True).stdout
    tmp = Path(tempfile.mkdtemp()) / "original_streaming.py"
    tmp.write_text(src)
    spec = importlib.util.spec_from_file_location("original_streaming", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["original_streaming"] = mod
    spec.loader.exec_module(mod)
    return mod


async def handoff_pattern(channel_cls):
    """The lifecycle sketched in B01_CLAUDE_API_INTEGRATION_HANDOFF.md: the consumer iterates the channel to its end, THEN awaits the kernel task, THEN closes."""
    channel = channel_cls(maxsize=4)

    async def kernel():
        for piece in ("a", "b", "c"):
            await channel.push(piece)
        return "RESULT"

    task = asyncio.create_task(kernel())
    seen = []
    async for d in channel:
        seen.append(d)
    result = await task
    channel.close()
    return seen, result


async def main():
    orig = load_original()
    print("== 1. handoff lifecycle against the ORIGINAL channel (15befec) ==")
    try:
        await asyncio.wait_for(handoff_pattern(orig.RawDeltaChannel), timeout=2.0)
        print("terminated")
    except asyncio.TimeoutError:
        print("HANG: the consumer waited 2s for a terminal signal that the sample only sends after the consumer has finished")

    print("== 2. close() on a FULL original channel ==")
    ch = orig.RawDeltaChannel(maxsize=1)
    await ch.push("x")
    before = len(asyncio.all_tasks())
    ch.close()
    after = len(asyncio.all_tasks())
    print(f"tasks before close()={before} after close()={after} -> {'UNTRACKED background task created' if after > before else 'no task'}")
    ch2 = orig.RawDeltaChannel(maxsize=1)
    await ch2.push("x")
    await ch2.push("y") if False else None
    ch2.fail(RuntimeError("late"))
    print(f"fail() on a full channel also spawned a task: {len(asyncio.all_tasks()) > before}")

    print("== 3. the corrected bridge (this branch), same shape of use ==")
    from orca.cognitive.streaming import KernelRun, RawDeltaChannel

    async def producer(hook):
        for piece in ("a", "b", "c"):
            await hook(piece)
        return "RESULT"

    run = KernelRun(producer, maxsize=4).start()
    seen = [d async for d in run.deltas()]
    result = await run.result()
    await run.aclose()
    print(f"terminated by itself: seen={seen} result={result} state={run.channel.state} terminal_observed={run.channel.terminal_observed}")
    full = RawDeltaChannel(maxsize=1)
    await full.push("x")
    before = len(asyncio.all_tasks())
    full.close()
    print(f"close() on a full channel: tasks before={before} after={len(asyncio.all_tasks())}; drained={[d async for d in full]}")


asyncio.run(main())
