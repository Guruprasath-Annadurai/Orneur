# Block-1 audit package — Part 5: pre-audit risk register (I)

`NON_NORMATIVE_AUDIT_EVIDENCE`. Severity is the impact **if realized** in the delivered system. The **Basis** column keeps proven facts apart from conjecture:

- `PROVEN` — reproduced or directly verified this session (how is stated).
- `CARRY_FORWARD` — accepted earlier finding awaiting its closure milestone.
- `HYPOTHETICAL` — an attack scenario derived from the design; no code exists to confirm it.
- `OPEN_QUESTION` — the frozen text is silent; a ruling is needed before implementation can be judged.

No CRITICAL defect is proven. Nothing in IMP-2/3/4 can be judged defective yet because none of it has been delivered.

## CRITICAL (impact if realized)

| ID | Basis | Requirement | Threat | Exploitation path | Expected prevention | Required negative test | Acceptance condition |
|---|---|---|---|---|---|---|---|
| R-C01 | HYPOTHETICAL | Keys/secrets only synthetic (all locks) | Real or real-looking key, token or credential committed or baked into an image | Developer convenience, test fixture, Docker layer | Synthetic labelled seeds only; secret scans in the gate script | `audit_gate_checks.sh` privacy step plus manual `docker history` / env review | zero findings |
| R-C02 | HYPOTHETICAL | Phase 1 is key-absent; Phase 2 parses nothing structured (RSE12_04 §6) | Attacker-controlled parser runs while the private key is in memory | Phase 1 shortcuts that unlock the volume early; Phase 2 module imports a parser | Structural separation; recording fake; static import audit | T4-21, T4-23 | proof the key never exists during Phase 1 |
| R-C03 | HYPOTHETICAL | K/Q/T/W/D/R fail closed (CL1 §14) | A new entry point in IMP-2/3/4 returns success for a deferred class | Lifecycle code that treats "signed + witnessed" as enough | Single success gate; deferred-class refusal in every public function | T2-12 over every new public function | none reaches success |
| R-C04 | HYPOTHETICAL | Plaintext never leaves Forge/Witness (FRZ §5) | Plaintext or key written to logs, temp files, crash dumps, pipes to the wrong process | Debug logging, exception text with payload | Scan of logs/temp after tests; bounded pipe only | scan with planted marker (C37) | marker absent everywhere outside RAM |

## HIGH

