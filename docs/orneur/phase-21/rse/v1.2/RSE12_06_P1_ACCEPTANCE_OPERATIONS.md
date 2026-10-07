# RSE-ARCH-1.2 — Part 6: P1 requirements, threat model, operator budget, acceptance register, roadmap

Architecture only. No product is selected, nothing is bought, installed or created.

## 1. P1 Witness requirements (revised; replaces `RSE11_02` §J)

Classes: **M** MANDATORY, **P** PREFERRED, **O** OPTIONAL, **D** DISQUALIFYING_IF_ABSENT. Every M/D row states the property it creates, so a later hardware choice needs no redesign.

| # | Requirement | Class | Property created |
|---|---|---|---|
| 1 | Dedicated physical machine used for nothing else | M | no shared hardware root with Forge/Crown (removes U1 for the Witness) |
| 2 | TPM 2.0 | D | key release bound to measured state; offline quote |
| 3 | TPM NV index support including counter type, and policy comparison on NV | **M** (was PREFERRED) | the rollback fence of `RSE12_03` §3; without it Witness rollback is not preventable |
| 4 | UEFI Secure Boot with owner-enrolled keys; vendor/OEM keys removable | M | only an owner-signed chain runs |
| 5 | Measured boot into PCRs; quote supported and verifiable offline | M | boot state is evidenced to Crown |
| 6 | **Role-code identity measurement**: the role code lives inside the measured image and its version is part of the generation | M | the code that runs is the code the owner approved |
| 7 | Fixed PCR policy for key release (image PCR and PCR 7), re-sealed per generation | M | unseal fails after any chain change |
| 8 | Linux with owner-built signed unified kernel image | M | auditable minimal OS; drivers for absent links not built |
| 9 | LUKS2 vault | M | data at rest |
| 10 | TPM-bound key release plus PIN (Argon2id-hardened) | M | resists TPM bus sniffing and a stolen powered-off machine |
| 11 | Offline recovery passphrase (paper) | M | recovery without silent trust downgrade |
| 12 | **Firmware setup password; boot order locked; boot from internal drive only; network boot disabled** | M | firmware settings cannot be changed casually; no alternate boot path |
| 13 | **Management engine / out-of-band management (e.g., AMT-class, BMC-class) absent or disabled in a way the owner can verify** | M; D if present, network-capable and not disableable | no hidden network-reachable controller with memory access |
| 14 | **DMA-capable externally accessible buses** (Thunderbolt/USB4, external PCIe, hot-pluggable M.2/ExpressCard, FireWire-class): either absent/disabled **or** IOMMU enabled and enforced | **M**: IOMMU is MANDATORY when any such bus exists; D if such a bus exists and no IOMMU | removes DMA-based memory attack by an attached device |
| 15 | Radios absent, physically removable, or hardware-disableable (software-disable alone is not enough) | M | no wireless path |
| 16 | Wired network port: unused, blocked or firmware-disabled | M | no network path |
| 17 | USB default-deny with an allow-list limited to the one transfer-medium class | M | bounded USB surface |
| 18 | Firmware and OS updates only offline from the owner-approved registry | M | no network updater |
| 19 | Approved artifact registry and offline distribution exist | M | provenance of code |
| 20 | Physical custody in a controlled location; tamper-evident seals and a photographed baseline | M (custody) / P (seals) | bounds thief and casual physical access |
| 21 | Adequate RAM, storage, CPU for the largest planned bundle and the sandboxed checker | M | operational capacity |
| 22 | Hardware random source (TPM RNG available) | P | better entropy for challenges and keys |
| 23 | Discrete TPM versus firmware TPM | O | discrete exposes the bus (PIN mitigates); firmware TPM shares CPU trust; neither is claimed immune |
| 24 | No GPU requirement | M | keeps the Witness small |
| 25 | A second identical spare (cold) for disaster recovery | O | availability after hardware loss |

Hardware-specific attacks beyond this list (cold-boot, invasive TPM attacks, silicon backdoors) are out of scope (declared).

## 2. Threat model (structured)

