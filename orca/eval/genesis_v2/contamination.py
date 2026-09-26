"""V2 contamination controls (fail-closed). Every check returns one of PASS / FAIL / NOT_CONFIGURED / CONTAMINATION_DATASET_UNAVAILABLE /
INCOMPLETE; only PASS on EVERY mandatory check can support contamination_controls_pass. Reports carry item ids + scores, never content.

Thresholds (empirically grounded on the public V1 corpus, 3082 items; 300 sampled items compared against every item of a DIFFERENT category, i.e.
different templates by construction; sampling seed 1234, all constants public):
  NEAR_DUP_JACCARD      = 0.60  word-5-gram Jaccard.  Cross-category maximum observed 0.414; 0.60 leaves a 0.19 margin (no false positive on distinct
                                templates) while catching genuinely close rewrites. Same-template pairs are caught by the structural signal instead.
  STRUCT_CLONE_JACCARD  = 0.75  skeleton Jaccard.     Cross-category maximum observed 0.565 (short arithmetic/logic prompts); 0.75 leaves a 0.18 margin;
                                same-template V1 pairs have 10th percentile 0.784, i.e. ~90% of template clones sit at or above the line.
Structure is only assessed for prompts with >= 14 tokens; shorter items are reported as structurally UNASSESSABLE and need private manual/semantic
review before freeze (the semantic hook below is mandatory and currently NOT_CONFIGURED).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orca.eval.genesis_v2 import similarity as S

NEAR_DUP_JACCARD = 0.60
STRUCT_CLONE_JACCARD = 0.75
HIGH_ENTROPY_ANSWER_CHARS = 24

PASS, FAIL = "PASS", "FAIL"
NOT_CONFIGURED = "NOT_CONFIGURED"
DATASET_UNAVAILABLE = "CONTAMINATION_DATASET_UNAVAILABLE"
INCOMPLETE = "INCOMPLETE"

V1_FILES = ("dev.jsonl", "pilot_train.jsonl", "holdout.jsonl")
V1_DIR = "eval_private/genesis_capability_eval_v1"
STATUS_RECORD = "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json"


@dataclass
class CheckResult:
    name: str
    status: str
    findings: list
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "findings": self.findings, "note": self.note}


def overall(results: list) -> dict:
    """PASS only if every check is PASS. Unavailable / unconfigured / incomplete are never PASS."""
    return {"pass": bool(results) and all(r.status == PASS for r in results),
            "statuses": {r.name: r.status for r in results}, "failing": [r.name for r in results if r.status != PASS]}


def high_entropy_answer(rec: S.Rec) -> bool:
    return len(rec.gt_canon) >= HIGH_ENTROPY_ANSWER_CHARS and len(S.normalize(rec.gt_canon)) >= HIGH_ENTROPY_ANSWER_CHARS


# ------------------------------------------------------------------------------------------------------ reference (V1) corpus
def load_v1_reference(root: Path) -> tuple:
    """Returns (records, error). Verifies every V1 file against the hash pins in the V1 status record; any mismatch/absence => (None, reason)."""
    root = Path(root)
    try:
        pins = json.loads((root / STATUS_RECORD).read_text())["exposed_files_sha256"]
        rows = []
        for f in V1_FILES:
            rel = f"{V1_DIR}/{f}"
            blob = (root / rel).read_bytes()
            if hashlib.sha256(blob).hexdigest() != pins.get(rel):
                return None, f"{rel} does not match its pinned hash"
            rows += [json.loads(l) for l in blob.decode().splitlines() if l.strip()]
        return [S.make_rec(r) for r in rows], ""
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:100]}"


def check_v1_contamination(v2_items: list, v1_recs: list | None, *, unavailable_reason: str = "") -> list:
    """Exact / normalized / commitment / answer / reference / instance / near-duplicate / structural checks of V2 items against V1."""
    if not v1_recs:
        return [CheckResult("v1_reference", DATASET_UNAVAILABLE, [], unavailable_reason or "V1 reference corpus not supplied")]
    v2 = [S.make_rec(i) for i in v2_items]
    v1_id = {r.item_id for r in v1_recs}
    v1_norm = {}
    v1_content = {}
    for r in v1_recs:
        v1_norm.setdefault(r.text_norm, []).append(r.item_id)
        v1_content.setdefault(r.content_fp, []).append(r.item_id)
    v1_gt = {}
    v1_leaf = {}
    v1_inst = {}
    for r in v1_recs:
        if r.gt_canon:
            v1_gt.setdefault(r.gt_canon, []).append(r)
        for lf in r.gt_leaves:
            v1_leaf.setdefault(lf, []).append(r.item_id)
        for part in r.instance:
            v1_inst.setdefault(part, []).append(r.item_id)
    exact, answer, reference, instance = [], [], [], []
    for r in v2:
        if r.item_id in v1_id:
            exact.append({"v2": r.item_id, "kind": "ITEM_ID"})
        if r.text_norm and r.text_norm in v1_norm:
            exact.append({"v2": r.item_id, "v1": v1_norm[r.text_norm][0], "kind": "PROMPT_NORMALIZED"})
        if r.content_fp in v1_content:
            exact.append({"v2": r.item_id, "v1": v1_content[r.content_fp][0], "kind": "CONTENT"})
        hit = next((p for p in r.instance if p in v1_inst), None)
        if hit is not None:
            instance.append({"v2": r.item_id, "v1": v1_inst[hit][0], "kind": "INSTANCE_MATERIAL"})
        for lf in r.gt_leaves:
            if lf in v1_leaf:
                reference.append({"v2": r.item_id, "v1": v1_leaf[lf][0], "kind": "REFERENCE_LEAF"})
                break
        if r.gt_canon and r.gt_canon in v1_gt:
            same = v1_gt[r.gt_canon]
            if high_entropy_answer(r):
                answer.append({"v2": r.item_id, "v1": same[0].item_id, "kind": "ANSWER_EXACT_HIGH_ENTROPY"})
            elif any(S.struct_sim(r, o) >= STRUCT_CLONE_JACCARD or S.surface_sim(r, o) >= NEAR_DUP_JACCARD for o in same):
                answer.append({"v2": r.item_id, "v1": same[0].item_id, "kind": "ANSWER_EXACT_WITH_SIMILAR_PROMPT"})
    near = [{"v2": a, "v1": b, "score": s, "kind": "NEAR_DUPLICATE"} for a, b, s in S.similar_pairs(v2, v1_recs, "text", NEAR_DUP_JACCARD)]
    struct = [{"v2": a, "v1": b, "score": s, "kind": "STRUCTURAL_CLONE"} for a, b, s in S.similar_pairs(v2, v1_recs, "struct", STRUCT_CLONE_JACCARD)]
    unassessable = sorted(r.item_id for r in v2 if not r.struct_ok)
    res = [
        CheckResult("v1_exact_reuse", FAIL if exact else PASS, exact),
        CheckResult("v1_instance_seed_reuse", FAIL if instance else PASS, instance),
        CheckResult("v1_answer_reuse", FAIL if answer else PASS, answer),
        CheckResult("v1_reference_solution_reuse", FAIL if reference else PASS, reference),
        CheckResult("v1_near_duplicate", FAIL if near else PASS, near, f"word-5-gram Jaccard >= {NEAR_DUP_JACCARD}"),
        CheckResult("v1_structural_clone", FAIL if struct else PASS, struct, f"skeleton Jaccard >= {STRUCT_CLONE_JACCARD}"),
    ]
    res.append(CheckResult("v1_structure_assessability", PASS if not unassessable else INCOMPLETE,
                           [{"v2": u} for u in unassessable],
                           "prompts under 14 tokens cannot be structurally fingerprinted; private manual/semantic review required before freeze"))
    return res


# ------------------------------------------------------------------------------------------------------ training / adaptation corpora
class TrainingCorpusSource(Protocol):
    name: str

    def available(self) -> bool: ...
    def records(self) -> list: ...


class FileTrainingCorpus:
    """A public/private training or adaptation corpus stored as JSONL. Each record is turned into a text via `text_key` (default 'text')."""
    def __init__(self, name: str, path: Path, text_key: str = "text"):
        self.name, self._path, self._key = name, Path(path), text_key

    def available(self) -> bool:
        return self._path.is_file()

    def records(self) -> list:
        out = []
        for i, l in enumerate(self._path.read_text().splitlines()):
            if l.strip():
                d = json.loads(l)
                out.append(S.make_rec({"item_id": f"{self.name}#{i}", "category": "training", "prompt": d.get(self._key, "") if isinstance(d, dict) else str(d)}))
        return out


def check_training_corpora(v2_items: list, sources: dict, *, required: tuple, declared_complete: bool) -> list:
    """`required` names every Genesis training/adaptation corpus that exists before qualification. Missing/unavailable => CONTAMINATION_DATASET_UNAVAILABLE.
    `declared_complete` is an explicit owner attestation that `required` lists ALL such corpora; without it the check is INCOMPLETE, never PASS."""
    if not declared_complete:
        return [CheckResult("training_corpora", INCOMPLETE, [], "the set of training/adaptation corpora was not declared complete")]
    missing = [n for n in required if n not in sources or sources[n] is None or not sources[n].available()]
    if missing:
        return [CheckResult("training_corpora", DATASET_UNAVAILABLE, [{"corpus": n} for n in missing], "required corpora not available for comparison")]
    v2 = [S.make_rec(i) for i in v2_items]
    findings = []
    for n in required:
        recs = sources[n].records()
        norm = {r.text_norm for r in recs if r.text_norm}
        findings += [{"v2": r.item_id, "corpus": n, "kind": "EXACT"} for r in v2 if r.text_norm in norm]
        findings += [{"v2": a, "corpus": n, "score": s, "kind": "NEAR_DUPLICATE"} for a, _, s in S.similar_pairs(v2, recs, "text", NEAR_DUP_JACCARD)]
        findings += [{"v2": a, "corpus": n, "score": s, "kind": "STRUCTURAL_CLONE"} for a, _, s in S.similar_pairs(v2, recs, "struct", STRUCT_CLONE_JACCARD)]
    return [CheckResult("training_corpora", FAIL if findings else PASS, findings, f"compared against {list(required)}")]


# ------------------------------------------------------------------------------------------------------ semantic overlap hook
class SemanticOverlapChecker(Protocol):
    configured: bool
    local_private: bool

    def check(self, v2_items: list, references: list) -> CheckResult: ...


class NotConfiguredSemanticChecker:
    """No local/private embedding mechanism is authorized: semantic review is NOT performed and can never be reported as passed."""
    configured = False
    local_private = True

    def check(self, v2_items: list, references: list) -> CheckResult:
        return CheckResult("semantic_overlap", NOT_CONFIGURED, [], "no authorized local/private semantic-overlap mechanism; semantic review not performed")


def check_semantic(checker: SemanticOverlapChecker, v2_items: list, references: list) -> CheckResult:
    if not getattr(checker, "configured", False) or not getattr(checker, "local_private", False):
        return CheckResult("semantic_overlap", NOT_CONFIGURED, [], "checker is not a configured local/private mechanism; semantic review not performed")
    r = checker.check(v2_items, references)
    if r.status == PASS and (not getattr(checker, "configured", False)):
        return CheckResult("semantic_overlap", NOT_CONFIGURED, [], "refusing PASS from an unconfigured checker")
    return r


MANDATORY_CHECKS = ("v1_exact_reuse", "v1_instance_seed_reuse", "v1_answer_reuse", "v1_reference_solution_reuse", "v1_near_duplicate",
                    "v1_structural_clone", "v1_structure_assessability", "training_corpora", "semantic_overlap")


def contamination_controls_pass(results: list) -> bool:
    """True only if EVERY mandatory check is present and PASS (semantic review is mandatory; absence/NOT_CONFIGURED blocks)."""
    by = {r.name: r.status for r in results}
    return all(by.get(n) == PASS for n in MANDATORY_CHECKS)
