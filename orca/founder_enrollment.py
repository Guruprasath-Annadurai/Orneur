"""Founder enrollment ceremony for the inactive freeze amendment.

Schema ``orneur-founder-enrollment/2`` signs a statement that does not contain
an observation hash. The observation is a projection built after signing, and
it does not contain its own hash. A publication receipt is a separate object.
This module does not generate a private key, store one, or treat a
caller-supplied public key, GitHub URL, git author, or in-repository pin as
authority.

``orneur-founder-enrollment/1`` is refused. Its bytes are not read as v2.
The operational observation pin, the publisher anchor, and the witness
identity channel are absent. ``future_exception_applies`` returns false.
The live governance test does not call it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orca.freeze_amendment import BASELINE, PROPOSAL_SHA256

SCHEMA_ENROLLMENT = "orneur-founder-enrollment/2"
SCHEMA_OBSERVATION = "orneur-founder-enrollment-observation/2"
LEGACY_SCHEMA = "orneur-founder-enrollment/1"
SCHEMA_RECEIPT = "orneur-founder-publication-receipt/1"
SCHEMA_REVOCATION = "orneur-founder-enrollment-revocation/1"
SCHEMA_REVOCATION_LIST = "orneur-founder-revocation-list/1"
SCHEMA_LOSS = "orneur-founder-enrollment-loss/1"
ENROLL_DOMAIN = b"orneur-founder-enrollment/2\n"
WITNESS_DOMAIN = b"orneur-founder-enrollment-witness/2\n"
RECEIPT_DOMAIN = b"orneur-founder-publication-receipt/1\n"
REVOCATION_DOMAIN = b"orneur-founder-enrollment-revocation/1\n"
LOSS_DOMAIN = b"orneur-founder-enrollment-loss/1\n"
SCOPE = "freeze-amendment-adopt-files/1"
PUBLICATION_CHANNEL = "external-signed-receipt"
REPOSITORY = "github.com/Guruprasath-Annadurai/Orneur"
AWAITING = "AWAITING_INDEPENDENT_ENROLLMENT"
REJECTED = "REJECTED"
ENROLLMENT_DIR = "docs/orneur/cursor/founder_enrollment"
MAX_VALIDITY = timedelta(days=366)
# None until an anchor that does not live in this repository is established
# by the founder. Assigning a digest here does not create that anchor.
OPERATIONAL_OBSERVATION_SHA256: str | None = None

_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_SIG128 = re.compile(r"^[0-9a-f]{128}$")
_KEY64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ENROLL_KEYS = {
    "schema_version",
    "identity",
    "key_id",
    "public_key_hex",
    "fingerprint_sha256",
    "scope",
    "enrolled_at",
    "expires_at",
    "publication_channel",
    "founder_signature",
    "witness",
}
_WITNESS_KEYS = {"identity", "key_id", "public_key_hex", "signature"}
_RECEIPT_KEYS = {
    "schema_version",
    "statement_sha256",
    "observation_sha256",
    "immutable_id",
    "channel",
    "publisher_key_id",
    "publisher_fingerprint_sha256",
    "signature",
}
_REVOCATION_KEYS = {"schema_version", "identity", "key_id", "fingerprint_sha256", "revoked_at", "signature"}
_LOSS_KEYS = {"schema_version", "lost_key_id", "lost_fingerprint_sha256", "attested_at", "witness"}
_CRYPTO_PRIORITY = (
    "legacy_schema_refused",
    "malformed_enrollment",
    "scope_rejected",
    "publication_not_independent",
    "synthetic_key_refused",
    "synthetic_context_refused",
    "witness_required",
    "witness_not_independent",
    "fingerprint_mismatch",
    "signature_invalid",
    "witness_signature_invalid",
    "enrollment_not_yet_valid",
    "stale_enrollment",
    "validity_window_rejected",
    "revocation_invalid",
    "key_revoked",
    "witness_identity_unauthenticated",
    "publisher_anchor_absent",
    "identity_mismatch",
    "unknown_key",
    "conflicting_enrollments",
    "enrollment_store_refused",
)
_ABSENT_ANCHOR = {
    "established": False,
    "observation_sha256": None,
    "reason": "independent_anchor_absent",
}
_ABSENT_PUBLISHER = {
    "established": False,
    "public_key": None,
    "fingerprint_sha256": None,
    "key_id": None,
    "reason": "publisher_anchor_absent",
}
_ABSENT_WITNESS = {
    "established": False,
    "witnesses": (),
    "reason": "witness_identity_channel_absent",
}


class FounderEnrollmentError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EnrollmentReview:
    status: str
    reason: str
    reasons: tuple[str, ...]
    synthetic: bool
    cryptographic_accept: bool
    operational_authority: bool
    governance_exception_active: bool
    signature_checked: bool
    signature_ok: bool = False
    witness_authenticated: bool = False
    publication_verified: bool = False


@dataclass(frozen=True)
class LossReview:
    reason: str
    signature_checked: bool
    signature_ok: bool
    operational_authority: bool
    governance_exception_active: bool


@dataclass(frozen=True)
class PublicationReview:
    reason: str
    signature_checked: bool
    signature_ok: bool
    publication_verified: bool
    operational_authority: bool
    governance_exception_active: bool
    synthetic: bool


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def fingerprint_of(public_key: bytes) -> str:
    return hashlib.sha256(bytes(public_key)).hexdigest()


def _parse_ts(stamp: object) -> datetime | None:
    if not isinstance(stamp, str) or not _TS.match(stamp):
        return None
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def statement_of(document: dict) -> dict:
    """Signed statement. It has no observation hash and no signature."""
    witness = document.get("witness") if isinstance(document.get("witness"), dict) else {}
    return {
        "schema_version": document.get("schema_version"),
        "identity": document.get("identity"),
        "key_id": document.get("key_id"),
        "public_key_hex": document.get("public_key_hex"),
        "fingerprint_sha256": document.get("fingerprint_sha256"),
        "scope": document.get("scope"),
        "enrolled_at": document.get("enrolled_at"),
        "expires_at": document.get("expires_at"),
        "publication_channel": document.get("publication_channel"),
        "witness": {
            "identity": witness.get("identity"),
            "key_id": witness.get("key_id"),
            "public_key_hex": witness.get("public_key_hex"),
        },
    }


def statement_sha256(document: dict) -> str:
    return hashlib.sha256(_canonical(statement_of(document))).hexdigest()


def founder_signing_bytes(document: dict) -> bytes:
    return ENROLL_DOMAIN + _canonical(statement_of(document))


def witness_signing_bytes(document: dict) -> bytes:
    signature = document.get("founder_signature")
    raw = bytes.fromhex(signature) if isinstance(signature, str) and _SIG128.match(signature) else b""
    return WITNESS_DOMAIN + founder_signing_bytes(document) + raw


def observation_of(document: dict) -> dict:
    """Projection after signing. The result does not contain its own hash.

    ``publication_immutable_id`` is the statement digest. That digest is known
    before this projection is hashed. The publication receipt signs the
    observation digest from outside this object.
    """
    witness = document.get("witness") if isinstance(document.get("witness"), dict) else {}
    witness_key = witness.get("public_key_hex")
    witness_fingerprint = None
    if isinstance(witness_key, str) and _KEY64.match(witness_key):
        witness_fingerprint = fingerprint_of(bytes.fromhex(witness_key))
    statement_digest = statement_sha256(document)
    return {
        "schema_version": SCHEMA_OBSERVATION,
        "repository": REPOSITORY,
        "baseline": BASELINE,
        "proposal_sha256": PROPOSAL_SHA256,
        "identity": document.get("identity"),
        "key_id": document.get("key_id"),
        "fingerprint_sha256": document.get("fingerprint_sha256"),
        "witness_identity": witness.get("identity"),
        "witness_key_id": witness.get("key_id"),
        "witness_fingerprint_sha256": witness_fingerprint,
        "enrolled_at": document.get("enrolled_at"),
        "expires_at": document.get("expires_at"),
        "scope": document.get("scope"),
        "publication_channel": document.get("publication_channel"),
        "publication_immutable_id": statement_digest,
        "statement_sha256": statement_digest,
        "founder_signature": document.get("founder_signature"),
        "witness_signature": witness.get("signature"),
    }


def observation_sha256(document: dict) -> str:
    return hashlib.sha256(_canonical(observation_of(document))).hexdigest()


def receipt_signing_bytes(receipt: dict) -> bytes:
    body = {key: value for key, value in receipt.items() if key != "signature"}
    return RECEIPT_DOMAIN + _canonical(body)


def revocation_signing_bytes(document: dict) -> bytes:
    body = {key: value for key, value in document.items() if key != "signature"}
    return REVOCATION_DOMAIN + _canonical(body)


def loss_signing_bytes(document: dict) -> bytes:
    witness = document.get("witness") if isinstance(document.get("witness"), dict) else {}
    body = {key: value for key, value in document.items() if key != "witness"}
    body["witness"] = {
        "identity": witness.get("identity"),
        "key_id": witness.get("key_id"),
        "public_key_hex": witness.get("public_key_hex"),
    }
    return LOSS_DOMAIN + _canonical(body)


def _verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception as exc:
        raise FounderEnrollmentError("signature_verifier_unavailable") from exc
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes(public_key)).verify(bytes(signature), message)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def load_operational_anchor() -> dict:
    """The independent observation pin. This preparation has none."""
    return dict(_ABSENT_ANCHOR)


def load_external_publisher_anchor() -> dict:
    """Publisher key held outside this repository. This preparation has none.

    This function does not read a file, an environment variable, or a GitHub
    URL. A value substituted for this function is not the anchor.
    """
    return dict(_ABSENT_PUBLISHER)


def load_external_witness_anchor() -> dict:
    """Witness identity channel outside this repository. This preparation has none."""
    return dict(_ABSENT_WITNESS)


def operational_anchor_established() -> bool:
    """True only for a later pin. A substituted loader is not that pin."""
    anchor = load_operational_anchor()
    if anchor != _ABSENT_ANCHOR:
        return False
    return anchor["established"] is True


def witness_identity_authenticated(document: object) -> bool:
    """Two keys are not two people. No external witness channel exists here."""
    del document
    anchor = load_external_witness_anchor()
    if anchor != _ABSENT_WITNESS:
        return False
    return False


def github_url_is_not_publication(uri: object) -> str:
    """A GitHub URL is not evidence that the founder published the object."""
    del uri
    return "publication_not_independent"


def git_identity_is_not_publication(author: object, email: object, badge: object) -> str:
    """Git author text, an email, and a verified badge are not a publisher signature."""
    del author, email, badge
    return "git_identity_not_publication"


def repository_material_cannot_authorize(material: object) -> str:
    """Source text, an in-repo digest, and a caller pin are not founder authority."""
    del material
    return "repository_logic_not_authority"


def environment_cannot_authorize(name: object, value: object) -> str:
    """An environment variable is not the founder trust anchor."""
    del name, value
    return "environment_not_authority"


def scope_cannot_authorize_training(scope: object) -> str:
    """The freeze-file scope does not authorize training, GPU, spending, or corpus."""
    if scope == SCOPE:
        return "freeze_scope_does_not_authorize_training"
    return "scope_rejected"


def accept_presented_public_key(material: object) -> str:
    """A raw key, a dict, or an empty registry is not an enrollment."""
    return "caller_supplied_key_refused" if material is not None else "independent_anchor_absent"


def _ordered(found: set[str]) -> tuple[str, ...]:
    return tuple(reason for reason in _CRYPTO_PRIORITY if reason in found)


def _review(document: object, revocations: tuple[dict, ...] | list[dict], *, now: datetime, synthetic_context: bool) -> EnrollmentReview:
    if isinstance(document, dict) and document.get("schema_version") == LEGACY_SCHEMA:
        return EnrollmentReview(
            REJECTED,
            "legacy_schema_refused",
            ("legacy_schema_refused",),
            synthetic_context,
            False,
            False,
            False,
            False,
        )
    found: set[str] = set()
    signature_checked = False
    public_hex = None
    witness = None
    if not isinstance(document, dict) or set(document) != _ENROLL_KEYS:
        found.add("malformed_enrollment")
    else:
        if document.get("schema_version") != SCHEMA_ENROLLMENT or document.get("scope") != SCOPE:
            found.add("scope_rejected" if document.get("schema_version") == SCHEMA_ENROLLMENT and document.get("scope") != SCOPE else "malformed_enrollment")
        if document.get("publication_channel") != PUBLICATION_CHANNEL:
            found.add("publication_not_independent")
        identity = document.get("identity")
        key_id = document.get("key_id")
        if not _IDENT.match(str(identity)) or not _IDENT.match(str(key_id)):
            found.add("malformed_enrollment")
        elif str(identity).startswith("synthetic-"):
            if not synthetic_context:
                found.add("synthetic_key_refused")
        elif synthetic_context:
            found.add("synthetic_context_refused")
        public_hex = document.get("public_key_hex")
        fingerprint = document.get("fingerprint_sha256")
        if not isinstance(public_hex, str) or not _KEY64.match(public_hex) or not isinstance(fingerprint, str) or not _SHA64.match(fingerprint):
            found.add("malformed_enrollment")
        elif fingerprint_of(bytes.fromhex(public_hex)) != fingerprint:
            found.add("fingerprint_mismatch")
        witness = document.get("witness")
        if not isinstance(witness, dict) or set(witness) != _WITNESS_KEYS:
            found.add("witness_required")
        else:
            if witness.get("identity") == identity or witness.get("public_key_hex") == public_hex or witness.get("key_id") == key_id:
                found.add("witness_not_independent")
            if not _IDENT.match(str(witness.get("identity"))) or not _IDENT.match(str(witness.get("key_id"))):
                found.add("malformed_enrollment")
            if not isinstance(witness.get("public_key_hex"), str) or not _KEY64.match(str(witness.get("public_key_hex"))):
                found.add("malformed_enrollment")
            if not isinstance(witness.get("signature"), str) or not _SIG128.match(str(witness.get("signature"))):
                found.add("witness_signature_invalid")
        founder_signature = document.get("founder_signature")
        if not isinstance(founder_signature, str) or not _SIG128.match(founder_signature):
            found.add("signature_invalid")
        enrolled_at = _parse_ts(document.get("enrolled_at"))
        expires_at = _parse_ts(document.get("expires_at"))
        if enrolled_at is None or expires_at is None:
            found.add("malformed_enrollment")
        else:
            if enrolled_at > now:
                found.add("enrollment_not_yet_valid")
            if now >= expires_at:
                found.add("stale_enrollment")
            if expires_at - enrolled_at > MAX_VALIDITY or expires_at <= enrolled_at:
                found.add("validity_window_rejected")
        if "malformed_enrollment" not in found and "fingerprint_mismatch" not in found and isinstance(public_hex, str) and _KEY64.match(public_hex):
            public = bytes.fromhex(public_hex)
            if isinstance(founder_signature, str) and _SIG128.match(founder_signature):
                signature_checked = True
                if not _verify(public, bytes.fromhex(founder_signature), founder_signing_bytes(document)):
                    found.add("signature_invalid")
            if isinstance(witness, dict) and isinstance(witness.get("public_key_hex"), str) and _KEY64.match(witness["public_key_hex"]):
                if isinstance(witness.get("signature"), str) and _SIG128.match(witness["signature"]):
                    signature_checked = True
                    if not _verify(bytes.fromhex(witness["public_key_hex"]), bytes.fromhex(witness["signature"]), witness_signing_bytes(document)):
                        found.add("witness_signature_invalid")
            found.update(_revocation_problems(document, revocations, public, now))
    crypto = _ordered(found)
    signature_ok = (
        signature_checked
        and "signature_invalid" not in found
        and "witness_signature_invalid" not in found
        and "malformed_enrollment" not in found
        and "fingerprint_mismatch" not in found
    )
    operational: list[str] = []
    if not synthetic_context and isinstance(document, dict) and "malformed_enrollment" not in found and "legacy_schema_refused" not in found:
        if not witness_identity_authenticated(document):
            operational.append("witness_identity_unauthenticated")
        operational.append("publisher_anchor_absent")
    if not crypto and not operational:
        return EnrollmentReview(
            AWAITING,
            "independent_anchor_absent",
            ("independent_anchor_absent",),
            synthetic_context,
            True,
            False,
            False,
            signature_checked,
            signature_ok,
            False,
            False,
        )
    reasons = crypto + tuple(reason for reason in operational if reason not in crypto)
    reason = reasons[0]
    return EnrollmentReview(
        REJECTED,
        reason,
        reasons,
        synthetic_context,
        not crypto,
        False,
        False,
        signature_checked,
        signature_ok,
        False,
        False,
    )


def _revocation_problems(document: dict, revocations: tuple[dict, ...] | list[dict], public: bytes, now: datetime) -> set[str]:
    found: set[str] = set()
    for item in revocations:
        if not isinstance(item, dict) or set(item) != _REVOCATION_KEYS or item.get("schema_version") != SCHEMA_REVOCATION:
            found.add("revocation_invalid")
            continue
        if item.get("key_id") != document.get("key_id") and item.get("fingerprint_sha256") != document.get("fingerprint_sha256"):
            continue
        signature = item.get("signature")
        if not isinstance(signature, str) or not _SIG128.match(signature):
            found.add("revocation_invalid")
            continue
        if item.get("identity") != document.get("identity") or item.get("fingerprint_sha256") != document.get("fingerprint_sha256"):
            found.add("revocation_invalid")
            continue
        if not _verify(public, bytes.fromhex(signature), revocation_signing_bytes(item)):
            found.add("revocation_invalid")
            continue
        revoked_at = _parse_ts(item.get("revoked_at"))
        if revoked_at is None or revoked_at > now:
            found.add("revocation_invalid")
            continue
        found.add("key_revoked")
    return found


def review_enrollment(document: object, revocations: tuple[dict, ...] | list[dict] = (), *, now: datetime, synthetic_context: bool) -> EnrollmentReview:
    """Check one enrollment. Operational authority stays false."""
    if now.tzinfo is None:
        raise FounderEnrollmentError("naive_clock")
    return _review(document, revocations, now=now, synthetic_context=synthetic_context)


def review_publication_receipt(
    receipt: object,
    enrollment: object,
    *,
    trusted_publisher: bytes | None = None,
    synthetic_context: bool,
) -> PublicationReview:
    """Check a publication receipt. An operational publisher anchor is absent.

    A key passed by the caller is used only when ``synthetic_context`` is true,
    and even a matching synthetic signature stays ``publisher_not_enrolled``.
    """
    if not synthetic_context:
        supplied = trusted_publisher is not None or load_external_publisher_anchor() != _ABSENT_PUBLISHER
        reason = "caller_supplied_publisher_refused" if supplied else "publisher_anchor_absent"
        return PublicationReview(reason, False, False, False, False, False, False)
    if trusted_publisher is None or len(trusted_publisher) != 32:
        return PublicationReview("publisher_anchor_absent", False, False, False, False, False, True)
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS or receipt.get("schema_version") != SCHEMA_RECEIPT:
        return PublicationReview("receipt_malformed", False, False, False, False, False, True)
    if not isinstance(enrollment, dict):
        return PublicationReview("receipt_not_bound", False, False, False, False, False, True)
    key_id = str(receipt.get("publisher_key_id"))
    channel = receipt.get("channel")
    if "cursoragent" in key_id.casefold() or (isinstance(channel, str) and "cursoragent" in channel.casefold()):
        return PublicationReview("agent_publication_refused", False, False, False, False, False, True)
    if channel != PUBLICATION_CHANNEL or enrollment.get("publication_channel") != PUBLICATION_CHANNEL:
        return PublicationReview("publication_not_independent", False, False, False, False, False, True)
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not _SIG128.match(signature):
        return PublicationReview("receipt_unsigned", False, False, False, False, False, True)
    expected_statement = statement_sha256(enrollment)
    expected_observation = observation_sha256(enrollment)
    if (
        receipt.get("immutable_id") != expected_statement
        or receipt.get("statement_sha256") != expected_statement
        or receipt.get("observation_sha256") != expected_observation
        or not _SHA64.match(str(receipt.get("publisher_fingerprint_sha256")))
    ):
        return PublicationReview("receipt_not_bound", False, False, False, False, False, True)
    if receipt.get("publisher_fingerprint_sha256") != fingerprint_of(trusted_publisher):
        return PublicationReview("publisher_fingerprint_mismatch", False, False, False, False, False, True)
    witness = enrollment.get("witness") if isinstance(enrollment.get("witness"), dict) else {}
    if trusted_publisher.hex() in (enrollment.get("public_key_hex"), witness.get("public_key_hex")) or key_id in (
        str(enrollment.get("key_id")),
        str(witness.get("key_id")),
    ):
        return PublicationReview("publisher_not_independent", True, False, False, False, False, True)
    if not _verify(trusted_publisher, bytes.fromhex(signature), receipt_signing_bytes(receipt)):
        return PublicationReview("receipt_signature_invalid", True, False, False, False, False, True)
    return PublicationReview("publisher_not_enrolled", True, True, True, False, False, True)


def review_approval_binding(approval: dict, enrollment: dict, review: EnrollmentReview) -> tuple[str, ...]:
    """Bind a freeze approval to an enrollment. This does not activate the exception."""
    from orca.freeze_amendment import assess_approvals, canonical_approval_bytes

    structural = assess_approvals([approval])
    if structural:
        return structural
    if not review.signature_ok or not review.cryptographic_accept:
        return review.reasons
    if "witness_identity_unauthenticated" in review.reasons or "publisher_anchor_absent" in review.reasons:
        return review.reasons
    founder = approval.get("founder") if isinstance(approval.get("founder"), dict) else {}
    if founder.get("identity") != enrollment.get("identity"):
        return ("identity_mismatch",)
    if founder.get("key_id") != enrollment.get("key_id"):
        return ("unknown_key",)
    signature = approval.get("signature")
    public_hex = enrollment.get("public_key_hex")
    if not isinstance(signature, str) or not _SIG128.match(signature) or not isinstance(public_hex, str):
        return ("signature_invalid",)
    if not _verify(bytes.fromhex(public_hex), bytes.fromhex(signature), canonical_approval_bytes(approval)):
        return ("signature_invalid",)
    return ()


def review_loss(document: object, *, now: datetime) -> LossReview:
    """A witness may attest that a key is lost. That attestation enrolls nothing."""
    if isinstance(document, dict) and (
        "replacement_public_key_hex" in document or document.get("activates") is True or document.get("operational_authority") is True
    ):
        return LossReview("recovery_cannot_bind_replacement", False, False, False, False)
    if not isinstance(document, dict) or set(document) != _LOSS_KEYS or document.get("schema_version") != SCHEMA_LOSS:
        return LossReview("malformed_enrollment", False, False, False, False)
    witness = document.get("witness")
    if not isinstance(witness, dict) or set(witness) != _WITNESS_KEYS:
        return LossReview("witness_required", False, False, False, False)
    if _parse_ts(document.get("attested_at")) is None or _parse_ts(document.get("attested_at")) > now:
        return LossReview("malformed_enrollment", False, False, False, False)
    signature = witness.get("signature")
    public_hex = witness.get("public_key_hex")
    if not isinstance(signature, str) or not _SIG128.match(signature) or not isinstance(public_hex, str) or not _KEY64.match(public_hex):
        return LossReview("witness_signature_invalid", True, False, False, False)
    ok = _verify(bytes.fromhex(public_hex), bytes.fromhex(signature), loss_signing_bytes(document))
    if not ok:
        return LossReview("witness_signature_invalid", True, False, False, False)
    return LossReview("recovery_requires_new_enrollment", True, True, False, False)


def review_rotation(document: object) -> str:
    """Rotation is a new enrollment after revocation, not an activation shortcut."""
    if not isinstance(document, dict):
        return "malformed_enrollment"
    if document.get("activates") is True or document.get("operational_authority") is True or document.get("scope") not in (None, SCOPE):
        return "rotation_cannot_activate"
    return "rotation_requires_new_enrollment"


def future_exception_applies(diff_reasons: tuple[str, ...], approval_problems: tuple[str, ...], enrollment_problems: tuple[str, ...]) -> bool:
    """Prepared gate. Repository code cannot establish founder authority.

    The live governance test does not call this function. Editing this
    function, replacing a hash in this repository, or substituting the anchor
    loader does not make the return value true in this commit.
    """
    if diff_reasons or approval_problems or enrollment_problems:
        return False
    if load_operational_anchor() != _ABSENT_ANCHOR:
        return False
    if repository_material_cannot_authorize(load_operational_anchor()) != "repository_logic_not_authority":
        return False
    return False


def gate_problems(review: EnrollmentReview, approval_problems: tuple[str, ...] = ()) -> tuple[str, ...]:
    problems: list[str] = []
    if review.synthetic:
        problems.append("synthetic_key_refused")
    problems.extend(reason for reason in review.reasons if reason != "independent_anchor_absent")
    problems.extend(approval_problems)
    if not review.witness_authenticated:
        problems.append("witness_identity_unauthenticated")
    if not review.publication_verified:
        problems.append("publisher_anchor_absent")
    if not operational_anchor_established():
        problems.append("independent_anchor_absent")
    return tuple(dict.fromkeys(problems))


def _load_json(path: Path) -> tuple[object | None, str | None]:
    if path.is_symlink() or not path.is_file():
        return None, "enrollment_store_refused"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "malformed_enrollment"


def establish(root: Path | None = None, *, now: datetime | None = None) -> EnrollmentReview:
    """Read the enrollment directory. No file here establishes operational authority."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise FounderEnrollmentError("naive_clock")
    anchor = load_operational_anchor()
    if anchor != _ABSENT_ANCHOR:
        return EnrollmentReview(REJECTED, "caller_supplied_anchor_refused", ("caller_supplied_anchor_refused",), False, False, False, False, False)
    directory = base / ENROLLMENT_DIR
    if not directory.exists():
        return EnrollmentReview(AWAITING, "enrollment_absent", ("enrollment_absent", "independent_anchor_absent"), False, False, False, False, False)
    if directory.is_symlink() or not directory.is_dir():
        return EnrollmentReview(REJECTED, "enrollment_store_refused", ("enrollment_store_refused",), False, False, False, False, False)
    names = sorted(path.name for path in directory.iterdir())
    allowed = {"enrollment.json", "revocations.json"}
    if any(path.is_symlink() for path in directory.iterdir()) or any(name not in allowed for name in names):
        return EnrollmentReview(REJECTED, "enrollment_store_refused", ("enrollment_store_refused",), False, False, False, False, False)
    if "enrollment.json" not in names:
        return EnrollmentReview(AWAITING, "enrollment_absent", ("enrollment_absent", "independent_anchor_absent"), False, False, False, False, False)
    payload, problem = _load_json(directory / "enrollment.json")
    if problem:
        return EnrollmentReview(REJECTED, problem, (problem,), False, False, False, False, False)
    revocations: list[dict] = []
    if "revocations.json" in names:
        listed, list_problem = _load_json(directory / "revocations.json")
        if list_problem or not isinstance(listed, dict) or set(listed) != {"schema_version", "records"} or listed.get("schema_version") != SCHEMA_REVOCATION_LIST or not isinstance(listed.get("records"), list):
            return EnrollmentReview(REJECTED, "revocation_invalid", ("revocation_invalid",), False, False, False, False, False)
        revocations = list(listed["records"])
    review = review_enrollment(payload, revocations, now=clock, synthetic_context=False)
    if operational_anchor_established():
        return EnrollmentReview(REJECTED, "caller_supplied_anchor_refused", ("caller_supplied_anchor_refused",), False, False, False, False, review.signature_checked)
    return review
