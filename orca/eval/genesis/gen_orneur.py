"""Generators for the strategic ORNEUR categories: research, evidence_use, counterfactual_reasoning, hypothesis_testing,
discovery_quality, cross_domain_transfer. Ground truth is deterministic: planted facts, anchors, decoys, graphs and formulas."""
from __future__ import annotations

import json
import random
from fractions import Fraction

from orca.eval.genesis.common import ANSWER_LINE, CITIES, NAMES, PRODUCT_NOUNS, ROLES, company, distinct, distinct_companies

_JSON_ONLY = "Respond with ONLY a JSON object (no code fences, no commentary)."


# ------------------------------------------------------------------ research
def _doc(co, year, city, founder, ceo, product):
    forms = [f"{co} was founded in {year} in {city} by {founder}. Its chief executive is {ceo}. Its flagship product is the {product}.",
             f"The flagship product of {co} is the {product}. The firm began in {city} in {year}, started by {founder}, and is now run by {ceo}.",
             f"{ceo} is the chief executive of {co}. {co} started in {year} when {founder} opened its first office in {city}, and sells the {product}."]
    return forms


def gen_research(rng: random.Random) -> dict:
    k = 5
    cos = distinct_companies(rng, k)
    people = rng.sample(NAMES, k * 2)
    facts = [{"co": cos[i], "year": rng.randint(1961, 2015), "city": rng.choice(CITIES), "founder": people[2 * i], "ceo": people[2 * i + 1],
              "product": f"{cos[i].lower()[:3]} {rng.choice(PRODUCT_NOUNS)}"} for i in range(k)]
    kind = rng.choice(["product_city", "founder_ceo", "two_hop", "earlier"])
    # shuffle order of documents
    order = list(range(k))
    rng.shuffle(order)
    texts = {}
    for i, f in enumerate(facts):
        texts[i] = rng.choice(_doc(f["co"], f["year"], f["city"], f["founder"], f["ceo"], f["product"]))
    extra = None
    if kind == "two_hop":
        j = rng.randrange(k)
        # person of doc j: the CEO also 'previously led' another company mentioned only in a separate doc
        tgt = rng.choice([x for x in range(k) if x != j])
        extra = f"Before joining {facts[j]['co']}, {facts[j]['ceo']} led {facts[tgt]['co']}."
    docs = [(f"D{n + 1}", texts[i], i) for n, i in enumerate(order)]
    id_of = {i: d for d, _, i in docs}
    if kind == "product_city":
        i = rng.randrange(k)
        q = f"In which city was the company that sells the {facts[i]['product']} founded?"
        ans, cites = facts[i]["city"], {id_of[i]}
    elif kind == "founder_ceo":
        i = rng.randrange(k)
        q = f"Who is the chief executive of the company founded by {facts[i]['founder']}?"
        ans, cites = facts[i]["ceo"], {id_of[i]}
    elif kind == "two_hop":
        q = f"Where was the company that {facts[j]['ceo']} led BEFORE {facts[j]['co']} started?"
        ans, cites = facts[tgt]["city"], {id_of[tgt], f"D{k + 1}"}
        docs.append((f"D{k + 1}", extra, -1))
        rng.shuffle(docs)
        # re-id after shuffle so ids stay D1..Dn in displayed order
        remap = {old: f"D{n + 1}" for n, (old, _, _) in enumerate(docs)}
        cites = {remap[c] for c in cites}
        docs = [(remap[o], t, i) for o, t, i in docs]
    else:
        a, b = rng.sample(range(k), 2)
        while facts[a]["year"] == facts[b]["year"]:
            b = rng.choice([x for x in range(k) if x != a])
        q = f"Which company was founded earlier, {facts[a]['co']} or {facts[b]['co']}?"
        ans = facts[a]["co"] if facts[a]["year"] < facts[b]["year"] else facts[b]["co"]
        cites = {id_of[a], id_of[b]}
    body = "\n".join(f"[{d}] {t}" for d, t, _ in docs)
    prompt = (f"Use ONLY the numbered documents to answer.\n\n{body}\n\nQuestion: {q}\n\n{_JSON_ONLY} Format: "
              "{\"answer\": <string>, \"citations\": [<document ids that you relied on>]}. Cite every document needed, and no others.")
    return {"prompt": prompt, "input": {}, "ground_truth": {"answer": ans, "citations": sorted(cites)}, "scoring_method": "answer_citations",
            "difficulty": "easy" if kind in ("product_city", "founder_ceo") else "medium",
            "meta": {"chance": 0.01, "dedup_text": body + q, "subtype": kind}}


