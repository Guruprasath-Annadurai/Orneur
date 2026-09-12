# PHASE 17 — Authority Call-Path Audit (section 32)

Traces the two limitations carried from Phase 16 before declaring OCL integration safe. Backed by
`tests/ocl/test_authority_call_path.py`.

## A. REQ-BOUNDARY-002c — Mission-state writers

`orca.mission.mission_store.transition_mission()` is the sole real write function for Mission
state (confirmed: `orca.mission.mission_verification_gate` and `orca.mission.court_mission_gate`'s
own docstrings both name it as the one owner of the `COURT_REVIEW -> COMPLETED_VERIFIED` and other
transitions; `mission_store.py` itself calls it internally for `RUNNING`).

Direct-import evidence (unchanged from Phase 16, re-verified this phase): no module under
`orca/{agent,society,train,cognitive,deliberation,gateway}` imports `orca.mission`
(`tests/test_phase16_architecture_invariants.py`, still passing). **Extended this phase**: no
module under `orneur/intelligence/ocl/` imports `orca.mission` either
(`tests/ocl/test_authority_call_path.py::test_ocl_package_does_not_import_orca_mission`), and no
existing model-facing package imports both `orneur.intelligence` and `orca.mission` together
(`::test_no_model_facing_package_imports_orneur_intelligence_ocl_and_orca_mission_together`).

This closes the DIRECT-import sub-claim fully. The full "every possible indirect/injected/service
path" enumeration (REQ-BOUNDARY-002c's stronger form) remains `DEFERRED_TO_FUTURE_PHASE` — a
complete inventory of every `mission_store`/`transition_mission` caller across the Relay/API layer
is Phase 15's own domain and was not re-audited in full here; no evidence of a bypass was found,
but "no evidence found" is recorded honestly as narrower than "proven absent."

## B. REQ-COURT-ARCH-005 — `owner_approval_required` callers

Direct AST-based search across all of `orca/` (excluding the definition file
`orca/mission/cognitive_court.py` itself and test files) for a call to `arbiter_decide(...)` found
**zero production callers**. The only callers are in `tests/test_cognitive_court.py`. This is a
genuine, honest finding, not a grep-only overclaim:
`tests/ocl/test_authority_call_path.py::test_arbiter_decide_has_zero_production_callers_today`
parses every file with `ast` and looks for an actual `Call` node naming `arbiter_decide`, not a
text match that could be fooled by a comment or docstring.

**Conclusion**: there is currently no live path anywhere in the shipped system for
`owner_approval_required` to be set from anything — model-influenced or otherwise — because nothing
calls the function that reads it in production yet. This means:

- No bypass exists today (vacuously true — there is no live caller to bypass).
- The Court's `HUMAN_APPROVAL_REQUIRED` path is real and independently correct in isolation
  (`arbiter_decide()`'s own docstring/tests prove it reads only the deterministic
  `owner_approval_required: bool` parameter, never any critic's `provider_narrative`), but it is
  NOT yet wired into a real Mission/Relay human-approval signal.
- This is recorded as the closure of REQ-COURT-ARCH-005's audit obligation (the trace was
  performed, honestly, with a result), while the actual wiring of a real approval source remains
  future work (a Mission/Relay integration task, out of Phase 17's OCL scope) — tracked as
  `OCL-AUTHORITY-004`, `DEFERRED_TO_FUTURE_PHASE`.

## Regression guard

If a future PR adds a production caller to `arbiter_decide()`,
`test_arbiter_decide_has_zero_production_callers_today` will fail by design — that failure is a
signal to re-run this exact audit for the new caller's `owner_approval_required` source, not a bug
to silence.
