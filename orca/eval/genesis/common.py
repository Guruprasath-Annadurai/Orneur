"""Shared vocabulary and helpers for the Genesis Capability Eval V1 generators.

Every generator is a pure function of a seeded ``random.Random``; the same (category, split, index) always yields the
same item. All text is original ORNEUR-authored template text; no external benchmark item is copied.
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Any

from orca.eval.genesis_eval_v1 import CORPUS_VERSION

AUTHORING_SOURCE = ("ORNEUR original; authored by Claude Sonnet 5 (Anthropic) on behalf of ORNEUR as seeded procedural generators; "
                    "no external benchmark item or text was copied")
ANSWER_LINE = "\n\nEnd your reply with a final line of the form `ANSWER: <value>` and nothing after it."

NAMES = ["Asha", "Bram", "Chiara", "Devan", "Elena", "Farid", "Gwen", "Hiro", "Imani", "Joaquin", "Kavya", "Liam", "Mira", "Nikhil", "Oksana",
         "Pavel", "Quinn", "Rania", "Soren", "Tessa", "Umar", "Vera", "Wen", "Xavier", "Yara", "Zane", "Alma", "Boris", "Cyrus", "Dara",
         "Emeka", "Freya", "Goran", "Hana", "Ivo", "Jun", "Kira", "Lars", "Maya", "Nadir"]
CITIES = ["Lisbon", "Osaka", "Nairobi", "Quito", "Oslo", "Pune", "Hanoi", "Lima", "Cairo", "Perth", "Turin", "Accra", "Kyoto", "Basel",
          "Dhaka", "Sofia", "Tunis", "Bergen", "Cusco", "Leeds", "Recife", "Tartu", "Mysore", "Trieste"]
_SYL_A = ["Zor", "Qui", "Mar", "Tav", "Bel", "Nuv", "Kel", "Ost", "Vur", "Lum", "Dra", "Fen", "Hol", "Iri", "Jax", "Pel", "Rin", "Sol", "Tor", "Wyn"]
_SYL_B = ["vex", "llo", "net", "ora", "grio", "dex", "mar", "trin", "lis", "bex", "nol", "quar", "ven", "tal", "ryn", "dor", "min", "sel", "kar", "pho"]
PRODUCT_NOUNS = ["turbine", "sensor", "router", "battery", "compressor", "valve", "drone", "scanner", "printer", "pump", "lens", "kiln"]
ROLES = ["CEO", "CFO", "CTO", "founder", "director", "chair"]


def seed_for(category: str, split: str, idx: int, salt: str = "") -> int:
    return int(hashlib.sha256(f"{CORPUS_VERSION}|{category}|{split}|{idx}|{salt}".encode()).hexdigest()[:16], 16)


def rng_for(category: str, split: str, idx: int, salt: str = "") -> random.Random:
    return random.Random(seed_for(category, split, idx, salt))


def company(rng: random.Random) -> str:
    return rng.choice(_SYL_A) + rng.choice(_SYL_B)


def distinct(rng: random.Random, pool: list[str], k: int) -> list[str]:
    return rng.sample(pool, k)


def distinct_companies(rng: random.Random, k: int) -> list[str]:
    out: list[str] = []
    while len(out) < k:
        c = company(rng)
        if c not in out:
            out.append(c)
    return out


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def fmt_money(x: int) -> str:
    return f"{x:,}"
