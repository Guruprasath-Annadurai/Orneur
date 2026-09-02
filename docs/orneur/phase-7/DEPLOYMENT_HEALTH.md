# Deployment Health (Phase 7.1 spec §25-28)

## The real root cause Phase 7 disclosed

Phase 7 found Model Society's deployment-health hard filter was a
documented no-op for the common case: no `ModelDeployment` records existed
on disk for the legacy tier-based Ollama serving path. Phase 7.1's
investigation found the EXACT reason: `orca.gateway.wiring.brain_for_tier_resolution()`
(the function every live model call actually goes through) already
registers a `ModelDeployment` on the SHARED, LIVE `ModelGateway` singleton
for every resolved tier/backend -- but only IN MEMORY, never persisted to
disk. Model Society's router reads the DISK-based
`orca.gateway.deployment.list_deployments()` registry -- a completely
different, effectively-always-empty store in production. Two parallel
deployment-tracking systems existed; only one was ever populated.

## The fix

`brain_for_tier_resolution()` now calls `deployment.save()` once per
unique `deployment_id` (not on every request -- a small, tracked
`_deployments_persisted` set avoids redundant disk I/O on the hot path).

## Legacy Genesis deployment identity (spec §26)

The persisted record for `orca-nano-v7` (Genesis's legacy 7B checkpoint,
served via the real local Ollama installation) uses:

- `model_id="orneur-genesis"`, `model_version="orca-nano-v7"`,
  `artifact_id="orca-nano-v7"` -- the EXACT checkpoint identity, never
  collapsed with the canonical future 3B target (which has no deployment
  at all, since no checkpoint exists to serve).
- `runtime="ollama"`, `runtime_endpoint=CONFIG.ollama.host` -- the real,
  actually-configured local Ollama endpoint.
- `hardware_profile="local"` -- descriptive only, no GPU/hardware claim
  fabricated.
- `lifecycle=LEGACY_PRODUCTION_SERVING` -- see below.

## A real regression this fix could have caused, and how it's prevented (spec §26, §34)

If this record had used the ordinary `LifecycleState.EXPERIMENTAL.value`
(what Novus's deployment record correctly uses), then once persisted,
Model Society's `ModelDeployment.is_routable(allow_experimental=False)`
check would start REJECTING Genesis for every production request --
a severe regression (Court would always abstain). Genesis's record
instead uses the disclosed `LEGACY_PRODUCTION_SERVING` pseudo-lifecycle
(`orca.society.lifecycle`, introduced Phase 7) precisely because it is
neither honestly `PRODUCTION` (no formal `ModelRegistry` promotion has
happened) nor safely `EXPERIMENTAL` (that would break real, working
behavior). Novus's own deployment record is UNCHANGED --
`LifecycleState.EXPERIMENTAL.value`, still correctly gated. Verified
directly:
`tests/test_gateway_wiring_deployment_records.py::test_persisted_genesis_deployment_is_routable_in_production_by_society`
(the regression guard) and
`test_novus_deployment_still_gets_real_experimental_lifecycle` (the
non-regression proof for Novus).

## Worker/circuit health (spec §27)

`orca.society.router._deployment_health_ok()` now ALSO consults the live
shared `ModelGateway`'s `CircuitBreaker` (`_default_circuit_breaker()`,
best-effort -- returns `None`, never raises, if the gateway can't be
reached) in addition to `ModelDeployment.is_routable()`. Tested directly
with all five required cases
(`tests/test_society_deployment_worker_health.py`): READY selected,
DRAINING rejected, UNHEALTHY rejected, OFFLINE rejected, open-circuit
rejected (even when health=READY) using a real `CircuitBreaker` instance.

## Unknown-deployment policy (spec §28)

When NO deployment record exists at all for a model_id (still the
majority case for anything not yet actively served this process --
deployments are registered lazily, on first live call), the health check
returns `(True, "no deployment record on file -- health check skipped
(documented gap)")` -- an explicit COMPATIBILITY-POLICY choice, not a
silent "unknown means healthy" default: it is documented, tested, and
distinct from an actually-present-but-unhealthy record (which IS
rejected). This matches spec §28's "allow only under compatibility
policy" option, chosen because Model Society must not regress a legacy
serving path that predates deployment records existing at all.
