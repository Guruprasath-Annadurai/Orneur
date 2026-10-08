# RSE-ARCH-1.2 — Clarification Candidate 1 (IMP-1 protocol constants and semantic rulings)

> **STATUS: `CLARIFICATION_CANDIDATE` — NOT CANONICAL.** It becomes part of RSE-ARCH-1.2 only after independent architecture review, the owner/ChatGPT decision, and a freeze-amendment record. It does not alter Manifest V2 (`5b352e2c…0347d`), any frozen file, any authorization, or any IMP-1 code. `IMP_1_NOT_ACCEPTED`; `IMP_2_NOT_AUTHORIZED`.

Baseline: canonical `main` `be54d5b0e6d1cdebca8923343dd9830d20ce1688`; frozen RSE-ARCH-1.2; IMP-1 candidate `3ebd6186eb9b500e0a3fe36613ce266f205cb8b7` (verdict `RSE_IMP_1_REMEDIATION_REQUIRED`). All integers are **unsigned big-endian**; ranges are inclusive; any value outside a stated range is rejected. "Reserved" means *rejected by every parser until a later clarification assigns it*. Where this candidate and an incorporated historical section disagree, this candidate (once adopted) controls.

## 0. Summary table (ACR-1 … ACR-14 and the three extra rulings)

"Wire-normative" = changes bytes that are signed, hashed into an ID, or persisted. "Effect on frozen text": **D** = disambiguates a gap; **A** = amends/tightens a frozen statement (flagged for the independent audit); **P** = process rule, no architecture change.

