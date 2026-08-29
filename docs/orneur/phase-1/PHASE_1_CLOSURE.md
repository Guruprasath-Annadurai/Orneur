# Phase 1.1 — Closure

## Why the "no checkpoint was deleted" gate was replaced, not falsely marked complete

Phase 1's final report included "no checkpoint was deleted" among its acceptance gates. This was flagged, correctly, as unable to be truthfully satisfied: `orca-core:latest` and `orca-core-dpo:latest` were both removed from local Ollama storage during Phase 0.5 (a real, already-happened disk-pressure decision, made before any registry existed to record it). Marking that gate "passed" would have been a fabrication — the artifacts genuinely were gone from local disk at that point, and no amount of careful process in Phase 1.1 changes what already happened in Phase 0.5.

The corrected gates for this phase, per explicit instruction, are:
- No model artifact loss is hidden or untracked
- Every missing local artifact is explicitly represented
- Lineage/evaluation metadata remains intact
- Recoverability is assessed
- No additional artifact may be deleted without lifecycle policy
- Future artifact deletion/eviction is registry-aware and auditable

All six are addressed below with real evidence, not asserted.

## Artifact recovery — real results, not assumed

### `orca-core-dpo:latest` — **RECOVERED, verified**

Its documented Kaggle merge-export kernel (`guruprasathannadurai/orca-core-dpo-merge-export-v1`) was found in `KernelWorkerStatus.COMPLETE` state and its output downloaded successfully (after one transient `IncompleteRead` retry, the same known network flakiness documented earlier in this project). Verification performed:
- **File size**: 4,920,738,816 bytes — identical to every other confirmed Llama-3.1-8B Q4_K_M export in this project.
- **Direct GGUF header parse** (no `llama.cpp` dependency, a raw binary metadata read): `general.architecture=llama`, `llama.embedding_length=4096`, `llama.block_count=32`, `llama.attention.head_count=32`, `head_count_kv=8` — the exact Llama-3.1-8B GQA signature.
- **SHA-256 computed**: `3075a9bb064a63e4ea0d48be2378d6dc4fb08883724c58cee5489022b6d10873`. **Honest caveat**: no checksum was recorded for this artifact *before* it was deleted in Phase 0.5, so this is the first verified checksum on record for it, not a confirmed-unchanged comparison against a prior hash.

Registered with `availability=REMOTE` (verified recoverable, `recovery_source` pointing at the exact kernel) — **not** `LOCAL`, since it was not re-imported into this machine's Ollama store (disk constraints) and per `CheckpointRecord.is_loadable()`, `REMOTE` is correctly never treated as loadable without an explicit fetch step.

### `orca-core:latest` — **partial recovery, honestly incomplete**

Its matching Kaggle kernel (`guruprasathannadurai/orca-core-qlora-v2`, status `COMPLETE`) was found and its output download attempted. The LoRA adapter portion (671MB) downloaded and verified successfully — real corroborating lineage evidence: `base_model_name_or_path=unsloth/meta-llama-3.1-8b-instruct-unsloth-bnb-4bit` and `r=64`/`lora_alpha=128`, which matches `orca/train/variants.py`'s core-tier `lora_rank=64` exactly. **The merged, quantized GGUF — the actual artifact that was `orca-core:latest`— stalled at 0 bytes for 55+ minutes** while the smaller adapter/tokenizer files completed normally in under 2 minutes, and did not complete within this session.

Per the explicit instruction ("If recovery cannot be proven: leave it explicitly MISSING_LOCAL_ARTIFACT. This is acceptable."), `orca-core` is registered `availability=MISSING`, with the adapter recovery documented as real, useful, corroborating progress — not silently discarded, and not overstated as a full recovery. A future session can resume the GGUF download from the same kernel.

## Artifact availability is now a real field, not an ad-hoc string

Both records above use `orca/registry/checkpoint.py`'s new `ArtifactAvailability` enum (`LOCAL`/`REMOTE`/`MISSING`/`CORRUPT`/`ARCHIVED`), replacing Phase 1's placeholder `"UNVERIFIED_ARTIFACT_REMOVED_FROM_LOCAL_DISK"` checksum-sentinel string. `CheckpointRecord.is_loadable()`/`is_routable()` return `True` only for verified `LOCAL` — tested in `tests/test_artifact_availability.py` (8 tests) including the exact case that motivated this: a checkpoint with a recorded checksum but no local file must never be treated as loadable.

## No additional artifact may be deleted without lifecycle policy

`orca/registry/artifact_retention.py`'s `evict_artifact()` is now the single sanctioned path for evicting a registered checkpoint's local artifact: it always logs the eviction (who/why/when, preserving the checksum) to an append-only JSONL log, and refuses to evict a family's current `PRODUCTION` checkpoint or `rollback_target` without an explicit `force=True`. Tested: `tests/test_artifact_retention.py` (5 tests).

## Environment variable migration — completed for all real variables

Phase 1 wired only `ORCA_HOME`. This phase completed the resolver for all 24 genuine `os.environ`-read `ORCA_*` variables (see `docs/orneur/phase-1/ENV_MIGRATION.md` for the full, corrected disposition table — several of the Phase 0 census's ~42 "variables" turned out to be Python constants or doc references, not env vars at all). A new invariant test (`tests/test_env_migration_census.py`) already caught one real miss during this pass (`orca/auth/crypto.py`'s multi-line `os.environ.get()` call).

## Atheris deployment naming — classified and migrated

"Atheris" confirmed as purely a first-party brand identifier (no distinct technical meaning) used at the deployment-resource layer. Migrated: `docker-compose.yml`, `k8s/*.yaml`, `Dockerfile*`, CI job display name. Deliberately not migrated: `fly.toml`'s `app`/volume names (potential live-resource risk) and any production domain (three historical domains already in play, none confirmed by the owner). A real, unrelated pre-existing bug was also fixed in passing: `Dockerfile.fly` referenced a wheel filename that never matched the actual built package. See `docs/orneur/phase-1/DEPLOYMENT_NAME_MIGRATION.md`.

Also migrated in this pass: remaining first-party "Atheris" display text in `orca/auth/email.py` (verification/reset email subject lines and HTML) and `orca/auth/routes.py` (verification-page HTML), plus docstring/console-label branding in `orca/cli.py`, `orca/auth/rbac.py`, `orca/code/__init__.py`, `orca/docs/__init__.py`, `orca/train/{config,variants,eval,__init__}.py`, `orca/governance/__init__.py` — all cosmetic text, no functional/external-contract risk, confirmed via a full test-suite rerun after each batch.

## What was explicitly NOT done (correct scope discipline)

No new Genesis, Novus, or Aeternum training was launched. Novus remains `NOT_PROMOTABLE` on its real, unchanged evidence (calibration 100%, accuracy 72.8%, domain eval 37.5% — fails, jailbreak 70% — fails, bias 12.5%) — this phase did not attempt to improve or re-measure it. Aeternum remains a family definition with no checkpoint, and the registry's `lookup_production("aeternum")`/`lookup_latest_candidate("aeternum")` both correctly return `None`.
