# Phase 14B §4-6 — VPS Baseline and Hardening

**Status: NOT_EXECUTED.** No real VPS is available to this session —
see `REAL_STAGING_TOPOLOGY.md`'s infrastructure-availability check and
OWNER ACTION REQUIRED checkpoint.

## What this document will record once a VPS exists

Per spec §4, before any deployment:

- Provider, region, OS, kernel version, vCPU count, RAM, disk, network/
  IP, trial duration, resource limits — recorded from the provider's
  own dashboard/API, never assumed or estimated.
- No provider SLA claimed unless independently verified from the
  provider's own published documentation for that specific plan tier.

Per spec §5, before ORNEUR deployment:

- A non-root `orneur` service user created for running the
  application (never running the service as root).
- SSH key-only login confirmed working BEFORE disabling password
  authentication — spec's own explicit "every SSH change must preserve
  a tested recovery path" and "do not lock owner out."
- SSH restricted (e.g. to key-based auth, a non-default port only if
  the owner prefers it, `AllowUsers`/`fail2ban` or equivalent).
- Host firewall (ufw/nftables/iptables) enabled, default-deny inbound
  except for SSH and whatever Cloudflare Tunnel needs (which, using a
  Tunnel, is an outbound-only connection — see `CLOUDFLARE_STAGING.md`
  — meaning no inbound HTTP port needs to be opened at all).
- Security updates installed (`apt update && apt upgrade`/equivalent).
- Unused services disabled.
- Time synchronization confirmed (`timedatectl`/`chronyd`/`ntpd`) —
  relevant since this project's hash-chained audit trails and lease
  expiry logic depend on reasonably accurate wall-clock time across
  hosts.
- Resource limits set (systemd `MemoryMax`/`CPUQuota` or container
  equivalents, per spec §51's "no test may deliberately exhaust
  provider resources").
- Basic audit/logging enabled (`auditd` or the provider's default
  logging, at minimum).

None of this has been done — there is no VPS to do it on.
