"""Contamination control for the Genesis Capability Eval V1 corpus (CPU-only, deterministic).

Provides exact-duplicate, near-duplicate, n-gram-overlap and split-boundary checks, a semantic-overlap hook (protocol only), and a
training-corpus screen that runs a candidate training corpus against the private holdout fingerprints without exposing holdout text.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

NEAR_DUP_CHAR_NGRAM = 5
NEAR_DUP_THRESHOLD = 0.90
TRAIN_NGRAM = 8
TRAIN_OVERLAP_THRESHOLD = 0.20   # fraction of an item's n-grams found in a training record that flags contamination
_TOKEN = re.compile(r"\w+", re.U)


def normalize_text(s: str) -> str:
    """NFC, casefold, collapse whitespace. Punctuation and symbols are KEPT: they carry meaning in code, brackets and arithmetic items."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s).casefold()).strip()


def prompt_of(item: Mapping[str, Any]) -> str:
    """The text a model sees. Long-context items are materialised prompts, represented by their generator spec + question for fingerprints."""
    if item.get("prompt") is not None:
        return item["prompt"]
    spec = item["input"]["generator_spec"]
    return f"long_context {spec['task']} seed {spec['seed']} target {spec['target_tokens']} sha {item['input']['materialized_prompt_sha256']}"


