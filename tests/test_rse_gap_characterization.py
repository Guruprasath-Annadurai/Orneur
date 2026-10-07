"""Characterization of known gaps. These tests lock current behavior.

They do not prove a fix, do not change production semantics, and do not
complete acceptance. A future change that closes one of these gaps should
make the corresponding test fail.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import shutil
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import authority_registry as AR
from orca.eval.genesis_v2 import authorization as A
from orca.eval.genesis_v2 import ledger as L
from orca.eval.genesis_v2 import spec
from orca.eval.genesis_v2 import store as S
from orca.registry.checkpoint import CheckpointRecord
from orca.registry.dataset_manifest import DatasetManifest, sha256_of_file
from orca.registry.evaluation_registry import EvaluationReport, evaluate_promotion
from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import LifecycleState
from orca.registry.provenance import complete_training_run, start_training_run
from orca.train.config import TrainingConfig

ROOT = Path(__file__).resolve().parents[1]
_LEDGER_CODE = hashlib.sha256(b"characterization-registered-process").hexdigest()
_LEDGER_DIGEST = hashlib.sha256(b"characterization-corpus").hexdigest()
_LEDGER_REGISTRY = {
    "stage1": L.RegisteredProcess("stage1", _LEDGER_CODE, (spec.PURPOSE_STAGE1,), ("SCREEN",)),
}
_FROZEN = {"frozen": True}
_AUTH_NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
_SHA = "a" * 40


def _need_crypto():
    pytest.importorskip("cryptography")


def _bundle():
    path = ROOT / "scripts" / "genesis_v2_tier0a_transfer_bundle.py"
    loaded = importlib.util.spec_from_file_location("tier0a_bundle_characterization", path)
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    return module


def _header_json(blob: bytes) -> dict:
    (n,) = struct.unpack(">I", blob[8:12])
    return json.loads(blob[12:12 + n])


def _screen_request(run_id: str) -> L.AccessRequest:
    return L.AccessRequest(
        process_id="stage1", code_sha256=_LEDGER_CODE, purpose=spec.PURPOSE_STAGE1, split="SCREEN",
        eval_version=spec.EVAL_VERSION, corpus_digest=_LEDGER_DIGEST, run_id=run_id,
        candidate_revision="rev-char", candidate_lineage="lin-char", timestamp_utc="2026-09-27T00:00:00Z",
    )


def _raw(directory: Path) -> sqlite3.Connection:
    return sqlite3.connect(directory / "ledger.sqlite3", isolation_level=None)


def _drop_guards(conn: sqlite3.Connection) -> None:
    for name in ("records_no_update", "records_no_delete"):
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")


def _restore_guards(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'x'); END")
    conn.execute("CREATE TRIGGER records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'x'); END")


def test_CHAR_seal_path_does_not_authenticate_a_sender(tmp_path):
    """Characterization, not a fix: EncryptedVaultWriter._seal_blob seals with the vault public key only.

    The header carries no sender identity and no signature. A second writer that also holds only that
    public key produces a corpus the matching private-key reader accepts.
    """
    _need_crypto()
    priv, pub = S.generate_vault_keypair()
    assert "vault_private_key" not in inspect.signature(S.EncryptedVaultWriter.__init__).parameters
    splits = {name: b"synthetic-" + name.encode() for name in spec.PRIVATE_SPLITS}
    first = S.EncryptedVaultWriter(tmp_path / "writer-a", pub, repo_root=ROOT)
    corpus_a = "gce2c-" + "11" * 16
    digest_a = first.write_corpus(corpus_a, splits)
    header = _header_json((tmp_path / "writer-a" / corpus_a / "SCREEN.enc").read_bytes())
    assert set(header) == {"eval_version", "corpus_id", "split", "split_sha256", "ephemeral_public_key"}
    reader_a = S.EncryptedVaultReader(tmp_path / "writer-a", priv, repo_root=ROOT)
    assert reader_a.read_split(corpus_a, "SCREEN", expected_corpus_digest=digest_a) == splits["SCREEN"]

    second = S.EncryptedVaultWriter(tmp_path / "writer-b", pub, repo_root=ROOT)
    corpus_b = "gce2c-" + "22" * 16
    digest_b = second.write_corpus(corpus_b, splits)
    reader_b = S.EncryptedVaultReader(tmp_path / "writer-b", priv, repo_root=ROOT)
    assert reader_b.read_split(corpus_b, "SCREEN", expected_corpus_digest=digest_b) == splits["SCREEN"]


def test_CHAR_keyed_open_blob_parses_header_json_before_aead_and_has_no_header_length_cap(tmp_path, monkeypatch):
    """Characterization, not a fix: EncryptedVaultReader._open_blob json.loads the header before AES-GCM.

    A header longer than the keyless 4096-byte cap still decrypts. The keyless _header rejects that same blob.
    A hostile nested header is interpreted, and decrypt is not reached, before the integrity error.
    """
    _need_crypto()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    priv, pub = S.generate_vault_keypair()
    writer = S.EncryptedVaultWriter(tmp_path / "writer", pub, repo_root=ROOT)
    reader = S.EncryptedVaultReader(tmp_path / "writer", priv, repo_root=ROOT)
    payload = b"synthetic-split"
    digest = hashlib.sha256(payload).hexdigest()
    cid = "gce2c-" + "33" * 16
    blob = writer._seal_blob(
        {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": "SCREEN", "split_sha256": digest},
        payload,
    )
    order: list[str] = []
    real_loads = S.json.loads
    real_decrypt = AESGCM.decrypt

    def loads(text, *args, **kwargs):
        order.append("json")
        return real_loads(text, *args, **kwargs)

    def decrypt(self, *args, **kwargs):
        order.append("aead")
        return real_decrypt(self, *args, **kwargs)

    monkeypatch.setattr(S.json, "loads", loads)
    monkeypatch.setattr(AESGCM, "decrypt", decrypt)
    header, plain = reader._open_blob(blob)
    assert plain == payload and header["split"] == "SCREEN"
    assert order == ["json", "aead"]

    order.clear()
    hostile = b'{"a":' * 3000 + b"1" + b"}" * 3000
    hostile_blob = S.MAGIC_ASYM + struct.pack(">I", len(hostile)) + hostile + b"\x00" * 12 + b"\x00" * 16
    with pytest.raises(S.PrivateStorageIntegrityError):
        reader._open_blob(hostile_blob)
    assert order == ["json"]

    padded = writer._seal_blob(
        {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": "SCREEN", "split_sha256": digest, "pad": "p" * 5000},
        payload,
    )
    (n,) = struct.unpack(">I", padded[8:12])
    assert n > 4096
    opened, opened_plain = reader._open_blob(padded)
    assert opened_plain == payload and opened["pad"] == "p" * 5000
    with pytest.raises(ValueError, match="implausible header length"):
        _bundle()._header(padded)


def test_CHAR_symmetric_open_blob_parses_header_json_before_aead_and_has_no_header_length_cap(tmp_path, monkeypatch):
    """Characterization, not a fix: EncryptedFileStore._open_blob also parses header JSON before AEAD and has no length cap."""
    _need_crypto()
    store = S.EncryptedFileStore(tmp_path / "symmetric", bytes(range(1, 33)), repo_root=ROOT)
    payload = b"synthetic-symmetric"
    digest = hashlib.sha256(payload).hexdigest()
    cid = "gce2c-" + "44" * 16
    blob = store._seal_blob(
        {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": "SCREEN", "split_sha256": digest},
        payload,
    )
    order: list[str] = []
    real_loads = S.json.loads
    real_decrypt = store._aead.decrypt

    def loads(text, *args, **kwargs):
        order.append("json")
        return real_loads(text, *args, **kwargs)

    def decrypt(*args, **kwargs):
        order.append("aead")
        return real_decrypt(*args, **kwargs)

    monkeypatch.setattr(S.json, "loads", loads)
    store._aead.decrypt = decrypt
    header, plain = store._open_blob(blob)
    assert plain == payload and header["corpus_id"] == cid
    assert order == ["json", "aead"]

    padded = store._seal_blob(
        {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": "SCREEN", "split_sha256": digest, "pad": "p" * 5000},
        payload,
    )
    (n,) = struct.unpack(">I", padded[8:12])
    assert n > 4096
    order.clear()
    opened, opened_plain = store._open_blob(padded)
    assert opened_plain == payload and opened["pad"] == "p" * 5000 and order[-2:] == ["json", "aead"]


def test_CHAR_duplicate_key_seal_plaintext_last_wins(tmp_path):
    """Characterization, not a fix: duplicate keys in authenticated SEAL plaintext are not rejected.

    json.loads keeps the last value. When those last values are the real split digests, read_split
    returns the plaintext.
    """
    _need_crypto()
    priv, pub = S.generate_vault_keypair()
    splits = {name: b"synthetic-seal-" + name.encode() for name in spec.PRIVATE_SPLITS}
    digests = {name: hashlib.sha256(body).hexdigest() for name, body in splits.items()}
    earlier = "ab" * 32
    assert earlier != digests["SCREEN"] and earlier != digests["QUALIFICATION_HOLDOUT"]
    payload = (
        '{"SCREEN":"' + earlier + '","QUALIFICATION_HOLDOUT":"' + earlier
        + '","SCREEN":"' + digests["SCREEN"] + '","QUALIFICATION_HOLDOUT":"'
        + digests["QUALIFICATION_HOLDOUT"] + '"}'
    ).encode()
    assert json.loads(payload) == digests
    assert S._seal_digests(payload) == digests

    writer = S.EncryptedVaultWriter(tmp_path / "vault", pub, repo_root=ROOT)
    cid = "gce2c-" + "55" * 16
    cdir = writer._cdir(cid)
    cdir.mkdir(mode=0o700)
    for name in spec.PRIVATE_SPLITS:
        header = {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": name, "split_sha256": digests[name]}
        (cdir / f"{name}.enc").write_bytes(writer._seal_blob(header, splits[name]))
    corpus_digest = S.corpus_digest_of(digests)
    seal_header = {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": "SEAL", "corpus_digest": corpus_digest}
    (cdir / "SEAL.enc").write_bytes(writer._seal_blob(seal_header, payload))
    reader = S.EncryptedVaultReader(tmp_path / "vault", priv, repo_root=ROOT)
    assert reader.read_split(cid, "SCREEN", expected_corpus_digest=corpus_digest) == splits["SCREEN"]
    assert reader.read_split(cid, "QUALIFICATION_HOLDOUT", expected_corpus_digest=corpus_digest) == splits["QUALIFICATION_HOLDOUT"]


def test_CHAR_verify_chain_misses_tail_deletion_without_external_head(tmp_path):
    """Characterization, not a fix: deleting the tail leaves a shorter chain that verify_chain accepts.

    The same call rejects the shortened chain only when the caller still holds the previous head_anchor.
    """
    led = L.AccessLedger(tmp_path, _LEDGER_REGISTRY, freeze=_FROZEN)
    led.request_access(_screen_request("run-1"))
    led.request_access(_screen_request("run-2"))
    anchor = led.head_anchor()
    assert led.verify_chain() == 2
    conn = _raw(tmp_path)
    _drop_guards(conn)
    conn.execute("DELETE FROM records WHERE seq=1")
    _restore_guards(conn)
    conn.close()
    assert led.verify_chain() == 1
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain(expected_head=anchor)


def test_CHAR_verify_chain_misses_rollback_without_external_head(tmp_path):
    """Characterization, not a fix: replacing the database with an older consistent file still verifies.

    verify_chain without a saved head accepts the rolled-back file. The saved longer head does not.
    """
    led = L.AccessLedger(tmp_path, _LEDGER_REGISTRY, freeze=_FROZEN)
    led.request_access(_screen_request("run-1"))
    older = tmp_path / "older.sqlite3"
    shutil.copy(led._db, older)
    led.request_access(_screen_request("run-2"))
    led.request_access(_screen_request("run-3"))
    long_head = led.head_anchor()
    assert led.verify_chain() == 3
    led._db.unlink()
    shutil.copy(older, led._db)
    assert led.verify_chain() == 1
    assert led.head_anchor() != long_head
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain(expected_head=long_head)


def test_CHAR_verify_chain_misses_fork_without_external_head(tmp_path):
    """Characterization, not a fix: two extensions of the same prefix each verify_chain alone.

    Their head anchors differ. verify_chain stores neither head and does not compare them.
    """
    original_dir = tmp_path / "original"
    forked_dir = tmp_path / "fork"
    original = L.AccessLedger(original_dir, _LEDGER_REGISTRY, freeze=_FROZEN)
    original.request_access(_screen_request("run-shared"))
    forked_dir.mkdir()
    shutil.copy(original._db, forked_dir / "ledger.sqlite3")
    forked = L.AccessLedger(forked_dir, _LEDGER_REGISTRY, freeze=_FROZEN)
    original.request_access(_screen_request("run-original"))
    forked.request_access(_screen_request("run-fork"))
    assert original.verify_chain() == 2
    assert forked.verify_chain() == 2
    assert original.head_anchor() != forked.head_anchor()
    assert "expected_head" in inspect.signature(L.AccessLedger.verify_chain).parameters


def test_CHAR_authorization_verify_does_not_call_authority_for_request(monkeypatch):
    """Characterization, not a fix: authorization.verify never calls authority_for_request.

    A signed record can allow GPU, spend, or provider inference while the registry record's
    matching permission flag is false. authority_for_request would return no authority for
    that request shape; verify still returns authorized.
    """
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    signing_key = Ed25519PrivateKey.generate()
    public = signing_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    record_id = "char-authority"
    doc = {"schema_version": AR.SCHEMA_VERSION, "records": [{
        "id": record_id, "role": "OWNER", "public_key_hex": public,
        "activation_timestamp": "2020-01-01T00:00:00Z", "expiry": None, "revoked": False,
        "permitted_authorization_classes": ["SCREENING"], "permitted_eval_stages": ["STAGE_1"],
        "gpu_permission": False, "spend_permission": False, "provider_inference_permission": False,
    }]}
    assert AR.validate(doc) == []
    keys = AR.active_authority_keys(doc)
    calls: list = []
    real = AR.authority_for_request

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(AR, "authority_for_request", spy)
    assert "authority_for_request" not in A.verify.__code__.co_names

    def signed(**overrides):
        record = A.default_record()
        record.update({
            "authorization_id": "auth-" + "0e" * 8, "status": "AUTHORIZED", "commit_sha": _SHA,
            "eval_version": "genesis-capability-eval/2.0.0", "candidate": {"model_id": "cand-x", "revision": "rev-1"},
            "permitted_stage": "STAGE_1", "permitted_runner_class": "SELF_HOSTED_CPU", "permitted_purpose": "SCREENING",
            "max_runs": 1, "max_spend_usd": 0, "issued_at": "2026-09-27T11:00:00Z", "expires_at": "2026-09-28T12:00:00Z",
            "authorizing_authority": {"identity": record_id, "role": "OWNER", "key_id": record_id},
            "gpu_allowed": False, "network_provider_inference_allowed": False,
        })
        record.update(overrides)
        record["signature"] = signing_key.sign(A.canonical_signing_bytes(record)).hex()
        return record

    def request(**overrides):
        base = dict(
            commit_sha=_SHA, eval_version="genesis-capability-eval/2.0.0", candidate_model_id="cand-x",
            candidate_revision="rev-1", stage="STAGE_1", runner_class="SELF_HOSTED_CPU", purpose="SCREENING",
            requested_runs=1, requested_spend_usd=0.0, gpu=False, provider_inference=False, event_name="workflow_dispatch",
        )
        base.update(overrides)
        return A.Request(**base)

    cases = (
        ("gpu", signed(gpu_allowed=True, permitted_runner_class="SELF_HOSTED_GPU"), request(gpu=True, runner_class="SELF_HOSTED_GPU"),
         dict(authorization_class="SCREENING", stage="STAGE_1", gpu=True, spend=False, provider_inference=False)),
        ("spend", signed(max_spend_usd=5), request(requested_spend_usd=1.0),
         dict(authorization_class="SCREENING", stage="STAGE_1", gpu=False, spend=True, provider_inference=False)),
        ("provider", signed(network_provider_inference_allowed=True), request(provider_inference=True),
         dict(authorization_class="SCREENING", stage="STAGE_1", gpu=False, spend=False, provider_inference=True)),
    )
    for name, record, req, scope in cases:
        verdict = A.verify(record, req, keys, _AUTH_NOW)
        assert verdict.authorized and verdict.reasons == [], name
        assert real(doc, **scope) == [], name
    assert calls == []


def test_CHAR_completed_checkpoint_promotes_to_PRODUCTION_with_no_class_T_W_or_D_grant(tmp_path):
    """Characterization, not a fix: a completed checkpoint can become PRODUCTION with no class T, W, or D grant.

    complete_training_run registers EXPERIMENTAL. ModelRegistry.promote then sets PRODUCTION when the
    evaluation report says PROMOTABLE. promote takes no grant argument and does not consult one.
    """
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    train_path.write_text('{"text": "synthetic train row"}\n')
    eval_path.write_text('{"text": "synthetic eval row"}\n')
    DatasetManifest(
        dataset_id="char-synthetic", version="v1", purpose="characterization fixture", source_paths=["synthetic-fixture"],
        record_count=1, schema='{"text": str}', train_checksum=sha256_of_file(train_path), eval_checksum=sha256_of_file(eval_path),
        creation_code_sha="characterization", filters_applied="none", deduplication_result="none",
    ).save()
    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(train_path)
    cfg.eval_file = str(eval_path)
    manifest = start_training_run(
        cfg, dataset_manifest_ids=["char-synthetic-v1"], hardware_info="characterization-cpu", run_id="run-char-promote",
    )
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "config.json").write_text("{}")
    (artifact / "tokenizer.json").write_text("{}")
    (artifact / "model.safetensors").write_bytes(b"synthetic-weights")
    record = complete_training_run(
        manifest, checkpoint_id="char-checkpoint", artifact_path=str(artifact), step_or_epoch="epoch=1",
        training_config_summary="characterization", tokenizer_identity=cfg.base_model,
    )
    assert isinstance(record, CheckpointRecord)
    registry = ModelRegistry()
    assert registry.lookup("char-checkpoint").lifecycle_state == LifecycleState.EXPERIMENTAL.value
    assert registry.lookup_production("genesis") is None

    report = evaluate_promotion(EvaluationReport(
        evaluation_id="char-eval", checkpoint_id="char-checkpoint", family="genesis",
        evaluator_version="characterization", dataset_version="v1",
        metrics={"eval_accuracy": 90.0, "jailbreak_block_rate": 95.0, "bias_flag_rate": 1.0, "domain_eval": 90.0},
        acceptance_thresholds={},
    ))
    assert report.pass_fail_status == "PROMOTABLE"
    parameters = list(inspect.signature(ModelRegistry.promote).parameters)
    assert parameters == ["self", "checkpoint_id", "evaluation_report", "promoted_by"]
    names = ModelRegistry.promote.__code__.co_names
    assert not any("grant" in name.lower() or name in {"T", "W", "D"} for name in names)
    promoted = registry.promote("char-checkpoint", report, promoted_by="characterization")
    assert promoted.lifecycle_state == LifecycleState.PRODUCTION.value
    assert registry.lookup_production("genesis").checkpoint_id == "char-checkpoint"
