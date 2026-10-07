# RSE-ARCH-1.2 — Part 4: OCR1 v2 envelope, cryptographic construction, grants, enrolment (closes H4)

Architecture only. No production code, key or secret exists or is created by this document. The 1.1 "OCR1 version 1" layout is **withdrawn** (it had no encapsulation or nonce field and no frame-set rules). Where this part and `RSE11_03` §M differ, this part governs.

Evidence classes used in this package: `STRUCTURAL_CODEC_EVIDENCE` (grammar behaviour; see `prototype/`) versus `CRYPTOGRAPHIC_IMPLEMENTATION_EVIDENCE` (none exists; it is an acceptance item, `RSE12_06`).

## 1. Construction decision: HPKE versus the existing ECIES-style pattern

The existing encrypted store uses an ad hoc public-key AEAD wrapper with a JSON header parsed with the key present. Options weighed:

| Option | For | Against |
|---|---|---|
| Keep the ad hoc ECIES-style wrapper | already in repository | no published profile or test vectors; JSON header; each implementer re-decides KDF inputs, which is the "hidden second protocol" problem |
| **HPKE, RFC 9180, Base mode** | published standard with test vectors; includes both public keys and the caller's `info` in the key schedule (RFC 9180 §9.1 says this mitigates malleability of earlier ECIES designs); explicit sequence-number nonces; several independent implementations (Go standard library `crypto/hpke`, OpenSSL ≥ 3.2 HPKE API, the Rust `hpke` crate, the Python `pyhpke` package, all observed to exist this phase; their audit status and exact API surface were **not** reviewed) | Base mode gives **no sender authentication**; library maturity must be checked at implementation time |
| age-style file format | widely used chunked encryption | its own text header grammar (parser surface), no sender authentication, no place for grant/epoch binding |
| libsodium sealed box | simple | one message, no context binding, no multi-frame structure |

**Decision: HPKE Base mode with the exact profile below, plus a separate Ed25519 sender signature.** Rationale for keeping the signature rather than using HPKE Auth mode: Auth mode proves origin only to the recipient through static Diffie-Hellman (RFC 9180 §9.1 notes key-compromise-impersonation limits and it is deniable); the ledger and later auditors need origin evidence verifiable by third parties and by the Monitor-Lite without the recipient's private key. If, at implementation time, no vetted HPKE library meets the profile, the fallback is **not** "invent something": the architecture owner must re-open this decision.

## 2. Exact profile

| Element | Value |
|---|---|
| HPKE mode | `mode_base` (0x00) |
| KEM | `DHKEM(X25519, HKDF-SHA256)`, ID 0x0020 |
| KDF | `HKDF-SHA256`, ID 0x0001 |
| AEAD | `ChaCha20Poly1305`, ID 0x0003 (Nk 32, Nn 12, Nt 16) |
| Sender signature | Ed25519 (RFC 8032), pure variant |
| Hash | SHA-256 |
| Context | one HPKE sender context per **bundle** (`SetupBaseS` once; one `Seal` per frame), per RFC 9180 §5.2 |

Test-vector requirement: the library used must reproduce the RFC 9180 Appendix A vectors for this suite before it is admitted to the artifact registry.

## 3. Envelope layout (type 1 or 2; fixed offsets; big-endian integers)

| Offset | Field | Size | Rule |
|---|---|---|---|
| 0 | magic `OCR1` | 4 | exact |
| 4 | version | 1 | must equal 2; any other value is rejected (no negotiation, no downgrade) |
| 5 | type | 1 | 1 corpus bundle (Forge→Witness); 2 weights export bundle (future) |
| 6 | recipient_id | 32 | enrolment entry ID (§6) |
| 38 | sender_id | 32 | enrolment entry ID |
| 70 | grant_id | 16 | grant governing this transfer |
| 86 | artifact_id | 32 | registry entry ID of the corpus/model being carried |
| 118 | bundle_digest | 32 | SHA-256 of the whole plaintext bundle |
| 150 | sequence | 8 | bundle sequence in the sender→recipient stream |
| 158 | incident_epoch | 4 | |
| 162 | frame_index | 4 | 0-based |
| 166 | frame_count | 4 | 1..65536 |
| 170 | total_len | 8 | plaintext bytes, ≥ 1 |
| 178 | enc | 32 | HPKE KEM encapsulation (X25519 public key); identical in every frame of a bundle |
| 210 | ciphertext | derived | see below; includes the 16-byte tag |
| 210+n | signature | 64 | Ed25519 |

