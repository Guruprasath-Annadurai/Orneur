# RSE-ARCH-1.1 — Part 6: fresh architecture self-attack and corrections to 1.0 claims

Paper attacks against 1.1 only; nothing was run against real systems. Result words: BLOCKED, DETECTED, CONTAINED, UNRESOLVED_DECLARED. (B12: the 1.0 report's claims were overstated; the column "1.0 claim" records the correction rather than rewriting history.)

| # | Attack | 1.0 claim | 1.1 result | Control / residual |
|---|---|---|---|---|
| 1 | Crown environment compromised, tokens intact | BLOCKED | CONTAINED | consumer re-render + dual token; owner rubber-stamping is residual |
| 2 | Forge compromised | "cannot decrypt" | CONTAINED | Forge sees plaintext in-window (R-I1) |
| 3 | Witness compromised after unlock | UNRESOLVED | UNRESOLVED_DECLARED | short window; rebuild and key rotation |
| 4 | TPM failure/denial | — | CONTAINED | recovery passphrase, rebuild |
| 5 | Firmware compromise | DETECTED on Mac | UNRESOLVED_DECLARED for Mac; CONTAINED for P1 Witness | owner-enrolled keys, PCRs |
| 6 | Stolen Witness PC / disk | BLOCKED | BLOCKED (at rest) | TPM+PIN+LUKS2 |
| 7 | Stolen token | CONTAINED | CONTAINED | second token, PIN, epoch |
| 8 | Malicious transfer medium | CONTAINED | CONTAINED | two-phase, OCR1, minimal verifier; verifier bug residual |
| 9 | Parser differential | not found | CONTAINED | single grammar, canonical re-encode; JSON removed from security positions |
| 10 | Ledger fork | DETECTED | DETECTED | witness consistency proofs |
| 11 | Ledger tail suppression | DETECTED | UNRESOLVED_DECLARED (bounded window) | checkpoint interval ≤ grant life |
| 12 | Rollback | BLOCKED | per-object table (Part 3 §W); Mac OS state UNSOLVED | |
| 13 | Replay | BLOCKED | BLOCKED | consumer nonce + consumption record |
| 14 | Old incident epoch | — | CONTAINED | epoch in grants; role must learn epoch from ledger |
| 15 | Malicious approved dependency | CONTAINED | UNRESOLVED_DECLARED for shared upstream | independent comparison |
| 16 | Poisoned recovery kit | CONTAINED | CONTAINED | re-root re-verification |
| 17 | Weights exfiltration (future) | not covered | CONTAINED by separate W grant | insider/owner residual |
| 18 | Qualification extraction (future) | not covered | CONTAINED by bit budget | long-run accumulation |
| 19 | Provider compromise (future) | not covered | UNRESOLVED_DECLARED | P2 decision |
| 20 | Common-owner error | UNRESOLVED | UNRESOLVED_DECLARED | drills; cannot be eliminated |

**Unresolved HIGH blockers after this round: none.** Every HIGH row is either CONTAINED/BLOCKED or declared in `RSE11_05` §AH. Freeze is *for audit*, not a claim of verification.
