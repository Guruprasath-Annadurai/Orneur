# Orneur Phase 0 — Production Gap Analysis

Severity: **P0 critical**, **P1 high**, **P2 medium**, **P3 low**. Each gap cites the evidence behind it (full detail in the companion status docs) and a recommended phase, not a recommendation to act now.

## P0 — Critical

| Gap | Evidence | Risk | Recommended phase |
|---|---|---|---|
| Aeternum (ultra) has no trained checkpoint | `test_persona_claim_gate.py` explicitly covers "no eval/redteam files at all" as current reality | Any Orneur claim about a 3-tier model family is false for the third tier today | Model training (Phase 1 follow-on) |
| Nano's base model is ambiguous between two config files (Qwen2.5-3B vs 7B) | `orca/train/variants.py` docstring vs. its own code value; `orca/train/config.py` preset disagrees with the code value | Training Orneur Genesis on the wrong base model wastes a full training cycle | Phase 1, before any Genesis retraining |
| `fs_server.py` prefix-confusion path-traversal bug | New finding, `orca/mcp/fs_server.py`'s `_safe_path()` uses `startswith()` not proper path resolution | Potential sandbox escape via a sibling-directory name collision on the MCP filesystem server | Phase 1, security fix |

## P1 — High

| Gap | Evidence | Risk | Recommended phase |
|---|---|---|---|
| No paid real-time search API | `orca/tools/web.py` scrapes DuckDuckGo only | Search quality/reliability ceiling, no SLA | Phase 2-equivalent work |
| Hallucination/grounding judge built but unwired | Zero call sites for `check_grounding()` found repo-wide | A "Truth Fabric" claim is weaker than the code could support with a small wiring fix | Quick win, any phase |
| `run_shell` tool has no path restriction | Documented in existing `docs/SECURITY_AUDIT.md`, reconfirmed | An allowlisted read command can reach files outside the intended workspace | Security hardening phase |
| No model registry with promotion/rollback | `orca/serve/registry.py` only resolves "currently installed" model per tier | Cannot safely test a new checkpoint alongside a stable one, no rollback path | Phase 1 (per user's own Phase 1 scope) |
| No dataset versioning/checksums, no active experiment tracking | wandb wired but never enabled; mlflow absent; no checksum files found anywhere | Training runs are not reproducible from records alone; adapter provenance depends on filename discipline only | Phase 1 (per user's own Phase 1 scope) |
| Single-host/single-GPU inference, no scaling story | No vLLM/continuous-batching/KV-cache-sharing; no multi-instance inference architecture | Cannot serve more than one host's worth of GPU capacity | New phase, not currently in the roadmap at all |
| Auth secret dev-fallback risk | `ORCA_AUTH_SECRET` falls back to a hardcoded dev string if unset | Real risk if ever left unset in an actual deployment; not verified whether current deployments set it | Security hardening phase |

## P2 — Medium

| Gap | Evidence | Risk | Recommended phase |
|---|---|---|---|
| Citation enforcement is marker-presence-only | `citation_check.py`'s own docstring admits this scope | Overclaiming "verified citations" would be a real, catchable false claim | Documentation honesty fix now; deeper verification later |
| Cost-aware routing is a regex heuristic, not a trained classifier | `routing.py`'s own code comment | "Our routing model" language would overclaim; "rules engine" is accurate | Phase 3-equivalent work, if ever upgraded |
| Rate limiter fails open on Redis outage; trusts `X-Forwarded-For` unconditionally | `ratelimit.py` | Silent degradation under partial infra failure; spoofable bucket without a real reverse proxy | Hardening phase |
| Deployment naming already inconsistent (Orca/Atheris/orca.systems/atheris.ai/orca.ai) | `k8s/*.yaml`, `docker-compose.yml`, `pyproject.toml`, `orca/cli.py`, `install.sh` | Confusing to operators and to any future Orneur migration; not a security issue | Brand migration phase |
| Full rate-limit endpoint coverage not exhaustively re-verified | Only the primitive itself was confirmed | Possible gap if some route doesn't call the limiter | Quick audit pass |

## P3 — Low

| Gap | Evidence | Risk | Recommended phase |
|---|---|---|---|
| `doctor.py`'s `shell=True` fix-runner | `orca/doctor.py:448` | Low — input built from internal check definitions, not remote/untrusted input directly | Opportunistic cleanup |
| No perplexity/standard-benchmark harness (MMLU, HumanEval) | Confirmed absent from `orca/train/` | Limits external comparability of Orneur's models against public leaderboards | Later, if desired for marketing/positioning |
| No general schema-migration framework (only a one-off SQLite→Postgres script) | `orca/auth/migrate_to_postgres.py` | Manageable at current scale; would matter more with frequent schema changes | Deployment hardening, later |

## Explicitly NOT gaps — things that are already solid and should not be re-litigated

- The persona-claim governance gate (`orca/governance/model_cards.py`) is real, runtime-enforced, and already does exactly what an honesty-first platform needs — preserve this mechanism through any rebrand.
- Test suite: 409 real tests, all passing, genuinely exercising conditional logic.
- Password/token/API-key handling: real, modern, correctly implemented.
- Account deletion cascades real cleanup across memory, docs, and knowledge-graph stores — a genuine right-to-delete implementation, not a stub.
- No unbounded agent loops or `while True` autonomy risks exist anywhere in the codebase today.