def exact_key(item: Mapping[str, Any]) -> str:
    """Identity of what the model is shown: the normalised prompt plus the structured input (images, tool specs, generator spec)."""
    inp = json.dumps(item.get("input", {}), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((normalize_text(prompt_of(item)) + "\x1f" + inp).encode()).hexdigest()


def find_exact_duplicates(items: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    dups = []
    for it in items:
        k = exact_key(it)
        if k in seen:
            dups.append((seen[k], it["item_id"]))
        else:
            seen[k] = it["item_id"]
    return dups


def _shingles(text: str, n: int) -> set[str]:
    t = normalize_text(text)
    if len(t) <= n:
        return {t}
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def find_near_duplicates(items: Sequence[Mapping[str, Any]], threshold: float = NEAR_DUP_THRESHOLD) -> list[tuple[str, str, float]]:
    """Near-duplicates (character 5-gram Jaccard) on the instance text of items whose meta.dedup_kind == "text", within each category and across
    every split. PARAMETRIC items (a template plus a few numbers) are inherently similar to each other in text; for those, exact uniqueness of the
    parameter tuple is enforced instead and the template clustering is reported in the manifest (see genesis_manifest)."""
    by_cat: dict[str, list[tuple[str, set]]] = {}
    for it in items:
        if (it.get("meta") or {}).get("dedup_kind") != "text":
            continue
        txt = (it.get("meta") or {}).get("dedup_text") or prompt_of(it)
        by_cat.setdefault(it["category"], []).append((it["item_id"], _shingles(txt, NEAR_DUP_CHAR_NGRAM)))
    out = []
    for cat, lst in by_cat.items():
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                a, b = lst[i][1], lst[j][1]
                if abs(len(a) - len(b)) > max(len(a), len(b)) * (1 - threshold):
                    continue
                s = jaccard(a, b)
                if s >= threshold:
                    out.append((lst[i][0], lst[j][0], round(s, 4)))
    return out


def word_ngrams(text: str, n: int = TRAIN_NGRAM) -> set[int]:
    toks = _TOKEN.findall(unicodedata.normalize("NFC", text).casefold())
    if len(toks) < n:
        return {int(hashlib.sha256(" ".join(toks).encode()).hexdigest()[:8], 16)} if toks else set()
    return {int(hashlib.sha256(" ".join(toks[i:i + n]).encode()).hexdigest()[:8], 16) for i in range(len(toks) - n + 1)}


def ngram_overlap(item_text: str, corpus_ngrams: set[int], n: int = TRAIN_NGRAM) -> float:
    g = word_ngrams(item_text, n)
    return len(g & corpus_ngrams) / len(g) if g else 0.0


def item_fingerprint(item: Mapping[str, Any]) -> list[int]:
    """8-gram fingerprint of what the model sees plus the answer text, for screening WITHOUT exposing holdout text."""
    txt = prompt_of(item) if item.get("prompt") is not None else prompt_of(item)
    if item.get("prompt") is None:
        txt = item["input"].get("question_tail", txt)
    gt = item.get("ground_truth", {})
    ans = " ".join(str(gt.get(k, "")) for k in ("answer", "expected_output")) if isinstance(gt, dict) else ""
    return sorted(word_ngrams(txt) | word_ngrams(ans))


def check_split_boundaries(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Violations: duplicate ids/hashes, cross-split exact or near duplicates, a HOLDOUT item not flagged private, a non-holdout flagged private."""
    v: list[str] = []
    ids, shas = set(), set()
    for it in items:
        if it["item_id"] in ids:
            v.append(f"duplicate item_id {it['item_id']}")
        ids.add(it["item_id"])
        if it["sha256"] in shas:
            v.append(f"duplicate sha256 for {it['item_id']}")
        shas.add(it["sha256"])
        if it["split"] == "HOLDOUT" and it["private_holdout"] is not True:
            v.append(f"holdout item {it['item_id']} not flagged private")
        if it["split"] != "HOLDOUT" and it["private_holdout"] is not False:
            v.append(f"non-holdout item {it['item_id']} flagged private")
    seen_keys: dict[tuple[str, str], str] = {}
    for it in items:
        k = (it["category"], (it.get("meta") or {}).get("dedup_text") or it["item_id"])
        if k in seen_keys:
            v.append(f"duplicate instance key {it['item_id']} == {seen_keys[k]}")
        seen_keys[k] = it["item_id"]
    split_of = {it["item_id"]: it["split"] for it in items}
    for a, b in find_exact_duplicates(items):
        v.append(f"exact duplicate {a} ({split_of[a]}) == {b} ({split_of[b]})")
    for a, b, s in find_near_duplicates(items):
        v.append(f"near duplicate {a} ({split_of[a]}) ~ {b} ({split_of[b]}) jaccard={s}")
    return {"ok": not v, "violations": v}


class SemanticOverlapHook(Protocol):
    """Protocol for an embedding-based overlap check (a later phase may supply one). Returns similarity in [0, 1]."""

    def similarity(self, a: str, b: str) -> float: ...


class NullSemanticHook:
    configured = False

    def similarity(self, a: str, b: str) -> float:  # pragma: no cover - never used as a real signal
        raise NotImplementedError


def run_semantic_check(hook: SemanticOverlapHook | None, holdout_texts: Sequence[str], train_texts: Sequence[str], threshold: float = 0.92) -> dict[str, Any]:
    if hook is None or getattr(hook, "configured", True) is False:
        return {"status": "HOOK_NOT_CONFIGURED", "flagged": [], "note": "semantic overlap is NOT checked; exact, near-duplicate and n-gram checks still apply"}
    flagged = [(i, j) for i, h in enumerate(holdout_texts) for j, t in enumerate(train_texts) if hook.similarity(h, t) >= threshold]
    return {"status": "CHECKED", "flagged": flagged, "threshold": threshold}


def screen_training_texts(texts: Iterable[str], holdout_fingerprints: Mapping[str, Sequence[int]], *, threshold: float = TRAIN_OVERLAP_THRESHOLD) -> list[dict]:
    """Flag any training text that overlaps a holdout item. ``holdout_fingerprints`` maps item_id -> 8-gram hashes (no holdout text needed)."""
    fp = {k: set(v) for k, v in holdout_fingerprints.items()}
    flagged = []
    for idx, t in enumerate(texts):
        g = word_ngrams(t)
        if not g:
            continue
        for item_id, s in fp.items():
            if not s:
                continue
            frac = len(g & s) / len(s)
            if frac >= threshold:
                flagged.append({"record_index": idx, "item_id": item_id, "overlap_fraction": round(frac, 3)})
    return flagged


def load_texts_from_jsonl(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out.append(rec["text"] if isinstance(rec, dict) and "text" in rec else json.dumps(rec, ensure_ascii=False))
    return out


def screen_repo_training_corpora(root: Path, holdout_fingerprints: Mapping[str, Sequence[int]]) -> dict[str, Any]:
    """Screen every existing ORNEUR training/eval corpus file under notebooks/data against the private holdout."""
    results: dict[str, Any] = {}
    for p in sorted((root / "notebooks/data").glob("*.jsonl")):
        texts = load_texts_from_jsonl(p)
        results[str(p.relative_to(root))] = {"records": len(texts), "flagged": screen_training_texts(texts, holdout_fingerprints)}
    return results
