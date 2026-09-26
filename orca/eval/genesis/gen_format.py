"""Generators: instruction_following, strict_contracts, structured_outputs, tool_use."""
from __future__ import annotations

import json
import random
import re
from typing import Any

from orca.contracts import ContractEngine, ContractStatus
from orca.contracts.jsonutil import canonical_dumps
from orca.eval.genesis.common import (AUTHORING_SOURCE, CITIES, NAMES, PRODUCT_NOUNS, company, distinct, distinct_companies, norm_ws)

# ------------------------------------------------------------------ instruction_following
IF_TOPICS = ["a community garden", "a bicycle repair shop", "the first day at a new job", "a rainy weekend", "a school science fair",
             "a neighbourhood library", "a long train journey", "cooking for a large family", "a lost umbrella", "a village market",
             "learning to swim", "a broken clock", "a mountain hike", "an old radio", "a quiet harbour", "planting a tree",
             "a power cut at night", "a birthday surprise", "a stray cat", "moving to a new city", "a street musician", "a winter morning",
             "a rooftop telescope", "a repair cafe", "a bus that never came", "the smell of fresh bread", "a chess club", "an empty stadium",
             "a postcard from abroad", "an overgrown path", "a borrowed ladder", "a night shift", "a paper boat", "a jammed printer",
             "a lighthouse keeper", "a farmers cooperative", "a foggy airport", "a hand-drawn map", "a tea stall", "a kite festival"]
IF_POOL = ["river", "lantern", "orchard", "compass", "harbor", "meadow", "cobalt", "ember", "saffron", "granite", "willow", "falcon",
           "mosaic", "quartz", "thistle", "velvet", "anchor", "bramble", "cinder", "dune"]
IF_EXCL = ["always", "never", "very", "really", "suddenly", "amazing", "terrible", "perfect", "obviously", "literally", "basically", "honestly"]
IF_FILLER = ["the", "a", "and", "with", "for", "every", "small", "steady", "plan", "note", "simple", "useful", "clear", "team", "day", "work",
             "idea", "result", "step", "plain", "local", "good", "open", "shared", "early", "quiet", "slow", "kind", "fresh", "calm"]
IF_STARTS = ["Well then", "In short", "First of all", "To begin", "Right now"]
IF_ENDS = ["That is all.", "End of note.", "Thank you.", "Nothing more."]
_WORD = re.compile(r"[A-Za-z0-9'’]+")


def words_of(t: str) -> list[str]:
    return _WORD.findall(t)


def _count(word: str, text: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z0-9'’]){re.escape(word)}(?![A-Za-z0-9'’])", text, flags=re.I))


def check_constraint(c: dict, text: str) -> bool:
    t = text.strip()
    k = c["k"]
    if k == "word_range":
        return c["lo"] <= len(words_of(t)) <= c["hi"]
    if k == "include":
        return _count(c["w"], t) >= 1
    if k == "exclude":
        return _count(c["w"], t) == 0
    if k == "times":
        return _count(c["w"], t) == c["n"]
    if k == "starts":
        return t.startswith(c["p"])
    if k == "ends":
        return t.endswith(c["p"])
    if k == "lowercase":
        return t == t.lower() and any(ch.isalpha() for ch in t)
    if k == "uppercase":
        return t == t.upper() and any(ch.isalpha() for ch in t)
    if k == "bullets":
        return sum(1 for ln in t.splitlines() if ln.startswith("- ")) == c["n"]
    if k == "no_commas":
        return "," not in t
    if k == "quoted":
        return len(t) >= 2 and t[0] == '"' and t[-1] == '"'
    raise ValueError(k)


def describe_constraint(c: dict) -> str:
    k = c["k"]
    return {
        "word_range": f"Use between {c.get('lo')} and {c.get('hi')} words (words are runs of letters/digits).",
        "include": f"Include the word \"{c.get('w')}\".",
        "exclude": f"Do not use the word \"{c.get('w')}\" anywhere.",
        "times": f"Use the word \"{c.get('w')}\" exactly {c.get('n')} times.",
        "starts": f"Begin the reply with exactly: {c.get('p')}",
        "ends": f"End the reply with exactly: {c.get('p')}",
        "lowercase": "Write everything in lowercase letters.",
        "uppercase": "Write everything in UPPERCASE letters.",
        "bullets": f"Write exactly {c.get('n')} lines that begin with \"- \" (a dash and a space).",
        "no_commas": "Do not use any commas.",
        "quoted": "Wrap the whole reply in double quotation marks (the first and last character must be a double quote).",
    }[k]


