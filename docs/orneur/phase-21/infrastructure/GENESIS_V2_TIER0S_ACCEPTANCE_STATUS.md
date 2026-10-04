# Genesis V2 — Tier0-S acceptance status (separate from the Tier0-A / Tier0-B table)

Statuses: `PROVEN_SYNTHETIC_ONLY` · `PARTIAL` · `NOT_YET_PROVEN` · `OWNER_ACTION_REQUIRED` · `UNACCEPTABLE`. **`PROVEN_REAL` is not used in this design phase.** No second boot environment exists, so nothing that needs one is claimed. Decision gate: `TIER0_S_REDUCED_ASSURANCE_ONLY`.

## A. Synthetic validation checks
| # | Check | Status | Basis |
|---|---|---|---|
| 1 | Forge environment holds only public key + synthetic generation secret | `PARTIAL` | Gate fully enumerates the role's own state directory (any unreadable subtree, symlink or special file is `FAIL_CLOSED`) by file name and first-256-byte key header — WEAK evidence; per-container evidence exists only for the (different) Tier0-B topology. No Tier0-S environment exists. |
| 2 | Witness environment holds only the private key | `PARTIAL` | Same. |
| 3 | Forge cannot decrypt | `PROVEN_SYNTHETIC_ONLY` | Topology-independent cryptographic property (writer holds no private key); existing store/Tier-0 tests. |
| 4 | Witness decrypts | `PROVEN_SYNTHETIC_ONLY` | Existing store and Tier-0 tests; `cryptographic_verify` with an ephemeral key. |
| 5 | Wrong key fails | `PROVEN_SYNTHETIC_ONLY` | Same. |
| 6 | Transfer format validator accepts a valid bundle | `PROVEN_SYNTHETIC_ONLY` | Establishes only `EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED` (shape). `tests/test_genesis_v2_tier0a_transfer_bundle.py`. |
| 7 | Plaintext in place of an encrypted artifact is rejected at the format level; plaintext payload behind a valid header is rejected only by Witness-side `cryptographic_verify` | `PROVEN_SYNTHETIC_ONLY` | Keyless validation cannot detect a plaintext payload behind a valid header (tested limit); the keyed AEAD check does (tested). |
| 8 | Extra / secret-shaped / symlinked / hardlinked / duplicate-key / traversal entries are rejected | `PROVEN_SYNTHETIC_ONLY` | Same test file. |
| 9 | Forge cannot see Witness secret store in its phase (storage physically absent) | `NOT_YET_PROVEN` | Needs two real environments and the detachment procedure. |
| 10 | Witness cannot see Forge secret store in its phase (storage physically absent) | `NOT_YET_PROVEN` | Same. |
| 11 | Full shutdown/reboot required between phases | `NOT_YET_PROVEN` | Owner-controlled physical procedure. The software interlock is advisory, same-environment, forgeable by any writer, and earns no credit. |
| 12 | No shared container runtime / control plane survives between roles | `PARTIAL` | Gate detects known runtime processes, sockets, install dirs and env vars (not exhaustive; renamed binaries evade the process check); no cross-phase run exists. |
| 13 | No role secret in a common mounted filesystem | `NOT_YET_PROVEN` | Needs provisioned storage. |
| 14 | Network disabled independently per phase | `NOT_YET_PROVEN` | Gate checks interfaces (by address, structurally validated and cross-checked against `ifconfig -l`), default routes and TCP/UDP sockets once at phase start (v4 parsers: plausibility floors, no data after a blank line, terminated sections); not continuous; UDP absence and inability to communicate are not established; this host fails it; no per-phase run. |
| 15 | Qualification code excluded from the role environment | `PARTIAL` | Role code root must equal a hash-pinned manifest confined to a fixed role policy (byte-identical files, nothing else, no links/special files/bytecode); valid within that root only and only as good as the out-of-band pin; Tier-0 role images omit it; the full repository is rejected. |
| 16 | Owner private key absent from both | `PARTIAL` | Filename-pattern and first-256-byte key-header scan of the role's own state directory is WEAK evidence only (renamed, encoded or late-header keys are not detected); no real key exists. |
| 17 | No plaintext remains on transfer storage | `PARTIAL` | Format validator cannot see plaintext behind a valid header; erasure of real media not exercised. |
| 18 | No secret-shaped data in logs | `NOT_YET_PROVEN` | Requires an actual phase. |
| 19 | Teardown scoped | `PARTIAL` | Tier0-B scoped teardown only; none for Tier0-S. |
| 20 | Protected benchmark untouched | `PARTIAL` | An unchanged inventory/signature blob shows nothing was modified, not that nothing was read. (Main acceptance item 20 provenance is also `PARTIAL`.) |
| 21 | Persistence channels inspected | `PARTIAL` | Read-only inspection of this host + classification in the design doc; not a proof. |
| 22 | Surviving shared state documented | `PARTIAL` | Documented; unverified on provisioned environments. |

