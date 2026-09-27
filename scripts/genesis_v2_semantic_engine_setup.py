#!/usr/bin/env python3
"""OWNER-RUN ONLY. Not invoked by any test, CI job or other script in this repository.

Installs a local sentence-embedding model for orca.eval.genesis_v2.semantic.load_local_embedder, pins its exact revision, and prints the content
hash to bind into the preregistration. Refuses to download anything unless --allow-download is passed explicitly on this exact invocation; with
no cached copy and no --allow-download, it does nothing and reports NOT_CONFIGURED. Never called automatically -- this is the "explicitly
authorized owner setup step" the design requires before any network access for model installation may occur.

  python scripts/genesis_v2_semantic_engine_setup.py --model-dir <LOCAL_DIR> --revision <PINNED_REVISION> [--allow-download]
"""
import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True, help="Local directory to hold the model (outside the repository).")
    ap.add_argument("--model-id", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--revision", required=True, help="Exact pinned revision/commit, never a floating tag.")
    ap.add_argument("--allow-download", action="store_true", help="Explicit owner authorization for this one invocation to reach the network.")
    a = ap.parse_args()
    model_dir = Path(a.model_dir)
    if model_dir.exists() and any(model_dir.iterdir()):
        print("model directory already populated; not downloading")
    elif not a.allow_download:
        print("NOT_CONFIGURED: no cached model and --allow-download was not passed; nothing was downloaded")
        return 2
    else:
        try:
            from huggingface_hub import snapshot_download
        except Exception:
            print("NOT_CONFIGURED: huggingface_hub is not installed")
            return 2
        snapshot_download(repo_id=a.model_id, revision=a.revision, local_dir=str(model_dir))
    from orca.eval.genesis_v2.semantic import _dir_sha256
    digest = _dir_sha256(model_dir)
    print(f"model_dir={model_dir}\nmodel_id={a.model_id}\nrevision={a.revision}\ncontent_sha256={digest}")
    print("Bind this content_sha256 into the preregistration's semantic_review_mechanism_version binding, and pass model_dir/digest to "
          "orca.eval.genesis_v2.semantic.load_local_embedder(model_dir, digest) — never auto-download again after this point.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
