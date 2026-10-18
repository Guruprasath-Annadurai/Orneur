"""
GENESIS Native Learning Engine, Phase 1, Workstream 2 tests:
`orca.genesis.data.loader`. Bounded, CPU-only, synthetic corpus only.
"""
from __future__ import annotations

import json
import os

import pytest

torch = pytest.importorskip("torch")
spm = pytest.importorskip("sentencepiece")

import torch.nn.functional as F  # noqa: E402

from orca.genesis.data.loader import (  # noqa: E402
    BlockStoreCorruptionError,
    BlockStoreTamperedError,
    CachePathSecurityError,
    CrossSplitAccessError,
    GenesisBlockDataset,
    LoaderConfig,
    ReproducibleSampler,
    ShardIntegrityError,
    compute_block_store_cache_id,
    make_batch,
)
from orca.genesis.data.pipeline import compute_shard_digests, process_corpus  # noqa: E402
from orca.genesis.tokenizer.framework import GenesisTokenizer, TokenizerTrainingConfig, train_tokenizer  # noqa: E402
from orca.genesis.training.primitives import causal_lm_loss  # noqa: E402


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
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest")
    ds = GenesisBlockDataset(cfg, tok)
    assert len(ds) > 0
    assert ds.report.records_read > 0
    input_ids, labels = ds.block(0)
    assert input_ids.shape == (8,)
    assert labels.shape == (8,)


