"""Log-first grant session.

SIGNED is not usable. The consumer journal, not a caller-supplied ledger,
is the freshness authority. Private keys are not written into the journal.
"""

from __future__ import annotations

import hashlib
import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from orca.rse.imp1.authority import ChallengeLedger, Floors, IntentSheet, consumer_verify, crown_validate
from orca.rse.imp1.codec import OwnerToken, parse_enrolment, parse_grant, parse_registry
from orca.rse.imp1.profiles import (
    DEFERRED_CLASSES,
    ENROLMENT,
    ROLE_CROWN,
    ROLE_FORGE,
    ROLE_WITNESS,
)
from orca.rse.imp1.verdict import CHECKS_PASSED, FailClosed, Quarantine
from orca.rse.imp2.machine import (
    ACTIVE,
    CONSUMED,
    CONSUMER_CONFIRMED,
    DELIVERED,
    EVIDENCE_PENDING,
    EXPIRED,
    INTERRUPTED,
    PRE_ACTIVE,
    QUARANTINED,
    REVOKED,
    SIGNED,
    GrantMachine,
    promotes,
)
from orca.rse.imp3.egress import Egress
from orca.rse.imp3.freshness import RoleFreshness
from orca.rse.imp3.journal import JournalSink, MemorySink, SyntheticFence
from orca.rse.imp3.ledger import EvidenceLog, Monitor, ack_matches, enrolment_key, require_monitor, verify_grant_inclusion
from orca.rse.imp4.ocr1 import CounterJournal, RecipientJournal, Sender
from orca.rse.imp3.merkle import leaf_hash, verify_inclusion
from orca.rse.imp3.records import (
    KIND_ACCEPTANCE,
    KIND_BOOT,
    KIND_CONSUMPTION,
    KIND_RESULT,
    NON_STATE_CHANGING,
    OCA1_LEN,
    OCI1_LEN,
    OCK1_LEN,
    OEL1_LEN,
    parse_ack,
    parse_checkpoint,
    parse_inclusion,
    parse_record,
)

_ROUTINE = frozenset({ord("G"), ord("V")})


def _public(key: Ed25519PrivateKey) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