# ------------------------------------------------------------------ evidence_use
_ATTRS = [("revenue", lambda r: f"{r.randint(20, 900)} million rupees"), ("headcount", lambda r: f"{r.randint(40, 4000)} employees"),
          ("warehouse count", lambda r: f"{r.randint(2, 30)} warehouses"), ("defect rate", lambda r: f"{r.randint(1, 9)}.{r.randint(0, 9)} percent")]


def gen_evidence_use(rng: random.Random) -> dict:
    co = company(rng)
    kind = rng.choice(["answerable", "conflict", "abstain", "answerable", "conflict", "abstain"])
    attr, mk = rng.choice(_ATTRS)
    other_attr, mk2 = rng.choice([a for a in _ATTRS if a[0] != attr])
    ent_other = company(rng)
    passages: list[tuple[str, str]] = []
    conflict, answer, evidence = False, "", []
    v_new, v_old = mk(rng), mk(rng)
    while v_new == v_old:
        v_old = mk(rng)
    if kind == "answerable":
        passages.append((f"The {attr} of {co} is {v_new}.", "S"))
        answer, evidence = v_new, ["S"]
    elif kind == "conflict":
        d_old = f"2026-0{rng.randint(1, 4)}-{rng.randint(10, 28)}"
        d_new = f"2026-0{rng.randint(6, 9)}-{rng.randint(10, 28)}"
        passages.append((f"[dated {d_old}] The {attr} of {co} is {v_old}.", "OLD"))
        passages.append((f"[dated {d_new}] The {attr} of {co} is {v_new}.", "NEW"))
        answer, evidence, conflict = v_new, ["NEW"], True
    else:
        answer, evidence = "INSUFFICIENT", []
    passages.append((f"The {other_attr} of {co} is {mk2(rng)}.", "D1"))
    passages.append((f"The {attr} of {ent_other} is {mk(rng)}.", "D2"))
    passages.append((f"{co} is based in {rng.choice(CITIES)}.", "D3"))
    rng.shuffle(passages)
    idmap = {tag: f"E{n + 1}" for n, (_, tag) in enumerate(passages)}
    body = "\n".join(f"[{idmap[tag]}] {t}" for t, tag in passages)
    ev_ids = sorted(idmap[t] for t in evidence)
    q = f"What is the {attr} of {co}?"
    prompt = (f"Answer using ONLY these evidence passages. If passages conflict, use the most recently dated one. If the passages do not contain the answer, "
              f"the answer must be exactly INSUFFICIENT.\n\n{body}\n\nQuestion: {q}\n\n{_JSON_ONLY} Format: "
              "{\"answer\": <string>, \"evidence\": [<ids of the passages that support the answer>], \"conflict\": <true if two passages disagree about the asked fact, else false>}.")
    return {"prompt": prompt, "input": {}, "ground_truth": {"answer": answer, "evidence": ev_ids, "conflict": conflict}, "scoring_method": "answer_evidence",
            "difficulty": "medium" if kind == "conflict" else "easy", "meta": {"chance": 0.03, "dedup_text": body + q, "subtype": kind}}