Header = 210 bytes. **There is no ciphertext-length field**: the parser derives it. `FRAME_PT` = 1 MiB. `frame_count` must equal ⌈`total_len` / `FRAME_PT`⌉. Plaintext length of frame *i* is `FRAME_PT` for *i* < count−1 and `total_len − (count−1)·FRAME_PT` for the last; ciphertext length is that plus 16. Total frame length must equal exactly `210 + ct + 64`. **No reserved bytes, no flags, no extension area, no optional fields, no compression.** A new capability means a new version number and a new decoder; unknown versions are rejected.

Deliberate duplication: `enc` and the per-bundle fields repeat in every frame so each frame is self-describing and cross-bundle injection is detectable by equality, not by remembered state.

Canonical rule: decode then re-encode must reproduce the exact input bytes (trivially true for a fixed layout; kept as an invariant test). Bundle maximum: 65536 × 1 MiB = 64 GiB.

## 4. Sender procedure

1. Resolve `recipient_id` to an owner-approved, non-revoked enrolment entry in the sender's registry copy; take its KEM public key `pkR` (§6). Resolve the sender's own entry.
2. Compute `bundle_digest = SHA-256(plaintext)`; take `sequence` from the grant's range (never reused; forfeited on interruption, `RSE12_02` §8).
3. Derive the ephemeral key pair (§5) and run `SetupBaseS(pkR, info)` with
   `info = "OCR1v2-info" ‖ 0x00 ‖ header[0:162] ‖ header[166:178]`
   (all fixed bundle fields: magic, version, type, recipient, sender, grant, artifact, digest, sequence, epoch, frame_count, total_len — i.e., everything except `frame_index` and `enc`).
4. For frame *i* in order 0…count−1: build the 210-byte header with `frame_index = i` and the context's `enc`; `ct_i = Seal(aad = header_i, pt_i)`; signature `σ_i = Ed25519(skS, "OCR1v2-SIG" ‖ 0x00 ‖ header_i ‖ ct_i)`.

## 5. Ephemeral key: the exact property and standard mechanism

Property wanted: **confidentiality of the Base-mode transfer survives a weak or repeating system random number generator on the sender**, which RFC 9180 §9.7.5 says is otherwise lost completely, and which that section says can be mitigated "as described in RFC 8937".

Mechanism (RFC 8937 randomness wrapper, applied to the HPKE ephemeral seed):
`ikm = Expand(Extract(salt = SHA-256(Ed25519_Sign(skS, tag1)), IKM = G(32)), tag2, 32)` using HKDF-SHA256 as Extract/Expand, where `G(32)` is 32 bytes from the operating-system CSPRNG; the ephemeral pair is `DeriveKeyPair(ikm)` per RFC 9180 §7.1.3.
- `tag1 = "OCR1v2-EPH" ‖ 0x00 ‖ sender_id ‖ environment identity digest` (a constant per sender instance; must differ from every message the key signs; the signature is cached and **never exposed**, per RFC 8937 §3).
- `tag2 = grant_id ‖ sequence ‖ 64-bit counter` persisted in the sender's journal, unique per use (RFC 8937 §4 requires tags that never collide).
- Ed25519 is deterministic (RFC 8032), satisfying the wrapper's requirement that Sig be deterministic.

What it does **not** give: protection if the sender's long-term key and the CSPRNG are both compromised; protection of the plaintext from Forge itself (Forge holds the plaintext).

Library constraint: the library must let the caller supply `ikm` to `DeriveKeyPair` (or supply the ephemeral private key) through a **non-test** interface. If a candidate library exposes this only as a test-vector hook, that is recorded as a library-selection risk; the approved fallback is plain OS CSPRNG plus the controls in §7, with the residual R-RNG1 stated. Which path was used must be recorded in the sender's evidence record.

## 6. Receiver procedure and enrolment

### Role enrolment (binds the 32-byte IDs to keys)

`sender_id`/`recipient_id` is the **SHA-256 of the canonical enrolment entry** (a registry entry of type ENROLMENT, `RSE12_01` §2), so the identifier commits to every field below; it is meaningless without that owner-signed entry:

