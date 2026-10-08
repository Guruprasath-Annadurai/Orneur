# Block-1 audit package — Part 6: exact-SHA audit procedure (J), acceptance criteria (K), open architecture questions (L), evidence pending (M)

`NON_NORMATIVE_AUDIT_EVIDENCE`. The final implementation verdict is **unavailable** until the delivered code and its evidence have been examined at an exact SHA. Nothing here accepts, or pre-accepts, IMP-2, IMP-3 or IMP-4.

## J. Exact-SHA audit procedure for the combined candidate

Run in a detached worktree; never edit, merge or push. Record every command output in the report.

1. **Exact-SHA verification.**
   `git fetch origin`; confirm the candidate SHA equals the PR head (`gh pr view <n> --json headRefOid`), the PR base equals the current canonical `main`, and the candidate descends from it. Confirm `main` is unchanged. Verify the CI run: `gh run view <id> --json headSha,event,headBranch,conclusion,jobs` — event, ref, exact head SHA, whether it is bare-head or merge-ref, and **all six** jobs: Deterministic Unit Tests, Genesis V2 Security, Genesis V2 Sandbox, Training Math (Torch), Production Container Build + Boot Smoke, Dependency Vulnerability Scan. Run `review/block1/audit_gate_checks.sh <base> <candidate>` (frozen/authorization/workflow paths, Manifest V3 digest and 32 entries, privacy patterns, removed/skipped tests, swallowed exceptions). Inspect any `REVIEW` line by hand.
2. **Architecture conformance.** Complete the matrices in Part 1 with `file:symbol:line` evidence per row. Flag any production behavior with no frozen requirement. Every constant, layout or enumeration the code invents must appear in the implementer's gap report and be classified (A implementation detail / B clarification / C semantic change); none may be silently treated as frozen.
3. **Independent known-answer tests.** Run `vectors/run_checks.sh` to regenerate and confirm the vector file hash; drive the delivered code through an auditor-written adapter with P1, P2 digests, the wrapper KAT and the earlier canonical vectors (CL1 §17 Merkle, KEYID, SAS). Run the chosen library against RFC 9180 Appendix A through the *same API the code uses*.
4. **Negative tests.** Execute all N01–N36 vectors and the stateful cases S01–S04; every row of Part 2 marked negative.
5. **Adversarial tests.** Execute Part 2 T2/T3/T4. Run an independent mutation campaign separate from the implementer's suite: (a) byte-mutation of grants, registries, checkpoints, medium records and OCR1 frames; (b) **re-signed** semantic mutation of the signed region with an independent oracle (the method used in the IMP-1R retest); (c) differential decoding against a second implementation. Report seeds and iteration counts. Add a mutation check: neutralise each defence in a scratch copy and confirm a test fails.
6. **Integration tests.** End-to-end synthetic flow with real separation of keys and processes: G grant → witness acknowledgement → Forge bundle → witnessed RESULT → Witness Phase 1/Phase 2 → keyless checker → acceptance record → witnessed acceptance. Include crash points and the outage of M1. Use the Docker lab only as synthetic infrastructure (Part 4 §H).
7. **Authorization-lock verification.** `prove_authorization_locks`, the three authorization JSON files unchanged, no corpus/Qualification/model/GPU/provider/spend/training path reachable; deferred classes still unsupported through every new entry point; IMP-5 not started.
8. **Privacy and secret checks.** Scan added lines and image layers; confirm all keys are labelled synthetic; no host names, user paths, addresses or tokens.
9. **Protected benchmark checks.** No path read or written; `known_leakage` remains false; tests never open protected content (blob ids and hashes only).
10. **Dependency/security review.** Diff dependency declarations; for each new package record name, version, hash, maintainers, audit status and vulnerability scan; compare the scan output with the canonical-main run (pre-existing findings stay classed as pre-existing). Review any FFI or custom crypto glue as security-critical.
11. **Residual-risk classification.** Each residual is one of: declared in the frozen text, new but contained, or blocking. Nothing may be re-labelled as a property.
12. **Final gate.** Apply the criteria below and issue per-milestone and combined verdicts.

## K. Independent acceptance criteria

A candidate is acceptable only if **all** hold:

1. Exact-SHA identity and CI are verified as above; no workflow/test requirement weakened; the six jobs succeed.
2. Every Part-1 row for the accepted milestone has evidence or an explicit, frozen residual; no row is satisfied by "the owner confirms" or by a mock.
3. All known-answer vectors reproduce byte-for-byte; all negatives are rejected at the stated phase.
4. No unresolved CRITICAL or HIGH defect; no fail-open path (including default parameters, swallowed exceptions, mutable or caller-owned security state, truthiness bugs, unvalidated types).
5. Deferred classes K/Q/T/W/D/R cannot reach success anywhere.
6. N-1 and N-2 are closed per Part 4 (or the architect's ruling is recorded and its residual accepted).
7. Every invented constant/layout is classified; any Class B or C item has an approved clarification or amendment **before** acceptance of the affected part.
8. The cryptographic library decision (OAQ-5) is recorded; the chosen library is conformance-tested; no hand-rolled primitives.
9. Authorization locks, protected benchmark and privacy checks are clean; no real secret exists.
10. Residual risks are declared and none is converted into a claimed security property (especially: witnessed effectiveness without real hardware, Docker as a boundary, Mac rollback).

Per-milestone outcomes are allowed (for example IMP-2 and IMP-3 acceptable while IMP-4 awaits OAQ-5), but a combined acceptance requires all three. Verdict vocabulary for the eventual report: `RSE_BLOCK_1_ACCEPTED`, `RSE_BLOCK_1_REMEDIATION_REQUIRED`, `RSE_BLOCK_1_BLOCKED_BY_ARCHITECTURE_CLARIFICATION` (plus the per-milestone breakdown), always followed by the standing lock tokens.

## L. Open architecture questions (need rulings; the reviewer will not fill gaps by invention)

| ID | Question | Why it matters | Suggested class |
|---|---|---|---|
| OAQ-1 | The labels IMP-2/3/4 and their scope are not in the frozen text. Confirm the mapping used here (IMP-2 lifecycle/consumption/crash/ceilings; IMP-3 ledger/witness/freshness/journal; IMP-4 OCR1 v2/HPKE/checker) and which of K/W/D/R semantics, M1→M2 handover and the TPM fence are in or out | prevents scope drift and false "complete" claims | process |
| OAQ-2 | Ledger Merkle profile, per-role leaf serialization (grant append, consumption-start, RESULT, acceptance, registry update records), inclusion and consistency proof algorithms and encodings, `prev_checkpoint_digest` function, checkpoint body encoding | frozen text names `OCK1/OCP1/OCA1/OCI1` fields but not these; CL1 §1 says the registry tree is *not* the ledger tree and defers to IMP-3 | B |
| OAQ-3 | Signature domains for `OCK1` and `OCH1` role signatures (only `OCA1-SIG` is frozen) | one Ed25519 role key signs frames, checkpoints, challenges and `tag1` | B |
| OAQ-4 | Exact set of "non-state-changing" record kinds for the `prev_role_checkpoint` rule (boot, challenge issue, maintenance evidence are named; the list is not closed) | a wrong list either blocks valid grants or lets stale ones through | B |
| OAQ-5 | HPKE library/API: `cryptography` 49 is single-shot (no AAD, no context, no caller IKM, cannot reproduce Appendix A). Which context-capable library is admitted, or is OCR1 amended? | blocks a faithful IMP-4 and the library-admission rule of RSE12_04 §2 | B or C |
| OAQ-6 | Plaintext checker sandbox: mechanism per platform, bounded pipe sizes, CPU/memory/output limits, the "defined output set", behavior on checker crash | frozen text is qualitative; "no network, keyless, bounded" cannot be tested without numbers and a real boundary | B |
| OAQ-7 | N-1: does a refused grant that is not bound to the outstanding challenge or role void that challenge (literal CL1 §11) or not (narrowed)? | availability and replay-of-old-grants | B |
| OAQ-8 | Journal and sealed-state format, location, full-sync requirements per platform (macOS `F_FULLFSYNC`), torn-write recovery, who may read/write it | durability and N-2 closure depend on it | B |
| OAQ-9 | Enrolment/registry source for Phase 1 sender lookup: whose registry copy, and how it interacts with the exact-snapshot rule when the registry changes between grant and bundle | identity and replay | B |
| OAQ-10 | `type 2` (weights export bundle): must IMP-4 reject it as unsupported until the W milestone? | avoids partial W semantics | process |
| OAQ-11 | Test-only frame size and ephemeral-IKM hooks: how may tests reach them without a production-reachable switch? | KATs need fixed IKM and small frames | B |
| OAQ-12 | M1→M2 handover record format and the owner-checkpoint (OC) interface — in IMP-3 or deferred? | quorum logic for irreversible events | process |

## M. Evidence pending from Cursor

For the eventual delivery: exact SHA and PR; CI run id; the implementation-gap/ACR report **committed** as non-normative evidence (the IMP-1 report was initially absent from the repository); requirement-to-code-to-test traceability for every Part-1 row; library selection and dependency records; reproduction output of the RFC 9180 Appendix A vectors and this package's vectors through the delivered API; fuzz/property seeds, iteration counts and what each mutation kind targets; negative controls; durability and crash-test method; sandbox description and tests against the real boundary; journal/state format documentation; N-1/N-2 closure mapping; authorization-lock proof; privacy scan output; list of every invented constant and its proposed classification.

## Status of everything above

Until Cursor delivers, each row in Part 1 is `PENDING_IMPLEMENTATION_EVIDENCE` (or `EXISTS_IN_IMP1` where the accepted IMP-1 already covers it), Part 4 §H is `PENDING_DOCKER_FILES`, and Part 6 §L is awaiting rulings. No result in this package is a PASS for any implementation.
