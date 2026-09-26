#!/usr/bin/env python3
"""Build the Genesis Capability Eval V1 corpus, manifests, pre-registration and (once) the architecture freeze records. CPU-only; no inference."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca.eval import genesis_prereg as PR  # noqa: E402
from orca.intelligence import freeze_record as FRZ  # noqa: E402


def main() -> None:
    print(json.dumps({"freeze_records": FRZ.write_freeze_records(ROOT), **PR.write_all(ROOT)}, indent=1))


if __name__ == "__main__":
    main()
