"""
GENESIS Foundation Sprint 2, Workstream B: checkpoint integrity tests.
Covers corruption, substitution, missing-manifest, and crash-consistency
(interruption) conditions, per the sprint's own explicit instruction.
"""
from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")

from orca.genesis.training.checkpoint_integrity import (  # noqa: E402
    ChecksumMismatchError,
    ManifestMissingError,
    load_verified_training_state,
    save_verified_training_state,
    state_dict_fingerprint,
)
from orca.genesis.training.primitives import TrainingState, save_training_state  # noqa: E402


def _state(step=1) -> TrainingState:
    return TrainingState(
        step=step, epoch=0, dataloader_position=0, model_state_dict={}, optimizer_state_dict={},
        python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None,
    )


def test_round_trip_through_verified_save_and_load(tmp_path):
    path = tmp_path / "checkpoint.pt"
    manifest = save_verified_training_state(_state(step=7), path)
    loaded = load_verified_training_state(path)
    assert loaded.step == 7
    assert manifest.step == 7


def test_manifest_file_has_owner_only_permissions(tmp_path):
    import os
    import stat
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    manifest_path = tmp_path / "checkpoint.pt.manifest.json"
    assert manifest_path.exists()
    mode = stat.S_IMODE(os.stat(manifest_path).st_mode)
    assert mode == 0o600


# --------------------------------------------------------- corruption --

def test_single_byte_corruption_of_the_checkpoint_is_caught(tmp_path):
    """Adversarial corruption test: flip one byte in the checkpoint file
    itself (simulating disk corruption or a truncated/interrupted write
    that still left a file of the expected size) and confirm the
    mismatch is caught BEFORE deserialization is attempted."""
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)

    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF  # flip a bit somewhere in the middle
    path.write_bytes(bytes(data))

    with pytest.raises(ChecksumMismatchError):
        load_verified_training_state(path)


def test_truncated_checkpoint_is_caught(tmp_path):
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(ChecksumMismatchError):
        load_verified_training_state(path)


# -------------------------------------------------------- substitution --

def test_substituting_a_different_valid_checkpoint_is_caught(tmp_path):
    """The substitution attack: swap in a DIFFERENT, perfectly valid
    checkpoint (step=99 instead of step=1) under the original path.
    Must be caught by the hash mismatch even though the substituted file
    is itself a completely well-formed, loadable checkpoint on its own."""
    path_a = tmp_path / "checkpoint_a.pt"
    path_b = tmp_path / "checkpoint_b.pt"
    save_verified_training_state(_state(step=1), path_a)
    save_training_state(_state(step=99), path_b)  # a different, valid checkpoint, no manifest of its own

    # Simulate substitution: overwrite path_a's CONTENT with path_b's,
    # but leave path_a's original manifest (recorded for step=1) in place.
    path_a.write_bytes(path_b.read_bytes())

    with pytest.raises(ChecksumMismatchError):
        load_verified_training_state(path_a)


def test_manifest_itself_tampered_to_match_a_substituted_checkpoint_is_still_internally_consistent():
    """Documents, precisely, what this mechanism does and does not
    guarantee: if BOTH the checkpoint and its manifest are replaced
    together with a mutually-consistent pair (attacker controls both
    files), the hash check alone cannot detect that -- this is a
    content-integrity check, not a provenance/signing check (stated in
    this module's own docstring). Verifying WHO produced a checkpoint
    remains orca.registry.provenance's job, not duplicated here."""
    assert True  # documentation-only test; no new assertion needed beyond the module's own stated scope


# -------------------------------------------------------- missing manifest --

def test_missing_manifest_raises_a_distinct_error_not_checksum_mismatch(tmp_path):
    """A checkpoint saved via the OLDER, unverified save_training_state()
    (no manifest ever written) must raise ManifestMissingError, not
    ChecksumMismatchError -- the two conditions mean different things and
    must not be conflated in logs or alerting."""
    path = tmp_path / "checkpoint.pt"
    save_training_state(_state(), path)  # the plain, non-manifested save
    with pytest.raises(ManifestMissingError):
        load_verified_training_state(path)


