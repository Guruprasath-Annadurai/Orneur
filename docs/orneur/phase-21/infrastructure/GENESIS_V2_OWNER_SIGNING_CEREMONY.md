# GENESIS V2 — Owner Signing Ceremony

Status: **DESIGN ONLY. THE CEREMONY HAS NOT BEEN PERFORMED.** No CGA has been signed, no generation receipt has been signed, `CORPUS_GENERATION_AUTHORIZATION.status` remains `NOT_AUTHORIZED`.

## Purpose

Make it structurally difficult for the owner to accidentally authorize something they did not deliberately review. Every step below exists because skipping it is exactly the kind of shortcut that turns a sound cryptographic design into a rubber stamp.

## Ceremony A — Corpus Generation Authorization (before generation)

1. **Read-only evidence snapshot generated.** Run `scripts/genesis_v2_evidence_snapshot.py --role owner` (existing tool, unchanged) to get a fresh, honest picture of current repository/registry state. Never sign against stale information.
2. **Owner reviews the exact commit and digests.** The reviewed commit SHA, the generator code-tree hash (`corpus_generation_authorization.code_tree_sha256()`), and the corpus-inventory + preregistration digests the CGA will bind to must all be independently re-derived by the owner from the actual repository state at signing time — never copy-pasted from a value someone else computed.
3. **Owner reviews requested scope.** Confirm the CGA's `authorized_scope` is exactly what's needed (e.g. `["SCREEN", "QUALIFICATION_HOLDOUT"]`) — never broader "to be safe."
4. **Owner reviews authorization expiry.** Confirm `issued_at`/`expires_at` form a short, deliberate window (`MAX_VALIDITY = 7 days` is the code's own hard ceiling) — not a long-lived standing authorization.
5. **Owner confirms generator identity.** Cross-check the specific `generator_id` this CGA is meant to cover against `CORPUS_GENERATOR_REGISTRY.json` — confirm it is the identity the owner actually intends to authorize, registered with the exact code hash that will run.
6. **Offline/hardware-backed signature.** The Ed25519 signature over the CGA's canonical signing bytes (`corpus_generation_authorization.canonical_signing_bytes()`) is produced on the Crown Plane — never on a machine that also runs Forge or Witness code, never through a CI job, never via a copy-pasted private key.
7. **Signed CGA imported.** The signed record is committed to `docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json` through the normal reviewed-commit process — not hand-edited on a running Forge machine.
8. **Exact signature independently verified.** Before generation starts, run `corpus_generation_authorization.verify()` (or `check_authorization()`) against the real committed record and the real execution context, and confirm it returns `authorized=True` for exactly the intended generator/scope — this is the same check `require_authorization()` performs automatically, but the owner should also watch it succeed once, consciously, before triggering real generation.
9. **Generation starts.** Only now does the Forge call `protected_generate_write_handle()`.

## Ceremony B — Generation Receipt Attestation (after a successful write)

10. **Generation result emitted.** `GeneratorWriteHandle.write_corpus()` returns the immutable `GenerationWriteResult` (`corpus_digest`, `generation_event_payload`, `generation_event_payload_digest`) — captured directly from the write, never reconstructed from memory or re-typed.
11. **Owner reviews the emitted digest.** The `generation_event_payload_digest` is transmitted to the owner through a channel independent of the ciphertext-transfer channel (e.g. displayed on the Forge's own console and read aloud/copied by the owner, or committed as a small, separate evidence artifact the owner fetches themselves) — never trusted merely because "the generator said so" over the same channel carrying the ciphertext.
12. **Owner signs the generation receipt.** `generation_receipt.attest_receipt(payload, attesting_authority=..., sign_bytes=..., expected_payload_digest=...)` is called with the **independently captured** digest from step 11 — this is now mandatory in code (the digest-optional call shape was removed in the final-emission-evidence-hardening phase), and the ceremony's own discipline (an independent capture channel) is what gives that mandatory parameter real security value rather than being satisfied by blindly re-hashing whatever the generator happens to hand over in the same breath.
13. **Verifier validates receipt and ciphertext.** `operational_boundary.verify_manifest_digest_only_same_process()` runs the full composed check (CGA authentication, manifest authentication, receipt authentication and window check, ledger-gated read) — this is the existing, accepted, unchanged code path.
14. **Evidence bundle sealed.** The signed CGA, the signed manifest, the signed receipt, and the ledger records are committed together as one evidence bundle for that corpus — not left scattered across separate, unlinked artifacts.

## What this ceremony deliberately makes hard to skip

- Steps 2–5 and 11 all require the owner to independently *compute or receive through a separate channel* a value, rather than simply clicking "approve" on a value someone else already prepared — this is the actual countermeasure to "owner signs something they didn't review," not a policy statement alone.
- Step 6 and step 12 both happen on the Crown Plane, never on Forge or Witness — enforced by the custody plan (the key physically cannot be used elsewhere), not merely by procedure.
- Step 8 requires watching a **negative-then-positive** control: the owner should also try (or recall having tried, during the acceptance test in `GENESIS_V2_REAL_DEPLOYMENT_ACCEPTANCE.md`) an intentionally wrong scope/identity and confirm it's rejected, so step 8's "it worked" has been contrasted against "and it correctly fails when wrong."

## Not performed by this phase

No step above has been executed. This document is the design the owner will follow when they choose to authorize real corpus generation — a decision explicitly reserved for the owner, not this phase.
