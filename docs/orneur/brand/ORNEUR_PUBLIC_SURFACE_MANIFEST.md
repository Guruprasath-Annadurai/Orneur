# ORNEUR Public Surface Manifest

Defines what counts as an "active public surface" for the brand invariant
test (`tests/test_brand_invariant.py`). Only files listed here are
scanned for stale Orca/Atheris branding; everything else (historical
phase docs, test fixtures, internal Python namespace) is intentionally
out of scope, per `ORNEUR_IDENTITY_STANDARD.md`.

This exists so the invariant test cannot accidentally start failing
because someone edits an archived Phase-1 doc, and cannot accidentally
pass by having a regex so broad it excludes half the repository.

## Active public surfaces (scanned by the brand invariant test)

| Path | Why it's public |
|---|---|
| `README.md` | First thing a visitor reads |
| `pyproject.toml` | Package metadata shown on PyPI/pip |
| `install.sh` | Installer banner/messages |
| `orca/character.py` | Injected into every LLM system prompt + CLI `--help` |
| `orca/tui.py` | Terminal boot banner |
| `orca/cli.py` | `--help`/command output |
| `orca/serve/api.py` | FastAPI/OpenAPI title |
| `orca/serve/web/index.html` | Chat app UI |
| `orca/serve/web/landing.html` | Marketing landing page |
| `orca/serve/web/trust.html` | Trust & Security page |
| `orca/upgrade.py` | Self-update messaging + real package target |
| `docs/MODEL_CARDS.md` | README-linked ("Model Cards & the Persona Claim Gate") |
| `docs/SECURITY_AUDIT.md` | README-linked ("Security Audit") |
| `docs/PERPLEXITY_DIFFERENTIATION_PLAN.md` | README-linked ("Differentiation Strategy") |
| `docs/AETERNUM_TRAINING_PLAN.md` | README-linked ("Aeternum Training Plan") |

## Explicit exclusions (not scanned, with reason)

| Path/pattern | Reason |
|---|---|
| `docs/orneur/phase-*/**` | The project's own historical engineering-closure audit trail; rewriting it would destroy the record other code comments cite by path |
| `docs/orneur/brand/**` | These documents legitimately discuss "Orca"/"Atheris" as the subject of the audit itself |
| `tests/**` | Internal test fixtures/imports (`from orca.cli import app`, legacy Ollama model-name fixtures) |
| `.git/**`, git history | Immutable historical record |
| `orca/**/*.py` internal imports/class names (`OrcaBrain`, `OrcaNano`, `orca.registry.model_spec`, etc.) | Internal Python namespace, explicitly not renamed this closure — see `ORNEUR_IDENTITY_STANDARD.md` |
| `orca/license/keys.py`, `orca/auth/apikeys.py` | Live, stable token-format generators (`ORCA-`/`athr_`) — a live-format string is not "stale branding," it's a functional compatibility surface, tracked separately in `ORNEUR_LEGACY_NAMESPACE_MIGRATION.md` |
| Remaining top-level `docs/*.md` NOT linked from README (14 files: `ARCHITECTURE.md`, `ORCA_BLUEPRINT.md`, `SELF_HOSTING.md`, `RUNBOOK.md`, `STARTUP_PLAN.md`, `LOGO_DESIGN_PROMPT.md`, `CLAUDE_DESIGN_PROMPTS.md`, `API_REFERENCE.md`, `DEVELOPMENT_PHASES.md`, `DESIGN_BRIEF.md`, `LAUNCH_PLAN.md`, `FRONTIER_ROADMAP.md`, `MASTER_PLAN.md`, `FINAL_PLAN.md`, `STITCH_DESIGN_PROMPT.md`) | Deliberately deferred (see `ORNEUR_IDENTITY_AUDIT.md`'s "DEFERRED" rows) — not directly linked from the live README, so lower priority than the four docs above, which ARE README-linked and therefore promoted into the scanned set |
| `docker-compose.yml`, `Dockerfile*`, `k8s/**` | Deployment config, not end-user-facing product identity; already partially migrated (see audit) |

## Allowlisted exceptions within scanned files

Every allowlist entry below must have a reason — no blanket exclusions.

| File | Allowed string | Reason |
|---|---|---|
| `README.md` | `ORCA-PRO-XXXXX-XXXXX-XXXXX` | The real, current, stable license-key format — changing the docs without changing the generator would make the docs lie |
| `README.md` | `` `orca/tools/search_grounding.py` ``, `` `orca/docs/citation_check.py` ``, `` `orca/serve/routing.py` `` | Legitimate internal module-path references in technical prose, explicitly permitted by `ORNEUR_IDENTITY_STANDARD.md` |
| `orca/serve/web/index.html` | `appendOrcaMsg`, `orcaEl`, `orca-row`, `orca_token` | Internal JS function/variable/CSS-class/localStorage-key names, not displayed text |
| `orca/upgrade.py` | module docstring's explanation of the `orca-ai`/"Orca Systems" investigation | Historical explanation of why the fix was made, not live branding |
| `docs/SECURITY_AUDIT.md` | `"You are Orca — a powerful,` | A factual quote of what the model actually said during a 2026-07 eval run, before the rebrand — rewriting it to "Orneur" would misrepresent the historical finding |
| `docs/MODEL_CARDS.md`, `docs/AETERNUM_TRAINING_PLAN.md` | `orca-core`, `orca-ultra`, `orca-nano*`, `orca_nano_llama3_train_v3_safety.jsonl`, `orca_core_finetune_kaggle_v2.ipynb` | Real legacy Ollama model tags / dataset / notebook filenames, not the product name — lowercase, distinct from the capitalized "Orca" wordmark pattern this test flags |

Any new allowlist entry added in the future must come with its own reason
in this table, in the same commit that adds it.
