"""IMP-4 OCR1 v2. Synthetic keys only. A checker pass is not corpus acceptance."""

from __future__ import annotations

import hashlib
import random

import pytest
from orca.rse.imp1.codec import public_of
from orca.rse.imp1.verdict import FailClosed, Quarantine
from orca.rse.imp4 import ocr1
from orca.rse.imp4.ocr1 import (
    FRAME_PT,
    HEADER_LEN,
    RecipientJournal,
    Sender,
    _reject_zero_shared,
    admit_rfc9180_base,
    build_header,
    enc_canonical,
    expected_count,
    ingest_phase1,
    ingest_phase2,
    ochk,
    open_frames,
    parse_frame,
    structural_phase,
)
from tests.rse.block1_support import authorize, ed_key, v_intent, v_tail, world, x_key, x_pub


def test_rfc9180_base_vector_is_admitted():
    admit_rfc9180_base()


def test_frame_count_bounds_do_not_allocate():
    assert expected_count(1) == 1
    assert expected_count(FRAME_PT) == 1
    assert expected_count(FRAME_PT + 1) == 2
    assert expected_count(65536 * FRAME_PT) == 65536
    with pytest.raises(FailClosed, match="FRAME_COUNT"):
        expected_count(65536 * FRAME_PT + 1)
    with pytest.raises(FailClosed, match="TOTAL_LEN"):
        expected_count(0)


@pytest.mark.parametrize("enc", [
    bytes(32),
    bytes(31) + b"\x80",
    ((1 << 255) - 19).to_bytes(32, "little"),
])
def test_malformed_enc_is_rejected(enc):
    with pytest.raises(FailClosed, match="ENC"):
        enc_canonical(enc)


def _v_session():
    registry, parts = world()
    _crown, witness, raw, _delivery = authorize(
        registry, parts, klass="V", target="witness", tail=v_tail(parts), intent_for=v_intent,
        grant_id=b"V" * 16, entropy=hashlib.sha256(b"ocr1-challenge").digest(),
    )
    return registry, parts, witness, raw


def _seal(parts, plaintext: bytes, *, sequence: int = 1, recipient=None, sender_id=None, grant_id=b"V" * 16,
          artifact=None, epoch: int = 1, entropy: bytes | None = None):
    sender = Sender(ed_key("forge"), parts["forge"].entry_id if sender_id is None else sender_id, hashlib.sha256(b"env").digest())
    return sender.seal(
        plaintext, typ=1, recipient_id=parts["witness"].entry_id if recipient is None else recipient,
        recipient_public=x_pub("witness"), grant_id=grant_id, artifact_id=parts["corpus"].entry_id if artifact is None else artifact,
        sequence=sequence, epoch=epoch, os_entropy=entropy or hashlib.sha256(b"ocr1-entropy-" + bytes([sequence])).digest(),
    )


