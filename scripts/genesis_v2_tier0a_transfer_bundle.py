#!/usr/bin/env python3
"""Genesis V2 Tier0-A ciphertext-only transfer bundle: builder + validator (STDLIB + store.MAGIC only; no key, no decryption).

Intended use (future, owner-mediated removable encrypted storage): on the Forge machine `seal` a bundle copied from the Vault write path; on the
Witness machine `validate` it BEFORE anything is imported. Nothing here decrypts, reads a key, or touches a corpus: it checks that the bundle
carries ONLY the permitted ciphertext files and metadata, and that nothing was altered in transit.

Bundle layout:  MANIFEST.json  +  <corpus_id>/{SCREEN,QUALIFICATION_HOLDOUT,SEAL}.enc   (nothing else, no symlinks, no extra files)
This reuses the rules of the in-repo courier (infra/tier0-local/roles/courier.py): expected names, magic prefix, write-once, and adds header-metadata
allowlisting + digest manifest checks. It is a transfer-hygiene check, NOT an authenticity proof (authenticity comes from AEAD + the signed
generation receipt downstream).

CLI:  seal <dir> | validate <dir>      (exit 0 = clean; non-zero prints problems, never any file content)
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca.eval.genesis_v2 import store as S  # noqa: E402

CORPUS_ID = re.compile(r"^gce2c-[0-9a-f]{16,64}$")
SPLIT_FILES = {"SCREEN.enc": "SCREEN", "QUALIFICATION_HOLDOUT.enc": "QUALIFICATION_HOLDOUT", "SEAL.enc": "SEAL"}
SPLIT_HEADER_KEYS = {"eval_version", "corpus_id", "split", "split_sha256", "ephemeral_public_key"}
SEAL_HEADER_KEYS = {"eval_version", "corpus_id", "split", "corpus_digest", "ephemeral_public_key"}
MANIFEST = "MANIFEST.json"
MAX_FILE_BYTES = 64 * 1024 * 1024


def _header(blob: bytes) -> dict:
    n = len(S.MAGIC_ASYM)
    (hlen,) = struct.unpack(">I", blob[n:n + 4])
    if hlen <= 0 or hlen > 4096:
        raise ValueError("implausible header length")
    return json.loads(blob[n + 4:n + 4 + hlen])


def _files(bundle: Path) -> dict:
    out = {}
    for cdir in sorted(bundle.iterdir()):
        if cdir.name == MANIFEST:
            continue
        if cdir.is_symlink() or not cdir.is_dir():
            out[cdir.name] = None
            continue
        for f in sorted(cdir.iterdir()):
            out[f"{cdir.name}/{f.name}"] = f
        out.setdefault(cdir.name + "/", cdir)
    return out


def validate(bundle: Path) -> list:
    """Returns a list of problem strings (empty == clean). Never includes file content."""
    bundle = Path(bundle)
    problems = []
    if not bundle.is_dir() or bundle.is_symlink():
        return ["bundle is not a plain directory"]
    mpath = bundle / MANIFEST
    manifest = None
    if mpath.is_symlink() or not mpath.is_file():
        problems.append("MANIFEST.json missing or not a regular file")
    else:
        try:
            manifest = json.loads(mpath.read_text())
            if not isinstance(manifest, dict) or not all(isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for k, v in manifest.items()):
                problems.append("MANIFEST.json must map relative paths to sha256 hex"); manifest = None
        except Exception:
            problems.append("MANIFEST.json unreadable"); manifest = None
    seen = {}
    for cdir in sorted(bundle.iterdir()):
        if cdir.name == MANIFEST:
            continue
        if cdir.is_symlink() or not cdir.is_dir() or not CORPUS_ID.match(cdir.name):
            problems.append(f"unexpected top-level entry {cdir.name[:40]!r}")
            continue
        names = set()
        for f in sorted(cdir.iterdir()):
            rel = f"{cdir.name}/{f.name}"
            if f.is_symlink() or not f.is_file() or f.name not in SPLIT_FILES:
                problems.append(f"unexpected entry {rel[:80]!r}"); continue
            names.add(f.name)
            if f.stat().st_size > MAX_FILE_BYTES or f.stat().st_size < len(S.MAGIC_ASYM) + 4:
                problems.append(f"{rel}: implausible size"); continue
            blob = f.read_bytes()
            if not blob.startswith(S.MAGIC_ASYM):
                problems.append(f"{rel}: not ciphertext (magic prefix missing)"); continue
            try:
                h = _header(blob)
            except Exception:
                problems.append(f"{rel}: malformed header"); continue
            want = SEAL_HEADER_KEYS if f.name == "SEAL.enc" else SPLIT_HEADER_KEYS
            if set(h) != want:
                problems.append(f"{rel}: header metadata outside the allowlist")
            if h.get("corpus_id") != cdir.name or h.get("split") != SPLIT_FILES[f.name]:
                problems.append(f"{rel}: header does not match its path")
            seen[rel] = hashlib.sha256(blob).hexdigest()
        if names != set(SPLIT_FILES):
            problems.append(f"{cdir.name[:24]}: corpus must contain exactly SCREEN, QUALIFICATION_HOLDOUT and SEAL")
    if not seen:
        problems.append("bundle contains no corpus")
    if manifest is not None and manifest != seen:
        problems.append("MANIFEST.json does not match bundle contents (missing, extra, or altered file)")
    return problems


def seal(bundle: Path) -> dict:
    """Writes MANIFEST.json for a bundle that currently validates apart from its manifest. Refuses to seal anything with other problems."""
    bundle = Path(bundle)
    manifest_path = bundle / MANIFEST
    if manifest_path.exists():
        raise FileExistsError("MANIFEST.json already exists (write-once)")
    digests = {}
    for cdir in sorted(p for p in bundle.iterdir() if p.is_dir() and not p.is_symlink()):
        for f in sorted(cdir.iterdir()):
            if f.is_file() and not f.is_symlink():
                digests[f"{cdir.name}/{f.name}"] = hashlib.sha256(f.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(digests, sort_keys=True))
    problems = validate(bundle)
    if problems:
        manifest_path.unlink()
        raise ValueError("refusing to seal: " + "; ".join(problems))
    return digests


def main(argv):
    if len(argv) != 3 or argv[1] not in ("seal", "validate"):
        print(__doc__); return 2
    if argv[1] == "seal":
        print(json.dumps(seal(Path(argv[2])), sort_keys=True)); return 0
    problems = validate(Path(argv[2]))
    for p in problems:
        print("PROBLEM:", p)
    print("CLEAN" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
