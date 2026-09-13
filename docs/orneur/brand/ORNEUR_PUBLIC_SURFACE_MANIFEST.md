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
| `docs/AETERNUM_TRAINING_PLAN.md` | README-linked ("Aeternum Training Plan (historical record, superseded)") |

## Document status classification (semantic truth closure)

Brand-string scanning alone doesn't catch a document that uses correct
ORNEUR branding while asserting stale or contradictory FACTS. Every
README-linked document is classified below; README must never describe a
`HISTORICAL_SUPERSEDED` document as current.

| Document | Classification | Rationale |
|---|---|---|
| `docs/MODEL_CARDS.md` | **CURRENT_SUPPORTING** | Describes a real, live mechanism (`check_persona_claim_allowed`, `PERSONA_CLAIM_THRESHOLDS`) that runs on every chat request today — accurate as a mechanism description once corrected to not overclaim which variants currently have a checkpoint/card |
| `docs/SECURITY_AUDIT.md` | **CURRENT_SUPPORTING** | A dated (2026-07-24) point-in-time scan whose findings/remediations remain the live security record; linked from README as the trust source |
| `docs/PERPLEXITY_DIFFERENTIATION_PLAN.md` | **CURRENT_SUPPORTING** | Contains a mix of original planning prose (some now stale, corrected this closure) and a later "Honest status update" section that is the actual current-truth record — kept as one document since the sections are explicitly dated relative to each other, not asserted as uniformly current |
| `docs/AETERNUM_TRAINING_PLAN.md` | **HISTORICAL_SUPERSEDED** | Predates the Phase 16 architecture audit; treats `Qwen2.5-14B-Instruct` as a selected base model and "14B" as the definition of "flagship" — both contradicted by `orca/registry/model_spec.py`'s `base_model=None`/`UNSELECTED_PROVISIONAL`. Marked with an explicit STATUS banner this closure; README no longer calls it "the real, current plan" |
| `README.md` | **CURRENT_CANONICAL** | The top-level entry point; must never assert anything a `HISTORICAL_SUPERSEDED` linked document contradicts |
| `docs/orneur/phase-16/PHASE16_NATIVE_INTELLIGENCE_BASELINE_AUDIT.md` | **CURRENT_CANONICAL** | The authoritative source of truth for native-model state, per this closure's own instructions — not itself README-linked, but is the document README's tiers table and this manifest defer to |

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
