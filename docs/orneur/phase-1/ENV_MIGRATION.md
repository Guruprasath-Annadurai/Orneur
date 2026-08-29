# ORCA_* → ORNEUR_* Environment Variable Migration

## Correction to the Phase 0 census

Re-verifying every one of the ~42 names against actual code (not just grep matches) found that **several were misclassified as environment variables** in the Phase 0 census — they're Python identifiers/constants or documentation references that happen to share the `ORCA_` prefix convention, never read via `os.environ`:

| Name | What it actually is | Disposition |
|---|---|---|
| `ORCA_ASCII`, `ORCA_ASCII_COMPACT` | Python string constants (ASCII art banners) in `orca/tui.py` | Not an env var — no migration needed. Renaming these constants is a code-identifier concern (Stage B), not env-var migration. |
| `ORCA_SYSTEM`, `ORCA_SYSTEM_PROMPT` | Python string constants (the actual system prompt text) in `orca/data/collector.py`, `orca/serve/export.py` | Not an env var — same as above. |
| `ORCA_VOICE` | A `Domain` object constant (training data domain definition) in `orca/data/seeds.py` | Not an env var — same as above. |
| `ORCA_BLUEPRINT` | A markdown filename reference (`docs/ORCA_BLUEPRINT.md`) in code comments | Not an env var at all. |
| `ORCA_TEST_SECRET`, `ORCA_TEST_SECRET_SHELL` | Synthetic env var names used ONLY by `tests/test_code_sandbox_safety.py` / `tests/test_run_shell_sandbox.py` to verify that sandboxed subprocess environments strip all variables | Deliberately NOT migrated — their entire test purpose is to inject an arbitrary-named variable and confirm it's stripped from a sandboxed child process's environment. Migrating them to `ORNEUR_*` would not improve the test and would just rename a fixture. |
| `ORCA_MODEL_BACKEND`, `ORCA_OLLAMA_MODEL` | Referenced only in `orca/serve/export.py`'s user-facing example/instructional strings ("Use in Orca: export ORCA_MODEL_BACKEND=... ") — **no `os.environ` read site exists anywhere in the codebase** | Dead/aspirational documentation, not a real config path. Left as-is (still valid future work to either wire them up or remove the misleading instructions — out of scope for this pass, flagged here for visibility). |

**Real, application-level environment variables actually read via `os.environ`: 24**, all migrated below.

## Migration table — the 24 real variables

All resolved via `orca.config.orneur_env(suffix, default)`. `ORNEUR_<suffix>` takes precedence; `ORCA_<suffix>` is a deprecated fallback with a one-time `DeprecationWarning`.

| Legacy `ORCA_*` | Canonical `ORNEUR_*` | Secret? | Required? | Default | Legacy fallback | Removal target |
|---|---|---|---|---|---|---|
| `ORCA_HOME` | `ORNEUR_HOME` | no | optional | `~/.orca` | yes | next major version |
| `ORCA_OLLAMA_HOST` | `ORNEUR_OLLAMA_HOST` | no | optional | `http://localhost:11434` | yes | next major version |
| `ORCA_NANO_MODEL` | `ORNEUR_NANO_MODEL` | no | optional | `orca-nano` | yes | next major version |
| `ORCA_CORE_MODEL` | `ORNEUR_CORE_MODEL` | no | optional | `orca-core` | yes | next major version |
| `ORCA_ULTRA_MODEL` | `ORNEUR_ULTRA_MODEL` | no | optional | `orca-ultra` | yes | next major version |
| `ORCA_NANO_BACKEND` | `ORNEUR_NANO_BACKEND` | no | optional | `ollama` | yes | next major version |
| `ORCA_CORE_BACKEND` | `ORNEUR_CORE_BACKEND` | no | optional | `ollama` | yes | next major version |
| `ORCA_ULTRA_BACKEND` | `ORNEUR_ULTRA_BACKEND` | no | optional | `ollama` | yes | next major version |
| `ORCA_OPENAI_MODEL_CORE` | `ORNEUR_OPENAI_MODEL_CORE` | no | optional | `gpt-4o` | yes | next major version |
| `ORCA_OPENAI_MODEL_ULTRA` | `ORNEUR_OPENAI_MODEL_ULTRA` | no | optional | `gpt-4o` | yes | next major version |
| `ORCA_ANTHROPIC_MODEL_CORE` | `ORNEUR_ANTHROPIC_MODEL_CORE` | no | optional | `claude-sonnet-4-6` | yes | next major version |
| `ORCA_ANTHROPIC_MODEL_ULTRA` | `ORNEUR_ANTHROPIC_MODEL_ULTRA` | no | optional | `claude-opus-4-8` | yes | next major version |
| `ORCA_OPENAI_API_KEY` | `ORNEUR_OPENAI_API_KEY` | **yes** | optional | `""` | yes | next major version |
| `ORCA_ANTHROPIC_API_KEY` | `ORNEUR_ANTHROPIC_API_KEY` | **yes** | optional | `""` | yes | next major version |
| `ORCA_DATA_SOVEREIGNTY_LOCK` | `ORNEUR_DATA_SOVEREIGNTY_LOCK` | no | optional | `false` (bool) | yes | next major version |
| `ORCA_COST_AWARE_ESCALATION` | `ORNEUR_COST_AWARE_ESCALATION` | no | optional | `false` (bool) | yes | next major version |
| `ORCA_ESCALATION_BACKEND` | `ORNEUR_ESCALATION_BACKEND` | no | optional | `""` | yes | next major version |
| `ORCA_ESCALATION_DAILY_CAP` | `ORNEUR_ESCALATION_DAILY_CAP` | no | optional | `0` (int) | yes | next major version |
| `ORCA_AUDIT_KEY` | `ORNEUR_AUDIT_KEY` | **yes** | optional | `""` (falls back to a fixed dev key with a loud warning) | yes | next major version |
| `ORCA_LICENSE_SECRET` | `ORNEUR_LICENSE_SECRET` | **yes** | optional | built-in dev secret | yes | next major version |
| `ORCA_ALLOW_UNSIGNED_WEBHOOKS` | `ORNEUR_ALLOW_UNSIGNED_WEBHOOKS` | no | optional | `""` (unset = signed-only) | yes | next major version |
| `ORCA_DATABASE_URL` | `ORNEUR_DATABASE_URL` | **yes** (connection string may embed credentials) | optional | `""` (falls back to SQLite) | yes | next major version |
| `ORCA_AUTH_SECRET` | `ORNEUR_AUTH_SECRET` | **yes** | **required in production** (falls back to `"dev-secret-change-me"` otherwise — a real, disclosed risk, see `docs/orneur/phase-0/SECURITY_BASELINE.md`) | dev fallback | yes | next major version |
| `ORCA_GOVERNANCE_KEY` | `ORNEUR_GOVERNANCE_KEY` | **yes** | optional | falls back to `ORCA_AUDIT_KEY`/`ORNEUR_AUDIT_KEY`, then a fixed dev key | yes | next major version |
| `ORCA_REDIS_URL` | `ORNEUR_REDIS_URL` | **yes** (may embed credentials) | optional | `None` (session continuity disabled) | yes | next major version |
| `ORCA_PUBLIC_URL` | `ORNEUR_PUBLIC_URL` | no | optional | `http://localhost:7337` | yes | next major version |

