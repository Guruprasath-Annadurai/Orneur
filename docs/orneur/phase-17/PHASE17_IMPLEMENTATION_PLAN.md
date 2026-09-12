# PHASE 17 — Implementation Plan (as executed)

Baseline (before any Phase 17 code): HEAD `1321ca932deea235c760fdf2f6a5189226161099`, 2610 tests
collected.

## Task sequence

1. Repository investigation (§1): read `orca/cognitive/contracts.py` in full (439 lines) to confirm
   its stability and avoid destructive modification; confirmed via `git log` that
   `orca/deliberation/contracts.py` (Phase 6) and `orca/mission/cognitive_court.py` (Phase 15.9) are
   the two real, distinct Court abstractions already reconciled in Phase 16's closure.
2. Architecture decision (§27): three-option comparison, Option B selected —
   `docs/orneur/phase-17/PHASE17_OCL_ARCHITECTURE.md`.
3. Master spec + architecture docs written before implementation (§41 C-E):
   `PHASE17_OCL_MASTER_SPEC_V1.md`, `PHASE17_OCL_ARCHITECTURE.md`.
4. Package skeleton created: `orneur/`, `orneur/intelligence/`, `orneur/intelligence/ocl/`.
5. Core types built bottom-up, each with an immediate smoke test before moving to the next:
   `version.py` → `errors.py` → `limits.py` → `enums.py` → `provenance.py` → `evidence.py` →
   `graph.py` → `proposals.py` → `causal.py` → `artifact.py` → `transformations.py` →
   `extensions.py` → `compiler.py` → `canonical.py` → `diff.py` → `observer.py` → `checkpoint.py` →
   `adapters.py`.
6. Full TDD test suite written per category (`tests/ocl/`): schema, atoms, relations, authority,
   provenance, serialization, limits, diff, conservation, observer, checkpoint, extensions,
   adapter, causal, authority-call-path, performance — 90 tests, all genuinely exercising the
   implementation (several caught real bugs during authoring, e.g. the NaN-rejection timing test
   and the wire-payload-size-before-parsing gap, both fixed in place — see `PHASE17_EVIDENCE.md`).
7. Section 32 authority call-path audit performed and documented
   (`PHASE17_AUTHORITY_CALL_PATH.md`), closing OCL-AUTHORITY-003/004, deferring OCL-AUTHORITY-005.
8. Threat model written against the actual implementation, not aspirationally
   (`PHASE17_THREAT_MODEL.md`, 40 items, 31 tested).
9. Requirements registry compiled (`PHASE17_REQUIREMENTS.md`).
10. Full Phase 16 regression + full deterministic suite run (evidence in `PHASE17_EVIDENCE.md`).
11. Logical commits pushed; fresh GitHub CI verified green on the final SHA.

No task in this list was implemented with a TODO/placeholder; every module listed above is complete
and covered by at least one passing test that exercises its real behavior.
