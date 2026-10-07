# RSE-ARCH-1.1 — Part 3: transfer, evidence ledger, Monitor-Lite, storage, anti-rollback

Sections M, N, O, U, W. All `DESIGNED`; the canonical-format evidence is from a scratch prototype outside the repository. Resolves blockers B3, B4, B6, B8.

## M. Transfer Chamber: canonical envelope and two-phase ingestion

### Why 1.0 was defective (B6)

The existing tools parse the same bytes with two different parsers: a strict manifest hook that rejects duplicate keys, and a lenient header parser. The encrypted-store reader parses a JSON header with the key present before authentication, with an unbounded header length. A scratch differential run confirmed that JSON parsers disagree: for `{"a":1,"a":2,"n":NaN}` Python accepts NaN and takes the last duplicate, Node rejects NaN. Encryption to a public key also authenticates no sender. So: **no JSON in any signed or security-parsed position.**

### OCR1 envelope (one fixed grammar)

All integers big-endian. No optional fields, no compression, no extension area.

| Offset | Field | Size |
|---|---|---|
| 0 | magic `OCR1` | 4 |
| 4 | version (must be 1) | 1 |
| 5 | type (1 corpus bundle, 2 evidence, 3 grant) | 1 |
| 6 | flags (must be 0) | 1 |
| 7 | reserved (must be 0) | 1 |
| 8 | recipient role ID | 32 |
| 40 | sender role ID | 32 |
| 72 | bundle digest | 32 |
| 104 | grant ID | 16 |
| 120 | artifact ID | 16 |
| 136 | sequence | 8 |
| 144 | incident epoch | 4 |
| 148 | expiry | 8 |
| 156 | ciphertext length *n* (≤ 2^24 per frame; larger payloads are multiple frames) | 4 |
| 160 | ciphertext (AEAD, associated data = bytes 0–159) | *n* |
| 160+n | Ed25519 signature by the sender role key over `domain || bytes 0..160+n` | 64 |

Total length must equal exactly `160 + n + 64`. The parser rejects: wrong magic/version/type/flags/reserved, length mismatch, `n` over the ceiling, trailing bytes. **Parse then re-encode must reproduce the exact input bytes**; otherwise reject. Format choice reason: fixed offsets allow independent implementations of about thirty lines with no object model; fashion formats were not considered because none has a smaller or less ambiguous grammar.

Scratch evidence (not product code): independent Python and JavaScript decoders agreed on 20,000 mutated inputs (bit flips, byte replacement, truncation, trailing bytes), 0 disagreements, 9,276 accepted structurally. This is *structure only*; signature and AEAD verification were not exercised, so it is evidence for grammar determinism, not for the verifier.

### Sender authentication

Forge signs the canonical envelope with its role key. Encryption alone does not prove origin. The Witness checks: recipient = self; sender = enrolled Forge ID; bundle digest matches decrypted content; grant ID matches an ACTIVE/CONSUMER_CONFIRMED grant; sequence = expected next; epoch current; expiry; signature; AEAD tag.

### Two-phase key-absent ingestion

- **Phase 1 (secret volume locked, key absent):** read the medium, bounded copy to a quarantine area, check only fixed framing and length, compute digest, detach the medium. Reboot to baseline if the medium was ever mounted or enumerated beyond the raw device. A reboot defends against USB and kernel-level exploitation; it does **not** defend against decoder bugs, which is why Phase 2 is minimal.
- **Phase 2 (key present):** a **minimal verifier** (minimal dependencies, bounded memory, no compression, no dynamic object graph, no lenient parser) verifies signature, grant, sequence, epoch, expiry and AEAD. A second, independently written implementation exists **for acceptance testing only**, not as a production cross-check.

### Plaintext handoff

Decryptor → bounded pipe → sandboxed checker. The checker has no key, no network, a controlled temporary workspace, strict CPU/memory/output bounds, and a defined output set (verdict plus bounded counts). Nothing else leaves the sandbox.

## N. Evidence Ledger (B3)

### Why a local hash chain is not enough

An administrator of the machine holding the chain can truncate or rewrite it. The existing `AccessLedger` documents this itself. 1.1 therefore trusts **independently held checkpoints**, not the local chain.

### Architecture (ADAPTED from C2SP tlog-checkpoint/tlog-witness)

- Each role keeps an append-only Merkle log of its records.
- A **signed checkpoint** (size, root hash, role ID, epoch) is produced by the role.
- A **witness** cosigns a checkpoint only after verifying a consistency proof from the last checkpoint it saw (it never accepts a smaller or forked tree).
- **Log-first rule:** nothing is authorized until its authorization record is durably included in a witnessed checkpoint; results likewise. A role refuses to act on a grant whose inclusion proof it cannot verify.
- **Per-role head binding:** each grant carries the previous per-role checkpoint; at most **one outstanding state-changing grant per role**. Classification: ADAPTED (compare-and-swap on a log head, as in git push certificates). It survives audit only with the one-outstanding-grant rule; without it two concurrent grants fork the binding.

### Independent checkpoint holders

