# RSE-03 — Architecture attack report, revisions and freeze

Attacks were run against the working draft (v0, the first complete design before this round) as paper attacks: each one traces an attacker through the design and states which control stops, detects, contains or fails to stop it. **No attack was executed against any real system; nothing exists to execute against.** The result of this round is a revised design (RSE-ARCH-1.0, `RSE_02`) and a list of declared unresolved risks.

Result words: BLOCKED (the attacker's goal is not reached), DETECTED (reached but visible), CONTAINED (reached but bounded), UNRESOLVED_DECLARED (not stopped; stated in §3).

## 1. Attack table

| ID | Attack | Path against v0 | Result against RSE-ARCH-1.0 | Revision it forced |
|---|---|---|---|---|
| A1 | Compromised daily-driver forges an approval | v0 let the daily-driver present and sign grants with a token; a compromised host shows one thing and requests another | BLOCKED for Class G, Q, T, K: approval only in Crown; digest compared on the consuming role's display; tokens never inserted elsewhere. Class V is also Crown-signed | **R1** daily-driver demoted to propose-only; Crown environment and dual display added |
| A2 | Stolen or abused token | stolen token plus observed PIN; or a plugged-in token tapped for the wrong message | CONTAINED: PIN and touch; two tokens and time separation for G, Q, T, K; revocation by epoch; Sentinel flags unlogged signatures | **R2** thresholds and cool-off added per class |
| A3 | Common-mode trust failure | one macOS kernel, one firmware, one Secure Enclave, one human, one git host | P0: UNRESOLVED_DECLARED (U1, U2, U3); P1: reduced for the Witness by a second platform family and TPM sealing | **R3** platform diversity (M19) and Witness hardware separation made the central reason to reopen Decision 9 |
| A4 | Replay of a grant | resubmit a captured grant | BLOCKED: challenge issued by the role for the session; single-use journal; ledger CONSUMPTION | none (already in v0), strengthened by challenge binding |
| A5 | Rollback of role state or ledger | restore an older drive image or ledger so an old grant is unspent | BLOCKED by `prev_head` binding and epoch; detected by counterparty memory | **R4** `prev_head` added to every grant |
| A6 | Malicious artifact (bundle exploits a parser) | v0 relied on key-absent parsing; the same bytes were re-parsed with the key present | CONTAINED: complex parsing key-absent in W1; reboot to baseline; key-present step is a minimal fixed-format verifier | **R5** minimal verifier (M25) and two-phase Witness added; v0's claim was wrong because the exploit would trigger again at unlock |
| A7 | Stale authorization | use a grant after the situation changed | BLOCKED: nonce-bound session; window; epoch; incident state in cosign | **R6** Sentinel as independent clock and policy cosigner (offline roles have no trusted clock) |
| A8 | Counterfeit environment | an environment that prints the expected gate result | P1 Witness: BLOCKED by TPM sealing (key does not release); Mac environments: DETECTED only by human pin and Env-ID registration; self-measurement is SELF_ATTESTED | **R7** SELF_ATTESTED label (L8); no Mac claim of attestation; residual U2 |
| A9 | Compromised transfer medium | media carries a filesystem or parser exploit | CONTAINED: raw container, no filesystem, validators A and B, key-locked W1 | R5; **R8** single-use media, evidence-only return medium |
| A10 | Compromised dependency | upstream wheel or tool poisoned | CONTAINED by hash-pinned vendored sets, two builders, minimal verifier; **UNRESOLVED_DECLARED** if both builders share the compromised upstream (U4) | **R9** reproducible two-builder release (M17); fake independence of shared upstream recorded |
| A11 | Stolen SSD | physical theft of a role drive | BLOCKED for confidentiality: boot volume holds no secrets; secret volume separately encrypted; Witness TPM plus PIN in P1; corpus secret rotation on loss | none |
| A12 | Evidence fork | a compromised actor keeps two histories | DETECTED: counterparty countersignature, external anchors, head binding kills the fork at the next grant | **R10** two-sided records and external anchoring in place of a local-only chain |
| A13 | Secret persistence | plaintext or key left behind (swap, snapshots, history, clipboard, crash dumps) | CONTAINED: storage control register in `RSE_04` C27; plaintext only in RAM; baseline restore | none in design; execution proof is a TESTED requirement |
| A14 | Network activation | a role goes online mid-phase | DETECTED, not prevented: gate at phase start and end; router canary; radios cannot be removed on the Mac (U8); P1 Witness chosen without radios | **R11** gate at both ends, canary added; honest residual |
| A15 | Cross-boot persistence | malware survives into a later environment | CONTAINED for software: baseline restore and sealed system volumes; **UNRESOLVED_DECLARED** for firmware, LocalPolicy or internal-drive persistence on shared Mac hardware (U1) | R3 |
| A16 | Recovery poisoning | rebuild kit or golden image is poisoned so rebuilds are compromised | CONTAINED: kit built twice, threshold-signed manifest, pin checked by a human, kit held offline | **R12** rebuild kit moved into Reliquary with its own drill |
| A17 | Compromised role (each of nine) | any role is hostile | CONTAINED: §11 of `RSE_02`; no role holds two of generate, decrypt, approve, record | none |
| A18 | Sentinel not independent | the same owner account controls the monitor and the anchor | PARTIAL: separate account with its own token required; roles check the Sentinel policy digest embedded in the cosignature | **R13** Sentinel redefined as secret-free monitor and cosigner; independence limits declared (U5) |
| A19 | Rubber-stamping and single-human two-party control | the owner approves without reading; the second signature is the same person | UNRESOLVED_DECLARED (U3); mitigated by dual display, cool-off, templates, Sentinel check | R2 |
| A20 | Malicious owner or coercion | the owner is the adversary | OUT OF SCOPE; not a goal of Tier0-S or P1 | — |

## 2. Revisions made (v0 → RSE-ARCH-1.0)

R1 daily-driver demoted; Crown environment. R2 thresholds and time separation. R3 platform diversity as a requirement. R4 `prev_head` in grants. R5 minimal key-present verifier and two-phase Witness. R6 Sentinel as clock and policy cosigner. R7 SELF_ATTESTED labeling. R8 single-use media and evidence-only return. R9 two-builder reproducible release. R10 two-sided, externally anchored evidence. R11 gate at both ends and a router canary. R12 rebuild kit in Reliquary with a drill. R13 Sentinel holds no secrets.

## 3. Declared unresolved risks (not hidden; none is a design contradiction)

| ID | Risk | Profiles affected | Why not resolved | Bound |
|---|---|---|---|---|
| U1 | Firmware, LocalPolicy or internal-drive persistence on shared Mac hardware | P0 all roles; P1 Crown and Forge | needs a second machine per role to remove; Secure Enclave and internal drive are shared | P1 removes it for the Witness; out of the stated adversary for the rest |
| U2 | No owner-verifiable boot measurement for Apple-silicon environments | P0, P1 Crown and Forge | not found in the sources read (`RSE_01` §3) | self-reported state only; human pin and Env-ID registration compensate partially |
| U3 | One human on both sides of two-party control | all | single-owner reality | protects against a hijacked session or stolen token, not against the owner |
| U4 | Shared upstream for both builders and both validators | all | `cryptography` and the language runtime are one supply chain | vendoring, hash pinning, minimal verifier; second-language validator is a future requirement |
| U5 | Sentinel and external anchor administered by the same owner | all | single-owner reality | separate accounts with their own tokens; policy digest check |
| U6 | External anchoring is detective for offline roles | all | offline roles cannot query a log | head binding converts detection into a block at the next grant |
| U7 | Witness host compromise in memory after unlock | all | key present in RAM during verification | short exposure window, no network; regenerate under new keys |
| U8 | Wi-Fi and Bluetooth radios cannot be removed from the Mac | P0, P1 Crown and Forge | hardware | gate, canary, procedure; P1 Witness hardware chosen without radios |
| U9 | Qualification Chamber and GPU confidential-compute design not verified to depth | P2 | out of this phase's scope and research depth | marked FUTURE, no claim |
| U10 | Several mechanisms unverified on real hardware: ephemeral state restore on macOS, Ed25519 PIV attestation, TPM sealing on the chosen PC, Secure Enclave-held Env-ID keys | P0, P1 | no hardware chosen or provisioned | each is a TESTED-level acceptance item (`RSE_04`) |
| U11 | Research gaps listed in `RSE_00` | all | retrieval limits | flagged, no claim depends on them as established |

## 4. Capability theatre removed

Removed or refused because they did not improve a named security property: a separate Vault environment, a separate Transfer Chamber environment, FROST, blockchain anchoring, multiple clouds, a Sentinel that holds secrets, hardware-wallet displays (not researched), and any wording that treats a Mac self-measurement as attestation.

## 5. Freeze statement

**RSE-ARCH-1.0 is frozen for independent audit.** Every attack above is either resolved by a revision, contained to a stated bound, or declared in §3. No unresolved item contradicts a design law. Frozen does not mean verified: the design is DESIGNED only. A later change to any law, role, key, grant field, transfer step or profile requires a new version and a new attack round. If the audit finds a blocker, the version number changes.
