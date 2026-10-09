"""Owner-decision locks for the block-1 successor. Synthetic keys only."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from orca.rse.imp1.locks import prove_authorization_locks
from orca.rse.imp1.verdict import CHECKS_PASSED
from orca.rse.imp3 import records
from tests.rse.block1_support import ed_key

_REPO = Path(__file__).resolve().parents[2]
_SIX = (
    "pytest",
    "torch-loss-tests",
    "container-build",
    "genesis-v2-security",
    "genesis-v2-sandbox",
    "security-audit",
)


def test_ock1_and_och1_domains_match_the_accepted_bytes():
    key = ed_key("ock1-domain")
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert public.hex() == "2fab2bcbeb1ea8b7a9fa5fad31aa31fe221fe5eebe8b435f03d375fe8dcd4a6f"
    checkpoint = records.pack_checkpoint(
        log_id=bytes(range(32)), tree_size=1, root=bytes(32), epoch=1,
        registry_version=1, prev_checkpoint_digest=bytes(32), role_key=key,
    )
    body, signature = checkpoint[:-64], checkpoint[-64:]
    assert len(checkpoint) == records.OCK1_LEN == 181
    assert len(body) == 117
    assert body[:5] == b"OCK1" + bytes([1])
    assert hashlib.sha256(body).hexdigest() == "09f8be5083fe1453e9c8fff647883f66c42ec0731d5606cef736134460911031"
    assert signature == key.sign(b"OCK1-SIG" + b"\x00" + body)
    records.parse_checkpoint(checkpoint, public)
    with pytest.raises(InvalidSignature):
        Ed25519PublicKey.from_public_bytes(public).verify(signature, body)

    challenge = records.pack_challenge(
        role_id=bytes(range(32)), challenge=bytes(32), challenge_seq=1,
        next_sequence=2, role_log_head=bytes(32), role_key=key,
    )
    challenge_body, challenge_signature = challenge[:-64], challenge[-64:]
    assert len(challenge) == records.OCH1_LEN == 181
    assert len(challenge_body) == 117
    assert challenge_body[:5] == b"OCH1" + bytes([1])
    assert hashlib.sha256(challenge_body).hexdigest() == "6f9b66f38ef83997329bab8799abe3ebb80cfd768f5541f187d02de90bf0a5d4"
    assert challenge_signature == key.sign(b"OCH1-SIG" + b"\x00" + challenge_body)
    records.parse_challenge(challenge, public)
    with pytest.raises(InvalidSignature):
        Ed25519PublicKey.from_public_bytes(public).verify(challenge_signature, challenge_body)


def test_ocr1_import_fails_closed_without_site_packages():
    proc = subprocess.run(
        [
            sys.executable, "-I", "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import orca.rse.imp4.ocr1",
            str(_REPO),
        ],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0
    assert "ModuleNotFoundError" in proc.stderr
    assert "pyhpke" in proc.stderr or "cryptography" in proc.stderr


def test_rse_extra_is_pinned_and_separate_from_the_base_install():
    project = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    base = project["project"]["dependencies"]
    assert not any("pyhpke" in item or "cryptography" in item for item in base)
    for extra in ("dev", "rse"):
        pins = project["project"]["optional-dependencies"][extra]
        assert "pyhpke==0.6.5" in pins
        assert any(item.startswith("cryptography>=49.0.0,<51.0.0") for item in pins)
    assert "pyhpke>=" not in (_REPO / "pyproject.toml").read_text(encoding="utf-8")


def test_rse_lock_is_hashed_and_resolves_inside_the_cryptography_window():
    text = (_REPO / "requirements" / "rse.txt").read_text(encoding="utf-8")
    names = re.findall(r"^([A-Za-z0-9_.-]+)==", text, flags=re.M)
    assert names == ["cffi", "cryptography", "pycparser", "pyhpke"]
    assert "pyhpke==0.6.5" in text
    match = re.search(r"^cryptography==(\d+)\.(\d+)\.(\d+)", text, flags=re.M)
    assert match is not None
    major, minor = int(match.group(1)), int(match.group(2))
    assert (major, minor) >= (49, 0)
    assert major < 51
    blocks = re.split(r"\n(?=[A-Za-z])", text)
    packages = [block for block in blocks if "==" in block.splitlines()[0]]
    assert packages
    for block in packages:
        assert "--hash=sha256:" in block
    assert "diskcache" not in text and "chromadb" not in text


def test_workflow_keeps_exact_sha_push_and_adds_a_failing_rse_audit():
    path = _REPO / ".github" / "workflows" / "test.yml"
    raw = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    assert "permissions" not in workflow
    # PyYAML 1.1 reads the workflow key `on` as boolean True.
    trigger = workflow[True]
    assert "cursor/**" in trigger["push"]["branches"]
    assert "cursor/**" not in trigger["pull_request"]["branches"]
    jobs = workflow["jobs"]
    for name in _SIX:
        assert name in jobs
        assert jobs[name].get("continue-on-error") is not True
    base = jobs["security-audit"]
    base_run = "\n".join(step.get("run", "") for step in base["steps"])
    assert 'uv pip install --system -e .' in base_run
    assert ".[rse]" not in base_run
    assert "pip-audit || true" in base_run
    audit = jobs["rse-dependency-audit"]
    assert audit.get("continue-on-error") is not True
    audit_run = "\n".join(step.get("run", "") for step in audit["steps"])
    assert "scripts/ci/run_rse_dependency_audit.sh" in audit_run
    script = (_REPO / "scripts" / "ci" / "run_rse_dependency_audit.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert "--require-hashes -r requirements/rse.txt" in script
    assert "pip-audit" in script
    assert "|| true" not in script
    assert "permissions:" not in raw


def test_authorization_locks_remain_denied():
    assert prove_authorization_locks().decision == CHECKS_PASSED


def test_manifest_v3_entries_still_match():
    root = _REPO / "docs" / "orneur" / "phase-21" / "rse"
    manifest = (root / "v1.2" / "RSE_ARCH_1_2_FREEZE_MANIFEST_V3.txt").read_text(encoding="utf-8")
    rows = [line for line in manifest.splitlines() if line and not line.startswith("#")]
    assert len(rows) == 32
    bad = []
    for line in rows:
        digest, size, _rest = line.split("  ", 2)
        rel = line.split("  ")[5]
        data = (root / rel).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or str(len(data)) != size:
            bad.append(rel)
    assert bad == []
