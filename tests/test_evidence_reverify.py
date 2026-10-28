from __future__ import annotations

from orca.sovereign_mission.store import digest
from orca.sovereign_mission.verify import verify_aggregate, verify_marker_receipt, verify_record


def test_reverify_detects_mismatch_and_confirms_intact():
    record = {"action": "local_marker", "text": "once"}
    claimed = digest(record)
    ok = verify_record(record, claimed)
    assert ok["match"] is True
    bad = verify_record(record, "f" * 64)
    assert bad["match"] is False
    assert bad["status"] == "mismatch"


def test_aggregate_and_marker_receipt(tmp_path):
    record = {"k": 1}
    hashed = digest(record)
    aggregate = digest({"evidence": [hashed]})
    body = verify_aggregate([{"record": record, "record_sha256": hashed}], aggregate)
    assert body["status"] == "intact"
    assert body["witness"] == "local_recompute"
    tampered = verify_aggregate([{"record": record, "record_sha256": hashed}], "0" * 64)
    assert tampered["status"] == "mismatch"
    marker = tmp_path / "marker.txt"
    marker.write_text("once")
    receipt = verify_marker_receipt(marker, "once", claimed_sha256=__import__("hashlib").sha256(b"once").hexdigest())
    assert receipt["status"] == "verified"
    missing = verify_marker_receipt(tmp_path / "gone.txt", "once")
    assert missing["status"] == "missing"
