# Phase 14 §13-17 (infra), §41-45, §60-62, §85 — Canary and Rollback

## Real, executable today: infra rollback and model-lifecycle authority

Not new this phase, but confirmed by reading the code: model lifecycle
(NOT_PROMOTABLE/EXPERIMENTAL/RETIRED/ABSENT states, per Phase 8's
registry work) is enforced at `orca/registry/model_registry.py` and
`orca/gateway/gateway.py`'s deployment registration — a deployment
record cannot manufacture lifecycle eligibility (spec §15 of this
phase's numbering) because the Gateway's `register_deployment`-style
call sites consult the registry's own lifecycle field, not a value the
deploying request supplies. This was not modified or re-tested this
phase (out of scope — no lifecycle-bypass attack was newly attempted),
but it directly satisfies spec §15's requirement structurally.

## Real canary/rollback deployment — NOT_EXECUTED

**Status: NOT_EXECUTED.** A real canary (bounded traffic sample to a
candidate deployment, measured error/latency/schema-failure rates,
explicit promotion decision) requires a real multi-replica deployment
behind a real router making that traffic split — no such deployment
exists (see `MULTI_WORKER.md`, `GCP_DEPLOYMENT.md`). Similarly, a real
"bad candidate crashes, stable deployment survives, rollback occurs"
test (spec §61-62) requires the same real infrastructure.

## What this phase's Gateway code already provides as the substrate (unchanged, confirmed by reading)

`orca/gateway/gateway.py`'s `_deployments` registry already models
multiple deployments coexisting (old + new, spec §13) since it's keyed
by deployment ID, not a single "current model" pointer — this is the
structural precondition for canary routing, though no traffic-splitting
policy engine sits on top of it yet. `orca/gateway/circuit_breaker.py`
already provides the "quarantine a failing deployment" mechanism a
canary-rollback decision would use (spec §41's crash-loop detection),
again unchanged and pre-existing.

## Release/rollback manifest foundation (spec §71-72, §85)

**Not implemented as a concrete artifact this phase.** The conceptual
contents (code SHA, container digest, model deployment IDs, checkpoint
hashes, config version, security-suite result reference) are listed in
`PHASE_14_CLOSURE.md`'s own "Release Manifest" section using this
phase's actual, real values (git SHA, test counts) as a first concrete
instance — but no reusable manifest-generation tooling was built.

## Config dry-run (spec §73, §86)

**Not built this phase.** A "validate config/registry/artifacts/
dependencies without serving traffic" mode does not exist in this
codebase today. Recommended as a concrete next addition (distinct from
Simulation Chamber, per spec §86's own caution not to conflate the
two — Simulation Chamber previews privileged *actions*, not deployment
configuration).
