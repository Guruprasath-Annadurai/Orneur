"""
Orca Lens — image generation via self-hosted Flux.1 [schnell].

Model choice: Flux.1 [schnell], not [dev] — [dev]'s license explicitly
prohibits "revenue-generating activity" and "direct interactions with end
users," which is exactly what a paid, user-facing Orca Lens feature is.
[schnell] is Apache 2.0 — fully permissive for commercial use and
commercial fine-tuning. This is a real legal constraint, not a style
preference; do not swap back to [dev] for this reason.

HONEST SCOPE:
  - This module has NOT been run against a live GPU yet — built and
    structurally verified (import shape, function signatures, error
    handling) on a machine with no CUDA available (Apple Silicon Mac).
    Treat the actual generation path as unverified until it's been run for
    real on a CUDA GPU with `pip install -e ".[lens]"` installed.
  - Real VRAM requirement: ~24GB for full precision, ~12-16GB quantized
    (fp8/nf4). This will not run on the same process/GPU allocation as the
    text tiers — needs its own dedicated GPU, same constraint flagged when
    this was first scoped.
  - Content-safety filtering (orca/lens/safety.py) now runs in
    generate_image() before any GPU work — hard-blocks CSAM-adjacent,
    non-consensual real-person imagery, and named copyrighted characters
    (the Seedance/MPA precedent that motivated building this proactively).
    Same honesty caveat as orca/serve/moderation.py: keyword/pattern-based,
    a floor not a ceiling — a real deployment at scale should layer a
    trained image-prompt classifier on top, not rely on this alone.
  - Still missing: an async job queue (generate_image() is synchronous/
    blocking — fine for local testing, not for a real API endpoint serving
    concurrent users) and the actual GPU-hosting decision (RunPod
    Serverless was the leading option, never provisioned).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from orca.config import ORCA_HOME

LENS_OUTPUT_DIR = ORCA_HOME / "lens" / "generated"
LENS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_MODEL_ID = "black-forest-labs/FLUX.1-schnell"

# Module-level cache so the (large) model loads once per process, not once
# per request — reloading a multi-GB diffusion model per image request
# would make latency and GPU memory churn unworkable in production.
_pipeline = None


def _load_pipeline():
    """
    Lazily loads and caches the Flux [schnell] pipeline. Raises a clear
    ImportError if the `lens` optional dependency group isn't installed,
    rather than a confusing deep-stack trace from a missing submodule —
    same pattern as `orca/docs/store.py`'s ChromaDB-missing fallback.
    """
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    try:
        import torch
        from diffusers import FluxPipeline
    except ImportError as e:
        raise ImportError(
            "Image generation requires the 'lens' optional dependency group. "
            "Install with: pip install -e '.[lens]'"
        ) from e

    if not torch.cuda.is_available():
        raise RuntimeError(
            "No CUDA GPU detected. Flux [schnell] needs ~12-24GB VRAM depending "
            "on precision — this cannot run on CPU at usable speed, and will not "
            "run on the same machine as Genesis/Novus/Aeternum's Ollama process "
            "without a dedicated GPU allocation."
        )

    _pipeline = FluxPipeline.from_pretrained(_MODEL_ID, torch_dtype=torch.bfloat16)
    _pipeline.enable_model_cpu_offload()  # reduces peak VRAM at some latency cost
    return _pipeline


class LensPromptBlocked(Exception):
    """Raised when check_image_prompt blocks a prompt — the caller (an API
    endpoint, once one exists) should turn this into a 4xx, not a 500."""
    def __init__(self, matched_pattern: str, flagged_categories: list[str]):
        self.matched_pattern = matched_pattern
        self.flagged_categories = flagged_categories
        super().__init__(f"Prompt blocked by content-safety filter: {flagged_categories}")


def generate_image(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    num_inference_steps: int = 4,  # schnell is distilled for few-step generation — more steps ≠ better here
    seed: Optional[int] = None,
    on_flag: Optional[callable] = None,
) -> Path:
    """
    Generates a single image from a text prompt using Flux [schnell].
    Returns the path to the saved PNG file under
    ~/.orca/lens/generated/.

    Content-safety filtering (orca/lens/safety.py) now runs here, at the
    source — not left to the caller. Raises LensPromptBlocked for hard-block
    categories (CSAM-adjacent, non-consensual real-person imagery, named
    copyrighted characters) before any GPU work happens. FLAG-category
    prompts (e.g. "in the style of [named artist]") are NOT blocked —
    generation proceeds, but `on_flag` (if given) is called with the
    LensModerationResult for governance/audit visibility, same triage-not-
    proof spirit as orca/train/redteam.py's bias flags.
    """
    from orca.lens.safety import check_image_prompt

    moderation = check_image_prompt(prompt)
    if moderation.action == "block":
        raise LensPromptBlocked(moderation.matched_pattern, moderation.flagged_categories)
    if moderation.action == "flag" and on_flag:
        on_flag(moderation)

    import torch  # deferred import — see _load_pipeline for why

    pipe = _load_pipeline()

    generator = torch.Generator("cpu").manual_seed(seed) if seed is not None else None

    result = pipe(
        prompt=prompt,
        width=width,
        height=height,
        num_inference_steps=num_inference_steps,
        generator=generator,
    )
    image = result.images[0]

    import uuid
    filename = f"{uuid.uuid4()}.png"
    out_path = LENS_OUTPUT_DIR / filename
    image.save(out_path)
    return out_path