| Adversary | Capability | Entry point | Target | Trust root attacked | Expected control | Residual |
|---|---|---|---|---|---|---|
| Compromised daily-driver | full control of an agent-exposed host | proposals, files, display | owner approval; supply chain | R-Owner (intent), registry | proposals only; Crown validates against registry; consumer re-renders; typed SAS; daily-driver never builds, signs or compares | owner approves a bad intent |
| Compromised Forge | arbitrary code on Forge in-window | generation phase | plaintext, bundle integrity | R-Custody | sees plaintext in the window (declared); cannot decrypt Witness vault; signs only enrolled bundles; ceilings; result gating | plaintext in window |
| Compromised Witness | code execution after unlock | sandbox escape / dependency | vault key, corpus | R-Witness-Boot | short key window, no network, sandbox, rebuild, key rotation | key in RAM during window |
| Stolen hardware | physical possession | disk, machine, token | confidentiality | R-Witness-Boot, R-Owner | TPM+PIN+LUKS2; token PIN/touch; second token; epoch | disk+recovery passphrase together |
| Malicious transfer medium | crafted bytes | media | parser/kernel | R-Custody | raw medium, fixed grammar, signature before key, two-phase ingestion, minimal key-present primitives | verifier bug |
| Malicious approved artifact | owner approved something bad | registry | everything downstream | R-Artifacts | independent builds, minimal verifier, bounded ceilings | shared upstream; owner error |
| Malicious foundation weight | poisoned/backdoored weights | acquisition | trained model | R-Artifacts | provenance, format inspection, owner approval | undetectable backdoor |
| Supply-chain compromise | upstream or build host | acquisition/build | code | R-Artifacts | two independent builds, comparison on Crown | both from compromised upstream |
| Owner mistake | rubber-stamping, loss, wrong card | Crown, procedures | any | R-Owner | typed SAS, policy caps, drills | cannot be eliminated |
| Ledger administrator compromise | rewrites one log, withholds | role or Monitor host | history | R-Ledger | witnessed checkpoints, M1∧M2 for irreversible, XH and OC detection | all holders and the administrator |
| Cloud/provider compromise (future) | provider-level control | hosted compute | weights, spend | P2 | attested environment, provider-side key release, spend caps | provider root of trust; UNPROVEN |

## 3. Operator budget (normal G corpus-generation cycle, P1 steady state)

Steady state assumes challenges are pre-issued at the end of the previous cycle and checkpoint trips are batched.

