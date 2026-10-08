# Block-1 audit package — Part 3: cryptographic conformance findings (F)

`NON_NORMATIVE_AUDIT_EVIDENCE`. Scope: independent assessment of the *intended* OCR1 v2 construction (RSE12_04) before IMP-4 code exists. No protocol was created; no real key was generated (all keys below are public deterministic test seeds). Evidence is reproducible with `vectors/run_checks.sh`.

## F1. What was independently established

| Claim | Evidence |
|---|---|
| An independent RFC 9180 base-mode implementation (DHKEM(X25519, HKDF-SHA256) / HKDF-SHA256 / ChaCha20Poly1305), written from the RFC text, reproduces **every** value of RFC 9180 Appendix A.2.1: `DeriveKeyPair` for both ikm values, `enc`, `shared_secret`, `key_schedule_context`, `secret`, `key`, `base_nonce`, and sealed ciphertexts and nonces for sequence 0, 1, 2, 255 | `vectors/check_rfc9180_a2.py` → `RFC9180_A2_REFERENCE_PASS` (22 checks) |
| That reference plus the frozen OCR1 v2 text yields deterministic known-answer frames (single frame P1; two production frames P2; three-frame set P3 with a test-only frame size) | `vectors/ocr1_v2_independent_vectors.json`; regenerated twice with identical SHA-256 |
| 31 negative cases (header/ciphertext/signature tamper, re-signed tamper, wrong recipient id and key, sender substitution, unknown sender, non-canonical/zero/low-order `enc`, truncation, trailing bytes, unknown version/magic, stale epoch, sequence/artifact/sender grant mismatch, lying bundle digest, Ed25519 `S+L` malleation, and seven frame-set attacks) are rejected at the phase the frozen text implies | each case's expectation was written from the spec text first, then cross-checked against the reference (`reference_agrees: true` for all) |
| Key uniqueness argument of RSE12_04 §7 holds: with the same shared secret, changing only `bundle_digest` changes both the HPKE key and base nonce | computed; both differ |
| X25519 low-order `enc` (u = 1) yields an all-zero DH output that an implementation must abort on (RFC 9180 §7.1.4, RFC 7748 §6.1) | N12: aborts in the reference (OpenSSL via `cryptography`) |
| Strict Ed25519: a signature with non-canonical `S+L` is rejected by OpenSSL-backed verification | N22 |

Limits of this evidence: it is a **reference derived from the spec**, not proof that any implementation is secure; it does not cover side channels or the sandbox; the multi-frame production-size case (P2) is carried as digests only.

## F2. Conformance matrix against the frozen profile

| Element | Frozen value (source) | Independent check | Residual / note |
|---|---|---|---|
| Mode, KEM, KDF, AEAD | base; 0x0020; 0x0001; 0x0003 (RSE12_04 §2) | A.2.1 reproduction | none |
| One context per bundle; nonce = `base_nonce XOR I2OSP(frame_index, 12)`; frames opened in order | §4, §7; RFC 9180 §9.7.1 | P3/P2 and N30–N36 | requires a library with a context API (F3) |
| `info` = `"OCR1v2-info"‖0x00‖hdr[0:162]‖hdr[166:178]` | §4 | P1 `info_hex` | excludes `frame_index` and `enc` by design |
| AAD = the 210-byte header of that frame | §4 | N04/N05 (re-signed tamper fails AEAD) | **needs AEAD associated data** (F3) |
| Signature message `"OCR1v2-SIG"‖0x00‖header‖ciphertext`; Ed25519 pure | §4 | N01–N03, N08 | strict-S (N22) must be asserted |
| Ephemeral key via RFC 8937 wrapper | §5 | `ephemeral_wrapper` KAT | needs caller-supplied IKM (F3); fallback must be recorded |
| `enc` canonical (non-zero, top bit clear, < 2²⁵⁵−19) | §3, §6(b) | N10, N11 | stricter than RFC 7748 by design |
| Zero shared secret aborts | §6 Phase 2 | N12 | each library must be checked |
| Phase 1 verifies the sender signature before any private key use | §6 | N01–N03 | structural property; requires a recording fake |

## F3. Library / API limitations (potential blockers for IMP-4)

Checked against the repository's own environment (`cryptography` 49.0.0 in `.venv`, Python 3.11.15) and public documentation.

