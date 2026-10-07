"""PROTOTYPE_ONLY: OCR1 v2 framing reference decoder A + deterministic case generator.

STRUCTURAL_CODEC_EVIDENCE only. No cryptography, no keys. Never import from production code.
"""
import hashlib
import json
import sys

FRAME_PT = 64  # production value: 1 MiB
HDR = 210
TAG = 16
SIG = 64
MAXF = 65536
P25519 = (1 << 255) - 19


def hdr_fields(h):
    return dict(
        magic=h[0:4], ver=h[4], typ=h[5], rcpt=h[6:38], send=h[38:70], gid=h[70:86],
        aid=h[86:118], bd=h[118:150], seq=int.from_bytes(h[150:158], "big"),
        epoch=int.from_bytes(h[158:162], "big"), idx=int.from_bytes(h[162:166], "big"),
        cnt=int.from_bytes(h[166:170], "big"), tot=int.from_bytes(h[170:178], "big"), enc=h[178:210],
    )


def pt_len(i, cnt, tot):
    return FRAME_PT if i < cnt - 1 else tot - (cnt - 1) * FRAME_PT


def check_header(f):
    if f["magic"] != b"OCR1" or f["ver"] != 2 or f["typ"] not in (1, 2):
        return False
    if not (1 <= f["cnt"] <= MAXF) or f["tot"] < 1 or f["idx"] >= f["cnt"]:
        return False
    if f["cnt"] != -(-f["tot"] // FRAME_PT):
        return False
    e = f["enc"]
    if e == bytes(32) or (e[31] & 0x80) or int.from_bytes(e, "little") >= P25519:
        return False
    return True


def decode_frame(b):
    if len(b) < HDR + TAG + SIG:
        return None
    f = hdr_fields(b[:HDR])
    if not check_header(f):
        return None
    if len(b) != HDR + pt_len(f["idx"], f["cnt"], f["tot"]) + TAG + SIG:
        return None
    return f


SAME = ("magic", "ver", "typ", "rcpt", "send", "gid", "aid", "bd", "seq", "epoch", "cnt", "tot", "enc")


def decode_message(frames):
    fs = []
    for b in frames:
        f = decode_frame(b)
        if f is None:
            return False
        fs.append(f)
    if not fs or len(fs) != fs[0]["cnt"]:
        return False
    for i, f in enumerate(fs):
        if f["idx"] != i:
            return False
        if any(f[k] != fs[0][k] for k in SAME):
            return False
    return True


class Rng:
    """xorshift64*, independent of the Python version's random module."""

    def __init__(self, seed):
        self.x = seed or 1

    def nxt(self):
        m = 2**64 - 1
        self.x ^= self.x >> 12
        self.x ^= (self.x << 25) & m
        self.x ^= self.x >> 27
        return (self.x * 2685821657736338717) & m

    def below(self, n):
        return self.nxt() % n


def make_message(tag, tot):
    cnt = -(-tot // FRAME_PT)
    enc = bytes([tag]) + bytes(range(1, 31)) + b"\x01"
    frames = []
    for i in range(cnt):
        h = (b"OCR1" + bytes([2, 1]) + bytes([tag]) * 32 + bytes([tag ^ 1]) * 32 + bytes([tag]) * 16
             + bytes([tag ^ 2]) * 32 + bytes([tag ^ 3]) * 32 + (7).to_bytes(8, "big") + (2).to_bytes(4, "big")
             + i.to_bytes(4, "big") + cnt.to_bytes(4, "big") + tot.to_bytes(8, "big") + enc)
        frames.append(h + bytes(pt_len(i, cnt, tot) + TAG) + bytes(SIG))
    return frames


def cases(n=20000, seed=20261007):
    r = Rng(seed)
    out = []
    a = make_message(5, 150)
    b = make_message(9, 150)
    special = [bytes(32), (2**255 - 19).to_bytes(32, "little"), (2**255 - 18).to_bytes(32, "little"),
               (2**255).to_bytes(32, "little"), b"\xff" * 32, b"\x01" + bytes(31)]
    for _ in range(n):
        m = [bytearray(f) for f in a]
        k = r.below(13)
        if k == 0:
            j = r.below(len(m))
            m[j][r.below(len(m[j]))] ^= 1 << r.below(8)
        elif k == 1:
            j = r.below(len(m))
            m[j] = m[j][:r.below(len(m[j]) + 1)]
        elif k == 2:
            j = r.below(len(m))
            m[j] += bytes(r.below(9) + 1)
        elif k == 3:
            del m[r.below(len(m))]
        elif k == 4:
            j = r.below(len(m))
            m.insert(j, bytearray(m[j]))
        elif k == 5:
            x, y = r.below(len(m)), r.below(len(m))
            m[x], m[y] = m[y], m[x]
        elif k == 6:
            m.append(bytearray(a[r.below(len(a))]))
        elif k == 7:
            m[r.below(len(m))] = bytearray(b[r.below(len(b))])
        elif k == 8:
            j = r.below(len(m))
            m[j][166:170] = r.below(6).to_bytes(4, "big")
        elif k == 9:
            j = r.below(len(m))
            m[j][170:178] = r.below(400).to_bytes(8, "big")
        elif k == 10:
            j = r.below(len(m))
            m[j][178:210] = special[r.below(len(special))]
        elif k == 11:
            j = r.below(len(m))
            m[j][r.below(6)] = r.below(256)
        else:
            m = m[:r.below(len(m) + 1)]
        out.append([bytes(f).hex() for f in m])
    return out


if __name__ == "__main__":
    cs = cases()
    if len(sys.argv) > 1:
        json.dump(cs, open(sys.argv[1], "w"))
    v = ["A" if decode_message([bytes.fromhex(h) for h in c]) else "R" for c in cs]
    print("py cases", len(cs), "accepted", v.count("A"))
    print("py verdict_digest", hashlib.sha256("".join(v).encode()).hexdigest())
    print("py baseline_accepts", decode_message(make_message(5, 150)))
