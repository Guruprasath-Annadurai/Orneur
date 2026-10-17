"""
GENESIS Native Learning Engine, Phase 1, Workstream 2 tests:
`orca.genesis.data.loader`. Bounded, CPU-only, synthetic corpus only.
"""
from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")
spm = pytest.importorskip("sentencepiece")

from orca.genesis.data.loader import (  # noqa: E402
    CrossSplitAccessError,
    GenesisBlockDataset,
    LoaderConfig,
    ReproducibleSampler,
    ShardIntegrityError,
    make_batch,
)
from orca.genesis.data.pipeline import compute_shard_digests, process_corpus  # noqa: E402
from orca.genesis.tokenizer.framework import GenesisTokenizer, TokenizerTrainingConfig, train_tokenizer  # noqa: E402


@pytest.fixture
def corpus_fixture(tmp_path):
    corpus_path = tmp_path / "raw.jsonl"
    texts = [f"the quick brown fox jumps over the lazy dog number {i} today" for i in range(300)]
    corpus_path.write_text("\n".join(json.dumps({"text": t}) for t in texts) + "\n")
    out_dir = tmp_path / "shards"
    _, kept = process_corpus(corpus_path, out_dir, num_shards=2)
    model_prefix = str(tmp_path / "tok")
    train_tokenizer(kept, TokenizerTrainingConfig(vocab_size=320), model_prefix)
    tok = GenesisTokenizer((tmp_path / "tok.model"))
    digests = compute_shard_digests(out_dir)
    return out_dir, tok, digests


def test_loader_produces_valid_blocks_and_reads_every_shard(corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests)
    ds = GenesisBlockDataset(cfg, tok)
    assert len(ds) > 0
    assert ds.report.records_read > 0
    input_ids, labels = ds.block(0)
    assert input_ids.shape == (8,)
    assert labels.shape == (8,)


def test_cross_split_isolation_train_and_validation_never_overlap_files(corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    train_cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests)
    val_cfg = LoaderConfig(shard_dir=out_dir, split="validation", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests)
    train_ds = GenesisBlockDataset(train_cfg, tok)
    val_ds = GenesisBlockDataset(val_cfg, tok)
    train_paths = {p.name for p in train_ds._split_shard_paths()}
    val_paths = {p.name for p in val_ds._split_shard_paths()}
    assert train_paths.isdisjoint(val_paths)
    assert all(name.endswith("-train.jsonl") for name in train_paths)
    assert all(name.endswith("-validation.jsonl") for name in val_paths)


def test_tampered_shard_content_is_rejected_at_construction(corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    shard_file = sorted(out_dir.glob("shard-*-train.jsonl"))[0]
    original = shard_file.read_bytes()
    shard_file.write_bytes(original[:-1] + b"X")
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests)
    with pytest.raises(ShardIntegrityError):
        GenesisBlockDataset(cfg, tok)


def test_unauthorized_extra_shard_file_is_rejected(corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    (out_dir / "shard-9999-train.jsonl").write_text(json.dumps({"text": "an unauthorized extra shard"}) + "\n")
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests)
    with pytest.raises(ShardIntegrityError):
        GenesisBlockDataset(cfg, tok)


def test_malformed_records_are_rejected_and_counted_not_silently_dropped(tmp_path, corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    # Append a malformed line directly to one shard file, then recompute digests
    # (simulating a corpus that genuinely contains malformed records, not tampering).
    shard_file = sorted(out_dir.glob("shard-*-train.jsonl"))[0]
    with open(shard_file, "a") as f:
        f.write("not valid json at all\n")
        f.write(json.dumps({"no_text_field": "x"}) + "\n")
    fresh_digests = compute_shard_digests(out_dir)
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=fresh_digests)
    ds = GenesisBlockDataset(cfg, tok)
    assert ds.report.records_rejected_malformed == 2


def test_empty_authorized_shard_digests_is_rejected():
    with pytest.raises(ValueError):
        LoaderConfig(shard_dir="/tmp", split="train", seq_len=8, batch_size=1, seed=0, authorized_shard_digests={})


def test_invalid_split_name_is_rejected():
    with pytest.raises(ValueError):
        LoaderConfig(shard_dir="/tmp", split="not_a_real_split", seq_len=8, batch_size=1, seed=0, authorized_shard_digests={"x": "y"})


def test_reproducible_sampler_same_seed_same_order():
    s1 = ReproducibleSampler(num_blocks=50, seed=42)
    s2 = ReproducibleSampler(num_blocks=50, seed=42)
    assert s1.next_batch_indices(10) == s2.next_batch_indices(10)


def test_reproducible_sampler_different_seed_different_order():
    s1 = ReproducibleSampler(num_blocks=50, seed=1)
    s2 = ReproducibleSampler(num_blocks=50, seed=2)
    assert s1.next_batch_indices(10) != s2.next_batch_indices(10)


def test_sampler_position_resume_continues_from_the_exact_point():
    s1 = ReproducibleSampler(num_blocks=50, seed=42)
    s1.next_batch_indices(10)
    position_after_10 = s1.position

    s2 = ReproducibleSampler(num_blocks=50, seed=42)
    s2.position = position_after_10
    next_from_fresh = s1.next_batch_indices(5)

    s3 = ReproducibleSampler(num_blocks=50, seed=42)
    s3.position = position_after_10
    next_from_resumed = s3.next_batch_indices(5)
    assert next_from_fresh == next_from_resumed


def test_make_batch_stacks_correct_shapes(corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests)
    ds = GenesisBlockDataset(cfg, tok)
    sampler = ReproducibleSampler(len(ds), seed=0)
    input_ids, labels = make_batch(ds, sampler.next_batch_indices(4))
    assert input_ids.shape == (4, 8)
    assert labels.shape == (4, 8)


def test_non_packing_mode_pads_short_records(tmp_path):
    corpus_path = tmp_path / "raw.jsonl"
    corpus_path.write_text(json.dumps({"text": "short"}) + "\n")
    out_dir = tmp_path / "shards"
    _, kept = process_corpus(corpus_path, out_dir, num_shards=1)
    model_prefix = str(tmp_path / "tok2")
    train_tokenizer(kept + [f"filler sentence number {i} for vocabulary coverage" for i in range(50)], TokenizerTrainingConfig(vocab_size=300), model_prefix)
    tok = GenesisTokenizer(tmp_path / "tok2.model")
    digests = compute_shard_digests(out_dir)
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=16, batch_size=1, seed=0, authorized_shard_digests=digests, packing=False)
    ds = GenesisBlockDataset(cfg, tok)
    assert len(ds) == 1
    input_ids, labels = ds.block(0)
    assert (labels == -100).any(), "padded positions must be masked out of the loss"
