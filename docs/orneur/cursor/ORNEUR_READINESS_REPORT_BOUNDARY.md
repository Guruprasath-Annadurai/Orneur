# Readiness report boundary

Reproduced on `eaa3eaceef79c78924f0b1d5b0eaea48a04f7c4d` before this change:

`report()` with a cleared synthetic `Observation` (`counted` 2) and the caller dict `{"EXEC-1": "forged", "FINAL-2": "forged"}` returned `execution_allowed: true`, `founder_authorized: true`, and `readiness_reportable: true`. The gate label was still `BLOCKERS_CLEAR_NOT_ACCEPTED`. The acceptance engine was not called.

`report()` is now the `SYNTHETIC_OBSERVATION` interface. A supplied identifier dict or list is copied into `supplied_identifiers_ignored`. `formally_accepted` stays empty. `execution_allowed`, `founder_authorized`, and `readiness_reportable` stay false.

`production_report()` and `report_evaluated()` call `acceptance_engine.evaluate`. They do not accept an acceptance map from the caller. A non-empty in-memory ledger against the committed empty root document is `missing_authority`. The engine's first code is `WRONG_ROOT_STATE_SHA` because that document has no 40-character subject SHA. The pin check is not reached. No bootstrap key was created to reach it. Duplicate requirement ids, ids outside the register, and a `git_sha` other than the supplied subject are refused before that call. The committed ledger file is not written.

`_claims_for_engine_map` can describe a complete engine map. `report()` does not call it. The production observation still carries the real blockers, so the committed repository stays unauthorized.

No key was minted. The ledger bytes stay `[]\n`.
