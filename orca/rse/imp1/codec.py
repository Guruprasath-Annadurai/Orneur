"""Canonical binary codec for registry entries, registry objects and OCG1 grants.

No JSON. Decode then re-encode must reproduce the input bytes. Unknown versions,
unknown types, unknown states, truncated buffers, extra bytes and non-canonical
padding are rejected.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from types import MappingProxyType

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from orca.rse.imp1.merkle import merkle_root
from orca.rse.imp1.profiles import (
    APPROVAL_STATES,
    APPROVED,
    ARTIFACT_FORMATS,
    DATA_ONLY_TENSOR_V1,
    APPROVABLE_ARTIFACT_FORMATS,
    CLASS_SIG_LEN,
    CLASS_TOTAL,
    CODE,
    COMMON_LEN,
    CORPUS,
    DEST_KINDS,
    DESTINATION,
    ENROLMENT,
    ENTRY_TYPES,
    FAMILY_BEARING_TYPES,
    FAMILY_LABELS,
    FAMILY_NEUTRAL_TYPES,
    FOUNDATION_MODEL,
    GRANT_MAGIC,
    GRANT_SIG_DOMAIN,
    GRANT_VERSION,
    HOLDOUT_SET,
    K_SCENARIOS,
    KNOWN_CLASSES,
    LIFECYCLE_STATES,
    MAX_DESTINATIONS,
    MAX_ENTRIES,
    MAX_REGISTRY_BYTES,
    MODEL,
    NAME_LEN,
    POLICY,
    REG_FORMAT_VERSION,
    REG_MAGIC,
    REG_SIG_DOMAIN,
    RETIRE_REASONS,
    RETIREMENT_STATES,
    ROLE_IMAGE,
    ROLE_TYPES,
    TAIL_LEN,
    TOKEN_ID_DOMAIN,
    TOKENIZER,
    W_FORMAT_NO_CODE,
    WITNESS_REQUIREMENTS,
)
from orca.rse.imp1.verdict import FailClosed

_NAME_RE = re.compile(rb"[A-Za-z0-9._-]{1,64}\Z")
_REV_RE = re.compile(rb"[A-Za-z0-9._-]{1,64}\Z")
_PATH_COMPONENTS = {b".", b".."}
_CONFUSABLE = str.maketrans({"0": "0", "O": "0", "1": "1", "l": "1", "I": "1"})
_U32 = 0xFFFFFFFF
_U64 = 0xFFFFFFFFFFFFFFFF


def _u32(n: int) -> bytes:
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= _U32:
        raise FailClosed("U32")
    return struct.pack(">I", n)


def _u64(n: int) -> bytes:
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= _U64:
        raise FailClosed("U64")
    return struct.pack(">Q", n)


def _b32(buf: bytes, reason: str) -> bytes:
    if not isinstance(buf, (bytes, bytearray)) or len(buf) != 32:
        raise FailClosed(reason)
    return bytes(buf)


def name_skeleton(name: str) -> str:
    return name.translate(_CONFUSABLE)


def pack_name(name: str) -> bytes:
    if not isinstance(name, str):
        raise FailClosed("NAME_TYPE")
    try:
        raw = name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise FailClosed("NAME_CHARSET") from exc
    if raw != name.encode("utf-8"):
        raise FailClosed("NAME_CHARSET")
    if not _NAME_RE.fullmatch(raw) or raw in _PATH_COMPONENTS:
        raise FailClosed("NAME_CHARSET")
    return raw + bytes(NAME_LEN - len(raw))


def unpack_name(field: bytes) -> str:
    if len(field) != NAME_LEN:
        raise FailClosed("NAME_LEN")
    if b"\x00" in field:
        raw, pad = field.split(b"\x00", 1)
        if pad != bytes(len(pad)) or not raw:
            raise FailClosed("NAME_PADDING")
    else:
        raw = field
    if not _NAME_RE.fullmatch(raw):
        raise FailClosed("NAME_CHARSET")
    # Re-pad and compare so a non-zero byte hiding past the first NUL cannot pass.
    if pack_name(raw.decode("ascii")) != field:
        raise FailClosed("NAME_PADDING")
    return raw.decode("ascii")


@dataclass(frozen=True)
class Entry:
    entry_type: int
    name: str
    version: int
    artifact_digest: bytes
    provenance_digest: bytes
    producer_entry_id: bytes
    approval_state: int
    min_permitted_version: int
    policy_entry_id: bytes
    signing_key_id: bytes
    approval_evidence_checkpoint: bytes
    not_after: int
    tail: bytes
    canonical: bytes
    entry_id: bytes


def entry_id_of(canonical: bytes) -> bytes:
    return hashlib.sha256(canonical).digest()


def _pack_common(
    entry_type: int,
    name: str,
    version: int,
    artifact_digest: bytes,
    provenance_digest: bytes,
    producer_entry_id: bytes,
    approval_state: int,
    min_permitted_version: int,
    policy_entry_id: bytes,
    signing_key_id: bytes,
    approval_evidence_checkpoint: bytes,
    not_after: int,
) -> bytes:
    if entry_type not in ENTRY_TYPES:
        raise FailClosed("ENTRY_TYPE")
    if approval_state not in APPROVAL_STATES:
        raise FailClosed("APPROVAL_STATE")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise FailClosed("VERSION_TYPE")
    if not isinstance(min_permitted_version, int) or isinstance(min_permitted_version, bool):
        raise FailClosed("MIN_VERSION_TYPE")
    # version < min_permitted_version stays decodable (Clarification 1 §10). Use is a later check.
    return b"".join(
        (
            bytes([entry_type]),
            pack_name(name),
            _u32(version),
            _b32(artifact_digest, "ARTIFACT_DIGEST"),
            _b32(provenance_digest, "PROVENANCE_DIGEST"),
            _b32(producer_entry_id, "PRODUCER"),
            bytes([approval_state]),
            _u32(min_permitted_version),
            _b32(policy_entry_id, "POLICY_ID"),
            _b32(signing_key_id, "SIGNING_KEY"),
            _b32(approval_evidence_checkpoint, "CHECKPOINT"),
            _u64(not_after),
        )
    )


def encode_entry(entry_type: int, name: str, version: int, *, artifact_digest: bytes, provenance_digest: bytes,
                 producer_entry_id: bytes, approval_state: int, min_permitted_version: int, policy_entry_id: bytes,
                 signing_key_id: bytes, approval_evidence_checkpoint: bytes, not_after: int, tail: bytes) -> Entry:
    if not isinstance(tail, (bytes, bytearray)):
        raise FailClosed("TAIL_TYPE")
    tail_b = bytes(tail)
    if len(tail_b) != TAIL_LEN[entry_type]:
        raise FailClosed("TAIL_LEN")
    _check_tail(entry_type, tail_b)
    if entry_type in FAMILY_NEUTRAL_TYPES and policy_entry_id != bytes(32):
        raise FailClosed("POLICY_NEUTRAL")
    if entry_type in FAMILY_BEARING_TYPES and policy_entry_id == bytes(32):
        raise FailClosed("POLICY_SCOPE")
    if entry_type == FOUNDATION_MODEL and approval_state == APPROVED:
        if tail_b[256] not in APPROVABLE_ARTIFACT_FORMATS:
            raise FailClosed("ARTIFACT_FORMAT")
        if tail_b[257:289] == bytes(32) or provenance_digest == bytes(32):
            raise FailClosed("INCOMPLETE_FOUNDATION")
    common = _pack_common(
        entry_type, name, version, artifact_digest, provenance_digest, producer_entry_id, approval_state,
        min_permitted_version, policy_entry_id, signing_key_id, approval_evidence_checkpoint, not_after,
    )
    if len(common) != COMMON_LEN:
        raise FailClosed("COMMON_LEN")
    canonical = common + tail_b
    return Entry(
        entry_type, name, version, bytes(artifact_digest), bytes(provenance_digest), bytes(producer_entry_id),
        approval_state, min_permitted_version, bytes(policy_entry_id), bytes(signing_key_id),
        bytes(approval_evidence_checkpoint), not_after, tail_b, canonical, entry_id_of(canonical),
    )


def _check_tail(entry_type: int, tail: bytes) -> None:
    if entry_type == ROLE_IMAGE:
        _u32_at(tail, 0)
    elif entry_type == FOUNDATION_MODEL:
        _check_revision(tail[64:128])
        if tail[256] not in ARTIFACT_FORMATS:
            raise FailClosed("ARTIFACT_FORMAT")
    elif entry_type == MODEL:
        if tail[96] not in LIFECYCLE_STATES:
            raise FailClosed("LIFECYCLE")
    elif entry_type == CORPUS:
        if tail[164] not in RETIREMENT_STATES:
            raise FailClosed("RETIREMENT")
    elif entry_type == ENROLMENT:
        if tail[0] not in ROLE_TYPES:
            raise FailClosed("ROLE_TYPE")
    elif entry_type == POLICY:
        _check_policy_tail(tail)
    elif entry_type == DESTINATION:
        if tail[0] not in DEST_KINDS:
            raise FailClosed("DESTINATION_KIND")
        if tail[1:33] == bytes(32):
            raise FailClosed("DESTINATION")
    elif entry_type == HOLDOUT_SET:
        _u32_at(tail, 32)
        _u32_at(tail, 36)


def _check_revision(field: bytes) -> None:
    if len(field) != 64:
        raise FailClosed("REVISION_LEN")
    if b"\x00" in field:
        raw, pad = field.split(b"\x00", 1)
        if pad != bytes(len(pad)) or not raw:
            raise FailClosed("REVISION_CHARSET")
    else:
        raw = field
    if not _REV_RE.fullmatch(raw):
        raise FailClosed("REVISION_CHARSET")


def _check_policy_tail(tail: bytes) -> None:
    if len(tail) != TAIL_LEN[POLICY]:
        raise FailClosed("TAIL_LEN")
    witness = tail[36]
    allowed = tail[37]
    if witness not in WITNESS_REQUIREMENTS:
        raise FailClosed("WITNESS_REQUIREMENT")
    if allowed == 0:
        raise FailClosed("OPERATION_SCOPE")
    count = tail[70]
    if count > MAX_DESTINATIONS:
        raise FailClosed("DESTINATION_COUNT")
    slots = [tail[71 + i * 32:71 + (i + 1) * 32] for i in range(MAX_DESTINATIONS)]
    for index, slot in enumerate(slots):
        if index < count:
            if slot == bytes(32):
                raise FailClosed("DESTINATION")
            if index and slot <= slots[index - 1]:
                raise FailClosed("DESTINATION_ORDER")
        elif slot != bytes(32):
            raise FailClosed("DESTINATION_PADDING")


def _u32_at(buf: bytes, offset: int) -> int:
    return struct.unpack_from(">I", buf, offset)[0]


def decode_entry(buf: bytes) -> tuple[Entry, int]:
    data = bytes(buf)
    if len(data) < 1:
        raise FailClosed("TRUNCATED")
    entry_type = data[0]
    if entry_type not in ENTRY_TYPES:
        raise FailClosed("ENTRY_TYPE")
    need = COMMON_LEN + TAIL_LEN[entry_type]
    if len(data) < need:
        raise FailClosed("TRUNCATED")
    chunk = data[:need]
    common = chunk[:COMMON_LEN]
    name = unpack_name(common[1:65])
    version = struct.unpack_from(">I", common, 65)[0]
    artifact = common[69:101]
    provenance = common[101:133]
    producer = common[133:165]
    approval = common[165]
    if approval not in APPROVAL_STATES:
        raise FailClosed("APPROVAL_STATE")
    min_version = struct.unpack_from(">I", common, 166)[0]
    policy_id = common[170:202]
    signing_key = common[202:234]
    checkpoint = common[234:266]
    not_after = struct.unpack_from(">Q", common, 266)[0]
    tail = chunk[COMMON_LEN:]
    _check_tail(entry_type, tail)
    entry = encode_entry(
        entry_type, name, version, artifact_digest=artifact, provenance_digest=provenance,
        producer_entry_id=producer, approval_state=approval, min_permitted_version=min_version,
        policy_entry_id=policy_id, signing_key_id=signing_key, approval_evidence_checkpoint=checkpoint,
        not_after=not_after, tail=tail,
    )
    if entry.canonical != chunk:
        raise FailClosed("NONCANONICAL")
    return entry, need


def parse_role_image(tail: bytes) -> tuple[int, bytes]:
    generation = struct.unpack_from(">I", tail, 0)[0]
    return generation, tail[4:36]


def parse_foundation(tail: bytes) -> dict:
    return {
        "family_id": tail[0:32],
        "foundation_model_id": tail[32:64],
        "foundation_revision": tail[64:128],
        "tokenizer_entry_id": tail[128:160],
        "weights_digest": tail[160:192],
        "license_record_digest": tail[192:224],
        "architecture_config_digest": tail[224:256],
        "artifact_format": tail[256],
        "inspection_evidence_digest": tail[257:289],
    }


def parse_tokenizer(tail: bytes) -> dict:
    return {"tokenizer_id": tail[0:32], "vocab_digest": tail[32:64]}


def parse_model(tail: bytes) -> dict:
    return {
        "family_id": tail[0:32],
        "parent_entry_id": tail[32:64],
        "weights_digest": tail[64:96],
        "lifecycle_state": tail[96],
        "qualification_record_digest": tail[97:129],
    }


def parse_corpus(tail: bytes) -> dict:
    return {
        "corpus_id": tail[0:32],
        "corpus_version": struct.unpack_from(">I", tail, 32)[0],
        "manifest_digest": tail[36:68],
        "source_provenance_digest": tail[68:100],
        "witness_acceptance_record_digest": tail[100:132],
        "contamination_status_ref": tail[132:164],
        "retirement_state": tail[164],
    }


def parse_enrolment(tail: bytes) -> dict:
    return {
        "role_type": tail[0],
        "ed25519_public_key": tail[1:33],
        "x25519_public_key": tail[33:65],
        "environment_measurement": tail[65:97],
        "key_version": struct.unpack_from(">I", tail, 97)[0],
    }


def parse_policy(tail: bytes) -> dict:
    count = tail[70]
    slots = tuple(tail[71 + i * 32:71 + (i + 1) * 32] for i in range(count))
    return {
        "max_batch_bytes": struct.unpack_from(">Q", tail, 0)[0],
        "max_runtime_s": struct.unpack_from(">I", tail, 8)[0],
        "max_spend": struct.unpack_from(">Q", tail, 12)[0],
        "max_run": struct.unpack_from(">I", tail, 20)[0],
        "max_query_budget": struct.unpack_from(">I", tail, 24)[0],
        "max_bit_budget": struct.unpack_from(">I", tail, 28)[0],
        "min_grant_schema_version": struct.unpack_from(">I", tail, 32)[0],
        "witness_requirement": tail[36],
        "allowed_operations": tail[37],
        "family_scope": tail[38:70],
        "destination_count": count,
        "permitted_destinations": slots,
    }


def parse_destination(tail: bytes) -> dict:
    return {"kind": tail[0], "identifier_digest": tail[1:33]}


def parse_holdout(tail: bytes) -> dict:
    return {
        "holdout_id": tail[0:32],
        "bit_budget_total": struct.unpack_from(">I", tail, 32)[0],
        "query_budget_total": struct.unpack_from(">I", tail, 36)[0],
    }


def pack_role_image(generation: int, measurement_set_digest: bytes) -> bytes:
    return _u32(generation) + _b32(measurement_set_digest, "MEASUREMENT")


def pack_revision(revision: bytes | str) -> bytes:
    if isinstance(revision, str):
        try:
            raw = revision.encode("ascii")
        except UnicodeEncodeError as exc:
            raise FailClosed("REVISION_CHARSET") from exc
    elif isinstance(revision, (bytes, bytearray)):
        raw = bytes(revision)
    else:
        raise FailClosed("REVISION_CHARSET")
    if len(raw) == 64:
        _check_revision(raw)
        return raw
    if len(raw) > 64:
        raise FailClosed("REVISION_LEN")
    padded = raw + bytes(64 - len(raw))
    _check_revision(padded)
    return padded


def pack_foundation(*, family_id: bytes, foundation_model_id: bytes, foundation_revision: bytes | str,
                    tokenizer_entry_id: bytes, weights_digest: bytes, license_record_digest: bytes,
                    architecture_config_digest: bytes, artifact_format: int = DATA_ONLY_TENSOR_V1,
                    inspection_evidence_digest: bytes) -> bytes:
    if artifact_format not in ARTIFACT_FORMATS:
        raise FailClosed("ARTIFACT_FORMAT")
    return b"".join((
        _b32(family_id, "FAMILY"), _b32(foundation_model_id, "FOUNDATION_ID"), pack_revision(foundation_revision),
        _b32(tokenizer_entry_id, "TOKENIZER"), _b32(weights_digest, "WEIGHTS"),
        _b32(license_record_digest, "LICENSE"), _b32(architecture_config_digest, "CONFIG"),
        bytes([artifact_format]), _b32(inspection_evidence_digest, "INSPECTION"),
    ))


def pack_tokenizer(tokenizer_id: bytes, vocab_digest: bytes) -> bytes:
    return _b32(tokenizer_id, "TOKENIZER_ID") + _b32(vocab_digest, "VOCAB")


def pack_model(*, family_id: bytes, parent_entry_id: bytes, weights_digest: bytes, lifecycle_state: int,
               qualification_record_digest: bytes) -> bytes:
    if lifecycle_state not in LIFECYCLE_STATES:
        raise FailClosed("LIFECYCLE")
    return b"".join((
        _b32(family_id, "FAMILY"), _b32(parent_entry_id, "PARENT"), _b32(weights_digest, "WEIGHTS"),
        bytes([lifecycle_state]), _b32(qualification_record_digest, "QUALIFICATION_RECORD"),
    ))


def pack_corpus(*, corpus_id: bytes, corpus_version: int, manifest_digest: bytes, source_provenance_digest: bytes,
                witness_acceptance_record_digest: bytes, contamination_status_ref: bytes, retirement_state: int) -> bytes:
    if retirement_state not in RETIREMENT_STATES:
        raise FailClosed("RETIREMENT")
    return b"".join((
        _b32(corpus_id, "CORPUS_ID"), _u32(corpus_version), _b32(manifest_digest, "MANIFEST"),
        _b32(source_provenance_digest, "SOURCE"), _b32(witness_acceptance_record_digest, "WITNESS_ACCEPTANCE"),
        _b32(contamination_status_ref, "CONTAMINATION"), bytes([retirement_state]),
    ))


def pack_enrolment(*, role_type: int, ed25519_public_key: bytes, x25519_public_key: bytes,
                   environment_measurement: bytes, key_version: int) -> bytes:
    if role_type not in ROLE_TYPES:
        raise FailClosed("ROLE_TYPE")
    return b"".join((
        bytes([role_type]), _b32(ed25519_public_key, "ED25519"), _b32(x25519_public_key, "X25519"),
        _b32(environment_measurement, "ENVIRONMENT"), _u32(key_version),
    ))


def pack_policy(*, max_batch_bytes: int, max_runtime_s: int, max_spend: int, max_run: int, max_query_budget: int,
                max_bit_budget: int, min_grant_schema_version: int, witness_requirement: int, allowed_operations: int,
                family_scope: bytes, destination_ids: list | None = None) -> bytes:
    if witness_requirement not in WITNESS_REQUIREMENTS:
        raise FailClosed("WITNESS_REQUIREMENT")
    if not isinstance(allowed_operations, int) or isinstance(allowed_operations, bool) or not 1 <= allowed_operations <= 255:
        raise FailClosed("OPERATION_SCOPE")
    ids = [] if destination_ids is None else list(destination_ids)
    if len(ids) > MAX_DESTINATIONS:
        raise FailClosed("DESTINATION_COUNT")
    packed_ids = [_b32(item, "DEST_ID") for item in ids]
    for index in range(1, len(packed_ids)):
        if packed_ids[index] <= packed_ids[index - 1]:
            raise FailClosed("DESTINATION_ORDER")
    if any(item == bytes(32) for item in packed_ids):
        raise FailClosed("DESTINATION")
    slots = b"".join(packed_ids) + bytes(32 * (MAX_DESTINATIONS - len(packed_ids)))
    tail = b"".join((
        _u64(max_batch_bytes), _u32(max_runtime_s), _u64(max_spend), _u32(max_run), _u32(max_query_budget),
        _u32(max_bit_budget), _u32(min_grant_schema_version), bytes([witness_requirement, allowed_operations]),
        _b32(family_scope, "FAMILY"), bytes([len(packed_ids)]), slots,
    ))
    if len(tail) != TAIL_LEN[POLICY]:
        raise FailClosed("TAIL_LEN")
    _check_policy_tail(tail)
    return tail


def pack_destination(*, kind: int, identifier_digest: bytes) -> bytes:
    if kind not in DEST_KINDS:
        raise FailClosed("DESTINATION_KIND")
    digest = _b32(identifier_digest, "DEST_ID")
    if digest == bytes(32):
        raise FailClosed("DESTINATION")
    return bytes([kind]) + digest


def pack_holdout(*, holdout_id: bytes, bit_budget_total: int, query_budget_total: int) -> bytes:
    return _b32(holdout_id, "HOLDOUT") + _u32(bit_budget_total) + _u32(query_budget_total)


def synthetic_family_id(label: str) -> bytes:
    """Domain-separated fixture id. Not a selected foundation model."""
    if label not in FAMILY_LABELS:
        raise FailClosed("UNKNOWN_FAMILY")
    return hashlib.sha256(b"SYNTHETIC-RSE-FAMILY\x00" + label.encode("ascii")).digest()


def token_id(public_key: bytes) -> bytes:
    return hashlib.sha256(TOKEN_ID_DOMAIN + b"\x00" + _b32(public_key, "TOKEN_KEY")).digest()


def public_of(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


@dataclass(frozen=True)
class OwnerToken:
    slot: int
    public_key: bytes


@dataclass(frozen=True)
class Registry:
    format_version: int
    registry_version: int
    previous_registry_root: bytes
    entries: tuple
    registry_root: bytes
    body: bytes
    signatures: tuple
    raw: bytes

    def by_id(self, entry_id: bytes):
        for entry in self.entries:
            if entry.entry_id == entry_id:
                return entry
        return None


def _reject_duplicate_semantics(entries: list[Entry]) -> None:
    seen_id = set()
    seen_key = set()
    skeletons: dict[str, str] = {}
    for entry in entries:
        if entry.entry_id in seen_id:
            raise FailClosed("DUPLICATE_ENTRY")
        seen_id.add(entry.entry_id)
        key = (entry.entry_type, entry.name, entry.version)
        if key in seen_key:
            raise FailClosed("DUPLICATE_NAME")
        seen_key.add(key)
        sk = name_skeleton(entry.name)
        previous = skeletons.get(sk)
        if previous is not None and previous != entry.name:
            raise FailClosed("CONFUSABLE_NAME")
        skeletons[sk] = entry.name


def _require_ascending(entries: list[Entry]) -> None:
    previous = None
    for entry in entries:
        if previous is not None and entry.entry_id <= previous:
            if entry.entry_id == previous:
                raise FailClosed("DUPLICATE_ENTRY")
            raise FailClosed("ENTRY_ORDER")
        previous = entry.entry_id


def build_registry_body(registry_version: int, previous_registry_root: bytes, entries: list[Entry]) -> bytes:
    if not isinstance(registry_version, int) or isinstance(registry_version, bool) or registry_version < 1:
        raise FailClosed("REGISTRY_VERSION")
    previous = _b32(previous_registry_root, "PREVIOUS_ROOT")
    if registry_version == 1 and previous != bytes(32):
        raise FailClosed("GENESIS_PREVIOUS")
    if registry_version > 1 and previous == bytes(32):
        raise FailClosed("MISSING_PREVIOUS")
    if not entries or len(entries) > MAX_ENTRIES:
        raise FailClosed("ENTRY_COUNT")
    _reject_duplicate_semantics(entries)
    _require_ascending(entries)
    root = merkle_root([entry.entry_id for entry in entries])
    body = b"".join((
        REG_MAGIC, bytes([REG_FORMAT_VERSION]), _u32(registry_version), previous, _u32(len(entries)),
        *(entry.canonical for entry in entries), root,
    ))
    if len(body) > MAX_REGISTRY_BYTES:
        raise FailClosed("REGISTRY_TOO_LARGE")
    return body


def sign_registry(body: bytes, signers: list[tuple[int, Ed25519PrivateKey]]) -> bytes:
    if len(signers) != 2:
        raise FailClosed("SIG_COUNT")
    _require_distinct(signers)
    if len(body) < 5 or body[:4] != REG_MAGIC or body[4] != REG_FORMAT_VERSION:
        raise FailClosed("REGISTRY_BODY")
    domain = REG_SIG_DOMAIN + b"\x00" + bytes([body[4]])
    return body + _pack_sigs(domain, body, signers)


def _require_distinct(signers: list[tuple[int, Ed25519PrivateKey]]) -> None:
    slots = []
    pubs = []
    for slot, key in signers:
        if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot <= 255:
            raise FailClosed("SLOT")
        slots.append(slot)
        pubs.append(public_of(key))
    if len(set(slots)) != len(slots) or len(set(pubs)) != len(pubs):
        raise FailClosed("DUP_SIGNER")


def _pack_sigs(domain: bytes, body: bytes, signers: list[tuple[int, Ed25519PrivateKey]]) -> bytes:
    out = []
    for slot, key in signers:
        signature = key.sign(domain + body)
        if len(signature) != 64:
            raise FailClosed("SIG_LEN")
        out.append(bytes([slot]) + signature)
    return b"".join(out)


def parse_registry(raw: bytes, *, expect_signatures: bool = True) -> Registry:
    data = bytes(raw)
    if len(data) > MAX_REGISTRY_BYTES:
        raise FailClosed("REGISTRY_TOO_LARGE")
    if len(data) < 4 + 1 + 4 + 32 + 4 + 32:
        raise FailClosed("TRUNCATED")
    if data[:4] != REG_MAGIC:
        raise FailClosed("MAGIC")
    if data[4] != REG_FORMAT_VERSION:
        raise FailClosed("UNKNOWN_VERSION")
    registry_version = struct.unpack_from(">I", data, 5)[0]
    previous = data[9:41]
    count = struct.unpack_from(">I", data, 41)[0]
    if registry_version < 1:
        raise FailClosed("REGISTRY_VERSION")
    if count < 1 or count > MAX_ENTRIES:
        raise FailClosed("ENTRY_COUNT")
    offset = 45
    entries = []
    for _ in range(count):
        if offset >= len(data):
            raise FailClosed("TRUNCATED")
        try:
            entry, consumed = decode_entry(data[offset:])
        except FailClosed:
            raise
        entries.append(entry)
        offset += consumed
        if offset > len(data):
            raise FailClosed("TRUNCATED")
    if len(data) - offset < 32:
        raise FailClosed("TRUNCATED")
    root = data[offset:offset + 32]
    offset += 32
    body = data[:offset]
    _reject_duplicate_semantics(entries)
    _require_ascending(entries)
    if registry_version == 1 and previous != bytes(32):
        raise FailClosed("GENESIS_PREVIOUS")
    if registry_version > 1 and previous == bytes(32):
        raise FailClosed("MISSING_PREVIOUS")
    expected_root = merkle_root([entry.entry_id for entry in entries])
    if root != expected_root:
        raise FailClosed("REGISTRY_ROOT")
    rebuilt = build_registry_body(registry_version, previous, entries)
    if rebuilt != body:
        raise FailClosed("NONCANONICAL")
    if not expect_signatures:
        if offset != len(data):
            raise FailClosed("TRAILING")
        return Registry(REG_FORMAT_VERSION, registry_version, previous, tuple(entries), root, body, (), data)
    if len(data) - offset != 130:
        raise FailClosed("TRAILING" if len(data) - offset > 130 else "TRUNCATED")
    signatures = _split_sigs(data[offset:], 2)
    return Registry(REG_FORMAT_VERSION, registry_version, previous, tuple(entries), root, body, signatures, data)


def _split_sigs(buf: bytes, count: int) -> tuple:
    if len(buf) != count * 65:
        raise FailClosed("SIG_LEN")
    out = []
    slots = set()
    for i in range(count):
        slot = buf[i * 65]
        sig = buf[i * 65 + 1:i * 65 + 65]
        if slot in slots:
            raise FailClosed("DUP_SIGNER")
        slots.add(slot)
        if len(sig) != 64:
            raise FailClosed("SIG_LEN")
        out.append((slot, sig))
    return tuple(out)


def verify_registry_signatures(registry: Registry, tokens: list[OwnerToken]) -> None:
    if len(registry.signatures) != 2:
        raise FailClosed("SIG_COUNT")
    by_slot = {}
    for token in tokens:
        if token.slot in by_slot or token.public_key in by_slot.values():
            raise FailClosed("DUP_SIGNER")
        by_slot[token.slot] = token.public_key
    seen_keys = []
    domain = REG_SIG_DOMAIN + b"\x00" + bytes([registry.format_version])
    message = domain + registry.body
    for slot, signature in registry.signatures:
        public = by_slot.get(slot)
        if public is None:
            raise FailClosed("UNKNOWN_TOKEN")
        _verify(public, message, signature)
        seen_keys.append(public)
    if len(set(seen_keys)) != 2:
        raise FailClosed("DUP_SIGNER")


def _verify(public_key: bytes, message: bytes, signature: bytes) -> None:
    if len(public_key) != 32 or len(signature) != 64:
        raise FailClosed("SIG_LEN")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except Exception as exc:
        raise FailClosed("BAD_SIGNATURE") from exc


@dataclass(frozen=True)
class Grant:
    version: int
    klass: int
    grant_id: bytes
    owner_authority_version: int
    incident_epoch: int
    registry_version: int
    registry_root: bytes
    policy_entry_id: bytes
    target_role_id: bytes
    env_measurement_digest: bytes
    code_entry_id: bytes
    challenge: bytes
    prev_role_checkpoint: bytes
    created_at: int
    not_after: int
    max_runtime_s: int
    tail: dict
    signed: bytes
    signatures: tuple
    raw: bytes


def sign_grant(signed_body: bytes, signers: list[tuple[int, Ed25519PrivateKey]]) -> bytes:
    """Sign an already-canonical grant prefix. Does not consult the registry."""
    if len(signed_body) < 6 or signed_body[:4] != GRANT_MAGIC:
        raise FailClosed("GRANT_BODY")
    if signed_body[4] != GRANT_VERSION:
        raise FailClosed("UNKNOWN_VERSION")
    klass = signed_body[5]
    if klass not in KNOWN_CLASSES:
        raise FailClosed("GRANT_CLASS")
    sig_len = CLASS_SIG_LEN[klass]
    if len(signers) * 65 != sig_len:
        raise FailClosed("SIG_COUNT")
    _require_distinct(signers)
    domain = GRANT_SIG_DOMAIN + b"\x00" + bytes([klass])
    raw = signed_body + _pack_sigs(domain, signed_body, signers)
    if len(raw) != CLASS_TOTAL[klass]:
        raise FailClosed("GRANT_LEN")
    return raw


def parse_grant(raw: bytes) -> Grant:
    data = bytes(raw)
    if len(data) < 6:
        raise FailClosed("TRUNCATED")
    if data[:4] != GRANT_MAGIC:
        raise FailClosed("MAGIC")
    if data[4] != GRANT_VERSION:
        raise FailClosed("UNKNOWN_VERSION")
    klass = data[5]
    if klass not in KNOWN_CLASSES:
        raise FailClosed("GRANT_CLASS")
    if len(data) != CLASS_TOTAL[klass]:
        raise FailClosed("GRANT_LEN")
    sig_len = CLASS_SIG_LEN[klass]
    signed = data[:-sig_len]
    signatures = _split_sigs(data[-sig_len:], sig_len // 65)
    view = _unpack_common(signed, klass)
    tail = _freeze_tail(_unpack_tail(klass, signed[278:]))
    rebuilt = _repack_signed(view, klass, tail)
    if rebuilt != signed:
        raise FailClosed("NONCANONICAL")
    return Grant(
        version=view["version"], klass=klass, grant_id=view["grant_id"],
        owner_authority_version=view["owner_authority_version"], incident_epoch=view["incident_epoch"],
        registry_version=view["registry_version"], registry_root=view["registry_root"],
        policy_entry_id=view["policy_entry_id"], target_role_id=view["target_role_id"],
        env_measurement_digest=view["env_measurement_digest"], code_entry_id=view["code_entry_id"],
        challenge=view["challenge"], prev_role_checkpoint=view["prev_role_checkpoint"],
        created_at=view["created_at"], not_after=view["not_after"], max_runtime_s=view["max_runtime_s"],
        tail=tail, signed=signed, signatures=signatures, raw=data,
    )


def _unpack_common(signed: bytes, klass: int) -> dict:
    if len(signed) < 278:
        raise FailClosed("TRUNCATED")
    return {
        "version": signed[4],
        "klass": klass,
        "grant_id": signed[6:22],
        "owner_authority_version": struct.unpack_from(">I", signed, 22)[0],
        "incident_epoch": struct.unpack_from(">I", signed, 26)[0],
        "registry_version": struct.unpack_from(">I", signed, 30)[0],
        "registry_root": signed[34:66],
        "policy_entry_id": signed[66:98],
        "target_role_id": signed[98:130],
        "env_measurement_digest": signed[130:162],
        "code_entry_id": signed[162:194],
        "challenge": signed[194:226],
        "prev_role_checkpoint": signed[226:258],
        "created_at": struct.unpack_from(">Q", signed, 258)[0],
        "not_after": struct.unpack_from(">Q", signed, 266)[0],
        "max_runtime_s": struct.unpack_from(">I", signed, 274)[0],
    }


def _unpack_tail(klass: int, tail: bytes) -> dict:
    if klass == ord("G"):
        if len(tail) != 140:
            raise FailClosed("TAIL_LEN")
        return {
            "corpus_entry_id": tail[0:32],
            "batch_count": struct.unpack_from(">I", tail, 32)[0],
            "batch_ceiling_bytes": struct.unpack_from(">Q", tail, 36)[0],
            "recipient_role_id": tail[44:76],
            "destination_entry_id": tail[76:108],
            "source_provenance_digest": tail[108:140],
        }
    if klass == ord("V"):
        if len(tail) != 80:
            raise FailClosed("TAIL_LEN")
        return {
            "sender_role_id": tail[0:32],
            "artifact_entry_id": tail[32:64],
            "seq_first": struct.unpack_from(">Q", tail, 64)[0],
            "seq_last": struct.unpack_from(">Q", tail, 72)[0],
        }
    if klass == ord("K"):
        if len(tail) != 298:
            raise FailClosed("TAIL_LEN")
        count = tail[41]
        if count > 8:
            raise FailClosed("REVOKED_COUNT")
        ids = [tail[42 + i * 32:42 + (i + 1) * 32] for i in range(8)]
        for i, item in enumerate(ids):
            if i < count:
                if item == bytes(32):
                    raise FailClosed("REVOKED_ID")
            elif item != bytes(32):
                raise FailClosed("REVOKED_PADDING")
        if tail[0] not in K_SCENARIOS:
            raise FailClosed("SCENARIO")
        if tail[9:41] == bytes(32):
            raise FailClosed("CHECKPOINT")
        return {
            "scenario": tail[0],
            "new_authority_version": struct.unpack_from(">I", tail, 1)[0],
            "new_epoch": struct.unpack_from(">I", tail, 5)[0],
            "checkpoint_root": tail[9:41],
            "revoked_count": count,
            "revoked_ids": tuple(ids[:count]),
        }
    if klass == ord("Q"):
        if len(tail) != 108:
            raise FailClosed("TAIL_LEN")
        return {
            "candidate_model_entry_id": tail[0:32],
            "chamber_env_digest": tail[32:64],
            "holdout_set_entry_id": tail[64:96],
            "run_budget": struct.unpack_from(">I", tail, 96)[0],
            "query_budget": struct.unpack_from(">I", tail, 100)[0],
            "bit_budget": struct.unpack_from(">I", tail, 104)[0],
        }
    if klass == ord("T"):
        if len(tail) != 140:
            raise FailClosed("TAIL_LEN")
        return {
            "corpus_entry_id": tail[0:32],
            "foundation_entry_id": tail[32:64],
            "family_id": tail[64:96],
            "spend_ceiling": struct.unpack_from(">Q", tail, 96)[0],
            "run_ceiling": struct.unpack_from(">I", tail, 104)[0],
            "provider_env_digest": tail[108:140],
        }
    if klass == ord("W"):
        if len(tail) != 169:
            raise FailClosed("TAIL_LEN")
        if tail[128] != W_FORMAT_NO_CODE:
            raise FailClosed("ARTIFACT_FORMAT")
        return {
            "model_entry_id": tail[0:32],
            "qualification_record_digest": tail[32:64],
            "source_entry_id": tail[64:96],
            "destination_entry_id": tail[96:128],
            "format": tail[128],
            "size_ceiling": struct.unpack_from(">Q", tail, 129)[0],
            "recipient_role_id": tail[137:169],
        }
    if klass == ord("D"):
        if len(tail) != 208:
            raise FailClosed("TAIL_LEN")
        return {
            "model_entry_id": tail[0:32],
            "serving_env_digest": tail[32:64],
            "policy_digest": tail[64:96],
            "tool_permission_digest": tail[96:128],
            "data_scope_digest": tail[128:160],
            "revocation_endpoint_entry_id": tail[160:192],
            "spend_ceiling": struct.unpack_from(">Q", tail, 192)[0],
            "run_ceiling": struct.unpack_from(">I", tail, 200)[0],
            "release_version": struct.unpack_from(">I", tail, 204)[0],
        }
    if klass == ord("R"):
        if len(tail) != 33:
            raise FailClosed("TAIL_LEN")
        if tail[32] not in RETIRE_REASONS:
            raise FailClosed("RETIRE_REASON")
        return {"object_entry_id": tail[0:32], "reason": tail[32]}
    raise FailClosed("GRANT_CLASS")


def _freeze_tail(tail: dict):
    frozen = {}
    for key, value in tail.items():
        if isinstance(value, (bytes, bytearray)):
            frozen[key] = bytes(value)
        elif isinstance(value, tuple):
            frozen[key] = tuple(bytes(item) if isinstance(item, (bytes, bytearray)) else item for item in value)
        else:
            frozen[key] = value
    return MappingProxyType(frozen)


def _repack_signed(view: dict, klass: int, tail: dict) -> bytes:
    common = b"".join((
        GRANT_MAGIC, bytes([GRANT_VERSION, klass]), view["grant_id"],
        _u32(view["owner_authority_version"]), _u32(view["incident_epoch"]), _u32(view["registry_version"]),
        view["registry_root"], view["policy_entry_id"], view["target_role_id"], view["env_measurement_digest"],
        view["code_entry_id"], view["challenge"], view["prev_role_checkpoint"],
        _u64(view["created_at"]), _u64(view["not_after"]), _u32(view["max_runtime_s"]),
    ))
    return common + _pack_tail(klass, tail)


def _pack_tail(klass: int, tail: dict) -> bytes:
    if klass == ord("G"):
        return b"".join((
            tail["corpus_entry_id"], _u32(tail["batch_count"]), _u64(tail["batch_ceiling_bytes"]),
            tail["recipient_role_id"], tail["destination_entry_id"], tail["source_provenance_digest"],
        ))
    if klass == ord("V"):
        return b"".join((
            tail["sender_role_id"], tail["artifact_entry_id"], _u64(tail["seq_first"]), _u64(tail["seq_last"]),
        ))
    if klass == ord("K"):
        ids = list(tail["revoked_ids"])
        if len(ids) != tail["revoked_count"] or tail["revoked_count"] > 8:
            raise FailClosed("REVOKED_COUNT")
        packed = b"".join(ids) + bytes(32 * (8 - len(ids)))
        return b"".join((
            bytes([tail["scenario"]]), _u32(tail["new_authority_version"]), _u32(tail["new_epoch"]),
            tail["checkpoint_root"], bytes([tail["revoked_count"]]), packed,
        ))
    if klass == ord("Q"):
        return b"".join((
            tail["candidate_model_entry_id"], tail["chamber_env_digest"], tail["holdout_set_entry_id"],
            _u32(tail["run_budget"]), _u32(tail["query_budget"]), _u32(tail["bit_budget"]),
        ))
    if klass == ord("T"):
        return b"".join((
            tail["corpus_entry_id"], tail["foundation_entry_id"], tail["family_id"],
            _u64(tail["spend_ceiling"]), _u32(tail["run_ceiling"]), tail["provider_env_digest"],
        ))
    if klass == ord("W"):
        return b"".join((
            tail["model_entry_id"], tail["qualification_record_digest"], tail["source_entry_id"],
            tail["destination_entry_id"], bytes([tail["format"]]), _u64(tail["size_ceiling"]),
            tail["recipient_role_id"],
        ))
    if klass == ord("D"):
        return b"".join((
            tail["model_entry_id"], tail["serving_env_digest"], tail["policy_digest"], tail["tool_permission_digest"],
            tail["data_scope_digest"], tail["revocation_endpoint_entry_id"], _u64(tail["spend_ceiling"]),
            _u32(tail["run_ceiling"]), _u32(tail["release_version"]),
        ))
    if klass == ord("R"):
        return tail["object_entry_id"] + bytes([tail["reason"]])
    raise FailClosed("GRANT_CLASS")


def build_grant_prefix(**fields) -> bytes:
    """Build the unsigned grant prefix from explicit fields. No display text is accepted."""
    klass = fields["klass"]
    if isinstance(klass, str):
        if len(klass) != 1:
            raise FailClosed("GRANT_CLASS")
        klass = ord(klass)
    view = {
        "version": GRANT_VERSION,
        "grant_id": _exact(fields["grant_id"], 16, "GRANT_ID"),
        "owner_authority_version": fields["owner_authority_version"],
        "incident_epoch": fields["incident_epoch"],
        "registry_version": fields["registry_version"],
        "registry_root": _b32(fields["registry_root"], "REGISTRY_ROOT"),
        "policy_entry_id": _b32(fields["policy_entry_id"], "POLICY_ID"),
        "target_role_id": _b32(fields["target_role_id"], "TARGET"),
        "env_measurement_digest": _b32(fields["env_measurement_digest"], "ENVIRONMENT"),
        "code_entry_id": _b32(fields["code_entry_id"], "CODE"),
        "challenge": _b32(fields["challenge"], "CHALLENGE"),
        "prev_role_checkpoint": _b32(fields["prev_role_checkpoint"], "CHECKPOINT"),
        "created_at": fields["created_at"],
        "not_after": fields["not_after"],
        "max_runtime_s": fields["max_runtime_s"],
    }
    tail = fields["tail"]
    return _repack_signed(view, klass, tail)


def _exact(buf: bytes, n: int, reason: str) -> bytes:
    if not isinstance(buf, (bytes, bytearray)) or len(buf) != n:
        raise FailClosed(reason)
    return bytes(buf)


def verify_grant_signatures(grant: Grant, tokens: list[OwnerToken]) -> None:
    expected = CLASS_SIG_LEN[grant.klass] // 65
    if len(grant.signatures) != expected:
        raise FailClosed("SIG_COUNT")
    by_slot = {}
    for token in tokens:
        if token.slot in by_slot:
            raise FailClosed("DUP_SIGNER")
        by_slot[token.slot] = token.public_key
    seen = []
    domain = GRANT_SIG_DOMAIN + b"\x00" + bytes([grant.klass])
    message = domain + grant.signed
    for slot, signature in grant.signatures:
        public = by_slot.get(slot)
        if public is None:
            raise FailClosed("UNKNOWN_TOKEN")
        _verify(public, message, signature)
        seen.append(public)
    if len(set(seen)) != expected:
        raise FailClosed("DUP_SIGNER")


def reject_raw_digest(digest: bytes) -> None:
    """A proposer digest is never an entry identity, even when it is 32 well-formed bytes."""
    if isinstance(digest, (bytes, bytearray)):
        raise FailClosed("RAW_DIGEST")
    raise FailClosed("RAW_DIGEST")
