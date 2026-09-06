# Orneur Phase 0 — Brand Migration Plan (PLANNING ONLY — NOT EXECUTED)

No renaming has been performed. This document classifies every meaningful first-party "orca" reference so a future, deliberate migration can be scoped and sequenced safely.

## Critical finding to resolve before planning further

The requested Orneur model names — **Genesis / Novus / Aethernum** — are **not new**. A near-identical scheme already exists throughout the codebase as the public-facing tier names: **Genesis (nano) / Novus (core) / Aeternum (ultra)**. Note the spelling: the incumbent is "**Aeternum**", the requested target is "**Aethernum**" — one letter apart. Confirmed live in `orca/cli.py:1069`'s `persona_names` dict, `orca/auth/db.py`, `orca/brain/backends.py`, `orca/auth/store.py`, `orca/data/seeds.py`, `orca/lens/generate.py`, `orca/lens/intent.py`, and an entire dedicated doc (`docs/AETERNUM_TRAINING_PLAN.md`).

**Decision needed before Phase 1 touches any of this**: adopt the existing "Aeternum" spelling (zero-cost, nothing to change), or deliberately respell to "Aethernum" everywhere it appears (real, mechanical work across code, docs, model names, and the `ultra` persona's identity text). This is a one-letter decision with repo-wide surface area — resolve it explicitly, don't let it happen by accident during a broader find-and-replace.

## Package/module/binary identity (confirmed)

- **PyPI/pip package name**: `orca-ai` (`pyproject.toml:6`)
- **Importable Python module**: `orca` (`[tool.hatch.build.targets.wheel] packages = ["orca"]`)
- **CLI binary name**: `orca` — same as the module, not the pip name (`[project.scripts] orca = "orca.cli:app"`, `pyproject.toml:108`)

These three are already inconsistent with each other (pip name vs. module/binary name) even before Orneur — worth deciding whether Orneur's equivalent triple should finally be made consistent.

## Classified inventory

| Category | Finding |
|---|---|
| FIRST-PARTY BRAND | Pervasive in README, docs, legal prose (~45 hits in README.md alone) |
| FIRST-PARTY IDENTIFIER | Python module `orca` and all submodules (`orca.serve`, `orca.auth`, etc.) across 112 `.py` files |
| FIRST-PARTY MODULE/PACKAGE | `orca-ai` (pip), `orca` (module/binary) — see above |
| FIRST-PARTY CONFIG | `ORCA_HOME` (`orca/config.py:16`), Postgres user/db named `orca` in docker-compose |
| FIRST-PARTY ENV VARS | **42 distinct `ORCA_*` variables** (full list below) |
| FIRST-PARTY API | No route *paths* contain "orca" (routes are generic: `/api/chat`, `/healthz`, etc.) — only in derived filenames (`orca-{session_id}.md` export names) |
| FIRST-PARTY DATABASE IDENTIFIER | Table names are generic; the identifying artifact is the `~/.orca/auth.db` path and Redis key prefixes `orca:ratelimit:`, `orca:session:` |
| FIRST-PARTY MODEL IDENTIFIER | **11 distinct Ollama model names**: `orca-core`, `orca-core-combined`, `orca-core-dpo`, `orca-core-qlora`, `orca-core-v1`, `orca-core-v2`, `orca-nano`, `orca-nano-qlora`, `orca-nano-v7`, `orca-ultra`, `orca-ultra-qlora` |
| FIRST-PARTY ARTIFACT PATH (Kaggle) | **6 distinct dataset/kernel slugs** under `guruprasathannadurai/orca-*`, plus 15+ notebook filenames encoding version history informally |
| FIRST-PARTY CONTAINER/SERVICE | **Inconsistent already**: Dockerfiles/fly.toml use `orca-demo`/`orca` naming, but **k8s and docker-compose use `atheris`** naming — a pre-existing third brand, see `DEPLOYMENT_BASELINE.md` |
| FIRST-PARTY CI/CD | Workflow/job names are generic; "Orca" only appears in step display text ("Install Orca...") |
| FIRST-PARTY TELEMETRY | `orca_uptime_seconds` metric, `orca.serve` logger namespace, `orca:ratelimit:`/`orca:session:` Redis key prefixes |
| FIRST-PARTY DOCUMENTATION | Pervasive — 19 files in `docs/`, 3 in `legal/`, each with 2–30 "orca" mentions. Treat as blanket rewrite scope, not enumerated line-by-line |
| HISTORICAL REFERENCE | **None found** — no trace anywhere of the earlier "Aethlis" naming attempt from earlier in this project's history |
| BACKWARD-COMPATIBILITY REQUIREMENT | The `ORCA_HOME` (`~/.orca/`) directory contains real user data (auth.db, trained model artifacts, training data) on any existing install — a rename must not silently orphan this directory |
| THIRD-PARTY OR EXTERNAL ORCA NAME | **Confirmed absent.** No dependency in `uv.lock` is literally named `orca` (the only `orca*` entry is this project's own `orca-ai`). No citation anywhere of the Microsoft "Orca" LLM paper or any other external Orca-branded tool/product. **Nothing here is off-limits to rename on those grounds.** |

### Full `ORCA_*` environment variable list (42)

```
ORCA_ALLOW_UNSIGNED_WEBHOOKS, ORCA_ANTHROPIC_API_KEY, ORCA_ANTHROPIC_MODEL_CORE,
ORCA_ANTHROPIC_MODEL_ULTRA, ORCA_ASCII, ORCA_ASCII_COMPACT, ORCA_AUDIT_KEY,
ORCA_AUTH_SECRET, ORCA_BASE_MODEL, ORCA_BLUEPRINT, ORCA_CORE_BACKEND,
ORCA_CORE_MODEL, ORCA_COST_AWARE_ESCALATION, ORCA_DATABASE_URL,
ORCA_DATA_SOVEREIGNTY_LOCK, ORCA_DB_PASSWORD, ORCA_EPOCHS,
ORCA_ESCALATION_BACKEND, ORCA_ESCALATION_DAILY_CAP, ORCA_GOVERNANCE_KEY,
ORCA_HOME, ORCA_JWT_SECRET, ORCA_LICENSE_SECRET, ORCA_MODEL_BACKEND,
ORCA_NANO_BACKEND, ORCA_NANO_MODEL, ORCA_OLLAMA_HOST, ORCA_OLLAMA_MODEL,
ORCA_OPENAI_API_KEY, ORCA_OPENAI_MODEL_CORE, ORCA_OPENAI_MODEL_ULTRA,
ORCA_PRESET, ORCA_PUBLIC_URL, ORCA_RANK, ORCA_REDIS_URL, ORCA_SYSTEM,
ORCA_SYSTEM_PROMPT, ORCA_TEST_SECRET, ORCA_TEST_SECRET_SHELL,
ORCA_ULTRA_BACKEND, ORCA_ULTRA_MODEL, ORCA_VOICE, ORCA_VERSION
```

### Domains already in play (a fourth naming axis)

Three distinct live domain references exist today: `atheris.ai` (pyproject.toml Homepage/Docs/Changelog), `orca.systems` (CLI purchase/contact/docs links, install script), `orca.ai` (one marketing-doc reference). GitHub repo URL is `github.com/Guruprasath-Annadurai/Orca`. Any Orneur domain decision needs to account for all of these, not just pick a new domain in isolation.

## Migration ordering (planning only — do not execute)

Recommended order, safest-first, once the Aeternum/Aethernum spelling decision is made:

1. **Documentation and brand prose** (docs/, README, legal/) — zero functional risk, purely textual.
2. **Environment variable names** — requires a compatibility shim period (accept both `ORCA_*` and `ORNEUR_*` for one deprecation cycle) since existing deployments/`.env` files depend on the current names.
3. **Python package/module/CLI binary rename** (`orca` → `orneur`) — highest mechanical blast radius (112 files), should be done via a scripted rename + full test-suite re-run, not manual edits. The pip-name/module-name/binary-name inconsistency should be resolved in the same pass, not left split again.
4. **`ORCA_HOME` (`~/.orca/`) directory** — must be migrated, not abandoned: existing installs have real data (auth.db, trained artifacts) there. Plan a one-time migration path (copy/symlink `~/.orca` → `~/.orneur` on first run of the renamed binary), not a silent break.
5. **Ollama model names and Kaggle dataset/kernel slugs** — rename going forward for new training runs; existing checkpoints should be mapped `orca-core:<version> → orneur-novus:<version>` while preserving the underlying weight files and any checksums (none currently exist — see `MODEL_TRAINING_STATUS.md` — so this is also the moment to add them).
6. **Deployment naming** (`k8s/*.yaml`, `docker-compose.yml`, `fly.toml`) — do this together with step 3, since it's already inconsistent (`atheris` vs `orca`) and shouldn't be migrated twice.
7. **Domain/external-facing identity** (which of `atheris.ai`/`orca.systems`/`orca.ai` becomes the canonical Orneur domain, and what happens to the others) — a business decision, not an engineering one; sequence last since it doesn't block any internal work.

## Target end-state

**FIRST-PARTY STALE ORCA REFERENCES: 0** — every category above fully migrated, with the `~/.orca/` → `~/.orneur/` data migration verified non-destructive (existing user data preserved), and the Aeternum/Aethernum spelling decision applied consistently everywhere rather than left mixed.

## What must NOT be touched by any migration

Per the explicit prohibition in this Phase 0 request: no existing model weights, checkpoints, or trained adapters get rewritten, moved, or destroyed as part of branding. Lineage mapping (`orca-core:<version> → orneur-novus:<version>`) must preserve the underlying files and add checksums where none exist today, not replace anything in place.
