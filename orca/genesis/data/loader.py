"""
GENESIS Native Learning Engine, Phase 1, Workstream 2: the missing
bridge from `orca.genesis.data.pipeline`'s qualified, content-verified
shard files to model-ready `(input_ids, labels)` batches for
`orca.genesis.training.learning_step.TrainingStepEngine`.

Reuses existing, already-tested infrastructure rather than duplicating
it: `orca.genesis.data.pipeline.compute_shard_digests()` for the same
real, streamed SHA-256 shard-content digest every other GENESIS
integrity check already uses (`_shard_path()`'s own `shard-{idx:04d}-
{split}.jsonl` naming convention), and `orca.genesis.tokenizer.framework
.GenesisTokenizer` for encoding -- this module adds only the batching/
packing/sampling orchestration neither of those already provides.

**Consumed-data integrity contract, stated explicitly (per this phase's
directive)**: `GenesisBlockDataset.__init__` re-verifies every shard
file's content digest against the caller-supplied
`authorized_shard_digests` mapping ONCE, at construction time, before
reading a single byte for tokenization. This is read-TIME verification,
not read-CONTINUOUS verification -- it proves the bytes on disk matched
the authorized digest at the moment this dataset object was built, not
that no process modifies the underlying files during the lifetime of a
long-running training loop that holds this dataset open across many
steps. Closing that residual window would require either re-verifying
the full shard set before every single batch (prohibitively expensive
for anything beyond a tiny synthetic corpus) or a filesystem-level
immutability guarantee this module does not have access to. This is the
SAME class of boundary `orca.genesis.training.orchestration`'s P0-01 fix
documents for its own, different checkpoint (verification at state
transition, not continuous) -- restated here because this is a genuinely
different code path (reading data bytes for training, not re-entering
RUNNING), not something the orchestration-layer check already covers.
"""
from __future__ import annotations

import array
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import torch

from orca.genesis.data.pipeline import _shard_path, compute_shard_digests
from orca.genesis.tokenizer.framework import EOS_ID, PAD_ID, GenesisTokenizer

VALID_SPLITS = ("train", "validation", "test")
IGNORE_INDEX = -100
_TOKEN_TYPECODE = "q"  # array module "long long" -- platform-independent minimum 8 bytes, safely covers any real vocab id
_TOKEN_ITEM_SIZE = array.array(_TOKEN_TYPECODE).itemsize


class ShardIntegrityError(Exception):
    """Raised when a shard file's live, re-computed content digest does
    not match the caller-supplied `authorized_shard_digests` mapping --
    fail-closed, never silently read with a warning."""


class CrossSplitAccessError(Exception):
    """Raised if construction or any read path would touch a shard file
    belonging to a split other than the one this dataset was bound to.
    Structural, not merely a filtered glob: `_shard_path()`'s own
    filename convention encodes the split, so this is checked against
    the actual filename, not a value the caller could spoof by mislabeling."""


class MalformedRecordError(Exception):
    """A single malformed record's own identifying detail -- raised
    internally and always caught by `GenesisBlockDataset`'s own loading
    loop (see `_load_split_tokens`), which converts it into a counted,
    skipped rejection, never a silent inclusion and never an uncaught
    crash partway through loading a large corpus."""


@dataclass(frozen=True)
class LoaderConfig:
    """Every knob the loader needs, validated eagerly. `packing=True`
    (the default, and the standard choice for pretraining -- see e.g.
    nanoGPT/most published LLaMA-family data pipelines) concatenates
    every record's tokens (each terminated by `eos_id`) into one long
    stream and chunks it into fixed-`seq_len` blocks, maximizing token
    utilization with no padding at all. `packing=False` instead
    pads/truncates EACH record independently to `seq_len`, which is
    slower (more padding waste) but keeps record boundaries == batch-item
    boundaries, useful for inspection or for data that must never be
    concatenated across record boundaries."""
    shard_dir: Path
    split: str
    seq_len: int
    batch_size: int
    seed: int
    authorized_shard_digests: Mapping[str, str]
    packing: bool = True
    pad_id: int = PAD_ID
    eos_id: int = EOS_ID
    construction_buffer_tokens: int = 65_536  # AUDIT-P1-01: the real, enforced in-memory ceiling during construction -- see GenesisBlockDataset's own docstring

    def __post_init__(self) -> None:
        if self.split not in VALID_SPLITS:
            raise ValueError(f"split must be one of {VALID_SPLITS}, got {self.split!r}")
        if self.seq_len < 2:
            raise ValueError("seq_len must be >= 2 (causal_lm_loss requires at least one next-token pair)")
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if not self.authorized_shard_digests:
            raise ValueError(
                "authorized_shard_digests is required and must be non-empty -- this loader never reads "
                "shard content without an explicit, caller-supplied set of digests to verify against"
            )
        if self.construction_buffer_tokens < self.seq_len:
            raise ValueError("construction_buffer_tokens must be >= seq_len (a buffer smaller than one block can never flush a complete block)")


