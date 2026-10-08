# RSE_ARCH_1_2_CLARIFICATION_1_FREEZE_AMENDMENT

Immutable freeze-amendment record. It adds no design and changes no value: it binds the independently accepted Clarification Candidate 1 to the existing architecture-freeze governance (`RSE_ARCH_1_2_ARCHITECTURE_FREEZE.md`, `RSE_ARCH_1_2_FREEZE_CANONICALITY_CORRECTION.md`). This file is never edited in place; a later change needs a new clarification, independent review and a new amendment record.

## 1. Binding

| Item | Value |
|---|---|
| Base architecture | RSE-ARCH-1.2 (accepted candidate `1df94810bc35692b0ce8c969978920d4dea06d8e`; freeze record first committed at `6da3b7c75740f2056853e5b8ef32eecaefde6e8c`; canonicality correction `be54d5b0e6d1cdebca8923343dd9830d20ce1688`) |
| Canonical `main` at amendment creation | `be54d5b0e6d1cdebca8923343dd9830d20ce1688` (not moved) |
| Accepted clarification | commit `62c128129f2c26968dd675df3e89e1a7561a82c3`; file `clarification-1/RSE12_CLARIFICATION_1_CANDIDATE.md`; SHA-256 `49ed1e669b27fcb5dbfd3cf92bc258d41ffd3c3c9aed815fb297f4e6b402f8ac`; 23,309 bytes; exact-SHA CI run `37744916016`, all six jobs success |
| Independent audit | verdict `RSE_ARCH_1_2_CLARIFICATION_1_ACCEPTED_FOR_FREEZE_AMENDMENT` (as relayed by the owner; the audit report is not in this repository and is classed `NON_NORMATIVE_AUDIT_EVIDENCE`) |
| Manifest | `RSE_ARCH_1_2_FREEZE_MANIFEST_V3.txt`, SHA-256 `7b19e6ca6b60f6209a35036690c9d05dc5352dfb6219ed17887b63343e72e703`, 32 entries. It extends, and does not replace, Manifest V2 (`5b352e2c01f6fa9d1ffb1406eee5ba89104f4d36b74dc3aa15df360c0ec0347d`), which stays byte-identical |

**Effect timing.** This amendment, and the clarification it freezes, become part of the normative RSE-ARCH-1.2 specification **only after the commit containing this record is canonical on `main`**. Until then they are accepted-but-not-effective, and `main` and Manifest V2 govern.

## 2. Accepted rulings (frozen by reference to the accepted file; values below are the accepted ones)

The accepted clarification file controls the exact text; the table repeats the accepted values so a reader can check them. Any mismatch between this table and the file is a defect in this record and the file controls; none was found (§6).

