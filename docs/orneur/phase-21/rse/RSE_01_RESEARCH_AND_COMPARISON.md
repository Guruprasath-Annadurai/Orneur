# RSE-01 — Research, comparison matrix and novelty classification

Research date 2026-10-07. Method and limits are in `RSE_00_INDEX_AND_STATUS.md`. "Primary" means the vendor's or standards body's own page was read; "secondary" means a third-party summary.

## 1. Sources and what each established

| ID | Source (primary unless stated) | URL | Version / date seen | What it established that this design uses |
|---|---|---|---|---|
| S1 | Apple, *Private Cloud Compute: A new frontier for AI privacy in the cloud* | security.apple.com/blog/private-cloud-compute/ | 2024 post, read 2026-10-07 | Five requirements: stateless computation, enforceable guarantees, no privileged runtime access, non-targetability, verifiable transparency. A client wraps its request key only to nodes whose attested measurements match a release in a public transparency log; every production image is published for inspection. |
| S1b | Apple, *Expanding Private Cloud Compute* | security.apple.com/blog/expanding-pcc/ | 8 June 2026 | PCC extended to Google Cloud with NVIDIA GPUs. Apple does not rely on confidential computing alone; every component from firmware to application is in the trusted computing base. An append-only, verifiable ledger of fleet hardware. For components that could exfiltrate data, attestation is rooted in at least two separate roots of trust from independent vendors. |
| S2 | Apple Platform Security Guide (Secure Enclave; Startup Disk security policy; boot process) | support.apple.com/guide/security/ | read 2026-10-07 | Secure Enclave with its own boot ROM and encrypted memory; OS-bound keys derived from the device UID and the hash of the running sepOS; a Boot Monitor that keeps a running hash of the boot. The LocalPolicy (Full, Reduced, Permissive) is signed locally by a Secure Enclave key and carries an anti-replay value, so an old weaker policy cannot be replayed. Booting from external media first requires personalizing that OS through an authenticated restart from recoveryOS, which creates a LocalPolicy file **on the internal drive**. |
| S3 | Apple, Managed Device Attestation | support.apple.com/guide/deployment/managed-device-attestation-dep28afbde6a/web | read 2026-10-07 | A Mac can hold Secure Enclave-bound keys; attestation of device properties (serial, sepOS version, a freshness code) is delivered through a device-management service or an ACME certificate authority; a fresh attestation is limited to one per device per seven days. It attests device properties, not the integrity of role software, and needs management infrastructure. |
| S4 | NVIDIA, Hopper H100 confidential computing blog and whitepaper | developer.nvidia.com/blog/confidential-computing-on-h100-gpus-for-secure-and-trustworthy-ai/ | read 2026-10-07 | GPU attestation validated through NVIDIA Remote Attestation Service; relying party supplies a random nonce of at least 128 bits; device certificates checked for revocation (OCSP). |
| S5 | AWS KMS condition keys for Nitro Enclaves and NitroTPM | docs.aws.amazon.com/kms/latest/developerguide/conditions-nitro-enclave.html | pages dated Sept 2025 | A KMS key policy can allow Decrypt only when the signed attestation document in the request carries matching PCR or image-hash values; with no attestation document, permission is denied. |
| S6 | Microsoft, Secure Key Release with Azure Key Vault / Managed HSM and the trusted-launch pattern | learn.microsoft.com/azure/confidential-computing/concept-skr-attestation | read 2026-10-07 | An exportable HSM-backed key carries a release policy over attestation-service claims. The publisher keeps the trust anchors (vault and attestation provider) in its own tenant, outside the consumer's RBAC. |
| S7 | Google Cloud, Confidential Space security overview | docs.cloud.google.com/docs/security/confidential-space | read 2026-10-07 | Attestation detects modification of the workload image or VM; a hardened image blocks operator access after attestation; attestation tokens feed workload-identity federation so a protected resource releases only to an attested workload. |
| S8 | IETF RFC 9334, RATS architecture | rfc-editor.org/rfc/rfc9334.html | Jan 2023 | Roles Attester, Verifier, Relying Party, Endorser, Reference Value Provider. Claims must be collected so the target cannot lie to the attesting environment; evidence must be bound to its environment. Freshness by timestamps, nonces or epoch IDs. |
| S9 | Anthropic, *Activating AI Safety Level 3 protections* and the ASL-3 report | anthropic.com/news/activating-asl3-protections | 22 May 2025 | More than 100 controls: two-party authorization for model-weight access (permission limited in time and timing out automatically), change management, binary allowlisting, and egress bandwidth controls, described as the control "more unique" to protecting weights. Scope: sophisticated non-state actors; nation-state attackers (beyond non-novel chains) and sophisticated insiders are out of scope. |
| S10 | RAND, *Securing AI Model Weights* and the playbook brief | rand.org/pubs/research_briefs/RBA2849-1.html | brief and PDF excerpts only (full page HTTP 403) | Five security levels. SL3 targets insiders and supply chain; SL4 adds comprehensive hardening and confidential computing for weights in use; SL5 means weights held in a disconnected setup with stringent transfer policies, and the brief says SL5 is currently not achievable for production serving. |
| S11 | Google DeepMind, Frontier Safety Framework v2 blog | deepmind.google/blog/updating-the-frontier-safety-framework/ | excerpts | Recommends a security level for each critical capability level, drawing on RAND. |
| S12 | OpenAI, "Reimagining secure infrastructure for advanced AI" | (primary page not retrievable) | **secondary only** (the-decoder.com, maginative.com, analyticsvidhya.com) | Six measures: trusted computing for accelerators (GPUs cryptographically verifiable, weights encrypted until loaded), network and tenant isolation including offline operation, data-center and physical security, AI-specific audit, AI for cyber defense, resilience. Treat as unverified against the primary text. |
| S13 | Qubes OS architecture | doc.qubes-os.org/en/latest/developer/system/architecture.html | 4.3.1 | Security by compartmentalization: components and applications run in lightweight VMs so that compromise of one does not affect the integrity of the rest. |
| S14 | The Update Framework specification | theupdateframework.github.io/specification/latest/ | v1.0.36, 5 Aug 2026 | Roles root, targets, snapshot, timestamp; offline root keys; thresholds so that compromising fewer than a threshold of keys does not compromise clients; rollback, fast-forward, freeze and mix-and-match protections via versioned, expiring metadata. It states that if a threshold of root keys is compromised, assume attackers have taken over the machines, and recovery is nearly impossible. |
| S15 | SLSA v1.2 and in-toto attestations | slsa.dev/spec/v1.2/build-provenance | v1.2 | Build provenance as in-toto statements; the builder identity determines the level; externally supplied build parameters are untrusted and must be verified downstream. |
| S16 | Sigstore Rekor; transparency.dev | docs.sigstore.dev/logging/overview/ | read 2026-10-07 | An append-only, verifiable log; auditors check consistency; separate witness software can audit the log. |
| S17 | IETF RFC 9591, FROST | rfc-editor.org/rfc/rfc9591.html | June 2024 | Two-round threshold Schnorr signatures; a ciphersuite yields Ed25519-compliant signatures; the dealer-based variant trusts the dealer; nonce reuse allows key recovery. |
| S18 | systemd-cryptenroll and systemd-stub | freedesktop.org/software/systemd/man/latest/systemd-cryptenroll.html | systemd 262 | A LUKS2 volume can be bound to TPM2 PCR values (for example Secure Boot policy and the kernel image); an added PIN, hardened with Argon2id, makes the TPM a second factor so a compromised TPM alone does not expose the key; failed PINs increment the TPM lockout counter. |
| S19 | Yubico YubiKey technical manual and PIV documentation | docs.yubico.com/hardware/yubikey/yk-tech-manual/yk5-firmware-5.7.html | search results | Firmware 5.7 and later add Ed25519 and X25519 key generation; PIV keys generated on the device are not exportable; an attestation certificate can show a key was generated on the device. Ed25519 PIV attestation specifically was **not** verified. |

