# Phase 10 — Revocation, Expiry, and Restart Safety

## Revocation (spec §14, §41-42)

`orca.godmode.lease_store.revoke(lease_id)` sets
`revocation_state=REVOKED` and persists it immediately. There is no
cache in front of lease resolution — `resolve_lease()` reads the lease
fresh from disk (via `get()`) on every call, so there is no "stale
cache" that could permit a new action after revocation. Verified:
`test_revocation_immediately_denies_next_action_even_with_time_remaining`
(a lease valid with 300s remaining is denied the instant after
`revoke()` is called, before its TTL would otherwise have expired).

Active long-running actions: this codebase's connector/file elevation
operations are all short, synchronous, single-shot writes (no
long-running elevated stream exists to interrupt mid-flight) — so
"handle according to action class" (spec §14) is satisfied trivially:
there is nothing to interrupt, and a revoked lease's next attempted use
is denied regardless.

## Expiry checked before every action (spec §13)

`resolve_lease()` calls `is_expired()` fresh on every invocation — never
only at session/lease creation time. Verified:
`test_expiry_checked_before_every_action_not_only_at_session_creation`
(a lease forcibly expired between issuance and a later resolve call is
denied on that later call).

## Restart safety (spec §57-58)

Leases persist as JSON files under `ORCA_HOME/godmode/leases/` (mirroring
`orca.gateway.deployment`'s established `ModelDeployment` persistence
pattern). After a process restart:

- An expired lease read back from disk is still expired (`expires_at` is
  a fixed, signed field — nothing about a restart changes it).
- A revoked lease read back from disk is still revoked
  (`revocation_state` persists to disk immediately on `revoke()`).
- No "all sessions become valid" behavior is possible because
  `GodmodeSession` itself holds no authority (see AUTHORITY_LEVELS.md) —
  every action re-resolves its named lease from the persistent store,
  regardless of in-memory session bookkeeping state.

Verified: `test_restart_safety_expired_lease_stays_expired_after_reread`
in the eval harness re-reads a lease via a fresh `get_lease()` call
(simulating the post-restart read path) and confirms it still resolves
to DENY.

## Cache safety (spec §42)

This implementation does not add a SEPARATE lease-validation cache layer
at all — every `resolve_lease()` call reads the current on-disk state
directly. This sidesteps spec §42's cache-key requirements entirely by
having no cache to key in the first place, which is the simplest way to
guarantee "no stale lease cache may permit new actions" (there is
nothing that could go stale). A future performance-driven cache would
need to follow spec §42's key composition (lease ID + principal + tenant
+ nonce/revocation epoch) exactly as specified.
