# Browser Stop and Recovery

**Status: NOT VERIFIED (no Chromium journey run in this agent VM)**

Frontend already aborts via `AbortController` (`conversation.html`).  
Server cancels `KernelStreamBridge` on `request.is_disconnected()`.

Antigravity should re-run journey Stop/disconnect cases (browser_stream_journey / B1) on the final SHA.
