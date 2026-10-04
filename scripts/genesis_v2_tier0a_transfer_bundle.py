#!/usr/bin/env python3
"""Genesis V2 ciphertext transfer bundle: builder + validators (used by Tier0-A and Tier0-S).

CLAIM LEVELS (precise -- do not conflate):
  EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED  -- what `validate`/`seal`/`validate_and_stage` establish, WITHOUT any key: only the expected files exist, each starts
      with the encrypted-artifact magic and a well-formed, allowlisted plaintext header that matches its path, sizes are plausible, and a strict manifest
      of SHA-256 digests matches. This is a SHAPE check. A file with a valid magic+header followed by PLAINTEXT passes it (proven by test). It is NOT proof of
      encryption, and entropy is deliberately not used as proof.
  CRYPTOGRAPHICALLY_VERIFIED -- what `cryptographic_verify` establishes on the WITNESS side only, with the ephemeral/real vault PRIVATE key and the expected
      corpus digest: every split and the SEAL decrypt under AES-256-GCM (the authentication tag verifies, so a plaintext payload FAILS) and the split/corpus
      digests match. This is the only keyed, real proof, and it handles key material -- it is a library function, not a CLI command.
Neither level is proof of authenticity of the generator: that comes from the signed generation receipt downstream. Nothing here authorizes anything.

Bundle layout:  MANIFEST.json  +  <corpus_id>/{SCREEN,QUALIFICATION_HOLDOUT,SEAL}.enc   (no other entries, no symlinks, no hardlinks)

HANDOFF / TOCTOU: `validate_and_stage` reads every file exactly once (O_NOFOLLOW, fstat on the open descriptor), validates THOSE bytes, and writes a read-only
staged copy from the same in-memory bytes; import must read only from the staged copy. A writer who controls the staging directory (same host user/root)
can still alter it afterwards -- this narrows the race, it does not defeat a privileged local attacker.

OPERATIONAL NOTE: removable media formatted exFAT/FAT create `._*`/`.DS_Store` entries that this validator rejects (fail closed). Use an encrypted APFS
transfer volume and keep Finder/Spotlight metadata off it, or remove those entries by an owner-reviewed step.

CLI:  seal <dir> | validate <dir> | stage <dir> <staging_parent>   (non-zero exit on any problem; never prints file content)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import sys
import tempfile
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
FORMAT_CLAIM = "EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED"
CRYPTO_CLAIM = "CRYPTOGRAPHICALLY_VERIFIED"


def _strict_manifest(text: str):
    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key")
        return dict(pairs)
    return json.loads(text, object_pairs_hook=hook)


def _header(blob: bytes) -> dict:
    n = len(S.MAGIC_ASYM)
    (hlen,) = struct.unpack(">I", blob[n:n + 4])
    if hlen <= 0 or hlen > 4096:
        raise ValueError("implausible header length")
    h = json.loads(blob[n + 4:n + 4 + hlen])
    if not isinstance(h, dict):
        raise ValueError("header is not an object")
    return h


def _kind_label(mode: int) -> str:
    for label, fn in (("symlink", stat.S_ISLNK), ("directory", stat.S_ISDIR), ("fifo", stat.S_ISFIFO), ("socket", stat.S_ISSOCK),
                      ("block device", stat.S_ISBLK), ("character device", stat.S_ISCHR)):
        if fn(mode):
            return label
    return "special file"


def _read_once(path: Path):
    """lstat BEFORE any open (so a FIFO/socket/device/symlink/directory is rejected without ever blocking), then open with O_NOFOLLOW|O_NONBLOCK, re-check the
    OPEN descriptor (same device/inode as the lstat, regular, single link, bounded size) and read once. Returns (bytes|None, problem|None)."""
    try:
        pre = os.lstat(path)
    except OSError:
        return None, "unreadable"
    if not stat.S_ISREG(pre.st_mode):
        return None, f"not a regular file ({_kind_label(pre.st_mode)})"
    if pre.st_nlink != 1:
        return None, "hard-linked (link count != 1)"
    if pre.st_size > MAX_FILE_BYTES:
        return None, "implausible size"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None, "unreadable, or swapped for a symlink"
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (pre.st_dev, pre.st_ino) or not stat.S_ISREG(st.st_mode):
            return None, "changed between check and open"
        if st.st_nlink != 1:
            return None, "hard-linked (link count != 1)"
        if st.st_size > MAX_FILE_BYTES:
            return None, "implausible size"
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(MAX_FILE_BYTES + 1), None
    finally:
        os.close(fd)


def snapshot(bundle: Path) -> tuple:
    """Single read of the whole bundle. Returns (problems, blobs{rel: bytes}, manifest|None). Never includes file content in problems."""
    bundle = Path(bundle)
    problems, blobs, manifest = [], {}, None
    try:
        if bundle.is_symlink() or not bundle.is_dir():
            return ["bundle is not a plain directory"], blobs, None
        entries = sorted(os.scandir(bundle), key=lambda e: e.name)
    except OSError:
        return ["bundle unreadable"], blobs, None
    for e in entries:
        if e.name == MANIFEST:
            data, why = _read_once(Path(e.path))
            if why:
                problems.append(f"MANIFEST.json {why}")
                continue
            try:
                manifest = _strict_manifest(data.decode())
                if not isinstance(manifest, dict) or not all(isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for k, v in manifest.items()):
                    raise ValueError("shape")
            except Exception:
                problems.append("MANIFEST.json must be strict JSON (no duplicate keys) mapping relative paths to sha256 hex")
                manifest = None
            continue
        if e.is_symlink() or not e.is_dir(follow_symlinks=False) or not CORPUS_ID.match(e.name):
            problems.append(f"unexpected top-level entry {e.name[:40]!r}")
            continue
        names = set()
        for f in sorted(os.scandir(e.path), key=lambda x: x.name):
            rel = f"{e.name}/{f.name}"
            if f.name not in SPLIT_FILES:
                problems.append(f"unexpected entry {rel[:80]!r}")
                continue
            data, why = _read_once(Path(f.path))
            if why:
                problems.append(f"{rel}: {why}")
                continue
            names.add(f.name)
            blobs[rel] = data
        if names != set(SPLIT_FILES):
            problems.append(f"{e.name[:24]}: corpus must contain exactly SCREEN, QUALIFICATION_HOLDOUT and SEAL")
    return problems, blobs, manifest


def check_snapshot(problems: list, blobs: dict, manifest) -> list:
    problems = list(problems)
    seen = {}
    for rel, blob in blobs.items():
        cid, fname = rel.split("/")
        if len(blob) < len(S.MAGIC_ASYM) + 4 or not blob.startswith(S.MAGIC_ASYM):
            problems.append(f"{rel}: expected encrypted-artifact magic prefix missing")
            continue
        try:
            h = _header(blob)
        except Exception:
            problems.append(f"{rel}: malformed header")
            continue
        if set(h) != (SEAL_HEADER_KEYS if fname == "SEAL.enc" else SPLIT_HEADER_KEYS):
            problems.append(f"{rel}: header metadata outside the allowlist")
        if h.get("corpus_id") != cid or h.get("split") != SPLIT_FILES[fname]:
            problems.append(f"{rel}: header does not match its path")
        seen[rel] = hashlib.sha256(blob).hexdigest()
    if not blobs:
        problems.append("bundle contains no corpus")
    if manifest is None:
        if not any("MANIFEST.json" in p for p in problems):
            problems.append("MANIFEST.json missing")
    elif manifest != seen:
        problems.append("MANIFEST.json does not match bundle contents (missing, extra, or altered file)")
    return problems


def validate(bundle: Path) -> list:
    """KEYLESS. Establishes EXPECTED_ENCRYPTED_ARTIFACT_FORMAT_VALIDATED when the returned list is empty -- NOT proof of encryption."""
    return check_snapshot(*snapshot(bundle))


def seal(bundle: Path) -> dict:
    """Write-once manifest for a bundle that is otherwise well-formed. Refuses to seal anything with other problems."""
    bundle = Path(bundle)
    mpath = bundle / MANIFEST
    if os.path.lexists(mpath):
        raise FileExistsError("MANIFEST.json already exists (write-once)")
    problems, blobs, _ = snapshot(bundle)
    digests = {rel: hashlib.sha256(b).hexdigest() for rel, b in blobs.items()}
    problems = check_snapshot(problems, blobs, digests)
    if problems:
        raise ValueError("refusing to seal: " + "; ".join(problems))
    fd = os.open(mpath, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(digests, sort_keys=True))
    return digests


def validate_and_stage(bundle: Path, staging_parent: Path) -> Path:
    """Read once, validate those bytes, write a read-only staged copy from the SAME bytes. Import must read only from the returned directory."""
    problems, blobs, manifest = snapshot(bundle)
    problems = check_snapshot(problems, blobs, manifest)
    if problems:
        raise ValueError("bundle rejected: " + "; ".join(problems))
    staged = Path(tempfile.mkdtemp(prefix="staged-bundle-", dir=staging_parent))
    os.chmod(staged, 0o700)
    for rel, blob in blobs.items():
        cid, fname = rel.split("/")
        (staged / cid).mkdir(mode=0o700, exist_ok=True)
        fd = os.open(staged / rel, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
    fd = os.open(staged / MANIFEST, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(manifest, sort_keys=True))
    if validate(staged):
        raise ValueError("staged copy failed re-validation")
    for d in staged.iterdir():
        if d.is_dir():
            os.chmod(d, 0o500)
    os.chmod(staged, 0o500)
    return staged


def cryptographic_verify(bundle: Path, vault_private_key: bytes, expected_corpus_digest: str) -> list:
    """WITNESS SIDE ONLY. Decrypts every split in memory (AES-GCM tag verification) and checks digests; returns problems (empty == CRYPTOGRAPHICALLY_VERIFIED).
    Plaintext is discarded immediately and never returned, logged or persisted. The caller supplies the private key (ephemeral in tests); this module never
    reads, stores or prints key material."""
    problems = validate(bundle)
    if problems:
        return problems
    reader = S.EncryptedVaultReader(Path(bundle), vault_private_key, repo_root=ROOT)
    from orca.eval.genesis_v2 import spec
    out = []
    for cdir in sorted(p for p in Path(bundle).iterdir() if p.is_dir()):
        for split in spec.PRIVATE_SPLITS:
            try:
                reader.read_split(cdir.name, split, expected_corpus_digest=expected_corpus_digest)
            except Exception as e:
                out.append(f"{cdir.name[:24]}/{split}: cryptographic verification failed ({type(e).__name__})")
    return out


def main(argv):
    if len(argv) < 3 or argv[1] not in ("seal", "validate", "stage"):
        print(__doc__); return 2
    try:
        if argv[1] == "seal":
            print(json.dumps(seal(Path(argv[2])), sort_keys=True)); return 0
        if argv[1] == "stage":
            print(validate_and_stage(Path(argv[2]), Path(argv[3]))); return 0
    except (ValueError, FileExistsError, IndexError, OSError) as e:
        print("PROBLEM:", str(e)[:300]); return 1
    problems = validate(Path(argv[2]))
    for p in problems:
        print("PROBLEM:", p)
    print(FORMAT_CLAIM if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
