# RSE-ARCH-1.1 — Part 5: profiles, novelty, hardware, phases, acceptance, residuals, next action

Sections AC–AI, plus complexity budget and future governance. Resolves blockers B1, B9, B10, B12 (with Part 6).

## AC. P0 / P1 / P2 re-evaluation

| Profile | Definition | Status |
|---|---|---|
| P0 | advanced one-Mac Tier0-S | **SYNTHETIC REHEARSAL ONLY.** Not authorized for a real private corpus: Forge, Crown and verification share one hardware root; Mac OS-state rollback is UNSOLVED; no owner-verifiable measured boot |
| P1 | Crown + Forge + independent physical Witness (TPM/Secure Boot/LUKS2/PIN) | **required target for the real-corpus path** |
| P2 | P1 plus attested confidential environment, provider-side key release, optional confidential GPU, spend controls, weights custody | **not required before the initial private corpus if P1 passes; required (or an equivalent the programme independently decides) before real training.** Open decisions: attested confidential environment; provider-side key release; confidential GPU (attestation must show CC-on; does not make training trustworthy); spend controls; model-weight custody |

## AD. Novelty classification

| Mechanism | Class |
|---|---|
| Hash-chained evidence | STANDARD |
| Witnessed checkpoints, consistency proofs | ADAPTED (C2SP/Sigsum) |
| Per-role head binding | ADAPTED (git signed-push certificate pattern) |
| TPM PCR-sealed disk key with PIN | STANDARD |
| NV-counter re-seal-on-bump | ADAPTED (TPM policy patterns) |
| OCR1 fixed-grammar envelope | STANDARD practice (fixed binary framing), ORNEUR-specific layout |
| Crown three-view grant rendering with consumer re-render | ORNEUR_SPECIFIC_COMBINATION |
| Separate W and D grants | ORNEUR_SPECIFIC_COMBINATION |
| Whole-architecture combination | UNVERIFIED_NOVELTY |

**Final novelty answer: `INSUFFICIENT_RESEARCH`.** Full texts of several lab frameworks, RAND and Intel/AMD/TCG documents were not read (see Part 1 §C). No claim of "world first" or "never implemented by another LLM" is made or implied.

## AE. Hardware dependency matrix

| Need | Crown | Forge | Witness (P1) | Note |
|---|---|---|---|---|
| Hardware security token(s) | 2 | — | — | |
| TPM 2.0 | — | — | required | |
| Secure Boot owner keys | — | — | required | |
| Radios removable/disableable | preferred | residual | required | Mac radios cannot be removed |
| IOMMU | — | — | preferred | |
| Dedicated machine | **minimum dedicated environment before corpus; independent device before Q/T** | existing Mac acceptable (P1) | required | |
| GPU | no | no | no | not authorized |

## AF. Implementation phases (planning only; none authorized)

1. Independent audit of RSE-ARCH-1.1.
2. Owner decision on P1 hardware (separate authorization).
3. IMPLEMENTED level: OCR1 codec and minimal verifier; Crown renderer and grant verifier; ledger checkpoint/witness tooling; Monitor-Lite; artifact repository tooling.
4. PROVISIONED: hardware inventory, Secure Boot enrolment, TPM sealing, keys (separate authorization).
5. TESTED: the §AG tests; adversarial verification.
6. Acceptance; then separate corpus approval.
7. P2 decisions before any training.

## AG. Acceptance specification

Maturity ladder unchanged from `../RSE_04` (DESIGNED → IMPLEMENTED → PROVISIONED → TESTED → ADVERSARIALLY_VERIFIED → ACCEPTANCE_COMPLETE); **"owner confirms" alone never validates a technical property.** Enforcement types: **CE** cryptographically enforced, **HE** hardware enforced, **SE** software enforced, **DET** detective, **PROC** procedural, **ADV** advisory, **UNP** unproven.

