# Block-1 audit package — Part 1: requirement-to-evidence matrices (IMP-2, IMP-3, IMP-4)

`NON_NORMATIVE_AUDIT_EVIDENCE`. Written by the independent reviewer before any IMP-2/3/4 code exists. No rule is invented: every row names its normative source in the canonical tree at `464b602…` (governing set: RSE-ARCH-1.2, Clarification 1, Freeze Amendment, Manifest V3). Where the frozen text is silent the row says so and points to an open question (`OAQ-n`, Part 6). Status values: `PENDING_IMPLEMENTATION_EVIDENCE` (nothing to judge yet) or `EXISTS_IN_IMP1` (accepted code already covers it).

**Source abbreviations.** `RSE12_02` = `v1.2/RSE12_02_WITNESS_LEDGER_FRESHNESS.md`; `RSE12_03` = `…ROLLBACK_TPM.md`; `RSE12_04` = `…OCR1_GRANTS_ENROLMENT.md`; `RSE12_05` = `…CUSTODY_RECOVERY_SUPPLY_NETWORK.md`; `RSE12_06` = `…P1_ACCEPTANCE_OPERATIONS.md`; `CL1` = `clarification-1/RSE12_CLARIFICATION_1_CANDIDATE.md`; `FRZ` = `RSE_ARCH_1_2_ARCHITECTURE_FREEZE.md`; `RSE11_03` = incorporated sections "Two-phase key-absent ingestion" and "Plaintext handoff"; `C##` = acceptance-register row in `RSE12_06` §4.

**Milestone mapping (assumption, see OAQ-1).** The frozen text does not define the labels IMP-2/3/4. This package follows the assignment: IMP-2 = grant lifecycle, consumption, crash and ceilings; IMP-3 = Evidence Ledger, witness/checkpoint, freshness and replay journal; IMP-4 = OCR1 v2 transport, HPKE/Ed25519 and the keyless plaintext checker.

## B. IMP-2 — grant lifecycle and authority

