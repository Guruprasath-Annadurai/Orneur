# Owner Authority Key — Generation Procedure (OWNER-RUN ONLY)

**Permanent doctrine: the human owner holds the private authority key. ORNEUR (this repository, its CI, Claude, and ChatGPT) only ever
verifies signatures against the registered public key. No automated process may generate, hold, transmit, or paste this private key.**

This procedure is to be run by the owner, on the owner's own machine, outside any Claude/ChatGPT/CI session. Nothing in this file is
executed automatically by any tooling in this repository.

## 1. Generate the Ed25519 keypair (owner's own terminal)

```bash
openssl genpkey -algorithm ed25519 -out orneur_owner_authority_1.private.pem
chmod 600 orneur_owner_authority_1.private.pem
```

Do not run this inside a Claude Code session, a CI runner, or any shared/automated environment. Run it locally, interactively, on
hardware the owner physically controls.

## 2. Private-key storage requirements

- Store `orneur_owner_authority_1.private.pem` **only** in a secret manager the owner controls (e.g. macOS Keychain, a hardware
  security key, or a password manager's secure-note/file attachment with encryption at rest).
- Never commit it to any git repository (this one or any other).
- Never paste it into a chat session, an issue, a PR description, a CI log, or any file this repository's tooling reads.
- Never transmit it over email, Slack, or any unencrypted channel.
- If it must leave the local machine for backup, encrypt it first with a passphrase only the owner knows, and store the encrypted
  blob, not the raw key.

## 3. Export the public key (owner's own terminal)

```bash
openssl pkey -in orneur_owner_authority_1.private.pem -pubout -out orneur_owner_authority_1.public.pem
openssl pkey -pubin -in orneur_owner_authority_1.public.pem -outform DER | tail -c 32 | xxd -p -c 32
```

The last command prints the 32-byte raw Ed25519 public key as a 64-character lowercase hex string — this is the `public_key_hex`
value the registry (`orca/eval/genesis_v2/authority_registry.py`) expects. Send **only** this hex string (and the key_id below) back
for registration. The `.pem` files themselves, and the private key in particular, must never be sent.

## 4. Key ID format

`orneur-owner-authority-<n>` where `<n>` is a small increasing integer, starting at `1` (matching the id already reserved in the
design docs: `orneur-owner-authority-1`). A new id is used for every rotation; ids are never reused.

## 5. Verification command (anyone, using only the public key)

Given a message `msg.bin` and a hex signature `sig.hex` produced by the owner's private key:

```bash
python3 - <<'PY'
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex("<public_key_hex>"))
pub.verify(bytes.fromhex(open("sig.hex").read().strip()), open("msg.bin", "rb").read())
print("signature OK")
PY
```

This is exactly the check `orca/eval/genesis_v2/inventory.validate_attestation_record()` and
`orca/eval/genesis_v2/authorization.py` perform internally once the public key is registered.

## 6. Rotation procedure

1. Generate a new keypair under the next `orneur-owner-authority-<n+1>` id (steps 1–3 above).
2. Register the new public key in `AUTHORITY_REGISTRY.json` with role `OWNER`, `revoked: false`.
3. Set `revoked: true` on the old record (do not delete it — historical signatures made under it must remain independently
   re-verifiable against the record that was active at signing time).
4. Any attestation or authorization signed after rotation must use the new key; anything already signed under the old key remains
   valid for that point in time (a revocation is forward-only — see `identity_registry.is_active()`).

## 7. Revocation procedure (compromise or owner decision)

1. Immediately set `revoked: true` on the affected `AUTHORITY_REGISTRY.json` record. `identity_registry.is_active()` then returns
   `False` for it regardless of its `expiry`, so no further signature verifies against it as an *active* authority key.
2. If compromise is suspected, treat every signature made under that key **after** the suspected compromise timestamp as untrusted
   pending manual review; signatures from before the suspected compromise are not automatically invalidated by revocation alone.
3. Generate a replacement key under a new id (see Rotation, above) before any further owner-authority signing is needed.

## What registering this key does NOT do

Registering `orneur-owner-authority-1`'s public key:

- does **not** authorize any model execution — `MODEL_EVAL_AUTHORIZATION.status` remains `NOT_AUTHORIZED` until a separate,
  explicit authorization record is created and signed;
- does **not** sign the corpus-inventory attestation by itself — a signed `completeness_attestation.record` must still be produced
  and verified against the registered key;
- does **not** freeze Genesis Capability Eval V2;
- does **not** by itself grant any private-split (SCREEN / QUALIFICATION_HOLDOUT) access.

## Current status

`AUTHORITY_REGISTRY.json` is committed **empty** (`records: []`). It stays empty until the owner completes steps 1–3 above and
provides only the resulting `public_key_hex` + `key_id` for registration. Until then: `authority_registry` state remains
`CONFIGURED_ZERO_KEYS_REGISTERED`, the corpus-inventory attestation remains unsigned, and `owner_preflight` remains `NOT_READY` on
this specific requirement.