## 2. Comparison matrix (what the comparable systems do, what ORNEUR profiles can do)

Cells state what is documented for the comparator. "—" means not documented in the sources read.

| System | Root of trust | Environment measurement / attestation | Key or authority bound to measured state | Multi-party / threshold | Transparency / evidence | Exfiltration control | Compromise recovery | Adversary assumed |
|---|---|---|---|---|---|---|---|---|
| Apple PCC (S1, S1b) | Apple silicon and, for third-party data centers, additionally an independent vendor root | node attests measurements; public log of releases | client wraps keys only to nodes matching the log | — | public transparency log; append-only hardware ledger | stateless, no privileged access | — | operator and Apple staff |
| NVIDIA H100 CC + NRAS (S4) | device-unique key and NVIDIA certificates | GPU attestation report with nonce | via relying party policy | — | — | encrypted CPU-GPU channel | certificate revocation (OCSP) | host/hypervisor operator |
| AWS Nitro + KMS (S5) | Nitro hypervisor and AWS | signed attestation document, PCRs | KMS key policy conditions on PCRs | IAM roles | CloudTrail records attestation values | — | key policy change | cloud operator, tenant admin |
| Azure SKR (S6) | Azure attestation service | MAA claims, vTPM PCRs | key release policy | RBAC | — | — | policy change | consumer-tenant admin |
| Google Confidential Space (S7) | Google attestation | image and VM attestation | workload identity federation | multiple data owners | — | hardened image, no operator access | — | untrusted workload operator |
| Anthropic ASL-3 (S9, as disclosed) | — | binary allowlisting | — | two-party, time-limited authorization | — | egress bandwidth limits | — | sophisticated non-state actors; excludes nation-state and sophisticated insiders |
| RAND SL3 to SL5 (S10) | — | — | confidential computing at SL4 | reduced access sets | — | SL5 isolated, strict transfer policy | — | up to state actors (SL5) |
| Qubes (S13) | Xen and dom0 | — | — | — | — | compartment boundaries | rebuild disposable VMs | compromised applications |
| TUF, SLSA, in-toto, Rekor (S14–S16) | offline root keys | provenance statements | thresholds on metadata | thresholds | append-only log with witnesses | — | key rotation, threshold | compromise of fewer than a threshold of keys |
| TPM2 sealing (S18) | TPM and UEFI Secure Boot | PCR measurements | PCR-bound disk unlock, optional PIN | — | — | — | recovery key | offline disk theft, boot tampering |
| **ORNEUR P1** (design, `RSE_02`) | owner tokens + Apple root (Forge, Crown) + TPM root (Witness) + owner-held pin | TPM-sealed unlock for the Witness; self-reported manifest and gate result elsewhere | owner-signed, challenge-bound grants; TPM sealing on the Witness | token thresholds, time-separated, external cosigner | two-sided, externally anchored ledger | bounded evidence-only return path | epoch revocation, taint lineage, rebuild kit | accidental exposure, compromised role or host, stolen media |
| **ORNEUR P0** (design, `RSE_02`) | owner tokens + one Apple root + owner-held pin | self-reported only | owner-signed, challenge-bound grants | same | same | same | same | same, with common-mode on one machine |

