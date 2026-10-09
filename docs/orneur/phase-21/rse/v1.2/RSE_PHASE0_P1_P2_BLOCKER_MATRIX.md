# RSE Phase 0 — real P1/P2 hardware and security blocker matrix

NON_NORMATIVE. Not in Manifest V3. No hardware was purchased, provisioned, or tested for this matrix. Synthetic passage is not a row closure.

Source: `RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` §1 and §4, `RSE12_03` as named by the freeze, and the labeled software in `orca/rse/imp3/journal.py` and `orca/rse/imp4/ocr1.py` on `da567d9` (unchanged on `f424dbf`). Authorization: purchase, provisioning, secrets, corpus, qualification, GPU, and training remain denied.

Column REAL_HW is the freeze column. "Blocks" means the freeze says the control is required before the named milestone. It does not mean a new software defect was found in this pass.

## P1 — required before a real private corpus

Witness requirements §1, classes M or D, are hardware or physical controls. None has an acceptance artifact in this tree. FACT: the freeze says no product is selected and nothing is bought. ASSUMPTION NOT MADE: no vendor, TPM model, or machine count is chosen here.

| Freeze row | What it requires | Software substitute in this tree | Blocks |
| --- | --- | --- | --- |
| §1.1–§1.25 M/D rows | Dedicated Witness machine, TPM 2.0, NV counter, owner Secure Boot, measured boot, LUKS2, radios and network absent or hardware-disabled, DMA/IOMMU, ME/OOB policy, USB default-deny, custody | None. `SyntheticFence` label is `SYNTHETIC_NOT_REAL_HARDWARE_PROOF`. | Real corpus (G4–G7 in the requirement register). |
| C22 | Key-absent Phase 1 leaves the vault locked. REAL_HW yes. | Not a vault. | P1 acceptance. |
| C23 | Plaintext sandbox: no key, no network, bounded I/O. REAL_HW yes. | `CHECKER_ISOLATION = SYNTHETIC_NOT_A_SANDBOX`. Linux CI is the software environment of record, not a sandbox. | P1 acceptance. |
| C24 | Vault key release bound to measured boot. HW. | Not implemented. | P1 acceptance. |
| C25 | NV fence denies an old image. HW. | Synthetic generation counter only. A caller who holds the fence object is not outside the process. | P1 acceptance. |
| C26 | NV update safe at every power cut. REAL_HW yes. Freeze maturity notes a simulator only. | `JournalSink` contract is in-process. No disk power-cut procedure was run. | P1 acceptance. |
| C27 | TPM or board replacement without rollback. REAL_HW yes. | No K-grant path. Class K raises `UNSUPPORTED_CURRENT_MILESTONE`. | P1 recovery. |
| C28 | Owner Secure Boot keys only. HW. | Not implemented. | P1 acceptance. |
| C29 | Offline quote against a pinned attestation key. REAL_HW yes. | Not implemented. | P1 acceptance. |
| C30 | DMA protection. HW. | Not implemented. | P1 acceptance. |
| C31 | USB default-deny. REAL_HW yes. | Not implemented. | P1 acceptance. |
| C32 | Radios absent or hardware-off. HW. | Not implemented. | P1 acceptance. |
| C33 | No usable network device. REAL_HW yes. | Not implemented. | P1 acceptance. |
| C34 | ME/OOB absent or disabled and owner-verifiable. HW. | Not implemented. | P1 acceptance. Disqualifies hardware that cannot meet it. |
| C35 | Firmware password and locked boot order. HW. | Not implemented. | P1 acceptance. |
| C36 | LUKS2 at rest. REAL_HW yes. | Not implemented. | P1 acceptance. |
| C37 | No plaintext on persistent channels. REAL_HW yes. | Not a storage scan of a real machine. | P1 acceptance. |
| C38 | Crown isolation inventory. REAL_HW yes. | No dedicated Crown. | P1 acceptance and Crown milestone 1. |

M1/M2 independence in software checks distinct enrolment bytes. FACT: tests use synthetic keys from `SYNTHETIC-RSE-BLOCK1-TEST-ONLY`. That is not two machines or two operators. It does not close §1.1.

## P2 — required before real training

| Freeze row | Statement | Status | Blocks |
| --- | --- | --- | --- |
| §6 | P2 or an equivalent training-security architecture is required before real training. No provider or GPU is selected. | Unchanged. | Training authorization. |
| Threat row "Cloud/provider compromise" | Attested environment, provider-side key release, spend caps. Residual: provider root of trust UNPROVEN. | No provider selected. `network_provider_inference_allowed` is false. | Training on hosted compute. |
| C46 | Qualification output quantization and bit budget. REAL_HW value in the table is `P2`. Maturity `DESIGNED (future)`. | Not implemented. | Qualification before training. |
| C47 | Qualification counters not rollbackable. TYPE `UNP`. REAL_HW `P2`. | Not implemented. | Qualification before training. |
| R-Q | P2 and Qualification counters UNPROVEN. | Freeze residual. | Training authorization. |
| R-EXF | P2 egress control for training blocks training authorization. | Freeze residual. | Training authorization. |
| §7.12–§7.14 | Chamber, then P2 acceptance, then training infrastructure, then Genesis training. Each authorization is separate. | Not started. | First official Genesis training run. |

## Security limits that stay open even if PR #8–#10 merge

These are software facts on `da567d9` / `f424dbf`. They are not new defects from this pass. They block a secure-environment claim, not the writing of this matrix.

- Recipient-local quarantine does not propagate to other roles. Class K cannot move `QUARANTINED` to `RECOVERY`.
- OFJ1 caps 8192 and 4096 are synthetic-stage ceilings, not a production lifetime.
- In-process objects are not role isolation.
- The base dependency scan does not cover pyhpke. The RSE lock audit on run `37893124711` reported no known vulnerabilities for cffi, cryptography 50.0.2, pycparser, and pyhpke 0.6.5. That is not a hardware or training audit.
- macOS is not the qualifying software environment. A `setrlimit` failure exits 71.

## Missing evidence

- No photograph, serial, TPM quote, PCR list, or purchase record.
- No independent hardware test log for any REAL_HW row.
- No owner authorization file whose status is anything other than not authorized.
- The freeze AUDIT column still says an independent audit is required. This matrix is not that audit.

## Safe next action

Keep G4–G12 closed. Do not select hardware, a provider, or a GPU. An independent reviewer can check this matrix against `RSE12_06` without running a machine.
