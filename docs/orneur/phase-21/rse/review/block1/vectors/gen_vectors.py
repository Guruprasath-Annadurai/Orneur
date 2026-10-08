"""REVIEW_REFERENCE_ONLY: generate and self-check independent OCR1 v2 vectors from the frozen spec.

Expected outcomes below are written from the SPEC TEXT (RSE12_04 sections 3-7), then cross-checked against the
independent reference. They are not copied from any implementation under audit.
Keys are public deterministic TEST-ONLY seeds. Nothing here is secret. Output: ocr1_v2_independent_vectors.json
"""
import hashlib
import json
import struct
import sys

import hpke_ref as H
import ocr1v2_ref as O

sha = O.sha256
SELF = sha(b"RSE-REVIEW|role|recipient")
OTHER = sha(b"RSE-REVIEW|role|other-recipient")
SENDER = sha(b"RSE-REVIEW|role|sender")
GRANT = sha(b"RSE-REVIEW|grant")[:16]
ARTIFACT = sha(b"RSE-REVIEW|artifact")
ENV = sha(b"RSE-REVIEW|env")
G32 = sha(b"RSE-REVIEW|G32-fixed-for-vector")
EPOCH, SEQ, COUNTER = 2, 7, 1

sender_sk = O.ed25519_from_label("sender-ed25519")
attacker_sk = O.ed25519_from_label("attacker-ed25519")
recip_sk = O.x25519_from_label("recipient-x25519")
other_sk = O.x25519_from_label("other-recipient-x25519")
recip_pk, other_pk = H.pub_bytes(recip_sk), H.pub_bytes(other_sk)
enrolled = {SENDER: O.ed_pub(sender_sk)}
grant_ctx = dict(sender=SENDER, artifact=ARTIFACT, grant_id=GRANT, seq_first=1, seq_last=10, epoch=EPOCH)


def ikm_for(seq=SEQ, counter=COUNTER):
    return O.ephemeral_ikm(sender_sk, SENDER, ENV, GRANT, seq, counter, G32)


def seal(pt, *, frame_pt=None, recipient_id=SELF, recipient_pk=recip_pk, sk=sender_sk, typ=1, sender_id=SENDER,
         epoch=EPOCH, seq=SEQ, ikm=None):
    return O.seal_bundle(pt, typ=typ, recipient_id=recipient_id, sender_id=sender_id, grant_id=GRANT, artifact_id=ARTIFACT,
                         sequence=seq, epoch=epoch, sender_sk=sk, recipient_kem_pk=recipient_pk,
                         ikm_e=ikm or ikm_for(seq), frame_pt=frame_pt)


def run(frames, *, frame_pt=None, grant=grant_ctx, self_id=SELF):
    try:
        fs = O.phase1(frames, self_id=self_id, enrolled_senders=enrolled, expected_grant=grant, frame_pt=frame_pt)
    except O.Reject as r:
        return ("REJECT", r.phase, r.reason)
    try:
        out = O.phase2(fs, recip_sk)
    except O.Reject as r:
        return ("REJECT", r.phase, r.reason)
    return ("ACCEPT", 0, sha(out).hex())


def resign(frame, sk=sender_sk):
    h = frame[:O.HDR]
    f = O.parse_header(frame, None) if False else None
    ct = frame[O.HDR:-O.SIG]
    return h + ct + sk.sign(O.SIG_DOMAIN + h + ct)


def flip(b, i):
    x = bytearray(b)
    x[i] ^= 0x01
    return bytes(x)


