# Genesis Capability Eval V2 — Process-Isolation Verification Procedure (OWNER ACTION, not a unit test)

`operational_boundary.verify_manifest_digest_only_same_process()`'s own docstring states plainly that it provides
NO operating-system process isolation — it runs in the same Python process/thread as its caller. Genuine process
isolation between the generator and the creation-time verifier is a DEPLOYMENT fact, not something any test in this
repository can establish. This document is the concrete procedure for the owner to verify that fact on the REAL
deployment, once one exists. **Nothing below has been run. This is a procedure, not a result.**

## What "isolated" means here, precisely

Two things must both be true:
1. **Key isolation** (already proven at the code level, see `tests/test_genesis_v2_identity_credential_boundaries.py`): the generator's process never has the private key in its own memory/environment, structurally.
2. **Process/host isolation** (NOT provable by this repository's code — the subject of this procedure): the generator and the creation-time verifier run as genuinely separate OS processes, ideally on separate machines or in separate containers/VMs with separate credential grants, so that a compromise of one does not trivially give an attacker code-execution access to the other's memory, filesystem, or credential store.

## Verification steps (run by the owner, on the real deployment)

### 1. Confirm separate execution contexts exist
- **Two machines (A1 default):** confirm via `hostname`, `uname -a`, or equivalent that the generator and verifier commands were actually run on two different physical/virtual hosts, not the same host under two user accounts pretending to be separate (a genuinely separate host is stronger isolation than a shared-kernel user-account split).
- **Two OS user accounts on one machine (weaker A1 variant):** confirm via `id`/`whoami` that the two roles run under different, unprivileged OS accounts, and that neither account's process can read the other's home directory or Keychain (`ls -la` on the other user's home directory should fail with a permission error).
- **Two containers/CI jobs (A2, if later chosen):** confirm via the orchestrator's own job/container IDs that the generator and verifier steps ran in genuinely separate containers, not merely separate steps of the same job sharing one filesystem.

### 2. Confirm the credential grant, not just the credential
For whichever execution context applies: read the ACTUAL secret-manager grant (Keychain ACL, GitHub Environment's configured secrets, cloud IAM policy — whichever applies) for the generator's identity and confirm it does NOT include `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY`, independent of what the generator's own code happens to read. A broader grant that HAPPENS to never be read by the current code is still a real exposure if the code changes later.

### 3. Confirm no shared writable filesystem path
Confirm the generator's working directory / temp directory is not the same filesystem location the verifier reads from with elevated trust, and that neither process can write into a path the other treats as already-verified (e.g. the vault directory itself should be write-accessible to the generator only for its OWN new corpus writes, never for modifying existing sealed corpora — enforced today by `EncryptedVaultWriter`'s write-once semantics, but worth confirming at the filesystem-permission level too: `ls -la` on the vault directory from the verifier's account should show it cannot write into corpus subdirectories it did not create).

### 4. Confirm the run-record trail
For a real activation, keep a record (outside this repository, per the "no secrets in git" rule) of: which host/container ran the generator, which host/container ran the verifier, and the timestamp of each. This is the artifact an independent auditor would ask for to confirm isolation was real at the time content was created, not merely designed to be real.

### 5. Repeat after any deployment change
Any change to where the generator or verifier runs (new machine, new CI runner image, new container base) invalidates a prior confirmation. This procedure is not a one-time certification; it is a check to repeat whenever the deployment topology changes.

## What this procedure does NOT establish

It does not (and cannot) prove that a genuinely determined attacker with root on the generator's host could never, through some means, read verifier-side data — that is the same limit any process/host isolation boundary has. It establishes that the OBVIOUS, structural failure modes (shared credential grant, shared filesystem, shared OS account, running both roles in the literal same process) are absent, which is the practical bar this program's design has always aimed for, consistent with `operational_boundary.py`'s own honestly-documented residual limitations.