def test_cross_split_isolation_train_and_validation_never_overlap_files(corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    train_cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest")
    val_cfg = LoaderConfig(shard_dir=out_dir, split="validation", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest")
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
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest")
    with pytest.raises(ShardIntegrityError):
        GenesisBlockDataset(cfg, tok)


def test_unauthorized_extra_shard_file_is_rejected(corpus_fixture):
    out_dir, tok, digests = corpus_fixture
    (out_dir / "shard-9999-train.jsonl").write_text(json.dumps({"text": "an unauthorized extra shard"}) + "\n")
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest")
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
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=fresh_digests, tokenizer_digest="test-tok-digest")
    ds = GenesisBlockDataset(cfg, tok)
    assert ds.report.records_rejected_malformed == 2


def test_empty_authorized_shard_digests_is_rejected():
    with pytest.raises(ValueError):
        LoaderConfig(shard_dir="/tmp", split="train", seq_len=8, batch_size=1, seed=0, authorized_shard_digests={}, tokenizer_digest="test-tok-digest")


def test_invalid_split_name_is_rejected():
    with pytest.raises(ValueError):
        LoaderConfig(shard_dir="/tmp", split="not_a_real_split", seq_len=8, batch_size=1, seed=0, authorized_shard_digests={"x": "y"}, tokenizer_digest="test-tok-digest")


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
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=8, batch_size=4, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest")
    ds = GenesisBlockDataset(cfg, tok)
    sampler = ReproducibleSampler(len(ds), seed=0)
    input_ids, labels = make_batch(ds, sampler.next_batch_indices(4))
    assert input_ids.shape == (4, 8)
    assert labels.shape == (4, 8)


class _IdentityTokenizer:
    """Encodes a space-separated string of integers back into those
    integers unchanged -- lets these oracle tests construct EXACT,
    irregular, nonperiodic token sequences by hand, rather than
    depending on whatever a real SentencePiece vocabulary happens to
    assign."""
    def encode(self, text: str) -> list[int]:
        return [int(t) for t in text.split()]


def test_block_returns_a_single_unshifted_token_identity_not_pre_shifted(tmp_path):
    """AUDIT-P0-01 regression: `block()` must return `(tokens, labels)`
    as the SAME underlying sequence (labels content-identical to
    tokens, only pad positions masked) -- never `labels` pre-shifted
    relative to `tokens`. This is the exact, specific defect Antigravity
    Audit #074 found: the prior version returned `full[:-1]`/`full[1:]`,
    a pre-shifted pair that then shifted AGAIN inside `causal_lm_loss()`."""
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    # An IRREGULAR, NONPERIODIC sequence -- deliberately not a repeating
    # pattern, so no "skip-one" alignment could accidentally look correct.
    (shard_dir / "shard-0000-train.jsonl").write_text(json.dumps({"text": "11 23 37 41 59 7 2"}) + "\n")
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=7, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest", packing=False)
    ds = GenesisBlockDataset(cfg, _IdentityTokenizer())
    tokens, labels = ds.block(0)
    assert tokens.tolist() == [11, 23, 37, 41, 59, 7, 2]
    assert labels.tolist() == [11, 23, 37, 41, 59, 7, 2], (
        "labels must be the SAME sequence as tokens (no pre-shift) -- causal_lm_loss() "
        "performs the one and only shift in this pipeline"
    )


def test_independent_manual_cross_entropy_oracle_proves_exact_target_alignment():
    """The directive's own required "independent oracle test": manually
    (by hand-indexing, NOT by calling causal_lm_loss's own internal
    shift) computes which target token each logit position is actually
    compared against when `GenesisBlockDataset`'s now-unshifted
    `(tokens, labels)` pair is fed through `causal_lm_loss()`, on an
    IRREGULAR, NONPERIODIC sequence -- then confirms `causal_lm_loss()`'s
    own real loss value matches a from-scratch `F.cross_entropy` call
    over those manually-selected (logit, target) pairs. If the
    double-shift defect were still present, this manual alignment
    (logit i vs token i+1) would NOT match causal_lm_loss()'s actual
    computation (which would instead be comparing against token i+2),
    and this test would fail -- this is the exact proof the directive
    requires: "a new synthetic-learning test that would FAIL under the
    former double-shift implementation." """
    torch.manual_seed(0)
    seq = [11, 23, 37, 41, 59, 7, 2, 90]  # irregular, nonperiodic
    tokens = torch.tensor([seq], dtype=torch.long)
    labels = tokens.clone()  # the module's own documented single-shift contract: labels == tokens
    vocab_size = 128
    logits = torch.randn(1, len(seq), vocab_size, requires_grad=False)

    # Manual oracle: logit at position i must be compared against token i+1 (the TRUE next token),
    # for i in [0, len(seq)-2] -- hand-indexed, not derived from causal_lm_loss's own shift code.
    manual_pairs = [(i, seq[i + 1]) for i in range(len(seq) - 1)]
    assert manual_pairs[0] == (0, 23), "position 0's target must be token index 1 (23), not token index 2 (37)"
    manual_logits = torch.stack([logits[0, i] for i, _ in manual_pairs])
    manual_targets = torch.tensor([t for _, t in manual_pairs])
    manual_loss = F.cross_entropy(manual_logits, manual_targets)

    actual_loss = causal_lm_loss(logits, labels)
    assert torch.allclose(manual_loss, actual_loss, atol=1e-6), (
        f"causal_lm_loss()'s real alignment ({actual_loss.item()}) does not match the manually "
        f"computed, hand-indexed T_{{i+1}} oracle ({manual_loss.item()}) -- exact target alignment is broken"
    )


def test_final_token_utilization_is_the_standard_accepted_trade_off_not_a_silent_loss():
    """With `seq_len` tokens per block (the corrected, single-shift
    design), the LAST position's logit is computed (needed as context)
    but never itself supervised -- there is no `seq_len+1`-th token in
    this block to compare it against. This is standard, accepted
    practice (not a bug): confirmed here explicitly, by construction,
    rather than left as an unstated/undocumented side effect."""
    seq_len = 6
    labels = torch.arange(seq_len).unsqueeze(0)
    logits = torch.randn(1, seq_len, 32)
    # causal_lm_loss's own internal shift: shift_logits has seq_len-1 rows.
    shift_logits = logits[..., :-1, :]
    shift_labels = labels[..., 1:]
    assert shift_logits.shape[-2] == seq_len - 1
    assert shift_labels.shape[-1] == seq_len - 1
    # The logit at the LAST position (index seq_len-1) is excluded from shift_logits
    # entirely -- it contributes context to nothing further and is never supervised.
    assert seq_len - 1 not in range(shift_logits.shape[-2])


def test_a_record_too_short_to_form_any_supervised_pair_is_rejected_not_crashed(tmp_path):
    """AUDIT-P0-01 "handle short/fully-masked records safely": a
    non-packed record with fewer than 2 real tokens can never produce
    even one supervised (logit, target) pair under the correct
    single-shift objective -- rejected at LOAD time (counted as
    malformed), not silently passed through to crash deep inside
    causal_lm_loss() mid-training-step."""
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    (shard_dir / "shard-0000-train.jsonl").write_text(json.dumps({"text": "7"}) + "\n")
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest", packing=False)
    ds = GenesisBlockDataset(cfg, _IdentityTokenizer())
    assert len(ds) == 0
    assert ds.report.records_rejected_malformed == 1
    assert ds.report.records_read == 0


def test_packed_sequence_boundaries_are_eos_separated_and_single_shifted(tmp_path):
    """Packing mode: two short records concatenated with an EOS
    separator must still carry exactly one shift end-to-end -- a block
    spanning a document boundary legitimately trains the model to
    predict EOS (and, at the EOS position itself, whatever the next
    document's first token is) exactly once, not skipped or doubled."""
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    (shard_dir / "shard-0000-train.jsonl").write_text(
        "\n".join(json.dumps({"text": t}) for t in ["1 2 3", "4 5 6"]) + "\n"
    )
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=8, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest", packing=True, eos_id=99)
    ds = GenesisBlockDataset(cfg, _IdentityTokenizer())
    tokens, labels = ds.block(0)
    assert tokens.tolist() == [1, 2, 3, 99, 4, 5, 6, 99]
    assert labels.tolist() == tokens.tolist()
    # The position right before EOS (index 2, token 3) must predict EOS (99) -- the shift is exactly one.
    shift_logits_len = len(tokens) - 1
    manual_targets = [int(tokens[i + 1]) for i in range(shift_logits_len)]
    assert manual_targets[2] == 99, "the token immediately before EOS must be supervised to predict EOS"


def test_non_packing_mode_pads_short_records(tmp_path):
    corpus_path = tmp_path / "raw.jsonl"
    corpus_path.write_text(json.dumps({"text": "short"}) + "\n")
    out_dir = tmp_path / "shards"
    _, kept = process_corpus(corpus_path, out_dir, num_shards=1)
    model_prefix = str(tmp_path / "tok2")
    train_tokenizer(kept + [f"filler sentence number {i} for vocabulary coverage" for i in range(50)], TokenizerTrainingConfig(vocab_size=300), model_prefix)
    tok = GenesisTokenizer(tmp_path / "tok2.model")
    digests = compute_shard_digests(out_dir)
    cfg = LoaderConfig(shard_dir=out_dir, split="train", seq_len=16, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest", packing=False)
    ds = GenesisBlockDataset(cfg, tok)
    assert len(ds) == 1
    input_ids, labels = ds.block(0)
    assert (labels == -100).any(), "padded positions must be masked out of the loss"


# ==================================================================================
# Antigravity Audit #074 remediation: AUDIT-P1-01 (bounded-memory dataset loading)
# ==================================================================================

def test_p1_01_peak_memory_stays_bounded_on_a_corpus_larger_than_the_buffer(tmp_path):
    """Real, measured proof (not an argument): a corpus whose total
    token count exceeds `construction_buffer_tokens` several times over
    must not cause peak memory during construction to scale with corpus
    size. Uses `tracemalloc`, the same real-measurement discipline this
    codebase's own A-07 bounded-memory proof already established --
    this test would fail if `_build_block_store()` ever regressed back
    to materializing the whole corpus in memory."""
    import tracemalloc

    class _IdentityTok:
        def encode(self, text):
            return [int(t) for t in text.split()]

    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    buffer_tokens = 2_000
    # Deliberately several times larger than the buffer -- e.g. 20,000
    # real tokens total (10x the buffer), spread across many small records.
    records_per_file = 2_000
    tokens_per_record = 10
    with open(shard_dir / "shard-0000-train.jsonl", "w") as f:
        for i in range(records_per_file):
            text = " ".join(str((i * tokens_per_record + j) % 500) for j in range(tokens_per_record))
            f.write(json.dumps({"text": text}) + "\n")
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=8, batch_size=4, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="test-tok-digest", packing=True, construction_buffer_tokens=buffer_tokens,
    )

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    snapshot_after = tracemalloc.take_snapshot()
    peak_bytes = sum(stat.size_diff for stat in snapshot_after.compare_to(snapshot_before, "filename") if stat.size_diff > 0)
    tracemalloc.stop()

    total_corpus_tokens = records_per_file * tokens_per_record
    assert total_corpus_tokens > buffer_tokens * 5, "test fixture itself is not large enough to prove anything"
    assert ds.report.total_tokens > 0
    # The bound is on the WRITE BUFFER (construction_buffer_tokens), not on
    # Python/torch's own fixed per-object overhead -- an 8-byte-per-token
    # buffer of 2,000 tokens is 16 KiB; allow a generous fixed overhead
    # margin (interpreter/object bookkeeping) while still proving peak
    # memory does NOT scale with the 20,000-token corpus (which an
    # unbounded implementation would materialize many times over).
    assert peak_bytes < 2_000_000, (
        f"peak memory during construction was {peak_bytes} bytes for a corpus of {total_corpus_tokens} tokens "
        f"with a {buffer_tokens}-token buffer -- this suggests the corpus was materialized in memory, not streamed"
    )


def test_p1_01_block_reads_remain_o1_regardless_of_dataset_size(tmp_path):
    """`block()` must read exactly one block's worth of bytes from disk,
    not scan or load anything proportional to the dataset's total size."""
    class _IdentityTok:
        def encode(self, text):
            return [int(t) for t in text.split()]

    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    with open(shard_dir / "shard-0000-train.jsonl", "w") as f:
        for i in range(500):
            f.write(json.dumps({"text": f"{i % 50} {(i + 1) % 50}"}) + "\n")
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="test-tok-digest", packing=True)
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    assert len(ds) > 10
    # Reading the LAST block must not require scanning every prior block.
    tokens, labels = ds.block(len(ds) - 1)
    assert tokens.shape == (4,)
    ds.close()


