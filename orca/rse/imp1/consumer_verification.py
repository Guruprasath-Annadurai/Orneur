"""C06 / C07 consumer verification evidence (RSE 1.2).

C06 — Signed-byte consumer rendering
  Validate received grant bytes, render the operator-visible card only from
  those verified bytes, and cryptographically bind the rendered-card evidence
  to the exact verified input. Refuse malformed, altered, non-canonical, or
  mismatched representations.

C07 — SAS and independent Intent Sheet
  60-bit SAS (OCR-SAS-v1) plus independently typed Intent Sheet fields per
  RSE12_01 §4 / RSE12_06 C07. Fail closed on incorrect SAS, altered intent,
  stale grant, or inconsistent signed bytes.

Success yields CHECKS_PASSED evidence only. It is never executable authority:
spending, training, GPU, corpus generation, and qualification stay denied
until upstream trust / authorization dependencies are satisfied.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType

from orca.rse.imp1.authority import (
    ChallengeLedger,
    Floors,
    IntentSheet,
    _check_grant,
    _consumer_snapshot,
    _load,
    _reject_deferred,
    _require_authenticated_version,
    compare_intent,
    grant_sas,
    render_card,
    typed_artifact,
    ceilings_of,
    destination_entry,
)
from orca.rse.imp1.codec import OwnerToken, parse_grant
from orca.rse.imp1.profiles import NOT_CLAIMED, CARRY_FORWARD, SAS_DOMAIN
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, FailClosed, Result, guard

# Evidence domain separation. Not signing domains; digests only.
C06_CARD_DOMAIN = b"OCR-C06-CARD-v1"
C07_TYPED_DOMAIN = b"OCR-C07-TYPED-v1"

_SAS_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
_MISSING = object()


def _hex_digest(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def _deny_authority() -> dict:
    return {
        "not_claimed": NOT_CLAIMED,
        "carry_forward": CARRY_FORWARD,
        "spending": False,
        "training": False,
        "model_selection": False,
        "gpu": False,
        "provider": False,
        "executable": False,
        "authority_usable": False,
        "corpus_generation": "NOT_AUTHORIZED",
        "qualification": "NOT_AUTHORIZED",
        "unresolved_deps": (
            "G3",
            "trust_anchors_absent",
            "independent_reviews_missing",
            "training_authorization_absent",
        ),
    }


def _card_binding(grant_raw: bytes, card: str) -> str:
    """Bind rendered card UTF-8 to the exact received grant bytes."""
    card_bytes = card.encode("utf-8")
    material = C06_CARD_DOMAIN + b"\x00" + bytes(grant_raw) + b"\x00" + card_bytes
    return _hex_digest(material)


def _typed_record_digest(fields: dict) -> str:
    """Deterministic digest over safe typed-entry fields (no secrets)."""
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _hex_digest(C07_TYPED_DOMAIN + b"\x00" + canonical.encode("ascii"))


def _normalize_typed_sas(typed_sas: object) -> str:
    """Accept only the RSE 1.2 display form XXXX-XXXX-XXXX over the Base32 alphabet.

    Unicode, confusables outside the alphabet, lowercase, whitespace padding, and
    alternate separators are refused. The operator types what Crown shows; the
    consumer does not "helpfully" normalize attacker-controlled lookalikes.
    """
    if not isinstance(typed_sas, str):
        raise FailClosed("SAS_TYPE")
    if typed_sas != typed_sas.strip():
        raise FailClosed("SAS_FORM")
    if any(ord(ch) > 127 for ch in typed_sas):
        raise FailClosed("SAS_UNICODE")
    parts = typed_sas.split("-")
    if len(parts) != 3 or [len(p) for p in parts] != [4, 4, 4]:
        raise FailClosed("SAS_FORM")
    joined = "".join(parts)
    if joined != joined.upper() or any(ch not in _SAS_ALPHABET for ch in joined):
        raise FailClosed("SAS_ALPHABET")
    return f"{joined[0:4]}-{joined[4:8]}-{joined[8:12]}"


def _refuse(reason: str, *, requirement_id: str, **extra) -> Result:
    payload = _deny_authority()
    payload["requirement_id"] = requirement_id
    payload["evidence_kind"] = "REFUSAL"
    payload.update(extra)
    return Result(FAIL_CLOSED, reason, MappingProxyType(payload))


def _pass(reason: str, *, requirement_id: str, **extra) -> Result:
    payload = _deny_authority()
    payload["requirement_id"] = requirement_id
    payload["evidence_kind"] = "EVIDENCE"
    payload.update(extra)
    return Result(CHECKS_PASSED, reason, MappingProxyType(payload))


@dataclass(frozen=True)
class RenderedCardEvidence:
    """Operator-visible C06 artifact. Digest-bound to received signed bytes."""

    requirement_id: str
    decision: str
    reason: str
    grant_raw_digest: str
    signed_region_digest: str
    card: str
    card_digest: str
    binding_digest: str
    authority_usable: bool = False

    def to_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id,
            "decision": self.decision,
            "reason": self.reason,
            "grant_raw_digest": self.grant_raw_digest,
            "signed_region_digest": self.signed_region_digest,
            "card": self.card,
            "card_digest": self.card_digest,
            "binding_digest": self.binding_digest,
            "authority_usable": False,
        }


@dataclass(frozen=True)
class TypedEntryRecord:
    """C07 typed-entry record for SAS and Intent Sheet fields. No secrets."""

    requirement_id: str
    decision: str
    reason: str
    typed_sas: str
    computed_sas: str
    typed_intent: dict
    grant_derived_intent: dict
    grant_raw_digest: str
    record_digest: str
    authority_usable: bool = False

    def to_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id,
            "decision": self.decision,
            "reason": self.reason,
            "typed_sas": self.typed_sas,
            "computed_sas": self.computed_sas,
            "typed_intent": dict(self.typed_intent),
            "grant_derived_intent": dict(self.grant_derived_intent),
            "grant_raw_digest": self.grant_raw_digest,
            "record_digest": self.record_digest,
            "authority_usable": False,
        }


def _intent_public_fields(intent: IntentSheet) -> dict:
    return {
        "grant_class": intent.grant_class,
        "artifact_name": intent.artifact_name,
        "artifact_version": intent.artifact_version,
        "destination_name": intent.destination_name,
        "ceilings": list(intent.ceilings),
        "sas": intent.sas,
        "target_role_name": intent.target_role_name,
        "counterpart_name": intent.counterpart_name,
        "sequence": list(intent.sequence),
    }


def _grant_derived_intent(grant, registry) -> dict:
    artifact_name, artifact_version = typed_artifact(grant, registry)
    dest = destination_entry(grant, registry)
    dest_name = "" if dest is None else dest.name
    role = registry.by_id(grant.target_role_id)
    role_name = "" if role is None else role.name
    counterpart = ""
    sequence: list = []
    if grant.klass == ord("G"):
        recipient = registry.by_id(grant.tail["recipient_role_id"])
        counterpart = "" if recipient is None else recipient.name
    elif grant.klass == ord("V"):
        sender = registry.by_id(grant.tail["sender_role_id"])
        counterpart = "" if sender is None else sender.name
        sequence = [grant.tail["seq_first"], grant.tail["seq_last"]]
    return {
        "grant_class": chr(grant.klass),
        "artifact_name": artifact_name,
        "artifact_version": artifact_version,
        "destination_name": dest_name,
        "ceilings": list(ceilings_of(grant)),
        "sas": grant_sas(grant.klass, grant.signed),
        "target_role_name": role_name,
        "counterpart_name": counterpart,
        "sequence": sequence,
    }


@guard
def render_from_signed_bytes(
    grant_raw: bytes,
    registry_raw: bytes,
    tokens: list[OwnerToken],
    floors: Floors,
    crown_image_entry_id: bytes,
    *,
    claimed_card: str | None = None,
    **extra,
) -> Result:
    """C06: render the operator card only from verified received signed bytes.

    ``claimed_card``, when supplied, must equal the consumer-rendered card.
    A Crown-display (B1) card that does not match the card rendered from the
    received signed bytes (B2) is refused — the consumer never trusts a
    proposer- or Crown-supplied display string as authoritative.
    """
    raw_digest = ""
    try:
        if extra:
            raise FailClosed("UNEXPECTED_ARGUMENT")
        if not isinstance(grant_raw, (bytes, bytearray)):
            raise FailClosed("GRANT_TYPE")
        grant_raw = bytes(grant_raw)
        raw_digest = _hex_digest(grant_raw)
        grant, registry = _load(grant_raw, registry_raw, tokens)
        _reject_deferred(grant)
        # Re-parse must reproduce the exact received bytes (canonical + signatures).
        if grant.raw != grant_raw:
            raise FailClosed("RAW_MISMATCH")
        _check_grant(grant, registry, floors, crown_image_entry_id)
        card = render_card(grant, registry, floors, crown_image_entry_id)
        if claimed_card is not None:
            if not isinstance(claimed_card, str):
                raise FailClosed("CLAIMED_CARD_TYPE")
            if claimed_card != card:
                raise FailClosed("CARD_MISMATCH")
        card_digest = _hex_digest(card.encode("utf-8"))
        binding = _card_binding(grant_raw, card)
        evidence = RenderedCardEvidence(
            requirement_id="C06",
            decision=CHECKS_PASSED,
            reason="C06_RENDERED_CARD",
            grant_raw_digest=raw_digest,
            signed_region_digest=_hex_digest(grant.signed),
            card=card,
            card_digest=card_digest,
            binding_digest=binding,
            authority_usable=False,
        )
        # Binding must include the exact verified input; recompute as a self-check.
        if _card_binding(grant_raw, card) != evidence.binding_digest:
            raise FailClosed("BINDING")
        if grant_sas(grant.klass, grant.signed) not in card:
            raise FailClosed("CARD_SAS")
        return _pass(
            "C06_RENDERED_CARD",
            requirement_id="C06",
            rendered_card_evidence=evidence.to_dict(),
            sas=grant_sas(grant.klass, grant.signed),
            card=card,
        )
    except FailClosed as exc:
        return _refuse(
            exc.reason,
            requirement_id="C06",
            grant_raw_digest=raw_digest,
            rendered_card_evidence={
                "requirement_id": "C06",
                "decision": FAIL_CLOSED,
                "reason": exc.reason,
                "grant_raw_digest": raw_digest,
                "signed_region_digest": "",
                "card": "",
                "card_digest": "",
                "binding_digest": "",
                "authority_usable": False,
            },
        )


@guard
def verify_typed_sas_and_intent(
    grant_raw: bytes,
    registry_raw: bytes,
    tokens: list[OwnerToken],
    floors: Floors,
    crown_image_entry_id: bytes,
    typed_sas: str,
    intent: IntentSheet,
    outstanding_challenge: bytes,
    own_role_id: bytes,
    observed_environment: bytes,
    *,
    highest_authenticated_version=_MISSING,
    challenge_ledger=_MISSING,
    **extra,
) -> Result:
    """C07: typed 60-bit SAS + independently entered Intent Sheet comparison.

    The Intent Sheet is operator-supplied and independent of Crown's screen.
    The SAS is recomputed from the received signed region and compared to the
    typed value. Stale / superseded / cross-session challenges fail closed.
    """
    raw_digest = ""
    typed_sas_safe = ""
    try:
        if extra:
            raise FailClosed("UNEXPECTED_ARGUMENT")
        if not isinstance(grant_raw, (bytes, bytearray)):
            raise FailClosed("GRANT_TYPE")
        grant_raw = bytes(grant_raw)
        raw_digest = _hex_digest(grant_raw)
        if highest_authenticated_version is _MISSING or challenge_ledger is _MISSING:
            raise FailClosed("AUTHENTICATED_VERSION")
        highest = _require_authenticated_version(highest_authenticated_version)
        if not isinstance(challenge_ledger, ChallengeLedger):
            raise FailClosed("CHALLENGE_LEDGER")
        if not isinstance(intent, IntentSheet):
            raise FailClosed("INTENT_TYPE")

        normalized_sas = _normalize_typed_sas(typed_sas)
        typed_sas_safe = normalized_sas
        grant, registry = _load(grant_raw, registry_raw, tokens)
        _reject_deferred(grant)
        if grant.raw != grant_raw:
            raise FailClosed("RAW_MISMATCH")
        if isinstance(outstanding_challenge, (bytes, bytearray)) and challenge_ledger.is_void(
            bytes(outstanding_challenge)
        ):
            raise FailClosed("CHALLENGE_VOID")
        _consumer_snapshot(grant, registry, highest, challenge_ledger)
        if not isinstance(own_role_id, (bytes, bytearray)) or bytes(own_role_id) != grant.target_role_id:
            raise FailClosed("ROLE_ID")
        if not isinstance(observed_environment, (bytes, bytearray)) or len(observed_environment) != 32:
            raise FailClosed("ENVIRONMENT")
        if bytes(observed_environment) != grant.env_measurement_digest:
            raise FailClosed("ENVIRONMENT")
        if not isinstance(outstanding_challenge, (bytes, bytearray)) or len(outstanding_challenge) != 32:
            raise FailClosed("CHALLENGE")
        if grant.challenge != bytes(outstanding_challenge):
            raise FailClosed("CHALLENGE")
        if challenge_ledger.is_void(grant.challenge):
            raise FailClosed("CHALLENGE_VOID")
        _check_grant(grant, registry, floors, crown_image_entry_id)

        computed = grant_sas(grant.klass, grant.signed)
        # Independent of intent.sas: the typed confirmation is the operator entry.
        if normalized_sas != computed:
            raise FailClosed("SAS")
        # Intent sheet must also carry the matching SAS (machine field equality).
        if intent.sas != computed:
            raise FailClosed("SAS")
        compare_intent(grant, registry, intent)

        derived = _grant_derived_intent(grant, registry)
        typed_fields = _intent_public_fields(intent)
        # Force the typed SAS field in the public record to the normalized operator entry.
        typed_fields = dict(typed_fields)
        typed_fields["sas"] = normalized_sas
        record_body = {
            "typed_sas": normalized_sas,
            "computed_sas": computed,
            "typed_intent": typed_fields,
            "grant_derived_intent": derived,
            "grant_raw_digest": raw_digest,
            "signed_region_digest": _hex_digest(grant.signed),
            "sas_domain": SAS_DOMAIN.decode("ascii"),
            "sas_bits": 60,
        }
        record = TypedEntryRecord(
            requirement_id="C07",
            decision=CHECKS_PASSED,
            reason="C07_TYPED_ENTRY",
            typed_sas=normalized_sas,
            computed_sas=computed,
            typed_intent=typed_fields,
            grant_derived_intent=derived,
            grant_raw_digest=raw_digest,
            record_digest=_typed_record_digest(record_body),
            authority_usable=False,
        )
        return _pass(
            "C07_TYPED_ENTRY",
            requirement_id="C07",
            typed_entry_record=record.to_dict(),
            sas=computed,
        )
    except FailClosed as exc:
        return _refuse(
            exc.reason,
            requirement_id="C07",
            grant_raw_digest=raw_digest,
            typed_entry_record={
                "requirement_id": "C07",
                "decision": FAIL_CLOSED,
                "reason": exc.reason,
                "typed_sas": typed_sas_safe,
                "computed_sas": "",
                "typed_intent": {},
                "grant_derived_intent": {},
                "grant_raw_digest": raw_digest,
                "record_digest": "",
                "authority_usable": False,
            },
        )


@guard
def consumer_confirm_from_signed_bytes(
    grant_raw: bytes,
    registry_raw: bytes,
    tokens: list[OwnerToken],
    floors: Floors,
    crown_image_entry_id: bytes,
    typed_sas: str,
    intent: IntentSheet,
    outstanding_challenge: bytes,
    own_role_id: bytes,
    observed_environment: bytes,
    *,
    highest_authenticated_version=_MISSING,
    challenge_ledger=_MISSING,
    claimed_card: str | None = None,
    **extra,
) -> Result:
    """Combined C06 then C07 path used by consumer confirmation drills.

    Renders from signed bytes first; only then accepts typed SAS / Intent Sheet.
    Either refusal short-circuits. Never grants authority.
    """
    if extra:
        return _refuse("UNEXPECTED_ARGUMENT", requirement_id="C06+C07")
    rendered = render_from_signed_bytes(
        grant_raw,
        registry_raw,
        tokens,
        floors,
        crown_image_entry_id,
        claimed_card=claimed_card,
    )
    if rendered.decision != CHECKS_PASSED:
        return rendered
    typed = verify_typed_sas_and_intent(
        grant_raw,
        registry_raw,
        tokens,
        floors,
        crown_image_entry_id,
        typed_sas,
        intent,
        outstanding_challenge,
        own_role_id,
        observed_environment,
        highest_authenticated_version=highest_authenticated_version,
        challenge_ledger=challenge_ledger,
    )
    if typed.decision != CHECKS_PASSED:
        return typed
    payload = _deny_authority()
    payload["requirement_id"] = "C06+C07"
    payload["evidence_kind"] = "EVIDENCE"
    payload["rendered_card_evidence"] = rendered.payload["rendered_card_evidence"]
    payload["typed_entry_record"] = typed.payload["typed_entry_record"]
    payload["sas"] = typed.payload["sas"]
    payload["card"] = rendered.payload["card"]
    return Result(CHECKS_PASSED, "C06_C07_CONFIRMED", MappingProxyType(payload))
