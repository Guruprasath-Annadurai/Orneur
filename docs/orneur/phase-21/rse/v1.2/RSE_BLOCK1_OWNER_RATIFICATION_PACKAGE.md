# RSE block 1 — owner ratification package

NON_NORMATIVE. Not in Manifest V3. This file does not ratify anything. It does not edit the freeze, the accepted implementation, or canonical main.

Accepted implementation SHA: `da567d927b61c41e253b42732aad249b5fdbb104` on PR #8. Parent of that commit: `53de28d647038bdeb0509d5640828beb57a1bec1`. Canonical main baseline: `464b602f3f259b56f139c3304828baa660e6b860`. Exact-SHA push CI of the accepted implementation: run `37884389862`. Independent verdict on that SHA: `RSE_MASTER_BLOCK_1_ACCEPTED`, with IMP-2, IMP-3, and IMP-4 accepted for the software gate. B-1, B-2, and B-3 are not reopened here.

The owner decision is recorded in `RSE_BLOCK1_OWNER_APPROVAL_RECORD.md`. This file remains the byte specification. It is not Manifest V3 and it is not constitutional authority.

## Decision status

The five profiles below are APPROVED for synthetic software-gate use. The approval is non-normative, version-specific, and restricted to the layouts on accepted SHA `da567d9`. It does not change signed bytes or fail-closed checks. Caps, including 8,192 challenge-set members and 4,096 forfeiture intervals, are synthetic-stage operational limits, not an unlimited production lifetime.

Each profile stays classified `NON_NORMATIVE_PROFILE_RATIFICATION_REQUESTED` as the request class. The approval record is what marks that request approved. They are not added to Manifest V3.

The separate items in `RSE_BLOCK1_ARCHITECTURE_CHANGE_REQUESTS.md` are `ARCHITECTURE_CHANGE_REQUIRED`. They are not part of this ratification.

## Shared rules

Integers are big-endian. Magic is 4 ASCII bytes. Version is one byte. A parser that sees a different magic, a different version, a truncated buffer, a duplicate key, or trailing bytes raises `FailClosed` and does not return a usable object. Caps are checked before the object grows. Export order is sorted so the same state has one byte image. No profile carries a role private key.

Rollback for OBS1 and OMJ1 is the synthetic fence in `orca/rse/imp3/journal.py`. `SyntheticFence.authenticate` accepts only the one generation and SHA-256 digest it has already committed. A virgin fence fails `FENCE`. `pin_observed` fails `FENCE`. The first successful `advance` is generation 1. Every later advance is `floor + 1`. The label is `SYNTHETIC_NOT_REAL_HARDWARE_PROOF`. This is not TPM NV (`RSE12_03`).

## 1. OMJ1

Classification: `NON_NORMATIVE_PROFILE_RATIFICATION_REQUESTED`.

Purpose: restart state for Monitor-Lite fork history. Component: `Monitor.export` / `Monitor.boot` in `orca/rse/imp3/ledger.py`. RSE12_02 §3 defines OCP1 and the packet rules. It does not number a monitor journal.

Version: 1.

Layout, in order:

| Field | Width |
| --- | --- |
| magic `OMJ1` | 4 |
| version `1` | 1 |
| generation | u64 |
| epoch floor | u32 |
| witness id | 32 |
| registry version | u32 |
| previous checkpoint digest | 32 |
| evidence-log root | 32 |
| log count | u32 |
| log rows | count × 76 |
| packet count | u32 |
| packet rows | count × 321 |

Log row: log id 32, tree size u64, root 32, epoch u32. Packet row: source role id 32, witness id 32, packet sequence u64, SHA-256 of the request 32, OCA1 acknowledgement 217. Rows are sorted by log id, then by `(source, witness)`. The acknowledgement must be 217 bytes. Parse requires the packet section to end at the last byte.

Caps: 64 logs, 256 packets (`_MAX_LOGS`, `_MAX_PACKETS`). A new log or packet past the cap fails `JOURNAL` before mutation.

Generation: `Monitor(...)` with a virgin fence commits an empty journal at generation 1. `consider` commits the new acknowledgement before it returns. The same packet sequence and the same request hash returns the stored acknowledgement and does not allocate a new generation. A lower sequence, or the same sequence with a different request hash, is `PACKET_REPLAY`. A smaller tree is `ROLLBACK`. The same size with a different root is `FORK`. `boot` refuses a virgin fence and requires `fence.authenticate(generation, SHA-256(blob))`.

