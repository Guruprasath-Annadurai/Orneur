# RSE-ARCH-1.1 — Part 4: custody, Qualification, supply chain, network, recovery

Sections L, P, T, X, Y, Z, AA, AB. All `DESIGNED`. Resolves blockers B1 (completeness), B7, and supports B4/B10.

## L. Qualification Chamber (future, P2; design only)

Purpose: produce **evidence**, never authorization.

- Holdout key exists only inside the chamber; holdout items are in RAM only; candidate weights read-only; no training write path; no network; no swap or core dumps; no signing authority; no operator access to items.
- Outputs: bounded aggregate results only (counts, a pass/fail contamination boolean). A **run budget** and an **information/bit budget** cap how much the outputs can reveal across runs; exceeding either freezes the chamber.
- **Protected contamination oracle:** answers a bounded yes/no question without exposing the holdout; run-rate limited; **no hashes of low-entropy questions** are ever emitted (they would be brute-forceable).
- Qualification evidence feeds a W grant (as a digest in its bindings) but never replaces the owner's confirmation.

## P. Reliquary and recovery (offline)

Offline encrypted copies of: owner authority records, Crown recovery material, the artifact repository, Witness rebuild kit, checkpoint root, paper checkpoint card. Held physically apart; restore drill is an acceptance item (§AG). Recovery never silently downgrades trust: if trust cannot be restored, the answer is re-root, not "best effort".

### Recovery scenarios

| Scenario | Effect | Action |
|---|---|---|
| Lost Forge storage | generation secret and in-flight work lost; no corpus loss (Witness holds accepted) | rebuild Forge, new Forge role key, new generation secret under class K grant; old Forge ID revoked |
| Lost Witness drive | accepted corpus and key lost locally | rebuild Witness, restore corpus from Reliquary encrypted copy (if exists) and re-verify against ledger digests; otherwise regenerate under new keys |
| Lost Witness motherboard / TPM | key sealing gone | treat as lost drive; new TPM enrolment; PCR policy re-created by owner ceremony |
| Lost owner token | one class key unusable | use the other token + recovery to re-issue under K grant; epoch bumped |
| All tokens lost | no signing authority | **re-root ceremony** (below) from the paper recovery path |
| Lost paper checkpoint | offline checkpoint reference lost | cross-role and Monitor-Lite checkpoints remain; owner re-establishes root checkpoint; loss recorded |
| Ledger service loss | external checkpoint holder gone | cross-role holders carry; replace holder; recorded gap |
| Compromised artifact repository | code provenance broken | quarantine all roles; rebuild repository from an independent source comparison; re-root if signing keys exposed |
| Corpus corruption | digest mismatch | quarantine; restore from Reliquary; re-verify |
| Trained-weight corruption (future) | digest mismatch | restore from Reliquary or retrain; revoke the digest |

### High-level re-root ceremony

1. Declare incident; freeze all roles (QUARANTINED).
2. Create a new owner authority version and keys on a freshly built Crown.
3. Raise the incident epoch; set new minimum versions.
4. Establish a new checkpoint root; publish to cross-role and Monitor-Lite holders.
5. Revoke old roles and their keys; old grants are invalid by epoch.
6. Re-verify every artifact in the repository from independent sources.
7. Rebuild roles from re-verified artifacts; re-attest; re-enrol.
8. Re-ingest corpus only after re-verification; record the re-root in the ledger.

## T. Network sovereignty

| Role | Policy | Link types considered |
|---|---|---|
| Crown | never networked | physical (no port used), Wi-Fi, Bluetooth, IPv6, tunnels, USB networking, Thunderbolt networking: radios absent/removed where possible, otherwise software-disabled and gate-checked (recorded residual on Mac) |
| Forge | offline in secret phases; no cable | same list; Mac radios cannot be removed (residual U8) |
| Witness | **no radios, wired port unused**, network boot disabled | USB gadget/networking disabled by default-deny; Thunderbolt/PCIe DMA mitigated by IOMMU where present |
| Monitor-Lite | online by design, holds no secrets | outbound only to checkpoint holders |
| Maintenance mode | updates only via offline artifact repository medium; never "temporarily online" | — |

## X. Supply chain and approved artifact repository

Pipeline: untrusted acquisition → quarantine → signature/provenance check → hash → SBOM → malware and static review → **independent source/build comparison** → owner approval → TUF-style metadata (versions, expiry, rollback protection) → **offline, read-only distribution**. **Two downloads from the same upstream are not independent evidence**; only a separately built or separately sourced artifact counts.

### Owner-signed Witness boot chain (UKI)

