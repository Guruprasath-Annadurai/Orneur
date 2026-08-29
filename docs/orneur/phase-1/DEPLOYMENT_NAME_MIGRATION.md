# Atheris → Orneur Deployment Naming

## What "Atheris" actually means here

Investigated directly, not assumed. "Atheris" is **purely a first-party product brand identifier** — the same project this repository calls "Orca," used at the deployment-resource layer (container/service names) instead of the code layer (Python package/CLI name). Evidence: `pyproject.toml`'s `authors = [{"name": "Atheris"}]` and `Homepage = "https://atheris.ai"`; `docker-compose.yml`'s own comments refer to "Orca" and "atheris" interchangeably in the same sentences (e.g. "these defaulted to... not Orca's actual fine-tuned models" describing the `atheris` service's env vars). **No distinct technical meaning was found** — it is not a different system, a third-party dependency, or an external technology. Safe to migrate.

## What was migrated

| File | Change |
|---|---|
| `docker-compose.yml` | `atheris-ollama`→`orneur-ollama`, `atheris-postgres`→`orneur-postgres`, `atheris-redis`→`orneur-redis`, service `atheris:`→`orneur-api:`, container `atheris-server`→`orneur-api`, volume `atheris_data`→`orneur_data`, Postgres user/db `orca`→`orneur`, all env vars to `ORNEUR_*` (with legacy `${ORCA_*}` still substitutable as a shell-level fallback for anyone with existing `.env` overrides) |
| `k8s/deployment.yaml` | Deployment/labels `atheris`→`orneur-api`, image `atheris:latest`→`orneur-api:latest`, `secretKeyRef`/`configMapKeyRef` names, env vars to `ORNEUR_*` |
| `k8s/service.yaml` | Service `atheris`→`orneur-api`, Ingress `atheris-ingress`→`orneur-api-ingress`; **the `host: atheris.ai` line was replaced with an explicit `<YOUR_DOMAIN_HERE>` placeholder** — not migrated to any new domain, per instruction not to invent a canonical production domain (three historical domains are already in play — see `docs/orneur/phase-0/BRAND_MIGRATION_PLAN.md` — and none has been confirmed by the project owner) |
| `k8s/configmap.yaml` | ConfigMap/PVC/Secret names `atheris-*`→`orneur-api-*` |
| `Dockerfile` | `ENV ORCA_HOME`/`ORCA_OLLAMA_HOST` → `ORNEUR_HOME`/`ORNEUR_OLLAMA_HOST` (directory value stays `/root/.orca` — the physical path convention is a separate, deferred migration, see `LEGACY_COMPATIBILITY.md`) |
| `Dockerfile.fly` | Same env var rename, **plus a real pre-existing bug fix**: this file referenced `dist/atheris_ai-*.whl`, which has never matched the actual built wheel (`orca-ai` per `pyproject.toml`, producing `dist/orca_ai-*.whl`) — this build would have failed against any real `dist/` directory. Fixed to reference the wheel that's actually built (not renamed to a new `orneur_ai` name, since the Python package itself hasn't been migrated yet) |
| `.github/workflows/eval.yml` | Job display name `"Atheris Model Eval"` → `"Orneur Model Eval"` (cosmetic only — workflow/job IDs were already generic) |

## What was deliberately NOT migrated

- **`fly.toml`'s `app = "orca-demo"` and the volume `source = "atheris_data"`.** Unlike the k8s/compose manifests (config that, as far as this repository's history shows, has never been deployed), a Fly app name and a Fly volume are potentially **already-provisioned live cloud resources** tied to a real account. Renaming them here would either point this config at nonexistent resources or — worse — silently orphan real data in an existing volume if one already exists under the old name. `fly.toml` now carries an explicit comment explaining this and pointing at this document; the env vars inside it (`ORNEUR_HOME`, `ORNEUR_OLLAMA_HOST`) were still updated, since those don't carry the same live-resource risk.
- **The Python package (`orca/`) itself, the CLI binary name, and the repository root directory.** Explicitly out of scope for this pass — see `LEGACY_COMPATIBILITY.md`'s "stages NOT performed" section.
- **`ORCA_DB_PASSWORD`'s underlying secret VALUE** — only the variable name changed to `ORNEUR_DB_PASSWORD`; no secret values were touched or logged anywhere in this migration.

## Validation performed

- All edited YAML files parse successfully (`python3 -c "import yaml; yaml.safe_load_all(...)"`).
- `docker compose -f docker-compose.yml config` — **VALID** (real `docker` CLI on this machine; one pre-existing, unrelated warning about the obsolete `version:` key, not introduced by this change).
- `kubectl apply --dry-run=client` against the k8s manifests — **could not be validated**: this environment has no reachable Kubernetes API server (`connection refused` to `localhost:8080`), and this kubectl version requires live server contact even for client-side dry-run. YAML-syntax validity was confirmed instead; full schema validation against the Kubernetes OpenAPI spec was not possible here and should be run in an environment with cluster access before relying on it.

## Remaining Atheris references (all justified)

After this migration, the only remaining first-party "Atheris" strings are: `pyproject.toml`'s `authors`/`Homepage` fields (a genuine company/brand identity question, not a deployment-naming one — deferred alongside the canonical-domain decision), and `fly.toml`'s explicitly-commented, deliberately-unmigrated app/volume names (live-resource risk, documented above).