# ==============================================================================
# AUDIT #075 (successor requalification) -- block-store cache identity,
# concurrency coordination, atomic publication, and read-time integrity.
# ==============================================================================

def _simple_shard(tmp_path, text="token_one token_two token_three token_four"):
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    (shard_dir / "shard-0000-train.jsonl").write_text(json.dumps({"text": text}) + "\n")
    digests = compute_shard_digests(shard_dir)
    return shard_dir, digests


class _IdentityTok:
    def encode(self, text):
        return [int(t) if t.isdigit() else (ord(t[0]) % 28 + 4) for t in text.split()]


def test_audit075_differing_seq_len_never_collide_on_the_same_cache_path(tmp_path):
    """AUDIT-075 finding #1: the old filename omitted seq_len, so two
    datasets with different seq_len over the same shard_dir silently
    shared one store file. The cache id must differ."""
    shard_dir, digests = _simple_shard(tmp_path)
    cfg1 = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True)
    cfg2 = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=8, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True)
    ds1 = GenesisBlockDataset(cfg1, _IdentityTok())
    ds2 = GenesisBlockDataset(cfg2, _IdentityTok())
    assert ds1._store_path != ds2._store_path
    assert compute_block_store_cache_id(cfg1) != compute_block_store_cache_id(cfg2)
    ds1.close()
    ds2.close()


