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
a capability score for random weights. `is_randomly_initialized` is a
required, not optional, field on every result this module's own
diagnostic function returns, specifically so a caller cannot accidentally
read a "score" without also seeing that flag.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path

import torch

from orca.eval.genesis_harness import GenerationResult, SamplingConfig
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.tokenizer.framework import GenesisTokenizer, EOS_ID


@dataclass(frozen=True)
class AdapterDiagnostics:
    """Returned alongside (not instead of) harness results by
    `run_one_and_diagnose`, so a caller inspecting results has no way to
    miss whether what they're looking at is a meaningful evaluation or a
    software-integration smoke test."""
    is_randomly_initialized: bool
    checkpoint_source: str  # "none (fresh random init)" or a real checkpoint path, never silently blank


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


def diagnose_adapter(model: GenesisTransformer, *, checkpoint_source: str | None = None) -> AdapterDiagnostics:
    """Call this alongside (never skip it in place of) any harness run
    built from `make_inference_backend`'s output -- it is the explicit,
    unmissable statement of whether the model behind this adapter is a
    fresh random initialization (the only kind that currently exists
    anywhere in this codebase) or a real checkpoint. `checkpoint_source`
    is deliberately required to be stated explicitly by the caller (never
    auto-detected or defaulted) -- this module has no way to know on its
    own whether a model object was loaded from a real, trained checkpoint
    or constructed fresh, and guessing would be exactly the kind of
    "quietly blur the distinction" behavior this module exists to
    prevent.

    Audit #017 DEFECT-04 remediation: previously, ANY caller-supplied
    string -- including a nonexistent, fabricated path -- was enough to
    flip `is_randomly_initialized` to `False`, letting a fresh random
    model be reported as trained with no verification at all. This now
    requires `checkpoint_source` to name a file that actually exists on
    disk, raising `FileNotFoundError` otherwise.

    This remains a BOUNDED fix, not a complete provenance guarantee: a
    real file existing at `checkpoint_source` does not, by itself, prove
    `model`'s weights were actually loaded from that file (that stronger
    binding would require the caller to load through
    `orca.genesis.training.checkpoint_integrity.load_verified_training_state`
    and thread the resulting, hash-verified checkpoint identity through to
    this call -- a larger provenance-binding change out of this bounded
    remediation's scope). What this fix does close is the specific
    reproduced exploit: an arbitrary, non-existent string spoofing trained
    status with zero verification."""
    if checkpoint_source is None:
        return AdapterDiagnostics(is_randomly_initialized=True, checkpoint_source="none (fresh random init)")
    if not Path(checkpoint_source).exists():
        raise FileNotFoundError(
            f"declared checkpoint_source does not exist: {checkpoint_source!r} -- refusing to report "
            f"a model as trained based on a checkpoint path that cannot be found"
        )
    return AdapterDiagnostics(is_randomly_initialized=False, checkpoint_source=checkpoint_source)