| ID | Subject | Wire-normative | Effect | Section |
|---|---|---|---|---|
| ACR-1 | Registry Merkle profile | yes | D | §1 |
| ACR-2 | `OREG` v1 framing and limits | yes | D | §2 |
| ACR-3 | Signature and key-ID domains | yes | D | §3 |
| ACR-4 | Lifecycle codes | yes | D | §4 |
| ACR-5 | Retirement codes | yes | D | §4 |
| ACR-6 | Role-type codes | yes | D | §4 |
| ACR-7 | POLICY widths and order | yes | D (widths) / A (added fields, §6) | §6 |
| ACR-7b | Policy semantics; role identity independent of family | yes | **A** (removes Cursor's per-policy role binding; adds `family_scope`, destination allow-list) | §6 |
| ACR-8 | DESTINATION kinds; remove recipient field | yes | D vs frozen; reverses Cursor | §7 |
| ACR-9 | W/R missing constants only | yes | D | §8 |
| ACR-10 | Crown phrases and complete rendering | no (display) | D | §9 |
| ACR-11 | Historical entries below floor decode | yes (parser) | D | §10 |
| ACR-12 | Exact registry-snapshot binding | no (check) | **A** (tightens `RSE12_01` §3) | §11 |
| ACR-13 | FOUNDATION_MODEL artifact-format and inspection fields | yes | **A** (tail 256 → 289 bytes) | §12 |
| ACR-14 | K scenario codes | yes | D | §13 |
| M | IMP-1 milestone rule | no | P | §14 |
| L | Model lineage | no (admission check) | D | §15 |
| C | Consumer identity binding | no (check) | D | §16 |

No ruling grants any role new authority. Most rulings only fix a value or restrict what IMP-1 may accept. ACR-7b deliberately **relaxes** IMP-1's per-policy role binding (as the owner ruled) and compensates with authorization-time policy checks; ACR-7b and ACR-13 add fields to existing tails, which is why they are marked A.

## 1. ACR-1 — Registry Merkle profile

`registry_root` is the RFC 6962 §2.1 Merkle Tree Hash over the ordered list `D[0..n-1]` of 32-byte `ENTRY_ID` values:

- Leaf hash: `SHA-256(0x00 ‖ ENTRY_ID)`.
- Node hash: `SHA-256(0x01 ‖ left ‖ right)`.
- Split: for `n ≥ 2`, `k` = the largest power of two **strictly less than** `n`; `MTH(D) = node(MTH(D[0:k]), MTH(D[k:n]))`. For `n = 1`, `MTH = leaf hash`. No odd-node duplication.
- Empty tree: **not supported.** `entry_count` is 1..1024; a registry with zero entries is rejected.
- Order: entries appear in **strictly ascending unsigned-lexicographic order of `ENTRY_ID`** (so one entry set has exactly one encoding). Equal or descending neighbours are rejected.
- This tree is **not** the Evidence Ledger tree. Its root is only used inside `OREG` objects and grants. If it is ever logged, it enters the ledger as a typed record leaf (IMP-3 decision), never as a bare ledger root. No inclusion or consistency proof format is defined here; none is needed to verify the whole object, since the verifier holds all entries and recomputes the root.

## 2. ACR-2 — `OREG` v1 wire framing

| Offset | Field | Size | Rule |
|---|---|---|---|
| 0 | magic `OREG` | 4 | exact |
| 4 | format_version | 1 | must be 1; any other value rejected (no negotiation) |
| 5 | registry_version | 4 | ≥ 1 |
| 9 | previous_registry_root | 32 | all-zero **iff** registry_version = 1 |
| 41 | entry_count | 4 | 1..1024 |
| 45 | entries | variable | each entry = 274-byte common block + type-specific tail (§5), ascending `ENTRY_ID` |
| … | registry_root | 32 | must equal the §1 computation |
| … | signatures | 130 | exactly two: `slot (1) ‖ Ed25519 signature (64)` each; slots distinct and the two signing public keys distinct |

Limits: at most 1024 entries; at most 1,048,576 total bytes (never binding before the entry cap, kept as a defence). Reject: truncated input, any trailing byte, unknown format_version, count out of range, non-canonical entry, unsorted/duplicate entries, root mismatch, wrong signature count or length. The slot-to-public-key mapping is the owner token set for the verifying role (an input, not part of the object); how that set is distributed is outside IMP-1.

## 3. ACR-3 — Domains (all persisted-identity or signature-affecting constants)

| Use | Exact bytes |
|---|---|
| Registry signature message | `"OREG-SIG" ‖ 0x00 ‖ format_version (1 byte) ‖ registry_body`, where `registry_body` = bytes from offset 0 through the end of `registry_root` (excludes the signatures) |
| Key ID of an Ed25519 public key | `KEYID(pk) = SHA-256("OREG-TOKEN" ‖ 0x00 ‖ pk32)` |
| Grant signatures | unchanged and frozen: `"OCG1-SIG" ‖ 0x00 ‖ class` ‖ grant signed region |
| SAS | unchanged: `"OCR-SAS-v1" ‖ 0x00 ‖ class ‖ signed region` |

Signature algorithm: Ed25519 (RFC 8032, pure). No domain string is implementation-local. None of these strings is a prefix of another, and each is followed by `0x00`. **Open, not ruled here (OPEN-1):** the semantic meaning of the common field `signing_key_id`; IMP-1 treats it as an opaque 32-byte field that no decision depends on.

## 4. ACR-4, ACR-5, ACR-6 — Numeric codes

`0` is invalid in every table. Unlisted values are reserved and rejected.

| Field | Codes |
|---|---|
| Lifecycle (MODEL) | 1 CANDIDATE, 2 QUALIFIED, 3 ACCEPTED, 4 EXPORTED, 5 DEPLOYED, 6 RETIRED; 7–255 reserved |
| Retirement (CORPUS) | 1 ACTIVE, 2 RETIRED; 3–255 reserved |
| Role type (ENROLMENT) | 1 CROWN, 2 FORGE, 3 WITNESS, 4 MONITOR_LITE; 5–255 reserved |
| Approval state (frozen) | 1 PENDING, 2 APPROVED, 3 DEPRECATED, 4 REVOKED; others rejected |
| Entry type (frozen order) | 1 CODE, 2 ROLE_IMAGE, 3 FOUNDATION_MODEL, 4 TOKENIZER, 5 MODEL, 6 CORPUS, 7 ENROLMENT, 8 POLICY, 9 DESTINATION, 10 HOLDOUT_SET; others rejected |

Monitor-Lite primary and secondary (M1, M2) are both type 4; they are distinguished by their ENROLMENT entries and the policy witness requirement. Numbers carry no ordering semantics beyond identity; no implementation may use a language enum's implicit ordering.

## 5. Entry layout (common block + tails)

Common block, 274 bytes, unchanged from `RSE12_01` §2: `entry_type 1, name 64 (ASCII [A-Za-z0-9._-]{1,64}, zero-padded, non-empty), version u32, artifact_digest 32, provenance_digest 32, producer_entry_id 32, approval_state 1, min_permitted_version u32, policy_entry_id 32, signing_key_id 32, approval_evidence_checkpoint 32, not_after u64`. `ENTRY_ID = SHA-256(canonical entry bytes)`.

Tail lengths after this candidate: CODE 0; ROLE_IMAGE 36; **FOUNDATION_MODEL 289** (was 256); TOKENIZER 64; MODEL 129; CORPUS 165; ENROLMENT 101; **POLICY 199** (was 70); **DESTINATION 33** (was 65); HOLDOUT_SET 40. Names `.` and `..` are additionally rejected (they are path components). Confusable-name rule unchanged (`0/O`, `1/l/I`).

## 6. ACR-7 and ACR-7b — POLICY and family scope without identity contamination

### 6.1 Tail layout (199 bytes, fixed order)

| Off | Field | Width |
|---|---|---|
| 0 | max_batch_bytes | u64 |
| 8 | max_runtime_s | u32 |
| 12 | max_spend (minor units) | u64 |
| 20 | max_run | u32 |
| 24 | max_query_budget | u32 |
| 28 | max_bit_budget | u32 |
| 32 | min_grant_schema_version | u32 |
| 36 | witness_requirement | u8 (1 ROUTINE, 2 IRREVERSIBLE, 3 IRREVERSIBLE_PLUS_OWNER_CHECKPOINT; 0 and 4–255 rejected) |
| 37 | allowed_operations | u8 bitmask, bit 0 G, 1 V, 2 K, 3 Q, 4 T, 5 W, 6 D, 7 R (same order as `RSE12_04` §8); value 0 rejected |
| 38 | family_scope | 32 bytes: one `family_id`, or all-zero = family-neutral policy |
| 70 | destination_count | u8, 0..4 |
| 71 | permitted_destinations | 4 × 32 bytes; first `destination_count` are DESTINATION `ENTRY_ID`s, strictly ascending; the rest all-zero |

Caps are inclusive upper bounds; a cap of 0 means "that resource may only be requested as 0" (never unlimited).

### 6.2 Rulings

1. **Role identity does not depend on family policy.** An ENROLMENT entry's `policy_entry_id` MUST be all-zero. The same holds for ROLE_IMAGE, CODE and DESTINATION ("family-neutral" entries). Therefore a Forge, Witness, Crown or Monitor-Lite keeps the same `ROLE_ID` across Genesis, Novus and Aeternum while its role type, keys, environment measurement, key version and other canonical enrolment bytes are unchanged. Operating for another family changes no byte of the ENROLMENT entry. (Approval-state changes still change the ID, as frozen: revocation kills the ID.)
2. **Family-bearing entries** — TOKENIZER, FOUNDATION_MODEL, MODEL, CORPUS, HOLDOUT_SET — MUST carry `policy_entry_id` = a POLICY entry in the same registry. POLICY entries carry zero.
3. **Where family scope lives:** only in `POLICY.family_scope` and in the `family_id` fields of FOUNDATION_MODEL and MODEL. A grant names exactly one POLICY. Authorization-time rules:
   - Every family-bearing entry a grant references must have `policy_entry_id` equal to the grant's POLICY.
   - For FOUNDATION_MODEL and MODEL, the entry's `family_id` must equal `POLICY.family_scope`, which must be non-zero.
   - A K grant requires a family-neutral POLICY (`family_scope` all-zero).
4. **Destinations are shared, authority is not:** a DESTINATION entry may serve several families only if each family's POLICY lists its `ENTRY_ID` in `permitted_destinations` and the grant names it. A destination not in the grant's POLICY list is refused.
5. **One family per policy** (zero or one `family_scope`). This keeps "no family inherits another's authority" structurally checkable. A multi-family policy is deliberately not defined (OPEN-2 for the audit).
6. Role permission is by **role type per class** (§16), not by listing role IDs in a policy.

## 7. ACR-8 — DESTINATION

Tail (33 bytes): `kind u8 ‖ identifier_digest 32`. Codes: `1 MEDIUM` (carried medium), `2 RECIPIENT_ROLE` (delivery to the role the **grant** names), `3 EXPORT_TARGET`; 0 and 4–255 reserved. `identifier_digest` is an opaque, non-zero descriptor digest. **The extra recipient-role field is removed**: the recipient is named only by the grant's `recipient_role_id`, so there is a single source of target authority. For G, the destination kind must be 1 or 2.

## 8. ACR-9 — W and R missing constants (layouts unchanged and frozen)

- W `format`: 1 = DATA_ONLY_TENSOR_V1 (the same code space as §12); every other value rejected at parse.
- R `reason`: 1 SUPERSEDED, 2 COMPROMISED_OR_SUSPECTED, 3 POLICY_VIOLATION, 4 END_OF_LIFE; 0 and 5–255 reserved.
- No W/R semantics are specified or implemented by this candidate (§14).

## 9. ACR-10 — Crown phrases and complete rendering

Phrases are display text, not signed bytes, and may stay implementation-local **only if all hold**: (a) deterministic from the signed class (and, for K, the signed scenario) through a fixed table; (b) pairwise distinct per class and per K scenario, uppercase ASCII; (c) no proposer free text, only registry names and signed numbers; (d) **every signed field that has human meaning is rendered**. Per class the card must show: all registry-resolved names/versions (with approval state and min version), target role and key version, destination name, and every numeric ceiling or ID-derived name in the tail (G: batches, bytes; Q: run, query and bit budgets; T: spend and run; W: size; D: spend, run and release version; K: scenario name, new authority version, new epoch, checkpoint-root short form, revoked roles by name; R: object name and reason name), plus epoch, registry version, authority version, floor result and SAS. **K renders its actual scenario name** (§13), never a generic "RE-ROOT" label.

## 10. ACR-11 — Entries below today's floor decode

Canonical decoding **must not** reject an entry because `version < min_permitted_version`; a historical snapshot stays parseable. Representation is not authorization: when anything *uses* an entry, the authority layer rejects it if `entry.version < effective_min_version`, where `effective_min_version(type, name)` = the maximum `min_permitted_version` over all entries with that type and name in the same registry snapshot (including the entry itself). Admission checks that require a referenced entry to be "approved" (for example, a tokenizer bound by a foundation) mean *usable* in this sense.

## 11. ACR-12 — Exact registry-snapshot binding

A grant binds exactly one `(registry_version, registry_root)`. Crown signs against that snapshot; the consumer verifies against that snapshot. The consumer MUST refuse a grant when (a) its held snapshot differs from the grant's, or (b) it has authenticated any registry with a higher version than the grant's. In either case the grant is permanently unusable; the consumer voids its outstanding challenge and issues a new `OCH1` (`RSE12_02` §5), and a new grant is signed against the new snapshot. Outstanding authority is never reinterpreted against a newer registry. This is intentionally stricter than "≥" and means every registry update invalidates all unconsumed grants (an availability cost accepted by the owner).

## 12. ACR-13 — FOUNDATION_MODEL metadata

Tail (289 bytes): `family_id 32 ‖ foundation_model_id 32 ‖ foundation_revision 64 ‖ tokenizer_entry_id 32 ‖ weights_digest 32 ‖ license_record_digest 32 ‖ architecture_config_digest 32 ‖ artifact_format 1 ‖ inspection_evidence_digest 32`.

- `foundation_revision`: ASCII `[A-Za-z0-9._-]{1,64}`, zero-padded, non-empty.
- Common-field roles for this type: `artifact_digest` = digest of the exact approved artifact package; `provenance_digest` = digest of the source record (publisher and retrieval source), non-zero.
- `artifact_format` codes: **1 DATA_ONLY_TENSOR_V1** (a data-only container: tensors and metadata, no object deserialization, no code-loading hooks); **128 EXECUTABLE_OR_CODE_LOADING** (e.g. pickled-object or arbitrary code-loading formats); **255 UNINSPECTED**; all other values reserved. Only code 1 may be `APPROVED`; 128 and 255 may appear in `PENDING`, `DEPRECATED` or `REVOKED` entries and can never be approved or used.
- Approval admission requires: format 1; non-zero `inspection_evidence_digest`; every digest and the revision non-zero; tokenizer entry usable and in the same POLICY; `family_id` = POLICY `family_scope`. The inspection tool and its evidence are owner-approved artifacts; this candidate fixes only that the evidence is referenced by digest. No foundation is selected.

## 13. ACR-14 — K scenario codes

Derived from the frozen recovery material (`RSE11_04` "Recovery scenarios", `RSE12_05` §4, `RSE12_03` §3). `0` invalid; 14–255 reserved; **no universal fallback; 255 is rejected.**

| Code | Name | Frozen source |
|---|---|---|
| 1 | EPOCH_RAISE | epoch bump after theft or suspicion (`RSE12_05` §4.1) |
| 2 | FORGE_REBUILD | lost Forge storage |
| 3 | WITNESS_REBUILD | lost Witness drive |
| 4 | TPM_REPLACE | TPM or motherboard replacement (`RSE12_03` §3.2) |
| 5 | WITNESS_ENV_UPDATE | environment generation N→N+1 (`RSE12_03` §3.1) |
| 6 | TOKEN_REPLACE | lost owner token |
| 7 | CHECKPOINT_HOLDER_REPLACE | ledger service loss, checkpoint holder lost, M1→M2 handover (`RSE12_02` §3) |
| 8 | CHECKPOINT_ROOT_REESTABLISH | lost paper checkpoint |
| 9 | ARTIFACT_REPO_RECOVERY | compromised artifact repository |
| 10 | CORPUS_RESTORE | corpus corruption |
| 11 | WEIGHTS_RESTORE | trained-weight corruption (future) |
| 12 | LUKS_SLOT_ROTATION | recovery passphrase theft response (`RSE12_05` §4.1) |
| 13 | RE_ROOT | all tokens lost; re-root ceremony |

Parse-level constraints: `checkpoint_root` non-zero; `revoked_count` ≤ 8; unused revoked slots zero. Semantic constraints, binding when K becomes executable (not in IMP-1): no scenario may lower `new_authority_version` or `new_epoch` below the current values; `new_epoch` must exceed the current epoch for EPOCH_RAISE, TOKEN_REPLACE, ARTIFACT_REPO_RECOVERY, LUKS_SLOT_ROTATION and RE_ROOT (the frozen text raises or bumps the epoch there); `new_authority_version` must exceed the current for RE_ROOT.

## 14. Implementation-milestone rule

For RSE-IMP-1 only **G** and **V** may receive complete semantic validation and the final success result (`CHECKS_PASSED`, never executable). **K, Q, T, W, D, R** have: canonical parse and layout, registry-entry support, and deterministic display; but `crown_validate` and `consumer_verify` MUST return `FAIL_CLOSED` with reason `UNSUPPORTED_CURRENT_MILESTONE` for them, and no other public function may report a deferred-class grant as valid. Their frozen future architecture is unchanged. Carry-forward obligations (already frozen; recorded so they are not lost): W must equal the model entry's `qualification_record_digest`; T and Q-linked corpora need a non-zero witnessed acceptance record; D may reference an exported **or** accepted model; each class defines its own target-role type then.

## 15. Model lineage

`MODEL.family_id` MUST equal its parent's `family_id` (parent is a FOUNDATION_MODEL or MODEL), and the MODEL and its parent MUST share the same `policy_entry_id`. Registry admission rejects cross-family parentage. A foundation and its tokenizer must share a POLICY. Genesis, Novus and Aeternum remain independently governed, with no inherited approval.

## 16. Consumer identity (and the G/V role matrix)

`consumer_verify` takes the consumer's own `ROLE_ID` and its **observed environment identity** (from the role's measured or enrolled state, never from the registry). It MUST check: `grant.target_role_id == own ROLE_ID`; the ENROLMENT entry is usable and of the class's required role type; `grant.env_measurement_digest` equals both the observed identity and the enrolment's environment measurement. For Mac-based roles the observed identity is `SELF_ATTESTED` and is labelled so. Challenge equality is required **in addition**, never instead. Role types: G — target FORGE, recipient WITNESS; V — target WITNESS, sender FORGE. Other classes' matrices are defined at their milestones. Also required: allowed-operation bit for the class; ceilings `batch_count`, `batch_ceiling_bytes`, `max_runtime_s` ≥ 1 and ≤ the policy caps; destination per §6.2 and §7; corpus bound to the grant's policy, ACTIVE, and its `source_provenance_digest` equal to the grant's.

