"""Fail-closed public-repository privacy scanner: no private qualification corpus / ground truth / secret seed may be tracked or generated.

Only the exact, hash-pinned V1 exposure recorded in GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json is tolerated (historical, already public).
Any error (git unavailable, unreadable file, oversize file, unknown release mode) is a VIOLATION, never a pass.
"""
from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

from orca.eval.genesis_v2 import spec

STATUS_RECORD = "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json"
RELEASE_MODE = "docs/orneur/phase-21/GENESIS_V2_REPOSITORY_RELEASE_MODE.json"
ATTEST_ENV = "ORNEUR_REPO_ATTESTED_PRIVATE"
MAX_SCAN_BYTES = 64 * 1024 * 1024
GENERATED_DIRS = ("artifacts", "build", "dist", "out", "reports", "eval_private", "data", "notebooks", "logs", "tmp")
PUBLIC_SFT_CLASSIFICATION = "docs/orneur/phase-21/PUBLIC_SFT_DATASET_CLASSIFICATION.json"
NOTEBOOK_DATA_DIR = "notebooks/data/"
DATA_SUFFIXES = (".jsonl", ".json", ".csv", ".tsv", ".parquet", ".txt", ".ndjson")
MAX_ARCHIVE_DEPTH = 2
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024

PATH_PATTERNS = ("eval_private/*", "*qualification_holdout*", "*private_holdout*", "*private_corpus*", "*screen_private*", "*/holdout.jsonl",
                 "*holdout_answers*", "*ground_truth*.json*", "*.enc", "*genesis_v2_private*", "*corpus_secret*", "notebooks/data/*qualif*", "notebooks/data/*holdout*", "notebooks/data/*screen*",
                 "*gce2c-*")
SECRET_EXPORT_PATTERNS = (".env", ".env.*", "*/.env", "*/.env.*", "*.env", "secrets.*", "*/secrets.*", "*.tfvars", "*.pfx", "*.p12", "*/id_rsa*", "id_rsa*",
                          "*_secrets.json", "*secret_manager_export*", "*.kdbx")
SECRET_EXPORT_ALLOWED = (".env.example", ".env.sample", ".env.template")
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tgz", ".tar.gz", ".gz", ".bz2", ".tar.bz2", ".xz", ".tar.xz")
UNSCANNABLE_ARCHIVE_SUFFIXES = (".7z", ".rar", ".zst", ".lz4", ".cab", ".jar.enc")
TEXT_PATTERNS = {
    "private_holdout_flag": re.compile(r"""["']?private_holdout["']?\s*[:=]\s*(true|True|1)\b"""),
    "secret_generator_seed": re.compile(r"""["']?(secret|master|private|corpus)[_-]?(generator[_-]?)?seed["']?\s*[:=]\s*["']?[0-9a-fA-F]{12,}"""),
    "aes_key_assignment": re.compile(r"""["']?(encryption|aes|corpus|store)[_-]?key["']?\s*[:=]\s*["']?[0-9a-fA-F]{64}\b"""),
    "corpus_secret_assignment": re.compile(r"ORNEUR_GENESIS_V2_(CORPUS_SECRET|ENCRYPTION_KEY|STORE_TOKEN)\s*[=:]\s*[\"']?[A-Za-z0-9+/=_-]{16,}"),
}
STRUCT_SPLITS = frozenset({"SCREEN", "QUALIFICATION_HOLDOUT", "HOLDOUT"})
STRUCT_SECRET_KEYS = frozenset({"secret_seed", "generator_seed", "master_seed", "rng_state", "generation_state", "corpus_secret"})
# answers/reference solutions hidden under alternate field names are caught the same way
CONTENT_KEYS = frozenset({"prompt", "ground_truth", "answer", "answers", "reference_solution", "sft_target", "solution", "reference", "reference_answer",
                          "gold", "gold_answer", "correct_answer", "expected", "expected_output", "expected_answer", "answer_key", "scoring_key",
                          "rubric", "truth", "target", "completion", "canonical_solution", "test_cases", "hidden_tests"})
