> `SUPERSEDED_BY_RSE_ARCH_1_2` — 1.1 was rejected for freeze on re-audit (four unresolved HIGH gaps: H1–H4). Its statements that all of B1–B12 are RESOLVED and that no HIGH remains (`RSE11_06`) are **withdrawn**; see `../v1.2/RSE12_00_INDEX_HISTORY_CLOSURE.md`.

# ORNEUR / Genesis V2 — RSE-ARCH-1.1 (architecture blocker remediation)

Package version **RSE-ARCH-1.1**, written 2026-10-07 against canonical `main` `0264242cb5ea544ca3eefc7c1ab4b4c7294f2de7`; remediates the 1.0 candidate `8fa4100d77636fc0e7382dbdcf748d9567b9396f`. Version 1.0 files are retained unchanged as history. **Everything here is DESIGNED.** `DECISION_9R_P1_INDEPENDENT_WITNESS_REQUIRED`; P0 is `SYNTHETIC_REHEARSAL_ONLY`. Authorizations unchanged: no provisioning, hardware purchase, secret creation, corpus generation, Qualification, model selection, GPU or training. `main` is not advanced.

## Files and A–AI map

| Item | Where |
|---|---|
| A Executive verdict; B Baseline; C Research; D Competitive matrix; E Threat model; F Trust roots | `RSE11_01` |
| G Sovereign plane; H Crown; I Forge; J Witness (+P1 requirements); K Vault; Q Attestation; R Keys; S Grants; V Role/grant state machines | `RSE11_02` |
| M Transfer; N Evidence ledger; O Monitor-Lite; U Storage lifecycle; W Anti-rollback | `RSE11_03` |
| L Qualification; P Reliquary/recovery; T Network; X Supply chain; Y Corpus custody; Z Weight custody; AA Compromise scenarios; AB Disaster recovery | `RSE11_04` |
| AC P0/P1/P2; AD Novelty; AE Hardware matrix; AF Phases; AG Acceptance; AH Residuals; AI Next action; complexity budget; future governance | `RSE11_05` |
| Self-attack and corrected 1.0 claims | `RSE11_06` |

No A–AI item is MISSING. Items that are future (L, T/W/D grants, P2) are marked as design-only and belong to the phase stated.

## Blocker closure

Format: BLOCKER → DESIGN CHANGE → EVIDENCE → RESIDUAL → STATUS. "RESOLVED" means resolved **at design level**, to be confirmed by independent audit; nothing is implemented or tested.

| # | Blocker | Design change | Evidence | Residual | Status |
|---|---|---|---|---|---|
| B1 | six A–AI areas missing | full A–AI package (this index) | map above | later-phase items marked | RESOLVED |
| B2 | Crown approval path insufficient | assumed-compromised daily-driver; three views; consumer re-render from actual signed bytes; field list; dedicated Crown roadmap (`RSE11_02` §H) | protocol steps, fields | owner rubber-stamping | RESOLVED |
| B3 | ledger vulnerable to its administrator | witnessed checkpoints, log-first, per-role binding, independent holders (`RSE11_03` §N) | holder table, common-mode list | one-human holders, tail window | RESOLVED |
| B4 | anti-rollback overclaimed | per-object table with honest classes; TPM NV design; Mac state UNSOLVED (`RSE11_03` §W) | table | Mac state; NV details unverified | RESOLVED |
| B5 | false two-party terminology | `DUAL_TOKEN_OWNER_CONFIRMATION`; distinctions stated (`RSE11_02` §H) | text | no independent reviewer exists | RESOLVED |
| B6 | transfer format/auth/parser defective | OCR1 grammar, sender signature, two-phase ingestion, minimal verifier, plaintext sandbox (`RSE11_03` §M) | scratch differential run: 20,000 cases, 0 disagreements between Python and JavaScript decoders; JSON NaN/duplicate-key differential shown | verifier bug; signature/AEAD not covered by the fuzz run | RESOLVED |
| B7 | no separate export/deployment authorization | W (export only) and D (release) grants, never implied (`RSE11_02` §S, `RSE11_04` §Z) | schemas | future | RESOLVED |
| B8 | Sentinel overbuilt | Monitor-Lite, secret-free (`RSE11_03` §O) | scope list | same-owner independence limit | RESOLVED |
| B9 | acceptance lacks enforcement classes/tests | register with enforcement type, positive and negative tests (`RSE11_05` §AG) | 25 rows | all tests unrun | RESOLVED |
| B10 | P1 Witness requirements incomplete | 24-row classed requirement spec tied to properties (`RSE11_02` §J) | table | hardware unverified | RESOLVED |
| B11 | Forge plaintext mis-described | Forge sees plaintext; lifecycle and window documented (`RSE11_02` §I) | lifecycle | R-I1 | RESOLVED |
| B12 | attack-report claims overstated | corrected claims table (`RSE11_06`) | table | — | RESOLVED |

## Research status

Closure pass: tpm2-tools policy/NV pages, Azure and Google confidential GPU pages, OpenTimestamps, SLSA, Sigsum read; `SOURCE_UNAVAILABLE`: TCG library specification (HTTP 403), Intel TDX overview (HTTP 403), AMD SEV-SNP white paper (empty body). Anthropic RSP, DeepMind and RAND full texts were not read. Novelty answer: `INSUFFICIENT_RESEARCH`.