Persistence: in-memory `Monitor` fields are not witness evidence. An acknowledgement is durable only after `sink.commit` returns and `fence.advance` succeeds. A failed commit restores the previous maps and generation and does not return the new acknowledgement.

Integrity: the journal as a whole is not signed. Each stored OCA1 still verifies under `"OCA1-SIG" || 0x00 ||` its body when a public key is supplied (`RSE12_02` §3). The fence binds the blob digest. A caller who can call `advance` on a `SyntheticFence` can build a matching floor. That is not an independent witness.

Fail closed: missing sink or fence, wrong magic or version, over-cap counts, and digest or generation mismatch raise `FENCE` or `JOURNAL` and do not restore history.

Crash: a monitor that is constructed again with a new virgin fence is a new journal, not a restoration. Restoration is `Monitor.boot` of the committed blob with the same fence. An older committed blob against a fence that has moved fails `FENCE`.

Tests: `test_monitor_fork_rollback_and_idempotent_ack`, `test_monitor_journal_keeps_fork_history_across_restart`, `test_old_journal_invalid_generation_and_monitor_rollback`.

Compatibility: implements the frozen packet rules. It does not add a second witness, a grant signature, or a class-K path. Approval does not change normative security semantics. Putting OMJ1 into Manifest V3 would be a later amendment and is not requested.

## 2. OFJ1 version 2

Classification: `NON_NORMATIVE_PROFILE_RATIFICATION_REQUESTED`.

Purpose: the role's challenge, registry-generation, dead-grant, and forfeited-sequence state. Component: `RoleFreshness` in `orca/rse/imp3/freshness.py`. The freeze requires the sets. It does not number this journal.

Version: 2. Version 1 is rejected.

Layout, in order:

| Field | Width |
| --- | --- |
| magic `OFJ1` | 4 |
| version `2` | 1 |
| outstanding flag | 1 (`0` none, `1` present) |
| role id | 32 |
| outstanding challenge | 32 (32 zero bytes when the flag is 0) |
| registry root | 32 |
| role-log head | 32 |
| highest registry version, challenge sequence, next bundle sequence | 3 × u32 |
| voided count, then challenges | u32 + count × 32 |
| consumed count, then challenges | u32 + count × 32 |
| dead-grant count, then grant ids | u32 + count × 16 |
| interval count, then inclusive pairs | u32 + count × 16 (`start` u64, `end` u64) |

Canonical rules: each set is sorted and contains no duplicates. Intervals are sorted, `end >= start`, and the next start is at least `previous_end + 2` (adjacent intervals must already have been merged). Flag 0 with a non-zero outstanding image fails. An outstanding value that is also voided or consumed fails. Trailing bytes fail. Export drops voided challenges that are also consumed. The consumed set still rejects replay.

Caps: 8192 members in each of voided, consumed, and dead grants (`MAX_SET`). 4096 forfeiture intervals (`MAX_INTERVALS`). A mutation that would exceed a cap raises `FRESHNESS` and does not keep the new member.

Generation and rollback: OFJ1 has no generation field of its own. It is a length-prefixed section of OBS1. The OBS1 fence is the rollback boundary. `RoleFreshness.authenticate` moves the registry generation only forward. A lower version is `REGISTRY_ROLLBACK`. The same version with a different root is `REGISTRY_FORK`.

Persistence: the section is committed only as part of `Session.durable_commit`. Callers cannot assign `Session.freshness`.

Integrity: unsigned section inside a fence-bound OBS1 blob. Not a second owner signature.

Fail closed: stale snapshot, consumed challenge, voided challenge, and a challenge that is not the outstanding one are refused. A stale grant records that grant id as dead and does not void a different outstanding challenge. The outstanding challenge is voided when a successor registry is authenticated. That is the Clarification 1 availability cost already recorded for N-1. It is not changed by ratifying this layout.

Crash: boot parses OFJ1 only after the fence accepts the OBS1 blob. A cap or overlap that this code would not export fails parse.

Tests: `test_freshness_ranges_round_trip_and_excess_fails_closed`, `test_stale_grant_does_not_void_a_different_challenge`.