# ------------------------------------------------------------------ counterfactual_reasoning
def _dag(rng):
    n = rng.randint(7, 9)
    names = [f"N{i + 1}" for i in range(n)]
    spec = {}
    for i, t in enumerate(names):
        if i < 2:
            spec[t] = ("src", [])
        else:
            deps = sorted(rng.sample(names[:i], rng.randint(1, min(3, i))))
            spec[t] = (rng.choice(["all", "any"]) if len(deps) > 1 else "all", deps)
    failed = rng.choice(names[:4])
    works = {}
    for t in names:
        kind, deps = spec[t]
        if t == failed:
            works[t] = False
        elif kind == "src":
            works[t] = True
        elif kind == "all":
            works[t] = all(works[d] for d in deps)
        else:
            works[t] = any(works[d] for d in deps)
    dead = sorted(t for t in names if t != failed and not works[t])
    lines = []
    for t in names:
        kind, deps = spec[t]
        if kind == "src":
            lines.append(f"{t} needs nothing else.")
        elif len(deps) == 1:
            lines.append(f"{t} needs {deps[0]} to be working.")
        else:
            lines.append(f"{t} works if {'ALL' if kind == 'all' else 'AT LEAST ONE'} of {', '.join(deps)} {'are' if kind == 'all' else 'is'} working.")
    q = (" ".join(lines) + f"\n\nIf {failed} stops working (and nothing is repaired), which OTHER components stop working? "
         "List their names in ascending order separated by commas with no spaces, or write NONE.")
    return q, ",".join(dead) if dead else "NONE", "set", "dependency_graph", " ".join(lines) + failed


def _formula(rng):
    price, units, fixed, var = rng.choice([10, 12, 15, 20, 25]), rng.choice([100, 200, 400, 500]), rng.choice([500, 800, 1000, 2000]), rng.choice([2, 3, 4, 5, 6])
    pct = rng.choice([10, 20, 25, 50])
    knob = rng.choice(["price", "units", "var"])
    base = dict(price=price, units=units, fixed=fixed, var=var)
    new = dict(base)
    up = Fraction(100 + pct, 100)
    new[knob] = Fraction(base[knob]) * up
    profit = lambda d: Fraction(d["price"]) * d["units"] - (Fraction(d["fixed"]) + Fraction(d["var"]) * d["units"])
    names = {"price": "the selling price per unit", "units": "the number of units sold", "var": "the variable cost per unit"}
    q = (f"A shop sells units at {price} rupees each and sold {units} units. Its costs are a fixed {fixed} rupees plus {var} rupees for each unit sold. "
         f"Profit = revenue - cost.\n\nCounterfactual: if {names[knob]} had been {pct} percent higher and every other number unchanged, what would the profit have been in rupees?")
    a = profit(new)
    return q, (str(a.numerator) if a.denominator == 1 else f"{float(a):.2f}".rstrip("0").rstrip(".")), "numeric", "formula", q


def gen_counterfactual_reasoning(rng: random.Random) -> dict:
    q, ans, match, sub, key = rng.choice([_dag, _dag, _formula])(rng)
    return {"prompt": q + ANSWER_LINE, "input": {}, "ground_truth": {"answer": ans, "match": match}, "scoring_method": "answer_line",
            "difficulty": "hard" if sub == "dependency_graph" else "medium", "meta": {"chance": 0.03, "dedup_text": key, "subtype": sub}}


# ------------------------------------------------------------------ hypothesis_testing
_CAUSES = [("the new fertiliser", "taller plants"), ("the night-time cooling schedule", "fewer cracked bricks"), ("the updated firmware", "shorter boot times"),
           ("the revised shift rota", "fewer late deliveries"), ("the second catalyst", "higher yield"), ("the new coating", "slower rusting")]
_OBS = ["the effect appears", "the effect does not appear", "the effect is stronger", "the effect is weaker", "the effect is unchanged"]


