# Orneur — Final Architectural Decisions (Phase 0.5)

These decisions are final per explicit human direction. This document is the single canonical reference; all other docs should defer to it if any conflict arises.

## Canonical brand

```
ORNEUR
```

Official expansion:

```
Orchestrated Reasoning Neural Engine for Unified Retrieval
```

## Canonical model family

```
Orneur Genesis
Orneur Novus
Orneur Aeternum
```

Canonical machine identifiers:

```
orneur-genesis
orneur-novus
orneur-aeternum
```

## Spelling — FINAL

**"Aeternum" is the final, canonical spelling.** "Aethernum" is NOT to be introduced anywhere in new first-party code, configs, documentation, model metadata, artifacts, deployment resources, or APIs.

No occurrence of "Aethernum" was found in the repository as of this audit (`docs/orneur/phase-0/*.md`, written during Phase 0 and 0.5, use only "Aeternum"/"Aethernum" as a discussion point, not as an introduced spelling in code). If any accidental "Aethernum" spelling is found in future work, it is a typo and must be corrected as part of the controlled rename/migration plan, not left in place.

## Genesis canonical future target

```
Qwen2.5-3B class
```

**Reason** (per direction): Genesis is the fast/nano cognition tier (routing, classification, extraction, retrieval planning, query rewriting, memory relevance, context compression, claim extraction, fast verification, lightweight reasoning). Novus already occupies the ~8B operational-cognition tier; a 7B Genesis would create unnecessary role overlap.

**Historical fact, does not change the decision above**: every currently-installed Genesis/nano checkpoint (`orca-nano`, `orca-nano-v4`, `orca-nano-v7`) is forensically confirmed **Qwen2.5-7B-class** (7.6B params, embedding length 3584, per direct `ollama show` inspection — see `GENESIS_MODEL_IDENTITY.md`). These are preserved as legacy checkpoints, not relabeled, not deleted. The 3B target applies to future training only.

## Novus current base

```
Llama-3.1-8B
```

Confirmed unambiguous across both live config sources (`orca/train/variants.py` and `orca/train/config.py` agree) — no contradiction found for Novus, unlike Genesis.

## Aeternum

- Canonical spelling: **Aeternum**.
- Native trained checkpoint: **ABSENT** — confirmed by the test suite's own explicit coverage of this exact state (`test_persona_claim_gate.py::test_persona_system_ultra_with_zero_training_data_is_demoted_not_crashed`). No checkpoint has been fabricated or implied to exist as part of this or any prior phase.
- This is not treated as a Phase 1 blocker in isolation — Aeternum training is scoped to its own later phase with its own acceptance criteria, per direction.

## Legacy vs. canonical project name

```
Legacy project name:    ORCA
Canonical project name: ORNEUR
```

No full rename has been performed. `BRAND_MIGRATION_PLAN.md` (Phase 0) already contains the classified inventory and proposed migration ordering; it should be read as still current, with this document's spelling/naming decisions layered on top of it as the now-final targets. The plan itself remains **not yet executed** — Phase 1 is scoped to *begin* a controlled migration, not complete a blind global search-and-replace.

## Config single source of truth (to be implemented in Phase 1, not now)

Both `orca/train/variants.py` and `orca/train/config.py` currently define per-tier base-model literals independently, which is exactly how the Genesis 3B/7B ambiguity arose. Phase 1 should eliminate this duplication by deriving all downstream code from one canonical model manifest, not by patching the two files' current disagreement in place during Phase 0.5 (out of scope — no retraining or config-literal changes were made during this phase, only forensic identification and documentation).
