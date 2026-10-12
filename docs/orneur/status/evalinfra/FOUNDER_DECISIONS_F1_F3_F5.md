# Founder decisions: evalinfra findings F1, F3, F5

NON_NORMATIVE status document. It authorizes nothing, freezes nothing, flips no flag. No training, GPU, network call, private evaluation material or real key was used. Training remains NOT_AUTHORIZED. Findings are those recorded in `docs/orneur/status/evalinfra/INVENTORY.md` section 3.

| Finding | Outcome on this branch | Decision needed from founder |
|---|---|---|
| F1 prereg validator | Reproduced (strict xfail tests). Fix written and verified but WITHHELD: `prereg.py` is hash-bound in frozen artifacts | Yes: D0 approve patch and the frozen-hash refresh; D1, D2 |
| F3 category numbering | NO behaviour change. Non-frozen mapping proposal + validator + tests added | Yes: D3 to D5 |
| F5 human vs LLM judge | NO behaviour change. Characterisation tests only | Yes: D6 |

## F1. `validate_binding_status` and the deferred commitment

**Reproduced.** `orca/eval/genesis_v2/prereg.py` (`validate_binding_status`, the `elif k in DEFERRED` branch) required `binding_status[private_corpus_aggregate_commitment] == "DEFERRED"` unconditionally. A freeze record that fills the commitment and marks it `BOUND` (or any other status) was rejected by `validate_for_freeze`. Reproduced by `tests/test_evalinfra_findings_f1.py::test_f1_filled_deferred_binding_with_a_non_deferred_status_passes_freeze_validation` (3 cases, strict xfail on the unmodified validator).

**Fix was written, verified, then withheld.** The status table in `prereg.py` (lines 24-33) defines `DEFERRED` as "intentionally null", so forcing `DEFERRED` on a filled binding contradicts the module's own definition and the intended specification is clear enough. The patch (verified: the 3 failing cases pass, the committed DRAFT and `schema()` unaffected, null commitment still must be `DEFERRED`) was, in the `elif k in DEFERRED` branch of `validate_binding_status`:

```python
if v != "DEFERRED" and b.get(k) is None:     # was: if v != "DEFERRED":
```

It was not shipped because `orca/eval/genesis_v2/prereg.py`'s sha256 is bound in `docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json` (`code_hashes`, line 134) and `docs/orneur/phase-21/GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json` (line 41). Editing the file made `tests/test_genesis_v2_owner_preflight.py` and `tests/test_genesis_v2_final_pre_corpus_closure.py` report NOT_READY / stale evidence (7 extra failures in the run), and repairing that means editing frozen files under `docs/orneur/phase-21` (out of scope), regenerating the closure manifest, the DRAFT record hash and the status document. The reproducing tests are strict `xfail`: they fail loudly once the bug is fixed, forcing the marker's removal.

**Decisions.**
* D0. Approve the one-line patch above and the follow-up refresh of the hash bindings (DRAFT `code_hashes`, closure manifest, status document, owner-preflight evidence) as a single founder-sanctioned change. Recommendation: yes, bundled with D1/D2 so the hashes are refreshed once.
* D1. Tighten: reject "filled but DEFERRED". Recommendation: yes, at freeze time. Change: in `prereg.py`, the DEFERRED branch becomes `if (v == "DEFERRED") != (b.get(k) is None)`; update the one test above to use `BOUND`, and `synthetic.py` line 70 to `"BOUND"` (this regenerates `docs/orneur/status/evalinfra/demo/prereg.json`, which a test checks byte-for-byte). Risk: none for any real record (none exists).
* D2. Which status a filled commitment carries. The `BOUND` description (prereg.py comment) says "non-corpus-dependent value", which the corpus commitment is not; `OPERATIONALLY_CONFIGURED` and `QUALIFIED` have their own meanings. The fix accepts any non-`DEFERRED` legal status rather than choosing. Recommendation: `BOUND` and reword the `BOUND` comment to "a real value that needs no further operational qualification", or add a new status `CORPUS_BOUND`. A new status changes `BINDING_STATUS_VALUES`, hence `schema()` and the committed SCHEMA JSON (a frozen-adjacent artifact), so it is a founder call.

## F3. Category naming and numbering

**Reproduced.** `tests/test_evalinfra_findings_f3_f5.py::test_f3_gap_reproduced_...`: zero-tolerance ids `(10, 14, 15, 17)` (`orca/evalinfra/prereg_check.py` line 27; `docs/orneur/phase-21/GENESIS_PRETRAINING_QUALIFICATION.md` "Critical non-regression categories") are keys of `orca/eval/genesis_suite.py` `CATEGORY_NAMES`, while the V2 corpus uses the 21 named strings of `orca/eval/genesis_eval_v1.py` `CATEGORIES`. No mapping exists. Beyond naming, the check shows a real content gap: the V2 list has **no category for human-sovereignty/authority (14), security/adversarial (15) or Presence Mode (17)**, and only a related one (`verification`) for 10.

**Why no behaviour change.** Defining the mapping decides what the zero-tolerance gate measures and could require new V2 categories (changing the frozen V2 design, floors and counts). The spec is therefore ambiguous and semantics-altering.

