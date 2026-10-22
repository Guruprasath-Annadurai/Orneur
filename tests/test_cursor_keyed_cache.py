"""Keyed derived-cache integrity. Synthetic shards only."""
from __future__ import annotations

import hashlib
import json

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.data.loader import (  # noqa: E402
    BlockStoreTamperedError,
    GenesisBlockDataset,
    LoaderConfig,
    _MIN_CACHE_INTEGRITY_KEY_BYTES,
    compute_block_store_cache_id,
)
from orca.genesis.data.pipeline import _shard_path, compute_shard_digests  # noqa: E402
from orca.genesis.training.resumable_checkpoint import MIN_INTEGRITY_KEY_BYTES  # noqa: E402


class _FakeTokenizer:
    def encode(self, text: str) -> list[int]:
        return [((ord(ch) % 17) + 1) for ch in text] or [1]


def _shard(tmp_path, text: str = "alpha beta gamma delta"):
    path = _shard_path(tmp_path, 0, "train")
    path.write_text(json.dumps({"text": text}) + "\n")
    return compute_shard_digests(tmp_path)


def _cfg(tmp_path, digests, key=None, **overrides):
    values = dict(
        shard_dir=tmp_path,
        split="train",
        seq_len=4,
        batch_size=1,
        seed=0,
        authorized_shard_digests=digests,
        tokenizer_digest="synthetic-tokenizer",
        packing=True,
        cache_integrity_key=key,
    )
    values.update(overrides)
    return LoaderConfig(**values)


def test_cache_key_minimum_matches_checkpoint_key_minimum():
    assert _MIN_CACHE_INTEGRITY_KEY_BYTES == MIN_INTEGRITY_KEY_BYTES == 32


def test_short_cache_key_is_rejected(tmp_path):
    digests = _shard(tmp_path)
    with pytest.raises(ValueError, match="at least"):
        _cfg(tmp_path, digests, key=b"short")


def test_unkeyed_cache_id_ignores_the_key_field(tmp_path):
    digests = _shard(tmp_path)
    left = compute_block_store_cache_id(_cfg(tmp_path, digests, key=None))
    right = compute_block_store_cache_id(_cfg(tmp_path, digests, key=None))
    assert left == right
    keyed = compute_block_store_cache_id(_cfg(tmp_path, digests, key=b"k" * 32))
    assert keyed != left


def test_keyed_cache_round_trip_and_rejects_coordinated_rewrite(tmp_path):
    digests = _shard(tmp_path)
    key = hashlib.sha256(b"caller-supplied-test-key").digest()
    cfg = _cfg(tmp_path, digests, key=key)
    first = GenesisBlockDataset(cfg, _FakeTokenizer())
    block = first.block(0)
    assert block[0].shape[0] == 4
    first.close()

    second = GenesisBlockDataset(cfg, _FakeTokenizer())
    again = second.block(0)
    assert torch.equal(block[0], again[0])
    second.close()

    manifest_path = second._manifest_path
    store_path = second._store_path
    manifest = json.loads(manifest_path.read_text())
    flipped = bytearray(store_path.read_bytes())
    flipped[0] ^= 0xFF
    store_path.write_bytes(bytes(flipped))
    manifest["store_sha256"] = hashlib.sha256(bytes(flipped)).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BlockStoreTamperedError, match="HMAC"):
        GenesisBlockDataset(cfg, _FakeTokenizer())


def test_wrong_key_does_not_accept_another_keys_cache_files(tmp_path):
    digests = _shard(tmp_path)
    key_a = b"a" * 32
    key_b = b"b" * 32
    cfg_a = _cfg(tmp_path, digests, key=key_a)
    built = GenesisBlockDataset(cfg_a, _FakeTokenizer())
    built.close()
    cfg_b = _cfg(tmp_path, digests, key=key_b)
    cache_b = compute_block_store_cache_id(cfg_b)
    base = tmp_path
    for suffix in (".bin", ".digests.bin", ".manifest.json"):
        source = base / f".block_store_{compute_block_store_cache_id(cfg_a)}{suffix}"
        target = base / f".block_store_{cache_b}{suffix}"
        target.write_bytes(source.read_bytes())
    with pytest.raises(BlockStoreTamperedError):
        GenesisBlockDataset(cfg_b, _FakeTokenizer())


