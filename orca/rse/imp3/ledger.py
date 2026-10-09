"""Append-only evidence log, checkpoints, and Monitor-Lite acknowledgement.

Witnesses are enrolled MONITOR_LITE keys. A container, a role key, or a
second copy of the same witness is not an independent witness.

``Monitor`` memory is not durable independent evidence. Fork history survives
a restart only when ``export`` / ``boot`` restore the OMJ1 journal. OMJ1 is a
bounded recommended layout; the freeze defines OCP1 and does not number OMJ1.
"""

from __future__ import annotations

import hashlib
import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from orca.rse.imp1.codec import Registry, parse_enrolment, parse_grant
from orca.rse.imp1.profiles import APPROVED, ENROLMENT, ROLE_MONITOR_LITE
from orca.rse.imp1.verdict import FailClosed, Quarantine
from orca.rse.imp3.journal import JournalSink, SyntheticFence
from orca.rse.imp3.merkle import (
    consistency_proof,
    inclusion_proof,
    leaf_hash,
    tree_hash,
    verify_consistency,
    verify_inclusion,
)
from orca.rse.imp3.records import (
    KIND_GRANT,
    OCA1_LEN,
    pack_ack,
    pack_checkpoint,
    pack_inclusion,
    pack_record,
    pack_witness_request,
    parse_ack,
    parse_checkpoint,
    parse_inclusion,
    parse_record,
    parse_witness_request,
    record_id,
)

ZERO = bytes(32)