| ID | Requirement | Normative source | Evidence required for acceptance | Status |
|---|---|---|---|---|
| M2-01 | Grant states and exact transitions: PROPOSED → OWNER_VERIFIED → SIGNED → APPENDED → CHECKPOINT_CREATED → REQUIRED_WITNESS_ACKNOWLEDGED → CHECKPOINTED → DELIVERED → CONSUMER_CONFIRMED → ACTIVE → CONSUMED → EVIDENCE_PENDING → COMPLETE; side states EXPIRED, REVOKED, QUARANTINED, INTERRUPTED | RSE12_02 §2, §7 | Exhaustive (state × event) test: only the table's transitions succeed; every other pair is refused and leaves state unchanged | PENDING_IMPLEMENTATION_EVIDENCE |
| M2-02 | Forbidden transitions (PROPOSED/SIGNED/APPENDED → ACTIVE; CHECKPOINT_CREATED → DELIVERED; DELIVERED → ACTIVE; EXPIRED/REVOKED/COMPLETE → ACTIVE; QUARANTINED → anything but RECOVERY handling; training-complete → W; W-complete → D) | RSE12_02 §2 | One negative test per listed pair | PENDING |
| M2-03 | A valid signature alone never makes a grant ACTIVE; SIGNED ≠ executable | RSE12_02 §2 | Test: signed grant without witnessed checkpoint stays unusable (C11) | PENDING |
| M2-04 | One outstanding state-changing grant per role | RSE12_02 §2 | Second grant refused until the first is COMPLETE/INTERRUPTED/EXPIRED/REVOKED | PENDING |
| M2-05 | Consumer confirmation conditions: layout and class; signatures; registry checks; challenge equals outstanding; target role and measurement; epoch/authority/registry floors; `prev_role_checkpoint` an ancestor with only non-state-changing records since; inclusion proof against a checkpoint carrying all required cosignatures; typed SAS and Intent Sheet where required | RSE12_02 §2 (DELIVERED → CONSUMER_CONFIRMED) | One failing-condition test per clause; IMP-1 covers the registry, role, environment and challenge clauses | PARTLY EXISTS_IN_IMP1 |
| M2-06 | Consumption-start record fsynced **before** any secret release | RSE12_02 §2, §7 | Crash-injection test between journal append and release; ordering proven by a recording fake | PENDING |
| M2-07 | Freshness by consumer-issued challenge: one outstanding per role, new voids old, valid until consumed or superseded, no wall clock | RSE12_02 §5 | Replay, supersession and reuse tests (T2-04…T2-08) | PENDING |
| M2-08 | `not_after` is advisory: checked only before activation, may only make a role refuse | RSE12_02 §5, §8; C10 | Clock set back/forward changes no acceptance outcome except extra refusal | PENDING |
| M2-09 | Crash table: DELIVERED resumes; CONSUMER_CONFIRMED needs re-confirmation; ACTIVE never resumes → INTERRUPTED, outputs discarded, sequences forfeited; EVIDENCE_PENDING re-commits evidence only; inconsistent journal → QUARANTINED | RSE12_02 §7; C15 | Kill-at-every-step test; "operation never runs twice" proven by a side-effect counter | PENDING |
| M2-10 | Write-ahead journal fsynced before each transition | RSE12_02 §7 | Journal replay reconstructs state; torn-write test | PENDING |
| M2-11 | No wall-clock kill after ACTIVE; bounded by monotonic `max_runtime_s`, byte and batch ceilings, spend and run ceilings | RSE12_02 §8; RSE12_04 §8 | Ceiling-bypass tests (T2-15…T2-19) | PENDING |
| M2-12 | Revocation in flight handled by ceilings and INTERRUPTED at next boot, not by clock | RSE12_02 §8 | Power-off/restart test | PENDING |
| M2-13 | Exact registry-snapshot binding; a registry change makes the old grant permanently unusable and voids the challenge | CL1 §11; RSE12_01 §3 | Snapshot mismatch tests incl. stale challenge after update (IMP-1 covers function-level) | EXISTS_IN_IMP1 (function level); lifecycle level PENDING |
| M2-14 | Incident epoch in every grant; lower epoch rejected; incident voids outstanding challenges (re-root step 0) | RSE12_04 §8; RSE12_05 §4.3 | Epoch downgrade and stale-challenge-after-incident tests | PENDING |
| M2-15 | Role lifecycle SEALED → PRE_FLIGHT → AUTHORIZED → SECRET_RELEASED → ACTIVE → SEALING → EVIDENCE_COMMIT → SEALED; MAINTENANCE, QUARANTINED, RECOVERY, REVOKED; listed impossible transitions | RSE12_02 §9; C45 | Exhaustive transition test | PENDING |
| M2-16 | Target-role matrix: G → FORGE (recipient WITNESS); V → WITNESS (sender FORGE) | CL1 §16 | Wrong-role, wrong-ROLE_ID, type-confusion tests | EXISTS_IN_IMP1 (validation) |
| M2-17 | Consumer binds own `ROLE_ID` and observed environment; challenge equality additional | CL1 §16 | Mismatch tests | EXISTS_IN_IMP1 |
| M2-18 | Dual-token thresholds: V needs 1 token; G, K, Q, T, W, D, R need 2 distinct | RSE12_04 §8; C08, C44 | Single, duplicate and wrong-domain signature tests | EXISTS_IN_IMP1 |
| M2-19 | K, Q, T, W, D, R remain unsupported/fail-closed until their milestone passes independent review | CL1 §14 | Every deferred class returns `UNSUPPORTED_CURRENT_MILESTONE` through every public entry point added by IMP-2 | EXISTS_IN_IMP1; new entry points PENDING |
| M2-20 | Training completion never implies W; W never implies D | RSE12_04 §8; FRZ §5 | Only the "no implication" negative is testable now | PENDING |
| M2-21 | Envelope grants: completed-batch count in the journal; remainder forfeited after a crash | RSE12_02 §7 | Crash mid-envelope test | PENDING |
| M2-22 | Resource ceilings never default to unlimited; zero is a cap of zero | RSE12_01/CL1 §6.1 | Boundary tests: cap−1, cap, cap+1, 0, u32/u64 max | EXISTS_IN_IMP1 (validation) |