def test_round_trip_and_signature_is_checked_before_decrypt():
    _registry, parts, witness, _raw = _v_session()
    frames = _seal(parts, ochk(b"synthetic-payload"))
    calls = []
    real = ocr1._SUITE.create_recipient_context

    def wrapped(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    ocr1._SUITE.create_recipient_context = wrapped
    try:
        broken = bytearray(frames[0])
        broken[-1] ^= 0x01
        with pytest.raises(FailClosed, match="BAD_SIGNATURE"):
            open_frames([bytes(broken)], sender_public=public_of(ed_key("forge")), recipient_private=x_key("witness"), journal=RecipientJournal())
        assert calls == []
        opened = open_frames(frames, sender_public=public_of(ed_key("forge")), recipient_private=x_key("witness"), journal=RecipientJournal())
    finally:
        ocr1._SUITE.create_recipient_context = real
    assert opened == ochk(b"synthetic-payload")
    assert calls == [1]


def test_phase1_does_not_decrypt_and_rejects_a_private_key_argument():
    _registry, parts, witness, _raw = _v_session()
    frames = list(_seal(parts, ochk(b"phase-1")))
    calls = []
    real = ocr1._SUITE.create_recipient_context
    ocr1._SUITE.create_recipient_context = lambda *a, **k: calls.append(1)
    try:
        view = ingest_phase1(witness, b"V" * 16, frames)
    finally:
        ocr1._SUITE.create_recipient_context = real
    assert view["decrypted"] is False
    assert view["acceptance"] == "ZERO_ACCEPTANCE_AUTHORITY"
    assert calls == []
    with pytest.raises(FailClosed, match="UNEXPECTED_ARGUMENT"):
        ingest_phase1(witness, b"V" * 16, frames, recipient_private=x_key("witness"))


def test_phase2_checker_pass_has_zero_acceptance_and_replay_dies():
    _registry, parts, witness, _raw = _v_session()
    frames = list(_seal(parts, ochk(b"checked")))
    phase1 = ingest_phase1(witness, b"V" * 16, frames)
    assert witness.activate(b"V" * 16) == "ACTIVE"
    opened = ingest_phase2(
        witness, b"V" * 16, frames, recipient_private=x_key("witness"), quarantine=phase1["quarantine"],
    )
    assert opened["verdict"] == "STRUCTURAL_OK"
    assert opened["acceptance"] == "ZERO_ACCEPTANCE_AUTHORITY"
    assert opened["executable"] is False
    with pytest.raises(FailClosed, match="REPLAY"):
        ingest_phase2(
            witness, b"V" * 16, frames, recipient_private=x_key("witness"),
            quarantine=phase1["quarantine"],
        )


def test_authenticated_malformed_plaintext_is_not_accepted():
    _registry, parts, witness, _raw = _v_session()
    malformed = b"OCHK" + bytes([1]) + (4).to_bytes(4, "big") + b"no"
    frames = list(_seal(parts, malformed))
    phase1 = ingest_phase1(witness, b"V" * 16, frames)
    witness.activate(b"V" * 16)
    opened = ingest_phase2(
        witness, b"V" * 16, frames, recipient_private=x_key("witness"),
        quarantine=phase1["quarantine"],
    )
    assert opened["verdict"] == "STRUCTURAL_REJECT"
    assert opened["acceptance"] == "ZERO_ACCEPTANCE_AUTHORITY"
    assert opened["executable"] is False


def test_substitution_and_reassembly_attacks():
    _registry, parts, witness, _raw = _v_session()
    plaintext = ochk(b"bind")
    frames = _seal(parts, plaintext)
    sender_public = public_of(ed_key("forge"))
    other = _seal(parts, ochk(b"other"), sequence=2, entropy=hashlib.sha256(b"other-entropy").digest())
    mixed = [frames[0], other[0]]
    with pytest.raises(FailClosed, match="FRAME_COUNT"):
        structural_phase(mixed, sender_public=sender_public)
    swapped_recipient = _seal(parts, plaintext, recipient=parts["forge"].entry_id, sequence=2,
                              entropy=hashlib.sha256(b"recipient").digest())
    with pytest.raises(FailClosed, match="BINDING"):
        ingest_phase1(witness, b"V" * 16, list(swapped_recipient))
    wrong_artifact = _seal(parts, plaintext, artifact=parts["forge"].entry_id, sequence=2,
                           entropy=hashlib.sha256(b"artifact").digest())
    with pytest.raises(FailClosed, match="BINDING"):
        ingest_phase1(witness, b"V" * 16, list(wrong_artifact))
    wrong_epoch = _seal(parts, plaintext, epoch=9, sequence=2, entropy=hashlib.sha256(b"epoch").digest())
    with pytest.raises(FailClosed, match="EPOCH"):
        ingest_phase1(witness, b"V" * 16, list(wrong_epoch))
    wrong_sequence = _seal(parts, plaintext, sequence=99, entropy=hashlib.sha256(b"sequence").digest())
    with pytest.raises(FailClosed, match="SEQUENCE"):
        ingest_phase1(witness, b"V" * 16, list(wrong_sequence))
    truncated = frames[0][:-1]
    with pytest.raises(FailClosed, match="FRAME"):
        parse_frame(truncated)
    short = frames[0][:10]
    with pytest.raises(FailClosed, match="TRUNCATED"):
        parse_frame(short)
    witness.activate(b"V" * 16)
    tampered_enc = bytearray(frames[0])
    # enc begins at byte 178. Re-signing is required for a signature-valid substitution.
    tampered_enc[178] ^= 0x01
    with pytest.raises(FailClosed, match="BAD_SIGNATURE"):
        structural_phase([bytes(tampered_enc)], sender_public=sender_public)


def test_multi_frame_reordering_duplicate_and_digest_mismatch():
    _registry, parts, _witness, _raw = _v_session()
    body = b"M" * (FRAME_PT + 20)
    frames = list(_seal(parts, body, entropy=hashlib.sha256(b"multi-frame").digest()))
    assert len(frames) == 2
    sender_public = public_of(ed_key("forge"))
    opened = open_frames(frames, sender_public=sender_public, recipient_private=x_key("witness"), journal=RecipientJournal())
    assert opened == body
    with pytest.raises(FailClosed, match="FRAME_ORDER"):
        structural_phase([frames[1], frames[0]], sender_public=sender_public)
    with pytest.raises(FailClosed, match="FRAME_ORDER"):
        structural_phase([frames[0], frames[0]], sender_public=sender_public)
    with pytest.raises(FailClosed, match="FRAME_COUNT"):
        structural_phase([frames[0]], sender_public=sender_public)
    with pytest.raises(FailClosed, match="FRAME_COUNT"):
        structural_phase([frames[0], frames[1], frames[1]], sender_public=sender_public)
    flipped = bytearray(frames[0])
    flipped[HEADER_LEN] ^= 0x01
    with pytest.raises(FailClosed, match="BAD_SIGNATURE"):
        structural_phase([bytes(flipped), frames[1]], sender_public=sender_public)


def test_zero_shared_secret_is_refused_before_open():
    _registry, parts, _witness, _raw = _v_session()
    frames = _seal(parts, ochk(b"zero"))

    class _ZeroKey:
        def exchange(self, _peer):
            return bytes(32)

    calls = []
    real_open = ocr1._SUITE.create_recipient_context
    ocr1._SUITE.create_recipient_context = lambda *a, **k: calls.append(1)
    try:
        with pytest.raises(FailClosed, match="ZERO_SHARED_SECRET"):
            open_frames(frames, sender_public=public_of(ed_key("forge")), recipient_private=_ZeroKey(), journal=RecipientJournal())
    finally:
        ocr1._SUITE.create_recipient_context = real_open
    assert calls == []


def test_enc_divergence_is_quarantined():
    journal = RecipientJournal()
    enc = bytes([1]) + bytes(31)
    sender = bytes([7]) * 32
    journal.admit(grant_id=b"V" * 16, sequence=1, enc=enc, bundle_digest=b"\x01" * 32, sender_id=sender)
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        journal.reject_replay(
            grant_id=b"V" * 16, sequence=2, enc=enc, bundle_digest=b"\x02" * 32, sender_id=sender,
        )
    assert journal.sender_quarantined(sender) is True
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        journal.reject_replay(
            grant_id=b"Z" * 16, sequence=3, enc=bytes([3]) + bytes(31),
            bundle_digest=b"\x03" * 32, sender_id=sender,
        )


def test_header_reencode_rejects_noncanonical_padding():
    header = build_header(
        typ=1, recipient_id=bytes(32), sender_id=bytes([2]) + bytes(31), grant_id=b"V" * 16,
        artifact_id=bytes([3]) + bytes(31), bundle_digest=bytes([4]) + bytes(31), sequence=1, epoch=1,
        frame_index=0, frame_count=1, total_len=1, enc=bytes([1]) + bytes(31),
    )
    assert len(header) == 210
    broken = bytearray(header)
    broken[5] = 9
    frame = bytes(broken) + bytes(17) + bytes(64)
    with pytest.raises(FailClosed, match="TYPE"):
        parse_frame(frame)


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 11, 19, 23])
def test_deterministic_fuzz_never_accepts_a_mutant(seed):
    _registry, parts, _witness, _raw = _v_session()
    frames = list(_seal(parts, ochk(b"fuzz-" + bytes([seed])), entropy=hashlib.sha256(b"fuzz" + bytes([seed])).digest()))
    sender_public = public_of(ed_key("forge"))
    rng = random.Random(seed)
    for _ in range(12):
        mutant = bytearray(frames[0])
        mutant[rng.randrange(len(mutant))] ^= 1 << rng.randrange(8)
        if bytes(mutant) == frames[0]:
            continue
        with pytest.raises((FailClosed, Quarantine)):
            open_frames([bytes(mutant)], sender_public=sender_public, recipient_private=x_key("witness"), journal=RecipientJournal())