def _witness(cs: list[dict], rng: random.Random) -> str | None:
    d = {c["k"]: c for c in cs}
    req = []
    if "starts" in d:
        req += d["starts"]["p"].split()
    incl = [c["w"] for c in cs if c["k"] == "include"]
    times = [w for c in cs if c["k"] == "times" for w in [c["w"]] * c["n"]]
    end_tokens = d["ends"]["p"].split() if "ends" in d else []
    lo, hi = (d["word_range"]["lo"], d["word_range"]["hi"]) if "word_range" in d else (20, 60)
    target = (lo + hi) // 2
    core = req + incl + times
    if len(core) + len(end_tokens) + 1 > target:
        return None
    n_fill = target - len(core) - len(end_tokens)
    filler = [IF_FILLER[i % len(IF_FILLER)] for i in range(n_fill)]
    tokens = req + incl + times + filler + end_tokens
    # strip punctuation tokens from the count check: phrases such as "That is all." are alphabetic words plus a period
    if "bullets" in d:
        n = d["bullets"]["n"]
        body = incl + times + filler
        if len(body) < n:
            return None
        per = len(body) // n
        lines = []
        for i in range(n):
            chunk = body[i * per:(i + 1) * per] if i < n - 1 else body[i * per:]
            lines.append("- " + " ".join(chunk))
        text = "\n".join(lines)
    else:
        text = " ".join(tokens)
    if "quoted" in d:
        text = f'"{text}"'
    if "lowercase" in d:
        text = text.lower()
    if "uppercase" in d:
        text = text.upper()
    return text


def gen_instruction_following(rng: random.Random) -> dict:
    for _ in range(200):
        kinds = ["word_range", "include", "exclude", "times", "starts", "ends", "lowercase", "uppercase", "bullets", "no_commas", "quoted"]
        n = rng.choice([2, 3, 3, 4])
        chosen = rng.sample(kinds, n)
        s = set(chosen)
        if len(s & {"word_range", "include", "times", "starts", "ends", "bullets", "quoted"}) < 2:
            continue                      # every item must demand real content; negative/case-only rule sets are satisfiable by any text
        if {"lowercase", "uppercase"} <= s or ({"bullets"} & s and {"starts", "ends", "quoted"} & s) or ({"quoted"} & s and {"starts", "ends"} & s):
            continue
        pool = rng.sample(IF_POOL, 4)
        excl = rng.choice(IF_EXCL)
        cs: list[dict] = []
        for k in chosen:
            if k == "word_range":
                lo = rng.randint(20, 40)
                cs.append({"k": k, "lo": lo, "hi": lo + rng.randint(15, 30)})
            elif k == "include":
                cs.append({"k": k, "w": pool[0]})
            elif k == "exclude":
                cs.append({"k": k, "w": excl})
            elif k == "times":
                cs.append({"k": k, "w": pool[1], "n": rng.randint(2, 3)})
            elif k == "starts":
                cs.append({"k": k, "p": rng.choice(IF_STARTS)})
            elif k == "ends":
                cs.append({"k": k, "p": rng.choice(IF_ENDS)})
            elif k == "bullets":
                cs.append({"k": k, "n": rng.randint(2, 5)})
            else:
                cs.append({"k": k})
        upper = any(c["k"] == "uppercase" for c in cs)
        lower = any(c["k"] == "lowercase" for c in cs)
        for c in cs:
            if c["k"] in ("starts", "ends"):
                c["p"] = c["p"].upper() if upper else c["p"].lower() if lower else c["p"]
        w = _witness(cs, rng)
        if w is None or not all(check_constraint(c, w) for c in cs):
            continue
        topic = rng.choice(IF_TOPICS)
        rules = "\n".join(f"- {describe_constraint(c)}" for c in cs)
        prompt = f"Write a short note about {topic}. Every rule below must hold at once.\n{rules}"
        key = json.dumps(cs, sort_keys=True)          # the rule set IS the task; the topic is decoration, so it must not make two items look distinct
        return {"prompt": prompt, "input": {}, "ground_truth": {"constraints": cs, "sft_target": w}, "scoring_method": "if_constraints",
                "difficulty": "easy" if n == 2 else "medium" if n == 3 else "hard",
                "meta": {"chance": 0.02, "dedup_text": key, "subtype": "verifiable_constraints", "n_constraints": n}}
    raise RuntimeError("instruction_following generator exhausted")


