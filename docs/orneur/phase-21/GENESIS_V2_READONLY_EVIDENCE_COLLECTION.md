# Genesis Capability Eval V2 — Read-Only Evidence Collection Procedure

A single command that aggregates every existing read-only check into one JSON bundle, so the owner (or an
independent auditor) can collect a full evidence snapshot without running five separate scripts. Role-aware since
this round's correction — see "Security contract" below for exactly which checks touch actual secret bytes versus
which only see presence/shape, and for why running all three role checks in one invocation is never evidence of
real cross-deployment separation.

```bash
python scripts/genesis_v2_evidence_snapshot.py                          # --role all (default): every role preflight against THIS environment
python scripts/genesis_v2_evidence_snapshot.py --role generator         # ONLY the generator's own preflight -- run FROM the generator's real deployment
python scripts/genesis_v2_evidence_snapshot.py --role verifier          # ONLY the verifier's own preflight -- run FROM the verifier's real deployment
python scripts/genesis_v2_evidence_snapshot.py --vault <REAL_VAULT_DIR>  # also checks vault isolation, once a vault exists
```

## What it collects (all pre-existing, read-only functions — nothing new was implemented for their logic)

| Section | Source | What it reports |
|---|---|---|
| `owner_preflight` | `orca.eval.genesis_v2.owner_preflight.run()` | The full pre-corpus readiness computation — `READY_FOR_PRIVATE_CORPUS_AUTHORIZATION` or `NOT_READY`, with every individual hard-requirement check |
| `privacy_scan` | `orca.eval.genesis_v2.privacy_scan.scan_repository()` | Whether the public repository itself contains any private-corpus-shaped content |
| `role_preflight_owner` / `_generator` / `_verifier` | `store.owner_setup_preflight()` / `generator_setup_preflight()` / `verifier_setup_preflight()` | Environment-variable PRESENCE/SHAPE for the role(s) selected by `--role`, run in the CURRENT process's own environment — this reports on THIS environment, not on a remote one; run the script separately, from within each real deployment environment, with the matching `--role`, to get that environment's own honest snapshot |
| `vault_isolation` | `orca.eval.genesis_v2.vault_verify.verify_vault_isolation()` | Whether the given vault directory is genuinely outside every git working tree, with correct permissions — only run if `--vault` is supplied |

## Security contract (which checks touch a secret value, and which never do)

| Check | Touches actual secret bytes? | What it emits |
|---|---|---|
| `owner_preflight` | No | Presence/shape/derived-boolean findings only |
| `privacy_scan` | No | Whether the public repo contains private-shaped content |
| `vault_isolation` | No | Path-permission/isolation booleans (never the path itself) |
| `role_preflight_generator` | Vault-key bytes: No — public key SHAPE only, private key NON-PRESENCE only. Corpus secret: **Yes — decodes and validates its entropy** (via `secret.load_secret_from_env`), since generation needs a real seed | Boolean/shape findings; a `violations` entry naming the offending env var if the private key is present, never its value |
| `role_preflight_verifier` | Vault-key bytes: No — private key SHAPE only. Corpus secret: never required or touched at all | Boolean findings |
| `role_preflight_owner` | Vault-key bytes: **Yes — the ONLY check here that reads actual key bytes.** Its X25519 pair-matching step reads the real public/private key bytes to confirm they form a genuine keypair. Corpus secret: **Yes — decodes and validates its entropy**, same as the generator | Only a boolean match/mismatch finding — the bytes themselves are never included in its return value or in this report |

**`--role all` (the default) never proves cross-deployment separation.** Running `role_preflight_generator` and
`role_preflight_verifier` in the SAME invocation only tells you what ONE environment (this process's own) exposes
— it is not, and is never presented as, evidence that two real, separate deployments keep their credentials apart.
The report's `cross_environment_separation_evidence` field is always the literal string
`"NOT_ESTABLISHED_BY_THIS_TOOL"`, regardless of what the individual role checks report, for exactly this reason.
Genuine separation evidence requires running this script SEPARATELY, once per real deployment (with the matching
`--role`), and comparing the two outputs by hand — see `GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md`.

## Guarantees

- **Never prints or emits a secret VALUE**, even though `role_preflight_owner`'s pair-matching step genuinely reads
  key bytes internally (see the table above) — only presence/shape/boolean findings ever leave any underlying
  function's return value.
- **Never writes anything.** No registry, vault, or ledger write occurs anywhere in this script.
- **Never activates, authorizes, or generates anything.** It is pure aggregation of read-only reads.
- **Always exits 0.** This script REPORTS; it does not gate. Each underlying check's own dedicated script
  (`genesis_v2_owner_preflight.py`, `genesis_v2_preflight.py --role ...`, `genesis_v2_vault_verify.py`) still has
  its own pass/fail exit code for gating purposes — use those in CI or a pre-flight gate, use this one for a
  human-readable or archivable evidence bundle.
- **A missing or unconfigured component is reported `NOT_CONFIGURED`, never silently omitted or manufactured as a
  PASS** — if any underlying call raises, the exception is caught and reported as an error entry, never swallowed
  into a false-positive result.
- **No part of an underlying exception's own message text is ever forwarded into this report, in any form**
  (item 3 of the authenticated-transfer-and-evidence-integrity-closure phase). An earlier version of this script
  forwarded a truncated exception message scrubbed only of 64-hex-character substrings — a pattern that would miss
  a base64-encoded secret, a variable-length secret, or a secret embedded in a path. Instead, `_safe()` returns a
  FIXED, ALLOWLISTED error code (`"UNEXPECTED_EXCEPTION"`), a static per-check description written into the script
  ahead of time, and the exception's class name only (a safe, non-secret Python identifier) — see
  `tests/test_genesis_v2_evidence_snapshot.py` for adversarial coverage across hex-, base64-, variable-length-, and
  path-shaped secrets, and deliberately hostile exception strings.

## Suggested use

- Run once now (no `--vault`, `--role all`) to capture the CURRENT, honest "nothing is configured yet" baseline —
  a useful artifact to compare against later.
- Once real deployments exist: run `--role generator` FROM the generator's own real environment, and separately
  `--role verifier` FROM the verifier's own real environment. Compare the two outputs by hand to confirm each only
  ever shows its own role's expected state — this comparison IS a meaningful step toward separation evidence,
  unlike a single `--role all` run.
- Run again, with `--vault`, once a real vault directory exists, from the OWNER's own admin context.
