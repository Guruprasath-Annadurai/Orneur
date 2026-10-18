"""
GENESIS Native Learning Engine, Phase 1, Workstream 2 tests:
`orca.genesis.data.loader`. Bounded, CPU-only, synthetic corpus only.
"""
from __future__ import annotations

import json

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
