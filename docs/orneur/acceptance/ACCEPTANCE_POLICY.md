# ORNEUR acceptance policy

This document is the governing text for `scripts/acceptance/acceptance_engine.py`'s
`POLICY_VERSION`. Its content is hashed at import time; every signed ledger
record must declare that exact hash as its `policy_version`, so changing
this document invalidates every previously-signed record and forces a
conscious re-attestation rather than letting an old record silently keep
validating under a changed policy. This binds "policy identity" to real
governing content instead of a free-floating version label.

## What a signed acceptance record attests to

A record for requirement row `R` is valid only if, together, it proves:

1. **Evidence identity** — the record's `evidence_key`, `artifact_class`,
   and `scope` match `R`'s own register entry exactly, and its
   `artifact_sha256` is a well-formed 256-bit digest that is not reused by
   any other accepted row in the same ledger.
2. **Source identity** — the record's `git_sha` equals the exact commit
   SHA under evaluation; an ancestor SHA is rejected as `STALE`, not
   accepted as equivalent.
3. **Independent review** — the record names a `reviewer_role` equal to
   `R`'s registered `independent_reviewer`, distinct from `R`'s
   `implementation_owner`, signed by a key enrolled with that exact role.
4. **Founder authority, where required** — if `R.founder_approval ==
   "REQUIRED"`, a second signature from a key enrolled with role
   `FOUNDER`, cryptographically distinct from the reviewer's key, is
   required over the same payload. A reviewer attestation alone never
   satisfies such a row.
5. **Corpus identity** — the three dependent protected-corpus evidence
   rows (`DATA-1`, `DATA-2`, `DATA-5`) must bind to the one digest
   `DATA-3` itself was accepted under, via a signed `bound_corpus_sha256`
   field, not merely a well-formed digest of their own choosing.
6. **Custody independence** — `DATA-5` (the corpus custody and integrity
   receipt) must be signed by a reviewer key cryptographically distinct
   from the key that got `DATA-3` (the corpus creation record) accepted —
   a custodian who is not the creator, checked by key identity, not merely
   by role name.
7. **Reviewer and founder trust** — every key used anywhere above must
   carry a detached enrollment signature from a currently non-revoked
   founder root key, covering its role, scope, and revocation state
   together at a specific monotonic epoch; among several enrollment
   records presented for the same key, only the highest-epoch one that
   verifies is authoritative, so a stale "still active" record cannot be
   replayed to override a later revocation.

Nothing in this document authorizes provisioning, purchase, real secret or
credential creation, protected-corpus generation, qualification, model
selection, GPU use, spend, or training. It governs the acceptance ledger
only.
