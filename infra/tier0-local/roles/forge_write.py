"""Forge role (SYNTHETIC): holds ONLY the vault public key + a synthetic corpus secret; writes encrypted synthetic splits; proves it cannot decrypt."""
import json, os, secrets, sys
from pathlib import Path
from orca.eval.genesis_v2 import store as S, spec

pub = bytes.fromhex(Path("/secrets/vault_public_key").read_text().strip())
corpus_secret_ok = len(bytes.fromhex(Path("/secrets/corpus_secret").read_text().strip())) >= 32
corpus_id = "gce2c-" + secrets.token_hex(16)
splits = {s: ("SYNTHETIC-TIER0-" + s + "-" + secrets.token_hex(24)).encode() for s in spec.PRIVATE_SPLITS}
w = S.EncryptedVaultWriter(Path("/ingest"), pub, repo_root=Path("/app"))
digest = w.write_corpus(corpus_id, splits)
# Forge cannot decrypt: it has no private key; the only 32 bytes it holds are the PUBLIC key -- using them as a "private key" must fail closed.
cannot_decrypt = False
try:
    S.EncryptedVaultReader(Path("/ingest"), pub, repo_root=Path("/app")).read_split(corpus_id, spec.PRIVATE_SPLITS[0], expected_corpus_digest=digest)
except Exception:
    cannot_decrypt = True
del splits
print(json.dumps({"corpus_id": corpus_id, "corpus_digest": digest, "forge_cannot_decrypt_with_its_own_material": cannot_decrypt,
                  "writer_has_private_key_attr": any("priv" in k.lower() for k in vars(w)), "corpus_secret_present": corpus_secret_ok}))