| Holder | Where | Catches | Common-mode risk |
|---|---|---|---|
| Role-local | the role itself | nothing alone | same compromise as the role |
| Cross-role | the other roles hold each other's latest cosigned checkpoint | rewrite of one role | a compromise of both roles |
| Offline owner | paper/token-signed periodic checkpoint root | whole-system rewrite after the card date | owner loss of the card |
| External Monitor-Lite | secret-free external service/device | truncation and tail suppression visible to the world | owner administers it too (one human) |

**Residual (R-N1):** one human administers every holder; a compromise of *all* holders plus the administrator is outside the model. **R-N2:** tail suppression between two checkpoints is possible; the exposure window is the checkpoint interval and is bounded by the grant lifetime (grants cannot outlive a checkpoint).

## O. Sentinel → Monitor-Lite (B8)

Dropped: ceremonial cosigning of every grant (a cool-off an offline owner cannot be forced to honour is not enforcement). Kept: **external time observation**, **checkpoint witnessing**, **repository/anchor inconsistency alerts**, later possibly provider-budget monitoring. Always **secret-free**: it holds no decryption key, no signing authority over grants, and no corpus. Independence limit: same owner; stated, not overstated.

## U. Storage and plaintext lifecycle

Strength labels: **STRONG** (cryptographic or hardware-enforced), **BEST_EFFORT**, **IMPOSSIBLE**.

| Channel | Treatment | Strength |
|---|---|---|
| Persistent storage | secret data only on LUKS2 (Witness) / encrypted APFS volume (Forge) | STRONG at rest |
| RAM | plaintext only here; no remanence claim | BEST_EFFORT |
| Swap / hibernation | disabled on roles; encrypted if unavoidable | BEST_EFFORT |
| Crash dumps / core dumps | disabled; verified absent | BEST_EFFORT |
| Temp files | RAM-backed workspace | BEST_EFFORT |
| APFS snapshots / Time Machine / Spotlight (Mac) | excluded/disabled and inspected before and after | BEST_EFFORT (procedural) |
| Linux temp/swap | tmpfs, swap off | STRONG if verified |
| Logs | no plaintext content, metadata only | BEST_EFFORT |
| Clipboard | not used in secret phases | PROCEDURAL |
| Backups | secrets excluded; Reliquary holds encrypted copies only | STRONG if encrypted |
| SSD wear-leveling | physical remanence possible; **no physical deletion is promised** | IMPOSSIBLE |
| Cryptographic erasure | destroy the key; data becomes unreadable if the cipher holds | STRONG |

## W. Anti-rollback (honest rewrite, B4)

One monotonic reference per mutable object. Classes: CRYPTOGRAPHIC (signature plus version rule), HARDWARE_MONOTONIC (TPM NV counter), EXTERNAL_CHECKPOINT (witnessed log), OWNER_PROCEDURAL, UNSOLVED.

| Object | Reference | Class (P1 Witness) | Class (P0 Mac / Crown / Forge) |
|---|---|---|---|
| Witness OS image | signed version ≥ minimum in policy | CRYPTOGRAPHIC + HARDWARE_MONOTONIC if NV counter used | — |
| Witness role code | version in signed manifest | CRYPTOGRAPHIC | OWNER_PROCEDURAL |
| Manifest / policy | monotonically increasing version in owner authority | CRYPTOGRAPHIC | CRYPTOGRAPHIC |
| Trust-root key version | owner authority version | CRYPTOGRAPHIC | CRYPTOGRAPHIC |
| Corpus version / model version | recorded in checkpointed log | EXTERNAL_CHECKPOINT | EXTERNAL_CHECKPOINT |
| Ledger checkpoint | cosigned checkpoint size | EXTERNAL_CHECKPOINT | EXTERNAL_CHECKPOINT |
| Incident epoch | in every grant; roles reject lower | CRYPTOGRAPHIC (needs the role to know the epoch) | OWNER_PROCEDURAL |
| Revocation state | checkpointed revocation records | EXTERNAL_CHECKPOINT | EXTERNAL_CHECKPOINT |
| Grant nonce | consumer-issued challenge + consumption record | EXTERNAL_CHECKPOINT | EXTERNAL_CHECKPOINT |
| **Mac OS state (P0)** | none exists | **UNSOLVED** | **UNSOLVED** (a restored older disk image looks valid to the Mac) |

### TPM NV counter / monotonic-version mechanism (designed, not implemented)

- Define an NV index of counter type; seal the Witness data key under a policy that requires the counter to equal N (`tpm2_policynv` comparison). To advance: boot the new signed image, increment, re-seal under N+1. Old images then cannot unseal the key (rollback → key denied).
- Constraints that must be designed in: NV wear (frequent increments are forbidden; counters advance only on owner-approved version changes); TPM clear destroys the index (recovery = re-root of that role, not silent re-enrolment); lockout from wrong PINs (PIN policy and recovery passphrase); firmware replacement can change measured state (re-seal ceremony under an owner grant); **motherboard replacement** loses TPM state (disaster-recovery path in §AB: rebuild Witness, new keys, corpus re-verified).
- Not verified: exact counter attributes on the chosen hardware (page text did not confirm them); labelled `UNVERIFIED_ON_HARDWARE`.