**What was added (non-frozen, unwired).**
* `docs/orneur/status/evalinfra/proposals/CATEGORY_MAPPING_PROPOSAL.NOT_FROZEN.json`: per V2 category, a relation (`CLOSE`/`PARTIAL`/`WEAK`/`NONE`), spec ids and rationale. Derived result: spec ids 1, 3, 4, 10, 11 are covered (only 3 and 4 as CLOSE); 14, 15, 17 are uncovered.
* `orca/evalinfra/category_mapping_proposal.py`: validator that requires status `PROPOSAL_NOT_FROZEN_NOT_NORMATIVE`, `frozen=false`, `authorizes_nothing=true`, the `PROPOSAL` schema token, a NOT FROZEN/NOT NORMATIVE banner, and forbids frozen-artifact keys (`record_sha256`, `frozen_at`, `plan_sha256`, `manifest_sha256`, `signature`). A test asserts no frozen-path module imports it.

**Decisions.**
* D3. Accept, amend or reject the proposed mapping (especially `verification` -> 10 PARTIAL).
* D4. For 14, 15, 17: (a) add V2 corpus categories (edits `genesis_eval_v1.CATEGORIES`/`CATEGORY_SPECS`, `genesis_v2/spec.py`, `isolation.py` SEPARATION_POLICY, prereg `category_counts`/`floors`; requires a new Eval version because floors are immutable post-freeze), or (b) evaluate the zero-tolerance categories from a separate spec-numbered suite (`genesis_suite`, deterministic scorers already exist for 10/14/15/17) and keep V2 as is. Recommendation: (b) for the first qualification, because it changes no frozen V2 semantics and the scorers exist; but note that suite is small (3 to 4 tasks per category) and public in-repo, so it cannot serve as a held-out private gate by itself. Decide whether that is acceptable or whether (a) is required before any qualification claim.
* D5. Which id scheme the analysis plan uses (evalinfra accepts spec ints or V2 names per manifest; the plan validator pins ints for zero-tolerance). Recommendation: keep ints and the mapping file, once accepted, converted into a frozen artifact hashed into the prereg.

## F5. Human vs LLM judge for categories 2, 6, 8, 13

**Reproduced.** `test_f5_gap_reproduced_*`: `genesis_suite.all_tasks()` has `scoring_type == "llm_judge"`, `deterministic=False` for exactly categories {2, 6, 8, 13}; `orca/evalinfra/schema.py` lines 22-23 and 100-101 refuse `llm_judge`/`model_judge` (`LLM_JUDGE_FORBIDDEN`) and offer `human_rubric`; refusal pinned in `tests/test_evalinfra_schema.py::test_llm_judge_scorer_refused`. A third test shows the inconsistency does not currently touch the zero-tolerance categories (10/14/15/17 are deterministic).

**Why no behaviour change.** The repo says only that the final decision "must never depend solely on an LLM judge" (`genesis_suite.py` module docstring; `GENESIS_EVALUATION_SUITE_V1.md` line 71-72, citing spec section 22) and defines a multi-judge protocol (`GENESIS_JUDGE_PROTOCOL_SPEC.md`, `GENESIS_FRONTIER_SCORING_CONTRACT.md` section 3). Neither forbids LLM judging outright nor mandates humans; evalinfra chose humans-only. The rubrics for these categories also say pass thresholds are "not yet defined" (e.g. `_CAT2_RUBRIC`). That is a methodology choice with cost, independence and freeze implications.

**Options.**
1. Human-rubric only (evalinfra's stance). Pro: no model-as-judge circularity, consistent with `rating.py` (kappa/alpha, adjudication). Con: needs raters that do not exist; cost and latency.
2. Multi-LLM-judge per the protocol spec, plus human audit sample. Pro: scalable. Con: needs provider calls (not authorized), judge-contamination and self-preference risks, evalinfra would have to lift `LLM_JUDGE_FORBIDDEN` (`schema.py` lines 22-23, 100-101; tests).
3. Exclude 2, 6, 8, 13 from gating; report-only until a method is chosen. Pro: unblocks everything else, no semantic change to deterministic gating. Con: those capabilities unmeasured.
4. Hybrid: humans score a stratified sample, LLM judges the rest, humans adjudicate disagreement; the gate depends on the human-scored portion only.

**Recommendation.** Option 3 now (they are not zero-tolerance and have no V2 corpus counterpart per F3), converging on option 4 or 1 once human raters exist. Do not lift `LLM_JUDGE_FORBIDDEN` until the judge protocol is qualified. Files that would change for option 1/3: `genesis_suite.py` scoring_type for tasks 2/6/8/13 (to `human_rubric`; changes suite digests, so the suite manifest and its contamination report must be regenerated) and the characterisation tests in `tests/test_evalinfra_findings_f3_f5.py`. For option 2: `schema.py` plus `tests/test_evalinfra_schema.py`.

## Unverified
Mapping relations in the F3 proposal are an engineer's reading of category descriptions, not validated against any corpus (none exists). No independent audit has reviewed any of this.
