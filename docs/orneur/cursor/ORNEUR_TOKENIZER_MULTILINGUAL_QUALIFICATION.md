# Tokenizer and multilingual qualification

No tokenizer was trained on an external or private corpus. SentencePiece, where used, sees only the short original sentences in the test file.

## Dependency-free checks

`orca/genesis/tokenizer/specials.py` holds pad/bos/eos/unk ids so other modules need not import SentencePiece.

`orca/genesis/tokenizer/robustness.py`

- NFC normalization.
- Strict UTF-8 decode.
- Literal `<pad>`, `<bos>`, `<eos>`, `<unk>` surfaces in raw text.
- Code-point chunks that concatenate back to NFC text.
- SHA-256 of the NFC bytes.

`framework.py` imports the special-token constants from that module and still re-exports them.

Tests: `tests/test_cursor_tokenizer_robustness.py`. Sample strings are English, Tamil, Hindi, Telugu, Kannada, Arabic, and Chinese. The tests check normalization and round-trip of the bytes. They do not report fertility as a quality score.

## SentencePiece round-trip

`tests/test_cursor_tokenizer_multilingual.py` trains a vocab of 800 on those sentences plus one mixed-script sentence and checks encode/decode against NFC. Determinism is the same call twice in one process.

This does not measure language proficiency.
