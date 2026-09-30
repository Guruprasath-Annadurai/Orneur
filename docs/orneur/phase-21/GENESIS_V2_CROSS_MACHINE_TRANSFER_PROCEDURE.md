# Genesis Capability Eval V2 — Cross-Machine (and Cross-Account) Ciphertext Transfer Procedure

Corrects a real gap in the prior round's deployment documents: neither `GENESIS_V2_INFRASTRUCTURE_DISCOVERY.md` nor
`GENESIS_V2_THREE_IDENTITY_DEPLOYMENT_DESIGN.md` specified HOW encrypted `SCREEN`/`QUALIFICATION_HOLDOUT` artifacts
actually move from the generator's machine to the verifier's, under the "two trusted local machines" default (A1).
This is not zero integration work — it requires an explicit transfer step, which this document specifies precisely
and which `tests/test_genesis_v2_cross_machine_transfer.py` demonstrates end-to-end with real cryptography.

## The six required properties

### 1. Ciphertext-only transfer, and how receipt is verified

What crosses the wire/media is exactly three files per corpus: `SCREEN.enc`, `QUALIFICATION_HOLDOUT.enc`,
`SEAL.enc` — raw bytes, copied verbatim. **No decryption happens on the sending side**: the generator holds
`store.EncryptedVaultWriter`, which has no `read_split` method and no private-key material anywhere in its object
state (see its own docstring) — it is structurally incapable of decrypting what it just wrote, so it cannot
"verify before sending" in any cryptographic sense, and does not need to.

Receipt verification happens entirely on the RECEIVING (verifier) side, using the SAME authenticated-encryption
check that already protects against on-disk tampering: `EncryptedVaultReader.read_split()` performs a full AEAD
decrypt-and-authenticate on every `.enc` file it opens. Any corruption introduced during transfer — a bit flip, a
truncated write, a dropped file — is caught at this point and raises `PrivateStorageIntegrityError`, exactly as
`tests/test_genesis_v2_cross_machine_transfer.py::test_a_corrupted_transfer_is_caught_by_seal_and_digest_verification`
and `::test_an_incomplete_transfer_is_caught_not_silently_accepted` demonstrate. There is no separate
"transfer-integrity" mechanism to build — the existing crypto already provides it.

### 2. File ownership and permissions

Whatever transfer mechanism is used (see §7) very likely does NOT preserve exact POSIX permissions (many
network-copy tools, cloud object stores, and archive formats do not). **The receiving side must explicitly
re-apply `0700` on the corpus directory and `0400` on each `.enc` file after the transfer completes, before ever
calling `read_split()`.** This is a real, required step — not implied by the code, and not automatic. See the test
above for the exact `os.chmod()` calls this requires.

### 3. Corpus digest and SEAL verification

`expected_corpus_digest` passed to `read_split()` **must come from an independent, already-trusted channel** — the
signed `corpus_generation_authorization` record or the `corpus_manifest` — **never re-derived from the transferred
artifacts themselves.** If the digest were computed FROM the same bytes being verified, an attacker who controlled
the transfer could simply recompute a self-consistent (but fake) digest alongside fake content — the whole point
of an independently-sourced digest is that it did NOT travel through the same channel as the content it checks.
`tests/test_genesis_v2_cross_machine_transfer.py::test_a_stale_or_mistaken_expected_digest_fails_closed_even_on_a_genuinely_valid_transfer`
proves the converse: even a perfect transfer is rejected if the WRONG (independently-sourced) digest is supplied —
there is no fallback to trusting the ciphertext's own claims.

### 4. Write-once preservation

Write-once is preserved independently on both sides, by different mechanisms:
- **Generator side**: `EncryptedVaultWriter.write_corpus()` itself refuses a second write to the same `corpus_id`
  (`cdir.mkdir(exist_ok=False)` raises `FileExistsError`) — unaffected by anything downstream.
