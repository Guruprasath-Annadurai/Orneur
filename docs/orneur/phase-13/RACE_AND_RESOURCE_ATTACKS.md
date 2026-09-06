# Phase 13 — Race Conditions & Resource Exhaustion

## Race / TOCTOU (spec §55-57)

Already covered: Godmode lease consumption
(`test_concurrent_actions_racing_a_one_use_lease_only_one_succeeds`),
Truth/Court cancellation races
(`tests/test_simulation_qualification_11_2.py`'s branch/Truth cancellation
proofs, Phase 11.2), Gateway chaos (`tests/test_gateway_chaos.py`).

Not newly tested this phase: registry freeze/dataset-approval TOCTOU
under genuine multi-process concurrency (Phase 12's `DatasetManifest`
freeze check is single-process-safe by construction — it reads-then-
writes within one Python call — but a true multi-process race wasn't
exercised). Disclosed as residual risk.

## Resource exhaustion (spec §51)

Already bounded and tested: `MAX_SIMULATION_ACTIONS`,
`MAX_SIMULATION_BRANCHES` (Phase 11/11.1), budget ledgers
(`tests/test_budget_invariants.py`, `tests/test_society_budget_ledger.py`,
`tests/test_connector_rate_limit_and_budget.py`).

## Archive/decompression bombs (spec §52)

**Audited: no archive/zip ingestion exists anywhere in this repository.**
Confirmed via `grep -rl "zipfile\|tarfile\|gzip" orca/ --include="*.py"` —
zero matches. No archive-bomb code was added, matching spec §52's
explicit "do not implement irrelevant archive support if none exists."

## JSON/structured-input bombs (spec §53)

Not newly tested this phase. `orca/serve/api.py`'s FastAPI/Pydantic layer
has default request-size handling from the framework; a dedicated
extreme-nesting/huge-array adversarial test was not added. Disclosed
residual risk.

## Regex/parser DoS (spec §54)

Not newly audited line-by-line this phase for catastrophic backtracking.
The secret-redaction patterns (`orca/connectors/security.py`,
`orca/serve/dlp.py`) use straightforward, non-nested-quantifier regexes
(bounded character classes, no adjacent unbounded quantifiers) — a quick
visual audit found no obvious ReDoS shape, but this was not a formal
fuzz/timing analysis. Disclosed residual risk.

## Fuzzing / property tests (spec §58-59)

**Not implemented this phase.** This is a genuine, disclosed scope gap —
bounded fuzz/property testing of canonicalizers, resource-scope matching,
and the other listed targets is real, valuable work not completed in this
pass.