## 17. Known-answer vectors (synthetic, non-secret; for independent implementers)

Let `ID[i] = SHA-256(byte i)`. Tree function over `ID[0..n-1]` in index order (a real registry additionally requires ascending order):

| n | registry_root |
|---|---|
| 1 | `d9de27625445003d8a9739a851e3ff8d41c0683630b4d63a88327a6aaa37c409` |
| 2 | `604d540f09268b91672ab011394d5266ccd7d4484d0d109411a55848126a1b2c` |
| 3 | `d1f13800048f5909d4043fc0c152f6643280cba608b672715e56ce159a20629f` |
| 5 | `6b313b611b40676b9e1dfd70c4503f2379f88f0f1c2740fb7e1cacc32c113465` |
| 8 | `80e139b44c90f91edebec705cc7586c3d90f4bdadd49628d25c20d4b03419287` |
| 9 | `aaba260cc2c4084b1d745f8817ad3d3350c5b005d8283bc3246396eee0ad9538` |

`KEYID(pk = 0x00,0x01,…,0x1f) = a43087ff40fd894549ae4283ba15466b00fa89847631ecc9323789cda4b72719`. SAS: class `G` (0x47) over an empty signed region → `W2BQ-3RAG-W5U3`; class `T` (0x54) over bytes `00..0f` → `FLC7-AFYI-RPWJ`. Vectors were computed with an independent script (base32 of the first 8 digest bytes, first 12 characters) and match the current IMP-1 SAS and Merkle code.