V2_ID_PREFIX = "gce2-"


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
        ident = data.get("item_id", data.get("id"))
        if isinstance(ident, str) and ident.startswith(V2_ID_PREFIX) and keys & CONTENT_KEYS:
            out.append((where, "v2_private_item_content", f"gce2 item carrying {sorted(keys & CONTENT_KEYS)[0]}"))
        if data.get("split") in STRUCT_SPLITS and keys & CONTENT_KEYS:
            out.append((where, "private_split_content", f"split={data['split']} with {sorted(keys & CONTENT_KEYS)[0]}"))
        for v in data.values():
            _struct_findings(v, where, out)
    elif isinstance(data, list):
        for v in data:
            _struct_findings(v, where, out)


_B64 = re.compile(rb"[A-Za-z0-9+/]{80,}={0,2}")


def _manifest_findings(rel: str, doc, out: list) -> None:
    """A V2 manifest-shaped document must satisfy the public-manifest whitelist (no content-bearing values)."""
    if isinstance(doc, dict) and doc.get("eval_version") == spec.EVAL_VERSION and ("splits" in doc or "items" in doc):
        from orca.eval.genesis_v2 import manifest as M
        try:
            M.validate_public_manifest(doc)
        except Exception as e:
            out.append((rel, "private_manifest_content", str(e)[:80]))


def _archive_members(rel: str, blob: bytes, depth: int):
    """Yield (name, bytes) for archive members; raises ValueError for anything that cannot be fully inspected."""
    low = rel.lower()
    if depth > MAX_ARCHIVE_DEPTH:
        raise ValueError("archive nested too deeply")
    if low.endswith(".zip") or zipfile.is_zipfile(io.BytesIO(blob)):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for i in z.infolist():
                if i.is_dir():
                    continue
                if i.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValueError("archive member too large")
                yield i.filename, z.read(i)
        return
    if low.endswith((".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz")) or tarfile.is_tarfile(io.BytesIO(blob)):
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as t:
            for m in t.getmembers():
                if not m.isfile():
                    continue
                if m.size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValueError("archive member too large")
                yield m.name, t.extractfile(m).read()
        return
    import bz2
    import gzip
    import lzma
    for suf, opener in ((".gz", gzip.decompress), (".bz2", bz2.decompress), (".xz", lzma.decompress)):
        if low.endswith(suf):
            data = opener(blob)
            if len(data) > MAX_ARCHIVE_MEMBER_BYTES:
                raise ValueError("decompressed member too large")
            yield rel[:-len(suf)] or "member", data
            return
    raise ValueError("unrecognized archive format")


def _scan_bytes(rel: str, blob: bytes, depth: int = 0) -> list:
    out: list = []
    low = rel.lower()
    if low.endswith(UNSCANNABLE_ARCHIVE_SUFFIXES):
        return [(rel, "unscannable_archive", "format cannot be inspected")]
    if low.endswith(ARCHIVE_SUFFIXES) or (depth and zipfile.is_zipfile(io.BytesIO(blob))):
        try:
            for name, data in _archive_members(rel, blob, depth):
                for f, rule, detail in _scan_bytes(f"{rel}!{name}", data, depth + 1):
                    out.append((f, rule, detail))
        except Exception as e:
            out.append((rel, "unscannable_archive", f"{type(e).__name__}: {str(e)[:60]}"))
        return out
    text = blob.decode("utf-8", "replace")
    for name, rx in TEXT_PATTERNS.items():
        if rx.search(text):
            out.append((rel, name, ""))
    docs = []
    if low.endswith((".json", ".jsonl", ".ndjson")) or depth:
        try:
            docs = [json.loads(l) for l in text.splitlines() if l.strip()] if low.endswith((".jsonl", ".ndjson")) else [json.loads(text)]
        except Exception:
            if low.endswith((".json", ".jsonl", ".ndjson")):
                out.append((rel, "unparseable_structured_file", ""))   # cannot prove it is clean => violation
            else:                                                       # embedded/decoded blob: best-effort line-wise JSON
                for l in text.splitlines():
                    try:
                        docs.append(json.loads(l))
                    except Exception:
                        pass
    for d in docs:
        _struct_findings(d, rel, out)
        _manifest_findings(rel, d, out)
    if depth < 1 and len(blob) <= 8 * 1024 * 1024:   # base64-embedded corpora / config dumps (one level)
        for m in list(_B64.finditer(blob))[:200]:
            try:
                dec = base64.b64decode(m.group(0), validate=False)
            except (binascii.Error, ValueError):
                continue
            for f, rule, detail in _scan_bytes(rel + "#base64", dec, depth + 1) if len(dec) >= 40 else []:
                if rule not in ("unparseable_structured_file", "unscannable_archive"):
                    out.append((rel, f"base64_embedded_{rule}", detail))
    return out