# ------------------------------------------------------------------ strict_contracts
_ENGINE = ContractEngine()


def _boom(_r):
    raise AssertionError("no model")


_LIT_WORDS = ["amber", "signal", "orbit", "granite", "harvest", "paper", "copper", "linen", "ripple", "lantern", "north", "delta", "mint"]


def _expected_via_engine(prompt: str, want_type: str) -> str | None:
    r = _ENGINE.execute(prompt, _boom)
    if r.status is not ContractStatus.SATISFIED or str(getattr(r.evidence.contract_type, 'value', r.evidence.contract_type)) != want_type:
        return None
    return r.final_output


def _rand_expr(rng: random.Random) -> str:
    a, b, c, d = (rng.randint(2, 40) for _ in range(4))
    forms = [f"{a} + {b} * {c}", f"({a} + {b}) * {c}", f"{a} * {b} - {c}", f"{a * b} / {b}", f"({a} - {b}) * ({c} + {d})", f"{a} * {b} + {c} * {d}",
             f"({a} + {b} + {c}) * 2", f"{a * c} / {c} + {b}"]
    return rng.choice(forms)


def gen_strict_contracts(rng: random.Random) -> dict:
    for _ in range(100):
        kind = rng.choice(["exact", "exact2", "math", "json", "schema"])
        if kind in ("exact", "exact2"):
            lit = " ".join(rng.sample(_LIT_WORDS, rng.randint(1, 3))) + (f" {rng.randint(10, 99)}" if rng.random() < 0.4 else "")
            if kind == "exact2":
                lit = lit + "\n" + " ".join(rng.sample(_LIT_WORDS, 2))
            prompt = f"Reply exactly:\n{lit}"
            exp = _expected_via_engine(prompt, "EXACT_TEXT")
            typ = "EXACT_TEXT"
        elif kind == "math":
            prompt = _rand_expr(rng)
            exp = _expected_via_engine(prompt, "DETERMINISTIC_MATH")
            typ = "DETERMINISTIC_MATH"
        elif kind == "json":
            keys = rng.sample(["id", "state", "count", "label", "ok", "mode", "level"], rng.randint(1, 3))
            obj = {k: rng.choice([rng.randint(1, 99), rng.choice(_LIT_WORDS), rng.choice([True, False])]) for k in keys}
            prompt = "Return valid JSON:\n" + json.dumps(obj)
            exp = _expected_via_engine(prompt, "JSON_LITERAL")
            typ = "JSON_LITERAL"
        else:
            name, city, qty = rng.choice(NAMES), rng.choice(CITIES), rng.randint(2, 90)
            schema = {"type": "object", "properties": {"name": {"type": "string"}, "city": {"type": "string"}, "qty": {"type": "integer"}},
                      "required": ["name", "city", "qty"], "additionalProperties": False}
            prompt = (f"Return valid JSON matching this schema:\n{json.dumps(schema)}\nUse: name = {name}, city = {city}, qty = {qty}.")
            from orca.contracts.detect import route
            if route(prompt).contract_type.value != "JSON_SCHEMA":
                continue
            return {"prompt": prompt, "input": {}, "ground_truth": {"contract_type": "JSON_SCHEMA", "schema": schema,
                    "expected_object": {"name": name, "city": city, "qty": qty}, "sft_target": canonical_dumps({"name": name, "city": city, "qty": qty})},
                    "scoring_method": "contract_raw", "difficulty": "medium",
                    "meta": {"chance": 0.0, "dedup_text": prompt, "subtype": "schema"}}
        if exp is None:
            continue
        return {"prompt": prompt, "input": {}, "ground_truth": {"contract_type": typ, "expected_output": exp, "sft_target": exp},
                "scoring_method": "contract_raw", "difficulty": "easy" if typ != "DETERMINISTIC_MATH" else "medium",
                "meta": {"chance": 0.0, "dedup_text": prompt, "subtype": typ.lower()}}
    raise RuntimeError("strict_contracts generator exhausted")


