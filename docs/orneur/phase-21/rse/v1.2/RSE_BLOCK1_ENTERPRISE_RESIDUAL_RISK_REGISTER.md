# RSE block 1 — enterprise residual risk register

NON_NORMATIVE. Not in Manifest V3. Software-gate acceptance of SHA `da567d927b61c41e253b42732aad249b5fdbb104` is not production acceptance and is not a secure-environment claim. Passing synthetic tests does not close these rows.

Severity uses the effect on a later real deployment. It is not a reason to reopen B-1, B-2, or B-3. "Software canonicalization" means merging the accepted software gate to canonical main after owner ratification. "Later release" means a P1 or hardware gate in RSE12_06.

## 1. SyntheticFence is not TPM NV

Severity: high for any deployment that needs hardware rollback. Not a software-gate blocker.

Mitigation: `SyntheticFence` refuses a virgin fence, refuses `pin_observed`, and accepts only generation 1 on first commit and `floor + 1` after that, bound to SHA-256 of the blob. The label is `SYNTHETIC_NOT_REAL_HARDWARE_PROOF` (`orca/rse/imp3/journal.py`). RSE12_03 and RSE12_06 row C25 name TPM NV. This object is not that control.

Development-stage acceptance: accepted for the software gate, with the label.

Production-stage requirement: a real NV index, the update transaction in RSE12_06 row C26, and an independent hardware test. A caller who can write the fence object is outside the threat model only when the fence is hardware.

Future phase: hardware fence work under RSE12_03. Not IMP-5 by assumption. IMP-5 is not authorized.

Blocks software canonicalization: no. Blocks later release: yes.

## 2. A caller can fabricate synthetic trust roots

Severity: high if a synthetic fence or an in-process monitor is presented as M1. Not a software-gate blocker.

Mitigation: `advance` on a virgin fence accepts only generation 1, so a caller cannot jump a new fence to an old generation in one call. They can still commit generation 1 of a journal they themselves build. `Monitor()` with a new fence is a new witness journal, not a restoration of an old one. Tests refuse `boot` of an old blob onto a virgin or mismatched fence. None of that is an independent party.

Development-stage acceptance: accepted only as a labeled synthetic.

Production-stage requirement: witness keys and the NV fence are provisioned outside the process under test. The software must fail closed when those are absent. No such provisioned root exists in this block.

Future phase: provisioning, which is not authorized (`NO_PROVISIONING_AUTHORIZED`).

Blocks software canonicalization: no. Blocks later release: yes.

## 3. In-process mutable references are not independent security boundaries

Severity: medium for a later multi-process deployment. Not a software-gate blocker.

Mitigation: `Session.freshness` cannot be replaced by assignment. `ingest_phase2` rejects a caller journal. Egress `note_witnessed` requires the session admit token. The durable boundary is the committed blob plus the fence, not a live Python object. A caller who holds the `Session` can still read and call it. That is the same trust as the process.

Development-stage acceptance: accepted for in-process software tests.

Production-stage requirement: separate roles are separate machines, as the freeze describes. Process separation is not demonstrated here.

Future phase: deployment and P1 acceptance (RSE12_06), not a journal-profile change.

Blocks software canonicalization: no. Blocks later release: yes, for any claim of role isolation.

## 4. The keyless checker is not a sandbox

Severity: high if phase 2 is treated as containment. Not a software-gate blocker.

Mitigation: `CHECKER_ISOLATION` is `SYNTHETIC_NOT_A_SANDBOX`. The child is a Python subprocess with CPU, address-space, and file-descriptor limits. If `setrlimit` fails, the child exits 71. The temporary directory is removed. Phase 2 returns `ZERO_ACCEPTANCE_AUTHORITY` and `executable` false. RSE12_06 row C23 requires a real sandbox and real hardware. This is not that row.

Development-stage acceptance: accepted as a labeled structural checker.

Production-stage requirement: a checker with no key, no network, and a boundary that is not the same Python runtime. Linux CI is not that boundary.

Future phase: Witness ingestion hardening. Not authorized as IMP-5.

Blocks software canonicalization: no. Blocks later release: yes.

## 5. Real M1/M2 independence has not been demonstrated

Severity: high for equivocation claims. Not a software-gate blocker.

Mitigation: the software refuses the same enrolment key, the same environment measurement, a non-monitor, and a Docker-shaped stand-in (`require_monitor`, `test_docker_and_same_key_are_not_witnesses`). M2 cannot satisfy the routine M1 quorum (`test_m2_cannot_replace_m1_and_later_checkpoint_is_not_the_ack`). Those are checks on bytes in a registry fixture. They are not two independent operators or two machines. Decision 9R still requires an independent witness for P1. The tests use synthetic keys from `SYNTHETIC-RSE-BLOCK1-TEST-ONLY`.

Development-stage acceptance: accepted as a software quorum rule.

Production-stage requirement: two provisioned Monitor-Lite identities, separate from the role under test, with the handover rule in RSE12_02 §1. Provisioning is not authorized.

