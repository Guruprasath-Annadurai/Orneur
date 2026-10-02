"""Harness courier (the explicit ciphertext transfer/backup/restore boundary). Holds NO key. Copies ONLY well-formed ciphertext files
(magic-prefixed, expected names); refuses anything else. Usage: courier.py <src> <dst> <owner_uid> <write_manifest 0|1>"""
import hashlib, json, os, re, shutil, sys
from pathlib import Path
MAGIC = b"GCE2ENC2"; NAMES = {"SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc"}; CID = re.compile(r"^gce2c-[0-9a-f]{16,64}$")
src, dst, uid, manifest = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == "1"
copied = {}
for cdir in sorted(p for p in src.iterdir() if p.is_dir() and not p.name.startswith(".")):
    if not CID.match(cdir.name):
        sys.exit("REFUSED: unexpected directory " + cdir.name)
    for f in sorted(cdir.iterdir()):
        if f.name not in NAMES or f.name.startswith(".tmp-"):
            sys.exit("REFUSED: unexpected file " + f.name)
        blob = f.read_bytes()
        if not blob.startswith(MAGIC):
            sys.exit("REFUSED: not ciphertext " + f.name)
        out = dst / cdir.name / f.name
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            sys.exit("REFUSED: write-once violation " + str(out.relative_to(dst)))
        fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400); os.write(fd, blob); os.close(fd)
        os.chown(out, uid, uid); copied[cdir.name + "/" + f.name] = hashlib.sha256(blob).hexdigest()
    os.chown(dst / cdir.name, uid, uid); os.chmod(dst / cdir.name, 0o500)
if manifest:
    m = dst / "MANIFEST.json"; m.write_text(json.dumps(copied, sort_keys=True)); os.chmod(m, 0o400)
print(json.dumps(copied, sort_keys=True))
