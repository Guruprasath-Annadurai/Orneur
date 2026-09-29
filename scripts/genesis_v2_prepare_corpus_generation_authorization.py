#!/usr/bin/env python3
"""OWNER-RUN ONLY. Prepares the exact canonical bytes for a CORPUS_GENERATION_AUTHORIZATION record, bound to the
REAL current commit SHA and the REAL current corpus-inventory / preregistration digests, for the owner to sign
locally. Never invoked automatically; never touches or requests the owner's private key.

  python scripts/genesis_v2_prepare_corpus_generation_authorization.py --scope PILOT_TRAIN DEV --days 3

Writes docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION_PAYLOAD_TO_SIGN.signable and prints its SHA-256
digest plus the exact openssl signing command. Does not write CORPUS_GENERATION_AUTHORIZATION.json itself -- that
happens in a later step once the owner supplies the signature, exactly like the corpus-inventory attestation flow.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca.eval.genesis_v2 import corpus_generation_authorization as CGA  # noqa: E402
from orca.eval.genesis_v2 import inventory as INV  # noqa: E402
from orca.eval.genesis_v2 import prereg as PR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", nargs="+", required=True, choices=CGA.ARTIFACT_CLASSES, help="which artifact classes to authorize")
    ap.add_argument("--days", type=float, default=1.0, help="validity window in days (must be <= %s)" % CGA.MAX_VALIDITY)
    ap.add_argument("--key-id", default="orneur-owner-authority-1")
    ap.add_argument("--identity", default="orneur-owner-authority-1")
    args = ap.parse_args()

    window = timedelta(days=args.days)
    if window <= timedelta(0) or window > CGA.MAX_VALIDITY:
        print(f"ERROR: --days must be > 0 and <= {CGA.MAX_VALIDITY.days} days", file=sys.stderr)
        return 2
    if len(set(args.scope)) != len(args.scope):
        print("ERROR: --scope entries must be unique", file=sys.stderr)
        return 2

    commit_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    inv = json.loads((ROOT / INV.INVENTORY_PATH).read_text())
    inv_digest = INV.inventory_digest(inv)
    draft = json.loads((ROOT / PR.DRAFT_PATH).read_text())
    prereg_sha = draft["record_sha256"]

    now = datetime.now(timezone.utc)
    issued_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = (now + window).strftime("%Y-%m-%dT%H:%M:%SZ")
    auth_id = "cgauth-" + commit_sha[:16]

    record = CGA.default_record()
    record.update({
        "authorization_id": auth_id, "status": "AUTHORIZED", "purpose": CGA.PURPOSE, "authorized_scope": list(args.scope),
        "authorized_commit_sha": commit_sha, "authorized_artifact_digests": {"corpus_inventory_digest": inv_digest,
                                                                              "preregistration_record_sha256": prereg_sha},
        "issued_at": issued_at, "expires_at": expires_at,
        "authorizing_authority": {"identity": args.identity, "role": "OWNER", "key_id": args.key_id},
    })
    payload = CGA.canonical_signing_bytes(record)
    out_payload = ROOT / "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION_PAYLOAD_TO_SIGN.signable"
    out_record = ROOT / "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION_UNSIGNED_DRAFT.json"
    out_payload.write_bytes(payload)
    out_record.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")

    import hashlib
    print(json.dumps(record, indent=1, sort_keys=True))
    print()
    print("payload path  :", out_payload.relative_to(ROOT))
    print("payload sha256:", hashlib.sha256(payload).hexdigest())
    print()
    print("Sign it (on YOUR machine, with YOUR private key -- never paste the key anywhere):")
    print(f"  openssl pkeyutl -sign -inkey ~/orneur-owner-authority/orneur_owner_authority_1.private.pem \\")
    print(f"    -rawin -in {out_payload.relative_to(ROOT)} -out /tmp/cga.sig")
    print("  xxd -p -c 1000 /tmp/cga.sig")
    print()
    print("Then send only the resulting 128-hex-char signature. Nothing here writes CORPUS_GENERATION_AUTHORIZATION.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
