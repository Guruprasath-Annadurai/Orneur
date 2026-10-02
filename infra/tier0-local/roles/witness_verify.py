"""Witness role (SYNTHETIC): holds ONLY the ephemeral vault private key; decrypts, verifies, records evidence (digests only; never plaintext)."""
import hashlib, json, sys
from pathlib import Path
from orca.eval.genesis_v2 import store as S, spec

corpus_id, digest = sys.argv[1], sys.argv[2]
priv = bytes.fromhex(Path("/secrets/vault_private_key").read_text().strip())
r = S.EncryptedVaultReader(Path("/vault"), priv, repo_root=Path("/app"))
out = {"corpus_id": corpus_id, "splits": {}}
for s in spec.PRIVATE_SPLITS:
    plain = r.read_split(corpus_id, s, expected_corpus_digest=digest)
    out["splits"][s] = {"sha256": hashlib.sha256(plain).hexdigest(), "synthetic_marker_ok": plain.startswith(b"SYNTHETIC-TIER0-")}
def _fails(fn):
    try:
        fn(); return False
    except Exception:
        return True
wrong_priv, _ = S.generate_vault_keypair()
out["wrong_key_fails"] = _fails(lambda: S.EncryptedVaultReader(Path("/vault"), wrong_priv, repo_root=Path("/app")).read_split(corpus_id, spec.PRIVATE_SPLITS[0], expected_corpus_digest=digest))
out["wrong_digest_fails"] = _fails(lambda: r.read_split(corpus_id, spec.PRIVATE_SPLITS[0], expected_corpus_digest="0" * 64))
out["corpus_secret_absent"] = not Path("/secrets/corpus_secret").exists()
Path("/evidence").mkdir(exist_ok=True)
Path("/evidence/" + corpus_id + ".json").write_text(json.dumps(out, sort_keys=True))
print(json.dumps(out, sort_keys=True))
