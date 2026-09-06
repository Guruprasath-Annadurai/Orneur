# Phase 14B §35-37 — Rolling Update and Canary

**Status: NOT_EXECUTED.** Both require at least two running service
instances behind a real router/load balancer or a Docker/Compose/
systemd-managed pair of processes on real infrastructure (spec §35's
own explicit allowance: "A Docker/Compose/systemd rolling procedure is
valid for this infrastructure... No fake Kubernetes requirement") —
none of which exists without the VPS this session does not have (see
`REAL_STAGING_TOPOLOGY.md`).

## Design (once Host A exists)

- **Rolling update**: v1 serving via Docker Compose, v2 built and
  started alongside it, v2's `/readyz` polled until it passes, traffic
  (via the Compose service's internal proxy or a simple nginx/Caddy
  config in front of both) shifted to v2, v1 drained and stopped.
  Interruption measured as the gap (if any) in successful `/readyz`
  polls during the cutover.
- **Bad candidate**: deploy v2 with a deliberately broken config (e.g.
  missing `ORNEUR_SECURITY_ROOT_DATABASE_URL` in DISTRIBUTED mode) —
  Phase 14A.3/14A.4's own fail-startup enforcement means v2 would never
  pass `/readyz` and never receive traffic, while v1 continues serving
  unaffected. This is the one piece of this section that IS already
  proven, just not in a literal "two Docker containers on a VPS"
  topology — the underlying mechanism (a misconfigured worker never
  joining the serving pool) was tested for real in Phase 14A.3/14A.4's
  own multiprocess tests.
- **Canary**: a minimal router-based split (e.g. nginx `split_clients`
  or a small application-level proportion check) sending a controlled
  percentage of traffic to a candidate version, with error rate/latency
  compared against the stable version before promoting or rolling back.

None of this was built or executed this phase — recorded here as the
concrete plan for Phase 14B's continuation once real infrastructure is
available.
