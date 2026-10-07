# RSE-ARCH-1.1 — Part 2: roles, Crown protocol, Witness requirements, keys, grants

Sections G, H, I, J, K, Q, R, S, V. All `DESIGNED`. Resolves blockers B2, B5, B7, B10, B11.

## G. Sovereign-plane architecture

```
 daily-driver (untrusted) --proposal text only--> Crown (offline, owner tokens)
 Crown --signed grant bytes (removable medium)--> Forge | Witness
 Forge --encrypted+signed envelope (single-use medium)--> Witness
 every state change --> Ledger (log-first, witnessed checkpoints) <-- Monitor-Lite (secret-free, external)
 Reliquary (offline copies) <-- Crown/owner only
```

Components: **Crown, Forge, Witness, logical Vault** (an encrypted volume *inside* Witness, not a machine), **logical Evidence Ledger**, **offline Reliquary**, **external Monitor-Lite**. Qualification Chamber and Transfer Chamber are not machines in P1: the transfer chamber is the Witness two-phase ingestion procedure (§M); the Qualification Chamber is P2.

Complexity rule: every extra role must own a distinct trust root or capability boundary. Roles removed from 1.0: separate Vault machine, separate Transfer Chamber machine, Sentinel as cosigner.

## H. Crown (redesigned: daily-driver assumed fully compromised)

**What the daily-driver may do:** draft, propose, display untrusted information, hold unsigned proposals. **What it must never do:** obtain owner authorization silently, hold a token, or produce signing bytes that the owner does not see rendered from the exact signed bytes.

### Three views

1. **Producer view** — the proposer's own display. Untrusted, informational only.
2. **Crown signing view** — Crown renders the *canonical signing bytes* (§S) with its own renderer into a fixed-layout page and shows the digest of those exact bytes on an independent display (the token display or a second small device).
3. **Consumer view** — the consuming role (Forge or Witness) decodes the *actual received signed grant bytes*, renders them with its own renderer, and shows the same digest. The owner compares the Crown digest with the consumer digest before the consumer accepts (R14, below).

### Owner-verifiable fields (each appears in both renderings)

grant class; target role identity; operation; corpus/model identity (digest); exact code version (digest); environment identity (measurement or enrolled ID); resource, budget and run ceilings; output destination; expiry; incident epoch; nonce.

### Protocol (one grant)

