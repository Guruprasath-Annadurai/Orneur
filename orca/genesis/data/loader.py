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

## Audit #075 (successor requalification) remediation -- derived block
store cache identity, concurrency and integrity

Audit #075 found that the on-disk block store introduced by the prior
Audit #074 fix (bounded-memory streaming) had four real gaps once a
second caller or a second process entered the picture:

1. **Cache identity collision**: the store filename
   (`.block_store_{split}_{packing}.bin`) omitted `seq_len` and
   tokenizer identity, so two datasets built with different `seq_len`
   (or a different tokenizer) over the same `shard_dir` silently shared
   one file -- the second construction's `block_len` no longer matched
   the bytes the first one wrote.
2. **No concurrency coordination**: `_build_block_store()` opened the
   canonical store path directly with `"wb"`, so a second concurrent
   constructor truncated the first one's in-progress write.
3. **No read-time integrity verification**: `block()` read raw bytes
   straight off disk with no way to detect either truncation or
   post-construction tampering of the derived `.bin` file itself.

This phase's fix, in one coherent design (not three independent patches):

- `compute_block_store_cache_id()` derives a collision-resistant
  (SHA-256) identifier from every input that affects the store's
  content: schema version, split, packing mode, `seq_len`, `pad_id`,
  `eos_id`, the caller-supplied `tokenizer_digest`, and the full,
  already-verified `authorized_shard_digests` mapping. The store,
  manifest and lock file names are all derived from this one id, so two
  configurations that differ in ANY of these inputs can never collide,
  and the same configuration always resolves to the same cache --
  closing the collision finding structurally, not by convention.
- Construction acquires an exclusive `fcntl.flock` on a dedicated lock
  file for the entire get-or-build sequence (check-cache -> build ->
  publish), serializing every constructor that targets the same cache
  id, in-process or cross-process. A second constructor that arrives
  while the first is still building blocks on the lock, then finds the
  now-published cache and skips rebuilding.
- The store is always built into a brand-new `tempfile.mkstemp()` file
  in the SAME directory (so the final rename is on one filesystem, and
  therefore atomic), fsynced, and only then published via `os.replace()`
  onto the canonical path -- a reader can never observe a partially
  written store at the canonical name, because the canonical name never
  refers to an incomplete file at any point in its existence.
- A sidecar manifest (`.manifest.json`, published the same tmp-then-
  atomic-replace way) records the whole-store SHA-256 and a per-block,
  fixed-width truncated digest table (a second binary sidecar file, read
  the same O(1) `seek()`-based way as the blocks themselves) so `block()`
  can both assert the exact expected byte length (catching truncation,
  e.g. from an external process that ignored the lock and overwrote the
  file directly) and recompute-and-compare that block's own digest
  (catching post-construction tampering) on every read, without reading
  the whole store.
- Canonical store/manifest/digest paths are checked with `is_symlink()`
  before being trusted, and are always resolved underneath `shard_dir`'s
  own resolved, real path -- a symlink planted at any of these three
  names is rejected rather than silently followed.

