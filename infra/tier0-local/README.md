# Tier 0 — Sovereign Local (Strategy A, owner-approved) — SYNTHETIC foundation only

**Built (this phase), synthetic fixtures + ephemeral keys only:**
- `docker/Dockerfile.{forge,witness,harness}` — separate, digest-pinned base images; hash-pinned `cryptography` (`requirements-tier0.txt`, compiled from `requirements-tier0.in`); minimal code subset (no qualification/privileged modules).
- `roles/` — in-container scripts: `probe.py`, `forge_write.py`, `witness_verify.py`, `provision.py`, `courier.py`, `audit.py`.
- Driver: `scripts/genesis_v2_tier0_local.py` (`discover | build | verify | teardown <run_id>`). Tests: `tests/test_genesis_v2_tier0_local.py`.

Topology = **Tier0-B (container variant)**: weaker than two physical machines; no distinct host OS users; no host firewall. See `docs/orneur/phase-21/infrastructure/GENESIS_V2_TIER0_TOPOLOGY_AND_HOST_CAPABILITIES.md`. Acceptance status: `GENESIS_V2_TIER0_ACCEPTANCE_STATUS.md` (no item is PROVEN_REAL).

**Not built / not authorized:** real keys or secrets, real vault, owner-key creation, host OS users (needs sudo), host firewall, real Reliquary drive, anything cloud. The earlier planned `create_*_user.sh` scripts remain intentionally unwritten (they need owner sudo).