1. Proposal arrives on a removable medium as **text**, with only proposer-supplied intent fields (no pre-rendered "approval" data).
2. Crown parses it with the canonical grammar; anything outside the grammar is refused.
3. Crown fills the binding fields itself (owner authority version, incident epoch, previous per-role checkpoint, nonce supplied by the consumer's challenge, creation time, expiry).
4. Crown renders the signing view; the owner checks fields and the displayed digest; the owner signs with DUAL_TOKEN_OWNER_CONFIRMATION where the class requires it (§terminology).
5. Crown writes the signed grant to a medium; no network is involved.
6. The consumer decodes the signed bytes, renders the consumer view, and shows the digest; the owner confirms on the consumer (R14). Only then can the grant become `ACTIVE` (§V).

**Terminology (B5).** The word "two-party" is retired. `DUAL_TOKEN_OWNER_CONFIRMATION` = one human using two separate hardware tokens, separated by time or action. It protects against a stolen token or a hijacked session. It is **not** two-person control, not multi-party governance, not an independent reviewer and not threshold human approval; none of those exist in a one-owner programme and none are claimed. A future independent human reviewer, if added, would be a separate named control.

### Consumer confirmation scope (R14) — avoiding approval fatigue

- **Explicit consumer confirmation required:** any irreversible phase change (first real corpus ingestion, K recovery/re-root, W export, D deployment, epoch change).
- **Bounded envelope grants (no per-step prompt):** internal operations inside an already-confirmed grant's declared ceilings (e.g., N generation batches within a signed count and size ceiling).
- **Never allowed:** an envelope grant that widens its own ceilings.

### Crown device roadmap

- **Minimum Crown before any real corpus:** a dedicated, offline, otherwise-unused environment with no agents, no sync, canonical renderer, hardware-backed owner keys, removable transfer only. It may share hardware with nothing that holds Forge or Witness duties at the same time (time-sharing on one machine is a recorded residual).
- **Before Qualification or training (P2):** an independently dedicated Crown device with: no agents; offline signing; hardware-backed owner keys; canonical renderer; independent digest display; removable transfer; minimal software stack; no Forge or Witness duties.

## I. Forge — plaintext exposure correction (B11)

**Forge sees plaintext and the generation secret.** Version 1.0's statement that Forge "cannot decrypt" referred only to the Witness *decryption private key*, which Forge never holds; that wording is retired. The exposure window is the whole generation interval.

Lifecycle: locked secret volume → phase gate → grant verified and confirmed → volume unlocked → plaintext generated in an ephemeral workspace (RAM-backed where possible) → **immediate** encryption to the Witness recipient → Forge role signature over the canonical envelope (§M) → evidence record → phase key destroyed → workspace wiped → power down. Between unlock and wipe Forge compromise yields plaintext; this is a declared residual (R-I1). Mitigations: short window, no network, bounded batch sizes, grant ceilings, wipe-and-attest procedure; none removes the exposure.

## J. Witness and the P1 requirements specification

The Witness verifies and decrypts accepted corpus material; it holds the decryption key, bound to its measured state. It is a *requirements* specification only; **no product, model or purchase** is selected.

Classes: **MANDATORY** (P1 cannot pass without it), **PREFERRED**, **OPTIONAL**, **DISQUALIFYING_IF_ABSENT**.

| # | Requirement | Class | Property it creates |
|---|---|---|---|
| 1 | Dedicated machine, used for nothing else | MANDATORY | removes shared-hardware persistence from Forge/Crown (closes U1 for Witness) |
| 2 | TPM 2.0 | DISQUALIFYING_IF_ABSENT | key release bound to measured state |
| 3 | UEFI Secure Boot with owner-enrolled keys (vendor/OEM keys removed) | MANDATORY | only owner-signed boot chain runs |
| 4 | Measured boot into PCRs | MANDATORY | boot state is evidenced |
| 5 | TPM quote support and a way to verify it offline | MANDATORY | identity/state evidence for Crown |
| 6 | PCR policy for key release (PCR 7 and the image PCR) | MANDATORY | unlock fails after any chain change |
| 7 | NV counters, if rollback counters are used | PREFERRED | HARDWARE_MONOTONIC reference (§W) |
| 8 | Linux (owner-built, signed unified kernel image) | MANDATORY | auditable minimal OS |
| 9 | LUKS2 for secret volume | MANDATORY | data at rest |
| 10 | TPM-bound key release | MANDATORY | key not recoverable off-machine |
| 11 | PIN (Argon2id-hardened) as second factor | MANDATORY | resists TPM bus sniffing and stolen-machine boot |
| 12 | Offline recovery passphrase, paper | MANDATORY | recovery without silent trust downgrade |
| 13 | IOMMU enabled | PREFERRED | limits DMA attacks via ports |
| 14 | Radios absent, physically removable, or hardware-disableable | MANDATORY | no wireless path; software-disable alone is insufficient |
| 15 | Network boot disabled | MANDATORY | no remote boot path |
| 16 | Wired-port treatment: no cable in secret phases; port disableable or physically blocked | MANDATORY | no network path |
| 17 | USB default-deny with an allow-list for the single transfer medium class | MANDATORY | limits USB attack surface |
| 18 | Firmware and OS updates only offline, from the owner-signed artifact repository | MANDATORY | no network updater |
| 19 | Approved artifact repository exists (§X) | MANDATORY | provenance for code |
| 20 | Physical custody in a controlled location | MANDATORY | thief/evil-maid bound |
| 21 | Tamper evidence (seals, photographed baseline) | PREFERRED | detects casual physical access |
| 22 | Adequate RAM/storage/CPU for verification and decryption of the largest planned bundle | MANDATORY | operational capacity |
| 23 | No GPU requirement | MANDATORY | Witness stays small |
| 24 | Discrete TPM vs firmware TPM | OPTIONAL | discrete exposes the bus; firmware TPM shares CPU trust; neither is claimed immune; PIN required either way |

The acceptance tests that prove these are listed in `RSE11_05` §AG.

## K. Vault (logical)

A LUKS2 volume on the Witness holding the accepted corpus and keys, unlocked only in a verified Witness state under an active grant. It is not a separate machine because it would add no independent trust root.

## Q. Hardware-rooted identity and attestation

- **Witness:** TPM quote over PCR 7 and the image PCR with a Crown-chosen challenge; Crown verifies offline against the enrolled attestation public key recorded at provisioning (TOFU-at-ceremony, then pinned).
- **Crown/Forge on Mac:** *no owner-verifiable measured boot found.* Their identity is an enrolled ID plus human procedure; labelled `SELF_ATTESTED` and never counted as attestation.

## R. Key hierarchy (design names only; no key exists)

| Key | Purpose | Holder |
|---|---|---|
| K-root | owner authority root, signs authority versions | offline token + paper backup (Reliquary) |
| K-class-G/V/K/(Q,T,W,D) | class grant signing | two separate tokens per sensitive class |
| K-forge-role | Forge role signature over envelopes | Forge secret volume |
| K-witness-recv | Witness recipient decryption key | Witness TPM-sealed volume |
| K-boot | owner Secure Boot signing key | offline |
| K-ledger-checkpoint | ledger checkpoint signing | role-local per role |
| K-ledger-owner | offline owner checkpoint cosignature | owner token |

Phase keys are ephemeral and destroyed per run. Rotation and compromise handling in §AA/§P.

## S. Short-lived grant model

### Canonical serialization

Grants use the fixed binary grammar of §M (OCR-style: fixed field order, fixed widths, length-prefixed bounded byte strings, no optional fields, no JSON signing). The signature is over `domain-prefix || canonical bytes`; domain prefixes differ per class so a signature for one class cannot be replayed in another.

### Common bindings (all classes)

grant version, grant ID, grant class, owner authority version, incident epoch, role identity, environment measurement, code SHA, policy version, bundle/corpus/model digest, operation, nonce/challenge, creation time, expiry, resource/spend/run ceilings, output destination, previous per-role evidence checkpoint, required evidence outputs.

### Per-class schemas (class-specific additions)

| Class | Purpose | Class-specific bindings |
|---|---|---|
| **G** corpus generation | Forge generates a batch | corpus label, batch count/size ceiling, recipient key ID, source-material digest list |
| **V** Witness verification | Witness verifies and accepts a bundle | bundle digest, sender ID, artifact ID, sequence range |
| **K** recovery / re-root / trust reset | recovery operation | recovery scenario ID, new authority version, checkpoint root, revoked roles |
| **Q** (future) Qualification | run Qualification on a candidate | candidate model digest, chamber measurement, run and bit budgets |
| **T** (future) training | training run | accepted corpus digest, foundation model digest, spend/run ceilings, provider environment measurement |
| **W** (future) weights export | **export only** | exact accepted model digest, Qualification acceptance record digest, source, destination, format, size ceiling, encryption recipient, expiry, epoch |
| **D** (future) deployment/release | public-release gate | exact model digest, serving environment measurement, policy digest, tool permissions, data-access scope, resource/spend ceilings, revocation endpoint, release version |
| **R** (consider) retirement | revoke/retire a model or corpus | object digest, revocation reason code |

Hard rules: **training completion never implies W; W never implies D.** Each is a separate grant under separate owner confirmation.

## V. Grant state machine and role lifecycle

States and exact transitions:

| From → To | Condition (all required) |
|---|---|
| (none) → PROPOSED | proposal decodes in canonical grammar |
| PROPOSED → OWNER_VERIFIED | Crown rendering shown; owner verified fields and digest |
| OWNER_VERIFIED → SIGNED | required tokens signed (class threshold + time separation met) |
| SIGNED → CHECKPOINTED | the **authorization record is durably included in a ledger checkpoint that a witness cosigned** (log-first) |
| CHECKPOINTED → DELIVERED | signed bytes plus inclusion proof reach the consumer role |
| DELIVERED → CONSUMER_CONFIRMED | consumer decoded the actual bytes, rendered them, checked signature, epoch, nonce, role, measurement, expiry, previous checkpoint; owner confirmed digest where §H requires |
| CONSUMER_CONFIRMED → ACTIVE | consumer wrote and checkpointed a consumption-start record **and** the per-role head matches (§N) |
| ACTIVE → CONSUMED | operation done within ceilings |
| CONSUMED → EVIDENCE_PENDING | result records produced |
| EVIDENCE_PENDING → COMPLETE | result record checkpointed and witnessed |
| any pre-CONSUMED → EXPIRED | clock past expiry (Monitor-Lite time observation plus role-local clock; skew ruling in §N) |
| any → REVOKED | epoch raised or explicit revocation record checkpointed |
| any → QUARANTINED | inconsistency (fork, head mismatch, bad proof) |

**A valid signature alone never makes a grant ACTIVE.** Role lifecycle states: UNPROVISIONED → PROVISIONED → ATTESTED → ARMED → ACTIVE_GRANT → SEALED/WIPED → (QUARANTINED | RETIRED); a role in QUARANTINED accepts no grants until a class-K grant clears it.