## 3. What the research does not show

- None of the sources shows a single-owner, offline, token-rooted design. They protect cloud workloads from operators, or weights at organization scale.
- No source demonstrates owner-verifiable measured boot on Apple silicon. S2 shows the Secure Enclave measures its own boot and binds some keys to it; S3 shows remote attestation of device properties needs management infrastructure. Neither exposes a local, owner-verifiable quote of an arbitrary external boot environment. This was not proven impossible, only not found.
- S5 and S6 bind key release to measurements in the cloud; S18 shows the same idea locally with a TPM. That local form is what ORNEUR P1 uses for the Witness.

## 4. Established design facts carried forward

1. Attestation is evidence for a verifier to appraise; its freshness needs a nonce, timestamp or epoch (S8). ORNEUR uses nonce-bound, session-bound grants because its roles have no trusted clock.
2. Threshold, offline, versioned and expiring metadata resist compromise of a single key and rollback (S14). ORNEUR's trust root, grants and revocation follow that shape.
3. Two roots of trust from independent vendors is a published practice for exfiltration-critical components (S1b). ORNEUR P1 gets this across roles by putting the Witness on a different platform family from Forge and Crown.
4. Two-party, time-limited authorization and egress limits are in use for weights (S9). ORNEUR uses the same ideas at the grant and transfer-medium level.
5. A token can hold a non-exportable Ed25519 key and can attest that it generated it (S19, partly unverified for Ed25519). That gives key-custody evidence the current owner key (generated as a file) lacks.

