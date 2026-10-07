# RSE_ARCH_1_2_FREEZE_CANONICALITY_CORRECTION

Governance-only correction to the freeze package committed at `6da3b7c75740f2056853e5b8ef32eecaefde6e8c` (parent: accepted architecture `1df94810bc35692b0ce8c969978920d4dea06d8e`). It changes **no** architecture semantics: H1–H4, OCR1 v2, HPKE, Crown, registry, witness quorum, TPM/NV, P1 requirements, acceptance controls, P0/P1/P2, residuals and authorization locks are exactly as accepted. Every native RSE-ARCH-1.2 file is byte-identical to its accepted version; the manifest verifies this.

## 1. Canonicality rule

The governing architecture version is **RSE-ARCH-1.2**. **RSE-ARCH-1.0** and **RSE-ARCH-1.1** are `SUPERSEDED / HISTORICAL / NON-NORMATIVE` versions. No RSE-ARCH-1.1 file is normative in itself, and the earlier freeze-record wording "normative as amended" for `RSE11_01`–`RSE11_05` is **withdrawn**.

## 2. INCORPORATED_BY_REFERENCE mechanism

RSE-ARCH-1.2 depends on a limited set of material first authored in RSE11 documents. That material becomes part of the normative RSE-ARCH-1.2 specification **only** as the immutable, hash-identified sections listed in §5, by reference.

1. The incorporated immutable content becomes part of the normative RSE-ARCH-1.2 specification by reference.
2. RSE-ARCH-1.1 itself remains superseded and non-normative.
3. Any content of a historical file that is **not** explicitly incorporated in §5 has **no normative authority**, including the remainder of the same file.
4. Where RSE-ARCH-1.2 conflicts with incorporated historical text, **RSE-ARCH-1.2 controls**. Examples already known: `RSE11_02` §H's reference to "ACTIVE (§V)" and its "separated by time or action" phrase are governed by `RSE12_02` §2 (a grant needs the required distinct token signatures; wall-clock time separation is not an enforced property); `RSE11_03` ingestion text is governed by `RSE12_04` §6; `RSE11_04` recovery scenarios are governed by `RSE12_05` §4 where they differ.
5. Identity: a section is identified by file path, the SHA-256 of the whole file as committed at `1df94810bc35692b0ce8c969978920d4dea06d8e`, the line range, and the SHA-256 of the section bytes (heading line through the line before the next heading of equal or higher level, newline-terminated). A section whose hash does not match carries no authority.
6. The sentence in `RSE12_00` that "parts of 1.1 that 1.2 does not mention … remain in force as amended" is **overridden by this record**: only §5 sections are in force. `RSE12_00` is left byte-identical because it is a frozen accepted file; this record controls its interpretation.

Not incorporated (no authority; superseded by the 1.2 file shown): `RSE11_02` §J (→ `RSE12_06` §1), §S (→ `RSE12_04` §8), §V (→ `RSE12_02` §2, §9); `RSE11_03` §M other than the two subsections below (→ `RSE12_04`), §N and §O (→ `RSE12_02`), §W (→ `RSE12_03`); `RSE11_04` §L (→ `RSE12_05` §1), §P other than "Recovery scenarios" (→ `RSE12_05` §4), §T (→ `RSE12_05` §7), §X (→ `RSE12_05` §6), §Z (→ `RSE12_05` §2), §AB (→ `RSE12_05` §4); `RSE11_05` §AF (→ `RSE12_06` §7), §AG (→ `RSE12_06` §4), §AH (→ `RSE12_06` §5), §AI (→ `RSE12_06` §8), "Complexity budget" and "Future God-mode governance" (→ `RSE12_06` §3, §6); `RSE11_00`, `RSE11_06`; all of RSE-ARCH-1.0.

## 3. Corrected normative set

**Seven native RSE-ARCH-1.2 normative documents:** `RSE12_00_INDEX_HISTORY_CLOSURE.md`, `RSE12_01_REGISTRY_CROWN.md`, `RSE12_02_WITNESS_LEDGER_FRESHNESS.md`, `RSE12_03_ROLLBACK_TPM.md`, `RSE12_04_OCR1_GRANTS_ENROLMENT.md`, `RSE12_05_CUSTODY_RECOVERY_SUPPLY_NETWORK.md`, `RSE12_06_P1_ACCEPTANCE_OPERATIONS.md` (`RSE12_00` through `RSE12_06`; not eight). Plus the **incorporated-by-reference sections** of §5 (five historical files, 21 section entries, counting §M's two subsections and §P's one subsection as entries).

`RSE12_07_SELF_ATTACK.md` is `NON_NORMATIVE_AUDIT_EVIDENCE`. The prototype is `NON_NORMATIVE_PROTOTYPE` (`STRUCTURAL_CODEC_EVIDENCE_ONLY`). Everything else is `HISTORICAL_SUPERSEDED`, including the first freeze record (classification only; its binding, guardrails, residuals, locks and gate rule stand) and the first manifest.

## 4. Manifest V2