| ID | Accepted ruling | Wire-normative | Effect on frozen text |
|---|---|---|---|
| ACR-1 | RFC 6962 §2.1 tree hash over ordered 32-byte `ENTRY_ID`s: leaf `SHA-256(0x00 ‖ ENTRY_ID)`, node `SHA-256(0x01 ‖ left ‖ right)`, split at the largest power of two strictly below n, no odd-node duplication, empty tree rejected; **strict ascending `ENTRY_ID` order**; not the Evidence Ledger tree; no proof protocol | yes | disambiguates |
| ACR-2 | `OREG` v1: magic `OREG`, version byte 1, `registry_version` u32 (≥1), previous root 32 bytes (zero iff version 1), `entry_count` u32 (1..1024), entries, root, exactly two signatures of slot byte + 64; max 1024 entries and 1,048,576 bytes; unknown version, trailing bytes, unsorted or duplicate entries rejected | yes | disambiguates |
| ACR-3 | registry signature message `"OREG-SIG" ‖ 0x00 ‖ format_version ‖ registry_body`; `KEYID(pk) = SHA-256("OREG-TOKEN" ‖ 0x00 ‖ pk)`; grant and SAS domains unchanged | yes | disambiguates |
| ACR-4/5/6 | lifecycle 1 CANDIDATE, 2 QUALIFIED, 3 ACCEPTED, 4 EXPORTED, 5 DEPLOYED, 6 RETIRED; retirement 1 ACTIVE, 2 RETIRED; role types 1 CROWN, 2 FORGE, 3 WITNESS, 4 MONITOR_LITE; 0 invalid; unlisted reserved and rejected | yes | disambiguates |
| ACR-7 | POLICY tail **199 bytes**: u64 `max_batch_bytes`, u32 `max_runtime_s`, u64 `max_spend`, u32 `max_run`, u32 `max_query_budget`, u32 `max_bit_budget`, u32 `min_grant_schema_version`, u8 `witness_requirement` (1–3), u8 `allowed_operations` bitmask (G V K Q T W D R = bits 0–7, non-zero), 32-byte `family_scope`, u8 `destination_count` (0..4), 4×32 `permitted_destinations` (ascending, zero-padded); unsigned big-endian; caps inclusive | yes | disambiguates widths, adds fields |
| ACR-7b | **stable `ROLE_ID` independent of family/policy**: ENROLMENT, ROLE_IMAGE, CODE and DESTINATION entries carry an all-zero `policy_entry_id`; family-bearing entries (TOKENIZER, FOUNDATION_MODEL, MODEL, CORPUS, HOLDOUT_SET) reference their POLICY; **exactly one family per POLICY** (`family_scope`, or zero for a family-neutral policy); destinations shared across families only when listed in the grant's POLICY | yes | amends (owner ruling) |
| ACR-8 | DESTINATION tail **33 bytes**: kind (1 MEDIUM, 2 RECIPIENT_ROLE, 3 EXPORT_TARGET) + non-zero `identifier_digest`; the recipient is named only by the grant | yes | reverses Cursor, matches the freeze |
| ACR-9 | **W/R wire constants only**: W `format` 1 = DATA_ONLY_TENSOR_V1; R `reason` 1 SUPERSEDED, 2 COMPROMISED_OR_SUSPECTED, 3 POLICY_VIOLATION, 4 END_OF_LIFE; no W/R semantics | yes | disambiguates |
| ACR-10 | deterministic Crown phrase mapping from signed class (and K scenario); no proposer text; every human-meaningful signed field rendered; K shows its actual scenario name | no | disambiguates |
| ACR-11 | entries with `version < min_permitted_version` **decode**; use is rejected when `entry.version < effective_min_version` | yes (parser) | disambiguates |
| ACR-12 | **exact registry snapshot binding**: a grant binds one `(registry_version, registry_root)`; consumer refuses if its snapshot differs or it has authenticated a higher version, voids its challenge, and a new grant is signed | no | amends (stricter than `RSE12_01` §3) |
| ACR-13 | FOUNDATION_MODEL tail **289 bytes**: the 256 frozen bytes + `artifact_format` u8 (1 DATA_ONLY_TENSOR_V1; 128 EXECUTABLE_OR_CODE_LOADING and 255 UNINSPECTED never approvable) + 32-byte `inspection_evidence_digest`; `foundation_revision` ASCII `[A-Za-z0-9._-]{1,64}`; source via non-zero `provenance_digest` | yes | amends (adds fields) |
| ACR-14 | **K scenarios 1–13**: 1 EPOCH_RAISE, 2 FORGE_REBUILD, 3 WITNESS_REBUILD, 4 TPM_REPLACE, 5 WITNESS_ENV_UPDATE, 6 TOKEN_REPLACE, 7 CHECKPOINT_HOLDER_REPLACE, 8 CHECKPOINT_ROOT_REESTABLISH, 9 ARTIFACT_REPO_RECOVERY, 10 CORPUS_RESTORE, 11 WEIGHTS_RESTORE, 12 LUKS_SLOT_ROTATION, 13 RE_ROOT; 0, 14–255 (including 255) rejected; no universal fallback | yes | disambiguates |
| Milestone | **G and V only** may receive full semantic validation in IMP-1; K, Q, T, W, D, R parse, register and display but `crown_validate`/`consumer_verify` return `FAIL_CLOSED` / `UNSUPPORTED_CURRENT_MILESTONE`; no other function may report a deferred grant valid | no | process rule |
| Lineage | **MODEL family and policy equal its parent's**; cross-family parentage rejected at admission; a foundation and its tokenizer share a POLICY | no | disambiguates |
| Consumer identity | consumer binds the grant to its own **`ROLE_ID` and observed environment identity** (equal to both the grant and the enrolment; `SELF_ATTESTED` on Mac roles); challenge equality in addition, never instead | no | disambiguates |

### Dispositions of the clarification's open items