## 5. Classification of every major ORNEUR mechanism

Classes: STANDARD (used as published), ADAPTED (a published mechanism moved to this setting), ORNEUR_SPECIFIC_COMBINATION (known parts, composed for this threat model; no equivalent was found in the limited search), POTENTIALLY_NOVEL (searched for and not found), UNVERIFIED_NOVELTY (looks unusual, not searched enough to say). **No mechanism is classed POTENTIALLY_NOVEL**, because the search was limited.

| ID | Mechanism | Closest published analog | Class | Security property it improves |
|---|---|---|---|---|
| M1 | Token-resident Ed25519 authority keys with attested generation | YubiKey PIV attestation (S19) | STANDARD | owner key cannot be copied from a host |
| M2 | Threshold (k-of-n) multi-signature authority with offline root | TUF thresholds (S14) | STANDARD | one stolen token or session cannot mint root changes |
| M3 | Time-separated second signature for high-class grants | Anthropic time-limited two-party authorization (S9) | ADAPTED | a rushed or hijacked session cannot complete a sensitive grant alone |
| M4 | Grants bound to role, environment, code hash, policy, dataset, model, operation, time, resource limits, destination, evidence | AWS KMS and Azure SKR policy conditions (S5, S6) | ADAPTED | authority cannot be reused for another purpose |
| M5 | Challenge-bound, session-bound grants (the role issues a nonce) | RFC 9334 nonce freshness (S8) | STANDARD | replay and stale authorization without a trusted clock |
| M6 | Grant carries the previous evidence-ledger head the role must hold | TUF snapshot and version chaining (S14) in spirit | **UNVERIFIED_NOVELTY** | rollback or fork of role state invalidates new authority |
| M7 | Incident epoch that invalidates all older grants at once | TUF root versioning and expiry (S14) | ADAPTED | global revocation without roles being online |
| M8 | Template-conformant grants with an external policy cosigner (time, cool-off, incident state) | transparency-log monitors and policy engines | ADAPTED | independent policy check and an independent clock |
| M9 | Pin of the role trust root, entered by a human from an offline copy | SSH fingerprint verification, TUF root pinning | STANDARD | same-authority replacement of manifest and pin is detected |
| M10 | Dual display path: the digest signed on Crown is compared with the digest shown by the consuming role | transaction verification on a second device | ADAPTED | a compromised presentation surface cannot get a different grant signed unnoticed |
| M11 | Key-absent ingestion: untrusted bytes are parsed while the secret volume is locked | privilege separation | STANDARD | parser compromise does not expose the key |
| M12 | Raw-container transfer medium with no filesystem | data-diode practice, minimal parsers | STANDARD | removes filesystem-driver attack surface from ingestion |
| M13 | Evidence-only, size-bounded return path from the Witness | Anthropic egress bandwidth limits (S9), RAND SL5 transfer policy (S10) | ADAPTED | a compromised Witness cannot export bulk data |
| M14 | Two-sided evidence: actor signature plus counterparty countersignature | RATS evidence plus verifier appraisal (S8) | ADAPTED | one compromised actor cannot write history alone |
| M15 | External anchoring of ledger heads and an external consistency monitor | Rekor, transparency.dev, witnesses (S16) | STANDARD | silent history rewrite becomes detectable |
| M16 | Ephemeral mutable state restored to a signed baseline before each secret-bearing phase | Qubes disposables (S13), PCC stateless nodes (S1) | ADAPTED | cross-boot software persistence is removed |
| M17 | Reproducible two-builder release, then threshold-signed manifest | SLSA provenance, reproducible builds (S15) | STANDARD | a compromised build host cannot ship unnoticed code |
| M18 | Local TPM2-sealed Witness volume unlock bound to measured boot plus a PIN | systemd-cryptenroll (S18), cloud key release (S5, S6) | STANDARD | key release only into the measured, pinned boot state (P1 only) |
| M19 | Platform diversity across roles: Apple silicon for Forge and Crown, TPM PC for the Witness | PCC's two independent roots (S1b) | ADAPTED | a platform-level flaw does not cross to the Witness |
| M20 | Lineage taint with a taint epoch so artifacts of a compromised role cannot re-enter | SLSA and in-toto provenance (S15) | ORNEUR_SPECIFIC_COMBINATION | contaminated state cannot silently return |
| M21 | Grant class table tying capability to authorization strength | RAND levels (S10), two-party control (S9) | ADAPTED | more capability gets stricter authority |
| M22 | Network canary at the router for registered role MACs | ordinary network monitoring | STANDARD | independent signal of radio use during offline phases |
| M23 | Sentinel as an external, secret-free monitor on separate accounts | transparency monitors (S16) | ADAPTED | detects missing anchors and unlogged owner-key use |
| M25 | Minimal key-present verifier: only a small fixed-format parser runs while the decryption key is present; complex parsing happens key-absent | privilege separation and attack-surface reduction | ADAPTED | an exploit in a large parser cannot reach a present key |
| M24 | Whole composition: single owner, sequential or two-machine, token authority, evidence-bound short-lived grants | no equivalent found in the sources read | ORNEUR_SPECIFIC_COMBINATION | composition of the above for a sovereign setting; **no claim of uniqueness** |

