# Evidence trust boundary

Schema: `orneur-evidence-trust-boundary/1`

Status: `DOCUMENTED`

The local journal is a single-operator crash log on one host. It is not an authenticated multi-user store, and it is not a defense against a writer who can change every file in the journal directory.

## What the current process checks

`Journal` labels the caller with `actor_user_id` and stores `actor_authenticated: false`. `orca.core_runtime.principal.authenticate` raises `principal_not_authenticated` for every claim. That function is a refusal. It does not identify a person, verify a signature, or return a principal.

`seal_verified` ignores caller totals and input bytes. It recomputes the input file written by `bind_input`, checks the artifact schema, and requires a mission admission whose effect file is `committed` with outcome `local_receipt_only`. A planted effect file alone does not create that admission. A later edit of one saved file leaves the historical `completed_verified` record in place and reports a separate integrity code.

`flock` on the lock inode serializes writers on this host. The lock is opened from the root directory descriptor with `O_NOFOLLOW`. A symlink, a hard link, and a non-regular lock are refused. `flock` does not hold across hosts or against a process that can write the directory without taking the lock.

The directory must not be placed where another user can write it. The memory API does not grant access to a second user. `share_with` is a same-owner label.

## What a matching hash does not prove

The seal stores SHA-256 digests of the input and the artifact. Those digests match the bytes the journal read. If a writer can replace the mission record, the input file, the effect file, and the artifact together, the digests still match the attacker's bytes. Ordinary hashes do not detect that writer. The same limit is stated for the training gate in `orca/train/authorization.py`: code running as the operator can edit the files the gate reads.

## How a later authenticated check would attach

No such check is active.

- Authentication has to come from a signature verified by the existing authorization code, `orca.train.authorization.verify_signature` or `orca.genesis.governance.authorization.verify_signature`, against a registry that currently has no keys. `principal.authenticate` stays a refusal until that verifier returns a key-bound identity. A caller string is not that identity.
- Authorization for a mission effect has to be a separate decision from that identity. It must not flip `training_authorized()` or `spending_authorized()` in `orca.rse.imp1.locks`. Both return false. Native pretraining stays on `authorize_native_pretraining`, whose committed record is `NOT_AUTHORIZED`.
- Evidence integrity beyond this host has to be a signature over the seal by a key the journal directory does not contain. Until that signature exists, the seal is a single-host consistency check among files in one directory.

The Postgres mission store, `orca.mission.mission_store`, is a different store. This journal does not replace it and does not export its directory to that store.