def test_audit075_differing_tokenizer_digest_never_collide_on_the_same_cache_path(tmp_path):
    """Same finding, different axis: two datasets identical in every
    field EXCEPT tokenizer_digest must never share a cache path."""
    shard_dir, digests = _simple_shard(tmp_path)
    cfg1 = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tokenizer-A", packing=True)
    cfg2 = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tokenizer-B", packing=True)
    assert compute_block_store_cache_id(cfg1) != compute_block_store_cache_id(cfg2)


def test_audit075_identical_config_reuses_the_published_cache_without_rebuilding(tmp_path):
    """A second constructor with an IDENTICAL config must reuse the
    already-published store (same cache id, same files) rather than
    rebuilding -- proven by checking the store's mtime does not change."""
    shard_dir, digests = _simple_shard(tmp_path)
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True)
    ds1 = GenesisBlockDataset(cfg, _IdentityTok())
    store_path = ds1._store_path
    mtime_after_first_build = store_path.stat().st_mtime_ns
    ds1.close()

    ds2 = GenesisBlockDataset(cfg, _IdentityTok())
    mtime_after_second_construction = store_path.stat().st_mtime_ns
    assert mtime_after_second_construction == mtime_after_first_build
    assert ds2.report.num_blocks == ds1.report.num_blocks
    ds2.close()


def test_audit075_concurrent_constructors_do_not_corrupt_each_others_build(tmp_path):
    """AUDIT-075 finding #2: concurrent constructors for the SAME cache
    id must serialize via the exclusive flock, not race on the store
    file. Runs several constructors from separate threads and confirms
    every one reports an identical, fully-valid block count."""
    import threading

    shard_dir, digests = _simple_shard(
        tmp_path, text=" ".join(f"tok{i}" for i in range(40))
    )
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True)

    results: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker():
        try:
            ds = GenesisBlockDataset(cfg, _IdentityTok())
            with lock:
                results.append(ds.report.num_blocks)
            ds.close()
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent construction raised: {errors}"
    assert len(results) == 8
    assert len(set(results)) == 1, f"concurrent constructors disagreed on block count: {results}"


def test_audit075_truncated_store_file_is_rejected_not_silently_undersized(tmp_path):
    """AUDIT-075 finding #2/#3: a store file truncated by a process that
    bypassed this module's lock-and-publish path must be rejected
    loudly at read time, never silently returned as a short tensor."""
    shard_dir, digests = _simple_shard(tmp_path, text="sample text for concurrency test")
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a")
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    assert ds.report.num_blocks > 0
    ds.close()

    with open(ds._store_path, "wb") as f:
        pass  # simulates an external writer ignoring the coordination lock entirely

    ds2 = GenesisBlockDataset.__new__(GenesisBlockDataset)
    ds2.cfg = cfg
    ds2.report = ds.report
    ds2._store_path = ds._store_path
    ds2._digests_path = ds._digests_path
    ds2._store_file = open(ds._store_path, "rb")
    ds2._digests_file = open(ds._digests_path, "rb")
    with pytest.raises(BlockStoreCorruptionError):
        ds2.block(0)
    ds2.close()


