# REAL_OLLAMA_AND_SERVING_REPORT

**Functional tip:** `2b6b6de8eccb2acbfaa5ece7ba52cebee8c357c8` (audit PR #132 HEAD after evidence freeze)

## Environment (this Cloud Agent run)

| Dependency | Status |
|---|---|
| Ubuntu | Available (container/VM) |
| Python 3.12 + project venv | Installed via `uv sync --extra dev --extra redis --extra postgres` |
| Real Redis | **Not available** (`redis-cli` missing; soak unverified) |
| SQLite | Used in-process for tests |
| Real Ollama + `llama3.2:1b` | **Not available** (no daemon on `:11434`) |
| Docker | Available for CI-style smoke; not used for live model here |

## Unit / fixture evidence (not live Ollama latency claims)

- Colon-safe deployment IDs: `tests/test_ollama_deployment_id.py` — PASS
- Inference gateway / reservation / DLP fixtures: ancestor P0 suites — PASS on targeted run
- Serving admission wiring for `/api/chat`, `/api/stream`, `/api/inference/*` — code-level

## Live model measurements

**None invented.** No latency, throughput, or token/s figures are reported because live Ollama was not exercised on this tip in this run.

### Required follow-up (qualification host)

```bash
# On a host with Ollama + llama3.2:1b + Redis:
ollama pull llama3.2:1b
pytest -q tests/journey/test_journey_api_live.py -m live_ollama_smoke
# Plus manual: POST /api/chat, /api/stream, /api/inference/complete with real model
```

Record exact SHA, command, pass/fail, and raw provider request payloads (redacted) in Antigravity’s package — do not backfill fake numbers here.

## Model identity truth

- Native GENESIS / NOVUS / AETERNUM are not aliases for Ollama tags.
- Served identity comes from server resolution (`model_identity`), not client spoofed labels.
