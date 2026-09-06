# Model Capability Profiles (Phase 7 spec §7-10)

## Genesis (legacy 7B artifact — `orca-nano-v7`)

- **Not** the canonical future Genesis 3B target (which has no trained
  checkpoint at all -- see `orca/registry/model_spec.py`'s `legacy_note`).
- `lifecycle_state = LEGACY_PRODUCTION_SERVING` (see `ARCHITECTURE.md`'s
  dedicated section for why this is not literal `ModelRegistry` state).
- `list_evaluations("orca-nano-v7")` returns `[]` -- **no formal
  EvaluationReport exists**. Every `ModelCapability` in its profile is the
  explicit `UNMEASURED` sentinel, never an invented average (spec §9).
- Known limitation on file: a live Falsifier run (Phase 6) mislabeled a
  correctly-cited claim as a contradiction and emitted an undocumented
  `objection_kind` ("repetition") -- see `EPISTEMIC_TWIN.md`'s Phase 6
  history and this phase's schema-validation fix in `SECURITY.md`.

## Novus (`orca-core-combined-v2`, EXPERIMENTAL)

Every numeric field is copied verbatim from the real, on-disk
`EvaluationReport` `novus-combined-v2-full-eval`:

| Metric | Value | vs. required threshold |
|---|---|---|
| eval_accuracy | 72.8% | ≥70% required — meets |
| jailbreak_block_rate | 70.0% | ≥92% required — **fails** |
| bias_flag_rate | 12.5% | ≤20% required — meets |
| domain_eval | 37.5% | ≥75% required — **fails** |
| calibration_score | 100.0% | — |

`pass_fail_status = NOT_PROMOTABLE` on the report itself. Model Society
does not weaken, hide, or override this -- `orneur-novus` is hard-filtered
out of every production (non-`allow_experimental`) routing decision (see
`tests/test_society_router.py::test_novus_not_production_routable_without_explicit_opt_in`).

## Aeternum

Family/architecture defined (`Meta-Llama-3.1-70B-Instruct` planned base) --
**no trained checkpoint exists under any name**. `list_current_profiles()`
returns `None` for `"aeternum"` deliberately, and `route()` always
represents it as an explicitly rejected candidate
(`RoutingReason.AETERNUM_ABSENT`) rather than omitting it silently --
so its absence is auditable in every `RoutingDecision`, never just assumed.

## Profile states (spec §9)

`ProfileState.MEASURED` (Novus -- backed by a real `EvaluationReport`),
`UNMEASURED` (Genesis-legacy -- no report on file). No profile in this
phase uses `PARTIALLY_MEASURED`, `STALE`, or `DISQUALIFIED` -- those states
exist in the contract for future checkpoints with partial/aging evidence,
honestly not needed yet with only two profiled families.
