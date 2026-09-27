"""Local, provider-free semantic-overlap engine. CPU only; no network, no telemetry, no auto-download; the embedding model and its hash are recorded.

`SemanticOverlapEngine` is the control flow (deterministic preprocessing, cosine similarity, per-category thresholds, IDs/scores-only artifact). The
embedder is injected. Two embedders are provided:
  * FeatureHashEmbedder — deterministic signed feature hashing of word uni/bigrams. It is LEXICAL, not semantic (semantic_capable=False), so it can
    triage and drive tests but is NEVER accepted as semantic review: the engine reports NOT_CONFIGURED with it.
  * load_local_embedder — loads a sentence-embedding model from an explicit LOCAL directory whose content hash matches a pre-registered value; never
    downloads (offline flags), never calls a provider; any deviation => NotConfiguredError => NOT_CONFIGURED.
Operationally the state is NOT_CONFIGURED: no model directory has been authorized or hashed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from pathlib import Path
from typing import Protocol

from orca.eval.genesis_v2 import contamination as C

PREPROCESSING_VERSION = "semantic-preprocessing/1"
DEFAULT_THRESHOLD = 0.85
AMBIGUITY_MARGIN = 0.10          # scores in [threshold - margin, threshold) are "ambiguous" and require manual review


class NotConfiguredError(RuntimeError):
    pass


def preprocess(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text)).lower()).strip()


class Embedder(Protocol):
    model_id: str
    model_sha256: str
    local_only: bool
    semantic_capable: bool

    def embed(self, texts: list) -> list: ...


class FeatureHashEmbedder:
    model_id = "feature-hash-v1"
    local_only = True
    semantic_capable = False       # lexical proxy: never accepted as semantic review
    DIM = 256

    def __init__(self):
        self.model_sha256 = hashlib.sha256(f"{self.model_id}|dim={self.DIM}|unigram+bigram|signed|blake2b-8".encode()).hexdigest()

    def embed(self, texts: list) -> list:
        out = []
        for t in texts:
            v = [0.0] * self.DIM
            toks = preprocess(t).split()
            for g in toks + [a + " " + b for a, b in zip(toks, toks[1:])]:
                h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
                v[h % self.DIM] += 1.0 if (h >> 63) & 1 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def _dir_sha256(model_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in model_dir.rglob("*") if x.is_file()):
        h.update(str(p.relative_to(model_dir)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


class _SentenceTransformerEmbedder:
    local_only, semantic_capable = True, True

    def __init__(self, model_dir: Path, sha: str):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer            # optional dependency, never installed by this repo
        self._m = SentenceTransformer(str(model_dir), device="cpu")
        self.model_id, self.model_sha256 = f"local:{model_dir.name}", sha

    def embed(self, texts: list) -> list:
        return [list(map(float, v)) for v in self._m.encode([preprocess(t) for t in texts], normalize_embeddings=True, show_progress_bar=False)]


class _TransformersMeanPoolEmbedder:
    """Loads a local sentence-embedding checkpoint via the already-installed `transformers`+`torch` stack (no sentence-transformers
    dependency required). Implements the standard mean-pooling + L2-normalize recipe (matches sentence-transformers' own encoding for
    models trained that way, e.g. all-MiniLM-L6-v2). `local_files_only=True` and the offline env vars are set BEFORE any HF call, so a
    missing/incomplete local directory raises instead of silently reaching the network."""
    local_only, semantic_capable = True, True

    def __init__(self, model_dir: Path, sha: str):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        from transformers import AutoModel, AutoTokenizer
        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        self._model = AutoModel.from_pretrained(str(model_dir), local_files_only=True)
        self._model.eval()
        self.model_id, self.model_sha256 = f"local:{model_dir.name}", sha

    def embed(self, texts: list) -> list:
        torch = self._torch
        enc = self._tok([preprocess(t) for t in texts], padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            out = self._model(**enc)
        mask = enc["attention_mask"].unsqueeze(-1).float()
        pooled = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        normed = pooled / pooled.norm(dim=1, keepdim=True).clamp(min=1e-9)
        return [list(map(float, v)) for v in normed]


def load_local_embedder(model_dir, expected_sha256: str) -> Embedder:
    """Explicit local directory + pre-registered content hash. Raises NotConfiguredError otherwise. Never downloads, never calls a provider.

    Tries sentence-transformers first (if the owner has it installed), then falls back to a manual mean-pooling encoder built on the
    transformers+torch stack this repo already depends on for other purposes. Either path is local-only and offline-forced."""
    if not model_dir or not expected_sha256:
        raise NotConfiguredError("no local embedding model directory / pre-registered hash supplied")
    d = Path(model_dir)
    if not d.is_dir():
        raise NotConfiguredError("local embedding model directory does not exist (no auto-download is performed)")
    if _dir_sha256(d) != expected_sha256:
        raise NotConfiguredError("local embedding model content does not match the pre-registered hash")
    try:
        return _SentenceTransformerEmbedder(d, expected_sha256)
    except ImportError:
        pass
    except Exception as e:
        raise NotConfiguredError(f"local embedding runtime unavailable: {type(e).__name__}") from None
    try:
        return _TransformersMeanPoolEmbedder(d, expected_sha256)
    except Exception as e:
        raise NotConfiguredError(f"local embedding runtime unavailable: {type(e).__name__}") from None


def _cos(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b))


class SemanticOverlapEngine:
    local_private = True

    def __init__(self, embedder: Embedder | None = None, thresholds: dict | None = None, default_threshold: float = DEFAULT_THRESHOLD):
        self.embedder = embedder
        self.default_threshold = default_threshold
        self.thresholds = dict(thresholds or {})
        for t in [default_threshold, *self.thresholds.values()]:
            if not (0.0 < t <= 1.0):
                raise ValueError("thresholds must be in (0, 1]")

    @property
    def configured(self) -> bool:
        e = self.embedder
        return bool(e is not None and getattr(e, "local_only", False) and getattr(e, "semantic_capable", False)
                    and isinstance(getattr(e, "model_sha256", None), str) and len(e.model_sha256) == 64)

    def threshold_for(self, category: str) -> float:
        return self.thresholds.get(category, self.default_threshold)

    def score_pairs(self, v2_items: list, references: list) -> list:
        """[(v2_id, ref_id, score, category)] for every pair at or above (threshold - margin). references: [{'item_id', 'text'}]."""
        if self.embedder is None:
            return []
        a = self.embedder.embed([self._text(i) for i in v2_items])
        b = self.embedder.embed([r["text"] for r in references])
        out = []
        for i, va in zip(v2_items, a):
            th = self.threshold_for(i.get("category", ""))
            for r, vb in zip(references, b):
                s = _cos(va, vb)
                if s >= th - AMBIGUITY_MARGIN:
                    out.append((i["item_id"], r["item_id"], round(s, 4), i.get("category", "")))
        return out

    @staticmethod
    def _text(item: dict) -> str:
        from orca.eval.genesis_v2 import similarity as S
        return "\n".join(S.string_leaves([item.get("system"), item.get("prompt"), item.get("input")]))

    def artifact(self, pairs: list) -> dict:
        """IDs and scores only — never prompts, answers or embeddings."""
        e = self.embedder
        body = {"mechanism": {"model_id": getattr(e, "model_id", None), "model_sha256": getattr(e, "model_sha256", None), "preprocessing_version": PREPROCESSING_VERSION,
                              "default_threshold": self.default_threshold, "per_category_thresholds": dict(sorted(self.thresholds.items())),
                              "ambiguity_margin": AMBIGUITY_MARGIN, "configured": self.configured},
                "pairs": [{"v2_id": a, "ref_id": b, "score": s, "category": c, "band": "OVERLAP" if s >= self.threshold_for(c) else "AMBIGUOUS"} for a, b, s, c in pairs]}
        body["artifact_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return body

    def check(self, v2_items: list, references: list) -> C.CheckResult:
        if not self.configured:
            why = "no embedder" if self.embedder is None else ("lexical proxy embedder is not accepted as semantic review" if not getattr(self.embedder, "semantic_capable", False)
                                                              else "embedder not local/hash-recorded")
            return C.CheckResult("semantic_overlap", C.NOT_CONFIGURED, [], f"{why}; semantic review not performed")
        pairs = self.score_pairs(v2_items, references)
        overlap = [p for p in pairs if p[2] >= self.threshold_for(p[3])]
        art = self.artifact(pairs)
        find = [{"v2": a, "ref": b, "score": s} for a, b, s, _ in overlap]
        if overlap:
            return C.CheckResult("semantic_overlap", C.FAIL, find, f"artifact {art['artifact_sha256']}")
        amb = [p for p in pairs if p[2] < self.threshold_for(p[3])]
        note = f"artifact {art['artifact_sha256']}; {len(amb)} ambiguous pairs require manual review"
        return C.CheckResult("semantic_overlap", C.PASS if not amb else C.INCOMPLETE, [{"v2": a, "ref": b, "score": s, "band": "AMBIGUOUS"} for a, b, s, _ in amb], note)