class EvidenceLog:
    """One role's append-only log. History is not rewritten."""

    def __init__(self, log_id: bytes, epoch_floor: int) -> None:
        if not isinstance(log_id, (bytes, bytearray)) or len(log_id) != 32:
            raise FailClosed("LOG_ID")
        self.log_id = bytes(log_id)
        self.epoch_floor = epoch_floor
        self._records: list[bytes] = []
        self._leaves: list[bytes] = []
        self._checkpoints: list[dict] = []
        self._acks: dict[tuple[int, bytes], bytes] = {}
        self.quarantined = False

    @property
    def size(self) -> int:
        return len(self._records)

    @property
    def root(self) -> bytes:
        if not self._leaves:
            raise FailClosed("EMPTY_TREE")
        return tree_hash(self._leaves)

    @property
    def head(self) -> bytes:
        if not self._checkpoints:
            return ZERO
        return self._checkpoints[-1]["digest"]

    def covered_size(self) -> int:
        if not self._checkpoints:
            return 0
        return self._checkpoints[-1]["tree_size"]

    def append(self, *, kind: int, payload_digest: bytes, grant_id: bytes, epoch: int, registry_version: int) -> bytes:
        if self.quarantined:
            raise Quarantine("QUARANTINED")
        if epoch < self.epoch_floor:
            raise FailClosed("EPOCH_FLOOR")
        prev = record_id(self._records[-1]) if self._records else ZERO
        raw = pack_record(
            kind=kind, index=len(self._records), payload_digest=payload_digest, grant_id=grant_id,
            epoch=epoch, registry_version=registry_version, prev_digest=prev,
        )
        self._records.append(raw)
        self._leaves.append(leaf_hash(raw))
        return raw

    def append_grant(self, grant_raw: bytes, *, epoch: int, registry_version: int) -> tuple[int, bytes]:
        digest = hashlib.sha256(bytes(grant_raw)).digest()
        raw = self.append(
            kind=KIND_GRANT, payload_digest=digest, grant_id=grant_raw[6:22],
            epoch=epoch, registry_version=registry_version,
        )
        return len(self._records) - 1, raw

    def checkpoint(self, role_key: Ed25519PrivateKey, *, epoch: int, registry_version: int) -> bytes:
        if self.quarantined:
            raise Quarantine("QUARANTINED")
        if not self._leaves:
            raise FailClosed("EMPTY_TREE")
        if epoch < self.epoch_floor:
            raise FailClosed("EPOCH_FLOOR")
        prev = self.head
        raw = pack_checkpoint(
            log_id=self.log_id, tree_size=self.size, root=self.root, epoch=epoch,
            registry_version=registry_version, prev_checkpoint_digest=prev, role_key=role_key,
        )
        parsed = parse_checkpoint(raw)
        if self._checkpoints:
            previous = self._checkpoints[-1]
            if parsed["tree_size"] < previous["tree_size"]:
                self.quarantined = True
                raise Quarantine("ROLLBACK")
            if parsed["tree_size"] == previous["tree_size"] and parsed["root"] != previous["root"]:
                self.quarantined = True
                raise Quarantine("FORK")
            if parsed["prev_checkpoint_digest"] != previous["digest"]:
                raise FailClosed("CHECKPOINT_CHAIN")
        elif parsed["prev_checkpoint_digest"] != ZERO:
            raise FailClosed("CHECKPOINT_CHAIN")
        self._checkpoints.append(parsed)
        return raw

    def prove_inclusion(self, index: int) -> bytes:
        return self.prove_inclusion_at(index, self.size)

    def prove_inclusion_at(self, index: int, tree_size: int) -> bytes:
        if tree_size < 1 or tree_size > len(self._leaves) or index >= tree_size:
            raise FailClosed("PROOF")
        leaves = self._leaves[:tree_size]
        proof = inclusion_proof(leaves, index)
        return pack_inclusion(leaf=leaves[index], index=index, tree_size=tree_size, proof=proof)

    def witness_request(self, checkpoint: bytes, *, source_role_id: bytes, witness_id: bytes,
                        packet_seq: int, old_tree_size: int) -> bytes:
        parsed = parse_checkpoint(checkpoint)
        if parsed["log_id"] != self.log_id or parsed["tree_size"] != self.size or parsed["root"] != self.root:
            raise FailClosed("CHECKPOINT")
        if old_tree_size == parsed["tree_size"]:
            proof: tuple[bytes, ...] = ()
        elif old_tree_size == 0:
            proof = ()
        else:
            proof = consistency_proof(old_tree_size, self._leaves)
        return pack_witness_request(
            packet_seq=packet_seq, source_role_id=source_role_id, target_witness_id=witness_id,
            checkpoint=checkpoint, old_tree_size=old_tree_size, proof=proof,
        )

    def store_ack(self, ack: bytes) -> None:
        parsed = parse_ack(ack)
        if parsed["log_id"] != self.log_id:
            raise FailClosed("LOG_ID")
        key = (parsed["tree_size"], parsed["witness_id"])
        current = self._acks.get(key)
        if current is not None and current != ack:
            raise FailClosed("ACK_CONFLICT")
        bound = self.checkpoint_for(parsed["tree_size"])
        if bound["root"] != parsed["root"] or bound["epoch"] != parsed["epoch"]:
            raise FailClosed("STALE_CHECKPOINT")
        self._acks[key] = bytes(ack)

    def covering(self, index: int) -> dict:
        """Earliest checkpoint that includes this leaf. A later checkpoint is not a substitute."""
        candidates = [item for item in self._checkpoints if item["tree_size"] > index]
        if not candidates:
            raise FailClosed("CHECKPOINT")
        return min(candidates, key=lambda item: item["tree_size"])

    def checkpoint_for(self, tree_size: int) -> dict:
        for item in self._checkpoints:
            if item["tree_size"] == tree_size:
                return item
        raise FailClosed("CHECKPOINT")

    def acks_for(self, tree_size: int) -> tuple[bytes, ...]:
        return tuple(raw for (size, _witness), raw in sorted(self._acks.items()) if size == tree_size)

    def record(self, index: int) -> bytes:
        if index < 0 or index >= len(self._records):
            raise FailClosed("LEAF")
        return self._records[index]

    def records_since(self, tree_size: int) -> tuple[bytes, ...]:
        if tree_size < 0 or tree_size > len(self._records):
            raise FailClosed("TREE")
        return tuple(self._records[tree_size:])

    def export(self) -> bytes:
        parts = [
            b"OLG1", bytes([1]), self.log_id, struct.pack(">II", self.epoch_floor, len(self._records)),
            b"".join(self._records), struct.pack(">I", len(self._checkpoints)),
        ]
        parts.extend(item["raw"] for item in self._checkpoints)
        acks = [self._acks[key] for key in sorted(self._acks)]
        parts.append(struct.pack(">I", len(acks)))
        parts.extend(acks)
        parts.append(bytes([1 if self.quarantined else 0]))
        return b"".join(parts)

    @classmethod
    def parse(cls, raw: bytes, public_key: bytes) -> "EvidenceLog":
        data = bytes(raw)
        if len(data) < 4 + 1 + 32 + 8 or data[:4] != b"OLG1" or data[4] != 1:
            raise FailClosed("LOG")
        log_id = data[5:37]
        epoch_floor, count = struct.unpack_from(">II", data, 37)
        offset = 45
        log = cls(log_id, epoch_floor)
        if count > 100000 or offset + count * 102 > len(data):
            raise FailClosed("LOG")
        for index in range(count):
            record = data[offset:offset + 102]
            offset += 102
            parsed = parse_record(record)
            if parsed["index"] != index:
                raise Quarantine("LOG")
            log._records.append(record)
            log._leaves.append(leaf_hash(record))
        if offset + 4 > len(data):
            raise FailClosed("LOG")
        checkpoints = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        for _ in range(checkpoints):
            if offset + 181 > len(data):
                raise FailClosed("LOG")
            raw_checkpoint = data[offset:offset + 181]
            offset += 181
            parsed = parse_checkpoint(raw_checkpoint, public_key)
            if parsed["log_id"] != log.log_id or parsed["tree_size"] > len(log._leaves):
                raise Quarantine("LOG")
            if tree_hash(log._leaves[:parsed["tree_size"]]) != parsed["root"]:
                raise Quarantine("LOG")
            log._checkpoints.append(parsed)
        if offset + 4 > len(data):
            raise FailClosed("LOG")
        ack_count = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        for _ in range(ack_count):
            if offset + 217 > len(data):
                raise FailClosed("LOG")
            ack = data[offset:offset + 217]
            offset += 217
            parsed = parse_ack(ack)
            log._acks[(parsed["tree_size"], parsed["witness_id"])] = ack
        if offset + 1 != len(data):
            raise FailClosed("TRAILING")
        log.quarantined = data[offset] == 1
        if data[offset] not in (0, 1):
            raise FailClosed("LOG")
        return log

    def ancestor(self, digest: bytes) -> dict | None:
        if digest == ZERO:
            return {"tree_size": 0, "digest": ZERO, "root": ZERO}
        for item in self._checkpoints:
            if item["digest"] == digest:
                return item
        return None


