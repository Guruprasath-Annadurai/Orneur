# Orneur Phase 1 — Implementation Plan (PLAN ONLY — NOT STARTED)

Phase 1 = **native LLM foundation + controlled Orca → Orneur migration**. This is a plan for future work; nothing in this document has been executed. Each task below is scoped to be independently testable.

## 1. Naming decisions — RESOLVED in Phase 0.5, see `ARCHITECTURAL_DECISIONS.md`

- [x] Spelling: **"Aeternum" is final and canonical.** "Aethernum" must not be introduced anywhere in new first-party work.
- [x] Model family: `Orneur Genesis` / `Orneur Novus` / `Orneur Aeternum`, machine identifiers `orneur-genesis` / `orneur-novus` / `orneur-aeternum`.
- [x] Genesis canonical future target: **Qwen2.5-3B class** (existing checkpoints remain identified as legacy Qwen2.5-7B, per `GENESIS_MODEL_IDENTITY.md` — not relabeled).
- [x] Novus base confirmed unambiguous: Llama-3.1-8B.
- [ ] Still open, not yet decided: canonical domain among `atheris.ai` / `orca.systems` / `orca.ai`, or a new one; and whether to resolve the pip-name/module-name/binary-name split (`orca-ai` vs `orca`) in the same pass as the Orneur rename.

## 2. P0 correctness bugs

- [x] **DONE in Phase 0.5**: Fixed `orca/mcp/fs_server.py`'s `_safe_path()` prefix-confusion bug via TDD (`.relative_to()` ancestry check, matching `orca/tools/__init__.py`'s pattern). Regression test suite: `tests/test_mcp_fs_server_sandbox.py` (5 tests). Full suite: 414 passed, 0 failed. See `P0_SECURITY_FIX.md`.
- [ ] Reconcile nano's base-model config literals: `orca/train/variants.py`'s docstring (wrong, says 3B) vs. its own code (7B, matches reality) vs. `orca/train/config.py`'s preset (wrong, says 3B). Canonical **future** target is Qwen2.5-3B per `ARCHITECTURAL_DECISIONS.md` — this task is about making the config files internally consistent and pointed at that decision, not about what to train next.

## 3. Model identity (native model foundation)

- [ ] Define canonical model configs for Genesis (Qwen2.5-3B target)/Novus (Llama-3.1-8B)/Aeternum with a single source of truth (retire the `variants.py`/`config.py` duplication that caused the nano ambiguity — see `GENESIS_MODEL_IDENTITY.md` for the forensic evidence behind this).
- [ ] Add dataset checksums (e.g. SHA-256 manifest alongside each training JSONL) — currently zero exist.
- [ ] Add a dataset-version manifest (source file + generation date + example count + domain) — currently only informal, via filename dates.
- [ ] Add a minimal model-registry layer: adapter name → version → training-config-hash → eval-report-path, distinct from the existing "currently installed Ollama model" resolver (which should remain as the serving-time fallback logic, not be replaced).
- [ ] Wire actual checkpoint promotion: a new adapter only becomes the "current" one for a tier after its eval/redteam report clears the existing `governance/model_cards.py` thresholds — formalizing what's currently a manual, ad-hoc process.
- [ ] Add a rollback path: keep the previous adapter available and swappable if a newly-promoted one regresses (this project has already hit exactly this scenario twice this session with Novus's calibration regression).

## 4. Tokenizer/dataset versioning

- [ ] Record which tokenizer version/revision was used per training run (currently implicit via base-model name only).
- [ ] Add a resume-from-checkpoint safety check (verify optimizer/scheduler state compatibility before resuming) — not currently needed at the current single-epoch-notebook scale, but worth scoping now given Phase 1's registry work touches the same area.

## 5. Experiment tracking

- [ ] Decide whether to actually enable the already-wired wandb integration (`use_wandb` flag exists, just never flipped on) or replace it with something else — don't leave it as dead-but-present config.

## 6. Controlled Orca → Orneur migration (sequenced per `BRAND_MIGRATION_PLAN.md`)

- [ ] Step 1: Documentation/prose rename (zero functional risk).
- [ ] Step 2: Environment variable rename with a deprecation-period compatibility shim (accept both prefixes, warn on old one).
- [ ] Step 3: Python package/module/CLI binary rename, done via scripted rename + full 409-test re-run to confirm nothing broke — not manual find-and-replace.
- [ ] Step 4: `~/.orca/` → `~/.orneur/` data migration path (copy or symlink on first run of the renamed binary; must not orphan or destroy existing `auth.db`/trained artifacts).
- [ ] Step 5: Ollama model name / Kaggle slug rename for new work, with an explicit lineage map (`orca-core:<version> → orneur-novus:<version>`) for existing checkpoints — files preserved, checksums added.
- [ ] Step 6: Deployment naming consistency (`k8s/*.yaml`, `docker-compose.yml`, `fly.toml`) — resolve the pre-existing Orca/Atheris split in the same pass.
- [ ] Step 7: Domain/external identity finalization (business decision, sequenced last).
- [ ] Verify at the end: zero first-party stale "orca" references remain (grep-verifiable), per `BRAND_MIGRATION_PLAN.md`'s target end-state.

## 7. Explicitly deferred out of Phase 1 (per the user's own phase ordering)

- Enterprise connectors (GitHub/Slack/Drive/Notion/etc.) — confirmed net-new, no existing code to build on.
- Multi-host/multi-GPU inference scaling — confirmed no existing story at all; needs its own phase, not folded into Phase 1.
- Wiring the unwired `hallucination_check.py` into the live RAG pipeline — small, real, valuable, but belongs with the Truth Fabric work, not the model/migration foundation work.
- A paid real-time search API integration — belongs with RAG/search work, not Phase 1.
- Godmode capability-lease redesign — the user's own spec says "do NOT implement Godmode during Phase 0"; current "god-mode" naming has no real bypass to fix, so this is a future architecture decision, not an urgent fix.

## Testing strategy for Phase 1

Every task above should land with its own test, run against the existing 409-test baseline (`TEST_AND_EVAL_BASELINE.md`) with zero regressions before merge. The rename steps (3, 4, 6) are the highest-blast-radius items — each should be a single, revertible commit/PR with the full test suite re-run as the acceptance gate, not a multi-day in-progress rename.
