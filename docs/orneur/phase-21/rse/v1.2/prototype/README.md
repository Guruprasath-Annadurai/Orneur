# OCR1 v2 framing prototype — `PROTOTYPE_ONLY`

Reference prototype for the RSE-ARCH-1.2 envelope *framing and field-validation* rules (`../RSE12_04_OCR1_GRANTS_ENROLMENT.md`). It is **not production code, must never be imported by production code, contains no cryptography and no keys**. Cryptographic fields (`enc`, signature, AEAD tag) are checked only for length and canonical form.

Evidence class: `STRUCTURAL_CODEC_EVIDENCE` only. There is **no** `CRYPTOGRAPHIC_IMPLEMENTATION_EVIDENCE`.

Not covered (by design): signature verification, KEM decapsulation, AEAD, recipient binding, replay state, key release, TOCTOU, the repository parsers. Agreement between the two decoders shows the *grammar* is deterministic; it is not proof of a secure implementation.

Files: `ocr1_ref.py` (decoder A + deterministic mutation generator), `ocr1_ref.js` (independently written decoder B), `json_contrast.py` / `json_contrast.js` (lenient-JSON contrast), `run.sh` (test command).

Test command (needs `python3` and `node`):

    bash docs/orneur/phase-21/rse/v1.2/prototype/run.sh

Expected: `py cases 20000`, `js cases 20000`, `disagreements 0`, and identical `verdict_digest` lines from both implementations (value recorded in `EXPECTED.txt`). `FRAME_PT` is 64 here for test economy; the production value is 1 MiB.
