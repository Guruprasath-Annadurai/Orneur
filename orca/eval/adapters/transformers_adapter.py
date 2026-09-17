"""
TransformersModelAdapter (Phase 21B.4.1, §5-8) -- the first real
`orca.eval.runner.ModelAdapter` implementation, backed by HuggingFace
`transformers`. Model-family-agnostic: works across any causal-LM
architecture `transformers` supports (Qwen3, Mistral-Nemo, Phi-4/mini,
etc.) via `AutoModelForCausalLM`/`AutoTokenizer`, so Genesis evaluation
is never bound to Qwen-specific implementation details. Each candidate
family's own native chat template is used as-is (never forced into a
common raw-string format) -- see `render_prompt()`'s docstring for why.

Deliberately import-light at module scope (does not import `torch`/
`transformers` until `TransformersModelAdapter.load()` is actually
called) so this module can be imported in CPU-only, no-torch
environments (e.g. for CLI --help) without error.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from orca.eval.runner import GenerationResult

_MUTABLE_REVISION_MARKERS = {"main", "latest", "head", "master", ""}


class AdapterRevisionError(ValueError):
    """A candidate revision is missing or looks like a mutable ref
    ("main"/"latest"/"head") -- refused before any model/tokenizer load
    is attempted, per spec §6: 'Never allow model="...", revision="main"
    for a real baseline.'"""


class AdapterLoadError(RuntimeError):
    """Model or tokenizer loading failed -- captured as a structured
    error rather than propagating a raw transformers/torch traceback to
    the caller."""


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_revision(revision: str, *, field_name: str) -> None:
    if not revision or revision.strip().lower() in _MUTABLE_REVISION_MARKERS:
        raise AdapterRevisionError(
            f"{field_name}={revision!r} is not an exact pinned revision -- refusing to load. "
            "A real baseline requires an immutable commit SHA, never a mutable branch/tag name."
        )


@dataclass(frozen=True)
class TransformersAdapterConfig:
    repo_id: str                       # exact HF repository id, e.g. "unsloth/Qwen3-8B"
    revision: str                      # exact immutable commit SHA -- required, never "main"
    tokenizer_revision: str | None = None  # defaults to `revision` if not given
    device: str = "cpu"                # "cpu" | "cuda" | "cuda:0" | "mps"
    dtype: str = "auto"                # "auto" | "float16" | "bfloat16" | "float32"
    quantization: str = "none"         # "none" | "4bit" | "8bit"
    max_new_tokens: int = 512
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int | None = 42

    def __post_init__(self):
        _validate_revision(self.revision, field_name="revision")
        # tokenizer_revision may be None (defaults to `revision`), but if
        # explicitly given it must ALSO be pinned -- never silently
        # allow a pinned model + an unpinned tokenizer.
        if self.tokenizer_revision is not None:
            _validate_revision(self.tokenizer_revision, field_name="tokenizer_revision")

    @property
    def resolved_tokenizer_revision(self) -> str:
        return self.tokenizer_revision or self.revision