| Field | Meaning |
|---|---|
| ROLE_ID | the hash itself (derived) |
| ROLE_TYPE | Crown / Forge / Witness / Monitor |
| ROLE_KEY (signature) | Ed25519 public key |
| ROLE_KEY (KEM) | X25519 public key (recipients) |
| ENVIRONMENT_IDENTITY | digest of the enrolled environment (Witness: attestation key and expected PCR set; Mac roles: enrolled-ID record, labelled SELF_ATTESTED) |
| OWNER APPROVAL | the registry update carrying it is dual-token signed |
| KEY VERSION | monotonic per role |
| REVOCATION STATE | the entry's approval state (REVOKED kills the ID) |
| LEDGER CHECKPOINT | a witnessed checkpoint **strictly earlier** than the entry, covering the enrolment-ceremony evidence (the entry cannot contain a checkpoint that includes itself); inclusion of the entry is proven by an inclusion proof |

Key rotation creates a **new entry and a new ROLE_ID**; the old entry is marked REVOKED. A frame naming a REVOKED or unknown ID is rejected.

### Phase 1 — key absent (the Witness secret volume is locked)

For each frame: (a) length and field checks as §3, with the derived length; (b) `enc` canonical check: 32 bytes, not all zero, top bit clear, value < 2²⁵⁵−19 (stricter than RFC 7748, which would reduce non-canonical values; canonical form is required so decode/re-encode is exact); (c) `recipient_id` equals this Witness; `sender_id` resolves to an APPROVED enrolment entry of type Forge at the registry version the active V grant references; (d) the V grant (state CONSUMER_CONFIRMED) names this `sender_id` and `artifact_id` and a sequence range containing `sequence`, and epoch equals current; the V grant does **not** carry the bundle digest (it does not exist when Crown signs, since G and V are signed in one session): instead `bundle_digest` must equal the digest in the sender's `RESULT` leaf for this sequence, proven by an inclusion proof against a sender checkpoint carrying the required cosignatures (`RSE12_02` §4); (e) **verify σ_i with the sender's enrolled Ed25519 key** (public data only — no secret is needed, so doing it here keeps unauthenticated input away from the key); (f) frame-set rules (§7). Then copy to quarantine, hash, detach the medium (reboot if the threat model of the day requires). Only frames that pass all of (a)–(f) proceed.

### Phase 2 — key present (after TPM release under an ACTIVE grant)

`SetupBaseR(enc, skR, info)` with the same `info` recomputed **from the received header**, then `Open(aad = header_i, ct_i)` for frames in order; reassemble; check `SHA-256(plaintext) == bundle_digest` and length `== total_len`; stream plaintext through a bounded pipe to the keyless sandboxed checker. Check on decapsulation: abort if the X25519 shared secret is all zero (RFC 9180 §7.1.4; RFC 7748 §6.1).

Parsers executing with the key present: HPKE decapsulation and AEAD open on **fixed-size inputs from an enrolled, signature-verified sender**, and the digest comparison. No structured-data parser touches ciphertext-derived content with the key present; structured content is parsed only in the keyless sandbox.

## 7. Frame-set, nonce and replay rules

- Frames are processed strictly in order; HPKE requires in-order `Open` (RFC 9180 §9.7.1), and the sequence-derived nonce is `base_nonce XOR I2OSP(frame_index, 12)`, so `frame_index` **is** the HPKE sequence number.
- Reject: missing frame (count mismatch), duplicate or reordered frame (index ≠ expected), extra frame (index ≥ count or more frames than count), truncated final frame (derived length mismatch), cross-bundle frame (any fixed-field or `enc` inequality; also AEAD failure because `info` differs), a bundle whose digest/length does not match after reassembly.
- Nonce reuse analysis. A (key, nonce) pair repeats only if two different plaintexts are sealed under the same key and the same frame index. The HPKE key depends on the shared secret **and** on `info`, which contains `bundle_digest`, `grant_id`, `sequence`, `epoch`, `sender_id` and `recipient_id`. A repeated `enc` with different `info` therefore yields different keys. Identical `info` implies an identical `bundle_digest`, hence identical plaintext, hence identical ciphertext (no leak). So nonce reuse is structurally excluded unless the sender lies about `bundle_digest` — and a sender able to do that already holds the plaintext. The recipient additionally keeps a set of every `enc` ever accepted and rejects a repeated `enc` under a different `bundle_digest` as a sender-RNG fault (detective; quarantines the sender).
- Replay: HPKE provides none beyond in-order delivery within a context (RFC 9180 §9.7.3). Replay is controlled by (i) the per-stream strictly increasing `sequence` with the recipient's last-accepted value in its journal, (ii) the V grant's consumer-issued challenge and single consumption, (iii) epoch. A rolled-back recipient can re-accept an already-accepted bundle once; for corpus bundles that is idempotent (same digest) and is detected at the next witnessed checkpoint.

