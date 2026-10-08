# RSE master block 1 — code-to-architecture traceability

NON_NORMATIVE. Not in Manifest V3. Maturity here stops at software tests on synthetic fixtures. Nothing in this table is `ACCEPTANCE_COMPLETE`, hardware-verified, or a secure-environment claim.

| Control | Architecture | IMP | Code | Test | Maturity |
| --- | --- | --- | --- | --- | --- |
| Grant lifecycle table, including forbidden revival | RSE12_02 state table | IMP-2 | `GrantMachine.move` | `test_imp2_machine.py` | ADVERSARIALLY_VERIFIED |
| Deferred classes stay fail-closed | RSE12_04 class tails; Clarification 1 milestone | IMP-2 | `GrantMachine.move`, `Session.owner_verify` | `test_deferred_classes_stay_fail_closed`, `test_deferred_grant_cannot_leave_proposed_except_terminal_refusal` | ADVERSARIALLY_VERIFIED |
| One outstanding grant per role, including quarantine; grant-id replay | RSE12_02 | IMP-2 | `GrantMachine.add`, `GrantMachine.parse` | `test_one_outstanding_grant_includes_quarantine_and_replay` | ADVERSARIALLY_VERIFIED |
| Class completion does not authorize another class | RSE12_02 class separation | IMP-2 | `promotes` | `test_class_completion_does_not_authorize_another_class` | ADVERSARIALLY_VERIFIED |
| Crash: reconfirm, ACTIVE becomes INTERRUPTED, evidence-only finish, tampered consumption quarantined | RSE12_02 crash table | IMP-2, IMP-3 | `Session._recover` | `test_crash_recovery_matrix`, `test_evidence_pending_crash_is_not_a_rerun`, `test_tampered_consumer_confirmed_with_consumption_is_quarantined` | ADVERSARIALLY_VERIFIED |
| Wall clock is advisory before ACTIVE; monotonic ceiling after ACTIVE | RSE12_02 freshness | IMP-2, IMP-3 | `Session.observe_clock`, `Session.observe_ticks` | `test_clock_is_advisory_and_ticks_are_monotonic` | ADVERSARIALLY_VERIFIED |
| Revocation releases the role slot and does not run an ACTIVE grant | RSE12_02 | IMP-2 | `Session.revoke` | `test_revocation_releases_the_role_slot` | TESTED |
| Evidence-log Merkle, distinct from the registry tree | RSE12_02; RFC 6962 / RFC 9162 §2.1; RSE11_03 §N | IMP-3 | `imp3/merkle.py` profile `RFC6962-SHA256-RECORD-LEAF` | `test_rfc9162_seven_leaf_shape_and_stack_root` | ADVERSARIALLY_VERIFIED |
| Fork, rollback, idempotent witness packet | RSE12_02 | IMP-3 | `Monitor.consider` | `test_monitor_fork_rollback_and_idempotent_ack` | ADVERSARIALLY_VERIFIED |
| M1 required; M2 cannot replace M1; later checkpoint is not that ack | RSE12_02 quorum | IMP-3 | `Session._quorum`, `EvidenceLog.covering` | `test_m2_cannot_replace_m1_and_later_checkpoint_is_not_the_ack` | ADVERSARIALLY_VERIFIED |
| Same key or same environment is not two witnesses; a container or non-enrolment is not a witness | RSE12_02; Decision 9R | IMP-3 | `Session.__init__`, `require_monitor` | `test_docker_and_same_key_are_not_witnesses` | ADVERSARIALLY_VERIFIED |
| N-1 stale grant does not burn a different challenge; an authenticated successor registry does | Clarification 1 ACR-12 | IMP-3 | `RoleFreshness.evaluate`, `RoleFreshness.authenticate` | `test_stale_grant_does_not_void_a_different_challenge` | ADVERSARIALLY_VERIFIED |
| N-2 caller cannot supply the replay ledger or a lower authenticated version | IMP-1 carry-forward | IMP-3 | `Session.confirm`, `Session.freshness` setter | `test_caller_cannot_supply_replay_state` | ADVERSARIALLY_VERIFIED |
| SIGNED is not usable; state-changing tail is a stale head; checkpoint substitution fails | RSE12_02 log-first | IMP-3 | `Session.activate`, `Session._require_ancestor` | `test_tail_suppression_and_checkpoint_substitution`, `test_m2_cannot_replace_m1_and_later_checkpoint_is_not_the_ack` | ADVERSARIALLY_VERIFIED |
| Staged output has zero acceptance authority; a witnessed RESULT label does not open locks | RSE12_02 egress | IMP-3 | `Egress.classify`, `Session.accept_result` | `test_signed_is_not_usable_and_result_label_does_not_open_locks` | ADVERSARIALLY_VERIFIED |
| Duplicate witness acknowledgement conflicts | RSE12_02 | IMP-3 | `EvidenceLog.store_ack` | `test_empty_log_parses_and_duplicate_ack_conflicts` | TESTED |
| RFC 9180 Base vector and frozen HPKE profile | RSE12_04 §1, Appendix A.2.1 sequences 0..2 | IMP-4 | `admit_rfc9180_base`, `HPKE_PROFILE` | `test_rfc9180_base_vector_is_admitted` | ADVERSARIALLY_VERIFIED |
| Canonical framing, enc checks, frame-count bound without allocating 64 GiB | RSE12_04 header | IMP-4 | `build_header`, `enc_canonical`, `expected_count` | `test_frame_count_bounds_do_not_allocate`, `test_malformed_enc_is_rejected`, `test_header_reencode_rejects_noncanonical_padding` | ADVERSARIALLY_VERIFIED |
| Ed25519 before decrypt; recipient, artifact, epoch, sequence, and enc substitution | RSE12_04 sender authentication and binding | IMP-4 | `structural_phase`, `_bind_grant`, `open_frames` | `test_round_trip_and_signature_is_checked_before_decrypt`, `test_substitution_and_reassembly_attacks` | ADVERSARIALLY_VERIFIED |
| Reassembly: order, duplicate, missing, extra, truncation | RSE12_04 | IMP-4 | `_same_bundle`, `parse_frame` | `test_multi_frame_reordering_duplicate_and_digest_mismatch` | ADVERSARIALLY_VERIFIED |
| All-zero shared secret refused before HPKE open | RSE12_04 | IMP-4 | `_reject_zero_shared` | `test_zero_shared_secret_is_refused_before_open` | TESTED |
| Recipient replay and enc divergence | RSE12_04 | IMP-4 | `RecipientJournal` | `test_phase2_checker_pass_has_zero_acceptance_and_replay_dies`, `test_enc_divergence_is_quarantined` | ADVERSARIALLY_VERIFIED |
| Key-absent phase 1; phase 2 checker is not acceptance | RSE12_04 two-phase ingestion | IMP-4 | `ingest_phase1`, `ingest_phase2`, `keyless_checker.py` | `test_phase1_does_not_decrypt_and_rejects_a_private_key_argument`, `test_authenticated_malformed_plaintext_is_not_accepted` | ADVERSARIALLY_VERIFIED |
| Malformed-frame fuzz across seeds | RSE12_04 adversarial profile | IMP-4 | `open_frames` | `test_deterministic_fuzz_never_accepts_a_mutant` | ADVERSARIALLY_VERIFIED |
| Cross-IMP rehearsal leaves authorization locks denied | Authorization lock files; RSE12_06 not in this block | IMP-2, IMP-3, IMP-4 | `Session.rehearse`, `imp1/locks.py` | `test_g_then_v_rehearsal_leaves_every_lock_denied` | ADVERSARIALLY_VERIFIED |
| IMP-1 security invariants still hold | IMP-1 as accepted on canonical main | IMP-1 | `orca/rse/imp1/` unchanged | `tests/rse/test_imp1*.py` | TESTED |
| IMP-5 and later | RSE12_03, RSE12_05, RSE12_06 | not started | no module | no test claims authority | NOT_AUTHORIZED |

Evidence narrative: `RSE_MASTER_BLOCK_1_EVIDENCE.md`.