## 18. Required conformance tests (for IMP-1 remediation and re-audit)

Each ACR needs a positive and a negative test using the vectors above and independent derivations: unsorted/duplicate entry order rejected; empty registry rejected; each reserved code rejected; ENROLMENT with non-zero policy rejected and its ID identical across two policies; destination outside the policy list refused; DESTINATION with a 65-byte tail rejected; foundation formats 128/255 cannot be approved; revision control bytes rejected; historical below-floor entry decodes but cannot be used; grant against an older or newer snapshot refused and challenge voided; every K scenario code 0, 14, 255 rejected; every deferred class returns `UNSUPPORTED_CURRENT_MILESTONE` from both Crown and consumer; cross-family MODEL parentage rejected at admission; consumer rejects a grant for another ROLE_ID or measurement with the correct challenge; the fuzz test asserts that no mutated input passes.

## 19. Self-attack of this candidate

| Attack | Result |
|---|---|
| Sorted-order rule creates malleability or a canonical-order bypass | none: ascending order gives one encoding per set; equal IDs rejected |
| Registry Merkle second preimage (leaf versus node) | blocked by the `0x00`/`0x01` prefixes; truncation changes the root |
| Cross-protocol signature reuse (registry ↔ grant ↔ SAS) | blocked: distinct NUL-terminated domains, distinct object lengths |
| Reserved/unknown codes accepted by a lenient parser | blocked by "reserved ⇒ rejected" in every table |
| Family-neutral entry smuggling a family via `policy_entry_id` | blocked: non-zero policy on a neutral entry is rejected |
| Destination reuse leaks authority across families | blocked: it must be in the grant's POLICY list |
| Historical below-floor entry used as a tokenizer/parent | blocked: admission means *usable* |
| Registry update races an unconsumed grant | grant dies, challenge voided; availability cost, no authority gain |
| `foundation_revision` or format downgrade to hide a pickle | blocked: only format 1 with non-zero inspection evidence is approvable |
| Deferred-class grant accepted through a side API | blocked by the single-gate rule (§14) and conformance tests |
| Multi-family policy ambiguity | avoided by one family per policy; flagged OPEN-2 |
| `signing_key_id` meaning | not ruled (OPEN-1); no decision depends on it |

Residual: the owner token set is an input; format-1 inspection depends on an owner-approved tool; M1/M2 identical-type distinction relies on enrolment entries. No HIGH issue found in the candidate; the independent audit should expect findings.

## 20. Open items for the independent audit

OPEN-1 meaning of `signing_key_id`. OPEN-2 whether multi-family policies are ever wanted. OPEN-3 whether ascending-`ENTRY_ID` ordering is accepted over the author's insertion-order option. OPEN-4 whether K per-scenario epoch rules should be frozen now or at the K milestone.