## C. IMP-3 — Evidence Ledger, witnessing, freshness, replay journal

| ID | Requirement | Normative source | Evidence required for acceptance | Status |
|---|---|---|---|---|
| M3-01 | Holder kinds LH, XH, OC, M1, M2 and the independence rule (a single compromise must not control both holders) | RSE12_02 §1 | Design review plus a test that two holders sharing a key/process are not counted as independent | PENDING |
| M3-02 | Required signatures by event: routine grant LH ∧ M1; K/Q/T/W/D/R and registry updates touching ENROLMENT, ROLE_IMAGE, POLICY, FOUNDATION_MODEL or epoch raise LH ∧ M1 ∧ M2 (K and epoch raise also OC); phase completion LH ∧ M1; recovery LH ∧ M1 ∧ M2 ∧ OC | RSE12_02 §1 table | Table-driven test over every event class | PENDING |
| M3-03 | Monitor-Lite is a REQUIRED_WITNESS, secret-free, signs no grants, refuses forks, smaller trees and same-size different roots | RSE12_02 §1; C13 | Witness-service tests T3-01…T3-06 | PENDING |
| M3-04 | Witness verifies: role signature, enrolment APPROVED, size ≥ last cosigned, consistency proof, same-size same-root, epoch ≥ floor; sees only hashes | RSE12_02 §1 | One negative per check | PENDING |
| M3-05 | Log-first sequence: a grant is consumable only after its own checkpoint carries all required acknowledgements | RSE12_02 §2; C11 | Test: later checkpoint is not a substitute (T3-07) | PENDING |
| M3-06 | Record formats: `OCK1` 181 bytes, `OCP1` 2315 bytes, `OCA1`, `OCH1` (incl. `next_sequence`, `role_log_head`), `OCI1` | RSE12_02 §3 | Round-trip and exact-length tests; independent decoder agreement | PENDING; layout gaps → OAQ-3 |
| M3-07 | `packet_seq` strictly increasing per (source, witness); replayed request is idempotent; ack valid only for its (log, size, root, epoch) | RSE12_02 §3 | Replay, regression and mismatched-ack tests | PENDING |
| M3-08 | Carried medium: raw block device, fixed-size records, public data only, fixed-size reads, no filesystem mounting on Crown/Witness | RSE12_02 §3 | Malformed-medium tests; no-mount assertion | PENDING |
| M3-09 | Witness unavailable: grants stay at CHECKPOINT_CREATED, no clock expiry, no fewer-witness mode; M2 takes over only after a K handover holding M1's last head | RSE12_02 §3 | Outage test; downgrade attempt refused | PENDING |
| M3-10 | Result egress: Witness Phase 1 requires RESULT leaf + inclusion proof + checkpoint with required cosignatures; ACCEPTED_PENDING_WITNESS until acceptance checkpoint is cosigned; E1/E2 exceptions only | RSE12_02 §4 | Un-witnessed "success" bundle refused (C14) | PENDING |
| M3-11 | `OCH1` challenge: pre-issued at phase end, at most one outstanding, produced via the RFC 8937 wrapper keyed with the role key, carries `next_sequence` and `role_log_head` | RSE12_02 §3, §5 | Challenge lifecycle tests; wrapper KAT | PENDING |
| M3-12 | `prev_role_checkpoint` must be an ancestor of the current head with only non-state-changing records after it | RSE12_02 §2 | Stale-head tests, incl. record-kind classification | PENDING; record-kind list → OAQ-4 |
| M3-13 | External time (`witness_time`, optional timestamp anchoring) is detective only, never a freshness gate | RSE12_02 §6; C10 | Tests that manipulating `witness_time` changes no authorization | PENDING |
| M3-14 | Anti-rollback classes per object (ledger checkpoint, registry, revocation state, grant nonce): witness refuses smaller or forked tree; routine-grant replay after in-state rollback is a declared residual | RSE12_03 §1, §2 | Rollback, fork and tail-suppression tests with a witness model | PENDING |
| M3-15 | Equivocation: any holder seeing two cosigned roots for one (log, size) quarantines that log | RSE12_02 §1 | Two-root injection test | PENDING |
| M3-16 | Replay journal / consumed set persisted, not caller-supplied | RSE12_02 §5, §7; IMP-1 residual N-2 | N-2 closure tests (Part 4) | PENDING |
| M3-17 | Highest authenticated registry version derived from witnessed registry updates and sealed floors, not from a parameter | CL1 §11; IMP-1 residual N-2 | Same | PENDING |
| M3-18 | Registry updates are owner-signed records effective only when witnessed | RSE12_01 §3; RSE12_02 §1 | Unwitnessed update not effective | PENDING |
| M3-19 | Floor = max(card, sealed, witnessed, fence) and recovery never lowers it | RSE12_01 §6; RSE12_05 §4.2 | Lowering attempts refused | PENDING |
| M3-20 | Per-role ledger is an append-only Merkle log with signed checkpoints (size, root, log id, epoch) | RSE12_02 §1, §3 (and non-incorporated `RSE11_03` §N history) | Append-only and consistency-proof tests | PENDING; **tree profile and leaf formats are not frozen → OAQ-2** |
| M3-21 | TPM NV fence and sealed-state binding | RSE12_03 §3; C25–C26 | Needs real P1 hardware or a TPM simulator | OUT_OF_SOFTWARE_SCOPE_FOR_THIS_BLOCK (record only) |

