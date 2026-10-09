# RSE block 1 — OCK1 and OCH1 signature-domain addendum

NON_NORMATIVE with respect to Manifest V3. This file is not a manifest row. It does not edit `RSE12_02_WITNESS_LEDGER_FRESHNESS.md`, Clarification 1, or `RSE_ARCH_1_2_FREEZE_MANIFEST_V3.txt`.

Owner decision: Approval 2 in `RSE_BLOCK1_OWNER_APPROVAL_RECORD.md`. The conditions were checked against accepted SHA `da567d927b61c41e253b42732aad249b5fdbb104`. They hold, so this addendum records the domains the accepted code already signs. It does not change signed bytes.

## Approved domains

| Record | Width | Signed message |
| --- | --- | --- |
| OCK1 | 181 = 117-byte body + 64-byte Ed25519 | `"OCK1-SIG" ‖ 0x00 ‖` body |
| OCH1 | 181 = 117-byte body + 64-byte Ed25519 | `"OCH1-SIG" ‖ 0x00 ‖` body |
| OCA1 | 217, unchanged | `"OCA1-SIG" ‖ 0x00 ‖` body, already stated in RSE12_02 §3 |

Implementation: `orca/rse/imp3/records.py`, `_sign` / `_verify`, `pack_checkpoint`, `parse_checkpoint`, `pack_challenge`, `parse_challenge`. Checkpoint identity for the log head remains SHA-256 of the unsigned body.

OCK1 body, in order: magic `OCK1` (4), version `1` (1), `log_id` 32, `tree_size` u64, `root` 32, `epoch` u32, `registry_version` u32, `prev_checkpoint_digest` 32. Offsets 0, 4, 5, 37, 45, 77, 81, 85. End of body is 117.

OCH1 body, in order: magic `OCH1` (4), version `1` (1), `role_id` 32, `challenge` 32, `challenge_seq` u64, `next_sequence` u64, `role_log_head` 32. Offsets 0, 4, 5, 37, 69, 77, 85. End of body is 117.

## Why this does not contradict the freeze

RSE12_02 §3 lists those fields and the OCK1 width 181. It states a domain only for OCA1. It does not say the role signature covers the raw body with no domain. Clarification 1 ACR-3 fixes `OREG-SIG` and leaves `OCG1-SIG` unchanged. It does not mention OCK1 or OCH1. This addendum fills that interoperability gap with the bytes already produced. A different domain would be a new implementation and is not approved.

## Byte vector

Synthetic seed label `SYNTHETIC-RSE-BLOCK1-TEST-ONLY`, key label `ock1-domain` (`tests/rse/block1_support.py` `ed_key`). Not an owner key.

Public key: `2fab2bcbeb1ea8b7a9fa5fad31aa31fe221fe5eebe8b435f03d375fe8dcd4a6f`.

OCK1 inputs: `log_id = bytes(range(32))`, `tree_size = 1`, `root` 32 zero bytes, `epoch = 1`, `registry_version = 1`, `prev_checkpoint_digest` 32 zero bytes. Body SHA-256 `09f8be5083fe1453e9c8fff647883f66c42ec0731d5606cef736134460911031`. Signature verifies over `OCK1-SIG ‖ 0x00 ‖` body and raises `InvalidSignature` over the body alone.

OCH1 inputs: `role_id = bytes(range(32))`, `challenge` 32 zero bytes, `challenge_seq = 1`, `next_sequence = 2`, `role_log_head` 32 zero bytes. Body SHA-256 `6f9b66f38ef83997329bab8799abe3ebb80cfd768f5541f187d02de90bf0a5d4`. Signature verifies over `OCH1-SIG ‖ 0x00 ‖` body and raises `InvalidSignature` over the body alone.

Test: `test_ock1_and_och1_domains_match_the_accepted_bytes`.

## What this addendum does not do

It does not add a signer, a witness, or a grant signature. It does not change OCR1, OCA1, OREG, or OCG1. It does not become a Manifest V3 entry in this commit.
