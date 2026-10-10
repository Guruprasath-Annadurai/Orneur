# ORNEUR acceptance policy

This document is the governing text for `scripts/acceptance/acceptance_engine.py`'s
`POLICY_VERSION`. `POLICY_VERSION` is the sha256 of this document's bytes,
the engine's own source file's bytes, and the published register graph
JSON's bytes, concatenated in that order. Every signed ledger record must
declare that exact hash as its `policy_version`, so changing any of the
three -- the written policy, the enforcement code itself, or the graph it
enforces -- invalidates every previously-signed record and forces a
conscious re-attestation rather than letting an old record silently keep
validating under a changed policy, changed code, or changed graph. This
binds "policy identity" to the actual enforcement mechanism, not a
free-floating version label a document alone could satisfy.

## What a signed acceptance record attests to

A record for requirement row `R` is valid only if, together, it proves:

1. **Evidence identity** -- the record's `evidence_key`, `artifact_class`,
   and `scope` match `R`'s own register entry exactly, and its
   `artifact_sha256` is a well-formed 256-bit digest that is not reused by
   any other accepted row in the same ledger.
2. **Source identity** -- the record's `git_sha` equals the exact commit
   SHA under evaluation; an ancestor SHA is rejected as `STALE`, not
   accepted as equivalent.
3. **Independent review** -- the record names a `reviewer_role` equal to
   `R`'s registered `independent_reviewer`, distinct from `R`'s
   `implementation_owner`, signed by a key enrolled with that exact role
   in the current `trust_snapshot` (see "Trust state" below).
4. **Founder authority, where required** -- if `R.founder_approval ==
   "REQUIRED"`, a second signature from a key enrolled with role
   `FOUNDER`, cryptographically distinct from the reviewer's key, is
   required over the same payload. A reviewer attestation alone never
   satisfies such a row.
5. **Evidence integrity** -- see "Signatures are not possession" below.
   An ordinary row needs the caller to present bytes that actually hash to
   the declared digest; the four protected corpus-evidence classes need a
   non-disclosing custody-possession signature instead, since real
   content for those must never be generated or accessed.
6. **Corpus identity, distinct from DATA-3's own record digest** --
   `DATA-3` declares `corpus_identity_sha256`: the identity of the corpus
   itself, a value distinct from `DATA-3`'s own `artifact_sha256` (the
   digest of `DATA-3`'s creation *record* -- who created it, when, under
   what manifest -- not of the corpus content). The three dependent rows
   (`DATA-1`, `DATA-2`, `DATA-5`) bind to that distinct identity via
   `bound_corpus_identity_sha256`, never to `DATA-3`'s record digest.
   Binding to the record digest instead of the declared identity is
   rejected as `CORPUS_IDENTITY_MISMATCH`.
7. **Custody independence by key, not by label** -- `DATA-5` (corpus
   custody and integrity) must be signed by a reviewer key whose actual,
   resolved `public_key_hex` is distinct from the key that got `DATA-3`
   accepted -- a custodian who is not the creator, checked by
   cryptographic identity. Two different `key_id` labels enrolled against
   the same underlying keypair would not be independent, and this check
   catches that; two different roles sharing a label would not either.
8. **Trust state** -- every key used anywhere above must appear in the
   current `trust_snapshot`, which must itself verify against the current
   `root_state`, which must itself verify against the permanent bootstrap
   identity. See "Trust state: three separate documents" below.

## Signatures are not possession

A detached Ed25519 signature over a claimed digest proves only that
*someone holding a particular private key* was willing to attest to that
digest string. It proves nothing about whether bytes matching that digest
actually exist, were ever produced, or are in anyone's custody. This
module never conflates the two:

- **Cryptographic signature verification** (`_verify_signature`,
  `_verify_whole_signature`) proves a specific key signed a specific
  payload. Nothing more.
- **Evidence-artifact existence**, for ordinary (non-protected) rows, is
  checked separately: the caller must supply `artifact_bytes` containing
  content that hashes to the record's declared digest
  (`EVIDENCE_NOT_RESOLVED` otherwise). A correctly shaped, correctly
  signed digest with no matching bytes anywhere is not evidence of
  anything existing.