def gen_hypothesis_testing(rng: random.Random) -> dict:
    cause, effect = rng.choice(_CAUSES)
    h = f"Hypothesis H: {cause} is what produces {effect}."
    ids = ["E1", "E2", "E3", "E4", "E5"]
    kind = rng.choice(["choose", "verdict"])
    disc = set(rng.sample(ids, rng.randint(1, 2)))
    exps = []
    for e in ids:
        base = rng.choice(_OBS)
        if e in disc:
            other = rng.choice([o for o in _OBS if o != base])
            h_pred, n_pred = base, other
        else:
            h_pred = n_pred = base
        exps.append((e, rng.choice(["Run a paired trial", "Repeat with the factor removed", "Swap the factor between two groups", "Compare before and after",
                                     "Use a matched control site", "Add the factor to a fresh batch"]), h_pred, n_pred))
    listing = "\n".join(f"{e}: {d}. If H is true, {hp}. If H is false, {np_}." for e, d, hp, np_ in exps)
    if kind == "choose":
        q = (f"{h}\n\nCandidate experiments:\n{listing}\n\nWhich single experiment could actually falsify H (its predicted result differs depending on whether H is true)? "
             "Answer with its id.")
        return {"prompt": q + ANSWER_LINE, "input": {}, "ground_truth": {"accepted": sorted(disc), "match": "any_of"}, "scoring_method": "answer_line",
                "difficulty": "medium", "meta": {"chance": len(disc) / 5, "dedup_text": listing, "subtype": "choose_falsifier"}}
    e, d, hp, np_ = rng.choice(exps)
    if hp == np_:
        obs, ans = hp, "NON_DISCRIMINATING"
    else:
        pick_h = rng.random() < 0.5
        obs = hp if pick_h else np_
        ans = "CONSISTENT_WITH_H" if pick_h else "FALSIFIED"
    q = (f"{h}\n\nExperiment {e}: {d}. If H is true, {hp}. If H is false, {np_}.\nObserved result: {obs}.\n\nWhat does this result do to H? "
         "Answer FALSIFIED (the result rules H out), CONSISTENT_WITH_H (H survived a test that could have refuted it), or NON_DISCRIMINATING "
         "(the experiment predicts the same result whether or not H is true, so it cannot test H).")
    return {"prompt": q + ANSWER_LINE, "input": {}, "ground_truth": {"answer": ans, "match": "text"}, "scoring_method": "answer_line",
            "difficulty": "medium", "meta": {"chance": 1 / 3, "dedup_text": listing[:0] + q, "subtype": "verdict"}}


# ------------------------------------------------------------------ discovery_quality
_STATUS_FILLER = ["The kitchen refit is on schedule.", "Office plants were watered.", "The quarterly newsletter went to print.", "Parking passes were renewed.",
                  "Two laptops were reimaged.", "The canteen menu was updated.", "A fire drill is planned for next month.", "The lobby paint has dried."]


