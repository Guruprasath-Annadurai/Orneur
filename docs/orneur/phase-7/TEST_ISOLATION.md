# Test Isolation (Phase 7.1 spec §29-31)

## The real leak found and fixed

`tests/test_gateway_chaos.py::test_chaos_deployment_draining_stops_new_requests_but_is_explicit`
called `dep.request_drain()` (which internally calls `ModelDeployment.save()`)
without isolating `orca.gateway.deployment.DEPLOYMENT_DIR` -- writing a
real `dep-fake-1.json` file into the developer's actual
`~/.orca/registry/deployments/` on every run. This was the actual root
cause of the file Phase 7 observed polluting its own routing
demonstrations (Phase 7's audit had suspected four DIFFERENT
`test_gateway_*.py` files based on which ones construct `ModelDeployment`
objects; the real culprit was the one file that calls `.save()`-triggering
methods without isolation). Fixed directly (`tests/test_gateway_chaos.py`
now isolates `DEPLOYMENT_DIR` via `tmp_path`/`monkeypatch`, matching the
established pattern in `tests/test_gateway_deployment.py`).

## Regression protection (autouse fixture)

`tests/conftest.py::_isolate_gateway_registry_dirs` is now an
**unconditional autouse fixture** applying to every test in the suite --
widened from an initial `test_gateway_*`-scoped version once Phase 7.1's
deployment-records fix (see `DEPLOYMENT_HEALTH.md`) meant
`orca.gateway.wiring.brain_for_tier_resolution()` persists a deployment
record on every live model call, meaning ANY test exercising a real
Court/Kernel/Truth Fabric call (not just `test_gateway_*` files) could
otherwise also write into the developer's real `~/.orca`. The fixture
repoints `DEPLOYMENT_DIR` to a fresh `tmp_path` before every test body
runs; a test that sets its own explicit override still works (its own
`monkeypatch.setattr` simply takes over after this fixture's).

Direct regression test:
`tests/test_gateway_test_isolation.py` proves the isolation actually
takes effect for the exact call chain that leaked
(`ModelDeployment.request_drain()` → `.save()`).

## Environment isolation audit (spec §30)

- `ORCA_HOME`/legacy `ORCA_HOME`: covered by the pre-existing
  `tests/conftest.py::isolated_home` fixture (auth/db tests, unchanged) and
  the new `_isolate_gateway_registry_dirs` fixture (deployment records).
- Registry DB (checkpoints/evaluations/registry_state): covered by
  `tests/test_registry_lifecycle.py`'s own `isolated_registry_dirs`
  fixture (pre-existing, unchanged, verified still isolating correctly).
- Deployment state: covered by the new autouse fixture above.
- Circuit-breaker state: in-memory only, never persisted -- no isolation
  needed (a fresh `ModelGateway()`/`CircuitBreaker()` per test is already
  the norm; `_default_circuit_breaker()` reads the SHARED live gateway
  singleton only in production code, and Society router tests inject
  their own `circuit_breaker_lookup` overrides, per
  `tests/test_society_deployment_worker_health.py`).
- Metrics: `tests/test_gateway_warmup_health.py`'s pre-existing
  `_reset_metrics` autouse fixture (unchanged).
- Worker state: no test writes real worker records outside
  `tests/test_gateway_worker_routing.py`, which constructs `Worker(...)`
  objects without calling `.save()` (verified -- no leak found here).

## Live integration tests remain non-destructive (spec §31)

Live-Ollama tests (`@pytest.mark.live_ollama_smoke`) still make real model
calls against the local Ollama instance -- isolation here is about
REGISTRY/CONFIG STATE, not about avoiding real inference. Verified: the
full `live_ollama_smoke` suite was re-run after this phase's changes and
confirmed to leave `~/.orca/registry/deployments/` untouched (see
`PHASE_7_FINAL_CLOSURE.md`'s test-run log).
