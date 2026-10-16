"""
GENESIS Foundation Sprint 2, Workstream A, Mission A1/A6: dataset
provenance manifest tests.
"""
from __future__ import annotations

import hashlib

import pytest

from orca.genesis.data.manifest import (
    GenesisDatasetManifest,
    ManifestTamperedError,
    ProvenanceRejected,
    SourceOrigin,
    TokenizerBinding,
    TransformationStep,
    normalize_record_text,
)


def _origin(**over) -> SourceOrigin:
    base = dict(source_id="fixture-1", description="synthetic fixture", license_name="CC0-1.0", usage_restrictions="none", retrieved_at="2026-10-16T00:00:00Z")
    base.update(over)
    return SourceOrigin(**base)


def _tb(**over) -> TokenizerBinding:
    base = dict(tokenizer_model_path="/tmp/tok.model", architecture_version="genesis-arch-v1", vocab_digest=hashlib.sha256(b"vocab-v1").hexdigest())
    base.update(over)
    return TokenizerBinding(**base)


def _build(**over):
    base = dict(
        dataset_name="genesis-data-fixture", version="v1", origins=[_origin()],
        normalized_records=["record one", "record two", "record three"],
        transformation_lineage=[TransformationStep(name="normalize", code_reference="normalize_record_text")],
        tokenizer_binding=_tb(),
    )
    base.update(over)
    return GenesisDatasetManifest.build(**base)


def test_build_produces_a_real_content_addressed_manifest_id():
    m = _build()
    assert len(m.manifest_id) == 64
    assert all(c in "0123456789abcdef" for c in m.manifest_id)


def test_manifest_id_is_order_independent_over_records():
    m1 = _build(normalized_records=["a", "b", "c"])
    m2 = _build(normalized_records=["c", "a", "b"])
    assert m1.manifest_id == m2.manifest_id
    assert m1.source_content_digest == m2.source_content_digest


def test_manifest_id_changes_if_content_changes():
    m1 = _build(normalized_records=["a", "b", "c"])
    m2 = _build(normalized_records=["a", "b", "d"])
    assert m1.manifest_id != m2.manifest_id


def test_manifest_id_changes_if_tokenizer_binding_changes():
    m1 = _build()
    m2 = _build(tokenizer_binding=_tb(vocab_digest=hashlib.sha256(b"a-different-vocab").hexdigest()))
    assert m1.manifest_id != m2.manifest_id


# ---------------------------------------------- explicit provenance rejection --

def test_rejects_empty_origins():
    with pytest.raises(ProvenanceRejected):
        _build(origins=[])


def test_rejects_an_origin_with_no_license():
    with pytest.raises(ProvenanceRejected, match="license"):
        _build(origins=[_origin(license_name="")])


def test_rejects_an_origin_with_no_usage_restrictions_stated():
    with pytest.raises(ProvenanceRejected, match="usage_restrictions"):
        _build(origins=[_origin(usage_restrictions="")])


def test_rejects_empty_records():
    with pytest.raises(ProvenanceRejected):
        _build(normalized_records=[])


def test_rejects_a_non_hex_vocab_digest():
    with pytest.raises(ProvenanceRejected, match="vocab_digest"):
        _build(tokenizer_binding=_tb(vocab_digest="not-a-real-digest"))


def test_rejects_an_arbitrary_caller_supplied_string_as_a_digest():
    """Mission A5's explicit requirement: the vocab digest must be a real
    64-char hex SHA-256, not any string a caller supplies."""
    with pytest.raises(ProvenanceRejected):
        _build(tokenizer_binding=_tb(vocab_digest="my-cool-dataset-v1"))


def test_rejects_missing_dataset_name():
    with pytest.raises(ProvenanceRejected):
        _build(dataset_name="")


# ------------------------------------------------------- tampering / forged manifests --

def test_verify_against_records_detects_content_tampering():
    m = _build(normalized_records=["a", "b", "c"])
    ok, msg = m.verify_against_records(["a", "b", "TAMPERED"])
    assert ok is False
    assert "digest mismatch" in msg


def test_verify_against_records_detects_record_count_tampering():
    m = _build(normalized_records=["a", "b", "c"])
    ok, msg = m.verify_against_records(["a", "b"])
    assert ok is False


def test_save_and_load_round_trips(tmp_path):
    m = _build()
    path = m.save()
    assert path.exists()
    loaded = GenesisDatasetManifest.load(path)
    assert loaded.manifest_id == m.manifest_id
    assert loaded.source_content_digest == m.source_content_digest
    assert loaded.origins == m.origins


def test_saved_manifest_file_has_owner_only_permissions():
    import os
    import stat
    m = _build()
    path = m.save()
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_loaded_manifest_detects_forged_file_content(tmp_path):
    """A-09 fix: `load()` itself is now the trusted boundary -- a
    manifest file edited on disk after saving (e.g. an attacker trying
    to forge a different dataset_name under the same path, leaving the
    original manifest_id unchanged) is REJECTED by `load()` directly,
    not merely detectable by a caller doing extra work afterward."""
    import json

    m = _build()
    path = m.save()
    raw = json.loads(path.read_text())
    raw["dataset_name"] = "forged-name"
    path.write_text(json.dumps(raw))
    with pytest.raises(ManifestTamperedError, match="TAMPERED"):
        GenesisDatasetManifest.load(path)


def test_load_rejects_an_arbitrary_substituted_manifest_id(tmp_path):
    """Even if EVERY other field is left genuinely untouched, a
    substituted manifest_id alone must be rejected -- confirms the
    recomputation is the actual trust boundary, not merely one of
    several fields compared loosely."""
    import json

    m = _build()
    path = m.save()
    raw = json.loads(path.read_text())
    raw["manifest_id"] = "f" * 64
    path.write_text(json.dumps(raw))
    with pytest.raises(ManifestTamperedError, match="TAMPERED"):
        GenesisDatasetManifest.load(path)


def test_load_rejects_a_missing_required_field(tmp_path):
    import json

    m = _build()
    path = m.save()
    raw = json.loads(path.read_text())
    del raw["source_content_digest"]
    path.write_text(json.dumps(raw))
    with pytest.raises(ManifestTamperedError, match="missing required field"):
        GenesisDatasetManifest.load(path)


def test_load_rejects_an_unrecognized_schema_version(tmp_path):
    import json

    m = _build()
    path = m.save()
    raw = json.loads(path.read_text())
    raw["schema_version"] = "some-future-schema/99"
    path.write_text(json.dumps(raw))
    with pytest.raises(ManifestTamperedError, match="schema_version"):
        GenesisDatasetManifest.load(path)


def test_load_rejects_malformed_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json at all")
    with pytest.raises(ManifestTamperedError, match="not valid JSON"):
        GenesisDatasetManifest.load(path)


def test_an_untampered_manifest_still_loads_cleanly(tmp_path):
    """Negative control: the trusted-load recomputation must not
    spuriously reject a genuinely unmodified, correctly-saved manifest."""
    m = _build()
    path = m.save()
    loaded = GenesisDatasetManifest.load(path)
    assert loaded.manifest_id == m.manifest_id
    assert loaded.dataset_name == m.dataset_name


def test_normalize_record_text_is_deterministic_and_idempotent():
    text = "  Hello   World  ́ "
    once = normalize_record_text(text)
    twice = normalize_record_text(once)
    assert once == twice