def _scenario(rng, kind):
    proj = rng.choice(["Harbor", "Summit", "Atlas", "Cedar", "Orchid"]) + " project"
    part = rng.choice(PRODUCT_NOUNS)
    co = company(rng)
    d = {}
    docs: list[tuple[str, str]] = []
    valid, decoys = [], []
    def add(t, tag):
        docs.append((t, tag))
    if kind == "hidden_contradiction":
        d1, d2 = f"2026-10-{rng.randint(5, 12):02d}", f"2026-11-{rng.randint(10, 25):02d}"
        add(f"Project plan: delivery of the {part} is confirmed for {d1}.", "A")
        add(f"Supplier note from {co}: the {part} will ship on {d2}.", "B")
        valid.append({"type": "CONTRADICTION", "anchors": ["A", "B"], "counter": [], "importance": "high", "why": "the plan and the supplier give different dates and nobody asked about dates",
                      "falsifier": ["confirm", "supplier", "date"], "action": ["confirm", "supplier", "reschedule", "date"]})
        decoys.append({"type": "CONTRADICTION", "anchors": ["C", "D"], "why": "apparent mismatch resolved by an explicit correction"})
        add(f"Budget sheet says the {part} costs 4,200 rupees.", "C")
        add(f"Correction: the {part} costs 4,200 rupees; an earlier draft showing 4,500 was a typo.", "D")
    elif kind == "hidden_dependency":
        add(f"Task Launch requires the {part} to be installed first.", "A")
        add(f"Installer log: the {part} is on backorder with no arrival date.", "B")
        valid.append({"type": "RISK", "anchors": ["A", "B"], "counter": [], "importance": "high", "why": "the launch depends on an item that is not arriving; the status question does not mention the part",
                      "falsifier": ["arrive", "arrival", "delivered", "installed"], "action": ["expedite", "alternative", "supplier", "reschedule"]})
        decoys.append({"type": "RISK", "anchors": ["C"], "why": "a task with no dependency on the delayed item"})
        add(f"Task Training requires only the meeting room, which is booked.", "C")
        add(f"The {part} order was placed in September.", "D")
    elif kind == "weak_signal":
        a, b, c = round(rng.uniform(0.8, 1.1), 1), None, None
        b, c = round(a + rng.uniform(0.3, 0.5), 1), 0
        c = round(b + rng.uniform(0.4, 0.6), 1)
        add(f"August report: defect rate {a} percent (tolerance is 3 percent).", "A")
        add(f"September report: defect rate {b} percent (tolerance is 3 percent).", "B")
        add(f"October report: defect rate {c} percent (tolerance is 3 percent).", "C")
        valid.append({"type": "WEAK_SIGNAL", "anchors": ["A", "B", "C"], "counter": [], "importance": "medium", "why": "each value is within tolerance so nothing looks wrong, but the trend rises every month",
                      "falsifier": ["november", "next month", "fall", "decrease", "trend"], "action": ["monitor", "investigate", "inspect", "root cause"]})
        add("Complaint volume: 12 in August, 10 in September, 11 in October (the report calls this normal variation).", "D")
        decoys.append({"type": "WEAK_SIGNAL", "anchors": ["D"], "why": "stated to be normal variation"})
    elif kind == "missing_information":
        add(f"Action list: (1) order the {part}, owner {rng.choice(NAMES)}, due 2026-11-03. (2) book the venue, owner {rng.choice(NAMES)}, due 2026-11-10.", "A")
        add("(3) approve the budget, owner: (blank), due: (blank).", "B")
        valid.append({"type": "MISSING_INFORMATION", "anchors": ["B"], "counter": [], "importance": "high", "why": "the budget approval has no owner or due date and it blocks the other items",
                      "falsifier": ["owner", "assigned", "due date"], "action": ["assign", "owner", "ask", "clarify"]})
        add("Attendance was 14 of 16 invited people.", "C")
        decoys.append({"type": "MISSING_INFORMATION", "anchors": ["C"], "why": "the two absentees are irrelevant to the decision"})
    elif kind == "invalidated_decision":
        pr = rng.choice([90, 95, 100])
        add(f"Decision log: we chose {co} as vendor because its unit price is at most {pr} rupees.", "A")
        add(f"Vendor bulletin: {co} raises its unit price to {pr + rng.randint(25, 60)} rupees from November.", "B")
        valid.append({"type": "INVALIDATED_CONCLUSION", "anchors": ["A", "B"], "counter": [], "importance": "high", "why": "the reason for the earlier vendor decision no longer holds and the update request does not mention it",
                      "falsifier": ["price", "contract", "locked", "fixed"], "action": ["renegotiate", "revisit", "compare", "review"]})
        add("The vendor's delivery record is 98 percent on time.", "C")
        decoys.append({"type": "INVALIDATED_CONCLUSION", "anchors": ["C"], "why": "delivery record is unrelated to the price condition"})
    elif kind == "opportunity":
        add(f"Supplier flyer: {co} offers 15 percent off bulk orders of the {part} until {'2026-12-01'}.", "A")
        add(f"Plan: we will need {rng.randint(300, 900)} units of the {part} next quarter.", "B")
        valid.append({"type": "OPPORTUNITY", "anchors": ["A", "B"], "counter": [], "importance": "medium", "why": "a live discount matches a known future need; nobody asked about purchasing",
                      "falsifier": ["expire", "deadline", "minimum", "price"], "action": ["order", "buy", "purchase", "place"]})
        add(f"Old flyer: 20 percent off {part} orders until 2025-03-01.", "C")
        decoys.append({"type": "OPPORTUNITY", "anchors": ["C"], "why": "the discount expired long ago"})
    else:  # cross_domain
        add("Bakery note: when orders arrive faster than the oven can bake, we pre-bake the most popular loaf during quiet hours.", "A")
        add("Support desk note: ticket volume spikes every Monday and the queue grows all morning.", "B")
        valid.append({"type": "CROSS_DOMAIN_TRANSFER", "anchors": ["A", "B"], "counter": [], "importance": "low", "why": "the bakery's pre-baking during quiet hours maps onto pre-drafting answers for predictable Monday tickets",
                      "falsifier": ["repeat", "predictable", "pattern", "different"], "action": ["pre-draft", "prepare", "template", "before"]})
        add("Canteen note: tea is served at 4 pm.", "C")
        decoys.append({"type": "CROSS_DOMAIN_TRANSFER", "anchors": ["C"], "why": "no structural similarity"})
    for _ in range(rng.randint(2, 3)):
        add(rng.choice(_STATUS_FILLER), f"F{rng.randint(1, 9999)}")
    rng.shuffle(docs)
    tag2id = {tag: f"D{i + 1}" for i, (_, tag) in enumerate(docs)}
    body = "\n".join(f"[{tag2id[tag]}] {t}" for t, tag in docs)
    gold = [{**v, "anchors": sorted(tag2id[a] for a in v["anchors"]), "counter": sorted(tag2id[a] for a in v["counter"])} for v in valid]
    dec = [{**dd, "anchors": sorted(tag2id[a] for a in dd["anchors"])} for dd in decoys]
    return proj, body, gold, dec, sorted(tag2id.values())


