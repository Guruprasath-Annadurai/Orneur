"""
GENESIS Foundation Sprint 2, Workstream D: model evaluation integration.

Wraps a `GenesisTransformer` + `GenesisTokenizer` pair into the exact
`Callable[[str, SamplingConfig], GenerationResult]` signature
`orca.eval.genesis_harness.Harness` already expects (that harness makes
NO inference itself by design -- its own docstring: "the generation
backend is an injected callable and the default raises
NoInferenceBackend"). This module is the injected callable; it does not
modify the harness.

**The one distinction this entire module exists to make explicit, not
silently blur**: a `GenesisTransformer` constructed with FRESH, RANDOM
initialization (the only kind that exists anywhere in this codebase --
no checkpoint has ever been produced by a real training run, per Wave 1
and Sprint 1's own findings) running through this adapter and through
`Harness` produces a SOFTWARE INTEGRATION TEST RESULT: proof that the
wiring (tokenize -> forward pass -> sample -> detokenize -> harness
scoring -> aggregation) functions correctly end to end. It is NOT a
meaningful capability evaluation -- a random-weight model's output is,
by construction, not meaningfully better than chance at any task the
harness scores, and nothing in this module computes, reports, or implies
a capability score for random weights. `status` (a `ProvenanceStatus`:
`RANDOM_INITIALIZATION` / `UNVERIFIED` / `TRAINED`) is a required, not
optional, field on every result this module's own diagnostic function
returns, specifically so a caller cannot accidentally read a "score"
without also seeing that flag. `TRAINED` is reachable only through a
full, independently-checkable verification chain (content-integrity
checkpoint verification, live model/checkpoint parameter binding, and an
explicit authorized training-run record) -- never from file existence,
a hash alone, or a caller-supplied label.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import torch

from orca.eval.genesis_harness import GenerationResult, SamplingConfig
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.tokenizer.framework import GenesisTokenizer, EOS_ID
from orca.genesis.training.checkpoint_integrity import (
    load_verified_training_state,
    state_dict_fingerprint,
)


class ProvenanceStatus(str, Enum):
    """Audit #017 DEFECT-04 remediation: a tri-state replacement for the
    prior boolean `is_randomly_initialized`. `TRAINED` is reachable ONLY
    through `diagnose_adapter()`'s full verification chain below --
    never from a bare caller-supplied label, a hash alone, or mere file
    existence. Unknown or unverifiable provenance must land on
    `UNVERIFIED` or `RANDOM_INITIALIZATION`, never `TRAINED` -- there is
    no code path in this module that can produce `TRAINED` without an
    explicit, independently-checkable, authorized training-run record."""
    RANDOM_INITIALIZATION = "RANDOM_INITIALIZATION"
    UNVERIFIED = "UNVERIFIED"
    TRAINED = "TRAINED"


class ModelCheckpointBindingError(Exception):
    """Raised when the live model's actual current parameters do not
    match the parameters inside a checkpoint that otherwise passed the
    full content-integrity trust boundary
    (`load_verified_training_state()`). A checkpoint can be perfectly
    valid, unmodified, and correctly hash-verified while still belonging
    to a DIFFERENT model instance than the one a caller is asking about
    -- this is the "swapped model states" / "incorrect model/checkpoint
    binding" failure mode the Audit #017 continuation directive requires
    adversarial coverage for."""


class TrainingRunRecordError(Exception):
    """Raised when a caller attempts to use the retired
    `training_run_record_path` / `TrainingRunRecord` mechanism (removed
    below). Kept as a distinct, importable exception type purely so any
    code still importing it gets an explicit, named failure rather than
    an `ImportError` with no context -- see `_REMOVED_TRAINING_RUN_RECORD_MSG`
    for why the mechanism itself no longer exists."""


_REMOVED_TRAINING_RUN_RECORD_MSG = (
    "TrainingRunRecord / training_run_record_path has been REMOVED, not merely "
    "hardened. Native-Authorization-Convergence Mission 1 (P0): this module's "
    "prior design accepted ANY caller-authored, unsigned JSON file as proof a "
    "checkpoint came from an authorized training run -- reproduced directly: "
    "a file containing only {'run_id': <any string>, "
    "'checkpoint_sha256': <copied from the checkpoint's own, non-secret "
    "manifest>, 'authorized': true} was sufficient to make diagnose_adapter() "
    "return ProvenanceStatus.TRAINED, with no cryptographic signature, no "
    "registered authority, and no founder involvement whatsoever. Unlike "
    "`orca.genesis.governance.authorization.NativePretrainingGrant` (a sealed "
    "dataclass constructible only via a real Ed25519-signature-verified "
    "`authorize_native_pretraining()` call), a bare JSON file carries no "
    "non-forgeable proof of anything -- there is no partial fix that keeps "
    "this parameter and makes it safe. ProvenanceStatus.TRAINED is therefore "
    "UNREACHABLE through this function today: no code anywhere in this "
    "codebase can yet produce a genuine, independently-verifiable attestation "
    "binding a specific completed checkpoint to a specific authorized "
    "training run (that requires a real signed completion-attestation design, "
    "itself gated on Workstream F's authorization chain actually authorizing "
    "a run -- which the current, real, committed founder-acceptance ledger "
    "does not). This is the correct, honest, fail-closed state, not a gap to "
    "silently paper over with new unreviewed crypto under this directive."
)


@dataclass(frozen=True)
class AdapterDiagnostics:
    """Returned alongside (not instead of) harness results, so a caller
    inspecting results has no way to miss whether what they're looking
    at is a meaningful evaluation or a software-integration smoke test.
    `status` is the authoritative field (see `ProvenanceStatus`);
    `checkpoint_source` and `training_run_id` are reporting detail, never
    inputs a caller can use to influence `status` themselves."""
    status: ProvenanceStatus
    checkpoint_source: str  # "none (fresh random init)" or a real checkpoint path, never silently blank
    training_run_id: str | None = None


def _rng_scope(seed: int | None):
    """Audit #017 DEFECT-06 (RNG mutation): generation previously called
    `torch.manual_seed()` directly, permanently mutating the process-wide
    RNG for every caller of this process, not just this one backend call.
    `torch.random.fork_rng()` saves the RNG state on entry and restores it
    on exit, so seeding inside this scope is confined to this call."""
    if seed is None:
        return contextlib.nullcontext()
    return torch.random.fork_rng(devices=[])


def _strip_stop_sequences(text: str, stop: tuple[str, ...]) -> str:
    """Audit #017 DEFECT-06 (stop token retention): standard evaluation
    benchmarks require the stop sequence itself to be excluded from the
    scored completion -- truncate `text` at the earliest occurrence of
    any configured stop string, exactly as a real inference server's
    stop-sequence handling would."""
    cut = len(text)
    for s in stop:
        idx = text.find(s)
        if idx != -1:
            cut = min(cut, idx)
    return text[:cut]


def make_inference_backend(model: GenesisTransformer, tokenizer: GenesisTokenizer, *, device: str = "cpu"):
    """Returns a callable matching `Harness`'s expected
    `Callable[[str, SamplingConfig], GenerationResult]` signature,
    closing over the given model/tokenizer. Performs real autoregressive
    generation via the model's own `generate_step()` (one real forward
    pass per emitted token, exactly as a real inference server would do
    it -- no shortcut or mocked generation path), measuring genuine
    wall-clock timing for `first_token_s`/`end_to_end_s`."""
    model = model.to(device)
    model.eval()

    def _backend(prompt: str, sampling: SamplingConfig) -> GenerationResult:
        t0 = time.monotonic()
        try:
            prompt_ids = tokenizer.encode(prompt)
            if len(prompt_ids) >= model.cfg.max_seq_len:
                # Audit #017 DEFECT-06 (context overflow): previously
                # returned text="", error=None -- indistinguishable from
                # a real, successful empty completion. A prompt that
                # already fills (or exceeds) the model's context window
                # cannot generate even one token and must be reported as
                # a real error, not a silent empty success.
                return GenerationResult(
                    text="", error=f"prompt_tokens={len(prompt_ids)} >= max_seq_len={model.cfg.max_seq_len}: "
                                   f"no room to generate even one token",
                    prompt_tokens=len(prompt_ids), completion_tokens=0,
                )

            with _rng_scope(sampling.seed):
                if sampling.seed is not None:
                    torch.manual_seed(sampling.seed)

                input_ids = torch.tensor([prompt_ids], device=device)
                generated_ids: list[int] = []
                first_token_s = None

                for _ in range(sampling.max_new_tokens):
                    if input_ids.shape[-1] >= model.cfg.max_seq_len:
                        break
                    next_id = model.generate_step(input_ids, temperature=sampling.temperature)
                    token_id = int(next_id.item())
                    if first_token_s is None:
                        first_token_s = time.monotonic() - t0
                    if token_id == EOS_ID:
                        break
                    generated_ids.append(token_id)
                    input_ids = torch.cat([input_ids, next_id.unsqueeze(0)], dim=-1)
                    decoded_so_far = tokenizer.decode(generated_ids)
                    if sampling.stop and any(s in decoded_so_far for s in sampling.stop):
                        break

            text = tokenizer.decode(generated_ids)
            if sampling.stop:
                text = _strip_stop_sequences(text, sampling.stop)
            end_to_end_s = time.monotonic() - t0
            return GenerationResult(
                text=text, first_token_s=first_token_s, end_to_end_s=end_to_end_s,
                prompt_tokens=len(prompt_ids), completion_tokens=len(generated_ids),
            )
        except Exception as e:  # noqa: BLE001 -- reported through the harness's own error field, not swallowed
            return GenerationResult(text="", error=repr(e))

    return _backend


def diagnose_adapter(
    model: GenesisTransformer,
    *,
    checkpoint_path: str | Path | None = None,
    training_run_record_path: str | Path | None = None,
) -> AdapterDiagnostics:
    """Call this alongside (never skip it in place of) any harness run
    built from `make_inference_backend`'s output -- it is the explicit,
    unmissable statement of whether the model behind this adapter is a
    fresh random initialization, or a real checkpoint whose binding to
    `model` cannot be fully authorized.

    Audit #017 continuation directive (Mission 1A): the prior remediation
    (requiring `checkpoint_source` to merely exist on disk) was itself
    independently re-reproduced as still insufficient -- an unrelated
    EXISTING file (e.g. a scratch temp file with unrelated bytes) still
    flipped the status away from random-initialization with zero
    verification that it was ever a real checkpoint, let alone one
    belonging to `model`. This function requires the FULL trusted
    checkpoint identity chain:

      1. `checkpoint_path` must pass `load_verified_training_state()`'s
         complete content-integrity trust boundary (manifest presence,
         format/architecture version, SHA-256 content hash, step/epoch
         self-consistency) -- any failure there propagates out of this
         function UNCHANGED (a forged path, an unrelated existing file,
         a corrupted or tampered checkpoint, an invalid manifest, all
         raise here exactly as they would from a direct
         `load_verified_training_state()` call; this function does not
         swallow or soften any of those).
      2. The live `model`'s ACTUAL current parameters must be
         bit-identical to the parameters inside that verified checkpoint
         (`state_dict_fingerprint()` equality) -- closing the "swapped
         model states" / "incorrect model/checkpoint binding" gap: a
         perfectly valid, correctly hash-verified checkpoint belonging to
         a DIFFERENT model instance must not be accepted as proof about
         THIS `model`. Mismatch raises `ModelCheckpointBindingError`.
      3. Passing steps 1-2 yields `UNVERIFIED` -- the ceiling this
         function can reach today. A checkpoint can be perfectly real,
         content-verified, and correctly bound to `model`'s live
         parameters while still never having come from any authorized
         training run (every checkpoint in this codebase's own test
         suite is exactly this: real tensors, real hash verification,
         zero authorized training behind them).

    Native-Authorization-Convergence Mission 1 (P0) remediation:
    `ProvenanceStatus.TRAINED` was previously reachable via a fourth,
    optional step -- supplying a `training_run_record_path` naming a
    bare, UNSIGNED JSON file with a matching `checkpoint_sha256` and
    `authorized: true`. Independently reproduced directly before this
    fix: `checkpoint_sha256` is not a secret (it is the checkpoint's own
    manifest hash, trivially readable by anyone with filesystem access to
    the checkpoint), so any caller able to write a JSON file could mint
    their own `TRAINED` verdict with zero cryptographic proof and zero
    founder involvement. That entire code path -- `TrainingRunRecord`,
    `_load_training_run_record()`, and this parameter's TRAINED-granting
    behavior -- has been REMOVED, not patched; see
    `_REMOVED_TRAINING_RUN_RECORD_MSG` for why a partial fix (e.g.
    HMAC-sealing the record in-process) would not actually establish
    founder authorization either, and would just move the forgeable
    surface rather than close it. Passing `training_run_record_path` now
    unconditionally raises `TrainingRunRecordError` -- a hard, visible
    failure for any caller still depending on the retired mechanism,
    never a silent downgrade to `UNVERIFIED` (which could mask a caller's
    mistaken assumption that authorization was actually being checked).
    `ProvenanceStatus.TRAINED` remains a defined enum value (for the
    eventual real completion-attestation design, gated on Workstream F's
    authorization chain and explicit founder authorization) but is
    UNREACHABLE through any code path in this function as of this fix."""
    if training_run_record_path is not None:
        raise TrainingRunRecordError(_REMOVED_TRAINING_RUN_RECORD_MSG)

    if checkpoint_path is None:
        return AdapterDiagnostics(status=ProvenanceStatus.RANDOM_INITIALIZATION, checkpoint_source="none (fresh random init)")

    checkpoint_path = Path(checkpoint_path)
    # The full existing content-integrity trust boundary. Any failure
    # (ManifestMissingError, ChecksumMismatchError,
    # UnsupportedManifestVersionError, ManifestStateMismatchError,
    # FileNotFoundError) propagates unchanged -- never caught, softened,
    # or reinterpreted as UNVERIFIED here.
    state = load_verified_training_state(checkpoint_path)

    # Live model/checkpoint binding.
    live_fingerprint = state_dict_fingerprint(model.state_dict())
    checkpoint_fingerprint = state_dict_fingerprint(state.model_state_dict)
    if live_fingerprint != checkpoint_fingerprint:
        raise ModelCheckpointBindingError(
            f"model's live parameters do not match the verified checkpoint at {checkpoint_path} -- "
            f"this checkpoint's content is valid and hash-verified, but it does not belong to the "
            f"model instance passed to diagnose_adapter() (fingerprint mismatch: "
            f"{live_fingerprint[:12]}... != {checkpoint_fingerprint[:12]}...)"
        )

    return AdapterDiagnostics(status=ProvenanceStatus.UNVERIFIED, checkpoint_source=str(checkpoint_path))
