# Phase 14 §61-64, §69-72 — Observability

## What already existed (confirmed by reading the code)

- `orca/serve/metrics.py` — a real in-process metrics module: request
  counts/status/duration (`record_request`), moderation actions,
  registry fallbacks, routing decisions, percentile calculation
  (`_percentile`), a JSON snapshot (`get_metrics_snapshot`), and a real
  **Prometheus text-format exporter** (`get_prometheus_text`). This
  predates Phase 14 and was not modified this phase.
- `orca/serve/api.py`'s `/api/cognitive/execute` response already
  includes `request_id` and `trace_id` fields (line ~686-687) — trace
  identity already exists in the response contract, though this phase
  did not audit whether every intermediate subsystem call
  (Kernel → Gateway → Truth → Memory) actually threads the SAME
  `trace_id` through rather than each generating its own.

## Cloud-provider backends (spec §61)

No GCP Cloud Monitoring / Azure Monitor / AWS CloudWatch integration
exists or was added this phase — none of these cloud accounts exist yet
in this environment (see `PHASE_14_CLOSURE.md`'s OWNER ACTION REQUIRED
checkpoints). `orca/serve/metrics.py`'s Prometheus-text export is
provider-neutral by construction (any of the three clouds' native
monitoring stacks can scrape a Prometheus-format endpoint), which is
the correct portable foundation per spec §61's own instruction — no
provider-specific work was needed to satisfy that requirement's intent.

## Cloud-neutral tracing across 3+ service boundaries (spec §62, §71)

**Not verified as an executable, asserted test this phase.** The
`trace_id` field exists in at least one response contract (above), but
no test in this codebase asserts "the same trace_id appears in the API
response AND in a Gateway-internal log line AND in a Truth Fabric log
line for the same request" as a checked property. This is a real,
specific, disclosed gap — not claimed as met.

## Security event pipeline (spec §63-64) — design only, not built

No normalization pipeline unifying Cloudflare/auth/Capability-Engine/
Godmode/connector/Simulation/deployment events into one structured
security-telemetry stream exists in this codebase. This is explicitly
gated on Cloudflare existing (§3, §63's own framing assumes a
Cloudflare event source) — since no Cloudflare account exists yet (see
`CLOUDFLARE_ARCHITECTURE.md`), this pipeline was not built this phase.
The individual event sources it would normalize (Godmode's
`_AUDIT_LOG`, auth's hash-chained `audit_log` table) already exist
independently — this phase did not merge them.

## SLO foundation (spec §72)

Per spec's own instruction ("do not claim achieved SLO before
measurement"): no SLO target is stated here as *achieved*. A candidate
starting point, grounded in what this phase actually measured on this
one machine (not a production claim):

- Availability target: not measurable without real production traffic.
- Latency: the full deterministic test suite's own timing (not a
  latency SLO, but the only real timing data this phase generated) —
  see `EVALUATION.md`.
- Error-rate objective: not measurable without real production traffic.
- Queue rejection objective: the existing `ConcurrencyLimiter`'s
  `max_queue_depth` is a bound, not a measured objective.

Establishing real SLOs requires real production or staging traffic,
which requires the cloud environment this phase did not provision.
