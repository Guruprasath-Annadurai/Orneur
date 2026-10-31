# MASTER-04 — packaging reality

Public production `Dockerfile` installs only `.[postgres]` via `uv pip install --system -e ".[postgres]"`.

- **chromadb** is under optional extra `memory` / `docs` — **not** in the public prod image.
- **cryptography** for encrypted backup is under optional extra `backup` — **not** in the public prod image.
- Server start /readyz / deletion paths remain functional without cryptography (`tests/test_l02_b6_no_crypto_dependency.py`).
- Enabling production vector backend or baking Chroma/crypto into the public image remains a **founder-blocked** decision.

MASTER-04 does not silently enable either package in the public image.