def test_cache_integrity_key_is_absent_from_diagnostic_forms(tmp_path):
    import copy
    import dataclasses
    import io
    import logging
    import pickle

    from orca.genesis.data.loader import CacheIntegrityKey

    secret = b"SYNTHETIC-CACHE-SECRET-DO-NOT-LEAK"
    assert len(secret) >= 32
    revealed = secret.decode("ascii")
    mutable = bytearray(secret)
    digests = _shard(tmp_path)
    cfg = _cfg(tmp_path, digests, key=mutable)
    mutable[:9] = b"MUTATED!!"
    assert isinstance(cfg.cache_integrity_key, CacheIntegrityKey)
    assert cfg.cache_integrity_key.material() == secret

    rendered = "\n".join([
        repr(cfg),
        str(cfg),
        format(cfg),
        format(cfg.cache_integrity_key),
        f"{cfg.cache_integrity_key}",
        repr(dataclasses.asdict(cfg)),
        repr(dataclasses.astuple(cfg)),
        json.dumps(dataclasses.asdict(cfg), default=str),
        compute_block_store_cache_id(cfg),
    ])
    buffer = io.StringIO()
    logger = logging.getLogger("cursor-cache-key-redaction")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(buffer)
    logger.addHandler(handler)
    try:
        logger.error("config %s", cfg)
        logger.error("key %s", cfg.cache_integrity_key)
        try:
            raise RuntimeError(repr(cfg))
        except RuntimeError as exc:
            rendered += "\n" + str(exc) + "\n" + repr(exc)
        with pytest.raises(TypeError, match="not available through bytes"):
            bytes(cfg.cache_integrity_key)
        with pytest.raises(TypeError, match="cannot be serialized") as pickled:
            pickle.dumps(cfg)
        rendered += "\n" + str(pickled.value)
        copied = copy.deepcopy(cfg)
        rendered += "\n" + repr(copied)
        assert copied.cache_integrity_key.material() == secret
    finally:
        logger.removeHandler(handler)
    rendered += "\n" + buffer.getvalue()
    built = GenesisBlockDataset(cfg, _FakeTokenizer())
    built.close()
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert secret not in path.read_bytes()
    assert revealed not in rendered

    with pytest.raises(ValueError, match="at least") as short:
        _cfg(tmp_path, digests, key=b"SYNTHETIC-CACHE-SECRET")
    assert "SYNTHETIC-CACHE-SECRET" not in str(short.value)
    assert "SYNTHETIC-CACHE-SECRET" not in repr(short.value)


def test_unkeyed_loader_refuses_a_keyed_manifest(tmp_path):
    digests = _shard(tmp_path)
    key = b"c" * 32
    keyed = _cfg(tmp_path, digests, key=key)
    built = GenesisBlockDataset(keyed, _FakeTokenizer())
    built.close()
    cache_id = compute_block_store_cache_id(keyed)
    unkeyed = _cfg(tmp_path, digests, key=None)
    unkeyed_id = compute_block_store_cache_id(unkeyed)
    base = tmp_path
    for suffix in (".bin", ".digests.bin", ".manifest.json"):
        source = base / f".block_store_{cache_id}{suffix}"
        target = base / f".block_store_{unkeyed_id}{suffix}"
        target.write_bytes(source.read_bytes())
    with pytest.raises(BlockStoreTamperedError, match="without cache_integrity_key"):
        GenesisBlockDataset(unkeyed, _FakeTokenizer())
