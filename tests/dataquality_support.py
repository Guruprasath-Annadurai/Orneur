"""Synthetic, deterministic fixtures for the dataquality tests. No real or private corpus, no network, no randomness (hash-derived choices only)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orca.dataquality._common import canonical_json, load_jsonl, sha256_text

_STEMS = ("amber", "basalt", "cobalt", "dune", "ember", "fjord", "garnet", "harbor", "indigo", "juniper", "kelp", "lagoon", "meadow", "nectar", "obsidian",
          "prairie", "quartz", "ridge", "saffron", "tundra", "umber", "velvet", "willow", "xenon", "yarrow", "zephyr")
_SUFFIX = ("", "ine", "ish", "ward", "ling", "ory", "ette", "land")
VOCAB = tuple(a + b for a in _STEMS for b in _SUFFIX)   # 208 synthetic words


def words(i: int, n: int = 28) -> str:
    """Deterministic n-word synthetic sentence unique to i (no two i share more than chance overlap)."""
    out = []
    for k in range(n):
        d = hashlib.sha256(f"dq-fixture/{i}/{k}".encode()).digest()
        out.append(VOCAB[int.from_bytes(d[:4], "big") % len(VOCAB)])
    return " ".join(out)


_FUNC = ("the", "of", "and", "to", "in", "is", "with", "for", "on", "by", "that", "as")


def varied(i: int, n: int = 24) -> str:
    """Like words() but each position is a function word with probability ~1/2, so skeleton (template) shapes differ between records."""
    out = []
    for k in range(n):
        d = hashlib.sha256(f"dq-varied/{i}/{k}".encode()).digest()
        v = int.from_bytes(d[:4], "big")
        out.append(_FUNC[v % len(_FUNC)] if (v >> 20) & 1 else VOCAB[v % len(VOCAB)])
    return " ".join(out)


SYSTEM = "You are a synthetic fixture assistant. This system block is shared boilerplate and is identical in every record of the fixture."


def chatml(user: str, assistant: str, system: str = SYSTEM) -> dict:
    return {"text": f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{assistant}<|im_end|>"}


def llama3(user: str, assistant: str, system: str = SYSTEM) -> dict:
    return {"text": f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{user}"
                    f"<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n{assistant}<|eot_id|><|end_of_text|>"}


def distinct_records(n: int, offset: int = 0) -> list:
    return [chatml(varied(offset + i), words(offset + i + 10_000)) for i in range(n)]


def write_jsonl(path: Path, records: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    return path


def lines_of(tmp_path: Path, records: list, name: str = "d.jsonl"):
    return load_jsonl(write_jsonl(tmp_path / name, records))


def source_registry() -> dict:
    return {"schema_version": "orneur-source-registry/1", "licenses": ["CC0-1.0", "internal-synthetic-test"],
            "sources": [{"source_id": "src-human", "license_id": "CC0-1.0"}, {"source_id": "src-prog", "license_id": "internal-synthetic-test"}]}


def prov(kind: str = "human", **gen) -> dict:
    g = {"kind": kind, **gen}
    return {"source_id": "src-human" if kind == "human" else "src-prog", "license_id": "CC0-1.0" if kind == "human" else "internal-synthetic-test",
            "generator": g, "creation_code_sha": "a" * 40}


def with_prov(rec: dict, p: dict, *, digest: bool = True) -> dict:
    out = dict(rec)
    p = dict(p)
    if digest:
        p["digest"] = sha256_text(canonical_json(rec))
    out["provenance"] = p
    return out