| Item | Count |
|---|---|
| Boots | Crown 1, Forge 1, Witness 1 (+1 optional reboot between ingestion phases) = **3 (4)** |
| Shutdowns | 3 (4) |
| Token touches | G (2 tokens) + V (1) = **3** (plus PIN entries) |
| Media insertions + removals | Crown↔M1 CM (1+1), Forge: CM + transfer medium (2+2), Witness: transfer medium + CM (2+2), M1 trips 2 (2+2, one of them shared with the next cycle) ≈ **14 moves** |
| Checkpoint round trips (to M1) | **2** per cycle (the acceptance trip merges with the next cycle's grant trip) |
| Human field-card reviews | 2 on Crown (G, V) + 2 on consumers (Forge, Witness) = 4 |
| Typed confirmations (12-character SAS plus about 4 Intent Sheet fields each) | 2 (Forge, Witness) |
| Floor-card tuple entry at Crown session start | 1 |
| Irreversible-class cycle (K/W/D/T/Q) | + M2 trip, + OC card update |

**Architecture target (not an arbitrary limit):** ≤ 4 boots, ≤ 14 media moves, ≤ 2 witness round trips, ≤ 3 token touches, ≤ 2 typed SAS per routine cycle. Reductions applied: batching several grants per Crown session; pre-issued challenges; one medium for all public records; envelope grants (N batches per confirmation); acceptance trip merged with the next cycle. **Excess is treated as a security risk**: if an acceptance drill measures more than the budget, the process is redesigned rather than the operator told to be careful (fatigue is how owners start skipping steps).

## 4. Acceptance register 1.2

Columns: ID, PROPERTY, TYPE, COMPONENT, SYNTH (synthetic test possible), REAL_HW (real hardware needed), POSITIVE, NEGATIVE, ADVERSARIAL, EVIDENCE (objective artifact), FAILURE (result), RECOVERY, AUDIT (independent audit required), MATURITY. Types: `CRYPTOGRAPHICALLY_ENFORCED` (CRYPTO), `HARDWARE_ENFORCED` (HW), `SOFTWARE_ENFORCED` (SW), `DETECTIVE` (DET), `PROCEDURAL` (PROC), `ADVISORY` (ADV), `UNPROVEN` (UNP). One type per row; a control with two mechanisms is two rows. Maturity is `DESIGNED` unless stated. Every AUDIT cell is **yes**: nothing is audited yet.

| ID | PROPERTY | TYPE | COMPONENT | SYNTH | REAL_HW | POSITIVE | NEGATIVE | ADVERSARIAL | EVIDENCE | FAILURE | RECOVERY | AUDIT | MATURITY |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C01 | Crown refuses unregistered/unapproved IDs | SW | Crown validator | yes | no | approved entry signs | unknown/REVOKED/wrong-type ID refused | substituted digest | refusal log + grant not created | no grant | fix registry | yes | DESIGNED |
| C02 | Consumer repeats registry validation | SW | role verifier | yes | no | valid grant accepted | grant with stale/unknown registry refused | Crown tricked by proposal | consumer refusal record | refuse | send registry delta | yes | DESIGNED |
| C03 | Registry canonical and owner dual-token signed | CRYPTO | registry codec | yes | no | valid update verifies | one signature / same token twice / bad layout rejected | forged update | verify log | reject | re-sign | yes | DESIGNED |
| C04 | Ceilings ≤ POLICY caps | SW | Crown + consumer | yes | no | within caps accepted | above cap refused | changed ceiling | refusal record | refuse | edit proposal | yes | DESIGNED |
| C05 | Names restricted and non-confusable | SW | registry validator | yes | no | clean name accepted | confusable/oversize name refused | homoglyph entry | validator output | reject entry | rename | yes | DESIGNED |
| C06 | Consumer renders from received signed bytes | SW | consumer renderer | yes | no | card equals Crown card | any altered byte changes card or fails signature | Crown shows B1 signs B2 | rendered-card digest | refuse | revoke grant | yes | DESIGNED |
| C07 | Typed SAS (60-bit) and typed Intent Sheet fields match the rendered grant | SW | consumer + Crown | yes | no | correct SAS and fields accepted | wrong SAS or any differing intent field rejected | compromised Crown showing a benign card (typed intent defeats it); grind to same SAS infeasible (cost estimate) | typed-entry record | refuse | retype | yes | DESIGNED |
| C08 | Dual-token threshold and distinct keys | CRYPTO | grant verifier | yes | tokens | two distinct approved sigs accepted | one sig / duplicate sig / wrong domain rejected | cross-class signature replay | verify log | refuse | re-sign | yes | DESIGNED |
| C09 | Challenge single-use, single-outstanding | SW | role journal | yes | no | fresh challenge accepted once | reuse / superseded / wrong role refused | replay of captured grant | journal + log | refuse | new challenge | yes | DESIGNED |
| C10 | Offline clock is advisory only | ADV | role | yes | no | past `not_after` refused before ACTIVE | clock set back does not extend a consumed/superseded challenge | clock manipulation | refusal record | refuse | new grant | yes | DESIGNED |
| C11 | No ACTIVE before witnessed checkpoint | SW | consumer state machine | yes | no | acks present → ACTIVE | signature without acks refused | valid grant, missing M1 | state log | stay unusable | obtain ack | yes | DESIGNED |
| C12 | Witness cosignature verification | CRYPTO | consumer | yes | no | correct ack accepted | ack for another size/root/epoch rejected | forged ack | verify log | refuse | re-witness | yes | DESIGNED |
| C13 | Monitor refuses forks, smaller trees, same-size different roots | SW | Monitor-Lite | yes | no | consistent growth cosigned | fork/shrink refused | equivocation across M1/M2 | witness log | quarantine | re-root if confirmed | yes | DESIGNED |
| C14 | Result egress gating (bundle needs witnessed RESULT) | SW | Witness Phase 1 | yes | no | bundle + proof accepted | bundle without proof refused | un-logged "success" | refusal record | quarantine bundle | obtain proof | yes | DESIGNED |
| C15 | Crash never double-executes | SW | journal | yes | no | each crash row behaves as specified | ACTIVE crash does not resume | kill at every step | journal replay report | INTERRUPTED | new grant | yes | DESIGNED |
| C16 | OCR1 v2 grammar and canonical re-encode | SW | codec | yes | no | canonical frame accepted | all malformed frames rejected | mutation corpus; second implementation agrees | digest of verdict vector (`prototype/`) | reject | n/a | yes | DESIGNED (STRUCTURAL_CODEC_EVIDENCE only) |
| C17 | `enc` validity and zero-shared-secret abort | CRYPTO | verifier | yes | no | valid enc accepted | non-canonical, zero, low-order rejected | crafted points | vector test | reject | n/a | yes | DESIGNED |
| C18 | Key/nonce uniqueness (info-bound key, index nonce) | CRYPTO | HPKE profile | yes | no | RFC 9180 vectors reproduce | repeated enc under new digest flagged | RNG repeat | test log | quarantine sender | rotate sender key | yes | DESIGNED |
| C19 | Frame set rules (missing/duplicate/reorder/extra/truncate/cross-bundle) | SW | assembler | yes | no | complete set accepted | each case rejected | injected foreign frame | per-case verdicts | reject | resend | yes | DESIGNED |
| C20 | Sender/recipient enrolment binding | CRYPTO | enrolment resolver | yes | no | enrolled ID resolves | unknown/REVOKED ID refused | sender-key substitution | resolver log | reject | re-enrol | yes | DESIGNED |
| C21 | Origin signature verified before key use | CRYPTO | Phase 1 | yes | no | valid σ passes | bad σ rejected, key never used | re-encrypted forged frame | verify log | reject | n/a | yes | DESIGNED |
| C22 | Key-absent Phase 1 leaves vault locked | SW | ingestion | yes | yes | vault locked throughout | attempt to unlock fails | media exploit | mount/key-state record | abort | reboot | yes | DESIGNED |
| C23 | Plaintext sandbox: no key, no network, bounded I/O | SW | checker sandbox | yes | yes | bounded output only | filesystem/key/network access fails; oversize and crash handled | malicious authenticated corpus; resource exhaustion | sandbox policy dump + test log | kill checker | rebuild | yes | DESIGNED |
| C24 | Vault key release bound to measured boot | HW | TPM policy | no | yes | unseal after correct boot | wrong PCR / wrong PIN / altered UKI denied | offline attack | TPM error codes | denial | recovery path | yes | DESIGNED |
| C25 | NV fence denies old image/sealed state | HW | TPM NV | no | yes | current generation boots | older image + older blob denied | rollback of disk image | counter value, denial record | denial | K re-seal | yes | DESIGNED |
| C26 | NV update transaction safe at every power cut | SW | updater | partly (simulator) | yes | update completes | cut at each step yields a safe state | power cut mid-increment | per-step test report | fail closed, not bricked | passphrase path | yes | DESIGNED |
| C27 | TPM/motherboard replacement without rollback | PROC | recovery | no | yes | K-grant re-enrolment completes | lower-generation restore refused | stale-state restore | re-enrolment records, new ROLE_ID | refuse | re-root | yes | DESIGNED |
| C28 | Owner Secure Boot keys only | HW | firmware | no | yes | owner-signed image boots | vendor-signed / unsigned refused | key enrolment attack | firmware key list | refuse | n/a | yes | DESIGNED |
| C29 | Quote verifies offline against pinned attestation key | CRYPTO | Crown verifier | partly | yes | fresh quote accepted | stale challenge / wrong PCR rejected | replay of old quote | quote record | reject | re-attest | yes | DESIGNED |
| C30 | DMA protection (IOMMU or buses absent) | HW | firmware/kernel | no | yes | IOMMU groups enforced / buses absent | DMA from attached test device blocked | malicious device | kernel report | n/a | n/a | yes | DESIGNED |
| C31 | USB default-deny | SW | kernel policy | partly | yes | allow-listed medium works | unlisted device ignored | rubber-ducky-class device | kernel log | ignore | n/a | yes | DESIGNED |
| C32 | Radios absent / hardware-off | HW | hardware | no | yes | enumeration shows none | enabled radio fails the gate | re-enable attempt | enumeration digest | stop | rebuild | yes | DESIGNED |
| C33 | No usable network device per link class (§`RSE12_05` §7) | SW | measured kernel | partly | yes | netdev list empty | test devices create no netdev | tunnel/USB-net/Thunderbolt-net attempts | measured config + netdev digest | stop | rebuild | yes | DESIGNED |
| C34 | ME/OOB management absent or disabled | HW | platform | no | yes | verified state | enabled network-capable controller fails acceptance | out-of-band access | platform report | disqualify hardware | choose other hardware | yes | DESIGNED |
| C35 | Firmware password and locked boot order | HW | firmware | no | yes | changes blocked | change attempt fails | physical menu access | settings record | n/a | reset by owner ceremony | yes | DESIGNED |
| C36 | LUKS2 at rest | CRYPTO | vault | yes | yes | unlock only via release path | key absent → unreadable | stolen disk | header check | n/a | restore | yes | DESIGNED |
| C37 | No plaintext on persistent channels | DET | storage scan | yes | yes | clean pre/post scan | planted marker found | swap/dump/log channels | scan report | wipe | wipe | yes | DESIGNED |
| C38 | Crown isolation inventory | DET | Crown | partly | yes | no agents/network found | planted agent or network found | compromised sibling | inventory digest | rebuild | rebuild | yes | DESIGNED |
| C39 | Genesis reproducibility (two independent builds equal) | DET | ceremony | yes | no | digests equal | one-bit change differs | compromised single host | both build reports | abort | rebuild | yes | DESIGNED |
| C40 | Registry rollback floors (Crown typed card, sealed floor) | SW | Crown | yes | no | current card accepted | lower card / lower sealed floor refused | stale Crown image | floor-check log | refuse | update card | yes | DESIGNED |
| C41 | Owner Floor Card integrity | PROC | custody | no | no | two copies match | mismatch detected by comparison procedure | replaced card | signed receipt of comparison with both serials | quarantine | recompute from witnessed floors | yes | DESIGNED |
| C42 | Recovery never restores below the effective floor | SW | Crown + role | yes | no | at-floor kit accepted | below-floor kit refused | old recovery media | refusal log | refuse | newer kit | yes | DESIGNED |
| C43 | Recovery media theft response | PROC | owner | no | no | epoch raised and LUKS slot rotated | — | stolen passphrase | epoch checkpoint + rotation record | n/a | n/a | yes | DESIGNED |
| C44 | Dual-token class signatures cannot be satisfied by one token | CRYPTO | verifier | yes | tokens | two distinct tokens accepted | one token twice refused | single stolen token | verify log | refuse | revoke token | yes | DESIGNED |
| C45 | Impossible role-lifecycle transitions rejected | SW | role state machine | yes | no | allowed transitions pass | every impossible one refused | forced skip | transition log | QUARANTINED | RECOVERY | yes | DESIGNED |
| C46 | Qualification output quantization and bit budget | SW | chamber | yes | P2 | within budget answers | over-budget / near-duplicate queries refused | threshold bisection | budget counter + log | freeze | retire holdout | yes | DESIGNED (future) |
| C47 | Qualification counters not rollbackable | UNP | chamber | no | P2 | — | restored state does not refund budget | state restore | provider/hardware monotonic evidence | freeze | retire holdout | yes | DESIGNED (future) |
| C48 | W and D separate, training ≠ export | CRYPTO | grant verifier | yes | no | W grant for accepted model | T-complete record cannot authorize W; W-complete cannot authorize D | bypass attempt | refusal records | refuse | issue correct grant | yes | DESIGNED |
| C49 | Foundation approval complete before use | PROC | approval | no | no | complete entry approved | incomplete entry refused by registry validator | poisoned foundation | entry with all provenance digests | refuse | complete | yes | DESIGNED (future) |
| C50 | Operator budget measured in drills | ADV | operations | no | yes | measured counts ≤ budget | over-budget flagged | — | drill measurement record | redesign | adjust process | yes | DESIGNED |

### Objective-evidence rule

A procedural control is accepted only on **objective evidence** — a signed receipt, a measured value, a key state, a physical-inventory record with both card serials, or a witnessed checkpoint. "The owner confirms" never validates a technical property, and a "drill completed" entry is not evidence by itself.

## 5. Residual risks (updated)

R-I1 Forge plaintext window; R-N1 one-human administration of M1, M2, OC; R-F1 pre-issued challenge staleness; R-RB1 consumer registry rollback detection-only; R-RB2 routine-grant replay after in-state rollback (bounded); R-W1 Mac OS rollback UNSOLVED; R-U1/U2/U8 Mac firmware persistence, no owner-verifiable boot measurement, non-removable radios; R-C1 time-shared minimum Crown; R-V1 verifier bug; R-RNG1 sender RNG if no library allows the RFC 8937 wrapper; R-B1/R-X1 shared upstream; R-F2 backdoored foundation; R-O1 owner error; R-RP1 disk plus recovery passphrase together; R-TPM bus, firmware-TPM trust, NV counter atomicity and endurance unverified; R-Q P2 and Qualification counters UNPROVEN; R-EXF P2 egress control for training (blocks training authorization); R-RES research gaps. None is hidden.

## 6. P0, P1, P2, God-mode, novelty

- **P0** = synthetic rehearsal only. **P1** (Crown + Forge + independent Witness) is required before the real private corpus. **P2** or an equivalent training-security architecture is required before real training; no provider or GPU is selected or authorized.
- **God-mode future compatibility:** RSE protects the sovereign training/control plane and does **not** solve the public online governance plane. Registry, grants, challenge freshness, consumer confirmation and log-first records are the substrate a future online Authority Broker could reuse (envelope grants, immediate revocation, multi-user identity, tool/action, memory, browser/computer-use, spend and external-communication authority); RSE does not preclude it. Doctrine: SURPRISING IN CAPABILITY. PREDICTABLE IN TRUST.
- **Novelty:** `INSUFFICIENT_RESEARCH`, unchanged; this phase added RFC 9180 and RFC 8937 reading only. No claim of world-first or uniqueness.

## 7. Implementation roadmap (all gates separate; none opens by this document)

1. Independent audit of RSE-ARCH-1.2 by a reviewer who did not author it (next action).
2. Architecture freeze commit (only if that audit accepts and the owner/ChatGPT review agrees).
3. Prototype/characterization with **synthetic ephemeral keys only** (CRYPTOGRAPHIC_IMPLEMENTATION_EVIDENCE for the HPKE profile; TPM simulator for update-transaction tests). Separate authorization.
4. Software implementation (codec, verifier, registry tool, Crown renderer simulator, checkpoint/witness tooling), by Cursor. Separate authorization.
5. Independent code audit.
6. P1 hardware selection (separate purchase authorization).
7. P1 provisioning and key creation (separate authorization).
8. P1 acceptance run (C-series real-hardware rows) and adversarial verification.
9. **Crown milestone 1:** minimum dedicated Crown before any real corpus.
10. Real corpus authorization (separate owner decision, as a grant).
11. **Crown milestone 2:** independent dedicated Crown device before Qualification/training.
12. Qualification milestone (chamber design implemented and accepted).
13. P2 research and acceptance (attested environment, egress control, counters, spend controls).
14. Training infrastructure; then Genesis training; then Novus; then Aeternum — each its own authorization.

## 8. Exact next action

**Independent architecture audit of RSE-ARCH-1.2 by a reviewer who did not author it.** No implementation gate opens before that audit accepts the architecture and the owner/ChatGPT review agrees. No provisioning, purchase, key or secret creation, corpus, Qualification, model selection, GPU, spending or training is authorized, and `main` is not advanced.
