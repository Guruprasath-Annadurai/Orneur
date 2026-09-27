"""Owner-side verification that a private vault is outside every git working tree and unreachable from the public repository. Creates nothing,
reads no key material, prints no secret. PASS/FAIL per check; any error is FAIL."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from orca.eval.genesis_v2 import privacy_scan as P


def _git(cwd: Path, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, timeout=30)


def verify_vault_isolation(vault, repo_root) -> dict:
    checks = {}
    try:
        vault_p, repo = Path(vault), Path(repo_root).resolve()
        checks["vault_is_absolute_path"] = vault_p.is_absolute()
        checks["vault_exists_and_is_directory"] = vault_p.is_dir()
        checks["vault_is_not_a_symlink"] = not vault_p.is_symlink()
        real = vault_p.resolve()
        checks["vault_outside_repository_tree"] = not (real == repo or repo in real.parents)
        r = _git(real, "rev-parse", "--is-inside-work-tree") if real.is_dir() else None
        checks["vault_not_inside_any_git_work_tree"] = bool(r is not None and (r.returncode != 0 or r.stdout.strip() != "true"))
        tracked = _git(repo, "ls-files", "-z").stdout.split("\0")
        leak = False
        for rel in [t for t in tracked if t]:
            fp = repo / rel
            if fp.is_symlink():
                tgt = Path(os.path.realpath(fp))
                if tgt == real or real in tgt.parents:
                    leak = True
        checks["no_tracked_symlink_points_into_vault"] = not leak
        checks["no_tracked_or_untracked_enc_artifacts_in_repo"] = not any(t.endswith(".enc") for t in tracked) and not any(
            p.endswith(".enc") for p in _git(repo, "ls-files", "-z", "--others", "--exclude-standard").stdout.split("\0"))
        vs = P.scan_vault_dir(real) if real.is_dir() else {"pass": False}
        checks["vault_permissions_and_no_plaintext_siblings"] = vs["pass"]
    except Exception as e:
        checks["verification_error"] = False
        return {"pass": False, "checks": checks, "error": type(e).__name__}
    return {"pass": all(checks.values()), "checks": checks}