## 8. Grants (separate canonical layout per class; no universal union)

Common prefix, **278 bytes**, identical order in every class (a tiny shared prefix, not a union; each class parser is a separate function that knows its exact total length):

| Field | Size |
|---|---|
| magic `OCG1` | 4 |
| version (=1) | 1 |
| class (ASCII `G` `V` `K` `Q` `T` `W` `D` `R`) | 1 |
| grant_id | 16 |
| owner_authority_version | 4 |
| incident_epoch | 4 |
| registry_version | 4 |
| registry_root | 32 |
| policy_entry_id | 32 |
| target_role_id | 32 |
| env_measurement_digest | 32 |
| code_entry_id (registry entry of the code to run) | 32 |
| challenge (consumer-issued, `RSE12_02` §5) | 32 |
| prev_role_checkpoint | 32 |
| created_at (advisory) | 8 |
| not_after (advisory) | 8 |
| max_runtime_s (monotonic runtime ceiling after activation) | 4 |

Class tails (fixed width), then `sig_count × 65` bytes (1-byte signer slot + 64-byte Ed25519). Signed bytes = everything before the signatures, under domain `"OCG1-SIG" ‖ 0x00 ‖ class`:

| Class | Tail fields (bytes) | Tail | Total | Signatures |
|---|---|---|---|---|
| G corpus generation | corpus_entry_id 32, batch_count 4, batch_ceiling_bytes 8, recipient_role_id 32, destination_entry_id 32, source_provenance_digest 32 | 140 | 418 + 130 | 2 |
| V Witness verification | sender_role_id 32, artifact_entry_id 32, seq_first 8, seq_last 8 | 80 | 358 + 65 | 1 |
| K recovery / re-root | scenario 1, new_authority_version 4, new_epoch 4, checkpoint_root 32, revoked_count 1, revoked_ids 8×32 (unused slots all-zero) | 298 | 576 + 130 | 2 |
| Q Qualification (future) | candidate_model_entry_id 32, chamber_env_digest 32, holdout_set_entry_id 32, run_budget 4, query_budget 4, bit_budget 4 | 108 | 386 + 130 | 2 |
| T training (future) | corpus_entry_id 32, foundation_entry_id 32, family_id 32, spend_ceiling 8, run_ceiling 4, provider_env_digest 32 | 140 | 418 + 130 | 2 |
| W weights export (future) | model_entry_id 32, qualification_record_digest 32, source_entry_id 32, destination_entry_id 32, format 1, size_ceiling 8, recipient_role_id 32 | 169 | 447 + 130 | 2 |
| D deployment (future) | model_entry_id 32, serving_env_digest 32, policy_digest 32, tool_permission_digest 32, data_scope_digest 32, revocation_endpoint_entry_id 32, spend_ceiling 8, run_ceiling 4, release_version 4 | 208 | 486 + 130 | 2 |
| R retirement | object_entry_id 32, reason 1 | 33 | 311 + 130 | 2 |

Rules: a grant is rejected unless its length equals the class total exactly; unknown class or version is rejected; every ID field must resolve in the registry (`RSE12_01`); the two signatures must come from two distinct approved owner-token keys; training completion never implies W and W never implies D (separate classes, separate confirmations, different `model_entry_id` states required).

## 9. Remaining open implementation points (stated, not hidden)

HPKE library selection and its test-vector conformance; whether the chosen library supports caller-supplied `ikm`; Ed25519 verification strictness profile (reject non-canonical S; enrolled keys only); constant-time review. All are acceptance items (`RSE12_06` C16–C22).
