# Block-1 audit package — Part 2: independent adversarial test specifications

`NON_NORMATIVE_AUDIT_EVIDENCE`. These are **executable specifications**, not tests of any code yet. They are written from the frozen text; expected outcomes name their basis. At review time the auditor writes a thin adapter around the delivered code (contract at the end) and runs them. "Oracle" says where the expected value comes from so it never comes from the implementation under audit.

Conventions: `FAIL_CLOSED` = refusal with no state change unless the row says otherwise. Every negative test must also prove the **negative control**: the same scenario with the defence disabled or the input made valid must succeed, so a test cannot pass by always failing. Mutation-style check: for each defence, temporarily neutralising it in a scratch copy must make at least one test fail.

## E1. IMP-2 — lifecycle, replay, revocation, crash, ceilings

| ID | Attack | Procedure | Expected (basis) | Oracle |
|---|---|---|---|---|
| T2-01 | Skip a state | For every (state, event) pair not in the frozen table, attempt the event | refused; state unchanged (RSE12_02 §2) | transition table typed in from the spec, independent of the code's table |
| T2-02 | Forbidden direct jumps | PROPOSED/SIGNED/APPENDED→ACTIVE, CHECKPOINT_CREATED→DELIVERED, DELIVERED→ACTIVE, EXPIRED/REVOKED/COMPLETE→ACTIVE, QUARANTINED→SEALED | each refused | spec list |
| T2-03 | Valid signature, no witness | Sign and deliver a G grant whose checkpoint lacks M1 acknowledgement | never CONSUMER_CONFIRMED/ACTIVE (C11) | spec §2 |
| T2-04 | Grant replay | Consume a grant, present the same bytes again | refused: challenge consumed | spec §5 |
| T2-05 | Stale challenge | Issue new challenge, present grant bound to the superseded one | refused | spec §5 (new voids old) |
| T2-06 | Two outstanding grants | Deliver second state-changing grant to a role with one in flight | second refused | spec §2 |
| T2-07 | Revoked grant | Epoch raise or revocation record after DELIVERED, then confirm | refused (REVOKED) | spec §2 |
| T2-08 | Advisory expiry abuse | Set role clock far past `not_after` after ACTIVE; set it back before activation | no kill after ACTIVE; clock never extends validity; before activation a late clock may only refuse | spec §5, §8 |
| T2-09 | Registry changed under a grant | Update registry between DELIVERED and CONSUMER_CONFIRMED | grant unusable; challenge voided; fresh flow requires new challenge | CL1 §11 |
| T2-10 | Same root different version / same version different root | Hand-build both | refused | CL1 §11 |
| T2-11 | Identity confusion | Present a grant for another ROLE_ID, a different environment measurement, a revoked or below-floor enrolment | refused for each | CL1 §16 |
| T2-12 | Class confusion | Flip class byte; re-sign G fields as another class; reuse V fields in G | refused; deferred classes `UNSUPPORTED_CURRENT_MILESTONE` | CL1 §14 |
| T2-13 | Duplicate execution after crash | Kill at: after journal append; after secret release; mid-operation; after result, before evidence | ACTIVE crash → INTERRUPTED, never resumed; EVIDENCE_PENDING re-exports only; side-effect counter ≤ 1 | spec §7 |
| T2-14 | Crash recovery attacks | Corrupt/truncate/rewind the journal; delete it; replace with an older copy | QUARANTINED (inconsistent) or detected; never silently ACTIVE | spec §7 |
| T2-15 | Ceiling bypass: bytes/batches | cap−1, cap, cap+1, 0, 2⁶⁴−1 | cap and below pass; others refused | policy caps (CL1 §6.1) |
| T2-16 | Ceiling bypass: runtime | Run past `max_runtime_s` using a monotonic timer; suspend/resume; clock jumps | operation ends in SEALING at the ceiling regardless of wall clock | spec §8 |
| T2-17 | Ceiling bypass: spend/run counters | integer overflow, negative, bool, float, NaN-like inputs | refused | codec widths |
| T2-18 | Envelope abuse | Consume batch N+1 of an N-batch envelope; crash mid-envelope and resume | refused; remainder forfeited | spec §7 |
| T2-19 | Resource ceilings default | Omit/zero a ceiling | zero means zero, never unlimited | CL1 §6.1 |
| T2-20 | Role lifecycle skips | SEALED→ACTIVE, PRE_FLIGHT→SECRET_RELEASED, ACTIVE→SEALED (skip SEALING/EVIDENCE_COMMIT), QUARANTINED→SEALED, REVOKED→any | each refused | spec §9 |
| T2-21 | Secret released before journal | Fake secret store; inject failure of fsync | no release when the consumption-start record is not durable | spec §2 |
| T2-22 | W/D implication | After a T-complete record try to start W; after W-complete try D | refused; separate grants only | spec §2 hard rule |
| T2-23 | Exception paths | Inject exceptions inside each guard (parse, verify, journal, clock) | FAIL_CLOSED, state not advanced, never CONSUMER_CONFIRMED | fail-closed rule |
| T2-24 | Aliasing/mutation | Mutate caller-held byte buffers, lists, mappings after submission | validated objects unchanged | IMP-1 immutability standard |
| T2-25 | Persistence durability on macOS | Verify the journal uses full-sync semantics (`F_FULLFSYNC`) on the Forge platform | durable ordering holds under power-cut simulation or documented platform limitation | platform fact (Part 5 R-M01) |