| Library | Finding | Consequence for the frozen design |
|---|---|---|
| **pyca/cryptography 49.0.0** — module `cryptography.hazmat.primitives.hpke` (documented "added in 47.0.0") | **Single-shot API only**: `Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.CHACHA20_POLY1305).encrypt(plaintext, public_key, info=None)` returns `enc‖ct`; `decrypt(ciphertext, private_key, info=None)`. Verified by inspection and by experiment: **no AAD parameter, no reusable sender/recipient context, a fresh ephemeral key on every call, no caller-supplied IKM.** Experiment: it cannot decrypt the RFC 9180 A.2.1 ciphertext (whose AAD is `Count-0`) — `InvalidTag`; it does interoperate with the reference for an empty-AAD, sequence-0 message | **It cannot implement OCR1 v2 as frozen**: (1) the frozen layout puts one `enc` in every frame of a bundle and derives frame nonces from one context — impossible with per-call encapsulation; (2) AAD = header cannot be expressed; (3) RFC 8937 hedging cannot be applied; (4) it **cannot be admitted under RSE12_04 §2** ("must reproduce RFC 9180 Appendix A vectors"), because every Appendix A vector uses non-empty AAD |
| **pyhpke 0.6.5** (PyPI; last release 2026-07-16; requires `cryptography<52,>=42.0.1`) | README: supports Base/PSK/Auth/AuthPSK, DHKEM(X25519), HKDF-SHA256, ChaCha20-Poly1305; "passed all official test vectors" but "**has not been formally audited**". Exposes `kem.derive_key_pair(ikm)`. Context objects with `seal`/`open` are shown in the README. **Not verified** (source not retrievable this session): AAD parameter on `seal`/`open`, and whether the *sender's ephemeral key* can be injected | The only candidate found that plausibly offers contexts + AAD. New third-party dependency: needs registry entry, pinned hash, source review, and recorded residual if no IKM injection (R-RNG1) |
| **OpenSSL ≥ 3.2** | Documents an HPKE API including `OSSL_HPKE_CTX_set1_ikme` ("deterministic key generation for senders") and `OSSL_HPKE_CTX_set_seq`; supports contexts and AAD. The macOS system `openssl` is LibreSSL 3.3.6 (no HPKE); the venv Python is linked against OpenSSL 3.5.7 but exposes no HPKE binding | Would need FFI (ctypes/cffi) → new hand-written glue; acceptable only if reviewed as security-critical |
| **Go `crypto/hpke`** (standard library, recent versions) | KEM interface exposes `DeriveKeyPair(ikm)` and `NewPrivateKey`; sender-side AAD and ephemeral-key injection **not confirmed**. No Go toolchain is installed on this host | Possible Linux-Witness option; unverified |
| Hand-written HPKE from primitives | Forbidden: "No implementer may hand-roll HPKE, X25519 KEM internals, HKDF, ChaCha20-Poly1305, Ed25519 or randomness-hedging modifications" (`FRZ` §5) | Not an option |

**Assessment.** As the repository stands, IMP-4 has no vetted in-tree library that satisfies the frozen OCR1 v2 construction. This is an architecture-level question (OAQ-5), not an implementation defect to be resolved silently by Cursor. Options for the architect, none decided here: (a) admit a context-capable library (pyhpke or an OpenSSL binding) after dependency review and conformance gating by the RFC vectors **plus** this package's vectors; (b) amend OCR1 (a new clarification) to a per-frame single-shot construction with the header carried in `info` — this changes the frozen layout semantics (each frame would carry its own `enc`) and is at least a Class B, probably Class C, change; (c) split roles (Linux-Witness receiver on OpenSSL/Go; Forge sender elsewhere) — interoperability is then proven only by the vectors.

## F4. Domain separation and cross-protocol use

| Domain / label | Use | Observation |
|---|---|---|
| `"OREG-SIG"‖0x00‖ver` | registry body signature | frozen (CL1 §3) |
| `"OREG-TOKEN"‖0x00` | key id hash | frozen |
| `"OCG1-SIG"‖0x00‖class` | grant signatures | frozen |
| `"OCR-SAS-v1"‖0x00‖class` | SAS | frozen |
| `"OCR1v2-SIG"‖0x00` | frame signatures | frozen (RSE12_04 §4) |
| `"OCR1v2-info"‖0x00` | HPKE `info` | frozen |
| `"OCR1v2-EPH"‖0x00` | RFC 8937 `tag1` | frozen |
| `"OCA1-SIG"‖0x00` | witness acknowledgement | frozen (RSE12_02 §3) |
| **`OCK1`, `OCH1` role signatures** | checkpoint and challenge signatures | **no domain string is frozen** — "role signature" only. The same Ed25519 role key also signs OCR1 frames and `tag1` (EPH). The leading bytes differ in practice (`OCK1`/`OCH1` magic vs `OCR1v2-…`), but cross-protocol safety rests on that coincidence, not on a rule → **OAQ-3** (Class B clarification expected) |

No string is a prefix of another when followed by its NUL, so the frozen domains are mutually safe.

## F5. Nonce, replay and state

Nonce reuse is structurally excluded as RSE12_04 §7 argues (verified). Two stateful requirements are not expressible as vectors and must be tested against the persistent state of IMP-3: recipient `sequence` monotonicity (S01) and the seen-`enc` set (S02). The RFC 8937 `tag2` includes `grant_id‖sequence`, which are never reused (forfeited on interruption), so the persisted `counter` is a secondary uniqueness input; its durability is an IMP-2/IMP-3 journal concern.

## F6. Items that must be demonstrated by the delivered code

1. Reproduction of RFC 9180 Appendix A vectors **by the chosen library through the same API the OCR1 code uses**.
2. Byte-identical output for P1 (and P2 digests) when the code is given the same fixed inputs, through a documented test hook that is **not reachable from production paths**.
3. All negatives rejected at the stated phase.
4. A written record, in the sender's evidence, of whether the RFC 8937 wrapper or the declared fallback was used.
5. Dependency record (name, version, hash, audit status) in the artifact registry before use (`RSE12_05` §6).