class TransformersModelAdapter:
    """Implements orca.eval.runner.ModelAdapter. Usage:

        adapter = TransformersModelAdapter(config)
        adapter.load()
        try:
            result = adapter.generate(prompt, system_instruction=..., config={...})
        finally:
            adapter.unload()

    `load()`/`unload()` are explicit (never implicit at import time or
    module scope), per spec §10's "do not make real model evaluation
    happen implicitly during import, tests, startup, CI, or ordinary
    application boot."
    """

    def __init__(self, config: TransformersAdapterConfig):
        self._config = config
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self.load_time_ms: float | None = None
        self.resolved_model_revision: str | None = None
        self.resolved_tokenizer_revision: str | None = None
        self.chat_template_digest: str | None = None
        self.library_versions: dict[str, str] = {}

    def load(self) -> None:
        if self._loaded:
            return

        import transformers

        self.library_versions["transformers"] = transformers.__version__
        try:
            import torch

            self.library_versions["torch"] = torch.__version__
        except ImportError:
            pass

        from transformers import AutoModelForCausalLM, AutoTokenizer

        start = time.time()
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._config.repo_id, revision=self._config.resolved_tokenizer_revision,
            )
            load_kwargs: dict = {"revision": self._config.revision}
            if self._config.dtype != "auto":
                import torch

                load_kwargs["torch_dtype"] = getattr(torch, self._config.dtype)
            if self._config.quantization != "none":
                load_kwargs["quantization_config"] = self._build_quantization_config()
            self._model = AutoModelForCausalLM.from_pretrained(self._config.repo_id, **load_kwargs)
            if self._config.device != "auto":
                self._model = self._model.to(self._config.device)
        except Exception as exc:
            raise AdapterLoadError(f"Failed to load {self._config.repo_id}@{self._config.revision}: {exc!r}") from exc

        self.load_time_ms = (time.time() - start) * 1000
        self._loaded = True

        # Best-effort resolved-identity capture -- transformers/huggingface_hub
        # expose the resolved commit hash on the loaded config when available;
        # fall back to the requested revision (still exact, just not
        # independently re-confirmed from the object itself) if not exposed
        # by this transformers version.
        self.resolved_model_revision = getattr(self._model.config, "_commit_hash", None) or self._config.revision
        self.resolved_tokenizer_revision = getattr(self._tokenizer, "_commit_hash", None) or self._config.resolved_tokenizer_revision

        if self._tokenizer.chat_template:
            self.chat_template_digest = f"sha256:{_sha256_of_text(self._tokenizer.chat_template)}"

    def _build_quantization_config(self):
        from transformers import BitsAndBytesConfig

        if self._config.quantization == "4bit":
            return BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4")
        if self._config.quantization == "8bit":
            return BitsAndBytesConfig(load_in_8bit=True)
        raise ValueError(f"Unknown quantization {self._config.quantization!r}")

    def render_prompt(self, prompt: str, *, system_instruction: str) -> str:
        """Uses the candidate's OWN native chat template, never a forced
        common raw-string format (spec §8: 'Do NOT force the same raw
        prompt string into every tokenizer if doing so violates the
        model's expected conversation format... Parity means same
        semantic instruction and task content NOT incorrectly forcing
        identical token serialization.'). Different model families will
        legitimately produce different rendered text for the same
        semantic content -- that's correct, not a parity bug."""
        messages = [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}]
        return self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    def generate(self, prompt: str, *, system_instruction: str, config: dict) -> GenerationResult:
        if not self._loaded:
            return GenerationResult(text=None, latency_ms=0.0, error="adapter not loaded -- call load() first")

        try:
            import torch

            if self._config.seed is not None:
                torch.manual_seed(self._config.seed)

            rendered_prompt = self.render_prompt(prompt, system_instruction=system_instruction)
            inputs = self._tokenizer(rendered_prompt, return_tensors="pt")
            if self._config.device != "auto":
                inputs = {k: v.to(self._config.device) for k, v in inputs.items()}

            temperature = config.get("temperature", self._config.temperature)
            start = time.time()
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=config.get("max_new_tokens", self._config.max_new_tokens),
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else None,
                top_p=config.get("top_p", self._config.top_p) if temperature > 0 else None,
            )
            latency_ms = (time.time() - start) * 1000

            input_len = inputs["input_ids"].shape[1]
            generated_text = self._tokenizer.decode(output_ids[0][input_len:], skip_special_tokens=True)
            return GenerationResult(text=generated_text, latency_ms=latency_ms)
        except Exception as exc:
            return GenerationResult(text=None, latency_ms=0.0, error=f"generation failed: {exc!r}")

    def unload(self) -> None:
        """Explicit, clean release -- never left to GC alone for a
        multi-GB model. Safe to call even if load() was never called or
        already unloaded."""
        self._model = None
        self._tokenizer = None
        self._loaded = False
        try:
            import gc

            gc.collect()
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def __enter__(self) -> "TransformersModelAdapter":
        self.load()
        return self

    def __exit__(self, *exc_info) -> None:
        self.unload()
