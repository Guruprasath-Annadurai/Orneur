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

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import torch

from orca.genesis.data.pipeline import _shard_path, compute_shard_digests
from orca.genesis.tokenizer.framework import EOS_ID, PAD_ID, GenesisTokenizer

VALID_SPLITS = ("train", "validation", "test")
IGNORE_INDEX = -100


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
    assumed from the caller's `split` argument alone."""

    def __init__(self, cfg: LoaderConfig, tokenizer: GenesisTokenizer):
        self.cfg = cfg
        self.tokenizer = tokenizer
        self._verify_shard_integrity()
        blocks, report = self._build_blocks()
        self._blocks = blocks  # list[torch.Tensor], each shape (seq_len + 1,) -- input+next-token in one tensor
        self.report = report

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

    def _build_blocks(self) -> tuple[list[torch.Tensor], LoadReport]:
        records_read = 0
        rejected = 0
        token_stream: list[int] = []
        per_record_blocks: list[torch.Tensor] = []

        for path in self._split_shard_paths():
            with open(path, encoding="utf-8") as f:
                for line_number, raw_line in enumerate(f):
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
                    except (json.JSONDecodeError, KeyError, MalformedRecordError):
                        rejected += 1
                        continue
                    records_read += 1

                    if self.cfg.packing:
                        token_stream.extend(ids)
                        token_stream.append(self.cfg.eos_id)
                    else:
                        seq = ids[: self.cfg.seq_len + 1]
                        if len(seq) < self.cfg.seq_len + 1:
                            seq = seq + [self.cfg.pad_id] * (self.cfg.seq_len + 1 - len(seq))
                        per_record_blocks.append(torch.tensor(seq, dtype=torch.long))

        if self.cfg.packing:
            block_len = self.cfg.seq_len + 1  # +1 so a block carries both input_ids and the final next-token target
            num_blocks = len(token_stream) // block_len
            blocks = [
                torch.tensor(token_stream[i * block_len:(i + 1) * block_len], dtype=torch.long)
                for i in range(num_blocks)
            ]
            total_tokens = len(token_stream)
        else:
            blocks = per_record_blocks
            total_tokens = sum(b.numel() for b in blocks)

        return blocks, LoadReport(
            records_read=records_read, records_rejected_malformed=rejected,
            total_tokens=total_tokens, num_blocks=len(blocks),
        )

    def __len__(self) -> int:
        return len(self._blocks)

    def block(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns `(input_ids, labels)`, each shape `(seq_len,)`.
        `labels` masks pad positions with `IGNORE_INDEX` so a
        pad-truncated record (non-packing mode) never contributes to
        the loss for its padded tail; `causal_lm_loss` performs its own
        additional internal shift on top of this."""
        full = self._blocks[index]
        input_ids = full[:-1]
        labels = full[1:].clone()
        labels[input_ids == self.cfg.pad_id] = IGNORE_INDEX
        return input_ids, labels


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
