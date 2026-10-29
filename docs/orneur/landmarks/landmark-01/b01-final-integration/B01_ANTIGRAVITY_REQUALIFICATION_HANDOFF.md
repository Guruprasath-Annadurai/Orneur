# Antigravity Requalification Handoff

1. Checkout `63f2dfa7cd51f4a79a1e09102c7fe7ad14b06520` on
   `cursor/b01-real-sse-chatbot-integration-1cdf` (exact-head CI green —
   run `40842561058`, Deterministic `9024 passed`). If the branch tip moved
   for docs-only commits, re-confirm CI on the tip before qualifying.
2. Confirm mandatory CI green on the SHA under test.
3. Re-run live Ollama (`llama3.2:1b`) + Chromium journeys (Stop, upstream
   delivery, DLP) beyond the CI Journeys fixture-provider job.
4. Reconcile prior Antigravity fixture-vs-real counts; do not inherit Cursor
   self-cert as G13.
5. Focus: producer-consumer lifecycle, Kernel deferral → AgentLoop
   fall-through, StreamRedactor, quota, SQLite fencing, temp-chat,
   multi-worker.
