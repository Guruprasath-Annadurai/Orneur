"""Crown validation and the separate consumer check.

The consumer never calls Crown. Both re-parse the registry bytes and re-check
the root, entry id, type, approval state, version floor and policy scope.
A proposer-supplied digest is not an entry id. Success is CHECKS_PASSED and
is not executable authority.

Registry signature authenticity is separate from the version-floor check.
Neither check is a hardware or TPM anti-rollback claim.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType

from orca.rse.imp1.codec import (
    Grant,
    OwnerToken,
    Registry,
    parse_corpus,
    parse_destination,
    parse_enrolment,
    parse_foundation,
    parse_grant,
    parse_holdout,
    parse_model,
    parse_policy,
    parse_registry,
    parse_role_image,
    parse_tokenizer,
    reject_raw_digest,
    verify_grant_signatures,
    verify_registry_signatures,
)
from orca.rse.imp1.profiles import (
    APPROVAL_NAME,
    APPROVABLE_ARTIFACT_FORMATS,
    APPROVED,
    CARRY_FORWARD,
    CLASS_BITS,
    CLASS_TEXT,
    CODE,
    CORPUS,
    DATA_ONLY_TENSOR_V1,
    DEFERRED_CLASSES,
    DEST_EXPORT_TARGET,
    DEST_MEDIUM,
    DEST_RECIPIENT_ROLE,
    DESTINATION,
    ENROLMENT,
    FAMILY_BEARING_TYPES,
    FOUNDATION_MODEL,
    HOLDOUT_SET,
    K_SCENARIO_NAME,
    MODEL,
    NOT_CLAIMED,
    POLICY,
    RETIRE_NAME,
    RETIREMENT_ACTIVE,
    ROLE_FORGE,
    ROLE_IMAGE,
    ROLE_WITNESS,
    SAS_DOMAIN,
    SEMANTIC_CLASSES,
    TOKENIZER,
    UNSUPPORTED_CURRENT_MILESTONE,
)
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, FailClosed, Result, guard

_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


@dataclass(frozen=True)
class Floors:
    min_registry_version: int
    min_authority_version: int
    min_epoch: int
    min_crown_generation: int


@dataclass(frozen=True)
class IntentSheet:
    """Operator-supplied comparison values. Not an authorization source."""

    grant_class: str
    artifact_name: str
    artifact_version: int
    destination_name: str
    ceilings: tuple
    sas: str
    target_role_name: str = ""
    counterpart_name: str = ""
    sequence: tuple = ()


@dataclass
class ChallengeLedger:
    """Outstanding challenge. A snapshot mismatch voids it. Not an authorization."""

    challenge: bytes | None
    void: bool = False

    def void_challenge(self) -> None:
        self.void = True
        self.challenge = None


def grant_sas(klass: int, signed: bytes) -> str:
    """SHA-256('OCR-SAS-v1' || 0x00 || class || signed bytes), first 60 bits, Base32."""
    if not isinstance(klass, int) or not 0 <= klass <= 255:
        raise FailClosed("GRANT_CLASS")
    if not isinstance(signed, (bytes, bytearray)):
        raise FailClosed("SIGNED_BYTES")
    digest = hashlib.sha256(SAS_DOMAIN + b"\x00" + bytes([klass]) + bytes(signed)).digest()
    bits = int.from_bytes(digest, "big") >> (256 - 60)
    chars = [_B32[(bits >> (55 - 5 * i)) & 31] for i in range(12)]
    text = "".join(chars)
    return f"{text[0:4]}-{text[4:8]}-{text[8:12]}"


def effective_min_version(registry: Registry, entry_type: int, name: str) -> int:
    versions = [entry.min_permitted_version for entry in registry.entries
                if entry.entry_type == entry_type and entry.name == name]
    if not versions:
        raise FailClosed("ABSENT")
    return max(versions)


def authenticate_registry(registry_raw: bytes, tokens: list[OwnerToken]) -> Registry:
    """Signature and canonical-root check. Does not apply the version floor."""
    registry = parse_registry(bytes(registry_raw))
    verify_registry_signatures(registry, tokens)
    _admit(registry)
    return registry


def check_freshness(registry: Registry, floors: Floors, prior: Registry | None) -> None:
    """Version-floor and previous-root linkage. Not a hardware anti-rollback control."""
    if registry.registry_version < floors.min_registry_version:
        raise FailClosed("REGISTRY_FLOOR")
    if registry.registry_version == 1:
        if prior is not None:
            raise FailClosed("GENESIS_PRIOR")
        return
    if prior is None or prior.registry_version + 1 != registry.registry_version:
        raise FailClosed("REGISTRY_ROLLBACK")
    if registry.previous_registry_root != prior.registry_root:
        raise FailClosed("PREVIOUS_ROOT")


def _admit(registry: Registry) -> None:
    for entry in registry.entries:
        if entry.entry_type in FAMILY_BEARING_TYPES:
            policy = registry.by_id(entry.policy_entry_id)
            if policy is None or policy.entry_type != POLICY or policy.policy_entry_id != bytes(32):
                raise FailClosed("POLICY_SCOPE")
        elif entry.policy_entry_id != bytes(32):
            raise FailClosed("POLICY_NEUTRAL")
        if entry.producer_entry_id != bytes(32) and registry.by_id(entry.producer_entry_id) is None:
            raise FailClosed("PRODUCER")
        if entry.entry_type == MODEL:
            _admit_model_lineage(registry, entry)
        if entry.approval_state != APPROVED:
            continue
        if entry.entry_type == FOUNDATION_MODEL:
            _require_foundation_complete(entry)
            _admit_foundation_use(registry, entry)
        elif entry.entry_type == TOKENIZER:
            parsed = parse_tokenizer(entry.tail)
            if parsed["tokenizer_id"] == bytes(32) or parsed["vocab_digest"] == bytes(32) or entry.artifact_digest == bytes(32):
                raise FailClosed("INCOMPLETE_TOKENIZER")
        elif entry.entry_type == MODEL:
            parsed = parse_model(entry.tail)
            if parsed["weights_digest"] == bytes(32):
                raise FailClosed("INCOMPLETE_MODEL")
            parent = _usable(registry, parsed["parent_entry_id"], registry.by_id(parsed["parent_entry_id"]).entry_type)
            if parent.entry_type not in (FOUNDATION_MODEL, MODEL):
                raise FailClosed("PARENT")
        elif entry.entry_type == ENROLMENT:
            parsed = parse_enrolment(entry.tail)
            if parsed["ed25519_public_key"] == bytes(32) or parsed["x25519_public_key"] == bytes(32):
                raise FailClosed("ENROLMENT_KEY")
            if parsed["environment_measurement"] == bytes(32):
                raise FailClosed("ENVIRONMENT")


def _admit_model_lineage(registry: Registry, entry) -> None:
    parsed = parse_model(entry.tail)
    if parsed["family_id"] == bytes(32):
        raise FailClosed("FAMILY_SCOPE")
    parent = registry.by_id(parsed["parent_entry_id"])
    if parent is None or parent.entry_type not in (FOUNDATION_MODEL, MODEL):
        raise FailClosed("PARENT")
    parent_family = parse_foundation(parent.tail)["family_id"] if parent.entry_type == FOUNDATION_MODEL else parse_model(parent.tail)["family_id"]
    if parsed["family_id"] != parent_family or entry.policy_entry_id != parent.policy_entry_id:
        raise FailClosed("FAMILY_LINEAGE")
    policy = parse_policy(registry.by_id(entry.policy_entry_id).tail)
    if policy["family_scope"] == bytes(32) or policy["family_scope"] != parsed["family_id"]:
        raise FailClosed("FAMILY_SCOPE")


def _admit_foundation_use(registry: Registry, entry) -> None:
    parsed = parse_foundation(entry.tail)
    if parsed["artifact_format"] not in APPROVABLE_ARTIFACT_FORMATS:
        raise FailClosed("ARTIFACT_FORMAT")
    if parsed["artifact_format"] != DATA_ONLY_TENSOR_V1:
        raise FailClosed("ARTIFACT_FORMAT")
    policy = parse_policy(registry.by_id(entry.policy_entry_id).tail)
    if policy["family_scope"] == bytes(32) or parsed["family_id"] != policy["family_scope"]:
        raise FailClosed("FAMILY_SCOPE")
    tokenizer = registry.by_id(parsed["tokenizer_entry_id"])
    if tokenizer is None or tokenizer.entry_type != TOKENIZER:
        raise FailClosed("TOKENIZER_BINDING")
    if tokenizer.policy_entry_id != entry.policy_entry_id:
        raise FailClosed("POLICY_SCOPE")
    if tokenizer.approval_state != APPROVED:
        raise FailClosed("TOKENIZER_BINDING")
    floor = effective_min_version(registry, TOKENIZER, tokenizer.name)
    if tokenizer.version < floor:
        raise FailClosed("BELOW_FLOOR")


def _require_foundation_complete(entry) -> None:
    parsed = parse_foundation(entry.tail)
    required = (
        parsed["family_id"], parsed["foundation_model_id"], parsed["tokenizer_entry_id"],
        parsed["weights_digest"], parsed["license_record_digest"], parsed["architecture_config_digest"],
        entry.artifact_digest, entry.provenance_digest, entry.producer_entry_id,
    )
    if any(item == bytes(32) for item in required) or parsed["foundation_revision"] == bytes(64):
        raise FailClosed("INCOMPLETE_FOUNDATION")


def _usable(registry: Registry, entry_id: bytes, expected_type: int):
    if not isinstance(entry_id, (bytes, bytearray)) or len(entry_id) != 32:
        raise FailClosed("ENTRY_ID")
    entry = registry.by_id(bytes(entry_id))
    if entry is None:
        raise FailClosed("ABSENT")
    if entry.entry_type != expected_type:
        raise FailClosed("WRONG_TYPE")
    if entry.approval_state != APPROVED:
        raise FailClosed("REVOKED" if entry.approval_state == 4 else "NOT_APPROVED")
    floor = effective_min_version(registry, entry.entry_type, entry.name)
    if entry.version < entry.min_permitted_version or entry.version < floor:
        raise FailClosed("BELOW_FLOOR")
    return entry


def _bound(registry: Registry, entry_id: bytes, expected_type: int, policy_id: bytes):
    entry = _usable(registry, entry_id, expected_type)
    if entry.policy_entry_id != policy_id:
        raise FailClosed("POLICY_SCOPE")
    return entry


def _bit(klass: int, allowed: int) -> None:
    if (allowed & (1 << CLASS_BITS[klass])) == 0:
        raise FailClosed("OPERATION_SCOPE")


def _le(value: int, cap: int, reason: str) -> None:
    if value > cap:
        raise FailClosed(reason)


def _family_required(policy: dict, family_id: bytes) -> None:
    if policy["family_scope"] == bytes(32) or family_id != policy["family_scope"]:
        raise FailClosed("FAMILY_SCOPE")


def _check_grant(grant: Grant, registry: Registry, floors: Floors, crown_image_entry_id: bytes) -> None:
    if grant.registry_version != registry.registry_version or grant.registry_root != registry.registry_root:
        raise FailClosed("REGISTRY_ROOT")
    if registry.registry_version < floors.min_registry_version:
        raise FailClosed("REGISTRY_FLOOR")
    if grant.owner_authority_version < floors.min_authority_version:
        raise FailClosed("AUTHORITY_FLOOR")
    if grant.incident_epoch < floors.min_epoch:
        raise FailClosed("EPOCH_FLOOR")
    image = _usable(registry, crown_image_entry_id, ROLE_IMAGE)
    generation, _measurement = parse_role_image(image.tail)
    if generation < floors.min_crown_generation:
        raise FailClosed("CROWN_FLOOR")
    policy_entry = _usable(registry, grant.policy_entry_id, POLICY)
    if policy_entry.policy_entry_id != bytes(32):
        raise FailClosed("POLICY_ROOT")
    policy = parse_policy(policy_entry.tail)
    if grant.version < policy["min_grant_schema_version"]:
        raise FailClosed("SCHEMA_FLOOR")
    if grant.klass not in SEMANTIC_CLASSES:
        raise FailClosed(UNSUPPORTED_CURRENT_MILESTONE)
    _bit(grant.klass, policy["allowed_operations"])
    if grant.max_runtime_s < 1:
        raise FailClosed("RUNTIME_CAP")
    _le(grant.max_runtime_s, policy["max_runtime_s"], "RUNTIME_CAP")
    _usable(registry, grant.code_entry_id, CODE)
    role = _usable(registry, grant.target_role_id, ENROLMENT)
    role_fields = parse_enrolment(role.tail)
    if grant.env_measurement_digest != role_fields["environment_measurement"]:
        raise FailClosed("ENVIRONMENT")
    _check_class(grant, registry, policy, role_fields)
    return


def _check_class(grant: Grant, registry: Registry, policy: dict, role_fields: dict) -> None:
    tail = grant.tail
    policy_id = grant.policy_entry_id
    klass = grant.klass
    if klass == ord("G"):
        if role_fields["role_type"] != ROLE_FORGE:
            raise FailClosed("ROLE_TYPE")
        corpus = _corpus(registry, tail["corpus_entry_id"], policy_id, tail["source_provenance_digest"])
        if tail["batch_ceiling_bytes"] < 1:
            raise FailClosed("RESOURCE_CAP")
        if tail["batch_count"] < 1:
            raise FailClosed("RUN_CAP")
        _le(tail["batch_ceiling_bytes"], policy["max_batch_bytes"], "RESOURCE_CAP")
        _le(tail["batch_count"], policy["max_run"], "RUN_CAP")
        _destination(registry, tail["destination_entry_id"], policy, {DEST_MEDIUM, DEST_RECIPIENT_ROLE})
        recipient = _usable(registry, tail["recipient_role_id"], ENROLMENT)
        if parse_enrolment(recipient.tail)["role_type"] != ROLE_WITNESS:
            raise FailClosed("ROLE_TYPE")
        if corpus.entry_type != CORPUS:
            raise FailClosed("WRONG_TYPE")
    elif klass == ord("V"):
        if role_fields["role_type"] != ROLE_WITNESS:
            raise FailClosed("ROLE_TYPE")
        sender = _usable(registry, tail["sender_role_id"], ENROLMENT)
        if parse_enrolment(sender.tail)["role_type"] != ROLE_FORGE:
            raise FailClosed("ROLE_TYPE")
        if tail["seq_last"] < tail["seq_first"]:
            raise FailClosed("SEQUENCE")
        _artifact(registry, tail["artifact_entry_id"], policy_id, policy)
    else:
        raise FailClosed(UNSUPPORTED_CURRENT_MILESTONE)


def _corpus(registry, entry_id, policy_id, source):
    entry = _bound(registry, entry_id, CORPUS, policy_id)
    parsed = parse_corpus(entry.tail)
    if parsed["retirement_state"] != RETIREMENT_ACTIVE:
        raise FailClosed("RETIRED_CORPUS")
    if source is not None and source != parsed["source_provenance_digest"]:
        raise FailClosed("SOURCE_MISMATCH")
    return entry


def _foundation(registry, entry_id, policy_id, policy):
    entry = _bound(registry, entry_id, FOUNDATION_MODEL, policy_id)
    _require_foundation_complete(entry)
    parsed = parse_foundation(entry.tail)
    _family_required(policy, parsed["family_id"])
    tokenizer = _bound(registry, parsed["tokenizer_entry_id"], TOKENIZER, policy_id)
    if tokenizer.approval_state != APPROVED:
        raise FailClosed("TOKENIZER_BINDING")
    return entry


def _model(registry, entry_id, policy_id, policy, lifecycle: int):
    entry = _bound(registry, entry_id, MODEL, policy_id)
    parsed = parse_model(entry.tail)
    if parsed["lifecycle_state"] != lifecycle:
        raise FailClosed("LIFECYCLE")
    _family_required(policy, parsed["family_id"])
    return entry


def _artifact(registry, entry_id, policy_id, policy):
    entry = registry.by_id(entry_id)
    if entry is None:
        raise FailClosed("ABSENT")
    if entry.entry_type == CORPUS:
        return _corpus(registry, entry_id, policy_id, None)
    if entry.entry_type == CODE:
        return _usable(registry, entry_id, CODE)
    if entry.entry_type == MODEL:
        parsed = parse_model(entry.tail)
        if parsed["lifecycle_state"] == LIFECYCLE_RETIRED:
            raise FailClosed("LIFECYCLE")
        return _model(registry, entry_id, policy_id, policy, parsed["lifecycle_state"])
    if entry.entry_type == FOUNDATION_MODEL:
        return _foundation(registry, entry_id, policy_id, policy)
    raise FailClosed("WRONG_TYPE")


def _destination(registry, entry_id, policy: dict, kinds: set):
    entry = _usable(registry, entry_id, DESTINATION)
    parsed = parse_destination(entry.tail)
    if parsed["kind"] not in kinds or parsed["identifier_digest"] == bytes(32):
        raise FailClosed("DESTINATION")
    if entry.entry_id not in policy["permitted_destinations"]:
        raise FailClosed("DESTINATION_SCOPE")
    return entry


def _role(registry, entry_id, policy_id, expected_role):
    entry = _bound(registry, entry_id, ENROLMENT, policy_id)
    parsed = parse_enrolment(entry.tail)
    if expected_role is not None and parsed["role_type"] != expected_role:
        raise FailClosed("ROLE_TYPE")
    return entry


def _retire_object(registry, entry_id, policy_id, policy):
    entry = registry.by_id(entry_id)
    if entry is None:
        raise FailClosed("ABSENT")
    if entry.entry_type in (MODEL, FOUNDATION_MODEL):
        _usable(registry, entry_id, entry.entry_type)
        family = parse_model(entry.tail)["family_id"] if entry.entry_type == MODEL else parse_foundation(entry.tail)["family_id"]
        _family_required(policy, family)
        if entry.policy_entry_id != policy_id:
            raise FailClosed("POLICY_SCOPE")
        return entry
    _family_absent(policy)
    return _bound(registry, entry_id, entry.entry_type, policy_id)


def ceilings_of(grant: Grant) -> tuple:
    tail = grant.tail
    runtime = grant.max_runtime_s
    klass = grant.klass
    if klass == ord("G"):
        return (tail["batch_count"], tail["batch_ceiling_bytes"], runtime)
    if klass in (ord("V"), ord("K"), ord("R")):
        return (runtime,)
    if klass == ord("Q"):
        return (tail["run_budget"], tail["query_budget"], tail["bit_budget"], runtime)
    if klass == ord("T"):
        return (tail["spend_ceiling"], tail["run_ceiling"], runtime)
    if klass == ord("W"):
        return (tail["size_ceiling"], runtime)
    if klass == ord("D"):
        return (tail["spend_ceiling"], tail["run_ceiling"], runtime)
    raise FailClosed("GRANT_CLASS")


def primary_entry(grant: Grant, registry: Registry):
    tail = grant.tail
    klass = grant.klass
    mapping = {
        ord("G"): tail.get("corpus_entry_id"),
        ord("V"): tail.get("artifact_entry_id"),
        ord("Q"): tail.get("candidate_model_entry_id"),
        ord("T"): tail.get("foundation_entry_id"),
        ord("W"): tail.get("model_entry_id"),
        ord("D"): tail.get("model_entry_id"),
        ord("R"): tail.get("object_entry_id"),
    }
    entry_id = mapping.get(klass)
    if entry_id is None:
        return None
    return registry.by_id(entry_id)


def destination_entry(grant: Grant, registry: Registry):
    key = "destination_entry_id" if grant.klass in (ord("G"), ord("W")) else None
    if grant.klass == ord("D"):
        key = "revocation_endpoint_entry_id"
    if key is None:
        return None
    return registry.by_id(grant.tail[key])


def render_card(grant: Grant, registry: Registry, floors: Floors, crown_image_entry_id: bytes) -> str:
    """Fixed card. Every name and version is read from the registry or the signed grant."""
    label, operation = CLASS_TEXT[grant.klass]
    if grant.klass == ord("K"):
        operation = K_SCENARIO_NAME[grant.tail["scenario"]]
    elif grant.klass == ord("R"):
        operation = RETIRE_NAME[grant.tail["reason"]]
    role = registry.by_id(grant.target_role_id)
    if role is None:
        raise FailClosed("ABSENT")
    role_fields = parse_enrolment(role.tail)
    lines = [
        f"CLASS        {chr(grant.klass)}  {label}",
        f"OPERATION    {operation}",
        f"TARGET ROLE  {role.name} v{role_fields['key_version']}",
    ]
    seen = set()
    for entry_id in _referenced_ids(grant):
        _append_artifact(lines, registry, entry_id, seen)
    dest = destination_entry(grant, registry)
    lines.append(f"DESTINATION  {dest.name if dest is not None else '-'}")
    lines.append(_limits_line(grant, registry))
    lines.append(
        f"EPOCH        {grant.incident_epoch}   REGISTRY v{grant.registry_version}   "
        f"AUTHORITY v{grant.owner_authority_version}"
    )
    image = registry.by_id(crown_image_entry_id)
    crown_ok = (
        image is not None and image.entry_type == ROLE_IMAGE and image.approval_state == APPROVED
        and parse_role_image(image.tail)[0] >= floors.min_crown_generation
    )
    epoch = "OK" if grant.incident_epoch >= floors.min_epoch else "FAIL"
    reg = "OK" if grant.registry_version >= floors.min_registry_version else "FAIL"
    auth = "OK" if grant.owner_authority_version >= floors.min_authority_version else "FAIL"
    crown = "OK" if crown_ok else "FAIL"
    floor_line = f"FLOOR CHECK  epoch {epoch}  registry {reg}  authority {auth}  crown {crown}"
    if "FAIL" in floor_line:
        raise FailClosed("FLOOR_CHECK")
    lines.append(floor_line)
    if grant.klass in DEFERRED_CLASSES:
        lines.append("STATUS       UNSUPPORTED CURRENT MILESTONE")
    lines.append(f"GRANT SAS    {grant_sas(grant.klass, grant.signed)}")
    return "\n".join(lines)


def _append_artifact(lines: list, registry: Registry, entry_id: bytes, seen: set) -> None:
    if entry_id in seen:
        return
    seen.add(entry_id)
    entry = registry.by_id(entry_id)
    if entry is None:
        raise FailClosed("ABSENT")
    state = APPROVAL_NAME[entry.approval_state]
    lines.append(f"ARTIFACT     {entry.name} v{entry.version} [{state}, min {entry.min_permitted_version}]")
    if entry.entry_type == FOUNDATION_MODEL:
        _append_artifact(lines, registry, parse_foundation(entry.tail)["tokenizer_entry_id"], seen)


def _limits_line(grant: Grant, registry: Registry) -> str:
    policy = parse_policy(registry.by_id(grant.policy_entry_id).tail)
    tail = grant.tail
    batches = tail.get("batch_count", 0)
    byte_cap = tail.get("batch_ceiling_bytes", tail.get("size_ceiling", 0))
    spend = tail.get("spend_ceiling", 0)
    return (
        f"LIMITS       bytes {byte_cap}  batches {batches}  runtime {grant.max_runtime_s} s  "
        f"spend {spend}  (cap bytes {policy['max_batch_bytes']} runtime {policy['max_runtime_s']} "
        f"spend {policy['max_spend']})"
    )


def _referenced_ids(grant: Grant) -> list:
    ids = [grant.policy_entry_id, grant.target_role_id, grant.code_entry_id]
    for key, value in grant.tail.items():
        if key.endswith("_entry_id") or key.endswith("_role_id"):
            ids.append(value)
        elif key == "revoked_ids":
            ids.extend(value)
    return ids


def typed_artifact(grant: Grant, registry: Registry) -> tuple[str, int]:
    """Human identity compared with the Intent Sheet.

    Classes that name more than one artifact join ``name vN`` with ``+`` so a
    swap of either object changes the typed identity. One version field remains;
    it is the version of the class's primary object, and the other versions are
    inside the joined name.
    """
    tail = grant.tail

    def label(entry) -> str:
        if entry is None:
            raise FailClosed("ABSENT")
        return f"{entry.name} v{entry.version}"

    klass = grant.klass
    if klass == ord("G"):
        entry = registry.by_id(tail["corpus_entry_id"])
        if entry is None:
            raise FailClosed("ABSENT")
        return entry.name, entry.version
    if klass == ord("T"):
        corpus = registry.by_id(tail["corpus_entry_id"])
        foundation = registry.by_id(tail["foundation_entry_id"])
        if corpus is None or foundation is None:
            raise FailClosed("ABSENT")
        return f"{label(corpus)}+{label(foundation)}", foundation.version
    if klass == ord("Q"):
        model = registry.by_id(tail["candidate_model_entry_id"])
        holdout = registry.by_id(tail["holdout_set_entry_id"])
        if model is None or holdout is None:
            raise FailClosed("ABSENT")
        return f"{label(model)}+{label(holdout)}", model.version
    if klass == ord("K"):
        return "", 0
    entry = primary_entry(grant, registry)
    if entry is None:
        raise FailClosed("ABSENT")
    return entry.name, entry.version


def compare_intent(grant: Grant, registry: Registry, intent: IntentSheet) -> None:
    if not isinstance(intent, IntentSheet):
        raise FailClosed("INTENT_TYPE")
    if intent.grant_class != chr(grant.klass):
        raise FailClosed("INTENT_CLASS")
    artifact_name, artifact_version = typed_artifact(grant, registry)
    if intent.artifact_name != artifact_name or intent.artifact_version != artifact_version:
        raise FailClosed("INTENT_ARTIFACT")
    dest = destination_entry(grant, registry)
    dest_name = "" if dest is None else dest.name
    if intent.destination_name != dest_name:
        raise FailClosed("INTENT_DESTINATION")
    if tuple(intent.ceilings) != ceilings_of(grant):
        raise FailClosed("INTENT_CEILINGS")
    if intent.sas != grant_sas(grant.klass, grant.signed):
        raise FailClosed("SAS")
    if grant.klass not in SEMANTIC_CLASSES:
        raise FailClosed(UNSUPPORTED_CURRENT_MILESTONE)
    role = registry.by_id(grant.target_role_id)
    if role is None or intent.target_role_name != role.name:
        raise FailClosed("INTENT_ROLE")
    if grant.klass == ord("G"):
        recipient = registry.by_id(grant.tail["recipient_role_id"])
        if recipient is None or intent.counterpart_name != recipient.name:
            raise FailClosed("INTENT_ROLE")
    if grant.klass == ord("V"):
        sender = registry.by_id(grant.tail["sender_role_id"])
        if sender is None or intent.counterpart_name != sender.name:
            raise FailClosed("INTENT_ROLE")
        if tuple(intent.sequence) != (grant.tail["seq_first"], grant.tail["seq_last"]):
            raise FailClosed("INTENT_SEQUENCE")


def _load(grant_raw: bytes, registry_raw: bytes, tokens: list[OwnerToken]) -> tuple[Grant, Registry]:
    registry = authenticate_registry(registry_raw, tokens)
    grant = parse_grant(bytes(grant_raw))
    verify_grant_signatures(grant, tokens)
    return grant, registry


def _success(reason: str, **payload) -> Result:
    payload.setdefault("not_claimed", NOT_CLAIMED)
    payload.setdefault("carry_forward", CARRY_FORWARD)
    payload["spending"] = False
    payload["training"] = False
    payload["model_selection"] = False
    payload["gpu"] = False
    payload["provider"] = False
    payload["corpus_generation"] = "NOT_AUTHORIZED"
    payload["qualification"] = "NOT_AUTHORIZED"
    return Result(CHECKS_PASSED, reason, MappingProxyType(payload))


def _reject_deferred(grant: Grant) -> None:
    if grant.klass in DEFERRED_CLASSES or grant.klass not in SEMANTIC_CLASSES:
        raise FailClosed(UNSUPPORTED_CURRENT_MILESTONE)


def _bind_snapshot(grant: Grant, registry: Registry, highest_authenticated_version: int | None,
                   ledger: ChallengeLedger | None) -> None:
    mismatch = (
        registry.registry_version != grant.registry_version
        or registry.registry_root != grant.registry_root
        or (highest_authenticated_version is not None and highest_authenticated_version > grant.registry_version)
    )
    if mismatch:
        if ledger is not None:
            ledger.void_challenge()
        raise FailClosed("SNAPSHOT")


@guard
def crown_validate(grant_raw: bytes, registry_raw: bytes, tokens: list[OwnerToken], floors: Floors,
                   crown_image_entry_id: bytes, **extra) -> Result:
    if extra:
        raise FailClosed("UNEXPECTED_ARGUMENT")
    grant, registry = _load(grant_raw, registry_raw, tokens)
    _reject_deferred(grant)
    _bind_snapshot(grant, registry, None, None)
    _check_grant(grant, registry, floors, crown_image_entry_id)
    card = render_card(grant, registry, floors, crown_image_entry_id)
    return _success("CROWN_CHECKS", card=card, sas=grant_sas(grant.klass, grant.signed))


@guard
def consumer_verify(grant_raw: bytes, registry_raw: bytes, tokens: list[OwnerToken], floors: Floors,
                    crown_image_entry_id: bytes, intent: IntentSheet, outstanding_challenge: bytes,
                    own_role_id: bytes, observed_environment: bytes, *,
                    highest_authenticated_version: int | None = None,
                    challenge_ledger: ChallengeLedger | None = None, **extra) -> Result:
    """Independent of Crown. There is no crown_already_checked input."""
    if extra:
        raise FailClosed("UNEXPECTED_ARGUMENT")
    grant, registry = _load(grant_raw, registry_raw, tokens)
    _reject_deferred(grant)
    _bind_snapshot(grant, registry, highest_authenticated_version, challenge_ledger)
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
    _check_grant(grant, registry, floors, crown_image_entry_id)
    compare_intent(grant, registry, intent)
    card = render_card(grant, registry, floors, crown_image_entry_id)
    return _success("CONSUMER_CHECKS", card=card, sas=grant_sas(grant.klass, grant.signed))


@guard
def accept_registry(registry_raw: bytes, tokens: list[OwnerToken], floors: Floors, prior: Registry | None) -> Result:
    registry = authenticate_registry(registry_raw, tokens)
    check_freshness(registry, floors, prior)
    return _success("REGISTRY_FRESH", registry_version=registry.registry_version)


@guard
def registry_authenticity(registry_raw: bytes, tokens: list[OwnerToken]) -> Result:
    registry = authenticate_registry(registry_raw, tokens)
    return _success("REGISTRY_AUTHENTIC", registry_version=registry.registry_version, registry_root=registry.registry_root)


@guard
def registry_freshness(registry: Registry, floors: Floors, prior: Registry | None) -> Result:
    check_freshness(registry, floors, prior)
    return _success("REGISTRY_FRESH", registry_version=registry.registry_version)


@guard
def refuse_proposer_digest(digest: bytes) -> Result:
    reject_raw_digest(digest)
    return Result(FAIL_CLOSED, "RAW_DIGEST")