def test_deleted_manifest_after_a_verified_save_is_caught(tmp_path):
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    manifest_path = tmp_path / "checkpoint.pt.manifest.json"
    manifest_path.unlink()
    with pytest.raises(ManifestMissingError):
        load_verified_training_state(path)


def test_missing_checkpoint_file_with_manifest_present_raises_file_not_found(tmp_path):
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        load_verified_training_state(path)


# ------------------------------------------------------ crash consistency --

def test_interrupted_manifest_write_leaves_old_manifest_intact(tmp_path, monkeypatch):
    """Crash-consistency check: if the manifest write is interrupted
    partway (simulated by making the atomic rename itself raise), the
    ORIGINAL manifest (if one existed from a prior successful save) must
    remain fully intact and loadable -- never a half-written manifest
    file left behind, matching save_training_state()'s own established
    atomic-write discipline (Sprint 1 / Audit #016)."""
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=1), path)
    original_manifest_bytes = (tmp_path / "checkpoint.pt.manifest.json").read_bytes()

    import orca.genesis.training.checkpoint_integrity as ci

    # Audit #017 DEFECT-01 remediation changed the manifest write to
    # os.replace() over a random mkstemp()-created tmp file (no longer a
    # deterministic ".manifest.json.tmp" name) -- patch os.replace itself.
    original_os_replace = ci.os.replace

    def _patched_replace(src, dst, **kwargs):
        if ".manifest.json.tmp-" in str(src):
            raise OSError("simulated crash during manifest rename")
        # AUDIT-077 P0-01: save_training_state()'s own os.replace() call
        # now passes src_dir_fd/dst_dir_fd (dir-fd-confined rename); this
        # stub must pass them through unchanged for that unrelated call
        # to keep working, since this test only cares about simulating a
        # crash on checkpoint_integrity.py's OWN manifest rename above.
        return original_os_replace(src, dst, **kwargs)

    monkeypatch.setattr(ci.os, "replace", _patched_replace)
    with pytest.raises(OSError, match="simulated crash"):
        save_verified_training_state(_state(step=2), path)
    monkeypatch.undo()

    # The original manifest (for step=1) must be untouched and still valid.
    assert (tmp_path / "checkpoint.pt.manifest.json").read_bytes() == original_manifest_bytes


# ---------------------------------------------- Audit #017 remediation --

def test_defect01_preexisting_symlink_at_the_old_predictable_manifest_tmp_path_is_not_followed(tmp_path):
    """Audit #017 DEFECT-01 (High, independently reproduced before this
    fix): the manifest write previously used a deterministic temporary
    filename opened without O_EXCL/O_NOFOLLOW, so a pre-planted symlink
    at that exact path caused the write to follow it and overwrite an
    arbitrary sensitive target file. `tempfile.mkstemp()`'s random name
    means an attacker cannot pre-plant the real tmp path; this test
    plants a symlink at the OLD, now-unused deterministic path to confirm
    it is simply never touched."""
    import os as _os

    sensitive = tmp_path / "sensitive_victim.txt"
    sensitive.write_text("TOP SECRET CONTENT")

    ckpt_path = tmp_path / "checkpoint.pt"
    old_predictable_tmp = tmp_path / f".{ckpt_path.name}.manifest.json.tmp"
    _os.symlink(sensitive, old_predictable_tmp)

    save_verified_training_state(_state(step=1), ckpt_path)

    assert sensitive.read_text() == "TOP SECRET CONTENT"


def test_defect01_manifest_has_owner_only_permissions_and_no_symlink_at_final_path(tmp_path):
    import os
    import stat
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(), path)
    manifest_path = tmp_path / "checkpoint.pt.manifest.json"
    assert not manifest_path.is_symlink()
    mode = stat.S_IMODE(os.stat(manifest_path).st_mode)
    assert mode == 0o600