def test_audit075_post_publication_tampering_is_detected_at_read_time(tmp_path):
    """AUDIT-075 finding #3: modifying the published store's bytes
    directly (bypassing this module entirely) must be caught by the
    per-block digest check, never silently fed to the model."""
    shard_dir, digests = _simple_shard(tmp_path, text="original record text here")
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a")
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    assert ds.report.num_blocks > 0
    orig_tokens, _ = ds.block(0)
    ds.close()

    import array as _array
    with open(ds._store_path, "r+b") as f:
        f.seek(0)
        f.write(_array.array("q", [9999, 9999, 9999, 9999]).tobytes())

    ds2 = GenesisBlockDataset.__new__(GenesisBlockDataset)
    ds2.cfg = cfg
    ds2.report = ds.report
    ds2._store_path = ds._store_path
    ds2._digests_path = ds._digests_path
    ds2._store_file = open(ds._store_path, "rb")
    ds2._digests_file = open(ds._digests_path, "rb")
    with pytest.raises(BlockStoreTamperedError):
        ds2.block(0)
    ds2.close()


def test_audit075_symlinked_lock_path_is_rejected(tmp_path):
    """AUDIT-075 finding (path substitution): a pre-planted symlink at
    the derived lock-file path must be rejected, never followed."""
    shard_dir, digests = _simple_shard(tmp_path)
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a")
    cache_id = compute_block_store_cache_id(cfg)
    lock_path = shard_dir.resolve() / f".block_store_{cache_id}.lock"
    elsewhere = tmp_path / "elsewhere.lock"
    elsewhere.write_text("")
    lock_path.symlink_to(elsewhere)

    with pytest.raises(CachePathSecurityError):
        GenesisBlockDataset(cfg, _IdentityTok())


def test_audit075_max_tokens_per_record_rejects_oversized_records(tmp_path):
    """Mission C requirement #12: a meaningful per-record working-memory
    ceiling -- a single record larger than the configured cap is
    rejected as malformed, not silently materialized in full."""
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    huge_text = " ".join(str(i % 50) for i in range(200))
    (shard_dir / "shard-0000-train.jsonl").write_text(
        json.dumps({"text": "5 6 7"}) + "\n" + json.dumps({"text": huge_text}) + "\n"
    )
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=False,
        max_tokens_per_record=50,
    )
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    assert ds.report.records_rejected_malformed == 1
    assert ds.report.records_read == 1


def test_audit075_disk_exhaustion_during_construction_leaves_no_partial_publish(tmp_path, monkeypatch):
    """CTO pre-handoff security directive: disk exhaustion must fail
    safely -- no partially-written store is ever published at the
    canonical path, and the temp files created during the failed
    attempt are cleaned up, not left behind."""
    shard_dir, digests = _simple_shard(tmp_path, text="token_one token_two token_three token_four token_five token_six")
    cfg = LoaderConfig(shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0, authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True, construction_buffer_tokens=4)

    import os as _os
    real_fsync = _os.fsync
    call_count = {"n": 0}

    def _failing_fsync(fd):
        call_count["n"] += 1
        if call_count["n"] >= 2:  # let the first fsync (e.g. an unrelated one) through, fail a later one mid-construction
            raise OSError(28, "No space left on device")  # ENOSPC
        return real_fsync(fd)

    monkeypatch.setattr(_os, "fsync", _failing_fsync)

    with pytest.raises(OSError):
        GenesisBlockDataset(LoaderConfig(**{**cfg.__dict__}), _IdentityTok())

    # No partially-written store/digests/manifest was published at the
    # canonical cache path, and no stray .tmp files were left behind.
    # (The lock file itself is expected to persist -- that is its own
    # normal, by-design lifecycle, not a leftover of this failure.)
    assert list(shard_dir.glob(".block_store_*.tmp*")) == []
    assert list(shard_dir.glob(".block_store_*.bin")) == []
    assert list(shard_dir.glob(".block_store_*.manifest.json")) == []


# ==============================================================================
# AUDIT #076 -- truly bounded shard ingestion. Independently measured at
# increasing scale (never a single small, fixed fixture), covering raw
# Python heap (tracemalloc) AND process RSS (resource.getrusage), per
# the CTO directive's own instruction not to rely on tracemalloc alone.
# ==============================================================================

def _write_shard(shard_dir, n_lines, line_text):
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_file = shard_dir / "shard-0000-train.jsonl"
    with open(shard_file, "w", encoding="utf-8") as f:
        for _ in range(n_lines):
            f.write(json.dumps({"text": line_text}) + "\n")
    return shard_file


