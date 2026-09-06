# Legacy Orca Compatibility (Phase 1)

Scope actually completed this phase, and what's deliberately deferred to later, independently-reviewable migration stages — per `docs/orneur/phase-0/BRAND_MIGRATION_PLAN.md`'s ordering and the explicit instruction not to combine every migration into one commit.

## Stage A — canonical model/config metadata: DONE

`orca/registry/model_spec.py` establishes `orneur-genesis` / `orneur-novus` / `orneur-aeternum` as the canonical machine identities, with `Orneur Genesis` / `Orneur Novus` / `Orneur Aeternum` as display names. This is layered ON TOP of the existing Orca codebase, not a rename of it.

## Stage D (partial) — environment variables

`orca/config.py`'s new `orneur_env(suffix, default)` resolver: `ORNEUR_<suffix>` takes precedence; `ORCA_<suffix>` is accepted as a deprecated fallback, emits a one-time `DeprecationWarning` naming both variables (never the resolved value — several of these vars carry secrets), and is fully tested (`tests/test_config_env_compat.py`, 6 tests: precedence, fallback, warning presence/absence, default behavior, no-secret-leakage).

**Only `ORCA_HOME`/`ORNEUR_HOME` is wired through this resolver in Phase 1** — deliberately, as the single highest-value case (it determines where every other `ORCA_HOME`-relative store lives: auth DB, memory, cache, vault, training data, and now the registry itself). The remaining ~41 `ORCA_*` variables census'd in `BRAND_MIGRATION_PLAN.md` are NOT yet migrated — doing so in one pass would be exactly the "one enormous unreviewable commit" the instructions warn against. They follow the same `orneur_env()` pattern at their own call sites in a dedicated, later stage.

**Full list of `ORCA_*` vars still pending this migration** (unchanged from the Phase 0 census, for tracking):
```
ORCA_ALLOW_UNSIGNED_WEBHOOKS, ORCA_ANTHROPIC_API_KEY, ORCA_ANTHROPIC_MODEL_CORE,
ORCA_ANTHROPIC_MODEL_ULTRA, ORCA_ASCII, ORCA_ASCII_COMPACT, ORCA_AUDIT_KEY,
ORCA_AUTH_SECRET, ORCA_BASE_MODEL, ORCA_BLUEPRINT, ORCA_CORE_BACKEND,
ORCA_CORE_MODEL, ORCA_COST_AWARE_ESCALATION, ORCA_DATABASE_URL,
ORCA_DATA_SOVEREIGNTY_LOCK, ORCA_DB_PASSWORD, ORCA_EPOCHS,
ORCA_ESCALATION_BACKEND, ORCA_ESCALATION_DAILY_CAP, ORCA_GOVERNANCE_KEY,
ORCA_JWT_SECRET, ORCA_LICENSE_SECRET, ORCA_MODEL_BACKEND,
ORCA_NANO_BACKEND, ORCA_NANO_MODEL, ORCA_OLLAMA_HOST, ORCA_OLLAMA_MODEL,
ORCA_OPENAI_API_KEY, ORCA_OPENAI_MODEL_CORE, ORCA_OPENAI_MODEL_ULTRA,
ORCA_PRESET, ORCA_PUBLIC_URL, ORCA_RANK, ORCA_REDIS_URL, ORCA_SYSTEM,
ORCA_SYSTEM_PROMPT, ORCA_TEST_SECRET, ORCA_TEST_SECRET_SHELL,
ORCA_ULTRA_BACKEND, ORCA_ULTRA_MODEL, ORCA_VOICE, ORCA_VERSION
```

## Ollama alias mapping

`ModelRegistry.register(checkpoint, family, ollama_alias=...)` records the legacy Ollama tag alongside the canonical family. Historical import (`scripts/import_historical_checkpoints.py`) registers:

- `orneur-genesis` → legacy `orca-nano` / `orca-nano-v4` / `orca-nano-v7` (all confirmed 7.6B — **not** the canonical 3B target; the registry entry's `base_model` field always carries the true historical value, so a caller can never confuse a legacy 7B artifact for the future 3B checkpoint just because both map to the same family). Tested in `tests/test_ollama_alias_mapping.py`.
- `orneur-novus` → legacy `orca-core-dpo` / `orca-core-combined` / `orca-core-combined-v2`.
- `orneur-aeternum` → legacy `orca-ultra`, with an explicit registry note that this alias has **never been trained** — a name existing in Ollama does not imply a checkpoint exists.

## Stages NOT performed this phase (deliberately deferred)

Per the migration order in `BRAND_MIGRATION_PLAN.md` and the explicit instruction to use independently reviewable commits rather than one massive rename:

- **B — internal Python/package-level branding**: the `orca` Python package/module name is unchanged. The repository root directory `/Users/ag/orca` is also unchanged — per explicit instruction, physically renaming the root directory while an active tool session operates inside it is deferred as its own careful, separate step (documented below).
- **C — CLI/application branding**: the `orca` CLI binary name is unchanged.
- **E — model registry/model aliases beyond what's described above**: no additional aliasing was built.
- **F/G — Docker/service names, Kubernetes/deployment naming**: unchanged. Recall from `docs/orneur/phase-0/DEPLOYMENT_BASELINE.md` that these are ALREADY inconsistent pre-Orneur (k8s/compose use `atheris`, not `orca`) — this should be resolved in the same future pass as the canonical rename, not migrated twice.
- **H — telemetry/metrics namespace**: unchanged (`orca_uptime_seconds`, `orca.serve` logger namespace).
- **I — documentation**: `docs/orneur/` itself is new/Orneur-branded; the rest of `docs/`, `README.md`, `legal/` remain Orca-branded.
- **J — compatibility aliases beyond `ORCA_HOME`**: see the pending list above.
- **K — final repository-wide stale-name audit**: not yet run: this happens only once stages B–J are actually executed, per the migration's own ordering (auditing for zero remaining stale references before all the renaming work exists would be premature).

## The deferred physical root-directory rename — exact steps for later

The repository currently lives at `/Users/ag/orca`. Renaming this directory while a tool session is actively operating inside it risks breaking that session's own working directory assumptions. When this step IS performed (as its own deliberate, isolated action, likely stage B or immediately after):

1. Stop any running dev server / active Claude Code session rooted in this directory.
2. `mv /Users/ag/orca /Users/ag/orneur` (a plain filesystem rename — git history, `.git/`, and all tracked content move with it).
3. Re-open the tool session (or shell) rooted at the new path.
4. Update any hardcoded absolute-path references to the old location (search for `/Users/ag/orca` specifically, distinct from the Python package name `orca` which is a separate migration stage).
5. Re-run the full test suite from the new location to confirm nothing broke from the path change alone (a completely mechanical, no-behavior-change verification).

This is a one-command operation with no code changes — it is deferred not because it's hard, but because doing it while other work is in flight in this same session would be genuinely disruptive, exactly as the instruction anticipated.
