"""C16 preparation: export OCR1 golden verdict digests for an independent second codec.

Does **not** claim C16. Cursor/ORNEUR cannot self-certify as the second
implementation. An external implementer must reproduce these digests.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from orca.pretrain_foundation.independent_codec import (
    CURSOR_IMPLEMENTATION_IDS,
    c16_engineering_status,
)


PRIMARY_IMPLEMENTATION_ID = "orca.rse.imp4.ocr1"


@dataclass(frozen=True)
class GoldenVector:
    vector_id: str
    description: str
    verdict_digest: str
    notes: str = ""


def _digest_label(label: str, payload: bytes) -> str:
    return hashlib.sha256(label.encode("utf-8") + b"\0" + payload).hexdigest()


def build_golden_vectors() -> list[GoldenVector]:
    """Stable synthetic golden digests derived from OCR1 structural constants.

    These are engineering reference vectors for a future independent codec.
    They are not formal C16 acceptance and not a second-implementation claim.
    """
    from orca.rse.imp4 import ocr1

    # Admit the RFC 9180 base vector once so export fails closed if broken.
    ocr1.admit_rfc9180_base()
    vectors = [
        GoldenVector(
            vector_id="ocr1-rfc9180-base-admitted",
            description="RFC 9180 base vector admission succeeds in primary OCR1",
            verdict_digest=_digest_label("rfc9180-base", b"ADMITTED"),
            notes="Primary implementation calls admit_rfc9180_base(); second codec must agree",
        ),
        GoldenVector(
            vector_id="ocr1-zero-shared-secret-refuse",
            description="Zero shared secret is refused before open",
            verdict_digest=_digest_label("zero-shared-secret", b"REFUSED"),
        ),
        GoldenVector(
            vector_id="ocr1-frame-count-bound",
            description="Frame count at max bound is 65536; +1 fails closed",
            verdict_digest=_digest_label(
                "frame-count",
                f"{ocr1.expected_count(ocr1.FRAME_PT * 65536)}".encode("ascii"),
            ),
        ),
    ]
    return vectors


def export_manifest() -> dict[str, Any]:
    vectors = build_golden_vectors()
    return {
        "schema": "orneur-ocr1-golden-vectors/1",
        "primary_implementation_id": PRIMARY_IMPLEMENTATION_ID,
        "c16_status": c16_engineering_status(secondary_present=False),
        "note": (
            "Published for an independent second codec. "
            f"Cursor implementations {sorted(CURSOR_IMPLEMENTATION_IDS)} "
            "cannot self-certify as the secondary party."
        ),
        "vectors": [asdict(v) for v in vectors],
    }


def write_golden_vectors(path: Path) -> dict[str, Any]:
    doc = export_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc
