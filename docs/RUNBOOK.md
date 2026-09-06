<!--
Incident response runbook for Orca's production serving layer. Every
scenario below is either a real incident found and fixed during this
project's own load testing, or a real, concretely-scoped operational
procedure — not generic boilerplate. Update this file whenever the
underlying code changes; a runbook that's drifted from what the code
actually does is worse than no runbook.
-->

# Orca Production Runbook

## 1. Health checks — which one to use for what

| Endpoint | Use for | Cost |
|---|---|---|
| `GET /healthz` | Load balancer / orchestrator liveness & readiness probes, polled every few seconds | Cheap — one cached registry lookup, no disk I/O. Measured: p50 8ms, p95 ~1ms, max 38ms under 25-concurrent load. |
| `GET /api/status` | Human/dashboard checks, occasional polling only | Heavier — globs every raw training file on disk and lists all sessions. Measured: p50 282-293ms, max ~400ms under 10-concurrent load. **Do not point a frequent automated health check at this endpoint** — it was built for occasional dashboard refreshes, not orchestrator polling. |
| `GET /metrics` | Prometheus scrape target | No auth by design (standard scrape convention) — put a firewall/reverse-proxy rule in front if this port is reachable from outside your private network. |
| `GET /api/admin/metrics` | Human-readable JSON metrics, admin-authenticated | Same data as `/metrics`, requires login. |

`/healthz` returns `503` with a `reason` field if no model resolves for the nano tier — treat that as a real outage signal, not a transient blip, since it means the registry couldn't find ANY installed model for the tier or its fallback chain.

## 2. What to watch, and why

- **`orca_errors_total` by endpoint** (from `/metrics`) — any nonzero rate on `POST /api/chat` or `/api/stream` is worth investigating immediately; those are the user-facing revenue path.
- **`orca_moderation_actions_total{action="block"}`** — a sudden spike could mean either a real attack wave or a false-positive regression in `orca/serve/moderation.py`'s patterns (check recent commits to that file first). A sudden drop to zero after previously showing nonzero blocks is equally worth investigating — it could mean the moderation check stopped being called somewhere in the request path.
- **`orca_registry_fallbacks_total`** — any nonzero value means a tier is being served by a DIFFERENT model than configured (e.g. ultra silently falling back to core because ultra's model isn't installed). This is expected behavior, not a crash, but it means users requesting that tier aren't getting what they think they're getting — investigate why the configured model isn't installed.
- **`orca_latency_p95_ms{endpoint="POST /api/chat"}`** — **real measured finding**: local CPU-bound Ollama inference degrades sharply under concurrency. In this project's own load test, 6 chat requests at concurrency=3 had a p50 of ~27.7 seconds and a max of 41.6 seconds — compare this against whatever hardware you're actually running Ollama on. If deploying for real user traffic, GPU-backed Ollama hosting is very likely required to keep latency acceptable under concurrent load; CPU-only inference on a laptop-class machine will not scale past a handful of simultaneous users.

## 3. Known incidents (found and fixed during this project's own testing)

### 3.1 "Model not found" on every single chat request despite the model being installed
**Symptom**: `POST /api/chat` returns 500 with `Model 'orca-nano' not found in Ollama` — even though `ollama list` clearly shows it installed.
**Root cause**: `OrcaBrain._resolve_model()` (`orca/brain/providers.py`) did an exact string match against Ollama's `/api/tags` listing, but Ollama always returns tagged names (`orca-nano:latest`) while the configured model name is bare (`orca-nano`). Every real request failed.
**Fix**: `_resolve_model()` now checks both the bare and `:latest`-suffixed form (matching the normalization `orca/serve/registry.py`'s `_model_installed()` already had). Covered by `tests/test_brain_providers.py`.
**If you see this again**: check whether a NEW model-name-comparison codepath was added somewhere that doesn't use this normalization — this is an easy bug to reintroduce in a new function that reads Ollama's tag list directly.

### 3.2 Every chat message crashes with a ChromaDB metadata error
**Symptom**: `POST /api/chat` returns 500 with `ValueError: Expected metadata to be a non-empty dict, got 0 metadata attributes in add.`
**Root cause**: `LongTermMemory.store()` (`orca/brain/memory.py`) defaulted to an empty `{}` metadata dict when the caller (the normal `commit_to_long_term()` path, called after every chat turn) didn't pass explicit metadata. A chromadb version upgrade started rejecting empty metadata dicts outright.
**Fix**: `store()` now always includes at least a `stored_at` timestamp, so the dict is never empty. Covered by `tests/test_memory_store_metadata.py`.
**If you see this again**: check whether chromadb's `validate_metadata()` behavior changed again in a dependency upgrade, or whether a new caller passes an empty dict some other way.

## 4. Common operational scenarios

### Ollama process is down / unreachable
- `/healthz` returns 503.
- All chat/stream requests will fail. `OrcaBrain._list_available()` (`orca/brain/providers.py`) raises a clear `RuntimeError("Ollama is not running...")` — this surfaces to the user as a 500, not a silent hang.
- Recovery: restart Ollama (`ollama serve`), confirm `ollama list` shows expected models, re-check `/healthz`.

### A tier's configured model isn't installed (e.g. ultra was never fine-tuned yet)
- Requests to that tier are NOT rejected — `orca/serve/registry.py`'s `resolve_tier_model()` steps down (ultra → core → nano) and serves the best available fallback instead.
- This is silent to the END USER by design (better degraded service than an error), but IS visible in `orca_registry_fallbacks_total` and in application logs (`_logger.warning` in `orca/serve/api.py`). Check that metric/log if a tier "works" but seems to respond with the wrong persona/quality.

### Sudden spike in blocked requests
- Check `orca_moderation_actions_total{action="block"}`.
- Pull a sample of the actual blocked messages from the audit log (`orca/audit.py` — `input_moderation_blocked` entries) to determine if this is a real attack wave or a false-positive pattern match.
- `orca/serve/moderation.py`'s jailbreak-framing detector requires BOTH a manipulation-framing pattern AND a harm-adjacent topic before blocking (see that module's docstring) specifically to minimize false positives — if you're seeing legitimate user messages blocked, check `_JAILBREAK_FRAMING_PATTERNS` and `_HARM_ADJACENT_TOPIC_PATTERNS` for an overly broad regex.

### High latency on chat/stream endpoints
- Check whether this correlates with concurrent request volume (see §2 latency note — this is expected behavior on CPU-only Ollama hosting, not necessarily a bug).
- If latency is high even at low concurrency, check Ollama's own resource usage (CPU/GPU/memory) on the host machine.

### Disk space exhaustion (local model management)
- Ollama models are large (4.5-4.9GB each). This project's own development hit this exact issue multiple times when accumulating multiple fine-tuned checkpoint versions locally.
- Check `ollama list` and remove superseded checkpoints (`ollama rm <model>`) — verify via `df -h` before and after.
- Production deployments should size disk allocation for: base model(s) + however many fine-tuned variants you keep live + headroom for a new version during a rollout (don't delete the old version until the new one is verified).

### Rollback to a previous model version
- Models are managed via Ollama aliases (e.g. `orca-nano` pointing at whichever checkpoint is "current"). To roll back: `ollama cp <previous-good-model> orca-nano` — this repoints the alias without needing to touch application config or restart the API server (the registry re-resolves on each request, with a 15-second cache).
- Always verify the previous checkpoint is still present locally (`ollama list`) before attempting this — if it was deleted, you'll need to re-download/re-register it from wherever the GGUF file is archived.

## 5. Load testing summary (this project's own measurements, single local instance, CPU-only Ollama)

| Endpoint | Load tested | Success rate | Latency (p50 / max) |
|---|---|---|---|
| `GET /healthz` | 100 req, concurrency 25 | 100/100 | 8ms / 38ms |
| `GET /api/status` | 40 req, concurrency 10 | 40/40 | 282-293ms / ~400ms |
| `POST /api/chat` | 6 req, concurrency 3 | 6/6 (after fixing §3.1 and §3.2) | 27.7s / 41.6s |

**Honest takeaway**: the API layer itself (routing, moderation, registry, metrics) is solid under load — the two real bugs found were both in the brain/memory layer, not the serving layer, and both are now fixed and tested. The actual bottleneck for real user traffic is Ollama inference speed on non-GPU hardware, which is a hosting/infrastructure decision, not a code bug. Do not commit to a concurrent-user capacity number without testing on the actual production hardware you intend to deploy on.
