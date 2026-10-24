# Authorized index HMAC trust boundary

The session index authenticates rows with HMAC-SHA256. The key lives in
`gN.mac.key` in the **same session directory** as `gN.chunks.jsonl`,
`gN.revoked.txt`, and the `.generation` commit pointer.

## What this protects against

- Coordinated rewrite of document text and its SHA-256 digest **without**
  the current generation key.
- Substitution of `chunks.jsonl` (or a generation leaf) without updating
  the hashed `.generation` pointer.
- Cross-tenant or cross-session rows whose MAC was not minted under this
  session's tenant/session binding.

## What this does not protect against

- An attacker who can write the session directory, including the MAC key
  and the generation pointer. That attacker can mint a valid MAC for any
  text. Same-UID local filesystem compromise of the session directory is
  **outside** this authenticity claim.
- An attacker who already holds the in-memory key of a live process.

There is no separately enforced key isolation (HSM, different UID, or
directory that the index worker cannot write). Do not describe this HMAC
as protection against arbitrary same-UID filesystem compromise.

Rotation commits a new key and re-MACed rows as **one generation**. The
durable commit is the `.generation` pointer, not two independent
`os.replace()` calls.
