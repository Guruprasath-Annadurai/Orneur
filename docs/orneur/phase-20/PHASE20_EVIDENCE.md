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

---

## 8. FINAL closure -- trusted registry, receipt binding, route identity

### 8.1 Registry self-elevation: reproduced, then fixed

```
status: RoutingStatus.SELECTED primary: CognitiveFamily.GENESIS
REPRODUCED: a caller-supplied, merely structurally-valid registry
claiming Genesis is EXPERIMENTAL/AVAILABLE was accepted and used to
select Genesis, with no out-of-band trust check at all.
```

After the fix:

```
FIXED: untrusted registry rejected -> UntrustedCapabilityRegistryRejected UNTRUSTED_CAPABILITY_REGISTRY_REJECTED
trusted+correct digest -> status: RoutingStatus.SELECTED primary: CognitiveFamily.GENESIS
```

### 8.2 Integrity-receipt binding: reproduced, then fixed

```
unrelated BLOCKED receipt -> status: RoutingStatus.BLOCKED_BY_INTEGRITY
REPRODUCED (incorrect over-block)
unrelated SATISFIED receipt -> status: RoutingStatus.SELECTED
REPRODUCED (fabricated SATISFIED accepted)
```

After the fix:

```
FIXED: untrusted receipt rejected -> UntrustedIntegrityReceiptRejected UNTRUSTED_INTEGRITY_RECEIPT_REJECTED
FIXED: unrelated-artifact receipt rejected via binding check -> IntegrityReceiptBindingInvalid INTEGRITY_RECEIPT_BINDING_INVALID
```

A genuinely bound, real Phase-19 `SATISFIED` receipt (built via an
actual `assess_integrity()` call, not a hand-constructed dataclass) is
correctly accepted and its digest surfaces in
`RoutingDecision.source_integrity_receipt_digest`.

### 8.3 Test-helper defect found while wiring real receipts

`tests/router/conftest.py`'s `make_blocked_integrity_receipt`/
`make_satisfied_integrity_receipt` used the literal placeholder string
`"irrelevant-for-router-tests"` for `source_artifact_digest` -- once
the binding check was added, this made even the "ordinary trusted
path" tests fail, because the placeholder digest never matches a real
artifact's digest. This confirmed the fix was live and exposed the
test-helper gap named in the closure spec (&sect;12). Fixed by adding
`make_real_integrity_receipt()`, which drives a genuine
`assess_integrity()` call (real `IntegrityProposal`/`ProposedAssertion`
against the real overlay/artifact) so `source_artifact_id`/
`source_artifact_digest`/`source_overlay_digest` are always genuinely
correct. A `make_forged_integrity_receipt()` helper was kept
separately, used only by tests that deliberately exercise the binding
boundary itself.

### 8.4 Review-honesty collision: confirmed live, not just by assertion

A task requiring only `ADVERSARIAL_REVIEW` against an all-eligible
registry does reach the collision branch (not a vacuous test):

```
primary: CognitiveFamily.AETERNUM mandatory_review: None
reasons: (ADVERSARIAL_REVIEW_REQUIRED, ELIGIBLE_CAPABILITY_MATCH,
          MANDATORY_REVIEWER_CANNOT_BE_PRIMARY_FAMILY)
```

Aeternum is selected as primary via the alphabetical role-priority
fallback (no investigative/implementation signal is present), and the
guard correctly clears `mandatory_review_family` rather than reporting
Aeternum as its own independent reviewer.

### 8.5 Hostile self-review grep sweep (FINAL closure package state)

Same seven checks as &sect;4, rerun against the full updated package
(now including `receipt_trust.py` and the expanded `registry.py`/
`evaluator.py`): zero findings across all seven.

### 8.6 Test counts

| Suite | Result |
|---|---|
| `tests/router/` (FINAL closure) | 67 passed (was 45) |
| `tests/integrity/` (Phase 19 regression) | 225 passed, unchanged |
| `tests/epistemic/` (Phase 18 regression) | 138 passed, unchanged |
| `tests/ocl/` (Phase 17 regression) | 348 passed, unchanged |
| `tests/test_packaging_invariant.py` | 8 passed, unchanged |
| Full deterministic suite | 3155 passed, 256 skipped, 43 deselected |

Reconciliation against the prior Phase 20 baseline (commit `7168557`):
3389 non-deselected + 22 new trust-closure tests = 3411 non-deselected
now (3155 passed + 256 skipped = 3411, exact match); deselected
unchanged at 43.
