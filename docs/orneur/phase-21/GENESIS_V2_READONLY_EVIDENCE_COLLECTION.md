# Genesis Capability Eval V2 — Read-Only Evidence Collection Procedure

A single command that aggregates every existing read-only check into one JSON bundle, so the owner (or an
independent auditor) can collect a full evidence snapshot without running five separate scripts and without ever
touching a real secret value.

```bash
python scripts/genesis_v2_evidence_snapshot.py                          # no vault check (no vault exists yet)
python scripts/genesis_v2_evidence_snapshot.py --vault <REAL_VAULT_DIR>  # also checks vault isolation, once a vault exists
```

## What it collects (all pre-existing, read-only functions — nothing new was implemented for their logic)

| Section | Source | What it reports |
|---|---|---|
| `owner_preflight` | `orca.eval.genesis_v2.owner_preflight.run()` | The full pre-corpus readiness computation — `READY_FOR_PRIVATE_CORPUS_AUTHORIZATION` or `NOT_READY`, with every individual hard-requirement check |
| `privacy_scan` | `orca.eval.genesis_v2.privacy_scan.scan_repository()` | Whether the public repository itself contains any private-corpus-shaped content |
| `role_preflight_owner` / `_generator` / `_verifier` | `store.owner_setup_preflight()` / `generator_setup_preflight()` / `verifier_setup_preflight()` | Environment-variable PRESENCE only for each role, run in the CURRENT process's own environment — this reports on THIS environment, not on a remote one; run the script separately, from within each real deployment environment, to get that environment's own snapshot |
| `vault_isolation` | `orca.eval.genesis_v2.vault_verify.verify_vault_isolation()` | Whether the given vault directory is genuinely outside every git working tree, with correct permissions — only run if `--vault` is supplied |

## Guarantees

- **Never prints a secret value.** Every underlying function it calls is presence/shape-only by construction (see each function's own docstring); this script adds no new secret-touching code.
- **Never writes anything.** No registry, vault, or ledger write occurs anywhere in this script.
- **Never activates, authorizes, or generates anything.** It is pure aggregation of read-only reads.
- **Always exits 0.** This script REPORTS; it does not gate. Each underlying check's own dedicated script
  (`genesis_v2_owner_preflight.py`, `genesis_v2_preflight.py --role ...`, `genesis_v2_vault_verify.py`) still has
  its own pass/fail exit code for gating purposes — use those in CI or a pre-flight gate, use this one for a
  human-readable or archivable evidence bundle.
- **A missing or unconfigured component is reported `NOT_CONFIGURED`, never silently omitted or manufactured as a
  PASS** — if any underlying call raises, the exception is caught and reported as an error entry, never swallowed
  into a false-positive result.

## Suggested use

- Run once now (no `--vault`) to capture the CURRENT, honest "nothing is configured yet" baseline — a useful
  artifact to compare against later.
- Run again, with `--vault`, once a real vault directory exists, from the OWNER's own admin context.
- Run `--role generator`/`--role verifier`-equivalent checks (i.e. this script itself, since it includes all three
  role preflights) from WITHIN each real deployment environment once they exist, to confirm each one's own
  environment matches what that role should — and only that role — see.