## E2. IMP-3 — ledger, witness, freshness, replay journal

| ID | Attack | Procedure | Expected (basis) | Oracle |
|---|---|---|---|---|
| T3-01 | Ledger rollback | Present the witness an older, validly signed checkpoint (smaller size) | witness refuses (never accepts a smaller tree) | RSE12_02 §1 |
| T3-02 | Fork | Two different roots at the same size, both role-signed | second refused; log QUARANTINED (equivocation) | §1 |
| T3-03 | Equivocation across holders | Show M1 root A and M2 root B for the same (log, size) | the holder that sees both quarantines | §1 |
| T3-04 | Tail suppression | Role drops its last N records and checkpoints a shorter-but-consistent tree | witness refuses (shrink); holder comparison detects | §1, RSE12_03 §1 |
| T3-05 | Delete from the middle | Remove a leaf and recompute roots | consistency proof from last cosigned size fails | §1 |
| T3-06 | Reorder / backdate | Swap leaves; change `witness_time` or role clock | proof fails; time never changes authorization | §1, §6 |
| T3-07 | Missing witness acknowledgement | Deliver grant with M1 ack for an older checkpoint, or for a different log/size/root/epoch | refused: ack must be for the checkpoint containing the grant | §2, §3 |
| T3-08 | Forged/stale ack | Wrong witness key, wrong domain (`OCA1-SIG`), replayed ack of another log | refused | §3 |
| T3-09 | Insufficient quorum | Irreversible event with M1 only; recovery without OC | refused | §1 table |
| T3-10 | Witness unavailable | Disable M1 | grants stay CHECKPOINT_CREATED; no timeout acceptance; no fewer-witness mode | §3 |
| T3-11 | M2 takeover | Switch to M2 without a K handover holding M1's last head | refused | §3 |
| T3-12 | Replay-journal reset | Delete, truncate, reload an old journal; construct a fresh journal object | consumed challenges stay consumed or the reset is detected at next witnessing; never silently usable | N-2 closure |
| T3-13 | Challenge reuse | Reuse consumed challenge; reuse after crash; reuse across roles | refused | §5 |
| T3-14 | Registry-version rollback | Present registry v(n−1) after v(n) was witnessed | refused; floor = max(card, sealed, witnessed) | RSE12_01 §6; RSE12_03 §1 |
| T3-15 | Unwitnessed registry update | Owner-signed update without M1 (or M2 where required) | not effective | RSE12_01 §3; RSE12_02 §1 |
| T3-16 | Incident-epoch downgrade | Grant with epoch below the sealed/witnessed epoch | refused | RSE12_04 §8 |
| T3-17 | Stale incident state | Role offline during epoch raise; present pre-incident grant after incident | outstanding challenge was voided (maintenance step) → refused | RSE12_05 §4.3 step 0 |
| T3-18 | `prev_role_checkpoint` stale | State-changing record appended after the referenced head | grant refused (stale); non-state-changing records tolerated | §2 |
| T3-19 | Forged/wrong inclusion proof | Proof for a different leaf, different size, truncated path, extra hashes | refused | §3 (OCI1) |
| T3-20 | Result egress without witness | Bundle with RESULT leaf not in a cosigned checkpoint; checkpoint cosigned by M1 for another log | refused; corpus stays ACCEPTED_PENDING_WITNESS | §4; C14 |
| T3-21 | Acceptance before witnessing | Use an ACCEPTED_PENDING_WITNESS corpus in a Q/T grant or registry approval | refused | §4 |
| T3-22 | Medium attacks | Malformed carried medium: bad header, wrong record count, oversize record, filesystem present | refused using fixed-size reads only; no mount | §3 |
| T3-23 | OCP1 abuse | `proof_count` > 64, unused slots non-zero, `old_tree_size` > size, negative-like values | refused | §3 |
| T3-24 | OCA1/OCK1 domain confusion | Present a role signature as a witness ack and vice versa | refused (needs frozen domains, OAQ-3) | §3 |
| T3-25 | Monitor secret-free | Search the monitor code/config for key material, grant-signing capability, corpus access | none present | §1 |
| T3-26 | Replay of witness requests | Replay an `OCP1` with a lower `packet_seq`; replay same seq | lower refused; same returns the same ack and moves nothing | §3 |
| T3-27 | Time manipulation | Skew witness and role clocks by ±years | outcomes identical (detective-only time) | §6 |
| T3-28 | Journal durability | Power-cut simulation between append and fsync | state either pre- or post-record, never torn-accepted | §7 |
| T3-29 | Same-owner single-point failure | Run M1 and the Forge on the same host/key in a test | independence rule flags it as not independent | §1 |
| T3-30 | N-1 old-grant void | Replay a validly signed stale grant bound to a *different* challenge | per OAQ-7 ruling: either narrow void (own challenge untouched) or literal void with rate/evidence controls | Part 4 |