| ID | Property | Type | Component | Positive test | Negative / adversarial test | Evidence | Failure result | Recovery | Independently audited? |
|---|---|---|---|---|---|---|---|---|---|
| R01 | Grant cannot become ACTIVE on signature alone | CE+SE | consumer state machine | valid grant + inclusion proof + confirmation → ACTIVE | valid signature without checkpoint inclusion → refused | consumption-start record | refuse | quarantine | no |
| R02 | Consumer renders actual signed bytes | SE | consumer renderer | digest matches Crown | altered bytes → digest differs | rendered digests | owner rejects | revoke | no |
| R03 | OCR1 parse/re-encode identity | SE | minimal verifier | canonical input accepted | any mutation rejected; second implementation agrees on fuzz corpus | fuzz log | refuse | n/a | no |
| R04 | Sender authentication | CE | Witness verifier | enrolled Forge key accepted | wrong key/replayed sequence → rejected | verify log | refuse | quarantine | no |
| R05 | Key-absent Phase 1 | SE | ingestion | volume stays locked | attempt to unlock in Phase 1 fails | mount table | abort | reboot | no |
| R06 | Witness key release bound to boot state | HE | TPM policy | unlock after correct boot | wrong PCR, wrong PIN, altered UKI → denial | TPM error codes | denial | recovery passphrase | no |
| R07 | Rollback denial (Witness OS) | HE/CE | NV counter/signed version | current image boots | older signed image → key denied | counter value | denial | owner re-seal | no |
| R08 | Ledger fork/truncation detection | CE+DET | witness/cosigner | consistent growth cosigned | forked or shorter tree → witness refuses | witness log | quarantine | re-root if confirmed | no |
| R09 | Log-first authorization | SE | consumer | grant with proof accepted | grant without proof refused | refusal record | refuse | n/a | no |
| R10 | One outstanding state-changing grant per role | SE | consumer | second grant while first ACTIVE refused | concurrent grants → second refused | records | refuse | n/a | no |
| R11 | Offline network state | HE+DET | gate / radios | no interface up | cable inserted, radio enabled → gate fails | gate output | stop | rebuild if exposed | no |
| R12 | USB default-deny | SE | kernel policy | allow-listed medium works | unlisted device ignored | kernel log | ignore | n/a | no |
| R13 | IOMMU active | HE | firmware/kernel | IOMMU groups present | DMA from untrusted port blocked | dmesg | n/a | n/a | no |
| R14 | LUKS2 volume sealed at rest | CE | Witness | unlock only via release path | key absent → unreadable | header check | n/a | restore | no |
| R15 | Evidence identity | CE | role signature | record verifies | forged record fails | verify log | reject | n/a | no |
| R16 | Power-cycle behavior | SE | Witness | state clean after power cycle | no plaintext residue in persistent paths | file scan | wipe | n/a | no |
| R17 | Firmware-update recovery | PROC+HE | owner ceremony | update then re-seal succeeds | skipped re-seal → locked | PCR log | locked | recovery | no |
| R18 | Secure Boot keys are owner's | HE | firmware | only owner keys enrolled | vendor-signed image refused | key list | refuse | n/a | no |
| R19 | TPM quote verifies offline | CE | Crown | quote verifies | stale challenge/wrong PCR rejected | quote record | reject | n/a | no |
| R20 | Plaintext not on persistent channels | DET/BEST_EFFORT | storage checks | pre/post inspection clean | planted marker found by scan | scan report | stop | wipe | no |
| R21 | Single-owner confirmation integrity | PROC | drills | drill completed | tampered rendering caught in drill | drill record | n/a | n/a | no |
| R22 | Crown isolation | PROC+SE | Crown | inventory shows no agents/network | network attempt fails | inventory | n/a | rebuild | no |
| R23 | Artifact approval pipeline | PROC+CE | repository | independent comparison matches | single-upstream artifact rejected as non-independent | comparison record | reject | n/a | no |
| R24 | Re-root and recovery drills | PROC | Reliquary | drill rebuilds roles | missing paper path fails loudly | drill log | n/a | n/a | no |
| R25 | Qualification boundedness (future) | SE | chamber | within budget runs | over-budget run refused | budget counter | freeze | n/a | no |

"Independently audited?" is **no** for every row at this point; each becomes yes only after an auditor not involved in the build signs off.

## AH. Unproven properties and residual risks

| ID | Residual | Why |
|---|---|---|
| R-I1 | Forge plaintext exposure window | Forge must see plaintext to generate |
| R-N1/N2 | One-human administration of all ledger holders; tail suppression window | single-owner reality |
| R-W1 | Mac OS-state rollback UNSOLVED | no hardware monotonic reference for Mac environments |
| R-U1 | Firmware/LocalPolicy persistence on shared Mac hardware | one hardware root |
| R-U2 | No owner-verifiable measured boot on Mac | not found |
| R-U8 | Mac radios not removable | hardware |
| R-C1 | Crown and Forge may time-share a machine before the dedicated Crown device | cost sequencing |
| R-V1 | Minimal verifier bug | software |
| R-TPM | TPM bus sniffing, firmware TPM trust, NV counter attribute details unverified | PIN mitigates; hardware tests required |
| R-X1 | Shared upstream for builds | independent comparison reduces, not removes |
| R-O1 | Owner error, rubber-stamping, loss | cannot be eliminated |
| R-Q | Qualification and P2 properties unproven | future |
| R-RES | Research gaps (Part 1 §C) | retrieval limits |

## AI. Exact next authorized action

**Independent audit of RSE-ARCH-1.1** (read-only) against the 12 blockers and the acceptance register. No provisioning, purchase, key or secret creation, corpus, Qualification, model selection, GPU, spending or training is authorized. `main` is not advanced.

## Complexity budget

Seven components only: Crown, Forge, Witness, logical Vault, logical Evidence Ledger, offline Reliquary, external Monitor-Lite. A new role is admitted only if it owns a distinct trust root or capability boundary and the register gains at least one test that fails without it.

## Future God-mode governance (not implemented in RSE)

Doctrine: **SURPRISING IN CAPABILITY. PREDICTABLE IN TRUST.** Future work would add an online **Authority Broker** issuing bounded envelope grants with immediate revocation, multi-user enterprise identity, and separate authority families for tools/actions, memory access, browser/computer use, financial/spend, and external communication. The RSE grants (class, bindings, state machine, consumer confirmation, log-first) are the intended substrate. None of this exists, and none is authorized.
