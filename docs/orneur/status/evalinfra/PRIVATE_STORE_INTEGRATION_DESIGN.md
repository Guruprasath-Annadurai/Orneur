# Private-storage integration: design and what is tested

NON_NORMATIVE. Designs how the protected evaluation reads a private corpus *through* the existing `orca.eval.genesis_v2` store, and proves with synthetic backends that
the interface fails closed. It creates no store, no key, no secret and no corpus.

## 1. Interface (unchanged, taken from `orca/eval/genesis_v2/store.py`)

```
PrivateCorpusStore:
  describe() -> dict
  write_corpus(corpus_id, {SCREEN: bytes, QUALIFICATION_HOLDOUT: bytes}) -> corpus_digest      # write-once; both private splits mandatory
  read_split(corpus_id, split, *, expected_corpus_digest) -> bytes                              # SEAL authenticated; digest mismatch => PrivateStorageIntegrityError
```

Backends and honest state:

| Backend | Where | State |
|---|---|---|
| `NoStore` | `store.py` | default; every call raises `PrivateStorageNotConfigured` (tested) |
| `EncryptedFileStore` (AES-256-GCM, symmetric) | `store.py` | implemented; **legacy**, superseded by the X25519 vault |
| `EncryptedVaultWriter` / `EncryptedVaultReader` (X25519 + AEAD, write-only vs read) | `store.py` | implemented; activated with an **ephemeral test key** only |
| `PRIVATE_GITHUB_REPO`, `PRIVATE_OBJECT_STORE` | `store.PrivateStoreConfig` | **descriptors only**; no transport code; needs the founder |
| `SyntheticMemoryStore`, `SyntheticDirStore` | `orca/evalinfra/private_store.py` | tests/demo only; **no confidentiality** (plaintext); `describe()["private_grade"] is False` |

`is_private_grade(store)` is true only for a configured, non-synthetic kind in `store.KINDS`. A synthetic backend therefore can never satisfy the
`private_storage_genuinely_configured` freeze prerequisite.

## 2. Access path (all steps must pass; the first three are founder/external acts that do not exist yet)

```
runner process                          ProtectedEvalGate (orca/evalinfra/access.py)                        store
  |  ProtectedAccessRequest ------------>  1. runner registry: registered, state AUTHORIZED, code hash, scope
  |                                        2. signed authorization: active authority key, exact request, not expired,
  |                                           not revoked, not replayed (chained consumption log)
  |                                        3. signed CLEAR review manifest bound to the corpus digest (>= N reviewers,
  |                                           no dual-role authority/reviewer)
  |                                        4. expected corpus digest == request digest (public commitment)
  |                                        5. vault configuration present for the runner role (presence/shape only)
  |                                        6. V2 frozen (qualification purposes) ; ledger chain verifies against an
  |                                           EXTERNALLY ANCHORED head
  |  <---- Grant (ledger seq + record hash) -  7. AccessLedger.request_access appends the grant (write-once lifecycle)
  |
  |  GuardedReader.read_split(grant, ...) -> check_grant(): ledger re-verified at USE time ---------------> read_split(...)
```

Properties tested with synthetic registries in temp directories (`tests/test_evalinfra_access.py`, 36 tests): every individual failure denies and the reasons of *all* failed gates are reported
(no short-circuit); unregistered/unauthorized/revoked runner, wrong code hash, missing/NOT_AUTHORIZED/unsigned/tampered/expired/wrong-field authorization, revoked or expired authority key,
revoked authorization id, unavailable revocation list, replayed authorization, tampered replay log, missing ledger anchor, fabricated grant with no ledger entry, tampered ledger chain,
rolled-back ledger, unfrozen V2, missing/invalid vault configuration, missing reviewers/manifest, unregistered reviewer signature, REJECT disposition, too few reviewers, dual role,
signature verifier unavailable, missing/mismatched dataset commitment. With the repository's *real* committed registries the gate denies everything.

## 3. Failure-mode table (fail closed)

| Condition | Result |
|---|---|
| backend unconfigured | `PrivateStorageNotConfigured` on write and read |
| corpus id reused | refused (write-once) |
| one split missing / non-bytes | `PrivateStorageViolation` |
| wrong expected digest, edited split, missing or malformed SEAL | `PrivateStorageIntegrityError` |
| no grant / grant for another split or digest / grant absent from the ledger | `AccessDeniedError`, store never touched |
| any unexpected exception inside a gate | recorded as `<GATE>_ERROR:<type>` and denied |
| consumed-first ordering | the authorization use is recorded *before* the ledger append, so a crash burns a use rather than granting twice |

## 4. What must exist before this design carries real data (see `PRIVATE_EVAL_PREREQUISITES.md`)

A real private store location outside every git tree (or a private repo/object store with transport code, which does not exist), the vault private key held only by the verifier/runner
identity, a real corpus secret in a secret manager, registered reviewer keys, an AUTHORIZED runner record, and a signed authorization. None of these is created here.

## 5. Residual risks stated plainly

* The vault-configuration check inside the gate is presence/shape only; it cannot prove the store is actually private or that the three identities run in separate OS processes (the existing documents already say the same).
* `evaluate()` reads registries from the `root` it is given. Pointing it at a directory an attacker controls defeats it; the runner must pin the repository state (the existing `operational_boundary` does this for generation via git ancestry; this module does not).
* The ledger anchor is only as good as where it is published. Publishing it outside the runner's trust domain is an operational step not implemented here.
