"""Deterministic local text/structure similarity for contamination and split-isolation checks (no network, no model, no provider inference).

Surface signal : word 5-gram shingles, exact Jaccard, candidate generation by MinHash+LSH (64 permutations, 32 bands x 2 rows; a pair at the
                 threshold is missed with probability < 1e-3, and every candidate is verified with EXACT Jaccard).
Structure signal: "skeleton" = function words kept, every other token replaced by a shape class (number -> '#', anything else -> 'w'); word
                 4-gram Jaccard of the skeleton, and Jaccard of the per-sentence skeleton set (reorder-robust). Names, numbers, and content
                 words therefore do not matter: this catches renamed-entity / changed-number / reworded / reordered clones.
MinHash parameters are fixed PUBLIC constants (not secrets, not used to generate items).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

_P = (1 << 61) - 1
NUM_PERM, BANDS, ROWS = 64, 32, 2
SHINGLE_N, SKEL_N = 5, 4
MIN_TOKENS_SHINGLE, MIN_TOKENS_STRUCT, MIN_SENTENCES = 12, 14, 3
MIN_LEAF_CHARS = 24

FUNCTION_WORDS = frozenset("""a an the and or but nor so yet if then else when while where which who whom whose that this these those it its is are was were be been
being am do does did done has have had having not no yes than as at by for from in into of off on onto out over per to up with within without about above
across after against along among around before behind below beneath beside between beyond during except inside like near through under until upon via
i me my we our us you your he him his she her they them their what how why can could may might must shall should will would each every all any some
more most less least both either neither only just also very too there here first second third last next final one two three four five six seven eight
nine ten reply answer line form using given following below above list return write give choose select find compute calculate determine identify""".split())

_PERMS = []
for _i in range(NUM_PERM):
    d = hashlib.blake2b(f"genesis-v2/minhash-public-parameter/{_i}".encode(), digest_size=16).digest()
    _PERMS.append((int.from_bytes(d[:8], "big") % (_P - 1) + 1, int.from_bytes(d[8:], "big") % _P))


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text)).lower()
    return re.sub(r"[\W_]+", " ", t).strip()


def string_leaves(o, out=None) -> list:
    out = [] if out is None else out
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            string_leaves(v, out)
    elif isinstance(o, (list, tuple)):
        for v in o:
            string_leaves(v, out)
    return out


def canonical(o) -> str:
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def shingle_set(tokens: list, n: int) -> frozenset:
    if not tokens:
        return frozenset()
    if len(tokens) < n:
        return frozenset({_h64(" ".join(tokens))})
    return frozenset(_h64(" ".join(tokens[i:i + n])) for i in range(len(tokens) - n + 1))


def skeleton_tokens(tokens: list) -> list:
    return [t if t in FUNCTION_WORDS else ("#" if any(c.isdigit() for c in t) else "w") for t in tokens]


def minhash(shingles: frozenset) -> tuple:
    if not shingles:
        return ()
    return tuple(min((a * h + b) % _P for h in shingles) for a, b in _PERMS)


def bands(sig: tuple):
    for b in range(BANDS):
        yield b, sig[b * ROWS:(b + 1) * ROWS]


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    u = len(a | b)
    return len(a & b) / u if u else 0.0


@dataclass
class Rec:
    item_id: str
    category: str
    split: str
    cluster: str
    text_norm: str
    tokens: list
    shingles: frozenset
    skel: frozenset
    sent_skel: frozenset
    struct_ok: bool
    content_fp: str
    gt_canon: str
    gt_leaves: frozenset
    instance: frozenset
    sig_text: tuple = field(default=())
    sig_skel: tuple = field(default=())


def _text_of(item: dict) -> str:
    return "\n".join(string_leaves([item.get("system"), item.get("prompt"), item.get("input")]))


def _instance_material(item: dict) -> frozenset:
    """Generator-derived instance material, each part compared separately: the creation-method tuple (generator, index, salt), the instance-parameter
    meta (only if it carries >= 24 chars, so trivial constants cannot collide), and any embedded content digest."""
    parts = set()
    if item.get("creation_method"):
        parts.add("m:" + str(item["creation_method"]))
    meta = item.get("meta")
    if meta and len(canonical(meta)) >= 24:
        parts.add("meta:" + canonical(meta))
    if item.get("sha256"):
        parts.add("sha:" + str(item["sha256"]))
    return frozenset(parts)


def make_rec(item: dict) -> Rec:
    text = _text_of(item)
    toks = normalize(text).split()
    sk = skeleton_tokens(toks)
    sents = [s for s in re.split(r"[.?!\n]+", unicodedata.normalize("NFKC", text).lower()) if s.strip()]
    sent_skel = frozenset(" ".join(skeleton_tokens(normalize(s).split())) for s in sents if normalize(s))
    gt = item.get("ground_truth")
    leaves = frozenset(x for x in (normalize(s) for s in string_leaves(gt)) if len(x) >= MIN_LEAF_CHARS)
    rec = Rec(
        item_id=str(item.get("item_id", "")), category=str(item.get("category", "")), split=str(item.get("split", "")),
        cluster=str(item.get("cluster", (item.get("meta") or {}).get("subtype", "") if isinstance(item.get("meta"), dict) else "")),
        text_norm=" ".join(toks), tokens=toks, shingles=shingle_set(toks, SHINGLE_N) if len(toks) >= 1 else frozenset(),
        skel=shingle_set(sk, SKEL_N) if len(toks) >= MIN_TOKENS_STRUCT else frozenset(),
        sent_skel=sent_skel if len(sents) >= MIN_SENTENCES else frozenset(), struct_ok=len(toks) >= MIN_TOKENS_STRUCT,
        content_fp=hashlib.sha256(canonical({k: item.get(k) for k in ("system", "prompt", "input", "ground_truth")}).encode()).hexdigest(),
        gt_canon=canonical(gt) if gt is not None else "", gt_leaves=leaves, instance=_instance_material(item))
    rec.sig_text = minhash(rec.shingles)
    rec.sig_skel = minhash(rec.skel)
    return rec


def surface_sim(a: Rec, b: Rec) -> float:
    return jaccard(a.shingles, b.shingles)


def struct_sim(a: Rec, b: Rec) -> float:
    if not (a.struct_ok and b.struct_ok):
        return 0.0
    s = jaccard(a.skel, b.skel)
    if a.sent_skel and b.sent_skel:
        s = max(s, jaccard(a.sent_skel, b.sent_skel))
    return s


def similar_pairs(left: list, right: list, kind: str, threshold: float, *, same_list: bool = False) -> list:
    """All (left_id, right_id, score) with score >= threshold. kind: 'text' | 'struct'."""
    sig = (lambda r: r.sig_text) if kind == "text" else (lambda r: r.sig_skel)
    sim = surface_sim if kind == "text" else struct_sim
    buckets: dict = {}
    for j, r in enumerate(right):
        s = sig(r)
        if not s:
            continue
        for band in bands(s):
            buckets.setdefault(band, []).append(j)
    out, seen = [], set()
    for i, l in enumerate(left):
        s = sig(l)
        if not s:
            continue
        for band in bands(s):
            for j in buckets.get(band, ()):
                if same_list and j <= i:
                    continue
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                sc = sim(l, right[j])
                if sc >= threshold:
                    out.append((l.item_id, right[j].item_id, round(sc, 4)))
    return out
