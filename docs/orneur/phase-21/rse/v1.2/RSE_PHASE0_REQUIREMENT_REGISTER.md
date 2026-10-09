# RSE Phase 0 — requirement register

NON_NORMATIVE. Not in Manifest V3. This file does not amend RSE-ARCH-1.2, does not authorize training, and does not accept the programme.

## Scope label

FACT: No repository file contains the title "ORNEUR Master Development and Model-Training Readiness Plan". A search of `docs/` found no that phrase. Historical "Phase 0" documents under `docs/orneur/phase-0/`, `docs/MASTER_PLAN.md`, and `docs/LAUNCH_PLAN.md` are earlier product plans. They are not this register.

ASSUMPTION: In this assignment, Phase 0 means the documentation gate that lists mandatory pre-training criteria and records what is actually true. It does not mean those historical plans, and it does not execute roadmap steps 6–14 in `RSE12_06` §7.

Normative source for the criteria below is frozen `docs/orneur/phase-21/rse/v1.2/RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` §6–§8, plus the authorization JSON files. Those freeze files were not edited.

## Phase 0 work items

| ID | Requirement | Status of this pass | Evidence class |
| --- | --- | --- | --- |
| P0-1 | Canonical requirement register | Drafted in this file | Author draft. Not independently verified. |
| P0-2 | PR #8–#10 dependency assessment | Drafted in `RSE_PHASE0_PR8_PR10_DEPENDENCY_ASSESSMENT.md` | `gh pr view` and `gh run view` on 2026-10-09. |
| P0-3 | Real P1/P2 hardware and security blocker matrix | Drafted in `RSE_PHASE0_P1_P2_BLOCKER_MATRIX.md` | Freeze rows plus labeled synthetic code. Not a hardware test. |
| P0-4 | Facts separated from assumptions | Applied in all three files | Method, not a test result. |
| P0-5 | No merge of PR #8, #9, or #10 | Held | All three `state=OPEN`, `mergedAt=null`. |
| P0-6 | No spend, provisioning, corpus, qualification, GPU, or training | Held | Lock files still `NOT_AUTHORIZED` / `REGISTERED_NOT_AUTHORIZED`. Code functions return false. |

## Mandatory pre-training criteria

These are the freeze roadmap gates. Phase 0 does not close them. Maturity in the freeze acceptance register is `DESIGNED` unless a row says otherwise, and every AUDIT cell in that register is `yes` with the freeze sentence "nothing is audited yet" (`RSE12_06` §4). Later software work did not edit that sentence.

| ID | Criterion (source) | Required before | Current status |
| --- | --- | --- | --- |
| G1 | Independent architecture audit by a non-author (`RSE12_06` §7.1, §8) | Any later gate | Not re-performed in this pass. FACT: the freeze file still names this as the next action. |
| G2 | Architecture freeze on canonical main | Implementation that claims the freeze | FACT: main is `464b602f3f259b56f139c3304828baa660e6b860`. Manifest V3 is unchanged by this pass. |
| G3 | Software implementation and its own independent code audit (`RSE12_06` §7.4–§7.5) | Calling the software gate canonical | FACT: PR #8–#10 are open and unmerged. See the dependency assessment. This is not G3 closed. |
| G4 | P1 hardware selection under a separate purchase authorization (`RSE12_06` §7.6) | Real corpus | NOT AUTHORIZED. No purchase recorded in this tree. |
| G5 | P1 provisioning and key creation (`RSE12_06` §7.7) | Real corpus | NOT AUTHORIZED. `NO_PROVISIONING_AUTHORIZED`. `NO_REAL_SECRET_CREATION`. |
| G6 | P1 acceptance of real-hardware C-rows and adversarial verification (`RSE12_06` §7.8) | Real corpus | NOT DONE. Synthetic tests are not this row. |
| G7 | Crown milestone 1: dedicated Crown before any real corpus (`RSE12_06` §7.9) | Corpus grant | NOT DONE. |
| G8 | Real corpus authorization as a grant (`RSE12_06` §7.10) | Corpus generation | FACT: `CORPUS_GENERATION_AUTHORIZATION.json` status `NOT_AUTHORIZED`. `corpus_generation_authorized()` returns false. |
| G9 | Crown milestone 2 before Qualification or training (`RSE12_06` §7.11) | Qualification, training | NOT DONE. |
| G10 | Qualification chamber accepted (`RSE12_06` §7.12) | Training | NOT AUTHORIZED. Runner registry state `REGISTERED_NOT_AUTHORIZED`. |
| G11 | P2 attested environment, egress control, counters, spend controls (`RSE12_06` §7.13; residual R-EXF) | Training authorization | UNPROVEN in the freeze. R-EXF "blocks training authorization". |
| G12 | Training infrastructure, then Genesis training, each its own authorization (`RSE12_06` §7.14) | First official training run | NOT AUTHORIZED. `training_authorized()` returns false. `MODEL_EVAL_AUTHORIZATION.json`: `gpu_allowed` false, `max_spend_usd` 0, status `NOT_AUTHORIZED`. |

`RSE12_06` §6, quoted as the rule this register uses: P0 is synthetic rehearsal only. P1 (Crown, Forge, and an independent Witness) is required before the real private corpus. P2, or an equivalent training-security architecture, is required before real training. No provider or GPU is selected or authorized.

## What this register refuses to say

- Synthetic RSE tests are not P1 acceptance, P2 acceptance, corpus readiness, or training readiness.
- `SyntheticFence` is not TPM NV. The keyless checker is not a sandbox. In-process monitors are not independent witnesses.
- Copying a verdict string into a non-normative note is not an auditor signature. See the dependency assessment.
- IMP-5 and IMP-6 are not authorized by Phase 0.

## Independent review

This register is an author draft. Independent verification has not been done. Programme acceptance is not issued.
