from __future__ import annotations

import pytest

from orca.rse.imp1.locks import training_authorized
from orca.train.dryrun.tokenizer import SyntheticByteTokenizer, TokenizerError, family_foundation_status


def test_synthetic_tokenizer_roundtrip_and_rejects_bad_ids():
    tok = SyntheticByteTokenizer()
    text = "ORNEUR-संश्लेषण-Ω"
    assert tok.decode(tok.encode(text)) == text
    with pytest.raises(TokenizerError) as exc:
        tok.decode([256])
    assert exc.value.code == "id_refused"
    with pytest.raises(TokenizerError):
        tok.encode(None)  # type: ignore[arg-type]


def test_family_foundation_has_no_official_scores_or_training():
    body = family_foundation_status()
    assert body["genesis"] == "INTERFACE_ONLY"
    assert body["novus"] == "NOT_AVAILABLE"
    assert body["aeternum"] == "NOT_AVAILABLE"
    assert body["official_scores"] is None
    assert body["trained_checkpoint"] is False
    assert training_authorized() is False