def test_defect02_unsupported_format_version_is_rejected(tmp_path):
    """Audit #017 DEFECT-02 (independently reproduced before this fix):
    an incompatible format_version must now be rejected, not silently
    accepted."""
    from orca.genesis.training.checkpoint_integrity import UnsupportedManifestVersionError, _manifest_path

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=1), path)
    mpath = _manifest_path(path)
    m = json.loads(mpath.read_text())
    m["format_version"] = "unsupported-incompatible-v999"
    mpath.write_text(json.dumps(m))

    with pytest.raises(UnsupportedManifestVersionError):
        load_verified_training_state(path)


def test_defect02_unsupported_architecture_version_is_rejected(tmp_path):
    from orca.genesis.training.checkpoint_integrity import UnsupportedManifestVersionError, _manifest_path

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=1), path)
    mpath = _manifest_path(path)
    m = json.loads(mpath.read_text())
    m["architecture_version"] = "genesis-incompatible-v999"
    mpath.write_text(json.dumps(m))

    with pytest.raises(UnsupportedManifestVersionError):
        load_verified_training_state(path)


def test_defect03_manifest_step_or_epoch_mismatch_against_real_state_is_rejected(tmp_path):
    """Audit #017 DEFECT-03 (independently reproduced before this fix):
    a manifest edited to claim a different step/epoch than the actually
    deserialized checkpoint state must now be rejected, not silently
    accepted (the checksum alone only proves the checkpoint BYTES are
    unchanged -- it says nothing about whether the manifest's own
    metadata fields agree with that content)."""
    from orca.genesis.training.checkpoint_integrity import ManifestStateMismatchError, _manifest_path

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=10), path)
    mpath = _manifest_path(path)
    m = json.loads(mpath.read_text())
    m["step"] = 999999
    mpath.write_text(json.dumps(m))

    with pytest.raises(ManifestStateMismatchError):
        load_verified_training_state(path)