## 6. What can and cannot be said about novelty

- **Can be said:** the architecture is assembled from published mechanisms (thresholds, nonces, attestation-bound key release, transparency logs, ephemeral state, egress limits) and applied to a single-owner offline setting that the sources do not describe.
- **Cannot be said:** that any mechanism is new, that no other system combines them, or that ORNEUR "exceeds" Apple PCC, the frontier labs or RAND SL4/SL5. M6 may be unusual but was not searched enough to call it novel.
- **Where ORNEUR is weaker than the comparators:** no hardware-attested measured boot on Apple silicon; no organization-scale security team; the same human on both sides of two-party control.
- **Where the design tries to go beyond what was found, without claiming it does:** binding each new grant to the evidence head the role already holds (M6, unverified novelty); session-bound grants that need no trusted clock (M5, standard technique applied to authority); platform diversity across roles for a single owner (M19, a published practice at much larger scale). Whether any of this exceeds the best published architecture is **not shown**.
- **Where it deliberately adopts their level:** time-limited two-party authority, egress bounds, attested key release (P1 Witness), append-only anchored evidence.

## 7. Research still needed before any later freeze (RSE-ARCH-2.0)

Confirm Ed25519 PIV attestation on the chosen token; read the primary OpenAI and RAND texts; study AMD SEV-SNP and Intel TDX attestation for the future Qualification Chamber; test whether Apple silicon exposes any owner-verifiable measurement of an externally booted OS; examine Sigsum and OpenTimestamps for the anchoring layer; survey signing devices with trusted displays.