## B. Required invariants
| # | Invariant | Status | Basis |
|---|---|---|---|
| 1 | Forge and Witness never simultaneously running | `NOT_YET_PROVEN` | Owner-controlled cold-boot procedure; the software interlock is advisory only and earns no credit. |
| 2 | Forge cannot mount/decrypt Witness secret storage (it is physically absent) | `NOT_YET_PROVEN` | Needs separately encrypted environments and the detachment procedure. |
| 3 | Witness cannot mount/decrypt Forge secret storage (it is physically absent) | `NOT_YET_PROVEN` | Same. |
| 4 | No shared active container runtime across phases | `PARTIAL` | Gate check by process token, socket, install dir and env var (not exhaustive); this host fails it. |
| 5 | No shared active secret manager | `PARTIAL` | Design rule; unverified. |
| 6 | No automatic cloud-sync path between role secrets | `UNACCEPTABLE` | On the current daily-driver: synchronized locations hold data and agent stores exist. Acceptable only in a dedicated environment; process absence alone never satisfies it. |
| 7 | No owner private key in either environment | `PARTIAL` | None exists; the name/first-256-byte key-header scan is WEAK evidence only. |
| 8 | Ciphertext transfer explicit and auditable | `PARTIAL` | Validator output and staged-copy handoff; not exercised across boots. |
| 9 | Plaintext corpus never crosses environments | `PARTIAL` | The keyless validator checks expected-format shape only and cannot detect plaintext behind a valid header; the keyed Witness-side check can. Plaintext handling inside Forge is unproven. |
| 10 | Qualification unavailable | `PARTIAL` | Role code root equals a hash-pinned manifest within a fixed policy (within that root only; not provenance). |
| 11 | Both environments can run with networking disabled | `NOT_YET_PROVEN` | Needs the environments; the owner must keep networking off for the whole phase. |
| 12 | Secret storage separately encrypted | `OWNER_ACTION_REQUIRED` | Requires owner provisioning of dedicated encrypted storage. |
| 13 | Transition requires full shutdown/reboot | `NOT_YET_PROVEN` | Owner-controlled physical procedure; software log earns no credit. |
| 14 | Cross-environment persistence risk assessed | `PARTIAL` | Assessed; two channels `UNCONTROLLED` on the daily-driver; process vs exposure now distinguished. |
| 15 | No real secrets created | `PROVEN_SYNTHETIC_ONLY` | None created. |
| 16 | The other role's storage is physically disconnected/unavailable during a role phase (wherever the topology permits) | `OWNER_ACTION_REQUIRED` | Owner-controlled physical procedure (design §1 lifecycle). The gate only checks that named paths/volumes are absent at phase start. |

Summary: no check or invariant is `PROVEN_REAL`; one invariant is `UNACCEPTABLE` on the current daily-driver environment; Tier0-S is **not provisioned** and **not accepted**.

> **N1–N10 phase note.** The gate was hardened again (trusted home from the password database, absolute tool paths, descriptor-relative traversal, validated volume/disk/deny configuration, plausibility floors, serialized interlock appends; see `GENESIS_V2_TIER0S_N1_N10_REMEDIATION.md`). No check or invariant above changes status: none is `PROVEN_REAL`, Tier0-S is not provisioned, and the maximum conclusion is `READY_FOR_FINAL_INDEPENDENT_REAUDIT`.