class Session:
    def __init__(self, *, role_id: bytes, role_key: Ed25519PrivateKey, epoch: int, authority_version: int,
                 floors: Floors, tokens: list[OwnerToken], registry_raw: bytes, crown_image_id: bytes,
                 m1_id: bytes, m2_id: bytes, sink: JournalSink | None = None,
                 fence: SyntheticFence | None = None) -> None:
        registry = parse_registry(bytes(registry_raw))
        entry = registry.by_id(bytes(role_id))
        if entry is None or entry.entry_type != ENROLMENT:
            raise FailClosed("ROLE_ID")
        fields = parse_enrolment(entry.tail)
        if fields["ed25519_public_key"] != _public(role_key):
            raise FailClosed("ROLE_KEY")
        if bytes(m1_id) == bytes(m2_id):
            raise FailClosed("INDEPENDENT_WITNESS")
        m1_env = _monitor_env(registry, m1_id)
        m2_env = _monitor_env(registry, m2_id)
        if m1_env == m2_env or enrolment_key(registry, m1_id) == enrolment_key(registry, m2_id):
            raise FailClosed("INDEPENDENT_WITNESS")
        self.role_id = bytes(role_id)
        self.role_type = fields["role_type"]
        self.role_key = role_key
        self.epoch = epoch
        self.authority_version = authority_version
        self.floors = floors
        self.tokens = list(tokens)
        self.registry_raw = bytes(registry_raw)
        self.crown_image_id = bytes(crown_image_id)
        self.m1_id = bytes(m1_id)
        self.m2_id = bytes(m2_id)
        self.machine = GrantMachine()
        self._freshness = RoleFreshness(self.role_id)
        self.log = EvidenceLog(self.role_id, epoch)
        self.egress = Egress()
        self._grants: dict[bytes, bytes] = {}
        self._delivery: dict[bytes, bytes] = {}
        self._bound: dict[bytes, int] = {}
        self._clock: int | None = None
        self._ticks = 0
        self._live: set[bytes] = set()
        self._executed: set[bytes] = set()
        self.executions = 0
        self.sink = sink if sink is not None else MemorySink()
        self.fence = fence if fence is not None else SyntheticFence()
        self.generation = 0
        self.recipient = RecipientJournal()
        self.counters = CounterJournal()
        self._freshness.authenticate(self.registry_raw, self.tokens, self.floors, None)

    @property
    def freshness(self) -> RoleFreshness:
        return self._freshness

    @freshness.setter
    def freshness(self, _value: object) -> None:
        raise FailClosed("FRESHNESS")

    def dump(self) -> bytes:
        grants = b"".join(struct.pack(">I", len(raw)) + raw for raw in (self._grants[k] for k in sorted(self._grants)))
        deliveries = b"".join(
            key + struct.pack(">I", len(value)) + value for key, value in sorted(self._delivery.items())
        )
        bounds = b"".join(key + struct.pack(">Q", value) for key, value in sorted(self._bound.items()))
        parts = [
            b"OBS1", bytes([2]), self.role_id,
            struct.pack(
                ">IIQQQ", self.epoch, self.authority_version, self._ticks,
                0 if self._clock is None else self._clock + 1, self.generation,
            ),
            self.crown_image_id, self.m1_id, self.m2_id,
            _len_blob(self.machine.export()), _len_blob(self.freshness.export()), _len_blob(self.log.export()),
            _len_blob(self.egress.export()), _len_blob(self.registry_raw),
            struct.pack(">I", len(self._grants)), grants,
            struct.pack(">I", len(self._delivery)), deliveries,
            struct.pack(">I", len(self._bound)), bounds,
            _len_blob(self.recipient.export()), _len_blob(self.counters.export()),
        ]
        return b"".join(parts)

    @classmethod
    def boot(cls, blob: bytes, *, role_key: Ed25519PrivateKey, floors: Floors, tokens: list[OwnerToken],
             fence: SyntheticFence | None = None, sink: JournalSink | None = None) -> "Session":
        try:
            parsed = _parse_blob(blob)
        except (FailClosed, Quarantine):
            raise
        except (KeyError, ValueError, struct.error, IndexError) as exc:
            raise FailClosed("JOURNAL") from exc
        session = cls.__new__(cls)
        session.role_key = role_key
        session.floors = floors
        session.tokens = list(tokens)
        session.role_id = parsed["role_id"]
        session.epoch = parsed["epoch"]
        session.authority_version = parsed["authority_version"]
        session.crown_image_id = parsed["crown_image"]
        session.m1_id = parsed["m1"]
        session.m2_id = parsed["m2"]
        session.registry_raw = parsed["registry"]
        session.machine = parsed["machine"]
        session._freshness = parsed["freshness"]
        session.egress = parsed["egress"]
        session._grants = parsed["grants"]
        session._delivery = parsed["delivery"]
        session._bound = parsed["bound"]
        session._ticks = parsed["ticks"]
        session._clock = parsed["clock"]
        session._live = set()
        session._executed = set()
        session.executions = 0
        session.generation = parsed["generation"]
        session.recipient = parsed["recipient"]
        session.counters = parsed["counters"]
        session.sink = sink if sink is not None else MemorySink()
        session.fence = fence if fence is not None else SyntheticFence()
        registry = parse_registry(session.registry_raw)
        entry = registry.by_id(session.role_id)
        if entry is None:
            raise FailClosed("ROLE_ID")
        fields = parse_enrolment(entry.tail)
        if fields["ed25519_public_key"] != _public(role_key):
            raise FailClosed("ROLE_KEY")
        session.role_type = fields["role_type"]
        session.log = EvidenceLog.parse(parsed["log"], fields["ed25519_public_key"])
        if session.freshness.role_id != session.role_id:
            raise Quarantine("FRESHNESS")
        if session.freshness.highest != registry.registry_version or session.freshness.root != registry.registry_root:
            raise Quarantine("SNAPSHOT")
        if session.m1_id == session.m2_id:
            raise Quarantine("INDEPENDENT_WITNESS")
        if enrolment_key(registry, session.m1_id) == enrolment_key(registry, session.m2_id):
            raise Quarantine("INDEPENDENT_WITNESS")
        if _monitor_env(registry, session.m1_id) == _monitor_env(registry, session.m2_id):
            raise Quarantine("INDEPENDENT_WITNESS")
        session._validate_journal()
        session.fence.pin_observed(parsed["generation"], hashlib.sha256(bytes(blob)).digest())
        session._recover()
        return session

    def _recover(self) -> None:
        for slot in self.machine.slots():
            if slot.state == ACTIVE and slot.consumption_started:
                self._forfeit(slot.grant_id)
                self.machine.move(slot.grant_id, INTERRUPTED)
            elif slot.state == CONSUMER_CONFIRMED and not slot.consumption_started:
                self.machine.require_reconfirm(slot.grant_id)
            elif slot.consumption_started and slot.state not in {CONSUMED, EVIDENCE_PENDING, INTERRUPTED}:
                self.machine.move(slot.grant_id, QUARANTINED)
            elif slot.state == EVIDENCE_PENDING and not slot.evidence_durable:
                self.machine.move(slot.grant_id, QUARANTINED)

    def _forfeit(self, grant_id: bytes) -> None:
        try:
            raw = self._grants[bytes(grant_id)]
        except KeyError as exc:
            raise FailClosed("GRANT_ABSENT") from exc
        try:
            grant = parse_grant(raw)
        except (FailClosed, Quarantine):
            raise
        except (KeyError, ValueError, struct.error) as exc:
            raise FailClosed("JOURNAL") from exc
        if grant.klass == ord("V"):
            self.freshness.forfeit_sequences(grant.tail["seq_first"], grant.tail["seq_last"])
        self.freshness.note_dead_grant(grant_id)

    def _validate_journal(self) -> None:
        try:
            slots = list(self.machine.slots())
        except (KeyError, ValueError, struct.error) as exc:
            raise FailClosed("JOURNAL") from exc
        for slot in slots:
            if slot.grant_id not in self._grants:
                raise FailClosed("JOURNAL")
            parse_grant(self._grants[slot.grant_id])
        for key, index in self._bound.items():
            if key not in self._grants or not isinstance(index, int) or index < 0 or index >= self.log.size:
                raise FailClosed("JOURNAL")
        for key in self._delivery:
            if key not in self._grants:
                raise FailClosed("JOURNAL")

    def durable_commit(self) -> None:
        """Commit the journal before a caller may observe ACTIVE or replay success.

        The fence moves only after ``sink.commit`` returns. A failed commit
        leaves an in-memory ACTIVE grant INTERRUPTED and does not return success.
        """
        self.generation += 1
        blob = self.dump()
        digest = hashlib.sha256(blob).digest()
        try:
            self.sink.commit(blob)
            self.fence.advance(self.generation, digest)
        except FailClosed:
            self.generation -= 1
            self._fail_closed_active()
            raise FailClosed("JOURNAL_COMMIT")
        except Exception as exc:
            self.generation -= 1
            self._fail_closed_active()
            raise FailClosed("JOURNAL_COMMIT") from exc

    def _fail_closed_active(self) -> None:
        for slot in list(self.machine.slots()):
            if slot.state != ACTIVE:
                continue
            try:
                self._forfeit(slot.grant_id)
            except FailClosed:
                pass
            self.machine.move(slot.grant_id, INTERRUPTED)
            self._live.discard(slot.grant_id)

    def _commit_view(self) -> bytes:
        return self.dump()

    def propose(self, grant_raw: bytes) -> str:
        grant = parse_grant(bytes(grant_raw))
        self.machine.add(grant.grant_id, grant.target_role_id, grant.klass)
        self._grants[grant.grant_id] = bytes(grant_raw)
        return self.machine.get(grant.grant_id).state

    def owner_verify(self, grant_id: bytes) -> str:
        grant_raw = self._grant_bytes(grant_id)
        grant = parse_grant(grant_raw)
        if grant.incident_epoch != self.epoch or grant.owner_authority_version != self.authority_version:
            raise FailClosed("EPOCH")
        result = crown_validate(grant_raw, self.registry_raw, self.tokens, self.floors, self.crown_image_id)
        if result.decision != CHECKS_PASSED:
            raise FailClosed(result.reason)
        self.machine.move(grant_id, "OWNER_VERIFIED")
        return "OWNER_VERIFIED"

    def mark_signed(self, grant_id: bytes) -> str:
        self._grant_bytes(grant_id)
        self.machine.move(grant_id, SIGNED)
        return SIGNED

    def append_authorization(self, grant_id: bytes) -> str:
        if self.role_type != ROLE_CROWN:
            raise FailClosed("ROLE_TYPE")
        grant_raw = self._grant_bytes(grant_id)
        grant = parse_grant(grant_raw)
        if self.machine.get(grant_id).state != SIGNED:
            raise FailClosed("GRANT_STATE")
        index, _record = self.log.append_grant(grant_raw, epoch=self.epoch, registry_version=grant.registry_version)
        self._bound[grant_id] = index
        self.machine.move(grant_id, "APPENDED")
        return "APPENDED"

    def checkpoint_authorization(self, grant_id: bytes) -> bytes:
        if self.machine.get(grant_id).state != "APPENDED":
            raise FailClosed("GRANT_STATE")
        raw = self.log.checkpoint(self.role_key, epoch=self.epoch, registry_version=self.freshness.highest)
        self.machine.move(grant_id, "CHECKPOINT_CREATED")
        return raw

    def accept_ack(self, grant_id: bytes, ack: bytes, **extra) -> str:
        if extra:
            raise FailClosed("UNEXPECTED_ARGUMENT")
        if self.machine.get(grant_id).state not in {"CHECKPOINT_CREATED", "REQUIRED_WITNESS_ACKNOWLEDGED"}:
            raise FailClosed("GRANT_STATE")
        index = self._bound[grant_id]
        checkpoint = self.log.covering(index)
        registry = parse_registry(self.registry_raw)
        parsed = parse_ack(ack)
        public = require_monitor(registry, parsed["witness_id"])
        if public == _public(self.role_key):
            raise FailClosed("INDEPENDENT_WITNESS")
        if parsed["witness_id"] not in {self.m1_id, self.m2_id}:
            raise FailClosed("WITNESS")
        ack_matches(ack, checkpoint, public)
        self.log.store_ack(ack)
        if self._quorum(grant_id, checkpoint["tree_size"]):
            if self.machine.get(grant_id).state == "CHECKPOINT_CREATED":
                self.machine.move(grant_id, "REQUIRED_WITNESS_ACKNOWLEDGED")
            self.machine.move(grant_id, "CHECKPOINTED")
            return "CHECKPOINTED"
        return self.machine.get(grant_id).state

    def _quorum(self, grant_id: bytes, tree_size: int) -> bool:
        grant = parse_grant(self._grants[grant_id])
        if grant.klass not in _ROUTINE:
            return False
        witnesses = set()
        for ack in self.log.acks_for(tree_size):
            parsed = parse_ack(ack)
            if parsed["tree_size"] != tree_size:
                continue
            witnesses.add(parsed["witness_id"])
        if self.m1_id not in witnesses:
            return False
        return True

    def deliver(self, grant_id: bytes) -> bytes:
        if self.machine.get(grant_id).state != "CHECKPOINTED":
            raise FailClosed("GRANT_STATE")
        index = self._bound[grant_id]
        record = self.log.record(index)
        checkpoint = self.log.covering(index)
        inclusion = self.log.prove_inclusion_at(index, checkpoint["tree_size"])
        acks = self.log.acks_for(checkpoint["tree_size"])
        if not acks:
            raise FailClosed("WITNESS")
        raw = _pack_delivery(self._grants[grant_id], record, inclusion, checkpoint["raw"], acks, self.registry_raw)
        self._delivery[grant_id] = raw
        self.machine.move(grant_id, DELIVERED)
        return raw

    def issue_challenge(self, entropy: bytes) -> bytes:
        if self.role_type == ROLE_CROWN:
            raise FailClosed("ROLE_TYPE")
        if self.log.size == 0:
            self.log.append(
                kind=KIND_BOOT, payload_digest=hashlib.sha256(b"boot").digest(), grant_id=bytes(16),
                epoch=self.epoch, registry_version=self.freshness.highest,
            )
            self.log.checkpoint(self.role_key, epoch=self.epoch, registry_version=self.freshness.highest)
        challenge = self.freshness.issue(entropy, head=self.log.head)
        self.log.append(
            kind=2, payload_digest=hashlib.sha256(challenge).digest(), grant_id=bytes(16),
            epoch=self.epoch, registry_version=self.freshness.highest,
        )
        return challenge

    def confirm(self, delivery: bytes, intent: IntentSheet, **extra) -> str:
        if extra:
            raise FailClosed("UNEXPECTED_ARGUMENT")
        if not isinstance(intent, IntentSheet):
            raise FailClosed("INTENT_TYPE")
        grant_raw, record, inclusion, checkpoint, acks, registry_raw = _parse_delivery(delivery)
        if registry_raw != self.registry_raw:
            raise FailClosed("SNAPSHOT")
        grant = parse_grant(grant_raw)
        if grant.target_role_id != self.role_id:
            raise FailClosed("ROLE_ID")
        if grant.incident_epoch != self.epoch:
            raise FailClosed("EPOCH")
        if grant.klass in DEFERRED_CLASSES:
            raise FailClosed("UNSUPPORTED_CURRENT_MILESTONE")
        registry = parse_registry(registry_raw)
        self.freshness.evaluate(grant, registry)
        crown_public = enrolment_key(registry, parse_checkpoint(checkpoint)["log_id"], expect_type=ROLE_CROWN)
        if crown_public == _public(self.role_key):
            raise FailClosed("INDEPENDENT_WITNESS")
        head = verify_grant_inclusion(
            grant_raw=grant_raw, record=record, inclusion=inclusion, checkpoint=checkpoint, crown_public=crown_public,
        )
        self._require_acks(grant, head, acks, registry)
        self._require_ancestor(grant.prev_role_checkpoint)
        disposable = ChallengeLedger(self.freshness.outstanding)
        result = consumer_verify(
            grant_raw, registry_raw, self.tokens, self.floors, self.crown_image_id, intent,
            self.freshness.outstanding, self.role_id, grant.env_measurement_digest,
            highest_authenticated_version=self.freshness.highest, challenge_ledger=disposable,
        )
        if result.decision != CHECKS_PASSED:
            raise FailClosed(result.reason)
        if grant.grant_id not in self._grants:
            self.machine.add(grant.grant_id, grant.target_role_id, grant.klass)
            self._grants[grant.grant_id] = grant_raw
            for state in ("OWNER_VERIFIED", SIGNED, "APPENDED", "CHECKPOINT_CREATED", "REQUIRED_WITNESS_ACKNOWLEDGED", "CHECKPOINTED", DELIVERED):
                self.machine.move(grant.grant_id, state)
        elif self.machine.get(grant.grant_id).state != DELIVERED:
            raise FailClosed("GRANT_STATE")
        self.machine.move(grant.grant_id, CONSUMER_CONFIRMED)
        return CONSUMER_CONFIRMED

    def _require_acks(self, grant, checkpoint: dict, acks: tuple[bytes, ...], registry) -> None:
        if grant.klass not in _ROUTINE:
            raise FailClosed("UNSUPPORTED_CURRENT_MILESTONE")
        seen = set()
        for ack in acks:
            parsed = parse_ack(ack)
            public = require_monitor(registry, parsed["witness_id"])
            ack_matches(ack, checkpoint, public)
            if parsed["witness_id"] in seen:
                continue
            seen.add(parsed["witness_id"])
        if self.m1_id not in seen:
            raise FailClosed("WITNESS")

    def _require_ancestor(self, prev: bytes) -> None:
        ancestor = self.log.ancestor(prev)
        if ancestor is None:
            raise FailClosed("STALE_HEAD")
        for raw in self.log.records_since(ancestor["tree_size"]):
            if parse_record(raw)["kind"] not in NON_STATE_CHANGING:
                raise FailClosed("STALE_HEAD")

    def reconfirm(self, grant_id: bytes, intent: IntentSheet) -> str:
        slot = self.machine.get(grant_id)
        if not slot.reconfirm_required:
            raise FailClosed("GRANT_STATE")
        grant_raw = self._grant_bytes(grant_id)
        grant = parse_grant(grant_raw)
        self.freshness.evaluate(grant, parse_registry(self.registry_raw))
        disposable = ChallengeLedger(grant.challenge)
        result = consumer_verify(
            grant_raw, self.registry_raw, self.tokens, self.floors, self.crown_image_id, intent,
            grant.challenge, self.role_id, grant.env_measurement_digest,
            highest_authenticated_version=self.freshness.highest, challenge_ledger=disposable,
        )
        if result.decision != CHECKS_PASSED:
            raise FailClosed(result.reason)
        self.machine.clear_reconfirm(grant_id)
        return CONSUMER_CONFIRMED

    def activate(self, grant_id: bytes) -> str:
        slot = self.machine.get(grant_id)
        if slot.reconfirm_required or slot.wall_expired:
            raise FailClosed("RECONFIRM" if slot.reconfirm_required else "EXPIRED")
        if slot.state != CONSUMER_CONFIRMED:
            raise FailClosed("FORBIDDEN_TRANSITION")
        grant = parse_grant(self._grant_bytes(grant_id))
        self.freshness.consume(grant.challenge)
        self.machine.move(grant_id, ACTIVE)
        self.machine.note_activation_tick(grant_id, self._ticks)
        self._live.add(bytes(grant_id))
        self.log.append(
            kind=KIND_CONSUMPTION, payload_digest=hashlib.sha256(grant_id).digest(), grant_id=grant_id,
            epoch=self.epoch, registry_version=self.freshness.highest,
        )
        self.durable_commit()
        return ACTIVE

    def rehearse(self, grant_id: bytes) -> str:
        """Software rehearsal only. The authorization locks do not move."""
        from orca.rse.imp1.locks import corpus_generation_authorized, qualification_authorized, training_authorized
        slot = self.machine.get(grant_id)
        if slot.state != ACTIVE or bytes(grant_id) not in self._live:
            raise FailClosed("INTERRUPTED" if slot.state == INTERRUPTED else "GRANT_STATE")
        if corpus_generation_authorized() or qualification_authorized() or training_authorized():
            raise FailClosed("LOCK")
        if bytes(grant_id) in self._executed:
            raise FailClosed("DOUBLE_EXECUTION")
        self._executed.add(bytes(grant_id))
        self.executions += 1
        return "NOT_AUTHORIZED"

    def consume(self, grant_id: bytes) -> str:
        if self.machine.get(grant_id).state != ACTIVE:
            raise FailClosed("GRANT_STATE")
        self.machine.move(grant_id, CONSUMED)
        return CONSUMED

    def commit_evidence(self, grant_id: bytes, result_digest: bytes) -> str:
        slot = self.machine.get(grant_id)
        if slot.state != CONSUMED:
            raise FailClosed("GRANT_STATE")
        if len(result_digest) != 32:
            raise FailClosed("DIGEST")
        self.log.append(
            kind=KIND_RESULT, payload_digest=bytes(result_digest), grant_id=grant_id,
            epoch=self.epoch, registry_version=self.freshness.highest,
        )
        self.machine.move(grant_id, EVIDENCE_PENDING)
        return EVIDENCE_PENDING

    def finish(self, grant_id: bytes) -> str:
        slot = self.machine.get(grant_id)
        if slot.state != EVIDENCE_PENDING or not slot.evidence_durable:
            raise FailClosed("GRANT_STATE")
        self.machine.move(grant_id, "COMPLETE")
        return "COMPLETE"

    def rerun(self, grant_id: bytes) -> None:
        raise FailClosed("DOUBLE_EXECUTION")

    def observe_clock(self, reading: int) -> None:
        if not isinstance(reading, int) or isinstance(reading, bool) or reading < 0:
            raise FailClosed("CLOCK")
        if self._clock is not None and reading < self._clock:
            reading = self._clock
        self._clock = reading
        for slot in self.machine.slots():
            if slot.state not in PRE_ACTIVE:
                continue
            grant = parse_grant(self._grants[slot.grant_id])
            if grant.not_after and reading > grant.not_after:
                self.machine.note_wall_expired(slot.grant_id)
                self.machine.move(slot.grant_id, EXPIRED)

    def observe_ticks(self, ticks: int) -> None:
        if not isinstance(ticks, int) or isinstance(ticks, bool) or ticks < self._ticks:
            raise FailClosed("MONOTONIC")
        self._ticks = ticks
        for slot in self.machine.slots():
            if slot.state != ACTIVE or slot.activation_tick is None:
                continue
            grant = parse_grant(self._grants[slot.grant_id])
            if ticks - slot.activation_tick > grant.max_runtime_s:
                self._forfeit(slot.grant_id)
                self.machine.move(slot.grant_id, INTERRUPTED)
                self._live.discard(slot.grant_id)

    def revoke(self, grant_id: bytes) -> str:
        slot = self.machine.get(grant_id)
        if slot.state == ACTIVE:
            raise FailClosed("GRANT_STATE")
        self.machine.move(grant_id, REVOKED)
        return REVOKED

    def incident(self, grant_id: bytes) -> str:
        if self.machine.get(grant_id).state != ACTIVE:
            raise FailClosed("GRANT_STATE")
        self._forfeit(grant_id)
        self.machine.move(grant_id, INTERRUPTED)
        self._live.discard(bytes(grant_id))
        return INTERRUPTED

    def advance_registry(self, registry_raw: bytes, prior_raw: bytes) -> None:
        prior = parse_registry(bytes(prior_raw))
        self.freshness.authenticate(bytes(registry_raw), self.tokens, self.floors, prior)
        self.registry_raw = bytes(registry_raw)

    def stage_output(self, digest: bytes) -> str:
        return self.egress.stage(digest)

    def accept_result(self, digest: bytes, *, record: bytes, inclusion: bytes, checkpoint: bytes, ack: bytes) -> None:
        registry = parse_registry(self.registry_raw)
        public = _public(self.role_key)
        head = parse_checkpoint(checkpoint, public)
        parsed = parse_record(record)
        if parsed["kind"] != KIND_RESULT or parsed["payload_digest"] != digest:
            raise FailClosed("RESULT")
        proof = parse_inclusion(inclusion)
        if proof["tree_size"] != head["tree_size"]:
            raise FailClosed("CHECKPOINT")
        if proof["leaf"] != leaf_hash(record):
            raise FailClosed("LEAF")
        verify_inclusion(proof["leaf"], proof["index"], proof["tree_size"], proof["proof"], head["root"])
        witness = require_monitor(registry, self.m1_id)
        ack_matches(ack, head, witness)
        self.egress.note_witnessed(digest, admit=self.egress._admit)

    def seal_frames(self, sender: Sender, **kwargs) -> tuple[bytes, ...]:
        """Seal with the session hedge counter and commit that counter first."""
        if not isinstance(sender, Sender) or "before_return" in kwargs:
            raise FailClosed("UNEXPECTED_ARGUMENT")
        sender.counters = self.counters
        return sender.seal(**kwargs, before_return=self.durable_commit)

    def classify(self, digest: bytes, status: str) -> str:
        return self.egress.classify(digest, status)

    def promote(self, source_class: str, target_class: str) -> None:
        promotes(source_class, target_class)

    def _grant_bytes(self, grant_id: bytes) -> bytes:
        try:
            return self._grants[bytes(grant_id)]
        except KeyError as exc:
            raise FailClosed("GRANT_ABSENT") from exc


