# Genesis Frontier Holdout Specification

**This document defines the SPECIFICATION only, per spec section 11.
No holdout tasks are authored this phase. No private content exists
yet.** Authoring high-quality, deliberately difficult tasks
responsibly takes real time; rushing it would produce exactly the
"low-quality filler" the owner explicitly prohibited.

## Why a second benchmark tier

`genesis-eval-v1` (created 2026-09-17, 90 tasks, committed to the
public ORNEUR repository) remains useful as a versioned public/
regression benchmark -- it is NOT being deprecated or discarded. But a
publicly committed evaluation suite cannot simultaneously serve as a
secret frontier-selection benchmark: any model trained or fine-tuned
on public internet/code data after 2026-09-17 could plausibly have
seen `genesis-eval-v1`'s exact prompts (directly, or via a
scraped copy, a discussion referencing it, etc.). This is a real,
structural contamination risk for any candidate whose training cutoff
postdates the suite's public commit -- not a hypothetical.

`genesis-frontier-holdout-v1` is the proposed second tier: a benchmark
whose CONTENTS (prompts, expected answers, rubrics) are never
committed to GitHub, existing only in an owner-controlled local
evaluation-artifact location.

## What the public repository MAY contain

- This specification document (schema, category list, expected task
  count, scoring architecture)
- A cryptographic content digest of the actual (private) task set,
  once authored -- so the public repo can prove a specific holdout
  version existed and was unchanged, without revealing its contents
- Creation timestamp
- Provenance policy (this document)
- The scoring architecture/contract (deterministic scorer code,
  SandboxBackend usage) -- the MECHANISM is public; the TASK CONTENT
  is not

## What the public repository must NEVER contain

- The actual holdout prompts
- The actual expected answers/rubrics
- Any partial excerpt large enough to reconstruct meaningful task
  content

## Storage location (private, owner-controlled)

Proposed: a new ORCA_HOME-rooted directory analogous to the existing
registry pattern, e.g. `ORCA_HOME/registry/genesis_frontier_holdout/`,
explicitly `.gitignore`'d at the repository level and never referenced
by path in any committed file (only its content digest, per above).
This mirrors the same "durable but not public" pattern
`GenerationArtifactManifest` already established for raw responses --
no new storage paradigm is introduced.

## Contamination policy

For every evaluated model record (once real evaluation begins):
- Model release date
- Exact revision timestamp (from the model's own repository metadata)
- Holdout creation timestamp

**If a model's exact revision predates the holdout's creation
timestamp**, mark the record `POST-REVISION HOLDOUT` -- this
STRONGLY REDUCES (does not eliminate -- a model could still have been
retrained/updated after its stated revision date in ways not fully
disclosed) direct training-data contamination risk, and should be
noted as a meaningfully stronger evidentiary position than a model
whose revision postdates the holdout.

**Mutable API-only models** (managed endpoints that can change
underneath a fixed name, e.g. some hosted "Max"/"Plus" product
variants distinct from a pinned open-weight checkpoint) must NEVER be
treated as reproducible, pinned foundation candidates for contamination-
tracking purposes. They may be used as FRONTIER REFERENCES (external
benchmark comparison points), but any such use must record: the
provider's own model ID as returned, full response metadata, exact
date/time of the call, and any provider-exposed version identifier --
never assumed stable across two separate calls.

## Difficulty requirements (spec section 11)

The holdout must NOT simply clone or lightly vary `genesis-eval-v1`'s
90 tasks. It must be designed, when authored, to distinguish frontier-
capability models from competent small models specifically -- meaning
task difficulty calibrated so that the smaller CONTROL/SMALL-BASELINE
candidates (Qwen3-8B, Mistral-Nemo, Phi-4) are expected to score
meaningfully lower than genuine frontier-tier candidates, not simply
"harder" in a way that fails everything uniformly. Target coverage
areas (from spec section 11, restated as the authoring checklist for
whenever this suite is actually built):

- Deep reasoning (multi-step, non-obvious chains)
- Quantitative reasoning
- Difficult coding (beyond simple function-completion)
- Debugging (given broken code, find and fix the actual defect)
- Repository-scale reasoning (understanding code in context, not isolated snippets)
- Architecture / system design judgment
- Specification interpretation (ambiguous or underspecified requirements)
- Agent planning (multi-step task decomposition)
- Tool planning (deciding which tool/action to use, not just executing one)
- Uncertainty handling (knowing what it doesn't know)
- Hallucination resistance (refusing to fabricate when evidence is absent)
- Verification behavior (checking its own work before claiming completion)
- Long-horizon reasoning (tasks requiring sustained context across many steps)
- Authority/control discipline (an ORNEUR-specific category: does the
  model respect explicit boundaries/authorization requirements rather
  than self-authorizing actions it wasn't granted)

## Statistical unit identifier requirement (LOCKED, Phase 21B.4.10)

Every authored holdout task MUST carry an explicit
**`statistical_unit_id`** field (or an equivalent cluster/family
identifier applied consistently), matching
`orca.eval.frontier_stats.StatisticalUnit`'s contract:

- **If a task is a genuinely independent observation**, its
  `statistical_unit_id` equals its own `task_id`.
- **If a task is one of several variants sharing a common scenario,
  source document, repository, base prompt/template, or generated
  fixture**, ALL tasks in that family share the SAME
  `statistical_unit_id` — they are never treated as independent
  observations in the paired-bootstrap comparison
  (`GENESIS_FRONTIER_SCORING_CONTRACT.md` §5.2,
  `orca.eval.frontier_stats.paired_bootstrap_ci()`). Resampling related
  variants independently would understate the true resampling variance
  and overstate statistical confidence — this is a real, testable
  effect: `orca.eval.frontier_stats`'s own test suite
  (`tests/test_frontier_stats.py::test_clustered_units_resample_together_not_independently`)
  demonstrates that treating correlated variants as independent yields
  an artificially narrower confidence interval than the correct
  clustered treatment.

**The pilot/calibration authoring process** (`GENESIS_FRONTIER_EXECUTION_PLAN.md`
§"Sample size / power / resolution planning") must record
`statistical_unit_id` assignments for its own pilot tasks too, so the
empirical paired-difference variance it measures reflects the correct
clustering structure — a pilot set that ignores clustering would
produce a variance estimate too optimistic to correctly size the final
sealed holdout.

No task content, and no `statistical_unit_id` assignment for any real
task, is authored this phase — this section fixes the SCHEMA
requirement future authoring must satisfy.

## What this phase does NOT do

No tasks were authored. No private storage location was created. No
digest exists yet (there is nothing to digest). This is the
specification only, per the owner's explicit instruction to design,
not rush, this benchmark tier.