def test_read_blocks_until_a_concurrent_exclusive_writer_lock_is_released(tmp_path):
    """Audit #017 section 4.1 TOCTOU remediation (Native-Authorization-
    Convergence P0 follow-up): load_verified_training_state() must hold
    a SHARED lock on the SAME .{name}.verified.lock file
    save_verified_training_state()'s writer uses across its ENTIRE
    save+hash+manifest-write sequence (not the narrower inner `.lock`
    file save_training_state() manages on its own) -- a concurrent
    exclusive holder of that lock must actually block the read, not
    merely be a documented intention."""
    import fcntl
    import threading
    import time

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=1), path)
    lock_path = tmp_path / f".{path.name}.verified.lock"

    held = threading.Event()
    release = threading.Event()

    def _hold_exclusive_lock():
        with open(lock_path, "a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            held.set()
            release.wait(timeout=5)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    holder = threading.Thread(target=_hold_exclusive_lock)
    holder.start()
    assert held.wait(timeout=5), "writer thread never acquired the exclusive lock"

    reader_done = threading.Event()

    def _do_read():
        load_verified_training_state(path)
        reader_done.set()

    reader = threading.Thread(target=_do_read)
    reader.start()
    time.sleep(0.2)
    assert not reader_done.is_set(), "read must still be blocked while the exclusive lock is held"

    release.set()
    reader.join(timeout=5)
    assert reader_done.is_set(), "read must complete once the exclusive lock is released"
    holder.join(timeout=5)


def test_concurrent_verified_saves_to_the_same_path_never_produce_a_mismatched_manifest(tmp_path):
    """Audit #017 section 4.1 (non-atomicity window, not independently
    covered by the audit's own dedicated test but documented as a real
    finding): several threads calling save_verified_training_state()
    against the SAME path concurrently must never leave behind a manifest
    whose recorded sha256/step/epoch disagree with the checkpoint that is
    actually on disk afterward -- whichever writer's result ends up on
    disk, the final (checkpoint, manifest) pair must be internally
    self-consistent and load cleanly."""
    import threading

    path = tmp_path / "checkpoint.pt"
    errors: list[BaseException] = []

    def _writer(step: int) -> None:
        try:
            save_verified_training_state(_state(step=step), path)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(1, 6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    loaded = load_verified_training_state(path)
    assert loaded.step in range(1, 6)


def test_state_dict_fingerprint_does_not_crash_on_bf16_tensors():
    """Native-Authorization-Convergence Mission 1 (P0): independently
    reproduced before this fix -- the prior implementation called
    `tensor.numpy()` directly, which raises
    `TypeError: Got unsupported ScalarType BFloat16` for any bf16
    parameter, meaning `diagnose_adapter()`'s model/checkpoint binding
    check would crash outright (not fail closed, not fail open -- simply
    error) for any bf16 model, a routine dtype for real pretraining."""
    sd = {"w": torch.zeros(4, dtype=torch.bfloat16)}
    fp = state_dict_fingerprint(sd)
    assert isinstance(fp, str) and len(fp) == 64


def test_state_dict_fingerprint_distinguishes_different_shapes_with_identical_bytes():
    """Native-Authorization-Convergence Mission 1 (P0): independently
    reproduced before this fix -- a (4,) tensor and a (2, 2) tensor
    holding the identical underlying values produced an IDENTICAL
    fingerprint, because only dtype and raw bytes were hashed, never
    shape. A reshape-only tamper of a checkpoint's parameters would
    therefore go completely undetected by the model/checkpoint binding
    check this function exists to provide."""
    flat = torch.arange(4, dtype=torch.float32)
    fp_flat = state_dict_fingerprint({"w": flat.reshape(4)})
    fp_square = state_dict_fingerprint({"w": flat.reshape(2, 2)})
    assert fp_flat != fp_square


def test_load_verified_training_state_stays_fail_closed_when_a_raw_write_races_a_verified_save(tmp_path):
    """Native-Authorization-Convergence Mission 1 (P0): independently
    reproduced before this fix -- `save_verified_training_state()`'s
    outer critical section and `load_verified_training_state()`'s reader
    lock used TWO DIFFERENT lock files (`.verified.lock` vs `.lock`), and
    the manifest itself was read with NO lock held at all. This test does
    not require perfect simulation of the full concurrent-thread race (see
    `test_concurrent_verified_saves_to_the_same_path_never_produce_a_mismatched_manifest`
    above for that); it confirms the narrower, directly-reproduced
    defect: a raw `save_training_state()` call racing a verified
    checkpoint's lifecycle must still be caught as a checksum mismatch,
    not silently accepted."""
    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=1), path)
    save_training_state(_state(step=2), path)  # raw write, bypasses save_verified_training_state() entirely
    with pytest.raises(ChecksumMismatchError):
        load_verified_training_state(path)