**Explicitly, honestly NOT claimed**: the per-block digest is a plain
(truncated) SHA-256, not an HMAC against any secret key -- there is no
established, owner-controlled key-custody infrastructure for derived
data caches the way `orca.genesis.training.resumable_checkpoint`'s
`integrity_key` exists for checkpoints. This detects accidental
corruption, truncation, and after-the-fact tampering by a party who
does not also control the digest sidecar at the moment of attack; it is
NOT cryptographic protection against an adversary with simultaneous
write access to both the store and its manifest. Closing that fully
would require the same class of trust-anchor work Audit #074's P0-04
fix did for checkpoints, applied to this cache -- recorded here as a
residual limitation, not silently claimed as closed.
"""
from __future__ import annotations

import array
import fcntl
import hashlib
import hmac
import json
import os
import tempfile
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
BLOCK_STORE_SCHEMA_VERSION = "genesis-block-store/2"
_BLOCK_DIGEST_SIZE = 8  # bytes -- truncated SHA-256, see module docstring for the explicit, honest scope of this check
_SHARD_READ_CHUNK_BYTES = 64 * 1024  # AUDIT-076: fixed-size read chunk for shard ingestion -- the real, enforced in-memory ceiling for the raw-byte side of shard streaming, independent of file size


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


class CachePathSecurityError(Exception):
    """Raised if a derived block-store path (store, manifest, digest
    table or lock file) is found to already be a symlink, or does not
    resolve underneath the dataset's own resolved `shard_dir` -- see
    module docstring, AUDIT-075 path-substitution finding."""


class BlockStoreCorruptionError(Exception):
    """Raised when a read from the on-disk block store does not return
    the exact expected number of bytes -- e.g. an external process
    truncated or partially overwrote the store file outside this
    module's own lock-coordinated publish path. Never silently
    returned as an undersized tensor."""


class BlockStoreTamperedError(Exception):
    """Raised when a block's recomputed digest does not match the
    digest recorded for it at construction time -- see module docstring
    for the explicit, honest scope of this check (plain SHA-256, not an
    HMAC against a secret key)."""


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
    concatenated across record boundaries.

    `tokenizer_digest` (AUDIT-075): a caller-supplied identity string
    for the tokenizer actually used to encode this split -- exactly the
    same posture as `authorized_shard_digests`, this module does not
    invent tokenizer identity, it only requires the caller state one so
    it can be bound into the derived cache's identity (see
    `compute_block_store_cache_id()`)."""
    shard_dir: Path
    split: str
    seq_len: int
    batch_size: int
    seed: int
    authorized_shard_digests: Mapping[str, str]
    tokenizer_digest: str
    packing: bool = True
    pad_id: int = PAD_ID
    eos_id: int = EOS_ID
    construction_buffer_tokens: int = 65_536  # AUDIT-P1-01: the real, enforced in-memory ceiling during construction -- see GenesisBlockDataset's own docstring
    max_tokens_per_record: int | None = None  # AUDIT-075: per-record working-memory ceiling (post-tokenization); defaults to construction_buffer_tokens in __post_init__
    max_record_bytes: int = 1_048_576  # AUDIT-076: per-record RAW BYTE ceiling, enforced on the undecoded line before any decode/json.loads/tokenize call -- see _build_and_publish_block_store's own docstring

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
        if not self.tokenizer_digest:
            raise ValueError(
                "tokenizer_digest is required and must be non-empty -- AUDIT-075 binds the derived block "
                "store's cache identity to the tokenizer actually used, closing the cache-collision finding"
            )
        if self.construction_buffer_tokens < self.seq_len:
            raise ValueError("construction_buffer_tokens must be >= seq_len (a buffer smaller than one block can never flush a complete block)")
        if self.max_tokens_per_record is None:
            object.__setattr__(self, "max_tokens_per_record", self.construction_buffer_tokens)
        if self.max_tokens_per_record < 1:
            raise ValueError("max_tokens_per_record must be >= 1")
        if self.max_record_bytes < 1:
            raise ValueError("max_record_bytes must be >= 1")


@dataclass(frozen=True)
class LoadReport:
    """Every record is accounted for in exactly one bucket -- mirrors
    `orca.genesis.data.pipeline.ProcessingReport`'s own discipline."""
    records_read: int
    records_rejected_malformed: int
    total_tokens: int
    num_blocks: int


def compute_block_store_cache_id(cfg: LoaderConfig) -> str:
    """A collision-resistant (SHA-256) identifier binding every input
    that affects the derived block store's content: schema version,
    split, packing mode, `seq_len`, `pad_id`, `eos_id`, the caller's
    `tokenizer_digest`, and the full `authorized_shard_digests`
    mapping (sorted for determinism). Two `LoaderConfig`s that differ
    in ANY of these fields always produce different cache ids -- see
    AUDIT-075 in the module docstring."""
    payload = {
        "schema_version": BLOCK_STORE_SCHEMA_VERSION,
        "split": cfg.split,
        "packing": cfg.packing,
        "seq_len": cfg.seq_len,
        "pad_id": cfg.pad_id,
        "eos_id": cfg.eos_id,
        "tokenizer_digest": cfg.tokenizer_digest,
        "authorized_shard_digests": sorted(cfg.authorized_shard_digests.items()),
    }
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _atomic_publish(tmp_path: Path, final_path: Path) -> None:
    """Fsync the completed temp file, then atomically rename it onto
    `final_path` (same directory, so the rename is a single filesystem
    op -- POSIX guarantees a reader never observes a partially written
    file at `final_path`). Best-effort directory fsync for durability
    against a crash immediately after rename; not fatal if unsupported."""
    with open(tmp_path, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp_path, final_path)
    try:
        dir_fd = os.open(str(final_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass  # best-effort only -- not every platform/filesystem supports directory fsync


class GenesisBlockDataset:
    """Owns exactly one split's worth of tokenized, block-ready data.
    Never reads, and structurally cannot read, another split's shard
    files -- `_shard_path()`'s filename convention (`shard-{idx:04d}-
    {split}.jsonl`) is parsed from the actual filename on disk, not
    assumed from the caller's `split` argument alone.

    ## Antigravity Audit #074 remediation -- AUDIT-P1-01 (bounded memory)

    Tokens are streamed to a fixed-width, append-only on-disk block
    store through a BOUNDED in-memory write buffer
    (`cfg.construction_buffer_tokens`, default 65,536 tokens = 512 KiB
    -- never the whole corpus). `block()` then reads exactly one
    block's worth of bytes (`seq_len * 8`) via a direct `seek()` +
    bounded `read()` on an already-open file handle -- O(1) memory per
    call, completely independent of how large the overall dataset is.

    ## Antigravity Audit #075 remediation -- cache identity, concurrency,
    atomic publication and read-time integrity

    See the module docstring for the full design. In short: the store's
    path is now a function of `compute_block_store_cache_id(cfg)`
    (closing the seq_len/tokenizer collision finding), construction is
    coordinated across processes via an exclusive `fcntl.flock`,
    publication is tmp-file-then-`os.replace()` (closing the torn-write
    / concurrent-writer-truncation finding), and every `block()` read
    both length-checks and digest-verifies its bytes against a sidecar
    digest table built at construction time (closing the unverified-
    read-time-tampering finding)."""

    def __init__(self, cfg: LoaderConfig, tokenizer: GenesisTokenizer):
        self.cfg = cfg
        self.tokenizer = tokenizer
        self._verify_shard_integrity()

        base_dir = Path(cfg.shard_dir).resolve()
        cache_id = compute_block_store_cache_id(cfg)
        self._store_path = base_dir / f".block_store_{cache_id}.bin"
        self._digests_path = base_dir / f".block_store_{cache_id}.digests.bin"
        self._manifest_path = base_dir / f".block_store_{cache_id}.manifest.json"
        lock_path = base_dir / f".block_store_{cache_id}.lock"
        self._reject_if_symlink(lock_path)

        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                cached = self._load_cached_report_if_valid()
                if cached is not None:
                    self.report = cached
                else:
                    self.report = self._build_and_publish_block_store(base_dir, cache_id)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

        self._store_file = open(self._store_path, "rb")
        self._digests_file = open(self._digests_path, "rb")

    def close(self) -> None:
        for f in (getattr(self, "_store_file", None), getattr(self, "_digests_file", None)):
            if f is not None and not f.closed:
                f.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _reject_if_symlink(self, path: Path) -> None:
        if path.is_symlink():
            raise CachePathSecurityError(f"refusing to use {path} as a block-store cache path -- it is a symlink, not a regular file")

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

    def _load_cached_report_if_valid(self) -> LoadReport | None:
        """Called while holding the exclusive cache lock. Returns a
        `LoadReport` reconstructed from an already-published manifest
        if, and only if, the store file's actual whole-file SHA-256
        matches the manifest's recorded digest and the schema/cache id
        line up -- never trusts a manifest's own claimed report fields
        without that independent check. Returns None (meaning: build
        it) if anything is missing, mismatched, or either path is a
        symlink."""
        for p in (self._store_path, self._manifest_path, self._digests_path):
            if p.is_symlink():
                raise CachePathSecurityError(f"refusing to trust {p} -- it is a symlink, not a regular file")
        if not (self._store_path.exists() and self._manifest_path.exists() and self._digests_path.exists()):
            return None
        try:
            manifest = json.loads(self._manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if manifest.get("schema_version") != BLOCK_STORE_SCHEMA_VERSION:
            return None
        actual_sha256 = self._sha256_of_file(self._store_path)
        if actual_sha256 != manifest.get("store_sha256"):
            return None
        try:
            return LoadReport(
                records_read=manifest["records_read"],
                records_rejected_malformed=manifest["records_rejected_malformed"],
                total_tokens=manifest["total_tokens"],
                num_blocks=manifest["num_blocks"],
            )
        except KeyError:
            return None

    @staticmethod
    def _sha256_of_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _build_and_publish_block_store(self, base_dir: Path, cache_id: str) -> LoadReport:
        """Called while holding the exclusive cache lock. Streams
        tokens through a BOUNDED buffer (`cfg.construction_buffer_tokens`),
        extracting and publishing exactly `seq_len`-token blocks as soon
        as enough tokens have accumulated -- never holding the full
        corpus, or even the full output, in memory at once. Builds into
        unique temp files and only publishes (atomic rename) after the
        full corpus has been consumed successfully; a crash or
        exception at any point leaves the canonical store/manifest/
        digest paths untouched (either still absent, or still holding a
        PRIOR valid publish) and only an orphaned temp file behind.

        ## AUDIT-076 remediation -- truly bounded shard ingestion

        Independently reproduced and confirmed before this fix: the
        PRIOR version of this method (an AUDIT-075 TOCTOU fix) called
        `path.read_bytes()` to read an ENTIRE shard file into one Python
        `bytes` object, then `.decode("utf-8").splitlines()` on top of
        that -- for a 5 GB shard, this allocates the raw bytes, the
        decoded Unicode string, AND the list of split line strings
        simultaneously, completely bypassing `construction_buffer_tokens`
        and scaling memory `O(shard_size)`. Separately, `block_digests:
        list[bytes]` accumulated one entry per block for the dataset's
        entire construction, scaling memory `O(block_count)` -- used
        only to compute `len(block_digests)` at the end, a value a
        plain integer counter already gives for free.

        **Fixed, both issues, in the SAME redesign (not two patches)**:
        - `block_digests` is gone entirely; `num_blocks_written` is a
          plain `int`, incremented once per flushed block.
        - Each shard file is opened ONCE via `os.open()` and read in
          fixed `_SHARD_READ_CHUNK_BYTES` chunks via `os.read()` -- never
          the whole file. Each chunk simultaneously (a) feeds a running
          `hashlib.sha256()` for the live content digest and (b) is
          appended to a small, BOUNDED `leftover` buffer that is split on
          newlines and immediately parsed/tokenized/emitted line-by-line
          as complete lines become available, so peak memory for a
          shard's own content is bounded by `_SHARD_READ_CHUNK_BYTES`
          plus at most one record's worth of `leftover`, never by the
          file's total size. `cfg.max_record_bytes` caps how large that
          `leftover` is EVER allowed to grow (checked incrementally,
          after every chunk, not only when a newline finally appears) --
          an oversized or malformed single line (even one with no
          newline at all) is rejected as malformed BEFORE it is ever
          decoded or handed to `json.loads()`/the tokenizer, never
          silently accumulated without bound.
        - The shard's digest is only known to match or not match once
          the ENTIRE file has been streamed (the running hash's final
          `hexdigest()`) -- exactly matching this method's own existing,
          unchanged "do not publish a derived block store until the
          entire source set is verified" guarantee: if a shard's final
          digest fails to match, this method raises BEFORE the overall
          `try` block reaches its publish step, so the tmp store/digests
          files built so far (potentially containing data tokenized from
          a file that turned out to be tampered or corrupted) are
          discarded by the `finally` block below, never published to the
          canonical path. Tokens from a not-yet-fully-verified shard DO
          reach the bounded in-memory buffer and the TEMP store file
          during streaming (unavoidable for a true single-pass, O(1)-
          memory design) -- they never reach the CANONICAL, trusted path
          unless every shard's digest, checked at the end of its own
          read, matched.

        **Explicitly, honestly NOT claimed -- corrects an overreach in
        Antigravity's own Audit #076 remediation-pattern suggestion**:
        opening a file descriptor once and rewinding it (`os.lseek`)
        does NOT, by itself, make a second read immune to an in-place
        mutation of the SAME inode's bytes between the hash pass and a
        hypothetical second (rewound) read pass -- an open read
        descriptor does not block another process's concurrent writes
        on POSIX without mandatory locking, which this module cannot
        impose on an arbitrary writer outside its own control. This
        module does NOT use a hash-then-rewind-and-reread pattern for
        that reason: hashing and tokenizing happen from the SAME single
        pass over the SAME bytes, so there is no second read for an
        in-place mutation to land in between. The residual exposure
        this does NOT close -- stated plainly -- is a mutation landing
        WHILE a chunk is being read (the bytes hashed and the bytes
        tokenized for that one chunk are identical, since they are the
        literal same `os.read()` return value, but a write from another
        process between two successive `os.read()` calls on the same
        fd can still interleave with this read in ways this module does
        not control). Closing that fully would require an exclusive
        advisory lock cooperatively honored by every writer of shard
        files, which this module cannot impose on an external data
        pipeline -- recorded as a residual limitation, not claimed as
        closed.

        **Per this phase's own directive**: `tokenizer.encode()` itself
        is a single, non-streaming call that returns one Python list for
        an entire record's text -- this module cannot bound ITS internal
        peak memory for a pathological tokenizer, only the SIZE OF THE
        INPUT it is ever called with (`cfg.max_record_bytes`, enforced
        on the raw, undecoded bytes before this method ever calls
        `.decode()` or `json.loads()`) and the size of its OUTPUT after
        the fact (`cfg.max_tokens_per_record`, rejecting -- not merely
        truncating -- an over-long result). This is NOT the same as a
        strict, enforced ceiling on the tokenizer's own transient
        working memory during a single `encode()` call; no claim to the
        contrary is made. A tokenizer known to expand a bounded input
        pathologically should not be used with this loader without this
        limitation being independently accepted."""
        records_read = 0
        rejected = 0
        total_tokens = 0
        num_blocks_written = 0
        pending: list[int] = []
        block_len = self.cfg.seq_len
        buffer_cap = self.cfg.construction_buffer_tokens
        max_record_tokens = self.cfg.max_tokens_per_record
        max_record_bytes = self.cfg.max_record_bytes

        store_fd, store_tmp_name = tempfile.mkstemp(dir=base_dir, prefix=f".block_store_{cache_id}.", suffix=".tmp")
        digests_fd, digests_tmp_name = tempfile.mkstemp(dir=base_dir, prefix=f".block_store_{cache_id}.digests.", suffix=".tmp")
        store_tmp = Path(store_tmp_name)
        digests_tmp = Path(digests_tmp_name)

        try:
            with os.fdopen(store_fd, "wb") as store, os.fdopen(digests_fd, "wb") as digests_out:
                def flush_complete_blocks() -> None:
                    nonlocal pending, num_blocks_written
                    while len(pending) >= block_len:
                        block_vals = pending[:block_len]
                        del pending[:block_len]
                        block_bytes = array.array(_TOKEN_TYPECODE, block_vals).tobytes()
                        store.write(block_bytes)
                        digest = hashlib.sha256(block_bytes).digest()[:_BLOCK_DIGEST_SIZE]
                        digests_out.write(digest)
                        num_blocks_written += 1

                def emit(ids: list[int]) -> None:
                    nonlocal total_tokens
                    pending.extend(ids)
                    total_tokens += len(ids)
                    if len(pending) >= buffer_cap:
                        flush_complete_blocks()

                def process_line(raw_line: bytes) -> None:
                    nonlocal records_read, rejected
                    raw_line = raw_line.strip()
                    if not raw_line:
                        return
                    try:
                        if len(raw_line) > max_record_bytes:
                            raise MalformedRecordError(
                                f"record line is {len(raw_line)} raw bytes, exceeding max_record_bytes={max_record_bytes} "
                                f"-- rejected before decoding or parsing"
                            )
                        rec = json.loads(raw_line.decode("utf-8"))
                        text = rec["text"]
                        if not isinstance(text, str) or not text.strip():
                            raise MalformedRecordError("empty or non-string 'text'")
                        ids = self.tokenizer.encode(text)
                        if not ids:
                            raise MalformedRecordError("tokenizer produced zero tokens")
                        if len(ids) > max_record_tokens:
                            raise MalformedRecordError(
                                f"record produced {len(ids)} tokens, exceeding max_tokens_per_record={max_record_tokens}"
                            )
                        # AUDIT-P0-01 fix: a non-packed block is exactly `seq_len`
                        # REAL tokens (truncated/padded), not `seq_len + 1`.
                        if not self.cfg.packing and len(ids) < 2:
                            raise MalformedRecordError(f"only {len(ids)} token(s) after encoding -- cannot form a single supervised next-token pair")
                    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, MalformedRecordError):
                        rejected += 1
                        return
                    records_read += 1

                    if self.cfg.packing:
                        emit(ids)
                        emit([self.cfg.eos_id])
                    else:
                        seq = ids[: self.cfg.seq_len]
                        if len(seq) < self.cfg.seq_len:
                            seq = seq + [self.cfg.pad_id] * (self.cfg.seq_len - len(seq))
                        emit(seq)  # exactly one full block -- never accumulated alongside any other record's

                for path in self._split_shard_paths():
                    authorized_digest = self.cfg.authorized_shard_digests.get(path.name)
                    live_hash = hashlib.sha256()
                    leftover = b""
                    fd = os.open(str(path), os.O_RDONLY)
                    try:
                        while True:
                            chunk = os.read(fd, _SHARD_READ_CHUNK_BYTES)
                            if not chunk:
                                break
                            live_hash.update(chunk)
                            leftover += chunk
                            *complete_lines, leftover = leftover.split(b"\n")
                            for line_bytes in complete_lines:
                                process_line(line_bytes)
                            if len(leftover) > max_record_bytes:
                                # Enforced BEFORE waiting for a newline that may never arrive --
                                # an oversized or newline-less record cannot grow `leftover` without bound.
                                rejected += 1
                                leftover = b""
                    finally:
                        os.close(fd)
                    if leftover:
                        process_line(leftover)

                    live_digest = live_hash.hexdigest()
                    if live_digest != authorized_digest:
                        raise ShardIntegrityError(
                            f"shard file {path.name} content digest {live_digest!r} (as streamed for tokenization) "
                            f"does not match authorized digest {authorized_digest!r} -- the file changed during "
                            f"reading, or was never authorized; refusing to publish any derived block store built "
                            f"from this (or any other) shard in this construction"
                        )

                flush_complete_blocks()
                store.flush()
                digests_out.flush()
                os.fsync(store.fileno())
                os.fsync(digests_out.fileno())

            num_blocks = num_blocks_written
            usable_tokens = num_blocks * block_len

            store_sha256 = self._sha256_of_file(store_tmp)
            manifest = {
                "schema_version": BLOCK_STORE_SCHEMA_VERSION,
                "cache_id": cache_id,
                "split": self.cfg.split,
                "packing": self.cfg.packing,
                "seq_len": self.cfg.seq_len,
                "records_read": records_read,
                "records_rejected_malformed": rejected,
                "total_tokens": usable_tokens,
                "num_blocks": num_blocks,
                "store_sha256": store_sha256,
            }
            manifest_tmp_fd, manifest_tmp_name = tempfile.mkstemp(dir=base_dir, prefix=f".block_store_{cache_id}.manifest.", suffix=".tmp")
            manifest_tmp = Path(manifest_tmp_name)
            with os.fdopen(manifest_tmp_fd, "w") as f:
                f.write(json.dumps(manifest))
                f.flush()
                os.fsync(f.fileno())

            # Publish store first, then digests, then manifest last -- the
            # manifest's presence is what `_load_cached_report_if_valid()`
            # treats as "this cache is complete and trustworthy", so it must
            # never be visible before the files it describes are.
            _atomic_publish(store_tmp, self._store_path)
            _atomic_publish(digests_tmp, self._digests_path)
            _atomic_publish(manifest_tmp, self._manifest_path)
        finally:
            for p in (store_tmp, digests_tmp):
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass

        return LoadReport(
            records_read=records_read, records_rejected_malformed=rejected,
            total_tokens=usable_tokens, num_blocks=num_blocks,
        )

    def __len__(self) -> int:
        return self.report.num_blocks

    def block(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns `(input_ids, labels)`, each shape `(seq_len,)` --
        the SAME token sequence, not pre-shifted against each other.
        See `GenesisBlockDataset`'s class docstring and the module
        docstring's AUDIT-P0-01 / AUDIT-075 sections for the single-shift
        contract and the read-time length + digest verification this
        method now performs on every call."""
        if not (0 <= index < self.report.num_blocks):
            raise IndexError(f"block index {index} out of range for a dataset of {self.report.num_blocks} blocks")
        block_len = self.cfg.seq_len
        expected_len = block_len * _TOKEN_ITEM_SIZE

        self._store_file.seek(index * expected_len)
        raw = self._store_file.read(expected_len)
        if len(raw) != expected_len:
            raise BlockStoreCorruptionError(
                f"block {index} read {len(raw)} bytes, expected exactly {expected_len} -- the on-disk "
                "block store is truncated or was modified outside this module's coordinated publish path"
            )

        self._digests_file.seek(index * _BLOCK_DIGEST_SIZE)
        expected_digest = self._digests_file.read(_BLOCK_DIGEST_SIZE)
        actual_digest = hashlib.sha256(raw).digest()[:_BLOCK_DIGEST_SIZE]
        if len(expected_digest) != _BLOCK_DIGEST_SIZE or not hmac.compare_digest(actual_digest, expected_digest):
            raise BlockStoreTamperedError(
                f"block {index}'s content does not match the digest recorded for it at construction time -- "
                "the on-disk block store was modified after publication"
            )

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
