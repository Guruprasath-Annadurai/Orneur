# Data integrity

Code: `orca/foundation_x/data.py`. Fixtures only. No corpus was downloaded.

`admit_text` rejects invalid UTF-8 and normalizes accepted text to NFC. A rights record needs an instrument and a URI. The instrument `approved` is rejected. The test uses `CC0-1.0` with `fixture://rights` and `synthetic_fixture=True`.

Exact duplicates compare SHA-256 of the normalized text. Near duplicates call the existing `jaccard` and `word_ngrams` helpers in `orca/eval/genesis_contamination.py`. Train/eval contamination is exact digest overlap.

Revocation of a retrieval document is `Corpus.revoke`, which drops it from later `visible` results. That is a retrieval fixture, not a training-corpus deletion pipeline.