PT1 = (b"OCR1-REVIEW-VECTOR-P1|" + bytes(range(256)))[:100]
PT3 = (b"OCR1-REVIEW-VECTOR-P3|" + bytes(range(256)))[:150]
FP3 = 64   # NON-PRODUCTION frame size: lets frame-set rules be tested without 1 MiB blobs
out = {"_note": "REVIEW_REFERENCE_ONLY. Public deterministic TEST-ONLY keys. Expected values derived from RSE12_04 text.",
       "profile": "HPKE RFC9180 base X25519/HKDF-SHA256/ChaCha20Poly1305 + Ed25519; OCR1 v2 (RSE12_04)",
       "inputs": {"recipient_id": SELF.hex(), "other_recipient_id": OTHER.hex(), "sender_id": SENDER.hex(), "grant_id": GRANT.hex(),
                  "artifact_id": ARTIFACT.hex(), "env_digest": ENV.hex(), "G32_for_vector": G32.hex(), "epoch": EPOCH, "sequence": SEQ,
                  "counter": COUNTER, "sender_ed25519_pub": O.ed_pub(sender_sk).hex(), "recipient_x25519_pub": recip_pk.hex()}}

# --- RFC 8937 wrapper KAT ---
ikm = ikm_for()
sk_e, enc_e = H.derive_key_pair(ikm)
out["ephemeral_wrapper"] = {"tag1": (O.EPH_DOMAIN + SENDER + ENV).hex(), "tag2": (GRANT + struct.pack(">Q", SEQ) + struct.pack(">Q", COUNTER)).hex(),
                            "sig_over_tag1": sender_sk.sign(O.EPH_DOMAIN + SENDER + ENV).hex(), "ikm": ikm.hex(), "enc": enc_e.hex()}
# --- positive P1 (single production-size frame) ---
fr1 = seal(PT1)
h0 = fr1[0][:O.HDR]
ss, enc = H.encap(recip_pk, ikm)
key, bn, ksc, secret = H.key_schedule(ss, O.info_of(h0))
out["P1"] = {"plaintext_hex": PT1.hex(), "plaintext_sha256": sha(PT1).hex(), "frames_hex": [f.hex() for f in fr1],
             "info_hex": O.info_of(h0).hex(), "aad_hex": h0.hex(), "shared_secret": ss.hex(), "key": key.hex(), "base_nonce": bn.hex(),
             "expected": "ACCEPT", "frame_lengths": [len(f) for f in fr1]}
assert run(fr1) == ("ACCEPT", 0, sha(PT1).hex()), run(fr1)
# --- positive P2: two production frames (1 MiB + 10) : digests only (blobs too large to commit) ---
PT2 = bytes((i * 7 + 3) & 255 for i in range((1 << 20) + 10))
fr2 = seal(PT2, seq=SEQ + 1)
assert run(fr2, grant={**grant_ctx}) == ("ACCEPT", 0, sha(PT2).hex())
out["P2"] = {"description": "2 frames, total_len = 2^20 + 10; plaintext byte i = (7*i+3) mod 256; sequence 8; counter reused value 1 with sequence 8",
             "plaintext_sha256": sha(PT2).hex(), "frame_sha256": [sha(f).hex() for f in fr2], "frame_lengths": [len(f) for f in fr2],
             "tail_frame_hex": fr2[1].hex(), "expected": "ACCEPT", "note": "ikm uses sequence 8 and counter 1; regenerate with gen_vectors.py"}
# --- positive P3: three small frames (reference-only FRAME_PT=64) ---
fr3 = seal(PT3, frame_pt=FP3)
assert run(fr3, frame_pt=FP3) == ("ACCEPT", 0, sha(PT3).hex())
out["P3_nonproduction_frame_pt_64"] = {"frame_pt": FP3, "plaintext_hex": PT3.hex(), "frames_hex": [f.hex() for f in fr3], "expected": "ACCEPT"}

# --- negatives (expected derived from spec) ---
NEG = []