_MAX_LOGS = 64
_MAX_PACKETS = 256


class Monitor:
    """Secret-free witness. It stores sizes and roots, never grant plaintext.

    Fields on this object are process memory. They are not durable evidence
    and they are not an independent witness. ``export`` writes the OMJ1
    journal; ``boot`` is the recovery path. A new ``Monitor()`` has no fork
    history.
    """

    def __init__(self, witness_id: bytes, witness_key: Ed25519PrivateKey, *, epoch_floor: int,
                 sink: JournalSink | None = None, fence: SyntheticFence | None = None) -> None:
        """First boot of an empty witness journal.

        ``sink`` and ``fence`` are required. A fence that has already
        authenticated a journal cannot be reused as a new witness. The empty
        journal is committed before this constructor returns.
        """
        if len(witness_id) != 32:
            raise FailClosed("WITNESS")
        if not isinstance(fence, SyntheticFence) or not fence.virgin or not callable(getattr(sink, "commit", None)):
            raise FailClosed("FENCE")
        self.witness_id = bytes(witness_id)
        self._key = witness_key
        self.epoch_floor = epoch_floor
        self.generation = 0
        self.registry_version = 0
        self.prev_checkpoint = bytes(32)
        self.log_root = bytes(32)
        self._last: dict[bytes, dict] = {}
        self._packets: dict[tuple[bytes, bytes], tuple[int, bytes, bytes]] = {}
        self.sink = sink
        self.fence = fence
        self._durable_commit()

    def _durable_commit(self) -> None:
        previous = self.generation
        self.generation = previous + 1
        blob = self.export()
        try:
            self.sink.commit(blob)
            self.fence.advance(self.generation, hashlib.sha256(blob).digest())
        except FailClosed:
            self.generation = previous
            raise FailClosed("JOURNAL_COMMIT")
        except Exception as exc:
            self.generation = previous
            raise FailClosed("JOURNAL_COMMIT") from exc

    def _require_bound(self, sink, fence) -> None:
        if sink is not self.sink or fence is not self.fence or not isinstance(fence, SyntheticFence) or fence.virgin:
            raise FailClosed("FENCE")
        self.fence.authenticate(self.generation, hashlib.sha256(self.export()).digest())

    def consider(self, request: bytes, *, source_public: bytes, witness_public: bytes,
                 sink=None, fence=None) -> bytes:
        self._require_bound(sink, fence)
        if witness_public != self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw):
            raise FailClosed("WITNESS_KEY")
        if source_public == witness_public:
            raise FailClosed("INDEPENDENT_WITNESS")
        parsed = parse_witness_request(request)
        if parsed["target_witness_id"] != self.witness_id:
            raise FailClosed("WITNESS")
        pair = (parsed["source_role_id"], self.witness_id)
        seen = self._packets.get(pair)
        if seen is not None:
            if parsed["packet_seq"] < seen[0]:
                raise FailClosed("PACKET_REPLAY")
            if parsed["packet_seq"] == seen[0]:
                if hashlib.sha256(request).digest() != seen[1]:
                    raise FailClosed("PACKET_REPLAY")
                return seen[2]
        checkpoint = parse_checkpoint(parsed["checkpoint"], source_public)
        if checkpoint["log_id"] != parsed["source_role_id"]:
            raise FailClosed("LOG_ID")
        if checkpoint["epoch"] < self.epoch_floor:
            raise FailClosed("EPOCH_FLOOR")
        prior = self._last.get(checkpoint["log_id"])
        old = parsed["old_tree_size"]
        if prior is None:
            if old not in (0, checkpoint["tree_size"]):
                raise FailClosed("CONSISTENCY")
            if old == checkpoint["tree_size"] and parsed["proof"]:
                raise FailClosed("CONSISTENCY")
        else:
            if old != prior["tree_size"]:
                raise FailClosed("CONSISTENCY")
            if checkpoint["tree_size"] < prior["tree_size"]:
                raise FailClosed("ROLLBACK")
            if checkpoint["tree_size"] == prior["tree_size"]:
                if checkpoint["root"] != prior["root"] or parsed["proof"]:
                    raise Quarantine("FORK")
            else:
                verify_consistency(prior["tree_size"], checkpoint["tree_size"], prior["root"], checkpoint["root"], parsed["proof"])
        if checkpoint["epoch"] < (prior["epoch"] if prior else self.epoch_floor):
            raise FailClosed("EPOCH_FLOOR")
        ack = pack_ack(
            witness_id=self.witness_id, source_role_id=parsed["source_role_id"], log_id=checkpoint["log_id"],
            tree_size=checkpoint["tree_size"], root=checkpoint["root"], epoch=checkpoint["epoch"],
            witness_time=0, witness_key=self._key,
        )
        if len(self._last) >= _MAX_LOGS and checkpoint["log_id"] not in self._last:
            raise FailClosed("JOURNAL")
        if len(self._packets) >= _MAX_PACKETS and pair not in self._packets:
            raise FailClosed("JOURNAL")
        previous_last = dict(self._last)
        previous_packets = dict(self._packets)
        previous_generation = self.generation
        previous_registry = self.registry_version
        previous_prev = self.prev_checkpoint
        previous_root = self.log_root
        self._last[checkpoint["log_id"]] = {
            "tree_size": checkpoint["tree_size"], "root": checkpoint["root"], "epoch": checkpoint["epoch"],
        }
        self._packets[pair] = (parsed["packet_seq"], hashlib.sha256(request).digest(), ack)
        self.registry_version = checkpoint["registry_version"]
        self.prev_checkpoint = checkpoint["prev_checkpoint_digest"]
        self.log_root = checkpoint["root"]
        try:
            self._durable_commit()
        except FailClosed:
            self._last = previous_last
            self._packets = previous_packets
            self.generation = previous_generation
            self.registry_version = previous_registry
            self.prev_checkpoint = previous_prev
            self.log_root = previous_root
            raise
        return ack

    def export(self) -> bytes:
        """OMJ1. Bounded. Not a freeze-numbered record and not hardware evidence."""
        if len(self._last) > _MAX_LOGS or len(self._packets) > _MAX_PACKETS:
            raise FailClosed("JOURNAL")
        logs = bytearray()
        for log_id in sorted(self._last):
            item = self._last[log_id]
            logs += log_id + struct.pack(">Q", item["tree_size"]) + item["root"] + struct.pack(">I", item["epoch"])
        packets = bytearray()
        for (source, witness), (seq, request_hash, ack) in sorted(self._packets.items()):
            if len(ack) != OCA1_LEN:
                raise FailClosed("JOURNAL")
            packets += source + witness + struct.pack(">Q", seq) + request_hash + ack
        return b"".join((
            b"OMJ1", bytes([1]), struct.pack(">Q", self.generation), struct.pack(">I", self.epoch_floor),
            self.witness_id, struct.pack(">I", self.registry_version), self.prev_checkpoint, self.log_root,
            struct.pack(">I", len(self._last)), bytes(logs),
            struct.pack(">I", len(self._packets)), bytes(packets),
        ))

    @classmethod
    def boot(cls, blob: bytes, witness_key: Ed25519PrivateKey, *, sink=None, fence=None) -> "Monitor":
        """Restore OMJ1 only when this fence already committed that exact blob.

        A virgin fence is not a first boot. First boot is ``Monitor(...)``.
        """
        if not isinstance(fence, SyntheticFence) or fence.virgin or not callable(getattr(sink, "commit", None)):
            raise FailClosed("FENCE")
        data = bytes(blob)
        parsed = _parse_omj1(data)
        fence.authenticate(parsed["generation"], hashlib.sha256(data).digest())
        monitor = cls.__new__(cls)
        monitor.witness_id = parsed["witness_id"]
        monitor._key = witness_key
        monitor.epoch_floor = parsed["epoch_floor"]
        monitor.generation = parsed["generation"]
        monitor.registry_version = parsed["registry_version"]
        monitor.prev_checkpoint = parsed["prev_checkpoint"]
        monitor.log_root = parsed["log_root"]
        monitor._last = parsed["last"]
        monitor._packets = parsed["packets"]
        monitor.sink = sink
        monitor.fence = fence
        return monitor


