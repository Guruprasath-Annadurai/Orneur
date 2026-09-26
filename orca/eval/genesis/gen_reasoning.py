"""Generators: reasoning, mathematics, verification, information_gain_reasoning. Ground truth comes from exact solvers."""
from __future__ import annotations

import itertools
import math
import random
from fractions import Fraction

from orca.eval.genesis.common import ANSWER_LINE, NAMES, CITIES, company

_NOUNS = ["blorps", "zints", "quells", "trevs", "mardins", "foobs", "wexes", "plims", "dorvs", "kestrels", "narls", "yubs"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ------------------------------------------------------------------ reasoning
def _ordering(rng):
    n = rng.randint(4, 6)
    people = rng.sample(NAMES, n)
    order = people[:]          # tallest first
    rng.shuffle(order)
    facts = [f"{order[i]} is taller than {order[i + 1]}." for i in range(n - 1)]
    for _ in range(rng.randint(0, 2)):
        i, j = sorted(rng.sample(range(n), 2))
        if j - i > 1:
            facts.append(f"{order[i]} is taller than {order[j]}.")
    rng.shuffle(facts)
    k = rng.randint(1, n)
    ordinal = {1: "tallest", 2: "second tallest", 3: "third tallest", 4: "fourth tallest", 5: "fifth tallest", 6: "sixth tallest"}[k]
    q = f"{' '.join(facts)}\n\nWho is the {ordinal}?"
    return q, order[k - 1], 1 / n, "ordering", "|".join(order)


def _syllogism(rng):
    ns = rng.sample(_NOUNS, 6)
    chain = ns[:4]                                     # chain[0] all-are chain[1] all-are chain[2] all-are chain[3]
    facts = [f"All {chain[i]} are {chain[i + 1]}." for i in range(3)] + [f"All {ns[4]} are {ns[5]}.", f"All {ns[5]} are {chain[1]}."]
    rng.shuffle(facts)
    # candidate conclusions with exactly one that must hold
    true_c = rng.choice([(chain[0], chain[3]), (chain[0], chain[2]), (ns[4], chain[1]), (ns[4], chain[3])])
    reach = {ns[4]: {ns[5], chain[1], chain[2], chain[3]}, ns[5]: {chain[1], chain[2], chain[3]},
             chain[0]: set(chain[1:]), chain[1]: set(chain[2:]), chain[2]: {chain[3]}, chain[3]: set()}
    wrong_pool = [(a, b) for a in reach for b in ns if a != b and b not in reach[a] and b in ns]
    rng.shuffle(wrong_pool)
    opts = [true_c] + wrong_pool[:4]
    rng.shuffle(opts)
    letters = "ABCDE"
    lines = "\n".join(f"({letters[i]}) Every one of the {a} is one of the {b}." for i, (a, b) in enumerate(opts))
    ans = letters[opts.index(true_c)]
    q = f"Premises: {' '.join(facts)}\n\nWhich statement must be true given only the premises? (Exactly one must be true.)\n{lines}\nAnswer with the letter."
    return q, ans, 0.2, "syllogism", "|".join(facts) + str(opts)


def _calendar(rng):
    d0 = rng.randint(0, 6)
    off = rng.randint(20, 900)
    q = f"Today is {_DAYS[d0]}. What day of the week will it be exactly {off} days from today?"
    return q, _DAYS[(d0 + off) % 7], 1 / 7, "calendar", f"{d0}|{off}"


def _knights(rng):
    for _ in range(200):
        people = ["A", "B", "C"]
        stmts = []
        for p in people:
            t = rng.choice(["knight", "knave", "same", "count"])
            o = rng.choice([x for x in people if x != p])
            stmts.append((p, t, o))
        sols = []
        for types in itertools.product([True, False], repeat=3):     # True = knight
            ty = dict(zip(people, types))
            ok = True
            for p, t, o in stmts:
                if t == "knight":
                    val = ty[o]
                elif t == "knave":
                    val = not ty[o]
                elif t == "same":
                    val = ty[p] == ty[o]
                else:
                    val = sum(1 for x in people if not ty[x]) == 1
                if ty[p] != val:            # knights tell the truth, knaves lie
                    ok = False
                    break
            if ok:
                sols.append(ty)
        if len(sols) == 1:
            s = sols[0]
            text = " ".join(
                f"{p} says: \"" + {"knight": f"{o} is a knight.", "knave": f"{o} is a knave.", "same": f"I am the same type as {o}.",
                                    "count": "Exactly one of us is a knave."}[t] + "\"" for p, t, o in stmts)
            ans = ",".join("KNIGHT" if s[p] else "KNAVE" for p in people)
            q = (f"On an island every person is either a knight (always tells the truth) or a knave (always lies). {text}\n\n"
                 "State the type of A, B and C in order, as three comma-separated words, each KNIGHT or KNAVE (no spaces).")
            return q, ans, 1 / 8, "knights", text
    raise RuntimeError("knights exhausted")


def _critical_path(rng):
    n = rng.randint(4, 6)
    names = [chr(65 + i) for i in range(n)]
    dur = {t: rng.randint(1, 9) for t in names}
    deps = {t: sorted(rng.sample(names[:i], rng.randint(0, min(2, i)))) for i, t in enumerate(names)}
    fin: dict[str, int] = {}
    for t in names:
        fin[t] = dur[t] + max([fin[d] for d in deps[t]] or [0])
    lines = [f"Task {t} takes {dur[t]} hours" + (f" and can start only after {' and '.join(deps[t])} finish{'es' if len(deps[t]) == 1 else ''}." if deps[t] else " and can start immediately.")
             for t in names]
    q = " ".join(lines) + "\n\nTasks run in parallel whenever their prerequisites are done. What is the minimum total number of hours until every task is finished?"
    return q, str(max(fin.values())), 0.1, "critical_path", q


def gen_reasoning(rng: random.Random) -> dict:
    fn = rng.choice([_ordering, _syllogism, _calendar, _knights, _critical_path, _ordering, _critical_path])
    q, ans, chance, sub, key = fn(rng)
    return {"prompt": q + ANSWER_LINE, "input": {}, "ground_truth": {"answer": ans, "match": "text"},
            "scoring_method": "answer_line", "difficulty": {"ordering": "easy", "calendar": "easy", "syllogism": "medium", "critical_path": "medium", "knights": "hard"}[sub],
            "meta": {"chance": chance, "dedup_text": key, "subtype": sub}}


# ------------------------------------------------------------------ mathematics
def _fmt(fr: Fraction) -> str:
    if fr.denominator == 1:
        return str(fr.numerator)
    return f"{fr.numerator}/{fr.denominator}"


def gen_mathematics(rng: random.Random) -> dict:
    kind = rng.choice(["rate", "percent", "modpow", "gcdlcm", "fractions", "committee", "base", "sequence", "linear"])
    if kind == "rate":
        per, h, m = rng.randint(3, 40), rng.randint(1, 6), rng.choice([15, 30, 45])
        q = f"A machine makes {per} parts every minute without pause. How many parts does it make in {h} hours and {m} minutes?"
        ans = per * (h * 60 + m)
    elif kind == "percent":
        p = rng.choice([200, 400, 500, 800, 1200, 2000])
        d, t = rng.choice([10, 20, 25, 50]), rng.choice([5, 10, 20])
        val = Fraction(p) * (100 - d) / 100 * (100 + t) / 100
        q = f"A jacket costs {p} rupees. It is discounted by {d} percent, and then a tax of {t} percent is added to the discounted price. What is the final price in rupees?"
        ans = val
    elif kind == "modpow":
        a, b, m = rng.randint(2, 12), rng.randint(5, 40), rng.choice([7, 11, 13, 17, 19, 23])
        q = f"What is the remainder when {a} raised to the power {b} is divided by {m}?"
        ans = pow(a, b, m)
    elif kind == "gcdlcm":
        a, b = rng.randint(12, 90), rng.randint(12, 90)
        which = rng.choice(["greatest common divisor", "least common multiple"])
        q = f"What is the {which} of {a} and {b}?"
        ans = math.gcd(a, b) if which.startswith("greatest") else a * b // math.gcd(a, b)
    elif kind == "fractions":
        a, b, c, d = rng.randint(1, 7), rng.randint(2, 9), rng.randint(1, 7), rng.randint(2, 9)
        q = f"Compute {a}/{b} + {c}/{d}. Give the answer as a fraction in lowest terms (or as an integer if it is whole)."
        ans = Fraction(a, b) + Fraction(c, d)
    elif kind == "committee":
        n, k = rng.randint(6, 12), rng.randint(2, 4)
        a, b = rng.sample(NAMES, 2)
        q = (f"A club has {n} members including {a} and {b}. How many different committees of {k} members can be formed if {a} and {b} "
             f"refuse to serve on the same committee?")
        ans = math.comb(n, k) - math.comb(n - 2, k - 2)
    elif kind == "base":
        n, base = rng.randint(30, 900), rng.choice([2, 3, 5, 8])
        digits = ""
        x = n
        while x:
            digits = str(x % base) + digits
            x //= base
        q = f"Write the decimal number {n} in base {base}. Give only the digits."
        ans = digits
    elif kind == "sequence":
        a1, d, n = rng.randint(-10, 20), rng.randint(2, 9), rng.randint(8, 30)
        q = f"An arithmetic sequence starts at {a1} with common difference {d}. What is the sum of its first {n} terms?"
        ans = n * (2 * a1 + (n - 1) * d) // 2
    else:
        x, a, b = rng.randint(-15, 25), rng.randint(2, 9), rng.randint(-30, 30)
        c = a * x + b
        q = f"Solve for x: {a}x {'+' if b >= 0 else '-'} {abs(b)} = {c}."
        ans = x
    a_s = _fmt(ans) if isinstance(ans, Fraction) else str(ans)
    if isinstance(ans, Fraction) and ans.denominator != 1 and kind == "percent":
        a_s = f"{float(ans):.2f}".rstrip("0").rstrip(".")
    return {"prompt": q + ANSWER_LINE, "input": {}, "ground_truth": {"answer": a_s, "match": "numeric" if kind != "base" else "text"},
            "scoring_method": "answer_line", "difficulty": "easy" if kind in ("rate", "linear", "gcdlcm") else "medium",
            "meta": {"chance": 0.0, "dedup_text": q, "subtype": kind}}


# ------------------------------------------------------------------ verification
def _chain(rng):
    n = rng.randint(4, 7)
    val = rng.randint(3, 30)
    lines = [f"Start with {val}."]
    vals = [val]
    steps = []
    bad = rng.randint(1, n) if rng.random() < 0.7 else None
    cur_true = val
    cur_shown = val
    first_wrong = None
    for i in range(1, n + 1):
        op = rng.choice(["+", "-", "*"])
        k = rng.randint(2, 9)
        cur_true_next = {"+": cur_shown + k, "-": cur_shown - k, "*": cur_shown * k}[op]
        shown = cur_true_next
        if bad == i:
            shown = cur_true_next + rng.choice([-9, -7, -5, -3, -2, -1, 1, 2, 3, 5, 7, 9])
            first_wrong = i
        lines.append(f"Step {i}: {cur_shown} {op} {k} = {shown}.")
        cur_shown = shown
    ans = str(first_wrong) if first_wrong else "NONE"
    q = ("Below is a worked calculation. Each step should apply its operation to the previous result.\n" + "\n".join(lines) +
         "\n\nWhich step is the FIRST one whose arithmetic is wrong? Answer with the step number, or NONE if every step is correct.")
    return q, ans, 1 / (n + 1), "planted_error", "\n".join(lines)


def _claim(rng):
    a, b = rng.sample(NAMES, 2)
    c1, c2 = rng.sample(CITIES, 2)
    y1, y2 = rng.randint(1990, 2020), rng.randint(1990, 2020)
    co = company(rng)
    facts = {f"{a} lives in {c1}.": ("city", a, c1), f"{a} joined {co} in {y1}.": ("year", a, y1), f"{b} lives in {c2}.": ("city", b, c2),
             f"{b} joined {co} in {y2}.": ("year", b, y2)}
    passage = " ".join(rng.sample(list(facts), 4))
    label = rng.choice(["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_INFO"])
    if label == "SUPPORTED":
        claim = rng.choice([f"{a} lives in {c1}.", f"{b} joined {co} in {y2}."])
    elif label == "CONTRADICTED":
        other = rng.choice([c for c in CITIES if c not in (c1, c2)])
        claim = rng.choice([f"{a} lives in {other}.", f"{b} joined {co} in {y2 + rng.randint(1, 5)}."])
    else:
        claim = rng.choice([f"{a} has two children.", f"{b} is older than {a}.", f"{co} has more than 50 employees."])
    q = (f"Passage: {passage}\n\nClaim: {claim}\n\nUsing ONLY the passage, is the claim SUPPORTED, CONTRADICTED, or NOT_ENOUGH_INFO?")
    return q, label, 1 / 3, "claim_evidence", passage + claim


def gen_verification(rng: random.Random) -> dict:
    q, ans, chance, sub, key = rng.choice([_chain, _claim])(rng)
    return {"prompt": q + ANSWER_LINE, "input": {}, "ground_truth": {"answer": ans, "match": "text"}, "scoring_method": "answer_line",
            "difficulty": "medium", "meta": {"chance": chance, "dedup_text": key, "subtype": sub}}


# ------------------------------------------------------------------ information_gain_reasoning
_TRAITS = ["striped", "winged", "nocturnal", "aquatic", "venomous", "social"]


def _entropy(k, n):
    if k in (0, n):
        return 0.0
    p = k / n
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def gen_information_gain_reasoning(rng: random.Random) -> dict:
    for _ in range(200):
        n = rng.randint(5, 8)
        traits = rng.sample(_TRAITS, rng.randint(4, 5))
        labels = [f"Specimen {chr(65 + i)}" for i in range(n)]
        table = {l: {t: rng.random() < 0.5 for t in traits} for l in labels}
        const = rng.choice(traits) if rng.random() < 0.4 else None
        if const:
            v = rng.random() < 0.5
            for l in labels:
                table[l][const] = v
        known = rng.random() < 0.3
        remaining = labels[:]
        note = ""
        if known:
            t = rng.choice(traits)
            val = rng.random() < 0.5
            remaining = [l for l in labels if table[l][t] == val]
            if len(remaining) < 1:
                continue
            note = f" You have already learned that the secret specimen {'is' if val else 'is not'} {t}."
        if len(remaining) == 1:
            ans_set = ["SUFFICIENT"]
        else:
            scores = {t: _entropy(sum(table[l][t] for l in remaining), len(remaining)) for t in traits}
            best = max(scores.values())
            if best == 0.0:
                continue
            ans_set = [f"Q{i + 1}" for i, t in enumerate(traits) if abs(scores[t] - best) < 1e-9]
            if len(ans_set) != 1:          # a unique optimal question keeps chance low and the answer unambiguous
                continue
        rows = "\n".join(f"{l}: " + ", ".join(f"{t}={'yes' if table[l][t] else 'no'}" for t in traits) for l in labels)
        menu = "\n".join(f"Q{i + 1}: Is the secret specimen {t}?" for i, t in enumerate(traits))
        q = (f"One of these specimens is secretly chosen, each equally likely.{note}\n{rows}\n\nYou may ask exactly ONE yes/no question from this menu:\n{menu}\n\n"
             "Choose the single question whose answer is expected to remove the most uncertainty about which specimen it is. "
             "If the specimen is already determined by what you know, answer SUFFICIENT instead of asking.")
        return {"prompt": q + ANSWER_LINE, "input": {}, "ground_truth": {"accepted": ans_set, "match": "any_of"}, "scoring_method": "answer_line",
                "difficulty": "medium", "meta": {"chance": len(ans_set) / (len(traits) + 1), "dedup_text": rows + note, "subtype": "max_information_question"}}
    raise RuntimeError("info gain exhausted")