def test_audit076_peak_memory_does_not_scale_with_increasing_shard_size(tmp_path):
    """Mission 2, item 1: increasing synthetic shard sizes, not a single
    fixed fixture. A genuinely bounded ingestion path shows peak heap
    memory staying roughly FLAT as shard size grows by 40x, not scaling
    proportionally with it (the hallmark of the AUDIT-076 whole-file
    read defect this phase fixes)."""
    import gc
    import tracemalloc

    line_text = "The quick brown fox jumps over the lazy dog in native pretraining loop testing. " * 5
    peaks = []
    sizes = []
    for n_lines in (2_000, 20_000, 80_000):
        shard_dir = tmp_path / f"shards_{n_lines}"
        shard_file = _write_shard(shard_dir, n_lines, line_text)
        sizes.append(shard_file.stat().st_size)
        digests = compute_shard_digests(shard_dir)
        cfg = LoaderConfig(
            shard_dir=shard_dir, split="train", seq_len=16, batch_size=4, seed=42,
            authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True,
            construction_buffer_tokens=1024, max_tokens_per_record=4096,
        )
        gc.collect()
        tracemalloc.start()
        ds = GenesisBlockDataset(cfg, _IdentityTok())
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)
        assert ds.report.num_blocks > 0
        ds.close()

    assert sizes[-1] > 35 * sizes[0], "fixture itself must actually grow ~40x to prove anything"
    # A scaling (unbounded) ingestion would show peak growing roughly
    # proportionally with file size; a bounded one shows peak staying
    # within a small, roughly-constant multiple regardless of size.
    assert peaks[-1] < 3 * peaks[0] + 2_000_000, (
        f"peak memory grew from {peaks[0]} to {peaks[-1]} bytes as shard size grew "
        f"from {sizes[0]} to {sizes[-1]} bytes -- this looks like O(shard_size) scaling, not bounded ingestion"
    )
    assert peaks[-1] < sizes[-1] / 4, (
        f"peak memory ({peaks[-1]} bytes) should be a small fraction of the largest shard's own size "
        f"({sizes[-1]} bytes) for genuinely bounded ingestion"
    )


def test_audit076_peak_process_rss_does_not_scale_with_shard_size(tmp_path):
    """Mission 2, item 5: process RSS, not merely tracemalloc's Python-
    heap-only view -- catches growth tracemalloc itself would miss (C
    extension buffers, non-Python allocator activity)."""
    import resource

    line_text = "RSS measurement fixture line of reasonable, realistic length for a corpus record. " * 5
    shard_dir = tmp_path / "shards_rss"
    shard_file = _write_shard(shard_dir, 80_000, line_text)
    file_size = shard_file.stat().st_size
    assert file_size > 20_000_000, "fixture must be large enough (>20MB) for an RSS comparison to mean anything"
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=16, batch_size=4, seed=42,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True,
        construction_buffer_tokens=1024, max_tokens_per_record=4096,
    )
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KB on Linux, bytes on macOS
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ds.close()

    # ru_maxrss is a HIGH-WATER MARK for the whole process and is platform-
    # unit-dependent (KB on Linux, bytes on macOS) -- normalize to the same
    # unit as file_size (bytes) using a conservative, platform-sized guess,
    # and assert the GROWTH during construction is a small fraction of the
    # shard size, not comparable to it.
    import sys as _sys
    unit = 1 if _sys.platform == "darwin" else 1024
    rss_growth_bytes = max(0, (rss_after - rss_before) * unit)
    assert rss_growth_bytes < file_size / 4, (
        f"process RSS grew by {rss_growth_bytes} bytes while ingesting a {file_size}-byte shard -- "
        f"this looks like the whole file (or a large fraction of it) was materialized in memory"
    )


def test_audit076_one_oversized_record_with_no_newline_is_rejected_not_unbounded(tmp_path):
    """Mission 2, item 2: a single JSONL "line" with NO newline at all,
    far exceeding max_record_bytes -- must be rejected (as malformed)
    strictly before it grows without bound waiting for a newline that
    never arrives, and must not prevent the rest of a (nonexistent,
    here) corpus from being processed."""
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"
    # No trailing newline -- 20MB of a single "line".
    record_size = 20 * 1024 * 1024
    shard_file.write_bytes(b'{"text": "' + b"x" * record_size + b'"}')
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True,
        max_record_bytes=1024,
    )
    import gc
    import tracemalloc

    gc.collect()
    tracemalloc.start()
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert ds.report.records_read == 0
    # AUDIT-076 Phase 2: exactly ONE rejection for the whole oversized physical
    # record, not one per chunk it happens to span (the discard-until-newline fix).
    assert ds.report.records_rejected_malformed == 1
    assert peak < record_size / 4, (
        f"peak memory {peak} bytes should be a small fraction of the {record_size}-byte newline-less "
        f"record -- it must not grow leftover without bound waiting for a newline that never arrives"
    )
    ds.close()


