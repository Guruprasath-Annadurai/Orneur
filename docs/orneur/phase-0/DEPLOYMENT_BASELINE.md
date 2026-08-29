# Orneur Phase 0 — Deployment Baseline

## What exists

- `Dockerfile` and `Dockerfile.fly` — both COPY the `orca/` package and CMD `["orca", "serve", ...]`. Set `ENV ORCA_HOME=...`, `ORCA_OLLAMA_HOST=...`.
- `docker-compose.yml` — defines a Postgres service (user/db named `orca`) and an app service.
- `k8s/{deployment.yaml, service.yaml, configmap.yaml}` — real, present manifests. **No Terraform anywhere in the repo.**
- `fly.toml` — Fly.io app config, app name `orca-demo`.
- `.github/workflows/{test.yml, seed.yml, eval.yml}` — CI jobs for the test suite, data-seeding, and model eval respectively. Workflow/job names themselves are generic (`Test Suite`, `pytest`, etc.) — "Orca" only appears in step display names like "Install Orca (dev deps)".
- `install.sh` — a real install script (references `ORCA_VERSION`).

## Naming inconsistency already present, independent of any Orneur rebrand

The k8s manifests and docker-compose service name are **not** `orca` — they're `atheris`: `atheris-deployment`, `atheris-config`, `atheris-secrets`, `atheris-pvc`, `atheris-ingress` (k8s), and the docker-compose service itself is named `atheris` with volume `atheris_data`. This is a **third** brand already live in deployment configuration, distinct from both the code-level "Orca" branding and the target "Orneur" name — see `BRAND_MIGRATION_PLAN.md`. This needs to be resolved as part of any deployment-layer migration, and should probably be resolved regardless of the Orneur decision, since it's already an inconsistency today.

`pyproject.toml`'s `Homepage`/`Docs`/`Changelog` URLs point to `atheris.ai` (a fourth-ish naming surface — the parent-company domain), while the GitHub repo URL is `github.com/Guruprasath-Annadurai/Orca`, and the CLI itself references `orca.systems` for purchase/contact/docs links. **Three live domains are referenced across the codebase today**: `atheris.ai` (pyproject homepage), `orca.systems` (CLI links, install script), and `orca.ai` (marketing-site reference in a design-prompt doc). This should be resolved alongside the brand migration, not treated as a documentation nit.

## Reproducibility

Cannot currently confirm the system deploys reproducibly end-to-end without executing an actual deploy (out of scope for a read-only Phase 0 audit) — no evidence either way was found for: health/readiness check wiring at the k8s level (manifests exist but their actual probe configuration wasn't deeply inspected in this pass), autoscaling config, canary/rollback support, database migration tooling beyond `orca/auth/migrate_to_postgres.py` (a real, one-directional SQLite→Postgres migration script — not a general schema-migration framework like Alembic), or disaster-recovery/backup restore procedures beyond `orca/ops/backup.py` (exists; depth not verified in this pass).

## What's absent

- No Terraform or other infrastructure-as-code beyond the k8s YAML + Dockerfiles + fly.toml.
- No general schema-migration framework (no Alembic or equivalent) — only the one-off SQLite→Postgres migration script.
- No confirmed autoscaling, canary deployment, or rollback tooling.
- No multi-node/multi-GPU-host deployment story — see `INFERENCE_STATUS.md`.

## Summary for Orneur planning

The deployment surface is real (working Dockerfiles, k8s manifests, Fly config, CI) but was clearly built incrementally without a single consistent naming decision — three brand names and three domains are already live simultaneously before any Orneur work begins. Any Phase 1 migration plan should treat "make deployment naming internally consistent" as valuable even independent of the final Orca→Orneur decision.
