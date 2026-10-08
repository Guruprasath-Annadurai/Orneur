"""REVIEW_REFERENCE_ONLY: independent RFC 9180 base-mode reference used to derive EXPECTED values for audit.

DHKEM(X25519, HKDF-SHA256) / HKDF-SHA256 / ChaCha20Poly1305, mode_base only.
Written from RFC 9180 text for the audit package. It is NOT production code, must never be imported by
production code, and is not a substitute for a vetted library (RSE12_04 section 1/2 guardrail).
It exists so expected values do not come from the implementation under audit.
"""
import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives import serialization

KEM_ID, KDF_ID, AEAD_ID = 0x0020, 0x0001, 0x0003
NK, NN, NH = 32, 12, 32
MODE_BASE = 0
KEM_SUITE = b"KEM" + KEM_ID.to_bytes(2, "big")
HPKE_SUITE = b"HPKE" + KEM_ID.to_bytes(2, "big") + KDF_ID.to_bytes(2, "big") + AEAD_ID.to_bytes(2, "big")


def i2osp(n, w):
    return n.to_bytes(w, "big")


def extract(salt, ikm):
    return hmac.new(salt if salt else bytes(NH), ikm, hashlib.sha256).digest()


def expand(prk, info, length):
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def labeled_extract(suite, salt, label, ikm):
    return extract(salt, b"HPKE-v1" + suite + label + ikm)


def labeled_expand(suite, prk, label, info, length):
    return expand(prk, i2osp(length, 2) + b"HPKE-v1" + suite + label + info, length)


def pub_bytes(sk: X25519PrivateKey) -> bytes:
    return sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def derive_key_pair(ikm: bytes):
    prk = labeled_extract(KEM_SUITE, b"", b"dkp_prk", ikm)
    sk_bytes = labeled_expand(KEM_SUITE, prk, b"sk", b"", 32)
    sk = X25519PrivateKey.from_private_bytes(sk_bytes)
    return sk, pub_bytes(sk)


def dh(sk: X25519PrivateKey, pk_bytes: bytes) -> bytes:
    shared = sk.exchange(X25519PublicKey.from_public_bytes(pk_bytes))
    if shared == bytes(32):
        raise ValueError("ZERO_SHARED_SECRET")  # RFC 9180 7.1.4 / RFC 7748 6.1
    return shared


def extract_and_expand(dh_out, kem_context):
    eae = labeled_extract(KEM_SUITE, b"", b"eae_prk", dh_out)
    return labeled_expand(KEM_SUITE, eae, b"shared_secret", kem_context, 32)


def encap(pk_r: bytes, ikm_e: bytes):
    sk_e, enc = derive_key_pair(ikm_e)
    return extract_and_expand(dh(sk_e, pk_r), enc + pk_r), enc


def decap(enc: bytes, sk_r: X25519PrivateKey):
    pk_r = pub_bytes(sk_r)
    return extract_and_expand(dh(sk_r, enc), enc + pk_r)


def key_schedule(shared_secret: bytes, info: bytes):
    psk_id_hash = labeled_extract(HPKE_SUITE, b"", b"psk_id_hash", b"")
    info_hash = labeled_extract(HPKE_SUITE, b"", b"info_hash", info)
    ksc = bytes([MODE_BASE]) + psk_id_hash + info_hash
    secret = labeled_extract(HPKE_SUITE, shared_secret, b"secret", b"")
    key = labeled_expand(HPKE_SUITE, secret, b"key", ksc, NK)
    base_nonce = labeled_expand(HPKE_SUITE, secret, b"base_nonce", ksc, NN)
    return key, base_nonce, ksc, secret


def nonce_for(base_nonce: bytes, seq: int) -> bytes:
    return bytes(a ^ b for a, b in zip(base_nonce, i2osp(seq, NN)))


def seal(key, base_nonce, seq, aad, pt):
    return ChaCha20Poly1305(key).encrypt(nonce_for(base_nonce, seq), pt, aad)


def open_(key, base_nonce, seq, aad, ct):
    return ChaCha20Poly1305(key).decrypt(nonce_for(base_nonce, seq), ct, aad)
