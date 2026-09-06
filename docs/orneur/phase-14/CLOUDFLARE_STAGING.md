# Phase 14B — Cloudflare Staging Edge

**Status: DESIGN UPDATED FOR REAL NORTHFLANK TOPOLOGY; TUNNEL NOT YET EXECUTED.**

The original design assumed a raw VPS. Phase 14B now has a real managed remote workload on Northflank (`orneur-api-a`, Europe-West/London) with port `7337/TCP` private-only. That changes how the edge connector should be hosted, but does not weaken the direct-origin requirement.

## Target topology

```
Internet
  -> Cloudflare edge
  -> remotely-managed Cloudflare Tunnel
  -> cloudflared connector workload on Northflank
  -> Northflank private service DNS
  -> orneur-api-a:7337
```

The ORNEUR API port stays private. PostgreSQL, the independent security-root database, and any future model-worker/admin ports are never published through the tunnel.

## Northflank Service B plan

Create the second and final free-project service only after `orneur-api-a` is proven stable and after the `orneur-phase14b-runtime` secret group has been restricted to that API service.

Recommended connector workload:

- Service ID: `orneur-edge-tunnel`
- Source: external Docker image
- Image: `cloudflare/cloudflared:latest`
- Region: Europe-West/London, same project/network as the API
- Compute: smallest free plan sufficient for the connector; do not spend money merely to increase edge-connector resources
- Public ports: none
- Private application ports: none required for the tunnel itself
- Autoscaling: off on the free project
- Persistent volume: none
- Secret group: separate runtime-only group, for example `orneur-cloudflare-tunnel`
- Secret key: `TUNNEL_TOKEN` only
- Command arguments: `tunnel --no-autoupdate --loglevel info run`

Cloudflare documents `TUNNEL_TOKEN` as the environment-variable equivalent of `--token` for remotely-managed tunnels, so the token does not need to appear in a command line or repository file. The official Cloudflare Docker guidance uses the same `cloudflare/cloudflared:latest` image and remotely-managed tunnel model.

## Cloudflare owner checkpoint

Owner action is still required for the Cloudflare-side trust decision:

1. Add/manage the `orneur.com` zone in the owner's Cloudflare account if not already present.
2. Create a **remotely-managed** tunnel named for staging (for example `orneur-phase14b-staging`).
3. Configure a staging hostname, preferably a non-production hostname such as `staging.orneur.com` or `api-staging.orneur.com`.
4. Set the tunnel origin service to the Northflank private API address for `orneur-api-a:7337` using HTTP inside the private project network.
5. Copy only the generated tunnel token into the Northflank runtime-only secret group. Never commit or paste the token into chat/docs.

No Global API Key is required for this path. If later automation uses a Cloudflare API token, it must be narrowly scoped to the minimum tunnel/DNS permissions required.

## Direct-origin isolation

The strongest property of the current Northflank layout is already structural: `orneur-api-a:7337` is configured as **Private**, so there is no public Northflank origin URL for ordinary clients to bypass Cloudflare through.

This is stronger than exposing a public origin and relying only on application headers. Before marking the counter green, however, execute a real bypass test after the tunnel exists:

- attempt to reach the API through any Northflank-generated public route: expected result — no such route / unreachable;
- attempt to reach port 7337 directly from the public Internet: expected result — unreachable;
- reach the configured staging hostname through Cloudflare: expected result — routed successfully only through the tunnel.

`DIRECT_ORIGIN_BYPASS=0` is claimed only after those tests run.

## Trusted proxy headers

Do not trust arbitrary client-supplied `CF-Connecting-IP` or `X-Forwarded-For` merely because the header exists. The primary trust boundary is the private-only origin plus Cloudflare Tunnel. Any code-level client-IP trust added later must be tested against spoofed headers and must not become an authentication/authorization primitive.

The absence of public direct-origin access means spoofed proxy headers from the public Internet should never reach the API except through the configured edge path, but this must still be verified after the tunnel is live.

## Connector health

Cloudflare's current container/Kubernetes guidance exposes a connector readiness endpoint when metrics are enabled. For Phase 14B, first prove the connector stays connected and that Cloudflare reports the tunnel Healthy. If a Northflank health check is added to Service B, configure a cloudflared metrics/readiness endpoint explicitly rather than probing ORNEUR's `/livez` through the connector container.

## Failure tests after execution

Once the real tunnel is running, execute and record at minimum:

1. restart `orneur-edge-tunnel` and verify automatic tunnel reconnection;
2. stop the connector and verify the public staging hostname fails closed rather than bypassing to the origin;
3. restore the connector and verify recovery without changing ORNEUR secrets/state;
4. spoof proxy headers through the public hostname and confirm they do not bypass auth/policy;
5. confirm no database/security-root/model-admin endpoint is reachable through the tunnel;
6. confirm API port 7337 remains private in Northflank after all edge changes;
7. scan runtime logs to ensure the tunnel token is never printed.

## Evidence boundary

Northflank + Cloudflare Tunnel can satisfy application-origin isolation and real remote edge qualification without a raw VPS. It cannot satisfy VPS-specific evidence such as host firewall rules, SSH daemon hardening, kernel controls, or root-owned systemd configuration. Those host-level checks remain NOT_EXECUTED unless a raw host is provisioned later.

## References used for this design

- Cloudflare Tunnel setup: `https://developers.cloudflare.com/tunnel/setup/`
- Cloudflare tunnel run parameters and `TUNNEL_TOKEN`: `https://developers.cloudflare.com/tunnel/advanced/run-parameters/`
- Cloudflare Kubernetes/container deployment guide: `https://developers.cloudflare.com/tunnel/deployment-guides/kubernetes/`
- Northflank command/entrypoint overrides: `https://northflank.com/docs/v1/application/run/override-command-entrypoint`
- Northflank runtime secrets: `https://northflank.com/docs/v1/application/secure/inject-secrets`

No tunnel, DNS route, or Cloudflare-side configuration is claimed as executed by this document yet.
