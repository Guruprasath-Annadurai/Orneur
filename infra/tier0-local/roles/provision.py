"""Harness provisioner (root, no network): creates EPHEMERAL synthetic key material straight into role volumes; never prints a key.
The owner stand-in file lives in a volume that NO role container mounts."""
import os, secrets, sys
from pathlib import Path
from orca.eval.genesis_v2 import store as S

FORGE, WITNESS = 10001, 10002
def put(path, data, uid, mode=0o400):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode); os.write(fd, data); os.close(fd); os.chown(p, uid, uid)
priv, pub = S.generate_vault_keypair()
put("/v/forge-secrets/vault_public_key", pub.hex().encode(), FORGE)
put("/v/forge-secrets/corpus_secret", secrets.token_hex(32).encode(), FORGE)
put("/v/witness-secrets/vault_private_key", priv.hex().encode(), WITNESS)
put("/v/owner/owner_signing_key.synthetic", secrets.token_hex(32).encode(), 0)
for d, uid, mode in (("forge-secrets", FORGE, 0o500), ("witness-secrets", WITNESS, 0o500), ("ingest", FORGE, 0o700), ("vault", WITNESS, 0o500),
                     ("vault-restored", WITNESS, 0o500), ("evidence", WITNESS, 0o700), ("reliquary", 0, 0o700), ("owner", 0, 0o700)):
    os.chown("/v/" + d, uid, uid); os.chmod("/v/" + d, mode)
del priv
print("provisioned")
