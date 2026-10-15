# Hardware, Trust-Root and Custody Options — Decision Package (Workstream H)

Status: **NON_NORMATIVE decision aid. BLOCKED on founder decisions. Nothing is purchased, provisioned, signed or keyed by this document.**
It does not amend RSE-ARCH-1.2, Manifest V3, R65, C27 or G1, and it never substitutes software or cloud mechanisms for physical isolation.
Sources: `docs/orneur/phase-21/infrastructure/` (owner-decisions, cost model, Tier0-S isolation, secret custody). Dollar figures are the order-of-magnitude estimates already recorded there, not quotes.

## 1. Where things stand (facts)

| Item | State |
|---|---|
| Tier0-A (two physically independent machines) | `TIER0_A_BLOCKED_SECOND_MACHINE_REQUIRED` |
| Tier0-S (sequential single machine) | Reduced-assurance fallback only (`TIER0_S_REDUCED_ASSURANCE_ONLY`); needs explicit founder risk acceptance (Decision 9, OPEN). Never equivalent to Tier0-A. |
| Owner/authority key | Not provisioned. Policy: private key MUST remain owner-controlled and non-cloud-resident at every tier. |
| Acceptance ledger / trust snapshot / root state | Committed empty baseline; engine accepts 0 rows |
| Hardware purchase | None made or authorized |

## 2. Assurance ladder (from the repository's own isolation document)

Tier0-B (concurrent single-host containers) < Tier0-S (sequential isolated environments, cold boot between roles) < Tier0-A (two physically independent machines).

**Tier0-S cannot protect against:** a malicious owner/root on the one machine, firmware/boot-chain compromise, physical machine compromise, persistence planted across both environments. Its separation depends on owner-performed physical procedures (cold boot, physical detachment) that no software enforces.

## 3. Options

Each option states what it satisfies, what it does not, and whether it needs a formal architecture-change request (ACR). **None of these is recommended as a silent replacement of a frozen requirement.**

| ID | Option | One-time cost (recorded estimate) | Satisfies physical-isolation requirement? | Needs ACR? | Status |
|---|---|---|---|---|---|
| H1 | **Add a second owner-controlled machine** (low-cost mini-PC) for Tier0-A Forge/Witness separation | ~$150–500 | **Yes** (physically independent machines) | No | BLOCKED_OWNER (purchase) |
| H2 | Tier0-S on the existing single Mac with owner-supplied encrypted external environments | $0 plus external drive ~$50–150 | **No** (reduced assurance, no adversarial-owner isolation) | **Yes** (accepting Tier0-S in place of Tier0-A) | BLOCKED_OWNER (Decision 9) |
| H3 | Hardware security key for the owner signing key (YubiKey-class) | ~$25–55 | Complements H1/H2; does not replace machine separation | No | BLOCKED_OWNER (purchase) |
| H4 | Physically owner-held local HSM (Tier 2 only) | varies | Complements; cloud KMS for the owner key is **not permitted** | No | BLOCKED_OWNER |
| H5 | Cloud-isolated Forge/Witness accounts (Tier 1) | ~$17–100/month recorded | **No** — cloud account separation is not physical isolation | **Yes** | BLOCKED_OWNER + ACR |
| H6 | Hybrid: owner key local/hardware, ciphertext in cloud object storage, compute separated by account | Tier 1 costs plus H3 | Partial; key custody stays physical, compute isolation is not | **Yes** for any isolation claim | BLOCKED_OWNER + ACR |
| H7 | Software-only separation (users/containers/gates) | $0 | **No** | Not eligible to replace any requirement | Rejected as a replacement |

**Engineering position (a proposal, not a decision):** H1 + H3 is the only combination that meets the frozen physical-isolation posture with no change to the architecture. H2/H5/H6 each weaken a stated requirement and must travel as a *formal architecture-change request* signed by the founder, reviewed by a person who did not author RSE-ARCH-1.2 (G1), before any of them is relied on.

## 4. Formal architecture-change request template (for H2, H5, H6)

```
ACR-ID:                  ACR-<n> (to be assigned by the founder)
Requirement affected:    <exact RSE-ARCH-1.2 / R65 / C27 clause>
Current mechanism:       <physical isolation as frozen>
Proposed mechanism:      <option>
What is lost:            <named threats no longer mitigated>
Compensating controls:   <list, each independently testable>
Residual risk accepted:  <founder statement, signed on the owner plane>
Reviewer (not author):   <name / UNRESOLVED_EXTERNAL>
Effect on acceptance:    none until reviewed; register rows stay as they are
```
Blocked until the founder files it. Engineering will not mark any register row accepted on the strength of an ACR.

## 5. Training hardware (separate from trust-root hardware)

The repository's decision package prices GPU evidence runs at roughly USD 6–9 for the pilot evidence set (×1.5 contingency). That is a *rental* estimate, not a purchase, and **no GPU is authorized**. Training compute can be added only after: foundation selection, V2 freeze, trust-root qualification and explicit founder authorization (FINAL-2, EXEC-1). No hardware purchase is proposed to meet the Nov 5 engineering deadline.

## 6. What the founder must decide (ordered)

1. Tier0-A (buy H1) vs. accepting Tier0-S risk via ACR (Decision 9).
2. Whether to buy the hardware key (H3) — cheapest highest-leverage control.
3. A monthly budget ceiling only if any Tier 1 option is considered (Decision 7).
4. Name an independent G1 reviewer who did not author RSE-ARCH-1.2.
5. Who holds the owner signing key and where (never cloud KMS).

Nothing here changes any gate, score or register row.