- **Verifier side**: the imported copy is inherently read-only in practice, because `EncryptedVaultReader` has no
  `write_corpus` method at all — there is no API surface through which the verifier's copy could be mutated by this
  program's own code. (Ordinary filesystem access outside this program could still overwrite files — the `0400`
  permission from §2 is the actual enforcement against that, same as on the generator's side.)

### 5. Ledger custody and evidence continuity

The access ledger (`ledger.py`, hash-chained SQLite) **never needs to move**, because the generator never touches
it — `write_corpus()` has no ledger interaction anywhere. Every ledger call (`AccessLedger.request_access()`) is
made by whichever process performs a READ (the creation-time verifier, and later the qualification runner). The
ledger's canonical location is therefore wherever verification/qualification actually happens — co-located with the
verifier's own machine/account, never synced with or duplicated to the generator's side. This keeps the hash chain
single-writer and meaningful as evidence, with no cross-machine consistency problem to solve.

### 6. Prevention of plaintext or private-key transfer

**Structurally guaranteed, not merely a transfer-discipline rule**: the generator never possesses plaintext beyond
what it itself just encrypted in memory (discarded after `write_corpus()` returns), and never possesses the private
key at all (only the public half — see `GENESIS_V2_THREE_IDENTITY_DEPLOYMENT_DESIGN.md`). There is therefore
nothing plaintext- or private-key-shaped for the transfer step to accidentally move, PROVIDED the transfer only
ever touches files ending in `.enc` — verified pre-transfer by running `privacy_scan.scan_vault_dir()` on the
staging/export location (it flags anything that isn't `.enc` or `.tmp-*` as `plaintext_beside_encrypted`).

## Two-OS-accounts-on-one-machine: NOT simpler than two machines

A prior document implied "two OS accounts on one machine" might avoid needing a transfer step, since both accounts
share one filesystem. **This is wrong, and is corrected here.** The generator's own corpus directory is `0700`,
owned by the generator's UID — a different OS account **cannot even list it**, let alone open the `.enc` files
inside (a plain permission-denied error). A shared vault directory model does not work under the strict permission
discipline this architecture otherwise requires everywhere else.

The fix is **structurally identical to the cross-machine case**: the verifier's OS account performs its own
explicit copy-in step, into its own freshly created, `0700`-owned directory, then re-applies `0400` on the copied
files — see `test_two_os_accounts_one_machine_still_requires_an_explicit_export_import_step` for the exact
demonstration. The only difference from the two-machine case is that the "transport" is a local filesystem copy
rather than physical media or a network protocol. Concretely, one of:

- **A shared, group-readable staging directory** (`0770`, owned by a group both accounts belong to): the generator
  copies `.enc` files there; the verifier copies them OUT into its own `0700` directory and deletes the staging
  copy. Requires creating that shared group and staging directory once.
- **`scp localhost`** (or equivalent) between the two accounts' SSH identities: works even without a shared group,
  at the cost of needing SSH configured for localhost logins under each account.

Neither pattern is chosen here — both are legitimate, and the choice belongs to the owner, consistent with this
program's standing rule of returning infrastructure decisions rather than deciding them.

## What this means for the "ready today, $0" claim

The claim in `GENESIS_V2_INFRASTRUCTURE_DISCOVERY.md` that the local-machine model requires "no new integration
work" was **correct about the cryptographic primitives** (`EncryptedVaultWriter`/`EncryptedVaultReader` are fully
implemented and tested) but **incomplete about the operational procedure** — the explicit transfer/import step
above was previously undocumented and undemonstrated. It is now both: documented in this file, and proven
end-to-end (including the corruption, incomplete-transfer, stale-digest, and two-account failure/fix scenarios) in
`tests/test_genesis_v2_cross_machine_transfer.py`. No new production code was required to make this real — the
existing `EncryptedVaultWriter`/`EncryptedVaultReader` API already supports it; what was missing was writing the
procedure down and proving it, not building anything new.