`RSE_ARCH_1_2_FREEZE_MANIFEST_V2.txt` assigns every listed file exactly one class: `NORMATIVE_NATIVE_1_2`, `NORMATIVE_INCORPORATED_BY_REFERENCE` (named sections only), `NON_NORMATIVE_AUDIT_EVIDENCE`, `NON_NORMATIVE_PROTOTYPE`, `HISTORICAL_SUPERSEDED`. No file has ambiguous status.

**Manifest V2 SHA-256: `5b352e2c01f6fa9d1ffb1406eee5ba89104f4d36b74dc3aa15df360c0ec0347d`.** It lists 29 files, does not list itself or this record, and supersedes the first manifest (`4ce5f0afe4c68503070ca0b4919f5e063585b6ab7ef4ebcdf6348e2d38c0c008`). Hashes of unchanged files are identical to the first manifest; only the first freeze record's hash changed (it gained a supersession banner), and it is now `HISTORICAL_SUPERSEDED`.

## 5. Incorporation register

Incorporation version: RSE-ARCH-1.2. Precedence: RSE-ARCH-1.2 controls.

| File (path under `docs/orneur/phase-21/rse/`) | File SHA-256 | Section | Lines | Section SHA-256 | Purpose | Version | Precedence |
|---|---|---|---|---|---|---|---|
| `v1.1/RSE11_01_BASELINE_RESEARCH_THREATS.md` | `200ee399815202aec19483e909d375123fef2513119a08362476576231a718b8` | ## A. Executive verdict | 5-12 | `59ae8e7d2726d2cd249773e1fe3c502751731776f09b74034aa59b45092626ce` | executive verdict and the seven-component reduction | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_01_BASELINE_RESEARCH_THREATS.md` | `200ee399815202aec19483e909d375123fef2513119a08362476576231a718b8` | ## B. True current-state baseline | 13-36 | `383b83c3b45517ec5a768266a77679a44daf4ce4f7ffcfc26fa869171bc879ac` | current-state baseline labels (extended by RSE12_00 for registry, floor card, prototype) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_01_BASELINE_RESEARCH_THREATS.md` | `200ee399815202aec19483e909d375123fef2513119a08362476576231a718b8` | ## C. External research (closure) | 37-57 | `82897649dfb030151bf4401400bdfeefb8efa639f80161bfe460b605753d700f` | external research record and SOURCE_UNAVAILABLE entries | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_01_BASELINE_RESEARCH_THREATS.md` | `200ee399815202aec19483e909d375123fef2513119a08362476576231a718b8` | ## D. Competitive matrix | 58-72 | `ae096cb531b55dbe84e3a9e782bb1bfe9e6fefa8cba352ce5d8e5ab7d8868472` | competitive comparison | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_01_BASELINE_RESEARCH_THREATS.md` | `200ee399815202aec19483e909d375123fef2513119a08362476576231a718b8` | ## E. Threat model | 73-82 | `b3f7b1f00dcb43fe05615a8e36c27fa50e7ae23c747c37b9d616c360498ea8aa` | adversary list and assets (extended by the structured table in RSE12_06 section 2) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_01_BASELINE_RESEARCH_THREATS.md` | `200ee399815202aec19483e909d375123fef2513119a08362476576231a718b8` | ## F. Trust-root decomposition | 83-94 | `43b304be40b39382ef8904b0dcd32882f2eec934e44c9f4b8d9f89a2aa8a8ed1` | trust-root decomposition | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_02_ROLES_CROWN_GRANTS.md` | `82e0ceabf71f4d28b10f2315c64557b27272ec7832aa729cd2e31aebe55a7f48` | ## G. Sovereign-plane architecture | 5-18 | `f424a3eb6856a68eca37b4fbb047630bf2c5a703afae5c8cd8cf6f0d98e44fe1` | sovereign-plane components and complexity rule | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_02_ROLES_CROWN_GRANTS.md` | `82e0ceabf71f4d28b10f2315c64557b27272ec7832aa729cd2e31aebe55a7f48` | ## H. Crown (redesigned: daily-driver assumed fully compromised) | 19-54 | `fc23576af04a06b260b0d92fc50540d9c9f1ee84a0bcda66d989cf254e838cd6` | Crown views, protocol, DUAL_TOKEN_OWNER_CONFIRMATION terminology, confirmation scope, Crown device roadmap (RSE12_01 adds to it) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_02_ROLES_CROWN_GRANTS.md` | `82e0ceabf71f4d28b10f2315c64557b27272ec7832aa729cd2e31aebe55a7f48` | ## I. Forge — plaintext exposure correction (B11) | 55-60 | `fcc3a78b983a4b148ba9b4b2db7aff79817637a62bf920b2e284241f4ad61cb2` | Forge plaintext exposure lifecycle | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_02_ROLES_CROWN_GRANTS.md` | `82e0ceabf71f4d28b10f2315c64557b27272ec7832aa729cd2e31aebe55a7f48` | ## K. Vault (logical) | 96-99 | `5961db19650ef84df71630b7103dc9df20cb8677e6b81a81465d165913df51ad` | logical Vault | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_02_ROLES_CROWN_GRANTS.md` | `82e0ceabf71f4d28b10f2315c64557b27272ec7832aa729cd2e31aebe55a7f48` | ## Q. Hardware-rooted identity and attestation | 100-104 | `83b655726161fa2ac7e7d4fdc29a7bd36e62d09e7ff92b595c111ec2ccf95cbb` | hardware-rooted identity and attestation (with RSE12_03) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_02_ROLES_CROWN_GRANTS.md` | `82e0ceabf71f4d28b10f2315c64557b27272ec7832aa729cd2e31aebe55a7f48` | ## R. Key hierarchy (design names only; no key exists) | 105-118 | `51d36ecbde1e511b39f8f2199f14b959b40335902e850df7fd9d7e1e8f21a021` | key hierarchy names (with RSE12_04 section 2) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_03_LEDGER_TRANSFER_STORAGE.md` | `720f96716087ed11255a54fc83ab4e6119e3f50ebb40e807c3dd568e4585a029` | ### Two-phase key-absent ingestion | 42-46 | `cd7d2dffe0b51be663adebb15c524355b8f843ccd6aa76c3db49050ef07dc988` | ingestion phase concept (RSE12_04 section 6 specifies the steps) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_03_LEDGER_TRANSFER_STORAGE.md` | `720f96716087ed11255a54fc83ab4e6119e3f50ebb40e807c3dd568e4585a029` | ### Plaintext handoff | 47-50 | `262993aa103e29f43751f1dd093a58f026ba69e694f70bea0f05c1a6cd76e30c` | decryptor to bounded pipe to keyless sandboxed checker | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_03_LEDGER_TRANSFER_STORAGE.md` | `720f96716087ed11255a54fc83ab4e6119e3f50ebb40e807c3dd568e4585a029` | ## U. Storage and plaintext lifecycle | 80-98 | `632256510f9213b72c2ff9fd24e775765618910f4ea5dc16a2c7e0672d0a8549` | storage and plaintext lifecycle strength labels | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_04_CUSTODY_RECOVERY_SUPPLY.md` | `25a75313337b23f7e3ae55b91256b364cfd396bcd79102ea391f6a328f34a27b` | ### Recovery scenarios | 18-32 | `541e53030f47d53f5f439c6e268c2f3c6a6c6f38d3bffd003bf65832454b1da4` | recovery scenario table (RSE12_05 section 4.4 keeps it) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_04_CUSTODY_RECOVERY_SUPPLY.md` | `25a75313337b23f7e3ae55b91256b364cfd396bcd79102ea391f6a328f34a27b` | ## Y. Corpus custody lifecycle | 62-77 | `5401cca0186f48c62e5c0f4e99f32539e85c5566b73b3b27c311c950a4c2d74a` | corpus custody lifecycle (as amended by RSE12_05 section 3) | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_04_CUSTODY_RECOVERY_SUPPLY.md` | `25a75313337b23f7e3ae55b91256b364cfd396bcd79102ea391f6a328f34a27b` | ## AA. Compromise scenarios | 82-107 | `4f51bdf41de3f18900ff06df0207eb864484e598bd0b13327fa7cb8f651f1c0d` | compromise scenarios | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_05_PROFILES_ACCEPTANCE_FUTURE.md` | `75115ccdd8dff3eeab4c8312eb686af9e3ef3fa88404ef446c2bc40dade115c6` | ## AC. P0 / P1 / P2 re-evaluation | 5-12 | `b163f6bfe7b2499ce28db03729293df2b7c9e17d2208bd439d624d59db060bb8` | P0/P1/P2 definitions | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_05_PROFILES_ACCEPTANCE_FUTURE.md` | `75115ccdd8dff3eeab4c8312eb686af9e3ef3fa88404ef446c2bc40dade115c6` | ## AD. Novelty classification | 13-28 | `b0a953f5400fdb4526986b6ac857a4670555683110f61262ff416c84dd6f9748` | novelty classification | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |
| `v1.1/RSE11_05_PROFILES_ACCEPTANCE_FUTURE.md` | `75115ccdd8dff3eeab4c8312eb686af9e3ef3fa88404ef446c2bc40dade115c6` | ## AE. Hardware dependency matrix | 29-40 | `fe580e78f47f2a4c79cdf93bcfbf3c073925d9d18940d71edcdf7eba2152d950` | hardware dependency matrix | RSE-ARCH-1.2 | RSE-ARCH-1.2 controls |

## 6. Unchanged

Authorization locks (`NO_PROVISIONING_AUTHORIZED`, `NO_HARDWARE_PURCHASE_AUTHORIZED`, `NO_SECRET_CREATION_AUTHORIZED`, `NO_CORPUS_GENERATION_AUTHORIZED`, `NO_QUALIFICATION_AUTHORIZED`, `NO_MODEL_SELECTION_AUTHORIZED`, `NO_GPU_AUTHORIZED`, `NO_TRAINING_AUTHORIZED`), `P0_SYNTHETIC_REHEARSAL_ONLY`, `DECISION_9R_P1_INDEPENDENT_WITNESS_CONFIRMED`, and `ARCHITECTURE_IMPLEMENTATION_GATE = CLOSED` pending canonicalization (conditions in the first freeze record §8) are unchanged.
