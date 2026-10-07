# RSE-ARCH-1.2 — Part 7: fresh hostile self-attack (H5+ search)

Paper attacks only, written after the other parts, by the same author (not independent; the next step is an independent audit). Each attack traces an attacker through the **written** text. Result words: BLOCKED, DETECTED, CONTAINED, UNRESOLVED_DECLARED, and **FOUND_AND_FIXED** (a defect in 1.2's own first draft, corrected in the text before this report).

## 1. Defects found in the first draft of 1.2 and corrected

| ID | Severity | Mode | Finding | Fix (where) |
|---|---|---|---|---|
| F1 | MEDIUM | fail-open | Typed SAS proves only that Crown's display and the consumer agree; a **compromised Crown** can show a benign card and the true SAS of a malicious grant | owner-independent **Intent Sheet** typed at the consumer (`RSE12_01` §4; C07) |
| F2 | MEDIUM | availability/logic | `prev_role_checkpoint` equality was brittle: pre-issued challenges mean the role's head moves before consumption, making every grant stale | ancestor-plus-only-non-state-changing-records rule (`RSE12_02` §2) |
| F3 | MEDIUM | logic | registry and enrolment entries referenced a checkpoint "including the entry", which is impossible (the entry ID is the hash of the entry) | field now means a strictly earlier checkpoint over the evidence; inclusion by proof (`RSE12_01` §2, `RSE12_04` §6) |
| F4 | MEDIUM | logic | nobody assigned bundle sequence numbers before Crown signs the V range | `next_sequence` in the role's `OCH1` challenge record (`RSE12_02` §3) |
| F5 | MEDIUM | logic | the V grant bound `bundle_digest`, which does not exist when G and V are signed in one session (contradicting the batching claim) | V binds sender, artifact and sequence range; the digest is checked against the sender's **witnessed RESULT leaf** (`RSE12_04` §6, §8) |
| F6 | MEDIUM | fail-open | offline roles keep an outstanding challenge across an incident, so a stolen pre-signed grant stays usable | re-root step 0 voids challenges in MAINTENANCE (`RSE12_05` §4.3) |
| F7 | LOW | operational | a bundle digest must be known before the first frame, and the plaintext workspace may be RAM-backed | bundle size capped by POLICY `batch_ceiling_bytes` far below 64 GiB; the 64 GiB format maximum is not a working size (noted in C-series tests) |

None of F1–F7 was HIGH after correction; F1 would have been HIGH if left, because the whole consumer-re-render story assumed an honest Crown display.

## 2. Attack list required by the assignment

| Attack | Path | Result | Control / residual |
|---|---|---|---|
| Malicious registry entry | owner approves a bad artifact; or homoglyph name | CONTAINED | provenance, two independent builds on Crown, confusable-name rule; owner error remains |
| Registry rollback | old registry on Crown/consumer | CONTAINED | card floor, sealed floor, witnessed registry checkpoints; consumer rollback detected only (R-RB1) |
| Crown substitution (software) | compromised Crown shows benign card | CONTAINED | consumer re-render, typed intent (F1) |
| Crown bootstrap compromise | poisoned upstream before genesis | UNRESOLVED_DECLARED | two independent builds from independently sourced inputs; shared upstream residual R-B1 |
| Stale Crown | restored older Crown image | DETECTED (Mac) / PREVENTED (TPM Crown, future) | card floor typed, witnessed checkpoint shrink refused |
| Token theft | one token stolen | CONTAINED | second token needed for G/K/Q/T/W/D/R; V needs one (verification is low-impact) |
| Grant replay | captured grant | BLOCKED | outstanding-challenge match, consumed set; after in-state rollback one replay possible for routine classes (R-RB2) |
| Nonce reuse | RNG failure / repeated enc | BLOCKED structurally | key depends on `info` which contains the digest; repeated enc under another digest flagged (`RSE12_04` §7) |
| Offline freshness failure | clock tampering | CONTAINED | clock advisory; challenge is the freshness mechanism |
| Witness quorum compromise | malicious M1 + compromised role | CONTAINED for irreversible classes (M2); routine classes UNRESOLVED_DECLARED (R-N1) | M1∧M2, equivocation detection |
| Witness unavailability | M1 down | AVAILABILITY loss, fail closed | no downgrade; K handover to M2 |
| Ledger fork | role keeps two histories | DETECTED | witness refuses fork/shrink; holders compare |
| Tail suppression | authorization | BLOCKED (log-first; acks for the checkpoint containing the grant); results CONTAINED (E1 staging untrusted until witnessed) |
| TPM rollback | old image + old blob | BLOCKED on a conforming TPM (needs C25) | fence |
| TPM update crash | power cut at each step | CONTAINED (not bricked) | A/B + dual sealed objects + passphrase path; counter atomicity unverified |
| OCR1 ambiguity | alternate encodings | BLOCKED | fixed grammar, derived lengths, no reserved bytes, prototype agreement (structural only) |
| Frame truncation | drop/duplicate/reorder/extra/cross-bundle | BLOCKED | frame_count, derived lengths, in-order, field equality, digest after reassembly |
| Sender-key substitution | attacker key in enrolment | BLOCKED | owner dual-token registry update; ID is hash of entry; REVOKED state |
| Malicious authenticated plaintext | compromised Forge | CONTAINED | keyless sandbox; escape = second failure (R-SB1) |
| Sandbox escape | kernel bug | UNRESOLVED_DECLARED | shared kernel; ceilings; rebuild |
| Recovery rollback | old kit | BLOCKED if floors are held | max of card/sealed/witnessed/fence; all-lowered is outside the model |
| Artifact repository compromise | poisoned approval host | CONTAINED | two independent builds, comparison on Crown |
| Malicious foundation weights | backdoor | UNRESOLVED_DECLARED (R-F2) | provenance, owner approval; undetectable by inspection |
| Qualification extraction | oracle bisection | CONTAINED | bit and query budgets, abuse freeze; counters need P2 monotonic state (UNPROVEN) |
| W bypass | export without W | BLOCKED by design, UNPROVEN until P2 | exporter only opens under W; training-environment egress is the future HIGH blocking *training* authorization (R-EXF) |
| D bypass | deploy without D | BLOCKED by design, UNPROVEN until P2 | same |
| Owner fatigue | skipped checks | CONTAINED | operator budget as a security target, envelope grants, typed fields; cannot be eliminated |

## 3. Position

No unresolved HIGH **architecture** defect remains in the written text. Known HIGH-class items are either contained, declared, or future-gated and tied to acceptance rows: Mac OS rollback UNSOLVED (P0 stays rehearsal-only), Qualification counter and training egress UNPROVEN (block Qualification/training authorization, not freeze), sandbox escape and shared upstream declared. This report is the author's own; an independent reviewer should expect to find H5+ items this author could not.
