# Owner-Side Corpus-Generation Authorization — Signing Runbook (OWNER-RUN ONLY)

**Permanent doctrine (same as the owner-authority key procedure): the human owner holds private authority. ORNEUR
only verifies signatures. This runbook never asks for, receives, or handles the private key.**

This authorizes exactly one thing: generating specific artifact classes (`PILOT_TRAIN`/`DEV`/`SCREEN`/
`QUALIFICATION_HOLDOUT`) at the reviewed commit (or any genuine git descendant of it, with the exact generator code
you reviewed unchanged) and the exact evidence state you review before signing — **not** literal commit-hash
equality, and **not** any code change after you sign, even on the same commit lineage (see §2's note below for why).
It does **not** authorize model execution, GPU use, training, spending, or a V2 freeze — those each have their own
separate gates.

## 1. Precondition

You must already have your Ed25519 keypair from `OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md`
(`~/orneur-owner-authority/orneur_owner_authority_1.private.pem`), and `orneur-owner-authority-1`'s public key must
already be registered in `AUTHORITY_REGISTRY.json` (already done — verify with `git log --oneline -1 -- docs/orneur/authorization/AUTHORITY_REGISTRY.json`).

## 2. Prepare the exact payload (owner's own terminal, on the reviewed repository checkout)

```bash
python scripts/genesis_v2_prepare_corpus_generation_authorization.py --scope PILOT_TRAIN DEV --days 1
```

- `--scope`: the exact artifact classes you are authorizing generation of, from `PILOT_TRAIN DEV SCREEN
  QUALIFICATION_HOLDOUT`. Only name what you actually intend to generate in this window — a narrower scope is
  always safer; you can prepare a new authorization for a later stage.
- `--days`: validity window, at most 7 (`corpus_generation_authorization.MAX_VALIDITY`); shorter is safer. The
  window is counted from the moment you run this command, not from when you sign.

This script:
- reads the **real** current commit SHA, the **real** current corpus-inventory digest, and the **real** current
  preregistration record hash — it never lets you (or an automated process) pick these values yourself,
- writes `docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION_PAYLOAD_TO_SIGN.signable` (the exact bytes to
  sign) and `CORPUS_GENERATION_AUTHORIZATION_UNSIGNED_DRAFT.json` (the full record, for your review, unsigned),
- prints the payload's SHA-256 digest and the exact signing command below.

**Read the printed record before signing.** Confirm `authorized_scope`, `reviewed_commit_sha`,
`authorized_code_tree_sha256`, both digests, and the validity window are what you intend. If anything looks wrong,
do not sign — re-run with corrected flags, or on the commit you actually intend to authorize. The script refuses to
run at all on a dirty (uncommitted-changes) working tree — commit or stash first.

Note on the commit binding: `reviewed_commit_sha` is the commit that existed when you ran this script, not
necessarily the commit the signed authorization ends up stored in (a later commit that only adds the signed record
is fine and expected — see the module's own docstring for why literal commit-SHA equality would be circular).
`authorized_code_tree_sha256` is the real anti-drift binding: it is a hash of the actual generator code
(`orca/eval/genesis_v2/*.py`) at the moment you ran this, and any change to that code after you sign invalidates
the authorization even on the same commit lineage.

## 3. Verify the payload digest

```bash
shasum -a 256 docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION_PAYLOAD_TO_SIGN.signable
```

Must exactly match the digest the script printed.

## 4. Sign it

```bash
openssl pkeyutl -sign -inkey ~/orneur-owner-authority/orneur_owner_authority_1.private.pem \
  -rawin -in docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION_PAYLOAD_TO_SIGN.signable -out /tmp/cga.sig
xxd -p -c 1000 /tmp/cga.sig
```

The second command prints a 128-character hex Ed25519 signature.

## 5. What to send back

Send **only** the 128-hex-char signature string (never the `.pem` file, never the private key, never a screenshot
of your terminal history that might contain either). The unsigned draft record and the payload file are already
committed-repo-visible artifacts; you don't need to send those again.

## 6. What happens after you send the signature

The signature is verified against the registered `orneur-owner-authority-1` public key and the exact payload bytes
**before** it is written anywhere — exactly the same pattern used for the corpus-inventory attestation. If it
verifies, `CORPUS_GENERATION_AUTHORIZATION.json`'s `signature` field and `status: AUTHORIZED` are set; if it does
not, nothing changes and you are told why.

## 7. This still does not, by itself, permit generation

Per `operational_boundary.require_authorization()`, generation additionally requires a SEPARATE **generator**
identity to be `state: AUTHORIZED` in `CORPUS_GENERATOR_REGISTRY.json` (currently empty — no generator is
registered). The generator identity is deliberately distinct from the **qualification runner** identity in
`QUALIFICATION_RUNNER_REGISTRY.json` (still `REGISTERED_NOT_AUTHORIZED`): a generator may write PILOT_TRAIN/DEV/
SCREEN/QUALIFICATION_HOLDOUT to the vault before freeze, but must never also hold read access to the sealed private
splits — that is the qualification runner's distinct, later-stage role, itself additionally gated through the real
`AccessLedger` (`operational_boundary.require_private_split_access()`), which independently requires V2 to be
frozen. Signing a corpus-generation authorization is one necessary gate among several, never sufficient alone.

## 8. Expiry and re-signing

The signed authorization stops verifying, and this whole procedure must be repeated against the current state, if
any of the following happen — each maps to a specific denial reason so you know exactly why:

- the validity window from step 2 elapses (`EXPIRED`, or `STALE_BEYOND_MAX_VALIDITY` if `now` has drifted more than
  `MAX_VALIDITY` past `issued_at` even though `expires_at` is still technically in the future),
- execution happens at a commit that is not the reviewed commit or a genuine descendant of it — e.g. a rollback, a
  different branch, or reuse against an unrelated repository state (`REVIEWED_COMMIT_NOT_ANCESTOR_OF_EXECUTION`),
- the generator code (`orca/eval/genesis_v2/*.py`) changes after you signed, even on the very same commit lineage
  you reviewed (`CODE_TREE_HASH_MISMATCH` — this is the real anti-drift binding, not the commit SHA itself),
- the working tree is not clean at execution time (`DIRTY_WORKING_TREE`),
- the corpus inventory or preregistration record changes after you reviewed them (`CORPUS_INVENTORY_DIGEST_MISMATCH`
  / `PREREGISTRATION_DIGEST_MISMATCH`).

This is intentional — an authorization can never be silently reused against code or evidence you did not review.

## 9. Revocation

If you change your mind after signing but before generation happens, there is currently no separate revocation
record type for this authorization (unlike the owner-authority key itself, which has one — see
`OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md` §6). The authorization expires on its own within at most 7 days.
Treat "letting it expire without generating anything" as the revocation mechanism for now; a dedicated
`REVOKED` status is an unresolved capability for a future phase if immediate revocation is ever needed.
