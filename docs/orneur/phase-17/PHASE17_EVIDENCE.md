# PHASE 17 — Evidence

## Baseline (before any Phase 17 code)

- Repo: `/Users/ag/orca`, branch `session-update-2026-08-25`.
- Starting HEAD: `1321ca932deea235c760fdf2f6a5189226161099`, verified via `git status`/`branch`/
  `rev-parse`/`log` — exact match, clean tree.
- Collection count: **2610 tests**.

## Architecture decision

Option B (`orneur/intelligence/ocl/` core + one-way adapter to legacy `orca.cognitive.contracts`)
selected after a 3-option comparison. See `PHASE17_OCL_ARCHITECTURE.md` for the full table. Matches
Phase 16's own recommendation.

## Failing tests recorded during TDD (a representative sample — not every test was authored
failing-first against a pre-existing gap, since most of Phase 17 is genuinely new code with no
prior "unfixed" state to reproduce; the ones below caught REAL bugs during authoring, fixed in
place before this evidence was written)

1. `test_nan_in_metadata_rejected_for_canonical_form` — initially asserted the NaN rejection only
   fired on a separate `to_canonical_json()` call after `compile_artifact()` succeeded. Once
   `compile_artifact()` was changed to also enforce `MAX_ARTIFACT_SERIALIZED_BYTES` (which requires
   computing the canonical JSON internally), the NaN rejection started firing INSIDE
   `compile_artifact()` itself, and the test failed until updated to reflect the new, more correct
   behavior (NaN is now caught earlier, not later).
2. `test_oversized_wire_payload_rejected_before_parsing` — written after threat-modeling exercise
   #32 revealed the byte-limit check in `compile_artifact()` did nothing to protect
   `artifact_from_canonical_json()`'s own `json.loads()` call from an oversized untrusted string;
   failed until the pre-parse byte-length check was added to `canonical.py`.
3. `test_no_pickle_used_anywhere_in_serialization_module` — initially failed on a trivial false
   positive (the word "pickle" appeared inside the module's own docstring, not as an import);
   fixed by switching the test to AST-based import detection instead of a substring search.

## Implementation commits

See `git log` for the exact Phase 17 commit sequence (multiple logical commits: package skeleton +
core types, compiler + canonicalization + diff/conservation, observer + checkpoint + extensions +
adapter, tests, docs).

## Targeted Phase 17 test results

`.venv/bin/python -m pytest tests/ocl -q` → **90 passed, 0 failed** (per-file collection counts:
schema=3, atoms=6, relations=6, authority=18, provenance=8, serialization=8, limits=7, diff=5,
conservation=4, observer=4, checkpoint=6, extensions=4, adapter=3, causal=3,
authority_call_path=3, performance=2; sum=90).

## Phase 16 regression results

`.venv/bin/python -m pytest tests/test_phase16_architecture_invariants.py
tests/test_phase16_court_reconciliation.py tests/test_phase16_training_fail_closed.py
tests/test_phase16_canonical_training_identity.py tests/test_registry_model_spec.py -q` →
**46 passed, 0 failed**. No Phase 16 test was weakened, skipped, or deselected.

## Full deterministic regression

Project `.venv` used explicitly (`.venv/bin/python -m pytest`, never global Homebrew `pytest`),
pipefail-safe invocation (`bash -c 'set -euo pipefail; ...'`):

**2401 passed, 256 skipped, 43 deselected, 0 failed** (182.16s). Collection: **2700 tests**
(2610 baseline + 90 new OCL tests). 2401+256+43 = 2700, matching exactly. No new skip or
deselection was added anywhere in this phase.

## Performance measurements (representative, local, no GPU)

From `tests/ocl/test_performance.py` (actual measured output, not a claim):

| n_atoms | validate | serialize | digest | canonical JSON bytes |
|---|---|---|---|---|
| 10 | 0.0000s | 0.0001s | 0.0001s | 2,063 |
| 100 | 0.0001s | 0.0008s | 0.0008s | 15,113 |
| 1000 | 0.0006-0.017s | 0.007-0.0075s | 0.0072-0.0075s | 147,413 |

(The 1000-atom validate time varied between runs, 0.0006s-0.017s, most likely JIT/cache-warming
variance on this machine — recorded honestly rather than cherry-picking the faster run.) Diffing
two 500-atom artifacts completed in well under the test's 5-second sanity bound (exact figure not
separately logged; the bound itself was never approached).

## Threat model

`PHASE17_THREAT_MODEL.md`: 40 threats enumerated, **31 backed by a passing test**, 9 honestly
documented as untested/deferred (1 of the 9, #14, is N/A rather than a gap).

## Authority call-path audit (section 32)

See `PHASE17_AUTHORITY_CALL_PATH.md`. Direct-import sub-claim (Mission-state writers) fully closed
for both the pre-existing Phase 16 model-facing packages AND the new `orneur.intelligence.ocl`
package. `owner_approval_required` traced via AST across all of `orca/`: **zero production callers**
of `arbiter_decide()` exist today — a genuine, honest finding (not a grep-only overclaim), backed by
a regression test that will fail loudly if a future PR adds a production caller without a fresh
audit.

## Production mutation status / GPU spend / model training

No Neon/database touched, no migration. No compute provider invoked. **GPU spend: $0.** **No model
training occurred.**

## Requirements totals

From `PHASE17_REQUIREMENTS.md`: 39 requirements — **35 VERIFIED**, 2 IMPLEMENTED (real code, no
dedicated test beyond adjacent coverage: OCL-EVIDENCE-001, OCL-ESCALATE-001), 2
DEFERRED_TO_FUTURE_PHASE (OCL-AUTHORITY-005, OCL-EXTENSION-002). 0 UNIMPLEMENTED, 0 BLOCKED.

## Known limitations

- Unicode canonicalization does not perform normalization (NFC/NFKC) — two visually-identical but
  differently-normalized strings currently digest differently (threat #31, documented, not fixed).
- Cross-artifact ID uniqueness/collision (threats #18, #20, #36) is a storage-layer responsibility,
  not enforced by the compiler, which only validates within one artifact at a time.
- Extension namespaces have no per-namespace schema-contract enforcement yet (threat #33,
  OCL-EXTENSION-002) — only namespace registration exists, per the phase's own YAGNI instruction.
- `OCL-AUTHORITY-005`'s full indirect-bypass enumeration across every Mission-state writer (not
  just direct imports) was not performed this phase.
- `ActionIntent`/`EscalationRequest` have no real consumer yet (Phase 19+/20 will be the first) — 
  their "cannot execute/route" property is proven by absence of any execution/routing code path in
  this codebase today, which is necessarily a claim about the current snapshot, not a permanent
  guarantee against a badly-designed future consumer.

## Phase 18 entry contract

Phase 18 (Epistemic State) consumes: `CognitiveArtifact`'s atom/relation graph, `SourceClass`
(already distinguishes model assertion from measured/external/policy/human evidence — Phase 18 MUST
NOT reuse `SourceClass` itself as an epistemic-state enum), and `CausalHypothesis` (already
distinguishes hypothesis from established fact). See master spec §26.

## GitHub CI

Recorded in the Final Report (this document's companion STOP report), after the final Phase 17
commit is pushed.

## DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 18?

**YES**