def neg(name, frames, expect_phase, reasons, why, frame_pt=None, grant=grant_ctx, self_id=SELF):
    r = run(frames, frame_pt=frame_pt, grant=grant, self_id=self_id)
    ok = r[0] == "REJECT" and r[1] == expect_phase and r[2] in reasons
    NEG.append({"name": name, "expected": "REJECT", "expected_phase": expect_phase, "allowed_reasons": reasons, "spec_basis": why,
                "frames_hex": [f.hex() for f in frames], "frame_pt": frame_pt or O.FRAME_PT, "reference_agrees": ok, "reference_result": list(r)})
    if not ok:
        print("DISAGREE", name, r, expect_phase, reasons)
        sys.exit(1)


f = fr1[0]
neg("N01 header sequence bit flipped, not re-signed", [flip(f, 150 + 7)], 1, ["SIGNATURE", "GRANT_MISMATCH"], "s6 Phase1(e)/(d)")
neg("N02 ciphertext bit flipped, not re-signed", [flip(f, O.HDR + 3)], 1, ["SIGNATURE"], "s6 Phase1(e)")
neg("N03 signature bit flipped", [flip(f, len(f) - 5)], 1, ["SIGNATURE"], "s6 Phase1(e)")
seq_changed = bytearray(f); seq_changed[150 + 7] ^= 1
neg("N04 sequence changed AND re-signed by sender key (AAD/info mismatch)", [resign(bytes(seq_changed))], 2, ["AEAD"], "s4 AAD=header, info binds sequence; s6 Phase2")
type_changed = bytearray(f); type_changed[5] = 2
neg("N05 type changed 1->2 AND re-signed (info binds type)", [resign(bytes(type_changed))], 2, ["AEAD"], "s4 info includes type")
neg("N06 frame addressed to a different recipient_id", seal(PT1, recipient_id=OTHER), 1, ["RECIPIENT"], "s6 Phase1(c)")
neg("N07 right recipient_id but encrypted to a different KEM key", seal(PT1, recipient_pk=other_pk), 2, ["AEAD"], "s2/s6 recipient key binding via HPKE")
neg("N08 sender substitution: attacker key signs, claims enrolled sender_id", seal(PT1, sk=attacker_sk), 1, ["SIGNATURE"], "s6 Phase1(e) enrolled key")
unknown = sha(b"RSE-REVIEW|role|unenrolled")
neg("N09 sender_id not enrolled (valid signature by its own key)", seal(PT1, sender_id=unknown, sk=attacker_sk), 1, ["SENDER_UNKNOWN"], "s6 Phase1(c)")
enc_hi = bytearray(f); enc_hi[178 + 31] |= 0x80
neg("N10 enc top bit set (non-canonical), re-signed", [resign(bytes(enc_hi))], 1, ["ENC_NONCANONICAL"], "s6 Phase1(b)")
enc_zero = bytearray(f); enc_zero[178:210] = bytes(32)
neg("N11 enc all-zero, re-signed", [resign(bytes(enc_zero))], 1, ["ENC_NONCANONICAL"], "s6 Phase1(b)")
enc_low = bytearray(f); enc_low[178:210] = (1).to_bytes(32, "little")
neg("N12 enc = low-order point u=1 (canonical), re-signed: zero DH output must abort", [resign(bytes(enc_low))], 2, ["ZERO_SHARED_SECRET"], "s6 Phase2 note, RFC 9180 7.1.4")
neg("N13 truncated frame", [f[:-1]], 1, ["LENGTH", "TRUNCATED"], "s3 derived length")
neg("N14 trailing byte", [f + b"\x00"], 1, ["LENGTH"], "s3 derived length")
for nm, ver in (("N15a version 1", 1), ("N15b version 3", 3), ("N15c version 0", 0)):
    g = bytearray(f); g[4] = ver
    neg(nm, [bytes(g)], 1, ["UNKNOWN_VERSION"], "s3 version must equal 2")
