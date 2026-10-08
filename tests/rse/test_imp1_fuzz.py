"""Deterministic mutations. A mutated object must not reach CHECKS_PASSED.

Iteration count is fixed: 4 seeds x 100 mutations. Expected SAS and Merkle
answers live in test_imp1r_clarification.py and are not produced here.
"""

from __future__ import annotations

from orca.rse.imp1.authority import consumer_verify, crown_validate
from orca.rse.imp1.codec import parse_grant, parse_registry
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, QUARANTINE
from tests.rse.support import CHALLENGE, FLOORS, TOKENS, consumer_args, g_intent, simple_g

SEEDS = (20261008, 0xC1A51F1E, 11, 99)
PER_SEED = 100
FUZZ_ITERATIONS = len(SEEDS) * PER_SEED


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


def _mutate(blob: bytes, kind: int, nxt) -> bytes:
    data = bytearray(blob)
    if kind == 0:
        return bytes(data[: nxt() % len(data)])
    if kind == 1:
        return bytes(data) + bytes([nxt() & 0xFF])
    if kind == 2 and data:
        data[nxt() % len(data)] ^= 1 + (nxt() % 255)
        return bytes(data)
    if kind == 3 and len(data) > 4:
        data[4] = 2 + (nxt() % 20)
        return bytes(data)
    if kind == 4 and len(data) > 45:
        data[41:45] = (int.from_bytes(data[41:45], "big") ^ 0x01).to_bytes(4, "big")
        return bytes(data)
    if kind == 5 and len(data) > 80:
        data[45], data[46] = data[46], data[45]
        return bytes(data)
    if kind == 6:
        changed = bytes(data) + data[:32]
    else:
        changed = bytes(data[:-1] if data else b"")
    if changed == blob:
        changed = bytes(blob) + b"\xff"
    return changed


def test_fuzz_mutations_do_not_reach_semantic_success():
    assert FUZZ_ITERATIONS == 400
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    role, env = consumer_args(parts)
    intent = g_intent(registry, grant, parts)
    assert crown_validate(grant, registry.raw, TOKENS, FLOORS, image).decision == CHECKS_PASSED
    closed = 0
    for seed in SEEDS:
        nxt = _rng(seed)
        for _ in range(PER_SEED):
            kind = nxt() % 8
            target_grant = kind % 2 == 0
            raw = _mutate(grant if target_grant else registry.raw, kind, nxt)
            assert raw != (grant if target_grant else registry.raw)
            if target_grant:
                crown = crown_validate(raw, registry.raw, TOKENS, FLOORS, image)
                consumer = consumer_verify(
                    raw, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
                )
            else:
                crown = crown_validate(grant, raw, TOKENS, FLOORS, image)
                consumer = consumer_verify(
                    grant, raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
                )
            assert crown.decision in {FAIL_CLOSED, QUARANTINE}
            assert consumer.decision in {FAIL_CLOSED, QUARANTINE}
            assert crown.decision != CHECKS_PASSED
            assert consumer.decision != CHECKS_PASSED
            for parser in (parse_registry, parse_grant):
                try:
                    parser(raw)
                except Exception:
                    closed += 1
    assert closed > 0
    assert parse_registry(registry.raw).registry_root == registry.registry_root
    assert parse_grant(grant).raw == grant
