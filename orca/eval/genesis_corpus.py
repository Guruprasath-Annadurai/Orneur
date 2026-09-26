"""Genesis Capability Eval V1: build the private corpus, manifests and hashes (deterministic, CPU-only)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from orca.eval import genesis_eval_v1 as E
from orca.eval.genesis import gen_format, gen_misc, gen_orneur, gen_reasoning
from orca.eval.genesis.common import AUTHORING_SOURCE, rng_for

CORPUS_DIR = "eval_private/genesis_capability_eval_v1"
SPLIT_FILES = {"DEV": "dev.jsonl", "PILOT_TRAIN": "pilot_train.jsonl", "HOLDOUT": "holdout.jsonl"}
PROTOCOL_FILE = "protocol.jsonl"
IMAGES_DIR = "images"
FINGERPRINT_FILE = "holdout_fingerprints.json"
_SPLIT_TAG = {"DEV": "d", "PILOT_TRAIN": "p", "HOLDOUT": "h"}


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def item_sha256(item: Mapping[str, Any]) -> str:
    return sha256_text(canonical({k: v for k, v in item.items() if k != "sha256"}))


TEXT_DEDUP_CATEGORIES = frozenset({"structured_outputs", "research", "evidence_use", "discovery_quality", "verification"})

SIMPLE: dict[str, Callable] = {
    "instruction_following": gen_format.gen_instruction_following, "strict_contracts": gen_format.gen_strict_contracts,
    "structured_outputs": gen_format.gen_structured_outputs, "tool_use": gen_format.gen_tool_use,
    "reasoning": gen_reasoning.gen_reasoning, "mathematics": gen_reasoning.gen_mathematics, "verification": gen_reasoning.gen_verification,
    "information_gain_reasoning": gen_reasoning.gen_information_gain_reasoning, "research": gen_orneur.gen_research,
    "evidence_use": gen_orneur.gen_evidence_use, "counterfactual_reasoning": gen_orneur.gen_counterfactual_reasoning,
    "hypothesis_testing": gen_orneur.gen_hypothesis_testing, "discovery_quality": gen_orneur.gen_discovery_quality,
    "cross_domain_transfer": gen_orneur.gen_cross_domain_transfer, "multimodal_where_applicable": gen_misc.gen_multimodal, "coding": gen_misc.gen_coding,
}
LC_SLICES = (("8k", 8192), ("16k", 16384), ("40k", 40960))


def _count(cat: str, split: str) -> int:
    spec = E.CATEGORY_SPECS[cat]
    return {"HOLDOUT": spec["holdout"], "DEV": spec["dev"], "PILOT_TRAIN": spec.get("pilot", 0)}[split]


def _lc_plan(split: str) -> list[str]:
    spec = E.CATEGORY_SPECS["long_context"]
    if split == "HOLDOUT":
        return [s for s, n in spec["slices"].items() for _ in range(n)]
    if split == "DEV":
        return ["8k"] * spec["dev"]
    return []


def _finalize(cat: str, split: str, idx: int, salt: int, partial: dict, gen_name: str) -> dict:
    partial["meta"] = {**partial["meta"], "dedup_kind": "text" if cat in TEXT_DEDUP_CATEGORIES else "parametric"}
    item = {"item_id": f"gce1-{cat}-{_SPLIT_TAG[split]}{idx:04d}", "category": cat, "version": E.CORPUS_VERSION, "split": split,
            "private_holdout": split == "HOLDOUT", "authoring_source": AUTHORING_SOURCE,
            "creation_method": f"seeded_procedural_generator:{gen_name}@1 (category={cat}, split={split}, index={idx}, salt={salt})",
            "prompt": partial["prompt"], "system": None, "input": partial["input"], "ground_truth": partial["ground_truth"],
            "scoring_method": partial["scoring_method"], "difficulty": partial["difficulty"], "meta": partial["meta"]}
    item["sha256"] = item_sha256(item)
    return item


def build_all_items() -> tuple[list[dict], dict[str, bytes]]:
    """Every corpus item across splits, deduplicated on instance text within each category, plus rendered image bytes by relative path."""
    items: list[dict] = []
    images: dict[str, bytes] = {}
    seen: dict[str, set[str]] = {}
    for cat in E.CATEGORIES:
        seen.setdefault(cat, set())
        for split in E.SPLITS:
            n = _count(cat, split)
            plan = _lc_plan(split) if cat == "long_context" else None
            if cat == "long_context":
                n = len(plan)
            for idx in range(n):
                for salt in range(200):
                    rng = rng_for(cat, split, idx, str(salt) if salt else "")
                    if cat == "long_context":
                        sl = plan[idx]
                        part = gen_misc.gen_long_context(rng, dict(LC_SLICES)[sl])
                        gname = "long_context_v1"
                    elif cat == "multilingual":
                        part = gen_misc.gen_multilingual(rng, E.LANGUAGES[idx % len(E.LANGUAGES)])
                        gname = "multilingual_v1"
                    else:
                        fn = SIMPLE[cat]
                        part = fn(rng)
                        gname = fn.__name__
                    key = part["meta"]["dedup_text"]
                    if key in seen[cat]:
                        continue
                    seen[cat].add(key)
                    break
                else:  # pragma: no cover
                    raise RuntimeError(f"could not generate a unique {cat}/{split}/{idx}")
                if cat == "multimodal_where_applicable":
                    png = gen_misc.render_image(part["input"]["image_spec"])
                    item_id = f"gce1-{cat}-{_SPLIT_TAG[split]}{idx:04d}"
                    rel = f"{IMAGES_DIR}/{item_id}.png"
                    images[rel] = png
                    part["input"] = {**part["input"], "images": [rel], "image_sha256": hashlib.sha256(png).hexdigest()}
                items.append(_finalize(cat, split, idx, salt, part, gname))
    return items, images


def protocol_items() -> list[dict]:
    out = []
    for p in gen_misc.latency_probe_definitions():
        it = {"item_id": f"gce1-latency-{p['probe_id']}", "category": "latency", "version": E.CORPUS_VERSION, "split": "PROTOCOL", "private_holdout": False,
              "authoring_source": AUTHORING_SOURCE, "creation_method": "seeded_procedural_protocol_definition", "prompt": p["prompt"], "system": None,
              "input": {"input_words": p["input_words"], "max_new_tokens": p["max_new_tokens"], "repeat": p["repeat"], "measures": p["measures"]},
              "ground_truth": {}, "scoring_method": "measurement", "difficulty": "n/a", "meta": {"dedup_text": p["probe_id"], "chance": None, "subtype": "latency"}}
        it["sha256"] = item_sha256(it)
        out.append(it)
    return out


def item_prompt(item: Mapping[str, Any]) -> str:
    """The exact prompt a candidate sees; long-context prompts are re-materialised and verified against the stored hash."""
    if item.get("prompt") is not None:
        return item["prompt"]
    spec = item["input"]["generator_spec"]
    prompt, _ = gen_misc.materialize_long_context(spec)
    if hashlib.sha256(prompt.encode()).hexdigest() != item["input"]["materialized_prompt_sha256"]:
        raise ValueError(f"long-context materialisation drifted for {item['item_id']}")
    return prompt


def item_tail(item: Mapping[str, Any]) -> str:
    return item_prompt(item)[-600:]


def write_corpus(root: Path) -> dict[str, Any]:
    items, images = build_all_items()
    proto = protocol_items()
    base = root / CORPUS_DIR
    (base / IMAGES_DIR).mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for split, fname in SPLIT_FILES.items():
        rows = [it for it in items if it["split"] == split]
        counts[split] = len(rows)
        (base / fname).write_text("".join(canonical(r) + "\n" for r in rows), encoding="utf-8")
    (base / PROTOCOL_FILE).write_text("".join(canonical(r) + "\n" for r in proto), encoding="utf-8")
    for rel, data in images.items():
        (base / rel).write_bytes(data)
    from orca.eval import genesis_contamination as C
    fps = {}
    for it in items:
        if it["split"] == "HOLDOUT":
            probe = dict(it)
            if probe["prompt"] is None:
                probe["prompt"] = item_tail(it)
            fps[it["item_id"]] = C.item_fingerprint(probe)
    (base / FINGERPRINT_FILE).write_text(canonical(fps), encoding="utf-8")
    return {"counts": counts, "images": len(images), "protocol_items": len(proto)}


def load_split(root: Path, split: str) -> list[dict]:
    path = root / CORPUS_DIR / SPLIT_FILES[split]
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_protocol(root: Path) -> list[dict]:
    return [json.loads(l) for l in (root / CORPUS_DIR / PROTOCOL_FILE).read_text(encoding="utf-8").splitlines() if l.strip()]


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def images_aggregate_sha(base: Path) -> str:
    img = sorted((base / IMAGES_DIR).glob("*.png"))
    return sha256_text(canonical([(p.name, file_sha256(p)) for p in img]))


def slice_of(item: Mapping[str, Any]) -> str | None:
    return (item.get("meta") or {}).get("slice")