| ID | Basis | Requirement | Threat | Exploitation path | Expected prevention | Required negative test | Acceptance condition |
|---|---|---|---|---|---|---|---|
| R-H01 | **PROVEN** (library inspection + experiment) | RSE12_04 §1/§2/§3: HPKE context per bundle, AAD = header, RFC 8937 hedge, library must reproduce RFC Appendix A | The in-repo HPKE API (`cryptography` 49) is single-shot: no AAD, no context, no caller IKM, cannot reproduce Appendix A | Cursor either mis-implements OCR1 on that API or silently changes the layout | architect ruling OAQ-5 before IMP-4 acceptance | T4-01, T4-14 | chosen library reproduces vectors through the API the code uses |
| R-H02 | **PROVEN, legacy** (9 characterization tests in open PR #6 executed here: pass) | W/D separation (RSE12_04 §8, RSE12_05 §2) | A completed checkpoint can be promoted to PRODUCTION without any T, W or D grant in the legacy model registry | Existing `orca.registry` path | Out of this block; must not be relied upon; closes at the model-custody milestone | n/a for IMP-2/3/4; IMP-2 must not claim W/D | no acceptance row marks W/D separation satisfied while this stands |
| R-H03 | **PROVEN, legacy** (same tests) | Evidence Ledger independence (RSE12_02 §1) | Legacy `AccessLedger.verify_chain` misses tail deletion, rollback and fork without an external head | Disk-level access to the SQLite file | Witnessed checkpoints (IMP-3) | T3-01…T3-05 | rollback/fork/tail suppression detected by the witness model |
| R-H04 | **PROVEN, legacy** | Sender authentication; parse-after-auth (RSE12_04) | Legacy `_seal_blob` authenticates no sender; `_open_blob` parses header JSON before AEAD with no length cap; duplicate keys are last-wins | Any holder of the public key; malformed header | OCR1 v2 is a separate path; legacy store stays unauthorized for real data | T4-24 (no reuse) | no reuse; legacy path not referenced by the new code |
| R-H05 | **PROVEN, legacy** | Authority check (RSE12_01) | Legacy `authorization.verify` does not call `authority_for_request` | Existing authorization module | closes outside this block | none here | not used by IMP-2/3/4 |
| R-H06 | OPEN_QUESTION | Ledger tree and leaf definitions (RSE12_02 §1, §3) | Cursor invents the log's Merkle profile, leaf serialization, proof algorithms, `prev_checkpoint_digest` function and RESULT/consumption leaf layouts; the accepted code then freezes an ad hoc transparency protocol | Implementation convenience | OAQ-2/OAQ-3: clarification record first | T3-19, T3-23, KAT agreement with an independent decoder | each invented constant has a ruling |
| R-H07 | HYPOTHETICAL | Log-first (RSE12_02 §2) | A checkpoint cosigned for an older/other log, size, root or epoch is accepted as the grant's acknowledgement | Missing equality checks on (log, size, root, epoch) | exact-match check at the consumer | T3-07, T3-08 | all variants refused |
| R-H08 | HYPOTHETICAL | Journal-before-release (RSE12_02 §2, §7) | Secret released before the consumption-start record is durable → double execution after a crash | Ordering bug, buffered write | Write-ahead + full sync before release | T2-13, T2-21 | counter shows ≤ 1 execution under every kill point |
| R-H09 | HYPOTHETICAL | Phase 2 uses exactly the verified bytes (RSE12_04 §6) | Quarantine copy modified (or re-read from the medium) after signature verification | Local attacker, medium swap | Hold the verified buffer or re-hash | T4-22 | mutation detected |
| R-H10 | HYPOTHETICAL | Keyless checker (RSE11_03) | "Sandbox" is a mock or an in-process function; key reachable | Test-friendly stub | Real process/namespace isolation with no key, network or secrets | T4-30…T4-36 | checks pass against the real boundary |
| R-H11 | HYPOTHETICAL | Result gating (RSE12_02 §4) | Un-witnessed Forge output accepted or used for Q/T | Convenience path | `ZERO_ACCEPTANCE_AUTHORITY` at every downstream entry | T3-20, T3-21, T4-37 | every entry refuses |
| R-H12 | HYPOTHETICAL | Dual-token / threshold (RSE12_04 §8) | New lifecycle code accepts one token for a two-token class or accepts duplicates | Shortcut around IMP-1 verifier | Reuse the accepted verifier only | T2 signature set | refused |
| R-H13 | HYPOTHETICAL | Equivocation (RSE12_02 §1) | Witness accepts two roots for one size; holders never compare | Missing store of last cosigned head | Per-log last-cosigned record; cross-holder comparison | T3-02, T3-03 | quarantine on divergence |
| R-H14 | HYPOTHETICAL | Replay (RSE12_04 §7) | Recipient accepts the same bundle twice or reuses a sequence consumed by an interrupted grant | State not persisted across restart | durable per-stream sequence; forfeit rule | S01, S03 | refused after restart |

## MEDIUM

| ID | Basis | Requirement | Threat | Exploitation path | Expected prevention | Required negative test | Acceptance condition |
|---|---|---|---|---|---|---|---|
| R-M01 | HYPOTHETICAL (platform fact) | Durable journal on the Forge platform | On macOS ordinary `fsync` does not flush the drive cache; full sync needs `fcntl(F_FULLFSYNC)`; the journal may lose records after power loss | Power loss between append and release | Use full-sync call on macOS; document Linux guarantees | T2-25, T3-28 | durable ordering evidence or a declared platform limitation |
| R-M02 | HYPOTHETICAL | Runtime ceiling by a monotonic timer (RSE12_02 §8) | Monotonic clock paused during sleep or adjustable; ceiling not enforced | Suspend/resume, clock change | Test across sleep/resume; use the platform's non-adjustable clock | T2-16 | ceiling holds |
| R-M03 | OPEN_QUESTION | Signature domains for `OCK1`/`OCH1` (RSE12_02 §3) | No frozen domain; shared Ed25519 role key across checkpoint, challenge and frame signing | Cross-protocol signature reuse | Frozen domains (OAQ-3) | T3-24 | domains frozen and tested |
| R-M04 | HYPOTHETICAL | Seen-`enc` set persistence (RSE12_04 §7) | Set lost on restart → nonce-reuse detection fails | State not persisted | Durable set tied to the stream | S02 | persistent |
| R-M05 | HYPOTHETICAL | Bounded allocation (RSE12_04 §3) | Header claims huge `total_len`/`frame_count` → memory/CPU exhaustion in Phase 1 | Attacker-controlled medium | Reject before allocating beyond one frame | T4-19, T4-20 | bounded |
| R-M06 | HYPOTHETICAL | Frame-set rules (RSE12_04 §7) | Cross-bundle frame accepted because only signatures are checked | Valid signature on a foreign bundle's frame | Equality of all fixed fields and `enc` across frames | N35 | rejected |
| R-M07 | HYPOTHETICAL | Strict Ed25519 | Library accepts non-canonical S or small-order keys | Signature malleability | Strict verification; enrolled keys only | N22 | rejected |
| R-M08 | CARRY_FORWARD (declared residual R-RNG1) | RFC 8937 hedging needs caller IKM | No library allows it; plain CSPRNG; weak RNG exposes plaintext | RNG failure on the Forge | Record which path was used; detect repeated `enc` | wrapper KAT or recorded fallback | path recorded in evidence |
| R-M09 | HYPOTHETICAL | New third-party dependency (e.g. pyhpke) | Unaudited crypto library enters the TCB | Dependency addition | Registry entry, pinned hash, source review, conformance gate | dependency review | complete record before use |
| R-M10 | HYPOTHETICAL | Envelope accounting (RSE12_02 §7) | Batch counter reset after crash → extra batches | Journal bug | Forfeit remainder | T2-18 | forfeited |
| R-M11 | HYPOTHETICAL | One outstanding grant per role (RSE12_02 §2) | Concurrent confirmation race | Two threads/processes | Atomic claim in the journal | T2-06 with concurrency | exactly one wins |
| R-M12 | HYPOTHETICAL | M1/M2 independence (RSE12_02 §1) | Test or deployment places both witnesses and a role on one host/key and calls it independent | Docker lab shortcuts | Independence flagged in evidence | T3-29 | not claimed independent |
| R-M13 | HYPOTHETICAL | Test quality | Fuzz/property tests assert tautologies or exercise only signature failure (non-re-signed mutants) | Green count without coverage | Re-signed mutants + oracle; mutation testing of defences | independent campaign | coverage shown |
| R-M14 | HYPOTHETICAL | Docker lab | False-assurance claims, shared volumes, docker.sock, unpinned images | Lab convenience | Part 4 §H checklist | review | no HIGH item |
| R-M15 | OPEN_QUESTION | Milestone scope (OAQ-1) | Cursor implements semantics outside IMP-2/3/4 or leaves a required area to "later" | Unclear mapping | Scope table agreed in advance | scope review | matches mapping |

## LOW

| ID | Basis | Requirement | Threat | Exploitation path | Expected prevention | Required negative test | Acceptance condition |
|---|---|---|---|---|---|---|---|
| R-L01 | CARRY_FORWARD | N-1 | Stale grant forces challenge re-issuance | Replay of old signed grant | OAQ-7 ruling; evidence + rate limit or narrowing | R-N1-01…06 | per Part 4 |
| R-L02 | CARRY_FORWARD | N-2 | Caller-owned replay state | Fresh ledger object / lower highest version | Authoritative journal wrapper | R-N2-01…07 | per Part 4 |
| R-L03 | CARRY_FORWARD | Display completeness for deferred classes (K, Q, T, D) | Owner cannot see all signed fields | Deferred milestones | Complete before those classes become executable | display tests | at the K/Q/T/D milestones |
| R-L04 | **PROVEN, pre-existing** (identical in canonical-main CI) | Dependency hygiene | `diskcache` 5.6.3 (PYSEC-2026-2447), `setuptools` 79.0.1 (PYSEC-2026-3447, fixed in 83.0.0) | Base-install packages; not imported by `orca.rse` | Upgrade/justify separately | scan output | tracked; not an IMP-2/3/4 blocker unless newly imported |
| R-L05 | HYPOTHETICAL | Reason-string drift | Error reasons differ between implementations | Interop | Tests check outcome and phase, not strings | n/a | n/a |

## INFORMATIONAL

- IMP-1 verifier remains the only accepted authority function; IMP-2/3/4 must wrap it, not duplicate it.
- The accepted IMP-1 tests use the same RNG/seed pattern as this package's fixtures; fixtures must stay obviously synthetic.
- Hardware rows (`C24`–`C35`) cannot be satisfied by any software block; they stay `PENDING_REAL_HARDWARE`.