def test_n12_low_order_enc_is_zero_shared_secret_on_the_real_library():
    """N12: a canonical low-order enc must not escape as ValueError.

    This calls cryptography's X25519 exchange. It does not mock the library.
    """
    points = [
        bytes.fromhex("e0eb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b800"),
        bytes.fromhex("0100000000000000000000000000000000000000000000000000000000000000"),
        bytes.fromhex("5f9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86d8224eddd09f1157"),
        bytes.fromhex("ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f"),
    ]
    private = x_key("witness")
    calls = []
    real = ocr1._SUITE.create_recipient_context
    ocr1._SUITE.create_recipient_context = lambda *a, **k: calls.append(1)
    try:
        for enc in points:
            enc_canonical(enc)
            with pytest.raises(FailClosed, match="ZERO_SHARED_SECRET"):
                _reject_zero_shared(private, enc)
            header = build_header(
                typ=1, recipient_id=bytes(32), sender_id=public_of(ed_key("forge")), grant_id=b"V" * 16,
                artifact_id=bytes([3]) + bytes(31), bundle_digest=hashlib.sha256(b"n12").digest(),
                sequence=1, epoch=1, frame_index=0, frame_count=1, total_len=4, enc=enc,
            )
            ciphertext = bytes(20)
            signature = ed_key("forge").sign(b"OCR1v2-SIG\x00" + header + ciphertext)
            with pytest.raises(FailClosed, match="ZERO_SHARED_SECRET"):
                open_frames(
                    [header + ciphertext + signature], sender_public=public_of(ed_key("forge")),
                    recipient_private=private, journal=RecipientJournal(),
                )
    finally:
        ocr1._SUITE.create_recipient_context = real
    assert calls == []