## E3. IMP-4 — OCR1 v2, HPKE, Ed25519, plaintext checker

All of T4-01…T4-24 are replayed from `vectors/ocr1_v2_independent_vectors.json` (positive P1/P2/P3 and negatives N01–N36 incl. N22). The adapter must return the phase and reason class; reason strings may differ, the **phase** (1 = key-absent reject, 2 = key-present reject) and the accept/reject outcome may not.

| ID | Attack | Vector / procedure | Expected (basis) |
|---|---|---|---|
| T4-01 | Known-answer: single frame | P1 byte-exact frames from fixed inputs | implementation output equals the vector; accept (RSE12_04 §3–§5) |
| T4-02 | Known-answer: two production frames | P2 per-frame SHA-256 | equal; accept |
| T4-03 | Ephemeral wrapper KAT | `ephemeral_wrapper` section | `ikm`, `enc` equal given fixed `G(32)` |
| T4-04 | Header tamper not re-signed | N01–N03 | Phase 1 reject |
| T4-05 | Header tamper re-signed (key holder) | N04, N05, N17–N20 | Phase 2 AEAD reject (N04, N05) or Phase 1 grant mismatch (N17–N20) |
| T4-06 | Wrong recipient | N06 (id), N07 (key) | Phase 1 reject / Phase 2 AEAD |
| T4-07 | Sender substitution | N08, N09 | Phase 1 reject |
| T4-08 | `enc` validation | N10, N11 (Phase 1), N12 (Phase 2 zero shared secret) | rejected at the stated phase |
| T4-09 | Framing | N13–N16 | Phase 1 reject |
| T4-10 | Digest lie | N21 | Phase 2 digest reject |
| T4-11 | Signature malleability | N22 | Phase 1 reject |
| T4-12 | Frame-set rules | N30–N36 | Phase 1 reject |
| T4-13 | HPKE context confusion | Seal with `info` lacking one field, or with a different suite id; open with the real recipient key | AEAD failure (never partial plaintext) |
| T4-14 | AAD omission | Implementation that seals with empty AAD | KAT mismatch; interop failure — reject the implementation |
| T4-15 | Nonce handling | Reuse the same (key, nonce) for two plaintexts via a fixed-IKM test hook; nonce for frame i must equal base_nonce XOR i | only unique per index; a second bundle with the same `enc` and different `info` yields a different key |
| T4-16 | Duplicate `enc` under a different digest (stateful) | S02 | sender quarantined |
| T4-17 | Replay (stateful) | S01 | second acceptance refused |
| T4-18 | Parser ambiguity | Differential: second independent decoder over 100,000 mutations (prototype in `v1.2/prototype/` is the model) | zero verdict disagreements; every accepted input re-encodes identically |
| T4-19 | Integer edges | `total_len` 0, 1, FRAME_PT, FRAME_PT+1, 2⁶⁴−1; `frame_count` 0, 65536, 65537, 2³²−1; `frame_index` ≥ count | rejected without allocation proportional to the claimed size |
| T4-20 | Unbounded allocation | Header claiming 64 GiB with a short body | refused before reading/allocating more than the frame size |
| T4-21 | Phase isolation | Instrument Phase 1: secret volume locked, no key in memory, no HPKE decapsulation call | proven by a recording fake and by a memory scan for the test key |
| T4-22 | TOCTOU | Mutate the quarantine copy between Phase 1 and Phase 2 | Phase 2 operates only on the verified, hashed bytes (re-hash or hold the verified buffer); mutation detected |
| T4-23 | Key-present parsing surface | Static check: Phase 2 module imports/calls | HPKE, AEAD, digest compare and pipe write only |
| T4-24 | Legacy reuse | Import graph of the new path | no use of `store.py` header-JSON path or the tier0a bundle parser |
| T4-30 | Checker isolation: network | Checker tries socket, DNS, raw sockets, unix sockets | all fail |
| T4-31 | Checker isolation: key access | Checker reads key paths, `/proc/*/mem`, environment, inherited file descriptors | no secret reachable |
| T4-32 | Checker isolation: filesystem escape | `../`, symlinks, `chdir`, mount, ptrace, `/dev` | confined to the temp workspace |
| T4-33 | Resource exhaustion | Zip-bomb-like data, huge output, fork bomb, memory balloon, CPU spin | killed at the configured bounds; verdict FAIL_CLOSED; decryptor unaffected |
| T4-34 | Output covert channel | Checker emits more than the defined output set / timing patterns | only the defined bounded output set accepted; rest dropped and logged |
| T4-35 | Malformed *authenticated* corpus | Validly signed+encrypted bundle with malformed content | checker rejects; Witness not compromised; no partial acceptance |
| T4-36 | Checker crash/hang | Kill the checker; stall it | bundle not accepted; plaintext zeroised; state returns to a safe lifecycle state |
| T4-37 | Staged output authority | Present Forge output lacking witnessed RESULT to every downstream entry point (register, Qualification, training) | `ZERO_ACCEPTANCE_AUTHORITY` — all refuse |

## Adapter contract (written by the auditor at review time; Cursor need not provide it)

`ocr1_encode(plaintext, inputs, ikm) -> frames`; `ocr1_phase1(frames, self_id, enrolled, grant_ctx) -> (ok, reason)`; `ocr1_phase2(verified_frames, recipient_sk) -> plaintext | error`; `ledger_checkpoint(...)`, `witness_cosign(...)`, `grant_step(state, event) -> state | refusal`. If the delivered code cannot be driven through such an adapter without modification, that is itself a finding (testability, requirement C-series "objective acceptance evidence").