# ------------------------------------------------------------------ structured_outputs
def gen_structured_outputs(rng: random.Random) -> dict:
    kind = rng.choice(["invoice", "meeting", "shipment"])
    a, b = rng.sample(NAMES, 2)
    v = company(rng)
    if kind == "invoice":
        num = f"INV-{rng.randint(1000, 9999)}"
        y, m, d = 2026, rng.randint(1, 12), rng.randint(1, 28)
        items = rng.randint(2, 9)
        total = round(rng.randint(120, 9800) + rng.choice([0, 0.25, 0.5, 0.75]), 2)
        paid = rng.random() < 0.5
        distract = rng.randint(100, 999)
        parts = [f"Vendor {v} issued invoice {num} on {y}-{m:02d}-{d:02d}.", f"It lists {items} line items.",
                 f"The amount due is {total:.2f} in total, and the purchase order reference {distract} is unrelated to the amount.",
                 "Payment has been received in full." if paid else "Payment is still outstanding."]
        rng.shuffle(parts)
        passage = " ".join(parts)
        schema = {"type": "object", "properties": {"vendor": {"type": "string"}, "invoice_number": {"type": "string"}, "date": {"type": "string"},
                  "line_items": {"type": "integer"}, "total": {"type": "number"}, "paid": {"type": "boolean"}},
                  "required": ["vendor", "invoice_number", "date", "line_items", "total", "paid"], "additionalProperties": False}
        exp = {"vendor": v, "invoice_number": num, "date": f"{y}-{m:02d}-{d:02d}", "line_items": items, "total": total, "paid": paid}
    elif kind == "meeting":
        att = rng.sample(NAMES, rng.randint(2, 4))
        actions = rng.randint(1, 6)
        d2 = rng.randint(1, 28)
        room = rng.choice(["Cedar", "Atlas", "Harbor", "Summit"])
        parts = [f"The {room} room was booked for the {v} planning meeting.", f"Attendees were {', '.join(att[:-1])} and {att[-1]}.",
                 f"They agreed on {actions} action items.", f"The next meeting is on 2026-11-{d2:02d}."]
        rng.shuffle(parts)
        passage = " ".join(parts)
        schema = {"type": "object", "properties": {"room": {"type": "string"}, "attendees": {"type": "array", "items": {"type": "string"}},
                  "action_items": {"type": "integer"}, "next_meeting": {"type": "string"}},
                  "required": ["room", "attendees", "action_items", "next_meeting"], "additionalProperties": False}
        exp = {"room": room, "attendees": att, "action_items": actions, "next_meeting": f"2026-11-{d2:02d}"}
        num = room
    else:
        city_from, city_to = rng.sample(CITIES, 2)
        weight = rng.randint(3, 400)
        fragile = rng.random() < 0.5
        code = f"SH{rng.randint(10000, 99999)}"
        parts = [f"Shipment {code} leaves {city_from} for {city_to}.", f"Its gross weight is {weight} kilograms.",
                 "It contains fragile goods." if fragile else "It contains no fragile goods.", f"The carrier is {v}."]
        rng.shuffle(parts)
        passage = " ".join(parts)
        schema = {"type": "object", "properties": {"code": {"type": "string"}, "origin": {"type": "string"}, "destination": {"type": "string"},
                  "weight_kg": {"type": "integer"}, "fragile": {"type": "boolean"}, "carrier": {"type": "string"}},
                  "required": ["code", "origin", "destination", "weight_kg", "fragile", "carrier"], "additionalProperties": False}
        exp = {"code": code, "origin": city_from, "destination": city_to, "weight_kg": weight, "fragile": fragile, "carrier": v}
        num = code
    prompt = (f"Read the passage and extract the facts.\n\nPassage: {passage}\n\nRespond with ONLY a JSON object that matches this schema "
              f"(no code fences, no commentary):\n{json.dumps(schema)}")
    return {"prompt": prompt, "input": {}, "ground_truth": {"schema": schema, "expected_object": exp, "sft_target": canonical_dumps(exp)},
            "scoring_method": "json_fields", "difficulty": "easy" if kind != "meeting" else "medium",
            "meta": {"chance": 0.0, "dedup_text": passage, "subtype": kind}}


# ------------------------------------------------------------------ tool_use
def _tools() -> dict[str, dict]:
    return {
        "get_weather": {"description": "Current weather for a city.", "params": {"city": "string", "unit": "string:celsius|fahrenheit"}, "required": ["city", "unit"]},
        "convert_currency": {"description": "Convert an amount between currencies.", "params": {"amount": "integer", "from_code": "string", "to_code": "string"}, "required": ["amount", "from_code", "to_code"]},
        "set_timer": {"description": "Start a countdown timer.", "params": {"minutes": "integer", "label": "string"}, "required": ["minutes", "label"]},
        "send_email": {"description": "Send an email message.", "params": {"to": "string", "subject": "string"}, "required": ["to", "subject"]},
        "find_flight": {"description": "Search flights.", "params": {"origin": "string", "destination": "string", "date": "string:YYYY-MM-DD"}, "required": ["origin", "destination", "date"]},
        "create_event": {"description": "Add a calendar event.", "params": {"title": "string", "date": "string:YYYY-MM-DD", "duration_minutes": "integer"}, "required": ["title", "date", "duration_minutes"]},
    }