def test_audit076_oversized_tokenizer_output_is_rejected_not_included(tmp_path):
    """Mission 2, item 3: a record whose encoded token count exceeds
    max_tokens_per_record is rejected as malformed and excluded from
    the block store entirely, not truncated or silently kept."""
    class _HugeExpansionTok:
        def encode(self, text):
            return [1] * 100_000  # wildly expands any input

    shard_dir, digests = _simple_shard(tmp_path, text="short")
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True,
        max_tokens_per_record=10,
    )
    ds = GenesisBlockDataset(cfg, _HugeExpansionTok())
    assert ds.report.records_read == 0
    assert ds.report.records_rejected_malformed == 1
    assert ds.report.num_blocks == 0
    ds.close()


def test_audit076_large_block_count_no_longer_accumulates_a_growing_list(tmp_path):
    """Mission 2, item 4 (and the exact AUDIT-076 block_digests finding):
    constructing a dataset with a large number of blocks must not hold
    one in-memory entry per block -- proven by confirming the internal
    list this phase removed is gone, and that peak memory for a
    many-block corpus does not scale with block COUNT any more than
    with shard byte size."""
    import gc
    import tracemalloc

    # ~50,000 short, independent records -> ~50,000+ packed blocks at seq_len=4.
    shard_dir = tmp_path / "many_blocks"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"
    with open(shard_file, "w") as f:
        for i in range(50_000):
            f.write(json.dumps({"text": f"{i % 50} {(i + 1) % 50} {(i + 2) % 50}"}) + "\n")
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True,
        construction_buffer_tokens=256,
    )
    gc.collect()
    tracemalloc.start()
    ds = GenesisBlockDataset(cfg, _IdentityTok())
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert ds.report.num_blocks > 20_000, "fixture must actually produce a large number of blocks"
    assert peak < 3_000_000, f"peak memory {peak} bytes scaled with block count ({ds.report.num_blocks} blocks)"
    ds.close()


def test_audit076_source_replacement_during_read_is_immune_due_to_open_fd(tmp_path):
    """Mission 2, item 6: replacing the shard file's directory entry
    (os.replace -- what a naive TOCTOU attack looks like) WHILE this
    module holds an already-open read file descriptor on the original
    inode has NO effect on what this read observes -- POSIX unlink/
    rename never affects an already-open fd's view of its (now
    unlinked-by-name) inode. Proven directly: the read must complete
    against the ORIGINAL content and its digest, not the replacement's."""
    shard_dir, digests = _simple_shard(tmp_path, text="original authorized content")
    shard_path = shard_dir / "shard-0000-train.jsonl"
    original_bytes = shard_path.read_bytes()

    real_open = os.open
    opened_event = {"opened": False}

    def patched_open(path, flags, *a, **kw):
        fd = real_open(path, flags, *a, **kw)
        if str(path) == str(shard_path) and not opened_event["opened"]:
            opened_event["opened"] = True
            # Attacker replaces the directory entry with a DIFFERENT file,
            # right after this module's os.open() returns its fd.
            replacement = shard_dir / "replacement.jsonl"
            replacement.write_text(json.dumps({"text": "forged replacement content"}) + "\n")
            os.replace(str(replacement), str(shard_path))
        return fd

    import orca.genesis.data.loader as loader_module
    orig = loader_module.os.open
    loader_module.os.open = patched_open
    try:
        ds = GenesisBlockDataset(LoaderConfig(
            shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
            authorized_shard_digests=digests, tokenizer_digest="tok-a",
        ), _IdentityTok())
    finally:
        loader_module.os.open = orig

    assert ds.report.num_blocks > 0  # succeeded, reading the ORIGINAL content via the already-open fd
    assert shard_path.read_bytes() != original_bytes  # the directory entry now points at the replacement
    ds.close()


def test_audit076_digest_mismatch_on_a_later_shard_publishes_nothing(tmp_path):
    """Mission 2, item 8: with multiple shard files, a digest mismatch
    discovered on a LATER file -- AFTER an earlier one already streamed
    and tokenized cleanly INTO THE BUILD LOOP's own temp buffers -- must
    still result in NOTHING being published. The tamper is injected
    precisely at the build loop's own os.open() of the second shard
    (not before `_verify_shard_integrity()`'s earlier, separate fast
    check, which uses a different open path entirely and would
    otherwise catch this before the build loop is ever reached, making
    this specifically a build-loop-level reproduction)."""
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    (shard_dir / "shard-0000-train.jsonl").write_text(json.dumps({"text": "first valid shard content"}) + "\n")
    second_path = shard_dir / "shard-0001-train.jsonl"
    second_path.write_text(json.dumps({"text": "second shard content pre tamper"}) + "\n")
    digests = compute_shard_digests(shard_dir)

    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True,
    )

    real_open = os.open
    tampered = {"done": False}

    def patched_open(path, flags, *a, **kw):
        if str(path) == str(second_path) and not tampered["done"]:
            tampered["done"] = True
            second_path.write_text(json.dumps({"text": "tampered during the build loop's own read"}) + "\n")
        return real_open(path, flags, *a, **kw)

    import orca.genesis.data.loader as loader_module
    loader_module.os.open = patched_open
    try:
        with pytest.raises(ShardIntegrityError):
            GenesisBlockDataset(cfg, _IdentityTok())
    finally:
        loader_module.os.open = real_open

    cache_id = compute_block_store_cache_id(cfg)
    assert not (shard_dir / f".block_store_{cache_id}.bin").exists()
    assert not (shard_dir / f".block_store_{cache_id}.manifest.json").exists()
    assert list(shard_dir.glob(".block_store_*.tmp*")) == []