def enrolment_key(registry: Registry, role_id: bytes, *, expect_type: int | None = None) -> bytes:
    entry = registry.by_id(role_id)
    if entry is None or entry.entry_type != ENROLMENT or entry.approval_state != APPROVED:
        raise FailClosed("ENROLMENT")
    fields = parse_enrolment(entry.tail)
    if expect_type is not None and fields["role_type"] != expect_type:
        raise FailClosed("ROLE_TYPE")
    return fields["ed25519_public_key"]


def require_monitor(registry: Registry, witness_id: bytes) -> bytes:
    """Docker and other non-enrolments are not witnesses. Only MONITOR_LITE is."""
    return enrolment_key(registry, witness_id, expect_type=ROLE_MONITOR_LITE)


def verify_grant_inclusion(*, grant_raw: bytes, record: bytes, inclusion: bytes, checkpoint: bytes,
                           crown_public: bytes) -> dict:
    parsed_record = parse_record(record)
    if parsed_record["kind"] != KIND_GRANT:
        raise FailClosed("RECORD_KIND")
    if parsed_record["grant_id"] != grant_raw[6:22]:
        raise FailClosed("GRANT_ID")
    if parsed_record["payload_digest"] != hashlib.sha256(grant_raw).digest():
        raise FailClosed("PAYLOAD")
    grant = parse_grant(grant_raw)
    if parsed_record["epoch"] != grant.incident_epoch:
        raise FailClosed("EPOCH")
    if parsed_record["registry_version"] != grant.registry_version:
        raise FailClosed("REGISTRY")
    proof = parse_inclusion(inclusion)
    leaf = leaf_hash(record)
    if proof["leaf"] != leaf or proof["index"] != parsed_record["index"]:
        raise FailClosed("LEAF")
    head = parse_checkpoint(checkpoint, crown_public)
    if head["epoch"] != grant.incident_epoch or head["registry_version"] != grant.registry_version:
        raise FailClosed("CHECKPOINT")
    if proof["tree_size"] != head["tree_size"] or head["tree_size"] <= parsed_record["index"]:
        raise FailClosed("STALE_CHECKPOINT")
    verify_inclusion(leaf, proof["index"], proof["tree_size"], proof["proof"], head["root"])
    return head