- **Verified corpus custody**, for the four protected corpus-evidence
  classes (where real content must never be generated or accessed by this
  program), is a *non-disclosing custody-possession signature*
  (`custody_signature_hex`, over `custody_challenge_bytes`): a second,
  purpose-built signature from the row's own reviewer key, over a
  challenge derived from the digest and commit. This proves the named
  custodian deliberately attested possession of *this exact* digest at
  *this exact* commit. It does **not** prove byte-for-byte possession the
  way a real Merkle inclusion proof or a disclosed-content hash check
  would -- that would require either disclosing the protected content (not
  permitted) or a disclosure-free commitment scheme this module does not
  implement. This limitation is disclosed, not hidden: a custody signature
  is evidence of a deliberate, bound attestation, not cryptographic proof
  of physical possession of underlying bytes.
- **Physical possession** of real protected-corpus content is outside this
  module's scope entirely, by design -- it is never generated, requested,
  or inspected here, synthetic test fixtures included.
- **Independent human-operator identity** is approximated by
  cryptographic key identity (`CUSTODY_INDEPENDENT_FROM`, matched on
  resolved `public_key_hex`), not asserted as a verified real-world fact.
  Two different keys are evidence of two different operators only to the
  extent the founder's own enrollment and key-custody practices keep them
  so -- this module cannot and does not verify who, in the real world,
  held a given private key.

## Trust state: three separate documents

Binding every signed document to the exact commit SHA under evaluation
(`subject_sha`) closes rollback *across* commits -- an older, still
validly-signed version of a trust document carries an ancestor SHA, not
the current one, and is rejected as stale. It does **not**, by itself,
close rollback *within* one commit: nothing about commit identity orders
two different, both validly signed, trust generations that happen to name
the same `subject_sha` (for example, a founder revocation decided without
any code change). Audit #003 reproduced exactly that. The fix is not to
compare generation numbers -- a caller who can choose which document to
present can also choose which generation claim to believe -- and it is
deliberately **not** to embed a commit's own SHA inside a file committed
as part of that very commit: the tree being hashed to produce a commit SHA
cannot already contain a file that names that same SHA without a
self-referential, unsatisfiable dependency. Three separate documents exist
instead:

1. **The immutable code/policy commit being evaluated** (`subject_sha`) --
   external to this module, supplied by the caller, unchanged by anything
   below.
2. **The signed trust-state snapshot** -- `root_state` (which founder
   roots are currently valid, anchored to a `bootstrap_root_key_hex` that
   must also appear in this module's own hardcoded
   `PINNED_BOOTSTRAP_ROOT_KEYS`, so a caller-supplied bootstrap key is
   never authoritative merely by being passed in) and `trust_snapshot`
   (which reviewer/founder keys are currently valid, signed by a
   non-revoked root). Both bound to `subject_sha`, as above -- necessary,
   but not sufficient for same-commit freshness.
3. **The independently trusted current trust-state checkpoint** --
   `trust_checkpoint`, a third signed document that commits to the exact
   hash of both #2's documents for this `subject_sha`. Its own hash must
   equal a `pinned_checkpoint_hash` the caller supplies from a channel
   *independent of this evaluation* -- published, witnessed, or mirrored
   outside this one call, the way a certificate-transparency signed tree
   head is independently monitored rather than trusted on an individual
   verifier's say-so. This module never derives that pin itself; it only
   verifies that what it was given is internally consistent and matches
   it exactly. A same-commit rollback -- two validly signed
   `trust_snapshot` generations, same `subject_sha` -- is closed because a
   hash pin matches at most one document, full stop, regardless of how
   many other validly signed but different documents also exist for that
   commit.

The committed baseline keeps all of this empty: `reviewer_trust.json` (no
entries), `founder_root_keys.json` (no roots), `BOOTSTRAP_ROOT_KEY.json`
(no key, and no key pinned in the engine's own source either),
`TRUST_CHECKPOINT.json` and `TRUST_CHECKPOINT_PIN.json` (both empty). No
real founder identity, reviewer key, or trust checkpoint has been
provisioned. Sourcing a real `pinned_checkpoint_hash` from an actually
independent channel, once real trust material exists, is an operational
process this module provides the verification primitive for but does not
itself implement end-to-end.

Nothing in this document authorizes provisioning, purchase, real secret or
credential creation, protected-corpus generation, qualification, model
selection, GPU use, spend, or training. It governs the acceptance ledger
only.