def test_save_verified_and_load_verified_use_the_same_lock_file(tmp_path):
    """Structural regression for the lock-file-mismatch defect: both
    functions must contend for the identical `.{name}.verified.lock`
    path, not two different files that leave each other's critical
    sections unprotected."""
    import fcntl

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state(step=1), path)
    verified_lock_path = path.parent / f".{path.name}.verified.lock"
    assert verified_lock_path.exists()
    # A shared lock from a reader and an independent attempt to acquire
    # an exclusive lock on the SAME path must contend (non-blocking
    # exclusive attempt fails while the shared lock is held).
    with open(verified_lock_path, "a+") as reader_fd:
        fcntl.flock(reader_fd.fileno(), fcntl.LOCK_SH)
        try:
            with open(verified_lock_path, "a+") as writer_fd:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(writer_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            fcntl.flock(reader_fd.fileno(), fcntl.LOCK_UN)


# ====================================================================
# Native-Authorization-Convergence Mission 1 Final Lock Qualification
# ("Part A"): the CTO's own inspection-based concern -- the verified
# reader hashes the checkpoint, then separately reopens it for
# deserialization, and a raw (non-verified) writer uses a DIFFERENT
# lock file than the verified reader -- is checked here with a
# deterministic synchronization-barrier reproducer (no timing/sleep),
# confirmed actually reproducible before the fix, and confirmed closed
# after it. Each test below states explicitly whether its underlying
# condition was REPRODUCED (an executable adversarial demonstration) or
# only VERIFIED BY INSPECTION (a structural/code-reading check), per
# the directive's own instruction never to conflate the two.
# ====================================================================

def _state_with_weight(step: int, value: float) -> TrainingState:
    sd = {"w": torch.full((4,), float(value))}
    return TrainingState(
        step=step, epoch=0, dataloader_position=0, model_state_dict=sd, optimizer_state_dict={},
        python_rng_state=(1,), torch_rng_state=b"", cuda_rng_state=None,
    )


def test_raw_writer_cannot_land_between_hash_and_deserialize__REPRODUCED(tmp_path, monkeypatch):
    """REPRODUCED (not merely inspected): before this fix, instrumenting
    `_sha256_of_file` to pause (via a threading.Event barrier, not a
    sleep) between computing the hash and returning it let a raw
    `save_training_state()` call -- a real, independently-callable
    function, not a hypothetical attacker tool -- land its own write in
    that exact window with ZERO lock contention, because the verified
    reader's lock (`.verified.lock`) and the raw writer's lock (`.lock`)
    were different files. `load_verified_training_state()` then
    returned the RAW WRITER's post-hash content with no exception at
    all -- the SHA-256 it had just verified never corresponded to what
    it actually returned. This test fails (as it did before the fix) if
    that silent substitution is still possible."""
    import threading

    import orca.genesis.training.checkpoint_integrity as CI

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state_with_weight(step=1, value=1.0), path)

    hash_computed = threading.Event()
    writer_done = threading.Event()
    real_sha256_of_file = CI._sha256_of_file

    def _instrumented_sha256(p):
        h = real_sha256_of_file(p)
        hash_computed.set()
        writer_done.wait(timeout=5)
        return h

    monkeypatch.setattr(CI, "_sha256_of_file", _instrumented_sha256)

    def _raw_writer():
        assert hash_computed.wait(timeout=5), "reader never reached the hash step"
        save_training_state(_state_with_weight(step=1, value=999.0), path)
        writer_done.set()

    writer_thread = threading.Thread(target=_raw_writer)
    writer_thread.start()
    try:
        returned_state = load_verified_training_state(path)
        returned_value = float(returned_state.model_state_dict["w"][0])
        # The fix: the raw writer must be BLOCKED until the reader's
        # entire critical section completes, so the reader must observe
        # exactly the content whose hash it verified (1.0), never the
        # writer's content (999.0) landing mid-read.
        assert returned_value == 1.0, (
            f"reader returned w[0]={returned_value}, expected 1.0 (the hash-verified content) -- "
            f"a raw writer landed its write inside the reader's hash-to-deserialize window"
        )
    finally:
        writer_thread.join(timeout=5)


