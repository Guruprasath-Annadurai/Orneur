"""REVIEW_REFERENCE_ONLY: prove the independent HPKE reference reproduces RFC 9180 Appendix A.2.1 (public test vector).

Source: RFC 9180, A.2 DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, ChaCha20Poly1305, base mode.
Values are the public RFC test vector (not secrets).
"""
import sys

import hpke_ref as H

V = dict(
    info="4f6465206f6e2061204772656369616e2055726e",
    ikmE="909a9b35d3dc4713a5e72a4da274b55d3d3821a37e5d099e74a647db583a904b",
    pkEm="1afa08d3dec047a643885163f1180476fa7ddb54c6a8029ea33f95796bf2ac4a",
    skEm="f4ec9b33b792c372c1d2c2063507b684ef925b8c75a42dbcbf57d63ccd381600",
    ikmR="1ac01f181fdf9f352797655161c58b75c656a6cc2716dcb66372da835542e1df",
    pkRm="4310ee97d88cc1f088a5576c77ab0cf5c3ac797f3d95139c6c84b5429c59662a",
    skRm="8057991eef8f1f1af18f4a9491d16a1ce333f695d4db8e38da75975c4478e0fb",
    shared_secret="0bbe78490412b4bbea4812666f7916932b828bba79942424abb65244930d69a7",
    ksc="00431df6cd95e11ff49d7013563baf7f11588c75a6611ee2a4404a49306ae4cfc5b69c5718a60cc5876c358d3f7fc31ddb598503f67be58ea1e798c0bb19eb9796",
    secret="5b9cd775e64b437a2335cf499361b2e0d5e444d5cb41a8a53336d8fe402282c6",
    key="ad2744de8e17f4ebba575b3f5f5a8fa1f69c2a07f6e7500bc60ca6e3e3ec1c91",
    base_nonce="5c4d98150661b848853b547f",
    pt="4265617574792069732074727574682c20747275746820626561757479",
)
ENC = {
    0: ("436f756e742d30", "5c4d98150661b848853b547f", "1c5250d8034ec2b784ba2cfd69dbdb8af406cfe3ff938e131f0def8c8b60b4db21993c62ce81883d2dd1b51a28"),
    1: ("436f756e742d31", "5c4d98150661b848853b547e", "6b53c051e4199c518de79594e1c4ab18b96f081549d45ce015be002090bb119e85285337cc95ba5f59992dc98c"),
    2: ("436f756e742d32", "5c4d98150661b848853b547d", "71146bd6795ccc9c49ce25dda112a48f202ad220559502cef1f34271e0cb4b02b4f10ecac6f48c32f878fae86b"),
    255: ("436f756e742d323535", "5c4d98150661b848853b5480", "18ab939d63ddec9f6ac2b60d61d36a7375d2070c9b683861110757062c52b8880a5f6b3936da9cd6c23ef2a95c"),
}


def main():
    ok = True

    def chk(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(("OK  " if good else "FAIL"), name)

    skE, pkE = H.derive_key_pair(bytes.fromhex(V["ikmE"]))
    chk("DeriveKeyPair(ikmE) pk", pkE.hex(), V["pkEm"])
    chk("DeriveKeyPair(ikmE) sk", skE.private_bytes_raw().hex(), V["skEm"])
    skR, pkR = H.derive_key_pair(bytes.fromhex(V["ikmR"]))
    chk("DeriveKeyPair(ikmR) pk", pkR.hex(), V["pkRm"])
    ss, enc = H.encap(bytes.fromhex(V["pkRm"]), bytes.fromhex(V["ikmE"]))
    chk("Encap enc", enc.hex(), V["pkEm"])
    chk("Encap shared_secret", ss.hex(), V["shared_secret"])
    chk("Decap shared_secret", H.decap(enc, skR).hex(), V["shared_secret"])
    key, bn, ksc, secret = H.key_schedule(ss, bytes.fromhex(V["info"]))
    chk("key_schedule_context", ksc.hex(), V["ksc"])
    chk("secret", secret.hex(), V["secret"])
    chk("key", key.hex(), V["key"])
    chk("base_nonce", bn.hex(), V["base_nonce"])
    pt = bytes.fromhex(V["pt"])
    for seq, (aad, nonce, ct) in ENC.items():
        chk(f"nonce seq {seq}", H.nonce_for(bn, seq).hex(), nonce)
        got = H.seal(key, bn, seq, bytes.fromhex(aad), pt)
        chk(f"seal seq {seq}", got.hex(), ct)
        chk(f"open seq {seq}", H.open_(key, bn, seq, bytes.fromhex(aad), got), pt)
    print("RFC9180_A2_REFERENCE_" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