_CUR = ["USD", "EUR", "INR", "GBP", "JPY", "CAD"]


def gen_tool_use(rng: random.Random) -> dict:
    tools = _tools()
    subset = rng.sample(sorted(tools), 4)
    kind = rng.choice(["call", "call", "call", "none", "missing"])
    name = rng.choice(subset)
    person = rng.choice(NAMES).lower()
    if kind == "none":
        req = rng.choice(["Tell me a short joke about penguins.", "Explain in one sentence why the sky looks blue.", "What is 12 times 12?",
                          "Recommend a title for a novel about a lighthouse.", "Write a two-line poem about autumn."])
        gold = {"tool": None}
        sub = "no_tool"
        req = req + f" (ref {rng.randint(100, 999)})"
    else:
        if name == "get_weather":
            c, u = rng.choice(CITIES), rng.choice(["celsius", "fahrenheit"])
            req = f"What is the weather like in {c} right now? I want it in {u}."
            args = {"city": c, "unit": u}
        elif name == "convert_currency":
            amt, f, t = rng.randint(5, 900), *rng.sample(_CUR, 2)
            req = f"How much is {amt} {f} in {t}?"
            args = {"amount": amt, "from_code": f, "to_code": t}
        elif name == "set_timer":
            mins, lab = rng.randint(2, 90), rng.choice(["pasta", "laundry", "tea", "focus", "oven"])
            req = f"Start a {mins} minute timer called {lab}."
            args = {"minutes": mins, "label": lab}
        elif name == "send_email":
            subj = rng.choice(["Quarterly numbers", "Lunch plan", "Route change", "Invoice question"])
            req = f"Email {person}@example.com with the subject \"{subj}\"."
            args = {"to": f"{person}@example.com", "subject": subj}
        elif name == "find_flight":
            o, d = rng.sample(CITIES, 2)
            dt = f"2026-{rng.randint(10, 12)}-{rng.randint(10, 28)}"
            req = f"Find me a flight from {o} to {d} on {dt}."
            args = {"origin": o, "destination": d, "date": dt}
        else:
            ttl = rng.choice(["Design review", "Dentist", "Team lunch", "Budget sync"])
            dt = f"2026-{rng.randint(10, 12)}-{rng.randint(10, 28)}"
            du = rng.choice([30, 45, 60, 90])
            req = f"Put '{ttl}' on my calendar on {dt} for {du} minutes."
            args = {"title": ttl, "date": dt, "duration_minutes": du}
        if kind == "missing":
            drop = rng.choice(list(args))
            # rewrite the request so that one required value is genuinely absent
            miss_req = {"get_weather": "What is the weather like right now?", "convert_currency": "Convert some money for me.",
                        "set_timer": "Start a timer.", "send_email": "Send an email for me.", "find_flight": "Find me a flight.",
                        "create_event": "Add something to my calendar."}[name]
            req = miss_req + f" (ticket {rng.randint(100, 999)})"
            gold = {"tool": None}
            sub = "missing_argument"
        else:
            gold = {"tool": name, "arguments": args}
            sub = "call"
        if name not in subset:
            subset[0] = name
    specs = [{"name": t, "description": tools[t]["description"], "parameters": tools[t]["params"], "required": tools[t]["required"]} for t in sorted(subset)]
    if kind != "none" and name not in {s["name"] for s in specs}:
        raise RuntimeError("tool missing")
    prompt = ("You can call exactly one tool, or none. Available tools (JSON):\n" + json.dumps(specs) +
              "\n\nRules: reply with ONLY a JSON object. To call a tool use {\"tool\": <name>, \"arguments\": {...}} with every required argument. "
              "If no listed tool applies, or a required argument is missing from the request, reply {\"tool\": null}. Do not invent values.\n\nRequest: " + req)
    tgt = canonical_dumps(gold)
    return {"prompt": prompt, "input": {"tools": specs}, "ground_truth": {**gold, "sft_target": tgt},
            "scoring_method": "tool_call", "difficulty": "easy" if sub == "call" else "medium",
            "meta": {"chance": 0.05, "dedup_text": req + "|" + ",".join(s["name"] for s in specs), "subtype": sub}}