def load_public_sft_classification(root: Path) -> dict:
    d = json.loads((root / PUBLIC_SFT_CLASSIFICATION).read_text())
    for rel, e in d["files"].items():
        if e.get("classification") != "PUBLIC_SFT" or e.get("may_be_qualification_evidence") is not False or e.get("is_genesis_capability_eval_v2") is not False:
            raise RuntimeError(f"{rel}: public SFT classification must deny qualification/V2 status")
    return {rel: e["sha256"] for rel, e in d["files"].items()}


def scan_vault_dir(path: Path) -> dict:
    """Owner-side check of an encrypted-artifact directory: only ciphertext, no plaintext siblings/temp plaintext, restrictive permissions."""
    path = Path(path)
    viol = []
    try:
        for d in [path, *[p for p in path.rglob("*") if p.is_dir()]]:
            if stat.S_IMODE(d.stat().st_mode) & 0o077:
                viol.append({"file": str(d.name), "rule": "vault_dir_permissions", "detail": oct(stat.S_IMODE(d.stat().st_mode))})
        for f in [p for p in path.rglob("*") if p.is_file()]:
            mode = stat.S_IMODE(f.stat().st_mode)
            if mode & 0o177:
                viol.append({"file": f.name, "rule": "vault_file_permissions", "detail": oct(mode)})
            if not f.name.endswith(".enc") and not f.name.startswith(".tmp-"):
                viol.append({"file": f.name, "rule": "plaintext_beside_encrypted", "detail": ""})
            elif f.name.startswith(".tmp-"):
                viol.append({"file": f.name, "rule": "stray_temp_file", "detail": "interrupted write; never readable as data"})
    except Exception as e:
        viol.append({"file": "<scanner>", "rule": "scan_error", "detail": f"{type(e).__name__}"})
    return {"pass": not viol, "violations": viol}


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
        sft = load_public_sft_classification(root)
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
            base = rel.rsplit("/", 1)[-1]
            if base not in SECRET_EXPORT_ALLOWED and any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(base, pat) for pat in SECRET_EXPORT_PATTERNS):
                viol.append({"file": rel, "rule": "secret_export_file", "detail": ""})
            if rel.startswith(NOTEBOOK_DATA_DIR) and rel.lower().endswith(DATA_SUFFIXES):
                if rel not in sft:
                    viol.append({"file": rel, "rule": "unclassified_notebook_data", "detail": "not listed as PUBLIC_SFT in the classification manifest"})
                elif hashlib.sha256(blob).hexdigest() != sft[rel]:
                    viol.append({"file": rel, "rule": "public_sft_dataset_modified", "detail": "hash differs from the classification manifest"})
            for f, rule, detail in _scan_bytes(rel, blob):
                viol.append({"file": f, "rule": rule, "detail": detail})
        for d in {rel.rsplit("/", 1)[0] for rel in set(tracked) | set(untracked) | set(ignored) if rel.endswith(".enc") and "/" in rel}:
            for rel in set(tracked) | set(untracked) | set(ignored):
                if rel.startswith(d + "/") and rel.lower().endswith((".json", ".jsonl", ".txt", ".csv")):
                    viol.append({"file": rel, "rule": "plaintext_beside_encrypted", "detail": ""})
    except Exception as e:  # fail closed
        viol.append({"file": "<scanner>", "rule": "scan_error", "detail": f"{type(e).__name__}: {str(e)[:120]}"})
    return {"pass": not viol, "mode": mode or "PUBLIC", "violations": viol, "scanned": scanned, "v1_exposed_allowlisted": allowed}