g = bytearray(f); g[0:4] = b"XCR1"
neg("N16 bad magic", [bytes(g)], 1, ["MAGIC"], "s3")
neg("N17 stale incident epoch (grant says epoch 3)", fr1, 1, ["GRANT_MISMATCH"], "s6 Phase1(d) epoch equals current", grant={**grant_ctx, "epoch": 3})
neg("N18 sequence outside the V grant range", fr1, 1, ["GRANT_MISMATCH"], "s6 Phase1(d) range", grant={**grant_ctx, "seq_first": 8, "seq_last": 9})
neg("N19 wrong artifact for the grant", fr1, 1, ["GRANT_MISMATCH"], "s6 Phase1(d)", grant={**grant_ctx, "artifact": sha(b"other")})
neg("N20 sender differs from the grant's sender", fr1, 1, ["GRANT_MISMATCH"], "s6 Phase1(d)", grant={**grant_ctx, "sender": sha(b"someone")})

# Ed25519 malleability: S + L (non-canonical S) must be rejected by a strict verifier (RFC 8032 5.1.7; RSE12_04 section 17/"strictness profile")
L_ORDER = 2**252 + 27742317777372353535851937790883648493
sig0 = f[-64:]
S0 = int.from_bytes(sig0[32:], "little")
mall = sig0[:32] + (S0 + L_ORDER).to_bytes(32, "little")
neg("N22 Ed25519 signature malleated with S+L (non-canonical S)", [f[:-64] + mall], 1, ["SIGNATURE"], "RSE12_04 open point: strict Ed25519 verification (reject non-canonical S)")
# digest lie: header bundle_digest != SHA-256(plaintext), consistent info and signature
lie = O.sha256(b"not the plaintext")
orig = O.sha256
O.sha256 = lambda b, _o=orig: lie if b == PT1 else _o(b)
try:
    liar = seal(PT1)
finally:
    O.sha256 = orig
neg("N21 header bundle_digest does not match decrypted plaintext (sender lies)", liar, 2, ["DIGEST"], "s6 Phase2 digest check")
# frame-set negatives (FRAME_PT=64)
a, b_, c = fr3
neg("N30 missing middle frame", [a, c], 1, ["FRAME_COUNT"], "s7 missing frame", frame_pt=FP3)
neg("N31 duplicated frame", [a, b_, b_], 1, ["FRAME_ORDER", "FRAME_COUNT"], "s7 duplicate", frame_pt=FP3)
neg("N32 reordered frames", [a, c, b_], 1, ["FRAME_ORDER"], "s7 reordered", frame_pt=FP3)
neg("N33 extra frame beyond count", [a, b_, c, c], 1, ["FRAME_COUNT"], "s7 extra frame", frame_pt=FP3)
neg("N34 truncated final frame", [a, b_, c[:-1]], 1, ["LENGTH"], "s7 truncated final", frame_pt=FP3)
other_bundle = seal(PT3[::-1], frame_pt=FP3, seq=SEQ)
neg("N35 cross-bundle frame injection (valid signature, different bundle)", [a, other_bundle[1], c], 1, ["CROSS_BUNDLE"], "s7 cross-bundle", frame_pt=FP3)
neg("N36 only the first frame of a multi-frame bundle", [a], 1, ["FRAME_COUNT"], "s7 truncation", frame_pt=FP3)
out["negatives"] = NEG
out["stateful_cases_not_expressible_as_vectors"] = [
    "S01 replay: accepting the same bundle (same sequence) a second time MUST be refused by recipient state (RSE12_04 s7 replay).",
    "S02 duplicate enc under a different bundle_digest MUST be flagged and the sender quarantined (RSE12_04 s7).",
    "S03 sequence numbers consumed by an interrupted ACTIVE grant MUST NOT be reused (RSE12_02 s7).",
    "S04 key-absent Phase 1 MUST leave the secret volume locked (RSE12_04 s6; acceptance C22).",
]
json.dump(out, open("ocr1_v2_independent_vectors.json", "w"), indent=1, sort_keys=True)
print("generated", len(NEG), "negatives; P1 frame bytes", [len(x) for x in fr1], "; all reference results agree with spec-derived expectations")