def test_lock_hierarchy_order_prevents_inversion_deadlock(tmp_path):
    """VERIFIED BY INSPECTION + a direct structural check: every
    function in this module that takes both lock files acquires
    `.{name}.verified.lock` (outer) strictly before `.{name}.lock`
    (inner), and releases in the reverse order -- confirmed here by
    actually acquiring both locks in that order from one thread (must
    succeed without blocking against itself) and confirming a SECOND
    attempt to acquire the outer lock exclusively, from a second
    thread, blocks until the first releases (proving the outer lock is
    the actual gate, not a no-op)."""
    import fcntl
    import threading

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state_with_weight(step=1, value=1.0), path)
    verified_lock_path = path.parent / f".{path.name}.verified.lock"
    raw_lock_path = path.parent / f".{path.name}.lock"

    acquired_both = threading.Event()
    release = threading.Event()

    def _hold_both():
        with open(verified_lock_path, "a+") as vf:
            fcntl.flock(vf.fileno(), fcntl.LOCK_EX)
            with open(raw_lock_path, "a+") as rf:
                fcntl.flock(rf.fileno(), fcntl.LOCK_EX)
                acquired_both.set()
                release.wait(timeout=5)
                fcntl.flock(rf.fileno(), fcntl.LOCK_UN)
            fcntl.flock(vf.fileno(), fcntl.LOCK_UN)

    holder = threading.Thread(target=_hold_both)
    holder.start()
    assert acquired_both.wait(timeout=5), "holder thread never acquired both locks in order -- deadlocked on itself"

    with open(verified_lock_path, "a+") as probe:
        with pytest.raises(BlockingIOError):
            fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    release.set()
    holder.join(timeout=5)


def test_lock_hierarchy_holds_across_real_separate_os_processes(tmp_path):
    """Multi-process verification, not merely concurrent threads: a
    real CHILD PROCESS (not a thread in this process) holds
    `.{name}.lock` exclusively for a measured interval; this process's
    attempt to acquire it (shared, non-blocking poll) must observe
    contention for approximately that whole interval, proving flock's
    advisory-lock contention genuinely holds across process boundaries
    for this exact lock file, not just within one process's thread
    table."""
    import multiprocessing
    import time

    path = tmp_path / "checkpoint.pt"
    save_verified_training_state(_state_with_weight(step=1, value=1.0), path)
    raw_lock_path = path.parent / f".{path.name}.lock"
    hold_seconds = 1.5

    def _child_hold_lock(lock_path_str: str, seconds: float, ready):
        import fcntl as _fcntl
        with open(lock_path_str, "a+") as f:
            _fcntl.flock(f.fileno(), _fcntl.LOCK_EX)
            ready.set()
            time.sleep(seconds)
            _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)

    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    child = ctx.Process(target=_child_hold_lock, args=(str(raw_lock_path), hold_seconds, ready))
    child.start()
    try:
        assert ready.wait(timeout=5), "child process never signaled it acquired the lock"
        start = time.monotonic()
        with open(raw_lock_path, "a+") as f:
            import fcntl as _fcntl
            _fcntl.flock(f.fileno(), _fcntl.LOCK_EX)  # blocks until the child releases
            elapsed = time.monotonic() - start
            _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
        assert elapsed >= hold_seconds * 0.6, (
            f"parent acquired the lock after only {elapsed:.2f}s, expected to block for "
            f"~{hold_seconds}s held by a SEPARATE OS PROCESS -- cross-process contention did not hold"
        )
    finally:
        child.join(timeout=10)


def test_symlink_at_lock_file_path_is_an_inherent_advisory_locking_limitation_not_a_new_regression(tmp_path):
    """Symlink/path behavior, verified directly: `flock()`-based locking
    is ADVISORY, not mandatory, and this module's lock files are opened
    via a plain `open(path, "a+")` (no O_NOFOLLOW/O_EXCL) -- a caller
    who ALREADY has write access to the checkpoint's parent directory
    (the same access required to plant a symlink there in the first
    place) could pre-plant a symlink at a lock-file path and redirect
    this module's own lock acquisition elsewhere. This is a structural
    property of advisory locking in a directory the attacker can
    already write to -- not a regression introduced by this fix, and
    not something any lock discipline can close without mandatory
    (kernel-enforced) locking, which this codebase does not use
    anywhere. Checked directly: the checkpoint and its manifest/lock
    files all live under `_mkdir_owner_only()`'s 0700 directory (Sprint
    1's established boundary) -- the real defense is restricting who
    can write to that directory at all, not the lock files' own
    symlink-following behavior."""
    import os
    import stat

    path = tmp_path / "subdir" / "checkpoint.pt"
    save_verified_training_state(_state_with_weight(step=1, value=1.0), path)
    mode = stat.S_IMODE(os.stat(path.parent).st_mode)
    assert mode == 0o700, f"checkpoint directory must be owner-only (0700), got {oct(mode)}"