## D. IMP-4 — OCR1 v2, HPKE/Ed25519, keyless checking

| ID | Requirement | Normative source | Evidence required for acceptance | Status |
|---|---|---|---|---|
| M4-01 | Profile: HPKE RFC 9180 base mode; DHKEM(X25519, HKDF-SHA256) 0x0020; HKDF-SHA256 0x0001; ChaCha20Poly1305 0x0003; Ed25519 pure; SHA-256; **one HPKE context per bundle**, one `Seal` per frame | RSE12_04 §2 | Library conformance report; RFC 9180 Appendix A vectors reproduced by the chosen library | PENDING; **library API risk → Part 3, OAQ-5** |
| M4-02 | Header 210 bytes: magic, version 2, type, recipient, sender, grant, artifact, bundle digest, sequence, epoch, frame index/count, total length, `enc`; no reserved bytes, flags, extensions or optional fields | RSE12_04 §3 | Independent decoder agreement over the vector set | PENDING |
| M4-03 | Ciphertext length derived (never transmitted); `FRAME_PT` = 1 MiB; count = ⌈total/FRAME_PT⌉; ≤ 65536 frames; total ≥ 1 | RSE12_04 §3 | Boundary tests: total 1, FRAME_PT, FRAME_PT+1, 65536×FRAME_PT, +1 | PENDING |
| M4-04 | Canonical `enc`: 32 bytes, non-zero, top bit clear, < 2²⁵⁵−19; decode-then-re-encode equals input | RSE12_04 §3, §6(b) | N10, N11 vectors | PENDING |
| M4-05 | `info = "OCR1v2-info"‖0x00‖hdr[0:162]‖hdr[166:178]`; AAD = full header; signature message `"OCR1v2-SIG"‖0x00‖header‖ciphertext` | RSE12_04 §4 | KATs P1/P2 (frames must be byte-identical for the same fixed ephemeral input); N04, N05 | PENDING |
| M4-06 | Ephemeral key via RFC 8937 wrapper: `ikm = Expand(Extract(SHA256(Ed25519_Sign(sk, tag1)), G(32)), tag2, 32)`; `tag1 = "OCR1v2-EPH"‖0x00‖sender_id‖env_digest`; `tag2 = grant_id‖seq‖counter`; the signature never exposed; the path used (wrapper or declared fallback) recorded in evidence | RSE12_04 §5; FRZ §5 | Wrapper KAT (vector file `ephemeral_wrapper`); fallback recorded if library gives no caller-IKM | PENDING |
| M4-07 | Nonce/key uniqueness: key depends on `info`; frame index is the HPKE sequence; recipient keeps a seen-`enc` set; repeated `enc` under a different digest quarantines the sender | RSE12_04 §7 | Duplicate-`enc` test (stateful) | PENDING |
| M4-08 | Phase 1 (key absent): length/fields, canonical `enc`, recipient = self, sender resolves to an APPROVED enrolled Forge, V grant names sender/artifact/sequence range and epoch, **Ed25519 signature verified before any key use**, frame-set rules; copy to quarantine, hash, detach | RSE12_04 §6; RSE11_03; C21, C22 | N01–N03, N06, N08–N11, N13–N20, N22 and the secret volume stays locked | PENDING |
| M4-09 | Phase 2 (key present): decapsulate (abort on all-zero shared secret), `Open` in order, reassemble, `SHA-256(plaintext) = bundle_digest`, length check, stream to a bounded pipe | RSE12_04 §6 | N04, N05, N07, N12, N21 | PENDING |
| M4-10 | Parsers executing with the key present: HPKE decap, AEAD open, digest compare only; no structured-data parsing of attacker-influenced bytes | RSE12_04 §6 | Code review and import audit of the key-present module | PENDING |
| M4-11 | Frame-set rules: missing, duplicate, reordered, extra, truncated-final, cross-bundle frames rejected | RSE12_04 §7; C19 | N30–N36 | PENDING |
| M4-12 | Replay: strictly increasing `sequence` per stream stored by recipient; consumed challenge; epoch | RSE12_04 §7 | Stateful tests S01–S04 | PENDING |
| M4-13 | Sender/recipient IDs are hashes of enrolment entries; unknown/REVOKED IDs rejected; rotation = new ID | RSE12_04 §6; CL1 §6.2 | N09; enrolment lookup tests | PENDING |
| M4-14 | V grant carries no bundle digest; the digest must equal the sender's witnessed RESULT leaf for that sequence | RSE12_04 §6(d), §8; RSE12_02 §4 | Digest-mismatch test with a witnessed RESULT fixture | PENDING |
| M4-15 | Plaintext handoff: key-holding decryptor → bounded pipe/IPC → **keyless** sandboxed checker; no network; controlled temp workspace; strict CPU/memory/output bounds; defined output set | RSE11_03 "Plaintext handoff"; C23 | T4-30…T4-36 on a real sandbox (not a mock) | PENDING; **sandbox mechanism unspecified → OAQ-6** |
| M4-16 | Staged encrypted output from Forge has `ZERO_ACCEPTANCE_AUTHORITY` until witnessed RESULT is verified; plaintext never leaves Forge or the Witness | FRZ §5; RSE12_02 §4 | Accept-before-witness refused at every downstream entry point | PENDING |
| M4-17 | No implementer may hand-roll HPKE, X25519 KEM internals, HKDF, ChaCha20-Poly1305, Ed25519 or the hedging; if the library lacks the safe API use the standard construction and record the residual | FRZ §5; RSE12_04 §1 | Dependency review; grep for custom primitives; recorded residual R-RNG1 | PENDING |
| M4-18 | Strict Ed25519: reject non-canonical S; enrolled keys only | RSE12_04 §9 | N22 | PENDING |
| M4-19 | Legacy transfer/store paths (`store.py`, `tier0a_transfer_bundle`) must not be reused for OCR1 v2 | RSE12_04 §1 rationale; PR #6 characterization | Import graph shows no reuse | PENDING |
