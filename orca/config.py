import errno
import os
import secrets
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


_DIRFD_SUPPORTED = (
    hasattr(os, "geteuid") and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
    and {os.open, os.mkdir, os.stat, os.readlink} <= os.supports_dir_fd
)
_DIR_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
# Ancestors are only traversed, identified (fstat) and used as an openat base -- never read or chmod'ed -- so where the platform has
# O_PATH (Linux) they are opened with it. That needs only execute permission on the directory, so an execute-only (0711) ancestor owned
# by another user no longer makes startup fail with PermissionError. Elsewhere (macOS) the previous O_RDONLY behaviour is kept. The
# leaf keeps O_RDONLY because it is fchmod'ed.
_ANCESTOR_OPEN_FLAGS = (getattr(os, "O_PATH", os.O_RDONLY)) | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_dir_nofollow(name: str, dir_fd: int, shown: str, flags: int = _DIR_OPEN_FLAGS) -> int:
    try:
        return os.open(name, flags, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise UntrustedStoreDirectory(
                f"refusing to use {shown}: {name!r} is a symlink or not a "
                "directory at the moment it was opened."
            ) from exc
        raise


def _require_trusted_ancestor(fd: int, shown: str, sealed: bool) -> bool:
    """Verify one directory on the walk; return True if the subtree below it
    is sealed off from other accounts.

    Owner must be root or this user. Unless an ancestor already sealed the
    subtree, the directory must also not be group/other-writable (a
    root-owned sticky directory such as /tmp is the one exception, because
    sticky stops other users renaming entries they do not own). A directory
    with no group/other permission bits at all (mode & 077 == 0, owned by
    root/us) cannot be traversed by another account, so nothing below it can
    be swapped by one: deeper group/other-writable bits (e.g. a leftover
    0775 from `umask 002`) are then harmless and are not rejected."""
    st = os.fstat(fd)
    if st.st_uid not in (0, os.geteuid()):
        raise UntrustedStoreDirectory(
            f"refusing to use a path under {shown}: owned by uid {st.st_uid}, "
            f"which is neither root nor this process's uid {os.geteuid()}."
        )
    if not sealed and st.st_mode & 0o022 and not (st.st_mode & stat.S_ISVTX and st.st_uid == 0):
        raise UntrustedStoreDirectory(
            f"refusing to use a path under {shown}: it is group/other-"
            "writable, so another local account could swap a path component "
            "for a symlink between validation and use. Remove the extra "
            "write bits (chmod go-w) or choose a different location."
        )
    return sealed or (st.st_mode & 0o077) == 0


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

    Returns the CANONICAL path -- the exact chain of directories this call
    verified, containing no symlink -- and callers must open stores through
    the returned value, not the argument. (An ancestor symlink owned by
    root/us is followed during the walk; it is not part of what is returned.)

    Contract / invariant: for the returned path P, every component of P was
    opened with openat(O_NOFOLLOW|O_DIRECTORY) from "/" and is owned by root
    or this user; and either no other non-root account can write to (or
    rename within) any of those directories, or the subtree is sealed
    (a 0700 directory owned by root/us, which other accounts cannot
    traverse). Therefore no other non-root account can make P resolve
    anywhere else after this function returns.

    Platform/filesystem assumptions (anything else fails closed or is
    unsupported): POSIX with openat/mkdirat/fstatat/O_NOFOLLOW/O_DIRECTORY
    (Linux, macOS) on a local filesystem with ordinary Unix owner/mode
    semantics. Not covered: Windows; network/FUSE filesystems that fake
    ownership or mode (NFS with root squash, some bind mounts); POSIX
    ACLs or capabilities that grant other accounts access the mode bits do
    not show; and an adversary that is root or the same uid.

    Race-safe by construction (symlink-swap / TOCTOU): nothing here
    re-resolves a path string between a check and its use. The path is
    walked once from "/" with openat(O_NOFOLLOW|O_DIRECTORY); every check
    (owner, mode) and the final chmod operate on the already-open
    descriptor.

    * Every directory on the walk must be owned by root or this user and
      not group/other-writable (root-owned sticky dirs like /tmp excepted).
      A directory no other non-root account can write to cannot have a
      component swapped, so once the walk succeeds nobody else can
      redirect `path`.
    * A symlink in an ancestor position is followed ONLY if the symlink
      itself is owned by root or this user (e.g. /tmp -> /private/tmp, or
      the user's own link). Such an entry cannot be created, replaced or
      repointed by another account: its directory is non-writable to them,
      or is sticky, which forbids removing/renaming entries they do not
      own. A symlink owned by anyone else -- the case of an attacker
      planting a link in /tmp that points at a safe-looking target and
      repointing it after validation -- is refused outright, as is a link
      chain deeper than 40. Link targets are walked with the same rules.
    * The leaf is opened with O_NOFOLLOW: a symlink at `path` is always
      refused (chmod would otherwise follow it).
    * The leaf must be owned by this process's uid: chmod changes mode
      bits, not ownership.
    * Missing directories (including intermediates when parents=True) are
      created with mkdirat mode 0700, not umask-dependent 0755.

    Not covered (cannot be, from here): root, or the same uid, acting
    maliciously; and pre-existing *contents* of a loosely-permissioned
    leaf that another account planted before this release hardened it.
    """
    if not _DIRFD_SUPPORTED:
        raise UntrustedStoreDirectory(
            "unsupported platform: descriptor-relative no-follow directory "
            "operations (openat/mkdirat/fstatat, O_NOFOLLOW) are required."
        )
    absolute = os.path.abspath(path)
    leaf = os.path.basename(absolute)
    if not leaf:
        raise UntrustedStoreDirectory(f"refusing to use {path}: no leaf name.")
    pending = [p for p in os.path.dirname(absolute).split(os.sep) if p]
    pending.reverse()  # used as a stack: next component is pending[-1]

    fd = os.open(os.sep, _ANCESTOR_OPEN_FLAGS)
    try:
        sealed = _require_trusted_ancestor(fd, os.sep, False)
        shown = os.sep
        canon: list[str] = []
        links = 0
        while pending:
            name = pending.pop()
            if name == ".":
                continue
            try:
                nfd = os.open(name, _ANCESTOR_OPEN_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not parents:
                    raise
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                nfd = _open_dir_nofollow(name, fd, shown, _ANCESTOR_OPEN_FLAGS)
            except OSError as exc:
                if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
                    raise
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISLNK(st.st_mode):
                    raise UntrustedStoreDirectory(
                        f"refusing to use a path under {shown}: {name!r} is not a directory."
                    ) from exc
                if st.st_uid not in (0, os.geteuid()):
                    raise UntrustedStoreDirectory(
                        f"refusing to use a path under {shown}: {name!r} is a symlink "
                        f"owned by uid {st.st_uid}, so its owner could repoint it "
                        "after validation."
                    ) from exc
                links += 1
                if links > 40:
                    raise UntrustedStoreDirectory(f"refusing to use {path}: too many symlinks.")
                target = os.readlink(name, dir_fd=fd)
                if target.startswith(os.sep):
                    os.close(fd)
                    fd = os.open(os.sep, _ANCESTOR_OPEN_FLAGS)
                    shown = os.sep
                    canon.clear()
                    sealed = _require_trusted_ancestor(fd, os.sep, False)
                pending.extend(reversed([p for p in target.split(os.sep) if p]))
                continue
            os.close(fd)
            fd = nfd
            shown = os.path.join(shown, name)
            if name == "..":
                if canon:
                    canon.pop()
                sealed = _require_trusted_ancestor(fd, shown, False)
            else:
                canon.append(name)
                sealed = _require_trusted_ancestor(fd, shown, sealed)

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
    return Path(os.sep + os.sep.join([*canon, leaf]))


def _open_dir_no_symlinks(path: Path, *, parents: bool = False) -> int:
    """AUDIT-077 P0-01 (intermediate-ancestor TOCTOU escape, found by
    Antigravity's independent requalification): a STRICTER sibling of
    `_mkdir_owner_only()` for a threat model where even a SAME-UID
    symlink substitution must be treated as hostile.

    `_mkdir_owner_only()` deliberately FOLLOWS an ancestor symlink that
    is owned by root or this process's own uid (see its own docstring)
    -- correct for ITS threat model (another, lower-privileged LOCAL
    ACCOUNT reading pickle-backed cache data), but wrong for a confined
    checkpoint workspace: there, the attacker model Antigravity
    demonstrated is a same-uid caller racing the narrow window between
    `_enforce_checkpoint_path_confinement()`'s validation and the
    checkpoint functions' own directory creation, substituting an
    intermediate ancestor directory (e.g. `sub` in `sub/inner/ckpt.pt`)
    for a symlink pointing outside the workspace. Because that symlink
    is owned by the very same uid performing the legitimate save,
    `_mkdir_owner_only()` accepted and followed it -- independently
    reproduced before this fix (see AUDIT-077 P0-01 correction report).

    This function walks every component of `path` from "/" using
    `openat(O_NOFOLLOW|O_DIRECTORY)` exactly like `_mkdir_owner_only()`.
    Unlike that function, a symlink is followed ONLY if it is owned by
    root (uid 0) -- the ordinary system symlinks every POSIX install
    has (e.g. `/var` -> `/private/var`, `/tmp` -> `/private/tmp` on
    macOS), which are not part of this attack's race window and would
    otherwise make this helper unusable on a stock system. A symlink
    owned by THIS PROCESS'S OWN UID -- or any other non-root uid -- is
    rejected unconditionally: that is exactly the loophole
    `_mkdir_owner_only()`'s same-uid exception leaves open, and exactly
    what Antigravity's reproduction exploited (planting a same-uid-
    owned symlink inside the workspace during the race window). Missing
    directories (when `parents=True`) are created via `mkdirat`, mode
    0700.

    Returns an OPEN file descriptor to the final (leaf) directory --
    the caller owns it and must `os.close()` it. Critically, the
    caller must perform EVERY subsequent filesystem operation inside
    that directory (temp-file creation, rename, lock-file open) via
    this `dir_fd` (the `dir_fd=` parameter on the relevant `os.*` call),
    never by re-resolving a fresh path string -- that is what actually
    closes the TOCTOU window a one-time walk cannot close by itself (a
    walk that rejects symlinks still has an inherent, narrow race
    between one `openat()` succeeding and the next syscall; holding the
    fd and never re-resolving a path string afterward removes every
    REMAINING re-resolution point an attacker could target). This
    function is not, and does not claim to be, race-proof against an
    attacker who wins that single-syscall race during the walk itself."""
    if not _DIRFD_SUPPORTED:
        raise UntrustedStoreDirectory(
            "unsupported platform: descriptor-relative no-follow directory "
            "operations (openat/mkdirat, O_NOFOLLOW) are required."
        )
    absolute = os.path.abspath(path)
    pending = [p for p in absolute.split(os.sep) if p]
    pending.reverse()
    fd = os.open(os.sep, _ANCESTOR_OPEN_FLAGS)
    shown = os.sep
    links = 0
    try:
        while pending:
            name = pending.pop()
            try:
                nfd = os.open(name, _ANCESTOR_OPEN_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not parents:
                    raise
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                nfd = _open_dir_nofollow(name, fd, shown, _ANCESTOR_OPEN_FLAGS)
            except OSError as exc:
                if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
                    raise
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISLNK(st.st_mode):
                    raise UntrustedStoreDirectory(
                        f"refusing to use a path under {shown}: {name!r} is not a directory."
                    ) from exc
                if st.st_uid != 0:
                    raise UntrustedStoreDirectory(
                        f"refusing to use a path under {shown}: {name!r} is a symlink owned by "
                        f"uid {st.st_uid}, not root -- rejected unconditionally, since this "
                        "confined workspace's threat model treats a same-uid (or other non-root) "
                        "ancestor symlink substitution between validation and use as hostile, "
                        "even though it would be an ordinary trusted case elsewhere."
                    ) from exc
                links += 1
                if links > 40:
                    raise UntrustedStoreDirectory(f"refusing to use {path}: too many symlinks.")
                target = os.readlink(name, dir_fd=fd)
                if target.startswith(os.sep):
                    os.close(fd)
                    fd = os.open(os.sep, _ANCESTOR_OPEN_FLAGS)
                    shown = os.sep
                pending.extend(reversed([p for p in target.split(os.sep) if p]))
                continue
            os.close(fd)
            fd = nfd
            shown = os.path.join(shown, name)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _dirfd_mkstemp(dir_fd: int, prefix: str) -> tuple[int, str]:
    """`tempfile.mkstemp()`-equivalent relative to an already-open,
    no-follow-verified directory descriptor (from
    `_open_dir_no_symlinks()`) -- `tempfile.mkstemp()` itself has no
    `dir_fd` parameter. Reimplements its `O_EXCL`-based collision
    avoidance (retry with a fresh random suffix on `FileExistsError`)
    using `os.open(..., dir_fd=dir_fd)`, so the file is created
    strictly inside the directory `dir_fd` refers to -- never a freshly
    re-resolved path string that could have been redirected since
    `dir_fd` was opened. Returns (fd, name); the caller owns both the
    fd and cleaning up the name on failure."""
    for _ in range(100):
        name = f"{prefix}{secrets.token_hex(8)}"
        try:
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dir_fd)
            return fd, name
        except FileExistsError:
            continue
    raise UntrustedStoreDirectory(f"could not create a unique temp file under this directory after 100 attempts (prefix={prefix!r})")


# .expanduser() is required here — python-dotenv (and any shell config a
# user copies verbatim from .env.example) can set ORCA_HOME to a literal
# unexpanded "~/.orca" string. Path() does NOT expand "~" on its own; only
# .expanduser() does. Without this, ORCA_HOME silently resolves to a
# relative "~/.orca" directory created under whatever the current working
# directory happens to be — a real bug found in this project's own testing,
# not a hypothetical: it silently redirected the auth DB, audit log, memory,
# and every other ORCA_HOME-relative store to the wrong location.
ORCA_HOME = Path(orneur_env("HOME", str(Path.home() / ".orca"))).expanduser()
ORCA_HOME = _mkdir_owner_only(ORCA_HOME, parents=True)

MEMORY_DIR = _mkdir_owner_only(ORCA_HOME / "memory")

CACHE_DIR = _mkdir_owner_only(ORCA_HOME / "cache")

VAULT_DIR = _mkdir_owner_only(ORCA_HOME / "vault")


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