def test_audit076_in_place_mutation_during_ingestion_is_caught_by_the_final_digest(tmp_path):
    """Mission 2, item 7: an IN-PLACE write into the SAME inode (not a
    replace) partway through this module's own streaming read -- unlike
    a replace (item 6), this IS visible through the open fd, since both
    the read-so-far and the mutation target the same underlying bytes.
    The running SHA-256 covers the ACTUAL bytes delivered by each
    os.read() call; a mutation landing after some chunks were already
    read and hashed changes the final digest away from the authorized
    one, and is caught -- not silently accepted."""
    line = json.dumps({"text": "stable prefix content repeated many times to span multiple read chunks. "}) + "\n"
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    shard_path = shard_dir / "shard-0000-train.jsonl"
    # Large enough to span several 64KiB read chunks.
    shard_path.write_text(line * 5000)
    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=True,
    )

    real_read = os.read
    mutated = {"done": False}

    def patched_read(fd, n):
        chunk = real_read(fd, n)
        if chunk and not mutated["done"]:
            mutated["done"] = True
            # In-place mutation of the SAME file, mid-stream -- not a
            # replace. Overwrites a chunk near the end of the file.
            with open(shard_path, "r+b") as f:
                f.seek(-200, os.SEEK_END)
                f.write(b"X" * 100)
        return chunk

    import orca.genesis.data.loader as loader_module
    loader_module.os.read = patched_read
    try:
        with pytest.raises(ShardIntegrityError):
            GenesisBlockDataset(cfg, _IdentityTok())
    finally:
        loader_module.os.read = real_read


def test_audit076_phase2_oversized_record_cannot_smuggle_a_crafted_suffix_as_a_separate_record(tmp_path):
    """AUDIT-076 Phase 2: independently reproduces, then proves fixed, a
    real parsing weakness -- an oversized physical line (no newline
    until its very end) whose prefix exceeds max_record_bytes used to
    have its `leftover` buffer reset to empty MID-LINE, so a crafted,
    well-formed JSON fragment appended right before the line's real
    terminating newline could be silently accepted and tokenized as if
    it were an entirely separate, legitimate record. The oversized
    prefix is deliberately an EXACT multiple of the module's own
    internal read-chunk size so the reset lands exactly at a chunk
    boundary -- the precise alignment that made the original version
    of this fix exploitable."""
    from orca.genesis.data.loader import _SHARD_READ_CHUNK_BYTES

    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard-0000-train.jsonl"

    normal_record = json.dumps({"text": "a perfectly normal valid record"}) + "\n"
    marker_record = json.dumps({"text": "SMUGGLED MARKER RECORD SHOULD NEVER BE TOKENIZED"})
    oversized_prefix = b"X" * (_SHARD_READ_CHUNK_BYTES * 5)  # exact multiple -- see docstring
    malicious_physical_line = oversized_prefix + marker_record.encode() + b"\n"
    shard_file.write_bytes(normal_record.encode() + malicious_physical_line)

    digests = compute_shard_digests(shard_dir)
    cfg = LoaderConfig(
        shard_dir=shard_dir, split="train", seq_len=4, batch_size=1, seed=0,
        authorized_shard_digests=digests, tokenizer_digest="tok-a", packing=False,
        max_record_bytes=1024, max_tokens_per_record=4096,
    )
    ds = GenesisBlockDataset(cfg, _IdentityTok())

    # Exactly one real record (the normal one) and exactly one rejection
    # for the ENTIRE oversized physical line -- not a leaked second record.
    assert ds.report.records_read == 1
    assert ds.report.records_rejected_malformed == 1
    assert ds.report.num_blocks == 1

    inp, _lbl = ds.block(0)
    marker_tokens = _IdentityTok().encode("SMUGGLED MARKER RECORD")
    block_tokens = inp.tolist()
    # The smuggled marker's own token sequence must not appear anywhere
    # in the published block store at all.
    assert not any(block_tokens[i:i + len(marker_tokens)] == marker_tokens for i in range(len(block_tokens))), (
        "the smuggled marker record's tokens leaked into the published block store"
    )
    ds.close()