def _parse_omj1(data: bytes) -> dict:
    if len(data) < 4 + 1 + 8 + 4 + 32 + 4 + 32 + 32 + 8 or data[:4] != b"OMJ1" or data[4] != 1:
        raise FailClosed("JOURNAL")
    offset = 5
    generation = struct.unpack_from(">Q", data, offset)[0]
    offset += 8
    epoch_floor = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    witness_id = data[offset:offset + 32]
    offset += 32
    registry_version = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    prev_checkpoint = data[offset:offset + 32]
    offset += 32
    log_root = data[offset:offset + 32]
    offset += 32
    if offset + 4 > len(data):
        raise FailClosed("JOURNAL")
    log_count = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    if log_count > _MAX_LOGS or offset + log_count * (32 + 8 + 32 + 4) > len(data):
        raise FailClosed("JOURNAL")
    last: dict[bytes, dict] = {}
    for _ in range(log_count):
        log_id = data[offset:offset + 32]
        offset += 32
        tree_size = struct.unpack_from(">Q", data, offset)[0]
        offset += 8
        root = data[offset:offset + 32]
        offset += 32
        epoch = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if log_id in last or tree_size < 1:
            raise FailClosed("JOURNAL")
        last[log_id] = {"tree_size": tree_size, "root": root, "epoch": epoch}
    if offset + 4 > len(data):
        raise FailClosed("JOURNAL")
    packet_count = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    row = 32 + 32 + 8 + 32 + OCA1_LEN
    if packet_count > _MAX_PACKETS or offset + packet_count * row != len(data):
        raise FailClosed("JOURNAL")
    packets: dict[tuple[bytes, bytes], tuple[int, bytes, bytes]] = {}
    for _ in range(packet_count):
        source = data[offset:offset + 32]
        offset += 32
        witness = data[offset:offset + 32]
        offset += 32
        seq = struct.unpack_from(">Q", data, offset)[0]
        offset += 8
        request_hash = data[offset:offset + 32]
        offset += 32
        ack = data[offset:offset + OCA1_LEN]
        offset += OCA1_LEN
        if witness != witness_id or (source, witness) in packets:
            raise FailClosed("JOURNAL")
        parsed_ack = parse_ack(ack)
        if parsed_ack["witness_id"] != witness_id or parsed_ack["source_role_id"] != source:
            raise FailClosed("JOURNAL")
        if parsed_ack["log_id"] != source or parsed_ack["tree_size"] < 1:
            raise FailClosed("JOURNAL")
        bound = last.get(parsed_ack["log_id"])
        if bound is None or parsed_ack["tree_size"] > bound["tree_size"]:
            raise FailClosed("JOURNAL")
        if parsed_ack["tree_size"] == bound["tree_size"] and parsed_ack["root"] != bound["root"]:
            raise FailClosed("JOURNAL")
        packets[(source, witness)] = (seq, request_hash, ack)
    if log_root != bytes(32) and last:
        roots = {item["root"] for item in last.values()}
        if log_root not in roots:
            raise FailClosed("JOURNAL")
    return {
        "generation": generation,
        "epoch_floor": epoch_floor,
        "witness_id": witness_id,
        "registry_version": registry_version,
        "prev_checkpoint": prev_checkpoint,
        "log_root": log_root,
        "last": last,
        "packets": packets,
    }


def ack_matches(ack: bytes, checkpoint: dict, witness_public: bytes) -> dict:
    parsed = parse_ack(ack, witness_public)
    if parsed["log_id"] != checkpoint["log_id"]:
        raise FailClosed("LOG_ID")
    if parsed["tree_size"] != checkpoint["tree_size"] or parsed["root"] != checkpoint["root"]:
        raise FailClosed("STALE_CHECKPOINT")
    if parsed["epoch"] != checkpoint["epoch"]:
        raise FailClosed("EPOCH")
    if parsed["witness_time"] < 0:
        raise FailClosed("WITNESS_TIME")
    return parsed