Compatibility: the interval encoding is a profile of the frozen forfeiture set. Approval does not raise the cap and does not make a stale grant usable. The caps are operational limits, recorded in the residual-risk register. They are not a new security semantic.

## 3. OBS1 version 2

Classification: `NON_NORMATIVE_PROFILE_RATIFICATION_REQUESTED`.

Purpose: the role write-ahead journal required by RSE12_02 §7. Component: `Session.dump` / `Session.boot` in `orca/rse/imp3/session.py`. The freeze requires the journal. It does not number OBS1.

Version: 2.

Fixed prefix, then length-prefixed and counted sections:

| Field | Width |
| --- | --- |
| magic `OBS1` | 4 |
| version `2` | 1 |
| role id | 32 |
| epoch, authority version | 2 × u32 |
| monotonic ticks | u64 |
| clock | u64 (`0` means no reading; otherwise the reading plus 1) |
| generation | u64 |
| Crown image id, M1 id, M2 id | 3 × 32 |
| machine, freshness, evidence log, egress, registry | each `u32` length + bytes |
| grant count | u32 |
| grants | each `u32` length + grant bytes, sorted by grant id |
| delivery count | u32 |
| deliveries | each key 16 + `u32` length + bytes, sorted by key |
| bound count | u32 |
| bounds | each key 16 + index u64, sorted by key |
| recipient journal, counter journal | each `u32` length + bytes |

Nested profiles parsed by their own code: OGJ1 (`GrantMachine`), OFJ1 v2, OLG1 (`EvidenceLog`), OEG1 (`Egress`), the registry bytes, ORJ1 v2, OCJ1. Private keys are not in the blob.

Canonical rules: one image for one state because maps are sorted. Boot checks the role key against the enrolment, the freshness role id, the registry root and version, and that M1 and M2 are distinct monitor enrolments in distinct environments. A grant slot, delivery, or bound index that does not point at a stored grant fails `JOURNAL`.

Generation: `Session(...)` on a virgin fence commits generation 1 before the constructor returns. That path refuses a fence that has already authenticated a journal, so a historical blob cannot enter through first boot. Later commits increment generation by one, write the blob, then advance the fence. The fence moves only after `commit` returns. On failure the generation is rolled back, the session is closed, an in-memory ACTIVE grant becomes `INTERRUPTED`, and the error is `JOURNAL_COMMIT`.

Persistence: activation, challenge issuance, consumer confirmation, consumption, evidence, finish, revocation, registry advancement, incident, tick interruption, wall-clock expiry, seal, and quarantine commit before success. `boot` refuses a missing sink, a missing fence, and a virgin fence.

Integrity: SHA-256 of the exact blob must equal the fence digest, and the generation field must equal the fence floor. There is no separate signature over OBS1. Trust is the fence plus the signatures inside nested checkpoints, acknowledgements, and grants.

Fail closed: tamper that still parses fails `FENCE` because the digest changed. An unreadable header fails `JOURNAL`. Recovery of an authentic ACTIVE journal with a consumption-start record moves that grant to `INTERRUPTED`, forfeits V sequences, and appends an interruption record in memory. The next commit persists that recovery. `QUARANTINED` and `COMPLETE` are not moved again on boot.

Crash: the authenticated blob is the last blob whose `commit` returned and whose fence advanced. A blob written by a sink that then raises is not authenticated. See residual risk 10. Tests: `test_commit_before_active_and_rollback_cannot_execute_twice`, `test_failed_and_partial_commit_do_not_return_active`, `test_crash_recovery_matrix`, `test_missing_and_virgin_fence_cannot_restore_history`, `test_persistence_failure_closes_the_session`.

Compatibility: this is the crash table in software. Approval does not authorize rehearsal, training, or a second execution of an ACTIVE grant. It does not put OBS1 in Manifest V3.

## 4. OCJ1

Classification: `NON_NORMATIVE_PROFILE_RATIFICATION_REQUESTED`.

Purpose: the RFC 8937 hedge counter for one grant and sequence, as applied by RSE12_04. Component: `CounterJournal` in `orca/rse/imp4/ocr1.py`, stored inside OBS1. `Session.seal_frames` commits it before the frames are returned. An unbound `Sender()` keeps a process-local counter. That object is not the restart boundary.

