# Phase 10 — Lease Integrity

Reuses the codebase's EXISTING HMAC signing discipline
(`orca.auth.tokens`, `orca.license.keys`, `orca.license.stripe_hook`) —
`hmac.new(secret, canonical_payload, sha256)` + `hmac.compare_digest` —
rather than inventing a second cryptographic primitive.

## What is signed

`_SIGNED_FIELDS` in `orca/godmode/integrity.py`: `lease_id`,
`principal_id`, `tenant_id`, `capability_domain`, `capability`,
`resource_scope`, `operation_scope`, `issued_at`, `expires_at`, `issuer`,
`issuer_id`, `approval_id`, `max_uses`, `delegable`, `nonce`. Modifying
ANY of these after signing is detected by `verify_lease_integrity()` —
verified individually for each field in
`tests/test_godmode_security.py::test_lease_tamper_any_signed_field_fails_integrity`.

Deliberately EXCLUDED: `uses_remaining` (legitimately decrements over
the lease's life without invalidating its origin) and `revocation_state`
(legitimately flips to `REVOKED` — checked separately by
`resolve_lease()`, never via the signature).

## Honesty about what this guarantees

This is a REAL integrity check — it detects any modification to a lease
object once it has left `issue_lease()`'s hands, whether that
modification happens in memory, on disk, or in transit. It is NOT a
claim of non-repudiation against a party who holds the server-side
`GODMODE_LEASE_SECRET` (the same limitation the existing
`orca.auth.tokens` pattern already has, and the same threat model this
codebase has always accepted for that mechanism). No fabricated
cryptographic guarantee (e.g. an asymmetric-signature claim this
codebase doesn't actually implement) is made anywhere in documentation
or code comments.

## Nonce (spec §12)

Every lease gets a fresh random `nonce` (`uuid.uuid4().hex`), covered by
the signature. Copying one lease's nonce onto a different lease object
does not help an attacker — the signature was computed over the
ORIGINAL object's full field set including its OWN nonce, so a nonce
swap alone (without a valid signature over the new field combination)
still fails `verify_lease_integrity()` — verified in
`test_lease_nonce_reuse_does_not_bypass_a_fresh_lease_signature`.
