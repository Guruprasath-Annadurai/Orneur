# RSE block 1 — architecture change requests

NON_NORMATIVE. Not in Manifest V3. Nothing in this file is ratified. No code change is authorized by writing it. The accepted implementation SHA remains `da567d927b61c41e253b42732aad249b5fdbb104`.

Two requests are semantic. The five journal profiles are not repeated here. They are `NON_NORMATIVE_PROFILE_RATIFICATION_REQUESTED` in `RSE_BLOCK1_OWNER_RATIFICATION_PACKAGE.md`. Approving those profiles does not add a constitutional rule. Approving either request below would.

## ACR-B1-1 — OCK1 and OCH1 signature domains

Classification: `ARCHITECTURE_CHANGE_REQUIRED` as a clarification of signed bytes. The recommended decision does not change the bytes the accepted code already signs. A different domain string would, and that alternative is not proposed for implementation.

### Frozen text

`docs/orneur/phase-21/rse/v1.2/RSE12_02_WITNESS_LEDGER_FRESHNESS.md` §3, carried-medium table:

- `OCK1` checkpoint (181 bytes): magic, version, `log_id`, `tree_size` u64, `root` 32, `epoch` u32, `registry_version` u32, `prev_checkpoint_digest` 32, role signature 64. No domain string is stated.
- `OCH1` challenge: magic, version, `role_id`, `challenge` 32, `challenge_seq` u64, `next_sequence` u64, `role_log_head` 32, role signature. No domain string is stated. `role_log_head` is the grant's `prev_role_checkpoint`.
- `OCA1` acknowledgement: the witness signature is over `"OCA1-SIG" ‖ 0x00 ‖` all prior fields. This is the only domain the section states.

Clarification 1 (`RSE_ARCH_1_2_CLARIFICATION_1_FREEZE_AMENDMENT.md`, ACR-3) fixes the registry domain `"OREG-SIG" ‖ 0x00 ‖ format_version ‖ registry_body` and says grant and SAS domains are unchanged: `"OCG1-SIG" ‖ 0x00 ‖ class ‖` grant signed region. It does not mention OCK1 or OCH1.

### Implemented domain

`orca/rse/imp3/records.py`:

- OCK1 body is magic, version, and the fields above, 117 bytes, plus a 64-byte Ed25519 signature. Total 181. The signed message is `b"OCK1-SIG" || 0x00 || body`.
- OCH1 body is 117 bytes plus a 64-byte signature. Total 181. The signed message is `b"OCH1-SIG" || 0x00 || body`.
- OCA1 matches the freeze: `b"OCA1-SIG" || 0x00 || body`, total 217.

`parse_checkpoint` and `parse_challenge` verify that message when a public key is supplied. Checkpoint digest for the log head is SHA-256 of the unsigned body, not of the signature.

### Mismatch

There is no second domain in the freeze that the code contradicts. There is also no sentence that says the role signature covers the raw body only, or that it uses the OCA1 domain. Two independent implementations can both match the field list and still reject each other's signatures. That is an interoperability semantic gap, not a discovered verification bug in this tree.

### Proposed resolution

Freeze the domain the accepted code already uses, by a clarification amendment, not by a silent Manifest V3 edit:

- OCK1: `"OCK1-SIG" ‖ 0x00 ‖` the 117-byte prefix.
- OCH1: `"OCH1-SIG" ‖ 0x00 ‖` the 117-byte prefix.
- OCA1: unchanged.

This resolution does not change signed bytes or verification behavior on SHA `da567d9`. No patch to `records.py` is proposed.

### Compatibility if the owner chooses something else

Signing the raw body with no domain, or reusing `"OCA1-SIG"`, would make every checkpoint and challenge produced by this tree fail verification, and the reverse. Grants, registries, and OCR1 frames would be unchanged, because they use `OCG1-SIG`, `OREG-SIG`, and `OCR1v2-SIG`. The carried medium would still need new OCK1 and OCH1 bytes. That alternative is not authorized.

### Owner decision required

Accept the implemented domains as the clarification, or specify a different domain and require a new implementation candidate plus independent retest. Until then the code stays as accepted and the clarification stays open. Deferral does not block describing the software gate. It does block calling the OCK1 and OCH1 domains constitutionally specified.

## ACR-B1-2 — Cross-role sender quarantine and class-K recovery

Classification: `ARCHITECTURE_CHANGE_REQUIRED`. Not implemented. Do not implement under this request.

### What block 1 enforces today

On this recipient only (`RecipientJournal`, ORJ1 v2, `ingest_phase1`, `ingest_phase2`):

- A repeated `enc` under a different bundle digest is `ENC_DIVERGENCE`.
- That grant moves to `QUARANTINED` and the commit happens before the exception is reported.
- The sender id is stored. A later bundle from that sender to this recipient fails closed, including under another grant id, including phase 1.
- `consume`, `commit_evidence`, `finish`, and `rehearse` fail closed.
- `GrantMachine` gives `QUARANTINED` no outgoing edge (`orca/rse/imp2/machine.py`). The role slot stays occupied.
- Restart through the fence restores that state.
- A different sender is not marked.
- Class K, Q, T, W, D, and R remain `UNSUPPORTED_CURRENT_MILESTONE`.

RSE12_02 §9 also says: any state to `QUARANTINED` on fork, head mismatch, bad proof, journal inconsistency, or duplicate `enc` under a different digest; `QUARANTINED` to `RECOVERY` only by a class-K grant; `RECOVERY` to `SEALED` only after re-enrolment, floor checks, and a new witnessed checkpoint. RSE12_04's recipient sentence quarantines the sender. It does not define a witness record that other roles must enforce.

### What is not enforced

- No other role learns the sender quarantine.
- No witness acknowledgement carries it.
- No registry entry is revoked by it.
- No class-K grant can be executed.
- No path leaves `QUARANTINED`.
- Completing a different grant does not clear it, because the slot is not released.
- There is no authenticated propagation, no witness-backed recovery authorization, and no cross-role replay or rollback rule for this fact.

Calling the recipient-local flag a substitute for those rules would be false. The accepted tests do not claim it.

### Authorization a future amendment must define before any code

1. The signed record: who signs the sender quarantine, over which domain, and which fields bind sender id, recipient id, enc, both bundle digests, grant id, epoch, and registry version.
2. The scope: one recipient, every enrolled recipient, or a named set. A scope wider than the recipient that observed the fault is a new authorization rule.
3. How a role that was offline obtains the record without treating an unsigned copy as authority.
4. Replay: a second presentation of the same record must not create a second incident or release a slot.
5. Rollback: a later journal must not drop the record because a fence generation went backwards. The record needs the same generation rule as the journal that stores it, or a witnessed checkpoint that covers it.
6. The class-K tail for `QUARANTINED → RECOVERY`, the required witnesses (the freeze's K row requires LH, M1, M2, and the owner card), and the check that the K grant names this incident.
7. The exit from `RECOVERY` to a sealed role, including new enrolment floors and a new witnessed checkpoint.
8. What remains fail-closed if any signature, witness, epoch, or fence check fails. The answer in block 1 is: stay `QUARANTINED`.

Until those sentences exist in an owner-approved amendment, implementation stays forbidden. IMP-5 is not that amendment and is not authorized.

### Owner decision required

Accept ACR-B1-2 as future work that stays fail-closed, or reject the wider scope and record that recipient-local quarantine is the whole requirement. Either decision is an owner act. This file does not choose it. Deferral leaves the accepted recipient-local behavior in place and leaves cross-role recovery unauthorized.