Version: 1.

Layout: magic `OCJ1`, version `1`, `nxt` u64, count u32, then count rows. Each row is a 24-byte tag (grant id 16 + sequence u64) and a counter u64. Rows are sorted by tag. The encoded length is exactly `17 + count * 32`.

Caps: 4096 rows. `nxt >= 1`. Each stored counter is unique, at least 1, and strictly less than `nxt`.

Generation: none of its own. OBS1 generation covers it.

Persistence: `take` happens before the frames are built. If seal or the session commit fails, `undo` restores `nxt` when it still equals that counter plus one. A closed session cannot seal again. Restart from the last authenticated OBS1 refuses the same tag with `COUNTER_REUSE`.

Integrity: unsigned section of a fence-bound OBS1 blob. The counter is not a signature domain and does not change the OCR1 header width (210).

Fail closed: reuse, a counter below 1, an over-cap journal, and a commit failure do not return frames as durable.

Crash: a failed commit does not advance the fence, so the next boot does not see the abandoned counter. Tests: `test_hedge_counter_is_committed_before_seal_returns`.

Compatibility: no new signature domain. Approval does not change HPKE, the header, or the hedge construction `HKDF-SHA256(salt=SHA256(Ed25519(OCR1v2-EPH || 0x00 || sender || environment)), info=grant || sequence || counter)`.

## 5. ORJ1 version 2

Classification: `NON_NORMATIVE_PROFILE_RATIFICATION_REQUESTED`.

Purpose: the recipient replay set and the recipient-local sender quarantine required by RSE12_04 (a repeated `enc` under a different `bundle_digest` quarantines the sender). Component: `RecipientJournal` in `orca/rse/imp4/ocr1.py`, stored inside OBS1. This profile does not propagate the sender to any other role and does not implement class-K recovery.

Version: 2. Version 1 is rejected.

Layout, in order:

| Field | Width |
| --- | --- |
| magic `ORJ1` | 4 |
| version `2` | 1 |
| last sequence | u64 |
| quarantined-grant count | u32 |
| grant ids | count × 16, sorted, unique |
| quarantined-sender count | u32 |
| sender ids | count × 32, sorted, unique |
| row count | u32 |
| rows | count × 88 |

Row: grant id 16, sequence u64, `enc` 32, bundle digest 32. `last_sequence` is 0 when there are no rows and otherwise equals the highest row sequence. Duplicate `(grant, sequence)` or duplicate `enc` fails parse.

Caps: 256 quarantined grants, 256 quarantined senders, 4096 rows (`_MAX_REPLAY`).

Generation: none of its own. OBS1 generation covers it.

Persistence: a successful phase-2 admission is committed before success is returned. On `ENC_DIVERGENCE` the grant is moved to `QUARANTINED` and `durable_commit` runs before the quarantine is reported. If that commit fails, the session is closed and the caller does not observe a successful ingest.

Integrity: unsigned section of a fence-bound OBS1 blob. The sender id is the 32-byte role id from the authenticated frame, not a new key.

Fail closed: a quarantined grant or a quarantined sender fails `ENC_DIVERGENCE` on phase 1 and phase 2, including a different grant id for that sender on this recipient. `consume`, `commit_evidence`, `finish`, and `rehearse` fail the same way. `QUARANTINED` has no exit in `GrantMachine`. The role slot stays occupied (`OUTSTANDING_GRANT`). A different sender is not marked.

Crash: boot of the committed OBS1 restores `QUARANTINED` and the sender set. Tests: `test_enc_divergence_is_quarantined`, `test_enc_divergence_quarantine_is_committed_before_it_is_reported`, `test_enc_divergence_quarantines_the_grant_and_the_sender`.

Compatibility: this is the frozen recipient sentence, not cross-role authority. Approval does not release the slot and does not authorize class K. Those gaps are `ARCHITECTURE_CHANGE_REQUIRED` in the architecture-change request.

## What the owner is not asked to do here

- Merge PR #8.
- Edit Manifest V3.
- Start IMP-5 or IMP-6.
- Treat `SyntheticFence` as TPM NV.
- Treat recipient-local quarantine as cross-role quarantine.
- Change OCK1 or OCH1 signature bytes. That decision is a separate request.
