# PHASE 20 -- EVIDENCE

## 1. Live end-to-end smoke test (real Phase 17/18/19 objects, no mocks)

Built a real `CognitiveArtifact` -> real `compile_artifact()` -> real
`assess_artifact()` overlay via `tests/integrity/conftest.py`'s
`build_known_affirmed_fixture()`, then called `route_task()` directly:

```
status RoutingStatus.INVESTIGATION_REQUIRED
primary CognitiveFamily.NOVUS
material_factors (MaterialEpistemicFactor(atom_id='a1', epistemic_state=<EpistemicState.KNOWN: 'KNOWN'>),)
decision_id 21cf506cd9b8ce344ba3cfe59ba95df508556ffef574517e28e800d5296b5add
deterministic: True
```

## 2. Defect #1 -- reproduced and fixed live

**Symptom** (before fix): a task requiring both `INVESTIGATION` and
`ADVERSARIAL_REVIEW`, with an all-eligible custom registry (Genesis,
Novus, and Aeternum all lifecycle `EXPERIMENTAL` / `AVAILABLE`),
produced `mandatory_review_family=None` and
`ADVERSARIAL_REVIEWER_UNAVAILABLE` even though Aeternum was genuinely
available and genuinely supports `ADVERSARIAL_REVIEW`:

```
AssertionError: assert None is <CognitiveFamily.AETERNUM: 'AETERNUM'>
```

**Root cause**: the mandatory-review lookup gated on
`eligible_by_family.get(CognitiveFamily.AETERNUM)`, i.e. it required
Aeternum to satisfy the *primary* task's core requirement set
(`INVESTIGATION`, which Aeternum's registry entry does not support) --
conflating "eligible to be the primary owner of this task" with
"eligible to review this task", two independent questions.

**Fix**: evaluate Aeternum's reviewer eligibility independently, using
only its own lifecycle/availability (`registry.is_eligible`) and
whether its own `supported_requirements` overlaps the review-triggering
kinds actually present in the task's effective requirements
(`orneur/intelligence/router/evaluator.py`).

**Verification**: `tests/router/test_routing_behavior.py::
test_adversarial_review_requirement_with_available_reviewer_is_granted`
now passes; the full 45-test router suite passes.

## 3. Defect #2 -- test-design correction (not an evaluator bug)

**Symptom**: a task requiring `{IMPLEMENTATION, INVESTIGATION}`
together against a registry where only Genesis was made eligible
(`supported_requirements` unchanged: `{IMPLEMENTATION,
EXECUTION_PLANNING, VERIFICATION}`) produced `primary_family=None`
instead of the test's expected `NOVUS`.

**Investigation**: confirmed this is correct, intentional behavior.
Genesis's registry entry does not support `INVESTIGATION`; Novus's does
not support `IMPLEMENTATION`. Neither family's `supported_requirements`
is a superset of the combined core requirement set, so neither is
eligible for single-primary-owner routing -- by design (Phase 20 V1 is
not a multi-agent task-splitting system; see
`PHASE20_INTELLIGENCE_ROUTER_SPEC.md` &sect;5). `NO_ELIGIBLE_ROUTE` is
the correct, honest outcome.

**Resolution**: replaced the flawed test with two tests that isolate
the two real claims: (a) role-priority preference for
`REASONER_INVESTIGATOR` when a candidate genuinely covers the
requirement set (`test_investigative_requirement_prefers_novus_role_priority`,
using a registry where Genesis is explicitly broadened to also support
`INVESTIGATION` so both are independently eligible), and (b) the
disjoint-requirement fail-closed behavior itself
(`test_disjoint_combined_requirements_with_no_single_covering_family_fails_closed`).

## 4. Hostile self-review grep sweep

```
$ grep -rn -E "uuid|random|datetime\.now|time\.time" orneur/intelligence/router/*.py   # (no output)
$ grep -rn "hash(" orneur/intelligence/router/*.py                                      # (no output)
$ grep -rn "except Exception" orneur/intelligence/router/*.py                           # (no output)
$ grep -rn ": Any" orneur/intelligence/router/*.py                                      # (no output)
$ grep -rn "cast(" orneur/intelligence/router/*.py                                      # (no output)
$ grep -rn "type: ignore" orneur/intelligence/router/*.py                               # (no output)
$ grep -rn -E "approved|authorized|execution_grant|human_approval|trusted =|verified =" orneur/intelligence/router/*.py  # (no output)
```

Zero findings across all seven checks.

## 5. Test counts

| Suite | Result |
|---|---|
| `tests/router/` (this phase) | 45 passed |
| `tests/integrity/` (Phase 19 regression) | 225 passed, unchanged |
| `tests/epistemic/` (Phase 18 regression) | 138 passed, unchanged |
| `tests/ocl/` (Phase 17 regression) | 348 passed, unchanged |
| `tests/test_packaging_invariant.py` (extended, wheel + sdist) | 8 passed |
| Full deterministic suite (`pytest -m "not live_ollama_smoke" -q`) | 3133 passed, 256 skipped, 43 deselected |

Reconciliation against the prior baseline (end of Phase 19's second
closure, commit `8083d85`): 3344 non-deselected + 45 new router tests =
3389 non-deselected now (3133 passed + 256 skipped = 3389, exact
match); deselected count unchanged at 43.

## 6. Wheel/sdist packaging verification

`tests/test_packaging_invariant.py` was extended to assert
`orneur/intelligence/router/` (and its `evaluator.py`/`enums.py`/
`canonical.py`) is present in both the built wheel and sdist, and that
`import orneur.intelligence.router` succeeds from a fresh virtualenv
installed from each artifact independently of the repository's own
`.venv`/`pythonpath` setting. All 8 packaging tests pass.

## 7. Cost

No model, tool, or network calls were made by any Phase 20 source file
(confirmed by `test_no_authority.py`'s substring scan and the AST-based
import scan). All work in this closure was static code authoring, live
Python execution for reproduction/verification, and `pytest` runs.
