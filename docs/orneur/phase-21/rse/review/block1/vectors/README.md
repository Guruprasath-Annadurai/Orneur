# Independent OCR1 v2 / HPKE audit references — `REVIEW_REFERENCE_ONLY`

Written by the independent reviewer for the RSE Block-1 audit package. **Not production code; never import from production code.**
Purpose: expected values for IMP-4 that do **not** come from the implementation under audit.

| File | Role |
|---|---|
| `hpke_ref.py` | RFC 9180 base-mode reference (X25519 / HKDF-SHA256 / ChaCha20-Poly1305) |
| `check_rfc9180_a2.py` | proves the reference reproduces RFC 9180 Appendix A.2.1 (public vector) |
| `ocr1v2_ref.py` | OCR1 v2 sender, Phase 1 (key-absent) and Phase 2 (key-present) reference from `RSE12_04` |
| `gen_vectors.py` | builds `ocr1_v2_independent_vectors.json`; spec-derived expected outcomes are cross-checked against the reference |
| `ocr1_v2_independent_vectors.json` | positive vectors P1/P2/P3 and 31 negative cases N01–N36 (incl. N22), plus stateful cases |
| `run_checks.sh` | `PYTHON=/path/to/python bash run_checks.sh` (needs the `cryptography` package; default `python3`) |

Keys are public deterministic **test-only** seeds (`SHA-256("RSE-REVIEW-BLOCK1-TEST-ONLY|"+label)`); nothing is secret.
The P3 set and `N30–N36` use a **non-production `FRAME_PT = 64`** so frame-set rules can be tested without 1 MiB blobs; an
implementation that hard-codes the production 1 MiB frame size can instead reproduce the same rules with larger inputs.
Evidence class: this is a *reference derived from the spec*, not proof that any implementation is secure.
