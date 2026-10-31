# B-01 — Claude API Integration Handoff

**From:** Cursor Kernel remediation  
**To:** Claude (`claude/landmark-01-secure-chatbot-integration` / PR #134 lineage)  
**Do not:** edit `conversation.html` from Cursor; do not invent a second `_stream_dispatch` design outside this contract.

## Why the API must change

Today `_stream_dispatch` does:

```text
cognitive_result = await _run_cognitive_kernel(...)   # FULL generate() finishes
# … later inside _event_stream:
if use_kernel_direct:
    delivery = "replayed"; cancellable = False
    yield one chunk with the complete text
```

Even with Kernel streaming available, **awaiting the Kernel before StreamingResponse** still forces replayed delivery. Claude must start the HTTP SSE response and run the Kernel **concurrently**.

## New Kernel contract (already on Cursor branch)

```python
from orca.cognitive.contracts import CognitiveRequest
from orca.cognitive.streaming import RawDeltaChannel

channel = RawDeltaChannel(maxsize=64)  # never silently drops
req = CognitiveRequest(
    objective=message,
    session_id=session_id,
    tenant=user.id if user else None,
    requested_mode=model_variant,
    on_raw_delta=channel.as_hook(),  # RAW — not browser-safe
)
task = asyncio.create_task(kernel.execute(req, entitlement=..., doc_store=...))
```

## Exact patch shape for `_stream_dispatch` / `_run_cognitive_kernel`

### 1. Extend `_run_cognitive_kernel` (or sibling)

Accept optional `on_raw_delta` and pass it into `CognitiveRequest`. Keep the non-streaming `/api/chat` path with `on_raw_delta=None`.

### 2. For ollama + expected kernel-direct turns (no docs / Truth Fabric answer)

Inside the SSE generator (after session/generation events, **before** waiting for full output):

```python
from orca.serve.stream_dlp import StreamRedactor

channel = RawDeltaChannel(maxsize=64)
# Construct CognitiveRequest with on_raw_delta=channel.as_hook()
kernel_task = asyncio.create_task(_run_cognitive_kernel(..., on_raw_delta=channel.as_hook()))

yield session event
yield generation event
# Prefer emitting model identity as soon as tier/identity is known;
# if identity needs CognitiveResult.resolved_*, emit a provisional identity
# then correct on done — but do NOT wait for full text before first chunk.

yield {"type": "stream", "delivery": "upstream", "cancellable": True}

redactor = StreamRedactor()
full = ""
try:
    async for raw_delta in channel:
        if await request.is_disconnected():
            kernel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await kernel_task
            redactor.cancel()
            return
        _consume_message_quota(user, request)  # first billable output
        safe = redactor.push(raw_delta)
        if safe:
            full += safe
            yield chunk(safe)
    cognitive_result = await kernel_task
    channel.close()
except BaseException:
    kernel_task.cancel()
    channel.fail(...)
    raise

tail = redactor.finish()
...
# Persist ONLY redacted `full` / redactor.safe_text(); never channel raw.
# delivery on done: "upstream" iff true upstream streaming was used.
# persisted: saved|failed|not_applicable — truthful, as today.
```

### 3. Gate carefully (B-06)

If the session has documents and the Kernel answer would be discarded today, **do not** start a streaming Kernel answer that will be thrown away — either skip Kernel stream (existing AgentLoop upstream path) or implement B-06 separately. Cursor did not change B-06.

### 4. `/api/chat`

Leave `on_raw_delta=None`. Non-streaming JSON route must keep working.

### 5. Protocol invariants Claude must preserve

| Event | Rule |
|---|---|
| Pre-admission HTTP JSON | Unchanged (401/402/400/404/429 before SSE) |
| `delivery` | `"upstream"` only when Kernel/gateway stream actually used |
| `cancellable` | `true` only when `kernel_task.cancel()` stops upstream |
| Stop / disconnect | cancel task + aclose path; release turn authority in `finally` |
| Quota | consume on first billable chunk; no false refund after |
| Persistence | SQLite commit of redacted complete turn only; null/failed persist status honest |
| DLP | every external delta through `StreamRedactor` |
| Done | do not re-send the full answer as a second mega-chunk |

## Acceptance Claude should add

- Fixture delayed provider: ≥2 SSE chunks with measurable arrival spread; `delivery=="upstream"`.
- Existing `tests/test_canonical_route_dlp.py` still green.
- Journey B1 (real Ollama) when available: upstream + Stop works.

## Files Cursor changed (for your merge)

- `orca/cognitive/contracts.py` — `on_raw_delta`
- `orca/cognitive/streaming.py` — new
- `orca/cognitive/kernel.py` — `_answer_directly` stream path
- `tests/test_kernel_streaming.py` — new
- `docs/orneur/landmarks/landmark-01/b01-remediation/*`
