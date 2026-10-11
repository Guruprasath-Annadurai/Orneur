import errno
import os
import stat
import warnings
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


def orneur_env(suffix: str, default: str = "") -> str:
    """
    ORCA -> ORNEUR environment variable compatibility resolver (Phase 1,
    stage D of docs/orneur/phase-0/BRAND_MIGRATION_PLAN.md's migration
    order). ORNEUR_<suffix> takes precedence; the legacy ORCA_<suffix> is
    accepted as a deprecated fallback with a one-time warning. Never logs
    the resolved VALUE (only the variable NAME) — several of these vars
    carry secrets (e.g. ORCA_AUTH_SECRET).

    Only ORCA_HOME is wired through this resolver in this phase, as the
    single highest-value case (it determines where every other ORCA_HOME-
    relative store lives). The remaining ~41 ORCA_* vars census'd in
    BRAND_MIGRATION_PLAN.md follow the same pattern at their own call sites
    in a later, deliberately separate migration stage — not silently done
    here in one pass.
    """
    orneur_name = f"ORNEUR_{suffix}"
    orca_name = f"ORCA_{suffix}"
    if orneur_name in os.environ:
        return os.environ[orneur_name]
    if orca_name in os.environ:
        warnings.warn(
            f"{orca_name} is deprecated; set {orneur_name} instead. "
            f"{orca_name} fallback support will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        return os.environ[orca_name]
    return default


class UntrustedStoreDirectory(RuntimeError):
    """A diskcache-backed (or otherwise owner-restricted) directory failed
    the symlink/ownership check in `_mkdir_owner_only` and was refused."""


_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_dir_nofollow(name: str, dir_fd: int, shown: str) -> int:
    try:
        return os.open(name, _DIR_OPEN_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise UntrustedStoreDirectory(
                f"refusing to use {shown}: {name!r} is a symlink or not a "
                "directory at the moment it was opened."
            ) from exc
        raise


def _require_trusted_ancestor(fd: int, shown: str) -> None:
    """An ancestor is trusted only if nobody but root or this user can
    rename, replace or plant entries in it: owned by root/euid and not
    group/other-writable (a root-owned sticky directory such as /tmp is the
    one exception, because sticky stops other users renaming our entries)."""
    st = os.fstat(fd)
    if st.st_uid not in (0, os.geteuid()):
        raise UntrustedStoreDirectory(
            f"refusing to use a path under {shown}: owned by uid {st.st_uid}, "
            f"which is neither root nor this process's uid {os.geteuid()}."
        )
    if st.st_mode & 0o022 and not (st.st_mode & stat.S_ISVTX and st.st_uid == 0):
        raise UntrustedStoreDirectory(
            f"refusing to use a path under {shown}: it is group/other-"
            "writable, so another local account could swap a path component "
            "for a symlink between validation and use. Remove the extra "
            "write bits (chmod go-w) or choose a different location."
        )


def _mkdir_owner_only(path: Path, *, parents: bool = False) -> Path:
    """
    Creates `path` restricted to the owning user (mode 0700) and enforces
    that mode even if the directory already existed with looser permissions
    from a prior release. PYSEC-2026-2447: diskcache.Cache (used under
    CACHE_DIR by orca/brain/memory.py and under QUEUE_DIR by
    orca/lens/queue.py) falls back to pickle for non-JSON-encodable values,
    and pickle deserialization of attacker-controlled bytes is arbitrary
    code execution. diskcache has no upstream fix (5.6.3 is the latest
    PyPI release), so the mitigation is denying write access to anyone but
    the owning user.

    Race-safe by construction (symlink-swap / TOCTOU): nothing here
    re-resolves a path string between a check and its use. The path is
    walked once from "/" with openat(O_NOFOLLOW|O_DIRECTORY), and every
    check (owner, mode) and the final chmod operate on the already-open
    descriptor, never on a name.

    * Every ancestor must be owned by root or this user and not
      group/other-writable (root-owned sticky dirs excepted). A directory
      an attacker cannot write to cannot have a component swapped for a
      symlink, so after this walk succeeds no other non-root account can
      redirect `path`. Symlinks that already exist in the *ancestor* part
      are resolved up front (realpath) and the resolved chain is what gets
      verified, so a symlink planted by an attacker can only point at a
      directory that itself passed the same ownership/mode test. If a
      component is swapped between resolution and the walk, O_NOFOLLOW
      fails and the call fails closed.
    * The leaf is opened with O_NOFOLLOW: a symlink at `path` is refused
      (chmod would otherwise follow it and "harden" the attacker's target).
    * The leaf must be owned by this process's uid: chmod changes mode
      bits, not ownership.
    * Missing directories (including intermediates when parents=True) are
      created with mkdirat mode 0700, not umask-dependent 0755.

    Not covered (cannot be, from here): root, or the same uid, acting
    maliciously; and pre-existing *contents* of a loosely-permissioned
    leaf that another account planted before this release hardened it.
    """
    absolute = os.path.abspath(path)
    leaf = os.path.basename(absolute)
    if not leaf:
        raise UntrustedStoreDirectory(f"refusing to use {path}: no leaf name.")
    parent_parts = [p for p in os.path.realpath(os.path.dirname(absolute)).split(os.sep) if p]

    fd = os.open(os.sep, _DIR_OPEN_FLAGS)
    try:
        _require_trusted_ancestor(fd, os.sep)
        shown = os.sep
        for name in parent_parts:
            shown = os.path.join(shown, name)
            try:
                nfd = _open_dir_nofollow(name, fd, shown)
            except FileNotFoundError:
                if not parents:
                    raise
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                nfd = _open_dir_nofollow(name, fd, shown)
            os.close(fd)
            fd = nfd
            _require_trusted_ancestor(fd, shown)

        try:
            os.mkdir(leaf, 0o700, dir_fd=fd)
        except FileExistsError:
            pass
        lfd = _open_dir_nofollow(leaf, fd, absolute)
    finally:
        os.close(fd)
    try:
        owner_uid = os.fstat(lfd).st_uid
        if owner_uid != os.geteuid():
            raise UntrustedStoreDirectory(
                f"refusing to use {path}: it is owned by uid {owner_uid}, not "
                f"this process's uid {os.geteuid()}. chmod only restricts "
                "mode bits, not ownership, so a directory this process does "
                "not own is never safe to treat as private."
            )
        os.fchmod(lfd, 0o700)
    finally:
        os.close(lfd)
    return path


# .expanduser() is required here — python-dotenv (and any shell config a
# user copies verbatim from .env.example) can set ORCA_HOME to a literal
# unexpanded "~/.orca" string. Path() does NOT expand "~" on its own; only
# .expanduser() does. Without this, ORCA_HOME silently resolves to a
# relative "~/.orca" directory created under whatever the current working
# directory happens to be — a real bug found in this project's own testing,
# not a hypothetical: it silently redirected the auth DB, audit log, memory,
# and every other ORCA_HOME-relative store to the wrong location.
ORCA_HOME = Path(orneur_env("HOME", str(Path.home() / ".orca"))).expanduser()
_mkdir_owner_only(ORCA_HOME, parents=True)

MEMORY_DIR = ORCA_HOME / "memory"
_mkdir_owner_only(MEMORY_DIR)

CACHE_DIR = ORCA_HOME / "cache"
_mkdir_owner_only(CACHE_DIR)

VAULT_DIR = ORCA_HOME / "vault"
_mkdir_owner_only(VAULT_DIR)


class OllamaConfig(BaseModel):
    host: str = orneur_env("OLLAMA_HOST", "http://localhost:11434")
    # Priority: your fine-tuned model → best available open model
    model_nano: str = orneur_env("NANO_MODEL", "orca-nano")
    model_core: str = orneur_env("CORE_MODEL", "orca-core")
    model_ultra: str = orneur_env("ULTRA_MODEL", "orca-ultra")
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
    backend_nano: str = orneur_env("NANO_BACKEND", "ollama")
    backend_core: str = orneur_env("CORE_BACKEND", "ollama")
    backend_ultra: str = orneur_env("ULTRA_BACKEND", "ollama")

    openai_model_core: str = orneur_env("OPENAI_MODEL_CORE", "gpt-4o")
    openai_model_ultra: str = orneur_env("OPENAI_MODEL_ULTRA", "gpt-4o")
    anthropic_model_core: str = orneur_env("ANTHROPIC_MODEL_CORE", "claude-sonnet-4-6")
    anthropic_model_ultra: str = orneur_env("ANTHROPIC_MODEL_ULTRA", "claude-opus-4-8")

    openai_api_key: str = orneur_env("OPENAI_API_KEY", "")
    anthropic_api_key: str = orneur_env("ANTHROPIC_API_KEY", "")

    # Fail-closed: when true, every tier is forced to "ollama" regardless
    # of backend_nano/core/ultra above. Real deployments serving customers
    # with a strict data-residency requirement set this once and trust it.
    data_sovereignty_lock: bool = orneur_env("DATA_SOVEREIGNTY_LOCK", "false").lower() == "true"

    # Cost-aware escalation (see orca/serve/routing.py) — OFF by default.
    # A tier configured for "ollama" is a promise of near-$0 marginal cost
    # and data staying on this deployment; silently escalating individual
    # queries to a paid frontier API would break that promise. An operator
    # must explicitly opt in and name which frontier backend to escalate
    # to before any per-query routing decision can ever fire.
    cost_aware_escalation_enabled: bool = orneur_env("COST_AWARE_ESCALATION", "false").lower() == "true"
    escalation_backend: str = orneur_env("ESCALATION_BACKEND", "")  # "openai" | "anthropic"

    # Safety valve even when opted in: opting into escalation should not mean
    # opting into an unbounded bill. 0 means "not set" — routing.py treats
    # that as a conservative default cap, not as unlimited, so an operator
    # who enables the flag but forgets to set a cap doesn't get surprised.
    escalation_daily_cap: int = int(orneur_env("ESCALATION_DAILY_CAP", "0") or "0")


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
