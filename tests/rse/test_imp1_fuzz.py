"""Deterministic mutations of the IMP-1 parsers. No path may return ALLOW, PASS, or APPROVED."""

from __future__ import annotations

import hashlib

from orca.rse.imp1.authority import consumer_verify, crown_validate, grant_sas
from orca.rse.imp1.codec import parse_grant, parse_registry
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, QUARANTINE
from tests.rse.support import CHALLENGE, FLOORS, TOKENS, g_intent, simple_g

_CLOSED = {FAIL_CLOSED, QUARANTINE}


def _rng(seed: int):
    x = seed or 1

    def nxt():
        nonlocal x
        x ^= (x >> 12) & 0xFFFFFFFFFFFFFFFF
        x ^= (x << 25) & 0xFFFFFFFFFFFFFFFF
        x ^= (x >> 27) & 0xFFFFFFFFFFFFFFFF
        x = (x * 2685821657736338717) & 0xFFFFFFFFFFFFFFFF
        return x

    return nxt


def test_fuzz_registry_grant_crown_consumer_and_sas():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    parsed = parse_grant(grant)
    nxt = _rng(20261007)
    seen_closed = set()
    for i in range(400):
        kind = nxt() % 8
        blob = bytearray(registry.raw if kind < 4 else grant)
        if kind == 0:
            blob = blob[: nxt() % (len(blob) + 1)]
        elif kind == 1:
            blob += bytes([nxt() & 0xFF])
        elif kind == 2:
            if blob:
                blob[nxt() % len(blob)] = nxt() & 0xFF
            if len(blob) > 4:
                blob[4] = 2 + (nxt() % 20)
        elif kind == 3:
            blob = b"\xff" * 8 + bytes(blob)
        elif kind == 4:
            blob = blob[: nxt() % (len(blob) + 1)]
        elif kind == 5:
            blob += b"\x00"
        elif kind == 6:
            if len(blob) > 40:
                blob[34] ^= 0x01
        else:
            if len(blob) > 200:
                blob[-1] ^= 0x01
        raw = bytes(blob)
        reg = _closed(lambda: parse_registry(raw))
        gr = _closed(lambda: parse_grant(raw))
        crown = crown_validate(raw, registry.raw, TOKENS, FLOORS, image)
        consumer = consumer_verify(grant if kind < 4 else raw, raw if kind < 4 else registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE)
        sas_decision = _sas(parsed.klass if kind % 2 == 0 else 0x99, raw[:64])
        for decision in (reg, gr, crown.decision, consumer.decision, sas_decision):
            assert decision in _CLOSED or decision == CHECKS_PASSED
            assert decision not in {"ALLOW", "PASS", "APPROVED"}
        if crown.decision == CHECKS_PASSED:
            assert raw == grant
        if kind == 0 and len(raw) < len(registry.raw):
            seen_closed.add(reg)
    assert seen_closed <= _CLOSED
    assert FAIL_CLOSED in seen_closed
    # Intact inputs still parse. Fuzz must not have mutated the fixtures.
    assert parse_registry(registry.raw).registry_root == registry.registry_root
    assert hashlib.sha256(grant).digest() == hashlib.sha256(parse_grant(grant).raw).digest()


def _closed(fn) -> str:
    try:
        fn()
    except Exception:
        return FAIL_CLOSED
    return CHECKS_PASSED


def _sas(klass, signed) -> str:
    try:
        grant_sas(klass, signed)
    except Exception:
        return FAIL_CLOSED
    return CHECKS_PASSED
