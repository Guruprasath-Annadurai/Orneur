"""Generators: multilingual, multimodal_where_applicable (synthetic PNGs), long_context (materialised on demand), coding, latency probes."""
from __future__ import annotations

import hashlib
import math
import random
import struct
import unicodedata
import zlib
from typing import Any

from orca.eval.genesis.common import ANSWER_LINE, NAMES, CITIES

# ------------------------------------------------------------------ multilingual
LEX = {
    "Hindi": {"fruit": ["आम", "केला", "सेब", "संतरा", "अंगूर"], "animal": ["कुत्ता", "बिल्ली", "घोड़ा", "गाय", "शेर"],
              "colour": ["लाल", "नीला", "हरा", "पीला", "काला"], "names": ["राम", "सीता", "अर्जुन", "मीरा", "कबीर"],
              "cities": ["दिल्ली", "मुंबई", "चेन्नई", "पुणे", "जयपुर"], "nums": ["एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ", "दस"],
              "catword": {"fruit": "फल", "animal": "जानवर", "colour": "रंग"}},
    "Tamil": {"fruit": ["மாம்பழம்", "வாழைப்பழம்", "ஆப்பிள்", "ஆரஞ்சு", "திராட்சை"], "animal": ["நாய்", "பூனை", "குதிரை", "பசு", "சிங்கம்"],
              "colour": ["சிவப்பு", "நீலம்", "பச்சை", "மஞ்சள்", "கருப்பு"], "names": ["ராமன்", "சீதா", "அர்ஜுனன்", "மீரா", "கபீர்"],
              "cities": ["டெல்லி", "மும்பை", "சென்னை", "புனே", "மதுரை"], "nums": ["ஒன்று", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது", "பத்து"],
              "catword": {"fruit": "பழங்கள்", "animal": "விலங்குகள்", "colour": "நிறங்கள்"}},
    "Kannada": {"fruit": ["ಮಾವಿನಹಣ್ಣು", "ಬಾಳೆಹಣ್ಣು", "ಸೇಬು", "ಕಿತ್ತಳೆ", "ದ್ರಾಕ್ಷಿ"], "animal": ["ನಾಯಿ", "ಬೆಕ್ಕು", "ಕುದುರೆ", "ಹಸು", "ಸಿಂಹ"],
                "colour": ["ಕೆಂಪು", "ನೀಲಿ", "ಹಸಿರು", "ಹಳದಿ", "ಕಪ್ಪು"], "names": ["ರಾಮ", "ಸೀತಾ", "ಅರ್ಜುನ", "ಮೀರಾ", "ಕಬೀರ"],
                "cities": ["ದೆಹಲಿ", "ಮುಂಬೈ", "ಚೆನ್ನೈ", "ಪುಣೆ", "ಮೈಸೂರು"], "nums": ["ಒಂದು", "ಎರಡು", "ಮೂರು", "ನಾಲ್ಕು", "ಐದು", "ಆರು", "ಏಳು", "ಎಂಟು", "ಒಂಬತ್ತು", "ಹತ್ತು"],
                "catword": {"fruit": "ಹಣ್ಣುಗಳು", "animal": "ಪ್ರಾಣಿಗಳು", "colour": "ಬಣ್ಣಗಳು"}},
    "English": {"fruit": ["mango", "banana", "apple", "orange", "grape"], "animal": ["dog", "cat", "horse", "cow", "lion"],
                "colour": ["red", "blue", "green", "yellow", "black"], "names": ["Ravi", "Sita", "Arjun", "Meera", "Kabir"],
                "cities": ["Delhi", "Mumbai", "Chennai", "Pune", "Madurai"],
                "nums": ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"],
                "catword": {"fruit": "fruits", "animal": "animals", "colour": "colours"}},
}
_T = {
    "Hindi": {"odd": "इन शब्दों में से कौन सा शब्द बाकी से अलग श्रेणी का है? {w}", "count": "नीचे दिए गए शब्दों में से कितने {c} हैं? {w}",
              "lookup": "{l}\n\n{n} किस शहर में है?", "sum": "{a} और {b} का योग कितना है? उत्तर अंकों में लिखें।"},
    "Tamil": {"odd": "இந்த சொற்களில் மற்றவற்றிலிருந்து வேறுபட்ட வகையைச் சேர்ந்த சொல் எது? {w}", "count": "கீழே உள்ள சொற்களில் எத்தனை {c}? {w}",
              "lookup": "{l}\n\n{n} எந்த நகரத்தில் இருக்கிறார்?", "sum": "{a} மற்றும் {b} இன் கூட்டுத்தொகை என்ன? எண்ணாக (இலக்கங்களில்) எழுதவும்."},
    "Kannada": {"odd": "ಈ ಪದಗಳಲ್ಲಿ ಉಳಿದವುಗಳಿಗಿಂತ ಬೇರೆ ವರ್ಗದ ಪದ ಯಾವುದು? {w}", "count": "ಕೆಳಗಿನ ಪದಗಳಲ್ಲಿ ಎಷ್ಟು {c} ಇವೆ? {w}",
                "lookup": "{l}\n\n{n} ಯಾವ ನಗರದಲ್ಲಿ ಇದ್ದಾರೆ?", "sum": "{a} ಮತ್ತು {b} ರ ಮೊತ್ತ ಎಷ್ಟು? ಅಂಕಿಗಳಲ್ಲಿ ಬರೆಯಿರಿ."},
    "English": {"odd": "Which of these words belongs to a different kind of thing from the others? {w}", "count": "How many of the following words are {c}? {w}",
                "lookup": "{l}\n\nWhich city is {n} in?", "sum": "What is {a} plus {b}? Write the answer in digits.",
                "letter": "How many of these words begin with the letter {L}? {w}"},
}


def gen_multilingual(rng: random.Random, language: str) -> dict:
    lx, tp = LEX[language], _T[language]
    kinds = ["odd", "count", "lookup", "sum"] + (["letter"] if language == "English" else [])
    kind = rng.choice(kinds)
    cats = ["fruit", "animal", "colour"]
    if kind == "odd":
        main, other = rng.sample(cats, 2)
        three = rng.sample(lx[main], 3)
        odd = rng.choice(lx[other])
        ws = three + [odd]
        rng.shuffle(ws)
        q, ans, chance, key = tp["odd"].format(w=", ".join(ws)), odd, 0.25, "|".join(ws)
    elif kind == "count":
        ws = [rng.choice(lx[rng.choice(cats)]) for _ in range(7)]
        cat = rng.choice(cats)
        ans = str(sum(1 for w in ws if w in lx[cat]))
        q, chance, key = tp["count"].format(c=lx["catword"][cat], w=", ".join(ws)), 1 / 7, "|".join(ws) + cat
    elif kind == "lookup":
        ns = rng.sample(lx["names"], 4)
        cs = rng.sample(lx["cities"], 4)
        lines = "\n".join(f"{n} - {c}" for n, c in zip(ns, cs))
        i = rng.randrange(4)
        q, ans, chance, key = tp["lookup"].format(l=lines, n=ns[i]), cs[i], 0.25, lines + ns[i]
    elif kind == "sum":
        a, b = rng.randint(1, 9), rng.randint(1, 9)
        q, ans, chance, key = tp["sum"].format(a=lx["nums"][a - 1], b=lx["nums"][b - 1]), str(a + b), 0.05, f"{a}+{b}"
    else:
        pool = ["table", "tiger", "cloud", "river", "tulip", "stone", "tower", "apple", "bread", "candle", "tunnel", "window", "garden"]
        ws = rng.sample(pool, 6)
        L = rng.choice(["t", "c", "b"])
        ans = str(sum(1 for w in ws if w.startswith(L)))
        q, chance, key = tp["letter"].format(L=L.upper(), w=", ".join(ws)), 1 / 7, "|".join(ws) + L
    q = unicodedata.normalize("NFC", q)
    return {"prompt": q + ANSWER_LINE, "input": {"language": language}, "ground_truth": {"answer": unicodedata.normalize("NFC", ans), "match": "text"},
            "scoring_method": "answer_line", "difficulty": "easy" if kind in ("odd", "sum") else "medium",
            "meta": {"chance": chance, "dedup_text": key, "subtype": f"{language}:{kind}", "language": language}}


# ------------------------------------------------------------------ multimodal (deterministic synthetic PNG)
COLORS = {"red": (220, 40, 40), "green": (40, 170, 70), "blue": (50, 80, 220), "yellow": (240, 210, 40), "black": (20, 20, 20)}


def _png(width: int, height: int, pixels: list[list[tuple[int, int, int]]]) -> bytes:
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def render_image(spec: dict) -> bytes:
    W = H = 120
    px = [[(255, 255, 255)] * W for _ in range(H)]
    def rect(x0, y0, x1, y1, col):
        for y in range(max(0, y0), min(H, y1)):
            for x in range(max(0, x0), min(W, x1)):
                px[y][x] = COLORS[col]
    if spec["kind"] == "squares":
        for cell, col, size in spec["squares"]:
            cx, cy = (cell % 3) * 40 + 4, (cell // 3) * 40 + 4
            rect(cx, cy, cx + size, cy + size, col)
    else:
        for i, (col, h) in enumerate(spec["bars"]):
            x0 = 8 + i * 28
            rect(x0, H - 4 - h, x0 + 20, H - 4, col)
    return _png(W, H, px)


def gen_multimodal(rng: random.Random) -> dict:
    kind = rng.choice(["count", "biggest", "tallest"])
    cols = list(COLORS)
    if kind == "tallest":
        cs = rng.sample(cols, 4)
        hs = rng.sample(range(20, 105, 5), 4)
        spec = {"kind": "bars", "bars": list(zip(cs, hs))}
        ans = cs[hs.index(max(hs))]
        q = "The image is a bar chart with four coloured bars. Which colour is the tallest bar? Answer with one colour word in English (red, green, blue, yellow or black)."
        chance = 0.25
    else:
        cells = rng.sample(range(9), rng.randint(3, 6))
        if kind == "count":
            target = rng.choice(cols[:4])
            sq = [(c, rng.choice(cols[:4]), rng.choice([20, 24, 28])) for c in cells]
            ans = str(sum(1 for _, col, _ in sq if col == target))
            q = f"How many {target} squares are in the image? Answer with a digit."
            chance = 0.2
        else:
            sizes = rng.sample([14, 18, 22, 26, 30, 34], len(cells))
            cs = [rng.choice(cols) for _ in cells]
            sq = list(zip(cells, cs, sizes))
            big = max(sq, key=lambda t: t[2])
            ans = big[1]
            # colours may repeat; ensure the biggest square's colour is unambiguous as 'the colour of the biggest square'
            q = "Which colour is the BIGGEST square in the image? Answer with one colour word in English (red, green, blue, yellow or black)."
            chance = 0.2
        spec = {"kind": "squares", "squares": sq}
    return {"prompt": q + ANSWER_LINE, "input": {"image_spec": spec}, "ground_truth": {"answer": ans, "match": "text"}, "scoring_method": "answer_line",
            "difficulty": "easy", "meta": {"chance": chance, "dedup_text": str(spec), "subtype": kind}}


# ------------------------------------------------------------------ long_context (materialised deterministically from a spec)
_SUB = ["maintenance", "logistics", "billing", "safety", "planning", "audit", "field", "design", "support", "quality"]
_VERB = ["reviewed", "scheduled", "archived", "inspected", "approved", "measured", "relabelled", "moved", "counted", "reconciled"]
_ADJ = ["old", "new", "spare", "shared", "sealed", "damp", "labelled", "surplus", "minor", "routine"]
_OBJ = ["ledger", "cabinet", "pallet", "gauge", "manifest", "crate", "binder", "toolkit", "cable", "shelf"]
_WORDS_PER_TOKEN = 0.75   # whitespace words per token (approximate; tokenizers differ, recorded as approximate)


def _filler(rng: random.Random, k: int) -> str:
    return (f"On day {rng.randint(1, 365)} the {rng.choice(_SUB)} team {rng.choice(_VERB)} the {rng.choice(_ADJ)} {rng.choice(_OBJ)} "
            f"at site {rng.choice('ABCDEFGH')}{rng.randint(10, 99)} and noted {rng.randint(2, 97)} minor items.")


def materialize_long_context(spec: dict) -> tuple[str, str]:
    rng = random.Random(spec["seed"])
    target_words = int(spec["target_tokens"] * _WORDS_PER_TOKEN)
    task = spec["task"]
    facts: list[str] = []
    if task == "needle":
        vaults = [f"{rng.choice(['amber', 'cobalt', 'jade', 'onyx', 'ruby', 'ivory'])}-{rng.choice(['heron', 'otter', 'lynx', 'crane', 'marten', 'ibis'])}" for _ in range(6)]
        vaults = list(dict.fromkeys(vaults))[:5]
        codes = [str(rng.randint(100000, 999999)) for _ in vaults]
        facts = [f"The access code for vault {v} is {c}." for v, c in zip(vaults, codes)]
        i = rng.randrange(len(vaults))
        q, ans = f"What is the access code for vault {vaults[i]}?", codes[i]
    elif task == "multihop":
        recs = [f"R{rng.randint(1000, 9999)}" for _ in range(6)]
        recs = list(dict.fromkeys(recs))
        shelves = [f"{rng.choice('ABCDEF')}{rng.randint(1, 40)}" for _ in recs]
        facts = [f"Record {recs[i]} points to record {recs[(i + 1) % len(recs)]}." for i in range(len(recs))]
        facts += [f"Record {recs[i]} lists the archive shelf as {shelves[i]}." for i in range(len(recs))]
        i = rng.randrange(len(recs))
        q, ans = f"Follow the pointer of record {recs[i]}. Which archive shelf does the record it points to list?", shelves[(i + 1) % len(recs)]
    else:
        cities = rng.sample(CITIES, 5)
        target = cities[0]
        facts, total = [], 0
        for c in cities:
            for _ in range(rng.randint(2, 4)):
                n = rng.randint(3, 60)
                facts.append(f"Delivery to {c} carried {n} crates.")
                if c == target:
                    total += n
        q, ans = f"What is the total number of crates that deliveries to {target} carried, summed over every such delivery entry?", str(total)
    lines: list[str] = []
    words = sum(len(f.split()) + 1 for f in facts)
    while words < target_words:
        ln = f"Entry {len(lines) + 1}: {_filler(rng, len(lines))}"
        lines.append(ln)
        words += len(ln.split())
    pos = sorted(rng.sample(range(len(lines) + 1), len(facts))) if lines else list(range(len(facts)))
    order = list(facts)
    rng.shuffle(order)
    out, fi = [], 0
    for i in range(len(lines) + 1):
        while fi < len(pos) and pos[fi] == i:
            out.append(f"Note: {order[fi]}")
            fi += 1
        if i < len(lines):
            out.append(lines[i])
    doc = "\n".join(out)
    prompt = f"Read the log below and answer the question at the end using only the log.\n\n{doc}\n\nQuestion: {q}" + ANSWER_LINE
    return prompt, ans


def gen_long_context(rng: random.Random, target_tokens: int) -> dict:
    task = rng.choice(["needle", "multihop", "aggregate"])
    spec = {"generator": "long_context_v1", "seed": rng.getrandbits(48), "target_tokens": target_tokens, "task": task,
            "words_per_token_assumed": _WORDS_PER_TOKEN, "length_note": "approximate; measured in whitespace words converted at a fixed ratio, tokenizer-specific length differs"}
    prompt, ans = materialize_long_context(spec)
    return {"prompt": None, "input": {"generator_spec": spec, "materialized_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                      "approx_words": len(prompt.split())},
            "ground_truth": {"answer": ans, "match": "numeric" if task != "multihop" else "text"}, "scoring_method": "answer_line",
            "difficulty": "medium" if task != "multihop" else "hard",
            "meta": {"chance": 0.0, "dedup_text": f"{spec['seed']}|{task}|{target_tokens}", "subtype": f"{task}@{target_tokens // 1024}k",
                     "slice": f"{target_tokens // 1024}k"}}


# ------------------------------------------------------------------ coding (data only: tests run later in a sandbox)
def _tests(rng, gen, ref, n=8):
    tests = []
    for _ in range(n):
        args = gen(rng)
        tests.append({"args": args, "expected": ref(*args)})
    return tests


def gen_coding(rng: random.Random) -> dict:
    kind = rng.choice(["count", "rotate", "dedupe", "top_freq", "rle", "balanced", "merge", "caesar", "kth_max", "windows"])
    if kind == "count":
        t, d = rng.randint(2, 40), rng.randint(3, 7)
        v = rng.choice(["even_gt", "odd_lt", "div_gt"])
        if v == "even_gt":
            spec = f"Define `count_matching(xs)` that returns how many integers in the list `xs` are even AND strictly greater than {t}."
            cond = f"x % 2 == 0 and x > {t}"
        elif v == "odd_lt":
            spec = f"Define `count_matching(xs)` that returns how many integers in the list `xs` are odd AND strictly less than {t}."
            cond = f"x % 2 != 0 and x < {t}"
        else:
            spec = f"Define `count_matching(xs)` that returns how many integers in the list `xs` are divisible by {d} AND strictly greater than {t}."
            cond = f"x % {d} == 0 and x > {t}"
        ref = eval(f"lambda xs: sum(1 for x in xs if {cond})")
        gen = lambda r: ([r.randint(-5, 45) for _ in range(r.randint(0, 10))],)
        name, code = "count_matching", f"def count_matching(xs):\n    return sum(1 for x in xs if {cond})\n"
    elif kind == "rotate":
        left = rng.random() < 0.5
        neg = rng.random() < 0.5
        d = "left" if left else "right"
        spec = (f"Define `rotate(xs, k)` returning a new list with `xs` rotated {d} by `k` positions. k may exceed len(xs); "
                + ("a negative k means rotating the other way; " if neg else "k is never negative; ") + "an empty list stays empty.")
        sign = 1 if left else -1
        ref = eval("lambda xs, k: (xs[(%d * k) %% len(xs):] + xs[:(%d * k) %% len(xs)]) if xs else []" % (sign, sign))
        gen = lambda r: ([r.randint(0, 9) for _ in range(r.randint(0, 8))], r.randint(-9 if neg else 0, 20))
        name, code = "rotate", "def rotate(xs, k):\n    if not xs:\n        return []\n    k = (%d * k) %% len(xs)\n    return xs[k:] + xs[:k]\n" % sign
    elif kind == "dedupe":
        keep_first, m = rng.random() < 0.5, rng.randint(1, 3)
        spec = (f"Define `dedupe(xs)` returning a list that keeps only values occurring at least {m} time(s) in `xs`, each value exactly once, "
                f"placed at the position of its {'first' if keep_first else 'last'} occurrence, preserving the original relative order.")
        def ref(xs):
            from collections import Counter
            c = Counter(xs)
            if keep_first:
                seen, out = set(), []
                for x in xs:
                    if c[x] >= m and x not in seen:
                        seen.add(x)
                        out.append(x)
                return out
            seen, out = set(), []
            for x in reversed(xs):
                if c[x] >= m and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out[::-1]
        gen = lambda r: ([r.randint(0, 6) for _ in range(r.randint(0, 12))],)
        name = "dedupe"
        code = ("from collections import Counter\n\ndef dedupe(xs):\n    c = Counter(xs)\n    seq = xs if %s else list(reversed(xs))\n    seen, out = set(), []\n"
                "    for x in seq:\n        if c[x] >= %d and x not in seen:\n            seen.add(x)\n            out.append(x)\n    return out if %s else out[::-1]\n") % (keep_first, m, keep_first)
    elif kind == "top_freq":
        k, small_first = rng.randint(1, 4), rng.random() < 0.5
        spec = (f"Define `top_values(xs)` returning the {k} most frequent values of `xs` as a list, most frequent first; break ties by "
                f"{'smaller' if small_first else 'larger'} value first. If fewer distinct values exist, return them all.")
        def ref(xs):
            from collections import Counter
            c = Counter(xs)
            sgn = 1 if small_first else -1
            return [v for v, _ in sorted(c.items(), key=lambda kv: (-kv[1], sgn * kv[0]))[:k]]
        gen = lambda r: ([r.randint(0, 5) for _ in range(r.randint(0, 14))],)
        name = "top_values"
        code = ("from collections import Counter\n\ndef top_values(xs):\n    c = Counter(xs)\n    return [v for v, _ in sorted(c.items(), key=lambda kv: (-kv[1], %d * kv[0]))[:%d]]\n") % (1 if small_first else -1, k)
    elif kind == "rle":
        fmt, L = rng.choice(["pairs", "string"]), rng.randint(1, 3)
        spec = (f"Define `rle(s)` returning the run-length encoding of string `s`, keeping only runs of length at least {L}, "
                + ("as a list of [character, count] pairs in order." if fmt == "pairs" else "as one string of character followed by its count, concatenated (e.g. 'aab' with min length 1 gives 'a2b1').") )
        def ref(s):
            runs = []
            for ch in s:
                if runs and runs[-1][0] == ch:
                    runs[-1][1] += 1
                else:
                    runs.append([ch, 1])
            runs = [r for r in runs if r[1] >= L]
            return runs if fmt == "pairs" else "".join(f"{c}{n}" for c, n in runs)
        gen = lambda r: ("".join(r.choice("abc") for _ in range(r.randint(0, 12))),)
        name = "rle"
        code = ("def rle(s):\n    runs = []\n    for ch in s:\n        if runs and runs[-1][0] == ch:\n            runs[-1][1] += 1\n        else:\n            runs.append([ch, 1])\n"
                "    runs = [r for r in runs if r[1] >= %d]\n    return %s\n") % (L, "runs" if fmt == "pairs" else "''.join(f'{c}{n}' for c, n in runs)")
    elif kind == "balanced":
        kinds = rng.sample(["()", "[]", "{}"], rng.randint(1, 3))
        opens, closes = "".join(k[0] for k in kinds), "".join(k[1] for k in kinds)
        spec = (f"Define `balanced(s)` returning True iff the bracket kinds {', '.join(kinds)} in string `s` are correctly nested and matched; "
                "every other character is ignored.")
        pairs = {c: o for o, c in zip(opens, closes)}
        def ref(s):
            st = []
            for ch in s:
                if ch in opens:
                    st.append(ch)
                elif ch in pairs:
                    if not st or st.pop() != pairs[ch]:
                        return False
            return not st
        gen = lambda r: ("".join(r.choice("()[]{}ab") for _ in range(r.randint(0, 10))),)
        name = "balanced"
        code = ("def balanced(s):\n    opens, pairs, st = %r, %r, []\n    for ch in s:\n        if ch in opens:\n            st.append(ch)\n        elif ch in pairs:\n"
                "            if not st or st.pop() != pairs[ch]:\n                return False\n    return not st\n") % (opens, pairs)
    elif kind == "merge":
        touch, total = rng.random() < 0.5, rng.random() < 0.4
        spec = (f"Define `merge(intervals)` taking a list of [start, end] integer pairs. Sort by start, then merge intervals that overlap"
                + (" or touch (next start <= current end)" if touch else " strictly (next start < current end; touching intervals stay separate)")
                + (". Return the TOTAL length covered (sum of end - start over the merged intervals)." if total else ". Return the merged list of [start, end] pairs."))
        def ref(iv):
            out = []
            for s, e in sorted(iv):
                if out and (s <= out[-1][1] if touch else s < out[-1][1]):
                    out[-1][1] = max(out[-1][1], e)
                else:
                    out.append([s, e])
            return sum(e - s for s, e in out) if total else out
        def gen(r):
            iv = []
            for _ in range(r.randint(0, 6)):
                s = r.randint(0, 20)
                iv.append([s, s + r.randint(0, 6)])
            return (iv,)
        name = "merge"
        code = ("def merge(intervals):\n    out = []\n    for s, e in sorted(intervals):\n        if out and (s <= out[-1][1] if %s else s < out[-1][1]):\n"
                "            out[-1][1] = max(out[-1][1], e)\n        else:\n            out.append([s, e])\n    return %s\n") % (touch, "sum(e - s for s, e in out)" if total else "out")
    elif kind == "caesar":
        k, back, up = rng.randint(1, 25), rng.random() < 0.5, rng.random() < 0.5
        spec = (f"Define `shift(s)` that shifts every lowercase letter of `s` {'backward' if back else 'forward'} by {k} places in the alphabet (wrapping around); "
                + ("uppercase letters are shifted the same way; " if up else "uppercase letters are unchanged; ") + "every other character is unchanged.")
        sg = -1 if back else 1
        def ref(s):
            out = []
            for c in s:
                if "a" <= c <= "z":
                    out.append(chr((ord(c) - 97 + sg * k) % 26 + 97))
                elif up and "A" <= c <= "Z":
                    out.append(chr((ord(c) - 65 + sg * k) % 26 + 65))
                else:
                    out.append(c)
            return "".join(out)
        gen = lambda r: ("".join(r.choice("abxyzAXYZ -9") for _ in range(r.randint(0, 10))),)
        name = "shift"
        code = ("def shift(s):\n    out = []\n    for c in s:\n        if 'a' <= c <= 'z':\n            out.append(chr((ord(c) - 97 + %d) %% 26 + 97))\n"
                "        elif %s and 'A' <= c <= 'Z':\n            out.append(chr((ord(c) - 65 + %d) %% 26 + 65))\n        else:\n            out.append(c)\n    return ''.join(out)\n") % (sg * k, up, sg * k)
    elif kind == "kth_max":
        k, dflt = rng.randint(2, 4), rng.choice(["None", "-1", "0"])
        spec = (f"Define `kth_largest(xs)` returning the {k}{'nd' if k == 2 else 'rd' if k == 3 else 'th'} largest DISTINCT value in `xs`, "
                f"or {dflt} if there are fewer than {k} distinct values.")
        def ref(xs):
            d = sorted(set(xs), reverse=True)
            return d[k - 1] if len(d) >= k else eval(dflt)
        gen = lambda r: ([r.randint(-5, 9) for _ in range(r.randint(0, 9))],)
        name = "kth_largest"
        code = "def kth_largest(xs):\n    d = sorted(set(xs), reverse=True)\n    return d[%d] if len(d) >= %d else %s\n" % (k - 1, k, dflt)
    else:
        m, op = rng.randint(2, 5), rng.choice(["sum", "max", "min"])
        spec = f"Define `windows(xs)` returning a list with the {op} of every window of {m} consecutive elements of `xs` (empty if len(xs) < {m})."
        fn = {"sum": sum, "max": max, "min": min}[op]
        ref = lambda xs: [fn(xs[i:i + m]) for i in range(len(xs) - m + 1)] if len(xs) >= m else []
        gen = lambda r: ([r.randint(-4, 9) for _ in range(r.randint(0, 9))],)
        name = "windows"
        code = "def windows(xs):\n    return [%s(xs[i:i + %d]) for i in range(len(xs) - %d + 1)] if len(xs) >= %d else []\n" % (op, m, m, m)
    tests = _tests(rng, gen, ref)
    prompt = f"{spec}\n\nReply with ONLY Python 3 code that defines the function (no explanation, no code fences, no test code). Standard library only."
    return {"prompt": prompt, "input": {}, "ground_truth": {"function_name": name, "tests": tests, "reference_solution": code},
            "scoring_method": "code_tests", "difficulty": "medium" if kind in ("merge", "balanced", "top_freq", "dedupe") else "easy",
            "meta": {"chance": 0.0, "dedup_text": spec, "subtype": kind}}


# ------------------------------------------------------------------ latency probes (protocol definitions, not Q&A)
def latency_probe_definitions() -> list[dict]:
    probes = []
    for i, (words, max_new) in enumerate([(32, 64), (32, 256), (512, 64), (512, 256), (4096, 64), (4096, 256)] * 2):
        rng = random.Random(9000 + i)
        body = " ".join(rng.choice(["signal", "harbor", "copper", "linen", "orbit", "granite", "ripple", "lantern", "north", "delta"]) for _ in range(words))
        probes.append({"probe_id": f"latency-probe-{i + 1:02d}", "input_words": words, "max_new_tokens": max_new, "repeat": i // 6 + 1,
                       "prompt": f"Here is some text: {body}\n\nSummarize it in one sentence.", "measures": ["time_to_first_token_s", "tokens_per_second", "end_to_end_s"]})
    return probes