@dataclass(frozen=True)
class LoadReport:
    """Every record is accounted for in exactly one bucket -- mirrors
    `orca.genesis.data.pipeline.ProcessingReport`'s own discipline."""
    records_read: int
    records_rejected_malformed: int
    total_tokens: int
    num_blocks: int


class GenesisBlockDataset:
    """Owns exactly one split's worth of tokenized, block-ready data.
    Never reads, and structurally cannot read, another split's shard
    files -- `_shard_path()`'s filename convention (`shard-{idx:04d}-
    {split}.jsonl`) is parsed from the actual filename on disk, not
    assumed from the caller's `split` argument alone.

    ## Antigravity Audit #074 remediation -- AUDIT-P1-01 (bounded memory)

    Independently reproduced: the PRIOR version of `_build_blocks()`
    tokenized every record from every shard file and accumulated ALL of
    it -- either one giant Python `list[int]` token stream (packing
    mode) or a `list[torch.Tensor]` with one entry per record
    (non-packing mode) -- held in `self._blocks` for this dataset's
    entire lifetime. Peak memory scaled linearly with total corpus
    size, with no configured ceiling at all; a corpus larger than
    available RAM crashed with `MemoryError` during construction,
    before a single training step could run.

    **Fixed**: tokens are now streamed to a fixed-width, append-only
    on-disk block store (`<shard_dir>/.block_store_<split>_<packing>.bin`,
    8 bytes/token, platform-independent `array('q')` layout) through a
    BOUNDED in-memory write buffer (`cfg.construction_buffer_tokens`,
    default 65,536 tokens = 512 KiB -- never the whole corpus). `block()`
    then reads exactly one block's worth of bytes (`seq_len * 8`) via a
    direct `seek()` + bounded `read()` on an already-open file handle --
    O(1) memory per call, completely independent of how large the
    overall dataset is. This is genuinely measured, not merely argued:
    `tests/test_genesis_data_loader.py`'s own
    `test_p1_01_peak_memory_stays_bounded_on_a_corpus_larger_than_the_buffer`
    uses `tracemalloc` (the same real-measurement discipline this
    codebase's own A-07 bounded-memory proof already established) to
    confirm peak memory during construction does not scale with corpus
    size, against a corpus deliberately larger than
    `construction_buffer_tokens`.

    Caller-supplied `authorized_shard_digests` is still, exactly as
    before, verified against the real, live shard file content at
    construction time (never a claim this dataset invents or weakens);
    Audit #074's P1-01 finding additionally noted this mapping itself
    has no independent authority root of its own at this layer -- true,
    and unchanged by this fix: the caller (ultimately
    `GenesisTrainingRun`/`orca.genesis.training.learning_governance`) is
    responsible for sourcing `authorized_shard_digests` from a real,
    signed grant, not an arbitrary caller-chosen mapping; this module's
    own job is to verify the FILES match WHATEVER mapping it is given,
    which it continues to do unconditionally."""

    def __init__(self, cfg: LoaderConfig, tokenizer: GenesisTokenizer):
        self.cfg = cfg
        self.tokenizer = tokenizer
        self._verify_shard_integrity()
        self._store_path = Path(cfg.shard_dir) / f".block_store_{cfg.split}_{'packed' if cfg.packing else 'padded'}.bin"
        self.report = self._build_block_store()
        self._store_file = open(self._store_path, "rb")

    def close(self) -> None:
        if not self._store_file.closed:
            self._store_file.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _split_shard_paths(self) -> list[Path]:
        """Every file in `shard_dir` whose OWN filename declares it
        belongs to this dataset's split -- never a path constructed from
        an unvalidated caller string."""
        paths = sorted(Path(self.cfg.shard_dir).glob(f"shard-*-{self.cfg.split}.jsonl"))
        for p in paths:
            if not p.name.endswith(f"-{self.cfg.split}.jsonl"):
                raise CrossSplitAccessError(f"internal glob error: {p} does not actually belong to split {self.cfg.split!r}")
        return paths

    def _verify_shard_integrity(self) -> None:
        """Read-time (not read-continuous -- see module docstring)
        re-verification: every file this split's own glob would read
        must have a live digest matching the authorized mapping. A
        shard present on disk but ABSENT from `authorized_shard_digests`
        is also rejected -- an unexpected file is never silently
        included just because its own digest happens to be internally
        consistent with itself."""
        live = compute_shard_digests(Path(self.cfg.shard_dir))
        for p in self._split_shard_paths():
            authorized = self.cfg.authorized_shard_digests.get(p.name)
            if authorized is None:
                raise ShardIntegrityError(f"shard file {p.name} is not present in authorized_shard_digests -- refusing to read an unauthorized file")
            actual = live.get(p.name)
            if actual != authorized:
                raise ShardIntegrityError(
                    f"shard file {p.name} content digest {actual!r} does not match authorized digest "
                    f"{authorized!r} -- refusing to read tampered or stale shard content"
                )

    def _build_block_store(self) -> LoadReport:
        """AUDIT-P1-01 fix: streams tokens to the on-disk block store
        through a BOUNDED buffer (`cfg.construction_buffer_tokens`),
        never holding the full corpus (or even the full output) in
        memory at once. See this class's own docstring for the full
        rationale and the dedicated `tracemalloc`-based test that
        measures this, rather than merely asserting it."""
        records_read = 0
        rejected = 0
        total_tokens = 0
        buffer = array.array(_TOKEN_TYPECODE)
        buffer_cap = self.cfg.construction_buffer_tokens

        with open(self._store_path, "wb") as store:
            def flush() -> None:
                nonlocal buffer
                if buffer:
                    store.write(buffer.tobytes())
                    buffer = array.array(_TOKEN_TYPECODE)

            def emit(ids: list[int]) -> None:
                nonlocal total_tokens
                buffer.extend(ids)
                total_tokens += len(ids)
                if len(buffer) >= buffer_cap:
                    flush()

            for path in self._split_shard_paths():
                with open(path, encoding="utf-8") as f:
                    for raw_line in f:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            rec = json.loads(raw_line)
                            text = rec["text"]
                            if not isinstance(text, str) or not text.strip():
                                raise MalformedRecordError("empty or non-string 'text'")
                            ids = self.tokenizer.encode(text)
                            if not ids:
                                raise MalformedRecordError("tokenizer produced zero tokens")
                            # AUDIT-P0-01 fix: a non-packed block is exactly `seq_len`
                            # REAL tokens (truncated/padded), not `seq_len + 1` -- see
                            # `block()`'s own docstring for why. A record whose real
                            # (non-padding) token count is < 2 can NEVER produce a
                            # single supervised pair under a correct one-shift
                            # objective (there is no "this token" + "the next token"
                            # pair to form at all) -- rejected here, at LOAD time, as
                            # malformed, rather than silently reaching
                            # causal_lm_loss() and crashing mid-training-step.
                            if not self.cfg.packing and len(ids) < 2:
                                raise MalformedRecordError(f"only {len(ids)} token(s) after encoding -- cannot form a single supervised next-token pair")
                        except (json.JSONDecodeError, KeyError, MalformedRecordError):
                            rejected += 1
                            continue
                        records_read += 1

                        if self.cfg.packing:
                            emit(ids)
                            emit([self.cfg.eos_id])
                        else:
                            seq = ids[: self.cfg.seq_len]
                            if len(seq) < self.cfg.seq_len:
                                seq = seq + [self.cfg.pad_id] * (self.cfg.seq_len - len(seq))
                            emit(seq)  # exactly one full block -- never accumulated alongside any other record's

            flush()
            store.flush()

        block_len = self.cfg.seq_len  # AUDIT-P0-01 fix: no "+1" -- see block()'s own docstring
        if self.cfg.packing:
            num_blocks = total_tokens // block_len
            usable_tokens = num_blocks * block_len
        else:
            num_blocks = records_read
            usable_tokens = total_tokens

        return LoadReport(
            records_read=records_read, records_rejected_malformed=rejected,
            total_tokens=usable_tokens, num_blocks=num_blocks,
        )

    def __len__(self) -> int:
        return self.report.num_blocks

    def block(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns `(input_ids, labels)`, each shape `(seq_len,)` --
        the SAME token sequence, not pre-shifted against each other.

        AUDIT-P0-01 fix (Antigravity Audit #074), stated as the single,
        mathematically consistent interface this module now commits to,
        documented here so it is never silently re-introduced: exactly
        ONE shift happens anywhere in the whole input->loss pipeline,
        and it happens inside `orca.genesis.training.primitives
        .causal_lm_loss()` -- which already, correctly, performs
        `shift_logits = logits[..., :-1, :]` / `shift_labels = labels[...,
        1:]` internally, the standard HuggingFace/nanoGPT convention of
        passing `labels == input_ids` (unshifted) and letting the loss
        function itself realign them. The PRIOR version of this method
        ALSO pre-shifted (`input_ids = full[:-1]`, `labels = full[1:]`)
        before handing both to `causal_lm_loss()`, which shifted AGAIN --
        independently reproduced (Audit #074, `test_p0_01_mathematical
        _proof_of_double_shift` and `test_p0_01_associative_recall_learns
        _t_plus_2_instead_of_t_plus_1`) to train the model to predict
        T_{i+2}, completely skipping T_{i+1}, while still producing a
        finite, decreasing loss -- a silent, catastrophic correctness
        defect no shape-level test had caught.

        `_build_block_store()` now produces blocks of exactly `seq_len`
        tokens (not `seq_len + 1`) for this exact reason -- feeding
        `causal_lm_loss()` its own expected, un-shifted convention costs
        exactly one supervised position per block versus the (buggy)
        `seq_len + 1` layout: with `seq_len` input tokens, the LAST
        position's logit is computed (needed as context for everything
        before it) but is never itself supervised, because there is no
        `seq_len + 1`-th token within this block to compare it against
        -- this is the standard, accepted "final-token utilization"
        trade-off every mainstream causal-LM training implementation
        makes (the alternative, carrying one extra token per block
        purely to supervise the final position, would itself need
        `causal_lm_loss()` to NOT re-shift, which is exactly what
        this fix establishes as the module's one, single, documented
        shift point) -- not an oversight, and explicitly verified by
        `tests/test_genesis_data_loader.py::test_final_token_utilization_is_the_standard_accepted_trade_off_not_a_silent_loss`.

        Padding is masked directly against the UNSHIFTED label array (a
        padded position's own label, not a shifted neighbor's), so
        `causal_lm_loss()`'s internal shift correctly carries the mask
        to the position it belongs to -- closing the companion
        AUDIT-P0-01 padding-mask defect (the prior pre-shifted version
        masked `labels` at `input_ids == pad_id`, which -- because
        `labels` was `full[1:]`, one position ahead of `input_ids` --
        left the FIRST real pad token's own label position unmasked).

        AUDIT-P1-01 fix: reads exactly this one block's bytes from the
        on-disk store via `seek()` + a bounded `read()` -- O(1) memory,
        independent of how many total blocks this dataset has."""
        if not (0 <= index < self.report.num_blocks):
            raise IndexError(f"block index {index} out of range for a dataset of {self.report.num_blocks} blocks")
        block_len = self.cfg.seq_len
        offset = index * block_len * _TOKEN_ITEM_SIZE
        self._store_file.seek(offset)
        raw = self._store_file.read(block_len * _TOKEN_ITEM_SIZE)
        buf = array.array(_TOKEN_TYPECODE)
        buf.frombytes(raw)
        tokens = torch.tensor(buf.tolist(), dtype=torch.long)
        labels = tokens.clone()
        labels[tokens == self.cfg.pad_id] = IGNORE_INDEX
        return tokens, labels


class ReproducibleSampler:
    """A seeded permutation over `[0, num_blocks)`, with an explicit,
    externally-readable/settable `position` so a resumed run can
    continue from the exact block a prior run stopped at -- the
    `dataset_sampler_position` Workstream 3's checkpoint extension
    requires. `torch.Generator` (not the ambient global RNG) is used
    specifically so sampling order never depends on, or perturbs, any
    other RNG-consuming code running in the same process."""

    def __init__(self, num_blocks: int, seed: int):
        self.num_blocks = num_blocks
        self.seed = seed
        gen = torch.Generator()
        gen.manual_seed(seed)
        self._order = torch.randperm(num_blocks, generator=gen).tolist() if num_blocks > 0 else []
        self.position = 0

    def next_batch_indices(self, batch_size: int) -> list[int]:
        """Returns up to `batch_size` block indices and advances
        `position`; wraps around (a new epoch) rather than raising, the
        standard pretraining-loop convention of treating the corpus as
        an effectively infinite stream."""
        if self.num_blocks == 0:
            raise ValueError("cannot sample from a dataset with zero blocks")
        out = []
        for _ in range(batch_size):
            out.append(self._order[self.position])
            self.position = (self.position + 1) % self.num_blocks
        return out


def make_batch(dataset: GenesisBlockDataset, indices: list[int]) -> tuple[torch.Tensor, torch.Tensor]:
    """Stacks individually-produced `(input_ids, labels)` pairs into one
    `(batch_size, seq_len)` batch each -- a thin, explicit collate step,
    not hidden inside a framework `collate_fn` callback."""
    input_ids_list, labels_list = zip(*(dataset.block(i) for i in indices))
    return torch.stack(input_ids_list, dim=0), torch.stack(labels_list, dim=0)
