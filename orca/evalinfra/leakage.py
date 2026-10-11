"""Prompt/answer leakage checks for RESULT artifacts (result manifests, reports, logs).

A result artifact may carry opaque ids, arms, categories, scores and hashes -- never prompt or answer text. Three independent layers:
  1. structural : any key in orca.eval.genesis_v2.spec.FORBIDDEN_PUBLIC_KEYS (prompt, answer, ground_truth, seed, salt, ...) at any depth;
  2. canary     : any registered canary string (normalized substring) anywhere in a key or value;
  3. content    : any word-8-gram window of a private prompt, or any private answer leaf of >= 24 normalized characters, anywhere in a key or value.
Findings give the JSON path, the kind and a short hash -- NEVER the matched text.

HONEST LIMITATION: a short hidden answer ("42", "B") cannot be found by text search without unacceptable false positives. For those the protection is
layer 1 plus the result-row whitelist enforced by orca.evalinfra.results (free text is not an allowed field at all). This guard is defense in depth.
"""
from __future__ import annotations

import hashlib

from orca.eval.genesis_v2 import similarity as S
from orca.eval.genesis_v2 import spec as V2
from orca.evalinfra.errors import LeakageDetected, SchemaViolation

NGRAM = 8
MIN_ANSWER_CHARS = 24
MIN_CANARY_CHARS = 12
MAX_STRING_LEN = 512


def _h(s: str) -> str:
    return hashlib.blake2b(s.encode(), digest_size=8).hexdigest()


class LeakGuard:
    def __init__(self, items=(), canaries=(), *, ngram: int = NGRAM, min_answer_chars: int = MIN_ANSWER_CHARS):
        self._n = ngram
        self._windows: set = set()
        self._answers: dict = {}
        self._canaries: dict = {}
        for c in canaries:
            nc = S.normalize(c)
            if len(nc) < MIN_CANARY_CHARS:
                raise SchemaViolation("CANARY_TOO_SHORT", f"a canary needs >= {MIN_CANARY_CHARS} normalized chars")
            self._canaries[" " + nc + " "] = _h(nc)
        for it in items:
            for txt in S.string_leaves([it.get("system"), it.get("prompt"), it.get("input")]):
                toks = S.normalize(txt).split()
                for i in range(0, max(0, len(toks) - ngram + 1)):
                    self._windows.add(_h(" ".join(toks[i:i + ngram])))
            for leaf in S.string_leaves(it.get("ground_truth")):
                nl = S.normalize(leaf)
                if len(nl) >= min_answer_chars:
                    self._answers[" " + nl + " "] = _h(nl)

    @property
    def has_private_material(self) -> bool:
        return bool(self._windows or self._answers or self._canaries)

    def _scan_string(self, s: str, path: str, out: list) -> None:
        if len(s) > MAX_STRING_LEN:
            out.append({"path": path, "kind": "LONG_STRING", "length": len(s)})
        n = " " + S.normalize(s) + " "
        for c, h in self._canaries.items():
            if c in n:
                out.append({"path": path, "kind": "CANARY", "hash": h})
        for a, h in self._answers.items():
            if a in n:
                out.append({"path": path, "kind": "ANSWER_TEXT", "hash": h})
        toks = n.split()
        hit = next((i for i in range(0, max(0, len(toks) - self._n + 1)) if _h(" ".join(toks[i:i + self._n])) in self._windows), None)
        if hit is not None:
            out.append({"path": path, "kind": "PROMPT_TEXT", "hash": _h(" ".join(toks[hit:hit + self._n]))})

    def scan(self, artifact, _path: str = "", _out: list | None = None) -> list:
        out = [] if _out is None else _out
        if isinstance(artifact, str):
            self._scan_string(artifact, _path or "/", out)
        elif isinstance(artifact, dict):
            for k, v in artifact.items():
                kp = f"{_path}/{k}"
                if k in V2.FORBIDDEN_PUBLIC_KEYS:
                    out.append({"path": kp, "kind": "FORBIDDEN_KEY"})
                self._scan_string(str(k), kp + "#key", out)
                self.scan(v, kp, out)
        elif isinstance(artifact, (list, tuple)):
            for i, v in enumerate(artifact):
                self.scan(v, f"{_path}[{i}]", out)
        return out

    def assert_clean(self, artifact) -> None:
        f = self.scan(artifact)
        if f:
            raise LeakageDetected("LEAKAGE", f"{len(f)} finding(s): " + ",".join(sorted({x['kind'] for x in f})))
