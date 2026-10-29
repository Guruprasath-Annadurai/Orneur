# Producer–Consumer Lifecycle Proof

## Defect

Handoff sample closed the channel only after `async for` finished → potential hang.  
`close()`/`fail()` used `create_task` on full queue → orphan tasks.

## Fix

- `RawDeltaChannel`: `asyncio.Event` wake; drain-then-exit on close; no background enqueue tasks.
- `KernelStreamBridge`: producer task always `close()`/`fail()`s; `cancel()` awaits cleanup.

## Tests (`tests/test_raw_delta_channel_lifecycle.py`)

success close; zero chunks; fail before/after chunks; full queue no drop; cancel while blocked on push; terminal once; no orphan producer.