Owner Secure Boot key → signed unified kernel image (kernel, initrd, command line fixed inside) → measurement into PCRs → TPM policy → PIN → LUKS key release. To audit: firmware (vendor key removal, update path), whether a shim is used (preferred: no shim, owner keys enrolled directly), kernel config, initrd contents, fixed command line, how role code is loaded (from a measured read-only image), and which PCRs are selected (PCR 7 for policy, the image PCR for the UKI; the choice of signed-policy vs fixed-PCR sealing is an owner decision and is listed in §AH).

## Y. Corpus custody lifecycle

| Stage | Reads | Modifies | Authorizes | Key | Grant | Evidence/checkpoint | Recovery |
|---|---|---|---|---|---|---|---|
| Source material | Forge | none | owner (inventory) | none | — | digest in ledger | re-import from source |
| Generation authorization | — | — | Crown | class-G key | G | authorization record checkpointed | revoke by epoch |
| Forge plaintext | Forge | Forge | — | generation secret | G | start/end records | wipe; regenerate |
| Encrypted bundle | Forge | — | — | Witness recipient key (public) | G | envelope digest | regenerate |
| Witness verification | Witness | none | Crown (V) | decryption key | V | verification result | quarantine |
| Accepted corpus | Witness | none | — | vault key | V | acceptance record | Reliquary copy |
| Private storage | Witness | none | — | vault key | — | periodic digest checks | Reliquary |
| Qualification (future) | chamber | none | Crown (Q) | holdout key | Q | evidence | rerun |
| Training input (future) | trainer | none | Crown (T) | per-run key | T | run records | rerun |
| Archive | none | none | owner | archive key | — | digest | restore |
| Retirement | none | delete/crypto-erase | owner | — | R | revocation record | n/a |

## Z. Model-weight custody (future)

Stages: foundation weights → approved input (digest) → checkpoints → candidate final → Qualification candidate → accepted model → exported → deployment artifact → retired/revoked. Each transition is an owner-confirmed record. **W (export) and D (deployment) are separate grants** (§S). The accepted-model digest is the only identity that W and D accept; a retrained model with a different digest needs new Qualification and new W/D grants.

## AA. Compromise scenarios

| Scenario | First failed control | What contains it | Residual |
|---|---|---|---|
| Crown environment compromised, tokens intact | presentation integrity | consumer view re-renders actual bytes; dual-token separation; epoch revocation | rubber-stamping by owner |
| Forge compromised | plaintext exposure window | no decryption key, grant ceilings, Witness verification, bounded window | plaintext in the window |
| Witness compromised after unlock | key in RAM | short window, no network, rebuild, key rotation | plaintext/key in window |
| TPM failure | key release | recovery passphrase path; rebuild | none beyond delay |
| Firmware compromise | below measured boot | P1 Witness: owner keys, measured state, PCR denial; Mac roles: none | persistence on Mac hardware (U1) |
| Stolen Witness PC | confidentiality | TPM + PIN + LUKS2 | none for at-rest data; hardware loss |
| Stolen disk | confidentiality | LUKS2 sealed | none |
| Stolen token | signing | PIN, touch, second token for sensitive classes, epoch | one-class exposure until revoked |
| Malicious transfer medium | parser | OCR1 fixed grammar, two-phase ingestion, minimal verifier | verifier bug |
| Parser differential | inconsistent acceptance | single grammar, canonical re-encode, second implementation in tests | untested edge |
| Ledger fork | history integrity | witnessed consistency proofs, per-role binding, quarantine | all-holder compromise |
| Ledger tail suppression | recency | checkpoint interval bounded by grant life | window |
| Rollback | stale state | W table | Mac OS state unsolved |
| Replay | stale grant | consumer nonce, single consumption record | none identified |
| Old incident epoch | stale authority | epoch in every grant | role unaware of new epoch (needs ledger sync) |
| Malicious approved dependency | supply chain | independent build comparison, minimal verifier | shared upstream |
| Poisoned recovery kit | recovery | independent re-verification, re-root | owner skips re-verification |
| Weight exfiltration (future) | export | separate W grant, destination binding, encryption recipient | insider/owner |
| Qualification extraction (future) | holdout leak | bounded outputs, bit budget | long-run accumulation |
| Provider compromise (future) | confidential compute | attested release, spend caps | provider root of trust |
| Common-owner error | everything owner-signed | dual-token separation, consumer confirmation, drills | cannot be eliminated |

## AB. Disaster recovery

Recovery targets by asset: owner authority (paper + second token), Witness (rebuild kit + corpus restore from Reliquary), ledger (cross-role + owner checkpoint), artifact repository (Reliquary + independent re-comparison). Drill cadence and success criteria are acceptance items (§AG, C-drills). Total owner-authority loss is not recoverable without the paper path; if that is also lost, **everything signed becomes unverifiable and the programme re-starts at provisioning**.