- **OPEN-1:** `signing_key_id` is **`OPAQUE_NON_AUTHORITATIVE`**: an opaque 32-byte field inside the hashed entry that no authorization, approval, identity or trust decision may read or depend on. Any future meaning needs a new clarification, independent review and a new amendment.
- **OPEN-2:** exactly one family per POLICY is frozen; multi-family policies are not defined.
- **OPEN-3:** strict ascending `ENTRY_ID` ordering is accepted over insertion order.
- **OPEN-4:** the K epoch and authority-version rules of the clarification (§13) are frozen **as architectural intent for the future K implementation** (never lower either value; `new_epoch` must exceed the current for EPOCH_RAISE, TOKEN_REPLACE, ARTIFACT_REPO_RECOVERY, LUKS_SLOT_ROTATION and RE_ROOT; `new_authority_version` must exceed the current for RE_ROOT). They are not executable in IMP-1.

Carry-forward obligations recorded by the clarification (already frozen elsewhere, restated so they are not lost): W equals the model entry's `qualification_record_digest`; T and Q-linked corpora need a non-zero witnessed acceptance record; D may reference an exported or accepted model; each deferred class defines its own target-role matrix at its milestone.

## 3. Contained residuals (not hidden, not converted into properties)

1. **Exact snapshot binding is an intentional availability cost.** Every registry update invalidates all unconsumed grants; the owner accepted this.
2. **`signing_key_id` must never become authority** without a future specification, review and amendment.
3. **Cursor must migrate from insertion order to strict ascending `ENTRY_ID`** (and from the other superseded IMP-1 choices); IMP-1 stays `IMP_1_NOT_ACCEPTED` until a remediated candidate passes re-audit.

Also unchanged: the owner token set is an input to verifiers; Mac-role environment identity is self-attested; format-1 inspection depends on an owner-approved tool; the earlier RSE-ARCH-1.2 residuals (`RSE_ARCH_1_2_ARCHITECTURE_FREEZE.md` §6) all remain.

## 4. Normative classification (see Manifest V3)

| Class | Meaning | Files |
|---|---|---|
| `NORMATIVE_RSE_ARCH_1_2_CLARIFICATION` | normative once this amendment is canonical; controls over conflicting incorporated or native text | `clarification-1/RSE12_CLARIFICATION_1_CANDIDATE.md` |
| `NORMATIVE_GOVERNANCE_RECORD` | governs classification and incorporation | `RSE_ARCH_1_2_FREEZE_CANONICALITY_CORRECTION.md`, `RSE_ARCH_1_2_FREEZE_MANIFEST_V2.txt` |
| unchanged from Manifest V2 | native normative (7), incorporated by reference (5), audit evidence (1), prototype (7), historical (9) | as listed in V3 |
| `NON_NORMATIVE_AUDIT_EVIDENCE` | the independent audit of the clarification | not stored in the repository |
| `HISTORICAL_SUPERSEDED` | RSE-ARCH-1.0, RSE-ARCH-1.1 files and the first freeze record's classification | unchanged |

Precedence: this clarification controls over the native RSE-ARCH-1.2 text and the incorporated sections wherever they conflict (notably `RSE12_01` §3 snapshot wording, the POLICY, DESTINATION and FOUNDATION_MODEL tails, and "approved" read as "usable").

## 5. Authorization locks and gate

Unchanged and preserved: `IMP_1_NOT_ACCEPTED`, `IMP_2_NOT_AUTHORIZED`, `NO_PROVISIONING_AUTHORIZED`, `NO_HARDWARE_PURCHASE_AUTHORIZED`, `NO_REAL_SECRET_CREATION`, `NO_CORPUS_GENERATION_AUTHORIZED`, `NO_QUALIFICATION_AUTHORIZED`, `NO_MODEL_SELECTION_AUTHORIZED`, `NO_GPU_AUTHORIZED`, `NO_TRAINING_AUTHORIZED`; `P0_SYNTHETIC_REHEARSAL_ONLY`; `DECISION_9R_P1_INDEPENDENT_WITNESS_CONFIRMED`. The amendment authorizes no code, no PR merge, and no change to Cursor's PR #7. `main` is not advanced by this record.

## 6. No-semantic-drift verification (performed at creation)

The candidate file at `62c128129f2c26968dd675df3e89e1a7561a82c3` and the working-tree file are byte-identical (same SHA-256). Every accepted constant named in §2 was checked to appear verbatim in the candidate: strings, codes, tail sizes (199, 33, 289), the Merkle prefixes, domains, scenario names 1–13, and the known-answer vectors. No contradiction was found. Manifest V2 is byte-identical to its copy on canonical `main`, and all 29 V2 entries re-verified before V3 was generated.

## 7. Canonicalization gate

Canonicalization requires: exact-SHA CI success on the commit that contains this record; verification of Manifest V3; and the explicit owner/ChatGPT authorization to fast-forward `main`. None is granted by this record.