def _monitor_env(registry, role_id: bytes) -> bytes:
    require_monitor(registry, role_id)
    return parse_enrolment(registry.by_id(role_id).tail)["environment_measurement"]


def _len_blob(blob: bytes) -> bytes:
    return struct.pack(">I", len(blob)) + blob


def _take(data: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(data):
        raise FailClosed("JOURNAL")
    length = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    if length > len(data) - offset:
        raise FailClosed("JOURNAL")
    return data[offset:offset + length], offset + length


def _parse_blob(blob: bytes) -> dict:
    data = bytes(blob)
    if len(data) < 4 + 1 + 32 + 32 + 96 or data[:4] != b"OBS1" or data[4] != 2:
        raise FailClosed("JOURNAL")
    offset = 5
    role_id = data[offset:offset + 32]
    offset += 32
    epoch, authority, ticks, clock_raw, generation = struct.unpack_from(">IIQQQ", data, offset)
    offset += 32
    crown = data[offset:offset + 32]
    offset += 32
    m1 = data[offset:offset + 32]
    offset += 32
    m2 = data[offset:offset + 32]
    offset += 32
    machine_raw, offset = _take(data, offset)
    fresh_raw, offset = _take(data, offset)
    log_raw, offset = _take(data, offset)
    egress_raw, offset = _take(data, offset)
    registry, offset = _take(data, offset)
    if offset + 4 > len(data):
        raise FailClosed("JOURNAL")
    grant_count = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    grants = {}
    for _ in range(grant_count):
        raw, offset = _take(data, offset)
        grant = parse_grant(raw)
        if grant.grant_id in grants:
            raise FailClosed("REPLAY")
        grants[grant.grant_id] = raw
    if offset + 4 > len(data):
        raise FailClosed("JOURNAL")
    delivery_count = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    delivery = {}
    for _ in range(delivery_count):
        if offset + 16 + 4 > len(data):
            raise FailClosed("JOURNAL")
        key = data[offset:offset + 16]
        offset += 16
        raw, offset = _take(data, offset)
        delivery[key] = raw
    if offset + 4 > len(data):
        raise FailClosed("JOURNAL")
    bound_count = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    bound = {}
    for _ in range(bound_count):
        if offset + 24 > len(data):
            raise FailClosed("JOURNAL")
        key = data[offset:offset + 16]
        index = struct.unpack_from(">Q", data, offset + 16)[0]
        offset += 24
        bound[key] = index
    recipient_raw, offset = _take(data, offset)
    counter_raw, offset = _take(data, offset)
    if offset != len(data):
        raise FailClosed("TRAILING")
    return {
        "role_id": role_id, "epoch": epoch, "authority_version": authority, "ticks": ticks,
        "generation": generation,
        "clock": None if clock_raw == 0 else clock_raw - 1, "crown_image": crown, "m1": m1, "m2": m2,
        "machine": GrantMachine.parse(machine_raw), "freshness": RoleFreshness.parse(fresh_raw),
        "egress": Egress.parse(egress_raw), "log": log_raw, "registry": registry,
        "grants": grants, "delivery": delivery, "bound": bound,
        "recipient": RecipientJournal.parse(recipient_raw),
        "counters": CounterJournal.parse(counter_raw),
    }


def _pack_delivery(grant: bytes, record: bytes, inclusion: bytes, checkpoint: bytes, acks: tuple[bytes, ...], registry: bytes) -> bytes:
    if not 1 <= len(acks) <= 4:
        raise FailClosed("WITNESS")
    if len(record) != OEL1_LEN or len(inclusion) != OCI1_LEN or len(checkpoint) != OCK1_LEN:
        raise FailClosed("DELIVERY")
    for ack in acks:
        if len(ack) != OCA1_LEN:
            raise FailClosed("ACK_LEN")
    return b"".join((
        b"ODL1", bytes([1]), struct.pack(">I", len(grant)), grant, record, inclusion, checkpoint,
        bytes([len(acks)]), b"".join(acks), struct.pack(">I", len(registry)), registry,
    ))


def _parse_delivery(raw: bytes):
    data = bytes(raw)
    if len(data) < 8 or data[:4] != b"ODL1" or data[4] != 1:
        raise FailClosed("DELIVERY")
    offset = 5
    grant, offset = _take(data, offset)
    if offset + OEL1_LEN + OCI1_LEN + OCK1_LEN + 1 > len(data):
        raise FailClosed("DELIVERY")
    record = data[offset:offset + OEL1_LEN]
    offset += OEL1_LEN
    inclusion = data[offset:offset + OCI1_LEN]
    offset += OCI1_LEN
    checkpoint = data[offset:offset + OCK1_LEN]
    offset += OCK1_LEN
    count = data[offset]
    offset += 1
    if not 1 <= count <= 4 or offset + count * OCA1_LEN > len(data):
        raise FailClosed("WITNESS")
    acks = tuple(data[offset + i * OCA1_LEN:offset + (i + 1) * OCA1_LEN] for i in range(count))
    offset += count * OCA1_LEN
    registry, offset = _take(data, offset)
    if offset != len(data):
        raise FailClosed("TRAILING")
    parse_grant(grant)
    return grant, record, inclusion, checkpoint, acks, registry