Future phase: P1 witness deployment. Not this block.

Blocks software canonicalization: no. Blocks later release: yes.

## 6. Durable hardware anti-rollback is pending

Severity: high for disk rollback of a real role. Not a software-gate blocker.

Mitigation: the software fence rejects an older generation and a same generation with a different digest, once a fence has been committed. That holds only for callers who do not replace the fence object. RSE12_06 rows C25 and C26 are hardware and are marked as needing real hardware.

Development-stage acceptance: the software rule is accepted. The hardware rule is not claimed.

Production-stage requirement: NV fence plus a power-cut-safe update. See also row 10 for the software publish gap that remains even before hardware.

Future phase: RSE12_03. Not IMP-5 by this note.

Blocks software canonicalization: no. Blocks later release: yes.

## 7. Challenge issuance has an 8192-entry cap

Severity: low for the software gate. Medium as an availability limit in a long-lived role.

Mitigation: `MAX_SET` is 8192 for voided challenges, consumed challenges, and dead grants. Exceeding it fails `FRESHNESS` and rolls the mutation back (`test_freshness_ranges_round_trip_and_excess_fails_closed`). The role stops issuing rather than dropping history. The freeze requires the sets and does not set this number. The number is part of the OFJ1 profile request.

Development-stage acceptance: accepted as a fail-closed cap, not as a sizing study.

Production-stage requirement: the owner either ratifies 8192 as the operational ceiling or names a different one before a role is expected to outlive it. A larger cap is a profile change, not a silent edit after ratification.

Future phase: owner ratification of OFJ1. No implementation change is requested now.

Blocks software canonicalization: no, if the profile is ratified or explicitly carried as an unratified residual. Blocks a production lifetime claim: yes, until the owner accepts the ceiling.

## 8. Fragmented forfeiture tracking has a finite interval cap

Severity: low for the software gate. Medium if a role forfeits many disjoint ranges.

Mitigation: forfeited sequences are merged inclusive intervals, cap 4096 (`MAX_INTERVALS`). Overlap and adjacency are rejected on parse. A merge that would exceed the cap fails `FRESHNESS`. A wide range such as 1..5000 is one interval, so the cap is on fragments, not on the numeric span. Test: the same freshness test as row 7.

Development-stage acceptance: accepted as fail-closed compaction.

Production-stage requirement: ratify 4096 or replace it before production sizing. Do not drop intervals to stay under the cap.

Future phase: the OFJ1 profile decision. Not a new grant class.

Blocks software canonicalization: no. Blocks an unbounded-lifetime claim: yes.

## 9. macOS checker limits; Linux CI is the qualifying software environment

Severity: low for the software gate. Informational for developers on macOS.

Mitigation: `run_keyless_checker` treats `setrlimit` failure as exit 71, including a macOS rejection. The suite does not continue unlimited. The qualifying run is the Linux CI job `Genesis V2 Security` and `Genesis V2 Sandbox` on ubuntu-latest in run `37884389862`. A macOS success is not an additional claim. The checker is still not a sandbox (row 4).

Development-stage acceptance: Linux CI is the software environment of record.

Production-stage requirement: the production checker is specified for its own OS. macOS is not that OS in this block.

Future phase: none until a real checker exists. Do not weaken the limit to make macOS pass.

Blocks software canonicalization: no. Blocks a macOS production claim: yes. No such claim is made.

## 10. Crash after sink commit and before fence advancement

Severity: medium for a real disk. The software tests fail closed. They do not prove a disk that overwrites the previous image can still restore it.

Mitigation: `JournalSink.commit` is specified to return only after the blob is what a later boot would read, and to leave the previous blob in place if it raises (`orca/rse/imp3/journal.py`). `durable_commit` advances the fence only after `commit` returns. On failure the session closes and does not report success. `test_failed_and_partial_commit_do_not_return_active` covers a sink that stores bytes and then raises: boot of those bytes with the unadvanced fence is `FENCE`, and boot of the previous authenticated blob still shows the pre-activation grant. `MemorySink` replaces `self.blob` only when `commit` is about to return. A sink that publishes the new image and destroys the old one before returning has broken the contract. The fence then rejects the new image and the old image is gone. That case is not a tested recovery procedure.

Development-stage acceptance: accepted for sinks that obey the contract. Not accepted as a disk recovery design.

Production-stage requirement: write the new blob beside the old one, advance the hardware fence, then publish. A power cut at each step must boot the last fenced image or fail closed, which is RSE12_06 row C26. Do not boot an unfenced image to "finish" the commit.

Future phase: the durable sink behind RSE12_03. Not a change to the accepted session machine.

Blocks software canonicalization: no. Blocks a production power-loss claim: yes.

## Summary

Rows 1 through 6 and row 10 block a real secure-environment release. They do not, by themselves, block software canonicalization of the accepted gate. Rows 7 and 8 are owner ceiling decisions inside the OFJ1 profile. Row 9 names the environment that already ran. None of these rows is closed by another green synthetic run.
