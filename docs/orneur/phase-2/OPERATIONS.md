# Operating the Model Gateway (today)

## Minimal working example

```python
from orca.gateway.gateway import ModelGateway
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.gateway.deployment import ModelDeployment, DeploymentHealth
from orca.registry.model_spec import LifecycleState

gateway = ModelGateway()
gateway.register_runtime("ollama", OllamaRuntime(host="http://localhost:11434"))

deployment = ModelDeployment(
    deployment_id="novus-local-ollama",
    model_id="orneur-novus",
    model_version="orca-core-combined-v2",
    artifact_id="orca-core-combined-v2",
    runtime="ollama",
    runtime_endpoint="http://localhost:11434",
    hardware_profile="local-cpu",
    lifecycle=LifecycleState.EXPERIMENTAL.value,  # Novus is NOT_PROMOTABLE -- see docs/orneur/phase-1/NOVUS_PROMOTION_DECISION.md
    health=DeploymentHealth.STARTING.value,
)
gateway.register_deployment(deployment)

# Must warm up before it's routable at all.
await gateway.warmup(deployment)

# A bare "orneur-novus" request would raise ModelNotRoutableError here
# (EXPERIMENTAL, no PRODUCTION deployment exists) -- must opt in explicitly:
from orca.gateway.contracts import InferenceRequest
request = InferenceRequest(
    request_id="req-1", model_id="orneur-novus",
    messages=[{"role": "user", "content": "Hello"}],
)
response = await gateway.generate(request, allow_experimental=True)
```

## Admin operations require existing authorization infrastructure

`register_deployment`, `warmup`, and `request_drain` are currently Python-API-level calls only — **no HTTP route exposes any of them yet**, so "normal user inference routes cannot invoke them" is trivially true today (nothing exposes them at all). When a future phase adds an HTTP admin surface for these (deploy/promote/drain a model), it **must** gate every one of those routes through the existing `orca/auth/rbac.py` RBAC infrastructure (already real: rank-based `owner > admin > member > viewer`) — not a new, parallel authorization mechanism, and explicitly not a "Godmode" bypass (which this phase was instructed not to implement, and did not).

## Health check integration (not yet wired into `/healthz`)

`ModelGateway.report_health()` is a real, callable function today — it is **not yet wired into `orca/serve/api.py`'s existing `/healthz` endpoint**. That endpoint continues to report exactly what it reported before Phase 2 (unchanged, unregressed). Wiring `report_health()`'s three-way liveness/readiness/model-readiness distinction into a real HTTP response is a natural, small next step, deliberately not bundled into this same pass per the same "don't rewrite the working serving path in the same commit as building its replacement" discipline applied everywhere else in Phase 2.

## Running the test suite

```bash
python3 -m pytest tests/test_gateway_*.py -v
```

Four tests in `tests/test_gateway_ollama_runtime.py` require a real, locally-reachable Ollama instance and auto-skip (not fail) if one isn't running — everything else is self-contained (fake/mocked runtimes, isolated temp directories for any file-backed state).
