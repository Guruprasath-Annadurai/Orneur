# RSE-IMP-1R implementation evidence

`NON_NORMATIVE_IMPLEMENTATION_EVIDENCE`

This file is not architecture. It does not amend RSE-ARCH-1.2, Manifest V2, or Manifest V3. Clarification 1 is canonical because `docs/orneur/phase-21/rse/v1.2/RSE_ARCH_1_2_CLARIFICATION_1_FREEZE_AMENDMENT.md` is on `main` at `11d1d50b435a84173d9b2f8b06925f915495d29c`. The normative text is `clarification-1/RSE12_CLARIFICATION_1_CANDIDATE.md` as bound by that amendment. Where this note and Clarification 1 differ, Clarification 1 controls.

The rejected implementation was `3ebd6186eb9b500e0a3fe36613ce266f205cb8b7` (`RSE_IMP_1_REMEDIATION_REQUIRED`).

## Original proposal and canonical replacement

| Topic | IMP-1 proposal at `3ebd618` | Canonical Clarification 1 | Migration |
|---|---|---|---|
| Entry order | Insertion order | Strict ascending `ENTRY_ID` | Build and parse reject any other order. Callers sort before signing. No silent reorder inside the parser |
| Registry framing | `OREG` v1, already close | Exact `OREG` v1 layout, 1024 entries, 1 MiB, two signature slots | Kept the layout. Unknown version and trailing bytes stay fail-closed |
| Merkle | RFC 6962 over entry IDs | Same, plus ascending order, empty rejected, not the Evidence Ledger | Profile kept. Order rule added. No proof format added |
| Registry domain | `"OREG-SIG" \|\| 0x00 \|\| format_version \|\| body` | Same | Kept. Cross-protocol replay is tested |
| Token id | `SHA-256("OREG-TOKEN" \|\| 0x00 \|\| pk)` | Same | Kept |
| Lifecycle, retirement, role | 1-based codes, 0 rejected | Same codes, plus reserved values rejected | Kept. Wire integers are literals, not `Enum` ordinals |
| POLICY tail | 70 bytes, `required_family_id` | 199 bytes: caps, witness, operation mask, one `family_scope`, destination count and four slots | Replaced the tail. 0 is a real cap, not unlimited |
| Role binding | Enrolment, code, image and destination carried a policy id | Those types carry `policy_entry_id` = 0 so `ROLE_ID` does not change across families | Removed the policy binding. Family scope lives only on POLICY and on family-bearing entries |
| DESTINATION tail | 65 bytes including a recipient role | 33 bytes: kind + identifier digest | Removed the recipient field. The grant names the recipient |
| FOUNDATION tail | 256 bytes | 289 bytes: prior fields plus `artifact_format` and `inspection_evidence_digest` | Added the fields. Only format 1 may be APPROVED. Inspection is a digest reference, not a backdoor proof |
| W format / R reason | Recommended small integers | W format 1; R reasons 1–4 | Parser constants only |
| K scenario | Any non-zero byte, display label RE-ROOT | Codes 1–13 with distinct names; 0, 14–255 rejected | Parser and display only. K does not execute |
| Below-floor entries | Encode rejected `version < min_permitted_version` | Decode succeeds; use rejects `version < effective minimum` | Parser no longer rejects. Authorization still returns `BELOW_FLOOR` |
| Snapshot | Root equality | Exact `(registry_version, registry_root)`. A higher authenticated version voids the challenge | Added `SNAPSHOT` and challenge voiding. Old grants are not reinterpreted |
| Milestone | Partial semantic success for K, Q, T, W, D, R | G and V only may return `CHECKS_PASSED` | Deferred classes return `UNSUPPORTED_CURRENT_MILESTONE` from Crown and the consumer |
| `signing_key_id` | Stored, unused | `OPAQUE_NON_AUTHORITATIVE` | Still stored because the common block requires it. No authorization decision reads it |

## Unresolved future work

Not implemented, and not a success path:

- Witness-gated registry effectiveness and the Evidence Ledger (`RSE12_02`).
- HPKE and OCR1 frame encryption (`RSE12_04`).
- Executable K, including the frozen epoch and authority-version rules (OPEN-4, architectural intent only).
- W must equal the model entry's `qualification_record_digest`.
- T and Q-linked corpora need a non-zero witnessed acceptance record.
- D may reference an exported or accepted model.
- Each deferred class's target-role matrix, at that class's milestone.
- Hardware anti-rollback, TPM, real enrolment, corpus generation, Qualification, model selection, GPU, spend, and training.

`IMP_2_NOT_AUTHORIZED`. This evidence does not authorize them.

## Final remediation after `924ad6c`

Hostile re-audit returned `RSE_IMP_1_REMEDIATION_REQUIRED`. R-1 through R-5 only:

- Consumer verification requires an explicit `highest_authenticated_version` and a `ChallengeLedger`. Omission fails `AUTHENTICATED_VERSION`. A voided challenge stays void on that ledger (`CHALLENGE_VOID`), including a retry of the old snapshot.
- Class V accepts only a CORPUS artifact. Other entry types fail `WRONG_TYPE`.
- The V card renders `SEQUENCE     {seq_first}..{seq_last}` from the signed tail. K, Q, T, and D display gaps stay in `CARRY_FORWARD` and are not executable.
- The dead `_retire_object` path, which called the removed `_family_absent`, is gone. Deferred R still returns `UNSUPPORTED_CURRENT_MILESTONE`.
- Fuzz covers G, V, K, Q, T, W, D, and R. No mutant is allowed to return `CHECKS_PASSED`.