def gen_discovery_quality(rng: random.Random) -> dict:
    kind = rng.choice(["hidden_contradiction", "hidden_dependency", "weak_signal", "missing_information", "invalidated_decision", "opportunity", "cross_domain"])
    proj, body, gold, dec, ids = _scenario(rng, kind)
    types = "CONTRADICTION, RISK, WEAK_SIGNAL, MISSING_INFORMATION, INVALIDATED_CONCLUSION, OPPORTUNITY, CROSS_DOMAIN_TRANSFER"
    prompt = (f"Here are the current documents for the {proj}.\n\n{body}\n\nTask: write a two-sentence status summary for the weekly update.\n\n"
              "Also report anything important you notice that I did NOT ask about. Report only findings that the documents actually support; do not brainstorm. "
              f"{_JSON_ONLY} Format: {{\"summary\": <string>, \"discoveries\": [{{\"type\": <one of {types}>, \"evidence\": [<document ids>], "
              "\"statement\": <string>, \"falsification_condition\": <what observation would show you are wrong>, \"suggested_action\": <string>}]}. "
              "Use an empty list if there is nothing worth reporting.")
    return {"prompt": prompt, "input": {"document_ids": ids}, "ground_truth": {"valid_discoveries": gold, "decoys": dec},
            "scoring_method": "discovery_anchor", "difficulty": "hard", "meta": {"chance": 0.0, "dedup_text": body, "subtype": kind}}


