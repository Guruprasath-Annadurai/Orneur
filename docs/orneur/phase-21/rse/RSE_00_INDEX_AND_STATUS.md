# ORNEUR / Genesis V2 — Advanced Real Secure Environment (RSE) architecture package

Package version: **RSE-ARCH-1.0 (frozen for independent audit)**. Written 2026-10-07 against repository SHA `0264242cb5ea544ca3eefc7c1ab4b4c7294f2de7`.

**This package is a design. Nothing in it is provisioned, implemented or tested.** Every authorization stays locked: `NO_PROVISIONING_AUTHORIZED`, `NO_HARDWARE_PURCHASE_AUTHORIZED`, `NO_SECRET_CREATION_AUTHORIZED`, `NO_CORPUS_GENERATION_AUTHORIZED`, `NO_QUALIFICATION_AUTHORIZED`, `NO_MODEL_SELECTION_AUTHORIZED`, `NO_GPU_AUTHORIZED`, `NO_TRAINING_AUTHORIZED`. A design status of `DESIGNED` is never permission.

## Files

| File | Content |
|---|---|
| `RSE_00_INDEX_AND_STATUS.md` | this file: scope, requirement mapping, research limits, honest status |
| `RSE_01_RESEARCH_AND_COMPARISON.md` | sources, established facts, comparison matrix, mechanism classification (STANDARD / ADAPTED / ORNEUR_SPECIFIC_COMBINATION / POTENTIALLY_NOVEL / UNVERIFIED_NOVELTY) |
| `RSE_02_ARCHITECTURE.md` | design laws, trust families, roles, daily-driver challenge, key hierarchy, grants, transfer, evidence, one-control-failure analysis, compromise recovery, lifecycle, realization profiles, Decision 9 reopening analysis, ten diagrams |
| `RSE_03_ATTACK_REPORT.md` | the attack round, the revisions it forced, declared unresolved risks, freeze statement |
| `RSE_04_ACCEPTANCE_SPECIFICATION.md` | maturity ladder DESIGNED → ACCEPTANCE_COMPLETE and the per-control evidence required |

## Requirement mapping

The owner message referred to a "full A–AI architecture package" of detailed requirements. **That package was not present in any message or transcript available to this session**, so it could not be used. This package is therefore built from the fifteen numbered requirements of the approval message and the thirteen items of the locked ORNEUR directive. If an A–AI heading list exists, it should be cross-mapped against the table below in the audit.

| Requirement | Where it is met |
|---|---|
| Current external research (req. 1, directive 13) | `RSE_01` |
| Design the strongest architecture first, then map to Tier0-S / Tier0-A / hardware / later tier (req. 2) | `RSE_02` §13–§15 |
| Classify every major feature STANDARD … UNVERIFIED_NOVELTY, no unsupported claim (req. 3, directive 1, 13) | `RSE_01` §5–§6 |
| ONE_CONTROL_FAILURE_ASSUMPTION for every sensitive operation (req. 4, directive 2) | `RSE_02` §10 |
| Daily-driver treated as potentially compromised (req. 5) | `RSE_02` §5 |
| Crown, Forge, Witness, Vault, Qualification Chamber, Transfer Chamber, Evidence Ledger, Sentinel, Reliquary (req. 6, directive 3) | `RSE_02` §4 |
| Compromise recovery as a primary property, per role (req. 7, directive 7) | `RSE_02` §11 |
| Cryptographically bound short-lived authority, designed not created (req. 8, directive 5) | `RSE_02` §7 |
| Future God-mode ecosystem governance (req. 9, directive 9–12) | `RSE_02` §16 |
| No capability theatre, simplify (req. 10, directive 11) | `RSE_02` §2, `RSE_03` §4 |
| Diagrams and state models (req. 11) | `RSE_02` D1–D10 |
| Attack report before freeze (req. 12) | `RSE_03` |
| Acceptance specification separating DESIGNED / IMPLEMENTED / PROVISIONED / TESTED / ADVERSARIALLY VERIFIED / ACCEPTANCE_COMPLETE (req. 13) | `RSE_04` |
| Every authorization stays locked (req. 14) | this file, all other files |
| No production change (req. 15) | only documents under `docs/orneur/phase-21/rse/` |
| Boot-bound trust (directive 4) | `RSE_02` §14 |
| Controlled transfer (directive 6) | `RSE_02` §8 |
| Evidence before authority (directive 8) | `RSE_02` §9 |

## Research limits (stated so the audit can weigh the claims)

Research was run on 2026-10-07 from primary pages where retrievable. Not retrievable or not read, so claims that depend on them are marked secondary or unverified:

- OpenAI's "Reimagining secure infrastructure for advanced AI": the primary page returned a trust-portal redirect; only secondary summaries were read.
- RAND `RRA2849-1` full report page returned HTTP 403; the research-brief excerpt and PDF excerpts were read, not the full text. A RAND SL3 report (Aug 2026) appeared in related-content listings and was not read.
- Anthropic's Responsible Scaling Policy full text was not read; the ASL-3 activation post and report were searched, not read end to end.
- Google DeepMind's Frontier Safety Framework: blog excerpts only.
- Apple PCC security guide pages other than the blog posts did not render usable text.
- Not researched at all: AMD SEV-SNP and Intel TDX primary documents, Sigsum, OpenTimestamps, hardware-wallet style signing displays, Heads/coreboot, macOS-specific attestation beyond Apple's Managed Device Attestation guide.
- Several parallel search calls were rate-limited (HTTP 429) and were retried or replaced.

Consequence: no claim in this package is "novel" in an evidenced sense. `RSE_01` §6 states exactly what can and cannot be said.

## Honest status in one paragraph

The design is internally consistent after one attack-and-revise round (`RSE_03`). Its strongest conclusion is uncomfortable: **the diversity-of-trust requirement cannot be met well on a single Apple-silicon machine.** Tier0-S can carry a reduced subset. The design recommends reopening Decision 9 and choosing between (i) a two-machine minimum (`P1`) and (ii) an explicitly weaker single-machine fallback (`P0`). That is a recommendation, not a decision, and no purchase is authorized.
