"""Fail-closed public-repository privacy scanner: no private qualification corpus / ground truth / secret seed may be tracked or generated.

Only the exact, hash-pinned V1 exposure recorded in GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json is tolerated (historical, already public).
Any error (git unavailable, unreadable file, oversize file, unknown release mode) is a VIOLATION, never a pass.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from orca.eval.genesis_v2 import spec

STATUS_RECORD = "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json"
RELEASE_MODE = "docs/orneur/phase-21/GENESIS_V2_REPOSITORY_RELEASE_MODE.json"
ATTEST_ENV = "ORNEUR_REPO_ATTESTED_PRIVATE"
MAX_SCAN_BYTES = 64 * 1024 * 1024
GENERATED_DIRS = ("artifacts", "build", "dist", "out", "reports", "eval_private", "data")

PATH_PATTERNS = ("eval_private/*", "*qualification_holdout*", "*private_holdout*", "*private_corpus*", "*screen_private*", "*/holdout.jsonl",
                 "*holdout_answers*", "*ground_truth*.json*", "*.enc", "*genesis_v2_private*", "*corpus_secret*")
TEXT_PATTERNS = {
    "private_holdout_flag": re.compile(r"""["']?private_holdout["']?\s*[:=]\s*(true|True|1)\b"""),
    "secret_generator_seed": re.compile(r"""["']?(secret|master|private|corpus)[_-]?(generator[_-]?)?seed["']?\s*[:=]\s*["']?[0-9a-fA-F]{12,}"""),
    "corpus_secret_assignment": re.compile(r"ORNEUR_GENESIS_V2_(CORPUS_SECRET|ENCRYPTION_KEY|STORE_TOKEN)\s*[=:]\s*[\"']?[A-Za-z0-9+/=_-]{16,}"),
}
STRUCT_SPLITS = frozenset({"SCREEN", "QUALIFICATION_HOLDOUT", "HOLDOUT"})
STRUCT_SECRET_KEYS = frozenset({"secret_seed", "generator_seed", "master_seed", "rng_state", "generation_state", "corpus_secret"})
CONTENT_KEYS = frozenset({"prompt", "ground_truth", "answer", "reference_solution", "sft_target"})


def _git(root: Path, *args) -> list:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace')[:200]}")
    return [p for p in r.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def release_mode(root: Path, env: dict | None = None) -> str:
    """PUBLIC unless the file says PRIVATE *and* the runner attests it out-of-band. Missing/invalid/unknown => PUBLIC (fail closed)."""
    env = os.environ if env is None else env
    try:
        v = json.loads((root / RELEASE_MODE).read_text()).get("repository_visibility")
    except Exception:
        return "PUBLIC"
    return "PRIVATE" if v == "PRIVATE" and env.get(ATTEST_ENV) == "1" else "PUBLIC"


def load_v1_allowlist(root: Path) -> dict:
    d = json.loads((root / STATUS_RECORD).read_text())
    if d.get("GENESIS_CAPABILITY_EVAL_V1_PRIVATE_HOLDOUT_VALID") is not False or d.get("GENESIS_CAPABILITY_EVAL_V1_FROZEN") is not False:
        raise RuntimeError("V1 status record must say V1 is not frozen and its holdout is not private-valid")
    return dict(d["exposed_files_sha256"])


def _struct_findings(data, where: str, out: list) -> None:
    if isinstance(data, dict):
        keys = set(data)
        if keys & STRUCT_SECRET_KEYS:
            out.append((where, "secret_generator_state_key", sorted(keys & STRUCT_SECRET_KEYS)[0]))
        if data.get("private_holdout") is True:
            out.append((where, "private_holdout_flag", "private_holdout flag set"))
        if data.get("split") in STRUCT_SPLITS and keys & CONTENT_KEYS:
            out.append((where, "private_split_content", f"split={data['split']} with {sorted(keys & CONTENT_KEYS)[0]}"))
        for v in data.values():
            _struct_findings(v, where, out)
    elif isinstance(data, list):
        for v in data:
            _struct_findings(v, where, out)


def _scan_bytes(rel: str, blob: bytes) -> list:
    out: list = []
    text = blob.decode("utf-8", "replace")
    for name, rx in TEXT_PATTERNS.items():
        if rx.search(text):
            out.append((rel, name, ""))
    if rel.endswith((".json", ".jsonl")):
        docs = []
        try:
            docs = [json.loads(l) for l in text.splitlines() if l.strip()] if rel.endswith(".jsonl") else [json.loads(text)]
        except Exception:
            out.append((rel, "unparseable_structured_file", ""))   # cannot prove it is clean => violation
        for d in docs:
            _struct_findings(d, rel, out)
    return out


def scan_repository(root: Path, *, env: dict | None = None, mode: str | None = None) -> dict:
    """Returns {'pass': bool, 'mode': ..., 'violations': [...], ...}. Never raises: every failure becomes a violation."""
    root = Path(root).resolve()
    viol: list = []
    scanned = allowed = 0
    try:
        mode = mode or release_mode(root, env)
        if mode != "PUBLIC":
            return {"pass": True, "mode": mode, "violations": [], "scanned": 0, "note": "attested PRIVATE mode: invariant not enforced"}
        allow = load_v1_allowlist(root)
        tracked = _git(root, "ls-files", "-z")
        untracked = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
        ignored = []
        for d in GENERATED_DIRS:
            if (root / d).is_dir():
                ignored += _git(root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", d)
        for rel in sorted(set(tracked) | set(untracked) | set(ignored)):
            p = root / rel
            if not p.is_file():
                continue
            scanned += 1
            try:
                blob = p.read_bytes() if p.stat().st_size <= MAX_SCAN_BYTES else None
            except Exception as e:
                viol.append({"file": rel, "rule": "unreadable", "detail": str(e)[:80]})
                continue
            if blob is None:
                viol.append({"file": rel, "rule": "too_large_to_scan", "detail": ""})
                continue
            if rel in allow:
                if hashlib.sha256(blob).hexdigest() == allow[rel]:
                    allowed += 1
                    continue
                viol.append({"file": rel, "rule": "v1_exposed_file_modified", "detail": "hash differs from the V1 status record"})
                continue
            if any(fnmatch.fnmatch(rel, pat) for pat in PATH_PATTERNS):
                viol.append({"file": rel, "rule": "private_corpus_path", "detail": ""})
            for f, rule, detail in _scan_bytes(rel, blob):
                viol.append({"file": f, "rule": rule, "detail": detail})
    except Exception as e:  # fail closed
        viol.append({"file": "<scanner>", "rule": "scan_error", "detail": f"{type(e).__name__}: {str(e)[:120]}"})
    return {"pass": not viol, "mode": mode or "PUBLIC", "violations": viol, "scanned": scanned, "v1_exposed_allowlisted": allowed}