# ------------------------------------------------------------------ cross_domain_transfer
def gen_cross_domain_transfer(rng: random.Random) -> dict:
    kind = rng.choice(["bottleneck", "growth", "queue", "sync"])
    decoy = rng.random() < 0.4
    if kind == "bottleneck":
        ra, rb = [rng.randint(3, 9) * 10 for _ in range(3)], [rng.randint(12, 60) * 10 for _ in range(3)]
        ex = (f"Worked example (a bakery line): mixing handles {ra[0]} loaves per hour, baking {ra[1]} per hour and packing {ra[2]} per hour, one after another. "
              f"The line's output per hour is limited by its slowest stage, so the answer is {min(ra)} loaves per hour.")
        if decoy:
            ans = sum(rb)
            pb = (f"Problem (a data platform): three ingest workers run side by side and each feeds records independently at {rb[0]}, {rb[1]} and {rb[2]} records per minute. "
                  "How many records per minute does the platform take in altogether?")
        else:
            ans = min(rb)
            pb = (f"Problem (a data pipeline): records pass through ingest ({rb[0]} per minute), transform ({rb[1]} per minute) and load ({rb[2]} per minute), one after another. "
                  "How many records per minute can the pipeline deliver in steady state?")
    elif kind == "growth":
        base, t, tt = rng.randint(3, 9), rng.choice([2, 3]), rng.choice([2, 3, 4])
        n = rng.randint(2, 4)
        ex = (f"Worked example (yeast): a colony of {base} units doubles every {t} hours. After {t * n} hours it has {base} x 2^{n} = {base * 2 ** n} units.")
        f2, tt2, n2, b2 = rng.choice([3, 4]), tt, rng.randint(2, 4), rng.randint(5, 20)
        if decoy:
            add = rng.randint(5, 30)
            ans = b2 + add * n2
            pb = (f"Problem (a social post): it starts with {b2} viewers and gains a fixed {add} new viewers every {tt2} days. How many viewers after {tt2 * n2} days?")
        else:
            ans = b2 * f2 ** n2
            pb = (f"Problem (a social post): it starts with {b2} viewers and its audience multiplies by {f2} every {tt2} days. How many viewers after {tt2 * n2} days?")
    elif kind == "queue":
        arr, srv, back = rng.randint(4, 9), rng.randint(12, 20), rng.randint(40, 200)
        ex = (f"Worked example (a clinic): patients arrive at {arr} per hour, the doctor sees {srv} per hour, and {back} are waiting. The backlog shrinks by {srv - arr} per hour, "
              f"so it clears in {back}/{srv - arr} hours.")
        arr2, srv2, back2 = rng.randint(3, 8), rng.randint(15, 30), rng.randint(60, 300)
        if decoy:
            ans_f = Fraction(back2, srv2)
            pb = (f"Problem (a print queue): {back2} jobs are waiting and NO new jobs will arrive; the printer finishes {srv2} jobs per minute. In how many minutes is the queue empty?")
        else:
            ans_f = Fraction(back2, srv2 - arr2)
            pb = (f"Problem (a print queue): jobs arrive at {arr2} per minute, the printer finishes {srv2} per minute, and {back2} jobs are waiting now. In how many minutes is the queue empty?")
        ans = ans_f.numerator // ans_f.denominator if ans_f.denominator == 1 else round(float(ans_f), 2)
        if ans_f.denominator != 1:
            pb += " Give the answer as a decimal rounded to two places."
    else:
        a, b = rng.choice([(4, 6), (6, 8), (9, 12), (10, 15), (12, 18), (8, 12)])
        ex = f"Worked example (two lamps): one flashes every {a} seconds and the other every {b} seconds, both starting together. They flash together again after lcm({a}, {b}) = {a * b // __import__('math').gcd(a, b)} seconds."
        a2, b2 = rng.choice([(14, 21), (15, 20), (16, 24), (18, 27), (20, 30), (25, 10)])
        if decoy:
            ans = 2 * a2
            pb = (f"Problem (one bus route): a bus leaves the depot every {a2} minutes, the first at 09:00. "
                  "How many minutes pass between its first and third departures?")
        else:
            ans = a2 * b2 // __import__("math").gcd(a2, b2)
            pb = (f"Problem (two buses): both leave the depot at 09:00. Bus X then leaves every {a2} minutes and bus Y every {b2} minutes. "
                  "After how many minutes do they next leave together?")
    prompt = f"{ex}\n\n{pb}\n\nSolve the problem, applying the idea from the worked example ONLY if the structure really is the same." + ANSWER_LINE
    return {"prompt": prompt, "input": {}, "ground_truth": {"answer": str(ans), "match": "numeric"}, "scoring_method": "answer_line",
            "difficulty": "hard" if decoy else "medium", "meta": {"chance": 0.0, "dedup_text": pb, "subtype": f"{kind}{'_decoy' if decoy else ''}"}}
