# DLP / Quota / SQLite Regression Matrix

| Control | Result | Evidence |
|---|---|---|
| Canonical route DLP | PASS | `tests/test_canonical_route_dlp.py` |
| Stream split-secret (B-01) | PASS | `test_s3_split_secret_*` |
| Quota admission | PASS | `tests/test_canonical_quota_admission.py` |
| Turn authority / fencing | PASS | `tests/test_canonical_turn_authority.py` |
| Transcript integrity | PASS (2 skip Redis) | `tests/test_p0_transcript_integrity.py` |
| Auth / logout | PASS | serving_authorization, logout_revocation |
| `/api/chat` non-stream | PASS | `test_s11_*` |