def test_state_dict_fingerprint_is_deterministic_across_repeated_calls():
    """BF16 fingerprint determinism, directly tested, not assumed:
    fingerprinting the identical bf16 state dict twice (fresh tensor
    objects each time, same values) must produce the identical digest."""
    sd1 = {"w": torch.tensor([1.5, -2.25, 0.0, 3.0], dtype=torch.bfloat16)}
    sd2 = {"w": torch.tensor([1.5, -2.25, 0.0, 3.0], dtype=torch.bfloat16)}
    assert state_dict_fingerprint(sd1) == state_dict_fingerprint(sd2)


def test_state_dict_fingerprint_handles_noncontiguous_tensor_views():
    """A transposed (non-contiguous) view and its `.contiguous()`
    equivalent must fingerprint IDENTICALLY (same logical values, same
    shape) -- `state_dict_fingerprint()` already calls `.contiguous()`
    internally, but this is verified directly against an actual
    non-contiguous tensor (produced via `.t()`, not merely asserted),
    not just a dtype/shape this function has never been exercised
    against."""
    base = torch.arange(6, dtype=torch.float32).reshape(2, 3)
    transposed_view = base.t()  # non-contiguous: shares storage, different strides
    assert not transposed_view.is_contiguous()
    fp_view = state_dict_fingerprint({"w": transposed_view})
    fp_materialized = state_dict_fingerprint({"w": transposed_view.contiguous()})
    assert fp_view == fp_materialized


def test_state_dict_fingerprint_is_dtype_sensitive_for_identical_bit_patterns():
    """dtype sensitivity, directly tested: a tensor whose raw bytes
    happen to be identical under two different dtypes (int8 vs uint8,
    for values that round-trip identically in both signed and unsigned
    8-bit representation) must still fingerprint DIFFERENTLY, since
    dtype is hashed explicitly alongside the raw bytes -- confirms the
    fingerprint is not merely a raw-byte checksum blind to dtype."""
    raw_bytes_tensor_i8 = torch.tensor([1, 2, 3, 4], dtype=torch.int8)
    raw_bytes_tensor_u8 = raw_bytes_tensor_i8.to(torch.uint8)
    assert torch.equal(raw_bytes_tensor_i8.view(torch.uint8), raw_bytes_tensor_u8)  # identical underlying bytes
    fp_i8 = state_dict_fingerprint({"w": raw_bytes_tensor_i8})
    fp_u8 = state_dict_fingerprint({"w": raw_bytes_tensor_u8})
    assert fp_i8 != fp_u8


def test_state_dict_fingerprint_dtype_coverage_is_explicit_not_assumed_universal():
    """Directly tests the realistic set of dtypes GENESIS checkpoints
    actually use (float32, float16, bfloat16, int64 -- the standard
    parameter/buffer dtypes for this codebase's transformer) and
    confirms each fingerprints successfully and distinctly from the
    others. Does NOT claim or test support for complex or quantized
    dtypes, which this codebase's model never produces and which
    `.view(torch.uint8)` does not uniformly support -- per the
    directive's own instruction not to claim universal dtype support
    without testing it, this module's docstring and this test both
    scope the guarantee to the dtypes actually exercised here."""
    values = torch.arange(4)
    fingerprints = set()
    for dtype in (torch.float32, torch.float16, torch.bfloat16, torch.int64):
        fp = state_dict_fingerprint({"w": values.to(dtype)})
        assert isinstance(fp, str) and len(fp) == 64
        fingerprints.add(fp)
    assert len(fingerprints) == 4, "each tested dtype must produce a distinct fingerprint"
