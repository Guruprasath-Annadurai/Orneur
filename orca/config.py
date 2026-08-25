import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# .expanduser() is required here — python-dotenv (and any shell config a
# user copies verbatim from .env.example) can set ORCA_HOME to a literal
# unexpanded "~/.orca" string. Path() does NOT expand "~" on its own; only
# .expanduser() does. Without this, ORCA_HOME silently resolves to a
# relative "~/.orca" directory created under whatever the current working
# directory happens to be — a real bug found in this project's own testing,
# not a hypothetical: it silently redirected the auth DB, audit log, memory,
# and every other ORCA_HOME-relative store to the wrong location.
ORCA_HOME = Path(os.environ.get("ORCA_HOME", str(Path.home() / ".orca"))).expanduser()
ORCA_HOME.mkdir(parents=True, exist_ok=True)

MEMORY_DIR = ORCA_HOME / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

CACHE_DIR = ORCA_HOME / "cache"
CACHE_DIR.mkdir(exist_ok=True)

VAULT_DIR = ORCA_HOME / "vault"
VAULT_DIR.mkdir(exist_ok=True)


class OllamaConfig(BaseModel):
    host: str = os.environ.get("ORCA_OLLAMA_HOST", "http://localhost:11434")
    # Priority: your fine-tuned model → best available open model
    model_nano: str = os.environ.get("ORCA_NANO_MODEL", "orca-nano")
    model_core: str = os.environ.get("ORCA_CORE_MODEL", "orca-core")
    model_ultra: str = os.environ.get("ORCA_ULTRA_MODEL", "orca-ultra")
    fallback_models: list[str] = [
        "llama3.1:8b",
        "llama3:8b",
        "mistral:7b",
        "qwen2:7b",
        "gemma2:9b",
    ]


class BackendConfig(BaseModel):
    """
    Per-tier backend routing — see orca/brain/backends.py and
    docs/STARTUP_PLAN.md §2. Each tier independently chooses "ollama"
    (self-hosted, $0 marginal cost, data never leaves this deployment) or
    a frontier API ("openai" / "anthropic") for customers who want frontier
    capability with Orca's governance/audit/compliance layer wrapped
    around it.

    DATA_SOVEREIGNTY_LOCK is the real, code-enforced trust boundary: when
    set, orca/serve/registry.py refuses to construct or route to any
    non-Ollama backend for ANY tier, regardless of what's configured below
    — a deployment can promise "your data never leaves your
    infrastructure" and have that be an enforced fact, not a policy
    document. This is checked in registry.py, not here — this class only
    holds the configuration values.
    """
    backend_nano: str = os.environ.get("ORCA_NANO_BACKEND", "ollama")
    backend_core: str = os.environ.get("ORCA_CORE_BACKEND", "ollama")
    backend_ultra: str = os.environ.get("ORCA_ULTRA_BACKEND", "ollama")

    openai_model_core: str = os.environ.get("ORCA_OPENAI_MODEL_CORE", "gpt-4o")
    openai_model_ultra: str = os.environ.get("ORCA_OPENAI_MODEL_ULTRA", "gpt-4o")
    anthropic_model_core: str = os.environ.get("ORCA_ANTHROPIC_MODEL_CORE", "claude-sonnet-4-6")
    anthropic_model_ultra: str = os.environ.get("ORCA_ANTHROPIC_MODEL_ULTRA", "claude-opus-4-8")

    openai_api_key: str = os.environ.get("ORCA_OPENAI_API_KEY", "")
    anthropic_api_key: str = os.environ.get("ORCA_ANTHROPIC_API_KEY", "")

    # Fail-closed: when true, every tier is forced to "ollama" regardless
    # of backend_nano/core/ultra above. Real deployments serving customers
    # with a strict data-residency requirement set this once and trust it.
    data_sovereignty_lock: bool = os.environ.get("ORCA_DATA_SOVEREIGNTY_LOCK", "false").lower() == "true"

    # Cost-aware escalation (see orca/serve/routing.py) — OFF by default.
    # A tier configured for "ollama" is a promise of near-$0 marginal cost
    # and data staying on this deployment; silently escalating individual
    # queries to a paid frontier API would break that promise. An operator
    # must explicitly opt in and name which frontier backend to escalate
    # to before any per-query routing decision can ever fire.
    cost_aware_escalation_enabled: bool = os.environ.get("ORCA_COST_AWARE_ESCALATION", "false").lower() == "true"
    escalation_backend: str = os.environ.get("ORCA_ESCALATION_BACKEND", "")  # "openai" | "anthropic"

    # Safety valve even when opted in: opting into escalation should not mean
    # opting into an unbounded bill. 0 means "not set" — routing.py treats
    # that as a conservative default cap, not as unlimited, so an operator
    # who enables the flag but forgets to set a cap doesn't get surprised.
    escalation_daily_cap: int = int(os.environ.get("ORCA_ESCALATION_DAILY_CAP", "0") or "0")


class BrainConfig(BaseModel):
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9
    context_length: int = 8192
    stream_by_default: bool = True


class OrcaConfig(BaseModel):
    ollama: OllamaConfig = OllamaConfig()
    brain: BrainConfig = BrainConfig()
    backends: BackendConfig = BackendConfig()

    # Optional: only used for seeding training data, never for inference
    seed_api_key: str = os.environ.get("SEED_API_KEY", "")


CONFIG = OrcaConfig()