**Deployment-config-only variables** (read by shell scripts / compose files, not Python `os.environ`, so `orneur_env()` doesn't apply — the same ORNEUR-wins-over-ORCA precedence is inlined manually where it matters):

| Legacy | Canonical | Where |
|---|---|---|
| `ORCA_PRESET`, `ORCA_EPOCHS`, `ORCA_RANK`, `ORCA_BASE_MODEL` | `ORNEUR_PRESET`, `ORNEUR_EPOCHS`, `ORNEUR_RANK`, `ORNEUR_BASE_MODEL` | `orca/train/cloud.py`'s generated standalone cloud-training script (runs on a bare GPU instance with no `orca` package installed, so it inlines `os.environ.get("ORNEUR_X") or os.environ.get("ORCA_X", default)` directly rather than importing `orneur_env`) |
| `ORCA_VERSION` | — | `install.sh` — shell-only, install-script scoped, not application config. Not migrated (low value, install script is ephemeral per-run). |
| `ORCA_DB_PASSWORD` | `ORNEUR_DB_PASSWORD` | `docker-compose.yml` shell interpolation — updated in the compose file itself (see `DEPLOYMENT_NAME_MIGRATION.md`) |
| `ORCA_JWT_SECRET` | — | Referenced only in `scripts/deploy_fly.sh` (sets a Fly secret) — **no Python read site found anywhere**, flagged as a real naming-drift/dead-reference needing separate reconciliation, not silently migrated to a name that also wouldn't be read. |

## No first-party variable left unclassified

Every one of the Phase 0 census's ~42 names has an explicit disposition above — either a real migrated env var (24), a corrected non-env-var classification (6), a deliberately-unmigrated test fixture (2), a deployment-script-only var handled inline (4), or a flagged dead reference (1: `ORCA_JWT_SECRET`) — **and 5 more real deployment-only vars beyond Python** (`ORCA_VERSION`, `ORCA_DB_PASSWORD`, and the 3 in `cloud.py`'s generated script counted individually: `ORCA_PRESET`, `ORCA_EPOCHS`, `ORCA_RANK`, `ORCA_BASE_MODEL`). Total: 24 + 6 + 2 + 5 + 1 = 38 distinct names accounted for; the Phase 0 census's raw grep count of "~42" included some duplicate mentions across files that collapse to the same 38 distinct variable names once deduplicated.

## Tests

`tests/test_config_env_compat.py` (6 tests, from Phase 1): precedence, fallback, warning presence/absence, default behavior, no-secret-leakage.

`tests/test_env_migration_census.py` (new, Phase 1.1): an invariant test that fails if a new `os.environ.get("ORCA_...")` / `os.environ["ORCA_..."]` call site is added to `orca/` without going through `orneur_env()` — see that file for exact mechanics. This prevents "no silently forgotten variable" from being a one-time audit that immediately goes stale.
